# TB-DS-08 Interface Control Document

| Field | Value |
| --- | --- |
| Document | TB-DS-08 Interface Control Document (ICD) |
| Version | 0.7 (reference; frozen for the build stage) |
| Date | 2026-11-07 |
| Owner | Aimedics (author: Claude, for Changfu Kuo) |
| Status | Frozen reference for the build stage (TB-DS-20). Closes review finding M-02 (TB-REV-006); expands TB-DS-02 §8.13 with payload schemas, error codes and conformance tests. |
| Approvals | Product owner: — · Hospital IT (JP): — · Hospital IT (CGMH): — · REDCap administrator (JP): — · REDCap administrator (CGMH): — |
| Build stage | `20-build-map.md` decides which interfaces each build step needs: step 3 uses ICD-04 R1–R3, R7, R8, §4.1a (`tb_screening_no` mode) and the simulator §4.4; step 2 uses ICD-13 N1 and N2 only; ICD-06 DET, ICD-14 `shadow_log`, the `mrn` link mode, N3/N4 and the notice budget are H or L. Headings and the §1 table carry the build tag (legend TB-DS-00 §2: S0 built, S1–S5 build step, H hospital stage, L later). |
| Canonical values | TB-DS-00. Ports: TB-DS-02 §7 port table (gateway 8020, rc-bridge 8096). |

## 1. Purpose and scope

This document defines every interface between TrialBox and an outside system, and the two user-facing command interfaces (mail and chat). For each: parties, direction, transport, authentication, message formats with JSON Schema (draft 2020-12), error codes, versioning, and how conformance is tested.

| ID | Interface | Direction | Release |
| --- | --- | --- | --- |
| ICD-01 | Source readers: CSV / SQL with site mapping YAML | Hospital → TrialBox | S0 (built) |
| ICD-02 | Source reader: SS-MIX2 standardised storage | Hospital → TrialBox | H |
| ICD-03 | Source reader: FHIR bulk NDJSON | Hospital → TrialBox | S0 (built) |
| ICD-04 | REDCap API (read set) | TrialBox → REDCap | S3 |
| ICD-05 | REDCap API (write set, via External Module) | REDCap module → REDCap, on TrialBox's proposal | L |
| ICD-06 | REDCap Data Entry Trigger | REDCap → TrialBox | H |
| ICD-07 | REDCap External Module ↔ appliance `/rc/v1` | REDCap server ↔ TrialBox | L |
| ICD-08 | Mail command channel | Staff ↔ TrialBox | S0 (built); extensions S1 / L |
| ICD-09 | Chat command box | Console user → TrialBox | S4 |
| ICD-10 | Consortium envelope | Site ↔ hub | L |
| ICD-11 | Update bundle | Aimedics → site (offline) | S0 (built); additions H |
| ICD-12 | Diagnostics bundle | Site → Aimedics (offline) | H |
| ICD-13 | Outbound notices: PI clinic-day / Monday list, CRC digest, real-time notices | TrialBox → staff (mail; Web Push later, L) | S2 (N1, N2); H (N3, N4, N6); L (N5) |
| ICD-14 | Upload files: the weekly Phase-1 comparison log (upload kind `shadow_log`) and personal study database import | Staff / research office → TrialBox (on-prem web upload only) | H |

All JSON is UTF-8. Dates are ISO 8601. Times on the wire are UTC with `Z` unless stated. Every TrialBox-defined schema has an `$id` under `https://trialbox.local/schemas/` and lives in `trialbox/schemas/` (existing) or the new folders `schemas/rc_v1/`, `schemas/fed/` [target]. Generated pydantic models in `libs/tb_contracts` stay the only way services exchange messages (built rule).

## 2. Common rules

### 2.1 Versioning

| Item | Rule |
| --- | --- |
| TrialBox-defined schemas | Semantic version in the `description` (`Schema version x.y.z`) and in the path (`/rc/v1`, `envelope_version`). Minor = additive, optional fields only. Major = new path or version value; the previous major is served for at least one release. |
| External APIs (REDCap) | TrialBox declares supported REDCap versions (LTS 16.x at the pilot sites). `rc-bridge` reads `content=version` at connect and refuses unsupported majors with error `RC-VERSION`. |
| Mapping YAML | `version:` key (integer). The adapter refuses an unknown version. |

### 2.2 Error model

HTTP interfaces served by TrialBox return RFC 9457 problem details:

```json
{
  "type": "https://trialbox.local/errors/RC-FORBIDDEN",
  "title": "Not allowed for this REDCap user",
  "status": 403,
  "code": "RC-FORBIDDEN",
  "detail": "Your REDCap rights do not include this record's data access group.",
  "instance": "/rc/v1/projects/42/case",
  "trace_id": "01JC3V9N9W8Y0B4Z1R4G1D7K2Q"
}
```

`detail` is safe to show to the user, in the user's language, and never contains PHI.

### 2.3 Error code register

| Code | HTTP | Meaning | Caller action |
| --- | --- | --- | --- |
| AUTH-MISSING | 401 | No or expired credential | Re-authenticate |
| AUTH-2FA | 401 | Second factor required | Prompt TOTP |
| AUTH-FORBIDDEN | 403 | Role or study scope does not allow | Show message, no retry |
| RC-FORBIDDEN | 403 | REDCap rights or DAG do not allow | Show message |
| RC-VERSION | 409 | REDCap version unsupported | Admin warning; panel disabled |
| RC-TOKEN | 409 | Project read token invalid or missing | Admin re-links project |
| RC-UPSTREAM | 502 | REDCap returned an error | Retry with back-off (max 3) |
| RC-RATE | 503 | Rate limit reached | Retry after `Retry-After` |
| JOB-NOT-FOUND | 404 | Unknown job id | — |
| JOB-BUSY | 202 | Work queued; poll | Poll `/jobs/{id}` |
| MODEL-UNAVAILABLE | 503 | Interactive model not loaded (night window) | Show expected wait |
| VALIDATION | 422 | Payload failed schema | Fix request |
| FED-SIGNATURE | 400 | Envelope signature invalid | Drop; alert admin |
| FED-REPLAY | 409 | `msg_id` already seen or expired | Drop |
| FED-CLASS | 400 | `data_class` above D2 | Drop; alert admin |
| UPD-SIGNATURE | — | Bundle signature invalid (CLI) | Refuse update |
| MAP-UNKNOWN | — | Mapping version or table unknown (CLI/ingest report) | Fix mapping |
| RC-LINK-FIELD | 409 | A field named in the study's project link is missing from the REDCap data dictionary (§4.1a); the link is disabled for that study | Admin corrects the link on S21 |
| RC-LINK-DUP | 409 | Two REDCap records carry the same link value for one study (§4.1a join rule) | Coordinator resolves on S17; never resolved automatically |
| UP-META | 422 | Upload metadata missing or invalid (§12, FR-ING-21) | Fill the metadata form and upload again |
| UP-LAYOUT | 202 | Upload layout unknown; file held for mapping (§12) | Mapping written once per layout, then import runs |
| UP-IDMATCH | 422 | Some identifier rows matched no pid; count shown, those rows not imported (§12) | Check the identifier column; re-upload the corrected rows |
| UP-SIZE | 413 | Upload larger than 50 MB (§12) | Split the file |
| NOTIFY-UNDELIVERED | — | The mail server refused a notice (§11); recorded in `notify_log` | Admin checks the sender rule (IC-07) |

