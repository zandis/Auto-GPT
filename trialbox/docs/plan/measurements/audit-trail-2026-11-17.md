# The audit trail can be trusted: card V-8, 2026-11-17

Lane V, card V-8. Worked on master `ee1961e5d`. Basis words: *shown* (a test of this card showed it), *hypothesis*
(read from code, not run), *not run*.

## Verdict

- **(a) Tampering is caught: holds, with two Medium gaps in what the check says.** Shown: 17 kinds of tampering on
  a three-day chain of 363 events, each caught by both `tools/audit_verify.py --heads` and the console's Verify, and
  each error names the file and line or the event number. A fully re-chained forgery (the chain and its
  `HEAD.json` rewritten) is caught only by the signed heads kept off the box (D-355, D-562). Without `--heads` the
  tool says PASS and does not say that nothing signed was read (V8-02). A torn last line is reported in the words
  of tampering (V8-01).
- **(b) Every changing route writes who, what, when and which record: holds for the 15 routes brought to success;
  not shown for the other 213 of 228.** Every driven route wrote at least one event with the account id
  (`console:<username>`), the event, a timestamp and the record. The order of change and event is not safe on
  every route: account creation is kept when its audit event cannot be written (V8-04, High; extends V3-18).
- **(c) No audit row holds identifying free text: does not hold.** The data-ops decision's typed reason is stored as
  typed (V8-03, High). The break-glass opening note is too (V3-14, cited). The break-glass review note and the PI's
  mark note stay out (shown).

## What ran and what did not

- Ran: `tests/unit/test_audit_tamper.py` (writes `tamper.json`), `tests/console/test_audit_trail_routes.py` (writes
  `routes.json`), `python -m tools.audit_trail_check --sweep` (writes `sweep.json`), and
  `tools/audit_trail_check.py --check` with `tests/unit/test_audit_trail_check.py`. Run with
  `AUDIT_TRAIL_OUT=docs/plan/measurements/audit-trail-2026-11-17` to write the json again.
- The chain is written by the product's writer (`tb_common.audit.AuditLog`, which the `audit-writer` drain uses).
  The services' journal path (`TB_AUDIT_WRITER=db`, PostgreSQL) was **not run**: no database here.
- The compose box was **not run**. The routes were driven on the console's in-process test box.
- 213 changing routes were **not brought to success** (no valid body built). For each, `routes.json` gives the
  handler's place and the first audit write in the handler's own body, or none. "None" is a hypothesis only: many
  handlers call a service that writes the event.

## (a) Tampering

The chain: three day files, 120 events a day by four synthetic accounts, a signed head published to an anchor folder
each night. Each case is applied to a copy. Columns: the CLI with `--heads`, the console's Verify, the CLI without
`--heads`.

