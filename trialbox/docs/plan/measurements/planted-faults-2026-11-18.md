# Planted faults: does the box tell a person, 2026-11-18 (card H-32, D-1110)

**Reader:** the integrator, lane C2b (the console's health half of V17), lane D (the runbook, backup and doctor) and
lane E (the feed)

**Answer.** Seven faults were planted one at a time on the in-process box (no Docker daemon runs on this machine, so
not the compose box). **None of the seven shows on the administrator's first page** in any of the three languages.
Three (backup target unwritable, disk nearly full, certificate near its end) show in the mail and on `/metrics`; in
the mail their words are English inside the zh-TW and ja mails, and only the backup's own alert mail names a runbook
page. Four show nowhere: the morning mail not sent, the clock off, the model service down while a passing canary
stands, and the feed folder empty (the product holds the night correctly, but tells no one on these surfaces). The
backup target **gone** (the share unmounted, not read-only) shows nowhere either: the night then writes its copy to
the box's own disk and every check stays green. Every fault that showed cleared by itself at the next tick. Of the
runbook pages, the steps that can run here worked for the backup (`backup-status`) and the certificate
(`check-tls`); the disk page's first step looks at disks the health line did not name. The clock and the feed have
no runbook page.

## How it ran

- **Tool:** `tools/planted_faults.py` (`python -m tools.planted_faults run --out <file>`), the drill test
  `tests/e2e/test_planted_faults.py` (`make planted-faults`), the fast test `tests/unit/test_planted_faults.py`.
- **The box:** the console's own app (`console.app.create_app`) with `TB_OPS_RUNNER=inline` (the operations runner,
  the host facts and the health checks of `tb_common.metrics` run in this process), a throwaway PostgreSQL
  (`tools.pglocal`), the orchestrator's in-memory stand-in of the console tests (`FakeBackend`), which is also the
  mail outbox: every notice the console sends is recorded there as the orchestrator's `POST /notices` would hand it
  to the mail gateway. The backup's alert route (`TB_BACKUP_ALERT_CMD`) appends to a file: the second outbox. Three
  administrators (en, zh-TW, ja) and two coordinators (en, ja), all synthetic. Run as root on this container, so the
  backup target and the watched disk are real tmpfs mounts.
- **Each fault:** the box green on every check first; the fault planted; the product's tick (`OpsRunner.write_status`
  as `trialbox ops run` does each minute; the nightly backup and the hourly `backup-status` for the backup; the 07:00
  health mail and the 07:30 digest of a day of the fault's own, as `console.timers` calls them; the adapter's night
  for the feed); the four surfaces read; the fault removed; the tick again; the surfaces read again; the next
  morning's mail round.
- **Runs:** the whole drill twice by `python -m tools.planted_faults run` (record 4 and 5) and once by
  `make planted-faults`, on this branch. The fault-by-surface table was the same in every run.

