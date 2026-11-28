# The data TrialBox needs from a hospital, and how its codes reach the criteria (Taiwan and Japan)

**Reader:** the integrator, the data steward, the hospital's IT and records team.

Lane M, card SDR1, 2026-11-23. A design note: what TrialBox needs, what the product does today, and the gaps it
found. It changes no code path the night runs. It adds a check that can be tested: `tools/mapping_coverage.py`, and
`tools/owner_code_dictionaries.py` for the owner's own dictionaries.

## 要約 (日本語)

TrialBox が病院から必要とするのは、患者基本（生年月日・性別）、病名（ICD-10、診断日と状態）、検体検査結果
（コード・値・単位・採取日時）、処方・注射（薬剤コードと ATC、期間、状態）、処置・手術、受診（日時と診療科）、
バイタル（身長・体重・血圧）、画像・報告書、記録（経過記録など）の構造化データです。出荷済みの選択基準は
ICD-10-CM、LOINC、ATC、NHI 診療行為コード、TrialBox の診療科コードでコード化されています。日本の病院のコードは
次の経路で届きます。標準病名 → ICD-10（WHO）→ 同じコードが ICD-10-CM にある場合のみ ICD-10-CM、JLAC10 → LOINC、
YJ（または YJ の成分 7 桁）→ ATC。SS-MIX2 リーダーは 26 種別のうち 10 種別を部分的に読み、16 種別は読みません。
処置（OMG、診療行為）は読まないので、処置の基準は日本の施設では常に「不明」です。
新しいツール `tools/mapping_coverage.py` は施設のコード表（local_code, local_name, system）について、
領域ごとに基準のコード体系に届くコード数と届かないコードを示します。合成病院（TW と JP）では、
病名・検査・薬剤・処置・診療科の 5 領域とも 100%、報告書は 4 件中 1 件が届きます。
`tools/owner_code_dictionaries.py` はオーナーの端末上でだけ実行し、コード辞書（患者行なし）を読み、件数と
未対応コード名だけを書きます。患者識別子の列を持つファイルは拒否します。

## 摘要（繁體中文）

TrialBox 需要醫院提供的結構化資料：病人基本資料（出生日期、性別）、診斷（ICD-10-CM、日期與狀態）、檢驗結果
（代碼、數值、單位、採檢時間）、用藥（健保藥品代碼與 ATC、期間、狀態）、處置與手術（健保醫令代碼）、就診
（時間與科別）、生命徵象（身高、體重、血壓）、影像與報告、病歷記錄。已出貨的納入/排除條件使用 ICD-10-CM、
LOINC、ATC、健保醫令代碼及 TrialBox 科別代碼。台灣醫院的診斷已是 ICD-10-CM（2016 年前為 ICD-9-CM）；檢驗院內
代碼經對照表轉為 LOINC；藥品經匯出的 ATC 欄或健保藥品開放資料轉為 ATC；科別代碼目前沒有對照表，必須與 TrialBox
的科別代碼相同。新工具 `tools/mapping_coverage.py` 讀取醫院的代碼表（local_code、local_name、system），逐領域
報告多少代碼對應到條件所用的代碼系統、哪些沒有。合成醫院（台灣與日本）五個領域皆 100%，報告類 4 筆中 1 筆對應。
`tools/owner_code_dictionaries.py` 只在擁有者自己的電腦上執行，只讀代碼字典（不含病人資料列），只寫出件數與未對應
代碼名稱；含病人識別欄位的檔案一律拒絕。

## 1. The data TrialBox needs, by domain

The criteria are the shipped rulesets under `rulesets/` (eight: AD-MAB, GOUT-COH, GZQO, NEUR-COH, ONC-OSI, RA-BIO,
RA-COH, RA-JAK; 73 value sets, 91 criteria). A criterion of class `structured` is decided from coded data; `note`
and `mixed` read the notes as well; `human` is answered by a person. The columns are the canonical ones the adapter
reads (`services/adapter/mapping/templates/CANONICAL.md`); a dagger (†) there marks an optional column. Every value
set's code system, size and criteria: `python -m tools.mapping_coverage --criteria-table` (the table is printed from
the rulesets, not kept here, so it cannot go stale).

