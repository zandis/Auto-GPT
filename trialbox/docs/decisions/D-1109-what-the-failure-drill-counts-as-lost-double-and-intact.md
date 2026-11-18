# D-1109 What the failure drill counts as a lost job, a double mail and an intact audit chain

- **Task:** lane H, card H-31 (was lane V's V-6; plan 8 V12, "each service killed in turn during a night: no lost job,
  no double mail, an intact audit chain")
- **PR:** this branch (`claude/lane-h-31-failure-drill`)
- **Date:** 2026-11-18
- **Status:** proposed

## Context

Plan 8's V12 asks for a failure drill under compose and names three results without saying how each is counted. A
drill that counts them its own way each time cannot be compared night to night, and a red night must open a card the
same day (plan 9 rev 2, V12). The drill is `tools/failure_drill.py` (logic) and `tools/failure_drill_box.py` (the
compose test stack); `make failure-drill` runs it.

## Decision

The drill compares each drilled night with a **control night**: the same night's work on a fresh stack with no kill.
Everything is read from the product's own records after the night is finished or its window ends.

1. **A lost job.** A unit of the night's work is a job's type, study and origin (`mail`: a mailed command; `timer`:
   the scheduler's own, the night's chain included; `person`). A requeue, a retry and a second start of the same unit
   are the same unit. For every unit of the control night, the drilled night must have one job `done`, or one
   `failed` with a reason a person can read (the job's `error.message`; such a job can be retried: the administrator's
   retry for a timed job, a new mail for a mailed one), or a job in `awaiting_approval` (it waits for a person by
   design). A unit is **lost** when it has no job, when its job is in any other state at the end (stuck), or when it
   failed with no reason. A unit **done twice** fails the check too (not exactly once).
2. **A double mail.** The hospital's mail server (Mailpit on the test stack) holds at most one message per recipient
   and subject (the subject names the job). A key left `sending` in the gateway's outbox (`mail.send_keys`) at the end
   fails the check (a send that may or may not have left, with nobody told). Keys held `uncertain` or `failed` are
   listed: they wait for a person (`trialbox mail resolve`) and are not doubles. A mail the control night sent and
   the drilled night did not is reported as **missing**; it does not fail this check (the job check says why).
3. **An intact audit chain.** The product's verifier (`tools/audit_verify.py /data/audit` in the orchestrator's
   container) exits 0; every row of the audit journal (`audit.journal`) is in the chain (no journal row missing from
   it at the end: no gap at the kill); and the chain has more lines at the end than at the kill (a box that stopped
   auditing is not intact).

A kill is `kill -9` of the container's first process from the host (a crash: Docker's restart policy applies; `docker
kill` is a person's stop and is not used). The box recovered **by itself** when the killed service and every other
service are running and healthy within 300 s without a step by the drill; a step by the drill (the watchdog, then
`docker compose up -d`) is recorded as such and is a finding when no runbook page says to take it.

## Consequences

- The three counts are the same in every run and on every machine; the record of a target names the kill, its stage,
  the recovery and each count.
- A unit the control night did not run (a weekly step on another weekday) is not asked of the drilled night.
- Severity follows the findings register's rule: an audit chain that can be wrong is High; a job lost or a mail sent
  twice to a person is High (a patient wrongly left out or told twice); a recovery that needs a person with no page
  is Medium.
