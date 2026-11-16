# D-923 An English chart from a Taiwan hospital is masked: romanised and Han names, and the English form of an address

- **Task:** NEW-B-55 (D-1037's independent check, `eval/phi_second_opinion`), lane B2 · **PR:** `agent/NEW-B-55-english-taiwan-charts` · **Date:** 2026-11-16 · **Status:** accepted · **Builds on:** D-744, D-745, D-756, D-759

1. A Latin name after a title, `Patient:`, `Name:` or a word for a relative (and after `brought by`, `accompanied by`, `caregiver`, `guardian`, with or without a comma) may now be:
   - hyphenated (`Mei-Ling`, `Ellison-Ward`);
   - up to three words and an initial;
   - in capitals, surname first (`CHEN, MEI-LING`), after `Patient:` or `Name:`.
2. A Taiwanese name in Latin letters with no label is masked as one of the common surnames of Taiwan, in Wade-Giles or pinyin (`ROC_SURNAMES_LATIN`, 98), with a two-syllable hyphenated given name, in either order or in capitals (`Chen Mei-Ling`, `Mei-Ling Chen`, `CHEN MEI-LING`). A hyphenated medical term (`Guillain-Barre`) has no such surname and is left.
3. A Han name of the ROC surname list after an English label or a word for a relative (`Name: 黃家豪`, `son 曾冠宇`) is masked.
4. A Taiwan address in its English form (`13F., No. 322, Sec. 4, Minsheng Rd., Da'an Dist., Taipei City 106`) is masked, looked for only around each `No.`. Each new pattern has a gate that is a necessary condition of it (D-756).
5. `NOTE_MASK_VERSION` is 6. Tests are in `tests/unit/test_phi_english_taiwan_charts.py`: the shapes, the words left alone, the gates and window against the whole note, long runs in one pass, and the guard. Presidio beside version 6: every planted identifier of the English Taiwan charts is found, and nothing new is flagged on the public notes.
