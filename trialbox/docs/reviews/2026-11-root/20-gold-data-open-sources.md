# Root review 20: Japanese and Traditional Chinese gold data without paid clinician writers — open data and the literature (lane J, B-22, 2026-11-18)

**Reader:** the owner (a clinician) first, then the builders and whoever revises plan 10.

**The owner's ruling (2026-11-18).** Paid clinician writers for Japanese gold (review 17: about 125 hours,
¥1.5 to 2.5 million) are "difficult"; "extensive do open data search or academic journal". He accepted review 17's
release bound: at most 5 % of eligible patients wrongly excluded per language at release, proven on at least 124
eligible patients with at most two misses, with a 25 % coverage floor on note-based answers; targets must be
realistic. Plan 10 decisions 17 (criterion 1 as a bound) and 19 (how Japanese gold is made) wait on this
[R `docs/plan/47-plan-10-2026-11-18.md:138-139,656,658`].

**What this review did.** It goes under reviews 06, 07, 11, 15 and 17 and the lane G catalogue of 96 Chinese and
Japanese candidates (`docs/handover/lane-g-2026-11-16/public-data-zh-ja.md`, here "the catalogue") and does not
repeat them. It (1) lists what `eval/` already holds and what each set can prove; (2) re-opened the terms of every
source that matters for a company's evaluation and test suite, quoting the rule, and opened the ones the catalogue
did not; (3) read the literature on cheap gold with measured validity; (4) does the binomial arithmetic of what each
method can bound; (5) proposes a staged gold plan that fits the ruling, with clinician hours. Nothing was downloaded
beyond terms pages, dataset cards, one README and three short conference papers (all deleted; scratch 1.2 MB). No
patient data was read. The first site is not named.

**Marks.** **[M n]** measured here (section 13); **[R file:line]** read in the repository (paths from `trialbox/`,
master `6be0f8c0`); **[R nn]** read in root review nn; **[R cat]** read in the catalogue; **[S n]** a primary source
opened on 2026-11-18 (section 14); **[S2 n]** a search summary or secondary page, weaker; **[O]** opinion, with its
reason. "Not verified" where a source could not be opened. Nothing here is legal advice: licence readings are a
non-lawyer's reading of the text quoted, for the owner's regulatory reader to confirm.

---

## 0. One page for the owner

**The short answer.** Open data and the literature cannot replace clinicians, but they can cut the clinician time
for Japanese from about 125 hours to **about 23 hours** of our own (plus 5 for Traditional Chinese and about 12 hours
of the site's), because clinicians no
longer write charts: they **check** charts a model wrote, and only where checking changes the proof [O, section 6-7].

**What open data gives, today, for free** [S, R]:
- **Negation and suspicion in real Japanese text:** MedTxt (215 aligned case and radiology reports, CC BY 4.0) is
  already in the repository; it is the only open real-text Japanese set a company may use and test with.
- **Japanese synthetic patients with built-in truth:** JMED-Personas-100k (CC BY 4.0). Its own card says every field
  is filled and nothing is missing or ambiguous, and it was written by the same model family the box serves; so it
  tests the data path and recall, not real-chart reading.
- **Authoritative Japanese criterion texts under an open government licence (PDL 1.0, commercial use and
  translation allowed):** 348 指定難病 diagnostic criteria (MHLW), 29 最適使用推進ガイドライン (PMDA), and single
  jRCT records. These are the best criterion-level gold the ruling allows: the wording is the regulator's.
- **English physician labels** (TrialGPT, SIGIR, TREC, Chia) already in use; SIGIR's notes are CC BY-SA 4.0, so our
  Japanese and Chinese translations of them carry share-alike (the repository labels them "public domain": a fix).

**What open data cannot give** [S, O]: no public Japanese or Traditional Chinese set labels patients against trial
criteria; every real Japanese chart corpus I found is research-only, members-only, or on request (NTCIR MedNLP-2 and
MedNLPDoc "usable only for research purposes"; iCorpus research only; the full MedTxt-CR 3,148 reports on request with
no licence named). No real Taiwanese notes are public at all.

**The plan in four stages** (section 7):
1. **Now, no clinicians:** run the public sets (MedTxt negation and 疑い; JMED-Personas recall; English physician
   labels; criterion compile on official Japanese criteria texts).
2. **Criterion gold from official texts:** jRCT records that also have an English entry, 指定難病 and 最適使用 texts;
   the box compiles both languages; a clinician reads only where the two disagree (about 4 hours).
3. **Generated Japanese charts:** a model of a *different family* from the judge writes 150 charts for 12+ public
   protocols, seeded with clinician-written "hard phrases"; clinicians verify the planted facts (with the box's quotes
   shown, 2 minutes a chart) and adjudicate every exclusion of an eligible chart. About 17 hours. This reaches 124
   eligible patients and the 5 % bound **on generated charts**.
4. **The release proof at the first site:** a retrospective run on patients the site already enrolled in past studies
   (each was judged eligible by an investigator) plus review 17's shadow mode; counts only leave the hospital.

**What the release may then say** (section 7.6): "On 124+ Japanese charts generated for public criteria and checked by
clinicians, the box wrongly excluded at most 2 eligible patients (95 % upper bound 5 %)"; "on public Japanese reports
it reads x % of negated findings as present"; and, only after stage 4, "at the first site, of K patients the
investigators enrolled, the box would have excluded m". It **may not** say "at most 5 % of eligible patients at a
Japanese hospital are wrongly excluded" until stage 4 has 124 real eligible patients.

**The five changes that matter most.**
1. Adopt the four stages and the 28-hour budget (23 ja, 5 zh-TW) in place of 125 hours of writing (card 20-1;
   decision 1).
2. Generate the Japanese charts with a different model family and clinician-written hard phrases, and check **every**
   chart the box excludes, not a 10 % sample: a 10 % audit cannot protect a two-miss bound (section 6.2) (20-6 to 20-9).
3. Ask the first site for a **retrospective enrolment-log run** (patients enrolled in its past studies): the cheapest
   real-chart eligible gold there is (20-12; decision 4).
4. File three requests now: NAIST for the full MedTxt-CR, the jRCT help desk for collection of a few hundred records,
   the Tsukuba authors for their notes' licence (20-3).
5. Fix the licence labels in the repository: SIGIR-derived notes are CC BY-SA 4.0; MedTxt and MANBYO are missing from
   the register (20-2).

**What it costs.** About 28 clinician hours of ours (¥0.34 to 0.56 million at review 17's assumed ¥12,000 to ¥20,000
an hour, not verified;
or the two Japanese clinician readers the owner already ruled for wording); about 12 hours of the site's; chart
generation through the DEV gateway, under US$5 [O, section 7.5]. No fee was found for any source recommended.

---

## 1. What the repository already holds

| Set (path) | Language | Size | What is labelled | Licence as recorded | What it can prove | Mark |
| --- | --- | --- | --- | --- | --- | --- |
| `eval/criterion_ml` | en; ja, zh-TW, mixed by machine translation | 53 notes, 326 sentences each; 1,015 patient-criterion pairs, 103 trials | physician label (4-way) and evidence sentence ids | "public domain" (README, DATASETS.yaml) | criterion-level judging in four renderings; **not** clinician-checked translations | [R `eval/criterion_ml/README.md:8-33`; `eval/DATASETS.yaml:4-8`] |
| `eval/medtxt` | ja + clinician English | 215 aligned reports (148 CR + 135 RR in the zip) | finding certainty: present, negated, suspected, absent | CC BY 4.0 | negation and 疑い reading on real Japanese text | [R `eval/medtxt/README.md:1-9`; `tools/medtxt_eval.py:4,17`] |
| `eval/public_accuracy_key` (jmed) | ja (synthetic) | 300 patients x 2 criteria (DM, HT) | truth from the note (key v2) | CC BY 4.0 | data path, recall, family-history and hedge handling | [R `eval/public_accuracy_key/README.md`; `tools/public_accuracy/sets.py:992-1042`] |
| `eval/accuracy` | ja, zh-TW, en (templates) | 3,041 / 3,041 / 2,641 cases | gold exclusion per stratum (plain, long, negation, family, era, window, lab) | written for TrialBox | prompt and parser on planted strata | [R `eval/accuracy/MANIFEST.json`; `tools/accuracy_set.py:1-40`] |
| `eval/trec_ct`, `eval/open_cohorts` | en | TREC 2021/22/23 topics and qrels; SIGIR cohort | pair relevance 0/1/2 | NIST: no terms stated; SIGIR CC BY-SA 4.0 | patient-trial level, English, synthetic topics | [R `eval/DATASETS.yaml:64-68,139-143`] |
| `eval/chia` | en | 1,000 trials | criteria entities and relations | CC BY 4.0 | criterion compile | [R `eval/DATASETS.yaml:144-148`] |
| `tools/public_accuracy` sets `tfda`, `jrct` | zh-Hant + en; ja + en | 100 and 50 trials (compile only) | none (the other language is the check) | OGDL-TW 1.0; PDL 1.0 single records | criterion compile in zh-Hant and ja | [R `tools/public_accuracy/plan.py:275-276`; `sources.py:155-166,265-271`] |
| `eval/injection`, `eval/phi_synth`, synthetic hospital | ja, zh-TW, en | – | planted instructions, identifiers, templates | generated | plumbing, safety rules, scale; **no** accuracy on real notes | [R `eval/DATASETS.yaml:19-23,74-98`; R 07 §3.3] |

**Findings in the repository** [R, O]:
1. **SIGIR-derived notes are labelled public domain but are CC BY-SA 4.0.** `sources.py` and the licence register say
   the SIGIR notes are CC BY-SA 4.0 (CSIRO) [R `tools/public_accuracy/sources.py:112-118`;
   `docs/licences/register.csv:36`]; the CSIRO page confirms it [S 31]. `eval/criterion_ml` README and DATASETS.yaml
   call the notes and their ja/zh-TW translations "public domain" [R `eval/criterion_ml/README.md:27-29`;
   `eval/DATASETS.yaml:8`]. The translations are adaptations: they must carry CC BY-SA 4.0 and the CSIRO attribution.
   Share-alike binds the adapted notes, not the product [O].
2. **MedTxt is in `NOTICE` but not in `docs/licences/register.csv`**; MANBYO is in neither [R `NOTICE:254-259`;
   register grep, M 2].
3. **MANBYO's licence is not CC BY 4.0 as review 06 says.** Its page says only "feel free to use it" and points
   commercial users to JMED-DICT mini, "an open source (commercially available) medical dictionary" [S 1]; JMED-DICT
   mini's card is CC BY 4.0 [S 28]. Ship JMED-DICT mini; ask NAIST before shipping MANBYO (card 20-2).
4. **The medtxt count**: the download page says the test collection holds "100 reports as the training set only due to
   licensing issues" of MedTxt-CR [S 3]; the repository's zip held 148 [R `tools/medtxt_eval.py:4`]. Not resolved
   here (not verified which is current).
5. **The 1.0 frozen sets do not exist.** 07's V3b (frozen ja set) has no source; this review supplies one.

---

## 2. Japanese clinical and medical text: every source opened

Columns: **Eval** = may a company use it to evaluate its product; **Suite** = may it be redistributed inside the
product's test suite. Verdicts: **use now**, **apply** (for access or permission), **learn** (read, use for design,
do not test or ship with it), **no** (not usable).

