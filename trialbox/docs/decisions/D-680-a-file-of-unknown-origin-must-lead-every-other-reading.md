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

1. **A file of unknown origin** (a caller that names more than one candidate family: the sheets, the uploads, the
   SS-MIX2 notes) **is read only when its reading leads every other reading by the confidence margin, the
   rivals' too.** A tie with a rival is a refusal.
2. **A caller that names one family has said what the file is** (a vendor's master is Shift_JIS): there a rival
   must read the file better to refuse it, as before.
3. **Windows-1252 and EUC-KR are rivals**, never candidates. In Windows-1252 an accented letter in a run that
   touches an ASCII letter is a western word; a run with nothing ASCII beside it weighs `_WESTERN_ALONE` (0.8),
   set so that such a run alone ties with its half-width kana reading and is refused, while a kana word with its
   voicing marks and spaces is still read (measured: at 0.9 half of a fuzz of kana sheets was refused, at 0.75
   five of 3,600 western lines were read as kana).
4. **The upload reader takes valid UTF-8 as UTF-8 for a document only**: a byte order mark, all ASCII, or at
   least `UPLOAD_WESTERN_TEXT` (40) ASCII letters. A shorter upload is a cell or a line and is judged as a sheet.
5. **Scoring is one pass**: each run of half-width kana is looked at once.

## Consequences

- Measured, as a test with a ceiling of zero per shape: 7,000 fuzzed short texts in EUC-JP, GB18030, EUC-KR and
  Windows-1252, alone, after `Dx:` and in a two-line sheet: none is read as wrong text, by the sheet reader or
  the upload reader (before: 1,491 of 7,200).
- The price, held by the same test: of small real sheets (one to eight rows) some are now refused where they
  were read. The test's floors: at least 90 % of Shift_JIS sheets of half-width kana words are read, 85 % of Big5
  sheets with one cell a row, 95 to 100 % of the others. None is read wrong. A refused sheet is read when saved
  as UTF-8.
- A short western upload with one accented letter that is not in D-599's list (`ø` alone in a cell) is refused
  where the upload reader read it; a document is read as before.
- Known limit: a caller that names one family (the licensed masters) is still read on a tie, by decision 2.
