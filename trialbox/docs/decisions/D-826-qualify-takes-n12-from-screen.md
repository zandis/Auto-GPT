# D-826 qualify takes N-12 from SCREEN

- **Task:** N12-SCREEN, the owner's blocker 3 of 2026-11-15, lane D's half (lane A2's half is #662,
  `tools/n12_screen.py`; the split agreed on #639)
- **PR:** this branch (`agent/N12-SCREEN-qualify-takes-n12-from-screen`), stacked on #662
- **Date:** 2026-11-15
- **Status:** accepted
- **Builds on:** D-343 (N-12 gates on the unadjusted figure), D-313 (qualify), D-737 (qualify on the box)

## Decision

1. qualify's `n12` step refuses evidence that does not say `source: "screen"`: N-12 is read from SCREEN's own run
   (`python -m tools.n12_screen`), not from the benchmark prompt path (`tools.trec_ct_eval`). The other evidence
   (public_e2e, goldens) is unchanged.
2. Its wiring check (`--stub`) runs `tools.n12_screen --help`.
3. `--evidence n12=<file>` reaches qualify through the box wrapper as given (D-737 keeps every option).

## Test

`tests/unit/test_qualify_n12_from_screen.py`: before, failed; after, passed. The existing basis test gives its good
case `source: "screen"` too (stricter, not looser).
