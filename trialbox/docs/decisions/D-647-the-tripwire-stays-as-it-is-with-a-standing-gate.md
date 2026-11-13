# D-647 The tripwire stays as it is for go-live; its name patterns get a standing gate

- **Task:** NEW-LLM-3 / NEW-LLM-4 (plan v7 wave 2; deep review LLM-003): "the PHI tripwire stops refusing ordinary
  zh-TW and ja clinical text"
- **PR:** this branch (`agent/NEW-LLM-3-tripwire-tokeniser`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on a green train)
- **Ruling:** the owner's choice of 2026-11-13, relayed by the integrator: "C" of three options (A: a second look
  at Chinese and Japanese findings; B: at Japanese findings only; C: no change to the tripwire, the tests only).

## Context

The name recognisers are patterns: a surname, one to three more characters and a cue (a label, an honorific, a
sex). In running text that shape is everywhere: 患者 高血圧の…, 患者連絡…, 個案曾使用…. Measured on synthetic sets
(`tests/fixtures/guard`), the tripwire refuses 96 of 132 ordinary Japanese sentences (72.7 %) and every one of the
84 Chinese sentences collected because they are refused. A refused judge call is an unknown.

The card tried to take such findings away with a tokeniser's second look. Three forms were built, each measured
by its author on a set of names and passed, and each adversarial review then found shapes of real names that were
let through. The best form (option B) still lets through a kind of name that cannot be told from a word.

## Decision

1. **The tripwire is not changed for go-live.** No tokeniser, no dictionary, no change to the lock, the guard,
   the document parser or the doctor. What it costs stays: much ordinary Japanese and Chinese text is refused,
   and the judge answers unknown for it. LLM-003 stays open.
2. **A standing gate** (`tests/unit/test_tripwire_name_gate.py`, the names and shapes in `tests/guard_sets.py`):
   synthetic Chinese and Japanese names in every shape the three reviews found a name let through in, with a
   ceiling **per shape** on how many the tripwire lets through. Every ceiling is 0. Any later change to the
   tripwire must pass it; raising a ceiling is the owner's decision. The same file holds what the tripwire costs
   today (96 of 132), so a gain is seen as a changed figure.
3. **Option B is kept, not merged**: branch `backup/a2-d647-option-b` (head `2e7d99fd`), measured below, for later
   if the Japanese site finds the refusals a burden.

## Option B, as measured (not merged)

A NAME finding is taken away only on a line with kana, when the tokeniser (SudachiPy 0.7.0, sudachidict-core
20261015) tags no proper noun in it, no cue stands beside it, and one dictionary word covers the match.

- Ordinary Japanese text refused: 96 of 132 (72.7 %) today, 29 of 132 (22.0 %) with B. Chinese: unchanged.
- Names let through with B: 0 in every shape of the gate but one. **A two-character name that is itself a word
  of the Japanese dictionary** (a surname of one character and a given name of one character: 白雪 "white snow",
  黎明 "dawn", 王軍, 金平), after a patient label, on a line with kana, with no cue: 12 of 1,380 per shape (0.9 %)
  with the repository's twelve given characters; on the third review's wider pools 393 of 13,860 (2.8 %) and 779
  of 35,828 (2.2 %), most of them plain words (古書, 方法), 25 to 175 plausible names. The gain comes from the
  same place (連絡, 方法 are such words): asking for a word of three characters or more lets none through and
  gives the gain back (94 of 132 refused).
- Cost: the tokeniser and its dictionary in the lock, about 198 MB more in the image; 2 to 5 ms a Japanese
  sentence, about 1 s once per process.
- The gate of this card, run on B's code: the cost figure reads 29, the shape "Chinese, one-character given
  name, no cue, on a line with kana" lets 12 of 1,380 through, and 患者白雪は… is not refused.

## Not taken: the wider rule (option A), and what its forms got wrong

Option A also judged Chinese: a finding stood when a cue or a boundary followed, and otherwise unless it "read
as words" by a list of common Chinese words (built from the jieba project's dictionary file, MIT).

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

## What the name patterns never find (by running, in the reviews)

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


The gate holds the names the patterns do find. It says nothing about these.

## Test

`tests/unit/test_tripwire_name_gate.py`: 16 tests. They pass on today's tripwire (this card changes no code);
three of them fail on option B's code, as said above. The sets are synthetic; real notes will differ. Three
reviews each found a shape the sets before them did not hold: the gate says what was measured, not what cannot
happen.

## Review

Three adversarial reviews, by running, of the forms not taken (their findings are the shapes of the gate). The
card as it lands changes no code that decides anything; it was not reviewed again.
