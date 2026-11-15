# D-882 the network sheet names the rehearsal's stand-ins test-only

- **Task:** I-7 (network-sheet part), the integrator's I-7 list on #639
- **PR:** this branch (`agent/I-7a-the-network-sheet-skips-stand-ins`)
- **Date:** 2026-11-15
- **Status:** accepted

## Decision

`tools/network_sheet.py` puts `mail-sink` (the SMTP stand-in of `tools/rehearse_box/standins.yml`) in `TEST_ONLY`, so
install.sh's sheet step on a rehearsal box writes "test only" for it instead of raising KeyError.

## Test

`tests/unit/test_network_sheet.py::test_the_rehearsal_stand_ins_render_as_test_only`: before, KeyError; after, passed.
