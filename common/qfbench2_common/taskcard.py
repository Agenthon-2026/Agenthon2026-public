"""Parse and validate task-card v2 (card.toml)."""

from __future__ import annotations

import json
import pathlib
from typing import Any

try:
    import tomllib as _toml  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as _toml  # type: ignore

_SCHEMA_DIR = pathlib.Path(__file__).resolve().parent / "schemas"


def schema_path(name: str) -> pathlib.Path:
    """Absolute path to a bundled JSON schema. Schemas ship *inside* the package
    (``qfbench2_common/schemas/``) so they resolve identically from a source
    checkout and a ``pip install``ed wheel."""
    return _SCHEMA_DIR / name


def load_schema(name: str) -> dict[str, Any]:
    """Load a bundled JSON schema by filename, e.g. ``load_schema("taskcard.schema.json")``."""
    data: dict[str, Any] = json.loads(schema_path(name).read_text())
    return data


def load_card(unit_dir: str | pathlib.Path) -> dict[str, Any]:
    """Load <unit_dir>/card.toml into a dict."""
    p = pathlib.Path(unit_dir) / "card.toml"
    with p.open("rb") as fh:
        return _toml.load(fh)


def validate_card(card: dict[str, Any]) -> list[str]:
    """Validate against taskcard.schema.json. Returns a list of error strings ([] = valid).
    Requires `jsonschema`; if absent, performs minimal required-key checks."""
    schema = load_schema("taskcard.schema.json")
    try:
        import jsonschema

        validator = jsonschema.Draft202012Validator(schema)
        return [f"{'/'.join(map(str, e.path))}: {e.message}" for e in validator.iter_errors(card)]
    except ModuleNotFoundError:
        errs = []
        for key in schema["required"]:
            if key not in card:
                errs.append(f"missing required top-level key '{key}'")
        return errs


def load_and_validate(unit_dir: str | pathlib.Path) -> tuple[dict[str, Any], list[str]]:
    card = load_card(unit_dir)
    return card, validate_card(card)
