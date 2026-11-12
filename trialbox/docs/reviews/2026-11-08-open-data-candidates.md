# TrialBox: more open data for end-to-end validation (survey 2026-11-08)

## Scope

This survey lists open and public datasets that TrialBox does not yet use. It skips the sets TrialBox already uses (see
`docs/OPEN_DATA.md`, `eval/DATASETS.yaml`, `docs/reviews/2026-11-05-public-data-validation.md`):
- SIGIR 2016 and the TrialGPT data (`criterion_ml`, `trialgpt_compare`, `match_registry`);
- TREC CT 2021, 2022 and 2023 topics and qrels (`trec_ct`, `open_cohorts`, `ad`);
- MedTxt-CR/RR from NTCIR-16 (`medtxt`, `public_site`);
- the MIMIC-IV FHIR demo, Synthea (US) and Chia;
- ClinicalTrials.gov API records.

The 2026-11-05 review already lists n2c2 2018, ADNI/J-ADNI, MIMIC-IV notes and CHIP-CTC as not used. They appear below
only where something new was found.

**Verification column.** ✓ means the link was opened on 2026-11-08 and the licence was read at the source. Where a
check went further, the cell says so, for example a file downloaded and parsed. ~ means the link works but the licence
or a detail comes from a secondary page (a dataset card, a paper or a search snippet). ✗ means the item could not be
verified (dead link, gated page or no licence statement); verify it before use. GitHub web pages are blocked from this
sandbox, so the GitHub licences were read through `raw.githubusercontent.com` or the CRAN page.

**Access codes.**
- **Open**: free download, commercial testing allowed with attribution.
- **Reg**: free account or registration needed.
- **NC**: not for commercial use.
- **DUA**: signed data-use agreement.
- **ND**: no derivatives may be redistributed.

TrialBox is a commercial product, so an NC licence means internal evaluation only, and possibly not even that. Legal
must decide.

---

## Stage 1. Import (EMR CSV, SS-MIX2, FHIR R4 with JP Core / TW Core)

