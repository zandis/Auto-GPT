# TB-DS-10 Terminology and Mapping Specification

| Field | Value |
| --- | --- |
| Document | TB-DS-10 Terminology and mapping |
| Version | 0.4 (reference for build step 2) |
| Date | 2026-11-07 |
| Owner | Aimedics (author: Claude, for Changfu Kuo) |
| Status | Reference for build step 2 (TB-DS-20); site-master checks are hospital stage (H). Closes review finding M-05 (TB-REV-006). Supports FR-ING, FR-FEAS, FR-SCR, FR-EDC, FR-TC (TB-DS-01). |
| Approvals | Product owner: — · Clinical informatics JP: — · Clinical informatics CGMH: — · Pharmacist reviewer: — · Lab reviewer: — |
| Canonical values | TB-DS-00 BD-12 (FHIR R4 4.0.1, JP Core 1.2.0, TW Core pinned, OMOP 5.4, CTCAE v5.0). |

## 1. Purpose and scope

How TrialBox turns hospital codes and words into the concepts that criteria use, for Japan and Taiwan: code systems, mapping tables, the build and update process, unit conversion, text normalisers and the rule book. Licence status is marked; anything marked **unverified** must be checked before the table is shipped.

**Built today (`services/criteria_compiler/terminology/`):** Parquet tables `icd10cm_tw`, `nhi_drug` (with ATC), `atc`, `loinc_tw` (with `component_of`), `nhi_order`, `department`, `synonyms`, built by `tools/build_terminology.py` from `terminology/src/*.csv`. Mapper steps: exact display name → synonym table (codes or code-prefix groups) → LLM `concept_map` over top-20 lexical candidates, always flagged `needs_review`. Output: FHIR ValueSets with explicit `compose.include[].concept[]`. Normalisation: NFKC + lower-case + whitespace collapse (`norm()`).

**New for Japan [S1]:** MEDIS 標準病名, YJ / HOT drug codes, JLAC10 (and JLAC11 when the site uses it), 診療行為 codes, Japanese synonyms, 和暦 and Japanese text normalisers.

## 1a. Normative references and where each value is confirmed

| Reference | Edition used | Confirms | Status |
| --- | --- | --- | --- |
| HL7 FHIR R4 | 4.0.1 (TB-DS-00 BD-12) | resource and element names, `verificationStatus` | read |
| JP Core implementation guide (JAMI / jpfhir.jp) | 1.2.0, July 2025 | CodeSystem URIs for MEDIS 病名, YJ, HOT, JLAC10 | **to read** — TM-02 |
| MEDIS 標準病名マスター | release in use at the Japan head hospital | 病名交換用コード, 修飾語 codes incl. 「疑い」 | **site master needed** — TM-05 |
| JLAC10 (日本臨床検査医学会) | edition in use at the site lab | analyte codes in §5 | **site master needed** — TM-01 |
| 特定健診 data-format code table (MHLW) | current edition | HbA1c 3D046 (NGSP) / 3D045 (JDS) | to re-read — TM-07 |
| YJ / HOT code masters (MEDIS HOT, 薬価基準) | release in use at the site | drug codes; source for YJ/HOT → ATC | **licence answer needed** — TM-03 |
| WHO ATC/DDD index | 2026 | ATC level-5 ingredient codes | read; redistribution terms in §11 |
| LOINC | 2.8x (current release) | LOINC codes in §5 | read |
| UCUM | 2.2 | unit strings in §5 | read |
| ICD-10 (WHO 2019) and ICD-10-CM (NHI edition) | as in §2 | diagnosis codes | read (TW built) |
| CTCAE | v5.0 (TB-DS-00 BD-12) | §6 grading | to check line by line — TM-04 |

**What each "verify" flag needs.** A flag on a FHIR system URI is closed by reading the JP Core 1.2.0 CodeSystem page (TM-02). A flag on a code (JLAC10 analyte, MEDIS modifier, site LOINC for amyloid or p-tau) is closed only with the site's own master (TM-01, TM-05, TM-06); the synthetic hospital (TB-DS-21) uses the codes as written here, so the build does not wait for them. A flag on a licence is closed by a written answer from the licensor (TM-03, §11). No code in this file was invented to close a flag.

Shared terms: TB-DS-01 Appendix C.

## 2. Code systems

