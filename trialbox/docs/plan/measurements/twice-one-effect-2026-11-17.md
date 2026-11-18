# Twice has one effect (card V-11), 2026-11-17

Master: `ceae54678f5a06afba4e1526e7ff1d62752192e3`. Lane V: report, do not fix. No product code was changed.

## Verdict

The verdict is the generated block below; nothing outside it adds to it.

<!-- twice:verdict:begin -->
The claim holds only in part: 30 of 50 measured cases left one effect; 20 did not (account_disable_twice, account_reset, approach_twice, back_after_declined, back_consent_after_opt_out, back_mark_after_close, breakglass_end, breakglass_open, edc_switch, notices_race, opt_out, pilot_case, pilot_consent, pilot_request, release, retry_race, route_retry_race, sae_ack, sae_record, timer_twice). 14 findings: 4 High, 8 Medium, 2 Low. Changing console routes: 160 in the live app; 25 driven twice; 135 not driven.
<!-- twice:verdict:end -->

Every count above and below comes from `twice-one-effect-2026-11-17/twice.json`, written by the two test files
when `TB_TWICE_OUT` names this folder. `python tools/twice_check.py --check` compares the marked blocks with it.

## What ran and what did not

- Ran: `tests/console/test_twice_one_effect.py`: the real console routes in process, with the stand-in
  orchestrator of `tests/console/test_console_app.py`, the real data core and lifecycle API of
  `tests/console/test_lifecycle_pages.py`, and the EDC service of `tests/console/test_edc_pages.py`. Each regulated
  route is sent twice with the same session and token by one helper (`twice`). It counts the audit events, mails and
  jobs at the stand-in, and the route's own records, before, between and after. A second event is a second effect
  unless it is written as a refusal (`refused` in its detail) or a no-op (`sent: 0`). A chart-number reveal is an
  access: each reveal is its own audited event (D-280). `tests/unit/test_twice_one_effect_jobs_mail.py`: the mail
  gateway's own `POST /send` and its `deliver`/`drain`, with a stand-in MTA; the orchestrator's own
  `POST /jobs/{job_id}/retry` and job store; the night runner of `tests/unit/test_t726_night_runner.py`.
- Mails: the console box has no gateway outbox. Console mails are counted at the stand-in's `send_notice` and
  `send_test_mail`. Gateway mails are counted at the stand-in MTA.
- Two at once: threads against the in-process apps, each with its own client. Not true parallel HTTP to a running
  box. Where the window is short, the stand-in MTA or the store read waits a moment (0.3 s, 0.1 s); each test says so.
- Not run: compose, a real SMTP server, a real browser (the back button is the earlier form posted again with its
  old token), two orchestrator processes with one timer each (V11-06), and the routes listed at the end.
- Proof the tests can see (worktree only, restored, not committed): with the "duplicate" return of
  `Gateway.deliver` removed (`services/mail_gateway/gateway.py:194`), both `POST /send` cases went red. With a
  closed study allowed to close again (`services/console/sitestore.py:245`), `test_close_a_study_twice` went red.

## Findings

