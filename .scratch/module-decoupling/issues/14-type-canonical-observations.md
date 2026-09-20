# 14: Type the canonical observation contract

**What to build:** Define canonical observation records in Protocol, generate the JSON Schema from them,
and adapt headless, FullAppBridge and trace paths to encode their runtime state into that contract.

**Blocked by:** 13.

**Status:** resolved

- [x] One typed record family defines every published run-stage variant.
- [x] The generated schema and runtime captures validate against the same records.
- [x] Each host retains its runtime-specific encoder adapter.
- [x] Python validates and consumes the contract rather than redefining its field tree.
- [x] Parity reports field paths; host-specific hashes remain intentionally separate.
- [x] The Combat episode facade retains a compatible observation projection for research callers.

## Answer

`Sts2.NativeSim.Protocol` now owns the canonical observation records, including a closed family for
combat, map, reward, rest, event, treasure, shop, room-reward, custom-reward and run-only stages. A
Protocol-side generator publishes `schemas/canonical-state.schema.json`; contract tests require every
recorded capture to deserialize through the same types and require the checked-in schema to equal the
generated document.

Headless, FullAppBridge and TraceExporter retain explicit runtime adapters. FullAppBridge projects its
combat and non-combat DTOs without replacing its legacy wire DTO or state hash, while headless keeps
its transition-kernel hash separate. Python loads record fields from the generated schema for parity,
reports differences by canonical JSON path, and validates observations at the Combat episode boundary
without defining a second observation tree.
