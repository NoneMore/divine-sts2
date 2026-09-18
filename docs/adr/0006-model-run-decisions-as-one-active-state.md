---
status: accepted
---

# Model run decisions as one active state

The headless environment will replace its run-stage and mode-flag combinations with one closed active-state union behind an internal session interface that exposes only the current decision frame and applying an action ID. Legal actions, action execution, observation capture, nested prompt continuation, and transition to the next stable decision belong behind this seam; branch history, RPC envelopes, and timing remain with the coordinator. An all-purpose session command bus was rejected as too broad, while an open room-driver registry was rejected because the shipped game's state set is closed and exhaustive checking is more valuable than hypothetical plugin extensibility.

Each decision frame atomically projects its observation, legal actions, terminal status, and compatibility kernel data; the coordinator continues to compute the existing state hash and protocol result. Applying an action validates its ID against the frame's hidden executor table before any native mutation. A nested Card-select prompt becomes the sole active state and carries an in-memory typed continuation to its suspended parent; continuations are not serialized, and branch restore keeps replaying the reset recipe and action history against an expected hash. Shipped-game reflection sits behind an internal semantic command/query port with production and scripted-fake adapters, so reflection objects, Harmony callbacks, native tasks, and selectors never enter the run-decision interface.
