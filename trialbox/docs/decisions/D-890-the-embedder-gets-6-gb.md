# D-890 the embedder's memory cap is 6 GB

- **Task:** EMBED-MEM, the integrator's card from lane A2's embed-service fix (#756, D-900), 2026-11-15
- **PR:** this branch (`agent/EMBED-MEM-the-embedder-gets-6-gb`)
- **Date:** 2026-11-15
- **Status:** accepted

## Decision

The compose default of `TB_MEM_EMBED` is `6g` (was `4g`), and the GB10 overlay and `deploy/gb10-profile.yaml`
say the same 6 GB. Lane A2's figures: the weights about 2.3 GB, the runtime about 0.6 GB and one batch at the token
cap under 0.6 GB, about 3.5 GB for one load; 4 GB was too tight once several loads raced. A site's own
`TB_MEM_EMBED` in deploy/.env still wins. The memory checks read the cap from compose (`tools.trialbox.memcaps`,
doctor's `wsl2_memory` sum), so they follow without a change of their own; the two-device budget sums the profile.

Lane G's 16 GB diagnostic gives a measured high-water mark; if it contradicts 6 GB, the integrator says and this
record is followed by one with the measurement (`measured_peak_gib` stays null until then).

## Test

`tests/unit/test_embed_memory.py`: before, 3 failed; after, 3 passed (the compose default, the GB10 overlay and its
profile, and no compose file left at `4g`). The memory-cap, compose-limit, WSL2-fit, two-device, box-plan and doctor
tests pass unchanged.