### 2.4 Authentication summary

| Interface | Authentication | Transport |
| --- | --- | --- |
| ICD-01/02/03 | File system permissions on the drop folder or read-only DB account | Local mount / SFTP / ODBC inside the hospital network |
| ICD-04 | REDCap project-level **read** token (BD-05), stored in `tb-secrets` | HTTPS, hospital CA verified |
| ICD-05 | The user's own REDCap session in the External Module (no token stored by TrialBox) | HTTPS (inside REDCap) |
| ICD-06 | Source IP allowlist + per-project secret in the DET URL | HTTPS |
| ICD-07 | Module client credential + short-lived user assertion JWT (EdDSA), §5 | HTTPS, mTLS optional |
| ICD-08 | Sender allowlist + DKIM/SPF pass on the hospital mail server; replies only to internal domains for D3 content | SMTP/IMAP over TLS |
| ICD-09 | Console session (password; TOTP added at the hospital stage, BD-17) | HTTPS |
| ICD-10 | Ed25519 signature per envelope + mTLS (consortium CA) or S/MIME mail | HTTPS mTLS or mail |
| ICD-11 | Ed25519 vendor signature over the manifest | Offline media |
| ICD-12 | sha256 checksum; no signature needed (no PHI by construction) | Offline media / e-mail |

## 3. Source readers

### 3.1 ICD-01 CSV / SQL with site mapping YAML [S0 built]

**Parties:** hospital HIS export or data warehouse view → `adapter`. **Direction:** pull, nightly (BD-11: 22:00–23:30) and on admin demand. **Delta:** each table may declare a `delta` column; `adapter run --since` reads rows changed since the last successful snapshot.

**Mapping file schema (summary of the built format, `services/adapter/mapping/tw_core/demo_his.yaml`):**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://trialbox.local/schemas/site_mapping.schema.json",
  "title": "SiteMapping",
  "description": "Per-site mapping from HIS tables to FHIR R4. Schema version 1.0.0.",
  "type": "object",
  "required": ["version", "name", "tz", "systems", "tables"],
  "properties": {
    "version": {"const": 1},
    "name": {"type": "string", "pattern": "^[a-z0-9_]{1,32}$"},
    "extends": {"type": "string", "description": "Base mapping, e.g. tw_core/demo_his"},
    "tz": {"enum": ["Asia/Taipei", "Asia/Tokyo"]},
    "systems": {"type": "object", "additionalProperties": {"type": "string", "format": "uri"}},
    "tables": {
      "type": "object",
      "propertyNames": {"enum": ["patient", "practitioner", "encounter", "appointment", "diagnosis", "lab", "vital",
                                  "medication", "injection", "procedure", "report", "note", "claim", "registry"]},
      "additionalProperties": {
        "type": "object",
        "required": ["source", "key"],
        "properties": {
          "source": {"type": "string"},
          "key": {"type": "string"},
          "delta": {"type": "string"},
          "identity": {"type": "object", "description": "Columns that go only to the pid map (D4)",
                       "additionalProperties": {"type": "string"}},
          "rename": {"type": "object", "additionalProperties": {"type": "string"}},
          "values": {"type": "object", "description": "Value maps per column",
                     "additionalProperties": {"type": "object", "additionalProperties": {"type": "string"}}}
        }
      }
    },
    "lookups": {"type": "object", "additionalProperties": {
      "type": "object", "required": ["file", "key"],
      "properties": {"file": {"type": "string"}, "key": {"type": "string"}}}},
    "static": {"type": "array", "items": {"type": "object", "required": ["resourceType"]}}
  }
}
```

**Rules:** the `identity` columns (name, national ID) are written only to the pid map (D4). The `key` column of `patient` is the chart number; it is replaced by `pid = HMAC-SHA256(site_key, normalised MRN)` before anything is written to the snapshot (FR-DEID-01). Unknown columns are ignored and listed in the ingest report.

**CGMH profile [H]:** `mapping/tw_core/cgmh.yaml` extending `demo_his`, built with CGMH IT from their data-warehouse views. A second profile `mapping/tw_core/cgmh_cgrd.yaml` reads CGRD extracts into the D2 zone (feasibility only, FR-FEAS-10).

**Errors:** reported in the ingest report (`ingest_report.schema.json`, built): `MAP-UNKNOWN`, missing table, type errors (row dropped with reason), validation rate > 0.5 % fails the ingest (FR-ING-10).

**Conformance tests:** golden-file tests per mapping (synthetic export → expected NDJSON); 1 % profile validation sample on every real snapshot.

### 3.2 ICD-02 SS-MIX2 standardised storage [H]

**Parties:** SS-MIX2 storage on the EMR side (SSI and Fujitsu HOPE sites, read-only share) → `adapter` reader `ssmix2`.

**Directory layout read** (SS-MIX2 標準化ストレージ仕様): `<root>/<pid[0:3]>/<pid[3:6]>/<pid>/<YYYYMMDD>/<data-type>/<file>` where the file name carries patient ID, date, data type, order number, timestamp, department code and condition flag (`1` = valid, `0` = deleted/cancelled). The reader treats the newest file per order number as current and condition flag `0` as a deletion (FR-ING-11). Extended storage (拡張ストレージ) is read for documents when the site enables it. **The exact layout and data-type codes must be confirmed against the head hospital's storage before coding (open item IC-01).**

| SS-MIX2 data type | HL7 v2.5 message | FHIR R4 target (JP Core) | Notes |
| --- | --- | --- | --- |
| ADT-00 患者基本情報 | ADT^A08 | Patient (identity → pid map) | PID-5 kanji and kana names, PID-7 birth date, PID-8 sex, PID-11 address → pid map only |
| ADT-21/22 入院・退院, ADT-12 外来受診 | ADT^A01/A03/A04 | Encounter | |
| PPR-01 病名 | PPR^ZD1 | Condition | PRB-3 標準病名 code + ICD-10; 修飾語 → verification `provisional` for 「疑い」; 主病名 flag; 保険病名 heuristics (TB-DS-10) |
| OMP-01 処方オーダ | RDE^O11 | MedicationRequest | RXE-2 YJ / HOT code |
| OMP-02 注射オーダ | RDE^O11 | MedicationRequest / MedicationAdministration | |
| OML-01 検体検査オーダ / OUL-01 検体検査結果 | OML^O33 / OUL^R22 | Observation (laboratory) | OBX-3 JLAC10 (17 digits) → LOINC via lookup; units UCUM |
| OMG-xx 放射線・生理検査 | OMG^O19 | ServiceRequest → DiagnosticReport (reports from extended storage) | |
| Extended storage documents (経過記録, 退院サマリ, 診療情報提供書) | PDF / text / CDA | DocumentReference | OCR when no text layer (FR-ING-13) |

**Appointments are not in SS-MIX2 standardised storage**, which has no appointment data type (JAMI SS-MIX2 Ver.1.2h; TB-DS-02 §8.13.1). The next clinic visit is read from the vendor's 予約 export through ICD-01 (`appointment` table in the site mapping) or from extended storage where the vendor puts it there (SRS FR-ING-03b). Where neither exists, lists show "next visit: unknown" and sort by last encounter (IC-01).

**Parser:** python-hl7 for segment parsing, our own reader for the tree and file names (TB-DS-05 pick). Character set: ISO-2022-JP and Shift_JIS handled explicitly per MSH-18; NFKC applied after decoding (TB-DS-10 §8.2).

**Conformance tests:** a synthetic SS-MIX2 tree with every data type above, including cancelled orders and multi-version files; golden NDJSON output; JP Core validation sample.

### 3.3 ICD-03 FHIR bulk NDJSON [S0 built]

**Parties and direction:** a hospital FHIR server or an export job → TrialBox ingest (one way). **Requirements:** FR-ING-06 (TB-DS-01).

**Transport and authentication:** files in the site drop folder (local mount or SFTP inside the hospital network), as ICD-01; no network call from TrialBox to the FHIR server in the build.

**Format:** one NDJSON file per resource type (`Patient.ndjson`, `Condition.ndjson`, `Observation.ndjson`, `MedicationRequest.ndjson`, `Encounter.ndjson`, `Appointment.ndjson`, `DocumentReference.ndjson`) as produced by FHIR Bulk Data `$export` (FHIR Bulk Data Access IG 2.0.0), FHIR R4 4.0.1, UTF-8, one resource per line. A `manifest.json` in the same folder follows the `$export` completion output (`transactionTime`, `output[{type, url, count}]`) plus `sha256` per file (FR-ING-17).

**Processing:** identity mapping (`Patient.identifier` with the site's MRN system → pid), then the same pseudonymisation as ICD-01; profile validation per configured profile (JP Core 1.2.0, TW Core, IPA); resources failing validation go to the ingest report, not the lake.

**Errors:** `VALIDATION` per resource in the ingest report; `MAP-UNKNOWN` when the MRN identifier system is not configured; a manifest mismatch refuses the extract (FR-ING-17).

**Conformance tests:** TS-ING runs the built Synthea-derived NDJSON fixture through ingest; expected: resource counts equal the manifest, every pid differs from every MRN, invalid resources listed in the report.

## 4. REDCap API

### 4.1 ICD-04 Read set [S3]

**Endpoint:** `POST https://<redcap-host>/api/`, `Content-Type: application/x-www-form-urlencoded`, fields `token`, `content`, `format=json`, `returnFormat=json`. Token: the project-level read token (BD-05). TLS verified against the hospital CA. Rate cap 5 requests/s per project; back-off on 429/503.