| Name & URL | Owner | Licence / access | Size, language | Check it enables | Effort | Verif. |
|---|---|---|---|---|---|---|
| **TW Core IG 1.0.0 package** — https://packages.fhir.org/tw.gov.mohw.twcore/1.0.0 (also `https://twcore.mohw.gov.tw/ig/twcore/examples.json.zip`) | MOHW Taiwan | **CC0-1.0** (package.json), Open | 2.8 MB tgz; **98 example instances**: 27 Observation, 5 Bundle, 4 each MedicationDispense / MedicationStatement / AllergyIntolerance / Specimen, 3 Patient, 2 DocumentReference, 2 Composition, …; zh-TW + en | Ingest every TW Core example through the `fhir_bulk` adapter, with **0 validation errors expected**. Today the only FHIR fixture is MIMIC, which is not TW Core, so the error-rate gate is never really tested. Also exercises the NHI code systems in the IG's ValueSets. | S | ✓ (downloaded and parsed) |
| **TW EMR exchange IG 0.2.0** (`tw.gov.mohw.emr`) — https://packages.fhir.org/tw.gov.mohw.emr/0.2.0 | MOHW Taiwan | **CC0-1.0**, Open | 2.6 MB; 6 document Bundles: **出院病摘 discharge summary (24 entries)**, 門診病歷 outpatient record, 檢驗檢查 lab report, 電子處方箋 e-prescription, 調劑單張 dispensing slip, image bundle; NTUH-styled zh-TW narrative | Document-Bundle ingest (Composition → DocumentReference/notes). These are the only open zh-TW clinical *document* instances found, so they make a smoke test for zh-TW note extraction into the judge path. | S | ✓ (downloaded and parsed) |
| **TW NHI PAS IG 1.3.0** (`tw.gov.mohw.nhi.pas`, pre-authorisation) — https://packages.fhir.org/tw.gov.mohw.nhi.pas/1.3.0 | NHIA Taiwan | probably CC0 (same publisher); not read | Examples not counted | Extra NHI-coded Claim, Condition and Observation examples (oncology pre-auth) | S | ~ (registry entry only) |
| **THAS FHIR sandbox** — https://thas.mohw.gov.tw/v/r4/fhir (page: https://thas.mohw.gov.tw/smart/sandbox) | MOHW / ITRI 臺灣醫療資訊標準大平台 | No terms on the page; public endpoint, user-loaded data | HAPI FHIR R4 (`/metadata` answered on 2026-11-08) | Live R4 server for testing the FHIR pull/`$export` client and paging against a Taiwanese HAPI. Shared server: load synthetic data only. | S | ✓ endpoint / ✗ terms |
| **JP Core 1.2.0** — https://jpfhir.jp/fhir/core/1.2.0/jp-core.r4-1.2.0.tgz (+ `examples.json.zip`) | JAMI NeXEHRS FHIR WG | **No licence stated**; "© JAMI"; the IG says it is not HL7 Japan-approved and is used at one's own risk | 534 kB; about 70 example instances in the package (27 Observation, 7 DiagnosticReport, 4 MedicationRequest, 4 MedicationAdministration, Patient, Encounter, Condition, AllergyIntolerance, Immunization, …); ja | Fills the JP Core mapping gap (`jp_core/` holds only a README, A-T5): round-trip each example through a `jp_core` mapping, then compare the lake rows. Keep the examples in `.cache`; do not commit them until the terms are clarified. | S–M | ✓ (downloaded; licence absent) |
| **JP-CLINS IG 1.13.0** (電子カルテ情報共有サービス) — https://jpfhir.jp/fhir/clins/igv1/ (examples: `…/igv1/examples.json.zip`, `Bundle-Bundle-CLINS-*.json`) | JAMI | **CC BY-ND 4.0** (use and test allowed; do not redistribute modified copies) | 2026-08-31; 6 Bundles (referral 診療情報提供書, patient summary, 5-info Observations), about 40 Observation, 14 MedicationRequest, 8 Condition; ja | Ingest the national-format referral/discharge Bundles. These are the format Japanese hospitals will actually emit from FY2026, so the check is "a CLINS Bundle → patient, diagnoses, labs, meds all land in the lake". | S–M | ✓ |
| JP eReferral / eCheckup / ePrescriptionData IGs — https://jpfhir.jp/fhir/eReferral/igv1/ etc. | JAMI | Probably CC BY-ND (same site); not read | ja | More Japanese document examples (check-up results for lab-value feasibility) | S | ~ |
| **SS-MIX2 spec Ver.1.2j** (2026-08) + `ssmixStorageManifest.xml/.xsd` — https://www.jami.jp/jamistd/ss-mix2/ | JAMI / JAHIS (HS026, ISO/TS 24289) | Free PDF download; licence not stated; HELICS notes **patents** on systems built on the standard | PDFs + one manifest XML; ja | **No public SS-MIX2 sample storage exists** (searched ja/en). Build a synthetic standardized-storage tree from the spec (folder layout, file naming, ADT^A08, OMP^O09, OUL^R22, PPR^ZD1) and the manifest XML. Then test the R14 reader on it: folder walk, JIS/ISO-2022-JP encodings, delete flags, multi-volume. | L | ✓ |
| **JAHIS data-exchange standards** (臨床検査 Ver.5.0C, 処方 Ver.3.0C, 病名 Ver.3.2C, 注射 Ver.2.2C, …) — https://www.jahis.jp/standard/contents_type=33 | JAHIS | Free PDF; terms not read | Each PDF carries worked HL7 v2.5 message examples; ja | Copy the sample messages into the SS-MIX2 fixture tree as golden parser tests (lab OUL^R22 with JLAC10, prescription RDE with HOT/YJ). | M | ✓ listing / ✗ terms |
| **Synthea-international `jp/`** — https://github.com/synthetichealth/synthea-international/tree/master/jp | MITRE + contributors | Apache-2.0; data from e-Stat, Japan Post, GeoNames CC BY 4.0, MHLW PDL1.0 | 47 prefectures, 1,718 municipalities, 7,715 hospitals, 80,154 clinics (June 2026 MHLW facility data), age-dependent co-pay payer | A Japanese-shaped synthetic hospital at scale. It extends `eval/synthea` (US) to JP demographics and then feeds a JP Core / SS-MIX2 export writer. The disease modules are still US. There is **no Taiwan (`tw/`) folder**. | M | ✓ |
| **eICU-CRD Demo 2.0.1** — https://physionet.org/content/eicu-crd-demo/2.0.1/ | PhysioNet / MIT LCP / Philips | **ODbL 1.0**, Open | 2,500 ICU unit stays from 20 hospitals, 130.6 MB CSV; en | **EMR CSV import path** at 25× the MIMIC demo, multi-hospital (site-ID handling). Re-run the EMPULSE/STARRT-AKI-style FEAS invariants. | S–M | ✓ |
| MIMIC-IV Clinical Database Demo 2.2 (CSV) — https://physionet.org/content/mimic-iv-demo/2.2/ | PhysioNet | ODbL 1.0, Open | 100 patients, 15.5 MB | **Same patients as the FHIR demo, in CSV**: the CSV adapter and the FHIR adapter should give identical funnels (cross-adapter parity). | S | ✓ |
| **NHI drug list 健保用藥品項查詢項目檔** — data.gov.tw nid 23715 (API `https://info.nhi.gov.tw/IODE0000/openapi.json`) | NHIA Taiwan | **政府資料開放授權條款 v1** (Open, commercial OK, attribution); updated daily (last 2026-10-28) | NHI drug code, zh/en name, ingredient, **ATC** | Validate the NHI-code → ATC map used by drug criteria; every NHI drug code in the synthetic TW hospital must resolve. | S | ✓ |
| **NHI 醫療服務給付項目及支付標準 (CSV)** — data.gov.tw nid 174450 | NHIA Taiwan | Gov Open Data v1 | Order/procedure fee codes, updated 2026-11-08 | Validate procedure/order-code criteria (dialysis, ventilation) for TW | S | ✓ |
| ICD-10-CM/PCS 2023 中文版 (TW) — ValueSets in TW Core; full list at https://fhir.mohw.gov.tw/ts/valueset.jsp | MOHW | TW Core part CC0; terminology server terms not read | zh-TW | Chinese display names for the diagnosis dictionary (`public_site` DX) | S | ~ |
| **MEDIS standard masters** (標準病名, HOT, 臨床検査) — https://www2.medis.or.jp/master/ | MEDIS-DC | Free download; old terms allow **internal use only, no redistribution** | about 25k disease concepts → ICD-10; ja | Japanese diagnosis-name → ICD-10 mapping for SS-MIX2/JP Core; test the coverage of real 病名 strings | M | ✗ (page did not render; terms from a 2018 HELICS report) |
| **JLAC10 / JLAC11 code tables** — https://www.jslm.org/committees/code/ | JSLM | Free download; terms not read | Lab codes; JLAC11 list now covers more than the CLINS 43+5 items | JLAC10/11 → LOINC map for lab criteria (HbA1c, eGFR, NT-proBNP) | M | ✓ page / ✗ terms |
| 診療報酬情報提供サービス (レセ電 masters: 傷病名, 医薬品, 診療行為) — https://shinryohoshu.mhlw.go.jp/shinryohoshu/ | MHLW | MHLW site (PDL1.0 by default); updated 2026-11-02 | ja | Claims-code dictionaries for SS-MIX2 prescriptions and 病名; the YJ/receipt code → ATC join | S–M | ~ |

