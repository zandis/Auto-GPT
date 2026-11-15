# D-768 The EDC item map saves a real eCRF's size

- **Task:** NEW-JRN-5 (the deep review of 2026-11-12, JRN-005; `37-remaining-work-split.md`, lane C2's queue)
- **PR:** this branch (`agent/NEW-JRN-5-the-item-map-saves-a-real-ecrf`), from master after train 15
- **Date:** 2026-11-14
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-160 (EDC prefill: the item map), OD-10 (a limit is a declared rule, not a framework default)

## The problem

The item map page posts 13 fields per dictionary item. The form was read with the framework's default limit of
1,000 fields, so a map of 77 items or more was refused with a raw JSON answer (`{"detail":"Too many fields. Maximum
number of fields is 1000."}`, HTTP 400, no page); the demo's own dictionary already failed, and a real eCRF has
hundreds of items. **Confirmed by a test** before the change (kept failing output: `jrn5-fail.txt`).

## The decision

- **The limit comes from the study's dictionary.** `POST /studies/{rs}/edc/map` reads its form with
  `max_fields = (the dictionary's suggested items + the saved map's items + 1) × MAP_ROW_FIELDS + MAP_FORM_FIELDS`:
  13 inputs per item (the hidden item and its 12 named inputs; a test counts them in the template, so an input added
  to the row must raise the number) and 16 for the form's own fields and a margin. The study is checked before the
  form is read.
- **Past the limit, the console's page.** A form larger than the dictionary allows gets the map page with a plain
  sentence in the three languages (`edc.err.form_too_large`: nothing saved, read the dictionary again), HTTP 413;
  never the framework's raw answer.

## The review

One adversarial review: SOUND. Applied: only the framework's "too many fields" answer gets the size sentence (413);
another malformed form gets the console's page with its plain error (400); the over-limit test checks the sentence and
that nothing was saved. Found and left for their own cards (the same framework default of 1,000 fields, and the
app-wide handler that answers a form-parsing 400 with raw JSON): the sources page's REDCap attach (one checkbox per
dictionary field, `data_sources.html`), the SDV list (one per subject) and a very large data-entry form.

## Reuse check

The map page's own reads (`/edc/map/suggest`, `/edc`), its error partial (`_edc_err.html`), the CSRF check. No new
route, store or permission.

## Dropped (D-311)

No sign-off step.
