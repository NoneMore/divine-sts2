# Reusing the Ancient offer's native state handle

**Measured 2026-09-24.** The generator now keeps the `state_handle` returned by the
`run_step` that enters Neow and restores that handle before each later Ancient choice.
Previously it made an additional `fork` RPC after reading the offer. Native `run_step`
already captures the branch checkpoint; the extra `fork` refreshed that checkpoint
without advancing the run. The change removes one fork RPC per scenario generation
element. It does not remove a reset, restore, or step.

## Native differential regression

[`scenario_handle_reuse_acceptance.py`](../../tests/acceptance/scenario_handle_reuse_acceptance.py)
compares the public `generate_rows` interface with a test-only reference that performs
the former native fork after entering Neow. Both paths use real Godot-hosted workers
on the same shipped-game build. Six fixed elements span IRONCLAD and DEFECT,
Ascensions 0 and 2, both act variants, canonical and rewritten seeds, and every
offered Ancient choice. The 18 scenario rows matched as complete Python records and
as encoded JSONL bytes. Covered nested decisions were `card_choice`,
`custom_reward_choice`, and `option_choice`.

| Six-element native regression | Fork reference | Reused handle |
| --- | ---: | ---: |
| Successful rows | 18 | 18 |
| `run_reset` RPCs | 6 | 6 |
| `restore` RPCs | 12 | 12 |
| `run_step` RPCs | 69 | 69 |
| `fork` RPCs | 6 | 0 |

The reference's fork occurs immediately after the Ancient-entry step. The previous
driver read the offer first, then forked; reading the offer is Python-only and does
not mutate native state. The existing
[`scenario_record_acceptance.py`](../../tests/acceptance/scenario_record_acceptance.py)
independently replays recorded recipes from fresh resets against the shipped game.
The removed fork's own failure path is intentionally outside the equality contract;
other failure rows remain governed by the offline scenario tests.

## Three-round same-host benchmark

[`benchmark_scenario_generation.py`](../../python/tools/benchmark_scenario_generation.py)
uses `IRONCLAD` at Ascension 0 with seeds `A1B2C3D4E5`, `1`, `2`, and `3`: 12
successful rows and no failures per run. It times Python-side RPC wall time with
`time.perf_counter()` around `worker.request`, plus the outer generation wall time.
Each hot-path mode starts a fresh worker; corpus runs start fresh workers and write
new gzip shards. The two modes alternate order across three rounds. All runs used
Python 3.13.5 and shipped assembly SHA-256
`A1F9E653F1E28E4076558FEE1E60D218619CB7E057B887C6417F62C62C6D7A52`
with PCK SHA-256
`42520EB8B0911C6C0F0BD102D92B33F41ABD4D26B83489817D0A6DBD7DD48587`.

| Hot worker, 12 rows | Fork reference median (range) | Reused handle median (range) |
| --- | ---: | ---: |
| Generation wall time | 4.127 s (4.060–4.893) | 4.049 s (3.901–4.177) |
| Rows/sec, excluding startup | 2.908 (2.452–2.956) | 2.963 (2.873–3.076) |
| 4 `run_reset` RPCs | 1.209 s (1.134–1.388) | 1.139 s (1.122–1.142) |
| 8 `restore` RPCs | 1.728 s (1.719–2.095) | 1.715 s (1.597–1.802) |
| 49 `run_step` RPCs | 1.199 s (1.182–1.401) | 1.187 s (1.176–1.229) |
| `fork` RPCs | 4; 0.00151 s (0.00142–0.00190) | 0; 0 s |

| Fresh compressed corpus, 12 rows | Fork reference wall / rows/sec | Reused handle wall / rows/sec |
| --- | ---: | ---: |
| 1 worker | 6.662 s / 1.801 | 6.578 s / 1.824 |
| 2 workers | 5.841 s / 2.054 | 5.843 s / 2.054 |
| 4 workers | 5.975 s / 2.008 | 5.534 s / 2.169 |

Corpus table values are three-round medians. Every corpus run wrote 12 successes,
0 failures, and 0 worker replacements. For each worker count and round, the old
and new corpus summaries and compressed shards were byte-identical: 9 pairs.
The benchmark now asserts that property outside the timed region.

The hot-path median changes by about 1.9%, while the removed four fork RPCs total
only about 1.5 ms. Reset, restore, step, worker startup, and system variation
dominate this small request. The observed corpus differences vary by worker count
and round, so these measurements quantify the cost but do not establish a stable
end-to-end speedup. The raw measurements are in the gitignored
`artifacts/scenario-performance/results-handle-reuse-20260924.json`; rerun with a
fresh label, for example:

```powershell
pwsh -NoProfile -Command '. ./scripts/common.ps1; & ./.venv/Scripts/python.exe python/tools/benchmark_scenario_generation.py another-label --rounds 3 --legacy-comparison'
```

The earlier [performance investigation](act1-first-combat-scenario-generator-performance.md)
measured a previous generator revision that reset once per Ancient choice. The
current pre-optimization path already reset once per element and restored the
offered state for later choices; its only redundant RPC here was `fork`.
