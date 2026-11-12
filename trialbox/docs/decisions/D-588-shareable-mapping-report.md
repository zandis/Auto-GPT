# D-588 The first look at a real source: what the mapping check may send back, and what it never does

- **Task:** T-731 (the CGRD connector; plan v7 section 4 step 10a, section 5 lane E; preparation P-7)
- **PR:** this branch (`agent/T-731-cgrd-mapping-report`)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-84 (`tools/mapping_check.py`), D-580 (codes nobody knows are counted, and only what looks like a
  code is written out), D-334 (unit pairs), the owner's rule that nothing read from a hospital source enters the
  repository, a pull request, a log or a message

## Context

The CGRD read connection is on the owner's side. The people and sessions who repair the mapping cannot reach it and
must not. They still need to know what the real layout looks like: how dates are written, which codes the look-ups
lack, how units are spelt, whether keys repeat. `mapping_check` printed row values (`status=X`, a result's raw
text, validator messages with ids), stopped at the first row the mapping refused, and took the connection string
on the command line.

## Decision

1. **One file may leave the owner's side: the share report** (`mapping_check --share <file>`). It holds table and
   column names, counts, and for each kind of value only this:
   - **dates**: the *shape* of the text (`9999-99-99`, `9999999`, `民國999年9月9日`), never the value; how many the
     mapping reads, refuses, and finds empty; the database's column type when the driver tells it;
   - **codes**: a value is written out only when it looks like a code (D-580's rule) and is not the site's chart
     number pattern; anything else is counted as "(not a code)";
   - **units**: a unit spelling of at most 20 characters with no run of five digits; anything else "(not a unit)";
   - **coded result texts**: written out only when the shared table or the site's own answers read them; an
     unread text is given by its shape;
   - **rows the mapping refuses**: the reason, with every quoted value removed and every other word that holds a
     digit or a non-ASCII letter replaced by its shape;
   - **repeated keys**: counts only (keys that repeat, identical copies, copies that differ, copies that differ
     and fall on another day);
   - **structure errors**: a count.
2. **A second net over the whole file.** Before it is written, every text in the report is compared with the
   identifying values of the rows that were read (every value of the patient table, and of every column the
   mapping uses as a patient link or an identity) and run through the repository's own data scan patterns. A hit
   is replaced by "(withheld)" and counted. The count is in the report.
3. **With `--share`, the terminal shows only what the file holds.** Nothing else is printed, so a pasted terminal
   is as safe as the file.
4. **The connection string comes from the environment** (`--dsn-env NAME`), never the command line, and is never
   printed. `--dsn` stays for a test database.
5. **The check reads as little as it can.** From a SQL source it selects only the columns the mapping names, for
   one window of the table's change-time column (`--day`, or `--since` / `--until`), and at most `--rows` rows a
   table (the report says when the limit cut a table). `--columns-only` reads no row at all: it lists which mapped
   columns each table or view has.
6. **A refused row no longer stops the check.** It is counted by reason, as the night counts it.

## What the owner sends back

The share file, and nothing else. No screenshot of rows, no sample, no export.

## Not in this card

- The nightly read (`adapter.pipeline`) still selects every column of a table; selecting only the mapped ones
  there is lane B's file (sent to the integrator as a finding).
- The other four connectors of T-731 are dated in plan v7 section 3.3.
