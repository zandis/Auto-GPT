# The CSV reader sets aside a cut or ragged export (lane F, card F-2, 2026-11-22)

**Reader:** the people who build TrialBox

Three High findings of the imperfect-feed measurement (H34, [its page](../plan/measurements/imperfect-feed-2026-11-18.md))
showed a hospital CSV export served wrong: a file cut inside its last row served a lab value short of its digits and
no sample time (H34-01); a file that ends inside a quoted field served the last note cut short (H34-03); a row one
field short was mapped with the missing column taken as empty (H34-04). Nothing was counted and the night published.
All data named here is synthetic.

## What changed

`services/adapter/sources/csv/source.py`, in its first pass over a file (still a stream, no row kept). The file is
quarantined as not a readable CSV, as T-615b does for a file it cannot read, and the night is held, when:

- the file does not end with a line end: a cut can leave the last row the header's width (inside the sample time,
  just after a separator, after half of an escaped quote, between two Big5 characters), so only the missing line end
  tells it;
- a quoted field has no closing quote (the parse is strict);
- the first line is blank (every row's columns would be nameless);
- a row has fewer fields than the header names, or a value past the header's end, or a width other than the first
  data row's (a decimal comma in a row whose last field is empty).

Read as before: a clean export, a quoted field holding a line end, CR line ends, a trailing separator on the header
or on every row, a UTF-8 byte-order mark, a Big5 export, a header-only table. The reason names the file, the line
and the field counts, never a cell's text.

## Tests

`tests/unit/test_csv_reader_refuses_cut_rows_h34.py`, 24 tests: 14 red on master's reader, all green after, one of
them through the adapter (the night is held). Twelve planted mistakes in the new lines were each caught; one more
(`named > 1` to `> 0`) is equivalent, as a row is never empty. The CSV source's test files: 1,768 passed.

## Two independent reviews

A worker that did not write the change reviewed it twice. The first round found a cut that keeps the header's width
still served, and half an escaped quote served: both closed by the line-end rule. The second found a shifted row
whose extra field is empty still served: closed by the first row's width.

## Findings

In [findings.json](csv-cut-rows-2026-11-22/findings.json):

- H34-01, H34-03, H34-04: fixed by this card (the state is proposed here; H34's own file still says open, so the
  register's keeper decides).
- F2-01, Medium: a complete export that does not end with a line end, or ends with a DOS end-of-file byte, now holds
  the night where master read it. No file the box writes or tests read is such a file; a hospital's export can be.
- F2-02, Low: a file cut exactly at a line end (whole rows lost) cannot be told from a whole file, as on master.
- H34-05 (a renamed header column) is not covered: the source is not told the columns the mapping reads.