### 2.1 Clinical text corpora

| Source (opened) | Size, language | Labelled | Licence or terms (quoted) | Eval / Suite | How to obtain | Verdict | Mark |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Real-MedNLP test collection (MedTxt-RR all, MedTxt-CR part) https://sociocom.naist.jp/download/real-mednlp-test-collection/ | 373 KB zip; RR 72 + 63; CR "100 reports as the training set only due to licensing issues"; ja + en | entities with certainty and time attributes (disease, anatomy, time, test, medication, value) | "CC BY 4.0" | yes / yes, with attribution | download | **use now** (in use) | [S 3] |
| MedTxt-CR full (3,148 OCR'd case reports; 224 annotated) | ja | as above | the corpus page states **no licence**; the full set "not clearly available"; entry form "Closed"; contact real-mednlp[at]is.naist.jp | not without permission | e-mail request | **apply** | [S 2; R cat row 61] |
| NTCIR-10 MedNLP (50 dummy summaries written by doctors) | ja | disease, time, factuality | permission page 404 today; the NTCIR rule: "usable only for the research purpose use" | no (research only) | NII form + memorandum by post | **learn** at most | [S 6; R cat row 68] |
| NTCIR-11 MedNLP-2 (`mednlp2sub.xml`, 82 documents, 172 KB) | ja | "disease names, date and time expressions, and factuality" | "It is usable only for research purposes"; data "copyrighted and has commercial value" | no | application form + memorandum | **learn** | [S 4] |
| NTCIR-12 MedNLPDoc (200 train + 78 test documents) | ja | same, plus ICD labels | "usable only for research purposes" | no | as above | **learn** | [S 5] |
| NTCIR-17 MedNLP-SC RR (27 cases x 9 radiologists = 243 reports) | ja | T, N, M, cStage | the task page states no licence; the 100-tag RRTNM subset in JMED-LLM is "CC-BY-4.0" | subset: yes / yes | JMED-LLM | **use now** (RRTNM 100 tags) | [S 26; S 7] |
| JMED-LLM tasks (MRNER-disease 50 CR + 50 RR; CRADE 100; RRTNM 100; SMDIS 100) | ja | positive-certainty entities; ADE likelihood; TNM; symptom presence | each "CC-BY-4.0"; NRNER (nursing records) and JCSTS "CC-BY-NC-SA-4.0" | CC BY ones yes / yes; NC ones no | GitHub | **use now** (CC BY subsets); **no** for NRNER, JCSTS | [S 7] |
| Tsukuba pseudo progress notes (9,756 crowd + 83 rated + 19 doctor-written SOAP notes) | ja | none (style only; 83 rated "authentic quality") | record metadata `cc-by-4.0`; the description says "CC BY-NC 4.0" (both records) | not until resolved | Zenodo | **apply** (licence clarification) | [S 27] |
| iCorpus (179 J-STAGE case reports, 102 rare diseases) | ja | entities | "研究目的のためにのみ" | no | permission | **learn** | [R cat row 65] |
| CT-RATE-JPN (22,778 machine-translated chest CT reports; 150 revised by radiologists) | ja (MT) | report text | "cc-by-nc-sa-4.0" | no | HF | **learn** | [S 28] |
| PMC-Patients-JA-DDx (about 19.8k + 19.8k MT vignettes) | ja (MT) | differential diagnosis | "cc-by-nc-sa-4.0", research use only | no | HF | **learn** | [S 28] |
| Japanese medical records research at a hospital group (NHO NCDA) | ja, real | – | on-site, per-study anonymised subsets, ethics review | no | not for a company | **no** | [S2 search; S 16] |
| A 2016 to 2017 MHLW-funded project's "高品質な個人情報を含まない模擬のデータセット" of 入院カルテ and 退院サマリ, written with practising physicians | ja | not stated | "研究成果として公表することにしており" (planned publication); no release found | not verified | not found | **learn** (ask the authors, low priority) | [S 16] |
| ANLP 2026 C5-12: case reports, discharge summaries and charts generated from PubMed case reports by a hosted model, used to train a small Japanese model for lung-cancer record structuring | ja (generated) | lung-cancer items | paper CC BY 4.0; data release not stated | – | – | **learn** (method) | [S 49]; Japanese text did not render |
| ANLP 2026 B9-6: MIMIC-IV-Note translated into Japanese with planted pseudo identifiers | ja (MT) | identifiers | MIMIC terms bar redistribution (catalogue row 94) | no | – | **no** | [S 49; R cat] |
| Japanese discharge summaries or nursing records from a hospital, by ethics review | ja, real | – | only through a hospital's own ethics committee under 生命・医学系指針; no public route found | only at the site | the first site's ethics committee | **apply** (site, stage 4) | [R 11 §2.1; O] |

### 2.2 Dictionaries and synthetic patients

| Source | Size | What | Terms (quoted) | Eval / Suite | Verdict | Mark |
| --- | --- | --- | --- | --- | --- | --- |
| MANBYO 万病辞書 (MANBYO_202106) | 20.4 MB zip; about 380k expressions | disease expressions to ICD-10 | "feel free to use it"; for commercial use "consider using JMED-DICT mini as an open source (commercially available) medical dictionary" | eval yes; ship: ask | **apply** before shipping; use JMED-DICT mini meanwhile | [S 1] |
| JMED-DICT mini (v1.1.2) | – | links to the minimal licence-free set | `license_name: cc-by-4.0`; "再配布や商用利用する際は…権利関係を確認" for linked resources | yes / yes | **use now** | [S 28] |
| JMED-Personas-100k | 100,000 patients, 61 structured + 10 narrative fields | truth in structured fields (主病名, ICD-10, 既往歴, 家族歴, 血液検査, 処方薬) | "cc-by-4.0"; generated by "gpt-oss-120b"; limits: "全項目に値を設定…未実施，未確認，欠損や曖昧な記載を表現していません"; "臨床的妥当性を十分に検証できていません"; ICD-10 inconsistencies listed | yes / yes (attribution) | **use now**, as recall and data-path gold only | [S 17] |
| An individual's "dummy karte" upload on the hub (2026-11-15) | under 1k records | none | no licence | no | **no** | [S 28] |

**Finding on JMED-Personas** [S 17, R 17, O]: it was generated by gpt-oss-120b, the strongest single engine in
TrialBox's Japanese runs and the base family of its guard [R 17 §4.2]. A judge reading text its own family wrote is a
known source of optimism (self-preference); and with every field filled the set has almost no "unknown" cells, so its
decided share overstates real charts. Keep it for recall and plumbing; never quote it as reading accuracy (the register
already says so [R `docs/licences/register.csv:43`]).

### 2.3 Benchmarks and licensing-exam sets

| Source | Size | What | Terms | Verdict | Mark |
| --- | --- | --- | --- | --- | --- |
| JMedBench (36 subsets) | igakuqa 11.8k; crade, rrtnm, mrner 100 each; many MT sets | QA, NER, classification, MT | per subset: CC BY 4.0 (crade, rrtnm, mrner, smdis, ejmmt), CC BY-NC-SA (jcsts, nrner), MIT (MT sets), "Unknown" (bc2gm_jp, jnlpba_jp, ncbi_disease_jp), igakuqa not stated; "please conduct comprehensive human evaluation before deployment" | **learn**; the CC BY clinical subsets are the JMED-LLM ones above | [S 8] |
| IgakuQA | exams 2018 to 2022 | licensing-exam QA | README states no licence; questions "collected from the MHLW website" | **learn** | [S 9] |
| JMedQA (3,581 items, 2018 to 2026), KokushiMD-10 (MIT), igakuqa curated subset (Apache-2.0, 66 items) | – | exam QA | "other", MIT, Apache-2.0 on cards; underlying exam text on the MHLW site, whose content is under PDL 1.0 unless marked otherwise | **learn**: exam vignettes test knowledge, not chart reading or eligibility | [S 28; S 18] |
| JMed48k, MMedBench, EMPEC | – | QA | CC BY-NC | **no** | [R cat] |

[O] None of these measures what the release bound needs (a patient wrongly excluded on chart text). Licensing-exam
scores tell which engine knows Japanese medicine; review 17 already uses one such score [R 17 §4.2].

### 2.4 Public structured data and official texts

| Source | What it is | Terms (quoted) | Use for gold | Verdict | Mark |
| --- | --- | --- | --- | --- | --- |
| NDB オープンデータ (12th edition, FY2025 claims) | aggregated counts only | site terms (PDL 1.0 for MHLW content) | prevalence priors for the synthetic hospital; no patients | **learn** | [S 21; S 18] |
| MID-NET | real EHR and claims, on site at PMDA | "利活用に係る契約の締結及び利用料の納付後"; expert-panel review | costs money; not for one product's evaluation | **no** | [S2 22] |
| JADER (2004-04 to 2026-03 reports) | line list and CSV per ICH E2B | free (第7条); 第5条(8) forbids letting downstream users use a service built on it without presenting the terms; publication requires prior notice to PMDA | structured case lines; free-text narrative not confirmed in the CSV; not chart gold | **learn** | [S 20; S2 20] |
| National cancer registry public tables | aggregated statistics | not opened | priors only | **learn**; not verified | – |
| 添付文書 (package inserts) via PMDA | the label text per product | PMDA content under PDL 1.0 [S 19]; inserts are prepared by manufacturers, whose copyright is not addressed on the page; "自動的に巡回ダウンロードする類のアプリケーションについても一切認めておりません" | contraindication wording for criteria (e.g. 禁忌); fetch one by one | **use now** for single texts, attribution and 加工 note; bulk **no** | [S 19] |
| 審査報告書 (PMDA review reports) | Japanese summaries of pivotal trials incl. main criteria | PDL 1.0 (PMDA site policy) | criteria wording in Japanese for approved drugs | **use now** (single reports) | [S 19]; per-report check not done |
| Minds / society clinical guidelines | guideline text | copyright with each society or publisher; "利用者の責任において…著作権者から利用の許諾を得てください" | none without permission | **learn** | [S2 25] |

---

## 3. Trial eligibility text in Japanese

| Source | Terms, verbatim where it matters | Eval / Suite | What it gives as gold | Verdict | Mark |
| --- | --- | --- | --- | --- | --- |
| **jRCT** (臨床研究等提出・公開システム) | content "公共データ利用規約（第1.0版）（PDL1.0）に準拠した利用条件の下で、利用することができます"; excluded: names and contacts of committee members and researchers ("当サイトに掲載されている臨床研究…に関する問い合わせ等に限った利用"); "包括的・網羅的なデータ利用・収集等を行う場合は、必ずヘルプデスクまで利用許可の申請をお願いします"; "自動的に巡回して情報を収集する類のアプリケーション等の使用はご遠慮ください" | single records: yes / yes, with 出典 and 加工 statements; a collection of hundreds: after the help desk's permission | authoritative 選択基準 / 除外基準; many records carry an English version or an NCT number | **use now** (single records, as `tools/public_accuracy` does), **apply** for a collection | [S 10] |
| **PDL 1.0** itself | "商用利用も可能です"; "翻訳・変形等の翻案等、自由に利用できます"; attribution "出典：…（当該ページのURL）、PDL1.0"; edited content must say so ("…を加工して作成") and must not look official; compatible with CC BY 4.0 | – | – | – | [S 11] |
| **UMIN-CTR** CSV | "you cannot redistribute UMIN-CTR dataset"; "You shall not use information extracted from the UMIN-CTR database for marketing, promotional or commercial purposes"; FAQ: software that processes the data may be sold, but "you cannot build any commercial web service that displays information extracted from UMIN-CTR dataset"; no permission process described | eval: arguably internal processing; suite: **no** | registry-only studies (observational) | **learn**; for a suite, written permission (no route found) | [S 12] |
| **指定難病 概要・診断基準等** (MHLW) | 348 diseases "令和８年４月時点", one PDF each, plus 臨床調査個人票 PDFs; MHLW content under PDL 1.0 | yes / yes (attribution, 加工 note) | diagnostic criteria with k-of-n items and severity: structured, authoritative criteria | **use now** | [S 23; S 18] |
| **最適使用推進ガイドライン** (PMDA) | 29 ingredients listed (e.g. レカネマブ, ドナネマブ, デュピルマブ, ニボルマブ, ペムブロリズマブ, セマグルチド, チルゼパチド), PDF each; page footer "All Rights Reserved" while the site policy puts content under PDL 1.0 | yes / yes under PDL 1.0 (the footer is the generic one) [O] | patient and facility requirements: reimbursement-style criteria | **use now** | [S 24; S 19] |
| Japanese translations of ClinicalTrials.gov entries | no official translation found; the MHLW portal searches trials run in Japan | – | – | **no source**; jRCT's bilingual records serve instead | [S 51] |
| 審査報告書 inclusion criteria | as section 2.4 | yes | the pivotal trials' main criteria in regulator Japanese | **use now** (selected) | [S 19] |

**Copyright Act, Article 30-4** [S 15]: a work may be used "情報解析（多数の著作物その他の大量の情報から…抽出し、比較、
分類その他の解析を行うこと）の用に供する場合" and for "技術の開発又は実用化のための試験の用に供する場合", "ただし…著作権者の利益を
不当に害することとなる場合は、この限りでない". [O, not legal advice] This may let a company *test* on copyrighted
Japanese text (for example J-STAGE case reports with no CC licence) inside its own premises; it does **not** let the
text be redistributed in a test suite or bundle, and it does not override a contract (NTCIR's memorandum, a DUA). A
clinician reading a case report to label it is human perception of the work, which the article's wording
("享受…を目的としない") may not cover. The owner's regulatory reader should rule before any such use (decision 7).

**J-STAGE** [S 13, S2 14]: article reuse depends on each journal's own licence; about 250 J-STAGE journals carried a
CC licence in August 2023 (a J-STAGE seminar report, search summary). The J-STAGE WebAPI terms forbid caching
API data for 24 hours or more and require prior application for commercial use. The J-STAGE article host returned 502
to this machine before (catalogue §5) and its terms-of-use page 404 today: per-journal licences are not verified.

---

## 4. Patient-trial matching and cohort sets in any language: reuse and translation

| Set | Data | Terms (opened) | Machine translation into Japanese + spot check permitted? | In a product's test suite? | Verdict | Mark |
| --- | --- | --- | --- | --- | --- | --- |
| SIGIR 2016 (CSIRO) | 60 topics (case reports), about 4,000 judgements | "Creative Commons Attribution-ShareAlike 4.0 International Licence"; "All Rights (including copyright) CSIRO, U.S. NIST, U.S. NIH 2016" | **yes** (adaptation allowed; the translation carries CC BY-SA 4.0 and attribution) | yes, the adapted file under CC BY-SA | **use now**; relabel (finding 1) | [S 31] |
| TrialGPT criterion annotations (NCBI) | 1,015 physician criterion labels | `license_name: public-domain` | yes (labels); the notes inside are SIGIR's (CC BY-SA) | yes | **use now** | [S 33] |
| TREC Clinical Trials 2021 to 2023 (NIST) | 75 + 50 synthetic topics; 40 questionnaires | the 2021 page states **no licence or terms**, only the files and "Judgment of 0 is non-relevant, 1 is excluded, and 2 is eligible" | not stated; internal translation for evaluation low-risk [O]; keep in `.cache` as now | **no** (no grant) | **use now** internally (as now) | [S 30; R `tools/public_accuracy/sources.py:56`] |
| n2c2 2018 track 1 (288 real diabetic patients, 13 criteria) | real notes | DBMI portal: register and sign a DUA; separate academic and corporate DUA previews exist; older DUA: use "solely for the Specific Purpose"; portal and DUA pages refused this machine (403/503) | not without the provider's written consent [O]; terms not verified | **no** | **apply** (corporate DUA) only for English development; low priority | [S2 29] |
| Chia | 1,000 trials' criteria, annotated | "CC BY 4.0" | yes | yes | **use now** | [S 32] |
| PMC-Patients (167k case-report patients) | patient summaries | card "cc-by-nc-sa-4.0" | no (NC) | no | **learn** | [S2 34] |
| TrialGPT's own released patient-trial outputs (GPT-4 answers) | model output | as TrialGPT | – | – | **learn** (reference only; already recorded in `eval/suites/judge_public`) | [R `eval/DATASETS.yaml:49-53`] |

**What the literature says about translated clinical benchmarks** [S, S2]:

| Study | What was measured | Finding | Mark |
| --- | --- | --- | --- |
| Seinen et al., JAMIA 2024 | three annotated English clinical corpora machine-translated to Dutch with annotations embedded, two tools evaluated in both languages | "the concept extraction tools performed similarly in both English and Dutch"; annotation-preservation differences "did not affect extraction accuracy" | [S 35] |
| Physician detection of clinical harm in MT (arXiv 2310.16924) | physicians judging English to Chinese MT | "backtranslation helps physicians detect more clinically harmful errors that QE alone often misses" (no figure in the abstract) | [S 36] |
| MT error taxonomy in healthcare (EMNLP 2025) | error types and clinical risk | terminology and omission errors most often carry high or life-threatening risk | [S2 37] |
| JMedBench (2024) | MT of English biomedical sets into Japanese with manual correction | three failure types (word-sense, several valid terms, grammar); authors judged failures few | [S2 38] |

**Reading** [O]: a careful translation preserves *entity-level* labels well; what it cannot carry is the *Japanese way of
writing a chart* (保険病名, 疑い 病名 suffixes, (-), SOAP mixed script, 和暦). A translated SIGIR note is English
medicine in Japanese words. So translated sets prove that the box reads Japanese **language**; they do not prove it
reads Japanese **charts**. Use them for criterion-level parity (en vs ja vs zh-TW on the same physician labels), check
them by back-translation (section 6), and never count them toward the 124 eligible patients of the release bound.

---

## 5. Traditional Chinese (Taiwan)

| Source | Size | Terms | Verdict | Mark |
| --- | --- | --- | --- | --- |
| TFDA 台灣藥品臨床試驗現況資料集 | 5,533 trials with criteria | OGDL-TW 1.0, any purpose | **use now** (in the repository): criterion gold in zh-Hant by bilingual agreement | [R `tools/public_accuracy/sources.py:155-166`; R cat row 1] |
| NHI 藥品給付規定 (e.g. 第9節 抗癌瘤藥物, amendments effective 115年8月1日) | per-section PDFs and amendment tables | NHI site terms not opened; Taiwan's open-government licence likely applies (not verified) | **use now** for single sections after the terms are read (card 20-4): reimbursement criteria in authoritative zh-Hant | [S2 50] |
| 台灣藥品臨床試驗資訊網 (per-trial pages since 2025-01-01) | – | not read | **learn** until read | [R cat row 3] |
| OpenTWBench tw-exam-bench (medicine 13,963 items, 2,140 vignettes) | – | Apache-2.0 on the card | **use now** for language checks (in the repository) | [R `tools/public_accuracy/sources.py:231-242`] |
| medical-bench-tw (exam items and NHI/TFDA/CDC documents, about 170k) | – | "other", gated (auto) | **learn** until the terms are read | [S 28] |
| 衛生福利部 台灣e院 Q&A (an individual's upload) | 100k to 1M | card "apache-2.0", gated (manual); upstream MOHW terms not verified | **learn** | [S 28] |
| Real Taiwanese notes (code-mixed discharge summaries; NTUH; Cheng Hsin) | – | not public | **no**; the owner's carve is the only source (R 07) | [R cat §2] |
| Hugging Face searches "zh-tw medical", "taiwan medical", "traditional chinese medical", "emr taiwan" | – | 0 hits for clinical notes | – | [M 3] |

**Reading** [O, R cat §2]: for zh-TW the owner's de-identified carve, rewritten by his own clinicians (07's plan), stays
the only real-note source. Open data adds criterion gold (TFDA, NHI rules) and nothing at patient level. Taiwanese
charts are mostly English with Chinese history sections [R cat §2], so the generated zh-TW charts of section 7 should be
written that way, and the English physician-labelled sets are closer proxies than any Mainland corpus.

---

## 6. Cheap gold in the literature: measured validity, what each can prove, the clinician minutes it needs

### 6.1 Methods

| Method | Measured validity (source) | What it can prove for the release bound | What it cannot | Smallest honest clinician time [O] |
| --- | --- | --- | --- | --- |
| **Model-generated notes, clinician-validated sample** | SynthMedic: 900 synthetic discharge summaries; "credible and factually accurate when provided with the medical reference context" by expert rubric [S 39]. Gan et al.: models trained only on 15,000 synthetic epilepsy letters reached micro-F1 0.79 to 0.85 on clinician-checked **real** letters [S 40]. JMED-Personas: plausibility "not sufficiently validated" [S 17] | a bound on the box **for the generator's distribution**, if the gold of each chart is right | anything about real charts: the gap between generated and real text is not measurable inside the generated set; on real Japanese charts an open 70B model's precision was 0.07 against far higher on public sets [R 17 §1.3] | verify the planted facts of every chart the bound depends on (section 6.2), not a percentage |
| **Clinicians checking text instead of writing it** | in 90 synthetic discharge summaries with one planted clinically relevant error each, six clinicians found **47.8 %** of the errors on average; a frontier model found 97.8 % [S 41]. Experts given full pre-annotation "exhibit less agency" and accept more wrong suggestions [S 48] | that a planted fact is present and unambiguous, when the clinician is shown the sentence | a free "is this chart right?" read: half the errors pass | 2 minutes a chart **with the planted sentence and the box's quote shown**; never an unguided read |
| **Back-translation** | helps physicians find harmful MT errors that quality estimation misses [S 36]; annotation-preserving MT kept tool scores equal across languages [S 35] | that a translated sentence still means the labelled thing | Japanese chart style | read only the sentences whose back-translation differs from the source (about 1 minute each) |
| **Weak supervision from structured data** (a code as the label of a note question) | Snorkel: within 3.6 % of hand-labelled training performance [S 45] (training, not testing). In a Japanese acute hospital, cancer diagnosis codes had PPV **67 to 81 %** against chart review [S 42]; a claims algorithm for UC had PPV 90.6 % [S 43] | training signal; a prior for sampling | **a test label**: one code in five is wrong, which alone exceeds a 5 % bound | none for testing: do not use codes as gold |
| **Silver standard from agreement of different systems** | CALBC: 1.1 million harmonised annotations on 100,000 abstracts; systems trained on the silver standard scored best against it [S 44] | a pool to sample from; agreement cells need fewer reads | where the systems share a blind spot (same family, same prompt), agreement is not truth; scoring a system on a silver standard it helped build is circular | read **all** disagreements; sample agreements only where the bound is exposed |
| **Active sampling** (spend clinician minutes on uncertain cells) | Active Testing: unbiased risk estimates with fewer labels when selection is corrected [S 46]; LLM pre-annotation reduced human annotation time (58 % in one study, search summary) [S 47; S2 47] | the same bound with fewer reads, if the selection is recorded and weighted | an unweighted "hard cases only" set: it biases the rate | record the sampling probabilities; the scorer weights them |
| **Case reports as patients** | SIGIR and TREC are case-report patients (R 17 §1.1); ANLP 2026 C5-12 generated charts from case reports [S 49] | criterion reading on real clinical prose | longitudinal charts, coded data, 保険病名 | as the source set |
| **Crowd-written notes rated by doctors** | Tsukuba: 9,756 crowd notes, 83 rated "authentic quality", 19 by doctors [S 27] | Japanese charting style at low cost | clinical truth | none for gold |
| **The site's own records in shadow mode** (R 17 §3.3) and **past enrolment logs** (section 7.4) | Ni et al. used historical enrolment as gold [R 17 S 16] | the release proof on real charts | – | the coordinator's elusion reads; adjudication of each miss |

### 6.2 The arithmetic: what an audit bounds [M 1]

Exact one-sided 95 % Clopper-Pearson bounds.

**A clinician audit of n generated charts finding k label errors bounds the generator's label error rate at:**

| Audited n | 0 errors | 1 error | 2 errors |
| ---: | ---: | ---: | ---: |
| 13 (10 % of 130) | 20.6 % | 31.6 % | 41.0 % |
| 30 | 9.5 % | 14.9 % | 19.5 % |
| 60 | 4.9 % | 7.7 % | 10.1 % |
| 130 (10 % of 1,300) | 2.3 % | 3.6 % | 4.8 % |
| 260 | 1.1 % | 1.8 % | 2.4 % |

**Why a 10 % audit cannot protect the release bound.** Label errors matter in one direction only [O]:
- A chart labelled *eligible* that is really ineligible makes the box look worse (a correct exclusion counted as a
  miss): conservative, harmless to the claim.
- A chart labelled *ineligible* that is really eligible (the planted exclusion is missing, negated or ambiguous) is a
  truly eligible patient left out of the denominator; if the box excludes it, a real miss is never counted.

If h such hidden eligible patients exist and the box excludes them all, a run that shows 2 misses in 124 really has
2 + h in 124 + h [M 1]:

| Hidden eligible h | 0 | 1 | 2 | 3 | 5 | 9 |
| --- | --- | --- | --- | --- | --- | --- |
| Upper bound of the true rate | 4.99 % | 6.09 % | 7.12 % | 8.10 % | 9.95 % | 13.32 % |

A 10 % audit of 130 ineligible charts (13 read) bounds their error at 20.6 % even with no error found, so up to about
26 hidden eligible patients would remain possible (2 + 26 misses in 150: upper bound 24.7 % [M 1]): the claim
would be empty. **One hidden eligible patient breaks a
5 % claim.** So the honest design checks **every** ineligible chart the box excludes, and every exclusion of an
eligible chart, and samples only where an error is conservative. With the planted sentence and the box's quote on
screen that is about 2 minutes a chart [O; S 41 says why an unguided read is not enough].

**Chance the box passes** at n = 124, two misses allowed [M 1]: 0.97 if its true rate is 0.5 %, 0.87 at 1 %, 0.80
at 1.25 % (a quarter of the bound), 0.55 at 2 %, 0.40 at 2.5 %. Review 17's reading stands: plan for two misses.

**Recall at the site** [M 1]: known positives with 0 misses give a 95 % lower bound on recall of 90.2 % at 29 and
95.0 % at 59; with 2 misses, 95.0 % at 124 (the same 124 as the bound).

---

## 7. The gold plan that fits the ruling

### 7.1 Which source proves which part

| Part of the proof | Source | Language | Gold type | Size | Clinician hours |
| --- | --- | --- | --- | --- | ---: |
| Negation, 疑い, family history in real Japanese text | MedTxt (CC BY 4.0), JMED-LLM MRNER, RRTNM | ja | clinician annotation (published) | 1,677 items [R 11 M 3] | 1 (adjudicate the strict-slice conflicts, 60 items) |
| Criterion compile, ja | 50 jRCT records with an English version; 20 指定難病; 10 最適使用 | ja + en | the regulator's own wording; the bilingual compile as cross-check | about 80 protocols, about 1,200 lines [O] | 4 (disagreements only, about 150 lines x 1.5 min) |
| Criterion compile, zh-Hant | 100 TFDA trials with an English record; NHI rule sections | zh-Hant + en | same | about 1,300 lines [O] | 4 (a zh-TW clinician, same rule) |
| Criterion-level answers, cross-language parity | criterion_ml (1,015 physician labels) in en, ja, zh-TW, mixed | all | physician labels, translated notes | 1,015 pairs | 2 (back-translation diffs, 1 h per language) |
| Recall and data path | JMED-Personas (300 x 2, key v2) | ja | structured truth | 600 pairs | 0 |
| **Patient-level eligibility, Japanese, generated** | 150 generated charts x 2 public protocols | ja | planted truth, verified | ≥ 124 eligible, ≥ 124 ineligible or open | about 17 (section 7.5) |
| **Patient-level eligibility, real charts (release proof)** | the first site: past enrolment logs + shadow mode | ja | investigator's enrolment decision; coordinator's list | target ≥ 124 eligible | site: about 12 |
| zh-TW patient level | the owner's carve rewritten by his clinicians (R 07 B7-9) | zh-TW | clinician double label | 07's target | as 07 (not this plan) |

### 7.2 What remains unprovable without real charts [O]

- How often real Japanese charts state a criterion fact at all (the decided share on real charts): generated charts
  are written to state it. The 25 % coverage floor can be checked on generated charts only as a lower sanity line.
- Real error kinds: copy-forward text, contradictory 病名 lists, scanned documents, older records outside the chart,
  vendor-specific templates (review 12).
- Prevalence and the eligible share among candidates, which sets the coordinator's workload.
- Specificity on real charts (how many false candidates the coordinator must read).

### 7.3 The staged plan (ordered by what waits for what)

| Stage | What | Waits for | Proves | Release text it allows |
| --- | --- | --- | --- | --- |
| G0 | Relabel licences (SIGIR CC BY-SA; MedTxt, JMED-DICT mini, MANBYO rows); add RRTNM and MRNER CC BY subsets; file the three requests (7.4) | – | clean provenance | – |
| G1 | Public runs: MedTxt pair and box judge (17-3), JMED-Personas, criterion_ml parity, compile on jRCT / 指定難病 / 最適使用 / TFDA | G0 | negation and 疑い error with bounds; compile agreement | "on public Japanese reports …" |
| G2 | Criterion gold: bilingual compile disagreements read by a clinician; frozen criterion key per protocol | G1 | criterion-level answers for 80+ ja protocols | "on N official Japanese criteria texts, the compiled form agreed with a clinician on x %" |
| G3 | Generated charts (7.5), frozen and hashed before any box run (07's manifest) | G2 (protocols), clinician hard phrases | patient-level bound on generated charts | "on 124+ generated Japanese charts …" |
| G4 | First site: retrospective enrolment-log run, then shadow mode (17-4) | site agreement and ethics (17-15); G3 passed | release proof on real charts | "at the first site …" |

### 7.4 Applications to file

| To whom | What to ask | What they ask of us | Time to answer | Mark |
| --- | --- | --- | --- | --- |
| NAIST Social Computing Lab, real-mednlp[at]is.naist.jp | the full MedTxt-CR (3,148) and the 224-report annotated subset; whether a company may use them for internal evaluation, without redistribution; whether MANBYO may ship in a product | not stated on the page | not stated | [S 2, S 1] |
| jRCT help desk (the "お問い合わせ" link on jrct.mhlw.go.jp) | permission for "包括的" collection of up to 300 records, fetched slowly, kept as offline test fixtures with PDL 1.0 attribution and a 加工 statement | an application ("利用許可の申請"); form not published | not stated | [S 10] |
| Tsukuba authors (Zenodo records 4064153, 3752281) | which licence holds: CC BY 4.0 (metadata) or CC BY-NC 4.0 (description) | – | – | [S 27] |
| The first site's ethics committee (with 17-15) | a retrospective, counts-only run of the box on charts of patients enrolled in the site's past studies, as of each screening date; and the shadow mode | protocol, information disclosure (opt-out) under 生命・医学系指針 [R 11 §2.1; not verified for this design] | the committee's cycle | [O] |
| Optional: n2c2 corporate DUA (English development) | access | DUA signature | not verified | [S2 29] |
| Not filed (recommended) | NTCIR MedNLP-2 / MedNLPDoc (research only; small), iCorpus (research only), UMIN-CTR (no commercial use), CBLUE/Tianchi | – | – | [S 4, S 5, S 12; R cat] |

### 7.5 The generated Japanese chart set (stage G3)

| Step | Design [O] | Clinician minutes |
| --- | --- | ---: |
| Protocols | 12 or more: 6 jRCT records the site would run (the site's list, R 17 §11 item 2), 3 指定難病, 3 最適使用推進ガイドライン; criteria frozen from G2 | 0 |
| Hard phrases | a Japanese clinician writes 200 one-line snippets of the 11 §5 features: 疑い 病名, 否定できない vs 否定的, (-)/(+), 家族歴, 保険病名 with 中止, 和暦 dates, 読影 所見 vs 診断, abbreviations (Ca, RA, Ent) | 200 x 1 = 200 |
| Generation | a model of **another family** than the judge and verifier (the judge is Gemma, the verifier Qwen, the guard gpt-oss [R 17]); seeded with structured truth, 2 to 6 notes per chart (外来記録, 退院時要約, 読影, 病理, 紹介状), the hard phrases inserted, some facts left unstated on purpose (gold "unknown") | 0 |
| Arms | 150 charts; each chart written eligible for one protocol and ineligible or open for another: ≥ 124 eligible pairs survive verification (17 % margin) | 0 |
| Realism | a clinician rates 30 charts "would a Japanese doctor write this", 1 to 5; a chart type under 3 is regenerated | 30 x 6 = 180 |
| Gold check, ineligible arm | every chart: the planted exclusion sentence shown; "present and unambiguous?" | 150 x 2 = 300 |
| Gold check, eligible arm | 30-chart sample (error here is conservative; reported, not gating) | 30 x 6 = 180 |
| Freeze | manifest with hashes before any box run (07 B7-6) | 0 |
| Run and adjudication | every box exclusion of an eligible chart (a candidate miss) adjudicated by two clinicians with the quote | about 10 x 2 x 5 = 100 |
| Agreement | second clinician on 30 gold checks; Cohen's kappa reported | 30 x 2 = 60 |
| **Total** | | **1,020 min = 17 h** |

Generation cost [O]: 150 charts x about 6,000 output tokens ≈ 0.9 million tokens through the DEV gateway with the
integrator's key: under US$5 at hosted open-model prices (prices not checked today; inside the US$500 cap).

### 7.6 Sizes against the 124-eligible requirement, and total clinician hours

| Set | Eligible patients for the bound | Counts toward the release bound? |
| --- | ---: | --- |
| criterion_ml (SIGIR) | 46 eligible pairs (P1b gold) [R `eval/public_accuracy_key/README.md`] | no (development, English source, translated) |
| JMED-Personas | 300 own-condition patients, 2 criteria | no (synthetic, same family as the guard) |
| Generated charts (G3) | ≥ 124 | **yes, for the generated-chart claim** |
| Enrolment logs (G4) | the site's count; 124 needed for 5 % with 2 misses, 150 with 2 gives 4.1 % [M 1] | **yes, for the real-chart claim** |
| Shadow mode (G4) | 30 to 120 known positives in 8 to 12 weeks [R 17 §3.3] | yes, pooled with the enrolment logs if the same box version |

| Who | Work | Hours |
| --- | --- | ---: |
| Japanese clinician(s), ours | G1 strict-slice conflicts 1; G2 criteria 4; criterion_ml back-translation 1; G3 17 | **23** |
| zh-TW clinician, ours | TFDA / NHI criteria disagreements 4; criterion_ml back-translation 1 | **5** (the carve's labelling is 07's, not counted) |
| The site | enrolment-log misses adjudicated (about 10 x 15 min) 2.5; shadow elusion reads 3.3 a month for 3 months [R 17 §3.3] | **about 12** |
| **Total** | | **about 28 ours + 12 site, against 125** |

**What the release may claim** under this plan [O]:
- "On public Japanese case and radiology reports (MedTxt), the box treats x of n stated-absent findings as present
  (95 % upper bound y %)."
- "On 80 official Japanese criteria texts, the compiled criteria agreed with a clinician on x % of lines."
- "On a frozen set of 124 or more Japanese charts **generated** for public criteria, each planted fact checked by a
  clinician, the box wrongly excluded at most 2 eligible patients (one-sided 95 % upper bound 5 %), deciding z % of
  note cells."
- After G4: "At the first site, of E patients its investigators enrolled in past studies, the box would have excluded
  m (upper bound u %); in shadow mode it kept all but k of the coordinator's K candidates."

**What it may not claim**: a bound on real Japanese charts before G4 reaches 124 eligible real patients; any zh-TW
patient-level figure from open data; that generated-chart accuracy predicts real-chart accuracy; specificity or
workload on real charts before shadow mode; any figure on JMED-Personas or translated notes as "accuracy".

**A known weakness of the enrolment-log gold** [O]: enrolled patients are the easy eligible ones (well documented at
screening); the box missing none of them does not mean it misses no harder eligible patient. Report it as its own
line; the shadow mode's coordinator-found candidates and elusion reads cover the harder ones.

### 7.7 Traditional Chinese under the same ruling

| Stage | zh-TW content | Gold | Clinician hours [O] | Claim it allows |
| --- | --- | --- | ---: | --- |
| G0 to G1 | TFDA criteria (OGDL-TW) compiled in zh-Hant and English; criterion_ml zh-TW and mixed renderings; OpenTWBench vignettes for language | bilingual agreement; physician labels (translated) | 0 | "the compiled zh-Hant criteria agree with the English record on x %" |
| G2 | 100 TFDA trials and 3 to 5 NHI 給付規定 sections as criterion gold | a zh-TW clinician reads the disagreements | 4 | criterion level, zh-Hant |
| G3 (option) | generated charts written the Taiwanese way: English body, Chinese 主訴 / 家族史 / 社會史, 民國 dates, NHI drug names [R cat §2]; same design as 7.5 | planted truth, checked with quotes | about 17 (a zh-TW clinician) | patient level on generated zh-TW charts |
| Release proof | the owner's carve rewritten and double-labelled by his clinicians (07's B7-9); a Taiwanese site's shadow mode later | clinician labels on real-derived charts | 07's estimate (40 to 60 h for 300 pairs) | patient level on real-derived zh-TW charts |

[O] If the carve reaches 124 eligible zh-TW pairs, G3 for zh-TW is not needed; if it does not, G3 is the cheaper way
to the 124 and the release says "generated" for zh-TW too. The first site is Japanese, so zh-TW waits behind ja.

### 7.8 A worked example: the same claim, two audit designs

Take the G3 set: 150 eligible-arm and 150 ineligible-arm pairs; the box excludes 2 eligible-arm charts and 140
ineligible-arm charts [O, illustrative numbers].

| Design | Clinician reads | What is bounded | Claim |
| --- | --- | --- | --- |
| 10 % random audit of all 300 pairs, unguided | 30 reads x 8 min = 4 h | generator label error under 9.5 % (0 found of 30) | **none**: up to about 13 hidden eligible patients among the 140 excluded ineligible charts remain possible, so the true upper bound could be 16.4 % (15 misses in 137) [M 1] |
| Every box-excluded ineligible chart and every box-excluded eligible chart checked, with planted sentence and quote | 142 reads x 2 to 5 min = 5 h | hidden eligible patients in the excluded set: counted, not estimated | the 5 % claim holds on the set (2 of ≥ 124 after removing any chart whose gold failed) |

The guided full check costs about one hour more than the unguided sample and is the only one of the two that supports
the claim. The non-excluded ineligible charts need no check for this bound: if their gold is wrong the box kept a
truly eligible patient, which is not a wrongful exclusion.

---

## 8. Gap table

| What the product does today | What is needed | Evidence |
| --- | --- | --- |
| No Japanese patient-level gold | generated charts (G3) + enrolment logs (G4) | [R 07 §3.2; R 17 §3.4] |
| Japanese gold planned as 125 h of writing | 17 h of checking, with quotes on screen | sections 6.2, 7.5 |
| criterion_ml translations labelled public domain | CC BY-SA 4.0 with CSIRO attribution | [R `eval/criterion_ml/README.md:27-29`; S 31] |
| MedTxt not in the register; MANBYO planned to ship as CC BY 4.0 | register rows; JMED-DICT mini shipped, MANBYO asked | [R `NOTICE:254`; S 1; R 06 line 327] |
| jRCT used one record at a time | the help desk's permission for a few hundred | [S 10; R `tools/public_accuracy/sources.py:265-271`] |
| No Japanese criterion key from official texts | 指定難病 and 最適使用 rulesets as criterion gold | [S 23, S 24; R 15 B16-18] |
| Gold checks not tied to the box's evidence quote | the gold-check screen shows the planted sentence and the quote | [S 41, S 48] |
| Scorer has no sampling weights | weights recorded per sampled item | [S 46] |
| No translation check beyond counts | back-translation diff and a clinician read of the differing sentences | [R `eval/criterion_ml/README.md:16-21`; S 36] |
| JMED-Personas the only Japanese patient-level set run on the box | marked "recall and plumbing; same family as the guard" in every report | [S 17] |

---

## 9. Cards (to paste into plan 10)

| Card | What | Size | Lane (guess) | Waits for | Proof |
| --- | --- | --- | --- | --- | --- |
| 20-1 | Plan text: the four gold stages, the release wording of 7.6, the hours of 7.6 (replaces 17-5's 125 h) | S | Int | decision 1 | plan 10 decision 19 ruled with this text |
| 20-2 | Licence fixes: criterion_ml and DATASETS.yaml to CC BY-SA 4.0 for SIGIR-derived notes; register rows for MedTxt, JMED-DICT mini, MANBYO (status "asked") | S | H | – | `tools.licence_register --check` green; a test that no SIGIR-derived file says public domain |
| 20-3 | File the requests of 7.4 (NAIST, jRCT help desk, Tsukuba); keep the answers in `docs/licences/` | S | owner, Int | – | three dated letters and their answers on file |
| 20-4 | Read and record the NHI site terms and the 台灣藥品臨床試驗資訊網 terms | S | Int | – | register rows with the quoted terms |
| 20-5 | Add JMED-LLM CC BY subsets (RRTNM 100, MRNER-disease 100, CRADE 100) to `medtxt_eval` as extra Japanese slices | S | G | 20-2 | scores per slice with Wilson intervals |
| 20-6 | Criterion gold from official texts: fetch 50 jRCT (one by one, or under the 20-3 permission), 20 指定難病, 10 最適使用, 100 TFDA; compile both languages; list disagreements for a clinician | M | A2, H | 20-3 for more than single records | a frozen criterion key per protocol with the clinician's resolution of each disagreement |
| 20-7 | Hard-phrase library: the clinician's 200 snippets, stored with their feature tag; the generator inserts them | S | H, clinician | decision 2 | 200 snippets, each tagged; a test that each feature has ≥ 15 |
| 20-8 | Chart generator v1 (another model family, DEV gateway, structured truth seeds, note types, deliberate unknowns), 150 charts x 2 protocols | M | H | 20-6, 20-7, decision 3 | manifest of 150 charts with truth; no judge-family model in the generation record |
| 20-9 | Gold-check screen: planted sentence and box quote side by side, 2-minute task, two-clinician mode with kappa (builds on 07's B7-8 annotation mode) | M | C2a, H | 07 B7-8 | a dry run on 20 charts records times and kappa |
| 20-10 | Freeze G3 (07's manifest), run the box, adjudicate every candidate miss; report the bound with the decided share (17-2) | S | G, Int | 20-8, 20-9, B7-6 | the pre-registered decision line in the run record |
| 20-11 | Back-translation check for criterion_ml ja and zh-TW: list the sentences whose back-translation differs; clinician reads them | S | H | – | a list per language and the clinician's verdicts; README updated from "not clinician-verified" |
| 20-12 | Enrolment-log run kit for the site: counts-only report of the box run as of each screening date for enrolled patients of past studies | M | G | 17-15 (ethics), site's list | a dry run on the synthetic hospital produces the record with no chart text |
| 20-13 | Sampling weights in the scorer for any audited or actively sampled set | S | A2 | – | a test: weighted estimate unbiased on a planted population |
| 20-14 | Japanese use-rule rulesets (lecanemab 最適使用, UC 指定難病) as criterion gold, with 15's B16-18 | M | A2, J | 20-6 | both compile; a clinician agrees with every line |
| 20-15 | Report labels: every accuracy report names its gold kind (physician, generated-checked, translated, structured truth, enrolment) and never pools them | S | G | – | a test that pooling across kinds is refused |

Counts: **S 10** (20-1, 20-2, 20-3, 20-4, 20-5, 20-7, 20-10, 20-11, 20-13, 20-15), **M 5** (20-6, 20-8, 20-9,
20-12, 20-14), **L 0**.

---

## 10. Decisions only the owner can make

| # | Decision | Recommendation |
| --- | --- | --- |
| 1 | Replace review 17's 125 h of paid writing with the four-stage plan (about 28 h of clinician checking + about 12 h at the site) | **Yes.** It reaches 124 eligible generated charts and keeps the claim honest by saying "generated" |
| 2 | Who checks: the two Japanese clinician readers already ruled for wording (plan 10 decision 35), extended by about 23 h; one zh-TW reader about 5 h | **Yes**, the readers you have; paid only if they cannot |
| 3 | Generate the charts with a hosted open model of another family through the DEV gateway (public data only, under US$5) | **Yes**; never the judge's or verifier's family, and record the generator in the manifest |
| 4 | Ask the first site for the retrospective enrolment-log run (counts only, its ethics review) as the real-chart proof beside shadow mode | **Yes**, in the same request as 17-15 |
| 5 | Release wording limited to the gold kind (7.6) until G4 reaches 124 real eligible patients | **Yes** |
| 6 | Research-only or non-commercial sets (NTCIR MedNLP-2, MedNLPDoc, iCorpus, NRNER, JCSTS, CT-RATE-JPN, PMC-Patients) | **Do not use**, not even internally, without written permission |
| 7 | Copyright Act Art. 30-4 as a basis to test on non-CC Japanese case reports in-house | **Not yet**: ask the regulatory reader first; not needed for this plan |
| 8 | MANBYO in the shipped bundle | **Wait** for NAIST's answer; ship JMED-DICT mini now |

---

## 11. What the owner or the first site must supply

1. **The two Japanese clinician readers' time**: about 23 hours (200 hard phrases; 30 realism ratings; 150 + 30 gold
   checks; candidate-miss adjudication; 80 protocols' disagreements). One zh-TW reader: about 5 hours.
2. **The site's list of 3 to 5 current study numbers** (jRCT or ClinicalTrials.gov) and **6 more it would run**, so the
   generated set uses its criterion mix (as 17 asks).
3. **From the site, counts only**: how many patients were enrolled in its studies in the last 3 years, by study, and
   whether screening logs record the screening date (sizes G4).
4. **The site's ethics route** for the enrolment-log run and the shadow mode (with 17-15).
5. **The owner's signature** on the three requests of 7.4 (they come from the company).
6. **The integrator's DEV gateway key** for the generation run (stays in the gateway).

---

## 12. What this document did not verify

- **n2c2 terms**: the DBMI portal, the DUA page and the DUA PDFs refused this machine (403/503); only search summaries.
- **NTCIR-10 MedNLP's permission page** (404) and the NTCIR application forms' exact clauses for companies.
- **J-STAGE's terms of use** (404) and any journal's licence; the "about 250 CC journals" figure is a search summary.
- **The full MedTxt-CR and iCorpus terms beyond their pages**; the 100 vs 148 MedTxt-CR count.
- **Package-insert copyright** (manufacturers'), **JADER CSV fields** (free text or not), the **national cancer
  registry** tables, **MID-NET fees**.
- **NHI website terms** and the **台灣藥品臨床試驗資訊網** terms; medical-bench-tw and the 台灣e院 Q&A upstream terms.
- **The 2016 to 2017 MHLW-funded mock-chart dataset**: whether it was ever released.
- **ANLP 2026 papers C5-12, P9-2, B9-6**: their Japanese text did not render; only numbers and the CC BY line were
  legible. The figures of S 47 (58 % time saved) are from a search summary; the abstract gives none.
- **Whether Article 30-4 covers evaluation by a company** with human labelling: a reading of the text only.
- **Clinician minutes per task** (1, 2, 5, 6 minutes) and the disagreement rates of G2 are estimates.
- **Hosted generation prices** were not checked today.
- **Whether the ethics route for the enrolment-log run is opt-out under 生命・医学系指針** for a vendor's tool.

---

## 12a. Where this review differs from earlier ones

| Earlier | This review | Why |
| --- | --- | --- |
| 17: 130 charts written by clinicians, about 125 h (card 17-5) | 150 charts written by a model of another family, checked by clinicians: about 17 h; about 28 h of ours in all | the owner's ruling; checking with quotes on screen is what makes the bound honest (section 6.2) |
| 17: double labelling 260 pairs x 2 x 4 min | every box exclusion checked, eligible-arm sample; kappa on 30 | labels matter in one direction for this bound |
| 06: MANBYO CC BY 4.0, "ship" | MANBYO's page grants only "feel free to use it" and points commercial users to JMED-DICT mini | [S 1] |
| 11: "CR full set on request (J-Stage terms)" | confirmed: no licence named, entry closed, contact by e-mail | [S 2] |
| `eval/criterion_ml`: notes "public domain" | SIGIR-derived: CC BY-SA 4.0 | [S 31; R register:36] |
| catalogue: Tsukuba licence conflict | confirmed on both Zenodo records | [S 27] |
| 07: Japanese gold from "a partner or paid writers" | open criteria texts + generated charts + the site's enrolment logs and shadow mode | no partner corpus is usable by a company |

## 12b. Change history

- 2026-11-18: first version (B-22).

---

## 13. Measurement log

Scripts outside the repository (`/var/tmp/trialbox-0/b22/scripts/b22binom.py`), run with `python3 -I` on the shared
machine; outputs read from the terminal.

| # | Command | Result |
| --- | --- | --- |
| 1 | `python3 -I b22binom.py` (exact Clopper-Pearson by bisection; binomial tails) | section 6.2 tables; n for 5 % / 2 % with 0 to 3 misses = 59 / 93 / 124 / 153 and 149 / 236 / 313 / 386 (agrees with R 17); hidden-eligible table; pass probabilities; recall lower bounds 90.2 % (29, 0), 95.0 % (59, 0), 95.0 % (124, 2); enrolled 150 with 2 misses → 4.14 %; worked examples (same functions, `python3 -I -c`): 15 in 137 → 16.36 %, 28 in 150 → 24.69 % |
| 2 | `grep` of `docs/licences/register.csv` and `NOTICE` for MedTxt, Real-MedNLP, MANBYO, SIGIR, JMED | MedTxt only in NOTICE (254-259); MANBYO absent; SIGIR CC-BY-SA-4.0 (row 36); JMED-Personas row 43 |
| 3 | Hugging Face API `datasets?search=` for "japanese medical", "jmed", "igaku", "kokushi", "karte", "zh-tw medical", "taiwan medical", "traditional chinese medical", "emr taiwan", "taiwan" (medical filter), and `author=sociocom`, `author=SIP-med-LLM` | the rows of sections 2 and 5; no Japanese or Taiwanese clinical-note set with a commercial licence beyond those listed |
| 4 | `curl` of https://jrct.mhlw.go.jp/agreement, text extracted | the jRCT terms quoted in section 3 (WebFetch was refused 403) |
| 5 | e-Gov law API, 著作権法 (345AC0000000048), Article 30-4 | quoted in section 3 |
| 6 | Zenodo API records 4064153, 3752281 | `license: cc-by-4.0` in metadata; "CC BY-NC 4.0" in both descriptions; file sizes |
| 7 | JMED-Personas README (raw) | generation model, limitations, copyright and notes quoted in section 2.2 |

---

## 14. Sources (opened 2026-11-18 unless marked)

| n | Source | Link | Terms of the page |
| --- | --- | --- | --- |
| S 1 | MANBYO 万病辞書 page | https://sociocom.naist.jp/manbyo-dic/ | page text |
| S 2 | Real-MedNLP (NTCIR-16) task page | https://sociocom.naist.jp/real-mednlp/ | no licence stated |
| S 3 | Real-MedNLP test collection download | https://sociocom.naist.jp/download/real-mednlp-test-collection/ | CC BY 4.0 |
| S 4 | NTCIR-11 MedNLP permission | http://research.nii.ac.jp/ntcir/permission/ntcir-11/perm-en-MedNLP.html | research only |
| S 5 | NTCIR-12 MedNLPDoc permission | http://research.nii.ac.jp/ntcir/permission/ntcir-12/perm-en-MedNLPDOC.html | research only |
| S 6 | NTCIR permission (general); NTCIR-10 page 404 | http://research.nii.ac.jp/ntcir/permission/perm-en.html | research only |
| S 7 | JMED-LLM README | https://raw.githubusercontent.com/sociocom/JMED-LLM/main/README.md | per task |
| S 8 | JMedBench card | https://huggingface.co/datasets/Coldog2333/JMedBench | per subset |
| S 9 | IgakuQA README | https://raw.githubusercontent.com/jungokasai/IgakuQA/main/README.md | none stated |
| S 10 | jRCT 利用規約 | https://jrct.mhlw.go.jp/agreement | PDL 1.0 with 特記事項 |
| S 11 | 公共データ利用規約（第1.0版） | https://www.digital.go.jp/resources/open_data/public_data_license_v1.0 | the licence itself |
| S 12 | UMIN-CTR CSV data terms | https://www.umin.ac.jp/ctr/csvdata.html | the terms |
| S 13 | J-STAGE WebAPI terms | https://www.jstage.jst.go.jp/static/pages/WebAPI/-char/ja | the terms |
| S2 14 | J-STAGE seminar report 2023 (CC journals) | https://www.jstage.jst.go.jp/static/files/ja/pub_JSTAGEseminar_report2310.pdf (search summary) | – |
| S 15 | 著作権法 第30条の4 | https://laws.e-gov.go.jp/law/345AC0000000048 (API) | law |
| S 16 | 平成29年度 厚生労働科学研究 総括研究報告書 (電子カルテ情報のセマンティクス標準化) | https://mhlw-grants.niph.go.jp/system/files/2017/171013/201703007A_upload/201703007A0003.pdf | report |
| S 17 | JMED-Personas-100k card and README | https://huggingface.co/datasets/sociocom/JMED-Personas | CC BY 4.0 |
| S 18 | MHLW 著作権について | https://www.mhlw.go.jp/chosakuken/index.html | PDL 1.0 |
| S 19 | PMDA サイトポリシー | https://www.pmda.go.jp/0048.html | PDL 1.0 |
| S 20 | PMDA 医薬品副作用データベース 利用規約 | https://www.pmda.go.jp/safety/info-services/drugs/adr-info/suspected-adr/0006.html | the terms |
| S2 20 | JADER scope and publication duty (search summary of PMDA pages 0003 to 0005) | https://www.pmda.go.jp/safety/info-services/drugs/adr-info/suspected-adr/0004.html | – |
| S 21 | NDB オープンデータ | https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000177182.html | PDL 1.0 (MHLW) |
| S2 22 | MID-NET 利活用 (search summary) | https://www.pmda.go.jp/safety/mid-net/0002.html | – |
| S 23 | 指定難病一覧 | https://www.mhlw.go.jp/stf/newpage_53881.html | PDL 1.0 (MHLW) |
| S 24 | 最適使用推進ガイドライン | https://www.pmda.go.jp/review-services/drug-reviews/review-information/p-drugs/0028.html | PDL 1.0 (PMDA policy) |
| S2 25 | Minds site policy (search summary) | https://minds.jcqhc.or.jp/about-us/site-policy/ | – |
| S 26 | NTCIR-17 MedNLP-SC | https://sociocom.naist.jp/mednlp-sc/ | no licence stated |
| S 27 | Tsukuba pseudo progress notes | https://zenodo.org/records/4064153 ; https://zenodo.org/records/3752281 (API) | conflicting |
| S 28 | Hugging Face dataset API and cards: CT-RATE-JPN, PMC-Patients-JA-DDx, JMedQA, KokushiMD-10, igakuqa-subset-curated, JMED-DICT_mini (README), taiwan_e_hospital, medical-bench-tw, an individual's dummy_karte | https://huggingface.co/api/datasets/<id> | per card |
| S2 29 | n2c2 access and DUA (search summary; pages 403/503) | https://n2c2.dbmi.hms.harvard.edu/data-use-agreement | – |
| S 30 | TREC 2021 Clinical Trials data page | https://trec.nist.gov/data/trials2021.html | none stated |
| S 31 | SIGIR 2016 test collection (CSIRO) | https://researchdata.edu.au/a-test-collection-clinical-trials/664508 | CC BY-SA 4.0 |
| S 32 | Chia annotated datasets (figshare API) | https://api.figshare.com/v2/articles/11855817 | CC BY 4.0 |
| S 33 | TrialGPT-Criterion-Annotations (API, README) | https://huggingface.co/datasets/ncbi/TrialGPT-Criterion-Annotations | public domain |
| S2 34 | PMC-Patients card (search summary) | https://huggingface.co/datasets/zhengyun21/PMC-Patients | CC BY-NC-SA 4.0 (also S 28 API) |
| S 35 | Seinen et al., Annotation-preserving machine translation of English corpora to validate Dutch clinical concept extraction tools, JAMIA 2024;31(8):1725-34 (PubMed) | https://doi.org/10.1093/jamia/ocae159 | publisher terms |
| S 36 | Physician detection of clinical harm in machine translation (arXiv 2310.16924) | https://arxiv.org/abs/2310.16924 | CC BY 4.0 |
| S2 37 | MT error taxonomy in healthcare, EMNLP 2025 (search summary) | https://aclanthology.org/anthology-files/pdf/emnlp/2025.emnlp-main.535.pdf | – |
| S2 38 | JMedBench paper (search summary) | https://arxiv.org/pdf/2409.13317 | – |
| S 39 | Grazhdanski et al., SynthMedic, J Biomed Inform 2025;170:104906 (PubMed) | https://doi.org/10.1016/j.jbi.2025.104906 | publisher terms |
| S 40 | Gan et al., Reproducible synthetic clinical letters for seizure frequency extraction, J Biomed Inform 2026;183:105105 (PubMed) | https://doi.org/10.1016/j.jbi.2026.105105 | publisher terms |
| S 41 | May et al., AI-assisted error detection in complex clinical documentation, JCO CCI 2026;10:e2500194 (PubMed) | https://doi.org/10.1200/CCI-25-00194 | publisher terms |
| S 42 | Fujiwara et al., accuracy of algorithms for major cancers in a Japanese administrative database, BMJ Open 2022;12:e055459 (PubMed) | https://doi.org/10.1136/bmjopen-2021-055459 | CC BY-NC (BMJ Open; not opened) |
| S 43 | Ogino et al., claims-based algorithm for ulcerative colitis in Japan, J Gastroenterol Hepatol 2022;37:499-506 (PubMed) | https://doi.org/10.1111/jgh.15732 | publisher terms |
| S 44 | Rebholz-Schuhmann et al., CALBC Silver Standard Corpus, J Biomed Semantics 2011;2(Suppl 5):S11 (PubMed) | https://doi.org/10.1186/2041-1480-2-S5-S11 | CC BY |
| S 45 | Ratner et al., Snorkel, PVLDB 11(3) 2017 (arXiv 1711.10160) | https://arxiv.org/abs/1711.10160 | arXiv licence |
| S 46 | Kossen et al., Active Testing, ICML 2021 (arXiv 2103.05331) | https://arxiv.org/abs/2103.05331 | arXiv licence |
| S 47 / S2 47 | LLMs Accelerate Annotation for Medical Information Extraction (arXiv 2312.02296); the 58 % figure from a search summary | https://arxiv.org/abs/2312.02296 | CC BY 4.0 |
| S 48 | Assessing the impact of automated suggestions on decision making: domain experts mediate model errors but take less initiative (arXiv 2103.04725) | https://arxiv.org/abs/2103.04725 | arXiv licence |
| S 49 | 言語処理学会 第32回年次大会 (2026) C5-12, P9-2, B9-6 | https://www.anlp.jp/proceedings/annual_meeting/2026/pdf_dir/C5-12.pdf (and P9-2, B9-6) | CC BY 4.0 (stated on each page) |
| S2 50 | NHI 藥品給付規定 第9節 amendment tables (search summary) | https://www.nhi.gov.tw/ch/dl-100602-833add3e1b9140368cfee0e65408c0ce-1.pdf | not read |
| S 51 | MHLW 臨床研究情報ポータル | https://rctportal.mhlw.go.jp/ | terms not read |
