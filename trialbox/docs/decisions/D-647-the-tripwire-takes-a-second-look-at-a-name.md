# D-647 The tripwire takes a second look at a name finding on a Japanese line

- **Task:** NEW-LLM-4 (plan v7 wave 2; deep review LLM-003): "the PHI tripwire stops refusing ordinary ja
  criteria". NEW-LLM-3, the same for Traditional Chinese, is **not done by this card** (see "Not taken").
- **PR:** this branch (`agent/NEW-LLM-3-tripwire-tokeniser`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on a green train)
- **Ruling:** the owner's choice of 2026-11-13, relayed by the integrator: "B" of three options (A: the wider
  rule for both languages; B: Japanese only, Chinese as before; C: no change).

## Reuse proposal (accepted by the integrator 2026-11-13)

| What | Project | Licence | Pinned | Where |
| --- | --- | --- | --- | --- |
| Japanese part-of-speech tags | SudachiPy | Apache-2.0 | 0.7.0 | inside the tripwire only |
| its dictionary | sudachidict-core | Apache-2.0 | 20261015 | a wheel in the lock; nothing downloaded at run time |

**What the gates said** (by running, before the lock changed): `make lock-check` PASS with uv 0.13.7; allow-list
check PASS, no entry needed; pip-audit "No known vulnerabilities found", gate PASS; the licence gate on the lock's
SBOM PASS, both packages Apache-2.0. Installed size: the dictionary 193 MB, the tokeniser 4.9 MB (wheels 76.9 MB
and 1.8 MB): about +198 MB in the one Python image, the bundle and the media (for lane D). They are base
dependencies: there is one Python image for the services (the integrator's ruling).

Not taken: fugashi with UniDic (measured; dictionary terms and a native build); Presidio (a yardstick outside the
lock only).

## Context

The name recognisers are patterns: a surname, one to three more characters and a cue (a label, an honorific, a
sex). In running text that shape is everywhere: 患者 高血圧の…, 患者連絡…, 個案曾使用…. Measured on synthetic sets
(`tests/fixtures/guard`), the tripwire refused 72.7 % of ordinary Japanese sentences and every one of the Chinese.
A refused judge call is an unknown.

## Decision

1. **A second look at a NAME finding on a line that holds kana** (`guard.names.Look`; `Guard.tripwire`). It
   takes the finding away only when all three hold: the tokeniser (split mode C) tags no token inside the match
   as a proper noun; no cue stands beside it (an honorific inside the match or right after it, a sex after it,
   a surname of more than one character); and the match is plainly a Japanese word: one word of the tokeniser's
   own dictionary, longer than one character, covers the match from the surname's place to its end (高血圧,
   連絡). A line ends at every kind of line break.
2. **Everything else stands as before.** A finding on a line without kana: so Chinese text, and a Japanese name
   on a line without kana, are judged exactly as before this card. Every other kind of finding. A name in Latin
   letters. A name the dictionary does not know. A Chinese name beside a Japanese drug name (丁子｜涵: 丁子 is a
   word of the dictionary, but it does not cover the name).
3. **Who takes the look**: the gateway's tripwire, the guard service's `/v1/scan`, the test bench. **Who does
   not** (every pattern match counts): redaction at the trace store; the document parser's mask of a protocol's
   contact and subject lines; the older scan's other callers (the cloud clearance, consent, site set-up); note
   masking. The older scan inside the tripwire (`tb_common.phi_guard.scan`) takes the look through a parameter,
   for its name findings and its "date near a name" finding.
