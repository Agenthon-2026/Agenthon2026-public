"""Executive summary (read this first): Harbor adapter for Track 1.

Harbor owns task execution and sandboxing. This module only knows how to launch Harbor, normalize
its job artifacts, and compute the QFBench Track 1 pass@k metrics from binary rewards.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from typing import Any, Iterable, Sequence

import numpy as np

from qfbench2_common.eval import AttemptResult, EvalRunResult
from qfbench2_common.failure_labels import FailureLabel
from qfbench2_common.scoring import bootstrap, passk

try:
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover
    import tomli as _toml  # type: ignore


RUNNER = "harbor"
TRACK = "coding"
_DEFAULT_KS = (1, 3)


def run_harbor(
    units_dir: str | pathlib.Path,
    *,
    jobs_dir: str | pathlib.Path,
    job_name: str,
    n_attempts: int = 3,
    agent: str = "oracle",
    n_concurrent: int = 1,
    harbor_executable: str = "harbor",
    task_names: Sequence[str] | None = None,
    extra_args: Sequence[str] = (),
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run Harbor against a local Track 1 task directory or task tree."""

    cmd = [
        harbor_executable,
        "run",
        "--path",
        str(units_dir),
        "--jobs-dir",
        str(jobs_dir),
        "--job-name",
        job_name,
        "--n-attempts",
        str(n_attempts),
        "--n-concurrent",
        str(n_concurrent),
        "--agent",
        agent,
        "--yes",
    ]
    for task_name in task_names or ():
        cmd.extend(["--include-task-name", task_name])
    cmd.extend(extra_args)
    return subprocess.run(cmd, check=check, text=True)


def load_harbor_job(job_dir: str | pathlib.Path) -> EvalRunResult:
    """Normalize a Harbor job directory into runner-neutral attempt records."""

    job_path = pathlib.Path(job_dir)
    if not job_path.is_dir():
        raise FileNotFoundError(f"Harbor job directory not found: {job_path}")

    attempts: list[AttemptResult] = []
    seen_by_task: dict[str, int] = defaultdict(int)
    for trial_dir, trial in _iter_trial_records(job_path):
        raw_task_name = _trial_task_name(trial, trial_dir)
        attempt_index = seen_by_task[raw_task_name]
        seen_by_task[raw_task_name] += 1

        reward, reward_detail = _extract_reward(trial, trial_dir)
        exception_info = trial.get("exception_info")
        labels = _labels_for_exception(exception_info)
        passed = exception_info is None and reward == 1.0

        attempts.append(
            AttemptResult(
                unit_id=raw_task_name,
                attempt_index=attempt_index,
                runner=RUNNER,
                passed=passed,
                reward=reward,
                trial_name=_as_str(trial.get("trial_name")) or trial_dir.name,
                trial_dir=trial_dir,
                logs_dir=trial_dir / "verifier",
                output_dir=trial_dir / "artifacts",
                elapsed_sec=_elapsed_sec(trial),
                labels=labels,
                detail={
                    "raw_task_name": raw_task_name,
                    "exception_info": exception_info,
                    "reward_source": reward_detail.get("source"),
                    "rewards": reward_detail.get("rewards"),
                },
            )
        )

    return EvalRunResult(
        track=TRACK,
        runner=RUNNER,
        attempts=tuple(attempts),
        detail={"job_dir": str(job_path), "n_attempts": len(attempts)},
    )


