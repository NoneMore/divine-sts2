# 11: Split scenario generation and corpus orchestration

**What to build:** Replace the monolithic scenario file with model, generation, corpus, driver, codec
and store implementation modules while preserving its two public generation interfaces and the new
materialization interface.

**Blocked by:** 10.

**Status:** ready-for-agent

- [ ] `generate_rows` remains independently usable by parity and acceptance callers.
- [ ] `generate_corpus` retains deterministic sharding, resume, worker replacement and atomic byte-identical output.
- [ ] Request validation still precedes worker startup and writes; failure rows are never silently dropped.
- [ ] `read_scenario_corpus` precisely names the supported format; `read_corpus` remains a compatibility alias.
- [ ] Model/driver/codec/store files remain implementation, not new public interfaces.
