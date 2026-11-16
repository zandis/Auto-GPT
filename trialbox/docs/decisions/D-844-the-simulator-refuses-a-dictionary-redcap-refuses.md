# D-844 The REDCap simulator refuses a data dictionary a real REDCap refuses

- **Task:** CGRD-B5b (packet 2, B5 item 1; EDC-001), from the browser run against a real REDCap 17
- **PR:** this branch (`agent/CGRD-B5b-sim-refuses-what-the-dictionary-cannot-hold`), cut from CGRD-B5a (#734)
- **Date:** 2026-11-15
- **Status:** proposed (merges on green CI)
- **Builds on:** D-840 (the kit loads on a real REDCap)

## Decision

1. The simulator refuses a dictionary with `^` in a calculation, always, as the real REDCap did.
2. It refuses a validation type the instance does not offer (`create_app(not_offered=...)`): an instance's
   administrator chooses the types it offers. By default every type is offered, as REDCap's own list does.
3. The one fixture that sent `^` to the simulator (`test_edc_t302b.py`'s BMI) writes the power as a product; the
   evaluator keeps a `^` case of its own.
