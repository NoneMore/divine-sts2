---
status: accepted
---

# Share protocol models while keeping host adapters

The headless simulator and FullAppBridge will share one internal request, response, error, and legal-action model while retaining adapters for their existing wire encodings, so structural work does not silently break either external JSON contract. A future single wire dialect requires an explicit protocol version and deprecation plan; inferring a dialect from field types is rejected. This concentrates protocol semantics without coupling unlike transports or preserving two complete implementations.

Canonical observation records belong to `Sts2.NativeSim.Protocol`, with each host retaining an encoder adapter for its runtime environment and the published JSON Schema derived from those records. Parity compares the resulting canonical fields path by path rather than requiring one encoder implementation or a shared state hash: the headless hash also protects its transition kernel, which has no FullAppBridge counterpart. Hand-written schemas, anonymous Core projections, and Python parity code are therefore not competing definitions of the observation contract.
