# The re-run of an interrupted restore starts every service (2026-11-24)

**Reader:** the people who build TrialBox: lane H, the integrator and the independent reviewer.

Card H-126 (the integrator's red 7128848504, from the MVP walk's step 8 on a 16-service box, 7128827356). A double
Ctrl-C 25 s into `sudo trialbox restore --last --key <k> --yes --restart` left caddy, console and llm-verifier
stopped after the data part had finished. The re-run returned 0 and printed "the services run again and are
healthy: 13"; the three stayed stopped, the site stayed down, and `screening.after_restore` stayed `held` with
nothing said about it.

## Cause

H-100's F6 made `--restart` start "only what this command stopped". The re-run never saw the three running, so it
neither stopped nor started them. Its health line counted what compose said ran (restarting and paused included),
compared it with nothing, and called any count "healthy".

## Pull request body (draft)

**1. Every service the box defines.** `--restart` now starts the whole compose project (`up -d --wait`), as an
update starts the box, whatever an earlier run left stopped (`box_restore.BoxRestore.start_and_wait`).

**2. The full expected set, both counts.** After the start the expected set is checked: `compose config --services`
(the box's files and profiles) less the one-shot services (`restart: "no"` in `config --no-interpolate`), with `db`
and whatever this run stopped. Each must run (`ps --status running`, not restarting or paused) and be healthy (no
health check, or `healthy`). The line names both counts: `the services run again and are healthy: 16 of 16`, or
`did not all come back healthy: 15 of 16; not running or not healthy: llm-verifier` with exit 1. When compose cannot
name the services, they are started all the same and the command exits 1 without "healthy".

**3. The hold, said.** After the start the command says the hold on the list jobs: released by the restore, or held
with what releases it (RUNBOOK §5 step 4: the data steward or the administrator, on `/ops/flags`, with the reason).
A re-run is a second restore, so it leaves the box held by design (D-522, review H1); the walk's "stayed held" is
that, now said.

**Tests** (`tests/unit/test_restore_rerun_h126.py`, a stand-in compose that keeps each service's state):

- the invariant, `test_a_rerun_after_a_signal_at_every_step_serves_the_site_or_says_it_does_not`: Ctrl-C and SIGTERM
  at each of six steps (part-way through the stop; in the restore before and after its data part; the container
  ending 130 after its data part; part-way through the start; during the health check), then the same command: the
  first run never says "healthy" and says the box's state; the re-run ends 0 with all 16 running and healthy, the
  site's services up, "16 of 16" and the hold said; no scratch folder is left;
- the walk's box (three stopped, 13 up): one `up -d --wait` for the whole project, "16 of 16", never "13";
- a planted stopped service and a planted unhealthy one: exit 1, "15 of 16", the name, never "healthy";
- the expected set (one-shots out), compose that cannot name the services, the released hold said.

**Mutants.** The old "only what ran before" start (and the expected set as what ran) planted: 16 of 20 tests fail,
all 12 invariant cases among them. The old health line planted: 16 of 20 fail.

**Changed assertions** (the integrator's rulings 7129093062 and 7129949024), in
`tests/unit/test_restore_from_the_host_h100.py`:

- `test_restart_starts_the_services_only_after_a_complete_or_held_restore[0-released-True]` and `[4-held-True]`: old
  `ups[0][-6:] == ["-d", "--no-deps", "--wait", "--wait-timeout", "600", "console"]`; new: exactly one `up`, the whole
  command pinned, `ups == [["docker", "compose", "--project-directory", <deploy>, "up", "-d", "--wait",
  "--wait-timeout", "600"]]`, and `"healthy: 2 of 2"` in the output. Its cases where the restore is neither complete
  nor held (`3-held`, `4-NOT set`, `1`) still assert that no `up` runs.
- `test_the_one_documented_command_restores_the_last_backup_from_a_bare_sudo`: old
  `not ups and "the services run again and are healthy: 0"`; new: exactly one `up`, pinned
  (`["compose", "--project-directory", <deploy>, "up", "-d", "--wait", "--wait-timeout", "600"]`), and
  `"healthy: 1 of 1"`. Its stand-in compose now answers `config --services` and `ps --status running` with `db`;
  `returncode == 4` is unchanged.
- Added: `test_h126_a_service_the_start_leaves_stopped_is_a_shortfall_with_exit_1` (exit 1, "1 of 2", the name).

**The rehearsal** (`tools/rehearse_box/box.sh`, step `live-restore`) adds the walk's case after the good restore: the
same command signalled (SIGTERM twice) once its container has ended, caddy, console and llm-verifier stopped as the
walk's run left them, the command again: exit 0 or 4, "N of N", every service that ran before runs healthy, and the
site answers `/healthz` through caddy with its certificate checked. Not run here (it needs the real box).

**RUNBOOK §5** ("What it says") says the whole project starts, the two counts, the hold, and that an interrupted
restore is run again with the same command.

## Findings

In `restore-rerun-h126-2026-11-24/findings.json` (the register's `--add-from` form).

- **H126-01, High, fixed.** The re-run started only what it stopped; three services stayed stopped, the site down.
- **H126-02, Medium, fixed.** The health line counted what ran and compared it with nothing: a shortfall was exit 0
  and "healthy".
- **H126-03, Medium, fixed (said).** After a held re-run nothing said the hold stood or what releases it.
- **H126-04, Low, open (hypothesis).** Every restore after the first on a box stays held: the earlier restore's
  set-aside audit chain (`_data.pre-restore-*` in the audit volume) is never removed, and `backup.restore` counts it
  as carried. That is D-522's rule as written; whether a set-aside chain whose events were re-applied should stop
  counting is a ruling, not this card.
- **H126-05, Low, open (hypothesis).** When the restore's container itself ends 130 after its data part (the walk's
  first run, `complete: true`), the host's line takes the end as unknown and says "NOT as it was ... do not start the
  services". The re-run is the way back and now works; the first line overstates the damage.
