# D-1322 A reader takes a tier value only when it is measured; otherwise it keeps what it had

- **Task:** lane H, plan 10 row 10E-1c (the readers onto the tier record; the integrator's ruling of 2026-11-18,
  20:12 UTC, and the lane H lead's rulings for the card)
- **Date:** 2026-11-18
- **Status:** proposed
- **Builds on:** D-1320 (the tier record), D-445 (the gateway's slots)

## Context

Plan 10 row 10E-1 is done when every reader uses the tier record and the gateway's constant `SLOTS = 16` is gone.
The records state most fields as declared or not measured, and the 32 GB site box's record declares 4 judge
sequences while its gateway has run 16 slots per endpoint (no serving record is set on a compose box). Taking a
declared value would change a shipped box's behaviour without a measurement.

## Decision

1. **Where.** The services read the record through `libs/tb_common/tier_value.py`, at `models/tiers/<profile>.json`
   (the trialbox-py image copies `models/`). The profile comes from the box's `TB_PROFILE` label: `P-PRO6000` is
   `rtxpro6000`, `P-5090` is `rtx5090`; any other label (`P-GB10` on GB10, stub and CPU boxes) has no record.
2. **Measured only.** A reader takes a field's value only when its basis is `measured` and the value is a usable
   count. A declared or not-measured field, a missing or malformed record and an unknown label give no value; the
   reader keeps its value from before the record (the gateway 16 slots, `tier_value.FALLBACK_SLOTS`; the night
   budget 2000, `microbatch.DEFAULT_NIGHT_BUDGET`). A box never fails to start for its tier record.
3. **Settings win.** The gateway: a serving record (`TB_SERVING_RECORD`) first, then `TB_GATEWAY_SLOTS`, then the
   measured tier value, then 16. The night budget: a configured `TB_MICROBATCH_NIGHT_BUDGET` first, then the measured
   tier value, then 2000.
4. **Said at start.** The gateway logs one line per endpoint role at start (`gateway.load`): which case, and for a
   declared field both the record's number and the number kept.
5. **The constant goes.** `SLOTS` leaves `services/gateway/load.py` and `GATEWAY_SLOTS` leaves
   `tools/complete_run.py`; the number 16 remains once, as `tier_value.FALLBACK_SLOTS`. The declared setting's default
   (`TB_GATEWAY_SLOTS`, "16", in `libs/tb_common/config.py`) is unchanged.

## Consequences

- No shipped profile's slots or night budget change: rtxpro6000 reads 16 measured, the same as before; rtx5090 keeps
  16 and logs the declared 4; every other label keeps 16 and 2000.
- The 32 GB box's 4 against 16 stays open for the integrator. R-1 (row 10E-30) measures the sequences on the card.
