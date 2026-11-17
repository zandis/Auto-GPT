# Twice has one effect (card V-11), 2026-11-17

Master: `ceae54678f5a06afba4e1526e7ff1d62752192e3`. Lane V: report, do not fix. No product code was changed.

## Verdict

The claim holds only in part. The lifecycle step, the consent, enrolment and withdrawal forms, the contact
outcome, the account add, the second-person confirm, the send keys of the mail gateway, a done job run again and
a worker killed mid-job each left one effect. But a double Approach doubles the mark and the IRB-override record
(V11-01), two "send now" at once mail each person's patient digest twice (V11-03), and two retries at once make two
jobs (V11-07).

<!-- twice:verdict:begin -->
23 cases measured; 14 held one effect; 9 did not. 7 findings: 2 High, 4 Medium, 1 Low. Changing console routes: 160 in the live app; 7 driven twice; 153 not driven.
<!-- twice:verdict:end -->

Every count above and below comes from `twice-one-effect-2026-11-17/twice.json`, written by the two test files
when `TB_TWICE_OUT` names this folder. `python tools/twice_check.py --check` compares the marked blocks with it.

## What ran and what did not

- Ran: `tests/console/test_twice_one_effect.py` (the real console routes, in process, with the stand-in
  orchestrator of `tests/console/test_console_app.py` and the real data core and lifecycle API of
  `tests/console/test_lifecycle_pages.py`); `tests/unit/test_twice_one_effect_jobs_mail.py` (the mail gateway's
  `deliver` and `drain` with a stand-in MTA; the real orchestrator and job store of
  `tests/unit/test_t726_night_runner.py`).
- Two at once: threads against the in-process app (each with its own client and session), and threads on the
  orchestrator object. Not true parallel HTTP to a running box. Where the window is short, the stand-in MTA or the
  store read waits a moment (0.3 s, 0.1 s); that is said in each test.
- Not run: compose, a real SMTP server, a real browser back button (the replay is the earlier form posted again with
  its old token), and 153 of the 160 changing routes (listed at the end; not driven for the budget, in the card's
  priority order).
- Proof the tests can see: with the "duplicate" return of `Gateway.deliver` removed in the worktree
  (`services/mail_gateway/gateway.py:194`), `test_the_same_send_key_twice_is_one_copy` went red
  (`('sent', 'sent') != ('sent', 'duplicate')`). The file was restored; not committed.

## Findings

<!-- twice:findings:begin -->
| id | severity | lane | basis | place | claim |
|---|---|---|---|---|---|
| V11-01 | High | C2 | shown | `services/console/home.py:1238 (store.mark), home.py:1241 (add_override)` | A second identical Approach writes a second mark, a second IRB-override record and second override and mark audit events. |
| V11-02 | Medium | C2 | shown | `services/console/entry_pages.py:295` | A second identical save of the withdrawal (also enrolment, consent) form changes nothing but answers 'Saved.' and writes a data_entry event with changed 0. |
| V11-03 | High | C2 | shown | `services/console/notify.py:420-425 (send_all), notify.py:371 (notice_sent)` | Two 'send now' at once send each person's patient digest (N1, N2) twice: the once-a-day check, the send and the log are not one step. |
| V11-04 | Medium | C2 | shown | `services/console/app.py:1321-1330` | Disabling an account that is already disabled writes a second 'disable' audit event and answers with the same Undo toast. |
| V11-05 | Low | C2 | shown | `services/console/templates/data_entry.html:39, services/console/entry_pages.py:295` | The enrolment form replayed after a withdrawal is refused as 'correct the 1 marked fields' (a change reason), not as 'the participant is withdrawn'. |
| V11-06 | Medium | B2 | shown | `services/orchestrator/scheduler.py:196 (_submit)` | The ingest timer fired twice for one night makes two INGEST jobs; both run. The night's chain after it still runs once. |
| V11-07 | Medium | B2 | shown | `services/orchestrator/core.py:385-415 (retry_scheduled), core.py:404-406` | Two retries of one failed scheduler job at once make two jobs: the 'one already queued' read and the new job are not one step. Hypothesis: the same holds for a list job (two candidate lists). |
<!-- twice:findings:end -->

