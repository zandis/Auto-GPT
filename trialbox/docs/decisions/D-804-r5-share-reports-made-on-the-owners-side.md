# D-804 R5's share reports are made on the owner's side, from the export, and come back only as attachments

- **Task:** R5 (proof run: one CGRD day read, mapped and screened; plan 37), the task file for the first-look session
- **PR:** this branch (`agent/R5-first-look-task`)
- **Date:** 2026-11-15
- **Status:** proposed (merges on green CI)
- **Builds on:** D-588 (the share report: the one output that may leave the site), D-688 (a window that read nothing
  does not pass), D-510 (the owner is brought decisions only), the owner's rule that nothing read from a hospital
  source enters the repository, a pull request, a log or a message

## Context

Lane E maps the CGRD day; it cannot reach the export and must not. The first-look session on the owner's computer
holds a one-day slice of the export. The earlier runbook asked the owner to run two commands against the database
with a read-only account, which does not exist yet, and asked him to run them himself.

## Decision

1. **The first-look session runs R5 by itself** from `docs/handover/R5-first-look-share-reports.md`. The owner's part
   is a yes in that session and attaching the three files in lane E's session.
2. **It reads the export, not the database**: the slice is loaded into a local SQLite file outside the repository,
   because `--columns-only` reads a SQL source only; `--day` then windows it as the night would. No connection
   string. The csv source is the fallback, with no columns report.
3. **Three files come back**: `columns.json` and `day.json` (`mapping_check --share`), and `answers.md` (counts,
   names and shapes only). The session reads each line against the no-patient-data rule before anything leaves; a
   hit stops the send and is reported by kind and step, never by value.
4. **They come back only as attachments in lane E's session**, never on a pull request or in the repository (public).
   The site mapping lane E writes from them names the hospital's tables and stays outside the repository too.

## Known limits

- The export has no patient table, so the share report's second net (D-588 point 2) has nothing to compare with:
  the line-by-line read is the only net. D-588 point 1 holds by itself.
- The questions only the database or the DBA can answer stay open until a read-only account exists.