## Stage 2. Protocol parsing into criteria

| Name & URL | Owner | Licence / access | Size, language | Check it enables | Effort | Verif. |
|---|---|---|---|---|---|---|
| **台灣藥品臨床試驗現況資料集** (TFDA approved drug trials) — data.gov.tw nid 177198; file https://data.fda.gov.tw/data/opendata/export/205/json (zip); companion sets 177215 sites, 177216 drugs, 177212 indication ICD | TFDA Taiwan | **政府資料開放授權條款 v1**, Open, monthly (updated 2026-11-04) | **19,290 trials, 18,916 with 納入條件 / 排除條件 in Traditional Chinese**, plus sponsor protocol number, phase, TW and global sample size, sites; 180 MB JSON | **The best zh-TW find.** (a) Parse zh-TW criteria into IR and measure the route split against Chia. (b) The sponsor protocol number (e.g. `CBAF312D2301`) links to ClinicalTrials.gov `orgStudyId`, which gives **parallel zh-TW/en criteria for the same trial**: parse both and diff the IR. (c) The site list drives stage 5 (which TW hospitals run which trial). | S–M | ✓ (downloaded and parsed) |
| **jRCT** — https://jrct.mhlw.go.jp/search | MHLW Japan | Search-result CSV download with a 利用規約 (the PDF link returned HTML, **terms not read**); the site asks users not to collect in bulk by program | ja + en eligibility per record | Japanese protocol parsing with the en version as a cross-check (same idea as TFDA). Fetch a few dozen records by hand only. The appliance's own offline jRCT snapshot (E-T9) needs these terms. | M | ✓ site / ✗ terms |
| **UMIN-CTR daily snapshot** — https://www.umin.ac.jp/ctr/csvdata.html (`ctr_data_j.csv.gz`) | UMIN | **Free; NC**: no use of extracted information "for marketing, promotional or commercial purposes"; **no redistribution**; attribute; state modifications | All UMIN-CTR records, ja + en, UTF-8 CSV | Large Japanese criteria corpus for parser robustness. Internal evaluation only, never shipped in the appliance. Ask legal whether a vendor's internal QA counts as commercial. | S | ✓ |
| **Leaf Clinical Trials (LCT) corpus** — https://doi.org/10.6084/m9.figshare.17209610 | UW BioNLP (Dobbins et al., Sci Data 2022) | **CC BY 4.0**, Open | 1.3 MB tar.gz; more than 1,000 trials, fine-grained entity and relation annotation (EliIE/Chia-based); en | Second gold set for criteria → IR extraction, with finer temporal and value annotations than Chia; score entity and value/unit extraction | S | ✓ (figshare API) |
| **TrialPanorama** database + benchmark — https://huggingface.co/datasets/zifeng-ai/TrialPanorama-database, …/TrialPanorama-benchmark | Zifeng Wang et al. (2025) | **Apache-2.0**, Open | DB 2.44 GB parquet (1.33M study rows, 5.73M AE rows); benchmark 8 tasks incl. `eligibility_criteria_design` 28.3k; en | Large-scale regression for the protocol parser (no crash, every trial parsed). The AE table gives realistic AE term distributions for stage 6. The benchmark has no matching task. | M | ✓ (HF page) |
| **TrialBench** — https://zenodo.org/records/14975339 | Chen et al. (Sci Data 2025) | **CC BY 4.0** (Zenodo v1; a newer version exists) | 624 MB, 8 tasks incl. eligibility-criteria design (57 MB), SAE forecasting | Secondary: SAE / dropout tables for lifecycle simulations | M | ✓ |
| Criteria2SQL — https://github.com/xiaojingyu92/Criteria2SQL | Yu et al. (LREC 2020) | **No licence file** | 2,003 criteria → SQL (WikiSQL format); en | Stage 2→3 check: TrialBox IR → SQL against the gold SQL semantics | M | ~ (licence absent) |
| EliIE corpus — https://github.com/Tian312/EliIE | Columbia (Kang 2017) | Licence not found | 230 AD trials, OMOP-oriented | AD-specific extraction (complements `eval/ad`) | M | ✗ |
| CT-EBM-SP — https://zenodo.org/records/6059737 (v4 https://zenodo.org/records/18048413) | UAM / CSIC | **CC BY-NC 4.0** | 1,200 texts, Spanish | Low value (Spanish); NC | — | ~ |
| CHIP-CTC (CBLUE) | CHIP / Alibaba Tianchi | Reg; licence unclear (already rejected) | zh-CN criteria classes | — | — | — |

