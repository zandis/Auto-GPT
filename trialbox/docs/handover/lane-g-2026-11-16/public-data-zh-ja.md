# Public Chinese and Japanese clinical data for TrialBox: what exists, what we may use, what to run first

Research date 2026-11-14. Read-only: nothing in the repository was changed. I read the repository's current data first:
`eval/DATASETS.yaml`, `eval/*`, `docs/licences/register.csv`, `NOTICE`, `tools/public_site.py`, `tools/medtxt_eval.py`
and `audit-B-data.md`. Downloads went into the scratchpad only (`.../scratchpad/zhja/`). Nothing was bought, and no
account was created.

"Verified" means I opened the source's own page, API or files and read the line I quote. "Not verified" means I only saw it in
search results or in a third party's description.

**About the order to "use TrialGPT, it has them":** TrialGPT's patients are English only. They are the SIGIR 2016 notes and the
TREC CT 2021/2022 topics. The repository already holds them (`eval/criterion_ml`, `eval/trec_ct`). The ja and zh-TW files
there are TrialBox's own translations. TrialGPT has no Chinese or Japanese patients. Kaggle has nothing clinical in zh or ja that I could
find. The only Chinese medical sets I found on Kaggle are copies of online Q&A and dialogue data, and kaggle.com cannot be
reached from this machine (section 5).

**Size of the search:** I examined 96 candidates. They came from searches in English, Traditional Chinese, Simplified Chinese
and Japanese, from the Hugging Face API (30 keyword searches and 25 publisher listings), from raw GitHub READMEs, Zenodo,
PubMed/PMC E-utilities, data.gov.tw, and the BRIDGE benchmark's 87-task table, which I read in full.

---

## 1. Use first, per language (ranked)

### Traditional Chinese (Taiwan)

| # | Set | What it proves in TrialBox | Licence for a vendor |
|---|---|---|---|
| 1 | **TFDA 台灣藥品臨床試驗現況資料集** (data.gov.tw 177198). Real zh-Hant inclusion and exclusion criteria of 5,533 drug trials approved in Taiwan | **Criteria compile gold in zh-Hant** with no clinician labelling. About two thirds of the protocol numbers match a ClinicalTrials.gov record (20 of 30 sampled). Compile the zh-Hant text and the English text of the same trial, and the two IRs must agree. The texts also test long criteria, lab thresholds and mixed zh/en drug names, and they make real criteria for a Taiwanese site | **Open, commercial use allowed** (OGDL-TW 1.0, "any purpose") |
| 2 | **PMC Chinese-language case reports under CC BY** (314 articles titled "case report", e.g. 中华血液学杂志, 中国肺癌杂志) | Long real notes (about 2,500–3,000 characters in the case section) with ages, absolute dates, labs and pathology. Convert them to zh-Hant (OpenCC s2twp), then a Taiwan clinician reviews the terms. They can be loaded as site charts. These are the best public substitute for long zh notes | **Open, commercial use allowed** (CC BY 3.0/4.0, per article) |
| 3 | **OpenTWBench tw-exam-bench** (考選部 exam questions; the medicine file has 13,963 items, 2,140 of them patient vignettes) | Real Taiwanese wording, mixed with English in the same way charts are (median Latin-letter share 11.6%, top quarter at 26% or more). ROC years appear as fields. Use the vignettes to check that the judge reads Taiwanese medical Chinese. Each is one or two sentences, so they are **not** long notes | **Open** (Apache-2.0 on the card; source is government exam papers) |
| 4 | **English-note sets already in the repository** (SIGIR 53, TREC 2021/2022, MedTxt-CR-EN) used **as the Taiwan accuracy proxy** | A Taiwanese study of 1,700 discharge summaries found "the majority of records being written in English". It also found that English-only sentences are the most common type, then code-mixed, then Chinese-only (section 2). English notes therefore test the dominant language of a Taiwanese chart | already cleared |
| 5 | **MedQA Taiwan subset (TWMLE)**, 14,123 Taiwanese licensing-exam questions | More vignettes in Taiwanese style, with gold answers | repo MIT; **data licence unclear** (BigBio: "unknown"). Use internally only, after a check |

There is no public set of Taiwanese clinical notes with eligibility labels. Section 2 explains why.

### Simplified Chinese (convert to zh-Hant, then review the terms)

| # | Set | What it proves | Licence for a vendor |
|---|---|---|---|
| 1 | PMC CC BY Chinese case reports (as above) | long notes, labs in text, dates | open |
| 2 | **CHIP-CDEE** (CBLUE; 1,971 real 现病史 and imaging-finding passages from EMRs, each finding labelled 肯定/否定/不确定) | **Negation and uncertainty stratum gold** on real EMR text. A labelled finding becomes an exclusion criterion, the same way `medtxt_eval` turns MedTxt certainty tags into criteria | **blocked until terms are read**: data only through the Tianchi application. CBLUE code is Apache-2.0, and the data terms are not stated publicly |
| 3 | **CHIP-CTC** (CBLUE; 40,644 ChiCTR eligibility sentences in 44 categories) | Gold for routing criterion types in zh (sentence → category). Covers criteria only, not patients | as CHIP-CDEE (Tianchi application) |
| 4 | **Yidu-S4K / CCKS 2019** (about 1,379 EMR passages, 6 entity types) | Real EMR text for entity spans: diagnosis, drug, lab, surgery | Tianchi or OpenKG; terms not verified |
| 5 | **CMB-Clin** (74 real teaching cases with expert answers) | Long case text with a diagnostic gold standard | Apache-2.0 (HF card); verified |

