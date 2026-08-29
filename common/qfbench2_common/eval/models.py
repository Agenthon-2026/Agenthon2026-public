"""Executive summary (read this first): runner-neutral eval result records.

Adapters translate runner-specific artifacts into these small dataclasses. Shared scoring code can
then work over attempts without importing the runner that produced them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from qfbench2_common.failure_labels import FailureLabel


@dataclass(frozen=True)
class AttemptResult:
    """One scored attempt for one evaluation unit."""

    unit_id: str
    attempt_index: int
    runner: str
    passed: bool
    reward: float | None = None
    trial_name: str | None = None
    trial_dir: Path | None = None
    output_dir: Path | None = None
    logs_dir: Path | None = None
    elapsed_sec: float | None = None
    labels: tuple[FailureLabel, ...] = ()
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvalRunResult:
    """A normalized eval run produced by one runner."""

    track: str
    runner: str
    attempts: tuple[AttemptResult, ...]
    detail: dict[str, Any] = field(default_factory=dict)
