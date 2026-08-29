"""Hierarchical verifier: admissibility gates -> score.

Gates run in order; a submission is admissible iff ALL gates pass. Only then is the
track scorer invoked. Gate ordering is the published contract:

    g0_integrity        manifest checksums OK, image hash logged, interface_version==2.0
    g1_schema           output validates against the track output schema
    g2_cutoff_resource  closed-resource respected; data cutoff / wall-clock / memory OK
    g3_domain_semantics  track-specific admissibility (invariants / calibration /
                         semantic-regression+stylized-facts / faithfulness+embargo)

This is the single contract behind all four tracks; each track supplies its own g3 and
scorer but reuses g0-g2 verbatim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .failure_labels import FailureLabel


@dataclass
class GateResult:
    passed: bool
    label: FailureLabel | None = None
    detail: dict = field(default_factory=dict)


@dataclass
class Verdict:
    admissible: bool
    gate_results: dict[str, GateResult]
    labels: list[FailureLabel]
    score: float | None
    detail: dict = field(default_factory=dict)


Gate = Callable[[dict], GateResult]  # ctx -> GateResult
Scorer = Callable[[dict], dict]  # ctx -> {'score': float, ...}


class HierarchicalVerifier:
    def __init__(self, gates: list[tuple[str, Gate]], scorer: Scorer) -> None:
        self._gates = gates
        self._scorer = scorer

    def run(self, ctx: dict) -> Verdict:
        results: dict[str, GateResult] = {}
        labels: list[FailureLabel] = []
        for name, gate in self._gates:
            res = gate(ctx)
            results[name] = res
            if not res.passed:
                if res.label:
                    labels.append(res.label)
                return Verdict(
                    admissible=False,
                    gate_results=results,
                    labels=labels,
                    score=None,
                    detail=res.detail,
                )
        # All gates passed. A passing gate may still attach a *diagnostic* label (e.g. the T1 DI
        # overlay run with di_label_only=True, which classifies the root cause of an admissible-
        # but-imperfect attempt). Surface those so the cross-track failure map is actually written —
        # previously labels were collected only on failure, so the DI overlay produced nothing.
        labels.extend(res.label for res in results.values() if res.passed and res.label is not None)
        scored = self._scorer(ctx)
        return Verdict(
            admissible=True,
            gate_results=results,
            labels=labels,
            score=scored.get("score"),
            detail=scored,
        )