### Japanese

| # | Set | What it proves | Licence for a vendor |
|---|---|---|---|
| 1 | **MedTxt-CR / MedTxt-RR** (already used): CR 100 training reports (the page says so; the repository says 148, check this), RR 135 reports, ja + en | Negation, suspected (疑い) and positive findings already turned into criteria; the original check can be restored | CC BY 4.0 (verified on the download page) |
| 2 | **MedTxt-CR full release**: 3,148 OCR'd J-STAGE case reports, plus a 224-report balanced, annotated subset | **Long notes and real OCR noise**: about 20 times more Japanese case text than today | "can be used free of charge if requested"; **no licence named**. Write to the lab and ask about vendor validation |
| 3 | **JMED-Personas-100k** (Sociocom, 100,000 synthetic patients, 71 fields) | **Lost-eligible and product-path runs with built-in truth.** Structured fields (主病名, ICD-10, 既往歴, 家族歴, 血液検査, 処方薬) sit next to narrative text written from them. Load the narrative as charts, put criteria on the structured fields, and count misses. Covers family history, labs in text and medicines. The text is **synthetic**, so it measures recall and the data path, not real-note accuracy | **CC BY 4.0** (verified) |
| 4 | **iCorpus** (University of Tokyo; 179 J-STAGE case reports of 102 designated rare diseases, annotated) | More real Japanese case text with entity gold | **research use only** ("本目的…研究目的のためにのみ"). A vendor needs permission |
| 5 | **jRCT eligibility text** (Japanese) | **Criteria compile gold in ja**: real 選択基準/除外基準. jRCT records often carry an NCT ID, so the ja↔en pairs can work like the TFDA ones | **PDL 1.0 = CC BY-compatible, commercial use allowed**, but bulk collection needs written permission from the helpdesk first |
| 6 | **Tsukuba pseudo progress notes** (Zenodo; 9,756 crowd-written + 83 rated + 19 doctor-written SOAP notes) | Real Japanese charting style: short SOAP notes with English mixed in ("vital stable") | **licence conflict**: the record says CC BY 4.0, the description says "CC BY-NC 4.0". Treat it as NC until the authors confirm |
| 7 | NTCIR-17 MedNLP-SC RR (243 lung-cancer radiology reports with TNM labels) | Staging criteria (T, N, M, cStage) against real reports | licence not stated on the page |

---

## 2. Traditional Chinese: the honest answer

**No real Traditional Chinese clinical notes are publicly usable.** Everything real from Taiwan sits behind an institution or an IRB:

* 1,700 code-mixed discharge summaries from a Taiwanese medical centre (Dai et al., JMIR 2024, doi 10.2196/48443). They are
  not public. The authors say "we created a manipulated subset of the resynthesized data set available for research
  purposes". It is research-only and has no public link; the request goes to the NKUST lab.
* 4,737 NTUH psychiatric discharge summaries (SHTI 2022): not public.
* 7 million Cheng Hsin outpatient notes (arXiv 2312.13533): not public.
* NHIRD / 衛生福利資料科學中心 (HWDC): claims data, used on site, results only. Applicants are academic, government, or
  industry with the patient's written consent. No free text.
* AI CUP medical tracks: the 2020 NCKU doctor–patient dialogue de-identification data is spoken dialogue; the
  education ministry's programme rule says contest data stays open for teaching and research, but I did not verify
  that for this set. The 2023 SREDH/AI CUP track used **Australian English** pathology reports (OpenDeID, under a DUA).
* Hong Kong: I found no Traditional Chinese clinical-note corpus. The only one is a gated OCR set of scanned forms
  (meddocbench).

**What Taiwanese charts look like, with evidence.** Dai et al. measured the 1,700 discharge summaries and wrote of "the
writing convention in Taiwan's medical records, with the majority of records being written in English". They also found that
"the most frequent type of sentences was English only, followed by code-mixed and Chinese only", with a corpus
code-mixing index of 22.21 (verified on PMC10853853). Hospital teaching material says orders, admission notes and
diagnoses are written in English with Chinese notes added. Taiwanese exam questions show the same mix: Chinese sentences
with English terms in parentheses and English lab names (OpenTWBench sample above).
**Conclusion:** for Taiwan, an **English-heavy note set is closer to the real thing than a Mainland Chinese EMR corpus**.
Mainland EMRs are written almost entirely in Chinese and use Mainland terms. The Chinese in a Taiwanese chart sits
mostly in the subjective and history parts (complaint, social and family history), in nursing notes, consent forms and
letters, and in code-mixed sentences.

**Substitutes, ranked, with their weaknesses**

1. **A mixed set written by Taiwan clinicians** (not translated). One or two Taiwanese clinicians write about 200 notes in
   real EMR style: English body, Chinese 主訴/家族史/社會史, 民國 dates, NHI drug names. Each note carries planted strata
   and gold labels. *Best realism; costs clinician time; it is still not real patient text.*
