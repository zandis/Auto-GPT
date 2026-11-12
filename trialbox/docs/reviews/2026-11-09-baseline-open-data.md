# TrialBox: open data to ship as baseline data (assessment 2026-11-09)

Scope: which open data the release should carry, offline, to make drafting, SQL screening, note screening, local-code
mapping, feasibility and AE capture work better at Japanese and Taiwanese sites. The 2026-11-08 survey
(`2026-11-08-open-data-candidates.md`) covered data for *validation*; this one covers *runtime* data, plus the evaluation
sets used to measure the gain. The reference-data pack being built in parallel (CT.gov, TFDA trial sets, 薬価基準, NHI
lists, ICD-10-CM, LOINC, jRCT/UMIN) is assessed here too, so this is one list.

**Licence status.** **Ship**: the terms clearly allow a commercial vendor to redistribute it in the bundle (notice or
attribution may be required). **Ship after OK**: free, but the publisher asks a vendor to apply first. **Site**: the
hospital downloads it itself (free, sometimes with registration) and loads it with our loader. **No**: not usable in the
product. **Eval**: used only to measure, never shipped. "Unverified" means the terms were not read at the source today.

## 1. Summary (one page)

**Where we start.** Outside ICD-10-CM, the shipped terminology is a gout demo. `terminology/src` holds 27 LOINC rows,
24 ATC rows, 64 named ICD-10-CM rows, 24 *synthetic* NHI drug codes and 4 synthetic NHI orders. The Japanese lookups
hold 32 標準病名, 14 JLAC10 and 22 YJ rows, all synthetic and marked `verify`. Only the full ICD-10-CM list (98,186
codes) is real. Every lab, drug or diagnosis name outside these rows falls through to the LLM `concept_map`. That step
picks from the top-20 lexical candidates of the same tiny tables and is always `needs_review`. Chia routes 54 % of
criteria to the structured filter (`eval/chia/results/routes.json`), so the terminology, not the models, now caps
SQL recall at a real site.

**Recommended P0 set (first release).**

| # | Source | Licence status | Stage it improves |
|---|---|---|---|
| 1 | ICD-10-CM FY2027 (CMS/NCHS), replacing the 2026 file | Ship (US public domain) | SQL recall, compile |
| 2 | Taiwan 2023 中文版 ICD-10-CM/PCS + the 2014↔2023 map (NHIA) | Ship (政府資料開放授權條款 v1) | zh-TW names, TW pre-2025 records, procedures |
| 3 | LOINC (Regenstrief), lab subset or the full table | Ship (free, commercial OK, notice and version required) | lab criteria compile |
| 4 | NHI service → LOINC ConceptMap, 806 codes (NHIA PAS IG 1.3.0) + TW Core lab ValueSet | Ship (CC0, verified in package.json) | TW local lab mapping |
| 5 | UCUM + our unit-conversion table | Ship (UCUM free with notice; unverified today) | value criteria, harmonization |
| 6 | NHI drug list 健保用藥品 with ATC (NHIA, daily) + NHI 醫療服務給付項目 | Ship (Gov Open Data v1) | TW drug and procedure criteria |
| 7 | MHLW 薬価基準収載品目リスト + 一般名処方マスタ | Ship (PDL1.0, attribution) | JP drug codes, generic names, 薬効分類 classes |
| 8 | MEDIS 標準病名マスター and 医薬品HOTコードマスター | **Site now; ship after MEDIS OK** (free download; vendors apply for 使用許諾) | JP unknown-code rate, 病名 → ICD-10 |
| 9 | JLAC10 code table (JSLM) and 臨床検査マスター まとめ表 (JLAC Center) | **Site** (free download; no licence stated, unverified) | JP lab mapping suggestions |
| 10 | Our own tables: drug-class table (class → ATC prefixes, our own words), 薬効分類 → class, JLAC10 → LOINC for the CLINS 43+5 items, the WHO ICD-10 → ICD-10-CM category bridge | Ship (we author them) | drug-class criteria, JP labs, D-130 unknowns |
| 11 | ClinicalTrials.gov JP + TW subset (about 23,000 studies) + TFDA trial sets | Ship (NLM public data; Gov Open Data v1) | drafting examples, feasibility, offline default |
| 12 | CTCAE v6.0 (+ v5 → v6 map), NCI | Ship (US public domain) | AE form term list |
| 13 | Formulas: Japanese eGFR (JSN), Cockcroft–Gault CrCl, BSA, ECOG / Karnofsky definitions | Ship (formulas; we write the text) | value criteria at JP sites |
| 14 | Hyakuyaku 百薬辞書, JMED-DICT mini, NAER 醫學學術名詞 (en ↔ zh-TW) | Ship (CC BY 4.0; "商用利用可"; Gov Open Data v1) | note retrieval, name matching in ja and zh-TW |