| # | Purpose | `content` (`action`) | Parameters | Used for |
| --- | --- | --- | --- | --- |
| R1 | Version | `version` | — | connect, health (RC-VERSION) |
| R2 | Project info | `project` | — | connect; `is_longitudinal`, `project_language` |
| R3 | Data dictionary | `metadata` | `forms[]` optional | schema compiler; cached by `last_logged_event` |
| R4 | Instruments | `instrument` | — | form list |
| R5 | Events, arms, form-event map | `event`, `arm`, `formEventMapping` | — | longitudinal projects, visit windows |
| R6 | Repeating forms/events | `repeatingFormsEvents` | — | visits, AEs |
| R7 | Records | `record` (`export`) | `type=flat`, `records[]`, `fields[]`, `events[]`, `rawOrLabel=raw`, `exportDataAccessGroups=true`, `dateRangeBegin` (records changed since the last read) | registry source (FR-ING-07b); nightly read of the project-link fields (§4.1a) for consent, enrolment, screen-fail and withdrawal status |
| R8 | DAGs | `dag` | — | site mapping |
| R9 | Users / rights | `user`, `userDagMapping` | — | admin check of who can see what (read-only) |
| R10 | Logging | `log` | `record`, `beginTime`, `endTime` | link audit to REDCap log (optional) |

**Not used:** `delete`, `projectXml`, `rename`, participant contact exports, `file` import. TrialBox never contacts patients.

**Response handling:**

| REDCap response | TrialBox behaviour |
| --- | --- |
| 200 JSON | Validate against the expected shape (e.g. metadata rows have `field_name`, `form_name`, `field_type`, `select_choices_or_calculations`, `text_validation_type_or_show_slider_number`, `branching_logic`, `field_annotation`) |
| 400 with `{"error": …}` | `RC-UPSTREAM`; message logged without the token |
| 403 | `RC-TOKEN` (admin re-links) |
| 429 / 503 | `RC-RATE`; retry with back-off |

**Data dictionary → extraction schema (input to FR-EDC-01, L):**

| REDCap `field_type` / validation | JSON Schema |
| --- | --- |
| `text`, no validation | `{"type": "string", "maxLength": 2000}` |
| `text`, `integer` | `{"type": "integer", "minimum": min, "maximum": max}` |
| `text`, `number` / `number_1dp` … | `{"type": "number"}` with `multipleOf` |
| `text`, `date_ymd` | `{"type": "string", "format": "date"}` |
| `text`, `datetime_ymd` | `{"type": "string", "format": "date-time"}` |
| `radio`, `dropdown` | `{"enum": [codes]}` from `select_choices_or_calculations` |
| `checkbox` | `{"type": "array", "items": {"enum": [codes]}, "uniqueItems": true}` |
| `yesno`, `truefalse` | `{"enum": ["0", "1"]}` |
| `calc`, `descriptive`, `file`, `signature` | not proposed |
| `@TB-SOURCE=<kind>:<system>:<code>` in `field_annotation` | rule-filled (FR-EDC-02) |
| `@TB-SKIP` | never proposed |

Each proposed property is wrapped: `{"value": <schema>, "quote": string, "source_did": string, "source_date": date, "confidence": "rule" | "model"}`.

### 4.1a Project link and field map per study [S3; `mrn` mode H] (TB-REV-006c C-06, C-17)

Every REDCap project names its fields differently. The connector reads status fields only through a **project link** kept per study in the study settings store (TB-DS-07) and edited on S21 Study set-up (TB-DS-09) by the `coordinator`, confirmed by the `investigator`. It is read-only (BD-05).

**Project link schema** (`schemas/rc_v1/project_link.json`; mirrors the `rc_project_link` store of TB-DS-07 and FR-RC-16):

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `ruleset` | string | yes | TrialBox study / ruleset id |
| `project_id` | integer | yes | REDCap project id (from R2) |
| `token_ref` | string | yes | Name of the project-level read token in the appliance secret store; never the token itself (rc-bridge settings) |
| `dag` | string | no | DAG unique name to read (multi-site project); records outside it are ignored |
| `link_mode` | enum `tb_screening_no` (default) / `mrn` | yes | How a REDCap record is joined to a TrialBox pid (below; TB-DS-00 BD-18) |
| `link_field` | string | yes | `tb_screening_no` for the default mode; the chart-number field for `mrn` |
| `consent_field`, `consent_event` | string | yes for trials and opt-in studies | Date ICF signed, and its event in a longitudinal project |
| `enrol_field` | string (+ value) | yes | Field and raw code meaning enrolled / randomised |
| `screenfail_field`, `screenfail_choice_map` | string, {code → TrialBox reason category} | no | Screen-fail flag or reason field, mapped to the reason categories of TB-DS-07 |
| `withdraw_field` | string (+ value) | no | Withdrawal / discontinuation |
| `subject_no_field` | string | no | Sponsor-issued subject number (IWRS / sponsor EDC), read and shown on the screening log where the project holds it |
| `last_read` | datetime | system | Watermark for `dateRangeBegin` |

