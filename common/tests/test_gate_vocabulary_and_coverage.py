"""Four ways a unit-level gate could be walked past, and the honest material each must keep passing.

Every case below was executed against this tree on 2026-08-29 and returned **zero errors** before
the fix. They are four instances of one failure mode: a guard that matches a *spelling* or a
*string prefix* rather than a *shape*.

    1. `_self_grading_path` was `path.startswith("checks/reference_data/")`, so
       `checks/reference_data/reference/outcome.json` -- the answer key, in a directory named
       exactly what the scorer reads -- was exempt on a practice unit. The blocked layout, rebuilt
       one level inside the exemption.
    3. Derived manifest coverage claimed the unit root only when the manifest happened to list a
       root-level file, so on a unit whose manifest listed `environment/data/input.txt` alone, an
       `answers.json` beside `card.toml` was invisible -- while the identical file one level lower
       inside `environment/data/` was refused.
    4. `_ORACLE_DIRS` / `_ORACLE_GLOBS` knew `solution/` and `solve.sh` but not `solutions/` and
       `solve.py`.
    7. `_ANSWER_DIRS` knew the singular `reference` but not the plural `references`.
    8. `_ANSWER_DIRS` knew neither `reference_data`, so Track 3's batched reference material
       stopped being answer material by being RENAMED out of `references/` into
       `checks/reference_data/` -- a directory that, off the practice split, no rule named at all.
       Its companion in `dataset.STRIP_DIRS`/`FINGERPRINT_DIRS` was blind to the same name, so a
       reference file whose basename `STRIP_FILES` does not list survived into the mounted tree.

Each hole is paired here with the legitimate material it must NOT start refusing. Over-tightening
is not a safe direction to fail in: a firewall that refuses honest units is one somebody turns off,
which is how the module header already justifies deriving `environment/data/` rather than
`environment/`.
"""

from __future__ import annotations

import hashlib
import json
import pathlib

import pytest

from qfbench2_common.manifest import assert_public_safe, verify_manifest


def _unit(tmp_path: pathlib.Path, split: str = "public-dev", *, manifest_data: bool = True):
    """A minimal, honest unit: one manifested data file, a card, an instruction, a manifest."""
    u = tmp_path / "unit"
    (u / "environment" / "data").mkdir(parents=True)
    payload = b"hello\n"
    (u / "environment" / "data" / "input.txt").write_bytes(payload)
    (u / "card.toml").write_text(
        f'[task]\nid = "unit"\ntrack = "analysis"\nsplit = "{split}"\n', encoding="utf-8"
    )
    (u / "instruction.md").write_text("do the thing\n", encoding="utf-8")
    files = (
        [
            {
                "path": "environment/data/input.txt",
                "role": "input",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
                "redistributable": True,
            }
        ]
        if manifest_data
        else []
    )
    (u / "manifest.json").write_text(
        json.dumps({"manifest_version": "2.0", "unit_id": "unit", "files": files}) + "\n",
        encoding="utf-8",
    )
    return u


def _answer_errors(unit: pathlib.Path) -> list[str]:
    return [
        e
        for e in assert_public_safe(unit)
        if "answer material" in e or "resolved outcome" in e or "oracle" in e
    ]


# --------------------------------------------------------------------------------------------- #
# The controls. If these ever fail, every "the hole is closed" assertion below is meaningless.    #
# --------------------------------------------------------------------------------------------- #
class TestTheHonestUnitIsClean:
    def test_a_bare_practice_unit_raises_nothing(self, tmp_path):
        u = _unit(tmp_path)
        assert assert_public_safe(u) == []
        assert verify_manifest(u) == []

    def test_assert_public_safe_returns_and_never_raises(self, tmp_path):
        """The published idiom's own trap: this function RETURNS its findings.

        A caller that wraps it in try/except and reports "clean" on no exception reports a false
        green on every unit, leaked or not. Pinned here so the contract is executable.
        """
        u = _unit(tmp_path)
        (u / "solution").mkdir()
        (u / "solution" / "oracle.py").write_text("# the answer\n", encoding="utf-8")
        result = assert_public_safe(u)  # must not raise
        assert isinstance(result, list) and result, "a planted oracle must be REPORTED, not raised"


