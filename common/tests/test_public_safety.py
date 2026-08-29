"""The public-safety firewall, and the hole it used to have.

`assert_public_safe` exempted practice (`public-dev`) units from every answer-material rule. The
exemption exists so a practice unit can ship reference VALUES under `checks/reference_data/` for
self-grading — but it was applied to the whole unit, so a practice unit could also carry
`reference/outcome.json`, the answer key at the exact path the scorer reads, and the check returned
no errors.

Measured 2026-08-28 by copying a genuine private `outcome.json` into a public practice unit: the
caller exited 0 and printed "answer-safe". These tests pin the exemption to the path that justifies
it, and pin that real practice content still passes.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from qfbench2_common.manifest import assert_public_safe

CARD = '[task]\nsplit = "public-dev"\n'


def _unit(tmp_path: pathlib.Path, name: str = "t4-practice") -> pathlib.Path:
    u = tmp_path / name
    u.mkdir()
    (u / "card.toml").write_text(CARD, encoding="utf-8")
    (u / "task.json").write_text(json.dumps({"task_id": name}), encoding="utf-8")
    (u / "manifest.json").write_text(json.dumps({"files": []}), encoding="utf-8")
    return u


def _answer_errors(unit: pathlib.Path) -> list[str]:
    return [
        e for e in assert_public_safe(unit) if "answer material" in e or "resolved outcome" in e
    ]


class TestAPracticeUnitMayStillSelfGrade:
    def test_reference_values_under_checks_are_allowed(self):
        """The one exemption, and the reason it exists."""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            u = _unit(pathlib.Path(td))
            d = u / "checks" / "reference_data"
            d.mkdir(parents=True)
            (d / "expected.json").write_text('{"value": 1}', encoding="utf-8")
            assert _answer_errors(u) == []

    def test_a_practice_unit_with_no_answer_material_passes(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            assert _answer_errors(_unit(pathlib.Path(td))) == []


class TestTheAnswerKeyPathIsNotExempt:
    """`reference/outcome.json` is where the scorer reads answers. No split makes it publishable."""

    @pytest.mark.parametrize("split", ["public-dev", "public", "validation"])
    def test_an_outcome_file_under_reference_is_refused(self, split, tmp_path):
        u = tmp_path / "u"
        u.mkdir()
        (u / "card.toml").write_text(f'[task]\nsplit = "{split}"\n', encoding="utf-8")
        (u / "manifest.json").write_text(json.dumps({"files": []}), encoding="utf-8")
        ref = u / "reference"
        ref.mkdir()
        (ref / "outcome.json").write_text('{"outcomes": []}', encoding="utf-8")
        errs = _answer_errors(u)
        assert errs, f"a planted answer key passed on split={split!r}"
        assert any("reference/" in e for e in errs)

    def test_adversarial_variants_are_refused_on_a_practice_unit(self, tmp_path):
        u = _unit(tmp_path)
        d = u / "adversarial_variants"
        d.mkdir()
        (d / "trap.json").write_text("{}", encoding="utf-8")
        assert _answer_errors(u)

    def test_a_held_out_unit_is_still_refused_outright(self, tmp_path):
        u = tmp_path / "u"
        u.mkdir()
        (u / "card.toml").write_text('[task]\nsplit = "private-test"\n', encoding="utf-8")
        (u / "manifest.json").write_text(json.dumps({"files": []}), encoding="utf-8")
        assert any("private-test" in e for e in assert_public_safe(u))
