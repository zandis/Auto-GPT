# D-1117 the replay takes the site's zone from the run's own record, scores a run on the key it states, and meets no target

- **Task:** lane H, card H-6 (the integrator on PR #639, 2026-11-17 03:08 and 03:24 UTC; the lead's addition of the
  same day: a new launch's gold is built on key v2)
- **PR:** this branch (`claude/lane-h-6-conflicted-pairs`)
- **Date:** 2026-11-17
- **Status:** reserved
- **Builds on:** D-315 (one site zone, no code default), D-1064 item 4 (a target is met only by a launch), D-1104
  (the answer key's versions), D-1111 and D-1112 (the replay)

## Context

Train 65 made the replay's site zone `TB_TZ`, else UTC (D-315). The integrator asked whether launch P1b ran in
another zone, which would move the age lines by a day at the edges, and asked that the zone come from the run's own
record when it has one. D-1064 item 4 rules that a replay's figure is never a met target, while the replay printed
"met". A new launch builds its gold on key v2 natively; the replay would have refused it (its gold is not P1b's
pinned v1) and labelled its gold "v1".

## Decision

1. **The zone.** The replay re-runs a set (the compile and the age lines) in the zone the run's record names:
   `work/set-clock.json` (`tz`, `site_tz`), `work/acc-env.json` (`tz`, `TB_TZ`), or a SCREEN report's
   `provenance.tz` / `provenance.site_tz` (`replay.ZONE_FIELDS`, the first valid IANA name). Without one, `TB_TZ`;
   without that, UTC. `--tz` overrides all three. Each set's report says the zone and where it came from, and what
   the record says when `--tz` differs from it.
2. **Met only by a launch.** Every target's `met` is false in a replay's report, with `met_only_by`. Whether the
   figure lies within the target is a new field, `within_target` (and `within_target_before_screen_only`). The
   printout says "met only by a launch" on every target and "within the target" beside each figure.
   `--require-targets` exits 3 when a figure at the highest level is not within its target. The report's
   `schema_version` is 2; no field was renamed.
3. **The key a folder states.** A set whose `gold/key.json` states v2 is scored as it is: no overlay of P1b's rows and
   no check against P1b's pins. It has no v1 figure ("not scored", with the reason). Each set's report carries
   `key_stated` (the scorer's `key.describe`). A set without `key.json`, or stamped v1, is read as before.

## What it showed on launch P1b

The stored sets (`sigir.tgz`, `jmed.tgz`) record no zone. `set-clock.json` holds the time used and the deadline;
SCREEN's reports say `"clock": "system clock"` with the run and snapshot days; `services.log` and `raw-traces.json`
stamp UTC whatever the site zone is (`tb_common.logging` writes UTC). Re-run under UTC and under Asia/Taipei, no level
(b) figure and none of the 3,198 re-decided verdicts (1,124 of them on age lines) differ. See
`docs/plan/measurements/p1b-replay-2026-11-17.md`.

## Test

`tests/unit/test_h6_replay_zone_and_key_2026_11_17.py`: the zone from the record (and from `TB_TZ`, then UTC, and
`--tz` over all), a name that is no IANA zone left out, a disagreement said; a run stamped v2 scored as it is, with
no v1 figure; no figure of the replay met; `--require-targets` on `within_target`.
`tests/unit/test_h4_replay_2026_11_17.py` asserts `met` false where it asserted a met figure.