| Domain | Japan source code | Taiwan source code | Canonical concept used by criteria | FHIR system URI | Release |
| --- | --- | --- | --- | --- | --- |
| Diagnosis | MEDIS 標準病名マスター (病名交換用コード + ICD-10 2013 対応) | ICD-10-CM (NHI, 2014 edition and later) | ICD-10 (WHO) at 3–4 characters; ICD-10-CM kept as-is for TW | `http://hl7.org/fhir/sid/icd-10`, `…/icd-10-cm`; MEDIS: JP Core `urn:oid:1.2.392.200119.4.101.6` **(verify against JP Core 1.2.0)** | JP S1 / TW built (S0) |
| Drug | YJ code (12), HOT code (9/13), 薬価基準収載医薬品コード | NHI drug code (10) | ATC (WHO) level 5 ingredient; RxNorm/RxNorm Extension concept optional for OMOP | `http://www.whocc.no/atc`; YJ/HOT: JP Core CodeSystem URIs **(verify)** | JP S1 / TW built (S0) |
| Lab | JLAC10 (17 chars: analyte 5 + identification 4 + material 3 + method 3 + result 2); JLAC11 where adopted | Hospital local code → LOINC (TW LOINC mapping) | LOINC + UCUM unit | `http://loinc.org`; JLAC10: `urn:oid:1.2.392.200119.4.504` **(verify)** | JP S1 / TW built (S0) |
| Procedure | 診療行為コード (医科診療報酬点数表), K-code | NHI order code | local code group per criterion | site CodeSystem | JP S1 / TW built (S0) |
| Department | site list | site list | `department` table | site CodeSystem | built |
| Adverse events | — | — | MedDRA LLT/PT (**licence required**) or CTCAE v5.0 term | `http://terminology.hl7.org/CodeSystem/mdr` | L (was M2) |
| OMOP export | — | — | OMOP standard concepts (Athena vocabularies) | — | L (was C) |

## 3. Japanese diagnosis mapping (MEDIS → ICD-10)

- **Source table:** MEDIS 標準病名マスター (病名基本テーブル, 修飾語テーブル, ICD-10 対応). Each 病名 has a 病名管理番号, 病名交換用コード (8 chars), ICD-10 code; 修飾語 (prefix/suffix) have their own codes.
- **Rules:**
  1. Condition code = ICD-10 from the MEDIS row; keep the MEDIS exchange code as a second coding.
  2. 修飾語 「疑い」 (suspected; code ending in suffix 8002 **verify**) → `Condition.verificationStatus = provisional`; criteria that require a confirmed diagnosis exclude provisional (FR-SCR rule; user can switch per criterion).
  3. 「の既往」「術後」 → `clinicalStatus = resolved` / history flag.
  4. 主病名 flag → `main_dx = true` (lake column, TB-DS-07 §6).
  5. **保険病名 (diagnoses entered for claim purposes):** flag `insurance_only = true` when a diagnosis has no supporting evidence within ±90 days (no matching drug, lab or note mention) and appears only with a test or drug order the same day. Feasibility counts both "all" and "excluding insurance-only"; criterion cards show the flag. Heuristic validated on the gold set (TB-DS-04).
  6. Free-text diagnoses without MEDIS code (ワープロ病名) → mapper steps (exact → synonym → model, `needs_review`).
- **Licence:** MEDIS masters are publicly downloadable from MEDIS-DC; redistribution terms **unverified** — ship the build script, not the table, until confirmed.

## 4. Japanese drug mapping (YJ / HOT → ingredient / ATC)

| Step | Rule |
| --- | --- |
| 1 | Read YJ code (or HOT) from the order (RXE-2 / mapping column). |
| 2 | YJ positions 1–7 = 薬価基準 classification + ingredient; map via the MEDIS HOT master (HOT ↔ YJ ↔ レセ電算 code) to the generic name. |
| 3 | Generic name → ATC via the KEGG DRUG / JAPIC mapping or a curated table (**source licence unverified**; fallback: our curated ATC table for criteria-relevant drug classes). |
| 4 | Combination products → one row per ingredient. |
| 5 | Dose form, strength and route kept from the order; 頓用 (as needed) flagged. |
| 6 | Taiwan: NHI drug code → ATC is in `nhi_drug` (built). |

Drug classes used often in criteria (biologics, JAK inhibitors, steroids with prednisolone-equivalent dose, anticoagulants, anti-amyloid antibodies, cholinesterase inhibitors) have curated ATC groups in `synonyms` with a pharmacist review record.

**Prednisolone-equivalent dose** (for criteria like "PSL > 10 mg/day"): conversion table prednisolone 1, methylprednisolone 0.8, dexamethasone 0.15, betamethasone 0.12, hydrocortisone 4 (mg equal to 1 mg PSL **reviewed by pharmacist before use**).

