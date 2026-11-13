# D-710 The first-run page asks the pid map over the map's own connection, and says when it could not be read

- **Task:** NEW-FR-1 (a finding of lane E, by reading, placed by the integrator on 2026-11-13)
- **PR:** this branch (`agent/NEW-FR-1-first-run-asks-the-pid-map-itself`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-544 / D-579 (the chart-number rule is asked at first run, only while the box holds no
  patient), D-378 (one database role per service, a group role per store)

## The problem

`console.firstrun.box_holds_patients` decides whether the first-run page may ask how chart numbers are written.
It asked about the pid map (`to_regclass` of `pidmap.pid_map`) over the console's `auth` connection. On a box,
the role script gives each store a group role and a store's connection takes that role; the role of `auth` may
not use the `pidmap` schema. The question raised on every box with roles, the error was caught, and the answer
was "cannot tell", which the page read as "holds patients". So the rule could never be chosen at first run on a
real box, and the page did not say why: the question was simply absent.

**Confirmed by a run** under the real role script (`deploy/docker/db-init/30-service-roles.sh` on a cluster of
its own, the console's login role `tb_console`): the old function answered None on a box whose map is empty.
The same class as the opt-out worker's failure of the same night (one store asked over another store's
connection).

## The decision

- **The map is asked over its own connection.** Whether the map's schema exists is read from the catalogue over
  the console's own connection (any role may read that; nothing is created). Only when it exists is the `pidmap`
  store opened (the console's login role is a member of its group), and the two tables are asked there.
- **"Cannot tell" is said.** When the answer is None the rule is still not offered (another rule on a box that
  does hold patients gives every patient a second pseudonym), but the page says that whether the box holds
  patients could not be read, that finishing without the rule is safe (the numbers are kept as written), and
  what to do if the rule is needed. An answer posted all the same is refused with the same reason, not with
  "this TrialBox already holds patients".
- English, Japanese and Traditional Chinese.

## What it does not do

- It does not offer the rule when the map cannot be read: fail closed, as before.
- **The same shape elsewhere in the console** was looked for (a catalogue question or a table of another store
  over one store's connection): there is no other. One related place is said here and sent to the integrator,
  not changed: `console.demo_guard._db_texts` (the scan of stored demo input) reads `information_schema` as the
  console's login role, so on a box with roles it sees the columns of the console's own stores only; the stores
  of other services are not scanned by it, and it does not say so.
- The role script and the console's list of stores are unchanged (`pidmap` was already on it).

## Review

See "What the adversarial review changed" when the review is in.

## Reuse check

`tb_common.db.Database.connect` and the way `tb_common.optout.with_survivors` opens the map only when its
schema exists; the role-script fixture of `tests/unit/test_db_roles.py`. Nothing new is built.

## Dropped (D-311)

No sign-off step.
