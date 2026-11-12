# TB-DR2-08 Data input mechanisms

| Field | Value |
| --- | --- |
| Document id | TB-DR2-08 |
| Date | 2026-11-12 |
| Tree | `514ae9b` (branch `claude/deep-review-2026-11-12`) |
| Area | Every way data enters the box: HIS exports (CSV, SQL), FHIR bulk, SS-MIX2, sheets, chart paste and upload, REDCap, and the harmonisation behind them (units, dates, codes) |
| Run | Eleven throwaway scripts that import the real functions and feed them synthetic input: `Mapper.map_row` (51 lab values, 33 date spellings), the whole `run_ingest` with a real lake rebuild on a 3-patient site (38 broken feeds: missing tables, ROC dates, encodings, delimiters, duplicates, lost zeros, key loss, chart-number change, deceased and test patients), `Ssmix2Source` on a synthetic storage (18 OBX cases, 5 orders, 5 PRB), `Flattener` on 36 FHIR resources, `fhir_bulk` end to end (4 feeds), `labunit.convert` and `labvalue.conversion` (46 unit pairs), `labvalue.read` (32 unit spellings), `messy.parse_date` (40), `parse_number` (23), `convert` (11), `read_grid` + `clean` on a built XLSX and 5 CSVs, a 200,000-row memory and speed measure. Targeted unit tests: 9 files, 334 passed; 4 files, 43 passed. |
| Only read | `services/rc_bridge`, `datacore/sources.py` and `forms.py` (REDCap), `services/omop` vocabulary mapping, `console/demo_guard.py`, `sitesetup/charts.py` and `publish.py`, the opt-out desk (`console/team.py`), exports. |
| Scripts | `/tmp/claude-0/-home-user-Auto-GPT/557c2965-90c5-5436-9013-fa5ea25fede8/scratchpad/DIN/` (`t1_lab.py` … `t11_scale.py`, `harness.py`). The throwaway PostgreSQL for the pid map ran under `/var/tmp/tb-din-root` (the scratch folder is not readable by the `postgres` user). |

## 1. Reading in ten lines

1. The unit Blocker of the last review (STD-001) is fixed and holds under test: creatinine `88 µmol/L` now leaves the adapter with **no value** (`unit_mismatch`), on CSV and on SS-MIX2. No unit case I ran gave a wrong number.
2. The ingest gate (DATA-001), the site key (DATA-004), the encoding crash (DATA-003), the two ingest stacks (DATA-002) and the Japanese feed items (STD-020, 021, 022) are fixed in code and by my runs.
3. **Dates are now the weak side of the feed.** The adapter's date parser has no ROC or era support and no sanity range. A ROC 7-digit date `1150501` is read as the year **1150**, a 6-digit `640715` as the year **6407**; the night passes (DIN-001).
4. A `fhir_bulk` feed makes its pseudonyms from `Patient.id`, drops the identifier and writes no pid-map row: no chart number can be revealed, the opt-out desk never matches, sheets never join (DIN-002).
5. The opt-out desk still accepts a chart number the box does not know; `12345` and `00012345` are two pseudonyms because no installer sets `TB_CHARTNO_RULE` (DIN-003).
6. SS-MIX2: an order number that repeats on another day replaces the earlier file (18 results lost in my run); a diagnosis whose first code is ICD-10 is stored with no code (DIN-004, DIN-005).
7. An unmapped or mis-spelt local lab code (`" CRE "`, `cre`) is dropped with no count in the night's report (DIN-006). A status code the map does not know becomes `active` for diagnoses (DIN-007).
8. The first night has no completeness baseline: `lab.csv` missing on night one is a good night (DIN-008).
9. The unit spelling table is closed in code: a site whose unit is `×10^3/µL`, `COI`, `秒` or `mL/min` gets no value even when the row and the lookup agree, until a code release (DIN-009).
10. The sheet path is the careful one (ROC, era, day/month order, unit questions to a person). Its number reader is not: `7,2` is 72 and `<0.3` is dropped (DIN-016).

## 2. Status of the previous review's findings

Checked in code and, where marked "run", by my scripts on this tree.

### 2.1 `06-data-flow-governance.md` (Blocker, Critical, High, and the data-input rows)

| Old ID | Severity | Status | Evidence |
| --- | --- | --- | --- |
| DATA-001 no completeness gate | Critical | **Fixed, one gap** | Run (`t2_pipe.py`): after a good night, `lab.csv` missing, `lab.csv` header only and `patient.csv` header only are each `held=True`, `CURRENT` unchanged. Gap: on the **first** night the same feeds pass (DIN-008). `pipeline.py:963-1030`. |
| DATA-002 two ingest stacks | High | Fixed | `services/dataplat` is gone (D-381); contracts, quarantine, gate and alias table moved into `adapter/governance.py`, `pidmap.py`. The contract checks are off unless `TB_DATA_CONTRACTS` is set (DIN-013). |
| DATA-003 CSV reader UTF-8 only | High | Fixed | Run (`t4_csv.py`): CP932 with `髙`, `①`, half-width kana and UTF-8 with BOM load; an ambiguous tiny Big5 file is quarantined and the night held, never guessed. `sources/csv/source.py:73-85`. |
| DATA-004 site key re-created | High | Fixed | Run (`t9_key.py`): key missing → `SiteKeyError`; another key → `SiteKeyError` naming the fingerprint. `pipeline.py:73-133`. |
| DATA-005 chart numbers per entry point | High | **Partly** | One normaliser (`tb_common/chartno.py`) behind `pid_for_mrn`; full-width and blanks agree on every path (run). Open: the default rule keeps leading zeros significant and no installer sets the rule; the opt-out desk still does not check that the patient is known (DIN-003). |
| DATA-006 COHORT primary suppression only | High | Not checked | Outside data input. |
| DATA-016 SQL engine compares without the unit | Medium | Fixed for what I ran | `labunit.convert` returns None for a unit it cannot bring to the criterion's unit; 46 pairs run, none wrong (§4.1). |
| DATA-017 duplicate keys | Low | Partly | Counted (`completeness.json` `duplicate_keys`); the last row still wins with no warning and the report's resource count differs from the lake's (DIN-015). |
| DATA-020 PHI in note text | High | Fixed in code, not re-run | `lake/store.py:531` masks note text (`phi_guard.mask_note`) before chunks, index and embeddings. |
| DATA-021 audit verify without anchor | High | Fixed in code, not re-run | `tb_common/audit.py:21-33` (head anchor, signed heads). |
| DATA-022 opt-out removes from lists only | Critical | Fixed in code, not re-run | `datacore/optout_worker.py` (T-206a): withholds in OMOP, vector store, outputs. Its input side is DIN-003. |
| DATA-024 WAL archiving off | High | Open (by reading) | `deploy/docker-compose.yml:65` `archive_mode=${TB_PG_ARCHIVE_MODE:-off}`; no install script sets it. Owner: operations review. |
| DATA-025 no steward role | High | Fixed in code | `tb_common/authz.py:283` and the role matrix. |

