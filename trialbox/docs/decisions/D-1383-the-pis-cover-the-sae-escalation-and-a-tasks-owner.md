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
    never share a day. **What it gives:** the PI's standing in that study (`is_pi`), on the site's days from the first
    to the last day (D-270), and only while the PI covered is still the PI the log names and the covering person's own
    sub-investigator entry is active; nothing in another study; nothing outside the dates; and never the delegation
    log's own rows (adding, changing or ending an entry, entering a cover, a monitor grant: `Standing.own_grant`), so
    the log stays the PI's and the steward's. An investigator account only (another role named by a cover row gains
    nothing). **Where:** one resolution step, `console.teamstore.log_rights`, which both readers of the log ask
    (`console.team.standing`, the console's one permission function of D-147, and `orchestrator.grants.log_standing`,
    which used to hold its own copy of the rule): default deny, every condition checked on every read. The matrix is
    not changed. **Audit:** `console.cover` events: `add` (both names, the dates, the maximum, by the PI), `end_early`
    (by whoever ended it, with the day), `irb_told`, and the cover's `start` and `end` (actor `system:cover`, each
    written once: when a cover is entered for today, when a team page first finds it in effect, and in each morning's
    notice round; an early end writes its end at once). Every event a person writes in that study while holding the
    cover gets `covering_for` (the PI's account and name, the covering person's name and the cover's id) from one step
    in the console's audit writer (`console.cover_pages.CoverAudit`); the actor stays the covering person, never the
    PI. **Mail:** the covering person's morning mail (N1) carries the study, as the PI's does, only while the cover is
    in effect: the study is in N1 because the standing is the PI's that day (the gate of D-273), with one line saying
    whom they cover; nothing is added to the PI's mail, and the covering person gets no more of the study than the
    PI's mail holds. **Pages:** a banner on the study's team pages while a cover is in effect; the cover card on the
    delegation log page (the covers, the PI's form, an early end); a task "tell the IRB of the cover" on the opening
    page until the PI (or the cover) or a coordinator entry of the log marks it done.
  - **Escalation (9f-4 b).** A serious AE the PI has not acknowledged (`needs_ack` of the orchestrator's AE list, and
    no acknowledgement in the register) is mailed, `TB_SAE_ESCALATE_HOURS` hours after the register first had the
    case (`sae_case.created_at`), to each account with an entry active that day on that study's delegation log as
    sub-investigator or coordinator (`crc`); nobody else (not another study's, not an ended entry's, not a coordinator
    off the log, not a monitor grant). **The setting:** declared in `tb_common.config.DECLARED`, default 24, a whole
    number from 1 to 720; anything else stops the console at start. **Once:** one escalation per case and threshold,
    a trail row `escalated` and a `console.sae` event (`action: escalated`, the hours, the time the case was first
    had, who was told, who got the full notice and who the short one, who failed and who had no mailbox) in one
    transaction under a lock per case; a later round does not repeat it. **When:** on each write of the register (an
    AE form saved, an acknowledgement, `POST /studies/{rs}/sae/sync`, the daily notice job) and an hourly round of the
    box's timers (`console.timers`, `:20`). **Content:** the SAE notice the PI already gets at once (D-764,
    `saerecord.office_notice`: study, screening number, event, onset, the day learned, fatal or life-threatening, rule
    set, the deadlines; never the AE term, a chart number or a name), after one line saying why the person is told.
    The screening number and the dates are patient identifiers a sub-investigator without the study's screen task
    cannot read on the SAE pages (`sae_scope`: the delegation log): such a person gets the line and the link only,
    without them (the brief's rule: not sent where the role could not otherwise see them; this is reported to the
    owner). **Never silenced:** no notice setting is read; the timer and the write path run whatever a preference says.
  - **Owner (9f-5).** A task of the opening page (call, find information, prepare, ask a treating doctor, the monthly
    log check, tell the IRB of a cover; `teamstore.TASK_KINDS`) may name an owner: a person with an entry active that
    day on that study's log as PI, sub-investigator, coordinator or other (never a monitor grant). Who may set or
    clear it: the study's PI (or the PI's cover, audited as such) and a person whose own active entry on that log is
    the coordinator's. Each change is a `console.task_owner` event (the task, the owner, the owner before). Who sees a
    task does not change: the owner is shown on the task line to whoever sees the line. Team schema version 5
    (`pi_cover`, `task_owner`), appended in the product's form (D-204, its checksum pinned in `test_migrations`).
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
  router table walked as a covering sub-investigator: the PI's column less the log's own rows inside the dates, the
  account's own answers otherwise).

- **Registries (finisher, for the reviewers).** The two new tables `team.pi_cover` and `team.task_owner` hold staff user
  names and days, no patient data. They are entered in `libs/tb_common/erasure.py` with exactly the treatment of the
  delegation log's tables (the staff rule: nothing to erase for a patient) and in the record inventory on the
  delegation log's row R-04, same class, keeper and retention. The two audit events `console.cover` and
  `console.task_owner` have labels (en, ja, zh-TW) in `services/console/i18n_audit.py`.
