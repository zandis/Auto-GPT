# Public data for TrialBox validation: English and multilingual (2026-11-14)

Read-only research. Repo tree read: `/home/user/Auto-GPT/.claude/worktrees/latest/trialbox` at `0c8e1211`
(`eval/DATASETS.yaml`, `eval/*/`, `docs/licences/register.csv`, `NOTICE`, `docs/VALIDATION.md`, `tools/public_site.py`,
`tools/open_cohorts_eval.py`) plus audits A and B in the scratchpad. Nothing in the repo was changed. Only small files
(≤ 1 MB: TREC qrels and topic XML) were downloaded, into `scratchpad/pubdata_dl/`, to count labels.

How to read the marks: **[v: url]** = I checked that fact on that page or API myself today. **[nv]** = not verified
(from a search snippet, a paper, or my own knowledge). Licence quotes are copied from the page named.

A word on "may a commercial on-premises vendor use it for validation": none of these licences mention "validation" by
name. I read them as follows, and the owner (or counsel) should confirm the yellow ones:
- **Green**: public domain, CC0, CC BY, CC BY-SA, Apache, MIT, ODbL: internal commercial testing is allowed; keep the
  attribution; do not ship the data unless the licence's redistribution terms are met.
- **Yellow**: no licence stated (NIST TREC files), "educational purposes" (MTSamples), "research purposes only" notes
  on otherwise-open repos (LongHealth): usable for internal testing with a written risk note, or ask the owner.
- **Red**: NC (non-commercial) licences, PhysioNet credentialed ("sole purpose of lawful use in scientific research"),
  n2c2/i2b2, Stanford and Mayo DUAs: a vendor validating a commercial product is not research; needs the owner's own
  agreement or the rights holder's written permission.

---

## 1. Use first (ranked)

Ranked by: most patients and labels, clean licence, and whether it can run through the **product path** (notes
loaded as a site's charts, real protocol criteria compiled through the gateway, cascade S0–S5 with the excerpt
builder, judge + verifier), not a benchmark prompt.

