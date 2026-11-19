# Intended use in Japan: the device question as the project reads it, and what TrialBox must never say

| Field | Value |
| --- | --- |
| Document ID | TB-IU-01-JP (the Japan part of TB-IU-01, `docs/plan/intended-use.md`) |
| Version | 0.3, draft (2026-11-19; card 10C-5, source JP-4 of `docs/reviews/2026-11-root/11-japan.md` section 3; decision D-1228) |
| Status | **Not legal advice.** The project's own reading, to be confirmed with the regulatory adviser (TB-IU-01 R1, R5) and with the ministry through the free 該当性 consultation filed after this card (plan 10 decision 65) |
| Enforced by | `libs/tb_common/wording.py` (`FORBIDDEN` and the `CLAIM_*_JA` lists, `check`), tested in `tests/unit/test_wording.py` |

## 1. The question

Under 薬機法 第2条 a program is a medical device (プログラム医療機器) when it is intended for the diagnosis, treatment
or prevention of disease. The MHLW guideline 「プログラムの医療機器該当性に関するガイドライン」 (薬生機審発0331第1号・
薬生監麻発0331第15号, 2021-03-31, last revised 2023-03-31;
<https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000179749_00004.html>) asks two questions: the program's intended
use, judged from its function and from what its labelling, explanations and advertising say (TB-IU-01 J1), and the
risk to life and health if it fails (J2). One device function makes the whole program a device. What the product says
is therefore one of the things that decide the answer: a claim in the product's own words can count against it even
when the function is unchanged.

## 2. The reading: a criteria-based record listing

TrialBox applies a study's written eligibility criteria, which the user sees, to the hospital's own records, and lists
the patients whose records may meet them, each with the record passage it rests on. The investigator decides every
case. The ministry's case database 「医療機器プログラム事例データベース」 (the version on the page above, updated
2026-09-08, corrected 2026-10-14; the four rows below checked against it on 2026-11-19) places this:

| Case | What it does | Ruling | What it means for TrialBox |
| --- | --- | --- | --- |
| Guideline, non-device examples | Programs that only display, store or transfer health records for medical staff | Not a device | Showing record passages to research staff |
| No.107 レセプトデータ抽出プログラム | Narrows receipt data to people matching conditions **disclosed to the user** and outputs a list, nothing more | 非該当 | The closest case to criteria-based record listing. Keep the criteria visible on every list |
| No.223 医療文献検索プログラム | A generative model searches medical literature and shows the results | 非該当 | Reading text with a model is not by itself a device |
| No.74 急性腎障害リスクアラートプログラム | From a patient's EHR labs, AI computes the probability of acute kidney injury and shows it to doctors, in all four variants including "to identify high-risk patients for in-hospital work" | 該当 (all four) | A per-patient risk, probability or score shown to a clinician is a device, even framed as work support |
| No.243 遺伝性血管性浮腫診断補助プログラム | Compares EHR data with typical cases of a rare disease to support diagnosis | 未判断 (in-house use only); may be a device if distributed | A list of patients who may have an undiagnosed disease is on the device side |

**The project's reading.** TrialBox is a criteria-based record listing in the sense of No.107: it narrows records to
the conditions a study states and the user sees; it does not find disease, predict an outcome, or give a patient a
risk or a score of its own, and it informs no one's care. The project reads it as **not a device under the Japanese
rules, to be confirmed with the regulatory adviser and the ministry**, and only as long as it never says otherwise.

**The scores it does compute, honestly.** The box computes some named clinical scores nightly by their published
formula (eGFR, DAS28, CDAI, SDAI) and stores scores a clinician enters (ECOG and other named scales), because study
criteria are written in them ("eGFR ≥ 30"). These are record values compared with a criterion's threshold, not a
risk or prognosis the product makes up about a patient, and they are shown to research staff inside a study, not to
a treating doctor for care. Whether that holds is part of what the adviser confirms (TB-IU-01 C5). Any score of the
product's own, or any of these shown for care, changes the reading (TB-IU-01 section 5).

## 3. What it must never say, in plain words

Finding **candidates for a study** by its written criteria is what TrialBox does, and may be said
(「治験に必要な患者を見つける」, 「候補者を一覧にします」). Finding, detecting or predicting **disease**, and giving a
**patient** a risk or score, is the device side, and is never said. The difference is the object, not the verb.

The product, its pages, mails, reports, guides and the public site never say that TrialBox, "the AI", "the system"
or a model:

- finds, detects or screens for disease or its signs, early or latent cases (疾患・兆候・発症を 発見／検出／検知,
  希少疾患のスクリーニング, 早期発見, 潜在患者, 掘り起こす, 拾い上げ);
