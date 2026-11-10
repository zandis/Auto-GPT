**D-319 The review fixes of PR #71 change D-205 and D-207: failed flag commits are named, flag reads create
nothing, a dead flag store is a 503, each rebuild records its source, a third night, and `--write` from both
sources.** Task T-655 of TB-PLAN-06 (`docs/plan/28-master-plan-v6.md` §6.2.4). Closes CR-051 (part) and PLAN-049.
Branch `agent/T-655-flag-fixes`. Date: 2026-11-10.

*The problem.* PR #71 rebuilt the reviewed branch of T-006 and T-008 and fixed its adversarial review. Master took
the work through PR #77 instead, and #71 was closed. Six of its fixes were not on master, and D-205 and D-207
recorded the gaps they closed as accepted.

*What changes from D-207 (feature flags).*

- **A commit that fails after the audit event is named.** D-207 left this (review M5) as a known gap for T-211. Now
  `Flags.set` appends a `flag.set.failed` event, with the detail of the `flag.set` event and the error, when the
  commit fails after the audit event was written. The audit write stays inside the transaction, so a full disk still
  refuses the change.
- **Reading creates nothing.** D-207 kept `migrate` on each page view. Now `row`, `get`, `read` and `env_drift`
  (doctor and the lake rebuild) create no schema and no table, and `all` and `events` (the `/ops/flags` page) create
  no table. Only `seed` and `set` install the store.
- **A flag store that does not answer is a 503 page.** D-207 said 400. Now the list, the confirmation sheet and Yes
  on `/ops/flags` are each a 503 page when the trial database does not answer.
- **Each rebuild records its source.** D-207 left this (review M2) to T-202 (`lake_meta.source`). Now each rebuild
  appends one line to `<lake>/source.jsonl` and, where `TB_AUDIT_DIR` is set, writes a `lake.rebuild.source` audit
  event. `lake_meta.source` stays with T-202. `lake.source.force(source)` lets a tool name its source whatever a
  seeded flag says. `tools/omop_parity.py` and `tools/goldens.py` use it and check each lake's record.

*What changes from D-205 (committed goldens).*

- **A third night.** A new data set, `synthetic-jp-a-restored`, rebuilds the JP lake the night after the deletes with
  everything back as on the first night. The OMOP store must have lifted every tombstone. It pins lake tables only,
  no ruleset. Each night's OMOP store is measured right after its own rebuild.
- **`--write` needs both sources.** D-205 wrote from one source. Now `--write` builds from legacy and then from omop,
  and writes nothing unless the two agree. `--write --source legacy|omop` is refused.
- **The reason must name a decision that exists**: a file in `docs/decisions` or an entry of `docs/DECISIONS.md`.
- **A golden that nothing computes any more is removed by `--write`.** D-205 said a stale golden stays and the check
  names it. The check still fails on a stale golden; `--write` now removes it.

*Not changed.* `--check` still runs both sources side by side in two processes. A flag store that cannot be read
still stops the rebuild at once. #71's three attempts before stopping were not ported. The stale confirmation sheet
is still refused in the route, not in `Flags.set`.

*Evidence.* `tools.goldens --write` from both sources: they agree, and the restored night has no tombstones left. Only
`lake/tables@ci.json` changed. Tests: `tests/unit/test_flags.py`, `tests/unit/test_goldens.py`,
`tests/console/test_flags_page.py`.
