# D-1228 The Japanese device-claims lint refuses the claim by its object, not the word

- **Task:** card 10C-5 of plan 10 (`docs/plan/47-plan-10-2026-11-18.md`, Track C; source JP-4 of
  `docs/reviews/2026-11-root/11-japan.md` section 3)
- **Date:** 2026-11-19
- **Status:** accepted; reserved for the pull request of card 10C-5 (lane J's block D-1220 to D-1319)
- **Builds on:** D-351 (a record's own field and quoted source text are not the product's wording), TB-IU-01
  (`docs/plan/intended-use.md`), its Japan part `docs/plan/intended-use-jp.md`

## Context

In Japan a program's device status is read partly from what it says it does. The wording check
(`libs/tb_common/wording.py`) refused 診断, 判定, 見逃し and AIが判定, but not "finds disease", "risk prediction",
"suspected patients" or "undiagnosed". A plain word ban does not work: on master 254 Japanese catalogue strings use
one of the words concerned (スクリーニング, 判断, スコア, 予測, 検出 ...) legitimately, and finding trial candidates is
the product's purpose.

## Decision

0. **It is a lint, not a guarantee.** The rule checks the project's own Japanese texts for common claim forms. It
   does not prove that a text makes no device claim; every new Japanese public text still needs a human reading.
   Measured on independent unseen sentences at 0a5b7170, it missed 14 of 40 claims and raised 7 false alarms on 40
   legitimate lines (at 82f4c721: 10 of 35 and 5 of 25). The known limits are in `docs/plan/intended-use-jp.md`
   section 5.
1. **Refuse the claim, by its object.** Compound claim nouns are refused outright (`CLAIM_OUTRIGHT_JA`: 早期発見,
   リスク予測, 予後, スコアリング, 未診断, 潜在患者 ...; 疑い患者 joins `FORBIDDEN`). A finding word (発見, 検出,
   スクリーニング ...) is a claim when its object is a disease, its signs or an early / latent case; a rate word
   (予測, リスク, スコア, 危険度, 確率) when it is about a patient or a disease, or the AI stands straight before it.
   Finding patients or candidates for a study is not a claim.
2. **Judgement has a person as subject.** 判断 is a claim when the product, the system, the AI or a model is its
   nearest subject. In the product's own words a judgement always has a person as subject; what a model does is
   読み取り. The catalogue strings that let a model or TrialBox be the implied judge are reworded so.
3. **Allowed contexts are data**, each pinned by a test: named clinical scales (a list, not any Latin word),
   バイアスのリスク, a lab's 検出限界, a study's enrolment forecast. A real denial (claim words and a negative verb that
   ends the clause) is not a claim; a double negative is.
4. **Denial is read by structure**, not from a list of phrasings: a claim word is denied when the rest of its clause
   carries an odd number of negative endings (「…機能はありません」, 「…ものではありません」 and a list of claim words
   with one negative verb all qualify; two negatives cancel). **Text is cleaned first**: NFKC, and zero-width and
   other invisible characters removed. **On a page** a block element ends a line and an inline tag joins, so a tag
   cannot split a subject from its verb. 候補者 is not a patient word (it is the product's own word for a candidate).
5. **It runs inside `check()`**, so every caller (catalogue tests, the page walk, report and mail tests) applies it,
   and a test applies it to the Japanese text of the public site. It is not part of `make lint`.

## Consequences

The reasoning and the plain list of what is never said are in `docs/plan/intended-use-jp.md`, marked as the
project's reading to be confirmed with the regulatory adviser and the ministry. zh-TW keeps the older word list
(診斷, 排除, 建議治療), weaker than ja: a follow-up card is needed. A Japanese morphological analyser would find the
grammatical subject and object better than the windows used here. The follow-up card (lemma matching with such an
analyser, a disease test from the product's own vocabulary) waits on the owner's decision about the library.
