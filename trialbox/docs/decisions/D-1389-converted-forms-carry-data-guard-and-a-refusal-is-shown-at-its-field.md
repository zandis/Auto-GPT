# D-1389 Converted forms carry `data-guard`, and a refusal a route already raises is shown at its field (9k-6b, journey 1)

- **Task:** 9k-6b of plan 10 (D-1376), lane K, first journey: the study's and the site's records. **Date:** 2026-11-20
- **Why:** D-1376 left two things to 9k-6b: whether a converted form carries `data-guard` (review 09: "leave without
  saving?" on every form that takes typed text) and how a form whose route answers a wrong value with the console's
  refusal page, not the form again, is converted ("a route change of its own").
- **Where the card comes from:** plan 46 (`docs/plan/46-plan-9-rev-2-2026-11-17.md`), card 9k-6 / DS-6 (line 278) and its
  `9k-6b` part as D-1376 names it; plan 47 only carries "9k-6" over.
- **No ruling exists on `data-guard`.** D-1376 left it as a question for the owner. Plan 46's acceptance for 9k-6 asks
  for "the guard on 100 % of text forms" (line 278, again at line 467, journey acceptance 24). Lane K recommended adding it
  form by form in 9k-6b, and this card does. **The question stays open with the owner:** if the owner rules otherwise, the
  attribute comes off these forms and the check in `tools/form_fields.py` goes.
- **Decision:**
  - **`data-guard` on every converted form.** It warns before the page is left with edits not yet saved
    (`console.js` §3); it changes what leaving a page does, not what is saved. The nine forms of this journey and
    the two of 9k-6a (the same template) carry it. `tools/form_fields.py` fails a converted form without it
    (`tests/unit/test_form_fields_guard.py`). A later journey's forms carry it from their first commit.
  - **A refusal is shown at its field, from the sentence the route already raises.** Where a route refuses a value
    with `problem(400, "request.refused", reason=<English sentence>)` (the IRB record, a consent-form version, the
    staff directory, the opt-out register), the form's route catches that refusal and shows the same page again, 400
    as before, with the summary and the field's own message (`console.form_errors.from_refusal`: a table of the
    sentences the form can raise, each to a field and a message key; a sentence that names no field, "dates are
    YYYY-MM-DD", names the fields whose text is not a day, read from the posted form). Nothing the route checks
    changes, nor the order of its checks, nor what is written, nor the audit events; an `/api/v1` twin answers as
    before. Where the route computes its own list of wrong fields (the committee record), it raises
    `form_errors.Refusal` with the fields and the refusal, and the API route re-raises the refusal.
    A refusal not on the table (a 403, a missing study, the box not answering, a refusal of a valid request) is
    raised as before. Only a refusal answered 400 is read this way (a 409 is a refusal of a valid request), and
    `tests/unit/test_form_errors_refusal_9k6b.py` holds that, and that every sentence on a table is still one the code
    raises. The state change and the take-back (`study_setup.py`) already answered a wrong value by showing the page again
    with a banner (`err=`); they now show the same words at the field (`sstate.need_reason`, `sstate.bad_move`,
    `sstate.bad_keep_years`, and `fe.sstate.take_reason`), 400 as before; the 409 refusals stay banners.
  - **One refusal is shown at a time** where the route stops at its first (the IRB record, a version, the directory);
    the committee record shows every wrong field, as its refusal always named them.
  - **The macro takes the control's own `data-testid`** in `attrs`, so a form's earlier tests keep reading it;
    without one the testid is the id, as before (`_fields.html`).
  - **A page whose title equals its heading keeps them equal.** D-1380 and `tests/unit/test_page_header_9k5.py` hold
    "the title is the heading" and the baseline of pages that break it may only go down; the staff directory and the
    opt-out register pass today, so after a failed post both their title and their heading begin with "Error:"
    (`fm.title` in both). A page already on that baseline (the IRB record, the committee record, the study's state) keeps its
    heading as it is. The consent-form versions' form is now on the IRB page itself, so that page's second save
    button is a secondary one (`test_page_header_9k5.py`: one primary act per page).
  - **The browser's own checks stay.** `required` (staff name, a contact's department and name, a consent-form version,
    the take-back reason) and `minlength="10"` on the lift note are carried by the macro's `attrs`, as on master; the
    server's checks are unchanged. The macro's own "required" word is not used.
  - **`data-guard` is armed on a page shown again after a refused post** (`console.js` §3): typed values nobody has
    saved are not lost by leaving it. Measured in Chromium (`tests/console/form_guard_9k6b.js`).
  - **What the person typed comes back**, as D-1376 says; this includes a chart number or a pseudonym typed on the
    opt-out page, shown again to the same person in the response to their own post, as any typed value (never kept,
    logged or sent anywhere else; not a new read of patient data). The response is `Cache-Control: no-store` (held by
    `test_form_errors_9k6b.py`) and the two fields are `autocomplete="off"`.
  - **Limit:** a `type="date"` field that was sent text that is not a date comes back with the text in its `value`, which
    a browser shows as empty; the summary and the field's message still name it.
- **Forms converted (9):** `irb`, `icf` (the consent-form versions, their form moved into `team_irb.html` with the page's
  summary, `_icf_list.html` removed), `committee`, `staff`, `contact` (`site_staff.html`), `optout`, `optout-lift`
  (`site_optouts.html`), `state`, `take-back` (`study_state.html`). The ratchet: **102 typed forms in 62 templates before,
  93 in 56 after**.
- **Not changed:** who may post (each route's right check is first, as before), what is valid, what is stored, the
  audit events, the status codes (400 for a refused value, 403, 404, 409 as before).
- **Proof:** `tests/console/test_form_behaviour_9k6b.py` replays a fixed sequence of valid and invalid posts per form
  (and posts by a role that may not post) against `tests/console/data/form_behaviour_9k6b1.json`, captured on
  origin/master before any form was converted: the same status, the same address, the same audit events, the same
  stored result at every step. `tests/console/test_form_errors_9k6b.py` posts each form with a wrong value in en, ja and
  zh-TW (the summary, each field's message, what was typed, nothing saved, CSRF still enforced).
- **Not verified:** no screen reader was run; the ja and zh-TW messages have not been read by a native reader; the
  keyboard order is measured in Chromium only where Node Playwright is installed.
- **Held by:** `tests/unit/test_form_fields_guard.py`, `tests/unit/test_form_errors_refusal_9k6b.py`, `tests/console/test_form_behaviour_9k6b.py`,
  `tests/console/test_form_errors_9k6b.py`.