<!-- twice:findings:begin -->
| id | severity | lane | basis | place | claim | ruling |
|---|---|---|---|---|---|---|
| V11-01 | High | C2 | shown | `services/console/home.py:1209 (warned), home.py:1226 (approach_override), home.py:1241 (add_override)` | A second identical Approach (what the code calls no new decision) writes a second IRB-override record and a second console.approach_override event: the override trail overcounts. | - |
| V11-02 | Medium | C2 | shown | `services/console/entry_pages.py:295` | A second identical save of the withdrawal (also enrolment, consent, an SAE form) form changes nothing but answers 'Saved.' and writes a data_entry event with changed 0. | - |
| V11-03 | High | C2 | shown | `services/console/notify.py:420-425 (send_all), notify.py:371 (notice_sent)` | Two 'send now' at once send each person's patient digest (N1, N2) twice: the once-a-day check, the send and the log are not one step. | - |
| V11-04 | Medium | C2 | shown | `services/console/app.py:1321-1330` | Disabling an account that is already disabled writes a second 'disable' audit event with the same Undo toast; a reset sent twice resets twice (two console.user events). | - |
| V11-05 | Low | C2 | shown | `services/console/templates/data_entry.html:39, services/console/entry_pages.py:295` | The enrolment form replayed after a withdrawal is refused as 'correct the 1 marked fields' (a change reason), not as 'the participant is withdrawn'. | - |
| V11-06 | Low | B2 | hypothesis | `services/orchestrator/scheduler.py:196 (_submit), scheduler.py:376 (add_job), tb_common config.py:305` | Calling the timer's entry (scheduler._submit) twice makes two INGEST jobs. The timer itself is one in-memory APScheduler job (id 'ingest', coalesce, max_instances=1), so it was not shown to fire twice; two orchestrator processes on one job store would each have that timer (not run). | - |
| V11-07 | Medium | B2 | shown | `services/orchestrator/core.py:385-415 (retry_scheduled), core.py:404-406` | Two retries of one failed scheduler job at once (POST /jobs/{job_id}/retry, two clients) make two jobs: the 'one already queued' read and the new job are not one step. Hypothesis: the same holds for a list job (two candidate lists). | - |
| V11-08 | High | C2 | shown | `services/console/breakglass.py:189 (POST /breakglass)` | A double click on break-glass open (the CSRF token is fixed for the session, auth.py:762 per the review) makes two grants: two console.breakglass_open events, two notices to the PI and the steward; the second ends the first. | - |
| V11-09 | Medium | C2 | shown | `services/console/team.py:1177 (POST /site/opt-outs)` | A second identical opt-out answers done=same but writes a second console.opt_out event that names what it removed, with nothing marking it a no-op. | - |
| V11-10 | Medium | C2 | shown | `services/console/home.py:1140 (apply_mark)` | An Approach replayed after the study is closed is accepted (303): a new mark row and a new screening number on a closed study. | D-386 has no rule for marks |
| V11-11 | Medium | C2 | shown | `services/console/breakglass.py:217 (POST /breakglass/{gid}/end), services/edc/service.py:143 (set_switch)` | Ending a break-glass grant that is already ended writes a second console.breakglass_end event; switching EDC prefill on when it is on writes a second edc.switch event and switch record. | - |
| V11-12 | Medium | C2 | shown | `services/console/app.py:1946, app.py:2138, app.py:2079, app.py:1583 (the pilot forms)` | A double submit of /pilot/request, /pilot/case, /pilot/consent or /pilot/jobs/{id}/release sends a second job request (a second console.request event and JobCreate at the stand-in). Whether the real orchestrator then makes two jobs was not run. | - |
| V11-13 | Medium | C2 | shown | `services/console/entry_pages.py:295` | After the person opts out, the coordinator's earlier consent and enrolment forms are saved: 2 steps and 5 values written, the participant becomes enrolled. | no decision says whether data entry is refused after an opt-out |
| V11-14 | High | C2 | shown | `services/console/lifecycle_pages.py:476 (sae_ack)` | A second acknowledgement of the same SAE by the investigator (a double click) answers 303 and writes a second console.sae_ack and a second life.sae_ack event: the SAE trail shows two acknowledgements. | - |
<!-- twice:findings:end -->

Each finding shown has a strict xfail test named in `findings.json`; each was confirmed red with `--runxfail`.
V11-06 is a hypothesis and has no test of its own.

## The cases

