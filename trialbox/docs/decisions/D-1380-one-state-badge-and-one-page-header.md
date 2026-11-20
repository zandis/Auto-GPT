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
  - **Also outside 9k-4:** the verdict *icons* `.critl .ic.vd-*` (the tick, cross and question mark beside a
    criterion) are icons, not pills; they keep their `vd-` classes, and the no-old-class guard looks only for
    `.pill.vd-`. The unused `.prow` rules of the sheet (no template, module or script names the class) are removed
    with the card.
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
  `tests/unit/test_page_header_9k5.py` (the ratchet, the header's markup, the title set once, and the counter's reading
  of both quote styles and of commented-out markup).
- **Six existing tests were changed to the new markup** (the old selector named a class that no longer exists); none
  is weaker than before, and the two that a first edit had weakened were restored:
  - `tests/console/test_one_person_state.py` (registry rows listed): `class="pill ps-listed"` →
    `class="pill" data-tone="neutral" data-state="listed"` (the state and its tone, count still pinned to 5).
  - `tests/console/test_step4b.py` (the current mark after Undo): `class="pill mk-need_info"` → the mark's own
    `<span class="pill" data-tone="...">` element is parsed: tone `warn` and the catalogue's "Need info" words.
  - `tests/console/test_people_lists.py` (`_registry_rows`): `class="pill ps-[a-z_]+" data-state=` →
    `class="pill" data-tone="[a-z]+" data-state=`.
  - `tests/console/test_coded_criterion_row.py` (no met / not met row without a value): `class="pill vd-(pass|fail)"`
    → `class="pill" data-tone="(ok|bad)"`. Like the original loop, it passes if no row matches.
  - `tests/console/test_text_keys_pages.py` (a visit with no date): `class="pill v-unplanned">words<` →
    `class="pill" data-tone="neutral">words<`, count still 2.
  - `tests/console/test_cjk_layout.py` (pills keep CJK words whole): the rule selector `.pill, .state, button, .button`
    → `.pill, button, .button`.
  Also changed for the removed `.state`: `tests/console/cjk_layout.js` (no longer matches `.state`) and
  `tests/unit/test_buttons_9k3.py` (`.state` leaves the "declared once" set).
- **Not built, open as follow-ups:** (1) 9k-5's third part, the menu label equal to the page's title where the menu has
  one (it moves with the pages, 9k-15; the sentence above is the rule, nothing enforces it yet); (2) the every-route
  test that renders each page and counts its `h1` and primary acts.
- **Not in this card, not verified:** the rule is counted from template text (a button on each branch of an `{% if %}`
  counts once per branch; a button drawn by a macro is not counted at all, so a page can show more primary acts than
  the count says; the ratchet reads both quote styles of `extends` and ignores Jinja and HTML comments), not on
  rendered routes: a rendered count over every route belongs to 9k-15 when the pages
  have moved. The pixel difference of the 72 first screens (D-1377) is not measured here: the job pills (admin, cascade,
  job pages) lose the 1 px `--line` border of the old `state` class on ok, warn and bad. A visible change the card does
  not ask for. It is not restored: the person, tier, mark and reading pills never had a border, and one rule on the
  three tones would add one to all of them; a rule for job pills alone would need a selector the table does not give.
  info and neutral keep their border as before.
- **Held by:** `tests/unit/test_state_tone_9k4.py`, `tests/unit/test_page_header_9k5.py`.

## Files outside the card

- `tests/console/test_dataops_full_night.py` (lane J's, 10B-23 / D-1254), and `tests/console/dataops_sources_master.json`
  (used by that test alone, removed). Pull request #1272 was taken off train 108 because this test held the
  data-operations sources section byte for byte against a stored copy of master's markup, and this card changes the
  pill markup that section holds. The integrator's ruling of 2026-11-20: compare with the card against without the
  card, as the J-6 and J-8 flag-off tests do, and keep what the test proves. Lane J reads this file.
  - Before: `test_no_record_and_no_delta_night_is_masters_page_byte_for_byte` rendered the sources section for a night
    with no record (and for one with an unknown record and no delta night) in three languages and compared it with
    the stored `dataops_sources_master.json` (markup rendered from master `f6c42230`).
  - After: `test_no_record_and_no_delta_night_is_the_page_without_this_card` renders that section twice in the same
    run from the current templates, once as they are and once with every 10B-23 part of `dataops.html` (now between
    `{#FN#}` and `{#/FN#}`) taken out, and compares the two byte for byte, for the same two nights and three
    languages. Nothing is stripped (no volatile attribute is on that section), and the pill is the same on both sides.
    It also asserts that the line is absent and that a source is on the page. What it proves is kept: a night with no
    record and no delta night adds nothing to the page. It fails if the card renders even one character in that case
    (shown by a temporary extra character inside the marked parts: both cases failed).