### 2.2 `05a-data-standards.md` (data-input rows)

| Old ID | Severity | Status | Evidence |
| --- | --- | --- | --- |
| STD-001 unit stamped from the look-up | Blocker | **Fixed** | Run (`t1_lab.py`): `CRE, 88, umol/L` → `dataAbsentReason error / unit_mismatch`, no `valueQuantity`. Same on SS-MIX2 (`t5b_ssmix.py`, `S-UMOL`). `engine.py:398-420`, `labvalue.read`. |
| STD-002 no UCUM table, no conversion | Medium | Fixed (table), see DIN-009 | `tb_common/labunit.py` (spellings, scale families), `labvalue.MOLAR`. The table is closed in code. |
| STD-010 Japan ICD-10 emitted as ICD-10-CM | High | Fixed | Run: PRB with a MEDIS code gives both `icd-10` and, where it exists, `icd-10-cm` codings (D-314). |
| STD-013 death flag without a date | High | Fixed | Run: `deceasedBoolean: true` → `deceased=True`; PID-30 test passes. |
| STD-014 narrow FHIR reader | Medium | Partly | `medicationReference`, `effectivePeriod`, `performedPeriod`, therapy period now read. Still: first coding wins for Condition; `valueInteger`, `valueBoolean`, `interpretation` unread; partial dates crash the rebuild (DIN-010, DIN-011). |
| STD-015 offset date-time loses its time | Medium | Fixed | Run: `2026-05-12T00:30:00+09:00` kept; `Z` kept and moved to the site zone in the lake. |
| STD-016 `Asia/Taipei` default | Medium | Fixed | No default zone (D-315): a mapping without `tz` is refused; `AdapterConfig` needs `TB_TZ`. |
| STD-020 strict ISO-2022-JP decoding | High | Fixed | `test_ssmix2_hardening.py` passes (half-width kana, NEC row 13, JIS X 0212, Shift_JIS under a wrong MSH-18; an unreadable file quarantined). My CP932 ADT with half-width kana loads. |
| STD-021 OML-11 read too simply | High | Fixed | Run: OBX-11 `D` a tombstone, `C` replaces, `X` cancelled, `P` kept without a usable value; OBX-2 `CWE` / `SN` read; time falls back OBX-14, OBR-7, SPM-17, folder. |
| STD-022 no Japanese or Chinese qualitative result | High | Fixed | Run: 陰性, (-), －, 陽性, +, 1+, Negative, Non-Reactive map to LA6577-6 / LA6576-8; 弱陽性, `trace`, `陰性 0.01` stay text (unknown). |
| STD-023 other SS-MIX2 field readings | Medium | Mostly fixed | PID-3 `PI` and PID-5 `I` repetitions chosen; 10-digit time keeps its hour. Main-diagnosis flag and 転帰 still not read. |
| STD-025 one bad date stops a table | Medium | Fixed | Run: one bad row of 303 is rejected and counted, the night passes; over 1 % holds. |
| STD-030 standard concept ids | High | Fixed in code, not run | `omop/vocab.py:224-246` follows `Maps to` and the ATC to RxNorm links. Needs an Athena load to show. |
| STD-040 old rulesets without families | High | Fixed | `rulesets/RA-BIO/valuesets/VS_RHEUMATOID_ARTHRITIS.json` now 418 codes (M05, M06 families); tuberculosis 61. |
| STD-042 Japan drug-class path | High | **Partly** | The path exists: order line → YJ stem → ingredient → ATC (`refdata_jp.DrugResolver`), unresolved codes listed by volume in `reader.json`. Shipped content is 56 ingredients (`refdata_src/jp_yj_atc.csv`) and 22 `verify` rows; the rest is each site's table. Run: an unknown YJ code and a HOT-only order are kept with no ATC and counted. |
| STD-043 JLAC10 by full 17 characters | Medium | Open | Run: the same analyte with another method code is dropped. 14 sample rows, all `verify` (DIN-020). |
| STD-060 REDCap version parsed as JSON | High | Fixed | `rc_bridge/client.py:136-139` reads plain text. Not run against a real REDCap. |
| STD-061 REDCap validation types | Medium | Mostly fixed | `datacore/forms.py:336-405`: time, e-mail, phone, `number_Ndp`, comma decimals. |

## 3. Findings

Severity as in the brief. "Run" = reproduced by a script named in the header; exact input and output are in §4.