## 5. Lab mapping (JLAC10 / local → LOINC + UCUM)

- **JLAC10 structure:** analyte (5) + identification (4) + material (3) + method (3) + result-type (2). Matching uses analyte + material first, then method where the LOINC method matters.
- **Mapping source:** JSLM JLAC10 master and the JLAC10–LOINC mapping work (**availability and licence unverified**); fallback: curated mapping for the labs used in the pilot studies, reviewed by the lab lead.
- **Pilot core labs (curated, must be complete for build step 1):**

| Concept | JLAC10 analyte (first 5) | LOINC | UCUM unit |
| --- | --- | --- | --- |
| HbA1c (NGSP) | 3D046 (legacy 3D045 = JDS; convert NGSP = 1.02 × JDS + 0.25) — see TM-07 | 4548-4 | % |
| Creatinine | 3C015 | 2160-0 | mg/dL |
| eGFR | 8A065 (calculated) | 62238-1 / 98979-8 | mL/min/{1.73_m2} |
| ALT | 3B045 | 1742-6 | U/L |
| AST | 3B035 | 1920-8 | U/L |
| Total bilirubin | 3J010 | 1975-2 | mg/dL |
| Haemoglobin | 2A030 | 718-7 | g/dL |
| WBC | 2A010 | 6690-2 | 10*3/uL |
| Neutrophils (abs.) | 2A160 | 751-8 | 10*3/uL |
| Platelets | 2A050 | 777-3 | 10*3/uL |
| CRP | 5C070 | 1988-5 | mg/dL |
| ESR | 2B120 | 4537-7 | mm/h |
| RF | 5G020 | 11572-5 | [IU]/mL |
| Anti-CCP | 5G626 | 53027-9 | U/mL |
| HBs antigen | 5F016 | 5196-1 | — (qualitative) |
| HCV antibody | 5F360 | 16128-1 | — (qualitative) |
| Amyloid β 42/40 (plasma/CSF) | site local | 94867-4 (CSF Aβ42/40) | {ratio} |
| p-tau217 | site local | site-specific LOINC **verify** | pg/mL |

**Every JLAC10 analyte code above is to be verified against the site's master before go-live (open item TM-01).** HbA1c is 3D046 (NGSP) with legacy 3D045 (JDS), not 3F015 (review correction); this file now matches TB-DS-02 §6 and TB-DS-04 TC-ING-031 (TM-07).

- **Units:** convert to the criterion unit with UCUM (`pint` with UCUM definitions or a small table): creatinine µmol/L ↔ mg/dL (÷ 88.4); glucose mmol/L ↔ mg/dL (× 18.0); Hb g/L ↔ g/dL (÷ 10); CRP mg/L ↔ mg/dL (÷ 10). Unknown unit → value kept, criterion card shows `unknown — unit` (never silently converted).
- **Qualitative results:** map 「陽性」「(+)」「1+」→ positive, 「陰性」「(-)」→ negative, 「判定保留」→ indeterminate.
- **Taiwan:** local lab code → LOINC in `loinc_tw` (built) with `component_of` for panels.

## 6. CTCAE v5.0 lab grading [L]

Used for AE suggestion tasks (FR-TC, BD-08). Grades computed from LOINC + UCUM values against the patient's baseline (ULN/LLN from the lab's reference range on the result, not a fixed number).

| Term | Grade 1 | Grade 2 | Grade 3 | Grade 4 |
| --- | --- | --- | --- | --- |
| ALT increased (baseline normal) | > ULN – 3.0 × ULN | > 3.0 – 5.0 × ULN | > 5.0 – 20.0 × ULN | > 20.0 × ULN |
| Blood bilirubin increased (baseline normal) | > ULN – 1.5 × ULN | > 1.5 – 3.0 × ULN | > 3.0 – 10.0 × ULN | > 10.0 × ULN |
| Creatinine increased | > ULN – 1.5 × ULN | > 1.5 – 3.0 × baseline; > 1.5 – 3.0 × ULN | > 3.0 × baseline; > 3.0 – 6.0 × ULN | > 6.0 × ULN |
| Neutrophil count decreased | < LLN – 1.5 ×10⁹/L | < 1.5 – 1.0 ×10⁹/L | < 1.0 – 0.5 ×10⁹/L | < 0.5 ×10⁹/L |
| Platelet count decreased | < LLN – 75 ×10⁹/L | < 75 – 50 ×10⁹/L | < 50 – 25 ×10⁹/L | < 25 ×10⁹/L |
| Anaemia (Hb) | < LLN – 10.0 g/dL | < 10.0 – 8.0 g/dL | < 8.0 g/dL | life-threatening (not lab-only) |

