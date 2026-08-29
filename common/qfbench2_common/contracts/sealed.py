"""C6 — the sealed dataset pointer, split into a public handle and a signed resolver descriptor.

## Executive summary (read this first)

C6 is **split in two**, and the split is the security property:

* **`SealedHandle`** ships in the bundle. It carries `schema_version`, track, phase, dataset
  version and an opaque pointer id — *nothing else*. A bundle never carries a digest or a roster
  count, so a participant reading the bundle learns nothing about the sealed set's size or content.
  The key set is exact, so a producer cannot "helpfully" attach a digest: an extra key is a parse
  error.
* **`ResolverDescriptor`** lives resolver-side, is signed, and holds digests, sizes, the roster
  commitment, resolver identity and the artifact roles.

**Role enum, three values, mutually exclusive:** `participant_input`, `scorer_reference`,
`verifier_asset`. **One object may not carry two roles.** Track 1 and Track 4 asked for this
independently; it is the schema-level statement of the firewall, and `role` is a single string
rather than a list precisely so "both" is unrepresentable.

Further frozen fields:

* `required: bool` per artifact, and a **null or empty digest is forbidden**.
* `answer_equivalent: bool` — set on any derived artifact that inverts to the answer. Track 2's
  `ref_scale.json` is the known instance: it is *derived*, looks innocuous, and inverts to the
  sealed target. Flagging it in the schema is what stops it being classified `participant_input`
  by someone who reads only the filename. This module refuses that combination outright.
* The Track 4 **corpus manifest is a first-class C6 artifact** mapping
  `doc_id -> {digest, trusted doc_date}`, so citation resolution is a dictionary lookup and never
  participant path interpolation.
* **Input and reference may never resolve from the same unresolved source** — enforced on the uri
  *and* the digest, because a redirect defeats a string comparison alone.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ._time import parse_rfc3339
from .digest import parse_digest
from .errors import (
    ContractError,
    req,
    req_bool,
    req_enum,
    req_int,
    req_list,
    req_str,
    reject_unknown_keys,
)
from .plan import PHASES, TRACKS
from .signing import SignatureEnvelope

__all__ = ["ArtifactRole", "CorpusEntry", "ResolverDescriptor", "SealedArtifact", "SealedHandle"]

SCHEMA_VERSION = "1.0.0"
_HANDLE_KEYS = ("schema_version", "track", "phase", "dataset_version", "pointer_id")


class ArtifactRole(StrEnum):
    """Three values, mutually exclusive. One object may not carry two roles."""

    PARTICIPANT_INPUT = "participant_input"
    SCORER_REFERENCE = "scorer_reference"
    VERIFIER_ASSET = "verifier_asset"


@dataclass(frozen=True, slots=True)
class SealedHandle:
    """The bundle-visible pointer. Five fields, exactly."""

    schema_version: str
    track: str
    phase: str
    dataset_version: str
    pointer_id: str

    @classmethod
    def from_mapping(cls, raw: Any) -> SealedHandle:
        if not isinstance(raw, Mapping):
            raise ContractError("a C6 public handle must be an object")
        # Exact, not merely closed: a handle carrying a digest, a count or a uri is refused, which
        # is what keeps the bundle free of sealed metadata by construction.
        extra = sorted(set(raw) - set(_HANDLE_KEYS))
        if extra:
            raise ContractError(
                f"a C6 public handle carries {extra}, which the bundle must never see. The handle "
                "is {schema_version, track, phase, dataset_version, pointer_id} and nothing else."
            )
        version = req_str(raw, "schema_version", path="sealed_handle")
        if version.split(".")[0] != SCHEMA_VERSION.split(".")[0]:
            raise ContractError(f"unsupported C6 schema_version {version!r}")
        return cls(
            schema_version=version,
            track=req_enum(raw, "track", TRACKS, path="sealed_handle"),
            phase=req_enum(raw, "phase", PHASES, path="sealed_handle"),
            dataset_version=req_str(raw, "dataset_version", path="sealed_handle"),
            pointer_id=req_str(raw, "pointer_id", path="sealed_handle"),
        )

    def to_mapping(self) -> dict[str, str]:
        return {
            "schema_version": self.schema_version,
            "track": self.track,
            "phase": self.phase,
            "dataset_version": self.dataset_version,
            "pointer_id": self.pointer_id,
        }


@dataclass(frozen=True, slots=True)
class SealedArtifact:
    artifact_id: str
    role: ArtifactRole
    uri: str
    tree_digest: str
    total_bytes: int
    object_count: int
    required: bool
    answer_equivalent: bool

    @classmethod
    def from_mapping(cls, raw: Any, *, path: str) -> SealedArtifact:
        if not isinstance(raw, Mapping):
            raise ContractError(f"{path} must be an object")
        reject_unknown_keys(
            raw,
            (
                "artifact_id",
                "role",
                "uri",
                "tree_digest",
                "total_bytes",
                "object_count",
                "required",
                "answer_equivalent",
            ),
            path=path,
        )
        role = ArtifactRole(req_enum(raw, "role", tuple(r.value for r in ArtifactRole), path=path))
        answer_equivalent = req_bool(raw, "answer_equivalent", path=path)
        if answer_equivalent and role is ArtifactRole.PARTICIPANT_INPUT:
            raise ContractError(
                f"{path} is flagged answer_equivalent and classified participant_input. Track 2's "
                "ref_scale.json is the known instance: derived, innocuous-looking, and it inverts "
                "to the sealed target. This combination is refused."
            )
        return cls(
            artifact_id=req_str(raw, "artifact_id", path=path),
            role=role,
            uri=req_str(raw, "uri", path=path),
            # A null or empty digest is forbidden (Track 3). parse_digest refuses both.
            tree_digest=parse_digest(
                req(raw, "tree_digest", path=path), field=f"{path}.tree_digest"
            ),
            total_bytes=req_int(raw, "total_bytes", path=path, minimum=0),
            object_count=req_int(raw, "object_count", path=path, minimum=1),
            required=req_bool(raw, "required", path=path),
            answer_equivalent=answer_equivalent,
        )


@dataclass(frozen=True, slots=True)
class CorpusEntry:
    """`doc_id -> {digest, doc_date}`. The trusted date; never the participant's citation field."""

    doc_id: str
    digest: str
    doc_date: str


