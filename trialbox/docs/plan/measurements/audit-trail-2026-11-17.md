# The audit trail can be trusted: card V-8, 2026-11-17

Lane V, card V-8. Worked on master `ee1961e5d`. Basis words: *shown* (a test of this card showed it), *hypothesis*
(read from code, not run), *not run*.

## Verdict

<!-- generated:verdict -->
Counts behind the verdict: 22 tamper cases, 17 caught by both verifiers; 228 changing routes, 16 brought to success; 7 findings, 6 High (V8-02, V8-03, V8-04, V8-05, V8-06, V8-07).
<!-- /generated:verdict -->

- **(a) Tampering is caught: does not hold against a person who can write the anchor folder.** Shown: 17 kinds of
  tampering on one copy of the volume, each caught by both `tools/audit_verify.py --heads` and the console's Verify,
  each error naming the file and line or the event number. But a forgery re-signed with a new key after the anchor
  folder was emptied passes both, as the runbook runs them, and the nightly signer then signs it with the box's own
  key (V8-05). A deleted newest signed head is not noticed (V8-06). Without `--heads` the tool says PASS on a forged
  chain with no word (V8-02). A torn last line is reported in the words of tampering (V8-01).
- **(b) What is checked: for the routes brought to success, each event's actor is the account that made the
  request, it has a timestamp, and every record id the request named (study, patient, job, batch, grant, account)
  stands in its events.** A mutation (the PI's mark written with `actor="console:admin"` and another pid) turns this
  test red (run, not committed). Nothing is checked for the routes not brought to success. The order of change and
  event is unsafe on some routes: an account is kept when its audit event cannot be written (V8-04; extends V3-18).
- **(c) No audit row holds identifying free text: does not hold.** The data-ops decision's reason (V8-03) and the IRB
  record's reason (V8-07) are stored as typed. The break-glass opening note is too (V3-14, cited). The break-glass
  review note, the PI's mark note and the reveal "other" note (a name after a label included) stay out (shown).

## What ran and what did not

- Ran: `tests/unit/test_audit_tamper.py` (writes `tamper.json`), `tests/console/test_audit_trail_routes.py` (writes
  `routes.json`), `python -m tools.audit_trail_check --sweep` (writes `sweep.json`), and
  `tools/audit_trail_check.py --check` with `tests/unit/test_audit_trail_check.py`. Run with
  `AUDIT_TRAIL_OUT=docs/plan/measurements/audit-trail-2026-11-17` to write the json again.
- The chain is written by the product's writer (`tb_common.audit.AuditLog`). On a box the `audit-writer` drain
  writes the same chain through the same class, so the tamper cases apply to it unchanged. The journal itself
  (`TB_AUDIT_WRITER=db`) was checked by the existing PostgreSQL tests, run here: `tests/unit/test_audit_writer.py`,
  14 passed (append-only for every role, the drain copies in order, a restored journal is recorded). The tamper
  cases on the chain's files were not repeated against the journal: the journal refuses UPDATE, DELETE and TRUNCATE
  to everyone, the superuser included (shown by that test), so editing, deleting or reordering a row is refused there,
  not detected afterwards.
- Not done: the `walked` fixture stays per test. The console's test box is per test (`tmp_path` and the global
  stores), so the walk runs once for each of four tests.
- The compose box was **not run**. The routes were driven on the console's in-process test box.
- 212 changing routes were **not brought to success** (no valid body built). Among them are consent, enrolment,
  withdrawal, EDC sign and send, criteria approval, release and settings. For each, `routes.json` gives the
  handler's place and the first audit write in the handler's own body. The services the handlers call were not
  traced, so "no write in the body" is never a missing event. Sampled: EDC sign, decide, switch, send, dictionary
  and drafts write in `services/edc/service.py`. The lead `/setup/{ws}/sheets/{iid}/roles` writes `screen.to_pid`
  (`orchestrator/identifiers.py:144`) and `setup.reread` (`sitesetup/service.py:255`). Hypothesis, not a finding.
- EDC sign's audit line holds `printed_name` and `values` (`services/edc/service.py:433`). Not driven. The printed
  name is part of the signature's signed content (D-281). Not filed.

## (a) Tampering

The chain: three day files, 120 events a day by four synthetic accounts, a signed head published to an anchor folder
each night with the box's own key. Each case is applied to a copy. Columns: the CLI with `--heads` (no `--pubkey`, as
the runbook runs it; for `night_signs_forgery` it runs with the box's key pinned), the console's Verify, the CLI
without `--heads`, the CLI with the box's key pinned, and whether the nightly signer signed.