Grades are suggestions; the investigator confirms (BD-08). The full CTCAE table is loaded from the NCI file (public domain, US government); the table above is a summary for review and must be checked against the official v5.0 document (TM-04). For abnormal baselines CTCAE v5.0 uses multiples of baseline; implement both rules.

## 7. Taiwan codes [S0, built]

ICD-10-CM (NHI), NHI drug codes with ATC, NHI order codes, TW LOINC mapping, CGMH department list. Source CSVs in `terminology/src/`; site official releases can replace them. CGMH local codes are added through the site mapping (TB-DS-08 ICD-01) and the synonym table.

## 8. Text normalisers

Applied in this order to free text and display names before matching (built steps marked).

| # | Normaliser | Rule | Status |
| --- | --- | --- | --- |
| 8.1 | Character set decode | Shift_JIS / CP932 / ISO-2022-JP / Big5 / UTF-8 detected by source config, never guessed silently | S1 (was M1) |
| 8.2 | NFKC | full-width → half-width alphanumerics, compatibility kana | built |
| 8.3 | Case and space | lower-case Latin, collapse whitespace | built |
| 8.4 | 和暦 / 民國 dates | 令和/平成/昭和/大正 + R/H/S/T abbreviations (R9.1.15, 令9.1.15) → ISO; 元年 = 1; 民國 n = n + 1911 | S1 (was M1) |
| 8.5 | Negation and certainty | 「疑い」「の疑い」「否定」「なし」「(-)」「r/o」「無」「未」→ certainty tags (provisional, negated); scope = same clause | S1 (was M1) |
| 8.6 | Abbreviations | curated list (DM → 糖尿病, RA → 関節リウマチ, AD → アルツハイマー型認知症 **context-dependent: AD also atopic dermatitis**, HT, CKD, MTX, PSL) with study context to disambiguate; ambiguous → `needs_review` | S1 (was M1) |
| 8.7 | Numbers and units | 「8.2%」「８．２％」「mg/dl」 → number + UCUM | S1 (was M1) |
| 8.8 | Okurigana and variants | 糖尿病/糖尿病性, 関節リウマチ/慢性関節リウマチ (old name) via synonym table | S1 (was M1) |

## 9. Rule book format

Site and study rules that change mapping behaviour are stored as YAML in `terminology/rules/` and versioned with the ruleset (TB-DS-12).

```yaml
version: 1
site: jp_head
rules:
  - id: TR-0001
    kind: synonym
    concept: rheumatoid_arthritis
    add: ["関節リウマチ", "慢性関節リウマチ", "RA"]
    codes: {icd10: ["M05", "M06"]}
    reviewed_by: clinical_lead_jp
    reviewed_at: 2026-11-30
  - id: TR-0002
    kind: insurance_only_window
    days: 90
  - id: TR-0003
    kind: unit_conversion
    loinc: "4548-4"
    from: "JDS%"
    to: "%"
    formula: "1.02*x+0.25"
```

Every rule has an ID, a reviewer and a date; the compiler refuses rules without review fields in production mode.

## 10. Build, update and validation

| Step | Rule |
| --- | --- |
| Source download | Admin or Aimedics downloads official releases (MEDIS, JLAC, NHI, LOINC, ATC) outside the hospital; checksums recorded. |
| Build | `tools/build_terminology.py` → Parquet tables + `terminology_manifest.json` (source, version, date, sha256). |
| Ship | Inside the signed update bundle, `kind: terminology` (TB-DS-08 ICD-11). |
| Validate | Golden tests: every pilot criterion concept resolves to the expected codes; unmapped-code rate per snapshot reported (S3 data-quality box, TB-DS-09). |
| Frequency | MEDIS and 薬価基準: quarterly (drug price revisions in April and ad hoc); LOINC: twice yearly; NHI: on release. |
| Change control | Diff report of added/removed codes per concept; clinical lead signs off concepts used by active rulesets (TB-DS-12). |

## 11. Licences

