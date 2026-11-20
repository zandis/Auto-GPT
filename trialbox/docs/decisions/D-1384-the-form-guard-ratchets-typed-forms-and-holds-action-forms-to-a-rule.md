# D-1384 The form guard ratchets the forms that take typed input and holds the action forms to a rule (9k-6c)

- **Task:** a follow-up to 9k-6a (D-1376), lane K. **Date:** 2026-11-20
- **Why:** D-1376's guard counted every raw POST form and asked a converted form for a field drawn through
  `fm.field` and a failed-POST case. A form with nothing to type (one button, a hidden CSRF token, perhaps hidden ids)
  can never be converted, so each new one could only raise the ratchet, which the lane does not do.
- **Ruling:** the integrator ruled on 2026-11-20 that a POST form with nothing a person types is not counted by the ratchet, and that D-1376 states it (amended there) and a test pins it.
- **Decision:** `tools/form_fields.py` classifies each raw POST form by its text.
  - **TYPED:** it holds an `<input>` whose type is not a literal hidden, submit, button, image or reset (text, file,
    checkbox, radio, an input with no type, a type written by an expression), a `<select>` or a `<textarea>`. TYPED
    forms keep exactly D-1376's rule and ratchet (converted through the macro, or on the list with a reason).
  - **ACTION:** only hidden inputs and buttons. Not ratcheted. Each one, old and new, must be a POST (it is, by
    how forms are found), carry a hidden input named `csrf` (how every template draws the token:
    `<input type="hidden" name="csrf" value="{{ csrf }}">`) and have a non-empty `action`. A form that breaks this
    fails the guard unless its template is on the ratchet file's second section (`@action`), which lists, per
    template, the action forms that break the rule as measured; it can only go down.
  - `tools/form_fields_ratchet.txt` now has two sections, `@typed` and `@action`; `--write` rewrites both.
- **Numbers (measured on master 6fecbf8, 2026-11-20):** before, 153 raw POST forms in 76 templates, all ratcheted.
  After: **102 typed in 62 templates** (ratcheted; every template's count is at most its old one, the new total at
  most 153), **51 action forms** (not ratcheted), of which **0 break the rule** (all have the csrf field and an
  action address), so the second section is empty and the rule holds for every new action form.
  Of the 102 typed, 99 hold a visible control and 3 are typed only because the text cannot see through them
  (`firstrun.html`, `life_schedule.html`, `site_checks.html`: a local macro call).
- **Limits of text classification:** the guard reads template text, not the rendered page. A control drawn by
  `{% include %}`, `{% call %}`, `{% import %}`, `{% extends %}`, `{% macro %}` or by a call inside `{{ }}` that is not
  a known text helper (`TEXT_CALLS`: the catalogue lookups and plain value methods) is invisible to it, so such a
  form is treated as TYPED, the stricter class; the guard does not follow includes. A form that is really an action
  can therefore sit on the typed list until its call is made a known helper or the form converted; a form whose
  controls are written by a helper the list names as text, but which draws a control, would be missed (a new helper
  is added to `TEXT_CALLS` only with this in mind). A button is not checked for what it does (a button that
  deletes is still an action form; its confirmation is a product question, not this guard's). `<form>` tags
  written by script, or a form that is not closed, are not seen, as in D-1376. The csrf check is that the field is
  named, not that the route checks it.
- **What did not change:** no template is edited, no product behaviour changes, no console template or CSS is
  touched (so no whole `tests/console`); D-1376's converted-form rules and failed-POST cases are unchanged.
- **Held by:** `tests/unit/test_form_fields_guard.py` (a new typed raw form fails; an action form with the token
  passes with no list; one without the token or the action fails; a checkbox makes a form typed; the recount equals a
  fresh measurement; no template's typed count is above D-1376's list, kept as
  `tests/unit/fixtures/form_fields_ratchet_d1376.txt` and, where git has it, `origin/master`).