| # | Set | What it proves on the product path | Why first |
|---|---|---|---|
| 1 | **TREC Clinical Trials 2021 + 2022, all qrels** (125 synthetic patients, **9,509 eligible + 9,055 excluded** labelled pairs over 26k–27k trials) | Eligible-loss (N-12) and excluded-caught at pair level, with patient-cluster CIs, through the box: each topic becomes one patient chart; each judged trial's criteria come from ClinicalTrials.gov (API or the NCBI TrialGPT corpus) and are compiled by `ir_extract`/`concept_map`, then screened. | Largest labelled patient–trial set that is openly downloadable. **The repo uses 1,700 of 18,564 labelled pairs (9 %), and only through the mlbench prompt.** Pick ~200 trials that cover many topics so protocol compile cost stays bounded. [v: https://trec.nist.gov/data/trials/qrels2021.txt, qrels2022.txt; counts from the files] |
| 2 | **TREC Clinical Trials 2023, all qrels** (37 judged questionnaire-style patients, **11,667 eligible + 10,699 excluded** over 17,106 trials) | Same as 1 on a looser, structured-questionnaire topic style; good for the deterministic S0/S1 filters (age, sex, history yes/no). | **The repo uses 900 of 22,366 labelled pairs (4 %).** Label noise is higher (audit: 7 of 12 drops were label errors) so report it beside 1, not merged. [v: https://trec.nist.gov/data/trials/qrels2023.txt] |
| 3 | **SIGIR 2016 cohort, full** (58 patients, 3,835 judgements: 421 "highly likely to refer", 681 "would consider", 2,733 "would not refer") plus the **TrialGPT criterion annotations** (1,015 physician-labelled criterion pairs with evidence sentence ids) | Physician criterion labels + evidence ids give the only open **criterion-level gold with the deciding sentence**: score not just the verdict but whether the excerpt builder kept the evidence sentence and whether the judge cited it. | Repo uses all 1,015 criterion pairs and the 413 scoreable "2" pairs, but **not the 681 "1" and 2,733 "0" pairs** and never through the box. Licence note below: the original is **CC BY-SA 4.0 (CSIRO)**, which NOTICE does not credit. [v: https://researchdata.edu.au/a-test-collection-clinical-trials/664508; counts from https://raw.githubusercontent.com/ncbi-nlp/TrialGPT/main/dataset/sigir/qrels/test.tsv] |
| 4 | **Chia** (1,000 Phase IV trials, 12,409 criteria, 41,487 entities, 25,017 relations: Condition, Drug, Measurement with Value, Temporal, Negation, Qualifier, Scope …) | **Criteria-compile gold** for `ir_extract`: criterion boundaries, negated exclusions, value thresholds, temporal windows, scopes ("and/or" groups). Run the compile on the 1,000 trials' CT.gov text and diff entity/relation output against Chia. | Open, CC BY 4.0, verified today: **this settles the `eval/DATASETS.yaml` contradiction** (line 58 says "licence unconfirmed, loader disabled"; line 133 says CC BY 4.0). Repo uses it only for route shares. [v: https://api.figshare.com/v2/articles/11855817 → `"license": "CC BY 4.0"`, files chia_with_scope.zip 2.5 MB, chia_without_scope.zip 2.4 MB] |
| 5 | **TCGA-Reports** (9,523 real pathology reports, 32 cancer types, OCR'd from TCGA PDFs) | Real clinician-written English text with OCR noise at scale; gold = TCGA cancer type (and, joinable from TCGA clinical data, stage/site): criteria like "histologically confirmed adenocarcinoma of the lung" judged against a real report. Also a **density/capacity** set (thousands of real notes). | Only large, real, English clinical-report set with an open commercial-friendly licence. [v: https://data.mendeley.com/datasets/hyg5xkznpx/1 → "CC BY 4.0"] |
| 6 | **BioScope, clinical sub-corpus** (radiology reports annotated for negation and speculation cues and scope) | **Negation and suspected/"r/o" stratum gold** at sentence level: turn each annotated finding into "Patients with X" and check the judge never blocks on a negated or speculative mention. | Licence CC BY 2.0 [v: https://huggingface.co/datasets/bigbio/bioscope card; original site rgai.inf.u-szeged.hu not checked]. 1,954 radiology reports in the clinical part [nv]. |
| 7 | **Synthea** (Apache 2.0 generator) and the **Synthea Coherent Data Set** (CC BY 4.0, FHIR + simple notes + DICOM + genomics), with **IPS and US Core IG example bundles** (CC0) | **English/US data path** (FHIR bundles with DocumentReference notes, US Core profiles) into the lake; capacity at any size. Not accuracy (notes are templates). | Fills the "English site formats" gap in audit B (§4 rank 3). [v: https://raw.githubusercontent.com/synthetichealth/synthea/master/LICENSE (Apache 2.0); Coherent: https://registry.opendata.aws/synthea-coherent-data/ via search snippet, CC BY 4.0 [nv on page]; IPS CC0: build.fhir.org IPS copyrights page via search snippet [nv]] |
| 8 | **ACI-Bench** (207 encounter notes, CC BY 4.0) and **MACCROBAT** (200 PMC case reports with brat annotations, CC BY 4.0) | Small, open, English, note-shaped text on which a clinician can write **stratum gold** cheaply (negation, family history vs patient, past/treated, labs in text). | Clean licences; real-shaped notes. [v: https://raw.githubusercontent.com/wyim/aci-bench/main/README.md "Creative Commons Attribution 4.0 International License (CC BY)"; v: https://api.figshare.com/v2/articles/9764942 → CC BY 4.0, 200 documents] |
| 9 | **LongHealth** (20 fictional patients, 5,090–6,754 words each, 400 questions incl. negation and ordering) | **Long-note stratum**: load each case as a chart of many notes; convert questions to criteria; tests the excerpt builder's clipping and `left_out` path. | Repo LICENSE is Apache 2.0, but the README says "The data is for research purposes only" and asks not to share examples. Treat as yellow. [v: https://raw.githubusercontent.com/kbressem/LongHealth/main/LICENSE and README.md] |

What none of these gives: real long longitudinal charts with criterion gold. The only public set that does,
**MIMIC-IV-Ext-CTRL-2026** (800 criterion pairs on full MIMIC-IV records, heart-failure trials, 2026), is credentialed
and research-only (see §3). There is still **no public real zh-TW clinical text** (searched; see §6).

Suggested first run, all through the box: TREC 2021/22 (#1) at ~3,000 pairs balanced eligible/excluded across all
125 patients, SIGIR full (#3) including the 681 "would consider" pairs reported separately, Chia compile diff (#4) on
100 trials, TCGA 500 reports (#5) with 10 cancer-type criteria, BioScope negation (#6). That is real-text accuracy,
eligible-loss, excluded-caught, compile gold and a negation stratum in one launch, all on green or yellow licences.

---

## 2. Full catalogue

Columns: holds / labels / language / licence and access (quote) / how to get + size / TrialBox use / product-path fit.
Use: ACC = accuracy per stratum, LOSS = eligible-loss and excluded-caught, CMP = criteria compile gold, PATH = data
path (formats in), CAP = capacity/density. Fit: **P** = can run as a site's charts through the gateway and cascade;
**B** = benchmark-shaped only (needs conversion); **–** = not for TrialBox.

### 2.1 Patient–trial matching with labels

| # | Set (owner) | Holds | Labels (how made) | Lang | Licence / access | Get it, size | Use | Fit |
|---|---|---|---|---|---|---|---|---|
| 1 | TREC CT 2021 (NIST) | 75 topics (5–10 sentence synthetic admission notes written by people with medical training), 35,832 judgements over 26,162 trials | 0 not relevant / 1 excluded / 2 eligible, pooled assessor judgements; 6,019 excl., 5,570 elig. | en | No terms stated on the page [v: https://trec.nist.gov/data/trials2021.html; https://www.trec-cds.org/2021.html]. Yellow. | `trec.nist.gov/data/trials/topics2021.xml`, `qrels2021.txt` (676 kB); corpus 5 zips ≈1.7 GB or NCBI `trec_2021_corpus.jsonl` 131 MB | LOSS, ACC | P (topic → one note) |
| 2 | TREC CT 2022 (NIST) | 50 topics, 35,394 judgements over 26,585 trials (same corpus as 2021) | 3,036 excl., 3,939 elig. | en | As 1 [v: https://trec.nist.gov/data/trials/qrels2022.txt] | `qrels2022.txt` 666 kB; NCBI `trec_2022_corpus.jsonl` 132 MB [v: https://ftp.ncbi.nlm.nih.gov/pub/lu/TrialGPT/] | LOSS, ACC | P |
| 3 | TREC CT 2023 (NIST) | 37 judged topics (questionnaire style), 33,870 judgements over 17,106 trials; corpus = 2023-05-08 CT.gov snapshot | 10,699 excl., 11,667 elig. | en | As 1 [v: https://trec.nist.gov/data/trials/qrels2023.txt; https://trec.nist.gov/data/trials2023.html listed] | `topics2023.xml`, `qrels2023.txt` 636 kB | LOSS, S0/S1 filters | P |
| 4 | SIGIR 2016 test collection (Koopman & Zuccon, CSIRO) | 60 topics (TREC CDS 2014/15 case reports), 204,855 trials, ~4,000 judgements | 0/1/2 "would not / would consider / highly likely to refer", assessors | en | "Creative Commons Attribution-ShareAlike 4.0 International Licence"; "All Rights (including copyright) CSIRO, U.S. National Institute of Standards, U.S. National Institutes of Health 2016." [v: https://researchdata.edu.au/a-test-collection-clinical-trials/664508]. Green (attribution + share-alike on adapted data). | DOI 10.4225/08/5714557510C17; NCBI copy: 58 queries, 3,835 qrels [v: raw.githubusercontent.com/ncbi-nlp/TrialGPT/main/dataset/sigir/] | LOSS, ACC | P |
| 5 | TrialGPT-Criterion-Annotations (NCBI/NLM) | 1,015 criterion pairs, 53 SIGIR patients, 103 trials | Physician label + evidence sentence ids; GPT-4 label | en | Public-domain notice (US Gov work) [v: https://huggingface.co/datasets/ncbi/TrialGPT-Criterion-Annotations; LICENSE at raw.githubusercontent.com/ncbi-nlp/TrialGPT/main/LICENSE] | HF `ncbi/TrialGPT-Criterion-Annotations` (1K–10K rows, parquet) | ACC (+ evidence) | P |
| 6 | TrialGPT repo datasets (NCBI) | Per cohort: `queries.jsonl`, `qrels/test.tsv`, `corpus.jsonl`, `retrieved_trials.json` (GPT-4 retrieval), `id2queries.json` (keywords incl. 4 clinicians' for SIGIR) | Qrels as 1–4; GPT keyword outputs | en | Public-domain notice [v: as above] | raw.githubusercontent.com/ncbi-nlp/TrialGPT/main/dataset/… (sigir corpus 16 MB, trec_2021 retrieved 46 MB); `trial_info.json` 1.1 GB on NCBI FTP [v] | LOSS; S2b retrieval recall check | P |
| 7 | **MIMIC-IV-Ext-CTRL-2026** (Nawal et al., U Alberta) | **800 patient–criterion pairs, 50 real MIMIC-IV patients, 3 heart-failure trials** (CONVERGE-HF, COMET, FINALITY-HF); full longitudinal records (discharge notes, radiology, labs, meds) | met / not met / insufficient / not applicable; medical student + resident, adjudicated | en | Zenodo CC BY 4.0 covers **only the description**; data "remains governed by the MIMIC-IV data use agreement … and requires credentialed access via PhysioNet"; until posted, contact the authors [v: https://zenodo.org/api/records/22103011; paper https://aclanthology.org/2026.findings-emnlp.1297/]. Red. | PhysioNet (pending) | ACC on long real charts, LOSS | **P (best fit of any public set)** |
| 8 | n2c2 2018 Track 1 cohort selection (Harvard DBMI) | 288 patients (202 train / 86 test), 2–5 longitudinal notes each (from 2014 i2b2 corpus) | 13 criteria met / not met per patient, annotators | en | DUA via DBMI portal; "Public: False" [v: https://huggingface.co/datasets/bigbio/n2c2_2018_track1]; corporate DUA exists, purpose-limited, no redistribution [nv: n2c2 pages 403 from here]. Red. | portal.dbmi.hms.harvard.edu (owner account) | ACC, LOSS on 13 real criteria | P |
| 9 | TREC Precision Medicine 2017–2019 (NIST) | ~30–50 synthetic oncology topics/yr (disease, gene, demographic), trial qrels | Trial relevance/eligibility judgements | en | No terms stated [nv]; 2019 topics 41 entries [v: https://trec.nist.gov/data/precmed/topics2019.xml downloaded, 6 kB] | trec.nist.gov/data/precmed/ | Biomarker criteria (S0/S1) | B (topics are 3 fields, not notes) |
| 10 | TREC CDS 2016 (NIST) | 30 **real MIMIC-III admission notes** (avg 236 words, with `[** **]` de-id brackets) | Labels are for PMC articles, not trials | en | No terms on NIST page [v: https://trec.nist.gov/data/clinical2016.html]; text derives from credentialed MIMIC-III. Red/ask. | `topics2016.xml` 80 kB [v, downloaded] | Messy-real-note smoke only | P (no gold) |
| 11 | a published trial-matching model eval set (Nievas et al., JAMIA 2024) | SIGIR + TREC pairs with GPT-4/expert labels | — | en | Paper says released "for public use"; **no URL found** [v: https://arxiv.org/abs/2312.09958] | not located | — | — |
| 12 | PRISM (2024, Massive Bio) | Real-EHR matching study | — | en | No public data found [nv] | — | — | — |
| 13 | TRIALSCOPE (Microsoft) | Real-world evidence platform | — | en | No public data found (searched) | — | — | — |
| 14 | Real-world multimodal EHR matching (arXiv 2503.15374) | 7,021 patient–criterion pairs, 485 patients, 36 trials, 30 sites | criterion reviews | en | No release found [nv] | — | — | — |
| 15 | Trial2Vec (Wang et al.) | Trial embeddings + CT.gov-derived trial pairs | similarity | en | Code MIT [v: raw.githubusercontent.com/RyanWangZf/Trial2Vec/main/LICENSE] | GitHub | S2b sanity only | B |
| 16 | CTBench (RPI) | CT-Repo 1,690 trials, CT-Pub 100 trials: baseline features | from CT.gov and papers | en | CC0 [v: raw.githubusercontent.com/nafis-neehal/CTBench_LLM/main/LICENSE] | GitHub | – (trial design, not matching) | – |
| 17 | ClinicalTrials.gov API v2 / records | All registered trials incl. eligibility text | — | en | CT.gov terms (already in register row `ctgov-public-protocols`) [v: https://clinicaltrials.gov/api/v2/version reachable] | API | CMP input; protocols for 1–4 | P |
| 18 | AACT (CTTI) | Daily relational snapshot of CT.gov, 40+ tables | — | en | "Data derived from ClinicalTrials.gov"; account needed for snapshots [v: https://aact.ctti-clinicaltrials.org/] | free account; ~GB Postgres dump [nv] | CMP at scale; trial sampling | P (protocol import) |

### 2.2 Criteria parsing (compile gold)

| # | Set | Holds | Labels | Lang | Licence | Get, size | Use | Fit |
|---|---|---|---|---|---|---|---|---|
| 19 | **Chia** (Kury et al. 2020) | 1,000 Phase IV trials, 12,409 criteria, 41,487 entities (15 types), 25,017 relations (12 types) | Human brat annotations | en | CC BY 4.0 [v: api.figshare.com/v2/articles/11855817]; HF `bigbio/chia` cc-by-4.0 [v] | figshare 2.5 MB zip | CMP | P |
| 20 | Leaf Clinical Trials (LCT) corpus (UW, 2022) | 1,000+ trials, fine-grained entities/relations (extends EliIE, Chia) | Human brat | en | Not verified (paper Sci Data 10.1038/s41597-022-01521-0) [nv] | GitHub per paper [nv] | CMP (richer logic) | P |
| 21 | FB Clinical Trial Parser data (Meta) | 121,221 entities/attributes/limits from 3,314 trials | Human labelled words | en | Code Apache 2.0 [v: raw.githubusercontent.com/facebookresearch/Clinical-Trial-Parser/master/README.md "Apache 2.0 licensed"]; data licence not separately stated [nv] | GitHub | CMP (numeric limits) | P |
| 22 | EliIE (Columbia) | 230 Alzheimer's trials, 8,008 entities, OMOP-oriented | Human | en | "Available upon request" in one source [nv] | Tian312/EliIE [nv] | CMP (AD slice!) | P |
| 23 | Criteria2Query (Columbia) | Tool, small eval sets | — | en | Not verified [nv] | GitHub [nv] | – | – |
| 24 | Cancer eligibility statements (Bustos & Pertusa; Kaggle `auriml/eligibilityforcancerclinicaltrials`) | 6,186,572 short statements from 49,201 cancer trials, label = inclusion/exclusion | automatic (from section) | en | Kaggle licence not readable here [nv]; data = CT.gov text | Kaggle (account) | Weak CMP (incl/excl split) | B |
| 25 | CT-EBM-SP | Spanish trial abstracts/announcements, entities | Human | es | cc-by-nc-4.0 [v: HF API `bigbio/ctebmsp`]. Red. | HF | – | – |
| 26 | CHIP-CTC (CBLUE) | ~23k/7.5k/10k criteria sentences from ChiCTR, 44 classes | Human | zh-Hans | Repo Apache-2.0; data licence not stated [nv] | Tianchi (account) | CMP class split, zh only as a proxy (Simplified, mainland) | B |
| 27 | CT-RATE | Chest CT volumes + reports | — | en | cc-by-nc-sa-4.0, gated [v: HF API `ibrahimhamamci/CT-RATE`] | HF | – (imaging) | – |

### 2.3 Patient case text at scale (open or semi-open)

| # | Set | Holds | Labels | Lang | Licence / access | Get, size | Use | Fit |
|---|---|---|---|---|---|---|---|---|
| 28 | PMC-Patients v1 (Tsinghua) | 167k patient summaries from PMC case reports; age, sex, text | patient–article and patient–patient relevance (3.1M / 293k) | en | **cc-by-nc-sa-4.0** [v: https://huggingface.co/datasets/zhengyun21/PMC-Patients]. Red for vendor use. | HF `zhengyun21/PMC-Patients`, 1.38 GB [v] | would be CAP + ACC | P |
| 29 | PMC-Patients-V2 | 250,294 patients (2024 PMC baseline) | as above | en | cc-by-nc-sa-4.0 [v: HF API `THUMedInfo/PMC-Patients`] | HF | — | P |
| 30 | PMC-Patients-ReCDS | retrieval benchmark on 28 | relevance | en | cc-by-nc-sa-4.0 [v: HF API] | HF | — | B |
| 31 | MTSamples (mtsamples.com) | 5,043 transcribed sample reports, 40 specialties (108 discharge summaries, 520 H&P, 167 SOAP/progress …) | specialty only | en | "You may print, share, or link to these sample reports for educational purposes." [v: https://mtsamples.com/]. Yellow (no commercial grant). | site; ~17 MB CSV via copies [nv] | ACC with new gold; varied note types | P |
| 32 | Kaggle `tboyle10/medicaltranscriptions` | ~4,999 rows | specialty | en | Uploader tags CC0 [nv; Kaggle page JS-only]. **True origin: MTSamples scrape** — the uploader cannot relicense MTSamples' text; treat as #31 | Kaggle | as 31 | P |
| 33 | HF MTSamples copies (`harishnair04/mtsamples` "apache-2.0", `argilla/medical-domain`, `NickyNicky/medical_mtsamples` …) | MTSamples copies | — | en | Uploader-chosen tags [v: HF API]; origin MTSamples → treat as #31 | HF | as 31 | P |
| 34 | AGBonnet/augmented-clinical-notes | 30,000 PMC-Patients notes + synthetic dialogues (NoteChat) + GPT-4 summaries | GPT-4 summaries (not gold) | en | Card says MIT [v: HF], but the notes are PMC-Patients (CC BY-NC-SA) → **MIT tag is not credible for the note text** | HF, 374 MB | — | P |
| 35 | Asclepius synthetic notes | 158,114 GPT-3.5 discharge summaries from PMC-Patients, with QA | GPT-3.5 | en | "CC-BY-NC-SA 4.0" [v: HF card] | HF, 402 MB | — | P |
| 36 | **TCGA-Reports** (Columbia) | 9,523 real pathology reports, 32 cancer types, OCR + cleaning | cancer type (TCGA) | en | "CC BY 4.0" [v: https://data.mendeley.com/datasets/hyg5xkznpx/1] | Mendeley DOI 10.17632/hyg5xkznpx.1 | ACC (dx/histology criteria), CAP | P |
| 37 | **ACI-Bench** (Microsoft/UW) | 207 doctor–patient conversations + clinical notes | note = reference | en | CC BY 4.0 [v: raw…/wyim/aci-bench/main/README.md] | figshare `aci-bench-corpus_zip` | ACC with new gold | P |
| 38 | MTS-Dialog (Ben Abacha) | 1,700 dialogue/section-summary pairs [nv] | summaries | en | CC BY 4.0 [v: raw…/abachaa/MTS-Dialog/main/LICENSE.txt] | GitHub | weak | B |
| 39 | **MACCROBAT** (Caufield) | 200 PMC case reports, brat events/entities | human | en | CC BY 4.0 [v: api.figshare.com/v2/articles/9764942]; 1.06 MB zip | figshare; Kaggle copy `okolojeremiah/maccrobat` (same data) | ACC (temporal events, negation attributes [nv]) | P |
| 40 | **LongHealth** (TU Dresden/Charité) | 20 fictional patients, 5,090–6,754 words each, 400 MCQ | author-written | en | Repo Apache 2.0, README: "for research purposes only" [v: raw…/kbressem/LongHealth/main/] | GitHub | ACC long-note, negation, ordering | P |
| 41 | E3C (FBK) | Clinical cases in en/it/es/eu/fr, clinical entity + **temporal** layers | human | multi | CC BY 4.0 per 2025 paper [nv]; e3c.fbk.eu does not state it [v: https://e3c.fbk.eu/data]; ELG catalogue 7618 | ELG; HF `NLP-FBK/*` | ACC temporality stratum (en part) | P |
| 42 | CAS (French clinical cases) | 4,900 cases, 1.7M words | — | fr | "Data User Agreement" [nv; HF `bigbio/cas` licence "other" v] | authors | – | – |
| 43 | BioScope | biomedical + **clinical radiology** sub-corpus, negation/speculation cues and scopes | human | en | cc-by-2.0 [v: HF `bigbio/bioscope`] | rgai.inf.u-szeged.hu | ACC negation / suspected | P (sentence → note) |
| 44 | Open-i Indiana chest X-ray | 3,955–3,996 reports + images | MeSH findings | en | CC BY-NC-ND 4.0 per mirrors [nv]; openi.nlm.nih.gov reachable | Open-i API | – (NC) | P |
| 45 | CheXpert Plus (Stanford AIMI) | 187,711 reports, 64,725 patients | — | en | Stanford research-use agreement, non-commercial [nv] | AIMI | – | – |
| 46 | MedAlign (Stanford) | 276 longitudinal EHRs, 983 clinician instructions | clinician answers (303) | en | "research data use agreement" [nv]; code MIT [v] | medalign.stanford.edu | would be long-chart ACC | P |
| 47 | EHRSHOT (Stanford) | 6,739 patients structured | tasks | en | Stanford DUA [nv] | — | – | – |
| 48 | NBME patient notes (Kaggle competition) | 43,985 USMLE Step 2 CS patient notes, 10 cases, feature spans | rubric features | en | Data via NBME data-sharing application "for academic research" [nv]; HF copy `bhatthars/nbme_patient_notes` tagged MIT is a re-upload [v: HF API] | NBME portal | ACC history/negation phrasing | P |
| 49 | Kaggle `akashadesai/clinical-notes`, `bpkapkar/health-prescription-data`, `cognizantergroup/mimic-clinical-summarization` | discharge summaries with `[** **]` dates | — | en | **True origin: MIMIC-III/IV redistributions** (de-id bracket format in previews) [nv]; violates PhysioNet DUA. Do not use. | — | – | – |
| 50 | HF MIMIC re-uploads (`hiimivantang/mimic-iv-notes`, `mimic-capstone/*`, `dischargesum/*`) | MIMIC notes | — | en | Not licensed for redistribution. Do not use. [v: listed by HF API] | — | – | – |
| 51 | Kaggle `muhammadimran112233/clinical-documents-on-syndromes-disease` | ~100 docs per category | — | en | not verified | — | – | – |
| 52 | Kaggle `nudratabbas/clinical-trials-ir-and-extraction-benchmark` | ~4,000 **synthetic, templated** patient–trial scenarios, eligible / not / insufficient | generated | en | not verified (JS page) | Kaggle | at most a smoke test | B |
| 53 | Kaggle `harrachimustapha/clinical-trial-eligibility-criteria-dataset`, `kagglegrandmaster99/clinical-trial-dataset`, `danielansted/clinicaltrials-gov-clinical-trials-dataset` | CT.gov eligibility text re-packaged | none | en | Origin CT.gov; use the API instead | — | – | – |
| 54 | Kaggle `sergionefedov/patient-records-100k-patients-15-conditions`, `olagokeblissman/eko-hospital-patient-care-dataset` | synthetic/structured tables | — | en | not verified; no notes | — | CAP at most | – |
| 55 | NHSEDataScience/synthetic_clinical_notes, rtemis/synthetic-clinical-notes, serag-ai/Synthetic-EHR-* | LLM-generated notes | — | en | MIT / CC0 / none [v: HF API tags] | HF | Injection/stress fodder, not gold | P |

### 2.4 Credentialed or DUA clinical corpora (strata gold exists here, but blocked)

| # | Set | Holds | Labels relevant to strata | Licence / access | Use if unblocked |
|---|---|---|---|---|---|
| 56 | MIMIC-IV-Note 2.2 | 331,794 discharge summaries (145,915 patients), 2,321,355 radiology reports | none | PhysioNet Credentialed Health Data License 1.5.0; clause 6: "use the data for the sole purpose of lawful use in scientific research and no other"; clause 3: "will not share access … with anyone else" [v: https://physionet.org/content/mimic-iv-note/2.2/ and view-license] | long real charts, CAP |
| 57 | MIMIC-IV 3.1 / MIMIC-IV on FHIR 2.1 | full structured EHR / FHIR | — | Credentialed [v: physionet.org/content/mimiciv/3.1, mimic-iv-fhir/2.1] | PATH at scale |
| 58 | MIMIC-III 1.4 | notes incl. physician/nursing | — | Credentialed [v] | — |
| 59 | MIMIC-CXR 2.1.0 | 227k radiology reports | — | Credentialed [v] | — |
| 60 | MedNLI | clinician NLI pairs from MIMIC | entail/contradict (negation-heavy) | Credentialed [v: physionet.org/content/mednli/1.0.0] | ACC negation |
| 61 | DiSCQ | clinician questions on discharge summaries | — | Credentialed [v] | — |
| 62 | ShARe/CLEF eHealth 2013 | MIMIC-II notes, disorders with negation/uncertainty attributes | assertion attributes | Credentialed [v: physionet.org/content/shareclefehealth2013/1.0] | ACC negation/uncertainty |
| 63 | CORAL (UCSF oncology) | expert-curated oncology progress notes | entities | Credentialed [v: physionet.org/content/curated-oncology-reports/1.0] | oncology ACC |
| 64 | MedDec, RadGraph, MIMIC-IV-Ext-CDM, Asclepius-R, MIMIC-IV-Ext-DiReCT | MIMIC derivatives | various | Credentialed or Restricted DUA [v: PhysioNet pages] | — |
| 65 | eICU-CRD 2.0 (full) | 200k ICU stays | — | Credentialed [v] | CAP |
| 66 | i2b2 2010 relations/assertions | ~871 discharge summaries [nv] | **assertion: present/absent/possible/conditional/hypothetical/not-patient** | n2c2 DUA [nv] | ACC negation, family-history ("not patient"), hypothetical |
| 67 | i2b2 2012 temporal | 310 discharge summaries [nv] | events, TIMEX3, TLINKs | n2c2 DUA [nv] | ACC temporality |
| 68 | i2b2 2009 medication; n2c2 2018 Track 2 ADE | meds, doses, ADE in MIMIC-III notes | med attributes | n2c2 DUA [nv; HF `bigbio/n2c2_2009`, `n2c2_2018_track2` licence "other" v] | drug criteria |
| 69 | n2c2/OHNLP 2019 family history | synthetic narratives from Mayo FH sections | family member, side, living status, observation | n2c2 DUA [nv; overview https://pmc.ncbi.nlm.nih.gov/articles/PMC7875692] | family-history stratum |
| 70 | i2b2 2014 de-id + heart-disease risk factors | 1,304 longitudinal notes [nv] | PHI; risk-factor time attributes (before/during/after DCT) | n2c2 DUA [nv] | PHI masker, temporality |
| 71 | i2b2 2006 smoking, 2008 obesity | discharge summaries | smoking status; 16 comorbidities present/absent/questionable | n2c2 DUA [nv] | assertion |
| 72 | n2c2 2022 SDOH | MIMIC social history | SDOH status/temporal | n2c2/PhysioNet [nv] | – |
| 73 | THYME (Mayo) | ~600 colon-cancer clinical + pathology notes | TimeML events, times, TLINKs | DUA with Mayo Clinic [nv: https://github.com/stylerw/thymedata] | temporality |
| 74 | emrQA | 400k+ QA pairs generated from i2b2 corpora | — | n2c2 licence [nv: github.com/panushri25/emrQA] | – |

### 2.5 Structured public EHR for data paths

| # | Set | Holds | Licence | Get | Use | Fit |
|---|---|---|---|---|---|---|
| 75 | MIMIC-IV Demo 2.2 | 100 patients, hosp + icu, **no notes** | ODbL 1.0, "Anyone can access the files" [v: https://physionet.org/content/mimic-iv-demo/2.2/] | 15.4 MB zip | PATH (CSV) | P |
| 76 | MIMIC-IV Demo on FHIR 2.1.0 (**in repo**) | 100 patients, 25+ Mimic* profiles, **no DocumentReference** | ODbL 1.0 [v: https://physionet.org/content/mimic-iv-fhir-demo/2.1.0/] | 49.5 MB | PATH | P |
| 77 | MIMIC-IV-ED demo 2.2, MIMIC-IV-ECG demo | ED stays; ECGs | ODbL 1.0 [v: PhysioNet pages, 111.8 KB / 76.1 MB] | PhysioNet | PATH (ED visit classes) | P |
| 78 | eICU-CRD demo 2.0.1 | 2,500+ unit stays, 20 hospitals; `note.csv.gz` 260 kB (structured note fragments, not free text [nv]) | ODbL 1.0 [v: https://physionet.org/content/eicu-crd-demo/2.0.1/] | 130 MB | PATH (second US schema) | P |
| 79 | Synthea (MITRE) | any size, FHIR R4/STU3, C-CDA, CSV; templated notes | Apache 2.0 [v: raw…/synthea/master/LICENSE] | generator (Java) | PATH, CAP | P |
| 80 | Synthea Coherent Data Set | FHIR + "simple clinical notes" + DICOM + genomics + ECG (CVD focus) | CC BY 4.0 [nv; AWS registry snippet] | AWS open data | PATH with notes | P |
| 81 | Synthea sample downloads (synthea.mitre.org) | 1k/100k sample FHIR/CSV | Apache 2.0 [nv] | **site has an expired TLS certificate and returned 503 today** | PATH | P |
| 82 | OHDSI Eunomia / EunomiaDatasets (GiBleed, Synthea-based OMOP) | ~2,700 synthetic persons in OMOP | Apache 2.0 [v: raw…/OHDSI/EunomiaDatasets/main/LICENSE] | GitHub / R package | OMOP parity | P |
| 83 | CMS DE-SynPUF (OMOP) | 2.3M synthetic Medicare beneficiaries, 1k/100k subsets | "in the public domain" per AWS registry [nv] | s3://synpuf-omop (no-sign-request) | CAP (OMOP at scale) | P |
| 84 | HL7 IPS IG examples | example IPS bundles | CC0 for IG content; terminologies separate [nv] | hl7.org/fhir/uv/ips/examples.html (reachable) | PATH (international summary) | P |
| 85 | HL7 US Core examples | example resources per profile | HL7 IG licence (CC0) [nv] | hl7.org/fhir/us/core (reachable, 206) | PATH (US Core profiles) | P |

### 2.6 Prompt injection, calibration

| # | Set | Holds | Licence | Use | Fit |
|---|---|---|---|---|---|
| 86 | MPIB (Medical Prompt Injection Benchmark, EMNLP Findings 2026) | 9,697 items from MedQA/PubMedQA: 2,734 benign, 5,737 direct, 644 embedded-instruction, 582 poisoned-context (RAG) | cc-by-nc-4.0, auto-gated; gate checkbox "I will use MPIB only for non-commercial research or evaluation" [v: https://huggingface.co/datasets/jhlee0619/mpib README] | Red. Pattern source only; injection inside **notes** is not covered | B |
| 87 | Calibration gold | — | **Nothing public found** for calibrated eligibility confidence on notes. Calibration must be measured on 1–5 (pair-level) and on clinician strata gold. | — | — |

---

## 3. Blocked by licence or account: what the owner would do

| Block | Sets | What it takes | Can the vendor then use it for product validation? |
|---|---|---|---|
| PhysioNet credentialed | MIMIC-IV-Note, MIMIC-IV, MIMIC-IV on FHIR, **MIMIC-IV-Ext-CTRL-2026**, MedNLI, ShARe/CLEF, CORAL, DiSCQ, MIMIC-CXR, eICU full | Owner's own PhysioNet account → credentialing (identity + reference) → CITI "Data or Specimens Only Research" training → sign the DUA per project [v: mimic-iv-note page]. Takes days to weeks. | Doubtful: licence clause 6 "sole purpose of lawful use in scientific research and no other" and clause 3 no sharing [v]. PhysioNet's 2025 note allows local LLMs and forbids sending data to third-party APIs [nv: https://physionet.org/news/post/llm-responsible-use/]. TrialBox runs locally, which fits; "research" vs product validation is the open question. Reasonable path: run as a **published research evaluation** by a credentialed person, keep data off any vendor image, report only aggregate numbers. Ask PhysioNet in writing first. |
| n2c2 / i2b2 (Harvard DBMI) | 2018 T1 cohort selection, 2010 assertions, 2012 temporal, 2009/2018 meds, 2019 family history, 2014 de-id/risk factors, emrQA | Owner's account on portal.dbmi.hms.harvard.edu, sign the **corporate** DUA (a corporate form exists) [nv: search snippets; pages return 403 here]. | Only if the corporate DUA's "Specific Purpose" covers it; no redistribution. **These hold exactly the strata gold TrialBox lacks** (negation/assertion, family history, temporality, 13 real trial criteria), so this is the highest-value application. |
| Mayo Clinic DUA | THYME | THYME wiki process | as above |
| Stanford research DUAs | MedAlign, EHRSHOT, CheXpert Plus | Stanford AIMI / medalign site | Non-commercial; ask Stanford for a commercial route ("separate route for commercial use" [nv]) |
| NC licences | PMC-Patients (v1, V2, ReCDS), Asclepius, CT-RATE, MPIB, CT-EBM-SP, Open-i (per mirrors) | Written permission from rights holders | Not without permission. For PMC-Patients the underlying case reports are PMC open-access articles under mixed licences; a **self-built** set from the PMC Open Access **commercial-use subset** (CC BY / CC0 case reports) is the clean substitute [nv; not built]. |
| Kaggle | all Kaggle items | Owner's Kaggle account + API token; network allowlist for `www.kaggle.com` (and its download storage) | Most Kaggle "clinical notes" are copies of MTSamples or MIMIC (see #32, #49). Nothing unique found that justifies the account, except NBME (needs NBME's application anyway). |
| Not released | a published trial-matching model eval set, PRISM, TRIALSCOPE, real-world 7,021-pair study | Ask authors | — |

---

## 4. Already in the repo, and under-used

| In repo | Used | Available | Gap |
|---|---|---|---|
| TREC CT 2021/22 (`eval/trec_ct`) | 1,700 pairs (1,200 eligible, 500 excluded), 125 patients, mlbench prompt, not the box | **18,564** labelled pairs (9,509 eligible, 9,055 excluded) [v: qrels files] | 9 % used; never through gateway/cascade; excluded side thin |
| TREC CT 2023 (`eval/open_cohorts`) | 900 pairs (600/300), 37 patients | **22,366** labelled (11,667/10,699) | 4 % used |
| SIGIR full (`eval/open_cohorts`) | 413 "highly likely" pairs, 53 patients | 3,835 judgements, 58 patients (421 / 681 / 2,733) | "would consider" (681) and the 2,733 negatives unused; no excluded-caught measure on SIGIR |
| TrialGPT criterion set (`eval/criterion_ml`) | all 1,015, recorded answers and mlbench | evidence sentence ids per pair | evidence ids not scored against the excerpt builder; never run through the box |
| Chia (`eval/chia`) | route shares only | entities, relations, negation, temporal, value | **licence now verified CC BY 4.0** → fix `eval/DATASETS.yaml` line 58 and enable `criteria_extract_public`; use as compile gold |
| MIMIC-IV FHIR demo | data path, stub model | — | fine as PATH; no notes, so not a model set (audit B agrees) |
| Synthea | cohort counts only | FHIR + notes + any size | no English FHIR site path built on it |
| TrialGPT NCBI corpus | trial texts for TREC | `retrieved_trials.json` (GPT-4 retrieval per patient) | not used to check S2b semantic recall |

Licence housekeeping found while checking:
- **SIGIR 2016**: the original collection is "Creative Commons Attribution-ShareAlike 4.0 International Licence", "All
  Rights (including copyright) CSIRO, U.S. National Institute of Standards, U.S. National Institutes of Health 2016"
  [v: researchdata.edu.au/…/664508]. `NOTICE` and `eval/DATASETS.yaml` credit only the NCBI public-domain notice. The
  53 notes in `eval/criterion_ml/notes_en.json` (and their ja/zh-TW/mixed translations, which are adaptations under
  share-alike) should also carry the CSIRO CC BY-SA 4.0 attribution. Not a blocker; a NOTICE line.
- **TREC**: NIST pages state no terms [v]. Keep as is; note "no licence stated" in the register.

---

## 5. Host reachability from this machine (2026-11-14, through the configured proxy)

Tested with `curl -sS -o /dev/null -w '%{http_code}'` (HEAD, then a ≤1 kB ranged GET where HEAD failed).

| Host | Result | Meaning / what is needed |
|---|---|---|
| huggingface.co (+ API, `resolve/` with redirect) | 200 / 307→206 | **Open.** Public datasets download. Gated sets (MPIB, CT-RATE) need the owner's HF token. `cdn-lfs.huggingface.co` directly: CONNECT 502 (blocked), but `resolve` downloads worked via redirect. |
| datasets-server.huggingface.co | 200 | open |
| www.kaggle.com (site and `/api/v1/…`) | **404 with empty body** to curl; page JS-only to the fetch tool | Kaggle refuses non-browser clients; the API needs the owner's Kaggle token. A browser-UA retry was refused by this session's permission check, so not tested further. Needs owner account + allowlist. |
| physionet.org | 200 (open project files 206) | Open sets download; credentialed sets need the owner's login. |
| github.com / api.github.com | 400 / **403** ("GitHub access to this repository is not enabled for this session") | Session policy: only attached repos. Needs `add_repo` or an allowlist change for browsing. |
| raw.githubusercontent.com | 200 | **Open**: all repo files used here came through it. |
| codeload.github.com | 403 | zip downloads blocked; use raw files |
| zenodo.org (+ API) | 200 | open |
| ftp.ncbi.nlm.nih.gov | 200 | open (TrialGPT corpora) |
| clinicaltrials.gov (+ API v2) | 200 | open |
| trec.nist.gov, www.trec-cds.org | 200 | open (qrels, topics downloaded) |
| figshare.com | 202 (bot challenge) | use **api.figshare.com** (200) and its download links |
| data.mendeley.com | 200 | page open (public-api path 404) |
| aact.ctti-clinicaltrials.org | 302 | redirects to login; snapshots need a free account |
| n2c2.dbmi.hms.harvard.edu | **403** | blocked here; owner's browser and account |
| portal.dbmi.hms.harvard.edu | **TLS error: certificate has expired** | server-side; owner's browser |
| synthea.mitre.org | **TLS error: certificate expired**; fetch tool 503 | use GitHub releases or AWS open data |
| synthetichealth.github.io | 206 | open |
| openi.nlm.nih.gov (+ API) | 200 | open |
| hl7.org, build.fhir.org | 206 | open |
| eutils.ncbi.nlm.nih.gov, www.ncbi.nlm.nih.gov | 200 | open (PMC OA subset possible) |
| storage.googleapis.com, s3.amazonaws.com (root) | 400 / 405 | roots only; specific public buckets not tested |
| www.mtsamples.com | 200 | open |

Summary: everything in §1 is downloadable from here **without any account** (NIST, NCBI FTP, raw GitHub, HF, figshare API,
Mendeley, PhysioNet open files). Owner action is only needed for PhysioNet credentialed, n2c2, Kaggle, and gated HF sets.

---

## 6. Searched for and found nothing (or nothing usable)

- **Public criterion-level clinician labels for TREC CT 2021/22/23**: none released; TrialGPT's criterion labels are
  SIGIR only.
- **a published trial-matching model's released eval set**: paper says released; no URL anywhere (arXiv, search).
- **TRIALSCOPE, PRISM data**: not public.
- **A 2024–2026 open benchmark with real EHR + criterion gold under an open licence**: only MIMIC-IV-Ext-CTRL-2026,
  which is credentialed.
- **Prompt injection planted inside clinical notes**: no dataset; MPIB is question/RAG-based and NC. TrialBox's own
  `eval/injection` remains the only note-level set.
- **Calibration gold for eligibility confidence**: none.
- **Real Traditional Chinese (Taiwan) clinical notes**: none public (searched HF, general web); only Simplified
  mainland sets (CHIP-CTC, CBLUE, TCM records) and general zh-TW text corpora.
- **MIMIC-IV-Note demo** (an open notes subset): does not exist; the open demos carry no free text.
- **Kaggle clinical-notes sets with an original source**: every one checked was MTSamples, MIMIC, Synthea, CT.gov or
  synthetic/templated; the NBME notes are the only original corpus and need NBME's application.
- **NegEx original annotated test set on GitHub**: paths 404 (chapmanbe/negex, mongoose54/negex); not located.

Search terms used (web and HF API): TrialGPT datasets/HF/FTP; SIGIR 2016 Koopman collection; TREC CT 2021–2023
qrels; TREC PM 2017–2019; TREC CDS 2014–2016; n2c2 2018 track 1 and n2c2 DUA; MIMIC-CTRL; a published trial-matching model; PRISM;
TRIALSCOPE; real-world EHR matching 2025; CTBench; Chia figshare; LCT corpus; Clinical-Trial-Parser; EliIE;
Criteria2Query; cancer eligibility 6M; CHIP-CTC; CT-EBM-SP; CT-RATE; PMC-Patients; Asclepius; augmented clinical
notes; MTSamples (site, Kaggle, HF); ACI-Bench; MTS-Dialog; MACCROBAT; TCGA-Reports; LongHealth; E3C; CAS; BioScope;
Open-i; CheXpert Plus; MedAlign; EHRSHOT; NBME patient notes; THYME; emrQA; i2b2 2006–2014; n2c2 2019 family
history; PhysioNet (MIMIC-IV-Note, MIMIC-IV, FHIR, MedNLI, DiSCQ, ShARe/CLEF, CORAL, MedDec, RadGraph, CDM, DiReCT,
Asclepius-R, eICU, demos) and PhysioNet LLM policy; Synthea, Coherent, Eunomia, DE-SynPUF, IPS, US Core;
medical prompt injection (MPIB); BRIDGE multilingual; Taiwan clinical text; HF keyword searches (clinical-notes,
discharge, synthetic-ehr, eligibility, n2c2, mimic-iv-note, mtsamples, nbme, longhealth, e3c, aci-bench, chip-ctc);
Kaggle site searches (clinical notes, trial eligibility, EHR).

Candidates examined: 87 rows above (some rows group 2–5 copies), about 100 sets in all.
