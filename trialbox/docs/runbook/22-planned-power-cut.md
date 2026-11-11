# RUNBOOK §22 part: a planned power cut

*T-635 (OPS-074). Japanese hospitals have a yearly legal electrical inspection (法定点検) with the power off for some
hours; any hospital may have planned work on its power.*

**Drill (T-213b):** `test_runbook_22_power_cut` (Docker drill: stop by these steps, a hard host restart, start; the
egress table is closed before Docker starts, the stack comes back, `doctor` has no FAIL).

## Before (a week ahead)

1. Hospital IT tells the site administrator the date and the hours. The administrator tells the study teams: no
   console, no mail answers, no night runs while the power is off.
2. No update in the week before (§5). Check that the last backup is good: `python3 -m tools.trialbox backup-status`.
3. If the cut covers the night, the night's jobs simply do not run; nothing is moved by hand. The next night's ingest
   reads the feed again.

## On the day, before the power goes

1. Make one backup by hand (Operations page, "Back up now", or `python3 -m tools.trialbox backup`) and wait for it.
2. Stop the stack cleanly: `systemctl stop trialbox` (D-377), then shut the host down (`shutdown -h now`).
3. If the box is on a UPS, the UPS is not a reason to keep it on: a clean stop is safer than a battery running out.

## After the power comes back

1. Start the host. The egress unit loads the closed table before Docker, then the stack starts (D-377). If Docker
   does not start, see §4 ("Docker does not start after a reboot"). The disk opens only in the hospital (D-408): a box
   that is not on the hospital network cannot reach its Tang server and waits at the LUKS prompt for the recovery
   passphrase (or the TPM PIN, where the site uses one); nothing starts until someone types it.
2. Unseal the KEK if it is not TPM-sealed (`python -m tools.keys unseal`, §23).
3. `trialbox doctor --env-file deploy/.env`: no FAIL; the clock check passes (a host clock that drifted while off is a
   FAIL until NTP answers).
4. The Operations page: services up, backup age, the runner answers.
5. The next morning: check that the morning mail arrived (§4, "The morning mail did not arrive").