2. **English real notes** (SIGIR, TREC, MedTxt-CR-EN, and the 4,000+ PMC-Patients English summaries, which are CC BY-NC-SA
   and so for internal use only). *They test the dominant language. They miss code-mixing, Taiwanese drug and brand names,
   and 民國 dates.*
3. **PMC CC BY Chinese case reports, converted** (OpenCC s2twp, Apache-2.0) and then reviewed by a Taiwanese clinician.
   *Real, long and licence-clean. But they are case reports, not charts. They use Mainland terms (心肌梗死 vs 心肌梗塞,
   阿司匹林 vs 阿斯匹靈, transliterated drug names where Taiwan writes English). They are far more Chinese than a Taiwanese
   chart, and they carry no 民國 dates.*
4. **CHIP-CDEE / Yidu-S4K, converted.** *These are real EMR passages with negation gold, which is valuable. But access goes
   through an application with unclear vendor terms, and the passages are short and use Mainland style.*
5. **TFDA criteria + OpenTWBench vignettes.** *Real Taiwanese language, but criteria and one-line vignettes, not
   charts.*

**Era dates.** No public zh set uses 民國 dates in notes (TFDA criteria: 1 of 5,533). OpenTWBench has `year_roc` only as
metadata. Japanese 和暦 in MedTxt was not checked. Both have to be placed in notes we write (route 1), as
`public_site.py` already places visit dates.

---

## 3. Catalogue (96 candidates)

Columns: **Lang** (zh-Hant, zh-Hans, ja, mix = mixed with English); **Licence / vendor use** ("vendor OK" = a product
vendor may use it for validation); **Serves** (L long notes, N negation, F family history, D era dates, B labs in text,
E eligible-loss, C criteria compile gold, P data path, O OCR); **Product path** (can notes be loaded as a site's charts and
real criteria run through the gateway and the cascade?); **Check** (V verified on the page given, NV not verified).

### 3a. Taiwan / Traditional Chinese / Hong Kong