Each finding has a strict xfail test (named in `findings.json`); each was confirmed red with `--runxfail`.

Where the product already keeps one effect, it says so plainly: a repeated lifecycle step is refused with "Not
saved: the participant is already at this step." (409); a second contact outcome the same day is refused (409) and
recorded as `console.refused`; a second account add answers 400 "exists"; the second confirmer of an account request
gets 409 "this request is no longer waiting" (10 of 10 rounds); the requester from two tabs is refused twice (403).
An uncertain mail stays uncertain until a person decides (`trialbox mail resolve`, T-108c, D-401): one copy.

Not a finding, a question: after "reached, declined", the earlier "reached, booked" form replayed is accepted and
adds an outcome (`back_after_declined`). No written rule says a declined contact is final.

## The cases

<!-- twice:cases:begin -->
| case | place | one effect | finding | counts |
|---|---|---|---|---|
| account_add_twice | `POST /ops/users (add)` | yes | - | `{"accounts": 1, "audit_console_user": 1, "status": [303, 400]}` |
| account_disable_twice | `POST /ops/users (disable)` | no | V11-04 | `{"audit_console_user": 2, "location_second": "/ops/users?undo=viewer#undo", "status": [303, 303]}` |
| approach_twice | `POST /studies/{rs}/patients/{pid}/mark (approach)` | no | V11-01 | `{"audit_approach_override": 2, "audit_pi_mark": 2, "mark_rows": 2, "notices": 0, "override_records": 2, "status_second": 303}` |
| back_after_declined | `POST /studies/{rs}/patients/{pid}/outcome` | yes | - | `{"outcomes_added": 1, "status": 303}` |
| back_after_withdrawal | `POST /studies/{rs}/entry (tb_enrolment), POST /studies/{rs}/subjects/{record}/step` | no | V11-05 | `{"form_message": "The form was not saved. Correct the 1 marked fields and save again.", "state": "withdrawn", "status": [200, 409], "steps_added": 0, "values_added": 0}` |
| consent_twice | `POST /studies/{rs}/entry (tb_consent)` | no | V11-02 | `{"audit_data_entry": 2, "consents": 1, "second_changed": 0, "status": [200, 200], "values_added_by_second": 0}` |
| enrolment_twice | `POST /studies/{rs}/entry (tb_enrolment)` | no | V11-02 | `{"enrolled_steps": 1, "second_changed": 0, "second_says_saved": true, "status_second": 200, "values_added_by_second": 0}` |
| killed_mid_job | `Orchestrator.run after a restart` | yes | - | `{"killed": ["ADX"], "microbatch_states": ["done", "done"], "work_runs": [["MICROBATCH", "ADX"], ["MICROBATCH", "GZQO"], ["NAV", "NHI1"], ["RETENTION", null]]}` |
| mail_race | `Gateway.deliver, two threads` | yes | - | `{"copies": 1, "states": ["SendUncertain", "sent"]}` |
| mail_refused_then_retry | `Gateway.deliver, Gateway.drain` | yes | - | `{"copies": 1, "drains": [{"sent": 1}, {}], "final": "sent", "states": ["queued", "queued"]}` |
| mail_same_key | `Gateway.deliver` | yes | - | `{"copies": 1, "states": ["sent", "duplicate"]}` |
| mail_uncertain | `Gateway.deliver, Gateway.drain` | yes | - | `{"copies": 1, "drains": [{}, {}], "final": "uncertain", "states": ["uncertain", "uncertain"]}` |
| night_twice | `night.advance` | yes | - | `{"chain_after": 4, "chain_before": 4, "work_runs": 4}` |
| notices_race | `POST /ops/notices, two threads at once` | no | V11-03 | `{"audit_console_notice": 4, "kinds": ["N2", "N2", "N1", "N1"], "mails": 4}` |
| notices_twice | `POST /ops/notices` | yes | - | `{"kinds": ["N2", "N1"], "mails_after_first": 2, "mails_after_second": 2, "status": [200, 200]}` |
| outcome_twice | `POST /studies/{rs}/patients/{pid}/outcome` | yes | - | `{"audit_contact_outcome": 1, "audit_refused": 1, "outcomes": 1, "status": [303, 409]}` |
| retry_race | `Orchestrator.retry_scheduled, two threads` | no | V11-07 | `{"rounds": [{"answers": ["made", "made"], "jobs_made": 2}, {"answers": ["made", "made"], "jobs_made": 2}, {"answers": ["made", "made"], "jobs_made": 2}, {"answers": ["made", "made"], "jobs_made": 2}, {"answers": ["made", "made"], "jobs_made": 2}]}` |
| retry_twice | `Orchestrator.retry_scheduled (D-474)` | yes | - | `{"ingest_jobs": 2, "second_answer": "a INGEST job of the same study is already queued or running (01M7NE5NC22XG6C2KEXFBV8QX7)"}` |
| run_done_again | `Orchestrator.run` | yes | - | `{"state": "done", "work_added": 0}` |
| step_twice | `POST /studies/{rs}/subjects/{record}/step` | yes | - | `{"audit_life_step": 1, "status": [303, 409], "steps_added": 1}` |
| timer_twice | `scheduler._submit (the timer)` | no | V11-06 | `{"ingest_jobs": 2, "work_runs": [["MICROBATCH", "ADX"], ["MICROBATCH", "GZQO"], ["NAV", "NHI1"], ["RETENTION", null]]}` |
| two_confirmers | `POST /ops/accounts/requests` | yes | - | `{"audit_confirmed": 10, "codes": [[200, 409], [200, 409], [200, 409], [200, 409], [200, 409], [200, 409], [200, 409], [200, 409], [200, 409], [200, 409]], "own_two_tabs": [403, 403], "repetitions": 10}` |
| withdrawal_twice | `POST /studies/{rs}/entry (tb_withdrawal)` | no | V11-02 | `{"second_says_saved": true, "status_second": 200, "values_added_by_second": 0, "withdrawn_steps": 1}` |
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
- `POST /api/v1/data/batches/{bid}/decide`
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
- `POST /breakglass`
- `POST /breakglass/{gid}/end`
- `POST /breakglass/{gid}/review`
- `POST /data-ops/batches/{bid}/decide`
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
- `POST /pilot/case`
- `POST /pilot/consent`
- `POST /pilot/jobs/{job_id}/approval/label`
- `POST /pilot/jobs/{job_id}/approval/tick`
- `POST /pilot/jobs/{job_id}/approve`
- `POST /pilot/jobs/{job_id}/release`
- `POST /pilot/jobs/{job_id}/reveal`
- `POST /pilot/mailbox`
- `POST /pilot/propose`
- `POST /pilot/propose/{pid}/confirm`
- `POST /pilot/protocol`
- `POST /pilot/registry/{ruleset}`
- `POST /pilot/registry/{ruleset}/promote`
- `POST /pilot/request`
- `POST /role`
- `POST /settings/notices`
- `POST /site/charts`
- `POST /site/checks/{cid}`
- `POST /site/codes`
- `POST /site/facts/{fid}`
- `POST /site/opt-outs`
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
- `POST /studies/{rs}/edc/decide/{draft_id}`
- `POST /studies/{rs}/edc/dictionary`
- `POST /studies/{rs}/edc/drafts`
- `POST /studies/{rs}/edc/import`
- `POST /studies/{rs}/edc/map`
- `POST /studies/{rs}/edc/send`
- `POST /studies/{rs}/edc/sign`
- `POST /studies/{rs}/edc/switch`
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
- `POST /studies/{rs}/patients/{pid}/reveal`
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
- `POST /studies/{rs}/state`
- `POST /studies/{rs}/state/take-back`
- `POST /studies/{rs}/subjects/{record}/aes/{event}/ack`
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