| Fault | How it was planted | Real or stand-in |
| --- | --- | --- |
| backup target gone | the NAS target (a tmpfs) unmounted, a night run; then mounted again read-only, a night run, `backup-status` | real (root); chmod 0555 when not root |
| disk nearly full | a 16 MiB tmpfs named in `TB_HEALTH_DISKS` (the product's own setting) filled to 94 % | real (root); a stand-in for `shutil.disk_usage` when not root |
| morning mail not sent | the 07:00 and 07:30 timers do not run on the fault's day (timers held back) | real |
| certificate near its end | `TB_TLS_MODE=hospital`, a synthetic certificate that ends in 12 days | real |
| clock off | `TB_NTP_SERVER` names this tool's SNTP server, which answers 600 s behind; the box's own clock not changed | real offset, stand-in time server |
| model service down | the orchestrator's canary gate (the real `Gate`) records the night's canary as unreached (`upstream_down`), as it does when the model servers do not answer; with a passing canary of the morning standing, and (second case) with none | stand-in for the model server |
| feed folder empty | the feed folder emptied after a good night (synthetic site A); the adapter's night (`run_ingest`) on it | real; the lake rebuild is the adapter tests' stand-in hook |

## What a person met

D-1110 says what each word means. "Not in the language": the line is there, but the fault's words are English on a
zh-TW or ja page or mail.

| Fault | First page en | zh-TW | ja | Mail | `/metrics` | Runbook page named | Clears by itself |
| --- | --- | --- | --- | --- | --- | --- | --- |
| backup target unwritable | not shown | not shown | not shown | not in the language (en shown; backup alert route in English) | shown (`backup` red) | yes, §5 by the backup alert mail only | yes: the next night and tick; mail the next morning |
| backup target gone (unmounted) | not shown | not shown | not shown | not shown | not shown (all ok) | no | (nothing to clear) |
| disk nearly full | not shown | not shown | not shown | not in the language | shown (`disk:<path>` red) | no | yes: the next tick; mail the next morning |
| morning mail not sent | not shown | not shown | not shown | not shown (nothing sent) | not shown (no check) | no | the next morning's mail goes |
| certificate near its end | not shown | not shown | not shown | not in the language | shown (`certificate` red) | no | yes: the next tick; mail the next morning |
| clock off | not shown | not shown | not shown | not shown | not shown (no check) | no page exists | doctor's own check only (see H32-09) |
| model service down, passing canary stands | not shown | not shown | not shown | not shown | not shown (`canary` ok) | no | (nothing to clear) |
| model service down, no passing canary | shown | shown | shown | not run here | shown (`canary` warn) | no | not timed |
| feed folder empty | not shown | not shown | not shown | not shown | not shown (no check) | no page exists | the next good night is ingested |

In words: the three faults that `/metrics` sees reach the mail too, but none reaches the first page. The first page
says so itself: "Disk, certificate and the model self-test are in the daily health mail and on /metrics"
(`services/console/admin_i18n.py:17`). The backup tile stays green ("0.0 hours ago") while `backup` is red, because
the tile's colour follows the newest backup's age, not the check (`services/console/templates/admin.html`, tile
`tile-backup`). The health mail and the coordinator's digest translate the level ("システム状態：異常") and then
carry the check's English sentence (`tb_common.metrics` `Check.text`). Each mail went once: a second round on the
same day sent nothing.

**The runbook, followed on the planted fault.**

| Fault | Page | Step (quoted) | Ran here | Result |
| --- | --- | --- | --- | --- |
| backup | `docs/runbook/05-updates-backup-restore-secrets.md:123` | "`python3 -m tools.trialbox backup-status` shows the newest good off-box backup" | yes, 0.12 s | exit 1, "backup ALERT ... the last nightly backup ... failed": it finds it |
| backup | `docs/runbook/05-updates-backup-restore-secrets.md:129` | "Fix the cause, then run `backup-nightly` by hand." | no: Docker | the same nightly function, run after the target was back, passed and cleared every surface |
| disk | `docs/runbook/04-disk-full.md:11` | "`df -h /data /var/lib/docker /` ... Note which disk is full." | yes, 0.00 s | exit 1; the full disk is not among the three paths (H32-12) |
| disk | `docs/runbook/04-disk-full.md:12` | "`python3 -m tools.trialbox backup-status`" | yes, 0.10 s | exit 0, backup OK: as the page says, a check that WAL archiving is not the cause |
| disk | `docs/runbook/04-disk-full.md:15`, `:16` | "`tools/apply_update.sh clean`", "`docker image prune`" | no: a box's `/opt/trialbox`, Docker | not run |
| morning mail | `docs/runbook/04-morning-mail-missing.md:14` | "`docker compose logs console --since 12h` names the timer runs" | no: Docker | not run |
| morning mail | `docs/runbook/04-morning-mail-missing.md:23` | "the administrator's **Send notices now** sends the morning's notices" | yes, 0.05 s | 0 mails, then 0: the box had no study rows and a green health, so there was nothing to send; it never sends the health mail (H32-08) |
| certificate | `docs/runbook/12-certificate-renewal.md:15` | "`python -m console.cli check-tls` warns 30 days before the end." | yes, 0.85 s | exit 0, "note: the certificate ends on 2026-11-30: ask hospital IT for the next one": it finds it |
| certificate | `docs/runbook/12-certificate-renewal.md:21` | "`docker compose up -d --force-recreate caddy`" | no: Docker | not run |
| model | `docs/runbook/04-gpu-fault.md:15`, `:21` | "`nvidia-smi` on the host", "`sudo python3 -m tools.trialbox selftest`" | no: a GPU and Docker | not run |

The four pages each name a drill (`test_runbook_04_disk_full` and the others, "Drill (T-213b)"); those tests are not
written yet (D-390 leaves them to T-213b), so no page's own drill was run here.

## Findings

Severity by plan 8's rule (the findings register's head): Medium, a person slowed or misled, or a document's claim
not true; Low, wording only. Basis: `shown` is this drill's run; `hypothesis` is read from the code.