| Source | Use | Licence status |
| --- | --- | --- |
| ICD-10 (WHO) | codes and titles | WHO licence for derivative works — **verify** for academic, free use |
| ICD-10-CM | TW codes | public domain (US CDC) |
| LOINC | lab concepts | free licence, attribution required (Regenstrief) |
| ATC/DDD (WHO) | drug classes | WHO Collaborating Centre terms — **verify** redistribution |
| MEDIS 標準病名, HOT | JP diagnosis and drug | free download — **redistribution unverified** |
| JLAC10/11 (JSLM) | JP labs | **unverified** |
| YJ / 薬価基準 | JP drugs | MHLW public list |
| CTCAE v5.0 | AE grading | US public domain |
| MedDRA | AE terms | **paid licence** (free for some academic uses — verify) |
| RxNorm / RxNorm Extension, Athena | OMOP | UMLS licence / OHDSI terms — later (L) only, with the OMOP export |

## 12. Open items

| ID | Item | Owner | Due |
| --- | --- | --- | --- |
| TM-01 | Verify every JLAC10 code in §5 against the Japan head hospital's lab master. | Japan site lab / IT with the Aimedics engineer | Hospital stage (H): before SAT-JP IQ/OQ (TB-PLAN-01 MS-10, hospital-stage plan) |
| TM-02 | Confirm FHIR system URIs for MEDIS, YJ, HOT and JLAC10 in JP Core 1.2.0. | Aimedics engineer | Build step 2 (the synthetic hospital uses the URIs as written until then). 2026-11-07: the JP Core 1.2.0 artifacts page lists no CodeSystem for MEDIS, YJ, HOT or JLAC10 (only JP Core's own code systems), so the URIs are probably defined as NamingSystems or external systems; still open. |
| TM-03 | Choose and license a YJ/HOT → ATC source. | Product owner (licence) + Aimedics engineer | Build step 2 uses the curated ATC table for criteria-relevant drug classes; a licensed source is needed before a hospital installs (H) |
| TM-04 | Check §6 CTCAE summary line by line against the official v5.0 document. | Aimedics engineer, checked by a site investigator | Before AE suggestions are built (L) |
| TM-05 | Confirm MEDIS 「疑い」 modifier code and 保険病名 heuristic with clinicians at both sites. | Site PIs (Japan, CGMH) | Hospital stage (H): Japan before SAT-JP IQ/OQ; CGMH before SAT-TW IQ/OQ (MS-13), previously planned by 2027-02-12 |
| TM-06 | Site lab codes for amyloid and p-tau assays (AD study). | Japan site lab | Hospital stage (H): before the AD study ruleset is approved for PQ (TB-PLAN-01 MS-12) |
| TM-07 | HbA1c code conflict: v0.1 of this file had 3D045 = NGSP; TB-DS-02 §6 and TB-DS-04 TC-ING-031 have 3D046 = NGSP, 3D045 = JDS. This file now follows 02/04; TB-DS-01 FR-EDC-02 carries no code and defers to this file. Re-read the MHLW 特定健診 code table and the site master and correct whichever is wrong. | Aimedics engineer; Japan site lab | Hospital stage, with TM-01 |

## Change history

| Version | Date | Author | Change |
| --- | --- | --- | --- |
| 0.1 | 2026-11-07 (seq 1) | Claude for Aimedics | First draft. |
| 0.1a | 2026-11-07 (seq 2) | Claude for Aimedics | TB-REV-006b R2-23: owners and due dates for TM-01..06, keyed to TB-PLAN-01 milestones. |
| 0.1b | 2026-11-07 (seq 3) | Claude for Aimedics | TB-REV-006f §R: release cells re-tagged S1 / L per `20-build-map.md` (was M1/M2/C). Reference for build step 2. |
| 0.2 | 2026-11-07 (seq 4) | Claude for Aimedics | TB-REV-006g Q-29, Q-30, S-06, S-08: §1a normative references with the edition used and what each verify flag needs; HbA1c aligned to 02/04 (3D046 NGSP) and conflict recorded as TM-07; remaining M1/M2 tags re-expressed S0/S1/L; change history unsplit with sequence numbers. |
| 0.3 | 2026-11-07 (seq 5) | Claude for Aimedics | TB-REV-006g §R R-28, S-10: §11 OMOP vocabularies later (L) only; TM-01, -05, -06 due dates marked hospital stage; TM-02 and TM-03 keyed to build step 2, TM-02 attempt recorded (JP Core 1.2.0 artifacts page read 2026-11-07, no CodeSystem for MEDIS / YJ / HOT / JLAC10; still open); Status line. |
| 0.4 | 2026-11-07 (seq 6) | Claude for Aimedics | TB-REV-006g §F F-09: TM-07 notes that TB-DS-01 FR-EDC-02 carries no code and defers to this file. |