<!-- twice:cases:begin -->
| case | place | one effect (measured) | finding | counts |
|---|---|---|---|---|
| account_add_twice | `POST /ops/users (add)` | yes | - | `{"accounts": 1, "audit_console_user": 1, "status": [303, 400]}` |
| account_disable_twice | `POST /ops/users (disable)` | no | V11-04 | `{"audit_console_user": 2, "location_second": "/ops/users?undo=viewer#undo", "status": [303, 303]}` |
| account_reset | `POST /ops/users (reset)` | no | V11-04 | `{"events_first": {"console.user": 1}, "events_second": {"console.user": 1}, "first_worked": true, "jobs": [0, 0], "mails": [0, 0], "records": [0, 0, 0], "status": [303, 303]}` |
| approach_twice | `POST /studies/{rs}/patients/{pid}/mark (approach)` | no | V11-01 | `{"audit_approach_override": 2, "audit_pi_mark": 2, "mark_rows": 2, "notices": 0, "override_records": 2, "status_second": 303}` |
| back_after_declined | `POST /studies/{rs}/patients/{pid}/outcome` | no | - | `{"outcomes_added": 1, "status": 303}` |
| back_after_withdrawal | `POST /studies/{rs}/entry (tb_enrolment), POST /studies/{rs}/subjects/{record}/step` | yes | V11-05 | `{"form_message": "The form was not saved. Correct the 1 marked fields and save again.", "state": "withdrawn", "status": [200, 409], "steps_added": 0, "values_added": 0}` |
| back_consent_after_opt_out | `POST /studies/{rs}/entry` | no | V11-13 | `{"opt_out_status": 303, "state": "enrolled", "status": [200, 200], "steps_added": 2, "values_added": 5}` |
| back_mark_after_close | `POST /studies/{rs}/patients/{pid}/mark` | no | V11-10 | `{"close_status": 303, "marks_added": 1, "screening_nos_added": 1, "state": "closed", "status": 303}` |
| back_outcome_after_withdrawal | `POST /studies/{rs}/patients/{pid}/outcome` | yes | - | `{"outcomes_added": 0, "status": 404}` |
| breakglass_end | `POST /breakglass/{gid}/end` | no | V11-11 | `{"events_first": {"console.breakglass_end": 1}, "events_second": {"console.breakglass_end": 1}, "first_worked": true, "jobs": [0, 0], "mails": [0, 0], "records": [0, 0, 0], "status": [303, 303]}` |
| breakglass_open | `POST /breakglass` | no | V11-08 | `{"events_first": {"console.breakglass_notice": 1, "console.breakglass_open": 1}, "events_second": {"console.breakglass_end": 1, "console.breakglass_notice": 1, "console.breakglass_open": 1}, "first_worked": true, "jobs": [0, 0], "mails": [1, 1], "records": [0, 0, 0], "status": [303, 303]}` |
| breakglass_review | `POST /breakglass/{gid}/review` | yes | - | `{"events_first": {"console.breakglass_review": 1}, "events_second": {}, "first_worked": true, "jobs": [0, 0], "mails": [0, 0], "records": [0, 0, 0], "status": [303, 303]}` |
| close_study | `POST /studies/{rs}/state` | yes | - | `{"events_first": {"console.study_state": 1}, "events_second": {}, "first_worked": true, "jobs": [0, 0], "mails": [0, 0], "records": [0, 1, 1], "status": [303, 400]}` |
| consent_twice | `POST /studies/{rs}/entry (tb_consent)` | yes | V11-02 | `{"audit_data_entry": 2, "consents": 1, "second_changed": 0, "status": [200, 200], "values_added_by_second": 0}` |
| dataops_decide | `POST /data-ops/batches/{bid}/decide` | yes | - | `{"events_first": {"dataops.decide": 1}, "events_second": {}, "first_worked": true, "jobs": [0, 0], "mails": [0, 0], "records": [0, 0, 0], "status": [303, 303]}` |
| dataops_decide_api | `POST /api/v1/data/batches/{bid}/decide` | yes | - | `{"events_first": {"dataops.decide": 1}, "events_second": {}, "first_worked": true, "jobs": [0, 0], "mails": [0, 0], "records": [0, 0, 0], "status": [200, 409]}` |
| edc_decide | `POST /studies/{rs}/edc/decide/{draft_id}` | yes | - | `{"events_first": {"edc.decide": 1}, "events_second": {"edc.decide:refused": 1}, "first_worked": true, "jobs": [0, 0], "mails": [0, 0], "records": [0, 0, 0], "status": [303, 409]}` |
| edc_send | `POST /studies/{rs}/edc/send` | yes | - | `{"events_first": {"edc.reconciled": 1, "edc.sent": 1}, "events_second": {"edc.reconciled": 1, "edc.sent:noop": 1}, "first_worked": true, "jobs": [0, 0], "mails": [0, 0], "records": [0, 0, 0], "status": [303, 303]}` |
| edc_sign | `POST /studies/{rs}/edc/sign` | yes | - | `{"events_first": {"edc.sign": 1}, "events_second": {"edc.sign:refused": 1}, "first_worked": true, "jobs": [0, 0], "mails": [0, 0], "records": [0, 1, 1], "status": [303, 409]}` |
| edc_switch | `POST /studies/{rs}/edc/switch` | no | V11-11 | `{"events_first": {"console.edc": 1, "edc.switch": 1}, "events_second": {"console.edc": 1, "edc.switch": 1}, "first_worked": true, "jobs": [0, 0], "mails": [0, 0], "records": [0, 0, 0], "status": [303, 303]}` |
| enrolment_twice | `POST /studies/{rs}/entry (tb_enrolment)` | yes | V11-02 | `{"enrolled_steps": 1, "second_changed": 0, "second_says_saved": true, "status_second": 200, "values_added_by_second": 0}` |
| killed_mid_job | `Orchestrator.run after a restart` | yes | - | `{"killed": ["ADX"], "microbatch_states": ["done", "done"], "work_runs": [["MICROBATCH", "ADX"], ["MICROBATCH", "GZQO"], ["NAV", "NHI1"], ["RETENTION", null]]}` |
| mail_race | `Gateway.deliver, two threads` | yes | - | `{"copies": 1, "states": ["SendUncertain", "sent"]}` |
| mail_refused_then_retry | `Gateway.deliver, Gateway.drain` | yes | - | `{"audit": {"mail.deferred": 1, "mail.duplicate_suppressed": 1, "mail.sent": 1}, "copies": 1, "drains": [{"sent": 1}, {}], "final": "sent", "states": ["queued", "queued"]}` |
| mail_same_key | `Gateway.deliver` | yes | - | `{"audit": {"mail.duplicate_suppressed": 1, "mail.sent": 1}, "copies": 1, "states": ["sent", "duplicate"]}` |
| mail_uncertain | `Gateway.deliver, Gateway.drain` | yes | - | `{"audit": {"mail.duplicate_suppressed": 1, "mail.uncertain": 1}, "copies": 1, "drains": [{}, {}], "final": "uncertain", "states": ["uncertain", "uncertain"]}` |
| night_twice | `night.advance` | yes | - | `{"chain_after": 4, "chain_before": 4, "work_runs": 4}` |
| notices_race | `POST /ops/notices, two threads at once` | no | V11-03 | `{"audit_console_notice": 4, "kinds": ["N2", "N2", "N1", "N1"], "mails": 4}` |
| notices_twice | `POST /ops/notices` | yes | - | `{"audit_console_notice": 2, "kinds": ["N2", "N1"], "mails_after_first": 2, "mails_after_second": 2, "status": [200, 200]}` |
| opt_out | `POST /site/opt-outs` | no | V11-09 | `{"events_first": {"console.opt_out": 1}, "events_second": {"console.opt_out": 1}, "first_worked": true, "jobs": [0, 0], "mails": [0, 0], "records": [0, 0, 0], "status": [303, 303]}` |
| outcome_twice | `POST /studies/{rs}/patients/{pid}/outcome` | yes | - | `{"audit_contact_outcome": 1, "audit_refused": 1, "outcomes": 1, "status": [303, 409]}` |
| pilot_case | `POST /pilot/case` | no | V11-12 | `{"events_first": {"console.request": 1}, "events_second": {"console.request": 1}, "first_worked": true, "jobs": [1, 1], "mails": [0, 0], "records": [0, 0, 0], "status": [303, 303]}` |
| pilot_consent | `POST /pilot/consent` | no | V11-12 | `{"events_first": {"console.request": 1}, "events_second": {"console.request": 1}, "first_worked": true, "jobs": [1, 1], "mails": [0, 0], "records": [0, 0, 0], "status": [303, 303]}` |
| pilot_request | `POST /pilot/request` | no | V11-12 | `{"events_first": {"console.request": 1}, "events_second": {"console.request": 1}, "first_worked": true, "jobs": [1, 1], "mails": [0, 0], "records": [0, 0, 0], "status": [303, 303]}` |
| release | `POST /pilot/jobs/{job_id}/release` | no | V11-12 | `{"events_first": {"console.request": 1}, "events_second": {"console.request": 1}, "first_worked": true, "jobs": [1, 1], "mails": [0, 0], "records": [0, 0, 0], "status": [303, 303]}` |
| requeued_while_running | `JobDB.enqueue + Orchestrator.run (second worker) + retry_scheduled` | yes | - | `{"final": "done", "retry": "refused: the job has not failed", "runs": 1, "second_claim": true, "second_run_state": "running"}` |
| retry_race | `Orchestrator.retry_scheduled, two threads` | no | V11-07 | `{"rounds": [{"answers": ["made", "made"], "jobs_made": 2}, {"answers": ["made", "made"], "jobs_made": 2}, {"answers": ["made", "made"], "jobs_made": 2}, {"answers": ["made", "made"], "jobs_made": 2}, {"answers": ["made", "made"], "jobs_made": 2}]}` |
| retry_twice | `Orchestrator.retry_scheduled (D-474)` | yes | - | `{"ingest_jobs": 2, "second_answer": "a INGEST job of the same study is already queued or running (<job>)"}` |
| reveal_job | `POST /pilot/jobs/{job_id}/reveal` | yes | - | `{"events_first": {"console.reveal_patient": 1}, "events_second": {"console.reveal_patient": 1}, "first_worked": true, "jobs": [0, 0], "mails": [0, 0], "records": [0, 1, 2], "status": [200, 200]}` |
| reveal_patient | `POST /studies/{rs}/patients/{pid}/reveal` | yes | - | `{"events_first": {"console.reveal_patient": 1}, "events_second": {"console.reveal_patient": 1}, "first_worked": true, "jobs": [0, 0], "mails": [0, 0], "records": [0, 1, 2], "status": [200, 200]}` |
| route_retry_race | `POST /jobs/{job_id}/retry (orchestrator), two clients at once` | no | V11-07 | `{"audit_job_retried": 6, "rounds": [{"codes": [200, 200], "jobs_made": 2, "round": 0}, {"codes": [200, 200], "jobs_made": 2, "round": 1}, {"codes": [200, 200], "jobs_made": 2, "round": 2}]}` |
| route_send_retry | `POST /send (mail gateway), outbox between` | yes | - | `{"audit": {"mail.deferred": 1, "mail.duplicate_suppressed": 1, "mail.sent": 1}, "copies": 1, "states": ["queued", "duplicate"], "status": [202, 200]}` |
| route_send_same_key | `POST /send (mail gateway)` | yes | - | `{"audit": {"mail.duplicate_suppressed": 1, "mail.sent": 1}, "copies": 1, "states": ["sent", "duplicate"], "status": [200, 200]}` |
| run_done_again | `Orchestrator.run` | yes | - | `{"state": "done", "work_added": 0}` |
| sae_ack | `POST /studies/{rs}/subjects/{record}/aes/{event}/ack` | no | V11-14 | `{"events_first": {"console.sae": 1, "console.sae_ack": 1, "life.sae_ack": 1}, "events_second": {"console.sae_ack": 1, "life.sae_ack": 1}, "first_worked": true, "jobs": [0, 0], "mails": [0, 0], "records": [0, 0, 0], "status": [303, 303]}` |
| sae_record | `POST /studies/{rs}/entry (tb_adverse_event)` | no | V11-02 | `{"events_first": {"console.data_entry": 1, "console.sae": 2, "data.entry": 1}, "events_second": {"console.data_entry": 1, "data.entry": 1}, "first_worked": true, "jobs": [0, 0], "mails": [1, 0], "records": [0, 1, 1], "status": [303, 303]}` |
| step_twice | `POST /studies/{rs}/subjects/{record}/step` | yes | - | `{"audit_life_step": 1, "status": [303, 409], "steps_added": 1}` |
| timer_twice | `scheduler._submit called twice (what the timer calls; not the timer firing)` | no | V11-06 | `{"ingest_jobs": 2, "work_runs": [["MICROBATCH", "ADX"], ["MICROBATCH", "GZQO"], ["NAV", "NHI1"], ["RETENTION", null]]}` |
| two_confirmers | `POST /ops/accounts/requests` | yes | - | `{"audit_confirmed": 10, "codes": [[200, 409], [200, 409], [200, 409], [200, 409], [200, 409], [200, 409], [200, 409], [200, 409], [200, 409], [200, 409]], "own_two_tabs": [403, 403], "repetitions": 10}` |
| withdrawal_twice | `POST /studies/{rs}/entry (tb_withdrawal)` | yes | V11-02 | `{"audit_data_entry": 2, "audit_life_step": 1, "second_changed": 0, "second_says_saved": true, "status_second": 200, "values_added_by_second": 0, "withdrawn_steps": 1}` |
<!-- twice:cases:end -->

