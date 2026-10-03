"""Unit handles are directory names: a trailing newline is refused in every phase.

`validate_unit_handle` is the grammar check the C1 parser applies to every roster handle and that
callers outside C1 run directly. Both of its patterns end in `$`, which a plain `match` lets stand
before one trailing newline, so `"unit-a\\n"` used to pass; the check is a full match.
"""

from __future__ import annotations

import pytest

from qfbench2_common.contracts import OrganizerFault
from qfbench2_common.contracts.plan import validate_unit_handle


@pytest.mark.parametrize("phase", ["dev", "final", "verification"])
def test_a_trailing_newline_is_refused_by_the_handle_validator_itself(phase):
    validate_unit_handle("u-0123456789abcdef", phase=phase)  # presence control
    for handle in ("u-0123456789abcdef\n", "unit-a\n"):
        with pytest.raises(OrganizerFault, match="character class"):
            validate_unit_handle(handle, phase=phase)


def test_a_readable_handle_stays_valid_in_development():
    """CONTROL: the Development grammar still takes a readable name."""
    assert validate_unit_handle("unit-a", phase="dev") == "unit-a"
