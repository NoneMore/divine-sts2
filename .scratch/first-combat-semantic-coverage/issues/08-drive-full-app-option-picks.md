# 08: Drive option picks in the shipped-game bridge

**What to build:** Let a caller select the options offered by the shipped game's Ancient reward prompts through the existing full-app bridge, alongside its current card-select support, so bundle and relic option branches become directly verifiable against the shipped game instead of being recorded as kinds the seam cannot drive.

Blocked by: None (can start immediately).

Status: ready-for-agent

- [ ] The bridge reports the legal option identities for a blocking card-bundle and relic option prompt and accepts a caller-selected legal option rather than letting autoplay answer it.
- [ ] Selecting each offered option advances the shipped run through the corresponding native reward effect; an illegal or stale selection is rejected explicitly.
- [ ] Every new stage word the bridge can report maps to a decision kind, so an unmapped word fails a test rather than passing silently.
- [ ] A focused full-app acceptance run proves caller-driven option picks for representative bundle and relic prompts, including a subsequent prompt when one opens.
- [ ] Existing card-select prompts and the prior first-combat bridge acceptance keep working.
- [ ] The bridge stays behind the existing protocol: option identities reach the caller through the observation and legal-action shapes already published.
