# 02: Port the shipped random-run-seed convention and record the stream

**What to build:** A corpus user can ask for game-like run seeds in exactly the form the shipped game draws when a run is started without a typed seed — the shipped length, the shipped alphabet, and the shipped redraw when a drawn string would be rejected — canonicalized to the form a run accepts. Because the shipped convention draws from a non-deterministic generator, the seeds that were accepted are recorded rather than re-derived, so a campaign can resume its stream and a reader can replay the exact sequence.

Blocked by: None (can start immediately).

Status: ready-for-agent

- [ ] A public surface returns the next run seed in the shipped convention, and a test can pin the exact sequence a caller gets by injecting the generator rather than reading a clock.
- [ ] A drawn seed is returned canonicalized and the raw drawn form is available when the two differ, so a caller can say canonicalisation happened and what it applied to.
- [ ] The accepted sequence is recordable and readable, so a resumed stream continues where it stopped with no redraw and a recorded sequence replays byte-identically.
- [ ] Two distinct drawn strings that canonicalize onto one run seed are detectable before a scenario generation element is created for either.
- [ ] The convention's observed behaviour — length, alphabet and the rejection redraw — is pinned against the shipped build, and the recorded evidence names that build.
