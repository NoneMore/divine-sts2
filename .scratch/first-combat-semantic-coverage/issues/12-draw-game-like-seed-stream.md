# 12: Draw a game-like run seed stream

**What to build:** A campaign can draw run seeds the way the shipped game draws them — same alphabet, same length, same rejection of unsuitable strings — canonicalize each one exactly as the shipped game canonicalizes a seed when a run begins, and keep an accepted sequence in which no two seeds resolve to the same run. Seeds a player would never be handed are not a corpus's seed stream, and a seed stream that cannot be replayed cannot be audited.

Blocked by: None (can start immediately).

Status: ready-for-agent

- [ ] Seeds are drawn by a deterministic generator that matches the shipped game's own drawing for the same underlying random stream, including its alphabet and its rejection of unsuitable strings.
- [ ] Every drawn seed is canonicalized exactly as the shipped game canonicalizes it, and the accepted sequence records the drawn and canonical forms wherever they differ.
- [ ] A seed that resolves to one already accepted in the campaign is rejected or redrawn explicitly, with the collision reported rather than dropped.
- [ ] The accepted sequence is reproducible from its recorded starting point and is what a campaign replays.
- [ ] Public tests cover the alphabet, the rejection path, canonicalization and collisions, with recorded shipped-game observations as the evidence for the drawing rule.
