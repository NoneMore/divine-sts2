# Version compatibility

The host is non-certifying and accepts only explicitly fingerprinted installed assemblies. No state, trace, or branch compatibility is claimed across assembly hashes; a mismatched build fails loudly rather than degrading.

This is the canonical pin record. Other documents may restate the pinned values but do not replace this one.

| Item | Value |
| :--- | :--- |
| Game version | `v0.107.1` (`release_info.json`: commit `59260271`, branch `v0.107.1`, date 2026-06-18) |
| Product version (`sts2.dll`) | `0.1.0+59260271157f76a2896f0eab5bc6ea1245d8b314` |
| Assembly SHA-256 (`sts2.dll`) | `A1F9E653F1E28E4076558FEE1E60D218619CB7E057B887C6417F62C62C6D7A52` |
| Package SHA-256 (`SlayTheSpire2.pck`) | `42520EB8B0911C6C0F0BD102D92B33F41ABD4D26B83489817D0A6DBD7DD48587` |
| Engine | Godot `4.5.1.stable.mono` |

The feasibility report records the complete SHA-256 and product version on every run. Update this file whenever the pin changes, and treat every build-pinned result elsewhere in `docs/` as stale until it is re-measured on the new pin.
