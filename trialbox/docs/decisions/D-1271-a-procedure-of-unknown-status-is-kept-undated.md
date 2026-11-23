# D-1271 A procedure of unknown status is kept undated: a criterion on it reads unknown, never true

- **Task:** lane M, card SDR2 part 3 (finding SDR1-03; the integrator's rulings on #639, comments 7104711754,
  7105496002 and 7105784808; the integrator rules for lane E's lake and compiler since that session closed) ·
  **Date:** 2026-11-23
- **Status:** reserved for SDR2 part 3 (the integrator flips the row when merged)
- **Builds on:** D-275 (an order of unknown status is kept undated), D-917 (a condition of another clinical status
  makes the answer unknown, never a silent true), D-1252 (the SS-MIX2 record and version rules), D-130

## Decision

1. **The SS-MIX2 reader reads OMG-11 and OMG-12** (radiology and endoscopy 実施, OMI^Z23) into the canonical
   `procedure` table, only when ORC-1 is `SC` and ZE1-2 says 実施. A record with no version in force (D-1252) is read
   with `status` `unknown`, as an order is, never set aside. The extended `procedure.csv` is still read beside them.
2. **Two optional canonical columns** (`CANONICAL.md`): `order_code_system` (the code's system as the source names
   it) and `status` (`completed` or `unknown`). The JP mapping reads both: a Japanese procedure's code is written
   under JJ1017, a 診療報酬点数表 K code (`JP-K`) or the hospital's own system, never as an NHI order code; the
   status becomes Procedure.status. The TW mappings ignore both: the Taiwan feeds read byte for byte as before.
3. **The lake keeps a Procedure of status `unknown` undated** (`lake.flatten`, `UNCERTAIN`), D-275's rule as for an
   order. The SQL needs no change: an undated matching row falls in the presence atom's undated branch, which makes
   the answer unknown where the dated records do not settle it, with or without a window. Every shipped ruleset's
   SQL stays byte for byte. The OMOP lake reads the same flattener.
4. **The CQL says the same**: a Procedure's date is null when its status is `unknown`
   (`compile_cql.generator`). GZQO, the one shipped ruleset with a procedure atom, is recompiled: its EXC-05 lines
   and library version change, nothing else.

## Why (the D-917 parallel)

D-917 keeps a cured cancer from reading as "active cancer": a row whose status says otherwise can only make the
answer unknown. A done examination whose record has no version in force is the same case: the hospital wrote two
versions and neither can be called current, so it can neither prove the procedure (a silent true on an exclusion
would exclude a patient on a record nobody can confirm) nor be dropped (a silent false would let an exclusion pass).
Kept undated, it is shown and stays unknown.

## Not chosen

- **Setting such a record aside** (no column): a silent false on an exclusion; the integrator ruled to keep it.
- **A status rule in the SQL generator**, as D-917 does for conditions: it would change the compiled SQL of every
  procedure atom; the undated row gives the same answer with no SQL change.

## Known gap, reported not fixed

The CQL medication presence reads `authoredOn` whatever the order's status, while the lake keeps an order of unknown
status undated (D-275): the two engines can differ on such an order. Not changed here (not this card's).

## Proof

`tests/unit/test_mapping_coverage.py`: the reader (done and not-done examinations, the extended CSV), the JP and TW
mappings (never `nhi_order`; Taiwan byte for byte), and the guard on the shipped GZQO-EXC-05 in the SQL and on the
local CQL engine (unknown gives unknown, completed gives true).
