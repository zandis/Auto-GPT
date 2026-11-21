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
    Traditional Chinese (`i18n_home.py`). The four states are one constant, `console.state_tone.PHASE_STATES`; the
    tone of each (done ok, current info, todo and off neutral) is the family `phase` of the 9k-4 table, and the macro
    writes it as `data-tone` (the card waits on 9k-4 for this). `tools.text_keys` takes the `ps.` family from the same
    constant, so a fifth state without words fails there.
  - **The wizard's name:** its strip is labelled with the wizard's own title (`site.start.title`), not the study
    procedure's.
  - **The style:** one block at the end of `console.css`, named for the card. A grid whose cells are drawn by a one
    pixel gap on the line colour; done is the green cell (its tone) with a tick that is not read aloud (`content` with an
    empty alternative), current an underline of the accent colour, off muted with a dashed line; in forced colours the
    current item has a border line and the off item a dashed border. A label is never cut: it wraps, and where a
    Japanese or Chinese label does not fit its cell it breaks between characters (`overflow-wrap: anywhere` over
    `keep-all`), with no ellipsis and no clipping. **Below 760 px the strip has two columns, and one when the person has chosen a larger text size** (a column is at least
    10em; at 100 % six phases are three rows, the wizard's five too), not three: with three columns the review found Japanese labels cut off ("週次の医師リス",
    "連絡とスクリー") at 390 px, which the first version of this card claimed fitted. The old `.steps` rules and their
    phone rule are deleted (the old strip also cut "実施可能性レポート" at 390 px; it no longer does). No new colour, no
    button. `.ps` is the phase strip of review 09; the `ps-` classes of a person's state (deleted by D-1380) are
    another family, and the 9k-4 guard, which looks for `ps-`, does not meet it.
- **The proof:** `tests/unit/test_phase_strip_markup_9k10.py` (per state and language the hidden word, written out in
  the test and not read from the catalogue; one `aria-current`; the six-step call; the states the templates use are the
  table's; the wizard's own label; no `.steps` markup or rule left; the style's tick, underline, forced-colours and
  no-cut rules) and `tests/console/test_phase_strip_9k10.py` (the coordinator's home, the weekly list and the set-up
  wizard in en, ja and zh-TW; Chromium at 390, 800 and 1280 px, and at 390 px in the dark and the contrast mode and
  at 150 % text (10F-1): for every item the label's box lies inside its cell
  and the cell does not scroll, rows within the limit (at most two on a desktop, half the items on a phone), no
  sideways scroll, no one-character line, one current item, the tick only on done and the underline only on current by
  computed style, and in forced colours a line under the current item).
- **Left out:**
  - **Links to each phase's page, and the eight phases of the review** (journey review §D: Visits, Safety, Monitoring,
    Close lit by the EDC): the card is the component; the phases and the EDC's lighting belong to 9k-11 and J-7 and
    plan 9's A-7.4. The item has no link and no state beyond the four. The review's second reason for "off" (a phase
    TrialBox does not carry) is not built either.
  - **No state "off" is produced yet:** no page has a phase a study does not use today; the macro and the style
    carry it so the study switcher (9k-11) can.
  - **`setup.html`'s `ol.wizard-steps`** (four chips with a done state, each an anchor to a section of the same
    form) is a step-like pattern but not `.steps`, which is what the card replaces; its chips are links inside one form
    page that 9k-12 and 9k-14 also edit, they carry no `aria-current`, and they are not a procedure of the study. It
    stays; moving it is a card of its own (the review calls it "a fourth step-like pattern"). `ol.steps-list`
    (handover, set-up help), the life-cycle step table of `life_subject.html`, `dataops_batch.html` and
    `registry_ruleset.html` are not phase strips.
  - **A screen reader says "current step" twice** on readers that also announce `aria-current` (the hidden word and the
    attribute): kept, because the card asks for the hidden word and the attribute is what the strip's source
    (the U.S. Web Design System's step indicator) carries; both are the same sentence, not a conflict.
  - **No role, read or export changes**: the strip shows the same words as before to the same pages.