_DESCRIPTOR_KEYS = (
    "schema_version",
    "pointer_id",
    "track",
    "phase",
    "dataset_version",
    "artifacts",
    "roster_commitment",
    "corpus_manifest",
    "resolver",
    "expires_at",
    "signature",
)


@dataclass(frozen=True, slots=True)
class ResolverDescriptor:
    """The resolver-side signed descriptor. Never ships in a bundle."""

    schema_version: str
    pointer_id: str
    track: str
    phase: str
    dataset_version: str
    artifacts: tuple[SealedArtifact, ...]
    roster_count: int
    roster_digest: str
    corpus_manifest: tuple[CorpusEntry, ...]
    resolver_identity: str
    allowed_destination_prefix: str
    expires_at: str
    signature: SignatureEnvelope

    @classmethod
    def from_mapping(cls, raw: Any) -> ResolverDescriptor:
        if not isinstance(raw, Mapping):
            raise ContractError("a C6 resolver descriptor must be an object")
        reject_unknown_keys(raw, _DESCRIPTOR_KEYS, path="resolver_descriptor")
        version = req_str(raw, "schema_version", path="resolver_descriptor")
        if version.split(".")[0] != SCHEMA_VERSION.split(".")[0]:
            raise ContractError(f"unsupported C6 schema_version {version!r}")

        artifacts = tuple(
            SealedArtifact.from_mapping(entry, path=f"artifacts[{i}]")
            for i, entry in enumerate(
                req_list(raw, "artifacts", path="resolver_descriptor", min_items=1)
            )
        )
        ids = [a.artifact_id for a in artifacts]
        if len(set(ids)) != len(ids):
            raise ContractError("artifacts repeats an artifact_id")
        inputs = [a for a in artifacts if a.role is ArtifactRole.PARTICIPANT_INPUT]
        references = [a for a in artifacts if a.role is ArtifactRole.SCORER_REFERENCE]
        if not inputs or not references:
            raise ContractError(
                "a resolver descriptor needs at least one participant_input and one "
                "scorer_reference artifact"
            )
        for participant_input in inputs:
            for reference in references:
                if participant_input.uri == reference.uri:
                    raise ContractError(
                        f"input {participant_input.artifact_id!r} and reference "
                        f"{reference.artifact_id!r} resolve from the same uri; input and reference "
                        "may never share an unresolved source"
                    )
                if participant_input.tree_digest == reference.tree_digest:
                    raise ContractError(
                        f"input {participant_input.artifact_id!r} and reference "
                        f"{reference.artifact_id!r} have the same tree_digest; a redirect defeats "
                        "a uri comparison alone, so the content is compared too"
                    )

        roster = req(raw, "roster_commitment", path="resolver_descriptor")
        if not isinstance(roster, Mapping):
            raise ContractError("roster_commitment must be an object")
        reject_unknown_keys(roster, ("count", "digest"), path="roster_commitment")

        corpus_raw = req(raw, "corpus_manifest", path="resolver_descriptor")
        if not isinstance(corpus_raw, Mapping):
            raise ContractError(
                "corpus_manifest must be an object of doc_id -> {digest, doc_date}; an array "
                "would make citation resolution a search instead of a lookup"
            )
        corpus: list[CorpusEntry] = []
        for doc_id in sorted(corpus_raw):
            path = f"corpus_manifest.{doc_id}"
            entry = corpus_raw[doc_id]
            if not isinstance(entry, Mapping):
                raise ContractError(f"{path} must be an object")
            reject_unknown_keys(entry, ("digest", "doc_date"), path=path)
            corpus.append(
                CorpusEntry(
                    doc_id=doc_id,
                    digest=parse_digest(req(entry, "digest", path=path), field=f"{path}.digest"),
                    doc_date=req_str(entry, "doc_date", path=path),
                )
            )
            parse_rfc3339(entry["doc_date"], field=f"{path}.doc_date")

        resolver = req(raw, "resolver", path="resolver_descriptor")
        if not isinstance(resolver, Mapping):
            raise ContractError("resolver must be an object")
        reject_unknown_keys(resolver, ("identity", "allowed_destination_prefix"), path="resolver")

        expires_at = req_str(raw, "expires_at", path="resolver_descriptor")
        parse_rfc3339(expires_at, field="expires_at")

        return cls(
            schema_version=version,
            pointer_id=req_str(raw, "pointer_id", path="resolver_descriptor"),
            track=req_enum(raw, "track", TRACKS, path="resolver_descriptor"),
            phase=req_enum(raw, "phase", PHASES, path="resolver_descriptor"),
            dataset_version=req_str(raw, "dataset_version", path="resolver_descriptor"),
            artifacts=artifacts,
            roster_count=req_int(roster, "count", path="roster_commitment", minimum=1),
            roster_digest=parse_digest(
                req(roster, "digest", path="roster_commitment"), field="roster_commitment.digest"
            ),
            corpus_manifest=tuple(corpus),
            resolver_identity=req_str(resolver, "identity", path="resolver"),
            allowed_destination_prefix=req_str(
                resolver, "allowed_destination_prefix", path="resolver"
            ),
            expires_at=expires_at,
            signature=SignatureEnvelope.from_mapping(
                req(raw, "signature", path="resolver_descriptor")
            ),
        )

    def matches_handle(self, handle: SealedHandle) -> None:
        """A handle and its descriptor must agree on pointer, track, phase and dataset version."""
        problems = []
        if handle.pointer_id != self.pointer_id:
            problems.append("pointer_id")
        if handle.track != self.track:
            problems.append("track")
        if handle.phase != self.phase:
            problems.append("phase")
        if handle.dataset_version != self.dataset_version:
            problems.append("dataset_version")
        if problems:
            raise ContractError(f"handle and resolver descriptor disagree on {problems}")

    def matches_plan_roster(self, *, count: int, digest: str) -> None:
        """C1's roster digest and C6's resolved content must be provably the same set."""
        if (count, digest) != (self.roster_count, self.roster_digest):
            raise ContractError(
                f"C6 roster commitment ({self.roster_count}, {self.roster_digest}) does not equal "
                f"C1's ({count}, {digest})"
            )

    def doc_date(self, doc_id: str) -> str:
        """Trusted document date by lookup. A missing doc_id raises; it never falls back."""
        for entry in self.corpus_manifest:
            if entry.doc_id == doc_id:
                return entry.doc_date
        raise ContractError(
            f"{doc_id!r} is not in the corpus manifest. A citation to an unknown document is a "
            "participant failure, never a reason to trust a participant-supplied date."
        )