| Id | Fault | Surface | What a person met | Expected (source) | Severity | Lane |
| --- | --- | --- | --- | --- | --- | --- |
| H32-01 | backup target unwritable | first page | no line in any language; the Backups tile stays green ("0.0 hours ago") while `/metrics` `backup` is red and the mail says RED | "a planted fault shown as one red line on the administrator's first page, the same in the mail and in `/metrics`" (plan 8 criterion 4, V17) | Medium | C2b |
| H32-02 | backup target gone | all | with the NAS share unmounted the night wrote its copy into the empty mount point on the box's own disk; backup ok, every check green, no mail | a target that is not there is a failed night (V17 "backup target gone"; RUNBOOK §5: the copies go to the NAS share and the USB disk) | Medium | D |
| H32-03 | disk nearly full | first page | no line; the page says disks are in the mail and on `/metrics` only | plan 8 criterion 4, V17 | Medium | C2b |
| H32-04 | certificate near its end | first page | no line; the page says the certificate is in the mail and on `/metrics` only | plan 8 criterion 4, V17 | Medium | C2b |
| H32-05 | backup, disk, certificate | mail | the zh-TW and ja health mails and the ja digest translate the level, then give the check in English ("システム状態：異常：certificate ends in 12 days ...") | the card's three languages; D-379's translated health line | Medium | C2b |
| H32-06 | disk, certificate | mail | the health mail and the digest name no runbook page; only the backup's own alert mail does ("docs/RUNBOOK.md §5") | "each has a runbook page that works" (V17) | Medium | C2b |
| H32-07 | morning mail not sent | all | nothing on the first page, in a mail or on `/metrics` says the morning's mails did not go; the product has no check for it | V17 "the morning mail missing"; the runbook itself starts "Users notice first" (`docs/runbook/04-morning-mail-missing.md:5`) | Medium | C2b |
| H32-08 | morning mail not sent | runbook | "Send notices now" sends N1 and N2 only (`console.notify` `send_now`); a missed 07:00 health mail is not sent again by the runbook's step | "sends the morning's notices" (`docs/runbook/04-morning-mail-missing.md:23`) | Low | C2b |
| H32-09 | clock off | all | doctor's clock check FAILs ("the clock is +600.0 s from ..."), but doctor is on no surface: no line, no mail, no `/metrics` check; no runbook page for the clock | V17 "the clock off"; T-211a (OPS-055) | Medium | D |
| H32-10 | model service down | all | with a passing canary of the morning standing, the night's unreached canary changes nothing anywhere (`canary` ok, the gateway's `/healthz` up) until the canary is 36 h old | V17 "a GPU fault"; `docs/runbook/04-gpu-fault.md` "Signs" | Medium | C2b |
| H32-11 | feed folder empty | all | the adapter holds the night (CURRENT kept) and audits it, but no first-page line, no mail, no `/metrics` check; no runbook page for an empty or missing feed | V17's rule applied to the card's seventh fault | Medium | E |
| H32-12 | disk nearly full | runbook | step 1 runs `df` on `/data /var/lib/docker /`; the health line names the full disk by its path (here a `TB_HEALTH_DISKS` disk), which the step does not look at | "Note which disk is full" (`docs/runbook/04-disk-full.md:11`) | Low | D |
| H32-13 | model service down, no canary | first page | the line shows in all three languages but gives no page or step to follow ("it tries again by itself") | "each has a runbook page that works" (V17) | Low | C2b |

Checks the product has that were not among the seven (listed, not walked): `backup_verified` (no key check of a
backup for 90 or 100 days, or a failed restore drill), `optout_worker` (D-441; on the Health tab since J-4),
`derive_batch` (D-442), `desktop_gpu` (a Windows workstation's card held by other programs), `facts` (the host's
runner silent for an hour), the services' `/healthz` list on the Health tab, the watchdog's restart and give-up
audit events (`ops.watchdog.*`), terminology tables the box refuses (E-TERM-3), and doctor's many checks.

## Could not be planted here

- **The compose box.** No Docker daemon runs in this container, so the services did not run as containers: the
  model server could not be stopped (the gate's own record of an unreached canary stands in for it), the mail did not
  pass through the mail gateway (its queue and `mail status` were not seen), and no runbook step that runs `docker`
  was run. Needs: a machine with Docker and the compose stack, then the same tool against it.
- **The digest's mail in a model-down morning with no passing canary** was not run (the variant was read on the page
  and `/metrics` only). The health mail goes daily, so its `[WARN]` line would be there; not verified.
- **A real clock step.** The box's clock was not moved (that would break the container); the time server moved
  instead. After the fault was removed doctor still FAILs here because this container's kernel clock is not
  NTP-synchronised, which is the container's state, not the fault's.
- **PRODUCTION backup rules.** The box runs as TEST, where an on-box target counts; under PRODUCTION an unmounted NAS
  would no longer count as off-box, but the USB disk still would, so H32-02 is expected to stay silent there too
  (hypothesis, not run).

The findings in the register's `--add-from` form are in `planted-faults-2026-11-18/findings.json`. Only lane V edits
the register; this card does not.
