# D-1386 The person card on the weekly list and the cohort list (9k-14)

- **Task:** plan 10 track F, carried card 9k-14 (DS-14) of plan 9 rev 2 §3.5: "Person card in place of three table-to-card
  patterns" (S, waits for 9k-4; proof: no sideways scroll and no clipped column at 390 px on the two lists), from
  review 09 §3.2 component 4 (`<article class="pc">` with pill, why, meta, one button; replaces `table.worklist` cards,
  `pf-cards`, `table.stack`). · **Date:** 2026-11-20
- **What the card asks for:** one component, the person card, instead of the table-turned-card patterns, shown on "the
  two lists" with no sideways scroll at 390 px.
- **What was built:**
  - `templates/_pcard.html`, the macro `person_card(...)`: `<article class="pcard">` with name, figure, date line, "why"
    and state parts. The page that owns a field builds its part and hands it in; the macro reads nothing of a patient.
  - **The two lists the card is proved on: the weekly list (`week.html`, was `table.worklist` and its phone-first
    cards) and the cohort list (`cohort.html`, was `table.worklist`).** One layout at every width: the
    name and the figure, the date and the state, then what is still needed, each with its column's name (from 641 px
    the state sits beside the name and the date). There is no header line and no column to scroll. Every test id of
    the old rows (`row-`, `open-`, `open-n-`, `state-`, `new-`, `mark-`, `sent-back-`, `elsewhere-`, `quick-`,
    `member-`) is on the same element. The old `table.worklist` rules are deleted; the new rules are one block at the
    end of `console.css`.
  - Class names are `pcard`, `pcard-name`, `-met`, `-meta`, `-why`, `-state`, not review 09's `pc` and `pc-why`: the
    badge guard of D-1380 forbids the `pc-` family.
  - The probes that read the old markup follow the new one, with the same checks and no threshold changed:
    `tests/console/cjk_layout.js` (first row: `table.worklist tbody tr` to `.pcards > .pcard`; the box that must not
    scroll sideways: `.scroll:has(> table.worklist)` to `.pcards`), `tests/e2e/phone_walk.js` and
    `tests/e2e/life_cycle_walk.js` (selectors only; e2e cannot run in the lane's container).
- **What was left out:** `pf-cards` on the participant page (`life_subject.html`, the 9k-10 phase strip edits the same
  file), `table.stack` and the other lists that are tables (excluded, SAE worklist, referrals, site people): the card
  names two lists, and "exactly what the card asks" is the weekly and cohort lists. They move in 9k-15 (templates) or
  a later card. A card selected state (`aria-current`) is the row link's, as before. No new words: the card reuses the
  column names the table had.
- **Invariant: no page shows a patient field it did not show before.** The card is a new layout of the same values.
  Held by `tests/console/test_person_card_9k14.py`: `tests/console/data/person_card_9k14_before.json` is what the two
  pages carried on origin/master before the card (every word and attribute value, per role of the role matrix and in
  en and ja, from the seeded synthetic study; captured by the same test with `TB_CAPTURE_9K14`); the test renders the
  pages now and fails if any role gets a value the old page did not carry for it, or a different status code. Roles
  that were refused (403) are still refused.
- **Measured:** `tests/console/test_cjk_layout.py::test_screenshots_ja_and_zh_tw_no_one_character_wrapping`, red on
  master (the ja week list 561 px against its 552 px box), passes with the cards; the check (the list does not scroll
  sideways in its box, the first row starts on the first screen, no one-character lines) is unchanged.
- **Not done:** no role, route, read or export changed; no new text; no new dependency.
