# 04: Drive an Ancient choice and any nested choice to completion

**What to build:** Choosing one of the Ancient's offered options completes through the game's own option path, so the relic is obtained by the game and whatever randomness that consumes is the game's, not a reimplementation's. Some choices open a second, blocking prompt — a card select, a reward set or a bundle pick. That prompt is answerable through the same headless decision loop as every other run-mode decision, so a caller can resolve it and carry on to the map without a graphical tree and without replaying the run.

**Blocked by:** 03: Offer and enter the act-1 Ancient room at run start.

**Status:** ready-for-agent

- [ ] Choosing an offered Ancient option obtains the relic that option reported, through the game's own option-completion path.
- [ ] Choosing an offered Ancient option consumes only randomness the game itself consumes, so the run's RNG counters afterwards are the ones a shipped run has.
- [ ] An Ancient choice that opens a nested prompt produces a further observable decision whose legal actions a caller can select.
- [ ] Each nested-prompt kind the shipped Ancient choices open — card select, reward set and bundle pick — is reachable and completable.
- [ ] An Ancient choice that opens no nested prompt proceeds straight to the map with no extra decision.
- [ ] The nested prompt resolves headlessly, with no reliance on presentation or a scene tree.

## Comments

**2026-09-16 — a concrete nested-prompt gap found while landing 03.**

Sweeping all offered choices over 37 seeds with a de-risking probe while landing 03 (the probe is not
kept; 03's acceptance script only takes a choice that opens no second prompt), one choice fails to
complete:
`NEOWS_BONES`. Its pick-up offers a reward set that itself begins a second reward set, and
`CaptureRewardsScreen` refuses the second with `nested_reward_collision` ("a second native reward set
began before the first was resolved"), so the choice cannot be driven to the map. Every other choice
completed, walking the first legal action at each step: plain relic pick-ups, `card_choice`
(`FromDeckForRemoval`, `FromChooseACardScreen`, `FromDeckForTransform`, `FromDeckForUpgrade`),
`option_choice` and custom-reward chains up to four reward sets deep. Before ticket 03 the Ancient
room was never entered, so none of this was reachable.

