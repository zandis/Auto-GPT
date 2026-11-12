# TB-DR2-11 Standards: how well each one is really incorporated

| Field | Value |
| --- | --- |
| Document id | TB-DR2-11 |
| Date | 2026-11-12 |
| Tree | `514ae9b` (branch `claude/deep-review-2026-11-12`) |
| Area | 11. Standards (prefix `STD`) |
| Read | `services/omop`, `services/lake/{source,flatten}.py`, `services/adapter` (mapping, sources, validate, pipeline), `services/edc/{odm,cdash,store}.py`, `services/datacore/export.py`, `services/criteria_compiler` (CQL path), `libs/tb_common/{labunit,labvalue,audit,refdata_jp,refdata_tw}.py`, `tools/{omop_parity,twcore_check,gen_traceability,audit_verify,fetch_jvm_deps.sh}`, `NOTICE`, `docs/licences/register.csv`, `docs/validation/*`, `docs/plan/{25-vmp,25-traceability.csv,intended-use,snomed-inquiry,28-master-plan-v6}`, D-311, the CI workflow, the previous `05a` and `05b` |
| Run (all on synthetic data) | (1) 12 standards test files, 198 passed: `test_labvalue`, `test_lab_units_per_row`, `test_unit_check`, `test_unit_scales`, `test_japan_icd10`, `test_ssmix2_hardening`, `test_fhir_inbound_contract`, `test_fhir_packages`, `test_licence_register`, `test_notice`, `test_vocab`, `test_omop_athena`. (2) 5 more files, 84 passed, 1 skipped (the local CQL engine is not fetched): `test_edc_t115` (ODM against the CDISC XSD, with `xmllint`), `test_odm_import`, `test_ae_grading_d396`, `test_edc_signing_d281`, `test_standards_conformance`. (3) `make contracts-check`: up to date. (4) `tools.licence_register --check`: 32 rows, 163 shipped data files, 0 problems. (5) `tools.omop_parity --sets synthetic` was started and **stopped by its 580 s limit without a result** (the machine's load average was about 20; the tool's own note says about 2.5 minutes); the OMOP numbers below are from the committed `eval/omop_parity/report-ci.json`, not from a run of mine. (6) Seven throwaway probes in the scratch folder `STD/`: `audit_poc.py`, `audit_poc2.py` (tamper tests on the audit chain and the signed heads), `icd9.py` (Taiwan ICD-9-CM rows through the TW mapping), `lab.py` (lab rows through the TW mapping), three inline unit and presence probes, and a 15-row sample of the traceability matrix |
| Not run | The HL7 FHIR validator jar and the CQL translator: `.cache/jvm` is absent on this machine and `make jvm-deps` downloads about 105 jars and the validator, which I did not do on a machine shared by 13 reviewers. So `tools/twcore_check.py` and `tools/cql_path_check.py` (the CI job `standards`) were read, not run. `omop_parity` sets `public` and `mimic`. A real REDCap, a real SS-MIX2 vendor file, a real Athena bundle, licensed MEDIS / JLAC10 / YJ masters. The whole test suite (not mine) |
| Deviation from the brief | PostgreSQL could not start under the session scratch folder (`/tmp/claude-0` is reset to mode 700 between commands, so the `postgres` user cannot reach it). I used `TB_TEST_ROOT=/var/tmp/tb-dr2-std/root` for the tests that need a database, stopped its cluster and removed the folder at the end. Nothing else was written outside the scratch folder |

Scores used: **nominal** (the name or the shape is used, the rules are not met), **partial** (correct in the main, known gaps),
**substantial** (the part used meets the standard's rules and a check proves it at every build), **conformant** (a
recognised validator or schema passes on the whole output).

## 1. Reading in ten lines

1. Most of the previous review's data-standards Highs are fixed in code with tests: the unit Blocker, Japan's WHO ICD-10,
   the SS-MIX2 decoding and OBX reading, Japanese presence results, the stale rulesets, the REDCap version call, the
   Part 11 claim in the ODM file, the licence register and NOTICE.
2. The standards that carry the product are **FHIR R4 as the internal shape** (substantial), **ODM 1.3.2** (conformant to
   the XSD, tested at every build), **JP Core 1.1.0 and TW Core 1.0.0 rule checks** (substantial for what is emitted).
3. **OMOP is still a parallel store.** With no Athena bundle on any box, every standard concept id is 0 (measurements and
   units too); the ids that are filled are local surrogates from 2,100,000,000. Nothing queries OMOP except its own
   export back into the lake's shape. The default lake source is still `legacy`.
4. **New, by a run:** Taiwanese diagnoses before 2016-01-01 are ICD-9-CM. The TW mapping labels them ICD-10-CM (and
   TW Core "2014 edition"). `714.0` (rheumatoid arthritis) leaves the adapter as ICD-10-CM `714.0`. Ten or more years of
   CGRD history cannot be read by any value set (STD-001).
5. **New, by a run:** the signed audit heads work, but nothing on a box ever signs one. No timer, no scheduled job, no
   `doctor` check. Without them a deleted event with a recomputed chain and a rewritten `HEAD.json` verifies as PASS
   (STD-002).
6. The traceability matrix is nominal: 273 of 273 rows "planned", generated from the superseded plan v5. In a sample of
   15 rows, 11 test ids exist in no test file and several rows pair a requirement with an unrelated test (STD-003).
7. Units: there is no UCUM library; a hand table of about 60 spellings does the work and is safe (unknown, never wrong).
   But `IU/L` for enzymes and `×10^3/μL` are not read, which will blank liver and blood-count criteria at a Japanese
   site that prints those spellings (STD-004).
8. Part 11 / ER-ES: the controls are much better (keyed signature over the whole act, record lock, append-only trail,
   two components at signing, OIDC signing). By D-311 there is no assessment document, no IQ/OQ/PQ and no signature on the
   VMP. So the truthful claim is "designed to Part 11 controls, not assessed, not validated".
9. Over-engineering for go-live: two lake sources forever, the OHDSI-conformance work on a store nobody queries, and a
   whole HAPI FHIR server plus 105 JVM jars kept on the box so that a second criteria engine (CQL) can agree with SQL.
10. Counts: **21 findings: 0 Blocker, 0 Critical, 6 High, 10 Medium, 5 Low.**

## 2. Status of the previous review's findings

### 2.1 `05a-data-standards.md` (Blocker, Critical, High)

