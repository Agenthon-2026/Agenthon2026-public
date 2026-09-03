"""C5 — the canonical submission descriptor. One vocabulary, `additionalProperties: false`.

## Executive summary (read this first)

C5 was contradictory in **field name and value format at once**. The canonical schema required
`image_digest` matching `^sha256:[0-9a-f]{64}$` — a bare digest that is **not pullable** — while
participants were told to write `image` = `registry/repo@sha256:...`. Three validated fields
reassembled by the consumer removes both the name clash and the argv-injection surface of a free
string:

```jsonc
"image": {"registry": "...", "repository": "...", "digest": "sha256:<64hex>"}
```

`SubmissionDescriptor.image_reference()` is the one place the three are joined, and it applies the
guards the freeze names for any future string form: no leading `-`, no `=`, no whitespace, bounded
length. Consumers still place `--` before the image position in an argv.

Other frozen rulings:

* `category` is **required on every track** (R-1), with `simulator` for Track 3. "Absent means
  valid" is the exact fail-open shape this program exists to remove, and absent was not even
  neutral: `declared_category()` turned it into `"api"`, which a Track 3 queue would then refuse.
* `model_disclosure` and the top-level `models` array are **collapsed into one required structured
  array**. The overlapping pair is the source of the generated-example drift.
* `descriptor_digest` is self-referential and checked: it is the digest of the descriptor with that
  field removed.
* Hub publishes **one valid fixture per (track, phase)** — four tracks by three phases. CodaBench
  ships those verbatim and the website renders from the same bytes. Nobody hand-writes a third
  example.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .digest import digest_json, parse_digest
from .errors import ContractError, req, req_enum, req_list, req_str, reject_unknown_keys
from .plan import PHASES, TRACKS

__all__ = [
    "CATEGORIES",
    "IMAGE_ACCESS",
    "ModelDisclosure",
    "SubmissionDescriptor",
]

SCHEMA_VERSION = "1.1.0"
INTERFACE_VERSION = "2.0"
CATEGORIES = ("api", "byo-large", "byo-small", "simulator")
IMAGE_ACCESS = ("public", "organizer_mirror")
MODEL_ACCESS = ("api", "local")

_REGISTRY_RE = re.compile(r"^[a-z0-9]([a-z0-9._-]*[a-z0-9])?(:[0-9]{1,5})?$")
_REPOSITORY_RE = re.compile(r"^[a-z0-9]+([._-][a-z0-9]+)*(/[a-z0-9]+([._-][a-z0-9]+)*)*$")
_MAX_REFERENCE_LEN = 512
_SPDX_RE = re.compile(r"^[A-Za-z0-9.+-]{1,64}(\s(WITH|OR|AND)\s[A-Za-z0-9.+-]{1,64})*$")

_TOP_KEYS = (
    "schema_version",
    "interface_version",
    "competition_id",
    "team_id",
    "track",
    "phase",
    "category",
    "image",
    "image_access",
    "models",
    "license",
    "descriptor_digest",
)


@dataclass(frozen=True, slots=True)
class ModelDisclosure:
    """One row of the single required `models` array."""

    name: str
    version: str
    training_cutoff: str
    access: str
    revision: str

    @classmethod
    def from_mapping(cls, obj: Any, *, path: str) -> ModelDisclosure:
        if not isinstance(obj, Mapping):
            raise ContractError(f"{path} must be an object")
        reject_unknown_keys(
            obj, ("name", "version", "training_cutoff", "access", "revision"), path=path
        )
        return cls(
            name=req_str(obj, "name", path=path),
            version=req_str(obj, "version", path=path),
            training_cutoff=req_str(obj, "training_cutoff", path=path),
            access=req_enum(obj, "access", MODEL_ACCESS, path=path),
            revision=req_str(obj, "revision", path=path),
        )

    def to_mapping(self) -> dict[str, str]:
        return {
            "name": self.name,
            "version": self.version,
            "training_cutoff": self.training_cutoff,
            "access": self.access,
            "revision": self.revision,
        }


@dataclass(frozen=True, slots=True)
class SubmissionDescriptor:
    schema_version: str
    interface_version: str
    competition_id: str
    team_id: str
    track: str
    phase: str
    category: str
    registry: str
    repository: str
    image_digest: str
    image_access: str
    models: tuple[ModelDisclosure, ...]
    license: str
    descriptor_digest: str

    # ------------------------------------------------------------------ parsing
    @classmethod
    def from_mapping(cls, raw: Any) -> SubmissionDescriptor:
        if not isinstance(raw, Mapping):
            raise ContractError("a C5 descriptor must be an object")
        reject_unknown_keys(raw, _TOP_KEYS, path="descriptor")
        version = req_str(raw, "schema_version", path="descriptor")
        if version.split(".")[0] != SCHEMA_VERSION.split(".")[0]:
            raise ContractError(
                f"unsupported C5 schema_version {version!r}; this build implements {SCHEMA_VERSION}"
            )
        interface_version = req_str(raw, "interface_version", path="descriptor")
        if interface_version != INTERFACE_VERSION:
            raise ContractError(f"interface_version {interface_version!r} != {INTERFACE_VERSION!r}")
        image = req(raw, "image", path="descriptor")
        if not isinstance(image, Mapping):
            raise ContractError("descriptor.image must be an object of registry/repository/digest")
        reject_unknown_keys(image, ("registry", "repository", "digest"), path="descriptor.image")
        registry = req_str(image, "registry", path="descriptor.image")
        repository = req_str(image, "repository", path="descriptor.image")
        if not _REGISTRY_RE.match(registry):
            raise ContractError(f"descriptor.image.registry={registry!r} is not a hostname[:port]")
        if not _REPOSITORY_RE.match(repository):
            raise ContractError(
                f"descriptor.image.repository={repository!r} is not a lowercase image path"
            )
        license_id = req_str(raw, "license", path="descriptor")
        if not _SPDX_RE.match(license_id):
            raise ContractError(f"descriptor.license={license_id!r} is not an SPDX identifier")

        # [] is valid: a model-free submission (deterministic simulator, text-blind baseline)
        # declares the empty array. The KEY stays required, so "no model" is a positive
        # statement rather than an omission (#62).
        models_raw = req_list(raw, "models", path="descriptor")
        models = tuple(
            ModelDisclosure.from_mapping(entry, path=f"descriptor.models[{i}]")
            for i, entry in enumerate(models_raw)
        )
        names = [m.name for m in models]
        if len(set(names)) != len(names):
            raise ContractError("descriptor.models lists the same model name twice")

        descriptor = cls(
            schema_version=version,
            interface_version=interface_version,
            competition_id=req_str(raw, "competition_id", path="descriptor"),
            team_id=req_str(raw, "team_id", path="descriptor"),
            track=req_enum(raw, "track", TRACKS, path="descriptor"),
            phase=req_enum(raw, "phase", PHASES, path="descriptor"),
            # R-1: required on all four tracks. A missing category is a validation error, not an
            # implied "api", and it is not conditional on the track.
            category=req_enum(raw, "category", CATEGORIES, path="descriptor"),
            registry=registry,
            repository=repository,
            image_digest=parse_digest(
                req(image, "digest", path="descriptor.image"), field="descriptor.image.digest"
            ),
            image_access=req_enum(raw, "image_access", IMAGE_ACCESS, path="descriptor"),
            models=models,
            license=license_id,
            descriptor_digest=parse_digest(
                req(raw, "descriptor_digest", path="descriptor"), field="descriptor_digest"
            ),
        )
        computed = digest_json({k: v for k, v in raw.items() if k != "descriptor_digest"})
        if computed != descriptor.descriptor_digest:
            raise ContractError(
                f"descriptor_digest {descriptor.descriptor_digest} does not match the canonical "
                f"descriptor body ({computed})"
            )
        return descriptor

    # ------------------------------------------------------------------ behaviour
    def image_reference(self) -> str:
        """Reassemble `registry/repository@sha256:...`, with the argv-injection guards applied.

        The freeze says that if a string form is ever reintroduced it must forbid a leading `-`,
        forbid `=` and whitespace, and bound its length — so the *reassembly* enforces exactly
        that, and the guard cannot be forgotten by a consumer that builds the string by hand.
        Consumers must still place `--` before the image position in an argv.
        """
        reference = f"{self.registry}/{self.repository}@{self.image_digest}"
        if reference.startswith("-"):
            raise ContractError("an image reference may not begin with '-'")
        if "=" in reference or any(ch.isspace() for ch in reference):
            raise ContractError("an image reference may not contain '=' or whitespace")
        if len(reference) > _MAX_REFERENCE_LEN:
            raise ContractError(f"image reference exceeds {_MAX_REFERENCE_LEN} characters")
        return reference

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "interface_version": self.interface_version,
            "competition_id": self.competition_id,
            "team_id": self.team_id,
            "track": self.track,
            "phase": self.phase,
            "category": self.category,
            "image": {
                "registry": self.registry,
                "repository": self.repository,
                "digest": self.image_digest,
            },
            "image_access": self.image_access,
            "models": [m.to_mapping() for m in self.models],
            "license": self.license,
            "descriptor_digest": self.descriptor_digest,
        }

    def matches_plan(self, *, competition_id: str, track: str, phase: str) -> None:
        """Refuse a descriptor from another competition, track or phase. All three, always."""
        mismatches = []
        if self.competition_id != competition_id:
            mismatches.append(f"competition_id {self.competition_id!r} != {competition_id!r}")
        if self.track != track:
            mismatches.append(f"track {self.track!r} != {track!r}")
        if self.phase != phase:
            mismatches.append(f"phase {self.phase!r} != {phase!r}")
        if mismatches:
            raise ContractError("descriptor does not match the plan: " + "; ".join(mismatches))

    def category_served_by(self, served: Sequence[str]) -> bool:
        return self.category in set(served)


def seal_descriptor_digest(body: Mapping[str, Any]) -> dict[str, Any]:
    """Return `body` with a correct `descriptor_digest` attached. Used to build fixtures."""
    without = {k: v for k, v in body.items() if k != "descriptor_digest"}
    return {**without, "descriptor_digest": digest_json(without)}
