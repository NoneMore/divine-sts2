# 11: Split scenario generation and corpus orchestration

**What to build:** Replace the monolithic scenario file with model, generation, corpus, driver, codec
and store implementation modules while preserving its two public generation interfaces and the new
materialization interface.

**Blocked by:** 10.

**Status:** resolved

- [x] `generate_rows` remains independently usable by parity and acceptance callers.
- [x] `generate_corpus` retains deterministic sharding, resume, worker replacement and atomic byte-identical output.
- [x] Request validation still precedes worker startup and writes; failure rows are never silently dropped.
- [x] `read_scenario_corpus` precisely names the supported format; `read_corpus` remains a compatibility alias.
- [x] Model/driver/codec/store files remain implementation, not new public interfaces.

## Answer

`sts2_native_sim.scenarios` is now a stable public facade over private model, generation, corpus,
driver, codec and store modules. Existing generation and materialization imports remain available;
the facade also preserves its replaceable default `NativeWorker` seam for CLI and acceptance callers.

`read_scenario_corpus` names the Generated scenario JSONL/gzip corpus reader, while `read_corpus` is
the same callable as a compatibility alias. Existing scenario tests continue to cover validation
before worker startup, failure rows, deterministic shard layout, resume and worker replacement, and
byte-identical atomic output.