def score_harbor_job(
    job_dir: str | pathlib.Path,
    *,
    units_dir: str | pathlib.Path | None = None,
    n_attempts: int = 3,
    ks: tuple[int, ...] = _DEFAULT_KS,
    n_boot: int = 10_000,
    seed: int = 0,
) -> dict[str, Any]:
    """Compute official Track 1 pass@k metrics from a Harbor job directory."""

    if n_attempts <= 0:
        raise ValueError(f"n_attempts must be positive, got {n_attempts}")
    too_large = [k for k in ks if k > n_attempts]
    if too_large:
        raise ValueError(f"cannot compute k={too_large} with n_attempts={n_attempts}")

    run = load_harbor_job(job_dir)
    unit_ids, aliases = _discover_units(units_dir)
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

    # Score each task over its TRUE observed attempt count (n) and pass count (c). Do NOT pin n to
    # the requested n_attempts: padding missing/crashed trials as failures deflates pass@k, and
    # truncating surplus trials drops genuine passes and makes the score order-dependent. A task
    # that ran fewer than max(ks) trials cannot yield a valid pass@max(k) estimate, so surface it
    # loudly rather than silently mis-score it.
    max_k = max(ks)
    per_task: dict[str, dict[str, Any]] = {}
    insufficient: dict[str, int] = {}
    for unit_id in unit_ids:
        attempts = sorted(grouped.get(unit_id, ()), key=lambda a: a.attempt_index)
        n_obs = len(attempts)
        passes = [bool(a.passed) for a in attempts]
        c = sum(passes)
        if n_obs < max_k:
            insufficient[unit_id] = n_obs
        per_task[unit_id] = {
            "attempts": passes,
            "n_observed_attempts": n_obs,
            "n_passed": c,
            "n_no_reward": sum(1 for a in attempts if a.reward is None),
            "raw_task_names": sorted(
                {_as_str(a.detail.get("raw_task_name")) or a.unit_id for a in attempts}
            ),
        }

    if insufficient:
        detail = ", ".join(f"{u} ran {n}" for u, n in sorted(insufficient.items()))
        raise ValueError(
            f"incomplete Harbor job: pass@{max_k} needs >= {max_k} attempts per task, but {detail}. "
            "Re-run the missing trials, or lower ks so max(ks) <= the attempts actually run."
        )

    per_k_values: dict[str, list[float]] = {f"pass@{k}": [] for k in ks}
    for unit_id in unit_ids:
        n_obs = int(per_task[unit_id]["n_observed_attempts"])
        c = int(per_task[unit_id]["n_passed"])
        for k in ks:
            value = passk.pass_at_k(n_obs, c, k)
            per_task[unit_id][f"pass@{k}"] = value
            per_k_values[f"pass@{k}"].append(value)

    metrics: dict[str, dict[str, float]] = {}
    for name, values in per_k_values.items():
        point, lo, hi = bootstrap.bootstrap_ci(
            np.asarray(values, dtype=np.float64), n_boot=n_boot, seed=seed
        )
        metrics[name] = {"point": point, "ci_lower": lo, "ci_upper": hi}

    result: dict[str, Any] = {
        "schema_version": "2.0",
        "track": TRACK,
        "runner": RUNNER,
        "job_dir": str(pathlib.Path(job_dir)),
        "units_dir": str(pathlib.Path(units_dir)) if units_dir is not None else None,
        "n_tasks": len(unit_ids),
        "n_attempts_per_task": n_attempts,
        "primary_metric": "pass@1",
        "leaderboard_sort": {"metric": "pass@1", "order": "desc"},
        "metrics": metrics,
        "per_task": per_task,
    }
    if "pass@1" in metrics:
        result["pass_at_1"] = metrics["pass@1"]["point"]
    if "pass@3" in metrics:
        result["pass_at_3"] = metrics["pass@3"]["point"]
    return result


def write_harbor_score(
    score: dict[str, Any],
    output_path: str | pathlib.Path,
) -> None:
    """Write a Track 1 Harbor score JSON file."""

    pathlib.Path(output_path).write_text(json.dumps(score, indent=2) + "\n")


def _iter_trial_records(job_dir: pathlib.Path) -> Iterable[tuple[pathlib.Path, dict[str, Any]]]:
    root_result = job_dir / "result.json"
    seen: set[str] = set()

    if root_result.exists():
        data = _load_json(root_result)
        trial_results = data.get("trial_results")
        if isinstance(trial_results, list):
            for trial in trial_results:
                if not isinstance(trial, dict):
                    continue
                trial_name = _as_str(trial.get("trial_name"))
                trial_dir = job_dir / trial_name if trial_name else job_dir
                if trial_name:
                    seen.add(trial_name)
                yield trial_dir, trial

    for result_path in sorted(job_dir.glob("*/result.json")):
        trial_dir = result_path.parent
        if trial_dir.name in seen:
            continue
        yield trial_dir, _load_json(result_path)


def _extract_reward(
    trial: dict[str, Any],
    trial_dir: pathlib.Path,
) -> tuple[float | None, dict[str, Any]]:
    verifier_result = trial.get("verifier_result")
    if isinstance(verifier_result, dict):
        rewards = verifier_result.get("rewards")
        reward = _primary_reward(rewards)
        if reward is not None:
            return reward, {"source": "result.json", "rewards": rewards}

    reward_json = trial_dir / "verifier" / "reward.json"
    if reward_json.exists():
        rewards = _load_json(reward_json)
        return _primary_reward(rewards), {"source": str(reward_json), "rewards": rewards}

    reward_text = trial_dir / "verifier" / "reward.txt"
    if reward_text.exists():
        value = _coerce_float(reward_text.read_text().strip())
        return value, {"source": str(reward_text), "rewards": {"reward": value}}

    return None, {"source": None, "rewards": None}


