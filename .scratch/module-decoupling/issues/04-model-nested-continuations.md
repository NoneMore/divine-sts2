# 04: Model Card-select prompts with typed continuations

**What to build:** Replace pending-choice side fields with a single active Card-select prompt carrying
an in-memory typed continuation to its suspended parent. Nested reward continuations use the same model.

**Blocked by:** 03.

**Status:** resolved

- [x] A prompt is the sole active state; its parent is suspended, not simultaneously active.
- [x] Resolving a prompt can reach another prompt, its parent, map, combat or terminal state.
- [x] Native tasks, selectors and completion sources remain inside the production adapter.
- [x] Option picks retain their existing external behaviour.
- [x] Restore still uses recipe/history replay; continuations are not serialized.

## Answer

`CompatibilityActiveRunSession` now owns exactly one member of a closed active-state model. A
Card-select prompt replaces the ordinary decision while it is active and carries an in-memory
`RunContinuation<CardSelection>`; custom and nested reward prompts use the same shape with a typed
`RewardSelection`. Resolving either prompt asks the semantic native adapter to continue and then
classifies the one resulting frame, so it can become another prompt, return to its parent flow, or
reach map, combat, or terminal state. Option picks remain ordinary adapter decisions and retain their
action identity and parameters.

The prompt continuation captures a `SuspendedNativeDecision` and resumes it through the typed
`ResumeCardSelectAsync(CardSelection)` or `ResumeRewardAsync(RewardSelection)` adapter operation.
The scripted adapter routes on the typed payload and records it for seam assertions; prompt
resolution does not fall back to the ordinary `ApplyAsync(actionId)` path.

Each suspended decision also carries an opaque, in-memory `PromptResumeToken` for its exact native
parent. The production adapter validates that token and dispatches the typed selection directly to
the native choice/reward continuation; the action id is retained only as the existing history and
transition identity. Nested rewards restore the enclosing parent's original marker after the inner
prompt resolves. Replay builds fresh marker objects, so no continuation identity enters a checkpoint.

Native tasks, selectors, reflected objects, and completion sources remain behind
`LegacyRunSessionAdapter` in `PersistentNativeCombatEnvironment`; none enter the active-state model.
Coordinator checkpoints still contain only the adapter's opaque recipe/history checkpoint. Restore
replays that checkpoint and creates a fresh typed continuation from the resulting prompt frame rather
than serializing a continuation.

Offline coordinator tests cover sole-active prompt behaviour, prompt target states, nested reward
suspension/resumption, option-pick compatibility, and choosing a different branch after restoring a
prompt checkpoint. The shipped-game Ancient sweep also passes for all 111 choices across 37 seeds,
including Card-select prompts, option picks, depth-two reward nesting, skipping nested rewards, and
restoring the resolved-choice branch to the same state hash.
