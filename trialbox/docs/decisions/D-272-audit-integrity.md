**D-272 Audit integrity: no chart number in clear in the audit chain, a head anchor that `verify` checks, and an
archive that never overwrites a closed day that changed.** Fix group FG-C of the critical-issues register
(`docs/reviews/2026-11-10-critical-issues-register.md`, TB-REG-01): rows CR-016 (Blocker) and CR-054 (High), with
patch PX-3 (the console's request-line writer) and PV-9; plan v6 §6.2.1 (`docs/plan/28-master-plan-v6.md`) also
names the deep-review findings DATA-021 and DATA-013 (`docs/reviews/2026-11-10-deep-review/06-data-flow-governance.md`).
Branch `agent/FG-C-D-272-audit-integrity`, one draft pull request. Date 2026-11-10. Status: proposed.

*Why.* Three writers put the chart number into the hash-chained audit log in clear: the orchestrator's `job.state`
event (the job's `options`, and a failure message that quotes `mrn=`), the mail gateway's `mail.received` (the
subject is the request line) and `mail.sent` (a reply quotes it), and the console's `console.request` (the request
line). The pages masked `mrn=…` in text only, for four keys, while the job line hides nine, and a stored `options`
mapping printed as text was not masked at all. Separately, `verify` recomputed the chain from GENESIS and nothing
else: dropping the last events, deleting the newest day file, deleting every day file, or rewriting and rehashing the
whole chain all passed (DI-4, DATA-021 by a run). The nightly archive copied a closed day again whenever its sha256
changed, so a rewritten day replaced the good copy.

*What.*

1. **One masking rule** (`libs/tb_common/audit.py`). `ID_KEYS` is the set the console's job line hides (`mrn`,
   `chart`, `chart_no`, `name`, `patient`, `patient_name`, `dob`, `birth_date`, `phone`). `mask_ids(text)` masks
   `key=value` in a line and `'key': value` in a printed mapping; `mask_detail(value)` masks those keys in a mapping
   and applies `mask_ids` to every text inside. The mask is `•••`, the form the pages already showed.
2. **The three writers store the masked form.** The orchestrator audits `mask_detail(options)` and a masked error;
   the job itself keeps its options, because the run needs the chart number to find the pseudonym. The mail gateway
   masks `subject` on `mail.received` and `mail.sent` and `reason` on `mail.rejected`. The console audits
   `mask_ids(line)` (PX-3).
3. **The pages use the same rule.** `console.app` imports `mask_ids` and `ID_KEYS` from `tb_common.audit`, so the
   audit table's mask and the stored form are one rule, and a row written before this change is masked on the page
   too. The CASE job page's "web request" row is the audited line with the chart number put back from the job's own
   options, then shown by the existing D-143 rule: in clear only to an account with identifier authority for the
   study, as one audited, capped view; masked for everyone else. D-143 is an owner decision and is kept; this change
   does not remove that view (see "Not done").
4. **The head anchor** (`audit/HEAD.json`: `lines`, `hash`, `file`). Every write appends its line, then replaces
   the anchor atomically (write, fsync, rename, fsync the folder), all under the existing lock. `verify` requires the
   anchor and compares the end of the chain with it. A chain one event past the anchor and chained to it (a crash
   between the line and the anchor, or a write in progress while `verify` reads) passes with a note. `verify` also
   takes an anchor kept elsewhere (`anchor={"lines": n, "hash": h}`; `tools/audit_verify.py --anchor FILE`): event
   `n` must have hash `h`, which catches a chain rewritten together with its own `HEAD.json`.
5. **A writer refuses a broken chain.** When the chain and the anchor are apart, `AuditLog.append` raises
   `AuditAnchorBroken` (an `OSError`, like `AuditFull`), so the action does not go ahead over a gap. A person checks
   with `tools/audit_verify.py` and then runs `tools/audit_verify.py <dir> --reanchor "why" --actor NAME`: an
   `audit.reanchored` event records the old anchor, the chain as found and the reason, and the chain is anchored
   where it ends. No line is changed or removed. A chain written before this change has no anchor: its next write
   adopts it with an `audit.anchored` event (the number of events and the last hash), so an upgrade needs no manual
   step; `verify` fails on such a chain until then, and lists every `audit.anchored` and `audit.reanchored` event as a
   note.
6. **The archive** (`tools/trialbox/logs.py`). It keeps its own `HEAD.json`: where the chain stood at the end of the
   last archived day. Before copying, the live chain must verify against its own anchor and against the archive's.
   A closed day whose content changed since it was archived is refused and the archived copy is kept; only a day
   that grew (its archived copy is the start of the file: the newest file can still take a late event stamped before
   midnight) is copied again. An archived day missing from the audit folder is refused. After copying, the
   decompressed archive must verify against the old anchor, and the new anchor is written.
7. **A report for the owner's ruling (OD-7).** `tools/audit_verify.py <dir> --find-ids` lists every event that holds
   a chart number in clear (file, line, time, event, job, field path; never the value), and counts per event the
   rows that name a 32-hex patient pseudonym (DATA-013). It changes nothing.

*Rows already in the chain (OD-7): the owner's ruling is pending.* This change does not rewrite or remove any
existing line. The register's recommendation is to keep the old chain sealed and readable by the data steward only
and to start a new chain after the fix; the `--find-ids` report is the list for that ruling. Until the owner rules,
the old rows stay as they are, and the console's audit table masks them on display.

*Not done, and why.*

* **Keyed hash, signed heads, off-box anchors and one writer** are task T-211a and T-211b (register CR-042). The
  head anchor here is not keyed: a process that can write the audit volume can rewrite the chain and `HEAD.json`
  together. The archive's anchor (or any copy of `HEAD.json` kept elsewhere, checked with `--anchor`) catches that
  as long as it is out of the same process's reach; signing it is T-211a.
* **Emptying the folder and the anchor together** cannot be told from a new box by the folder alone. The archive's
  anchor catches it (the archive refuses), and `--anchor` does.
* **PV-9** (the CASE job page shows the chart number on a GET, with an in-memory limiter): the audit side is closed
  (the stored line is masked); the page view stays as D-143 allows it. Removing it, or moving it to the guarded
  reveal path, needs the owner to revisit D-143; it is not decided here.
* **DATA-013** (pseudonyms in audit events and erasure): owner question Q2 of the deep review. The report counts
  the rows; no per-patient token is built here.
* **PV-11 (b) to (e)** (attachment names in audit rows, `phi` mail bodies, a refused CASE mailing the chart number
  back) are Medium and outside this group; only the subject and reason fields of the gateway's rows are masked.

*Evidence.* `tests/unit/test_audit_anchor.py`: dropping the last events, deleting the newest day file, deleting
every day file (with and without the anchor), and rewriting and rehashing everything all fail; a rewrite that also
rewrites `HEAD.json` fails against an anchor kept elsewhere; a writer refuses a cut chain and writes again after
`reanchor`, with the gap visible; a crash between line and anchor is accepted; an old chain is adopted visibly; a
torn line is repaired and anchored; the archive refuses a rewritten closed day (with and without its anchor), takes
a day that only grew, and refuses a missing day and an emptied folder; the mask rules; `--find-ids` lists old rows
without their values; the CLI `--anchor`, `--no-head` and `--reanchor`. `tests/integration/test_case_inproc.py`:
after a CASE request by mail (and a refused one, and the replies), no audit line holds the chart number, and the
chain verifies against its anchor. `tests/console/test_console_app.py`: the console's request writer stores the line
masked and `/audit` does not show the chart number; the job page still follows D-143.
