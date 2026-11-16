# D-983 The cascade reads the language of the notes, not the report's

- **Task:** NOTE-LANGUAGE-THRESHOLDS, from G12 of the integrator's second review of the P1b run (#639, 2026-11-16).
  - The cascade took the site's report locale (`site.locale`) as the language of the notes. The owner confirmed that charts are "mainly english in cgmh and taiwan", so at a zh-TW site that is the product's main path.
  - The integrator ranked this card after the cards already built.

  **Date:** 2026-11-16. **Status:** reserved.
- **Measured on the stored P1b data (#639).** Every pair went on to the models.
  - **No threshold changed:** without a site fit, every language uses the same public prior (0.10).
  - **S2 found terms almost nowhere:** its fixed 35-word table gave no term for 160 of sigir's 178 note criteria, nor for either of jmed's.
  - **S2b passed every pair:** 704 of 704.
- **The language-dependent choices** (listed with file and line on #639):
  - the S2b threshold's stratum;
  - S2's certified zero hit;
  - the index-condition sweep's absence.

  The judge prompt, date parsing and the excerpt heading cues do not depend on a language setting.
- **Decision**
  - **`matching.notelang`** reads a note's language from its script: kana means ja, Han without kana means zh-TW, Latin words mean en. A Taiwan chart with English text under Chinese headings and Chinese drug names is en, and a Japanese note with English drug names is ja. A patient's language is the one most of their window's notes are written in, by length.
  - **The site setting `notes_language`** (`auto` / `en` / `zh-TW` / `ja`, default `auto`) declares the notes' language. `auto` reads it from the notes. With nothing to read, the report locale is the fallback. The setting's name and default await the owner.
  - **The S2b threshold is the one for the patient's notes' language** (`Run.language_of`), and the trace records the language used.
  - **Fail safe, where the notes' language is known and is not the one the site's tables were set for** (`Run.mismatched`: declared, or read from the notes, and not the report locale):
    - The index-condition sweep never excludes under absence semantics on a threshold not fitted to that language. The public prior is a placeholder (CAS-14), so a person looks instead.
    - A certified zero hit counts only when the criterion's terms include one in the notes' script.
    - Where the language is the site's own, or cannot be told, the earlier rules stand, and their safety tests pass unchanged (CAS-11, CAS-13, CAS-18).
    - **For the integrator:** a stricter reading would apply both rules to every language until a stratum has a fit. That stops FEAS's index-absent exclusions everywhere, and it contradicts the agreed safety tests, so it is not built here.
- **Adversarial review** (this card). No blockers: nothing drops a patient that was kept before.
  - **High, fixed: the language cache.** It was filled from whichever criterion's window came first, so a short first window, or a Chinese window before an English one, decided by criterion order. It is now read once per patient from all their notes, at S2.
  - **Medium, fixed: detection.**
    - Japanese mostly in kanji is now ja: one Japanese-only kanji (歴 薬 変 検 …) suffices, since Chinese writes those characters differently.
    - Chinese with English abbreviations is now zh-TW: a word needs three letters or more with lower case, so SOB, CBC, Hb and Na are none.
    - A long lab table no longer outweighs the narrative: notes are weighed by their words and characters, not their length.
  - **Medium, fixed: cost.** The certified-list test runs before the language. That list is empty in screening.
  - **Low, fixed: the locale is read as its language** (ja-JP → ja, zh-Hant → zh-TW).
  - **Low, open:** once per-language fits exist, a patient read as en is judged on the en fit. If that fit is stricter, the index sweep may exclude where the zh-TW fit would have rescued. Calibration owns that, after D-517.
  - **Inert today:** screening runs with absence semantics off and no certified list, and no site fit exists. In production the change today names the right language in the trace and picks the same prior.
- **Not in this card:**
  - Calibration: no claim until the D-517 gold set exists per language.
  - S2's lexicon coverage: the 35-word table, and its "egfr" read as the receptor.
- **Test:** `tests/unit/test_note_language.py`.
