**D-273 Console privacy guards: one reveal path, the delegation log and the opt-out register on every patient-level
reader, a signed role and study on every chart-number call, and no change kept without its audit event.** Fix group
D-273 of the critical-issues register (`docs/reviews/2026-11-10-critical-issues-register.md`, FG-D and §7.3; plan
v6 `docs/plan/28-master-plan-v6.md` §6.2.1). Closes CR-017, CR-018, CR-019, CR-020, CR-021, CR-022 and CR-055;
PV-15 in part; patches PX-4, PX-5, PX-7 and PX-8 applied. Deep-review findings ROLE-016 (closed) and FIT-023,
ROLE-010 (in part). Branch `claude/tb-fix-d273`. Date: 2026-11-10.

*The problem.* The privacy review (PV-2 to PV-7, PV-15) and the integrity review (DI-5) found that the rules of
D-143 and D-147 were applied page by page. The oldest reveal route, on the job page, had no delegation check, an
optional reason and no opt-out check (CR-017). The delegation log was read on the week, patient, candidate and SAE
pages, not on their siblings (CR-018). The opt-out register was not read on the job page, the registry page, the
excluded list, the orchestrator's reveal or the assistant (CR-019). The orchestrator handed out chart numbers to
any signed name, whatever its role or study, and also for a NAV job (CR-020, PV-15). The opt-out door returned the
pseudonym of any chart number typed into it, with no cap (CR-021). The assistant answered one patient's verdicts to
any patient-data role, with no delegation check and no audit event (CR-022). A mark, a screening number or an
opt-out was committed before its audit event was written (CR-055).

*Decisions.*

1. **One reveal path in the console.** `POST /pilot/jobs/{id}/reveal` goes through `home.apply_reveal`, as the
   patient page, `/api/v1` and the candidate page do: identifier authority for the study, the delegation log for an
   investigator, a reason from the fixed list, a patient on the study's latest list only (so never an opted-out
   patient), and the audit event before the orchestrator is asked. The audit event is `console.reveal_patient`
   with `via=job`. The reason "other" needs a written note of 10 characters or more, kept in the audit record
   (ROLE-016). T-103 still owns the single reveal path across the console and the orchestrator.
2. **Two shared guards on `Helpers`.** `Helpers.delegated(sess, study, path, tasks)` is D-147's rule as one call; it
   is now applied on the excluded list, the screening log and cohort, the `/api/v1` patients and screening log, the
   participants and trial-values pages and their exports (`screen` or `enter_data`), the registry page and its
   export, the job page's candidate rows and the CASE sheet, and the investigator's N1 mail. `Helpers.gone()` is the
   opt-out register now; the job page's rows, the registry page and the excluded list leave those patients out and
   show only a count.
3. **The orchestrator checks the signed role and study.** The console's actor assertion now also covers the
   person's studies (`X-TB-Actor-Scope`, `*` for every study), in the same MAC as the name and role. The reveal and
   the registry export refuse a verified assertion whose role is not one with identifier authority (`admin`,
   `coordinator`, `investigator`, the console's `can_reveal`; D-280 takes `admin` out) or whose scope does not
   cover the study, each refusal audited. The reveal refuses a NAV job and a patient on the opt-out register now.
   The rate limits stay in memory (PV-15, rest).
4. **The opt-out door is no pseudonym oracle.** The page and `/api/v1` no longer return the pseudonym. A chart
   number typed at the door is a lookup: capped per person and hour (`TB_OPTOUT_LOOKUPS_PER_HOUR`, default 30,
   `console.rate_limited` when hit) and audited as `console.chart_lookup` even when nothing changes. Who may use the
   door is still the coordinator and the administrator (OD-5, FG D-280).
5. **The assistant's "why" answer** (`/ask?pid=`, `/api/v1/ask`) needs the study in the account's scope and, for an
   investigator, the delegation log's `screen`; it never answers for an opted-out patient; it is capped at 60 per
   person and hour; each answer is one `console.ask_patient` audit event.
6. **No change without its audit event.** A mark and the screening number it gives are written in one transaction
   and the audit events are appended inside it, before the commit; an opt-out or lift likewise. A failed append
   rolls the change back. The reverse (an event for a change whose commit then failed) is accepted: the trail may
   show an attempt, never miss a change. The site set-up publish writes `setup.publish_begin` before it touches the
   lake.

*Not done here.* The administrator keeps patient-level rights until FG D-280 (OD-5, PV-8, ROLE-010). The reveal
and export rate limits stay in process memory (PV-15). FEAS counts and data-core exports and the opt-out worker are
FG D-278 and T-206a (FIT-023, CR-026, CR-027). `/ask` stays a GET; a purpose prompt for the "why" answer and a POST
are left to T-103.

*Tests.* `tests/console/test_d273_privacy_guards.py`, `tests/unit/test_d273_orchestrator_guards.py`, and the
changed cases in `tests/console/test_console_app.py`, `tests/unit/test_service_auth.py` and
`tests/unit/test_site_setup.py`.
