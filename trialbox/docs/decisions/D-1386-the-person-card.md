# D-1386 The person card on the weekly list and the cohort list (9k-14, first of three patterns)

- **Task:** plan 10 track F, carried card 9k-14 (DS-14) of plan 9 rev 2 §3.5, row 286: "Person card in place of three
  table-to-card patterns" (S, waits for 9k-4, proof "No sideways scroll at 390 px"). Review 09 (`09-ux.md` §3.2
  component 4, DS-14) says what the three are, "`table.worklist` cards, `pf-cards`, `table.stack`", and gives the
  proof "no sideways scroll and no clipped column at 390 px on the two lists" (that wording is the review's, not the
  plan's). · **Date:** 2026-11-20
- **What the card asks for:** one component, the person card (`<article>` with pill, why, meta, one button), in place
  of three table-to-card patterns.
- **What this pull request does: one of the three.** It replaces `table.worklist` cards on the two person lists, the
  weekly list (`week.html`) and the cohort list (`cohort.html`). **Remaining, for a follow-up card (9k-14b):**
  `pf-cards` (the participant page's visits and step-trail tables, `life_subject.html`, flag on) and `table.stack`
  (the criteria table of `_criteria.html`). Those two are tables of visits, steps and criteria, not lists of people:
  turning them into cards needs a card variant per kind (a visit, a criterion with its evidence) and rewrites two
  guards that pin their markup (`test_phone_first`, `phone_walk.js`). The other person-shaped tables (excluded, SAE
  worklist, referrals, site people) are not among the card's three patterns. The card stays open until 9k-14b lands;
  10F-3, which waits for 9k-14, should wait for it too.
- **What was built:**
  - `templates/_pcard.html`, the macro `person_card(...)`: `<article class="pcard">` with name, figure, date, state and
    "why". The page that owns a field builds its part and hands it in; the macro reads nothing of a patient.
  - Every part starts with its column's name as text (visible for the date and "why", read out for the figure and the
    state), so a screen reader hears "Criteria met 2/2", "Status ..." and "Still needed ..." apart. The parts are written
    in the order they show on a phone (name, figure, date, state, why). The cohort's cards use h2, so the page has no
    skipped heading level; the cohort's department is plain text, not the warning colour.
  - One layout at every width (from 641 px the state sits beside the name and the date): no header line and no column
    to scroll. Every test id of the old rows (`row-`, `open-`, `open-n-`, `state-`, `new-`, `mark-`, `sent-back-`,
    `elsewhere-`, `quick-`, `member-`) is on the same element. The old `table.worklist` rules are deleted; the new
    rules are one block at the end of `console.css`.
  - **Behaviour that changed, on purpose:** the whole card is one link (review 09: "whole card one link plus one
    button") at every width, where the table made it so only on a phone with the phone-first flag; the quick outcomes
    stay clickable above it, and the text of a card can no longer be selected with the mouse. "Still needed" now shows
    on a phone with the flag off too (it showed on a desktop and with the flag on).
  - **The phone-first flag (D-1222) no longer decides whether the lists are cards.** Its description in en, ja and
    zh-TW and its declared help said "the list's rows are cards ... Off: the pages as before"; they now say what on
    and off do (the list first, the study fold, the menu's two levels, the evidence before the note) and that the
    weekly and cohort lists are person cards with the flag on or off.
  - Class names are `pcard`, `pcard-name`, `-met`, `-meta`, `-why`, `-state`, `-lab`, not review 09's `pc` and `pc-why`:
    the badge guard of D-1380 forbids the `pc-` family.
  - The probes that read the old markup follow the new one, with the same checks and no threshold changed:
    `tests/console/cjk_layout.js` (first row `table.worklist tbody tr` to `.pcards > .pcard`; the box that must not
    scroll sideways `.scroll:has(> table.worklist)` to `.pcards`; the box check still measures overflow, a planted
    unbreakable string makes it fail), `tests/console/test_one_person_state.py::_cell` (a row fragment ends at `</tr>`
    or `</article>`), `tests/console/test_phone_first.py` (the week's visit label is now the card's label text),
    `tests/e2e/phone_walk.js` and `tests/e2e/life_cycle_walk.js` (selectors only; e2e cannot run in the lane's
    container).
- **Measured:** `tests/console/test_cjk_layout.py::test_screenshots_ja_and_zh_tw_no_one_character_wrapping`, red on
  master (the ja week list 561 px against its 552 px box), passes with the cards; the check is unchanged.
- **Invariant: no page shows a patient field it did not show before, and none of its links, forms or buttons is lost.**
  The card is a new layout of the same values. Held by `tests/console/test_person_card_9k14.py`, per person card:
  `data/person_card_9k14_before_matrix.json.gz` and `..._marked.json.gz` are what the two pages carried on
  origin/master (every visible text, link, form, button, hidden input and attribute value, `id` and `data-label`
  included, per person and for the rest of the page) for each role of the role matrix, in en, ja and zh-TW, with the
  phone-first flag off and on, a selected row, and a study with an Approach mark (the quick outcomes). They were
  captured by the same test file run in a `git archive` copy of origin/master. The test fails if a card gains a text,
  an attribute value, a link, a form, a button or an input, or loses a text, link, form, button or input; the only
  words a card may add are the column names, the only attribute values it may lose are `data-label` and the scroll
  box's `tabindex`. A page a role was refused is the same refusal word for word. A test of the test makes the
  comparison fail on a patient link without its address, a patient id in `data-label` or in another attribute, and a
  visible patient id.
- **Not done:** no role, route, read or export changed; no new dependency (the test reads pages with lxml, which the
  test group already has); the column names are the old keys, so no new words except the flag texts.