- predicts a disease, an outcome or a prognosis (疾患を予測, リスク予測, 予後, 発症予測);
- gives a patient a risk, a danger level, a probability or a score (患者のリスク, 危険度, AIスコア, スコアリング);
- lists patients suspected of, or not yet diagnosed with, a disease (疑い患者, 未診断);
- diagnoses, supports diagnosis or judges (診断, 診断支援, 判定; AIが…判断). In the product's own words a judgement
  always has a person as its subject (医師が判断します); what a model does is 読み取り (reading the record).

What it says instead: 「研究計画書の選択・除外基準に照らして、記録上の該当状況を一覧にします。参加の可否は治験責任医
師が判断します。」 and the intended-use statement of TB-IU-01 section 1. A sentence that denies a claim
(「本製品は診断、予測、スコアリングを行いません」) may be said.

The same words stay usable where they make no claim about a patient or a disease: バイアスのリスク (risk of bias);
a named clinical scale (ECOG スコア, eGFR); a laboratory's 検出限界; a study's enrolment forecast (登録予測), which is a
count; the system detecting a settings change; information-security risk; and a protocol's or chart's own text, which
the product quotes as written (D-351).

## 4. Where the check runs, exactly

**What the check is.** A lint over the project's own Japanese texts that catches common claim forms. It is not a
guarantee that a text makes no device claim. **Every new Japanese public text still needs a human reading** (the
owner's Japanese colleague, and the adviser for anything external).

The rule is `check()` in `libs/tb_common/wording.py` (D-1228 describes it). It is not part of `make lint`; it runs in
the test suite (`make test`, and the CI job that shards it), through these tests:

- `tests/unit/test_wording.py`: every console, orchestrator and opportunity-hub catalogue string in three languages,
  every console template, and the Japanese text of the public site (`site/pages/*.html`, `site/i18n/site_text.json`,
  `site/i18n/criteria_ja.json`; the claim rule only);
- `tests/console/test_wording_walk.py`: every GET page of every role in three languages;
- the other callers of `check` and `check_page` (report, mail and page tests).

Not scanned: the guides and handover sheets in `docs/` (scanned once by hand for this card: no claim), `README.md`
and deploy messages (English), and the public site's words other than Japanese claims.

## 5. Known limits

Measured by the lane coordinator on independent sets of Japanese sentences the rule had not seen:

| Commit | Claims missed | False alarms on legitimate lines |
| --- | --- | --- |
| 82f4c721 | 10 of 35 | 5 of 25 |
| 0a5b7170 | 14 of 40 | 7 of 40 |

The commit after 0a5b7170 fixes the denial forms, the 候補者 false alarm, invisible characters and inline tags (the
items marked *fixed* below); it has not been re-measured. What a word list cannot catch stays a known limit:

- other spellings and inflections of the listed verbs (kana for kanji, conjugated stems), unlisted verbs of finding,
  estimating, deciding, ranking, early intervention or risk, and disease names not on the disease list;
- a disease word more than 12 characters from the verb;
- a synonym of 判断 (見極め, 決定 …);
- a person as subject in a later clause clearing the product's judgement in an earlier one
  (「AIが、医師が見る前に参加可否を判断します」 passes);
- a named clinical scale masking the product's own estimate of it (「AIがECOGスコアを推定します」 passes);
- a negative ending later in the same clause read as a denial of an earlier claim word, when no comma separates them;
- *fixed:* the common denial forms (「…機能はありません」, 「…ものではありません」, 「…ツールではありません」,
  「…判断を行いません」, 「…機能もありません」), a quoted denial inside a double negative, 候補者 counted as a patient
  word, zero-width characters, and inline tags splitting a subject from its verb.

**The follow-up card:** lemma matching with a Japanese morphological analyser and a disease test drawn from the
product's own vocabulary. It waits on the owner's decision about the library.

## 6. Change history

| Version | Date | Change |
| --- | --- | --- |
| 0.1 | 2026-11-18 | First draft (card 10C-5): the case-database reasoning of review 11 section 3, the words never said, the check |
| 0.2 | 2026-11-19 | Review: "criteria-based record listing"; the reading marked as the project's, to be confirmed; the guideline's notice numbers and page; the four case rows checked against the database; the nightly scores addressed; the candidate / disease distinction; exactly where the check runs |
| 0.3 | 2026-11-19 | Second review: the title no longer reads as a conclusion; the check stated as a lint, not a guarantee, with the measured rates and the known limits (section 5); the follow-up card |