## Stage 3. Feasibility counts (SQL sanity checks against aggregates)

| Name & URL | Owner | Licence / access | Size, language | Check it enables | Effort | Verif. |
|---|---|---|---|---|---|---|
| **NDB Open Data (12th edition, monthly releases)** — https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000177182.html | MHLW Japan | **PDL1.0 (公共データ利用規約, CC BY 4.0-compatible)**, Open | National claims aggregates: prescriptions by drug × sex × 5-year age, procedures, 特定健診 lab distributions (HbA1c, eGFR, BMI, BP) by age/sex; ja Excel | Plausibility gate for JP synthetic/real FEAS. For example, FEAS on a Synthea-jp hospital should give an HbA1c ≥6.5 % share by age band within ±X of the NDB 健診 distribution, and SGLT2 prescribing by age should match. Catches unit and code-map errors (JLAC, YJ). | M | ✓ |
| 全国がん登録 / cancer statistics download — https://ganjoho.jp/reg_stat/statistics/data/dl/index.html | National Cancer Center Japan | Free; **attribution required** (site rule) | Incidence by site × age × sex; ja | Oncology trial FEAS sanity (e.g. NSCLC stage IV counts per 100k) | S | ✓ |
| **Taiwan HPA 癌症發生統計** (nid 6399), **20歲以上高血糖/糖尿病盛行率** (nid 9337), **MOHW 死因統計** (nid 5965), 急診就診率 by age/sex (nid 32029) — https://data.gov.tw | HPA / MOHW | Gov Open Data v1 | TW aggregates, zh-TW CSV | The same plausibility gate for the TW synthetic hospital (diabetes prevalence by age, cancer incidence by site) | S–M | ✓ |
| eICU / MIMIC demo CSV (see stage 1) | — | ODbL | — | Re-count every applied criterion with an independent pandas implementation against the SQL: the same "two implementations agree" check as `eval/synthea` | S | ✓ |
| e-Stat 患者調査 (Patient Survey) | MHLW / e-Stat | Gov Standard ToU 2.0 (CC BY-compatible), per Synthea-jp README | Estimated patients by ICD chapter × age | Prevalence denominator for JP feasibility | S | ~ |

