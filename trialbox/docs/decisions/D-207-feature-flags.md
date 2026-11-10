**D-207 Feature flags: one audited `app.flag` table, an admin page, and `TB_LAKE_SOURCE` behind the `lake.source`
flag (T-008, MR-090, WS-01.4, WS-03.5).** Task T-008 of `docs/reviews/2026-11-09-assessment-and-tasks.md`; branch
`wave0-goldens`; pull request: opened by the integrator. Numbered by the coordinator's note in that document (cards
take D-200 upward in card order, so T-008 is D-207; the card's own "D-196" is superseded). Closes P-21 (two flag
mechanisms before the first flag). Built 2026-11-09, no cloud.

* **The store** (`libs/tb_common/flags.py`). Schema `app` of the trial database: `flag` (name, value, when, by whom,
  why) and `flag_event` (every seed and every change: old value, new value, actor, reason). `DECLARED` lists every
  flag with its values, default and seed variable; an undeclared name or an undeclared value is a `ValueError`.
* **A change** (`Flags.set`) needs an actor, a reason and an audit log, and differs from the stored value. It is one
  `flag_event` row and one `flag.set` audit event (actor, old, new, reason, event id) in one transaction: the audit
  write happens inside it, so a failed audit write (a full disk) rolls the change back.
* **Reading never raises** (`Flags.get(name, default)`): the caller's default when the flag has no row, the store is
  not installed or not configured, or on any error (logged). A five-second per-process cache, so a change reaches
  every service within five seconds, without a restart (tested with two processes). Reading creates nothing in the
  database (no schema, no table), so a read-only role and `trialbox doctor` can read a flag.
* **A reader that must not guess reads strictly** (`Flags.value`): None for "no row", `FlagUnreadable` for "the store
  did not answer or holds an undeclared value", `LookupError` for "no store configured". The lake rebuild uses it.
* **The environment seeds, once.** `Flags.seed()` runs when the console starts (`create_app` through
  `console.admin_flags.register`): a flag with no row takes its seed variable (`TB_LAKE_SOURCE`) or its default, as a
  `seed` event and a `flag.seed` audit event; a seed without an audit log is refused, like a change. After that the
  variable is ignored; a later start with another value logs a warning, and `trialbox doctor` has a `flags` check
  that WARNs naming the flag's value, and WARNs too when the variable is set and the flag was never seeded (the
  variable still decides there). The compose file gives the console the same `TB_LAKE_SOURCE` as the lake service,
  so the seed cannot differ from what the lake ran on.
* **`lake.source`** (`services/lake/source.py`). `lake_rows` reads `rebuild_source()` once, when the rebuild starts,
  and keeps it to the end. The variable decides only when the store was read and holds no row (never seeded) or no
  trial database is configured. A flag that cannot be read is tried three times and then **stops the rebuild**: the
  variable is never used in place of an unreadable flag, since that would build the lake from the source the
  administrator switched away from. The tools that build from a named source (`tools/omop_parity.py`,
  `tools/goldens.py`) say so with `lake.source.force(source)`, so a flag seeded in their database cannot make them
  build both lakes from one source and report a parity that compared nothing.
* **What built a snapshot is kept**, not only logged: one line per rebuild in `<lake>/source.jsonl` (snapshot,
  source, origin, time) and, where the audit log is mounted (`TB_AUDIT_DIR`), a `lake.rebuild.source` audit event.
  `lake_meta.source` needs `services/lake/store.py`, which this card may not touch: requested for T-202.
* **On the review's question** (a flag read on the screening path must not change a running job's bytes): the only
  reader is the lake rebuild, which reads it once at its start; screening jobs read built snapshots (`CURRENT` or
  the job's pinned snapshot) and never the flag. One limit, stated plainly: a snapshot can be rebuilt in place
  (site set-up's publish does, `sitesetup/service.py`), as it could before this card; after a flip such a rebuild
  comes from the other source, so a job pinned to that snapshot keeps its bytes only as far as the two sources are
  identical. That is what the committed goldens (D-205, both sources on every check) and `tools/omop_parity.py`
  hold, and why the flip waits for them; `source.jsonl` shows when it happened.
* **The page** `/ops/flags` (`services/console/admin_flags.py`, `templates/ops_flags.html`, `i18n_flags.py` in en,
  ja, zh-TW): administrators only (anyone else 403 and a `console.denied` event); each flag with its value, last
  change and reason, a form with the new value and a required reason, one confirmation sheet (P-10), and the last 50
  events. An undeclared name, a bad value, an empty reason, a reason over 500 characters (never cut) or a bad CSRF
  token: 400. The sheet carries the value it showed, and Yes is refused when the flag changed in between. A flag
  store that does not answer is a 503 page.
* **A commit that fails after the audit event** (the event is written inside the transaction, so that a failed audit
  write rolls the change back) leaves a `flag.set` event for a change that did not happen: a `flag.set.failed` event
  with the same detail is appended and the error is raised.

*Review of 2026-11-09 (adversarial, 4 High, 7 Medium, 8 Low), all fixed in this branch.* The items above marked by
"strictly", "stops the rebuild", `force`, `source.jsonl`, the audited seed, `flag.set.failed`, the stale sheet and
the 503 page are its fixes. Not closed, and why: with the clinical workspace off the console registers no page
module and so seeds nothing (the seed would have to move in `services/console/app.py`, beyond this card's two
lines); `trialbox doctor` now warns in that state.

*Files outside the card's list, and why.* `tools/omop_parity.py` (three lines: `force(source)` around its rebuild and
"the OMOP store holds persons" in `identical`; without them a seeded flag makes the parity vacuous),
`tools/pglocal.py` (`drop_prefix` refuses an empty prefix, which would be every schema of the database) and
`deploy/docker-compose.yml` (the console's `TB_LAKE_SOURCE`): each is a review finding the integrator should read. `services/console/app.py`: the card allows one `include_router` line; the
console registers pages with `module.register(app, helpers)`, so the change is that call plus the module's name in
the existing `from console import (...)` list (two lines). `tools/trialbox/doctor.py` and its test's list of check
names: the contract says `doctor` warns. `tests/console/test_flags_page.py` carries a file-level `# ruff: noqa: F811`
instead of a `pyproject.toml` entry (not in the card's list). The page is not linked from the navigation (the
templates that hold it are not in the card's list); it is reached at `/ops/flags`. With the clinical workspace off
(`TB_CONSOLE_WORKSPACE=off`) the console registers no page module and the flags are seeded by the next start that has
it.

*Evidence.* `tests/unit/test_flags.py` (27): the seed once and the variable ignored after, the default seed, a bad
seed variable refused, one event and one audit event with actor and reason, the refusals, a failed audit rolling the
change back, undeclared names, the default on any error, the cache, two processes, and the rebuild following the
flag (no OMOP store before the flip, its persons after, the same rows). `tests/console/test_flags_page.py` (15):
the seeded page, the confirmation and the audit event, 400s, 403 for viewer, coordinator, investigator and cro, the
start seed, three languages. `tools/e2e_simple.py` PASSED with the default (the flag seeded `legacy`, no OMOP store
loaded) and with `TB_LAKE_SOURCE=omop` (the flag seeded `omop` from the variable; the OMOP stores hold the 5,000 and
400 persons). `tools/omop_parity.py` IDENTICAL on all four data sets with the flag code in place.