**Size.** About 1 GB uncompressed and about 0.3 GB compressed in the bundle (estimates; CT.gov subset and HOT are most
of it). That is under 1 % of the roughly 40 GB offline media of D-138.

**Expected gains** (estimates to be checked with §3, not measured):
- More of the filter-routed criteria compile to codes without a PI fixing them. Target: at least 70 % of condition,
  drug and lab atoms mapped with at least 95 % precision.
- At Japanese SS-MIX2 sites, the D-130 "unknown code system" count falls to the rows the hospital really left uncoded.
  Today the 400-patient test hospital has 287 patients with unreadable diagnoses and 276 with unreadable medicines.
- Taiwanese lab codes (NHI order codes) get a LOINC suggestion out of the box, so one-tap confirmation replaces typing.
- The box can run with no outbound traffic by default, because drafting and feasibility read a local registry snapshot.
- AE entry gets coded CTCAE terms. Grading stays with a person (D-129).

**What the owner must decide.**
1. **Apply to MEDIS** (mhyojun@medis.or.jp, 使用許諾申請書) to distribute the 病名 and HOT masters in the product.
   Until MEDIS says yes, ship the loader and the instructions only: hospitals may download the masters freely, with no
   registration.
2. **Ask JSLM / JLAC Center** whether the JLAC10 table and the まとめ表 may be redistributed.
3. **Ask the jRCT help desk** for permission for bulk use. Their terms (PDL1.0) require it for 包括的・網羅的 use.
4. **ATC.** The WHOCC forbids "copying and distribution for commercial purposes". Either ask WHOCC for a commercial
   licence, or (recommended now) ship only ATC codes taken from the NHI list plus our own class table, with no WHOCC
   names or hierarchy text.
5. **Do not buy** SNOMED CT (Japan and Taiwan are not members; the SQL path does not need it), DrugBank, KEGG, or an
   ICTRP institutional feed. MedDRA stays with the sites and sponsors.
6. **Ask JCOG** before shipping its Japanese CTCAE translation. Translate to zh-TW ourselves.
7. **Approve** a NOTICE page in the console and the bundle (LOINC, UCUM, CC BY, PDL1.0, Gov Open Data v1 and MEDIS
   attributions). Also decide whether the wizard's default should become the offline registry (the open point of D-138).

## 2. Full candidate table

Columns: **Lic.** = licence status; **Size/upd.** = size and update frequency; **Load** = format and loader effort
(S ≤ 1 day, M 2–4 days, L 1–2 weeks); **Effect** = pipeline stage, expected size and how to measure; **P** = priority. ✓ = terms
read at the source today; ~ = secondary source or not re-read today.

### 2.1 Trial registries

