# D-975 the role walk waits for the person's name in the page, then opens the phone's menu to see it

- **Task:** lane D, the owner of the nightly; the integrator's request on #639 (2026-11-16): the role walk's 15 timeouts
  need a cause, not a longer wait
- **PR:** this branch (`agent/NIGHTLY-RED-3-the-role-walk-waits-for-the-header-not-its-menu`)
- **Date:** 2026-11-16
- **Status:** accepted
- **Builds on:** D-110 (the build step 4 browser walk)

## Context

`tests/e2e/test_role_walk.py` (`role_walk.js`: five roles, three languages, desktop and phone) failed every night on
record with 15 of 105 checks red, all `page.waitForSelector: Timeout 20000ms exceeded` on the phone. After signing in,
the walk waited for `[data-testid=whoami]` to be visible. On a phone the name sits in the menu, which `console.css`
folds away until it is opened (`.menu-body { display: none }` under the phone width). Playwright's default wait is for
a visible element, so all fifteen phone walks (5 roles x 3 languages) waited out the 20 seconds. Both the wait and the
folded menu date from the first commit; a longer wait would never have passed. Reproduced locally (the walk needs no
stack): 105 checks, 15 failed.

## Decision

1. The walk waits for the name to be in the page (`state: "attached"`), which is what "signed in" means.
2. On the phone it then opens the menu and checks the name is shown, and closes it again. The walk checks more than it
   did, not less.

## Test

The walk itself: locally `TB_INTEGRATION=1 pytest -m e2e tests/e2e/test_role_walk.py` passes (it failed 15 checks
before the change). The nightly's compose job runs it.
