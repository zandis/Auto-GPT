# D-923 An English chart from a Taiwan hospital is masked: romanised and Han names, and the English form of an address

- **Task:** NEW-B-55 (D-1037's independent check, `eval/phi_second_opinion`), lane B2 · **PR:** `agent/NEW-B-55-english-taiwan-charts` · **Date:** 2026-11-16 · **Status:** accepted · **Builds on:** D-744, D-745, D-756, D-759

1. **A Taiwanese name in Latin letters is masked with or without a label:**
   - A surname of `ROC_SURNAMES_LATIN` (Wade-Giles and pinyin, compound ones too: 157) and a given name of two romanised Mandarin syllables, in either order and either case, with or without a hyphen, space or comma: `Chen Mei-Ling`, `Chen Meiling`, `CHEN, MEI LING`, `Mei-Ling Chen`, `Chen M.L.`.
   - A possessive after it is left.
   - The syllable shape keeps English out (`He Self-Harmed`), and a short list keeps romanised medicine out (`Ma Huang`, `Tai Chi`).
2. **English names after a label or word:**
   - A Latin name after a title, `Patient:`, `Name:` or a word for a relative may be hyphenated, start `O'`, and run to three words and an initial.
   - Capitals after a label take only the record's `SURNAME, GIVEN` form, so `PATIENT: HTN, DM` and `NPO AFTER` are left.
   - A surname in capitals after `Mr`, `Ms` or `Miss` is masked, the title kept.
3. **A Han name after an English word:** a Han name of the ROC surname list is masked after an English label with its colon, a word for a relative or a staff word, a second name too. Never after a bare `Patient` or `by` (`Patient 高血壓`, `Referred by 林口`).
4. **A Taiwan address in its English form** is masked in bounded parts: room and floor; `No` or `No.`; lane, alley, section and neighborhood before or after the road; village, district, township, city, county or a city of Taiwan by name; postcode.
   - It is run only around `No` and a number, in a window longer than its longest match (`ADDRESS_TW_EN_MAX`), so the window loses nothing.
   - Every new quantifier is bounded (the adversarial review's quadratic white-space run is gone), and each new pattern's gate is a necessary condition (D-756).
5. **Version, measurement, tests and known limits:**
   - `NOTE_MASK_VERSION` is 6. Presidio beside version 6 finds every planted identifier of the English Taiwan charts, and nothing new is flagged on the public notes.
   - Tests: `tests/unit/test_phi_english_taiwan_charts.py`, holding every leak, over-masking case and timing case of the adversarial review.
   - Known over-masking, a word and never a leak: a two-character Han word after `Patient:`; a whole hyphenated word after `Dr.` or a relative word where version 5 took its first half; title-case English after a romanised surname (`He Can Go`).
