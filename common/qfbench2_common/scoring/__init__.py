"""QFBench 2.0 scoring primitives.

Each track's headline metric is implemented here so the public smoke scorer and the
private sealed scorer import *identical* code (no drift between dev and final).

    T1  passk            pass@1 / pass@3 (unbiased, Chen et al. 2021)
    T2  crps             CRPS composite (Gneiting & Raftery 2007; Scheuerer & Hamill 2015)
    T3  stylized_facts   stylized-fact divergences + admissibility (Cont 2001; Hill 1975)
    T4  faithfulness     NLI citation-faithfulness gate + analysis composite (Laurer et al. 2024)
    T4  factor_replication  factor-replication composite for code-execution units
                            (Chen & Zimmermann 2022; Jensen, Kelly & Pedersen 2023)
    *   bootstrap        cluster bootstrap CIs reported for every leaderboard number
"""

from __future__ import annotations

from . import bootstrap, crps, factor_replication, faithfulness, passk, stylized_facts

__all__ = ["passk", "crps", "stylized_facts", "faithfulness", "factor_replication", "bootstrap"]
