# R5: the share reports of one CGRD day, made by the first-look session

**Reader:** the box owner, and the people who build TrialBox. The first-look session on the owner's computer
carries this out by itself; the owner's part is two things: a yes in that session, and attaching the three files it
writes in lane E's session.

Proof run R5 (plan 37, "one CGRD day read, mapped and screened"); D-588 (what the mapping check may send back); D-688
(a window that read nothing does not pass). Lane E maps the day from these files. Nobody else reaches the data.

**Why this run exists.** Lane E cannot see the export and must not. It needs to know how the real day is laid out
(which mapped columns exist, how dates and units are written, which codes the look-ups lack, whether keys repeat)
to write the site mapping. `tools/mapping_check.py --share` writes exactly that and nothing else.

**Data.** The export already on this computer. No database connection, no connection string. Nothing from the export
goes into the repository, a pull request, a log, a commit, a message or a chat other than the three files below,
after the check in step 5. The repository is public.

## What you need

- This repository at master, with its Python environment (`make venv`; on Windows
  `uv sync --frozen --group test --extra dev --python 3.12`).
- The one-day slice of the export you built for lane E (the day 2026-01-13), in a folder **outside** the repository.
- The first-look mapping you already use (`cgrd_first_look.yaml`) and, if you hold it, lane E's question list
  (`only_the_connection_can_tell.md`). Both name things from the hospital's dictionaries: they stay outside the
  repository, as the export does.

## The run

Work from the `trialbox` folder. `<slice>` is the slice's folder, `<out>` a folder outside the repository. On
Windows write `.venv\Scripts\python` for `.venv/bin/python` and put each command on one line.

1. **The slice as a local database.** `--columns-only` reads a SQL source only, so load the slice into a SQLite
   file in `<out>` (outside the repository): one table per `source` the mapping names, the columns as the export
   names them, every value as text, as read from the export (no cleaning: the shapes are what lane E needs). The
   source below is then `--source cgrd_sql --dsn sqlite:///<out>/day.sqlite`. If the slice cannot be loaded, run
   step 3 alone with `--source csv --path <slice>` (each table the file the mapping's `source` names), skip step 2,
   and say so in `answers.md`.
2. **columns.json** (reads no row):

   ```
   .venv/bin/python tools/mapping_check.py --mapping <path>/cgrd_first_look.yaml \
     --source cgrd_sql --dsn sqlite:///<out>/day.sqlite --columns-only --share <out>/columns.json
   ```

3. **day.json** (the day's rows, at most 20,000 a table):

   ```
   .venv/bin/python tools/mapping_check.py --mapping <path>/cgrd_first_look.yaml \
     --source cgrd_sql --dsn sqlite:///<out>/day.sqlite --day 2026-01-13 --rows 20000 --share <out>/day.json
   ```

   With the csv source leave out `--day`: the slice is the window. A table that reads nothing is said in the file
   (`read_nothing_in_window`): that is an answer, not an error. "failed" and missing columns are expected; they
   are what lane E needs to learn. The export holds no patient table and no medication table: their lines say they
   cannot be read, and the check's second net (the patient table's values, D-588 point 2) has nothing to compare
   with, so step 5 is the only net.
4. **answers.md**, written by you, holding counts, names and shapes only (a shape writes each digit `9` and each
   letter `A`: `20260113` is `99999999`). If you hold lane E's question list, answer each `C-nn` item that the slice
   can answer, by its number, and write "needs the database" or "needs the DBA" for the others. If not, answer:
   - for each table: rows in the slice, and whether the file or table was read whole;
   - for each date and time column: its distinct shapes and how many rows have each (Western or ROC years, with or
     without a time, empty strings);
   - the file encoding of each table as you found it (UTF-8, Big5, CP950; with or without a byte-order mark);
   - for each column that links rows to a patient or a visit: whether every table writes it in the same shape, and
     how many rows of each table have it empty (counts, never a value);
   - for lab results: the distinct unit spellings seen for at least five patients, and how many rows have a unit
     column empty;
   - for each code column: which code system it looks like (ICD-9-CM, ICD-10-CM, NHI local codes, a hospital's own
     codes), from its shape and length, and the count of distinct codes;
   - anything the first-look deep review found that lane E's mapping must know, said as a kind and a count.
5. **Before anything leaves**, read all three files line by line. They may hold only table and column names, the
   check's own words, shapes, short codes, unit spellings and numbers. If any line holds a person's name, a chart,
   ID or phone number, an address, a real date of a patient, or a sentence of note or report text, delete the
   three files, do not send, and tell lane E in a message which kind of thing it was and which step wrote it,
   never the value. Lane E fixes the check first.
6. Tell the owner the three files are ready and checked, and where they are in `<out>`.

## What goes back, and how

The owner attaches `columns.json`, `day.json` and `answers.md` in lane E's session. Nothing else: no screenshot, no
sample row, no part of the slice, no log. They never go on a pull request or into the repository. Lane E keeps them
outside the repository too. What it commits is code and synthetic tests, never a line of these files; the site
mapping it writes from them names the hospital's tables and stays outside the repository, as the dictionaries do.