**Link modes** (chosen per study on S21, TB-DS-00 BD-18):

| Mode | How the join is made | Clinical entry needed | When to use |
| --- | --- | --- | --- |
| `tb_screening_no` (default) | TrialBox issues the per-study `screening_no` when a candidate first gets a PI mark of Approach (FR-STUDY-08) and shows it on the row. The study's REDCap administrator adds one text field `tb_screening_no` to the project; the CRC writes the number there when creating the REDCap record, as they write a screening number in their log today. The connector reads the field and joins `record_id` ↔ `screening_no` ↔ pid. | None beyond what the CRC writes today | Default for every study, including sponsor projects without identifiers |
| `mrn` | The project already holds the chart number in an identifier-flagged field and the site agrees. The connector reads it **inside the identified zone**, maps it to the pid through the pid map, stores only `(pid, record_id)` and discards the MRN. | None | Per-study alternative for identified hospital registries; the ethics approval must cover the link |

Nobody pastes a record ID or a pid into TrialBox, and TrialBox writes nothing to REDCap in the build or at the hospital stage (BD-05).

**Join rule:** one REDCap record joins to at most one pid per study; a second record with the same link value raises `RC-LINK-DUP` and is shown to the coordinator, never resolved automatically. A record whose link value matches no pid is listed as "in REDCap, not in TrialBox" on the monitoring view (FR-REP-06) and is not an error.

**Status mapping:** values read through the link update the registry status (TB-DS-07 outcome → status table): consent date present → `consented`; enrolled code → `enrolled`; screen-fail flag → `screen-failed` with the mapped reason; withdrawn code → `withdrawn`. REDCap wins over a TrialBox outcome for these four statuses; a conflict (TrialBox says "declined", REDCap has a consent date) is listed for the coordinator.

**Screening-log export (FR-RC-15):** the CSV is keyed on `screening_no` where present, and carries `record_id` where linked; columns follow TB-TMPL-03 (TB-TMPL-07 §6).

**Errors:** `RC-LINK-FIELD` (a mapped field is missing from the data dictionary: the link is disabled for that study and the admin home shows it); `RC-LINK-DUP`; `RC-TOKEN`; `RC-RATE`.

**Conformance tests:** on the REDCap API simulator, two projects with differently named fields (`consent_date`/`enrolled` in project A; `icf_dt`/`rand_yn` in a longitudinal project B with events and a DAG) are linked, one per mode `tb_screening_no` and `mrn`; expected: statuses mapped correctly, duplicate link value raises `RC-LINK-DUP`, a renamed field raises `RC-LINK-FIELD`, and no MRN is stored outside the identified zone (scan).

### 4.2 ICD-05 Write set via the External Module [L]