<!-- generated:tamper -->
| case | `audit_verify --heads` | console Verify | without `--heads` | first error |
|---|---|---|---|---|
| field_first | FAIL | FAIL | FAIL | 2026-11-14.jsonl:1: hash mismatch |
| field_middle | FAIL | FAIL | FAIL | 2026-11-15.jsonl:61: hash mismatch |
| field_last | FAIL | FAIL | FAIL | 2026-11-16.jsonl:121: hash mismatch |
| own_hash_recomputed | FAIL | FAIL | FAIL | 2026-11-15.jsonl:52: prev_hash does not match previous line |
| rechained_with_head | FAIL | FAIL | PASS | signed head 2026-11-15T16:20:00+00:00 (event 241, key 8b18e25366c968aac0e78cde8bfa8019): event 241 does not have the signed hash: the chain  |
| delete_middle | FAIL | FAIL | FAIL | 2026-11-15.jsonl:51: prev_hash does not match previous line |
| delete_last | FAIL | FAIL | FAIL | HEAD.json: the chain ends at event 362 (85035bf5c2273b31), the head anchor says event 363 (a5ad5eba407075ba): events dropped, a day file del |
| reorder_two | FAIL | FAIL | FAIL | 2026-11-15.jsonl:31: prev_hash does not match previous line |
| cut_tail_5 | FAIL | FAIL | FAIL | HEAD.json: the chain ends at event 358 (444d28d2f8ebff65), the head anchor says event 363 (a5ad5eba407075ba): events dropped, a day file del |
| drop_last_file | FAIL | FAIL | FAIL | HEAD.json: the chain ends at event 242 (d9a9ef3e238ecc7b), the head anchor says event 363 (a5ad5eba407075ba): events dropped, a day file del |
| prefix_with_head | FAIL | FAIL | PASS | signed head 2026-11-15T16:20:00+00:00 (event 241, key 8b18e25366c968aac0e78cde8bfa8019): the chain has only 232 events: events were dropped  |
| fresh_chain_from_genesis | FAIL | FAIL | PASS | signed head 2026-11-14T16:20:00+00:00 (event 120, key 8b18e25366c968aac0e78cde8bfa8019): the chain has only 60 events: events were dropped a |
| duplicate_event | FAIL | FAIL | FAIL | 2026-11-15.jsonl:42: prev_hash does not match previous line |
| insert_forged | FAIL | FAIL | FAIL | 2026-11-15.jsonl:43: prev_hash does not match previous line |
| swap_day_files | FAIL | FAIL | FAIL | 2026-11-14.jsonl:1: prev_hash does not match previous line |
| torn_last_line | FAIL | FAIL | FAIL | 2026-11-16.jsonl:121: invalid JSON (Unterminated string starting at: line 1 column 299 (char 298)) |
| rollback_to_backup | FAIL | FAIL | PASS | signed head 2026-11-16T16:20:00+00:00 (event 362, key 8b18e25366c968aac0e78cde8bfa8019): the chain has only 242 events: events were dropped  |
| rollback_after_last_signed_head | PASS | PASS | PASS |  |
| torn_then_written | PASS | PASS | - |  |

Cases: 19. Caught by both entries: 17. Passed by both: 2.
<!-- /generated:tamper -->

- **Where the outside anchor is kept.** `TB_AUDIT_ANCHOR_TARGETS`, a folder off the audit volume (the hospital
  share); the signed head is written once per name (`audit.py:719`). The services mount the audit volume read-only
  (D-394); the host's nightly `trialbox audit-sign` writes the anchor. A person with root on the host can write both
  (hypothesis). The console trusts the keys it finds in the anchor folder's `keys/` (`audit_page.py:356`); the nightly
  signer pins the box's own keys (`tools/trialbox/audit_heads.py`, hypothesis).
- **The window.** Events after the newest signed head can be rolled back unseen until the next night (case
  `rollback_after_last_signed_head`, shown). D-562 rules the nightly cadence, and `doctor` FAILs a head older than 36
  hours. Not filed.
- **Who runs the check.** Every write compares the chain's end with `HEAD.json` and refuses on a mismatch
  (`audit.py:357`). Each night `trialbox audit-sign` checks the whole chain against every signed head before it signs
  (D-562; `docs/runbook/02-daily-operation.md:8`). `logs archive-audit` verifies before it archives. The console's
  Verify is run by a person. `doctor` checks the age of the newest head, not the chain. Basis: hypothesis (read).

## (b) Routes and their events

The inventory is read from the live app objects: the console (from the test box), `orchestrator.app.app` with its
included routers (site set-up, EDC, data core, life-cycle), and `mail_gateway.app.app`. The registry service has no
changing route.