| Source (publisher) | Lic. | Size/upd. | Load | Effect | P |
|---|---|---|---|---|---|
| ClinicalTrials.gov API v2 bulk JSON (NLM) | Ship ✓ (public registry data; the box already uses it live) | 610,756 studies (2026-11-09); about 2 GB zipped for all; JP 9,961 (1,389 recruiting), TW 13,118 (1,835 recruiting); daily | JSON, S (other agent) | Drafting: similar-trial criteria as examples. Feasibility: competing trials at the site. Lets `TB_CTGOV_MODE` default to offline. Measure: drafting eval on CT.gov twins (TFDA ↔ CT.gov by protocol number); outbound sheet shows none | **P0** (JP+TW subset); full set P1 |
| AACT (CTTI) | Ship ~ (CT.gov-derived, free) | Postgres dump of the same data, daily | pg_dump, M | Nothing beyond the API bulk; a Postgres-shaped copy only | P2 |
| WHO ICTRP | **No** ✓: "shall not use … for marketing, promotional or commercial purposes"; the full feed needs an institutional form and a yearly fee | weekly | CSV | jRCT and other Asian records via WHO, but not usable | — |
| jRCT (MHLW) | **Ship after OK** ✓: PDL1.0, but 包括的・網羅的 use needs the help desk's permission, and no crawling | about 10k+ JP trials, ja + en; daily | search CSV, M | ja criteria for drafting examples and the JP feasibility list; includes JAPIC-CTI and JMACCT since 2023-03-06 | P1 (P0 if permission comes in time) |
| UMIN-CTR (UMIN) | **No** for shipping; Eval only ✓: no commercial use of extracted information, no redistribution | daily CSV snapshot | CSV, S | Japanese criteria corpus for parser QA (legal to confirm internal QA) | Eval |
| JAPIC-CTI, JMACCT-CTR | merged into jRCT ✓ (records moved 2023-03-06) | — | — | Covered by jRCT | — |
| TFDA 臨床試驗 datasets (nid 177198 trials, 177215 sites, 177216 drugs, 177212 indication ICD) | Ship ✓ (Gov Open Data v1; 2026-11-08 review) | 19,290 trials, 18,916 with zh-TW criteria; 180 MB JSON; monthly | JSON/CSV, S (other agent) | zh-TW drafting examples; TW site feasibility (which hospitals run which trials); zh-TW ↔ en twins for drafting eval | **P0** |
| EU CTIS (EMA) | ~ (EMA reuse notice; not read) | EU trials | API, M | Little for JP/TW sites | P2 |

### 2.2 Terminologies and code systems

