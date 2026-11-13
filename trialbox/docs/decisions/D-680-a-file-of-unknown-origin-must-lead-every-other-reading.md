# D-680 A file of unknown origin is read only when its reading leads every other, a rival's too

- **Task:** findings of lane A2's review of its upload readers and of the review of #465, ordered by the
  integrator on 2026-11-13 as one card on the decoder
- **PR:** this branch (`agent/DIN-detector-linear`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-215 (one detector: the right text or a refusal, never wrong text), D-599 (bytes that are valid
  UTF-8 are read as UTF-8 or refused)

## Context

The detector weighs the candidates a caller names (Shift_JIS, Big5) and, as rivals, the sets nobody asked for. A
rival only stopped a reading when it read the file **better**; when it tied, the candidate was taken. Short text
ties: two to four characters of EUC-JP or GB18030 were read as Shift_JIS or Big5 text 20 to 50 % of the time
(`辞退` as two other hanzi, `已转院了` as half-width kana), and Windows-1252 was no rival at all (`ATENÇÃO` read
with two kana in it). The upload reader took any valid UTF-8 as UTF-8, so a Big5 cell whose two bytes are valid
UTF-8 by chance was read as `¦`. Scoring a text walked back through each run of half-width kana once per
character: time quadratic in the run (8,000 `°` in a row: 17 s; 2 MB: hours).

## Decision

1. **A file of unknown origin** (a caller whose candidates span two languages: the sheets and the uploads, with
   Shift_JIS and Big5) **is read only when its reading leads every other reading by the confidence margin, the
   rivals' too.** A tie with a rival is a refusal.
2. **A caller that names one language has said what the file is** (a vendor's master is Shift_JIS; an SS-MIX2
   note is Japanese, in Shift_JIS or EUC-JP): there a rival must read the file better to refuse it, as before.
3. **Single-byte western text and EUC-KR are rivals**, never candidates. Western text is weighed as ISO 8859-1
   whatever the set really is (Windows-1252, Mac Roman, CP437, CP1250, KOI8-R): a high byte is an accented letter
   when its word holds at least two ASCII letters, no more high bytes than ASCII letters plus one and no run of
   more than three; a symbol counts in its place (`38 °C`, `5 ± 2`, `½ tablet`). A word of accented letters with
   nothing ASCII in it weighs `_WESTERN_ALONE` (0.8), set by measurement so that it ties with its half-width kana
   reading and is refused, while a kana word with its voicing marks is still read (at 0.9 half of a fuzz of kana
   sheets was refused; at 0.75 five of 3,600 western lines were read as kana).
4. **Big5-HKSCS is of the Big5 family**: a Cantonese sheet is read, not taken for Shift_JIS.
5. **A file that reads as UTF-16 without its mark is refused** (a NUL byte on the same side of most byte pairs),
   by the sheet reader and the upload reader. A stray NUL in a text is not that and is dropped as before.
6. **The upload reader takes valid UTF-8 as UTF-8 for a document only**: a byte order mark, all ASCII, or at
   least `UPLOAD_WESTERN_TEXT` (40) ASCII letters. A shorter upload is a cell or a line and is judged as a sheet.
7. **Scoring is one pass**: each run of half-width kana is looked at once.

## Consequences

- Measured, as tests with a ceiling of zero per shape and fixed seeds: over 10,000 fuzzed short texts per reader
  in EUC-JP, GB18030, EUC-KR, Big5 and Shift_JIS; 1,500 lines of French, German, Portuguese, Polish, Russian and
  Cantonese in nine sets; sheets of symbols; UTF-16; a word and one legacy character. None is read as wrong text,
  by the sheet reader or the upload reader (before: 1,491 of 7,200 of the first kind alone).
- The price, held by the same tests: of small real sheets (one to eight rows) some are refused where they were
  read. The floors: at least 90 % of Shift_JIS sheets of half-width kana words are read, 85 % of Big5 sheets with
  one cell a row, 95 to 100 % of the others; SS-MIX2 notes in either Japanese set at least 95 %. The reviewer's
  3,600 sheets: 2.8 % of one-row sheets refused, 0.5 % at five rows, none from ten rows. None is read wrong. A
  refused sheet is read when saved as UTF-8.
- A short western upload in UTF-8 whose accented letter is not in D-599's list is refused where the upload reader
  read it (the reviewer: 6 of 34 realistic one-line uploads, such as a two-word title with `é`); a document is
  read as before.
- Known limits. Thai in TIS-620: its words are the same bytes as runs of half-width kana, and a rival that
  refused them would refuse every kana sheet (16 of 180 fuzzed Thai lines are read as kana). A document of at
  least 40 ASCII letters whose only non-ASCII bytes are a legacy character that is valid UTF-8 by chance is read
  as UTF-8 (2.8 % of single Big5 words). A caller that names one language is read on a tie, by decision 2: text
  of another language given to it can be read wrong. An upload that is valid UTF-8 and holds U+FFFD is read with
  it, as before D-599.