<!-- generated:tamper -->
| case | `audit_verify --heads` | console Verify | without `--heads` | box key pinned | night signed | first error |
|---|---|---|---|---|---|---|
| field_first | FAIL | FAIL | FAIL | - | - | 2026-11-14.jsonl:1: hash mismatch |
| field_middle | FAIL | FAIL | FAIL | - | - | 2026-11-15.jsonl:61: hash mismatch |
| field_last | FAIL | FAIL | FAIL | - | - | 2026-11-16.jsonl:121: hash mismatch |
| own_hash_recomputed | FAIL | FAIL | FAIL | - | - | 2026-11-15.jsonl:52: prev_hash does not match previous line |
| rechained_with_head | FAIL | FAIL | PASS | - | - | signed head 2026-11-15T16:20:00+00:00 (event 241, key d1921b51ad41ff1c34958d957ef40df8): event 241 does not have the signed hash: the chain  |
| delete_middle | FAIL | FAIL | FAIL | - | - | 2026-11-15.jsonl:51: prev_hash does not match previous line |
| delete_last | FAIL | FAIL | FAIL | - | - | HEAD.json: the chain ends at event 362 (5ab117fd2d1c6835), the head anchor says event 363 (51c40e0acb054803): events dropped, a day file del |
| reorder_two | FAIL | FAIL | FAIL | - | - | 2026-11-15.jsonl:31: prev_hash does not match previous line |
| cut_tail_5 | FAIL | FAIL | FAIL | - | - | HEAD.json: the chain ends at event 358 (916569e841141d73), the head anchor says event 363 (51c40e0acb054803): events dropped, a day file del |
| drop_last_file | FAIL | FAIL | FAIL | - | - | HEAD.json: the chain ends at event 242 (f23580e40ee492f9), the head anchor says event 363 (51c40e0acb054803): events dropped, a day file del |
| prefix_with_head | FAIL | FAIL | PASS | - | - | signed head 2026-11-15T16:20:00+00:00 (event 241, key d1921b51ad41ff1c34958d957ef40df8): the chain has only 232 events: events were dropped  |
| fresh_chain_from_genesis | FAIL | FAIL | PASS | - | - | signed head 2026-11-14T16:20:00+00:00 (event 120, key d1921b51ad41ff1c34958d957ef40df8): the chain has only 60 events: events were dropped a |
| duplicate_event | FAIL | FAIL | FAIL | - | - | 2026-11-15.jsonl:42: prev_hash does not match previous line |
| insert_forged | FAIL | FAIL | FAIL | - | - | 2026-11-15.jsonl:43: prev_hash does not match previous line |
| swap_day_files | FAIL | FAIL | FAIL | - | - | 2026-11-14.jsonl:1: prev_hash does not match previous line |
| torn_last_line | FAIL | FAIL | FAIL | - | - | 2026-11-16.jsonl:121: invalid JSON (Unterminated string starting at: line 1 column 299 (char 298)) |
| rollback_to_backup | FAIL | FAIL | PASS | - | - | signed head 2026-11-16T16:20:00+00:00 (event 362, key d1921b51ad41ff1c34958d957ef40df8): the chain has only 242 events: events were dropped  |
| rollback_after_last_signed_head | PASS | PASS | PASS | - | - |  |
| resigned_forgery | PASS | PASS | - | FAIL | - |  |
| night_signs_forgery | PASS | PASS | - | - | yes |  |
| newest_head_deleted | PASS | PASS | - | - | - |  |
| torn_then_written | PASS | PASS | - | - | - |  |

Cases: 22. Caught by both entries: 17. Passed by both: 5.
<!-- /generated:tamper -->

- **Where the outside anchor is kept.** `TB_AUDIT_ANCHOR_TARGETS`, a folder off the audit volume (the hospital
  share); the signed head is written once per name (`audit.py:719`). The services mount the audit volume read-only
  (D-394); the host's nightly `trialbox audit-sign` writes the anchor. Whoever can write the anchor folder can rewrite
  it: case `resigned_forgery` (shown) empties `heads/` and `keys/` and signs with a new key. Both verifiers then pass,
  because they trust the keys found in the folder (`audit_page.py:356`; the CLI adds a note only). Only `--pubkey`
  with the box's key fails it, and no runbook command passes `--pubkey`. Case `night_signs_forgery` (shown): with
  `heads/` emptied, the nightly signer has no earlier head (`audit_heads.py:113`). It checks the chain only against its
  own `HEAD.json` (`:127`) and signs the forgery with the box's real key; after that even the pinned check passes.
  To close V8-05, the key must be pinned somewhere the same person cannot write. D-562 lists this under
  "Not done here": "a person who can delete files in the anchor folder and write the audit volume is not caught; the
  folder must be one the box's root cannot prune". The same section leaves out comparing the folder with the
  chain's own `audit.head_signed` events, which is why a deleted newest head goes unnoticed (V8-06).
