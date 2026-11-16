# D-805 An English UTF-8 note file is read, not quarantined

- **Task:** blocker 12 of lane G's VALIDATION dry run (2026-11-14), "an English UTF-8 note.csv is quarantined"
- **PR:** this branch (`agent/BLOCKER-12-english-utf8-notes`)
- **Date:** 2026-11-15
- **Status:** proposed (merges on green CI)
- **Builds on:** D-215 (one detector: the right text or a refusal), D-599 (valid UTF-8 is read as UTF-8 or refused),
  T-615b (`settings.data_source.encoding`), D-473 (a refused file is quarantined)

## Context

D-599 reads valid UTF-8 without weighing when it has three usual non-ASCII characters, or when every one stands in
a fixed western place. One `Crohn’s`, one `β blocker` or one `Humira®` in a day's English notes was neither: the file
was weighed against Shift_JIS and Big5 and quarantined, "the character set cannot be told for certain". Lane G worked
around it by writing a byte order mark.

## Decision

1. **A curly apostrophe or quote at a Latin letter is a western place.** Its bytes are the garble 窶冱 / 鈥檚 in
   Shift_JIS and GB18030, and no character in Big5, EUC-JP or EUC-KR.
2. **A site that declares `data_source.encoding: utf-8` has its valid UTF-8 read as UTF-8**, never weighed. Bytes
   that are not valid UTF-8 are weighed as before, and a file holding U+FFFD is still refused with its line.

## Known limits

- An undeclared site's file with one Greek letter, ®, ° or ½ outside D-599's places is still refused: the same bytes
  are a Big5 hanzi or a pair of half-width kana beside a letter or digit. Such a site sets `encoding: utf-8`.