Writes happen **inside REDCap**, in the External Module's PHP, under the user's REDCap session (`\REDCap::saveData` with the user's rights). TrialBox never holds a personal REDCap token (BD-05). The module asks the appliance for the accepted value and the proposal id, saves it, and reports the result back (`/rc/v1/prefill/{id}/saved`).

| Rule | Detail |
| --- | --- |
| Form status | Saved forms stay `1` = Unverified (REDCap codes: 0 Incomplete, 1 Unverified, 2 Complete). TrialBox never sets 2. |
| Overwrite | `overwriteBehavior=normal`: empty proposals never blank an existing value. |
| Audit | REDCap logs the user; TrialBox audits `prefill.accept` with proposal id, user, model and prompt version. |
| Failure | Module shows the REDCap error on the card; no automatic retry. |

### 4.3 ICD-06 Data Entry Trigger [H]

REDCap sends `POST` (form-encoded) to the configured URL `https://<appliance>/rc/det?k=<per-project secret>` on record save:

| Field | Example |
| --- | --- |
| project_id | 42 |
| instrument | screening |
| record | 1007 |
| redcap_event_name | screening_arm_1 |
| redcap_data_access_group | site_jp |
| `<instrument>_complete` | 1 |
| redcap_url, project_url | … |
| username | crc_tanaka |

**Handling:** verify source IP ∈ REDCap allowlist and `k` matches; de-duplicate on `(project_id, record, instrument, event, 60 s bucket)`; respond `200` within 2 s; queue the configured job: H: log + optional `CASE` for the mapped ruleset; L: `PREFILL` for the next visit. Errors are logged, never returned to REDCap.

**Conformance tests:** simulator sends DET calls with valid, wrong secret, wrong IP, duplicate and unknown project; expected: 200/403/403/200 (ignored)/404 logged.

### 4.4 ICD-04S REDCap API simulator [S3] (TB-REV-006f F6-15)

A small HTTP service (`services/rc_sim`, Python, about 300 lines) that answers the REDCap API the way REDCap does, from JSON fixture projects, so build step 3 and `e2e_simple` run without a real REDCap. It is written from the public REDCap API documentation only (no REDCap source, licence note in TB-DS-05). It ships in the **demo and test images** and never in a hospital product image (ADR-05). TrialBox calls it with PyCap exactly as it would call a real REDCap.

| Item | Behaviour |
| --- | --- |
| Endpoint | `POST /api/` with form fields `token`, `content`, `format=json`, as REDCap |
| Methods answered | R1 `version`, R2 `project`, R3 `metadata`, R7 `record` export (incl. `fields[]`, `events[]`, `dateRangeBegin`, `exportDataAccessGroups`), R8 `dag`. Any other `content` returns HTTP 501 with a REDCap-style error body |
| Token check | Each fixture project has its own 32-hex token; a wrong token returns 403 `{"error": "You do not have permissions to use the API"}` |
| Fixture projects | Loaded at start from `fixtures/rc_sim/*.json`. Two are shipped, matching the §4.1a conformance test: **A** classic project with `tb_screening_no`, `consent_date`, `enrolled`, `sf_reason` (choice list); **B** longitudinal project with events, a DAG and `icf_dt`, `rand_yn`, `withdrawn` |
| Changing data in a demo | `POST /sim/records` (simulator only, not part of the REDCap API) adds or edits a record and stamps its change time, so a demo can show a status change being read the next night or on Run now |
| Version string | Reports a configurable REDCap version (default the current LTS line, `16.x`, TB-DS-05 §10), so RC-VERSION checks can be tested |
| Rate limit | Optional, to test `RC-RATE` |
| Tests | ICD-04 §4.1a conformance tests run against it in CI; `e2e_simple` stage "REDCap read-back" uses project A |

## 5. ICD-07 REDCap External Module ↔ appliance `/rc/v1` [L]

**Transport:** HTTPS from the REDCap web server to `rc-bridge` (port 8096 behind the gateway 8020). **Auth:** OAuth2 client credentials per REDCap server (registered at install, rotatable, FR-AUTH-07), plus a user assertion per call.

**User assertion JWT** (header `X-TB-User-Assertion`):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://trialbox.local/schemas/rc_v1/user_assertion.schema.json",
  "title": "RcUserAssertion",
  "description": "Claims of the EdDSA-signed JWT the module sends per call. Schema version 1.0.0.",
  "type": "object",
  "required": ["iss", "sub", "aud", "pid", "dag", "rights_sha", "iat", "exp", "jti"],
  "properties": {
    "iss": {"type": "string", "description": "REDCap server id registered at install"},
    "sub": {"type": "string", "description": "REDCap username"},
    "aud": {"const": "trialbox-rc-v1"},
    "pid": {"type": "integer", "description": "REDCap project id"},
    "dag": {"type": ["string", "null"]},
    "rights_sha": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    "iat": {"type": "integer"},
    "exp": {"type": "integer", "description": "at most iat + 300"},
    "jti": {"type": "string"}
  },
  "additionalProperties": false
}
```

The appliance maps `sub` to a linked TrialBox account (S-23 `rc_user_map`) and intersects the TrialBox role and study scope with the REDCap rights; the narrower wins.

**Endpoints:**

| Method | Path | Request | Response | Errors |
| --- | --- | --- | --- | --- |
| GET | `/rc/v1/health` | — | `{version, redcap_compat, modules}` | — |
| GET | `/rc/v1/projects/{pid}/candidates?ruleset=&week=` | — | `CandidateRows` | AUTH-FORBIDDEN, RC-FORBIDDEN |
| POST | `/rc/v1/projects/{pid}/case` | `{record, ruleset, lang}` | `202 {job_id}` | MODEL-UNAVAILABLE |
| GET | `/rc/v1/jobs/{job_id}` | — | `{state, cards[]}` | JOB-NOT-FOUND |
| GET | `/rc/v1/projects/{pid}/prefill?record=&instrument=&event=&instance=` | — | `{status: "ready" or "computing", cards[]}` | |
| POST | `/rc/v1/prefill/{proposal_id}/accept` | `{value?}` | `{value_to_save, proposal_id}` | VALIDATION |
| POST | `/rc/v1/prefill/{proposal_id}/saved` | `{redcap_ok: bool, error?}` | `{ok: true}` | |
| POST | `/rc/v1/prefill/{proposal_id}/reject` | `{reason}` | `{ok: true}` | |
| GET | `/rc/v1/projects/{pid}/visits?from=&to=` | — | visit windows | |
| GET | `/rc/v1/projects/{pid}/ae-suggestions?record=` | — | AE cards | |
| POST | `/rc/v1/cards/{card_id}/dismiss` | `{reason}` | `{ok: true}` | AUTH-FORBIDDEN unless investigator for AE cards (BD-08) |

**Card schema** (shared with the console, TB-DS-09 §4):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://trialbox.local/schemas/rc_v1/card.schema.json",
  "title": "Card",
  "description": "One model or rule output shown to a person. Schema version 1.0.0.",
  "type": "object",
  "required": ["card_id", "kind", "state", "title", "primary_action", "evidence", "provenance"],
  "properties": {
    "card_id": {"type": "string"},
    "kind": {"enum": ["criterion", "prefill", "ae_suggestion", "conmed", "visit", "missing_data", "intent"]},
    "state": {"enum": ["needs_check", "meets", "does_not_meet", "unknown", "human", "accepted", "edited",
                       "rejected", "dismissed", "error"]},
    "title": {"type": "string", "maxLength": 120},
    "field": {"type": ["string", "null"], "description": "REDCap field_name for prefill"},
    "value": {"type": ["string", "number", "array", "null"]},
    "evidence": {"type": "array", "items": {
      "type": "object", "required": ["quote", "source_kind", "date"],
      "properties": {
        "quote": {"type": "string", "maxLength": 600},
        "source_kind": {"enum": ["note", "lab", "prescription", "diagnosis", "report", "letter", "registry"]},
        "date": {"type": "string", "format": "date"},
        "did": {"type": ["string", "null"]}}}},
    "checks": {"type": "array", "items": {"type": "string"}, "description": "validator results in the user's language"},
    "conflicts": {"type": "array", "items": {"type": "object"}},
    "primary_action": {"enum": ["accept", "send_to_pi", "open_note", "confirm_task", "start_command"]},
    "secondary_actions": {"type": "array", "items": {"enum": ["edit", "reject", "open_note", "dismiss"]}},
    "provenance": {"type": "object", "required": ["source"],
      "properties": {"source": {"enum": ["rule", "model"]}, "model": {"type": "string"},
                     "prompt_version": {"type": "string"}, "ruleset_version": {"type": "string"}}}
  },
  "additionalProperties": false
}
```

**Conformance tests:** contract tests against the JSON Schemas on both sides (PHP module test harness and pytest), plus the e2e test with the simulator.

## 6. ICD-08 Mail command channel [S0 built; extensions S1 / L]

**Transport:** the appliance is an IMAP/SMTP client of the hospital mail server (TB-DS-05 pick). Intake mailbox polled every 60 s.

**Subject grammar (built, `libs/tb_common/subject.py`, ABNF):**

```
subject = cmd SP ruleset *(SP option) [SP "--" SP comment]
cmd     = "FEAS" / "SCREEN" / "COHORT" / "NAV" / "APPROVE" / "STATUS" / "CANCEL" / "SUBMIT" / "FEEDBACK"
        / "CONSENT" / "RELEASE" / "CASE"
ruleset = 1*16(ALPHA / DIGIT / "-" / "_")        ; STATUS / CANCEL / RELEASE take a job id (ULID) instead; RELEASE is for sponsor packs only, consent explainers have no release step (BD-15)
option  = key "=" value
key     = "window" / "pract" / "dept" / "lookback" / "version" / "variant" / "since" / "pid" / "bundle" / "site"
        / "lang" / "drop" / "keep" / "mrn"
value   = 1*32(ALPHA / DIGIT / "-" / "," / "." / ":")
```

Reply/forward prefixes (`Re:`, `RE:`, `Fwd:`, `AW:`, `回覆:`, `回复:`, `轉寄:`, `转发:`, with ASCII or full-width colon) are stripped; full-width spaces are normalised (built).

**Extensions:**

| Release | Addition |
| --- | --- |
| S1 (was M1) | `cmd =/ "DRAFT"` — feasibility from pasted criteria without a ruleset ID (body text or attachment); the reply contains the generated draft ID used by `FEAS`. |
| S0 (was M1) | `RELEASE` for consent explainers is **removed** (TB-DS-00 BD-15: an explainer goes live automatically when its approval record holds the committee-approved file). `RELEASE` remains only for sponsor-report packs. A `RELEASE` naming a consent job gets the error reply "Consent explainers are released by their ethics approval record; see the study set-up page." |
| L (was M2) | `cmd =/ "PREFILL" / "VISITS" / "FEDFEAS"`; `key =/ "record" / "instrument" / "event" / "project"` |

**Reply subject (built, D-88/D-99):** `[STUDY] CMD kind: headline · job ID`, in the requester's language.

**Content rules (BD-04):** patient lists by mail carry pseudonyms only; chart numbers never appear in mail; aggregate reports apply k = 10 for recipients outside the site (N-01). Attachments with D3 content go only to internal domains and are encrypted (FR-MAIL-03).

**Errors:** a rejected subject gets a reply listing the accepted commands with one example each (built behaviour, localised).

