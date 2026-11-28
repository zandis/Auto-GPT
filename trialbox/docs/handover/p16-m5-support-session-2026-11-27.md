# P-16: M5's support session

**Reader:** the people who build TrialBox: the integrator and the lane H lead. Findings for builders, so in one
language.

- **Card:** P-16, the integrator's R1+1 batch D, part H (7210967559, PR #1504). Base: `int/r1plus1`. The card's
  other two pages, the health page and the data step, and its findings (P16-01 to P16-03) are in
  [`p16-m5-page-files-2026-11-27.md`](p16-m5-page-files-2026-11-27.md).
- **Date:** 2026-11-27
- **Files:** the new `services/console/support_page.py`, `i18n_support.py` and `templates/support_page.html`;
  `tests/console/test_m5_support_p16.py`; `tests/unit/test_framework_f0.py` (a test change: one entry leaves
  `PENDING`; no assertion changed).
- **Files outside the card:** `services/console/rc1_guard.py` (one line added to `ALLOWED`),
  `services/console/i18n.py` (`i18n_support` joined); the test tables `tests/console/data/role_route_matrix.md`,
  `route_actions.yaml` and `role_walk_unclear.txt` (three new rows each in the first two, two lines in the third, no
  row changed) and `tests/console/form_cases_9k6a.py` (the support form's case).

## 1. What was wrong

`console.app.MODULE_PAGES` declares `support_page`, a file no branch had: decision 99's support session was off on
every box, and F0's test let it pass because the file was listed in its `PENDING` set.

## 2. What was built

**The support session** (`/admin/support`, one form with a tick, and its twin `POST /api/v1/admin/support`), for
decision 99. Reading the page needs `ops.view`, turning the session on or off needs `ops.update_apply`; anyone else
gets 403 and a `console.denied` line. While it is on, every route that rc1's guard refuses on a refused box is refused
for every role, with the support session's own message and a `console.denied` line (`refusal: support_session`).

- `SupportGuard` is rc1's guard with its question changed, so both refuse the same routes.
- Start and end are audited as `console.support_session`. The session ends by itself 2 hours after it starts.
- The state is one file, written to a new file, fsynced and renamed into place.
- A start writes the state with its event owed, then sends the event. A stop between the two keeps the pages
  closed, and the next read sends the event. A state that cannot be read keeps the pages closed.

rc1's guard allows the page by name (`ALLOWED`); it holds a switch, never a patient.

## 3. Tests

`tests/console/test_m5_support_p16.py`, all on fixed clocks.
- During a support session, a coordinator's home page and a patient file are refused, and the administrator is
  refused the patient file too. After the end they open again, and the audit holds exactly one start and one end.
- The switch's API twin turns the session on and off.
- The session ends by itself at 2 hours, once.
- A stop between the state and its event is covered, and so is a state that cannot be read.
- A role other than the administrator is refused the page and the switch.

## 4. Not done, not verified

- No box was used; the session was tried on the test console only.
- `PENDING` in F0's test names `health_page` and `data_step` until the health page change is merged; whichever of
  the two changes merges second empties it.
