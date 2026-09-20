# 13: Share protocol models behind host wire adapters

**What to build:** Make Protocol own the internal request, response, error and legal-action model while
headless and FullAppBridge adapters continue to read and write their existing JSON dialects.

**Blocked by:** 09, 12.

**Status:** resolved

- [x] Both hosts translate through one internal semantic model.
- [x] Existing request ids, envelopes, field names, error shapes and method behaviour remain compatible.
- [x] Internal legal actions use one vocabulary; legacy codecs map it without leaking dialects to callers.
- [x] Error responses preserve correlation with their requests.
- [x] No codec guesses a dialect from incidental field types.

## Answer

`Sts2.NativeSim.Protocol` now owns the request, response, structured error and legal-action records
used by every host. The pure .NET and Godot headless loops share one explicit headless wire adapter;
FullAppBridge removed its duplicate RPC and legal-action DTOs and routes its server and state tracker
through the same semantic records.

Each adapter retains its published dialect deliberately: headless writes string request ids,
`ok/result/error`, and `kind/parameters`, while FullAppBridge writes integer ids, its result-or-string-
error envelope, and `action_type/description/metadata`. Adapter selection is explicit and neither
codec infers a dialect from payload member types. FullAppBridge failures now retain the decoded
request id instead of replacing it with zero.

Five protocol interface tests pin both envelopes, both legacy integer parameter forms, and the two
encodings of one semantic legal action. All 48 .NET tests, all 221 offline Python tests, the Debug
pure .NET/Godot builds, and the public-tree
gate pass.