**Conformance tests:** parser unit tests (built, extended for new commands), GreenMail/Mailpit end-to-end tests.

## 7. ICD-09 Chat command box [S4]

One parser serves mail and chat (FR-CHAT-02). Input is free text in ja / zh-TW / en; the output is a normalised command or a list of suggestions. No free-text clinical answers in this version.

**Request** `POST /console/api/chat` (session cookie + CSRF):

```json
{"text": "GZQOに今週合う患者は？", "lang": "ja"}
```

**Response schema:**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://trialbox.local/schemas/chat_result.schema.json",
  "title": "ChatResult",
  "description": "Result of the fixed-command chat parser. Schema version 1.0.0.",
  "type": "object",
  "required": ["outcome"],
  "properties": {
    "outcome": {"enum": ["started", "confirm", "suggest", "forbidden"]},
    "command": {"type": "string", "description": "Normalised subject, e.g. 'SCREEN GZQO'"},
    "job_id": {"type": ["string", "null"]},
    "open_url": {"type": ["string", "null"], "description": "The normal page of the result"},
    "suggestions": {"type": "array", "maxItems": 3, "items": {"type": "object",
      "required": ["command", "label"], "properties": {"command": {"type": "string"}, "label": {"type": "string"}}}},
    "message": {"type": "string"}
  },
  "additionalProperties": false
}
```

| Example input (any language) | Command | Outcome |
| --- | --- | --- |
| "Feasibility for these criteria: …" / 「この基準で実施可能性を」 / 「用這些條件做可行性評估」 | `DRAFT` + text, then `FEAS <draft>` | `confirm` (user confirms before the job starts) |
| "Who fits GZQO this week?" | `SCREEN GZQO` (latest list) | `started` / open list |
| "Check chart 12345 for GZQO" | `CASE GZQO mrn=12345` | `confirm` |
| "Status of job 01J…" | `STATUS <ULID>` | `started` |
| anything else | — | `suggest` with tiles |

Deterministic rules run first; if no rule matches, the `classify_intent` task of the native converse engine (stub in CI; production prompt and gate [target, L]) may propose a command, always returned as `confirm`, never `started`. `forbidden` is returned when the role or study scope does not allow the command (FR-CHAT-06).

## 8. ICD-10 Consortium envelope [L]

**Transport:** HTTPS with mTLS (certificates from the per-country consortium CA, BD-06) to the hub's `fed-agent`, or S/MIME mail with the envelope as an attachment where no link exists. Nightly batches (FR-FED-08).

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://trialbox.local/schemas/fed/envelope.schema.json",
  "title": "FedEnvelope",
  "description": "Signed consortium message. Schema version 1.0.0.",
  "type": "object",
  "required": ["envelope_version", "type", "msg_id", "from_site", "to_site", "created_at", "expires_at",
               "data_class", "payload_sha256", "payload", "signature"],
  "properties": {
    "envelope_version": {"const": "1"},
    "type": {"enum": ["ruleset.offer", "ruleset.approved", "funnel.result", "funnel.declined", "guid.clk",
                      "chain.head", "chain.countersign"]},
    "msg_id": {"type": "string", "pattern": "^[0-9A-HJKMNP-TV-Z]{26}$"},
    "in_reply_to": {"type": ["string", "null"]},
    "from_site": {"type": "string", "pattern": "^[a-z0-9-]{2,32}$"},
    "to_site": {"type": "string", "pattern": "^[a-z0-9-]{2,32}$"},
    "created_at": {"type": "string", "format": "date-time"},
    "expires_at": {"type": "string", "format": "date-time"},
    "data_class": {"enum": ["D0", "D1", "D2"]},
    "payload_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    "payload": {"type": "object"},
    "signature": {"type": "object", "required": ["alg", "key_id", "sig"],
      "properties": {"alg": {"const": "Ed25519"}, "key_id": {"type": "string"},
                     "sig": {"type": "string", "description": "base64 over RFC 8785 JCS of all fields except signature"}}}
  },
  "additionalProperties": false
}
```

**Payload `funnel.result`:**

```json
{
  "$id": "https://trialbox.local/schemas/fed/funnel_result.schema.json",
  "type": "object",
  "required": ["query_id", "ruleset", "ruleset_version", "snapshot_date", "steps", "pi_approval"],
  "properties": {
    "query_id": {"type": "string"},
    "ruleset": {"type": "string"},
    "ruleset_version": {"type": "string"},
    "snapshot_date": {"type": "string", "format": "date"},
    "steps": {"type": "array", "items": {"type": "object", "required": ["step", "label", "n", "suppressed"],
      "properties": {"step": {"type": "integer"}, "label": {"type": "string"},
                     "n": {"type": ["integer", "null"]}, "suppressed": {"type": "boolean"}}}},
    "pi_approval": {"type": "object", "required": ["by", "at"],
      "properties": {"by": {"type": "string"}, "at": {"type": "string", "format": "date-time"}}}
  }
}
```

Rules: `n` is `null` and `suppressed` true for cells < 10 (N-01), with complementary suppression (built in `services/deliverables`). `guid.clk` payloads carry base64 CLK strings and an opaque per-query candidate reference only; they are never combined with clinical data (FR-DEID-14) and never cross a country border (BD-06). Replay protection: `msg_id` store and `expires_at` (`FED-REPLAY`).

## 9. ICD-11 Update bundle [S0 built; additions H]

Uncompressed tar: `manifest.json` (built schema `schemas/update_manifest.schema.json`: `bundle_id`, `created_at`, `signer`, `description`, `files[{path, sha256, kind}]`), `manifest.json.sig` (Ed25519, vendor key), `files/<path>`.

**Hospital-stage additions** (schema minor version 1.1.0, optional fields):

| Field | Type | Purpose |
| --- | --- | --- |
| `version` | string, SemVer | release version |
| `release_notes` | path to `release_notes.md` | validation record (TB-DS-04 §9) |
| `sbom` | path to `sbom.spdx.json` | SBOM (SPDX 2.3) |
| `rollback_tag` | string | version to return to |
| `gates` | object | gate-set results (SIGIR, TREC, MedTxt, PHI, pre-fill) with pass/fail |
| `min_from_version` | string | oldest version this bundle can upgrade |

The appliance refuses an unsigned or tampered bundle (`UPD-SIGNATURE`) and an upgrade from a version older than `min_from_version`.

## 10. ICD-12 Diagnostics bundle [H]

**Parties and direction:** site admin → Aimedics support (one way, offline). **Requirements:** FR-SEC-05, FR-OPS-04 (TB-DS-01); SC-43 (TB-DS-03).

**Transport and authentication:** exported by an `admin` from the health page as one tar file; carried on offline media or attached to an e-mail by the hospital; sha256 checksum only, no signature (no PHI by construction).

**Content:** Exported by an admin from the health page. Tar with: container versions, health checks, ingest reports (counts only), job states (no `data` column), audit chain verification result, disk/GPU metrics, sanitised logs. A built-in check runs `phi_guard` over every file and refuses to export if any chart-number, phone or national-ID pattern is found. sha256 checksum file included.