## Stage 4. Screening: structured SQL and LLM notes (en/ja/zh-TW), negation and uncertainty

| Name & URL | Owner | Licence / access | Size, language | Check it enables | Effort | Verif. |
|---|---|---|---|---|---|---|
| **MedTxt-RR-TNM (NTCIR-17 MedNLP-SC RR)** — https://sociocom.naist.jp/download/mednlp-sc-rr-tnm/ | Sociocom NAIST | **CC BY 4.0** | 243 Japanese radiology reports (27 lung-cancer cases × 9 radiologists), TNM gold; no overlap with MedTxt-RR | Japanese oncology criteria such as "T≥2", "N0", "M1 excluded" judged from reports with gold TNM. The inter-radiologist variation gives an upper bound. Extends `eval/medtxt`. | S | ✓ (download button points to "#" on the page; fetch through the site's form) |
| **NTCIR-13 MedWeb** — https://research.nii.ac.jp/ntcir/permission/ntcir-13/perm-en-MedWeb.html (mirror `bigbio/ntcir_13_medweb`) | NII / Sociocom | **CC BY 4.0** (NII page); via NII IDR | 2,560 pseudo-tweets, **parallel ja/en/zh**, 8 symptoms with p/n labels | **Cross-language negation check**: the same statement in three languages ("no fever", "熱はない", "沒有發燒") should get the same label from both LLMs. The zh is probably Simplified: convert with OpenCC to zh-TW and verify. | S | ~ (licence from the NII page; script of zh not verified) |
| MedNLP-SC Social Media corpus (ADE, ja/en/de/fr) — https://sociocom.naist.jp/download/mednlp-sc-sm/ | Sociocom NAIST | "Publicly available since 2024-01-04"; licence not read | ADE in patient tweets | AE-mention detection in ja (stage 6 AE intake from notes) | S | ~ |
| JMED-LLM tasks (CRADE, RRTNM, SMDIS, MRNER) — https://github.com/sociocom/JMED-LLM | Sociocom NAIST | Per task: **CC BY 4.0** for MedTxt/MedWeb-based tasks; **CC BY-NC-SA** for NRNER (nursing records) and JCSTS | ja | Ready LLM-format versions; CRADE (ADE certainty in case reports) adds AE-causality judging | S | ✓ |
| MedNLP-CHAT — https://sociocom.naist.jp/download/mednlp-chat-corpus/ | Sociocom NAIST | CC BY 4.0 | About 200 ja Q&A with medical, legal and ethical risk labels | Front-desk chat safety (`eval/chat`), not screening | S | ~ |
| BioScope — `bigbio/bioscope` | Univ. Szeged | CC BY 2.0 (HF card) | en clinical radiology + biomedical, negation and speculation cue and scope | English negation/speculation regression for the judge's "absence is not negative" rule | S | ~ |
| PMC-Patients — https://huggingface.co/datasets/zhengyun21/PMC-Patients | Zhao et al. | **CC BY-NC-SA 4.0** | 167k patient summaries from case reports, en | Large note pool for de-identification and throughput tests; NC | — | ✓ |
| MMedBench — `Henrychur/MMedBench` | SJTU | **CC BY-NC 4.0** (card) | Medical MCQ in en/zh/ja/fr/ru/es | Language competence of the two local LLMs; NC | — | ✓ |
| TMMLU+ — `ikala/tmmluplus` | iKala | **CC BY-NC** (card) | zh-TW MCQ, incl. TCM and clinical subjects | zh-TW medical vocabulary sanity; NC | — | ~ |
| IMCS-21 — https://github.com/lemuria-wchen/imcs21 | Fudan | **No licence file** | zh-CN doctor–patient dialogues with symptom status (positive / negative / uncertain) | Would be the best zh negation/uncertainty set, but the licence is unknown and it is Simplified Chinese | — | ✗ |
| CTcl cross-lingual TREC CT 2021 topics — https://zenodo.org/doi/10.5281/zenodo.18503690 | Tecnalia / UPV-EHU (SIGIR 2026) | CC BY 4.0 | 7 languages: bn, el, es, eu, it, pl, tr (**no ja/zh**) | Method template only: translate TREC 2021 topics into ja/zh-TW the same way | — | ✓ |
| NLI4PR — https://github.com/CTInfer/NLI4PR | CL4Health 2025 | Not read | TREC 2022 patients rewritten in lay language, en | Robustness of the judge to non-clinical wording | S | ✗ |
| **n2c2 2018 Track 1** — https://n2c2.dbmi.hms.harvard.edu/data-sets | Harvard DBMI | **DUA** per user | 288 patients, 13 criteria, real longitudinal notes | Still the best real-note gold set (unchanged since the 11-05 review) | M | ~ |

