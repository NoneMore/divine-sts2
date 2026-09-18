# 14: Type the canonical observation contract

**What to build:** Define canonical observation records in Protocol, generate the JSON Schema from them,
and adapt headless, FullAppBridge and trace paths to encode their runtime state into that contract.

**Blocked by:** 13.

**Status:** ready-for-agent

- [ ] One typed record family defines every published run-stage variant.
- [ ] The generated schema and runtime captures validate against the same records.
- [ ] Each host retains its runtime-specific encoder adapter.
- [ ] Python validates and consumes the contract rather than redefining its field tree.
- [ ] Parity reports field paths; host-specific hashes remain intentionally separate.
- [ ] The Combat episode facade retains a compatible observation projection for research callers.
