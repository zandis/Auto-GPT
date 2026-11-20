# D-1383 The PI's cover, the escalation of an unacknowledged SAE and a task's owner, each limited to the study's delegation log (9f-3, 9f-4 (b), 9f-5)

- **Task:** lane K, plan 9 rows 9f-3, 9f-4 (part b only) and 9f-5 (review 02, J-3, J-4, J-5; plan 10 carries them as
  plan 9 states them). · **Date:** 2026-11-20 · **Owner's yes:** 2026-11-20 00:10 UTC: "yes to 9f-3, the escalation
  half of 9f-4 (N a setting, default 24 h), 9f-5 …; each limited to the study's delegation log and audited where it
  widens." Part (a) of 9f-4, the two-week warning before a delegation entry ends, is D-1382's.
- **The limits the owner set, and how each is held:**
  - **Cover (9f-3).** Who may cover: only a person already on that study's delegation log as **sub-investigator**
    (the card names no role; `teamstore.COVER_ROLE`), whose sub-investigator entry covers every day of the cover, and
    who signs in with an investigator account of the study. Who enters it: only the PI the study's log names today
    **by their own entry** (`delegation.keep`, unchanged); never the covering person (refused, 403), never naming the
    PI (refused), never a person under a cover. First and last day are both required; a cover with no end is refused;
    it starts today or later; it lasts **at most 90 days** (`COVER_MAX_DAYS`, both days counted); two covers of a study
    never share a day: the check and the insert are **one transaction under a per-study lock**
    (`pg_advisory_xact_lock`, the SAE register's form), so two requests at once store one cover. No database
    constraint says it: an exclusion constraint on a study and a range of days needs the `btree_gist` extension, which
    the box's store roles cannot create, and an early end or a lapse moves a cover's last day after it is stored;
    migration 5 carries the checks a row can hold alone (`start_day <= end_day`, `entered_on <= start_day`, the PI is
    not the covering person, a known lapse reason). Migration 5 is not on master yet, so it changed in this card; its
    checksum pin in `tests/unit/test_migrations.py` holds the new value. **Chained covers** (90 days, then another 90)
    are allowed: each is entered by the PI by their own entry, the next only once the days are free (the owner ruled 2026-11-20: no limit on a chain).
    **When it gives anything:** on a site day (D-270) from the first to the last day, only while every condition has
    held **on every day since it was entered**: the PI covered is still the PI the log names (from the day it was
    entered), and the covering person's own sub-investigator entry is active (from its first day)
    (`teamstore.cover_state`). Otherwise default deny. A cover that broke (`pi_changed`, `entry_ended`) is **lapsed**:
    it never gives anything again, even when the old PI is named again or the entry is made active again; the lapse is
    stored when first observed (`TeamStore.lapse_cover`: `lapse_reason`, `ended_on` the day after its true last day in
    effect, or its first day when it never took effect), and a new cover must be entered. `log_rights` reads the same
    state on every read, so a lapse not yet observed gives nothing either; the banner shows exactly the cover
    `log_rights` gives. An investigator account only (`console.team.log_account`; another role named by a cover row
    gains nothing); nothing in another study; nothing outside the dates.
    **What it gives: an allow-list** (`teamstore.COVER_RIGHTS`, at the one reading of the log, `log_rights`, carried as
    `pi_rights` into `tb_common.authz.Standing`; `permit` holds a `pi` or `logged_pi` condition under a cover only for
    a listed row; default deny, so a PI row added later is refused under a cover until it is listed):
    `task.screen`, `task.approach`, `task.refer`, `task.enter_data`, `task.run` (the patient pages and reads),
    `command.FEAS`, `command.SCREEN`, `command.CASE` (the runs the PI may start), `edc.view` (the prefill pages' read),
    `notmatched.sample`, `notmatched.send_back` (the weekly sample of criteria-not-matched patients) and
    `team.task_owner` (a task's owner; not a matrix row). SAE acknowledgement and sign-off are the `sae.*` rows of the
    role, not PI rows: the covering person does them in their own name. **Withheld on purpose**
    (`teamstore.COVER_WITHHELD`; the study's administration; the owner ruled 2026-11-20 that a cover gives clinical rights only): `delegation.keep` (the
    log's rows, entering a cover), `delegation.check` (the monthly comparison of the log), `monitor.grant`,
    `study.state` (open, pause, close), `study.reopen`, `study.irb_text`, `irb.edit`, `edc.switch_on`,
    `edc.switch_off`, `breakglass.study`, `profile.research_layers` and `criteria.approve` (the role row the console
    adds the PI's own entry to). `tests/console/test_role_route_matrix_cover.py` pins the two lists against every PI
    row of the matrix and walks the router table under a cover: the PI's column less the log's rows and less every
    route whose declared row is withheld. The orchestrator reads the same list (`orchestrator.grants.log_standing`);
    the console's signed assertion to the orchestrator names one action, and under a cover carries `is_pi` only when
    that action is listed (`console.actor`). **Where:** one resolution step, `console.teamstore.log_rights`, which
    both readers of the log ask (`console.team.standing`, the console's one permission function of D-147, and
    `orchestrator.grants.log_standing`). The matrix is not changed.
    **Audit:** `console.cover` events: `add` (both names, the dates, the maximum, by the PI), `end_early` (by whoever
    ended it, with the day), `irb_told`, and, actor `system:cover`, each once: `start` (only once the cover has taken
    effect: when it is entered for today, when a team page first finds it in effect, the morning notice round),
    `end` (a cover that never broke, once it is over: its last day; an early end writes it at once) and `lapsed`
    (when a lapse is first observed: the reason, the true last day in effect, None when it never took effect, and
    whether it took effect; it stands for the end, no `end` follows). **Stamped events:** every event the console's
    audit writer writes with `actor` `console:<name>` and a `ruleset`, while that account holds the study's cover by
    the same conditions as `standing()` (an investigator account that sees the study, `log_account`), gets
    `covering_for` (the PI's account and name, the covering person's name and the cover's id) from one step
    (`console.cover_pages.CoverAudit`); the actor stays the covering person, never the PI. The stamp is computed when
    the event is written (a request crossing the site's midnight is stamped by the day of its write). A run request
    the orchestrator refuses (`console.refused` with a job) now carries its study, so it is stamped. **Not stamped:**
    events with no study (`console.export` of the research office and of the site, `console.denied`, the account and
    notice events), the system's own events (`system:cover`, the SAE sync), the break-glass notice events (they carry
    no study; `console.breakglass_use` carries one and is stamped), and the orchestrator's own events (they name the
    covering person, without `covering_for`).
    **Mail:** the covering person's morning mail (N1) carries the study, as the PI's does, only while the cover gives
    the PI's standing (the gate of D-273), with one line saying whom they cover. **Pages:** a banner on the study's
    team pages while a cover gives it; the cover card on the delegation log page; a task "tell the IRB of the cover"
    on the opening page until the PI, the PI's cover or a coordinator entry of the log marks it done.
  - **Escalation (9f-4 b).** A serious AE the PI has not acknowledged (`needs_ack` of the orchestrator's AE list, and
    no acknowledgement in the register) is mailed, `TB_SAE_ESCALATE_HOURS` hours after the register first had the
    case (`sae_case.created_at`), to each account with an entry active that day on that study's delegation log as
    sub-investigator or coordinator (`crc`); nobody else. **The setting:** declared in `tb_common.config.DECLARED`,
    default 24, a whole number from 1 to 720; anything else stops the console at start. **Once per case, whatever
    the threshold:** a case with an `escalated` trail row is never escalated again; a later change of N does not
    escalate it again. **The first run after the update** escalates, once each, every unacknowledged case already
    older than N (the first-run burst; stated in the CHANGELOG's Unreleased line). **What is recorded, and when:**
    under a lock per case, inside one database transaction, each recipient is mailed (one mail each), then the trail
    row and the audit event are written: a round that reached at least one person writes the trail row `escalated`
    with each recipient's outcome (`to`, `full`, `short`, `failed`, `unreachable`, the attempt) and a `console.sae`
    event `escalated` naming who was reached and who was not; a round that reached nobody (the gateway down, nobody
    with a mailbox) is **not final**: it writes an `escalate_retry` trail row and a `console.sae` event
    `escalate_unreached` for the first three such rounds only (`ESCALATE_RETRY_NOTES`), and every next round mails
    again until somebody is reached or the PI acknowledges. The audit log is a file outside the database transaction:
    if the commit fails after the mails went and the event was appended, the audit says people were told and the trail
    does not, and the next round mails again (the gateway drops a same-day repeat with the same subject as a
    duplicate). **When:** on each write of the register (an AE form saved, an acknowledgement,
    `POST /studies/{rs}/sae/sync`, the daily notice job) and an hourly round of the box's timers (`console.timers`,
    `:20`). **Content:** the SAE notice the PI already gets (D-764, `saerecord.office_notice`: study, screening
    number, event, onset, the day learned, fatal or life-threatening, rule set, the deadlines; never the AE term, a
    chart number or a name), its first words saying the case still waits for the PI's acknowledgement, after one line
    saying why the person is told and how long it has waited. **Subject:** the orchestrator's duplicate key is day,
    kind, recipients and subject, so the subject names the case: for the full notice exactly as the PI's office notice
    subject does (study, screening number, event); for the short one, the register's case number (the id of the
    case's `create` trail row, `SaeStore.case_no`: a sequence of the register, unique per case, with no patient
    meaning; the SAE pages show such a person nothing of the case). The screening number and the dates are patient
    identifiers a sub-investigator without the study's screen task cannot read on the SAE pages (`sae_scope`): such a
    person gets the line, the link and that case number only. **Never silenced:** no notice setting is read.
  - **Owner (9f-5).** A task of the opening page (call, find information, prepare, ask a treating doctor, the monthly
    log check, tell the IRB of a cover; `teamstore.TASK_KINDS`) may name an owner: a person with an entry active that
    day on that study's log as PI, sub-investigator, coordinator or other (never a monitor grant). The task named must
    be one of THAT study's tasks today as the opening page lists them (`home.task_keys`; any other kind and reference
    is refused, 400). Who may set or clear it (`cover_pages.keeps_tasks`): the PI by their own entry (the row
    `delegation.keep`, the row the route declares in `route_actions.yaml`), the PI's cover (`team.task_owner` in
    `COVER_RIGHTS`, stamped as such) and a person whose own active entry on that log is the coordinator's. An owner
    whose own log entry has ended stays named and is shown as no longer on the log (en, ja, zh-TW); nothing is
    deleted. Each change is a `console.task_owner` event naming the task by the audit trail's convention for a patient
    (the `console.referral` events'): the pseudonym as `pid` for call, find information and prepare, a referral's
    `id`, a cover's `cover`; the owner and the owner before. Who sees a task does not change. Team schema version 5
    (`pi_cover`, `task_owner`), appended in the product's form (D-204, its checksum pinned in `test_migrations`).
  - **Told at once to the cover's person (9f-3, ruled 2026-11-20 08:25 UTC).** The immediate notice of a new
    serious AE (D-764, `sae_pages.office_copy`: the office mailbox and the PI) also goes, **in addition to the PI and
    never instead**, to the person whose cover is in effect that site day in that study (`console.cover_pages`
    `covering_now`: the state the banner and `log_rights` read: in effect, not lapsed; read only, no edge is written).
    It is the same one mail (same subject: study, screening number, event, so two cases the same day are two mails with
    distinct duplicate keys); the audit event `office_copy` names both: `pi` and `covering` (accounts). A covering
    person with no mailbox is a `cover_unreachable` event. The day after the cover ends, a lapsed cover, a cover of
    another study and no cover: the PI only. **The rule for the escalation:** a person told at once as the PI's cover
    has a `told_cover` trail row on that case and is **left out of that case's escalation** (they are not mailed a
    second copy); the escalation's trail and audit name them as `already_told`; a round whose only people left were
    already told is final (nobody is left to reach). Any other case, or the same person on a case before the cover,
    is as before.
- **The owner's ruling (2026-11-20 08:25 UTC, relayed by the integrator), all as recommended:** (1) a cover gives
  clinical rights only, exactly `COVER_RIGHTS` (no study open, pause, close or reopen, no IRB record, no EDC prefill
  switch, no monthly delegation-log check): kept; (2) covers may follow one another, each entered by the PI and
  audited: kept, no limit on a chain; (3) the immediate SAE notice also goes to the covering person inside the cover's
  dates: built, above; (4) a coordinator on the study's log may assign a task's owner: kept; (5) first-run
  escalations accepted and said in the release note (CHANGELOG, Unreleased), then one escalation per SAE and no
  resend when the hours change: kept.
- **Routes:** `POST /studies/{rs}/cover`, `POST /studies/{rs}/cover/{cid}/end`, `POST /studies/{rs}/cover/{cid}/irb`,
  `POST /studies/{rs}/tasks/owner`, each with its `/api/v1` twin, and `GET /api/v1/studies/{rs}/cover`; rows in
  `route_actions.yaml`, the design table regenerated (rows added only).
- **Not built (the owner's yes does not reach them):** the "lead coordinator" per study and "reassign X's open tasks
  to Y" on departure (9f-5's other half); the PI's absence recorded without a cover; a cover entered by the steward;
  the orchestrator's own audit events naming the cover (they name the covering person, as the console's do, without
  `covering_for`).
- **Tests:** `tests/console/test_9f345_cover_escalation_owner.py` (every role of the matrix with and without a cover,
  inside and outside its dates, another study, an ended cover, refusals, both names in the audit, the morning mail's
  gate, the escalation once at N and not before to the right people with N from the setting, the owner on the log,
  the migration up and an older release opening the store); `tests/console/test_role_route_matrix_cover.py` (the whole
  router table walked as a covering sub-investigator: the PI's column less the log's own rows and the withheld rows
  inside the dates, the account's own answers otherwise; the allow-list pinned against every PI row of the matrix).
  The reviews of 813c47eb, each reproduced first (they fail on 813c47eb): two covers entered at once (two
  connections, interleaved at the insert); a lapse written once when first seen, with its reason and true last day,
  no start for a cover that never took effect, never revived; the clinical rights and none of the administration
  under a cover; the API twins refusing another study's PI; two cases told the same day as two mails with distinct
  duplicate keys; a round that reaches nobody tried again; a change of N telling no case again; a task's owner only on
  a task of that study, shown lapsed; `tests/unit/test_optout_clears_the_owed_tables.py` (the owner rows go with the
  patient's tasks and referrals).

- **Registries.** `team.pi_cover` holds staff user names and days, no patient data: in `libs/tb_common/erasure.py`
  with the delegation log's treatment (the staff rule) and on the record inventory's row R-04. `team.task_owner` is
  **patient-linked**: its `ref` is the patient's pseudonym (call, find information, prepare) or the id of the
  patient's referral (ask a treating doctor), so it is registered as `team.referrals` is (`owed_tables`): on opt-out
  the worker deletes the rows of those pseudonyms and the refer rows of the patient's referrals, before the referrals
  (`datacore.optout_worker.OWED_TABLES`); it is on the record inventory's row R-11 with the referrals, and the erasure
  registry page is regenerated. The audit events `console.cover` and `console.task_owner` have labels (en, ja, zh-TW).
- **Another card's test.** `tests/console/test_committees_10c4.py` (10C-4) pinned the committee tables' reader to the
  team store's last migration; this card's fifth migration had loosened it to `>=`. It is restored at full strength:
  the reader's version is exactly the migration that makes the committee tables, no other migration names them, and
  there are exactly five migrations, so a sixth makes the guard be looked at again.