## Stage 5. PI and CRC patient lists

There is no public dataset of PI/CRC worklists. The useful inputs are realistic site and staff structures:

| Name & URL | Owner | Licence / access | Check it enables | Effort | Verif. |
|---|---|---|---|---|---|
| TFDA 試驗執行機構 (nid 177215) + trial set above | TFDA | Gov Open Data v1 | Real multi-site TW trials: route one trial's list to several departments and hospitals, using real hospital names and departments | S | ✓ |
| MHLW medical facility open data (used by Synthea-jp) — https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/iryou/newpage_43373.html | MHLW | PDL1.0 | Real JP hospital departments for the staff/department tables of a synthetic site | S | ~ |

## Stage 6. Trial lifecycle, EDC export (ODM 1.3, REDCap CSV, XLSX)

| Name & URL | Owner | Licence / access | Size, language | Check it enables | Effort | Verif. |
|---|---|---|---|---|---|---|
| **pharmaversesdtm 1.5.0** — https://cran.r-project.org/package=pharmaversesdtm (CSV in `inst/extdata/`) | pharmaverse (Roche, GSK, Cytel, …) | **Apache-2.0** (some domains derived from the CDISC pilot) | SDTM DM, AE, SUPPAE, CM, DS, EX, LB, VS, SV, MH, EG, TS, and oncology/vaccine/ophtha domains; **no DV (deviations)**; en | Load subject-level consent (DS), enrolment, visits (SV), AEs (AE+SUPPAE) and CRF values into the lifecycle tables. Export to ODM, REDCap CSV and XLSX, re-import, and require byte or row equality. AE fields test MedDRA-coded AE capture. | S | ✓ |
| pharmaverseadam 1.4.0 — https://cran.r-project.org/package=pharmaverseadam | pharmaverse | Apache-2.0 | ADSL, ADAE, … | Cross-check derived counts (AE by SOC) after the TrialBox export | S | ✓ |
| CDISC SDTM/ADaM pilot (CDISCPILOT01) — https://github.com/cdisc-org/sdtm-adam-pilot-project | CDISC | Custom ToU: **no modification or alteration** of the data; as-is | 254 subjects, XPT + define.xml | Prefer pharmaversesdtm (Apache). Use the pilot only read-only, e.g. its define.xml (an ODM-based file) as an ODM parser input. | S | ✓ |
| safetyData 1.0.0 — https://cran.r-project.org/package=safetyData | SafetyGraphics | MIT | CDISC-pilot-based SDTM/ADaM | Alternative source if the Apache NOTICE is a burden | S | ✓ |
| random.cdisc.data 0.3.16 — CRAN | Roche / insightsengineering | Apache-2.0 | Seeded random ADaM (ADAE, …) of any size | **Synthetic AE datasets at scale** for export stress tests (10k subjects) | S | ✓ |
| **odmlib test data** — https://github.com/swhume/odmlib (`tests/data/`) | Sam Hume (CDISC) | **MIT** | ODM 1.3.2 and 2.0 files: `test_odm_001.xml`, `test_clinical_data_01.xml`, `cdash-odm-test.xml`, `ae.xml`, `dm.xml`, `lb.xml`, nonconformant and invalid cases, Define-XML 2.0/2.1 | **ODM 1.3 conformance suite**: TrialBox's ODM reader must accept the valid files and reject the nonconformant ones. Round-trip `cdash-odm-test.xml` through TrialBox and diff the ClinicalData. | S | ✓ (listing via WebFetch, licence via raw) |
| CDISC ODM v2.0 repo (schema, examples, rules) — https://github.com/cdisc-org/DataExchange-ODM | CDISC | MIT | XSD + examples (ODM 2.0) | Schema validation; future ODM 2.0 export | S | ✓ |
| CDISC Dataset-JSON — https://github.com/cdisc-org/DataExchange-DatasetJson | CDISC | MIT | Examples | Optional extra export format | S | ✓ |
| CDISC ODM-XML 1.3.2 spec + examples — https://www.cdisc.org/standards/data-exchange/odm-xml/odm-xml-v1-3-2 | CDISC | **Reg** (free CDISC account) | Spec PDF, XSD, examples | The canonical 1.3.2 XSD for the validator | S | ✓ (gated) |
| **JADER** (Japanese adverse drug event reports) — https://www.pmda.go.jp/safety/info-services/drugs/adr-info/suspected-adr/0003.html | PMDA | Free; ToU: **notify PMDA before publishing**, cite JADER, report serious safety signals | Monthly CSV (DEMO, DRUG, REAC, HIST); Japanese MedDRA PT names | Japanese AE-term coding check: free-text AE → MedDRA PT (ja). Note that MedDRA itself needs a licence for any coding dictionary shipped. | M | ✓ page / ~ terms |
| CT-ADE — https://huggingface.co/datasets/anthonyyazdaniml/CT-ADE-PT (code https://github.com/ds4dh/CT-ADE) | Univ. Geneva (ds4dh) | MIT on the SOC card; PT card licence not seen | About 15.6k trial arms × MedDRA PT ADEs | Realistic AE PT distributions per drug class for synthetic lifecycle data | S | ~ |
| MDM Portal (Medical Data Models) — https://medical-data-models.org/ | Univ. Heidelberg / Münster | **Reg; "academic (non-commercial)"**; per-form licences (e.g. CC BY-NC-SA 3.0 DE) | more than 25,000 CRFs in ODM 1.3.2, many languages | Real-world ODM CRF variety (code lists, units, repeating groups); NC | M | ✓ (NC) |

