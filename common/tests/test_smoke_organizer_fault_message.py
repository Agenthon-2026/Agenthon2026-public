"""A track with no preview factory must not show a participant a traceback.

`qfbench2 smoke --track simulation` reaches the rankable factory, which needs organizer-held
evidence a participant cannot have. Before this, that surfaced as an uncaught `OrganizerFault`
traceback — our own word for OUR failure, printed at someone for running a command we accept.
"""

from __future__ import annotations

import argparse
import sys


from qfbench2_common import cli
from qfbench2_common.contracts.errors import OrganizerFault


def _args(track="simulation", profile="smoke"):
    return argparse.Namespace(track=track, profile=profile, unit_dir="u", output_dir="o")


class TestATrackWithNoPreviewFactoryFailsLegibly:
    def _run(self, monkeypatch, capsys, exc):
        mod = type(sys)("qfbench2_track_simulation.scoring")
        monkeypatch.setitem(sys.modules, "qfbench2_track_simulation.scoring", mod)

        from qfbench2_common import smoke as smoke_mod

        monkeypatch.setattr(smoke_mod, "resolve_verifier_factory", lambda m, p: ("f", object()))

        def boom(*a, **k):
            raise exc

        monkeypatch.setattr(smoke_mod, "run_smoke", boom)
        rc = cli._cmd_smoke(_args())
        return rc, capsys.readouterr()

    def test_it_exits_two_and_explains_rather_than_raising(self, monkeypatch, capsys):
        rc, out = self._run(
            monkeypatch,
            capsys,
            OrganizerFault("the production Track 3 verifier requires the trusted C2 run record"),
        )
        assert rc == 2, "a missing preview factory is not 'inadmissible' (1) and not success (0)"
        text = out.err
        assert "not a problem with your submission" in text
        assert "nothing you did caused it" in text
        assert "README" in text, "must point at the route that does work"

    def test_it_does_not_print_our_blame_vocabulary_at_the_participant(self, monkeypatch, capsys):
        rc, out = self._run(monkeypatch, capsys, OrganizerFault("some internal detail"))
        assert rc == 2
        assert "OrganizerFault" not in out.err, (
            "'OrganizerFault' is our word for our failure; showing the class name to a participant "
            "teaches the opposite of what the fault vocabulary means"
        )
        assert "Traceback" not in out.err

    def test_a_genuine_inadmissible_result_is_still_exit_one(self, monkeypatch, capsys):
        import sys as _sys

        mod = type(_sys)("qfbench2_track_simulation.scoring")
        monkeypatch.setitem(_sys.modules, "qfbench2_track_simulation.scoring", mod)
        from qfbench2_common import smoke as smoke_mod

        monkeypatch.setattr(smoke_mod, "resolve_verifier_factory", lambda m, p: ("f", object()))
        monkeypatch.setattr(
            smoke_mod, "run_smoke", lambda *a, **k: type("V", (), {"admissible": False})()
        )
        assert cli._cmd_smoke(_args()) == 1, "the ordinary refusal path must be untouched"