| ID | Severity | Finding | Evidence | Impact | Fix | Card | Flag |
| --- | --- | --- | --- | --- | --- | --- | --- |
| DIN-001 | Blocker | The feed's date parser (`engine.py:_parse_date`, `_parse_dt`) has no ROC or era reading and no range check. `strptime("%Y%m%d")` accepts 7 and 6 digits: `1150501` → **1150-05-01**, `0490301` → **0490-03-01**, `640715` → **6407-01-05**. A feed whose dates are all in months 01 to 09 passes whole. | Run `t3_pipe.py` C9: lab, medication and diagnosis dates `11505dd` → night `passed=True`, lake `effective=1150-05-01`, `authored=1150-05-01`, `onset=1150-05-01`. C2: births `0490301`, `640715` → `passed=True`, `birth_date` 0490-03-01 and 6407-01-05. Only months 10 to 12 are rejected (`1151001`), so a full ROC table is held by luck (25 % rejects), a delta or a young extract is not. | Every look-back window misses the record: "drug in the last 90 days" reads no drug, so an exclusion does not fire and the patient is listed; age is 1,500 years. Site survey question 29 A offers "ROC 7-digit" as an answer the adapter cannot take. | (1) Refuse any parsed year outside 1900 to the night's year + 1 (birth: 1880 +) as a rejected row. (2) Require exactly 8 digits for the compact form. (3) Add mapping types `roc_date`, `era_date` that call `tb_common.dates`, set per column. (4) Test with the corpus in §4.2. | NEW-DIN-1 "Feed dates: range check, ROC and era types" (S) | Go-live TW |
| DIN-002 | Critical | `fhir_bulk`: the pseudonym is `HMAC(key, Patient.id)`, the identifier is dropped, and no pid-map row is written. | Run `t10_bulk.py` F4: lake pid = `HMAC("p1")` ≠ `HMAC("00012341")`; `pid_map.resolve_many(lake pids)` = `{}`. `pipeline.py:157-198`, `:580`. | On a FHIR-fed site a candidate's chart number cannot be revealed, an opt-out typed by chart number never matches a patient, and sheet or chart facts never join the feed's patient. | Take the chart number from the identifier the site names (system or `type` MR / PI in settings), hash that, write the pid-map row; refuse a Patient without it. | NEW-DIN-2 "FHIR feed: pseudonym from the chart-number identifier, pid map filled" (M) | Later (before any FHIR-fed site) |
| DIN-003 | Critical | The opt-out desk turns any chart number into a pseudonym and registers it without checking that the box knows that patient; under the default rule `asis` leading zeros are significant, and nothing in `deploy/`, the wizard or the runbook sets `TB_CHARTNO_RULE`. | Run `t9_key.py`: `pid("12345") == pid("00012345")` → False. `console/team.py:962-981`, `orchestrator/setup_api.py:323-330`, grep `TB_CHARTNO_RULE` in `deploy`, `tools`: none. | A typed number without its zeros is "registered" for nobody; the patient stays in screening and can be contacted after refusing. | `/setup/pseudonym` answers whether the pid is in the pid map; the page says "not a patient of this box" and asks again (keep a "register anyway" with a reason for a patient not yet in the feed). The installer asks the chart-number format once and writes the rule. | NEW-DIN-3 "Opt-out desk checks the patient is known; chart-number rule set at install" (S) | Go-live both |
| DIN-004 | High | SS-MIX2: the current version of a file is chosen by (patient, type, order number), without the day. An order number used again on another day replaces the earlier order. | Run `t5_ssmix.py`: OML-11 order `O1` on 2026-10-01 (18 results) and order `O1` on 2026-10-15 (1 result) → only the second is read; no count, no message. `ssmix2/source.py:327-331`. | If a hospital's order numbers repeat (per day or per year), earlier labs, orders and diagnoses vanish; criteria read "no result". Unknown for the Japan site until its storage is seen. | Key by (patient, day, type, order). Count "same order number on another day" in `reader.json` so the site check shows it either way. | NEW-DIN-4 "SS-MIX2 version key includes the day; collisions counted" (S) | Go-live JP |
| DIN-005 | High | SS-MIX2 PPR-01: an ICD-10 code in the first triple of PRB-3 (`E11.9^糖尿病^I10`) is not read; only the alternate triple is. The Condition is stored with no code. | Run `t5_ssmix.py` D4, D5: `icd10=''`, Condition `code.coding=[]`; counted in `missed` only. `source.py:540`, `_alt` (`:182`). | A vendor that sends ICD-10 first gives every diagnosis no code: no disease criterion can be met. | Read ICD-10 from whichever triple names `I10` / `ICD10`. | NEW-DIN-5 "PRB-3: ICD-10 in either triple" (S) | Go-live JP |
| DIN-006 | High | CSV and SQL feeds: a lab row whose local code is not in the look-up is dropped by the resource's `where`, with no count in `ingest_report.json` or `completeness.json`. The look-up is exact: `" CRE "` and `cre` do not match `CRE`. | Run `t3_pipe.py` C6 (`GLU-AC` dropped, report shows nothing), `t4_csv.py` E12 (`" CRE "`, `cre` dropped: 1 Observation of 3, `passed=True`). `demo_his.yaml:161`, `engine.py:313`. | A fixed-width HIS column pads codes with blanks: every result of that analyte is gone and its criteria read "no data" each night, with nothing to see. `mapping_check` shows it only when someone runs it. | Strip and case-fold the key for the look-up; count unmapped local codes per night by volume (as `reader.json` does for SS-MIX2) and show the top ones on the data-operations page; hold when a mapped code's nightly count falls to zero. | NEW-DIN-6 "Nightly unmapped-code report for every source; look-up key normalised" (S) | Go-live TW |
| DIN-007 | High | D-275's rule "a code the map does not know is `unknown`, never the default" covers lab and order status only. Diagnosis status, encounter class and appointment status still fall to the default: `X` → `active`, an unknown class → `AMB`, an unknown appointment status → `booked`. | Run `t3_pipe.py` C6: diagnosis `status=X` → lake `status=active`, `passed=True`. `demo_his.yaml:116` (`default: AMB`), `:129` (`default: booked`), `:142` (`default: active`). | A deleted or ruled-out diagnosis under a site's own code counts as active and can include or exclude; a cancelled visit under an unknown code is shown as booked on today's list. | Add `unmapped:` to the three elements (Condition: `verificationStatus` unconfirmed or no clinicalStatus; appointment: leave out) and count them. | NEW-DIN-7 "Unknown status codes are unknown for diagnoses, visits and appointments" (S) | Go-live both |
| DIN-008 | High | The completeness gate compares with the last good night. On the first night there is none, `required_tables` is empty by default and absent from `deploy/settings.example.yaml`, so a missing or empty table passes and becomes the baseline. | Run `t2_pipe.py` B1 (`lab.csv` missing, first night): `passed=True`, `CURRENT` set, no Observation. B2 (`medication.csv` header only): passed. | Go-live night is the first night. A table missing then is never asked for later. | A first night requires every table the mapping declares unless the site lists it in `optional_tables`; ship that default. | NEW-DIN-8 "First night: every mapped table required" (S) | Go-live both |
| DIN-009 | High | Unit spellings are a closed table in code (`labunit.UCUM`). `units_agree` is False when either side is not in it, even when the row's unit and the look-up's `source_unit` are the same text. Not in the table: `×10^3/µL` (multiplication sign), `x10^4/μL`, `千/μL`, `/HPF`, `COI`, `S/CO`, `秒`, `copies/mL`, `LogIU/mL`, `mL/min`, `g/gCr`, `mg/day`, `mL/分/1.73m2`. The night's report does not count `unit_mismatch`. | Run (`labvalue.read`, 32 pairs, §4.1). `labvalue.py:119-128`. | Safe (no value, never a wrong one) but those analytes are unknown at the site until a code release, and nobody sees how many results a night lost to it. | A site file of unit spellings (`unit_aliases.csv`: spelling → UCUM code or "site unit, same as look-up"), checked by `mapping_check`; count `unit_mismatch` per analyte in the night's report. | NEW-DIN-9 "Site unit spellings as data; unit-mismatch counts in the night report" (M) | Go-live both |
| DIN-010 | High | A FHIR partial date (`1960-03`, `2026`), which the standard allows, raises `ValueError` in the lake flattener; the whole rebuild fails. | Run `t10_bulk.py` F2, F3: `errors=["lake rebuild failed: Invalid isoformat string: '1960-03'"]`, `passed=False`. `lake/flatten.py:383-393`. | One such record stops every night of a FHIR-fed site (loud, but total). The sheet and chart paths also refuse year-month dates. | Read `YYYY` and `YYYY-MM` as a date with a precision; an imprecise date decides a window only when the whole period lies inside or outside it, else unknown. | NEW-DIN-10 "Partial dates read with their precision" (M) | Later (before any FHIR-fed site) |
| DIN-011 | Medium | FHIR reader, still narrow: a Condition's first coding wins (SNOMED before ICD-10 loses the ICD-10); `valueInteger`, `valueBoolean` and `interpretation` give no value; a MedicationRequest with `doNotPerform: true` or `intent: proposal` counts as an order; `issued` is not a fallback time. | Run `t6_fhir.py`. `flatten.py:487-489`, `:501-522`, `:570`. | Missed inclusions (unknown) on a FHIR feed; a "do not give" order counted as exposure. | Prefer the ICD-10 coding; read the three value forms; void `doNotPerform`; leave non-order intents out. | T-616 follow-up, else NEW-DIN-11 "FHIR reader: coding choice, value forms, doNotPerform" (S) | Later |
| DIN-012 | Medium | Placeholder dates are facts: a death date `9999-12-31` makes the patient deceased; birth `1900-01-01`, a lab dated `2999-12-31` and a lab five days after death load with no mark. | Run `t3_pipe.py` C5, `t9_key.py` T1. | A living patient dropped from screening; ages of 126; a future result is "the latest". | With DIN-001's range check: a future clinical date and a date before 1900 are rejected rows; `9999-12-31` and `2999-12-31` in an end or death column read as empty (settable list). | NEW-DIN-1 | Go-live both |
| DIN-013 | Medium | The data contracts (types, `not_future`, control totals) run only when `TB_DATA_CONTRACTS` is set. No deploy file sets it; the only contract set is the demo HIS. | `cli.py:158`, `governance.py:144-150`; grep in `deploy/`: none. | The "controls moved from the data platform" (DATA-002) are not on at a site. | Generate a contract set from the site mapping at set-up and switch it on in the box profile. | NEW-DIN-12 "Contracts generated from the site mapping, on by default" (M) | Go-live both |
| DIN-014 | Medium | Time of day read wrong or lost: `202605120830` (12 digits) → **08:03**; `2026-05-12 08:30:00.000` and SQL `datetime` values with a fraction → 00:00; `24:00:00` → the same day 00:00. | Run `t1_lab.py`. `engine.py:209-226`; `cgrd_sql/source.py:43` (`str(v)`). | Same-day ordering of results and "latest value" can be wrong; the date stays right. | Accept a fraction; require 14 digits or handle 12; refuse `24:00`. | NEW-DIN-1 | Go-live both |
| DIN-015 | Medium | CSV reader: comma only. A tab, semicolon or UTF-16 file, or a header in another case, ends the night with a bare `KeyError: 'mrn'` (no table quarantine, no plain reason). A short row (`L2,00012346,CRE`) loads as a result with no value and no date. Two rows with one key and different values: the last wins, counted only; the report says 5 Observations, the lake holds 3. | Run `t4_csv.py` E4 to E7, E10; `t3_pipe.py` C7. | Loud but opaque on the first; a cut line or a corrected result goes unseen on the others. | Detect the delimiter from the header against the mapping's columns, else quarantine the table with the reason; reject a row with fewer cells than the header; report conflicting duplicates by count and hold over a share. | NEW-DIN-13 "CSV reader: delimiter, short rows, conflicting duplicates" (S) | Go-live TW |
| DIN-016 | Medium | Sheets: `parse_number` removes commas, so `7,2` is **72**; `<0.3`, `7.0 H` and `＞20` are dropped without a word (the sheet path does not use `labvalue.parse`); a percent-formatted HbA1c cell arrives as `0.072`; a formula with no cached value is blank; a tab or semicolon CSV gives one column and no records with no error; the header `檢驗日` gets the role `ignore`, so every fact of that sheet is undated. | Run `t8_sheet.py`. `messy.py:241-250`, `intake.py:44-61`. | A person confirms units, so most is caught; the dropped censored values and the undated sheet are not shown. | Use `labvalue.parse` (comparator kept); refuse `d,d`; list dropped cells in the import summary; add 檢驗日, 採檢日, 抽血日, 検査日, 採取日 to the date words; sniff the delimiter. | NEW-DIN-14 "Sheet reader: one number parser, dropped cells listed, date headers" (S) | Go-live both |
| DIN-017 | Medium | A lab row with an empty unit takes the look-up's unit with no plausibility check: `CRE 88 ''` → 88 mg/dL, `HbA1c 0.072 ''` → 0.072 %, `CRP 5 ''` → 50 mg/L. The sheet path has plausible ranges, the feed has none. | Run `t1_lab.py`. D-149 by decision. | A feed with a blank unit column and SI values gives wrong numbers with a correct-looking unit. | Keep D-149, add the analyte's plausible range (the `messy.ANALYTES` ranges, moved to `labunit`): outside it and unit-less → no value, counted. | NEW-DIN-9 | Go-live both |
| DIN-018 | Medium | Chart upload: the chart's day is the first date found in its text, else **today**, and a finished out-patient Encounter is written for that day. Limits `MAX_CHART_BYTES` 20 MB and `MAX_CHART_CHARS` 60,000 are constants, not settings (OD-10). Word headers, footers and text boxes are not read. | Read: `service.py:214`, `publish.py:172-183`, `charts.py:40-41`, `:84-91`. | A visit that did not happen can meet "seen in the last 12 months"; a long in-patient chart is refused. | No Encounter from a chart; the document's date empty when none is found; the two limits as settings with their reason (the model context already sizes the parts). | NEW-DIN-15 "Charts: no invented visit; limits as settings" (S) | Go-live both |
| DIN-019 | Medium | Exports write cell text as it is: openpyxl stores a string starting with `=` as a formula, CSV writes it raw. | Run `t11_scale.py`: `ws.append(["=1+1", '=HYPERLINK(...)'])` → cell types `f`, `f`. `datacore/export.py:105-126`, `console/screening_log.py`, `orchestrator/reports/candidate_xlsx.py`. | A free-text value (an EDC field, a REDCap value read back, a drug name from the feed) becomes a live formula in a workbook sent to a sponsor. | One `safe_cell()` for every export: prefix `'` (or set the cell type to string) for text starting with `=`, `+`, `-`, `@`, tab, CR. | NEW-DIN-16 "Formula-safe cells in every export" (S) | Go-live both |
| DIN-020 | Medium | Code tables are samples: JLAC10 → LOINC 14 rows, all `verify`, matched on the full 17 characters; TW local → LOINC 14 rows; YJ → ATC 22 `verify` rows plus 56 ingredients. No check ties a study's value sets to the site's tables ("which criteria of this study can no code of this site reach"). | `mapping/jp_core/*.csv`, `tw_core/lab_local_to_loinc.csv`; run `S-OTHERMETHOD` dropped. | The real mapping work is per site and unsized in the plan; a criterion can be undecidable for every patient and look like "nobody matches". | A per-study coverage report at set-up: for each lab, drug and diagnosis criterion, the count of feed records that reach its value set; zero is shown as "not mapped", not as zero patients. JLAC10 match on analyte + material with the method as a hint. | T-610 / T-619 follow-up, else NEW-DIN-17 "Per-study code coverage report" (M) | Go-live both |
| DIN-021 | Medium | A chart number that changes at the hospital is a new pseudonym with no warning; a merge is recorded only by hand (`adapter pid-merge`). No feed carries merges (no ADT merge read, no merge table in the canonical set). | Run `t9_key.py` K4: night passed, nothing reported. `cli.py:196-264`. | Marks, the opt-out and the screening history stay on the old pseudonym. | An optional canonical `merge` table (old chart number, new, date) and SS-MIX2 ADT merge messages feed `PidMap.merge`; report "patients gone and new patients with the same birth date and sex" as a hint. | NEW-DIN-18 "Chart-number merges from the feed" (M) | Later |
| DIN-022 | High | Registered as F-05 (scale review); measured again here: `run_ingest` holds 4.6 KB of memory per lab row before the snapshot is written and maps 3,700 rows per second on one core. | Run `t11_scale.py`: 200,000 rows, 13 MB file, peak 961 MB, 54 s. | 20 million lab rows: about 92 GB and 1.5 h for one table; the adapter container has 6 GB. The nightly default is a full run. | As T-692: the night through the streaming spool of `backfill.py`. | T-692 | Go-live both |
| DIN-023 | Low | The engines convert mass to substance for creatinine and CRP only; glucose, cholesterol, calcium, urate in `mmol/L` read unknown, though the adapter's table has the factors. `x10^4/μL` (Greek mu) is missing beside `x10^4/uL`. | Run `t7_units.py`. | Unknown, never wrong. | One analyte table for both readers. | NEW-DIN-9 | Later |