## Stage 7. Two-way sync with REDCap and spreadsheets

| Name & URL | Owner | Licence / access | Size | Check it enables | Effort | Verif. |
|---|---|---|---|---|---|---|
| **REDCapR test projects** — https://github.com/OuhscBbmc/REDCapR/tree/main/inst/test-data/projects | OUHSC BBMC | **MIT** (REDCapR 1.7.0, 2026-08-20) | 30 projects, each a `dictionary.csv` and `data.csv`: `clinical-trial-1`, `longitudinal`, `arm-single-longitudinal`, `longitudinal-with-repeating-instrument`, `repeating-instruments(-sparse)`, `checkboxes-1`, `validation-types-1`, `decimal-comma`, `russian` (non-ASCII), `dag`, `file-repo`, `potentially-problematic-dictionary/values`, `super-wide-3` | **REDCap data-dictionary and record CSV edge cases**: TrialBox must import each dictionary, map it to its CRF model, export identical CSV, and survive the "problematic" ones without silent loss. `russian` stands in for ja/zh-TW labels. | S | ✓ (folder list via WebFetch) |
| PyCap tests — https://github.com/redcap-tools/PyCap | Vanderbilt / redcap-tools | MIT | API response fixtures | Mock REDCap API for the sync client (export/import records, metadata, events, repeating instruments) without a server | S | ✓ |
| redcaptools `importdemo_dict` — https://rdrr.io/github/aghaynes/redcaptools/man/importdemo_dict.html | A. Haynes | Not read | Simulated dictionary covering all field types and validations | Validation-rule coverage | S | ✗ |
| REDCap server itself | Vanderbilt | **Consortium licence (non-profit institutions only)**; not open source | — | True two-way sync needs a partner hospital's REDCap test project; Vanderbilt does not license a vendor | — | ~ |
| **LibreClinica 1.4.0** — https://github.com/reliatec-gmbh/LibreClinica | Reliatec / community | LGPL-3.0 / GPL-3.0; Dockerfile + compose in the repo | OpenClinica 3.x successor | A real ODM 1.3-speaking EDC on-prem: export a TrialBox study as ODM, import it into LibreClinica, enter data, export ODM (with OpenClinica extensions), and sync back. Exact ODM support was not confirmed from the page. | M | ~ |
| OpenEDC — https://github.com/imi-muenster/OpenEDC | Univ. Münster | MIT, but **"unmaintained prototype"**; the rewrite at openedc.health has an unknown licence | Browser EDC on unmodified ODM | Lightweight ODM round-trip partner | M | ✓ |

---

## Top 10 to integrate next (no DUA, ranked by value per effort)