## Changing routes not driven

<!-- twice:not-driven:begin -->
- `DELETE /api/v1/session`
- `DELETE /api/v1/studies/{rs}/sources/redcap`
- `POST /account/password`
- `POST /admin/jobs/{job_id}/cancel`
- `POST /admin/jobs/{job_id}/retry`
- `POST /admin/models/canary`
- `POST /admin/ops/{action}`
- `POST /admin/redcap`
- `POST /admin/redcap/{ref}/test`
- `POST /api/edc/events/v1`
- `POST /api/edc/oidc/token`
- `POST /api/edc/tools`
- `POST /api/edc/tools/{proposal_id}/confirm`
- `POST /api/v1/audit/patients/by-chart`
- `POST /api/v1/audit/verify`
- `POST /api/v1/session`
- `POST /api/v1/site/charts`
- `POST /api/v1/site/checks/{cid}`
- `POST /api/v1/site/codes`
- `POST /api/v1/site/facts/{fid}`
- `POST /api/v1/site/opt-outs`
- `POST /api/v1/studies/{rs}/aes/{record}/{event}/ack`
- `POST /api/v1/studies/{rs}/candidates/{pid}/referral`
- `POST /api/v1/studies/{rs}/conflicts/{cid}`
- `POST /api/v1/studies/{rs}/edc/copy/{record}/tick`
- `POST /api/v1/studies/{rs}/edc/dictionary`
- `POST /api/v1/studies/{rs}/edc/drafts`
- `POST /api/v1/studies/{rs}/edc/drafts/{draft_id}/decide`
- `POST /api/v1/studies/{rs}/edc/import/odm`
- `POST /api/v1/studies/{rs}/edc/send`
- `POST /api/v1/studies/{rs}/edc/sign`
- `POST /api/v1/studies/{rs}/edc/switch`
- `POST /api/v1/studies/{rs}/forms/builtin`
- `POST /api/v1/studies/{rs}/forms/dictionary`
- `POST /api/v1/studies/{rs}/icf`
- `POST /api/v1/studies/{rs}/irb`
- `POST /api/v1/studies/{rs}/monitor/visits`
- `POST /api/v1/studies/{rs}/not-matched/check`
- `POST /api/v1/studies/{rs}/not-matched/sample/{pid}`
- `POST /api/v1/studies/{rs}/not-matched/{pid}/review`
- `POST /api/v1/studies/{rs}/patients/{pid}/mark`
- `POST /api/v1/studies/{rs}/patients/{pid}/outcome`
- `POST /api/v1/studies/{rs}/patients/{pid}/reveal`
- `POST /api/v1/studies/{rs}/referrals/{ref_id}/answer`
- `POST /api/v1/studies/{rs}/sources/{name}/sync`
- `POST /api/v1/studies/{rs}/state/take-back`
- `POST /api/v1/studies/{rs}/subjects/{record}/step`
- `POST /audit/patients/by-chart`
- `POST /audit/verify`
- `POST /data/conflicts/{cid}/resolve`
- `POST /data/instruments/{iid}`
- `POST /demo/ack`
- `POST /enrol`
- `POST /feedback`
- `POST /lang`
- `POST /login`
- `POST /login/first-run`
- `POST /login/first-run/answers`
- `POST /login/totp`
- `POST /logout`
- `POST /ops/flags`
- `POST /ops/identity`
- `POST /ops/ingest`
- `POST /pilot/cascade`
- `POST /pilot/jobs/{job_id}/approval/label`
- `POST /pilot/jobs/{job_id}/approval/tick`
- `POST /pilot/jobs/{job_id}/approve`
- `POST /pilot/mailbox`
- `POST /pilot/propose`
- `POST /pilot/propose/{pid}/confirm`
- `POST /pilot/protocol`
- `POST /pilot/registry/{ruleset}`
- `POST /pilot/registry/{ruleset}/promote`
- `POST /role`
- `POST /settings/notices`
- `POST /site/charts`
- `POST /site/checks/{cid}`
- `POST /site/codes`
- `POST /site/facts/{fid}`
- `POST /site/people/resolve`
- `POST /site/practice`
- `POST /site/remote`
- `POST /site/sheets`
- `POST /site/staff`
- `POST /studies/{rs}/candidates/{pid}/referral`
- `POST /studies/{rs}/candidates/{pid}/reveal`
- `POST /studies/{rs}/conflicts/{cid}`
- `POST /studies/{rs}/deviations`
- `POST /studies/{rs}/edc/copy/{record}/tick`
- `POST /studies/{rs}/edc/dictionary`
- `POST /studies/{rs}/edc/drafts`
- `POST /studies/{rs}/edc/import`
- `POST /studies/{rs}/edc/map`
- `POST /studies/{rs}/excluded/{pid}/review`
- `POST /studies/{rs}/feasibility/refresh`
- `POST /studies/{rs}/forms/builtin`
- `POST /studies/{rs}/forms/dictionary`
- `POST /studies/{rs}/identity`
- `POST /studies/{rs}/irb`
- `POST /studies/{rs}/irb-text`
- `POST /studies/{rs}/irb/icf`
- `POST /studies/{rs}/monitor/visits`
- `POST /studies/{rs}/not-matched/check`
- `POST /studies/{rs}/not-matched/sample/{pid}`
- `POST /studies/{rs}/not-matched/{pid}/review`
- `POST /studies/{rs}/profile`
- `POST /studies/{rs}/redcap-read`
- `POST /studies/{rs}/referrals/{ref_id}/answer`
- `POST /studies/{rs}/referrals/{ref_id}/print`
- `POST /studies/{rs}/sae/sync`
- `POST /studies/{rs}/sae/{record}/{event}/ack`
- `POST /studies/{rs}/sae/{record}/{event}/{what}`
- `POST /studies/{rs}/schedule`
- `POST /studies/{rs}/setup`
- `POST /studies/{rs}/setup/contact`
- `POST /studies/{rs}/setup/log`
- `POST /studies/{rs}/setup/redcap`
- `POST /studies/{rs}/setup/redcap/test`
- `POST /studies/{rs}/setup/sae`
- `POST /studies/{rs}/setup/scope`
- `POST /studies/{rs}/setup/study`
- `POST /studies/{rs}/sources/redcap`
- `POST /studies/{rs}/sources/redcap/detach`
- `POST /studies/{rs}/sources/redcap/undo`
- `POST /studies/{rs}/sources/{name}/sync`
- `POST /studies/{rs}/state/take-back`
- `POST /studies/{rs}/subjects/{record}/undo`
- `POST /studies/{rs}/team`
- `POST /studies/{rs}/team/check`
- `POST /studies/{rs}/team/{eid}`
- `PUT /api/edc/map`
- `PUT /api/v1/studies/{rs}/edc/map`
- `PUT /api/v1/studies/{rs}/records/{record}/forms/{form}`
- `PUT /api/v1/studies/{rs}/schedule`
- `PUT /api/v1/studies/{rs}/sources/redcap`
<!-- twice:not-driven:end -->