## 4. The runs, case by case

Verdicts: **pass** (right value, or no value where none can be known), **wrong-silently**, **rejected-loudly** (row rejected and counted, table quarantined, or night held).

### 4.1 Units (feed path: `Mapper.map_row` with `tw_core/demo_his.yaml`; SS-MIX2 gave the same)

| Input (code, value, unit) | Output | Verdict |
| --- | --- | --- |
| CRE, `88`, `umol/L` or `µmol/L` | no value, `unit_mismatch` | pass (STD-001 fixed) |
| CRE, `0.9`, `mmol/L` | no value, `unit_mismatch` | pass |
| CRE, `1.0`, `mg/dL` / `MG/DL` / `mg/dl` / `mg%` / `ｍｇ／ｄＬ` | 1 mg/dL | pass |
| CRE, `88`, empty unit | 88 mg/dL | wrong-silently when the site reports µmol/L (DIN-017) |
| HBA1C, `7.2`, `%` | 7.2 % | pass |
| HBA1C, `55`, `mmol/mol` (IFCC) | no value, `unit_mismatch` (never converted: offset equation) | pass |
| HBA1C, `7.2`, `% (NGSP)`; `6.8`, `%(JDS)` | no value, `unit_mismatch` | pass |
| HBA1C (JDS JLAC10 code `3D045…`), `6.8`, `%` | no Observation (code not in look-up), counted in `reader.json` | pass |
| HBA1C, `0.072`, empty unit (a fraction) | 0.072 % | wrong-silently (DIN-017) |
| CRP, `0.5`, `mg/dL` (look-up: source mg/dL, factor 10) | 5 mg/L | pass |
| CRP, `5`, `mg/L` | no value, `unit_mismatch` | pass |
| ALT, `35`, `IU/L` against `U/L` | no value, `unit_mismatch` | pass (kept apart on purpose) |
| ESR, `20`, `mm/hr` / `mm/1h` | 20 mm/h | pass |
| UA, `１２．５` (full width) | 12.5 | pass |
| UA, `<0.3`; `>20` | 0.3 with comparator `<`; 20 with `>` | pass |
| UA, `7.0 H` | 7 | pass |
| UA, `7,2` (comma decimal) | text `7,2` (unknown) | pass |
| UA, `1,234` | 1234 | pass (thousands); a European `1,234` would be wrong, not expected in TW / JP |
| UA, `1.5E1`; `trace`; `+`; `7.0mg/dL` | text (unknown) | pass |
| HBSAG, `陰性`, `(-)`, `-`, `NEG`, `Negative`, `Non-Reactive`, `陰性(-)` | LA6577-6 Negative | pass |
| HBSAG, `陽性`, `+`, `＋`, `1+` | LA6576-8 Positive | pass |
| HBSAG, `弱陽性`, `trace`, `0.01`, `<0.05 陰性` | text (unknown) | pass |
| `XYZ` (unmapped), `" CRE "`, `cre` | no Observation, nothing reported | wrong-silently (DIN-006) |