| Old ID | Severity | Status | Evidence |
| --- | --- | --- | --- |
| STD-001 (05a) adapter never reads the row's unit | Blocker | **fixed** | By a run (`STD/lab.py`): `CRE, 88, umol/L` gives no value and `dataAbsentReason` text `unit_mismatch`; `CRE, 1.0, MG/DL` gives `1 mg/dL`. `tests/unit/test_lab_units_per_row.py` passes (36 conversion pairs, the JP OBX-6 path, `cgrd_sql`). Remaining gaps are the new STD-004 |
| STD-010 Japan's ICD-10 handled as ICD-10-CM | High | **fixed** | `jp_core/ssmix2_site.yaml:27, 96-97` (WHO coding always, ICD-10-CM only when the same code); `test_japan_icd10.py` passes |
| STD-013 death flag without a date | High | **fixed** | `lake/flatten.py:412-413` (`deceasedBoolean`), `ssmix2/source.py:473` (PID-30); `test_fhir_inbound_contract.py` passes |
| STD-020 SS-MIX2 decoding strict; one file stops the night | High | **fixed** in code; never tried on a vendor file | `ssmix2/hl7.py:86-121` (ISO-2022-JP family, cp932 fallback, strict), quarantine with a threshold (`source.py:385-395`); `test_ssmix2_hardening.py` passes |
| STD-021 OML-11 read too simply | High | **fixed** in code | `source.py:642-660, 760` (OBX-2, OBX-11, OBR-7 / SPM-17 fallback, `C` replaces, `D` tombstone) |
| STD-022 no Japanese or Chinese qualitative result | High | **fixed** | By a run: `HBSAG 陽性` gives LOINC answer `LA6576-8`; `(-)` gives `LA6577-6`; 17 spellings probed, `±` and `判定保留` stay unknown. One gap: `Trace` returns None (falls to text; safe) |
| STD-030 OMOP standard concepts can never be filled | High | **partly** | The mechanism exists (`omop/vocab.py:224-250`: `Maps to`, ATC to RxNorm ingredient; Athena loader with an allow-list, `vocab_load.py:800+`; `test_omop_athena.py` passes on a test extract). No real Athena bundle has been loaded anywhere; conditions stay 0 by decision (no SNOMED). See new STD-006 |
| STD-040 committed rulesets older than the family expansion | High | **fixed** | `rulesets/RA-BIO/valuesets/VS_RHEUMATOID_ARTHRITIS.json` now holds 418 codes (was 5); active TB 61 (was 3) |
| STD-042 no YJ to ATC source at scale | High | **partly** | The path exists: order line to YJ 7-character stem to ATC (`source.py:295-301, 557-566`; `refdata_jp.ingredient_atc`), and a site drug master is read. The shipped stem table has 56 rows (`libs/tb_common/refdata_src/jp_yj_atc.csv`); the previous review sized the need at about 2,500 ingredients. See new STD-008 |
| STD-060 REDCap `content=version` parsed as JSON | High | **fixed** | `rc_bridge/client.py:136-139` reads plain text; pinned in `test_edc_signing_d281.py`. Still never run against a real REDCap (the only cassette is `rc-sim-16.0.10.json`) |

Mediums of 05a, checked in passing: STD-011 TW Core slices **fixed** (TW Core code systems by record date,
`demo_his.yaml:149-151`; rule file `twcore_rules.json`; CI job `standards`); STD-032 39 tables **fixed** (migration 5);
STD-031 domain routing **fixed** but inert without a vocabulary; STD-041 edition map **open** (new STD-007);
STD-044 licence hygiene **mostly fixed** (new STD-012 for what is left); STD-062, STD-063 **fixed** (units as
`MeasurementUnit`, IE / DS / AE tags, CTCAE grade); STD-033 `cdm_version_concept_id` **open** (new STD-019).

### 2.2 `05b-regulatory-standards.md` (Critical, High)

| Old ID | Severity | Status | Evidence |
| --- | --- | --- | --- |
| REG-007 legal basis memo | Critical | out of scope by owner rule | D-311 B26; plan v6 §0.3 item 4 |
| REG-010 promises made to IRBs ahead of the code | Critical | out of scope by owner rule | D-311 B4, B23 |
| REG-014 real chart text can be pasted into the hosted demo | Critical | **fixed** (read, not walked) | `services/console/demo_guard.py`, `i18n_demo.py` (banner and acknowledgement in three languages), flag `demo.mode` (T-502). The walk belongs to the UX reviewers |
| REG-001, REG-002 Japanese rule changes (GCP ordinance, ethical guidelines) | High | out of scope by owner rule | T-642 struck (D-311 B17) |
| REG-008 "pseudonymised" read as 仮名加工情報 | High | out of scope by owner rule | T-646 struck |
| REG-009 opt-out notices | High | out of scope by owner rule | T-646 struck |
| REG-015 PoC data-handling statement | High | **fixed** | acknowledgement gate stored as audit event `demo.ack` (T-502); `docs/poc/` |
| REG-016 clinician own-patient view | High | **partly** | T-314 restricts the view; not verified by me (authorisation belongs to another reviewer). The consultant's opinion was struck (D-311 B27) |
| REG-021 ODM file claims Part 11 and ER/ES | High | **fixed** | `services/edc/odm.py:42` `LEGAL_REASON = "Electronic signature of the person named; see the site's validation summary"`; pinned by a test |
| REG-022 no inventory of GxP records | High | **fixed** | `docs/validation/record-inventory.md` (30 records with class, system of record, keeper, retention, export, audit events), checked against `CREATE TABLE` by `tools/gen_traceability.py` |
| REG-023 no map to ICH E6(R3) §4; no procedures | High | **open by owner decision** | T-647 struck (D-311 B27); `docs/validation/README.md:27-28` lists `e6r3-section4.md` as "not here" |
| REG-024 source and copies not defined for prefill | High | **partly** | The signature meaning now says "compared each value with the source cited beside it" (`edc/service.py:69`); the monitor's source page exists (T-303). `source-and-copies.md` was struck (B27) |
| REG-025 a directory account cannot sign | High | **fixed** | `console/edc_pages.py:66, 358-436` (`oidc+mfa` re-authentication at the provider; no second local identity) |
| REG-027 VMP is a frame, matrix all "planned" | High | **partly** | VMP v1.1 with the missing sections; `docs/validation/` exists with 15 records. The matrix is unchanged: new STD-003 |
| REG-028 two risk files on two scales | High | **open by owner decision** | T-644 struck (D-311 B18) |

## 3. Verdict per standard

"May claim today" is what a hospital IT office or a sponsor can be told truthfully on this tree. "To claim more" is the
minimum by go-live.

