# 13: Share protocol models behind host wire adapters

**What to build:** Make Protocol own the internal request, response, error and legal-action model while
headless and FullAppBridge adapters continue to read and write their existing JSON dialects.

**Blocked by:** 09, 12.

**Status:** ready-for-agent

- [ ] Both hosts translate through one internal semantic model.
- [ ] Existing request ids, envelopes, field names, error shapes and method behaviour remain compatible.
- [ ] Internal legal actions use one vocabulary; legacy codecs map it without leaking dialects to callers.
- [ ] Error responses preserve correlation with their requests.
- [ ] No codec guesses a dialect from incidental field types.
