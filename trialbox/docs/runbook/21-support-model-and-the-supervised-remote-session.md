# 21. Support model and the supervised remote session

**Reader:** the box owner, and Aimedics.

*T-635, D-390. Closes OPS-038 and OPS-039; the support part of CR-096. The incident plan (severity scale for
incidents, notification clocks, the six cases) is T-318, not this page. The sheet the hospital keeps is
`docs/plan/sites/support-sheet.md` (en, ja, zh-TW).*

**Drill (T-213b):** none yet. The supervised session is not rehearsed by a test: the support-session switch
and its drill are built by card 10K-15, which names the drill here. Until then a tabletop (a ticket is opened,
a session runs to the rules below and is recorded) is the only rehearsal.

## Who answers

| Tier | Who | Does |
| --- | --- | --- |
| 1 | the site administrator (hospital IT or the trial office's named administrator) | first look: the Operations page (§15), `trialbox doctor`, the troubleshooting table (§4); opens the ticket |
| 2 | one named Aimedics person per country, with a named backup | answers the ticket in the site's language; guides the administrator; runs a supervised session when needed |
| 3 | Aimedics engineering | a fix, a signed update bundle (§5), a hardware replacement (§22) |

**Names.** *Default until the owner answers (TB-DR-09 Q6):* tier 2 in both countries is the Aimedics owner of record,
with no backup named yet. The names, phone numbers and mail addresses are written on the site's copy of the support
sheet and the responsibility-boundary sheet, never in this repository (TB-PLAN-06 §10.4 Q-21).

## Hours and languages

The two sites are one hour apart (JST is TST plus one hour). Both get the morning mail at 07:00 local.

| Site | Language | Cover (site time) |
| --- | --- | --- |
| Japan head hospital | Japanese, English | 08:30 to 19:00 JST, working days |
| CGMH | Traditional Chinese, English | 07:30 to 18:00 TST, working days |

*Default until the owner answers (TB-DR-09 Q6):* one person covers both rows from Taiwan, which is why the Japan row
is 08:30 to 19:00 JST (07:30 to 18:00 TST). Outside these hours a ticket waits for the next working morning; the box
keeps working on its own (backups, ingest and night runs need nobody).

**First month after go-live.** Tier 2 checks each site's Operations page every working morning before 09:00 site time
and answers the morning-mail question of §4 the same morning. The on-call list for that month is attached to the
responsibility-boundary sheet.

## Ticket priority

This is the support priority of a ticket. It is not the incident severity of T-318: a suspected privacy incident goes
to the hospital's incident procedure at once (§7), whatever its ticket priority.

| Priority | Example | First answer | Target to fix or work around |
| --- | --- | --- | --- |
| P1 | console down for everyone; no morning mail at all; backup red for more than a day; the box lost | 1 working hour | next working day, on site if needed |
| P2 | one run type fails; the GPU is down and notes are not judged; a certificate ends within 7 days | 4 working hours | 3 working days |
| P3 | a question, a wrong translation, one user cannot sign in | 1 working day | the next release |

## The ticket channel

One mail address per country, given on the support sheet. A ticket carries: the site, the priority, what was seen,
when, the job id if there is one, and the output of `python3 -m tools.trialbox ops status` and `trialbox doctor`
(both hold no patient data). **Never** a patient list, a chart number, a screenshot of a patient page, the pid map or
a key. Before a file is attached, the administrator may run `python -m tools.data_scan --exits <file>` on it (§3; `--exits`: the patterns of what leaves the box, D-747).

**The support bundle (T-209b, D-405).** When support asks for more than that, the administrator runs, on the box:

    sudo python3 -m tools.trialbox support-bundle --out /media/usb

and attaches the one file it writes (`trialbox-support-<time>.tar.gz`). It holds the operations snapshot, the
box's health, the release and update history, `deploy/.env` with secret values redacted, the audit chain's check
(not the chain), `doctor`, `check_host.sh`, `docker compose config` (redacted), restart counts, `df` and
`nvidia-smi`, and the last three collected log days of TrialBox's own services (`--days N` for more). It never holds
`/data`, a volume, a secret, a key, a backup, the audit chain, `settings.yaml` or the PostgreSQL, HAPI and vLLM
logs. The logs are scrubbed, every line the data-handling scan flags is removed, and the run prints what it removed;
the finished file is scanned again, and if anything is still flagged no file is written. `MANIFEST.json` inside
lists every file and what was left out. A file support asks for by name goes in with `--add <file>` (text only; a
path under `/data`, the secrets folder or a backup target is refused).

## The supervised remote session

*For the pilot (the owner, 2026-11-16, D-967):* TrialBox builds no remote session and the box has no remote way in; what follows is the hospital's own screen share from a hospital PC, nothing on the box. After the pilot this stays the default until the owner answers (TB-DR-09 Q2) with the hospital's IT. Aimedics has **no standing remote access**: no account, no VPN, no
open port (IT security pack A.3). When a fix needs Aimedics to see the box, the hospital may start a supervised
screen share. The rules:

1. **The hospital starts it**, with its own approved tool (the one it uses for other vendors), from a hospital PC,
   for one ticket. Aimedics never starts a session and never keeps one open.
2. **The hospital's person is at the keyboard** the whole time. Aimedics watches and says what to type. Aimedics
   does not take control of the keyboard or the mouse, even if the tool allows it.
3. **What may be on screen:** a terminal on the box, the administrator's Operations page (§15), the Jobs page, the
   health tab, `doctor`, logs (they hold pseudonyms only). **Never** a patient page, a patient list, a mail with a
   list, an export or the pid map. Today the administrator role can still open patient data (it loses it with T-102);
   until then the hospital's person does not open those pages during a session, and closes any window that shows one.
4. **No recording, no file transfer** by Aimedics. A file Aimedics needs is sent through the ticket, scanned first.
5. **The record.** The hospital's person writes in the ticket: the ticket number, the start and end time (site
   time), the hospital person, the Aimedics person, and what was done. The ticket is the record: a
   `support.session` audit event is not built yet (T-635 pull request, Remains).
6. **Ending it.** The hospital's person ends the session. If the hospital person must leave, the session ends.

A hospital that allows no screen share at all is supported by phone and the ticket only; the RTO of §22 then assumes
an Aimedics person travels for a hardware fault.

## Hardware return

A failed part under warranty is returned by the hospital to the supplier with Aimedics' help, **after** the disk is
removed or purged (§20, T-628). A disk never leaves the hospital. The replacement path is §22, "Replacing hardware".