Engine side (`labunit.convert`, 46 pairs): creatinine µmol/L ↔ mg/dL (88.4), CRP mg/dL ↔ mg/L, haemoglobin g/dL ↔ g/L, platelets `10*3/uL` ↔ `/uL` ↔ `万/µL` ↔ `10^9/L` ↔ `K/uL`, weight, height: all right. Glucose, cholesterol, calcium `mmol/L` → `mg/dL`: None (unknown; the adapter's table has 18.016, 38.665, 4.0078, so the factors differ per analyte as they should). `%` against a fraction, `%` against `mmol/mol`, `mL/min` against `mL/min/1.73m2`, `IU/L` against `U/L`, a missing unit: None. No pair gave a wrong number.

Unit spellings that give no value even against the same text in the look-up (DIN-009): `×10^3/µL`, `千/μL`, `/HPF`, `COI`, `S/CO`, `index`, `秒`, `mm/時`, `copies/mL`, `LogIU/mL`, `mg/day`, `g/gCr`, `mL/min`, `x10^4/μL` against `万/µL`, `個/μL`, `‰`, `titer`, `倍`.

### 4.2 Dates (feed path)

| Input | Output | Verdict |
| --- | --- | --- |
| `2026-05-12`, `2026/05/12 08:30`, `20260512`, `2026/5/12`, `20260512083000` | right | pass |
| `1130512` (ROC 113-05-12) | **1130-05-12** | wrong-silently (DIN-001) |
| `0113/05/12` | **0113-05-12** | wrong-silently |
| `0490301`, `640715` (ROC births) | **0490-03-01**, **6407-01-05** | wrong-silently |
| `1151001` (ROC, month 10) | rejected: unparseable | rejected-loudly |
| `113/05/12`, `113-05-12`, `民國113年5月12日`, `令和6年5月12日`, `R6.5.12`, `H31.4.30`, `2026年5月12日`, `2026.05.12` | rejected | rejected-loudly (a whole ROC or era feed cannot load: no mapping type) |
| `12/05/2026`, `05/12/2026`, `12-05-2026` | rejected | rejected-loudly |
| `2026-05`, `2026`, `202605` (partial) | rejected | rejected-loudly |
| `45789`, `45789.5` (Excel serial) | rejected | rejected-loudly |
| `2026-02-30` | rejected | rejected-loudly |
| `1900-01-01`, `0001-01-01`, `2099-12-31`, `2999-12-31`, death `9999-12-31` | accepted as written | wrong-silently (DIN-012) |
| `202605120830` | 2026-05-12 **08:03** | wrong-silently (DIN-014) |
| `2026-05-12 08:30:00.000` | 2026-05-12 **00:00** | wrong-silently (time lost) |
| `2026-05-12 24:00:00` | 2026-05-12 00:00 | wrong-silently (a day early) |
| `2026-05-12T23:30:00Z` | kept, then 2026-05-13 07:30 site time in the lake | pass |
| `2026-05-12T00:30:00+09:00` | kept with its offset | pass |
| death date `Y` | row rejected; 1 of 3 holds the night | rejected-loudly |

Sheet and chart path (`messy.parse_date`): `1130512`, `113/05/12`, `113.05.12`, `民國113年5月12日`, `113年5月12日` → 2024-05-12; `令和6年5月12日`, `R6.5.12` → 2024-05-12; `H31.4.30` → 2019-04-30; `平成元年1月8日`, `昭和64年1月7日` right; `H31.5.1`, `S64.1.8` → a question with the Gregorian reading; `12/05/2026`, `05/12/2026` → a question (day/month order); `13/05/2026` → 2026-05-13; `5/12/26`, `99年3月15日`, `990315`, `12052026`, `2026-05`, `1150229`, `R8.2.30` → not read, asked; `45789` → 2025-05-12 (Excel serial); `1900-01-01`, `9999-12-31`, `0001-01-01` accepted with no question. All pass except the last three (DIN-012).

### 4.3 Facts and completeness (whole `run_ingest`, real lake)

| Case | Result | Verdict |
| --- | --- | --- |
| `lab.csv` missing, header only; `patient.csv` header only (after a good night) | held, `CURRENT` unchanged | rejected-loudly (DATA-001 fixed) |
| The same on the first night | `passed=True` | wrong-silently (DIN-008) |
| Empty export folder, first night | lake refuses, held | rejected-loudly |
| Site key missing; another key | `SiteKeyError` | rejected-loudly (DATA-004 fixed) |
| Lab chart numbers without leading zeros, `mrn_regex` set | table refused (`lost_zeros`), held | rejected-loudly |
| The same, `123456.0` style | refused (`excel_number`) | rejected-loudly |
| The same, no `mrn_regex` | passes; 3 of 3 labs point at no patient; counted as orphans only | wrong-silently (the schema default `^\d{8}$` normally prevents it) |
| Full-width digits and blanks around a chart number | joined to the patient | pass (DATA-005 normaliser) |
| CP932 with `髙`, `①`, half-width kana; UTF-8 BOM | loads | pass |
| Big5, 3 rows, no declared encoding | quarantined ("cannot be told for certain"), held | rejected-loudly |
| Tab, semicolon, UTF-16, upper-case header | `KeyError` ends the night | rejected-loudly, opaque (DIN-015) |
| No `unit` column | rows rejected, held | rejected-loudly |
| Unquoted comma shifts a row | row rejected | rejected-loudly |
| Short row | result with no value and no date | wrong-silently (DIN-015) |
| Footer line `Total: 3 rows` | ignored | pass |
| Identical duplicate row; same key, other value | one row, last value (9.9) wins; counted | wrong-silently for the conflicting pair (DIN-015) |
| Diagnosis status `X` | `active` | wrong-silently (DIN-007) |
| Sex `男` (not mapped) | no sex (unknown) | pass |
| One patient's chart number changes | passes as a new patient | wrong-silently (DIN-021) |
| Test patients (`TEST0001`, 測試病人) | loaded as patients | not handled anywhere; a site filter is needed (in DIN-012's card) |
| Deceased patient with a lab after death | both loaded, no mark | Low; noted under DIN-012 |
| SS-MIX2 OBX-11 `D`, `C`, `X`, `P`, empty | tombstone; replaces; cancelled; no usable value; counts, tagged not recorded | pass |
| SS-MIX2 order `CA`; unknown `ZZ`; no ORC-5 | cancelled; unknown; unknown tagged not recorded | pass |
| SS-MIX2 suspected diagnosis (PRB-13 `1`, or 疑い in the name) | provisional, never coded | pass |
| SS-MIX2 same order number, another day | first day's 18 results gone | wrong-silently (DIN-004) |
| SS-MIX2 PRB-3 `E11.9^…^I10` | Condition with no code | wrong-silently (DIN-005) |
| FHIR `entered-in-error` result, `refuted` diagnosis, `not-done` procedure, `not-taken` statement | no row | pass |
| FHIR `FamilyMemberHistory` | not read (never a patient diagnosis) | pass |
| FHIR `doNotPerform: true` order | counted as an order | wrong-silently (DIN-011) |
| FHIR SNOMED before ICD-10 | SNOMED kept, ICD-10 lost | wrong-silently (DIN-011) |
| FHIR `valueString` 陰性 on a LOINC code (bulk feed) | LA6577-6 | pass |
| FHIR partial `birthDate` or `effectiveDateTime` | rebuild fails | rejected-loudly, whole night (DIN-010) |

## 5. What to drop or simplify

- **Three number readers** (`labvalue.parse`, `messy.parse_number`, `Decimal` in the mapping engine) and **three date readers** (`engine._parse_date`, `messy.parse_date`, `tb_common.dates.parse`). Keep `labvalue` and `dates`; the engine and the sheet reader call them. Most findings above sit in the copies.
- **Two unit tables** (`messy._UNITS` / `ANALYTES` with 88.42, `labunit` with 88.4). One.
- **`site_params.yaml`** at the repository root still describes a demo site with keys nothing reads for the feed (`his.tables`, `code_systems`); the settings file and the mapping are the truth. Remove or mark as demo only.
- **The Encounter invented from a chart's date** (DIN-018): drop it.
- **`fhir_bulk` as a go-live source**: neither site uses it. Keep it for tests and state in DATA.md that it is not ready for a site until DIN-002, DIN-010 and DIN-011 are done.

## 6. What the plan must change

1. **Before any real extract is loaded (S, first):** NEW-DIN-1 (date range, ROC, era, time forms), NEW-DIN-6 (unmapped codes counted, key normalised), NEW-DIN-7 (unknown status), NEW-DIN-8 (first night). Four small cards, no dependencies.
2. **Opt-out input (S):** NEW-DIN-3, before the opt-out desk is used at either site; depends on nothing.
3. **Japan (S + S):** NEW-DIN-4 and NEW-DIN-5 before the first SS-MIX2 storage from the Japan site is read; add to the site check a count of repeated order numbers and of PRB-3 coding systems seen.
4. **Site data survey answers are inputs to code, not notes:** question 29 A (date format, delimiter, encoding) must map to settings the adapter takes (NEW-DIN-1, NEW-DIN-13). Add to the survey: chart-number format (width, zeros), placeholder dates in use, whether order numbers repeat, test-patient convention, how merges are told.
5. **Mapping content is the long task (M to L per site):** size it in v7 as its own line per site with the coverage report (NEW-DIN-17) as its exit, and NEW-DIN-9 (site unit spellings) before it. T-692 (streaming night) stays a go-live blocker for a full-hospital nightly.
6. **FHIR feed (M + M + S):** NEW-DIN-2, NEW-DIN-10, NEW-DIN-11 as one work package, scheduled only when a FHIR-fed site is planned.

## 7. Needs GCP / owner hardware

None of this area needs a GPU. Three tests need data only a site has:

1. **Real CGMH extract shape:** run `tools/mapping_check.py --mapping <site>.yaml --source csv --path <extract>` on one day of the real export on the box; record date formats seen per column, unmapped lab codes by volume, unit spellings not in `labunit.UCUM`, duplicate keys. Pass: no date outside 1900 to today, every unit spelling in the table or the site alias file, unmapped volume listed and signed off by the lab.
2. **Real SS-MIX2 storage (Japan):** `python -m adapter.cli run --source ssmix2 ...` on a one-month copy; record `reader.json` (`quarantined`, `missed`, `read as cp932`), the count of order numbers that repeat across days, PRB-3 coding systems. Pass: 0 quarantined over 1 %, 0 repeated order numbers lost (after NEW-DIN-4).
3. **Full-size night:** the real row counts through the nightly on the box (after T-692): record peak RSS of the adapter and wall time. Pass: under the container's memory, inside the night window.

## 8. Small certain fixes

1. **DIN-001 (Blocker).** `services/adapter/mapping/engine.py:_parse_date` (about line 229): for the compact form require `len(raw) == 8 and raw.isdigit()` before `strptime("%Y%m%d")`; after any successful parse, `if not 1880 <= d.year <= date.today().year + 1: raise MappingError("date out of range")`. Same check at the end of `_parse_dt`. First failing test: `Mapper.convert("1130512", "date")` must raise; today it returns `1130-05-12`.
2. **DIN-005 (High).** `services/adapter/sources/ssmix2/source.py:540`: `icd = who_icd10(prb.comp(3, 1) if prb.comp(3, 3) in ("I10", "ICD10") else _alt(prb, 3, ("I10", "ICD10"))) or self._icd(code)`. First failing test: a PRB `E11.9^糖尿病^I10` row must give `icd10 == "E11.9"`.
3. **DIN-004 (High).** `source.py:327`: `key = (sf.patient, sf.type, sf.order, sf.day)`. First failing test: two OML-11 files, same order number, two days, both read. (Check with the Japan site first whether a changed order can move to another day folder; if so keep the old key for that case and count collisions.)
4. **DIN-006 (High), half.** `engine.py:313` and `:400`: look the key up as `str(row.get(key, "")).strip()`. First failing test: local code `" CRE "` gives an Observation.

## 9. What is good

- Units: the row's own unit is checked on every mapped path; nothing is converted on a guess; a mismatch is no value, never a wrong one. The conversion table has per-analyte molar masses and a test against textbook factors.
- Qualitative results in Japanese, Chinese and English, with borderline words left unknown on purpose.
- The night: site key refused when wrong, completeness gate, per-row rejects with a 1 % hold, quarantine of unreadable files, a held re-run that never touches `CURRENT`.
- SS-MIX2 decoding and OML-11 statuses are done properly and tested with hard cases.
- The sheet path asks a person instead of guessing (day/month order, era boundary, unit), refuses chart-number columns that Excel turned into numbers, and never stores the chart number.
- Encoding detection refuses rather than guesses; no U+FFFD reaches a record.

## 10. What was not checked

- No real hospital extract, SS-MIX2 vendor file, REDCap server, Athena bundle or licensed master (MEDIS, JLAC10, YJ, NHI). Every "Go-live" verdict on formats is from synthetic data.
- `cgrd_sql` was read, not run against Oracle or SQL Server (column case, `NUMBER` chart numbers, `datetime2` fractions are by reading and by the string forms I fed the mapper).
- OMOP load, vocabulary mapping, the derived store, DQD and the opt-out worker were read, not run.
- The chart path's LLM extraction (which facts the model dates or drops, G1 bug B1 / D-470) needs the real models; I ran only the D-470 unit test (passes: an undated chart fact stays unknown).
- Age and sex at the index date are computed in the compiler and engines (another reviewer's area); I checked only what the lake stores.
- The console upload routes and `demo_guard` were read, not driven over HTTP; PDF, OCR and DOCX parsing were not run on files.
- DATA-006 (COHORT suppression) was not checked; DATA-020, 021, 022, 025 are "fixed in code" by reading only.
- Whether real SS-MIX2 order numbers repeat across days (DIN-004) and whether a vendor sends ICD-10 first in PRB-3 (DIN-005) is not known; both were produced on synthetic files.