| Source (publisher) | Lic. | Size/upd. | Load | Effect | P |
|---|---|---|---|---|---|
| ICD-10-CM (CMS/NCHS) | Ship (US public domain; already shipped, D-122) | about 98k codes, 0.7 MB gz; yearly on Oct 1 (FY2027 in force since 2026-10-01) | CSV, S | Refresh to FY2027 so new codes are not off-list (D-113) | **P0** |
| Taiwan 2023 中文版 ICD-10-CM/PCS + 2014↔2023 map (NHIA; data.gov.tw 177507–177509) | Ship ✓ (Gov Open Data v1, free; the TW Core CodeSystem names WHO as copyright holder, so attribute both) | about 70k CM + 78k PCS rows, zh-TW + en; per version | Excel/CSV, S | (a) zh-TW names for exact and synonym matching on zh-TW criteria. (b) **TW claims before 2025-01-01 use the 2014 edition**: map 2014 codes so old records are not off-list. (c) PCS for procedure criteria. Measure: `mapping_check` rows off-list on a TW hospital with 2014 codes; Chia/TFDA term coverage | **P0** |
| WHO ICD-10 (2019) text | **No** without a WHO licence (commercial use needs licensing@who.int; ~) | — | — | JP data carries WHO codes via MEDIS. We need only the code strings for the bridge (row 10 of §1), not WHO's text | — |
| ICD-11 MMS (WHO) | Ship ✓ (CC BY-ND 3.0 IGO: commercial OK, no adaptation) | yearly | API/files, M | No JP/TW site codes in ICD-11 yet; MEDIS has an ICD-11 標準病名 draft | P2 |
| SNOMED CT | **No** ✓: Japan and Taiwan are not on SNOMED International's member list; affiliate fees per country | — | — | Not needed by the SQL path | — |
| SNOMED IPS Terminology | Ship ~ (CC BY 4.0, for non-member users) | about 13k concepts | RF2, M | Resolves JMED-DICT's SNOMED-IPS links and TW Core SNOMED ValueSets; small gain | P2 |
| LOINC (Regenstrief) | Ship ✓ (free "for any commercial or non-commercial purpose", with the copyright notice, licence and version; no competing standard) | about 100k terms, about 80 MB zip; twice a year | CSV, S | Lab and vital criteria compile to codes; today 27 rows. Measure: lab-atom coverage on Chia measurement entities | **P0** |
| UCUM (Regenstrief) | Ship ~ (free incl. commercial, with notice; terms not re-read today) | < 1 MB | XML, S | Unit checks and conversions beyond the 5 analytes of `messy.py`; fewer "please check" questions. Measure: e2e stage 12 unit questions; value-criterion errors on synthetic µmol/L data | **P0** |
| RxNorm current prescribable content (NLM) | Ship ~ (no licence needed for this subset; public domain) | about 50 MB; monthly | RRF, M | English generic and brand names in TW physician notes → ingredient; US-centric | P1 |
| RxNorm full / UMLS | Site (UMLS licence per user) | — | — | Not needed | P2 |
| ATC/DDD index (WHOCC) | **No** ✓: "Copying and distribution for commercial purposes is not allowed. Changing or manipulating the material is not allowed." | about 6,800 codes; yearly | — | Use ATC codes from the NHI list and our own class table instead; or license from WHOCC (owner decision) | — |
| MeSH (NLM) | Ship ~ (free, NLM terms) | about 30k descriptors; yearly | XML, M | Small: criteria drafting synonyms in English. The Japanese MeSH (医中誌) is licensed | P2 |
| MEDIS 標準病名マスター (MEDIS-DC) | **Site now; ship after OK** ✓: "どなたでも自由にダウンロードして使用できます。ただし、医療機関以外での使用若しくは配布目的で利用する場合は、「使用許諾申請書」を提出し、許可を得る必要があります"; modified copies must name MEDIS | about 27k 病名 + 修飾語 + index; Ver.5.19 next; several updates a year | CSV (Shift_JIS), S (loader exists, D-137) | 標準病名 → ICD-10 for SS-MIX2 PPR-01 without the alternate code; D-130 unknowns drop. Measure: e2e stage 13 and `test_ssmix2_path` unknown counts with the real master | **P0** |
| MEDIS 医薬品HOTコードマスター | Same as above ✓ (HOT is on the list that needs 使用許諾) | about 50 MB (~); monthly | CSV, S (loader exists) | HOT ↔ YJ ↔ receipt ↔ JAN codes: a drug code in any of the four reaches the generic name and the 薬効分類 | **P0** |
| 臨床検査マスター まとめ表 (JLAC Center since 2025-04; was MEDIS) | Site ~ (moved to JLAC Center; terms not read) | Excel; several updates a year | XLSX, M | JLAC10 ↔ receipt lab codes; suggestions for hospital lab codes | P1 |
| JLAC10 code table / JLAC11 list (JSLM) | Site ~ (free download; no licence statement found; ask JSLM) | monthly updates in 2026 | XLSX/PDF, M | Validates JLAC10 shapes and names; JLAC11 now beyond the 43+5 CLINS items (Ver.1.2, 2026-10-10). JSLM no longer publishes a JLAC10↔JLAC11 map | P0 as site; ship after OK |
| JLAC10 → LOINC | none public found | — | — | Ours: map the CLINS 43+5 items and the 114-item 基本コードセット by hand (row 10 of §1) | **P0** (own) |
| YJ via 薬価基準収載品目リスト (MHLW) | Ship ✓ (mhlw.go.jp content is PDL1.0, attribution) | about 14k items; at each price revision (April, plus additions) | Excel, S (other agent) | 12-digit 薬価基準コード whose first 4 digits are the 薬効分類 → drug-class criteria for JP without ATC | **P0** |
| 一般名処方マスタ (MHLW) | Ship ✓ (PDL1.0) | small; with price revisions | Excel, S | Generic names for JP products → ingredient matching | **P0** |
| 診療報酬情報提供サービス masters (傷病名, 医薬品, 診療行為; DX審査支払機構) | Site ~ (site says no modification without permission; redistribution not addressed) | monthly | CSV, S | Receipt-coded SS-MIX2 / claims data; overlaps MEDIS | P1 |
| NHI drug list 健保用藥品項查詢項目檔 (NHIA, nid 23715) | Ship ✓ (Gov Open Data v1; 2026-11-08 review) | tens of thousands of rows (~); daily | CSV/API, S (other agent) | Real NHI drug code → ATC; replaces 24 synthetic rows. Measure: TW synthetic hospital with real codes, `mapping_check` medication rows without ATC | **P0** |
| NHI 醫療服務給付項目 (nid 174450) | Ship ✓ (Gov Open Data v1) | about 10k codes (~); frequent | CSV, S (other agent) | Procedure criteria (dialysis, surgery); also the lab order codes | **P0** |
| NHI → LOINC ConceptMap + `nhi-sct-body-site` (NHIA PAS IG 1.3.0) | Ship ✓ (package licence CC0-1.0; 806 elements counted today) | small | FHIR JSON, S | TW hospital lab code (NHI order code) → LOINC suggestion. Measure: share of TW lab codes suggested and accepted at e2e stage 12 | **P0** |
| MOHW LOINC 對照 project (2025–) | unverified (no published table found) | — | — | Watch; would supersede our NHI map | P2 |
| TFDA 藥品許可證 (nid 9122 all, 9123 active) | Ship ~ (Gov Open Data v1; weekly) | ZIP, large | JSON, M | Licence number → ingredients and zh-TW indications; no ATC field. Small gain over the NHI list | P1 |
| OMOP vocabularies (Athena) | per vocabulary (SNOMED needs a licence; others vary) | GBs | CSV, L | Only useful with OMOP export (moved after the pilot) | P2 |

