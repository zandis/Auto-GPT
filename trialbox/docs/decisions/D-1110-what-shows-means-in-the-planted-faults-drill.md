# D-1110 What "shows" means in the planted-faults drill

- **Task:** lane H, card H-32 (plan 8, V17: "the box tells a person when something is wrong"; was lane V's V-7)
- **PR:** this branch (`claude/lane-h-32-planted-faults`)
- **Date:** 2026-11-18
- **Status:** reserved
- **Builds on:** D-379 (T-209a, the health checks, the health mail and `/metrics`), D-441 and D-1224 (the opt-out
  worker's line), D-735 (the backup alert route), D-915 (the canary waiting for the models), D-390 (the runbook's
  site pages)

## Context

Plan 8's V17 and release criterion 4 ask that a planted fault shows "on the administrator's first page, the same in
the mail and in `/metrics`", with "a runbook page that works". Card H-32 plants seven faults (backup target gone,
disk nearly full, morning mail not sent, certificate near its end, clock off, model service down, feed folder empty)
and has to say, for each, whether it showed. Without a rule a pill that turns red, a line on a second tab, or an
English sentence inside a Japanese mail would each be counted one way by one reader and the other way by the next.

## Decision

For this drill (`tools/planted_faults.py`, `tests/e2e/test_planted_faults_drill.py`):

1. **The first page** is the page sign-in lands an administrator on: `/home`, which for an administrator is the
   `/admin` Health tab. It is read as text, as a person reads it. A fault **shows** there when a line that the green
   page does not have names the fault in the page's language. A colour, a pill or a `data-level` attribute that
   changes while the words stay the same does not show it; a line on another tab or page does not show it on the
   first page. A new line that names the fault only in English on the zh-TW or ja page is **not in the language**.
2. **The mail** shows a fault when a mail that the administrators (or whoever the product names) get in the round
   after the fault (the 07:00 health mail and the 07:30 digest of that day, as the console's timers call them, and
   the backup's own alert route) has a line that names it, in the reader's language. A line that says a check is
   fine (`- [ok] ...`) does not count. A translated level before an English check text is **not in the language**.
   A second round on the same day must send nothing more (once).
3. **`/metrics`** shows a fault when a `tb_health_check_level` line of the fault's own check leaves 0 (ok). When
   only another check moves, it is "shown by another check".
4. **The runbook** is named when the new line or the mail carries a path below `docs/runbook/`, `RUNBOOK §n` or
   `docs/RUNBOOK.md §n` (resolved to that section's page), or a link. A page **works** when it exists and its steps
   that can run on the drill's box, run as written (the box's deploy folder where the page's command reads
   `deploy/`), give the next action; a step that needs Docker or a GPU is listed with what it needs, not run.
5. **Clears by itself** means: after the fault is removed and the product's own next tick (`trialbox ops run`, the
   nightly backup, the next 07:00 mail) has run, with no person acting, the three surfaces no longer show it.
6. **The box** is the one this machine can run. Where no Docker daemon runs it is the in-process box
   (`TB_OPS_RUNNER=inline`) with the orchestrator's stand-in; each fault says whether it is the real condition or a
   stand-in for it, and a fault that cannot be planted is listed with what it needs.

## Consequences

- The drill's table (fault by surface) is the findings page's table, and the drill test fails when the two differ:
  a fix that makes a fault show changes both in one pull request.
- A fault that the product has no check for (the morning mail, the clock on the health surfaces, the feed) is "not
  shown" on every surface; that is a finding, not a gap in the drill.
- The rule is for this drill. The console's own rule for banners (plan 9, DS-9) is lane J's.