| # | Name | URL | Owner | Holds | Lang | Licence / vendor use | Serves | Product path | Check |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 台灣藥品臨床試驗現況資料集 | data.gov.tw/dataset/177198 → data.fda.gov.tw/data/opendata/export/205/csv | TFDA | 19,290 rows, 5,724 trials, 5,533 with criteria; median 2,526 characters of criteria; 2,702 with lab thresholds; trials started 2004–2027. Quirks: in 3,922 rows the whole block is copied into both 納入 and 排除; 2,264 rows contain HTML entities | zh-Hant + en terms | OGDL-TW 1.0, "any purpose"; **vendor OK** | C, B, P | yes (criteria) | V (downloaded and counted) |
| 2 | 試驗藥品資料集 / 宣稱適應症(ICD9) | data.gov.tw/dataset/177216, 177212 | TFDA | drugs and ICD-9 per trial | zh-Hant | OGDL-TW; vendor OK | C (code gold) | yes | V (API) |
| 3 | 台灣藥品臨床試驗資訊網 | e-sub.fda.gov.tw | MOHW/TFDA | per-trial public pages since 2025-01-01, including main criteria | zh-Hant | not read | C | yes | NV |
| 4 | OpenTWBench tw-exam-bench | huggingface.co/datasets/OpenTWBench/tw-exam-bench | OpenTWBench | about 100k+ exam items; medicine file 13,963 (2,140 vignettes, median 105 characters); exams of ROC years 101–115 | zh-Hant mix | Apache-2.0; vendor OK (government source) | language check | weak (one-line notes) | V (downloaded) |
| 5 | EMPEC | huggingface.co/datasets/KenLuo/EMPEC | Univ. Manchester et al. | 157,803 Taiwanese health-profession exam items | zh-Hant | CC BY-NC-ND; not for a vendor | language check | no | V (HF tag) |
| 6 | MedQA (TWMLE part) | github.com/jind11/MedQA | Jin et al. | 14,123 Taiwan items | zh-Hant | repo MIT; data "unknown"; check first | language | weak | V (README, LICENSE) |
| 7 | TMMLU+ | huggingface.co/datasets/ikala/tmmluplus | iKala | 67 subjects, several medical | zh-Hant | MIT | language | no | V (HF tag) |
| 8 | TCEval-v2 | huggingface.co/datasets/MediaTek-Research/TCEval-v2 | MediaTek | general TW benchmarks; medical only through TMMLU+ | zh-Hant | none stated | – | no | V (card) |
| 9 | medical_dialogue-chinese-zhtw | huggingface.co/datasets/erhwenkuo/medical_dialogue-chinese-zhtw | individual | 799,743 online Q&A converted from Simplified | zh-Hant (converted) | MIT (an upstream claim) | weak; shows how converted text reads | no | V (card) |
| 10 | Code-mixed de-identification corpus (Dai et al.) | doi 10.2196/48443 | NKUST / medical centre | 1,700 discharge summaries, mostly English | mix | not public; resynthesized subset "for research purposes" | L, P (style) | would be yes | V (PMC text) |
| 11 | NTUH psychiatric discharge summaries | doi 10.3233/SHTI220153 | NTUH | 4,737 summaries | mix | not public | – | – | NV |
| 12 | Cheng Hsin outpatient notes | arxiv.org/abs/2312.13533 | Cheng Hsin GH | >7M notes | mix | not public | – | – | V (abstract) |
| 13 | AI CUP 2020 medical dialogue de-identification | aicup.tw | NCKU Hospital / MOE | clinic conversations, 18 PHI types | zh-Hant spoken | teaching and research after the contest (programme rule) | weak | no | NV |
| 14 | SREDH/AI CUP 2023 (OpenDeID v2) | github.com/SREDH-Consortium/OpenDeID-Corpus | UNSW / SREDH | 3,244 Australian pathology reports | en | DUA | de-identification only | no | V (README) |
| 15 | SREDH/AI CUP 2025 SHI speech corpus | zenodo.org/records/24032429 | SREDH | clinical speech | en/zh | DUA | – | no | NV |
| 16 | TW Core IG v1.0.0 examples | twcore.mohw.gov.tw/ig/twcore/package.tgz | MOHW | 98 example resources; DocumentReference holds only a PDF reference, no free text | zh-Hant | **CC0-1.0** (package.json); vendor OK | P (FHIR shape) | yes (structured only) | V (package) |
| 17 | TWPAS IG | nhicore.nhi.gov.tw/pas | NHIA | already in repo | zh-Hant | CC0 | P | yes | repo register |
| 18 | NHI drug, order and lab code tables | data.gov.tw/dataset/23715 | NHIA | already in repo | zh-Hant | OGDL-TW | P | yes | repo register |
| 19 | NHIRD / HWDC | dep.mohw.gov.tw | MOHW | claims; on site only | – | application; industry only with consent; no free text | – | no | V (search; MOHW forms) |
| 20 | Taiwan Biobank | biobank.org.tw | Academia Sinica | genotype and questionnaire | – | application | – | no | NV |
| 21 | 台灣醫學 (Formosan J Med) case reports | – | Formosan Medical Assoc. | zh-Hant case reports | zh-Hant | copyright transferred to the society; ask permission | L | yes if licensed | NV (search snippet of author rules) |
| 22 | 內科學誌 and other zh-Hant society journals | – | societies | zh-Hant case reports | zh-Hant | licence not found | L | – | NV |
| 23 | Tzu Chi Medical Journal | tzuchi.com.tw/medjnl | Tzu Chi / Wolters Kluwer | English case reports from TW | en | CC BY-NC-SA/ND (from the journal PDF) | L (en) | internal only | NV |
| 24 | J Formosan Med Assoc | doaj.org/toc/0929-6646 | FMA / Elsevier | English | en | CC BY-NC-ND | L (en) | internal only | NV |
| 25 | CMaiSpeech nursing speech | doi 10.2196/37562 | CMUH | nursing-record speech | mix | not public | – | – | NV |
| 26 | meddocbench (Hong Kong forms) | huggingface.co/datasets/Owenhku/meddocbench-sample | HKU (individual) | scanned HK clinical forms | zh-Hant/en | gated, manual approval | O | maybe | NV |
| 27 | HKCanCor | huggingface.co/datasets/hkcancor | – | Cantonese conversation, not medical | yue | – | – | no | NV |
| 28 | NAER bilingual medical terms | data.gov.tw/dataset/15460 | NAER | already in repo; Taiwan term review aid | zh-Hant/en | OGDL-TW | conversion review | – | repo register |

### 3b. Simplified Chinese

