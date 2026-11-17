# D-1048 A site list that is not read is said in the console, and approval is refused while it is not read

- **Task:** E-TERM-3. It comes from a finding in TERM-2's review (#936, D-1113 to D-1116), which the integrator relayed. The integrator ruled on #639 that approval is blocked.
- **PR:** this branch (`agent/E-TERM-3-refused-site-list`)
- **Date:** 2026-11-17
- **Status:** proposed (merges on green CI)
- **Builds on:** D-1028 (the site's own lists are the primary source), D-1029, D-858, D-1113, D-1114, D-1116, D-318

## The finding

A site list can be refused when it is read:
- its bytes differ from its manifest line;
- the manifest is damaged;
- its licence line names nobody.

Before this card, the refusal went only into the mapper's `installed_problems`, and only `trialbox doctor` and `tools.terminology_coverage` read that. The compile answered from the shipped tables, and nobody in the console learned it.

A list whose file was gone while its manifest line stayed was not refused at all. The mapper skipped it silently.

## Decision

1. **Every refused table is named.**
   - `Terminology.terminology_refused` lists each installed table refused at read, as `{"table", "reason"}`.
   - `installed_problems` stays, as the reasons' sentences.
   - A site list whose file is gone while its manifest line stays is refused ("in manifest.json but its file is missing").
   - While a site list is refused, every mapping the compile makes carries the note "site list site_<name> was not read; the shipped tables answered".
2. **The compile records them.**
   - The ruleset manifest gains `terminology_refused`: a list of `RefusedTable`, each a table name and the refusal's sentence (at most 600 characters, never a row of the table).
   - The review workbook gains a `terminology` sheet with the columns table, reason and whether it blocks approval.
   - The review notes say the same.
   - Each compile and each approval first re-reads the installed site lists and tables (`Terminology.refresh_installed`). A list loaded again, or removed, is seen without a restart of the compiler.
3. **Approval is refused while a site list is refused** (fail closed; the integrator's ruling).
   - Under D-1028 the site's lists are the primary source. A compile that silently answered from the shipped tables is not the compile the site configured, and approving it would fix those mappings into the ruleset.
   - The compiler's `approve()` adds one blocking line per list and answers `needs_review`. This holds for an e-mail reply and for the console alike.
   - A list refused at the compile asks for it to be loaded again or removed, and then for a new compile.
   - A list refused only since the compile asks for it to be loaded again or removed.
4. **A refused shipped or licensed table is not a site list.** It is recorded and said as a warning. Approval goes on.
5. **The console says it in en, zh-TW and ja.**
   - **The approval page** shows each refused table from the workbook, and a site list the box refuses now. While one is a site list, **Approve all** is held, and the POST answers 409 before anything is sent.
   - **The administrator's home** (`/admin`, health tab) shows each site list the box does not read now, and how to load it again or remove it.
6. **Removal is on purpose and audited.**
   - The command is `python -m tools.terminology_install remove-site-list --name NAME --by WHO [--audit-dir DIR]`. It deletes `site_<name>`'s file and its manifest line under the loader's lock, and writes `terminology.remove` to the hash-chained audit.
   - Without an audit folder (`--audit-dir` or `TB_AUDIT_DIR`) the removal is refused. A removal the audit cannot take does not happen.
   - A list removed this way is no refusal. Only a lower-case `[a-z0-9_]` name is taken, so nothing outside the folder is touched.

## Not in this card

- **The release stamp** that names each loaded table read (system, version, manifest sha256) is lane A2's card. Its shape is to be agreed with this card's `terminology_refused` through the integrator: the same `table` key.
- **Mounting `TB_TERMINOLOGY_DIR`** into the compose services is lane D's card. Until it lands, the console's admin banner is empty on a box where the folder is not mounted. The compiler's gate holds wherever the compiler reads the folder.
