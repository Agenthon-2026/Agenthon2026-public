"""C8 — the release evidence manifest. Strict parsing is normative.

## Executive summary (read this first)

One signed file with a `covers` block naming exact competition ids and artifact digests. **Every
boolean is a JSON boolean, and any string in a boolean position is a hard failure** — no
truthy/falsey strings. `strict_bool` is what makes that mechanical rather than aspirational.

Required beyond the draft, each row for a measured reason:

* `hub_source_sha`, `bundle_digests` per uploaded program/dataset zip, and a **distribution
  digest** — the built wheel's sha256 — for `qfbench2-common`, **never a version string.** A
  modified vendored fork imported from `PYTHONPATH` reported the version of an unrelated
  distribution, because `importlib.metadata` resolves the *distribution*, not the imported module.
  A version string is unfalsifiable by construction.
* `skipped_required_jobs` as an **integer asserted to be 0**, evaluated on **step** conclusions,
  not job conclusions: a green job can contain skipped steps, which is exactly the observed
  skipped-green defect. The field records which granularity was used and refuses `job`.
* Dataset-firewall attestation **per unit family**, not per repository: the exec family differs in
  anatomy from the analysis family, and a repository-level attestation hides that.
* `deployed_site`, `policy_documents`, and a `fact_matrix` where publication **fails when any row's
  `last_verified` predates its cited evidence**.
* An explicit `backend_security_review` row: the Django backend is outside the audited repository,
  so C8 blocks until its source has been reviewed.

## New in C8 1.1.0 — `phase_visibility`, and why a platform default became a contract field

Verified in the vendored upstream CodaBench source:

* `compute_worker.py:1758` — `self._put_dir(self.prediction_result, self.output_dir)`. The
  **ingestion program's output directory** is uploaded as the submission's `prediction_result`.
* `compute_worker.py:1371` — `bundles += [(self.prediction_result, "input/res")]`. It is
  downloaded back as `input/res` for the scoring step, which is how the frozen topology works.
* `src/apps/api/serializers/submissions.py:263` — `get_prediction_result` returns a **signed
  download URL** to the submitter unless `phase.hide_output` **or** `phase.hide_prediction_output`.
* `src/apps/competitions/models.py:311-312` — both of those are `BooleanField(default=False)`.

So under default phase settings a participant can download the entire ingestion output root. Under
the frozen topology that root contains `_control/` — the signed C2 run records, the Hub's unsigned
observations and the ingestion logs — and one directory per unit named by its roster handle. In a
sealed phase those directory names *are* the sealed roster, and the C2 records enumerate exactly
which controls were not established, which is an attack roadmap rather than an inconvenience.

There is no alternative placement. The scoring program receives `input/ref` and `input/res` and
nothing else, so organizer evidence the scorer must read has to travel inside the ingestion output
root. The fix is therefore not to move `_control/` but to make its exposure impossible **by gate
rather than by default**, which is what this block is: the observed value of each flag, recorded
per scored phase, in a signed manifest, checked before publication.

Two severities, because the two flags do different things:

* **Both false is a parse refusal.** That is the leak itself, and a document describing it is not
  evidence of a safe release; it is a description of an unsafe one. It does not parse.
* **`hide_prediction_output` false on a scored phase blocks publication** even when `hide_output`
  is true. `hide_output` also suppresses the logs, the leaderboard and `scoring_result`
  (serializer lines 253, 271, 277), so satisfying the gate that way costs participants everything
  they are supposed to receive — and the operator who notices will fix it by flipping `hide_output`
  back off, which reinstates the leak. The ruling is `hide_prediction_output = true`; the gate
  enforces the ruling, not merely the absence of the leak.

`hide_score_output` is deliberately **not** recorded. It gates `scoring_result`, which participants
are supposed to get; it plays no part in this leak, and a field recorded here would read as one
more knob to tighten.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ._time import parse_rfc3339
from .digest import parse_digest
from .errors import (
    ContractError,
    req,
    req_int,
    req_list,
    req_str,
    reject_unknown_keys,
    strict_bool,
)
from .plan import TRACKS
from .signing import SignatureEnvelope

__all__ = [
    "COMPETITION_IDS",
    "COMPETITION_ID_VALUES",
    "PUBLICATION_SIGN_OFF_ROLE",
    "SIGN_OFF_ROLES",
    "FactRow",
    "PhaseVisibility",
    "ReleaseEvidence",
]

SCHEMA_VERSION = "1.1.0"
_SHA_LEN = 40

#: The canonical CodaBench competition id per track, RATIFIED in C8 1.1.0.
#:
#: The operator repo pinned these locally so that a manifest naming something else would be a
#: refusal rather than a judgement call, and filed a contract request because the C8 golden fixture
#: used a `-final` suffix and the two could not both be right. They are now one string, defined
#: here, and the C8 parser refuses a `covers.competition_ids` entry outside the set — which is
#: what stops a manifest covering `agenthon2026-coding-final` from being read as evidence for
#: `agenthon2026-coding`. Phase is a property of a phase, not of a competition id.
COMPETITION_IDS: Mapping[str, str] = {track: f"agenthon2026-{track}" for track in TRACKS}
COMPETITION_ID_VALUES: tuple[str, ...] = tuple(sorted(COMPETITION_IDS.values()))

#: Closed set of sign-off roles, from the deferred-owner table in the frozen contract set.
SIGN_OFF_ROLES = (
    "project-owner",
    "security-owner",
    "operations-owner",
    "legal-owner",
    "product-owner",
)

#: **The role that authorises the unpublished -> published transition**, stated normatively here
#: rather than restated in the operator repo's publish gate.
#:
#: Publication is the one transition that must not be inferable from CI state: every other row in
#: this manifest is a machine-measured fact, and a release that goes out because all the machines
#: were green is a release nobody decided to make. A `project-owner` row inside the replay window
#: is that decision. The other roles may sign — a security owner attesting to the backend review is
#: exactly the right use — but only this one authorises publishing.
PUBLICATION_SIGN_OFF_ROLE = "project-owner"

_TOP_KEYS = (
    "schema_version",
    "covers",
    "hub_source_sha",
    "bundle_digests",
    "distribution_digest",
    "ci",
    "dataset_firewall",
    "phase_visibility",
    "deployed_site",
    "policy_documents",
    "fact_matrix",
    "backend_security_review",
    "sign_off",
    "signature",
)


@dataclass(frozen=True, slots=True)
class PhaseVisibility:
    """One scored-or-unscored phase, and the two platform flags that decide who can download it.

    `hide_prediction_output` and `hide_output` are `BooleanField(default=False)` on the platform's
    `Phase` model. A per-phase boolean that defaults to False is configuration, and configuration
    is what this contract set converts into gated invariants: the value is *observed* from the live
    phase, *recorded* here, and *signed*, so the gate is checking a measurement rather than trusting
    that somebody remembered to tick a box.
    """

    competition_id: str
    phase_index: int
    phase_name: str
    scored: bool
    hide_prediction_output: bool
    hide_output: bool

    @property
    def prediction_output_retrievable(self) -> bool:
        """True when a submitter can download the ingestion output root for this phase.

        The serializer's condition, verbatim: the URL is withheld only if
        `hide_output or hide_prediction_output`.
        """
        return not (self.hide_output or self.hide_prediction_output)

    @classmethod
    def from_mapping(cls, raw: Any, *, index: int) -> PhaseVisibility:
        path = f"c8.phase_visibility[{index}]"
        if not isinstance(raw, Mapping):
            raise ContractError(f"{path} must be an object")
        reject_unknown_keys(
            raw,
            (
                "competition_id",
                "phase_index",
                "phase_name",
                "scored",
                "hide_prediction_output",
                "hide_output",
            ),
            path=path,
        )
        competition_id = req_str(raw, "competition_id", path=path)
        if competition_id not in COMPETITION_ID_VALUES:
            raise ContractError(
                f"{path}.competition_id={competition_id!r} is not an Agenthon competition id "
                f"{list(COMPETITION_ID_VALUES)}"
            )
        row = cls(
            competition_id=competition_id,
            phase_index=req_int(raw, "phase_index", path=path, minimum=0),
            phase_name=req_str(raw, "phase_name", path=path),
            scored=strict_bool(req(raw, "scored", path=path), field=f"{path}.scored"),
            hide_prediction_output=strict_bool(
                req(raw, "hide_prediction_output", path=path),
                field=f"{path}.hide_prediction_output",
            ),
            hide_output=strict_bool(
                req(raw, "hide_output", path=path), field=f"{path}.hide_output"
            ),
        )
        if row.scored and row.prediction_output_retrievable:
            raise ContractError(
                f"{path}: scored phase {row.phase_name!r} of {row.competition_id!r} has "
                "hide_prediction_output=false AND hide_output=false, so the platform serves the "
                "submitter a signed download URL for the INGESTION OUTPUT ROOT "
                "(compute_worker.py:1758 uploads it as prediction_result; submissions "
                "serializer:263 releases it unless one of these flags is set). Under the frozen "
                "topology that root holds _control/ -- the signed C2 run records, the Hub's "
                "observations and the ingestion logs -- plus one directory per unit named by its "
                "roster handle, which in a sealed phase IS the sealed roster. A manifest "
                "describing that configuration is not evidence of a safe release; it is a "
                "description of an unsafe one, so it does not parse."
            )
        return row

    def to_mapping(self) -> dict[str, Any]:
        return {
            "competition_id": self.competition_id,
            "phase_index": self.phase_index,
            "phase_name": self.phase_name,
            "scored": self.scored,
            "hide_prediction_output": self.hide_prediction_output,
            "hide_output": self.hide_output,
        }


@dataclass(frozen=True, slots=True)
class FactRow:
    path: str
    digest: str
    max_evidence_age_days: int
    last_verified: str
    evidence_dated: str


@dataclass(frozen=True, slots=True)
class ReleaseEvidence:
    schema_version: str
    competition_ids: tuple[str, ...]
    artifact_digests: Mapping[str, str]
    hub_source_sha: str
    bundle_digests: Mapping[str, str]
    #: The built **wheel file's** sha256 for `qfbench2-common` — never a version string, and never
    #: the digest the running package reports about itself. `qfbench2_common.build_identity()`
    #: returns `source_tree_digest`, which covers the package *tree*; no code inside a wheel can
    #: compute its own wheel's digest, so the release job records this one from outside. The two
    #: were briefly one name in two contracts, which is how a C8 could be assembled from the wrong
    #: value and still look self-consistent.
    distribution_digest: str
    skipped_required_jobs: int
    skipped_evaluated_on: str
    dataset_firewall: Mapping[str, bool]
    phase_visibility: tuple[PhaseVisibility, ...]
    deployed_site: Mapping[str, str]
    policy_documents: tuple[Mapping[str, str], ...]
    fact_matrix: tuple[FactRow, ...]
    backend_security_review: Mapping[str, Any]
    sign_off: tuple[Mapping[str, str], ...]
    signature: SignatureEnvelope

    @classmethod
    def from_mapping(cls, raw: Any) -> ReleaseEvidence:
        if not isinstance(raw, Mapping):
            raise ContractError("a C8 manifest must be an object")
        reject_unknown_keys(raw, _TOP_KEYS, path="c8")
        version = req_str(raw, "schema_version", path="c8")
        if version.split(".")[0] != SCHEMA_VERSION.split(".")[0]:
            raise ContractError(f"unsupported C8 schema_version {version!r}")

        covers = req(raw, "covers", path="c8")
        if not isinstance(covers, Mapping):
            raise ContractError("c8.covers must be an object")
        reject_unknown_keys(covers, ("competition_ids", "artifact_digests"), path="c8.covers")
        competition_ids = req_list(covers, "competition_ids", path="c8.covers", min_items=1)
        for index, value in enumerate(competition_ids):
            if not isinstance(value, str) or not value:
                raise ContractError(f"c8.covers.competition_ids[{index}] must be a string")
            if value not in COMPETITION_ID_VALUES:
                raise ContractError(
                    f"c8.covers.competition_ids[{index}]={value!r} is not an Agenthon competition "
                    f"id. The grammar is ratified in C8 1.1.0 as {list(COMPETITION_ID_VALUES)} -- "
                    "one id per competition, with the phase carried by the phase and not spelled "
                    "into the id. A manifest naming a near-miss covers nothing."
                )
        if len(set(competition_ids)) != len(competition_ids):
            raise ContractError("c8.covers.competition_ids repeats an id")
        artifacts_raw = req(covers, "artifact_digests", path="c8.covers")
        if not isinstance(artifacts_raw, Mapping) or not artifacts_raw:
            raise ContractError("c8.covers.artifact_digests must be a non-empty object")
        artifact_digests = {
            name: parse_digest(artifacts_raw[name], field=f"c8.covers.artifact_digests.{name}")
            for name in sorted(artifacts_raw)
        }

        hub_sha = req_str(raw, "hub_source_sha", path="c8")
        if len(hub_sha) != _SHA_LEN or any(c not in "0123456789abcdef" for c in hub_sha):
            raise ContractError("c8.hub_source_sha must be a full 40-character lowercase git sha")

        bundles_raw = req(raw, "bundle_digests", path="c8")
        if not isinstance(bundles_raw, Mapping) or not bundles_raw:
            raise ContractError("c8.bundle_digests must be a non-empty object")
        bundle_digests = {
            name: parse_digest(bundles_raw[name], field=f"c8.bundle_digests.{name}")
            for name in sorted(bundles_raw)
        }

        ci = req(raw, "ci", path="c8")
        if not isinstance(ci, Mapping):
            raise ContractError("c8.ci must be an object")
        reject_unknown_keys(ci, ("skipped_required_jobs", "evaluated_on"), path="c8.ci")
        skipped = req_int(ci, "skipped_required_jobs", path="c8.ci", minimum=0)
        evaluated_on = req_str(ci, "evaluated_on", path="c8.ci")
        if evaluated_on != "step":
            raise ContractError(
                f"c8.ci.evaluated_on={evaluated_on!r}: 'no skipped required jobs' is evaluated on "
                "STEP conclusions. A green job can contain skipped steps, which is the observed "
                "skipped-green defect."
            )

        firewall_raw = req(raw, "dataset_firewall", path="c8")
        if not isinstance(firewall_raw, Mapping) or not firewall_raw:
            raise ContractError(
                "c8.dataset_firewall must attest per UNIT FAMILY; a repository-level attestation "
                "hides a family whose anatomy differs"
            )
        dataset_firewall = {
            family: strict_bool(firewall_raw[family], field=f"c8.dataset_firewall.{family}")
            for family in sorted(firewall_raw)
        }

        visibility_raw = req_list(raw, "phase_visibility", path="c8", min_items=1)
        phase_visibility = tuple(
            PhaseVisibility.from_mapping(entry, index=index)
            for index, entry in enumerate(visibility_raw)
        )
        seen_phases: set[tuple[str, int]] = set()
        for row in phase_visibility:
            if row.competition_id not in competition_ids:
                raise ContractError(
                    f"c8.phase_visibility records {row.competition_id!r}, which "
                    "c8.covers.competition_ids does not name. Evidence about a competition this "
                    "manifest does not cover is not evidence for this release."
                )
            key = (row.competition_id, row.phase_index)
            if key in seen_phases:
                raise ContractError(
                    f"c8.phase_visibility records {row.competition_id!r} phase "
                    f"{row.phase_index} twice; two observations of one phase cannot both be "
                    "the observation"
                )
            seen_phases.add(key)
        scored_competitions = {r.competition_id for r in phase_visibility if r.scored}
        unobserved = sorted(set(competition_ids) - scored_competitions)
        if unobserved:
            raise ContractError(
                f"c8.phase_visibility records no SCORED phase for {unobserved}, which c8.covers "
                "claims to cover. Frozen rule 0.1: an absent field is an error, never a satisfied "
                "constraint -- and omitting the row is the one way to get past a gate that only "
                "inspects the rows it is given."
            )

        site_raw = req(raw, "deployed_site", path="c8")
        if not isinstance(site_raw, Mapping):
            raise ContractError("c8.deployed_site must be an object")
        reject_unknown_keys(
            site_raw,
            ("host", "deployed_commit_sha", "deployed_at", "source_repository"),
            path="c8.deployed_site",
        )
        deployed_site = {
            "host": req_str(site_raw, "host", path="c8.deployed_site"),
            "deployed_commit_sha": req_str(
                site_raw, "deployed_commit_sha", path="c8.deployed_site"
            ),
            "deployed_at": req_str(site_raw, "deployed_at", path="c8.deployed_site"),
            "source_repository": req_str(site_raw, "source_repository", path="c8.deployed_site"),
        }
        parse_rfc3339(deployed_site["deployed_at"], field="c8.deployed_site.deployed_at")

        policies: list[Mapping[str, str]] = []
        for index, entry in enumerate(req_list(raw, "policy_documents", path="c8", min_items=1)):
            path = f"c8.policy_documents[{index}]"
            if not isinstance(entry, Mapping):
                raise ContractError(f"{path} must be an object")
            reject_unknown_keys(entry, ("name", "version"), path=path)
            policies.append(
                {
                    "name": req_str(entry, "name", path=path),
                    "version": req_str(entry, "version", path=path),
                }
            )

        facts: list[FactRow] = []
        for index, entry in enumerate(req_list(raw, "fact_matrix", path="c8", min_items=1)):
            path = f"c8.fact_matrix[{index}]"
            if not isinstance(entry, Mapping):
                raise ContractError(f"{path} must be an object")
            reject_unknown_keys(
                entry,
                ("path", "digest", "max_evidence_age_days", "last_verified", "evidence_dated"),
                path=path,
            )
            last_verified = req_str(entry, "last_verified", path=path)
            evidence_dated = req_str(entry, "evidence_dated", path=path)
            verified_at = parse_rfc3339(last_verified, field=f"{path}.last_verified")
            evidence_at = parse_rfc3339(evidence_dated, field=f"{path}.evidence_dated")
            if verified_at < evidence_at:
                raise ContractError(
                    f"{path}: last_verified ({last_verified}) predates the evidence it cites "
                    f"({evidence_dated}). Publication fails on a stale row."
                )
            max_age = req_int(entry, "max_evidence_age_days", path=path, minimum=1)
            if (verified_at - evidence_at).days > max_age:
                raise ContractError(
                    f"{path}: the cited evidence is older than max_evidence_age_days={max_age}"
                )
            facts.append(
                FactRow(
                    path=req_str(entry, "path", path=path),
                    digest=parse_digest(req(entry, "digest", path=path), field=f"{path}.digest"),
                    max_evidence_age_days=max_age,
                    last_verified=last_verified,
                    evidence_dated=evidence_dated,
                )
            )

        review_raw = req(raw, "backend_security_review", path="c8")
        if not isinstance(review_raw, Mapping):
            raise ContractError("c8.backend_security_review must be an object")
        reject_unknown_keys(
            review_raw,
            ("reviewed", "reviewer", "source_sha", "reviewed_at"),
            path="c8.backend_security_review",
        )
        review = {
            "reviewed": strict_bool(
                req(review_raw, "reviewed", path="c8.backend_security_review"),
                field="c8.backend_security_review.reviewed",
            ),
            "reviewer": req_str(review_raw, "reviewer", path="c8.backend_security_review"),
            "source_sha": req_str(review_raw, "source_sha", path="c8.backend_security_review"),
            "reviewed_at": req_str(review_raw, "reviewed_at", path="c8.backend_security_review"),
        }
        parse_rfc3339(review["reviewed_at"], field="c8.backend_security_review.reviewed_at")

        sign_off: list[Mapping[str, str]] = []
        for index, entry in enumerate(req_list(raw, "sign_off", path="c8", min_items=1)):
            path = f"c8.sign_off[{index}]"
            if not isinstance(entry, Mapping):
                raise ContractError(f"{path} must be an object")
            reject_unknown_keys(entry, ("owner_role", "owner_id", "signed_at"), path=path)
            parse_rfc3339(req(entry, "signed_at", path=path), field=f"{path}.signed_at")
            owner_role = req_str(entry, "owner_role", path=path)
            if owner_role not in SIGN_OFF_ROLES:
                raise ContractError(
                    f"{path}.owner_role={owner_role!r} is not a recognised sign-off role "
                    f"{list(SIGN_OFF_ROLES)}. Enums are closed (frozen rule 0.3): an unrecognised "
                    "role is an approval nobody can be held to, and the gate looks for exactly "
                    f"{PUBLICATION_SIGN_OFF_ROLE!r} to authorise publishing."
                )
            sign_off.append(
                {
                    "owner_role": owner_role,
                    "owner_id": req_str(entry, "owner_id", path=path),
                    "signed_at": req_str(entry, "signed_at", path=path),
                }
            )

        return cls(
            schema_version=version,
            competition_ids=tuple(competition_ids),
            artifact_digests=artifact_digests,
            hub_source_sha=hub_sha,
            bundle_digests=bundle_digests,
            distribution_digest=parse_digest(
                req(raw, "distribution_digest", path="c8"), field="c8.distribution_digest"
            ),
            skipped_required_jobs=skipped,
            skipped_evaluated_on=evaluated_on,
            dataset_firewall=dataset_firewall,
            phase_visibility=phase_visibility,
            deployed_site=deployed_site,
            policy_documents=tuple(policies),
            fact_matrix=tuple(facts),
            backend_security_review=review,
            sign_off=tuple(sign_off),
            signature=SignatureEnvelope.from_mapping(req(raw, "signature", path="c8")),
        )

    # ------------------------------------------------------------------ behaviour
    def blocking_reasons(self) -> tuple[str, ...]:
        """Everything that stops publication. Empty means `assert_publishable()` passes."""
        reasons: list[str] = []
        if self.skipped_required_jobs != 0:
            reasons.append(f"skipped_required_jobs={self.skipped_required_jobs}, asserted to be 0")
        unattested = sorted(f for f, ok in self.dataset_firewall.items() if not ok)
        if unattested:
            reasons.append(f"dataset firewall not attested for unit families {unattested}")
        if not self.backend_security_review["reviewed"]:
            reasons.append(
                "backend_security_review.reviewed is false; the Django backend is outside the "
                "audited repository and C8 blocks until its source has been reviewed"
            )
        for row in self.visible_scored_phases():
            reasons.append(
                f"{row.competition_id} phase {row.phase_index} ({row.phase_name!r}) is scored "
                "with hide_prediction_output=false. The RULING is that every scored phase sets "
                "it true: hide_output also suppresses the logs, the leaderboard and "
                "scoring_result, so relying on it to withhold the ingestion output root costs "
                "participants everything they are supposed to receive -- and the next operator "
                "fixes that by clearing hide_output, which reinstates the leak."
            )
        if not self.publication_authorised_by():
            reasons.append(
                f"no {PUBLICATION_SIGN_OFF_ROLE} sign-off. Publication is the one transition that "
                "must not be inferable from CI state: every other row here is a machine-measured "
                "fact, and a release that goes out because the machines were green is a release "
                "nobody decided to make."
            )
        return tuple(reasons)

    def visible_scored_phases(self) -> tuple[PhaseVisibility, ...]:
        """Scored phases that do not set `hide_prediction_output`. Empty is the required state.

        The *both-false* case never reaches here: it is refused at parse time, because that
        document describes a live leak. What this finds is the survivable-but-wrong case --
        `hide_output` covering for a `hide_prediction_output` nobody set.
        """
        return tuple(
            row for row in self.phase_visibility if row.scored and not row.hide_prediction_output
        )

    def publication_authorised_by(self) -> tuple[Mapping[str, str], ...]:
        """The sign-off rows that authorise unpublished -> published, in document order.

        Staleness is the caller's check, not this object's: the replay window is decision D7 and
        belongs to the security owner, so it arrives as a `max_age` at verification time rather
        than being baked in here at a number somebody guessed.
        """
        return tuple(row for row in self.sign_off if row["owner_role"] == PUBLICATION_SIGN_OFF_ROLE)

    def phase_visibility_for(self, competition_id: str) -> tuple[PhaseVisibility, ...]:
        """Every recorded phase of one competition. Raises if the manifest does not cover it."""
        if competition_id not in self.competition_ids:
            raise ContractError(
                f"this manifest does not cover {competition_id!r}; it covers "
                f"{list(self.competition_ids)}"
            )
        return tuple(r for r in self.phase_visibility if r.competition_id == competition_id)

    def assert_publishable(self) -> None:
        reasons = self.blocking_reasons()
        if reasons:
            raise ContractError("C8 blocks publication: " + "; ".join(reasons))

    def covers_artifact(self, name: str, digest: str) -> bool:
        """Bidirectional exactness is the caller's job; this answers one direction of it."""
        return self.artifact_digests.get(name) == digest