### 2.3 Mappings that raise SQL recall

| Mapping | Source | Lic. | Effect | P |
|---|---|---|---|---|
| ICD-10-CM 2014 ↔ 2023 (TW) | NHIA | Ship ✓ | Older TW records match today's lists | **P0** |
| WHO ICD-10 → ICD-10-CM | none published; ours: same 3-character category → CM family prefix as a grouper (D-113 style) | Ship (own, code strings only) | A WHO-only code from MEDIS becomes "in family" instead of `unknown_code_system` (D-137 keeps it unknown today). Measure: `test_ssmix2_path` with WHO-only codes | **P0** |
| MEDIS 病名 → ICD-10 | in the MEDIS master | as row 8 | as above | **P0** |
| JLAC10 → LOINC | ours (CLINS 43+5, 基本コードセット 114) | Ship (own) | JP lab criteria | **P0** |
| YJ/HOT → ATC | no free table (KEGG has one, paid) | — | Use 薬効分類 → class instead (ours); ATC only for TW | **P0** (own) |
| NHI drug → ATC | in the NHI list | Ship ✓ | TW drug criteria | **P0** |
| NHI lab → LOINC | PAS ConceptMap | Ship ✓ | TW lab criteria | **P0** |
| Local units → UCUM | UCUM + ours | Ship | value criteria | **P0** |

### 2.4 Drug knowledge for eligibility

| Source | Lic. | Effect | P |
|---|---|---|---|
| Our drug-class table (for example anticoagulants → B01A, B01AE, B01AF; platinum → L01XA), with 薬効分類 and NHI equivalents, in ja / zh-TW / en | Ship (we write it; ATC codes as identifiers, no WHOCC text) | "On anticoagulants", "prior platinum" compile without the LLM. Measure: Chia drug-class atoms mapped | **P0** |
| ATC classes via WHOCC | No (see 2.2) | — | — |
| RxClass (NLM API; sources ATC, MED-RT, FDA EPC) | Online API only; MED-RT and FDA EPC are public domain ~ | Could seed the class table offline (EPC/MED-RT files) | P1 |
| DailyMed SPL (NLM) / openFDA (FDA) | Ship ~ (public domain / CC0) | US labels; little for JP/TW drugs | P2 |
| ChEMBL (EMBL-EBI) | Ship with share-alike ~ (CC BY-SA 3.0) | Mechanism → class; SA burden | P2 |
| DrugBank | **No** without a paid commercial licence (open data CC BY-NC) | — | — |
| PMDA 添付文書 (XML via メディナビ, registration) | Site / unverified: bulk download needs PMDA メディナビ registration and the "添付文書XMLコンテンツ利用方針" (not read); texts belong to the MAHs | Contraindication text for drafting; not needed for SQL | P2 |
| Taiwan TFDA 仿單 | unverified | as above | P2 |
| KEGG DRUG (JP → ATC) | No (paid licence) | — | — |

### 2.5 Clinical knowledge for drafting and the models

