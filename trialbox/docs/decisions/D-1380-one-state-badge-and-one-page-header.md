# D-1380 One state badge fed by one table of tones, and one page header (9k-4, 9k-5)

- **Task:** plan 10 track F, the carried cards 9k-4 (DS-4) and 9k-5 (DS-5) of plan 9 rev 2 §3.5, from review 09
  (`docs/reviews/2026-11-root/09-ux.md` §1.1, §3.2 components 1 and 5, §3.4 rule 1, §5.4). 9k-4 waits for 9k-1
  (D-1368) and J-2 (D-1221, the person's one state); 9k-5 for 9k-3 (D-1375). Seven cards wait on these two: 9k-7,
  9k-10, 9k-13, 9k-14, 9k-15 and, through 9k-1 and these, 10F-2. · **Date:** 2026-11-19
- **Decision, 9k-4:**
  - **A badge is `<span class="pill" data-tone="ok|warn|bad|info|neutral">word</span>`.** The tone comes from one
    Python table, `console/state_tone.py`, keyed by the family of the state (person, life, visit, referral, tier,
    reading, verdict, mark, status, site_patient, job) and the state; the templates ask it through the global
    `tone(family, state)`. A state the table does not know is `neutral`, never an error. The word is the meaning;
    colour only repeats it. `data-state` stays where it was (tests and scripts read it).
  - **The 60 state classes are deleted** (`ps-`, `stt-`, `mk-`, `ref-`, `tier-`, `rd-`, `vd-`, `v-`, `pc-`, `life-`,
    `s-`, and the `st-` row accents) with the second badge class `state`: a job's state is a `pill` too. The row
    accent of a new candidate on the weekly list is `tr[data-status="new"]`. The colours are the old ones, value for
    value: "contacted" was amber as `st-contacted` and green as `stt-contacted` in review 09's count, and is one tone
    now (warn, as the person's state was). States that had no colour (a visit "due", "stopped", "unplanned"; the life
    steps "candidate" and "approached") are `neutral`; the job's running states are `info`.
  - **Left as they were:** the plain tone classes `pill ok`, `pill warn`, `pill bad` that templates choose by a
    computed level (health, backup, update outcome: the admin pages), which are a tone and not a state; their padding
    differs by 1 px and the admin templates are other pull requests' files. They move to `data-tone` with those pages.
- **Decision, 9k-5:**
  - **The page header** is the macro `page_header(title, ctx)` of `templates/_ds.html`: `<header class="ph">`, an
    optional context line (the study), one `h1`, and the page's one primary act as the body of a call block
    (`.ph-act`). **One name per page:** a page sets `{% set page_title = t('key') %}` once; `base.html` puts it in
    `<title>` and the page hands it to the header, so title and heading cannot differ. The menu label is the same key
    where the menu has one (9k-15 moves pages over). The header's phone form (the act in the bottom bar) is 9k-12.
  - **Three pages use it now** (`about.html`, `cmd.html`, `notices_received.html`), to prove the mechanism on the
    real base; the other pages move to it one journey at a time (9k-15).
  - **The rule is a ratchet over every page template:** exactly one `h1`, at most one primary act (a button or
    `.button` link not `secondary`, `quiet` or `danger`), `<title>` equal to the `h1`. Today 3 pages break the first,
    29 the second and 61 the third; `tests/unit/page_header_baseline_9k5.json` lists them: none may join, and one
    that keeps the rule must leave the list.
- **The proof:** `tests/unit/test_state_tone_9k4.py` (every state of the code has a tone, the five tones, the person
  states keep their old colours, no old class in the sheet, a template or a module, the sheet paints the five) and
  `tests/unit/test_page_header_9k5.py` (the ratchet, the header's markup, the title set once). Four console tests that
  matched an old class now match the tone (`test_one_person_state`, `test_text_keys_pages`, `test_step4b`,
  `test_coded_criterion_row`).
- **Not in this card, not verified:** the rule is counted from template text (a button on each branch of an `{% if %}`
  counts once per branch), not on rendered routes: a rendered count over every route belongs to 9k-15 when the pages
  have moved. The pixel difference of the 72 first screens (D-1377) is not measured here: the admin and cascade
  badges lose the 1 px border of the old `state` class on ok, warn and bad.
- **Held by:** `tests/unit/test_state_tone_9k4.py`, `tests/unit/test_page_header_9k5.py`.