- **The window.** Events after the newest signed head can be rolled back unseen until the next night (case
  `rollback_after_last_signed_head`, shown). D-562 point 5 says: "Events written after the newest signed head are
  protected by the chain and its anchor only, until the next night". It also says `doctor` FAILs when the newest head
  is older than `TB_AUDIT_HEAD_MAX_AGE_H` (36 hours). Not filed. Deleting the newest head widens this window by a
  night with no word (V8-06).
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
| `POST /studies/{rs}/patients/{pid}/reveal#other` | crc | 200 | console.reveal_patient | yes | yes | yes | yes | - | no change of state |
| `POST /studies/{rs}/irb` | crc | 303 | console.irb | yes | yes | yes | yes | chart, name, phone, email | change first |
| `POST /audit/verify` | privacy | 200 | console.audit_verify | yes | yes | yes | yes | - | no change of state |
| `POST /api/v1/audit/verify` | privacy | 200 | console.audit_verify | yes | yes | yes | yes | - | no change of state |

Changing routes in the live apps: 228. Brought to success: 16 (18 calls). Calls with no event: 0. Not shown: 212. Of those, 132 have no audit write in the handler's own body; the services they call were not traced, so this is not a count of missing events.
<!-- /generated:driven -->

- Refusals: not walked again. V2-02 (cited) found 46 refusals on 9 console routes with no record.
- The order of change and event, for the driven routes, is in the last column (from reading; D-273's two shown by
  `tests/console/test_d273_privacy_guards.py`, V8-04 shown here). On a box the console's audit write goes to the
  journal on its own autocommit connection (`audit_writer.py:171`), so "one transaction" means the event is written
  before the store commits.

## (c) Identifying text in audit rows

The sweep (`sweep.json`, hypothesis) counts the fields named like typed text or a person (note, reason, why, answer,
subject, name, request…):

<!-- generated:sweep -->
Audit writes in `services/`: 432. With a field named like typed text or a person: 77. Of those, not wrapped in a masking function at the call: 73.
<!-- /generated:sweep -->

Many of these hold fixed codes, such as a login failure's reason. The fields shown with planted synthetic values (a
chart number, a name after a label, a phone, an e-mail) are in the "planted values in clear" column above.

Pseudonyms in audit rows: D-272 (DATA-013) leaves them, counted by `audit_verify --find-ids`; the erasure registry
keeps the chain after an opt-out (`libs/tb_common/erasure.py:574`, D-394). Cited, not filed.

## Findings

<!-- generated:findings -->
| id | severity | lane | basis | place | claim | ruling |
|---|---|---|---|---|---|---|
| V8-01 | Medium | C2 | shown | `libs/tb_common/audit.py:528` | A torn last line (a write cut short) is reported as tampering: 'invalid JSON' and 'events dropped, a day file deleted, or the chain rewritte | - |
| V8-02 | High | C2 (D for the Makefile target and the runbook) | shown | `tools/audit_verify.py:148` | make audit-verify without ANCHOR (tools/audit_verify.py without --heads) prints PASS on a fully re-chained forgery, a prefix, a fresh chain  | - |
| V8-03 | High | C2 (audit); B2 (services/datacore/dataops.py) | shown | `services/datacore/dataops.py:497` | The steward's typed reason for a data-ops decision (page and /api/v1) reaches the audit chain in clear: a chart number, a name, a phone and  | - |
| V8-04 | High | C2 | shown | `services/console/app.py:1257` | POST /ops/users (add) makes the account before its audit event; with the audit write failing (AuditFull) the account stays, with no event. R | extends V3-18 |
| V8-05 | High | C2 (console verify, audit_verify, nightly signer); D (runbook, anchor folder placement) | shown | `services/console/audit_page.py:356` | A re-signed forgery passes both verifiers as an operator runs them (actor changed, chain re-made without its head_signed events, HEAD.json r | D-562, 'Not done here': 'a person who can delete files in the anchor folder and write the audit volume is not caught; the folder must be one the box's root cannot prune'. Filed because plan 8's High rule asks for more. |
| V8-06 | High | C2; D (anchor folder placement) | shown | `libs/tb_common/audit.py:654` | With the newest signed head deleted from the anchor folder, the genuine chain passes both verifiers with no word, so the rollback window sil | D-562, 'Not done here': the comparison of the anchor folder with the chain's own audit.head_signed events is not done. Filed because plan 8's High rule asks for more. |
| V8-07 | High | C2 | shown | `services/console/team.py:827` | The IRB record's typed reason reaches the audit in clear: a chart number, a name, a phone and an e-mail typed there are stored as typed. tea | - |

Findings: 7. High: 6. Medium: 1. Low: 0.
<!-- /generated:findings -->

Strict xfail tests: V8-01, V8-02, V8-05 (two tests) and V8-06 in `tests/unit/test_audit_tamper.py`; V8-03 (two
routes), V8-04 and V8-07 in `tests/console/test_audit_trail_routes.py`. Each was run with `--runxfail` and fails for
the product reason. Each asserts only the property: a fix that refuses the request is accepted too.
