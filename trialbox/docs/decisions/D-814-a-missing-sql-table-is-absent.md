# D-814 A mapped table the database does not have is absent, named, and the night goes on

- **Task:** CGRD-SQL (passed from lane A2: the SQL source had no `has_table`; one missing table stopped the night)
- **PR:** this branch (`agent/CGRD-SQL-a-missing-table-is-absent`), cut from CGRD-A2 (#711)
- **Date:** 2026-11-15
- **Status:** proposed (merges on green CI)
- **Builds on:** T-611 (a missing file is not an empty table), D-588 (an error's kind, never its text)

## Decision

1. **`SqlSource.has_table`**: a table is absent only when reading it fails **and** the database's catalogue has no
   table or view by that name. It then yields no rows and the night's report says `present: false`, as for a csv
   export without the file; the night goes on.
2. **Any other failure is raised** (a lost connection, no right to read): an outage never reads as "every table is
   absent".
3. `mapping_check` says the table cannot be read with the error's kind, as before, and reads the rest.
