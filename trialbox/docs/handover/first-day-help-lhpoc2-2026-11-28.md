# First-day help (lane H, PoC item 2)

**Reader:** the people who build TrialBox: the lane H lead and the integrator. In one language.

- **Card:** lane H, PoC item 2
- **Date:** 2026-11-28
- **Findings:** [`first-day-help-lhpoc2-2026-11-28/findings.json`](first-day-help-lhpoc2-2026-11-28/findings.json)
  (LHPOC2-01 to LHPOC2-03)
- **Tests:** `tests/console/test_first_day_help.py` (36 tests)

## What was there

Help already had `/help` and `/help/guide`: the signed-in account's own role guide, built from the catalogue
(`console.guides`). Nothing said what to do on a first day, and no procedure existed as a page.

## What was added

- `/help/first-day`: the signed-in role's own page for the investigator, coordinator, data steward and administrator,
  in en, ja and zh-TW. It lists the procedures that role uses, and four rules of the product. Help links it for those
  four roles only. Any other role is sent to its own guide, as Help's other pages answer every role.
- `/help/first-day?procedure=<name>`: seven one-page procedures (install check, the first night, approve a study,
  review the list, contact and consent, backup and restore, what to do when something is held). A procedure the role
  does not use is a 404.
- Every button or page a step names is a `{name}` filled from the console's own catalogue (`first_day.LABELS`), so the
  step shows the label the screen shows, in the reader's language. No label is typed twice.
- The words are in `services/console/i18n_first_day.py`; `tools.text_keys` holds the three languages to the same keys
  and placeholders.

## Files outside the card

- `services/console/app.py`: the account scope check lets a sponsor-form account reach `/help/first-day` as it reaches
  `/help/guide` (one list entry).
- `services/console/step4.py`: the route is registered beside the guide's; `services/console/i18n_home.py` joins the
  words; `services/console/templates/help.html` shows the link.
- `tests/console/data/role_route_matrix.md` (regenerated; one new row, and the generator's own order of three
  existing rows) and `tests/console/data/route_actions.yaml` (one new row). No assertion changed.