<!-- generated:driven -->
| route | column | status | events | who | what | when | which | planted values in clear | change and event |
|---|---|---|---|---|---|---|---|---|---|
| `POST /breakglass` | admin | 303 | console.breakglass_notice, console.breakglass_open | yes | yes | yes | yes | chart, name, phone, email | change first |
| `POST /breakglass/{gid}/review` | steward | 303 | console.breakglass_review | yes | yes | yes | yes | - | change first |
| `POST /data-ops/batches/{bid}/decide` | steward | 303 | dataops.decide | yes | yes | yes | yes | chart, name, phone, email | one transaction |
| `POST /api/v1/data/batches/{bid}/decide` | steward | 200 | dataops.decide | yes | yes | yes | yes | chart, name, phone, email | one transaction |
| `POST /site/opt-outs` | privacy | 303 | console.opt_out | yes | yes | yes | yes | - | one transaction |
| `POST /api/v1/site/opt-outs` | privacy | 200 | console.opt_out | yes | yes | yes | yes | - | one transaction |
| `POST /studies/{rs}/patients/{pid}/reveal` | crc | 200 | console.reveal_patient | yes | yes | yes | yes | - | no change of state |
| `POST /studies/{rs}/candidates/{pid}/reveal` | crc | 200 | console.reveal_patient | yes | yes | yes | yes | - | no change of state |
| `POST /pilot/jobs/{job_id}/reveal` | crc | 200 | console.reveal_patient | yes | yes | yes | yes | - | no change of state |
| `POST /api/v1/studies/{rs}/patients/{pid}/reveal` | crc | 200 | console.reveal_patient | yes | yes | yes | yes | - | no change of state |
| `POST /studies/{rs}/patients/{pid}/mark` | pi | 303 | console.pi_mark | yes | yes | yes | yes | - | one transaction |
| `POST /api/v1/studies/{rs}/patients/{pid}/mark` | pi | 200 | console.pi_mark | yes | yes | yes | yes | - | one transaction |
| `POST /ops/users` | admin | 303 | console.user | yes | yes | yes | yes | - | change first |
| `POST /ops/users#disable` | admin | 303 | console.user | yes | yes | yes | yes | - | change first |
| `POST /audit/verify` | privacy | 200 | console.audit_verify | yes | yes | yes | missing | - | no change of state |
| `POST /api/v1/audit/verify` | privacy | 200 | console.audit_verify | yes | yes | yes | missing | - | no change of state |

Changing routes in the live apps: 228. Brought to success: 15 (16 calls). Calls with no event: 0. Not shown: 213, of which no audit call in the handler's own body: 133.
<!-- /generated:driven -->

- Refusals: not walked again. V2-02 (cited) found 46 refusals on 9 console routes with no record.
- The order of change and event, for the driven routes, is in the last column (from reading; D-273's two shown by
  `tests/console/test_d273_privacy_guards.py`, V8-04 shown here). On a box the console's audit write goes to the
  journal on its own autocommit connection (`audit_writer.py:171`), so "one transaction" means the event is written
  before the store commits.

## (c) Identifying text in audit rows

The sweep (`sweep.json`, hypothesis) lists 432 audit writes in `services/`. 77 pass a field whose name suggests typed
text or a person (note, reason, why, answer, subject, name, request…). 73 of those do not wrap it in a masking function
at the call. Many are fixed codes (a login failure's reason). The ones shown with planted synthetic values (a chart
number, a name after a label, a phone, an e-mail) are in the "planted values in clear" column above.

Pseudonyms in audit rows: D-272 (DATA-013) leaves them, counted by `audit_verify --find-ids`; the erasure registry
keeps the chain after an opt-out (`libs/tb_common/erasure.py:574`, D-394). Cited, not filed.

## Findings

<!-- generated:findings -->
| id | severity | lane | basis | place | claim | ruling |
|---|---|---|---|---|---|---|
| V8-01 | Medium | C2 | shown | `libs/tb_common/audit.py:528` | A torn last line (a write cut short) is reported as tampering: 'invalid JSON' and 'events dropped, a day file deleted, or the chain rewritte | - |
| V8-02 | Medium | C2 (D for the Makefile target) | shown | `tools/audit_verify.py:148` | make audit-verify without ANCHOR (tools/audit_verify.py without --heads) prints PASS on a fully re-chained forgery, a prefix, a fresh chain  | - |
| V8-03 | High | C2 (audit); B2 (services/datacore/dataops.py) | shown | `services/datacore/dataops.py:497` | The steward's typed reason for a data-ops decision (page and /api/v1) reaches the audit chain in clear: a chart number, a name, a phone and  | - |
| V8-04 | High | C2 | shown | `services/console/app.py:1257` | POST /ops/users (add) makes the account before its audit event; with the audit write failing (AuditFull) the request fails but the account s | extends V3-18 |

Findings: 4. High: 2. Medium: 2. Low: 0.
<!-- /generated:findings -->

Strict xfail tests: V8-01 and V8-02 in `tests/unit/test_audit_tamper.py`; V8-03 (two routes) and V8-04 in
`tests/console/test_audit_trail_routes.py`. Each was run with `--runxfail` and fails for the product reason.