| Source | Lic. | Effect | P |
|---|---|---|---|
| CTCAE v6.0 (NCI, July 2025) + v5 → v6 map | Ship ~ (US public domain). MedDRA codes inside the file: ship terms only unless MedDRA licensing is confirmed | AE form: pick a CTCAE term; grade text shown to the person who grades (D-129 unchanged) | **P0** |
| CTCAE v5.0 日本語訳 JCOG版 | Ask JCOG (unverified) | ja term labels | P1 |
| RECIST 1.1 (EORTC, journal article) | definitions only; we write our own summary | Drafting prompts and the AE/response forms | P1 |
| ECOG PS / Karnofsky | Ship ~ (widely published; ECOG-ACRIN allows free use with attribution, not re-read) | Value set for "ECOG 0–1" criteria; note judge context | **P0** |
| eGFR and CrCl formulas: Japanese eGFR (JSN 2009) and eGFRcys, Cockcroft–Gault, BSA (DuBois). CKD-EPI 2021 exists in `tb_common.derived` | Ship (formulas) | JP protocols ask for 日本腎臓学会式 or CrCl; CKD-EPI alone misclassifies near the cut-off. Measure: FEAS eGFR-step counts on the JP synthetic hospital, CKD-EPI vs JSN | **P0** |
| Lab reference ranges: the record's own range first; JCCLS 共用基準範囲 (40 analytes) as fallback | JCCLS terms unverified: Site/ask | "> 3 × ULN" criteria when the feed has no range. Measure: value atoms with ULN made unknown vs decided | P1 |
| HPO (Monarch) | ~ (custom permissive licence, not re-read) | Rare-disease phenotype terms; little for SQL | P2 |
| MONDO | Ship ~ (CC BY 4.0) | Disease synonyms, cross-references to ICD-10; drafting help | P2 |
| Disease Ontology | Ship ~ (CC0, not re-read) | as MONDO | P2 |

### 2.6 Language resources for ja and zh-TW notes

| Source | Lic. | Size/upd. | Effect | P |
|---|---|---|---|---|
| Hyakuyaku 百薬辞書 (NAIST) | Ship ✓ (CC BY 4.0) | HYAKUYAKU_202107; static | Brand, abbreviated and English drug names in ja notes → generic name. Used for note retrieval (FTS synonym expansion) and name matching | **P0** |
| JMED-DICT mini (NAIST, SIP) | Ship ✓ ("商用利用可"; the ICD-10 and JLAC10 link columns need a separate inquiry); download after a short survey | about 100k disease, 30k drug, 10k body-part and 10k test surface forms; English and Chinese forms (ZH script unverified); v1.1.1, 2025-04 | ja synonyms to codes (SNOMED-IPS, HPO, 薬効分類, 一般名処方, HOT links) | **P0** (without the ICD/JLAC links until NAIST says yes) |
| MANBYO 万病辞書 (NAIST) | Ship ✓ (CC BY 4.0) but its ICD-10 and 標準病名 columns derive from the MEDIS master, so ship them under MEDIS's permission | MANBYO_202106; static | Clinical 病名 surface forms → ICD-10; feeds the local-code suggestions for 病名 as written | P1 (with the MEDIS permission) |
| J-MeDic full / JMED-DICT full | Paid ("要問い合わせ") | — | Larger coverage | P2 |
| NAER 醫學學術名詞 and 兩岸對照名詞 (國家教育研究院; data.gov.tw 15314 and others) | Ship ~ (Gov Open Data v1, from the dataset pages) | tens of thousands of en ↔ zh-TW terms (~) | zh-TW ↔ en names for zh-TW criteria and nursing notes; the mainland-name column lets us convert Simplified resources | **P0** |
| MedTxt corpora (NAIST; in `.cache/medtxt`, 1.4 MB) | Eval (CC BY 4.0) | — | Measurement only (`eval/medtxt`) | Eval |
| Abbreviation lists (en: published clinical abbreviation databases; ja / zh-TW: none found) | unverified | — | TW physician notes are English with abbreviations ("DM c/w HTN"). A small list of our own (about 300 entries) from the TFDA criteria and the field research | P1 (own) |

### 2.7 Evaluation and tuning data (never shipped)

| Set | Licence | Use | Status |
|---|---|---|---|
| TREC CT 2021/22 (+2023) | NIST, research | N-12 gate (3.1 % wrongly dropped on the PRO 6000), judge regression | in use (`eval/trec_ct`) |
| Chia | CC BY 4.0 | routes; **new: term coverage before/after** | in use (`eval/chia`) |
| LCT corpus | CC BY 4.0 | second extraction gold set with values/units | not yet |
| EliIE | licence not found | — | skip |
| Criteria2Query / Criteria2SQL | no licence file | — | skip |
| n2c2 2018 track 1 | DUA | real-note cohort selection | only with a DUA |
| MIMIC-IV demo (FHIR, CSV) | ODbL | open-data e2e, CSV/FHIR parity | in use |
| MedTxt-CR/RR, MedTxt-RR-TNM, NTCIR-13 MedWeb, JMED-LLM tasks | CC BY 4.0 (some JMED-LLM tasks NC) | ja note judging, ja/en/zh negation | MedTxt in use; others not yet |
| TFDA zh-TW criteria ↔ CT.gov twins | Gov Open Data v1 | zh-TW drafting accuracy | not yet |
| UMIN-CTR | NC | internal parser QA only, legal to confirm | not yet |
| CHIP-CTC, PMC-Patients, MMedBench, TMMLU+ | unclear or NC | — | skip |