def _primary_reward(rewards: Any) -> float | None:
    if isinstance(rewards, dict):
        if "reward" in rewards:
            return _coerce_float(rewards["reward"])
        numeric = [_coerce_float(value) for value in rewards.values()]
        numeric = [value for value in numeric if value is not None]
        if len(numeric) == 1:
            return numeric[0]
    return _coerce_float(rewards)


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _trial_task_name(trial: dict[str, Any], trial_dir: pathlib.Path) -> str:
    task_name = _as_str(trial.get("task_name"))
    if task_name:
        return task_name
    trial_name = _as_str(trial.get("trial_name")) or trial_dir.name
    if "__" in trial_name:
        return trial_name.split("__", 1)[0]
    return trial_name


def _labels_for_exception(exception_info: Any) -> tuple[FailureLabel, ...]:
    if not isinstance(exception_info, dict):
        return ()
    text = " ".join(
        _as_str(exception_info.get(key)) or "" for key in ("exception_type", "exception_message")
    ).lower()
    if "timeout" in text or "timed out" in text:
        return (FailureLabel.RESOURCE_TIMEOUT,)
    if "oom" in text or "out of memory" in text or "memoryerror" in text:
        return (FailureLabel.RESOURCE_OOM,)
    return ()


def _elapsed_sec(trial: dict[str, Any]) -> float | None:
    started = _parse_dt(_as_str(trial.get("started_at")))
    finished = _parse_dt(_as_str(trial.get("finished_at")))
    if started is None or finished is None:
        return None
    return (finished - started).total_seconds()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _discover_units(
    units_dir: str | pathlib.Path | None,
) -> tuple[list[str], dict[str, str]]:
    if units_dir is None:
        return [], {}
    root = pathlib.Path(units_dir)
    if not root.exists():
        raise FileNotFoundError(f"units directory not found: {root}")

    unit_ids: list[str] = []
    aliases: dict[str, str] = {}
    task_dirs = (
        [root] if (root / "task.toml").exists() else sorted(p for p in root.iterdir() if p.is_dir())
    )
    for unit_dir in task_dirs:
        canonical = _qfbench_unit_id(unit_dir) or unit_dir.name
        if canonical not in unit_ids:
            unit_ids.append(canonical)
        for alias in _unit_aliases(unit_dir, canonical):
            aliases[alias] = canonical
    return unit_ids, aliases


def _qfbench_unit_id(unit_dir: pathlib.Path) -> str | None:
    card_path = unit_dir / "card.toml"
    if not card_path.exists():
        return None
    with card_path.open("rb") as fh:
        card = _toml.load(fh)
    task = card.get("task")
    if isinstance(task, dict):
        return _as_str(task.get("id"))
    return None


def _unit_aliases(unit_dir: pathlib.Path, canonical: str) -> set[str]:
    aliases = {canonical, unit_dir.name}
    task_path = unit_dir / "task.toml"
    if task_path.exists():
        with task_path.open("rb") as fh:
            task_toml = _toml.load(fh)
        task = task_toml.get("task")
        if isinstance(task, dict):
            harbor_name = _as_str(task.get("name"))
            if harbor_name:
                aliases.add(harbor_name)
                aliases.add(harbor_name.rsplit("/", 1)[-1])
    return aliases


def _canonical_unit_id(raw_name: str, aliases: dict[str, str]) -> str:
    if raw_name in aliases:
        return aliases[raw_name]
    short = raw_name.rsplit("/", 1)[-1]
    return aliases.get(short, short)


def _load_json(path: pathlib.Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object in {path}")
    return data


def _as_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _json_default(value: Any) -> Any:
    if isinstance(value, pathlib.Path):
        return str(value)
    if isinstance(value, FailureLabel):
        return value.value
    raise TypeError(f"cannot serialize {type(value).__name__}")


def normalized_attempts_json(run: EvalRunResult) -> list[dict[str, Any]]:
    """Return JSON-safe normalized attempts for diagnostics and tests."""

    return [json.loads(json.dumps(asdict(a), default=_json_default)) for a in run.attempts]