# --------------------------------------------------------------------------------------------- #
# (1) the self-grading exemption is a place in the tree, not a string prefix                      #
# --------------------------------------------------------------------------------------------- #
class TestSelfGradingExemptionIsScoped:
    @pytest.mark.parametrize(
        "rel",
        [
            "checks/reference_data/reference/outcome.json",
            "checks/reference_data/references/outcome.json",
            "checks/reference_data/sub_01/reference/expected.json",
            "checks/reference_data/adversarial_variants/trap.json",
            "checks/reference_data/solution/solve_it.txt",
        ],
    )
    def test_answer_material_renamed_inside_the_exemption_is_refused(self, rel, tmp_path):
        u = _unit(tmp_path)
        p = u / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('{"outcomes": [{"entity_id": "AAPL", "y": 1.23}]}', encoding="utf-8")
        errs = _answer_errors(u)
        assert errs, f"{rel} passed public-safety on a practice unit"

    @pytest.mark.parametrize(
        "rel",
        [
            "checks/reference_data/expected.json",
            "checks/reference_data/checkpoints.json",
            "checks/reference_data/sub_01/expected.json",
            "checks/reference_data/sub_00_short/checkpoints.json",
            "checks/reference_data/concept_graph.json",
        ],
    )
    def test_real_self_grading_values_still_pass(self, rel, tmp_path):
        """The batched practice-pool layout that Track 1 and Track 3 actually ship."""
        u = _unit(tmp_path)
        p = u / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('{"value": 1}', encoding="utf-8")
        assert _answer_errors(u) == [], f"{rel} is legitimate self-grading material"

    def test_the_exemption_does_not_apply_off_the_practice_split(self, tmp_path):
        u = _unit(tmp_path, split="validation")
        d = u / "checks" / "reference_data"
        d.mkdir(parents=True)
        (d / "expected.json").write_text("{}", encoding="utf-8")
        assert _answer_errors(u), "the exemption is for public-dev only"

    def test_the_self_grading_root_itself_stays_exempt(self, tmp_path):
        """`checks/reference_data/` is now an answer-vocabulary NAME, and still a legal PLACE.

        Adding `reference_data` to `_ANSWER_DIRS` makes `_dirs_anywhere` report the practice pool's
        own self-grading directory on every unit that has one -- 24 of them across Track 1 and
        Track 3, all `public-dev`. If `_self_grading_path` did not exempt the root, closing the
        rename hole would refuse every practice unit that ships self-grading values, which is the
        over-tightening this module's header warns about.
        """
        u = _unit(tmp_path)
        d = u / "checks" / "reference_data"
        d.mkdir(parents=True)
        (d / "expected.json").write_text("{}", encoding="utf-8")
        assert _answer_errors(u) == [], "the practice self-grading root is the documented exemption"

    def test_the_blocked_layout_cannot_be_rebuilt_under_the_new_name_either(self, tmp_path):
        """`checks/reference_data/reference/` was already refused; `.../reference_data/` now is too.

        Measured 2026-08-29 before the fix: this returned zero errors, because `reference_data` was
        not in `_ANSWER_DIRS` and so was not a name `_self_grading_path` looked for BELOW the root.
        The cheapest bypass of an exemption is to rebuild the blocked layout one level inside it,
        and the vocabulary that guards the inside is the same one that guards the outside.
        """
        u = _unit(tmp_path)
        d = u / "checks" / "reference_data" / "reference_data"
        d.mkdir(parents=True)
        (d / "outcome.json").write_text("{}", encoding="utf-8")
        assert _answer_errors(u)

    def test_the_exemption_is_anchored_at_the_unit_root(self, tmp_path):
        """`checks/reference_data/` is a place. A lookalike elsewhere is not that place."""
        u = _unit(tmp_path)
        d = u / "nested" / "checks" / "reference_data" / "reference"
        d.mkdir(parents=True)
        (d / "outcome.json").write_text("{}", encoding="utf-8")
        assert _answer_errors(u)


