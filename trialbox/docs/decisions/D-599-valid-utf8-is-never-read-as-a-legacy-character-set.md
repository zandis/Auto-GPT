# D-599 Bytes that are valid UTF-8 are read as UTF-8 or refused, never as a legacy character set

- **Task:** a finding of the review of #452 (UX-004), ordered by the integrator on 2026-11-13
- **PR:** this branch (`agent/DIN-detector-utf8-first`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-215 (one detector for a site's files: the right text or a refusal, never wrong text)

## Context

`tb_common.encoding.detect` weighs a UTF-8 file with no byte order mark and fewer than three usual non-ASCII
characters against Shift_JIS and Big5, because one Big5 hanzi can be valid UTF-8 by chance (`職` is C2 BE, `¾`).
In that weighing the legacy reading could win: a sheet with one Cyrillic letter was read as half-width kana, with
no refusal (619 of the characters from U+0080 to U+2FFF, one at a time). Plain western text (`38°C`, `Sjögren`)
tied with its one-kanji reading and was refused. Four hanzi side by side that are valid UTF-8 by chance were read
as UTF-8, because Latin-1 symbols counted as usual wherever they stood.

## Decision

For bytes that are valid UTF-8 (bytes that are not are judged as before):

1. **A legacy character set is never the answer.** When the weighing would take the Shift_JIS or Big5 reading,
   the file is refused. Two half-width kana or one hanzi that happen to be valid UTF-8 and a word of another
   script are the same bytes (D0 AF is `Я` and `ﾐｯ`): too little to tell, whichever reading weighs more.
2. **UTF-8 is certain for a short list of places only western text has** (`_WESTERN`): an accented Latin-1
   letter inside a word between ASCII letters (`Sjögren`); a degree sign between a number and `C` or `F`; a micro
   sign before a unit (`µg`, `µmol`); a superscript 2 or 3 after `m`; a plus-minus between two numbers; a Greek
   letter hyphened to a word (`TNF-α`). A file whose every non-ASCII character stands so is UTF-8. A first
   version took any character beside an ASCII letter or digit for western; its review showed kana names and
   hanzi stand so too (`ﾐｷ1`, `職1`), and that rule is gone.
3. **Of the Latin-1 symbols only `µ ° ± ×` count as usual wherever they stand** (a urine protein column of `±`).
   The others are, as two bytes, frequent hanzi (`¾` 職, `²` 簡, `½` 翻, `§` 禮): three of them no longer make a
   file certain UTF-8, in `detect` and in the file reader's fast path alike.

## Consequences

- A UTF-8 sheet is never read as Shift_JIS or Big5; one with a western word or a unit of the list is read where it
  was refused.
- Refused where they were read: a Shift_JIS sheet whose only non-ASCII content is half-width kana that are all
  valid UTF-8 by chance (`ﾐｷ`, `ﾏｻﾕｷ`: read right before); a column of `½`, `¾`, `²` or `§` alone, in UTF-8 (read
  right before) or in Big5 (read wrong before). Each is too short to tell; UTF-8 with a byte order mark, or a
  sheet with more text, is read.
- Known limits: a short EUC-KR or GB18030 file that is not valid UTF-8 can still be read as Big5 (sites outside
  Japan and Taiwan). Legacy bytes in one of the places of rule 2 (a hanzi between two lowercase letters, `38簞C`)
  are read as UTF-8; no such text is known. `detect` takes time quadratic in the length of a run of non-ASCII
  characters that is valid UTF-8 (8,000 `°` in a row: 17 s), as before this decision.
