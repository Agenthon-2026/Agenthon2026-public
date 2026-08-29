"""Executive summary (read this first): Harbor adapter for Track-4 exec units.

Track-4 factor-replication units run under the same Harbor runner as Track 1 (this
module reuses `track1.harbor.run_harbor` / `load_harbor_job` for launch and job
normalization) but are scored on the CONTINUOUS reward each unit's verifier writes to
`verifier/reward.json` (the factor-replication composite in [0, 1]), not on binary
pass@k alone. The headline metric is the cross-unit mean of the per-unit mean reward
with a bootstrap CI; thresholded pass@k (per-unit `pass_threshold` from card.toml
`[scoring.params]`) is reported alongside for Harbor-tooling compatibility.
"""

from __future__ import annotations

import json
import pathlib
from collections import defaultdict
from typing import Any, Sequence

import numpy as np

try:
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover
    import tomli as _toml  # type: ignore

from qfbench2_common.eval import AttemptResult
from qfbench2_common.scoring import bootstrap, passk
from qfbench2_common.track1.harbor import (
    _canonical_unit_id,
    _discover_units,
    load_harbor_job,
    run_harbor,
)

RUNNER = "harbor"
TRACK = "analysis"
_DEFAULT_KS = (1, 3)

__all__ = ["run_harbor", "score_exec_job", "write_exec_score"]


def score_exec_job(
    job_dir: str | pathlib.Path,
    *,
    units_dir: str | pathlib.Path | None = None,
    n_attempts: int = 3,
    ks: tuple[int, ...] = _DEFAULT_KS,
    pass_threshold_default: float = 1.0,
    n_boot: int = 10_000,
    seed: int = 0,
) -> dict[str, Any]:
    """Score a Harbor job of Track-4 exec units on continuous rewards.

    Per unit: mean reward and best-of-n reward over its attempts (a missing/crashed
    attempt contributes 0.0 and is counted in `n_no_reward`). Cross-unit headline:
    mean of per-unit mean rewards with a bootstrap CI. Thresholded pass@k is computed
    per unit against its card's `[scoring.params].pass_threshold` when `units_dir` is
    given (else `pass_threshold_default`, whose 1.0 default reproduces reward.txt
    semantics); unlike Track 1 an incomplete job degrades pass@k to null for the
    affected k rather than raising, because the continuous headline stays valid.
    """
    run = load_harbor_job(job_dir)
    unit_ids, aliases = _discover_units(units_dir)
    thresholds = _unit_thresholds(units_dir, pass_threshold_default)

    grouped: dict[str, list[AttemptResult]] = defaultdict(list)
    for attempt in run.attempts:
        grouped[_canonical_unit_id(attempt.unit_id, aliases)].append(attempt)

    if not unit_ids:
        unit_ids = sorted(grouped)
    else:
        for unit_id in grouped:
            if unit_id not in unit_ids:
                unit_ids.append(unit_id)
    if not unit_ids:
        raise ValueError(f"no Harbor trial results found in {job_dir}")

    per_task: dict[str, dict[str, Any]] = {}
    mean_rewards: list[float] = []
    best_rewards: list[float] = []
    insufficient: dict[str, int] = {}
    max_k = max(ks)

    for unit_id in unit_ids:
        attempts = sorted(grouped.get(unit_id, ()), key=lambda a: a.attempt_index)
        threshold = thresholds.get(unit_id, pass_threshold_default)
        rewards = [
            float(a.reward) if (a.reward is not None and _clean(a)) else 0.0 for a in attempts
        ]
        passes = [r >= threshold for r in rewards]
        n_obs = len(attempts)
        if n_obs < max_k:
            insufficient[unit_id] = n_obs
        mean_r = float(np.mean(rewards)) if rewards else 0.0
        best_r = float(np.max(rewards)) if rewards else 0.0
        mean_rewards.append(mean_r)
        best_rewards.append(best_r)
        per_task[unit_id] = {
            "rewards": rewards,
            "mean_reward": mean_r,
            "best_reward": best_r,
            "pass_threshold": threshold,
            "attempts": passes,
            "n_observed_attempts": n_obs,
            "n_passed": sum(passes),
            "n_no_reward": sum(1 for a in attempts if a.reward is None),
        }

    metrics: dict[str, dict[str, float]] = {}
    for name, values in (
        ("replication_composite_mean", mean_rewards),
        ("replication_composite_best", best_rewards),
    ):
        point, lo, hi = bootstrap.bootstrap_ci(
            np.asarray(values, dtype=np.float64), n_boot=n_boot, seed=seed
        )
        metrics[name] = {"point": point, "ci_lower": lo, "ci_upper": hi}

    for k in ks:
        values = []
        for unit_id in unit_ids:
            task = per_task[unit_id]
            n_obs = int(task["n_observed_attempts"])
            if n_obs < k:
                task[f"pass@{k}"] = None
                continue
            value = passk.pass_at_k(n_obs, int(task["n_passed"]), k)
            task[f"pass@{k}"] = value
            values.append(value)
        if values and len(values) == len(unit_ids):
            point, lo, hi = bootstrap.bootstrap_ci(
                np.asarray(values, dtype=np.float64), n_boot=n_boot, seed=seed
            )
            metrics[f"pass@{k}"] = {"point": point, "ci_lower": lo, "ci_upper": hi}

    result: dict[str, Any] = {
        "schema_version": "2.0",
        "track": TRACK,
        "runner": RUNNER,
        "job_dir": str(pathlib.Path(job_dir)),
        "units_dir": str(pathlib.Path(units_dir)) if units_dir is not None else None,
        "n_tasks": len(unit_ids),
        "n_attempts_per_task": n_attempts,
        "primary_metric": "replication_composite_mean",
        "leaderboard_sort": {"metric": "replication_composite_mean", "order": "desc"},
        "metrics": metrics,
        "per_task": per_task,
    }
    if insufficient:
        result["incomplete_tasks"] = dict(sorted(insufficient.items()))
    return result


def write_exec_score(score: dict[str, Any], output_path: str | pathlib.Path) -> None:
    """Write a Track-4 exec-job score JSON file."""

    pathlib.Path(output_path).write_text(json.dumps(score, indent=2) + "\n")


def _clean(attempt: AttemptResult) -> bool:
    return attempt.detail.get("exception_info") is None


def _unit_thresholds(
    units_dir: str | pathlib.Path | None,
    default: float,
) -> dict[str, float]:
    """Per-unit `[scoring.params].pass_threshold` from each card.toml under units_dir."""
    if units_dir is None:
        return {}
    root = pathlib.Path(units_dir)
    if not root.exists():
        raise FileNotFoundError(f"units directory not found: {root}")
    task_dirs: Sequence[pathlib.Path] = (
        [root] if (root / "card.toml").exists() else sorted(p for p in root.iterdir() if p.is_dir())
    )
    thresholds: dict[str, float] = {}
    for unit_dir in task_dirs:
        card_path = unit_dir / "card.toml"
        if not card_path.exists():
            continue
        with card_path.open("rb") as fh:
            card = _toml.load(fh)
        task = card.get("task")
        unit_id = task.get("id") if isinstance(task, dict) else None
        if not isinstance(unit_id, str):
            unit_id = unit_dir.name
        params = card.get("scoring", {}).get("params", {})
        value = params.get("pass_threshold", default)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            thresholds[unit_id] = float(value)
    return thresholds