## 3. Measuring the gains

Rule: each P0 source lands as its own commit with a before/after line in the PR, from the evals we already run. Nothing
that changes a decided answer may raise N-12 above its 5 % gate.

| P0 source | Metric | How | Before |
|---|---|---|---|
| LOINC, UCUM, ICD-10-CM FY2027, TW 2023 ICD, NHI drug/service lists, class table | **Term coverage**: share of condition, drug and lab atoms in Chia's 6,660 filter-routed criteria that map by exact name or synonym; share left to the LLM or unmapped; precision on 200 hand-checked atoms | New small script over the Chia entities and `terminology.mapper` (S). Repeat on the TFDA zh-TW criteria for zh-TW names | run on current master first; target ≥ 70 % mapped, ≥ 95 % precise |
| MEDIS 病名/HOT, 薬価, WHO → CM bridge, 薬効分類 table | D-130 `unknown_code_system` patients | `tests/integration/test_ssmix2_path.py` and `e2e_simple` stage 13, with the real masters loaded by the site loader (not committed) | 287 / 276 patients (diagnoses / medicines) without lookups, 400-patient hospital |
| NHI → LOINC map, JLAC10 → LOINC (own) | Suggestions accepted at site setup; `mapping_check` rows without LOINC | `e2e_simple` stage 12 with real NHI lab codes in the IT dump; `tools/mapping_check.py` | current suggestions come from 14 JLAC10 rows and the analyte words |
| CT.gov JP/TW subset, TFDA trials | (a) outbound calls during drafting = 0; (b) zh-TW vs en IR agreement on 200 TFDA ↔ CT.gov twins | network sheet with the offline default; `tools/parser_compare.py` over the twins | live CT.gov today |
| Hyakuyaku, JMED-DICT mini, NAER | Evidence retrieval and note judging in ja / zh-TW: block rates and wrongly dropped eligible pairs | `tools/medtxt_eval.py`, `tools/trialgpt_compare.py` (ja, zh-TW) with synonym expansion on and off; then N-12 on the card | current `eval/medtxt` and `trialgpt_compare` scores; N-12 3.1 % |
| JSN eGFR, Cockcroft–Gault | FEAS step counts for eGFR/CrCl criteria on the JP synthetic hospital; GOUT-COH unchanged | `tools/hospital_sim.py scale` (JP), `e2e_simple` pinned GOUT-COH | CKD-EPI only |
| CTCAE v6 | AE entries with a coded term in `e2e_simple` stage 5 | form test | free text only |

The two hospital-scale numbers (`hospital_sim project`) are re-run once at the end, after all P0 sources are in.

## 4. Corrections to earlier decisions and documents

1. **D-122 "Not done" and D-137 "Licensed MEDIS / JLAC10 / YJ loader".** These assumed the masters are licensed. They
   are not.
   - MEDIS masters are a free download for anyone, with no registration. Hospitals use them without applying.
   - A vendor that distributes them, or uses them outside a medical institution, must file a 使用許諾申請 and get
     permission. Modified copies must name MEDIS. (Verified today on the MEDIS terms page.)
   - The lab master moved to JLAC Center in April 2025. JLAC10 tables are free downloads from JSLM with no licence
     statement.
   - The 12-digit 薬価基準 codes (the 薬効分類 and the YJ stem) are in MHLW's list under PDL1.0, which we may ship.

   Change:
   - Call these "standard masters", not "licensed".
   - Ship 病名 and HOT once MEDIS grants permission. Until then, the "not loaded" message should say they are free to
     download from MEDIS.
   - Ship the 薬価 list now.
   - Keep the loader; it is right as built.
