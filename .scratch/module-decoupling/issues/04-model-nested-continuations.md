# 04: Model Card-select prompts with typed continuations

**What to build:** Replace pending-choice side fields with a single active Card-select prompt carrying
an in-memory typed continuation to its suspended parent. Nested reward continuations use the same model.

**Blocked by:** 03.

**Status:** ready-for-agent

- [ ] A prompt is the sole active state; its parent is suspended, not simultaneously active.
- [ ] Resolving a prompt can reach another prompt, its parent, map, combat or terminal state.
- [ ] Native tasks, selectors and completion sources remain inside the production adapter.
- [ ] Option picks retain their existing external behaviour.
- [ ] Restore still uses recipe/history replay; continuations are not serialized.