# --------------------------------------------------------------------------------------------- #
# (4) + (7) both spellings of the oracle and answer vocabularies                                  #
# --------------------------------------------------------------------------------------------- #
class TestVocabularyCoversBothSpellings:
    @pytest.mark.parametrize("split", ["public-dev", "validation", "public"])
    @pytest.mark.parametrize("dirname", ["solution", "solutions"])
    def test_an_oracle_directory_is_refused_on_every_split(self, dirname, split, tmp_path):
        u = _unit(tmp_path, split=split)
        (u / dirname).mkdir()
        (u / dirname / "ref.py").write_text("# the reference implementation\n", encoding="utf-8")
        assert any(f"{dirname}/" in e for e in assert_public_safe(u))

    @pytest.mark.parametrize("split", ["public-dev", "validation", "public"])
    @pytest.mark.parametrize("name", ["solve.sh", "solve.py", "solution.py"])
    def test_an_oracle_script_is_refused_on_every_split(self, name, split, tmp_path):
        u = _unit(tmp_path, split=split)
        (u / name).write_text("# the oracle\n", encoding="utf-8")
        assert any(name in e for e in assert_public_safe(u))

    @pytest.mark.parametrize(
        "dirname", ["reference", "references", "reference_data", "adversarial_variants"]
    )
    def test_answer_directories_are_refused_off_the_practice_split(self, dirname, tmp_path):
        u = _unit(tmp_path, split="validation")
        (u / dirname).mkdir()
        (u / dirname / "trace.parquet").write_bytes(b"PAR1")
        assert any(f"{dirname}/" in e for e in _answer_errors(u))

    @pytest.mark.parametrize("dirname", ["reference", "references", "reference_data"])
    def test_answer_directories_are_refused_on_a_practice_unit_too(self, dirname, tmp_path):
        """The practice exemption is `checks/reference_data/`, not these at the root.

        `reference_data` is in this list and NOT in the lookalike list below, which is the whole
        of the 2026-08-29 policy change: the exemption is a PLACE (`checks/reference_data/`), so
        the same basename anywhere else -- at the unit root, or rebuilt inside the exemption -- is
        answer material like any other spelling of `reference`.
        """
        u = _unit(tmp_path)
        (u / dirname).mkdir()
        (u / dirname / "step_1.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        assert any(f"{dirname}/" in e for e in _answer_errors(u))

    @pytest.mark.parametrize(
        "rel",
        [
            "references_readme.md",
            "solver_notes.md",
            "resolution.py",
            "dev_guide.md",
            "checks/reference_data/values.csv",
        ],
    )
    def test_lookalike_names_are_not_swept_up(self, rel, tmp_path):
        """Component equality, not substring matching.

        Widening the vocabulary must not start refusing any name that merely CONTAINS `reference`,
        `solve` or `dev` as a substring, nor the self-grading directory the exemption is built
        around: `checks/reference_data/values.csv` is here and must stay passing.

        A bare `reference_data/values.csv` used to be in this list and is now refused on purpose;
        it moved to `test_answer_directories_are_refused_on_a_practice_unit_too`. The exemption is
        the PLACE `checks/reference_data/`, never the basename on its own -- which is exactly the
        distinction the rest of this class exists to hold.
        """
        u = _unit(tmp_path)
        p = u / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("a,b\n1,2\n", encoding="utf-8")
        assert _answer_errors(u) == [], f"{rel} is not answer material"


# --------------------------------------------------------------------------------------------- #
# (3) the manifest gate can see the unit root                                                     #
# --------------------------------------------------------------------------------------------- #
class TestManifestSeesTheUnitRoot:
    def test_a_planted_file_at_the_unit_root_is_refused(self, tmp_path):
        u = _unit(tmp_path)
        (u / "answers.json").write_text('{"AAPL": "beat"}\n', encoding="utf-8")
        errs = verify_manifest(u)
        assert any("answers.json" in e for e in errs), errs

    def test_the_root_is_covered_even_when_no_root_file_is_manifested(self, tmp_path):
        """The old rule made root coverage depend on an accident of the manifest's contents."""
        u = _unit(tmp_path)
        manifest = json.loads((u / "manifest.json").read_text())
        assert all("/" in e["path"] for e in manifest["files"]), "fixture must list no root file"
        (u / "leak.csv").write_text("entity,answer\nAAPL,beat\n", encoding="utf-8")
        assert any("leak.csv" in e for e in verify_manifest(u))

    def test_an_empty_manifest_no_longer_disables_the_disk_direction(self, tmp_path):
        """`files: []` used to derive no coverage at all, so the whole walk was skipped."""
        u = _unit(tmp_path, manifest_data=False)
        assert verify_manifest(u) == [], "an empty manifest over an unclaimed subtree is clean"
        (u / "leak.json").write_text('{"AAPL": "beat"}', encoding="utf-8")
        assert any("leak.json" in e for e in verify_manifest(u))

    @pytest.mark.parametrize("name", ["card.toml", "task.toml", "instruction.md", "manifest.json"])
    def test_the_documented_non_data_root_files_are_never_extras(self, name, tmp_path):
        """The four names this module's own header calls out as legitimately not data.

        `card.toml`, `instruction.md` and `manifest.json` already exist in the fixture; `task.toml`
        is added. Covering the unit root unconditionally would refuse all four on every real unit
        without this exemption -- measured at 175 refusals across the staged corpus.
        """
        u = _unit(tmp_path)
        if name == "task.toml":
            (u / name).write_text('[task]\nid = "unit"\n', encoding="utf-8")
        assert (u / name).exists()
        assert verify_manifest(u) == [], f"{name} must not be reported as an unmanifested extra"

    def test_the_exemption_is_root_only(self, tmp_path):
        """A `card.toml` inside a covered subtree is data like anything else there."""
        u = _unit(tmp_path)
        (u / "environment" / "data" / "card.toml").write_text("x\n", encoding="utf-8")
        assert any("environment/data/card.toml" in e for e in verify_manifest(u))

    def test_an_honest_unit_with_uncovered_subtrees_still_passes(self, tmp_path):
        """`checks/` and `environment/Dockerfile` are the shapes every Track 1 unit ships.

        Claiming them would refuse 388 legitimate files across the staged corpus, which is why
        derived coverage still stops at the manifested entry's parent.
        """
        u = _unit(tmp_path)
        (u / "environment" / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
        (u / "checks").mkdir()
        (u / "checks" / "test_outputs.py").write_text("def test_x(): pass\n", encoding="utf-8")
        (u / "checks" / "test.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        assert verify_manifest(u) == []
