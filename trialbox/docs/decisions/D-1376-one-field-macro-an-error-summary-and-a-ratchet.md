# D-1376 One field macro, an error summary at the top, and a ratchet on every POST form outside them (9k-6a)

- **Task:** plan 10 track F, the carried card 9k-6 (DS-6, with 9g-20) of plan 9 rev 2 §3.5, from review 09
  (`docs/reviews/2026-11-root/09-ux.md` §1, item 4; §3.2 component 8; §3.3 "Form"; GOV.UK's error summary) and
  A11Y-4 of review 02. The owner's side split it: **9k-6a** (this) is the macro, the summary and the guard with a
  small first use; **9k-6b** converts the console's other POST forms journey by journey. Waits for 9k-1 (D-1368).
  · **Date:** 2026-11-19
- **Decision:**
  - **The macro** (`services/console/templates/_fields.html`, imported `{% import "_fields.html" as fm with
    context %}`): `fm.field(fe, form, prefix, name, label, value, kind, type, hint, required, disabled, cls, options,
    checked, attrs)` draws, in this order, the label, the hint, the field's own error and the control. The control's
    id is `<prefix>-<name>`; the hint is `<id>-hint` and the error `<id>-err`, both in `aria-describedby`; a failing
    control has `aria-invalid="true"` and its wrapper `fm-bad` (a `--bad` border and rule, so the error is not shown
    by colour alone: the message is in words before the control). `required=True` writes "required" in words beside
    the label (`fe.required`: 必須, 必填, the catalogue's spellings) and `aria-required="true"`, **not** the browser's
    `required`: the server's check is the one check, so a missing value shows the summary as any other error does.
    Kinds: any `input` type, `textarea`, `select` (value, label pairs), `checkbox`, `password`.
  - **The summary** (`fm.error_summary(fe, testid)`), GOV.UK's pattern: at the top of the page, above the `h1`; a box
    with `role="alert"`, `tabindex="-1"` and `autofocus` (focus moves to it when the page loads, with no script: the
    page's one hashed script is not touched), labelled by its heading ("There is a problem", 入力内容に問題があります,
    輸入內容有問題), then one link per failing field in the form's order to `#<prefix>-<name>`; following a link
    moves focus to the field (measured in Chromium). The words of a link are the words at the field. `fm.title(fe,
    text)` puts "Error: " (エラー：, 錯誤：) before the page's `<title>`. A page with more than one converted form
    shows one summary, for the form that was posted (`fe.form`); its `testid` keeps the one the page's earlier tests
    read.
  - **The helper** (`services/console/form_errors.py`): `failed(form, prefix, errors, values)` gives the
    `FormErrors` a route hands to the page: the errors as (input name, message key) pairs in the form's order, and
    the typed values. The status stays the console's for a value that does not validate, **400** (`FAILED`; a
    refusal of a valid request stays 409, a missing right 403). The texts are in a new module,
    `i18n_form_errors.py`, joined by `form_errors.py` as `admin_flags.py` joins its own.
  - **Never shown again:** a field whose name says it holds a secret (`password`, `pass`, `pw`, `otp`, `totp`,
    `code`, `pin`, `secret`, `token`, `key`, `csrf`, alone or as a part between `_` or `-`: `new_password`,
    `enrol_code`, `api_key`), whatever a route passes; a `password` field is never given a value, stored or typed; an
    upload; anything past 2,000 characters. Everything else the person typed comes back as typed.
  - **The guard, on by default** (`python -m tools.form_fields`, in `make lint`; `tests/unit/test_form_fields_guard.py`,
    marked `guard` and `nodb`): a converted form carries `data-fields="<name>"`, takes every field through
    `fm.field(fe, '<name>', ...)` (no `<input>` other than hidden or submit, `<select>` or `<textarea>` of its own),
    and its template shows `fm.error_summary` and `fm.title`; each form name has a failed-POST case
    (`tests/console/form_cases_9k6a.py`) that `tests/console/test_form_errors_9k6a.py` posts in en, ja and zh-TW. Every
    other POST form is raw, and **the ratchet** `tools/form_fields_ratchet.txt`, generated from the tree, lists each
    template with raw POST forms: its count and why it is not converted. A new raw POST form fails until it is
    converted or its template's line says why; a converted form, or a template removed, fails until its line is
    lowered or removed (`--write` rewrites the counts and keeps the reasons; a new line's reason `REASON NEEDED`
    fails). Today: **153 raw POST forms in 76 templates**; 2 converted. (The 156 counted before included one
    form drawn twice: `study_state.html`'s title block was never closed, so the IRB record's section was also
    written into the page's `<title>`. Closed here.)
  - **First use, two forms of `study_state.html`:** the study's identifiers (`/studies/{rs}/identity`, the
    coordinator or the study's PI) and the study's IRB record (`/studies/{rs}/irb-text`, the PI). Chosen because their
    routes already answered a wrong value with the page again, 400 and the values typed, so only the showing changes;
    no open pull request touches the template, its route module or its catalogue; and neither takes a secret. Each
    field the checks can name has its own message (`fe.sid.*`, `fe.irbt.*`) in place of one "Check these fields"
    line. The same routes, roles, checks, writes and audit events; a right POST answers 303 to the same address. The
    page's two other forms (the state change and its taking back) stay raw: their failures are refusals with counts
    and committee codes, not one field's value, and stay on the ratchet (2) for 9k-6b.
  - **Colours:** one block at the end of `console.css`, existing tokens only (`--bad`, `--card`, `--ink`,
    `--accent`); nine pairs added to D-1368's contrast test in both modes (the summary's text, links and rule, a
    field's message and border, "required").
- **What 9k-6b inherits:** the macro, the summary, the helper and the guard as they are; per journey it converts
  the forms, lowers the ratchet in the same pull request, adds one case per form name, and gives each field a
  message key. A form whose route answers a wrong value with a redirect or the problem page (not the form again)
  needs that route to answer with the form and `FAILED` first, which is a route change of its own; a form whose
  fields the browser's `required` holds and the server does not check is converted only once the server checks them.
  Review 09's "leave without saving?" guard (`data-guard`, `console.js` §3) on every form that takes typed text is
  not added here: it changes what leaving a page does, not how a failed POST is shown (a question for the owner).
- **Not verified:** no screen reader was run (the summary's announcement and the reading of `aria-describedby` are
  read from the markup and the browser's focus, not heard); the ja and zh-TW messages have not been read by a native
  reader.
- **Held by:** `tests/unit/test_form_fields_guard.py`, `tests/console/test_form_errors_9k6a.py` (with
  `form_errors_keys_9k6a.js`), `tests/unit/test_console_tokens_and_type.py`; the converted forms' own tests
  (`tests/console/test_study_state_d386.py`, `tests/console/test_irb_text_gate.py`) pass unchanged.
