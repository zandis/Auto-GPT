# D-488 The audit says who wrote it: the drain checks each event's name against the database role that sent it, and its time against the journal's

- **Card:** T-721 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.2, TB-PLAN-06.1; wave T, safety core)
- **PR:** this branch (`agent/T-721-audit-says-who-wrote-it`)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI)
- **Builds on:** D-394 (one writer of the audit chain; the journal records the database role), D-378 (a role per
  service), D-451 (the audit browser)
- **Closes:** finding F10 and proposal TR-10 of `docs/reviews/2026-11-12-architecture/trust.md`, its first half
  (see "Not done")

## The problem

Every service sends its audit events to the append-only `audit.journal`, which records the database role that sent
each row (`session_user`, which the sender cannot choose). The event's name, its `actor` and its time are the
sender's. The mail gateway's role can append `screen.reveal` with `actor=dr_tanaka` and a time of last week; the
chain line carries `journal.role=tb_mail_gateway`, and nothing reads it: not the drain, not `tools/audit_verify.py`,
not the audit browser.

## The decision

1. **A table of who writes what** (`tb_common.audit_writer.ROLE_EVENTS`): for each service's database role, the
   event families (the part of a name before the first dot) it writes. The console and the orchestrator host the
   shared libraries, so their rows are wide: everything written anywhere in the modules they import. A service
   that reads outside input (the mail gateway, the model gateway, the lake, the adapter, the criteria compiler)
   has exactly what its own folder writes, plus named extras with a reason (`EDGE_EXTRA`: the compiler's `llm`).
   None of them may write `console`, `screen`, `registry`, `edc`, `life`, `job`, `data`, `actor`, `study`,
   `optout` or `audit`. The host's administrator role (`trialbox`) is not judged.
2. **The drain marks** (`flags_of`, in `Drain.step`): `role` when the event's family is not in the sending role's
   row, `unknown role` for a role the table does not know, and `time` when the event's own time is further from
   the time the journal received it than `TB_AUDIT_TS_MAX_SKEW_S` (default 300 seconds; a setting with its reason,
   OD-10: a service stamps an event when it happens and sends it in the same request to a database on the same
   host). The mark is a field of the record the event is written in, `journal: {seq, role, at, flag: [...]}`, so
   there is no moment at which the event is in the chain without it, a restart cannot lose it, and it is under
   the chain's hash. The event itself is written as it was sent: the chain keeps what was said, and says it
   should not have come from there. Nothing is dropped and no service is refused.
3. **The marks are read**: `audit_writer.flagged(directory)` and `python -m tools.audit_verify <dir> --foreign`
   (one line per marked event: the journal row, the role, the event, both times, the marks; exit 1 when there is
   any; `--json`).
4. **The table is held against the code** (`tests/unit/test_audit_roles.py`): every family a service's folder
   writes is in its row; for the console and the orchestrator, every family written in their import closure; an
   edge service's row is exactly its own events and its named extras; every labelled event family
   (`console.i18n_audit.EVENTS`) has a writer or is host-only. A service that starts to send a new family fails
   the test until its row has it, which is what keeps an honest event from being marked.

## Not done

- **The shared id and the hash of the patient list** on both sides of a reveal, an export and a download, and
  the audit browser's answer to "which files held this patient" (the second half of the row and of its
  acceptance). The id needs the v3 claim's nonce on every route that gives identifiers out (D-483; the reveal
  has it since D-484, the export and the downloads are still the older assertion or none), and the browser
  question needs the outputs' patient lists hashed where the files are made. Neither is in this pull request.
- **The audit browser does not show the mark.** It is in the chain record and in `audit_verify --foreign`; a
  column or a filter in the browser is console work with its three catalogues.
- **A mark is not an alarm.** Nothing tells the owner when one appears (the health mail of T-209a could).
- **The role is only as true as the password.** With D-481 a container holds its own role's password; a process
  that has another role's password writes under that role, and the table cannot tell.
- **The table rests on what the code writes, read statically.** An event whose name is built at run time, or a
  library call the scan does not see, could be marked though it is honest: the mark asks for a look, it does not
  refuse.

## Consequences

- An event sent by a role that does not write its family, or dated away from when it arrived, is visible in the
  record and in one command.
- A new audit event family needs a row (the test fails without it).

## Dropped (D-311)

No security sign-off or owner review step.