| # | Name | URL | Owner | Holds | Lang | Licence / vendor use | Serves | Product path | Check |
|---|---|---|---|---|---|---|---|---|---|
| 29 | PMC Chinese OA case reports | pmc (E-utilities: `chinese[la] AND open access[filter] AND case report[ti]`) | journals (中华血液学杂志 127 of 200 sampled, 中南大学学报, 中国肺癌杂志…) | 567 OA; **314 CC BY**, 36 CC BY-NC-ND, 5 CC BY-NC. 7,282 Chinese OA articles in total | zh-Hans + en terms | CC BY per article (e.g. PMC13688438: "CC BY 3.0"); **vendor OK** | L, B, D (absolute dates), P | **yes** (one report = one patient, as in public_site) | V (E-utilities counts, one article read) |
| 30 | CBLUE (whole suite) | github.com/CBLUEbenchmark/CBLUE; tianchi.aliyun.com/dataset/95414 | Alibaba / CHIP | CMeEE, CMeIE, CHIP-CDN, CDEE, CTC, STS, MDCFNPC, IMCS-V2, MedDG, KUAKE | zh-Hans | code Apache-2.0; data by Tianchi application, terms not public | see rows | – | V (README, LICENSE); data terms NV |
| 31 | CHIP-CTC | as above | CHIP 2019 | 22,962 / 7,682 / 10,000 ChiCTR criteria sentences, 44 classes | zh-Hans | Tianchi | C (types) | criteria only | V (README table) |
| 32 | CHIP-CDEE | as above | CHIP 2021 | 1,971 EMR history and imaging passages; status 肯定/否定/不确定 | zh-Hans | Tianchi | **N**, B | yes (passages as notes) | V (BRIDGE paper) |
| 33 | CHIP-CDN | as above | CHIP | diagnosis strings → ICD-10 Beijing v601 | zh-Hans | Tianchi | C (code mapping) | – | V (BRIDGE) |
| 34 | CHIP-MDCFNPC | as above | CHIP 2021 | dialogue findings, positive/negative | zh-Hans | Tianchi | N (dialogue; weak) | no | V (BRIDGE) |
| 35 | CMeEE / CMeIE | as above | CHIP | textbook text with entities and relations | zh-Hans | Tianchi | weak | no | V (CBLUE paper) |
| 36 | IMCS-21 / IMCS-V2 | github.com/lemuria-wchen/imcs21 | Fudan | 4,116 paediatric consultations | zh-Hans | MIT copies on HF; dialogue | weak | no | V (README) |
| 37 | MedDG | (CBLUE) | – | 17k GI dialogues | zh-Hans | – | weak | no | V (BRIDGE) |
| 38 | Yidu-S4K / CCKS 2019 | openkg.cn/dataset/yidu-s4k; tianchi 92085/144419 | Yidu Cloud / CCKS | about 1,379 EMR passages, 6 entity types | zh-Hans | not found | B, entity gold | yes (passages) | NV |
| 39 | CCKS 2017/2018 EMR NER | – | CCKS | EMR NER | zh-Hans | not found | – | – | NV |
| 40 | PromptCBLUE | github.com/michael-wzhu/PromptCBLUE | ECNU | 18 tasks as prompts | zh-Hans | "仅供学术研究之用，严禁用于商业用途"; **not for a vendor** | – | no | V (README) |
| 41 | CMB / CMB-Clin | huggingface.co/datasets/FreedomIntelligence/CMB | CUHK-SZ | CMB-Clin: 74 real teaching cases | zh-Hans | Apache-2.0; vendor OK | L (small), diagnosis gold | yes (74) | V (HF tag) |
| 42 | CMExam | huggingface.co/datasets/fzkuji/CMExam | – | 60k Mainland exam items | zh-Hans | Apache-2.0 (HF copy) | language | weak | V (tag, README) |
| 43 | MedQA (Mainland part) | github.com/jind11/MedQA | Jin et al. | 34,251 items | zh-Hans | as row 6 | language | weak | V |
| 44 | MMedBench | huggingface.co/datasets/Henrychur/MMedBench | SJTU | QA with rationale; zh and ja parts | zh, ja | CC BY-NC; not for a vendor | – | no | V (card) |
| 45 | Huatuo-26M, encyclopedia, consultation QA | huggingface.co/FreedomIntelligence | CUHK-SZ | QA | zh-Hans | Apache-2.0 | weak (QA) | no | V (tags) |
| 46 | MedDialog-CN | arxiv 2004.03329 | UCSD | 3.4M dialogues | zh-Hans | research | weak | no | NV |
| 47 | Toyhom Chinese-medical-dialogue | github.com/Toyhom/Chinese-medical-dialogue-data | individual | 792k Q&A | zh-Hans | not stated | weak | no | V (README) |
| 48 | ChatMed_Consult | huggingface.co/datasets/michaelwzhu/ChatMed_Consult_Dataset | ECNU | consultations with LLM answers | zh-Hans | CC BY 4.0 | weak | no | V (tag) |
| 49 | C-EMRs | doi 10.1038/s41598-018-24389-w | Huangshi Central Hosp. | 18,590 EMRs (complaint, exam; 10 diseases) | zh-Hans | "released" per paper; access route not found | L?, diagnosis | yes, if obtainable | V (BRIDGE desc.); access NV |
| 50 | EHRQA | (BRIDGE ref 42) | Zhejiang hospital | 210,175 EHRs + 3.02M QA | zh-Hans | not found | triage | – | V (BRIDGE desc.); access NV |
| 51 | CDrugRed (CHIP 2025) | github.com/DUTIR-BioNLP/CDrugRed; arXiv 2510.21084 | DUT | 5,894 de-identified records of 3,190 patients (history, course, discharge diagnosis) | zh-Hans | data use agreement (per paper) | L, B, medicines | yes, if a DUA allows | NV (repo page 404 for me) |
| 52 | MedCD | ieee-dataport.org/node/14761 | – | 1.7M EHR examples | zh-Hans | login, terms not read | – | – | NV |
| 53 | TCMNER2026 | ieee-dataport.org/documents/tcmner2026 | – | TCM case records | zh-Hans | academic, on request | weak (TCM) | no | NV |
| 54 | CMedCausal (CHIP 2022) | arXiv 2403.04261 | CHIP | 2,000 + 2,000 causal relations | zh-Hans | not found | weak | no | NV |
| 55 | DiaKG | tianchi 88836 | – | diabetes guideline text | zh-Hans | Tianchi | weak | no | NV |
| 56 | ShenNong TCM | huggingface.co/datasets/michaelwzhu/ShenNong_TCM_Dataset | ECNU | TCM instructions | zh-Hans | Apache-2.0 | – | no | V (tag) |
| 57 | ChiCTR registry text | chictr.org.cn | West China / ChiCTR | Chinese criteria per trial | zh-Hans | footer: "Copyright(c) (2005 - 2023) Chictr.org.cn. All rights reserved."; **not for a vendor without permission**; no bulk export | C | criteria | V (home page) |
| 58 | Chinese EMR corpora from 北京协和 (336 or 800 documents, research papers) | – | PUMCH | discharge summaries | zh-Hans | not public | – | – | NV |
| 59 | CHIP-STS / KUAKE-* | HF copies (wyp/*, dirtycomputer/*) | – | query and sentence pairs | zh-Hans | unlicensed copies | – | no | V (HF list) |

### 3c. Japanese

| # | Name | URL | Owner | Holds | Lang | Licence / vendor use | Serves | Product path | Check |
|---|---|---|---|---|---|---|---|---|---|
| 60 | MedTxt-CR + MedTxt-RR (Real-MedNLP test collection) | sociocom.naist.jp/download/real-mednlp-test-collection/ | NAIST Sociocom | CR 100 training reports (page; repo says 148), RR 72 + 63 | ja + en | **CC BY 4.0**; vendor OK | N (certainty), L (some), P | **yes** (already in public_site) | V |
| 61 | MedTxt-CR full and balanced subset | sociocom.naist.jp/?p=2949 | NAIST | 3,148 OCR'd J-STAGE case reports; 224 annotated | ja | "can be used free of charge if requested"; no licence named; ask | **L, O**, N | yes | V |
| 62 | JMED-LLM | github.com/sociocom/JMED-LLM | NAIST | MRNER (CC BY), CRADE (CC BY), RRTNM (CC BY), SMDIS (CC BY), NRNER (CC BY-NC-SA), JCSTS (CC BY-NC-SA) | ja | per task as listed | N (MRNER positive-only), drug-event | partial | V (README table) |
| 63 | JMedBench | huggingface.co/datasets/Coldog2333/JMedBench | NII | 36 subsets (crade 100, rrtnm 100, igakuqa 11.8k, translated EN sets) | ja | per subset | – | weak | V (card) |
| 64 | JMED-Personas-100k | huggingface.co/datasets/sociocom/JMED-Personas | NAIST | 100,000 synthetic patients; 61 structured fields + 10 narrative fields | ja | **CC BY 4.0**; vendor OK | **E, F, B, P**, medicines (synthetic) | **yes** (narrative as charts, structured fields as truth) | V (one record read) |
| 65 | iCorpus | ai-health.m.u-tokyo.ac.jp/home/research/corpus | Univ. Tokyo | 179 case reports, 102 rare diseases, annotated | ja | research only; vendor needs permission | L, entities | yes | V |
| 66 | J-CaseMap | – | Japanese Society of Internal Medicine | about 20,000 society case reports | ja | members only; not public | L | – | NV |
| 67 | JaMIE corpus | github.com/racerandom/JaMIE | Kyoto / NAIST | annotated RR and CR | ja | "cannot be opened" (paper); models only | – | – | V (paper text via search) |
| 68 | NTCIR-10 MedNLP | research.nii.ac.jp/ntcir/ntcir-10/permission | NII | 50 dummy summaries written by doctors | ja | participant agreement; research | N, D | yes (tiny) | NV |
| 69 | NTCIR-11 MedNLP-2 | research.nii.ac.jp/ntcir/permission/ntcir-11/perm-en-MedNLP.html | NII | 82 EHR texts, disease/time/factuality tags | ja | "usable only for research purposes"; not for a vendor | N, D | yes | V |
| 70 | NTCIR-12 MedNLPDoc | research.nii.ac.jp/ntcir/permission/ntcir-12/perm-en-MedNLPDOC.html | NII | 78 test records, ICD labels | ja | research only | diagnosis | yes | NV (search) |
| 71 | NTCIR-13 MedWeb | (JMED-LLM SMDIS) | NAIST | pseudo-tweets | ja/en/zh | CC BY (via JMED-LLM) | weak | no | V (README) |
| 72 | NTCIR-17 MedNLP-SC RR | sociocom.naist.jp/mednlp-sc/ | NAIST | 243 RR (27 cases × 9 radiologists) with TNM | ja | not stated | C (staging) | yes | V |
| 73 | NTCIR-17 MedNLP-SC SM | sociocom.naist.jp/download/mednlp-sc-sm/ | NAIST | 9,957 made-up tweets × 4 languages | ja/en/de/fr | not stated | weak | no | V |
| 74 | Tsukuba pseudo progress notes | zenodo.org/records/4064153 (+3752281) | Univ. Tsukuba | 9,756 crowd + 83 rated + 19 MD SOAP notes | ja + en | record "CC BY 4.0" vs text "CC BY-NC 4.0": conflict | P, style | yes | V (API, files read) |
| 75 | NursingRecord NER | (JMED-LLM NRNER) | NAIST | simulated nursing records | ja | CC BY-NC-SA | – | – | V (README) |
| 76 | Japanese-Clinical-STS | github.com/sociocom/Japanese-Clinical-STS | NAIST | about 4,000 case-report sentence pairs | ja | CC BY-NC-SA (JMED-LLM table) | – | no | V |
| 77 | MedNormJ | (ANLP 2026) | NAIST | 397 term→standard pairs | ja | "will be public" | – | – | NV |
| 78 | 万病辞書 MANBYO | sociocom.naist.jp/manbyo-dic-en/ | NAIST | 380k disease expressions to ICD | ja | "feel free to use"; for commercial use it points to JMED-DICT mini | synonym lexicon | lexicon | V |
| 79 | JMED-DICT mini | huggingface.co/datasets/sociocom/JMED-DICT_mini | NAIST | medical dictionary | ja | "cc", described as commercially usable | lexicon | lexicon | V (tag, page) |
| 80 | IFMIR | (BRIDGE 6.56) | JQ / NAIST | 58,658 medication incident reports | ja | not read | weak | no | V (BRIDGE desc.) |
| 81 | CT-RATE-JPN | huggingface.co/datasets/YYama0/CT-RATE-JPN | Yamagishi et al. | 22,778 machine-translated chest CT reports (150 revised by radiologists) | ja | CC BY-NC-SA | L (RR) | internal only | NV (search; card) |
| 82 | PMC-Patients-JA-DDx | huggingface.co/datasets/SIP-med-LLM/PMC-Patients-JA-DDx | SIP / NII | about 19.8k dev + 19.8k test machine-translated vignettes | ja (MT) | CC BY-NC-SA, "Research use only" | L | internal only | V (card) |
| 83 | JMedQA | huggingface.co/datasets/SIP-med-LLM/JMedQA | SIP | 3,581 exam items 2018–2026 | ja | "other" | language | weak | V |
| 84 | IgakuQA | github.com/jungokasai/IgakuQA | Kasai et al. | exam items 2018–2022, ja/en | ja | not read | language | weak | NV |
| 85 | JMed48k-Eval | huggingface.co/datasets/JMed48k/JMed48k | anon. (NeurIPS D&B) | 12,484 items, 11 professions | ja | CC BY-NC | – | no | V |
| 86 | KokushiMD-10 / YakugakuQA / NMLE | HF | various | exam items | ja | NC or CC BY-SA | – | no | V (curation list) |
| 87 | jRCT | jrct.mhlw.go.jp/agreement | MHLW | all trials under the Clinical Trials Act, with ja criteria | ja (+en) | **PDL 1.0** ("商用利用も可能", CC BY-compatible); "包括的・網羅的なデータ利用・収集等を行う場合は、必ずヘルプデスクまで利用許可の申請"; no crawling | **C** | criteria | V |
| 88 | UMIN-CTR CSV | umin.ac.jp/ctr/csvdata.html | UMIN | full database, daily CSV (ja and en) | ja | "you cannot redistribute"; "shall not use … for marketing, promotional or commercial purposes"; **not for a vendor without written permission** | C | criteria | V |
| 89 | JP Core IG | packages.fhir.org/jp-core.r4 (1.1.0) | JAMI NeXEHRS | profiles; example files | ja | package.json has **no licence** | P | structure only | V (package) |
| 90 | SS-MIX2 public samples | – | MEDIS / JAHIS | none found | – | – | P | – | searched; not found |
| 91 | MEDIS masters (byomei, HOT, JLAC10) | medis.or.jp | MEDIS-DC | already site-loaded | ja | licensed | P | yes | repo register |

### 3d. Multilingual, cross-cutting, and things looked for but not found

| # | Name | Finding |
|---|---|---|
| 92 | BRIDGE / BRIDGE-Open (huggingface.co/datasets/YLab-Open/BRIDGE-Open) | 87 tasks: 16 Chinese, 5 Japanese (CHIP-CDEE, C-EMRs, cMedQA, DialMed, MIE, EHRQA, CHIP-CDN/CTC/MDCFNPC, MedDG, IMCS-V2; IFMIR, iCorpus, JP-STS…). The HF set is gated ("must be authenticated"). Useful as a **map**, not a new source. V (paper text read) |
| 93 | E3C / MultiCoNER / XL-BEL | E3C covers European languages only (no zh or ja). MultiCoNER is not clinical. NV |
| 94 | Japanese or Chinese translations of MIMIC | none found (MIMIC terms bar redistribution anyway) |
| 95 | Trial-matching labels (patient × trial) in zh or ja | **none exist publicly.** Searched HF ("chictr", "clinical trial chinese", "trial matching"), BRIDGE (CHIP-CTC is criteria classification only), NTCIR and Sociocom lists, and the Japanese LLM data list (stardust-coder/jmed-data-for-llm). The nearest are CHIP-CTC (criteria types) and TFDA/jRCT ↔ ClinicalTrials.gov pairs (criteria text only) |
| 96 | Kaggle zh/ja clinical data | none found (only copies of Chinese dialogue sets); kaggle.com unreachable here |
| – | "JP1553" | No public Japanese set with 1,553 case reports turned up in English or Japanese searches. The real sources of Japanese case-report sets are **J-STAGE/CiNii** open-access reports (MedTxt-CR, iCorpus) and the **J-CaseMap** society database (about 20,000 reports, not public). If a TrialBox file says "JP1553", it most likely comes from one of these. Check its provenance before use. |

---

## 4. Blocked by licence or account: what the owner would need to do

| Set | Block | Owner action |
|---|---|---|
| MedTxt-CR full (3,148) and the 224-report subset | no licence named; J-STAGE terms | Email real-mednlp[at]is.naist.jp: state a vendor's internal validation, no redistribution, and ask whether commercial validation is allowed. **Most valuable single ask for Japanese.** |
| iCorpus | research use only | Ask the University of Tokyo lab for written permission for internal validation, or keep it to a research-partner setting |
| jRCT bulk | permission required for comprehensive collection | Apply to the jRCT helpdesk (state purpose: test set of a few hundred protocols, attribution kept). Individual records can be used under PDL 1.0 now |
| UMIN-CTR | no commercial use, no redistribution | Written permission from UMIN, or use jRCT instead |
| CHIP-CDEE, CHIP-CTC, Yidu-S4K (Tianchi / CBLUE) | data terms only behind a Tianchi account; secondary sources say "apply for authorisation" | Create a Tianchi account, read the agreement, keep a copy. If it says academic only (likely), ask CHIP / Alibaba for permission, or skip it |
| C-EMRs, EHRQA, CDrugRed, MedCD | access route or DUA not public | Write to the authors with a vendor-validation purpose; expect a "research only" answer |
| Taiwan code-mixed summaries (Dai et al.) | not public; resynthesized subset for research | Ask NKUST for the subset. A Taiwanese research partner may be required. **Most valuable single ask for zh-TW realism.** |
| HWDC / NHIRD, Taiwan Biobank | on-site, Taiwanese institutions only; no text | Not worth it for note reading |
| ChiCTR | all rights reserved | Do not use without permission. TFDA and ClinicalTrials.gov cover the need |
| Tsukuba notes | CC BY vs CC BY-NC conflict | Ask the authors which licence holds |
| EMPEC, MMedBench, JMed48k, PMC-Patients(-JA), CT-RATE-JPN, NRNER, JCSTS | non-commercial | Internal research comparisons at most; no product claims |
| BRIDGE-Open | gated on HF | Accept terms with an HF account; mostly a map of sets listed above |

The real gap is not a missing licence. **No public zh-Hant clinical notes exist.** The fix is a partner hospital agreement,
or notes written fresh by Taiwanese clinicians (the audit's rank-1 recommendation, still standing).

---

## 5. Host reachability from this machine (through the configured proxy)

Each host got a harmless request: `curl -sS -o /dev/null -w '%{http_code}'`, under 1 MB.

| Host | Result | Usable? |
|---|---|---|
| huggingface.co | 200 (API and file downloads work; datasets-server works) | yes |
| www.kaggle.com / kaggle.com | 404 on every path, including /datasets | **no** |
| tianchi.aliyun.com | 200 (pages are rendered by JavaScript; downloads need a login) | page only |
| modelscope.cn | 302 → /datasets 200 | yes (not used) |
| opendatalab.com | 200 | yes (not used) |
| sociocom.naist.jp | 200 | yes |
| research.nii.ac.jp | 200 | yes |
| jrct.mhlw.go.jp | 200 | yes (do not crawl) |
| jrct.niph.go.jp (old host) | no answer (000) | no |
| center6.umin.ac.jp | 401 at /, 200 at /cgi-open-bin/ctr/ctr_list.cgi | yes |
| www.chictr.org.cn | 200 | yes |
| twcore.mohw.gov.tw | 301 → /ig/twcore/ 200; package.tgz downloaded | yes |
| jpfhir.jp | 200 | yes |
| www.j-stage.jst.go.jp | **502 from the proxy** (000) | **no** |
| github.com | 400 at / and 403 on other pages: the session proxy allows only the session's repositories; codeload is blocked as well | **no** (use raw.githubusercontent.com, 200, for READMEs) |
| data.gov.tw / data.fda.gov.tw | 200; large exports were sometimes cut off (the second try finished) | yes |
| physionet.org, eutils/ncbi, zenodo.org, figshare.com, packages.fhir.org, clinicaltrials.gov | 200 / 202 | yes |

---

## Suggested first runs (all through the product path)

1. **zh-Hant criteria compile (no clinicians needed):** about 100 TFDA trials matched to NCT IDs. Compile the zh-Hant criteria
   and the ClinicalTrials.gov English criteria with `ir_extract`. The test is whether the two IRs agree, with a human check
   of the differences. Clean up the TFDA quirks first (split the duplicated 納入/排除 blocks, decode the HTML entities).
2. **ja criteria compile:** the same with about 50 jRCT records that carry NCT IDs, fetched one by one (not crawled).
3. **zh long-note site:** 314 CC BY PMC Chinese case reports → OpenCC s2twp → a Taiwanese clinician reviews the terms →
   `public_site`-style charts. Use real TFDA criteria for the same diseases. The gold comes from a clinician per stratum, as in audit rank 1.
4. **ja lost-eligible run:** JMED-Personas narrative fields as charts, criteria on the structured fields, count eligible
   patients lost per stratum (family history, labs in text, medicines).
5. Send the two emails in section 4 (NAIST MedTxt-CR full, NKUST code-mixed subset).
