# D-1121 A tested walk of a new study from its first step, under the stub model, with the testers' page from the same source

- **Task:** lane H, card H-10 (the new-study walk for the owner's testers)
- **PR:** this branch (`claude/lane-h-10-new-study-walk`)
- **Date:** 2026-11-17
- **Status:** reserved
- **Builds on:** D-1062 (steps mode), D-1063 (one sign-in with an acting role), D-540 (the steward names the PI before
  the first approval), D-309 (a short label per criterion on a zh-TW or ja page), D-110 (the browser walks)

## Context

The owner's testers walk a study from its first step on the preview box in steps mode (D-1062). Nothing checked that
the steps they are given still match the console: a renamed button, a page that moved or a permission that changed
would only be found by a tester on the day.

## Decision

1. **The walk.** `tests/e2e/test_new_study_walk.py` (marked e2e) starts the steps-mode box locally: `tools/demo.py`,
   the program the preview VM runs, with demo mode off, the stub model and the synthetic hospital (seed with
   `--day data`, so its data day is fixed). In Chromium (`tests/e2e/new_study_walk.js`, Node Playwright with the
   preinstalled browser, the house style of D-110) it walks one new study per page language (en, zh-TW, ja), each
   under its own new ruleset id: the coordinator pastes the SITE5B criteria (`tools/e2e_simple.py` `SITE_CRITERIA`,
   one text), the data steward names the investigator as PI on the delegation log, the investigator labels (zh-TW,
   ja), opens and approves every criterion, the coordinator runs FEAS, sets who to screen, runs SCREEN and reads the
   candidate list.
2. **What fails it.** A page not reached, a heading, link, button or field label that differs from the product's
   catalogue text, a job state, a missing or present mark (`data-testid` the console already has), and six role
   boundaries, each a real request with the page's own form token that must be answered 403 with the refusal page:
   the coordinator approving, the coordinator naming the PI, anyone approving before the PI is named, the investigator
   sending a protocol in, the steward starting a run, the administrator opening the candidate list. It waits on page
   states, never on time; its test ids are the three language codes.
3. **One source.** `tests/e2e/new_study_walk_plan.py` holds the steps as catalogue keys. The browser's plan and the
   step tables of `docs/handover/new-study-walk.{en,zh-TW,ja}.md` are both written from it; a fast test (no box)
   fails when a page's tables differ from what the plan writes, when a text the walk clicks is missing from a page,
   or when a key is not in the served console's catalogue. A text the product has in English only is marked so on the
   pages (none on 2026-11-17).
4. **Accounts are a parameter** (`TB_WALK_ACCOUNTS`): four accounts (default: the box's seeded crc, stw, pi, admin),
   or one person who switches the acting role (D-1063). The acting role is read from the box's account page; a box
   that offers none skips the walk with the reason it showed. Lane C2's STEPS-ROLE is not on master at `fae5c1f7`,
   so that mode skips today and its switching is untested against a real control.
5. **What it covers and does not.** It shows that the steps, their texts in three languages and the six permissions
   are what the product does on synthetic data under the stub model. It uses no real model and no real data, and it
   measures nothing: its counts (FEAS, SCREEN) come from the stub and the synthetic hospital, and are not checked as
   figures. The stub's reading of text it has not seen (one coded criterion, three for a person) is stated on the
   pages from `services/llm_stub/handlers.py` and checked by a fast test against the stub itself.
6. **How it runs.** A tester walks the page by hand on the preview box. Locally: `make walk-new-study` (about 7
   minutes of seed and about 70 seconds per language on a 4-core container). In CI: no change made here. Proposed:
   the nightly compose job (`make test-compose`, `trialbox-e2e.yml`), which selects every e2e test in `tests/e2e/`
   and so already collects this walk once merged; the fast tests run in the unit tier as they are. The integrator
   decides whether the nightly job's time budget takes the extra 10 to 11 minutes.

## Test

`tests/e2e/test_new_study_walk.py`: the walk in three languages (e2e); the pages hold exactly the plan's tables;
every clicked text is on all three pages; every key is the console's; the pages have the same parts and give no
verdict; the walk's ids are new to the stub and the box; the stub's reading under a new id and under SITE5B; the
accounts parameter.