| # | Dataset | Stage(s) | Exact check | Effort | Why now |
|---|---|---|---|---|---|
| 1 | **TFDA 台灣藥品臨床試驗現況** (data.gov.tw 177198; 19,290 trials, zh-TW 納入/排除條件; Gov Open Data v1) | 2, 5 | Parse zh-TW criteria → IR on a stratified 200-trial sample. Join to CT.gov by sponsor protocol no. and diff zh-TW IR vs en IR (agreement rate per criterion type). Route lists by real TW sites. | S–M | The first real Traditional Chinese protocol text, with commercial use allowed and a free en twin |
| 2 | **TW Core 1.0.0 + TW EMR IG 0.2.0 examples** (CC0) | 1, 4 | Ingest all 98 TW Core examples and 6 EMR Bundles with 0 validation errors. The 出院病摘 / 門診病歷 narratives go to the note store and through the zh-TW judge smoke test. | S | Closes "TW Core profiles are not tested" (OPEN_DATA.md §4) |
| 3 | **odmlib test data + CDISC ODM XSD** (MIT) | 6 | ODM 1.3.2 conformance: accept the valid files, reject the nonconformant ones, and round-trip `cdash-odm-test.xml` with zero ClinicalData diff | S | Cheap, deterministic, CI-friendly |
| 4 | **pharmaversesdtm / pharmaverseadam** (Apache-2.0) | 6 | Load DM/DS/SV/EX/AE/LB into lifecycle tables, export ODM, REDCap CSV and XLSX, re-import, then check row equality and that AE-by-SOC counts equal ADAE | S | Real subject-level trial data shape |
| 5 | **REDCapR test projects** (MIT) + PyCap fixtures | 7 | Import each of the 30 dictionaries and records, export, then diff. The problematic, decimal-comma and non-ASCII projects must not lose data silently. Mock the API sync with PyCap. | S | REDCap sync is untested without a server |
| 6 | **JP Core 1.2.0 + JP-CLINS 1.13.0 examples** | 1 | Build the `jp_core` mapping (gap A-T5). Each example and each CLINS Bundle should populate the expected lake rows. | S–M | First JP FHIR test. JP Core has no stated licence and JP-CLINS is CC BY-ND: keep them in `.cache` and do not commit them. |
| 7 | **MedTxt-RR-TNM + NTCIR-13 MedWeb** (CC BY 4.0) | 4 | Gold TNM → judge "T≥2 / N0 / M1" criteria on 243 ja reports. MedWeb ja/en/zh parallel negation: label agreement across languages for both LLMs. | S | Extends `eval/medtxt`; the only open ja/zh negation parallel found |
| 8 | **eICU-CRD demo + MIMIC-IV demo CSV** (ODbL) | 1, 3 | CSV adapter at 2,500 stays and 20 hospitals. CSV-vs-FHIR parity on the MIMIC demo should give identical funnels. Recount every criterion with an independent pandas implementation. | S–M | Exercises the EMR-CSV path, which no open test covers today |
| 9 | **NDB Open Data + TW HPA / MOHW aggregates** (PDL1.0 / Gov Open Data) | 3 | Plausibility gate: FEAS shares on the synthetic JP/TW hospitals (HbA1c ≥6.5 % by age, SGLT2 use, cancer incidence) within tolerance of the national aggregates | M | Catches unit and code-map errors that internal invariants cannot |
| 10 | **Synthea-international `jp/`** (Apache-2.0) | 1, 3 | Generate a JP-demography hospital, write it as JP Core bundles and as a synthetic SS-MIX2 tree (spec 1.2j + JAHIS sample messages), then run FEAS and check it against item 9 | M | Feeds the SS-MIX2 reader (R14); there is no public SS-MIX2 sample |

Next after the top 10:
- **LCT corpus** (CC BY 4.0, S): a second criteria-extraction gold set.
- **LibreClinica** (LGPL, M): ODM sync against a real EDC.
- **JADER** (free, M): Japanese AE terms.
- **TrialPanorama** (Apache-2.0, M): parser stress test on 1.3M trials.

Needs legal review or an agreement first:
- **jRCT**: terms not read; bulk collection discouraged.
- **UMIN-CTR**: non-commercial clause.
- **MEDIS masters**: internal use only.
- **MDM portal**: non-commercial.
- **n2c2 2018**: DUA.
- **MIMIC-IV notes**: credentialed access.

## Gaps found

- **No public SS-MIX2 sample storage** in Japanese or English sources. It has to be synthesised from the spec and JAHIS
  examples. The patent note in the HELICS documents should go to legal.
- **No open Taiwanese clinical notes** beyond the IG examples. The TFDA criteria and MedWeb (converted to zh-TW) are
  the best open zh-TW text. zh-TW negation needs a hand-built set, for example from the TFDA exclusion criteria.
- **No Taiwan Synthea configuration** (synthea-international has `jp/` but no `tw/`).
- **No Japanese public FHIR test server** was found. The JP Core CapabilityStatement requires 401 for unauthenticated
  requests; run a local HAPI with the JP Core package loaded.
- **No public dataset carries protocol deviations (DV)**. Synthesise them on top of pharmaversesdtm.
