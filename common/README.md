# qfbench2-common — shared evaluation harness (Agenthon 2026 / QFBench 2.0)

Every track repo **pip-installs** this package from this repository at a pinned tag, so the
dev-phase smoke test and the final-phase sealed scorer run *identical* code. It is the single
point that makes four heterogeneous tracks reproducible under one protocol.

```bash
pip install "qfbench2-common @ git+https://github.com/Agenthon-2026/Agenthon2026-public.git@v2.3.1#subdirectory=common"
```

There is no git submodule. Pin the tag: installing from a moving branch means your local result
and the scored result can diverge without either being wrong.

```
qfbench2_common/
  taskcard.py        parse + JSON-schema-validate card.toml (task-card v2)
  manifest.py        per-file sha256 + public-safety enforcement (no solutions in public)
  leakage.py         cutoff / embargo / network-mode (none|restricted) / canary scanning
  verifier.py        HierarchicalVerifier: g0 integrity -> g1 schema -> g2 cutoff/resource -> g3 domain
  failure_labels.py  cross-track failure-mode taxonomy + JSONL reporter
  smoke.py           public smoke-test CLI (qfbench2-smoke)
  eval/              runner-neutral eval-result dataclasses
  track1/
    harbor.py        Track-1 Harbor adapter: launch, parse job artifacts, pass@k over the true observed attempts
  scoring/
    passk.py          T1 unbiased pass@k (Chen et al. 2021)
    crps.py           T2 CRPS composite (Gneiting & Raftery 2007; Scheuerer & Hamill 2015)
    stylized_facts.py T3 KS/ACF/Hill/depth divergences + admissibility (Cont 2001; Hill 1975)
    faithfulness.py   T4 NLI citation gate + analysis composite (Laurer et al. 2024)
    bootstrap.py      cluster bootstrap CIs (reported for every leaderboard number)
  schemas/           taskcard, manifest, submission, forecast, analysis, sim_scenario (JSON Schema 2020-12)
```

**Contracts a track repo must honor:** ship one `card.toml` (v2) + `manifest.json` per unit;
expose `qfbench2_track_<track>.scoring.build_verifier(ctx)` returning a `HierarchicalVerifier`;
keep all ground-truth artifacts out of the public repo (`manifest.assert_public_safe` is wired
into public CI).

Quickstart — run from the root of a **track kit**, not from this repository:
```bash
pip install -e "./common[data,dev]"      # quote the extras: zsh globs the brackets
pip install -e .                         # the track kit itself: provides qfbench2_track_<track>
qfbench2-smoke units/<unit> ./my_output --track <track>
```

> `qfbench2-smoke` imports `qfbench2_track_<track>.scoring` from the track repo. Installed
> alone, this toolkit cannot run it: the command exits non-zero with
> `ModuleNotFoundError: No module named 'qfbench2_track_<track>'`. Install the track kit (or
> set `PYTHONPATH` to the kit root) first.

The unified `qfbench2` CLI exposes `smoke`, `card`, `manifest`, `eval`, `track1` and `track4`. The `track1`
group (`harbor-run` / `score-harbor-job`) drives the Track-1 **Harbor adapter** and needs the
optional `harbor` extra (`harbor>=0.15.0`, whose **Python ≥ 3.12** floor is already met by the
toolkit's **Python ≥ 3.13**). Harbor is shelled out (never imported), so `qfbench2_common` imports
and runs on 3.13 with Harbor absent:
```bash
# operator-only; enables qfbench2 track1 ...
pip install "qfbench2-common[harbor] @ git+https://github.com/Agenthon-2026/Agenthon2026-public.git@v2.3.1#subdirectory=common"
```
