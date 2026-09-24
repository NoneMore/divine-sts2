# Keep corpus artifacts free of wall-clock times and floats

A generated corpus claims that one request, on one game build, with one worker count, writes byte-identical shards — that claim is what lets a regenerated corpus be diffed, and a diff that means nothing hides a real change. Two kinds of value destroy it: a wall-clock duration differs between two runs of the same request, and a floating-point number invites formatting drift. So no duration and no float may appear in a shard, in a corpus summary, or in any other file a corpus owns; a corpus's manifest keeps carrying counts alone. Timing lives outside the corpus instead — an opt-in sidecar file, or a benchmark that wraps the generation call from the outside.

## Consequences

A reader cannot learn from a corpus how long it took to produce, so throughput must be reported by a separate artifact and can regress silently; a batch that needs to prove both reproducibility and speed keeps two files rather than one. This also means the generator's summary cannot be extended with stage timings as an observability convenience, however convenient that looks: the extension would have to move the corpus out from under its own guarantee.
