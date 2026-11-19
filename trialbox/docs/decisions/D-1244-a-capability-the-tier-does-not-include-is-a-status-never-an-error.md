# D-1244 A capability the tier does not include is a status, never an error (10E-17)

- **Task:** lane J, plan 10 row 10E-17 (review 13, item 13-18; `docs/plan/47-plan-10-2026-11-18.md`): tier-aware
  console wording. Exit: a home-page text test per tier. · **Date:** 2026-11-19
- **Builds on:** D-1320 (the tier record), D-1322 (a reader takes a tier value only when it is measured).
- **Decision:**
  - **One reader, reused.** The console reads the box's tier record through `tb_common.tier_value`, the services'
    one reader (lane H, 10E-1c), and only its field `console_promises`. `console.tier_words.lacks()` keeps the rows
    whose status says the tier does not include the capability: today `protocol_reading` "not on this box" and
    `chat_during_a_screening_run` "busy until the run releases the card" (`WORDED`). The rows `available` and
    `not_measured` are not absences and are never worded here. A row with no words in en, ja and zh-TW is shown as
    nothing, so a new capability in a record never appears as a raw key.
  - **Words may take a declared field.** `console_promises` is declared on every record. D-1322 keeps a declared
    value from changing what the box does; these rows change nothing: no route, button, run, permission or export
    reads them. They are only words. D-1322 stays the rule for every value that changes behaviour.
  - **Where.** The administrator's home page (`/home`, which is the health tab of `/admin`) gets one tile, "What this
    box's tier includes". It has one line per absence, and each line ends "nothing is wrong". The tile has no pill,
    no warning, error or alert class, and no link. It appears only on the page that already shows the administrator
    the box's capability state (the Models and System tiles). No other role sees it, and no route, export or reader of
    stored data is added.
  - **Errors stay errors.** The tile lists only what the tier lacks. A capability the tier includes and which is broken
    keeps its own warning or error: no model answering the note judge, note answers that may not exclude, a service
    that is down. These pills are unchanged on every tier.
  - **Nothing new elsewhere.** On the full tier (the RTX PRO 6000 record: every promise available or not measured)
    and on a box with no record (another `TB_PROFILE`, none, a missing or malformed file), the page is byte for byte
    what it was. A test compares the rendering.
  - **Not here.** The protocol page and the coordinator's home: showing them a capability's state would be a new
    reader for those roles. The site box's protocol wording ("sent to the coordinating box") is plan 10 row 10E-33's.
    A not-measured value shown as "not measured" (ECC) is the capability page's job (10K-11).
- **Held by:** `tests/console/test_tier_status_words.py`; the family `tier.lacks.` in `tools/text_keys.py`.
