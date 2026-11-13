# D-553 The data pages say which export is the file for REDCap and which is the file for a person

- **Task:** NEW-CSV-2 (the wording half of the REDCap export question; the integrator's word of 2026-11-13)
- **PR:** this branch (`agent/NEW-CSV-2-export-files-named`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI)
- **Builds on:** D-549 (a cell that could be read as a formula is written so a spreadsheet does not run it), D-129 /
  D-125 (the data pages and their exports)

## The problem

The study's data leave the console as three files: CDISC ODM, a REDCap CSV and an Excel workbook. D-549 put the
formula guard on the cells of the files a person opens (the workbook and the console's own CSV downloads) and left
the REDCap CSV exactly as it is written, because REDCap reads it as data and a guard mark would land in the
REDCap record. That is the right split, but nothing on the page said so. A coordinator who opened `export.csv`
in Excel, let Excel change it and saved it would load the changed file into REDCap; a coordinator looking for a
file to read might take the CSV because it is listed first.

## The decision

The export section of both data pages (`/studies/{rs}/forms` and `/studies/{rs}/entry`) carries one line under
the buttons, in English, Japanese and Traditional Chinese (`dc.export.files`):

> Load the REDCap CSV into REDCap as it is, without opening and saving it in a spreadsheet program first. The
> Excel workbook is the file for a person to open and read: the same columns, with the data dictionary on a
> second sheet.

It says how to handle each file; which file a REDCap project takes is said by the two lines already there (the
help line above the buttons and the CDISC line below them).

Nothing else changes: no mark is added to the CSV, no guard is put on its cells, the files and their routes are
as they were.

## What it does not do

- It does not stop anyone opening the CSV; it says what each file is for. A guard on that file is refused by
  D-549's reasoning (the mark would be loaded into REDCap).
- The ODM and CDISC buttons keep their own help text.

## What the adversarial review changed

One review by a fresh reviewer, who ran the two exporters and read the bytes. Verdict: fix first.

- **The first wording contradicted the page.** It said the CSV "is the file for REDCap"; the CDISC help line one
  paragraph below says "a REDCap project takes the plain ODM" (and the ODM is what the round trip is tested
  against). The line now says how to handle each file and claims no exclusivity.
- The workbook is the CSV as a workbook, not a report, so the line says what is in it (the same columns, the data
  dictionary on a second sheet).
- The test ordered the line against the workbook's button only, so it would have passed with the line spliced
  between the buttons on the forms page; it now orders it against the end of the button row.
- Checked and not changed: the CSV really is unguarded and REDCap-shaped, the workbook really is guarded
  (`=1+1` comes back as text), and the caution is right — that CSV has no byte order mark, so Excel on a Japanese
  or Chinese Windows garbles its CJK cells and saving destroys them (`tb_common.csvfile`).

## Reuse check

The page's existing hint line and the console's own catalogue (`console.i18n_entry`) carry it; the forbidden-word
check (`tb_common.wording.check_page`) is the one already used by the wording walk. Nothing is added.

## Dropped (D-311)

No sign-off step.
