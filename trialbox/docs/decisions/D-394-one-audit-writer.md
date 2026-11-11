# D-394 One audit writer: an append-only journal in the database and one drain

- **Task:** T-211b, audit integrity part b (`docs/plan/28-master-plan-v6.md` §6.2.5)
- **PR:** this branch (`agent/T-211b-one-audit-writer`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Builds on:** D-378 (one PostgreSQL role per service), D-355 (signed audit heads), D-272 (the head anchor)
- **Closes:** CR-042 (one writer; the signing part closed with D-355)

## Context

Six service containers (criteria-compiler, adapter, orchestrator, mail-gateway, gateway, console) mounted the audit
volume read-write, and each appended to the hash chain itself. A compromised service could rewrite history and
recompute the hashes (CR-042). D-355 made such a rewrite detectable against a signed head; it did not take the pen
away from the services.

## Decision

1. **The journal.** `audit.journal` in `trialbox_wf` holds each event the services send: `seq`, insert time,
   the signed-in database role, event, timestamp and fields. The schema, the table and the functions belong to
   `audit_writer` (NOLOGIN). Its only member is `trialbox`, the host tools' admin, which drops and restores schemas
   as it does for every store group of D-378. No service role can become it.
2. **One way in.** `audit.append(event, ts, fields)` is `SECURITY DEFINER`: it inserts as `audit_writer` and records
   `session_user`, which the caller cannot choose. The service roles of D-378 get EXECUTE on it and nothing else in
   the schema: no INSERT, SELECT, UPDATE, DELETE or TRUNCATE. It takes an advisory lock, so `seq` order is commit
   order.
3. **Append-only.** `audit_writer` has no UPDATE, DELETE or TRUNCATE on the journal. A trigger refuses all three to
   everyone, the superuser included.
4. **The services** get their writer from `tb_common.audit_writer.open_audit`. With `TB_AUDIT_WRITER=db` (each of
   the six in `deploy/docker-compose.yml`) it sends events to the journal over the service's own `TB_DB_URL`. Their
   audit mount is now read-only (the pages read the chain). Unset, it writes the chain in-process as before (tests,
   demos, a developer shell). Code that host tools run inside the orchestrator (watchdog, update, operations,
   backup schedule, install) uses it too.
5. **The drain.** The `audit-writer` service (`python -m tb_common.audit_writer drain`, role `tb_audit_writer`,
   SELECT on the journal only) is the one container that mounts the audit volume read-write. It copies each row, in
   `seq` order, into the chain through `AuditLog`, with `journal: {seq, role, at}`. It reads where it stands from the
   chain, so a restart neither repeats nor skips a row.
6. **A restored journal.** When the chain's last journal row is not in the journal as recorded (an update rollback
   restored the database, or a new database), the drain writes an `audit.journal_resync` event and goes on with the
   rows inserted after that row's time. The gap is visible; nothing written since is passed over.
7. **A broken chain** (disk full, a broken anchor) stops the drain, not the services: events wait in the journal.
8. **One place for the SQL.** `tb_common.audit_writer.JOURNAL_SQL`; both role scripts
   (`deploy/docker/db-init/30-service-roles.sh` and the platform copy) carry it, and a test keeps them equal.

## Consequences

- `tests/unit/test_audit_writer.py` runs the real role script on a throwaway cluster: each service role is refused
  INSERT, UPDATE, DELETE, TRUNCATE and SELECT on the journal and SET ROLE to its owner, and can call `audit.append`;
  even the superuser cannot change or delete a row; the drain writes a chain that verifies.
- `tests/unit/test_audit_one_writer.py` enumerates the writers: a new `AuditLog(...)` in a service or library, a
  new write to the `audit` schema, an in-container `AuditLog('/data/audit')`, or a second read-write mount fails.
- Events reach the chain about a second after the action (the drain is woken by `NOTIFY`).
- The platform (Kubernetes) form gets the SQL with the role script; its services still sign in as `trialbox` and
  write the chain in-process until it has a secret per service (as D-378).
- A restore made with `--no-owner` leaves the journal owned by `trialbox` and without grants until the role script
  runs again (as for D-378's schemas).
- Host tools that write the chain on the host (`tools/audit_verify.py`, the restore record) still write it directly;
  they run as the box's admin.

## Dropped (D-311)

No security sign-off or owner review step.