| Standard | Score | May claim today | To claim more by go-live |
| --- | --- | --- | --- |
| OMOP CDM 5.4 | **nominal to partial** | "An optional copy of the data in OMOP CDM 5.4 tables (official DDL v5.4.2, all 39 tables), with source codes and local concept ids. No OHDSI vocabulary is loaded; standard concept ids are 0." Not "OMOP-conformant", not "OHDSI-ready" | Either load a site-downloaded Athena bundle once on the acceptance box and record the fill rates (drugs through RxNorm, measurements through LOINC, units through UCUM; conditions stay 0), or say nothing about OMOP to a site (STD-006) |
| FHIR R4 (internal shape) | **substantial** | "Hospital data is converted to FHIR R4 resources inside the box; a 1 % sample is checked every night" | Nothing needed |
| FHIR inbound (Bulk Data files) | **partial** | "Reads NDJSON files of a Bulk Data export from a folder, a documented subset of elements" | Do not claim "Bulk Data client" or "SMART": there is no `$export` kick-off, no polling, no SMART Backend Services auth (STD-013) |
| TW Core 1.0.0 | **substantial** for 13 profiles emitted | "Output carries TW Core 1.0.0 profiles and code systems (ICD-10-CM TW edition by date, NHI drug and service codes); the HL7 validator checks 200 resources in CI" | Fix ICD-9-CM years first (STD-001), or the claim is false for records before 2016. Patient carries a pseudonym with `v2-0203#ANON`, by design: the 身分證 and 病歷號 identifier slices are never filled. Say so |
| JP Core 1.1.0 | **substantial** for 16 profiles | "Output is checked offline against JP Core 1.1.0 rules at every ingest" | State the version: the IG is at 1.2.0 and JP-CLINS uses 1.1.2. No kana name extension (no names are kept, by design). JAMI licence terms unconfirmed (NOTICE 9.4) |
| SMART on FHIR, CDS Hooks | **absent** | Nothing | Nothing needed for go-live |
| CQL / FHIR Clinical Reasoning | **partial**, and not needed at run time | "Criteria are also generated as CQL and compared with the SQL engine before approval" | Nothing; candidate to freeze (§5) |
| SS-MIX2 standardized storage v1.2 | **partial** (good reader, never fed a vendor file) | "Reads SS-MIX2 standardized storage: ADT-00/12/22/52, PPR-01, OMP-01/02/11/12, OML-11, and extended storage documents" | One real vendor storage read end to end. Allergies (ADT-61) are not read (STD-014) |
| HL7 v2.5 | **partial** | as above | as above |
| CDISC ODM 1.3.2 | **conformant** to the XSD | "Exports and imports CDISC ODM 1.3.2; every export is validated against the CDISC schema in the build" | Nothing needed. ODM 2.0 is not supported; say so |
| CDISC CDASH | **partial** | "Items carry CDASH tags (DM, VS, LB, MH, CM, SV, AE, IE, DS: 30 variables)" | Nothing needed |
| SDTM, Define-XML, CDISC CT files, USDM | **absent** (stated in `edc/cdash.py:14`) | "Not provided" | Nothing; do not start |
| LOINC | **partial** | "Lab codes are mapped to LOINC by a site table the steward confirms" | Pin the release (NOTICE 9.1 open; STD-012). Shipped maps are samples: 14 rows per site template |
| JLAC10 / JLAC11 | **partial** / absent | "JLAC10 codes are read and mapped by the site's own table and licensed release" | The site's lab master loaded and the unmapped list read once (STD-009) |
| ICD-10-CM (Taiwan 2014 / 2023) | **partial** | "ICD-10-CM, with the TW edition named by record date" | STD-001 (ICD-9-CM years) and STD-007 (the 2014 to 2023 map is not applied) |
| ICD-10 WHO 2013 with MEDIS 標準病名 | **partial** | "WHO ICD-10 kept as coded; the site loads its own MEDIS release" | Nothing more in code |
| ATC | **partial** | "Drug criteria are ATC classes" | WHOCC permission asked (letter drafted, not sent); the ATC version recorded (STD-012) |
| YJ / HOT to ATC | **partial** | "YJ and HOT codes are kept; an ingredient table gives ATC for 56 ingredients" | The resolution rate measured on the site's own drug master (STD-008) |
| NHI drug code to ATC (Taiwan) | **nominal** in the nightly path | "ATC is taken from the hospital's own column" | Apply the NHIA map when the row has no ATC (STD-005) |
| UCUM | **partial** | "Units are written as UCUM codes from a reviewed table; an unknown unit gives no value" | STD-004. Do not claim "UCUM validation": no UCUM library validates or converts |
| SNOMED CT | **absent** by decision | "Not used" (one route code in the TWPAS bundle, declared in the register) | Nothing. The inquiry TB-LIC-01 is not sent |
| MedDRA | **absent** | "AE terms are verbatim; coding is the sponsor's" | Nothing |
| CTCAE | **partial** | "A CTCAE grade and version can be recorded on the AE form" | Nothing |
| RxNorm | **absent** on a box (only inside an Athena bundle a site may load) | Nothing | Nothing; not relevant in Taiwan or Japan except as OMOP's drug standard |
| 21 CFR Part 11, Japan ER/ES 2005, Annex 11 | **partial** | "Built with Part 11 style controls: unique accounts, two components at signing, signature meaning, a keyed signature bound to the record, a record lock, an append-only hash-chained audit trail. Not assessed clause by clause, not validated (no IQ/OQ/PQ)" | STD-002 (signed heads on a schedule), STD-003 (a matrix that shows real tests). The assessment document is the owner's call under D-311 item 2 |
| ICH E6(R3) computerised systems; Taiwan GCP | **partial** | "A record inventory, change classes, a SOUP list, a problem log exist" | as above |
| Non-device position (TFDA, PMDA) | **partial**, consistent with the product | "Research-operations support; not a medical device" (statement in the footer, wording list enforced) | STD-016 (one sentence of the statement the product does not keep) |
| Licences (`NOTICE`, register) | **substantial** | "Every shipped data file has a licence row; the build fails otherwise" | STD-012 |

## 4. Findings