**Schema:** `manifest.json` (`schemas/diag_manifest.schema.json`): `{bundle_id (ULID), created_at, site_id, software_version, files[{path, sha256, kind: versions | health | ingest_counts | job_states | chain_verify | metrics | logs}], phi_scan: {passed: boolean, scanner_version}}`.

**Errors:** the export is refused when the PHI scan finds any match (`VALIDATION`, detail lists the file, never the matched text).

**Conformance tests:** TS-SEC builds a bundle from the e2e fixture with planted identifiers in a log line; expected: the scan refuses it; after removing the line the bundle is built and contains no D3/D4 field.

## 11. ICD-13 Outbound notices [S2: N1, N2; H: N3, N4, N6; L: N5] (TB-REV-006c C-02, C-13, C-14, C-20)

**Parties:** notification service (TB-DS-02 §5, building block `notify`) → hospital mail server (SMTP, as ICD-08) → staff. Later (L), Web Push (FR-NOTIF-06) is added with no patient data. **Content rule:** pseudonyms and counts only (BD-04); no chart numbers, **no screening numbers** (D4, BD-18), names, model names or scores (FR-UI-03/05).

| Notice | Recipient | When | Subject (FR-MAIL-02 grammar, in the recipient's language) | Body blocks, in order |
| --- | --- | --- | --- | --- |
| N1 PI clinic-day list | each `investigator` | 07:00 on each of the PI's clinic days where the appointment source exists (S19 default); Monday 07:00 after the weekend window otherwise (BD-11) | `[TrialBox] Clinic Tue 12 Jan: 3 candidates · 2 studies` | (1) **Your clinic today**: rows where the appointment practitioner is the recipient — pseudonym, time, clinic, study badges, "met / to check" counts; (2) **Other study doctors** (folded); (3) **Other doctors** with the mark "Ask treating doctor"; (4) this week folded; (5) link to S16 and to the full study list S5 sorted by next visit; (6) why-you-got-this line and settings link (FR-NOTIF-09) |
| N2 CRC digest | each `coordinator` | Working days at the person's time (default 07:30) | `[TrialBox] Today: 4 visits · 2 new · 3 PI marks` | Today's visits with next step; new pre-screens; PI marks since last digest (including "Ask treating doctor" tasks); later (L): tasks and unverified fields; links to S8; why-line |
| N3 Approach-today notice (optional per study, off by default) | the study's coordinators on duty (S8 toggle `on_duty_date` = today, not snoozed; FR-UI-18) | In working hours, within 2 min of a PI marking **Approach** for a patient with a visit **today** | `[TrialBox] Approach now · <study> · clinic <room>` | Study, clinic room, time of mark. No pseudonym, no screening number. Outside the weekly CRC count but at most 2 per day per CRC (NFR-USAB-10). |
| N4 Approval request | the study's `investigator` (one page, one Approve; FR-FEAS-12, BD-13) | Batched, at most one per approver per 2 h (FR-NOTIF-03) | `[TrialBox] Approve: <study> criteria v3 (2 flagged)` | What waits, link to S20, why-line |
| N5 Safety (L) | `investigator` or named deputy | Immediately, not snoozable | `[TrialBox] AE grade ≥ 3 suggestion · <study>` | Study, pseudonym, link (login required) |
| N6 Admin failure | `admin` | Immediately | as FR-OPS-08 | Component, time, health-page link |


**Payload schema** (`schemas/notify/notice.json`, JSON Schema 2020-12):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://trialbox.local/schemas/notify/notice.schema.json",
  "title": "Notice",
  "description": "One outbound notice (ICD-13). Schema version 1.0.0. Pseudonyms and counts only (BD-04); never chart numbers, screening numbers, names, scores or model names.",
  "type": "object",
  "required": ["notice_id", "kind", "recipient", "lang", "generated_at", "items", "why"],
  "properties": {
    "notice_id": {"type": "string", "pattern": "^[0-9A-HJKMNP-TV-Z]{26}$", "description": "ULID"},
    "kind": {"enum": ["N1", "N2", "N3", "N4", "N5", "N6"]},
    "recipient": {"type": "string", "description": "Account id"},
    "lang": {"enum": ["ja", "zh-TW", "en"]},
    "generated_at": {"type": "string", "format": "date-time"},
    "items": {"type": "array", "items": {
      "type": "object",
      "required": ["item_id", "study_ids", "link"],
      "properties": {
        "item_id": {"type": "string"},
        "pid_pseudonym": {"type": "string", "pattern": "^[0-9a-f]{8,64}$", "description": "pid as built: 8 to 64 hex characters (services/orchestrator/candidates.py)"},
        "study_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "visit_at": {"type": "string", "format": "date-time"},
        "clinic": {"type": "string"},
        "practitioner_is_recipient": {"type": "boolean"},
        "counts": {"type": "object", "properties": {"met": {"type": "integer", "minimum": 0}, "to_check": {"type": "integer", "minimum": 0}}, "additionalProperties": false},
        "link": {"type": "string", "format": "uri-reference"}
      },
      "additionalProperties": false
    }},
    "why": {"type": "string", "maxLength": 200},
    "budget": {"type": "object", "properties": {"week_count": {"type": "integer"}, "merged": {"type": "boolean"}}, "additionalProperties": false}
  },
  "additionalProperties": false
}
```

**Budget and merge:** before sending, the service counts the recipient's non-safety notices this week (NFR-USAB-10: PI one N1 per clinic day, at most 5, + ≤ 2 approval batches; CRC 5 N2; RA ≤ 2; `cro` ≤ 1). When a notice would exceed the budget its items are merged into the next scheduled N1/N2. N3 is outside the weekly count and capped at 2 per day per CRC; a third N3 that day is not sent and the S8 "Marks today" pane still shows the mark. Counts per role per week go to the FR-NOTIF-08 admin page without content.

**Fallback when no link works (C-16):** N1 and N2 are complete without opening a link: pseudonym, visit time, clinic and study badges are enough for the PI to recognise the patient in the EMR clinic list.

**Conformance tests:** TS-NOTIF renders N1–N4 from the e2e fixture in JA, zh-TW and EN; asserts subject grammar, block order, no chart number / screening number / name / score / model name (PHI scan), why-line present, item suppression after a web read, and the merge when a simulated week exceeds the budget.

## 12. ICD-14 Upload files [H] (TB-REV-006c C-21; FR-ING-19/21)

**Transport:** on-prem web upload only (HTTPS, logged-in user, study in scope); never e-mail. Files are stored in the identified zone (D4) until mapped; the original is deleted after mapping unless the study keeps it as source (setting).

**Kinds:**

| Kind | Uploader | Content | Mapping |
| --- | --- | --- | --- |
| `shadow_log` | research office or pilot team (TB-DS-04 §8.9) | The CRC's existing screening log (XLSX/CSV), weekly | Mapping written once per layout by the pilot team: identifier column(s) → pid; date screened; staff outcome; reason. After mapping, identifiers are dropped; only `(pid, date, outcome, reason)` is kept in the comparison table |
| `study_db` | `investigator` or RA with study scope | A PI's own study database (XLSX/CSV, or an export of a personal REDCap project) | Per layout: identifier → pid, date columns, value columns, drop; hospital-stage mapping by the pilot team, later (L) by the wizard (FR-ING-20) |

**Required metadata (FR-ING-21)** (`schemas/upload/metadata.json`): `{kind, study, owner (account), ethics_approval_no, consent_type: opt_in | opt_out | waiver, allowed_use: this_study_only | listed_studies[], layout_id, uploaded_at, sha256}`. Upload is refused without `ethics_approval_no` and `consent_type`. Use in another study needs a new approval number and the owner's approval (audited).

**Metadata schema (JSON Schema 2020-12):**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://trialbox.local/schemas/upload/metadata.schema.json",
  "title": "UploadMetadata",
  "description": "Metadata required with every upload (ICD-14, FR-ING-21). Schema version 1.0.0.",
  "type": "object",
  "required": ["kind", "study", "owner", "consent_type", "allowed_use", "uploaded_at", "sha256"],
  "properties": {
    "kind": {"enum": ["shadow_log", "study_db"]},
    "study": {"type": "string"},
    "owner": {"type": "string", "description": "Account id of the uploader"},
    "ethics_approval_no": {"type": "string", "description": "Required when kind = study_db"},
    "consent_type": {"enum": ["opt_in", "opt_out", "waiver"]},
    "allowed_use": {"oneOf": [{"const": "this_study_only"}, {"type": "array", "items": {"type": "string"}, "minItems": 1}]},
    "layout_id": {"type": ["string", "null"], "description": "Null until the layout is mapped (UP-LAYOUT)"},
    "uploaded_at": {"type": "string", "format": "date-time"},
    "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}
  },
  "if": {"properties": {"kind": {"const": "study_db"}}},
  "then": {"required": ["ethics_approval_no"]},
  "additionalProperties": false
}
```