4. **It fails closed.** When the tokeniser or its dictionary cannot be loaded, raises, or the line is longer
   than 4,000 characters (`MAX_LINE`: not prose, and the tokeniser's time grows with the line), the finding
   stands. `trialbox doctor` has the check `tripwire_names`: WARN with the reason (also after a failure on a
   text, until the service restarts; the reason never quotes the text), since nothing is let through.
5. **The dictionary is pinned and named** (`guard.names.DICTIONARY`, the lock). Another dictionary is a
   re-measurement on the sets, as a model change is a requalification.
6. **The standing gate** (the integrator's rule): `tests/guard_sets.py` and a ceiling per shape in
   `test_tripwire_name_second_look.py`, in the unit suite: 0 for every Chinese shape, by construction; the
   measured 0 or 1 for the Japanese shapes. No change of the tripwire passes on an average or on an easy set;
   raising a ceiling is the owner's decision.

## Measured, with the code of this card

**Ordinary text refused** (`tests/fixtures/guard`): Japanese 96 of 132 (72.7 %) before, 29 of 132 (22.0 %)
after. What stays refused is text the tokeniser splits (高｜血圧｜症: no one word covers the match) or that ends at
a cue. Chinese: 84 of 84 before and after.

**Names let through** (synthetic; "let through": the patterns find the name and the tripwire no longer refuses
the text). Each row is true of the set named, not beyond it:

| Shapes and names | Names found | Let through |
| --- | --- | --- |
| Chinese name with a two-character given name (115 listed surnames x 50), every shape of the reviews: cue or boundary (13), run into text (6), on a line with kana (8), middle dot, subject line (4) | 5,750 per shape | 0 |
| Chinese name with a one-character given name (115 x 12), on a line without kana, or with a cue or a boundary on a line with kana | 1,380 per shape | 0 |
| **the same with no cue, on a line with kana** (after a label and before は / の, before kana, before a digit or Latin with kana later; 5 shapes) | 1,380 per shape | **12 (0.9 %)**: 朱華 湯華 王軍 白明 白雪 白華 白軍 簡明 蘇芳 金平 陸軍 黎明 |
| the third review's wider pools for that shape: 132 given characters; 106 one-character surnames x 338 kanji | 13,860; 35,828 | 393 (2.8 %); 779 (2.2 %), most of them plain words (古書, 方法), 25 to 175 plausible names |
| Japanese name, every listed surname x 16 given names: with kana on the line (7 shapes), after a label before は / が / の / に (4), without kana (6) | 928 per shape | 0 |
| 森 and 林 with given names the dictionary does not hold, and with given names in kana, after a label before a particle (4 shapes) | 20 each | 0 |
| surnames of more than one character (third review: kanji and kana given names) | 259,908 and 1,120 per shape | 0 |
| the document parser's mask, the second review's 13 subject and contact shapes | 4,200 each | 0 lost |

Time: 2 to 5 ms a Japanese sentence; about 1 s once per process to load the dictionary.

## The trade, and the limits

- **A two-character name that is itself a word of the Japanese dictionary is let through** when it follows a
  patient label on a line with kana and no cue or boundary stands beside it: a surname of one character and a
  given name of one character, 白雪 ("white snow"), 黎明 ("dawn"), 王軍, 金平. On the sets: 0.9 % of such
  two-character names with the repository's twelve given characters, 2.2 to 2.8 % on the third review's wider
  pools. The gain of this card comes from the same place (連絡, 方法 are such words): asking for a word of three
  characters or more lets none of these through and gives the gain back (94 of 132 refused). With a cue, a
  boundary, a third character, or on a line without kana, the name stands. A test holds the case.
- The first form of option B also took away a match that itself held kana; the third review measured 11.6 % of
  森 with an uncommon two-kanji given name let through by it (the pattern's match runs on into the particle).
  Removed; it gained nothing on the ordinary set.
- **Traditional Chinese is not helped**: ordinary Chinese text that matches a name pattern is refused as before
  (LLM-003 stays open for zh-TW; see "Not taken").
- The sets are synthetic; real notes will differ. Three reviews each found a shape the sets before them did not
  hold; the table says what was measured, not what cannot happen.

## What the name patterns never find (before and after this card; by running, both reviews)

1. A name with no label, honorific or sex beside it (LLM-004).
2. A name after a role rather than a patient label: 計畫主持人：N, 協同主持人N, 研究護理師N, N醫師 / 教授 / 主任 / 藥師 /
   護理師 / 博士, 治験責任医師：N, 担当CRC N, 署名：N 日付：, 簽名：N 日期：, 聯絡人 N 分機1234, names in lists or table
   rows.
3. Surnames outside the two lists: 朴, 崔, 武 (金, 鄭, 阮, 范, 黎 are listed); Japanese surnames beyond the 58 listed.
4. Simplified forms of surnames: only 黄, 温, 邱, 洪 of 37 Simplified-only forms are listed (病人张伟今日复诊 is not
   found).
5. Names in kana only; names in Latin letters without a title; a name with a middle dot inside it.
6. A surname at the end of one line with the given name on the next is found only in part.

A line that also holds a phone number, an e-mail, an ID or a chart number is refused for that finding.

## Not taken: the wider rule (option A), and what its two first forms got wrong

Option A also judged Chinese: a finding stood when a cue or a boundary followed, and otherwise unless it "read
as words" by a list of common Chinese words (built from the jieba project's dictionary file, MIT; removed with
this choice, with its builder, NOTICE entry and licence row).

1. The owner first approved it on "97.9 % of names kept". That figure came from a set that was too easy: most
   names ended at a boundary, a dozen given names, none a common word, no compound surname, no line mixing
   Chinese and kana. The first review measured 7.2 % let through for a Chinese name run into text (100 % for
   歐陽 and 上官), 21 % for a Chinese name on a line with kana, 37 to 41 % for a Japanese name on a line without
   kana.
2. The reworked form's table said "0 on a line with kana"; its shapes all carried a cue or a boundary. The second
   review measured 24 to 27 % for a Chinese name run into text on such a line and 26 % after a middle dot.
3. After both were fixed, a Chinese name run straight into text was still let through in 3.3 % of cases on the
   hard set, and that figure was the middle of a wide spread: 12.9 % for the sixteen surnames that are ordinary
   words (黃, 高, 許, 曾 ...), 0.7 % to 63 % across the second review's own name sets, depending on how word-like
   the given name is. And the gain was smaller than first said: where a comma, a digit or a line end follows an
   ordinary word, 65 % of the second review's composed texts were still refused.

Two reviews in a row found 20 to 60 % in shapes the author's sets did not hold. A synthetic set of this lane
cannot approve a rule for Chinese names; it needs test material a site can judge. That is a finding for the
integrator, not a card.

## Test

`tests/unit/test_tripwire_name_second_look.py` (the rule, fail closed, the per-shape ceilings, the stated limit,
doctor, the lock), `tests/guard_sets.py`.
