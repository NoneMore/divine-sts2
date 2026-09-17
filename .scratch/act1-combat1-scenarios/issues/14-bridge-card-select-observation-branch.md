# 14: The bridge can observe the card-select prompt it currently drops

**What to build:** One of the shipped card-select prompts produces no observation branch at all — no room and no legal actions — even though the bridge is waiting for a decision, so a shipped run that reaches it cannot be advanced by the oracle. Several Ancient choices open exactly that prompt, which bounds what a parity campaign can honestly claim. The bridge projects that prompt like every other decision: a room a caller can recognise, and legal actions that name the cards on offer, so a caller selects one by identity and the run continues.

**Blocked by:** None (can start immediately).

**Status:** done

- [x] A shipped run that reaches this card-select prompt reports a room for it rather than no room at all.
- [x] The prompt's legal actions name the cards on offer, so a caller selects one by identity rather than guessing an index.
- [x] Selecting one of the offered cards advances the shipped run past the prompt.
- [x] The prompt and its resolution are observed end to end in a bridged run, not only inferred from static reading.
- [x] The other card-select prompt the bridge already handles is unchanged.

## Comments

**2026-09-17 — implemented.**

- **The static reading was right about the symptom and wrong about the cause, and the difference
  mattered.** `FullAppStateTracker` dispatches its stage blocks on the same word the handler handed
  it, and `RunSimpleCardSelectLoopAsync` was the one handler that handed a word with no block:
  `simple_card_select` fell through the if-chain, so a caller standing there got `room: null` and an
  empty action list. But the *reachability* was the deeper problem, and the ticket's premise — "the
  bridge is waiting for a decision" — turned out not to hold for the shipped run at all. Surveying
  the game's own command shows why: every one of the thirteen card-selection entry points in
  `CardSelectCmd` consults `CardSelectCmd.Selector` before it would push a screen, and the shipped
  autoplay installs its own random selector at run start. Two headless bridge runs say what that
  means in practice, in the run's own log: on `TRACERBULLET` (first Ancient choice
  `PRECISE_SCISSORS`) the removal was answered with `Auto-selected 1 card(s) for selection prompt`
  and never reached a screen or the bridge; on `GYMSCENAR10` (second choice `SCROLL_BOXES`) the bundle
  screen appeared and the autoplay's own handler answered it (`Handling screen:
  NChooseABundleSelectionScreen`, then `Action: Selecting card bundle`). So **both** card-select
  screens the bridge patches are dead in a bridged run, and the prompt the ticket is about was being
  resolved before any bridge stage existed. Adding the missing block alone would have been dead code
  and would have failed the ticket's own end-to-end item.
- **The repair is at the seam the game actually asks.** `FullAppBridgeMod` now prefixes
  `CardSelectCmd.UseSelector` and wraps whatever the autoplay installed in `BridgeCardSelector`,
  which routes `GetSelectedCards` to `FullAppBridgeServer.CoordinateCardChoiceAsync` and leaves
  `GetSelectedCardReward` with the wrapped selector — a card *reward* is the rewards stage's decision,
  and a second stage claiming it would describe one situation twice. One seam now covers the removal,
  upgrade, transform, discard and choose-a-card prompts that six of the act-1 Ancient's offered relics
  open (and the in-combat selections a card effect opens), which is what the ticket meant by "several
  Ancient choices". The offered cards are reported as `CardSelectPrompt` — the cards, the range the
  game asked for, and what the caller has already chosen — so the prompt is described once no matter
  which seam reported it, and the snapshot gained the `simple_card_select` stage block it was missing:
  room type `SimpleCardSelect`, `options` naming each offered card, one
  `choose_card_select:{index}:{model id}` action per card with `card_index`/`card_id` beside it, and
  `details` carrying `min_select`, `max_select` and `selected`.
- **`CoordinateCardChoiceAsync` resolves the caller's card by the identity the action names**, which
  is the ticket's "by identity rather than guessing an index": the model id decides, the position is
  honoured only when it agrees with the model, and an action naming a card the prompt does not offer
  fails loudly instead of selecting something else. A prompt that wants more than one card is reported
  again with the chosen ones removed and named as already selected, until the prompt's own minimum is
  met, so the set the game is handed is a legal one.
- **A second defect surfaced while wiring it, and it is why the prompt is answerable at all.** A
  room's loop re-reports the room while a prompt an effect inside it opened is still open — the
  Ancient's event loop re-reports the room roughly 50 ms after the choice, while the relic's own
  pick-up is blocked on the card selection. With two boundaries live at once, the caller's action
  completed whichever had published last, so any caller that took longer than that 50 ms to answer a
  card prompt would have had its answer delivered to the event room and left the game blocked on the
  prompt. `WaitForCoordinatorActionAsync` now holds a `BoundaryGate`, so one decision is live at a
  time and whoever published is who receives the answer. That is a change to the bridge's handshake
  rather than to this prompt, and it is the smallest one that makes the ticket's third item true
  rather than usually true.
- **The vocabulary table follows the code.** `python/sts2_native_sim/decision_vocabulary.py` lost
  `card_choice` from the `combat` and `card_reward` rows — a card select no longer surfaces under an
  ambient stage, it reports `simple_card_select` — and the `simple_card_select` row's comment now says
  what the word means and where its observation lives. The row keeps `option_choice`, and the `combat`
  row keeps it too, because a bundle or relic *option* pick has no selector branch in the shipped game
  and therefore still arrives under the ambient stage. The screen stages (`deck_upgrade`,
  `deck_card_select`) keep their rows and their branches untouched: this ticket changed neither.
- **Observed with the shipped game** (assembly `A1F9E653…`) by the new
  `python/bridge_card_select_acceptance.py`, four headless workers: three prompts and the bundle
  bound. `TRACERBULLET` (`DEFECT`, Ascension 0, first Ancient choice `PRECISE_SCISSORS`, canonical
  seed reported as `TRACERBULLET`): prompt at stage `simple_card_select`, room `SimpleCardSelect`, the
  deck's ten cards offered in deck order, ten card-naming actions,
  `{min_select: 1, max_select: 1, selected: []}`; selecting
  `choose_card_select:0:STRIKE_DEFECT` cost the deck exactly that card (10 → 9, three `STRIKE_DEFECT`
  left), stages `event → simple_card_select → event → map`, prompt state hash
  `AAFDCB93B88451C7A7CB75BE184F051BF889C1B30347B5F4B786E6F155B85726`. `ANC1ENT01` (`IRONCLAD`,
  Ascension 0, third choice `PRECARIOUS_SHEARS`) asks for **two** cards: `{min_select: 2,
  max_select: 2}` over the same ten, the second report offering the remaining nine with
  `selected: [STRIKE_IRONCLAD]`, the two selections costing the deck 10 → 8 with three
  `STRIKE_IRONCLAD` left, prompt state hash
  `7E1F39AB70A879E6807083B4260D0C1FC522FAEEF5A89271A9AF323D986F070B`. `ANCIENT01` (`IRONCLAD`,
  Ascension 0, third choice `HEFTY_TABLET` on this build — the raw seed is not canonical, so the
  shipped game offers its own choices) asks for a card to *add* with a minimum of **zero**:
  `{min_select: 0, max_select: 1}` over `[DEMON_FORM, FEED, MANGLE]`, the three card actions plus
  `finish_card_select`; answering with the finish action advanced the run with an empty selection, the
  deck gaining only the `Injury` that relic adds regardless (10 → 11) and none of the three offered
  cards, prompt state hash
  `02FD391C88F2A808A03FFD909FDAF992B5E5C47E68A3774BC4A0F2F0C5A0465E`. All three reached the map,
  so the prompts and their resolutions are measured rather than inferred. The acceptance also records
  the bound the ticket leaves behind: `GYMSCENAR10`'s `SCROLL_BOXES` drive sees only the `event`
  stage, `bundle_stage_reported` false, with the relic granted — the bundle pick is answered
  off-bridge, so ticket 15's sample must name `option_choice` as a kind it cannot drive.
- **The already-handled path is unchanged, and the evidence is stated for what it is.** The
  `python/bridge_combat_observation_acceptance.py` control run, on the same build and after the
  boundary gate, reproduces the state hashes recorded for schema version 6 byte for byte —
  `8C6638C1768F703CE36E9BCF4DB6400EDCF28F0E9A899E29D2CA2B7991A5401F` at the first fight and
  `37F1CB880C8EE96CAEDD2D0529CA3649363779FDA52B1A8C534BB48B9D63717E` on the turn a power is
  reported. What that shows is that the observations of a run that never meets a card prompt did not
  move; it does not show anything about `deck_card_select`, whose screen the autoplay's selector
  pre-empts before and after this ticket alike. Its handler is untouched, and its stage block reports
  through the same helper the new stage uses, so its behaviour is unchanged.
- **Offline, four pins state the properties the runtime run measures.** `test_decision_vocabulary.py`
  gained the invariant behind the symptom: every phase word the bridge hands the snapshot builder has
  a stage block dispatching on it (`bridge_emitted_phase_words() - bridge_dispatched_phase_words()` is
  empty), read from every bridge source so an emission cannot hide in one. `test_bridge_observation_shape.py`
  gained three: both card-select stages name the offered cards in the room and in the action that
  selects each one, through one shared shape; the multi-card prompt reports its range and offers the
  finish action exactly while the game allows it; and the bridge takes the game's card selector as a
  required patch (`nameof(CardSelectCmd.UseSelector)`, `BridgeCardSelector` present,
  `GetSelectedCards` routed to the coordinator, `GetSelectedCardReward` left with the wrapped
  selector, a prompt with no client deferred) — without which the stage is unreachable.
- **Deliberately not in this ticket.** The bundle and relic *option* picks, which need their own seam
  (`FromChooseABundleScreen` consults no selector, and `RelicSelectCmd.FromChooseARelicScreen` is the
  same kind). The screen stages, whose handlers and blocks stay as they are even though the autoplay's
  selector now pre-empts them — making those screens reachable would mean suspending the selector, and
  the game's own `NChooseACardSelectionScreen`, `NDeckTransformSelectScreen` and
  `NDeckEnchantSelectScreen` have no bridge handler at all, which is a larger change than this
  ticket's. The bridge's `schema_version` stays 6: no DTO member was added, removed or reworded, so no
  recorded bridge hash moved, and the one new stage reports through members that were already there.
  Nothing here maps a bridge stage onto a simulator decision kind *for a comparison* or compares two
  projections field by field — that remains ticket 15, whose sample can now cover `card_choice`.

**2026-09-17 — two-axis review, and what it changed.** Standards and Spec were reviewed in parallel
against `HEAD`; both axes could read the diff but neither could run the shipped-game acceptance (the
sandbox refuses the hard link onto the game's volume), so this entry is what the review produced and
what was done about it.

- **Two hard findings, both in the new tests and the new patch.** (1) The offline invariant added here
  read emission sites from `FullAppBridgeMod.cs` alone while the new emission lives in
  `FullAppBridgeServer.cs`, so the check the ticket's symptom needed would have gone blind the moment
  an emission moved — it now reads every bridge source. (2) The selector seam was patched with a
  string method name through `TryPatchPrefix`, which patches nothing and logs nothing when a target is
  missing, so a game rename would have deleted the seam silently; it now goes through
  `PatchRequiredPrefix` with `nameof`, which fails loudly instead. That second one is the
  `docs/architecture-review.md` candidate-9 class of defect, and the reasoning is a comment at the
  call site.
- **Both axes found the same real defect in the new code, and it took two repairs.**
  `Math.Max(minSelect, 1)` forced at least one card out of a prompt the game allows to be skipped
  (`FromChooseACardScreen` asks the selector for `(cards, 0, 1)`; `SeaGlass` asks for `0..N`) while
  `details.min_select` still reported the game's own `0` — a report the caller could not act on. And
  the loop stopped at the minimum, so a caller could never take more even where the game allowed up to
  `max_select`. The prompt now reports the game's range, offers `finish_card_select` exactly while the
  game allows leaving with what has been chosen (which is what makes a minimum of zero a skip), keeps
  asking while the caller is below its minimum, and throws rather than handing the game a short set
  when the offer runs out. The third acceptance sample is that path measured.
- **Scope creep the reviewers named, and where it landed.** The `BoundaryGate` was not in the ticket;
  it stays, because without it a caller slower than the room loop's 50 ms has its card action
  delivered to the room and the run hangs, which would make the ticket's third item true only for fast
  callers. Its comment no longer claims a priority the semaphore does not give: what it preserves is
  that whoever published the decision the caller saw is who receives the answer. The vocabulary
  table's `card_choice` removal from `combat` and `card_reward` stays too, and now rests on the
  decompiled build's own call sites rather than on assertion. A relic's *own* automatic card play
  (`WhisperingEarring` pushes `VakuuCardSelector`) is deliberately not taken, and the comments no
  longer imply otherwise: that selection is not a decision either encoder reports.
- **Smaller findings acted on.** The duplicated card/action loop between the two card-select stage
  blocks is one helper both call, so the deck stage's options and actions come from the same code as
  before while its handler stays untouched. The `details` payload and the finish action gained offline
  pins — the reviewer was right that the ticket's own new payload had none. The prose that called four
  prompt kinds "measured" now names the three that were measured and says the rest are read from the
  decompiled build. `simple_card_select` is glossed in `CONTEXT.md` as the card-select prompt it now
  names rather than the screen it was named after, and `CardSelectPrompt.OneCardFrom` says out loud
  that the screen seam reports the one card its own loop selects rather than the game's unknown range.
  A card action naming a card the prompt does not offer is now refused to the caller by `step`
  instead of throwing on the game's task and leaving the caller waiting, and `HasClient` follows the
  connection the server holds rather than a socket's stale `Connected` bit, so the "nobody is driving
  this" fallback can actually fire.
- **One finding was left alone on purpose.** `docs/agents/issue-tracker.md` points at a
  `triage-labels.md` that does not exist, so `Status: done` here follows the thirteen sibling tickets
  rather than a documented label. That is a repository-wide documentation defect, recorded here so the
  next reader sees it rather than assuming the file was checked.
- **One pre-existing defect found while reviewing, not fixed here.** An event room's loop coerces any
  action id it does not recognise to option `0`, and the bridge offers `proceed` for an event room, so
  a caller that sends `proceed` has option 0 clicked instead. It is the `FullAppBridgeMod` coercion
  class `docs/architecture-review.md` already lists, it is not on this ticket's path, and it belongs
  with that class's repair.
- **After the review.** The bridge builds with 0 warnings and 0 errors; `pytest tests -q` is 190
  passed outside the file policy (the 22 errors inside it are the documented `tmp_path` refusal);
  `scripts/test-public-tree.ps1` passes; `ruff` and `mypy` are clean on every changed Python file. The
  acceptance was re-run against the shipped game with all four drives green, and the two prompt
  observations it recorded before the review hashed *identically* afterwards (`AAFDCB93…`,
  `7E1F39AB…`), so the repairs did not move what had already been measured.