**Errors** (register §2.3): `UP-META` (metadata missing), `UP-LAYOUT` (unknown layout: held for mapping), `UP-IDMATCH` (identifier rows not matched: count shown, rows not imported), `UP-SIZE` (> 50 MB).

**Conformance tests:** two synthetic shadow-log layouts (JA Excel with 和暦 dates; zh-TW Excel with 民國 dates) and one study_db layout; expected: correct pid match rate, no identifier left in the comparison table or lake (PHI scan), metadata enforced.

## 13. Open items

| ID | Item |
| --- | --- |
| IC-01 | Confirm SS-MIX2 directory depth, data-type codes and extended-storage use at the Japan head hospital (SSI or Fujitsu), and the appointment (予約) source: vendor export (ICD-01 `appointment` table), extended storage, or none. |
| IC-02 | Confirm the REDCap API parameter list against the head hospital's REDCap 16 API documentation page (the call table is written from the public REDCap API; verify on the dev server). |
| IC-03 | CGMH data-warehouse view definitions (tables, delta columns) with CGMH IT. |
| IC-04 | Decide whether DET is reachable from REDCap to the appliance in each hospital network (firewall rule). |
| IC-05 | Consortium CA operator per country. |
| IC-06 | Per pilot study: REDCap field names for consent, enrolment, screen-fail and withdrawal; whether the admin will add `tb_screening_no` (default) or the project holds an MRN the site agrees to use (`mrn`); sponsor subject-number field; DAG use (REDCap project inspection, R-05). |
| IC-07 | Whether the hospital mail server accepts the appliance as a sender to all staff mailboxes, and the clinic-day source (appointment export) per site (IC-01, R-06). |

## 14. References

- ISO/IEC/IEEE 42010:2022 (interface view of TB-DS-02); IEEE 1016-2009 (design description practice).
- JSON Schema 2020-12 (json-schema.org/draft/2020-12).
- RFC 9457 Problem Details for HTTP APIs (error model, §2.2).
- RFC 6238 TOTP; RFC 8291 Message Encryption for Web Push (H/L).
- HL7 FHIR R4 4.0.1; FHIR Bulk Data Access IG 2.0.0 (ICD-03); JP Core 1.2.0; TW Core.
- REDCap API documentation of the installed version (IC-02); REDCap External Module framework.
- SS-MIX2 標準化ストレージ 仕様書 (ICD-02, H).
- RFC 5321 SMTP; RFC 6376 DKIM; RFC 7208 SPF (ICD-08, ICD-13).
- Shared terms: TB-DS-01 Appendix C.

## Change history

| Seq | Version | Date | Author | Change |
| --- | --- | --- | --- | --- |
| 1 | 0.1 | 2026-11-07 | Claude for Aimedics | First draft; payload schemas, error codes, conformance tests. |
| 2 | 0.1a | 2026-11-07 | Claude for Aimedics | TB-REV-006b: SIU^S12 row removed from ICD-02; appointments from the vendor 予約 export (ICD-01) or extended storage, IC-01 extended (R2-09); ICD-09 `classify_intent` wording (R2-19). |
| 3 | 0.2 | 2026-11-07 | Claude for Aimedics | TB-REV-006c: ICD-04 §4.1a project link and field map per study mirroring `rc_project_link` (TB-DS-07), link modes `tb_screening_no` (default, BD-18) / `mrn`, status mapping, RC-LINK errors and a two-project conformance test (C-06, C-17); R7 reads changed records nightly; consent `RELEASE` command removed (BD-15, C-05); new ICD-13 outbound notices (clinic-day list, CRC digest, optional approach-today notice, approval requests; budget merge; no-link fallback) (C-02, C-13, C-14, C-16, C-20); new ICD-14 upload files (shadow log, personal study database, metadata) (C-02, C-21); IC-06, IC-07. |
| 4 | 0.3 | 2026-11-07 | Claude for Aimedics | TB-REV-006d: ICD-13 content rule and TS-NOTIF PHI scan exclude the screening number (D-03); N3 recipients = coordinators on duty (D-16); budget per clinic day and N3 cap of 2 per day (D-10, D-18). |
| 5 | 0.4 | 2026-11-07 | Claude for Aimedics | TB-REV-006f: build-stage note in the control table (which interfaces each step needs); new §4.4 ICD-04S REDCap API simulator (F6-15). Frozen as reference. |
| 6 | 0.5 | 2026-11-07 | Claude for Aimedics | TB-REV-006f §R: mail-grammar release cells re-tagged S0 / S1 / L (was M1/M2). |
| 7 | 0.6 | 2026-11-07 | Claude for Aimedics | TB-REV-006g Q-25, Q-26, S-02, S-06, S-08: error register adds RC-LINK-FIELD, RC-LINK-DUP, UP-META, UP-LAYOUT, UP-IDMATCH, UP-SIZE, NOTIFY-UNDELIVERED; JSON Schema 2020-12 blocks for ICD-13 notice and ICD-14 upload metadata; ICD-03 and ICD-12 given the common headings (parties, transport, format/schema, errors, conformance); §10a/§10b renumbered §11/§12, open items §13, new §14 references; §1 table and headings carry build tags (S0/S2/S3/S4/H/L); N4 goes to the investigator only (one Approve, BD-13); ICD-09 auth TOTP marked hospital stage; escaped-pipe row fixed; sequence column. |
| 8 | 0.7 | 2026-11-07 | Claude for Aimedics | TB-REV-006g §R residue: §4.3 DET handling H / L; §7 intent-parsing gate L; N2 later items L; ICD-13 notice payload stated once (schema block only, file name kept); Status as frozen build-stage reference. |
