# D-1138 The life-cycle walk on a phone, 390 px wide, reports what does not fit and fixes nothing

- **Task:** lane H, card H-21 (size M): H-20's walk at a 390 px wide viewport
- **PR:** this branch (`claude/lane-h-21-walk-390`), stacked on H-20's (`claude/lane-h-20-life-cycle-walk`)
- **Date:** 2026-11-17
- **Status:** reserved
- **Builds on:** D-1135 (H-20's life-cycle walk), D-1121 (H-10's), D-1062 (steps mode), D-102 and FR-UI-09 (the PI
  list readable on a 390 px phone), `docs/plan/design/09-ui-ux-spec.md` §10 and its WCAG table

## Context

The PI is meant to decide on a phone between patients. The UI spec gives the phone 390 px:

- no horizontal page scroll (WCAG 1.4.10, FR-UI-09);
- targets at least 24 x 24 px, and the PI's mark buttons at least 44 x 44 px (2.5.8);
- the phone's pages: the work lists, the PI home, the approval, the report, the PI's card list and marks;
- "data entry and reveal are desktop only".

No walk had opened the console at that width.

## Decision

1. **The same walk on a phone.** `tests/e2e/test_life_cycle_walk_390.py` (marked e2e) runs H-20's plan and driver
   with a phone's viewport: 390 x 844 px, touch, mobile. It keeps every step, role, language and refusal of H-20's
   walk, and nothing is copied: the driver takes a `viewport`, and a fast test holds the phone plan equal to
   H-20's plan but for it. The phone's code is its own module (`tests/e2e/life_cycle_walk_phone.js`), which the shared
   driver loads only for a plan with a viewport and calls through one-line hooks at its existing places (the browser
   context, a page reached, a click, the menu, an expectation, a stop). Each walk has its own new ids (`LIFEPHONE`, `LIFEPHONEZH`, `LIFEPHONEJA`).
2. **What it measures.** On every page it reaches and before every click, the driver measures:
   - a horizontal page scroll;
   - a control off the screen, or covered where the finger would land;
   - a target under 24 px, a mark button under 44 px, and any other control under 44 px (the card's own size,
     logged as its own kind);
   - text cut;
   - a table wider than the screen (with whether it scrolls in its own frame).
   - a link that sits in a closed group, which it opens first as a person would ("behind a second fold"; the flag
     `layout.phone_first`, D-1222, folds More and the weekly page's study links).

   It measures the box's default layout: the flag is off by default, and a run with it on is shown on the findings
   page beside the findings, not as findings.

   Each measure goes to the step's log with a screenshot, both outside the repository (`TB_WALK_LOG_DIR`). A control
   the phone cannot reach stops the walk there, with what the browser saw.
3. **It reports and fixes nothing.** The findings by step are `FINDINGS` in
   `tests/e2e/life_cycle_walk_390_plan.py`. Each is read from the logs of the runs and states its expectation's
   source, a severity and the owning lane. They are on `docs/handover/life-cycle-walk-390-findings-2026-11-17.md`,
   and a fast test keeps the page equal to the plan. The walk fails when it measures something at a step that no
   finding names, so a new problem is read and recorded, never passed over. It does not fail when the product no
   longer has a problem: it never asserts a fault as correct. The committed files hold no screenshot and no
   patient-like text.
4. **How it runs.** `make walk-life-cycle-390`: one more Makefile target. It takes the box's seed, then about
   3 minutes per language on a 4-core container, and waits on page states, never time. CI is not changed here.

## Test

`tests/e2e/test_life_cycle_walk_390.py` holds:

- the walk on a phone in three languages (e2e);
- the phone's plan equal to H-20's but for the viewport;
- the findings well formed and the page equal to them;
- the new ids new to the stub, the box and the other walks;
- every measure kind the plan names written by the driver;
- the logs' measures summed up.
