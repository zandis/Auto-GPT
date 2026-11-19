# D-1157 The participant page's tables are cards on a phone, whatever the layout flag

- **Task:** the nightly phone walk (H-21, D-1138; `tests/e2e/test_life_cycle_walk_390.py`, steps 15 to 17), sent by the integrator on 2026-11-19: tables wider than 390 px on `/studies/{rs}/subjects/{record}` and on the page a step answers with. · **Date:** 2026-11-19
- **Decision:** the participant page's two tables (the visit schedule and the trail) carry the console's `stack` class (one card per row at 640 px and below, D-104) when the phone-first layout (`layout.phone_first`, lane J's J-3) is off, its default; with it on they keep its labelled `pf-cards`. No style sheet changes (lane J's). Measured at 390 px in Chromium on this page: 413 and 405 px before, 332 px after; the page itself never scrolled sideways.
- **Left:** the walk's findings page is lane H's; the other wide tables it names (P-02 to P-14) are pages not among the phone's pages, or lane J's.
- **Held by:** `tests/console/test_participant_page_fits_a_phone.py` (both tables, and the page a step answers with), synthetic data only (failing output on master kept: `s390-fail.txt`).
