# D-923 An English chart from a Taiwan hospital is masked: romanised and Han names, and the English form of an address

- **Task:** NEW-B-55 (D-1037's independent check, `eval/phi_second_opinion`), lane B2 · **PR:** `agent/NEW-B-55-english-taiwan-charts` · **Date:** 2026-11-16 · **Status:** accepted · **Builds on:** D-744, D-745, D-756, D-759

1. **A Taiwanese name in Latin letters is masked with no label when written as Taiwan writes it.**
   - The surname is one of `ROC_SURNAMES_LATIN` (178: Wade-Giles, pinyin, the passports' own spellings, compound ones), or two of them for a married woman's double surname.
   - The given name is two romanised Mandarin syllables joined by a hyphen or an apostrophe, or dotted initials: `Chen Mei-Ling`, `Mei-Ling Chen`, `CHEN MEI-LING`, `Chen Lin Mei-Ling`, `Chen M.L.`.
   - After the record's comma, any two syllables count (`CHEN, MEI LING`). A possessive after the name is left.
2. **With a label** (`Patient:`, `Name:`, a title, a relative's word) the name may be written any way: unjoined syllables, capitals, a comma, an initial first, `O'` or `Mc`.
   - With no label, no comma and no hyphen (`Chen Meiling`) it is **not** read. This is the known limit.
   - The reason: the second adversarial review counted 37 % of a chart's capitalised words as two syllables (`Lung Cancer`, `Pan Neuro`, `Tang Kuei`, `Kao Hsiung`), and a masked diagnosis is a wrong answer.
3. **A Han name of the ROC surname list is masked after:**
   - an English label with its colon (`Name`, `Pt`, `VS`, `Nurse`, `Resident`, `Physician`, ...);
   - a word for a relative;
   - a staff word (`R1`, `NSP`).
   
   Spaces between its characters are allowed, and a second name after the first is masked too. A Han name is never read after a bare `Patient` or `by` (`Patient 高血壓`, `Referred by 林口`).
4. **A Taiwan address in its English form is masked in bounded parts**, in the post office's order and in the Chinese order (`Taipei City Da'an District Heping E. Rd. Sec. 1 No. 18 5F`). The parts are:
   - room and floor;
   - `No` or `No.`;
   - lane, alley, section, neighborhood (ordinal too) before or after the road;
   - village, district, township, town, city, county, a city of Taiwan by name, `Taiwan`;
   - postcode.
   
   Both orders run only around `No` and a number, in windows longer than their longest match.
5. **Version, time, measurement and tests:**
   - `NOTE_MASK_VERSION` is 6.
   - Every new quantifier is bounded, and each new pattern's gate is a necessary condition (D-756).
   - Presidio beside version 6 finds every planted identifier of the English Taiwan charts, and nothing new is flagged on the public notes.
   - Tests: `tests/unit/test_phi_english_taiwan_charts.py` holds both reviews' leaks, over-masking, time and window cases, and the known limit.
   - Known over-masking (a word, never a leak): a two-character Han word after `Patient:`; a whole hyphenated word after `Dr.` or a relative's word; a capitals `WORD, WORD` after `Patient:` or `Name:` (`PATIENT: STABLE, AFEBRILE`).
