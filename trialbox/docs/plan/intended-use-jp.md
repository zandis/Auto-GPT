# Intended use in Japan: why TrialBox is not a programmed medical device, and what it must never say

| Field | Value |
| --- | --- |
| Document ID | TB-IU-01-JP (the Japan part of TB-IU-01, `docs/plan/intended-use.md`) |
| Version | 0.1, draft (2026-11-18; card 10C-5, source JP-4 of `docs/reviews/2026-11-root/11-japan.md` section 3) |
| Status | **Not legal advice.** The project's own reasoning, to be confirmed by the hospital's adviser or a regulatory adviser (TB-IU-01 R1, R5), and by the free MHLW 該当性 consultation filed after this card (plan 10 decision 65) |
| Enforced by | `libs/tb_common/wording.py` (`FORBIDDEN`, `CLAIMS_JA`, `check`), tested in `tests/unit/test_wording.py` |

## 1. The question

Under 薬機法 第2条 a program is a medical device (プログラム医療機器) when it is intended for the diagnosis, treatment
or prevention of disease. The MHLW guideline 「プログラムの医療機器該当性に関するガイドライン」 (2021, revised
2023-03-31) judges that intent from what the program and its labelling, explanations and advertising say it does
(TB-IU-01 question J1), and from the harm a malfunction could do (J2). One device function makes the whole program a
device. So in Japan the line runs through **words**: the same list, described as "the system finds patients at risk",
can be on the other side.

## 2. The reasoning: a case-finding aid over a case database

TrialBox applies a study's eligibility criteria, which the user sees, to the hospital's own records, and lists the
patients whose records may meet them, each with the record passage it rests on. The investigator decides every case.
The MHLW case database places this:

| Case | What it does | Ruling | Why TrialBox sits with it, or must stay away |
| --- | --- | --- | --- |
| Guideline non-device (2)① | Health-record viewing by medical staff | Not a device | Showing record passages to research staff |
| Case DB No.107 | Narrows receipt data to people matching conditions **disclosed to the user** and outputs a list | 非該当 | The closest case: criteria-based patient listing. Keep the criteria visible on every list |
| Case DB No.223 | Literature search with a generative model | 非該当 | Reading text with a model is not by itself a device |
| Case DB No.74 | Computes a patient's risk (acute kidney injury) from EHR labs and shows it to doctors, even as "work support" | **該当** | A per-patient risk or score shown to a clinician is a device: TrialBox shows none |
| Case DB No.243 | Compares EHR data with typical cases of a rare disease to support diagnosis | 未判断; device-side if distributed | "Patients who may have undiagnosed X" is a device: TrialBox makes no such list (plan 10 decision 68) |
| Guideline example 1)⑥ | Shows an individual's disease candidates or risk | Device | Never "this patient may have X" |

**Conclusion (the project's reasoning).** TrialBox is a case-finding aid over a case database, in the sense of
No.107: it narrows records to the conditions a study states and the user sees; it does not find disease, predict an
outcome or score a patient, and it informs no one's care. It is therefore not a device under the Japanese rules,
**provided it never says otherwise**. A claim alone can move it across, because intent is read from what it says.

## 3. What it must never say, in plain words

The product, its pages, mails, reports, guides and sales material never say that TrialBox or "the AI" or "the
system":

- finds, detects or picks out patients or disease (発見, 見つけ出す, 検出: "AIが適格患者を発見");
- predicts a patient's outcome, prognosis or eligibility (予測, 予後);
- gives a patient a risk, danger level or score (リスク, 危険度, スコア: "患者ごとのリスク");
- lists patients who are suspected of, or not yet diagnosed with, a disease (疑い患者, 未診断);
- diagnoses, supports diagnosis or judges (診断, 診断支援, 判定, "AIが判断"), or prevents missed patients (見逃し).

What it says instead: 「研究計画書の選択・除外基準に照らして、記録上の該当状況を一覧にします。参加の可否は治験責任医
師が判断します。」 and the intended-use statement of TB-IU-01 section 1.

The same words stay usable where they make no claim about a patient: バイアスのリスク (risk of bias); a named
clinical scale such as ECOG or eGFR, entered by a clinician or computed by its published formula for a criterion
(ECOG スコア); a laboratory's 検出限界; a study's enrolment forecast (登録予測), which is a count; a person's 判断; a
sentence saying what TrialBox does not do (「TrialBox は患者を発見しません」); and a protocol's or chart's own text,
which the product quotes as written (D-351).

## 4. How the check holds this

`FORBIDDEN` refuses 疑い患者 outright, beside 診断, 判定 and 見逃し, which it refused already. `CLAIMS_JA` lists the
words that are ordinary on their own (発見, 見つけ出, 予測, 予後, リスク, 危険度, 未診断, スコア, 検出, 判断); each is
refused when, in the same sentence, the product, the system, the AI or a model is its subject, or a patient word
(患者, 候補者, 対象者 ...) stands next to it; each has its allowed contexts as data, and a negation right after the
term ("予測しません") is not a claim. The check runs wherever the English check runs: the catalogue test, the page
walk over every role and language, the console templates, and every other caller of `check` and `check_page`.

## 5. Change history

| Version | Date | Change |
| --- | --- | --- |
| 0.1 | 2026-11-18 | First draft (card 10C-5): the case-database reasoning of review 11 section 3, the words never said, the check |