2. **2026-11-08 open-data survey, MEDIS row** ("old terms allow internal use only, no redistribution", marked ✗). That
   row is superseded by the current terms in correction 1. **NHI PAS IG row** ("probably CC0, not read"): verified CC0;
   it contains the NHI → LOINC ConceptMap (806 codes), which belongs in the baseline, not only in validation.
3. **D-137 "A licensed MEDIS file gives WHO ICD-10; a code is used only where it is also an ICD-10-CM code".** This stays
   safe, but it loses recall. Suggested change: treat a WHO-only code as inside its ICD-10-CM category family. That
   uses the D-113 family rule, needs no WHO text and is still fail-closed.
4. **D-122 / mapper docstring**: "a site's official NHI / LOINC releases". The NHI lists are Gov Open Data v1 and LOINC
   allows commercial redistribution with notice. The vendor can ship them, so the site does not have to supply them.
5. **Taiwan coding versions.** NHIA moved claims to the 2023 ICD-10-CM/PCS edition on 2025-01-01. Records from earlier
   years use the 2014 edition. TrialBox ships only CMS 2026 ICD-10-CM, so it needs the NHIA 2014 ↔ 2023 map for
   historical data. This was not noted in D-122.
6. **JAPIC-CTI and JMACCT** need no handling of their own. Their records have been in jRCT since 2023-03-06.
7. **D-138 open point (`TB_CTGOV_MODE=live` by default).** With the shipped registry subset, the wizard can default to
   offline, which makes outbound truly none.

## Sources (read 2026-11-09 unless marked)

- MEDIS terms: https://www.medis.or.jp/4_hyojyun/medis-master/riyou/index.html ; 病名: https://www2.medis.or.jp/stdcd/byomei/ ;
  HOT: https://www2.medis.or.jp/master/hcode/ ; lab master move: https://www2.medis.or.jp/master/kensa/index.html
- JSLM JLAC10/11: https://www.jslm.org/committees/code/ ; JLAC Center: https://www.idial.or.jp/jlac_center.html
- MHLW site terms (PDL1.0): https://www.mhlw.go.jp/chosakuken/index.html ; 診療報酬情報提供サービス FAQ:
  https://shinryohoshu.mhlw.go.jp/shinryohoshu/faq/
- jRCT terms: https://jrct.mhlw.go.jp/agreement ; migration notice: https://www.med.or.jp/dl-med/doctor/jmacct/MHLW20230302.pdf
- WHOCC ATC/DDD: https://www.whocc.no/copyright_disclaimer/
- LOINC licence: https://loinc.org/license (via search summary; the page returned 403 to the fetcher)
- ICD-11 licence: https://icd.who.int/en/docs/ICD11-license.pdf ; WHO classifications licensing:
  https://www.who.int/about/licensing/classifications/en/ (~)
- SNOMED members: https://www.snomed.org/members ; IPS Terminology:
  https://www.snomed.org/news/snomed-international-releases-an-open-terminology-to-broaden-clinical-data-interoperability (~)
- RxNorm prescribable: https://www.nlm.nih.gov/research/umls/rxnorm/docs/rxnormfiles.html (~)
- ICTRP: https://www.who.int/tools/clinical-trials-registry-platform/network/who-data-set/downloading-records-from-the-ictrp-database (~)
- CTCAE v6: https://dctd.cancer.gov/about/news-events/news/2026-news/ctcae-updated-version-6 (~)
- NAIST dictionaries: https://sociocom.naist.jp/manbyou-dic/ , https://sociocom.naist.jp/hyakuyaku-dic/ ,
  https://sip3-d2.naist.jp/jmed-dict.html
- NHIA ICD-10-CM/PCS 2023 中文版: https://data.gov.tw/dataset/177507 (~) ; NHI PAS IG package:
  https://packages.fhir.org/tw.gov.mohw.nhi.pas/1.3.0 (downloaded, licence and ConceptMap read)
- TFDA 藥品許可證: https://data.gov.tw/dataset/9122 (~); NAER terms: https://data.gov.tw/dataset/15314 (~)
- CT.gov counts: https://clinicaltrials.gov/api/v2/studies?countTotal=true (queried 2026-11-09)
- Earlier items: `docs/reviews/2026-11-08-open-data-candidates.md` (TFDA, NHI lists, UMIN, MedTxt, LCT)