| ID | Severity | Finding | Evidence | Impact | Fix | Card | Flag |
| --- | --- | --- | --- | --- | --- | --- | --- |
| STD-001 | High | Taiwanese diagnoses coded in ICD-9-CM (every NHI claim before 2016-01-01) are emitted as ICD-10-CM and tagged with TW Core's ICD-10-CM 2014 slice. The canonical diagnosis table has one column, `icd10`, and no code-system or version column; the only date rule is 2025-01-01 | By a run (`STD/icd9.py`): row `714.0`, 2014-03-02 gives codings `icd-10-cm 714.0` and `icd-10-cm-2014-tw 714.0`; `250.00` and `V58.69` the same. `tw_core/demo_his.yaml:148-151`; `templates/CANONICAL.md:14`; `templates/cgrd_sql_site.yaml:44`. `grep -i 'icd-9\|2016'` finds nothing in `docs/DATA.md`, the plan or the site survey (question 37 asks only 2014 / 2023) | CGRD holds records from 2001. A history criterion ("prior malignancy", "prior tuberculosis", "MI in the past") cannot see anything before 2016: an exclusion never fires and the patient is listed. The coverage rule (`matching/coverage.py`) does not help, because the system is a "known" one. ICD-9-CM V and E codes also share shapes with ICD-10-CM chapters (`V58.69`). The TW Core claim is false for these rows | A `diag_code_system` column (or a `date_before: 2016-01-01` rule) so ICD-9-CM rows carry `http://hl7.org/fhir/sid/icd-9-cm`; apply the CMS GEMs already in the licence register (`mimic/tables/icd9_to_icd10cm.csv` is a sample of it) to add an ICD-10-CM coding where the map is one-to-one, else leave the row unknown; add the years to survey question 37 | NEW-STD-1 "ICD-9-CM years in Taiwan" (M) | Go-live TW |
| STD-002 | High | The signed audit heads (D-355) are never made on a box. No systemd timer, no scheduler job and no service calls `--sign-head`; `doctor` has no check that an anchor folder is set or that a head is recent. `make audit-verify` runs without `--heads` | By a run (`STD/audit_poc.py`): delete event 3, recompute the chain, rewrite `HEAD.json`: `verify` returns `ok=True`. `STD/audit_poc2.py`: the same attack with `--heads ANCHOR` exits 1 ("the chain was rewritten"), so the mechanism works. `grep -rn 'sign-head\|sign_head'` over `deploy`, `services`, `tools/trialbox`: only `tools/audit_verify.py` itself and the decommissioning runbook. D-355 lines 36-37: "the nightly timer ... are deploy work" | On a deployed box the audit trail is protected only by an unkeyed chain and an unkeyed anchor on the same volume. Anyone who can write that volume can remove an event without trace. "Audit trail that cannot be altered" (Part 11 §11.10(e), ER/ES 真正性) cannot be claimed | A scheduled job in the box's scheduler (it already runs the backup) that signs the head and writes it to `TB_AUDIT_ANCHOR_TARGETS`; `doctor` FAILs in VALIDATION and PRODUCTION when no anchor folder is set or the newest signed head is older than the job's own period; `make audit-verify` and the audit page use the signed heads when a folder is set. Events after the last signed head stay unprotected: state the period as a setting with its reason | NEW-STD-2 "signed audit heads on a schedule, checked by doctor" (S) | Go-live both |
| STD-003 | High | The traceability matrix does not trace. All 273 rows are "planned". It is generated from plan v5 (`25-master-plan.md`), which v6 superseded. A test id is a plan label, not a test | By a run: `cut -d, -f7 25-traceability.csv` gives 273 "planned"; 65 distinct `TST-` ids, 8 of them named in any file under `tests/`. Sample of 15 rows (§4.3): 11 test ids have no test or tool file; 5 rows pair a requirement with an unrelated test (URS-ADM-20 shared GPU platform with TST-OPS-04 update rollback; URS-PRV-04 "no chart number by mail" with TST-SEC-01 authorisation matrix) | A hospital QA or a sponsor auditor who asks "show me requirement, test, result" gets a file that shows nothing was tested, although about 300 test files exist and pass. The VMP's own claim (§7) rests on it | Turn it round: tests declare what they prove (`@pytest.mark.req("URS-...")` or a `# covers:` line the generator reads), the generator writes requirement, test node id and the CI result; a requirement with no passing test is listed as such. No signature, no gate (D-311) | NEW-STD-3 "traceability from tests, with results" (M) | Go-live both |
| STD-004 | High | Common Japanese unit spellings are not read, so the value is dropped as `unit_mismatch`: `IU/L` against a table unit `U/L` (AST, ALT, ALP, LDH, CK, γ-GT), `×10^3/μL`, `×10^4/μL`, `×10^2/μL` (multiplication sign), `G/L`, `mL/分/1.73m2`, `mL/min/1.73m^2` | By a run (`STD/lab.py`): `ALT, 45, IU/L` gives `dataAbsentReason: unit_mismatch`. Probes: `labvalue.ucum('×10^3/μL')` is None (`x10^3/uL` reads); `labunit.convert(100,'IU/L','U/L',LOINC,'1742-6')` is None; `convert(52,'×10^2/μL','10*3/uL',...)` is None. `libs/tb_common/labunit.py:71-135` | Safe direction (unknown, never a wrong number), but a site that prints these spellings loses every liver-enzyme and blood-count criterion: every patient goes to "needs information". The steward must then edit a look-up row per analyte | Fold `×` to `x` and `分` to `min` in `norm_unit`; add `10*2/uL`; treat `[IU]/L` and `U/L` as the same unit for analytes listed as enzyme activity (a column in the analyte table, not a global rule); let `mapping_check` list every (analyte, unit) pair it could not read, by volume | NEW-STD-4 "Japanese unit spellings and enzyme IU/L" (S) | Go-live JP |
| STD-005 | High (if the CGMH feed has no ATC column) | In Taiwan the drug class comes only from the hospital's own `ATC_CODE` column. The NHIA drug-code to ATC map is parsed and registered (`refdata_tw.parse_nhi_drug_atc`) but only the site set-up suggestion page reads it; the nightly adapter does not | `tw_core/demo_his.yaml:241-244`; `templates/cgrd_sql_site.yaml:59`; `grep nhi.*atc services/adapter services/lake`: no use; `sitesetup/mapping.py:271-274`. Survey question 38 ("ATC present yes / no") has no answer on file | A medication row with an NHI code and no ATC cannot match any drug value set: drug exclusions never fire, inclusions become unknown | In the TW mapping, fill `atc` from the NHIA map when the column is empty, with a provenance tag; count rows resolved by column, by map, and unresolved in the ingest report | NEW-STD-5 "NHI drug code to ATC in the nightly path" (S) | Go-live TW |
| STD-006 | High | OMOP is a parallel store with no vocabulary. No Athena bundle exists on any box or in any test beyond a small extract, so every `*_concept_id` of a clinical row is 0, measurements and units included; `*_source_concept_id` is a local surrogate (2,100,000,000 and up). Nothing reads the store except `omop.export`, which rebuilds the lake's own tables. The seed in compose, `site.env` and `.env.example` is `legacy`. The committed evidence still words every gap as "until the Athena vocabulary bundle is loaded" | Committed `eval/omop_parity/report-ci.json`: JP site, `standardConceptRecordCompleteness` 7,206 / 7,206 conditions, 22,481 / 22,481 drugs, 21,240 / 21,240 measurements, 40 / 40 observations, 26 / 26 procedures at 0, status "known". `deploy/docker-compose.yml:149`, `deploy/platform/base/site.env:7`. `grep 'from omop'` outside `services/omop`: the lake, the dual write, the opt-out worker, the conflicts page, the terminology resolver; no screening or feasibility query. The DQD notes in the code are now honest per table (`omop/dqd.py:90-108`); the committed report is older than that wording (STD-021) | A site told "the data is in OMOP" will find that ATLAS, Achilles, the OHDSI DQD and any network study cannot use it. Meanwhile the store costs a second CI matrix (e2e and goldens run twice), a 1,551-line loader, and an open L card to make the load fit memory (T-702) | Decide once (§5): one lake source at go-live. Whichever wins, freeze OHDSI-conformance work and word the claim as in §3. If a site asks for OMOP, load its own Athena download on the acceptance box and record the three fill rates | T-202 (decide the flip or retire it), T-702; NEW-STD-6 "one honest OMOP sentence and one Athena trial load" (S) | Go-live both |
| STD-007 | Medium | The NHIA 2014 to 2023 ICD-10-CM edition map is loaded as data but never applied: `edition_code()` has no caller. Value sets are built from the US FY2026 list | `services/omop/vocab_load.py:773` is the only occurrence of `edition_code(` outside its definition (`grep -rn`); `NOTICE` §1 ICD-10-CM "FY2026" | A 2014-edition code that the 2023 edition split or retired matches a family (unknown) or nothing. Small in volume; hits records from 2016 to 2024 | Call it in the adapter for dated TW diagnoses, or delete it and state in DATA.md that edition differences read as unknown | T-105b (its acceptance names this) | Go-live TW |
| STD-008 | Medium | Japan's ingredient table is 56 YJ stems; the need is about 2,500. The path is right but the resolution rate on a real drug master is unknown | `libs/tb_common/refdata_src/jp_yj_atc.csv` (57 lines); register row `yj-atc` "56 stems"; `jp_core/yj_to_atc.csv` 22 rows marked `verify` | Drug criteria outside the 56 ingredients cannot be decided in Japan: exclusions do not fire | Measure on the site's own drug master (the ingest report already has `drug_resolution`); extend the table to the ingredients of that master with a pharmacist's check, starting with the classes the first study's criteria name | T-610 follow-up; NEW-STD-7 "YJ stems for the first study's drug classes" (M) | Go-live JP |
| STD-009 | Medium | Shipped lab maps are samples: 14 rows per site template, all JP rows marked `verify`. A lab code with no row is counted and dropped from coded criteria. No real lab master has been loaded | `jp_core/jlac10_to_loinc.csv` (15 lines), `tw_core/lab_local_to_loinc.csv` (15 lines), `catalogue/verification/jlac10_map.csv` (41 lines) | The first night at a site decides lab coverage; today nobody knows it | Before each go-live: load the site's lab master, run `mapping_check`, record the share of result volume mapped; a criterion whose analyte is unmapped is shown as undecidable at approval | T-320b / site set-up; no new card | Go-live both |
| STD-010 | Medium | The box carries a HAPI FHIR JPA server (5 GB memory limit, fed every night) and a JVM image with 105 translator jars so that CQL can be compared with SQL at ruleset approval. SQL is the only run-time engine | `orchestrator/scenarios/evaluate.py:3-4, 149-153`; `deploy/docker-compose.yml:109-131`; `adapter/load_fhir.py:9-12` ("A full 500k-patient reload took about 8 h on HAPI"); `criteria_compiler/service.py:299` (approval blocked without the translator); `tools/jvm-deps.sha256` (105 lines); plan v6 line 1720 (20 vulnerable jars, one CRITICAL, before PR #78) | Memory, a nightly load, a second pseudonymised copy of every resource, and the largest CVE surface on the box, for a check that the Python / SQL property tests (T-705, T-706) now also give | See §5: run the CQL comparison in CI on the equivalence fixture only; take HAPI and the nightly FHIR load off the box (T-306 already plans the second half "after go-live") | T-306 (bring forward), T-652 | Go-live both |
| STD-011 | Medium | Part 11 / ER-ES: no clause-by-clause statement exists (struck by D-311 B27), yet the product has an own EDC, an SAE register and e-signatures. The first sponsor or hospital QA that looks will ask for it, and in Japan for the PMDA EDC management sheet answers | `docs/validation/README.md:27-28`; plan v6 line 519 (T-648 struck); the controls themselves: `edc/store.py:231-250, 570-592, 686-711`, `console/edc_pages.py:363-436` | Not a code risk. A schedule risk at the moment plan §0.3 item 2 applies: the document then has to be written under time pressure | Not a gate: a generated table (clause, control, file, automated test id, CI result) built from the same marks as STD-003. It can be handed over the day it is asked for | NEW-STD-3 (same generator) | Later (Go-live for a site that uses prefill into a sponsor's record) |
| STD-012 | Medium | Licence items still open in `NOTICE` §9: no LOINC release pinned in the shipped files; ATC version not recorded and the WHOCC permission letter drafted but not sent; JP Core package states no licence; SNOMED inquiry TB-LIC-01 not sent while one SNOMED code ships in the TWPAS bundle | `NOTICE` §9.1 to 9.4; `docs/licences/register.csv` rows `loinc`, `atc` (status `permission-to-ask`), `snomed-ct`; `services/orchestrator/reports/twpas_bundle.py:24` | LOINC's licence asks for the version; ATC names ship in a commercial product without WHOCC's answer | Pin LOINC and ATC versions in the terminology release file; send the two letters, or ship ATC codes without names (the register names this fallback) | T-617b follow-up; NEW-STD-8 "LOINC and ATC versions pinned; ATC names fallback" (S) | Go-live both |
| STD-013 | Medium | "FHIR Bulk Data" is a folder reader. There is no `$export` kick-off, no status polling, no SMART Backend Services authentication, no TLS client | `services/adapter/sources/fhir_bulk/source.py` (45 lines: `glob("*.ndjson")`); `grep -ri 'smart\|client_assertion\|jwks' services/adapter`: nothing | A hospital that offers a FHIR server (TW Core at CGMH's platform, JP-CLINS style servers) must write its own export job. Fine for go-live if the site drops files; wrong if a pack says "Bulk Data" | Word it "reads Bulk Data export files". Build the client only when a site has a server to call | none (wording in DATA.md); later NEW-STD-9 (M) | Later |
| STD-014 | Medium | SS-MIX2: allergy information (ADT-61), lab and exam orders (OML-01, OMG), and procedures are not read from standardized storage; procedures and vitals must come from a side CSV | `ssmix2/source.py:8-37` (the list of types read), `:67-68` | "Known hypersensitivity to ..." criteria cannot be decided in Japan; they stay unknown (safe) | Read ADT-61 into AllergyIntolerance (the JP Core profile is already in the rule file) when the first vendor storage shows it is filled | T-615b; NEW-STD-10 "ADT-61 allergies" (S) | Later |
| STD-015 | Medium | A lab row with no unit takes the look-up's unit. This is declared per site (`unit_defaults`) and checked by `mapping_check`, but it is the one path where a number can still get a wrong unit | By a run (`STD/lab.py`): `CRE, 1.0, ""` gives `1 mg/dL`. `demo_his.yaml:39-48` | A feed that sends creatinine in µmol/L with an empty unit column would store 88 mg/dL. The engines' plausibility bounds may catch it; I did not test that | Ingest report: count, per analyte, results that took the default unit and show their median against the analyte's plausible range; hold the table when the median is outside | T-613b follow-up; NEW-STD-11 "default-unit plausibility check" (S) | Go-live both |
| STD-016 | Medium | The intended-use statement says TrialBox "gives no clinical alerts". The product sends SAE and deadline alerts to investigators. These are trial-conduct alerts, not clinical ones, but the sentence does not say so, and C7 of the statement says "sends nothing to patients" while a printed visit reminder is allowed | `docs/plan/intended-use.md:16, 44`; SAE register `services/console/saerecord.py` | A regulator reads the labelling literally (the Japanese guideline judges from wording). One clear sentence removes the question | "gives no clinical alerts (it reminds study staff of trial deadlines)" in the three languages, in the single statement source | T-506 follow-up (S) | Go-live both |
| STD-017 | Low | Fixed limits in my area that are neither settings nor derived: `REJECT_MAX_PCT = 1.0` (`adapter/pipeline.py:934`), HL7 validator `timeout=1800` per batch of 5,000 (`validate/validator.py:103, 168`), CQL translator `timeout=600` (`compile_cql/translator.py:104`) | the lines named | OD-10. A slow box holds the night on a validator timeout | Make each a declared setting with its reason, or derive the timeout from the batch size and a measured rate | T-713 family; NEW-STD-12 (S) | Later |
| STD-018 | Low | HbA1c reported in JDS (Japan, before April 2012) is not told from NGSP; the two differ by about 0.4 percentage points | `grep -r JDS services libs`: nothing; survey question 36 asks | Only old values; screening uses recent ones | A note in DATA.md; a date rule in the JP mapping if a study needs history | none | Later |
| STD-019 | Low | `cdm_source.cdm_version_concept_id` is 0 (the CDM v5.4 concept exists); `observation_period` is one span per person from first to last record, rebuilt at each load | `omop/load.py:1293-1305, 1328-1329` | Cosmetic for OHDSI tools | Set the concept when a vocabulary is loaded | T-106b | Later |
| STD-020 | Low | JP Core is pinned at 1.1.0 (2022); the IG is at 1.2.0 and JP-CLINS at 1.1.2 | `validate/jp_core_rules.json` `package.version` | A site may ask for the newer one | Ask the site which version its plans use; re-run `tools/jpcore_rules.py` | T-619a | Later |
| STD-021 | Low | The committed OMOP evidence (`eval/omop_parity/report.json`) has no profile, no date and no commit; `report-ci.json` has a profile but no commit either | keys of both files (by a run); the DQD notes in `report-ci.json` are the old wording, not the one `omop/dqd.py:90-108` writes today | Evidence that cannot be tied to a tree, and already stale | Write the commit and the date into the report; regenerate it | T-655 | Later |

### 4.1 STD-006: the OMOP run

My own parity run did not finish (see the header), so the row-for-row identity of the two lake sources was **not re-proved today**; it is asserted by the committed reports and by the CI jobs `e2e-simple (omop)` and `goldens (omop)`. The vocabulary facts below do not depend on that run: they follow from the loader's code and from `test_omop_athena.py` and `test_vocab.py`, which passed.

What is in the store, table by table (JP synthetic site, committed `report-ci.json`): person 2,500; visit_occurrence
17,133; condition_occurrence 7,206; drug_exposure 22,481; measurement 21,240; observation 40; procedure_occurrence 26;
note 4,709; death 0; fact_relationship 8,068; concept 109 (of which 89 local); `tb_record` 81,862. The other 24 CDM
tables exist and are empty.

How the questions of the brief answer:

| Question | Answer | Where |
| --- | --- | --- |
| CDM version | 5.4, the official PostgreSQL DDL of tag v5.4.2, pinned by sha256; foreign keys not applied, checked as data | `omop/ddl/pin.json`, `omop/schema.py` |
| Tables populated | 10 clinical and health-system tables, 6 vocabulary tables with seeded rows; 39 exist | above |
| Concept ids | Gender (8507 / 8532), visit (9201 / 9202 / 9203), type (32817), five operator ids: real OHDSI ids, seeded by hand. Everything else: local surrogates from the site block (2,100,000,000 up), never standard | `omop/vocab.py:38-56` |
| What stands in for licensed vocabularies | `TB-ICD10CM`, `TB-LOINC`, `TB-ATC`, `TB-NHI` local vocabularies, one concept per code the feed carries | `omop/vocab.py:9-17` |
| Standard vs source | Source concept always filled; standard 0 unless an Athena bundle is loaded; then `Maps to`, then ATC to RxNorm ingredient | `omop/vocab.py:224-250` |
| Visits | class to 9201 / 9202 / 9203; end date from `period.end`, else the start day | `omop/load.py:320-326, 882-883` |
| observation_period | one row per person, min to max over all event dates, deleted and rebuilt at each load | `omop/load.py:1293-1305` |
| Units in MEASUREMENT | `unit_source_value` kept; `unit_concept_id` 0 without Athena UCUM | `omop/load.py:975-977` |
| DQD / Achilles | a 226-check re-implementation in SQL ("a small subset", its own docstring); no Achilles; the OHDSI DQD R package has not been run | `omop/dqd.py:1` |
| Does anything downstream query OMOP? | No screening, feasibility or profile query. Readers: the export to the lake, the opt-out worker (`tb_withheld`), the conflicts page (`tb_conflict`), the terminology resolver (vocabulary tables) | `grep 'from omop'` |

### 4.2 STD-002: the audit-chain runs

| Attack (6 to 10 synthetic events) | `verify` without signed heads | with `--heads ANCHOR` |
| --- | --- | --- |
| none | PASS | PASS |
| drop the last 2 events, `HEAD.json` untouched | FAIL ("the chain ends at event ...") | FAIL |
| drop the last 2 events and rewrite `HEAD.json` | **PASS** | PASS when both were written after the last signed head (inherent; the signing period is the exposure) |
| edit one line in place | FAIL (hash mismatch) | FAIL |
| delete a middle event, recompute every hash, rewrite `HEAD.json` | **PASS** | FAIL ("event 6 does not have the signed hash: the chain was rewritten") |

Other Part 11 points checked by reading and by the tests named in the header:

| Requirement | State | Evidence |
| --- | --- | --- |
| Audit trail complete and time-stamped | built: one writer service, journal table, site-time stamps, chart numbers masked | `libs/tb_common/audit.py:40-52`; `test_audit_one_writer.py` exists (not run by me) |
| Not editable | chain and anchor: yes against accident; against a writer of the volume only with signed heads (STD-002). EDC trail tables refuse UPDATE, DELETE, TRUNCATE by trigger | `edc/store.py:20, 274`; `test_edc_signing_d281.py` passed |
| Signature unique to a person, two components | password and TOTP re-typed at signing; a directory account re-authenticates at the provider with its second factor | `edc_pages.py:363-436`; passed |
| Meaning, printed name, time, linked to the record | signature row with name, role, meaning, time, method; HMAC over the whole act and every value's hash; verified before send and export; version-1 signatures refused | `edc/store.py:231-250, 701-711`; commit `e7586b3` |
| Record lock after signing | a signed value changes only with a reason after re-authentication | `edc/store.py:570-592`; passed |
| Time source | `doctor` FAILs beyond `TB_CLOCK_MAX_SKEW_S` and on an unsynchronised clock in VALIDATION and PRODUCTION | `audit.py:44-46, 769-830` (read) |
| Human-readable copies | ODM, CSV, XLSX exports per study; the audit browser | record inventory column "export" |
| Validation documentation | VMP v1.1 without signatures (D-311), 15 development records, matrix nominal (STD-003), no IQ/OQ/PQ unless §0.3 item 2 | `docs/validation/README.md` |
| Retention and backup | owned by the operations reviewer; not re-checked here | |

### 4.3 STD-003: the 15 sampled rows of `25-traceability.csv`

Rows were picked by a hash order, one per distinct test id. "File" is any file under `tests`, `tools`, `services` or
`libs` that names the test id.

| Requirement | Test id | Level | A file names it? | Does the test fit the requirement? |
| --- | --- | --- | --- | --- |
| (none) / RSK-05 | TST-GOLD-02 OMOP parity | E | `tools/omop_parity.py` | yes |
| URS-PI-20 accuracy measured before any claim | TST-PQ-02 | PQ | no | site activity, not a test |
| URS-ADM-20 isolation on a shared GPU platform | TST-IQ-03 | IQ | `tests/platform/test_isolation_probe.py` | yes |
| URS-PI-07 cited profile page and twin | TST-PROF-01 | G | no | fits, no test file carries the id |
| URS-STW-06 a held night never moves `CURRENT` | TST-PERF-01 50k ingest in flat memory | P | `tests/perf/test_backfill_50k.py` | **no**: a performance test for a correctness requirement |
| URS-ADM-20 shared GPU platform | TST-OPS-04 update and rollback | E | no | **no** |
| URS-PI-12 setpoints and gap rules | TST-PROF-05 | E | no | fits, no file |
| URS-CRA-03 record audit trail with signature meaning | TST-EDC-04 Part 11-style walk | E | `tests/console/test_edc_signing_t205.py` | yes |
| URS-ADM-03 survives a reboot and a mail outage | TST-SEC-03 egress and boundary | S | no | **no** |
| URS-ADM-01 directory sign-in and second factor | TST-SEC-06 identity | S | no | fits, no file (tests exist under other names) |
| URS-PRV-04 no chart number by mail, no PHI prompt leaves | TST-SEC-01 authorisation matrix | S | only `test_gen_traceability.py` | **no** |
| URS-STW-04 steward resolves conflicts | TST-UNIT-05 conflicts | U | no | fits, no file |
| URS-PRV-05 record of processing, DPIA, DPA | TST-IQ-01 executed IQ | IQ | no | a document, not a test |
| URS-PI-05 not-matched list with evidence | TST-PQ-03 real-data dry run | PQ | no | site activity |
| URS-CRC-02 two taps on a phone | TST-WALK-01 `public_walk.js` | W | no | fits, no file carries the id |

Result: 4 of 15 test ids are named by a file; 3 of those 4 fit their requirement; 4 rows pair a requirement with a
test of another subject. No row has a result.

## 5. What to drop or simplify

| Candidate | Evidence | Proposal |
| --- | --- | --- |
| **Two lake sources kept alive together** (`legacy` flattener and `omop` load-then-export) | Both produce the same rows by construction (`lake/source.py`); CI runs e2e and goldens once per source (`trialbox-ci.yml:313-372`); the seed is still `legacy` in three deploy files; opt-out, conflicts and as-of export exist only on the OMOP side (architecture note `lifecycle.md:65-69, 311`) | Pick one for go-live and say so in v7. If `omop`: flip the seed, keep the flattener only as the parity oracle in CI, and T-702 (load at scale) becomes a go-live card. If `legacy`: move `tb_withheld` and `tb_conflict` reading into the flattener and freeze `services/omop` as an export. Either way the second CI matrix goes |
| **OHDSI-conformance work on OMOP** (Athena loader growth, standard concept ids, domain routing, 39 tables, "one run of the OHDSI DQD", code-map registry T-316b) | No reader of standard concepts exists; no bundle is loaded; conditions can never be standard without SNOMED | Freeze at today's state. One trial load of a site-downloaded bundle on the acceptance box is enough to know the fill rates (NEW-STD-6) |
| **CQL as a second engine on the box, with HAPI and the nightly FHIR load** | STD-010 | Keep the CQL generator and the comparison as a CI job on the equivalence fixture. Remove HAPI, `load_fhir` and the translator from the box's nightly and approval paths: approval then needs SQL plus the property tests. This also removes the 5 GB container, a second copy of the data and most JVM CVEs. TWPAS pre-check (the one other CQL user, `orchestrator/precheck`) is not a go-live function |
| **HL7 validator jar in the nightly path** | Japan already uses the offline rule file with no JVM; Taiwan now has `twcore_rules.json` from the same generator | Use the offline rule check at night for both countries; keep the HL7 validator in CI (job `standards`) only. Then no JVM is needed on the box at all |
| **TWPAS bundle and its IG packages** | `orchestrator/reports/twpas_bundle.py`, `scenarios/twpas.py`, package fetch per settings version (T-676); the one SNOMED code in the product comes from it | Not a go-live function for trial screening: freeze, keep out of the go-live image, and the SNOMED question disappears |
| **Define-XML, SDTM, USDM, ODM 2.0, RxNorm, MedDRA coding** | absent today; `edc/cdash.py:14` says so | Do not start. State "not provided" in DATA.md |
| **`25-traceability.csv` as generated from plan v5** | STD-003 | Replace, do not maintain |
| **`edition_code()` with no caller** | STD-007 | Call it or delete it |

## 6. What the plan must change (inputs to plan v7)

| # | Task | Size | Depends on | Flag |
| --- | --- | --- | --- | --- |
| 1 | NEW-STD-1 ICD-9-CM years in Taiwan: code-system column or date rule, GEMs applied where one-to-one, survey question 37 extended. Before the first CGRD history load, or history is loaded wrong and must be re-mapped | M | none | Go-live TW |
| 2 | NEW-STD-2 signed audit heads on a schedule, `doctor` check, `make audit-verify` with heads | S | T-211a (done) | Go-live both |
| 3 | Decide the single lake source (T-202 flip or retire). Order: decide, then T-702 only if `omop` wins; remove the second CI matrix either way | S (decision) + L (T-702) | architecture note G-7 | Go-live both |
| 4 | NEW-STD-4 Japanese unit spellings and enzyme `IU/L`; NEW-STD-11 default-unit plausibility check | S + S | none | Go-live JP / both |
| 5 | NEW-STD-5 NHI drug code to ATC in the nightly TW path (after the survey answer on question 38) | S | survey answer | Go-live TW |
| 6 | NEW-STD-3 traceability from tests with CI results; the Part 11 / ER-ES control table from the same marks (STD-011) | M | none | Go-live both |
| 7 | Bring T-306 forward and widen it: HAPI, the nightly FHIR load, the translator and the HL7 validator off the box; CQL and the validator stay as CI jobs | M | T-652 | Go-live both |
| 8 | Site data readiness as dated tasks, not code: the site's lab master and drug master loaded, `mapping_check` run, mapped share of volume recorded (STD-008, STD-009); one real SS-MIX2 vendor storage read (CR-015) | M per site | site access | Go-live both |
| 9 | NEW-STD-8 LOINC and ATC versions pinned; the WHOCC letter sent or ATC names dropped | S | owner (letter) | Go-live both |
| 10 | NEW-STD-6 one honest OMOP sentence in DATA.md and the site pack; one Athena trial load on the acceptance box | S | a site-downloaded bundle | Go-live both |
| 11 | Wording: "reads Bulk Data export files" (STD-013); the alert sentence of the statement (STD-016) | S | none | Go-live both |

Order: 1 and 3 first (both change what is loaded and how), then 2, 4, 5, then 7, then 6.

## 7. Needs GCP / owner hardware

None of the standards checks needs a GPU. Three need things this machine does not have:

| Test | Command | Record | Pass |
| --- | --- | --- | --- |
| TW Core through the HL7 validator, and the CQL path | `make jvm-deps && .venv/bin/python -m tools.twcore_check --json twcore.json && .venv/bin/python -m tools.cql_path_check --json cql-path.json` (the CI job `standards`; needs network for the fetch) | errors, unmatched slices; SQL / CQL disagreements | 0 errors; every filled slice matched once (ICD-10-CM 2023 TW excepted, as the tool states); 0 disagreements |
| OMOP load and export at site scale, if `omop` becomes the source | `python -m tools.omop_parity --sets synthetic --profile 50k --json report-50k.json` on the acceptance box, then the same at the site's real row count | wall seconds per rebuild, loader seconds per batch, peak RSS | identical; peak RSS under the box's free memory with the models loaded; the night's window holds (the scale review's F-17) |
| Athena trial load | on the acceptance box: load a site-downloaded bundle (LOINC, UCUM, RxNorm, RxNorm Extension, ATC) with `python -m omop` vocabulary load, re-load the synthetic site, run `python -m omop dqd --json dqd.json` | share of drug, measurement and unit rows with a standard concept; load minutes; database size | recorded (no threshold: this is the measurement the OMOP sentence will quote) |

## 8. Small certain fixes

| For | File:line | Change | Test that fails first |
| --- | --- | --- | --- |
| STD-004 (part) | `libs/tb_common/derived.py:198-201` `norm_unit` (used by `labunit.key`) and its SQL twin `labunit.key_sql` (`labunit.py:58-64`) | after NFKC, replace `×` (U+00D7) with `x` and `分` with `min`, in both; add `"10*2/uL": 0.1` to `SCALES["number concentration"]` (`labunit.py:133`); list `x10*2/uL`-style spellings under it in `UCUM` as the `10*3/uL` ones are | a new row in `tests/unit/test_lab_units_per_row.py::PAIRS`: `("6690-2", "×10^3/μL", "10*3/uL", 1.0)` and `("6690-2", "×10^2/μL", "10*3/uL", 0.1)` |
| STD-002 (part) | `Makefile:335-336` | `audit-verify` passes `--heads "$$TB_AUDIT_ANCHOR_TARGETS"` when the variable is set | a test that rewrites a chain and its `HEAD.json` under a signed head and expects exit 1 from the make target's command line |
| STD-001 (stop-gap) | `services/adapter/mapping/tw_core/demo_his.yaml:148-150` | add `{column: diag_date, date_from: "2016-01-01"}` to the `when` of `code.coding[0]` and `code.coding[1]`, and a `code.coding[3]` with `system: icd9cm` and `date_before: "2016-01-01"` (plus `icd9cm: http://hl7.org/fhir/sid/icd-9-cm` under `systems`). The row then reads as an unknown code system instead of a wrong ICD-10-CM code. Check first that `lake/flatten.py` picks the first coding present | `test_standards_conformance.py`: a diagnosis `714.0` dated 2014-03-02 must not carry `http://hl7.org/fhir/sid/icd-10-cm` |

## 9. What is good

- The unit path is now safe by construction: one table for the adapter and the engines, an unknown unit gives no value,
  and the test table has 36 conversion pairs with textbook factors.
- ODM is validated against CDISC's own XSD at every build, with `lxml` and `xmllint`; the file makes no conformance claim.
- The licence register is data, checked in CI against every shipped file (163 files, 0 problems), and renders NOTICE.
  SNOMED remnants were really removed; licensed Japanese masters are never shipped.
- The EDC signature is now a keyed HMAC over the whole act, with a lock, append-only tables and audited refusals.
- The signed-head design is right (write-once, off the box, key rotation endorsed by the old key). It only needs to run.
- JP Core and TW Core rule files are generated from hash-pinned packages by one tool and are reproducible offline.
- "Unknown never excludes" held in every probe I ran: bad units, unread spellings, unmapped codes all became unknown.
- The OMOP DDL is the official text, pinned, and local concepts can never be standard.

## 10. What was not checked

- The HL7 validator and the CQL translator were not run (no jars here); TW Core "substantial" rests on the rule file,
  the unit tests and the CI job's definition, not on a validator run of mine.
- No real hospital data of any kind: no vendor SS-MIX2 file, no CGRD extract, no real REDCap, no Athena bundle, no
  licensed master. Every "partial" above could move either way on first contact.
- Whether the CGMH feed carries an ATC column and from which year its diagnoses start (STD-001, STD-005 depend on it).
- Authorisation, the demo-mode walk, retention, backup and restore: other reviewers' areas; I cite their state only.
- The legal texts were not re-read; versions of laws and guidelines are as the previous review recorded them.
- The Mediums and Lows of the previous `05a` / `05b` were checked only where they touched a High or a new finding.
- Engine plausibility bounds for a value with a defaulted unit (STD-015) were not tested.
