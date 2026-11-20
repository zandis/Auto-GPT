# D-1385 The phase strip: one ordered list, four states said in words (9k-10)

- **Task:** plan 10 track F, the carried card 9k-10 (DS-10) of plan 9 rev 2 §3.5, from review 09
  (`docs/reviews/2026-11-root/09-ux.md` §3.2 component PS, DS-10: "screen-reader text names done and current; the
  strip in three languages at 390 px fits two lines"). It builds on 9k-4 (D-1380, the one table of tones). ·
  **Date:** 2026-11-20
- **What the card asks:** one phase-strip component that replaces `.steps`; states done, current, to do, off; a hidden
  "done" / "current" text for a screen reader; `aria-current` on the current item; three languages; two lines at 390 px.
- **What was built:**
  - **The macro `phase_strip(items, label, testid)`** in `templates/_steps.html`: `<ol class="ps">`, one `<li
    data-state="done|current|todo|off">` per phase, the current one with `aria-current="step"`, the name as
    "N · name", and the state in words as visually hidden text (`.sr`): "(done)", "(current step)", "(not done yet)",
    "(not used in this study)". The optional second line (`who`) is drawn on a desktop and left out on a phone.
    `steps_bar(steps, step)`, the call of the six-step study procedure, stays and builds the items from the step, so
    the weekly list and the coordinator's home need no change; the set-up wizard (`site_wizard.html`) calls the macro
    directly. `data-testid="steps"` and `"wizard-steps"` stay where tests read them.
  - **The four state words** are catalogue keys `ps.done`, `ps.current`, `ps.todo`, `ps.off` in English, Japanese and
    Traditional Chinese (`i18n_home.py`), different from each other and checked by a test.
  - **The style:** one block at the end of `console.css`, named for the card. A grid whose cells are drawn by a one
    pixel gap on the line colour; done is the green cell with a tick, current an underline of the accent colour, off
    muted. Below 760 px the strip has three columns, so six phases are two rows (the wizard's five too). The old
    `.steps` rules and their phone rule are deleted; `ol.steps-list` (a plain numbered list) and `.wizard-steps` are
    other things and stay. The tones are the sheet's own tokens; no new colour, no button, no state class (`ps` has no
    hyphen: the 9k-4 guard of the old `ps-` classes does not meet it).
- **The proof:** `tests/unit/test_phase_strip_markup_9k10.py` (the four states in three languages, one `aria-current`, the
  six-step call, no `.steps` markup or rule left, three columns on a phone) and
  `tests/console/test_phase_strip_9k10.py` (the coordinator's home, the weekly list and the wizard show the strip with
  a state on each item in three languages; Chromium at 390 px and at 1280 px: at most two rows, no sideways scroll,
  no one-character line, one current item).
- **Left out:**
  - **Links to each phase's page, and the eight phases of the review** (journey review §D: Visits, Safety, Monitoring,
    Close lit by the EDC): the card is the component; the phases and the EDC's lighting belong to 9k-11 and J-7 and
    plan 9's A-7.4. The item has no link and no state beyond the four.
  - **No state "off" is produced yet:** no page has a phase a study does not use today; the macro and the style
    carry it so the study switcher (9k-11) can.
  - **Other lists called "steps"** (`ol.steps-list` on the handover and set-up pages, the life-cycle step table of
    `life_subject.html`): not a phase strip; untouched, as are `dataops_batch.html` and `registry_ruleset.html`.
  - **No role, read or export changes**: the strip shows the same words as before to the same pages.
