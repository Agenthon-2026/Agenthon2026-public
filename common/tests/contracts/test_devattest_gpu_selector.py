# --------------------------------------------------------------------------------------------- #
# R-5 selector classification, both directions.
#
# `ingest.py:gpu_args()` records the docker FLAG form (`device=GPU-...`) in
# `applied.gpu.applied`, not the bare UUID. The projection used to test the raw string for a
# `GPU-` prefix, so a correctly pinned device classified as `all` while `source` stayed `pinned`
# -- and C2 then refused the record for not declaring a `gpu_device_unpinned` control that was
# never true. Measured 2026-09-04: every gpu=true unit filed 0 of 1 run records.
#
# Both directions are asserted deliberately. A fix that made everything classify as `uuid` would
# be worse than the bug: `all` has to keep costing the control.
# --------------------------------------------------------------------------------------------- #
_REAL_UUID = "GPU-c8076968-b9e6-53ab-227a-228b5ba3a29f"


def _project(applied_value, source="pinned"):
    from qfbench2_common.contracts import devattest

    obs = {
        "applied": {
            "gpu": {"requested": "required", "applied": applied_value, "source": source},
            "runtime": {},
            "network": {},
            "limits": {},
        }
    }
    return devattest._applied(obs)["gpu"]


def test_a_pinned_device_in_docker_flag_form_classifies_as_uuid():
    """THE REGRESSION. This is the form the Hub actually writes."""
    gpu = _project(f"device={_REAL_UUID}")
    assert gpu["selector"] == "uuid", gpu
    assert gpu["uuid"] == _REAL_UUID, gpu


def test_a_bare_uuid_still_classifies_as_uuid():
    gpu = _project(_REAL_UUID)
    assert gpu["selector"] == "uuid" and gpu["uuid"] == _REAL_UUID, gpu


def test_a_genuine_all_still_classifies_as_all():
    """The other direction: the fix must not launder an unpinned run into a pinned one."""
    gpu = _project("all")
    assert gpu["selector"] == "all", gpu
    assert gpu["uuid"] is None, gpu


def test_an_index_still_classifies_as_index_in_both_forms():
    for value in ("0", "device=0"):
        gpu = _project(value)
        assert gpu["selector"] == "index", (value, gpu)
        assert gpu["uuid"] is None, (value, gpu)


def test_no_device_applied_stays_null():
    gpu = _project(None)
    assert gpu["selector"] is None and gpu["uuid"] is None, gpu


def test_a_non_uuid_behind_the_prefix_is_not_promoted_to_uuid():
    """Stripping the prefix must not turn arbitrary text into a pinned device."""
    gpu = _project("device=not-a-device")
    assert gpu["selector"] == "all", gpu
    assert gpu["uuid"] is None, gpu
