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
  every service within five seconds, without a restart (tested with two processes).
* **The environment seeds, once.** `Flags.seed()` runs when the console starts (`create_app` through
  `console.admin_flags.register`): a flag with no row takes its seed variable (`TB_LAKE_SOURCE`) or its default, as a
  `seed` event and a `flag.seed` audit event. After that the variable is ignored; a later start with another value
  logs a warning, and `trialbox doctor` has a `flags` check that WARNs naming the flag's value.
* **`lake.source`** (`services/lake/source.py`). `lake_rows` reads `rebuild_source()` once, when the rebuild starts,
  and keeps it to the end; the source and its origin are logged. Before any service has seeded the database (a tool
  run on its own lakes, a fresh test database) there is no row and `TB_LAKE_SOURCE` decides, as before: this is what
  keeps `tools/omop_parity.py` (which must not change, T-006) and `tools/goldens.py` able to build both lakes in one
  run. On the review's question (a flag read on the screening path must not change a running job's bytes): the only
  reader is the lake rebuild, which reads it once at its start; screening jobs read built, immutable snapshots
  (`CURRENT` or the job's pinned snapshot) and never the flag, so a flip changes no running job. Recording the source
  in `lake_meta` would need `services/lake/store.py`, which this card may not touch: requested for T-202.
* **The page** `/ops/flags` (`services/console/admin_flags.py`, `templates/ops_flags.html`, `i18n_flags.py` in en,
  ja, zh-TW): administrators only (anyone else 403 and a `console.denied` event); each flag with its value, last
  change and reason, a form with the new value and a required reason, one confirmation sheet (P-10), and the last 50
  events. An undeclared name, a bad value, an empty reason or a bad CSRF token: 400.

*Files outside the card's list, and why.* `services/console/app.py`: the card allows one `include_router` line; the
console registers pages with `module.register(app, helpers)`, so the change is that call plus the module's name in
the existing `from console import (...)` list (two lines). `tools/trialbox/doctor.py` and its test's list of check
names: the contract says `doctor` warns. `tests/console/test_flags_page.py` carries a file-level `# ruff: noqa: F811`
instead of a `pyproject.toml` entry (not in the card's list). The page is not linked from the navigation (the
templates that hold it are not in the card's list); it is reached at `/ops/flags`. With the clinical workspace off
(`TB_CONSOLE_WORKSPACE=off`) the console registers no page module and the flags are seeded by the next start that has
it.

*Evidence.* `tests/unit/test_flags.py` (17): the seed once and the variable ignored after, the default seed, a bad
seed variable refused, one event and one audit event with actor and reason, the refusals, a failed audit rolling the
change back, undeclared names, the default on any error, the cache, two processes, and the rebuild following the
flag (no OMOP store before the flip, its persons after, the same rows). `tests/console/test_flags_page.py` (13):
the seeded page, the confirmation and the audit event, 400s, 403 for viewer, coordinator, investigator and cro, the
start seed, three languages. `tools/e2e_simple.py` PASSED with the default (the flag seeded `legacy`, no OMOP store
loaded) and with `TB_LAKE_SOURCE=omop` (the flag seeded `omop` from the variable; the OMOP stores hold the 5,000 and
400 persons). `tools/omop_parity.py` IDENTICAL on all four data sets with the flag code in place.