| Domain | Fields (canonical columns) | Required | Optional | Code system the rulesets use | Criteria that read unknown without it |
| --- | --- | --- | --- | --- | --- |
| Patient | `mrn`, `birth_date`, `sex` | chart number (pseudonymised at ingest), birth date (age), sex | `death_date`, `name`, `id_no`, `phone` (identity only; never reach a criterion) | `sex`: `M` / `F` | every age criterion (AD-MAB-INC-01, GZQO-INC-01, NEUR-COH-INC-03, RA-JAK-INC-01 and the other rulesets' age lines); GZQO-EXC-08 (sex); the eGFR criteria (age and sex enter the equation) |
| Diagnoses | `diag_no`, `mrn`, `icd10`, `diag_date`, `status` | code, date, status (`A` / `R`) | `enc_no`, `recorded_date`, `suspected` (a suspected diagnosis never excludes, D-142), `diag_code_system` (`icd9cm` / `icd10cm`, D-586) | ICD-10-CM (`http://hl7.org/fhir/sid/icd-10-cm`): 30 value sets | 30 value sets in all eight rulesets: gout, RA, T1DM/T2DM, malignancy, pregnancy, stroke, MI, heart failure, TB, infection, VTE, zoster, cognitive impairment, NSCLC |
| Laboratory results | `lab_no`, `mrn`, `local_code`, `result_value`, `unit`, `sample_datetime` | code, value, **unit**, sample time | `item_name`, `result_status` (D-275), reference range, flag | LOINC (`http://loinc.org`) for analytes; TrialBox's `clinical-score` for joint counts, patient global and the EGFR mutation | serum urate, creatinine (eGFR), HbA1c, ALT, ESR / CRP, HBsAg, anti-HBc, IGRA, urine hCG; DAS28 (TJC28, SJC28, PTGA with ESR or CRP); ONC-OSI's EGFR mutation |
| Medications | `rx_no`, `mrn`, `nhi_drug_code` (TW) or YJ / HOT (JP), `atc`, `start_date`, `end_date`, `status` | a drug code that reaches ATC level 5, start, end or duration, status | `daily_dose`, `dose_unit`, `order_date`, `dept_code` | ATC (`http://www.whocc.no/atc`): 15 value sets | ULT, colchicine, GLP-1 RA, methotrexate, csDMARD, biologics and JAK inhibitors, TB preventive therapy, HBV prophylaxis, EGFR TKI, anticoagulants |
| Orders and procedures | `proc_no`, `mrn`, `order_code`, `proc_date` | code, date | `proc_name` | TrialBox's `nhi-order` (NHI 醫療服務給付項目 codes): 1 value set, 2 codes | GZQO-EXC-05 (bariatric surgery) |
| Visits and departments | `enc_no`, `mrn`, `visit_datetime`, `dept_code`, `enc_type` | date, department, type (`OPD` / `IPD` / `ER`) | `staff_id`; appointments (`appointment` table) for the screening lists | TrialBox's `department` codes (RHEU, META, NEUR, PSY, ...) | GZQO-INC-09 (rheumatology or metabolism visit), NEUR-COH-INC-02 (memory clinic visit); the index date of every windowed criterion |
| Vital signs | `vital_no`, `mrn`, `measure_datetime`, `height_cm`, `weight_kg`, `sbp`, `dbp` | time and the measure | any of the four measures may be empty | LOINC, written by the mapping from the column (8302-2, 29463-7, 8480-6; no code list) | GOUT-COH-INC-06 and GZQO-INC-03 (BMI), GZQO-EXC-09 (systolic pressure) |
| Imaging and reports | `rpt_no`, `mrn`, `exam_code`, `exam_date`, `conclusion` | exam code, date | `exam_name` | LOINC 36643-5 for a chest X-ray (the mapping's rule for `RAD-CXR`) | ONC-OSI-DOC-01, RA-BIO-DOC-03 |
| Notes | `note_no`, `mrn`, `note_datetime`, `note_type`, `text` | time, type, text | `enc_no` | note type to a LOINC document code by the mapping | the `note` and `mixed` criteria (GZQO-INC-05 flares, GZQO-EXC-11 current flare, RA-BIO-REN-02, AD-MAB-INC-03, RA-JAK-EXC-06 and the rest: 10 in all) |

A criterion whose data is missing reads **unknown**, never "not eligible" (D-130). A missing domain therefore does not
exclude anyone wrongly; it makes the screen weaker, and the coverage lines of the night count it
(`docs/data/15-the-site-profile.md`, "Coverage lines and the work list").

## 2. How a hospital's codes reach the criteria's code systems today

| Domain | Taiwan (CSV or CGRD-type SQL export) | Japan (SS-MIX2) | Where |
| --- | --- | --- | --- |
| Diagnoses | ICD-10-CM as written (NHI's edition); ICD-9-CM before 2016 mapped only when reference data is loaded (`map:icd9cm->icd10cm`) | 標準病名 (MEDIS) or PRB-10's WHO ICD-10, written `E14.9`; it is given as ICD-10-CM **only when ICD-10-CM has the very same code** (D-314) | `services/adapter/mapping/tw_core/demo_his.yaml:164-175`; `services/adapter/sources/ssmix2/source.py:1617-1620`; `services/adapter/mapping/jp_core/ssmix2_site.yaml:109-110` |
| Laboratory | the site's local code through its lab table (local code to LOINC, unit, factor) | JLAC10 (OBX-3 `JC10`) through the JLAC10 table or the licensed JLAC10 release; the hospital's own code (`99HOSP`, scores) through the same table | `services/adapter/mapping/tw_core/lab_local_to_loinc.csv`; `services/adapter/mapping/jp_core/jlac10_to_loinc.csv`; `services/adapter/sources/ssmix2/source.py:2211-2256`; the site profile's `mapping.lab` table |
| Medications | the export's `atc` column; else the NHI drug list's level-5 ATC when the box has the NHIA open data loaded (D-689) | YJ (RXE-2 or RXE-31) through `yj_to_atc.csv` or the licensed YJ release; else the YJ code's 7-character ingredient stem; HOT and local codes through the site's drug master to YJ | `services/adapter/mapping/tw_core/demo_his.yaml:298-305`; `services/adapter/sources/ssmix2/source.py:55-67`, `source.py:1622-1626`, `source.py:2012-2030` |
| Procedures | `order_code` as written (NHI 醫令代碼) | **not read**: the reader has no procedure type | `services/adapter/sources/ssmix2/source.py:108-114` |
| Departments | `dept_code` as written; no cross-walk | PV1-10 as written; no cross-walk | `services/adapter/mapping/tw_core/demo_his.yaml:124`; `docs/data/15-the-site-profile.md` ("Department codes → names": no profile field) |
| Reports | `exam_code` `RAD-CXR` to LOINC 36643-5; other exams keep their local code | from `<root>/extended/report.csv` (canonical columns); the same rule | `services/adapter/mapping/tw_core/demo_his.yaml:334` |
| Vital signs | the four columns | `<root>/extended/vital.csv` | `services/adapter/mapping/tw_core/demo_his.yaml:229-266` |

What exists today to build and check a site's mapping, before this card:

- **Runbook section 18** (`docs/runbook/18-site-mapping-without-site-data.md`): the steward writes a schema from the
  survey, builds a synthetic site in the hospital's layout, writes the mapping against it and runs
  `tools.synth_site_from_schema check` until only the planted codes are unmapped. It checks rows of a synthetic or
  sample export, not the hospital's code dictionaries.
- **`tools/mapping_check.py`**: the mapping against a real export (missing columns, unmapped lab codes, unit pairs),
  reading rows on the hospital's machine, with `--share` writing the one report that may leave.
- **The site profile** (`docs/data/15-the-site-profile.md`): the lab, 病名, YJ and JLAC10 tables of a site, with
  coverage lines built from a night's files.
- **`tools/terminology_coverage.py`**: how many drafted criteria concepts the terminology resolves (the criteria side,
  not the site side).

None of them answered, from the dictionaries alone and before any night, how many of a hospital's codes reach the
criteria's code systems and which value sets no code of the hospital reaches. That is the new check (section 4).

## 3. SS-MIX2

### The specification and the code masters it relies on (cited, nothing downloaded)

Read from the publishers' pages on 2026-11-23. Only the free JAMI PDFs and the MEDIS field specification were opened.
No master was downloaded, and nothing of them is in the repository.

- **SS-MIX2 標準化ストレージ 仕様書 Ver.1.2j**, and **構成の説明と構築ガイドライン Ver.1.2j** with its コード表.
  - Published by 日本医療情報学会 (JAMI), 標準策定・維持管理部会, dated 2026-08-14 (https://www.jami.jp/jamistd/ss-mix2/).
  - The same set holds the 拡張ストレージ 構成の説明と構築ガイドライン and its 標準文書コード表 (LOINC document codes), also Ver.1.2j.
  - It is MHLW standard HS026 and ISO/TS 24289:2021.
  - It is HL7 v2.5 over the JAHIS exchange standards: 処方 Ver.3.0C, 注射 Ver.2.1C, 臨床検査 Ver.4.0C, 病名情報 Ver.3.1C, 放射線 Ver.2.3, 生理検査 Ver.3.0C and 内視鏡 Ver.2.1.
  - It names these codes: HOT9 for drugs (YJ in RXE-31 since Ver.1.2h); JLAC10 for labs (JLAC11 allowed since Ver.1.2f); MEDIS 標準病名 with ICD-10 for diagnoses; JJ1017 for radiology; LOINC for physiology results and documents.
  - The guideline's data types are 26. ADT: 00, 01, 12, 21, 22, 31, 32, 41, 42, 51, 52, 61. Then PPR-01, OMD, OMP-01/02/11/12, OML-01/11, OMG-01/02/03/11/12/13.
  - The storage tree is `<id 1-3>/<id 4-6>/<id>/<診療日>/<type>/<file>`, with seven-part file names.
- **ICD10対応標準病名マスター Ver.5.18**, MEDIS-DC, revised 2026-06-01 (https://www2.medis.or.jp/stdcd/byomei/download2019.html; field specification https://www2.medis.or.jp/stdcd/byomei/spc518.pdf).
  - It holds the 病名, 修飾語 and 索引 tables.
  - Its ICD-10 column ("ICD10-2013") is the WHO 2013 edition, not ICD-10-CM. That is why the WHO-to-CM step of section 2 decides what a Japanese diagnosis can reach.
  - Ver.5.19 was announced on 2026-11-17.
- **医薬品HOTコードマスター**, MEDIS-DC, monthly; the 2026-10-31 edition (https://www2.medis.or.jp/hcode/).
  - HOT13 is 7 + 2 + 2 + 2 digits.
  - It cross-maps to the 薬価基準収載医薬品コード, YJ, レセ電 and JAN codes. It carries no ATC.
- **YJコード** (個別医薬品コード), distributed by the 医薬品情報標準化推進協議会 (CAPS, http://www.capstandard.jp/), monthly.
  - Its licence terms were **not confirmed**.
- **JLAC10 / JLAC11**, 日本臨床検査医学会 (JSLM). Codes are assigned by the JLAC Center of IDIAL since fiscal 2024 (https://www.idial.or.jp/jlac_center.html).
  - JLAC10 Ver.10.a139 is dated 2026-08.
  - The JLAC11 code list Ver.1.1 is dated 2026-06-08. It covers the national record-sharing set only (43 tests and 5 infection items).
  - The JLAC10-to-JLAC11 table was withdrawn (not one to one). This is why SDR1-04 cannot be closed with a table derived from JLAC10.
  - The licence was **not confirmed** (the JSLM site refused the request).
- **臨床検査マスター まとめ表** (JLAC10 with the 医科診療行為 code), MHLW standard HS014, maintained by the JLAC Center since 2025-04; Ver.3.36, 2026-11-20 (https://www.idial.or.jp/clinicalexam-master.html).
  - Download needs a registration. The licence was **not confirmed**.
- **標準手術・処置マスター**, MEDIS-DC, Ver.20260914, with K-code tables (https://www2.medis.or.jp/stdcd/shujutu/index.html).
- **医科診療行為マスター** (レセ電 基本マスター), 医療情報基盤・診療報酬審査支払機構 (https://www.hpdx.or.jp/seikyushiharai/tensuhyo/kihonmasta/index.html), files on MHLW's 診療報酬情報提供サービス.
  - Its reuse terms were **not confirmed**.
- **MEDIS terms of use** (https://www.medis.or.jp/4_hyojyun/medis-master/riyou/index.html). They apply to the HOT, 病名, 手術・処置 and the other MEDIS masters.
  - A download is free.
  - Use outside a medical institution, or redistribution, needs a written permission. This is why the product never ships them and a site loads its own release (D-137).
- **JP Core 1.2.0**, 2025-07-30, by JAMI's FHIR implementation working group (https://jpfhir.jp/fhir/core/).
  - Its naming systems include MEDIS 病名, HOT7/9/13, YJ, JLAC10, the JAMI 用法 code and the SS-MIX2 診療科 code.
  - The repository's mapping claims JP Core 1.1.0.
- **Mappings to international codes.**
  - No official public JLAC10-to-LOINC or YJ/HOT-to-ATC mapping was found.
  - The WHO ATC index forbids copying for commercial purposes (https://www.whocc.no/copyright_disclaimer/).
  - So the JLAC10, YJ and stem tables stay site-loaded or hand-made from public sources, row by row, as `jp_core/README.md` says.

### What the reader in this repository covers and misses

The reader is `services/adapter/sources/ssmix2/source.py`; the full field-by-field account is
`docs/data/01-what-the-box-reads.md` (D-1252), counted against the 26 data types review 12 §4.9 listed: **0 read in
full, 10 partly, 16 not**. In short, for the criteria:

| Part | State | file:line | What it means for the criteria |
| --- | --- | --- | --- |
| ADT-00 patient | Partly (PID-3, 5, 7, 8, 13, 29, 30) | `source.py:1629-1645` | birth date and sex read: age and sex criteria work |
| ADT-12 / 22 / 52 visits | Partly (PV1-2, 7, 10, 19, 44, 45) | `source.py:108-114` (`TYPES`), `source.py:122` (`CHANGES`), `source.py:1647-1700` | department from PV1-10 as written: the two department criteria need the site to use TrialBox's codes (finding SDR1-02) |
| PPR-01 病名 | Partly (PRB-1 to 18, ZPR) | `source.py:1702-1800` | ICD-10 from PRB-10 first, then PRB-3's alternate, then the MEDIS release, then `byomei_to_icd10.csv`; ICD-10-CM only where the same code exists (finding SDR1-01) |
| OMP-01 / 02, OMP-11 / 12 | Partly | `source.py:166-167`, `source.py:694-701`, `source.py:2012-2030`, `source.py:2068-2130` | YJ, HOT and ATC kept; ATC from the YJ table, the licensed YJ release or the ingredient stem |
| OML-11 検体検査結果 | Partly (OBX-2, 3, 5, 6, 7, 8, 11, 14, 21) | `source.py:168`, `source.py:2211-2256` | JLAC10 to LOINC with its unit; `JC11` is accepted as a system name but looked up in the JLAC10 table (finding SDR1-04) |
| OML-01, OMG-01 to 13 (放射線), OMD (食事) | Not | `source.py:108-114` | no imaging order or report from the standardized storage; reports come from extended CSVs only |
| Procedures (処置・手術, 診療行為) | Not | `source.py:108-114` | GZQO-EXC-05 reads unknown at every Japanese site (finding SDR1-03) |
| Extended storage documents | Partly | `docs/data/01-what-the-box-reads.md` | notes for the `note` criteria; `_contents.xml` and CDA sections not read |
| Vitals, reports, claims | From `<root>/extended/<table>.csv` | `services/adapter/mapping/jp_core/README.md` | the BMI and blood-pressure criteria need a site's vital-sign CSV; SS-MIX2 does not standardise vitals |

The code tables the reader ships are samples, every row `verify` and synthetic: `jp_core/byomei_to_icd10.csv` (32
rows), `jp_core/jlac10_to_loinc.csv` (14), `jp_core/yj_to_atc.csv` (22), and the ingredient stems of
`libs/tb_common/refdata_src/jp_yj_atc.csv` (56). A site loads its licensed MEDIS, JLAC10 and YJ releases with
`python -m adapter.licensed load` (`services/adapter/mapping/jp_core/README.md`); TrialBox never ships them.

## 4. The mapping check that always runs (`tools/mapping_coverage.py`)

A site's code lists are CSV files with `local_code`, `local_name`, `system` and an optional `target_code` (the code
the site's own table already gives). One row per code, no patient. `system` is the system the hospital wrote the code
in: `icd-10-cm`, `icd-10` (WHO), `medis`, `icd-9-cm`, `loinc`, `local-lab`, `jlac10`, `jlac11`, `atc`, `nhi-drug`,
`yj`, `hot`, `nhi-order`, `jp-procedure`, `department`, `local-*` (`tools.mapping_coverage.SYSTEMS`).

    python -m tools.mapping_coverage <lists or a folder> [--json report.json]
    python -m tools.mapping_coverage --synthetic tw        # the shipped synthetic hospitals
    python -m tools.mapping_coverage --synthetic jp
    python -m tools.mapping_coverage --criteria-table      # every value set, its system and its criteria

**It checks codes that are already standard too.** An ICD-10-CM code must exist in the full ICD-10-CM list shipped
with the product; a LOINC code must pass LOINC's check digit; an ATC code must be level 5 (a substance, not a class);
an NHI order code must have the NHI shape; a department code must be one of TrialBox's. A non-standard code is taken
by the route the adapter takes today (section 2) and its target is checked the same way. A site's own cross-walks
replace the shipped samples (`--lab-lookup`, `--jlac10`, `--byomei`, `--yj`, `--ingredient-atc`, `--nhi-drug`).

It prints, per domain, the codes, how many map and by which route, and every code that does not, with the reason;
then how many value sets at least one site code reaches, and the value sets of a listed domain that none reaches (a
criterion that can only read unknown at that site). Vital-sign value sets are filled from the export's columns, not
a code list, and are counted apart.

**The synthetic hospitals' figures** (run 2026-11-23 on `master` `c931068d`):

| Hospital | Diagnoses | Laboratory | Medications | Procedures | Departments | Reports | Value sets reached |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TW (`--synthetic tw`) | 43 / 43, 100 % (direct) | 14 / 14, 100 % (lab table) | 36 / 36, 100 % (NHI list 24, the export's ATC 12) | 4 / 4, 100 % | 9 / 9, 100 % | 1 / 4, 25 % | 70 of 73; the other 3 are vital signs |
| JP (`--synthetic jp`) | 43 / 43, 100 % (標準病名 32, WHO ICD-10 11) | 14 / 14, 100 % (JLAC10 10, hospital codes 4) | 36 / 36, 100 % (YJ 22, the export's ATC alternate 14) | 4 / 4, 100 % | 9 / 9, 100 % | 1 / 4, 25 % | 70 of 73; the other 3 are vital signs |

The three reports that do not map are the memory clinic's MRI, amyloid PET and CSF amyloid (`tools/synth/catalog.py`,
`AD_REPORT_EXAMS`): no mapping gives them a LOINC code, and no shipped criterion reads them (finding SDR1-06). The JP
lists are the codes `tools/ssmix2_export.py` writes for the same patients; its procedures and departments are the TW
codes, because the export copies them (finding SDR1-03 says why a real Japanese site differs). The 100 % figures say
that the synthetic hospitals were built from the same sample tables the check reads; they say nothing about a real
hospital's coverage.

The tests: `tests/unit/test_mapping_coverage.py` (23 tests: both synthetic hospitals, WHO ICD-10 against ICD-10-CM,
standard codes with a wrong check digit or level, the cross-walks and a site's own targets, the YJ stem, the value
sets no code reaches, the owner script's refusals and its summary).

## 5. The owner's own dictionaries (`tools/owner_code_dictionaries.py`)

For the owner's own hospital data: the script runs **only on the owner's machine**, from a checkout of this
repository. The dictionaries never enter the repository, GitHub or a cloud session. How to run it, and what it
refuses, is in `tools/README.md` ("The owner's code dictionaries"). It reads the code dictionaries only (lab items,
orders, departments, diagnoses, drugs; no patient row), runs the check of section 4, and writes one summary file:
counts by domain and route, the unmapped codes with their dictionary names, and the value sets reached. It writes no
path and no other column. It refuses a file with a patient-identifier column (chart number, patient id, national id,
a person's name, birth date, telephone, address, in English, Japanese and Traditional Chinese), a cell shaped like a
Taiwanese national identity number, or a file whose codes repeat (a table of events, not a dictionary). The refusal
names the column header or the line number, never a value.

The summary may come back to the integrator. The unmapped code names are the hospital's dictionary names, not
patient data. The owner reads the summary before sending it: a dictionary name can still name a person (a clinic
called after a doctor, say).

## 6. Findings

In `site-data-requirements/findings.json` beside this page, in the register's `--add-from` form (card SDR1). The
register's keeper adds them.

| Id | Severity | Finding |
| --- | --- | --- |
| SDR1-01 | Medium | A Japanese diagnosis reaches a criterion only when its WHO ICD-10 code is also an ICD-10-CM code (D-314; `source.py:1617-1620`). Every shipped diagnosis value set is ICD-10-CM, and the product has no WHO-to-CM cross-walk, so codes ICD-10-CM split or lacks (E14 diabetes unspecified, I64 stroke unspecified, F00 Alzheimer dementia) read unknown at a Japanese site |
| SDR1-02 | Medium | Department criteria (GZQO-INC-09, NEUR-COH-INC-02) match TrialBox's own department codes. The mappings write the hospital's department code as it is (`demo_his.yaml:124`, PV1-10 on SS-MIX2) and the site profile has no department table, so a hospital whose codes differ (every real one) reads unknown |
| SDR1-03 | Medium | The SS-MIX2 reader reads no procedure type (`source.py:108-114`) and the only procedure value set uses NHI order codes, so GZQO-EXC-05 (bariatric surgery) reads unknown at every Japanese site; no Japanese procedure master (診療行為, K codes) is mapped |
| SDR1-04 | Low | `JC11` is taken as a JLAC system (`source.py:168`) but looked up in the JLAC10 table, which holds no JLAC11 row: a site on JLAC11 gets no LOINC code for its results |
| SDR1-05 | Low | No HOT-to-ATC table ships: a HOT-only drug reaches ATC only through the site's drug master (HOT to YJ); the shipped YJ sample covers 22 of the synthetic hospital's 36 drugs (the other 14 map through the ATC alternate code the export writes) |
| SDR1-06 | Low | The synthetic memory clinic's report kinds (MRI brain, amyloid PET, CSF amyloid) have no LOINC rule in a mapping; no shipped criterion reads them, but an AD criterion on imaging would read unknown |

## 7. SDR2 part 1: WHO ICD-10 codes ICD-10-CM lacks (D-1270)

Finding SDR1-01, closed in part by card SDR2 under the integrator's rulings on #639 (comments 7102870311,
7103067815, 7103442261).

- The reader tries three things in order. First, the very same ICD-10-CM code (D-314). Second, a row of
  `services/adapter/mapping/jp_core/who_icd10_to_icd10cm.csv`, allowed only when its ICD-10-CM code holds all of the
  WHO code's meaning (D-173's "wider"). Third, no code: the WHO code is counted in `missed` and listed.
- The rows today:
  - F00, F00.0 to F00.2 and F00.9 → G30.9;
  - F01.9 → F01.5;
  - A16.0 to A16.2 → A15.0.
- Sources: the ICD-10-CM Alphabetic Index and Tabular List FY2026 (CMS, public domain). Every row is marked `verify`.
- **E14 and I64 have no row.** No ICD-10-CM code holds "diabetes, type not stated" or "stroke, not stated as
  haemorrhage or infarction" without saying more. They stay WHO-only: unknown through the groupers, never false.
  `tests/unit/test_mapping_coverage.py` holds this on GZQO-EXC-01 and GOUT-COH-INC-07.
- A fact that rests on a `verify` row carries the `verify` basis tag, and the mapping check reports "applied, not
  verified" with a count.

## 8. What was not verified

- No real hospital's dictionary was read. The figures are the synthetic hospitals'; the owner's script has run here
  only on synthetic files written by its tests.
- The SS-MIX2 sources in section 3 come from the publishers' pages and the free JAMI and MEDIS PDFs. Items marked
  "not confirmed" there were not settled, and no licensed file was downloaded.
- The check follows the adapter's routes as this page cites them; it does not run the adapter. A difference between
  the two (a route added to the reader later) would show as a difference between this check and the night's coverage
  lines, which this card does not compare.
- WHO ICD-10 codes are checked against the shipped ICD-10-CM list only; no WHO ICD-10 list is in the repository, so a
  code that is in neither is reported "no same ICD-10-CM code", not "not a WHO code".
