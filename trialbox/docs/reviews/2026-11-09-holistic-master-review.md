# Holistic master review: every open finding, every owner intent, one register (2026-11-09)

| Field | Value |
| --- | --- |
| Date | 2026-11-09 (evening) |
| Head reviewed | `claude/trialbox-plan-v4-oxn56n` 6eb7ed8 (code equal to `origin/master` e91871c plus the review records). Wave 1a and 1b fixes exist on the branch `wave1-scenarios` (D-141 to D-143) and are **not merged** at this head; their status is marked "on branch". |
| Owner | Changfu Kuo (Aimedics) |
| Author | Claude, lead architect, for the master plan TB-PLAN-05 (`docs/plan/25-master-plan.md`) |
| Status | Record. The register, the contradictions and the coverage check are the input to TB-PLAN-05. New facts go into DECISIONS. |
| Binding input | `2026-11-09-owner-decisions-data-and-profile.md`, including its newest section "Master plan and pilot". Where any review disagrees with it, the decisions document wins. |

## 0. What this review is

Eleven reviews were written between 2026-11-05 and 2026-11-09, plus three design documents, a catalogue, and the owner's decisions. They overlap, and in places they disagree. This review puts every open finding and gap into **one register** (§2), lists every **contradiction** and how it is resolved (§3), and checks every **owner intent** against the plan (§4). Nothing is dropped. Where something is deferred, it is deferred in writing with the plan item that holds it.

Inputs read in full or in their findings sections:

| Short name | File | What it gave |
| --- | --- | --- |
| Plan v4 | `docs/plan/24-plan-v4.md` | the step list TB-PLAN-05 replaces |
| Plan review | `docs/plan/fable-review-2026-11-08.md` | ten findings, most closed by D-112 to D-122 |
| Design/code review | `docs/reviews/2026-11-08-fable-design-code-review.md` | F-01 to F-32 (code), mostly closed by D-126 to D-130 |
| Standards and security review | `docs/reviews/2026-11-08-fable-standards-security-review.md` | M1 to M12, S1 to S8, O1 to O6; security F-01 to F-23; top 10 actions |
| Field research | `docs/reviews/2026-11-08-field-research-tw-jp-sites.md` | requirements M1 to M12, S1 to S10, C1 to C5 |
| Novice UX review | `docs/reviews/2026-11-08-ux-review-novice.md` | top 15 changes (mostly closed by D-133) |
| Open data candidates and baseline | `docs/reviews/2026-11-08-open-data-candidates.md`, `2026-11-09-baseline-open-data.md` | the P0 data set, seven owner decisions, corrections to D-122 and D-137 |
| Full system review | `docs/reviews/2026-11-09-full-system-review.md` and `2026-11-09-review-parts/01..06` | R-01 to R-113 in waves 1 to 5, gate G1, O-01 to O-27 |
| Patient data design | `docs/reviews/2026-11-09-design-patient-data-and-roles.md` | the OMOP, profile, roles and consortium design; steps 0 to 13; nine questions |
| Standalone DB review | `docs/reviews/2026-11-09-standalone-db-vector-profiling-review.md` | the independent verdict; integration steps 0 to 10; 45 questions |
| Owner concept | `docs/reviews/2026-11-09-owner-patient-profiling-concept.md` | the profile layers and the "projection, never replacement" rule |
| Component reviews | `docs/reviews/2026-11-09-component-review-layer1.md`, `-layer2-verification.md` | library and licence facts; the Postgres image; python-hl7; Authelia; SNOMED fee |
| Holistic 01 | `docs/reviews/2026-11-09-holistic-01-clinical-operations.md` | site actors, missing-data rules, P0 to P2 components, Q1 to Q14 |
| Holistic 02 | `docs/reviews/2026-11-09-holistic-02-commercial-regulatory.md` | regulation, procurement, contracts, Study A to E, P0 to P2, Q1 to Q12 |
| Holistic 03 | `docs/reviews/2026-11-09-holistic-03-platform-engineering.md` | capability map, P0 to P2 components, 15 risks, Q1 to Q14 |
| Clinical item catalogue | `docs/reviews/2026-11-09-clinical-item-catalogue.md` and `catalogue/` (merged before the plan) | 469 items, 164 phenotypes, 26 scores, licence decisions, 10 questions |
| User-journey review | `docs/reviews/2026-11-09-user-journeys-e2e.md` (merged before the plan) | J-01 to J-29; 37 journeys; coverage by module; routes without a UI |
| Data-flow lifecycle review | `docs/reviews/2026-11-09-dataflow-lifecycle-review.md` (merged before the plan) | inputs, authority, audit, derived data, the data-ops console, the statistics page, import and export, compression; P0 to P2; 12 questions |
| Owner decisions | `docs/reviews/2026-11-09-owner-decisions-data-and-profile.md` | binding |
| DECISIONS | `docs/DECISIONS.md` D-112 to D-140 at this head; D-141 to D-143 on `wave1-scenarios` | what is built and what is "not done" |

Three reviews were still being written when this review started. All three arrived and are folded in: the clinical item catalogue (§2.6), the data-flow lifecycle review (§2.10) and the user-journey end-to-end review (§2.11). §6 records where each went.

## 1. One page

**State.** The product is a complete vertical slice (feed in, pseudonyms, criteria to SQL, two-model note reading, console in three languages, forms, lifecycle, REDCap two-way, signed updates, encrypted backups, hash-chained audit) with 1,423 to 1,460 tests passing, and an incomplete platform: no CI gate, no release identity, no metrics, no scheduled backup, no MFA, no AD/LDAP, nothing has run in Docker or on the production gateway path with the real model pair. Five patient-safety blockers were found on 2026-11-09; three are fixed on a branch (R-01, R-02, R-06 in D-142), two are fixed on a branch for the page part (R-03 in D-143) and open for the platform part (R-04 MFA, R-05 Windows keys).

**What the owner wants, decided today.** A full clinical repository on OMOP v5.4, study-patient profiles with citations, vectors, a steward role, PI sees everything for their studies, sub-PI by delegation, referral through a possibly unknown treating physician, whole-hospital screening, REDCap EDC prefill with GAMP 5 validation, both pilot sites in parallel, go-live within three months with real patients at both.

**The honest gap.** The reviews size the remaining platform work at 215 to 255 engineer-days (full system review) plus 135 to 180 (standalone DB review) plus 14 engineer-weeks of P0 (holistic 03): about 420 to 500 engineer-days of single-engineer work. Agents working in parallel compress calendar time, not review time or hospital lead time. The critical path of the next three months is **not code**: it is the boxes (4 to 8 weeks), hospital IT approval (2 to 6 weeks), two contracts, the second IRB (monthly meetings), and the two unknown data feeds. TB-PLAN-05 shows where each of these can make the date slip and what the fallback is.

**Counts in this register.** 212 rows. By status at head 6eb7ed8: about 34 done or partly done, 21 on a branch (D-141 to D-143, not merged), the rest open or decided-and-open. By severity: 20 Blocker (owner-frame items that block go-live are counted), 60 High, 80 Medium, 30 Low. The counts are by hand and approximate; the rows are what matter.

## 2. The register

How to read it. **MR** is the master id. **Sources** keeps every original id. **Sev** is the highest any review gave; owner-frame items that block go-live are Blocker. **Status** is checked against the code at head 6eb7ed8 and against DECISIONS: *done* (a decision names the test), *branch* (built on `wave1-scenarios`, D-141 to D-143, not merged), *open*, *decided* (the owner decided it; nothing is built), *docs* (only a document change). **Plan** is the TB-PLAN-05 item that holds it.

### 2.1 Patient safety and screening correctness

| MR | Sources | Sev | Area | Finding, short | Status | Plan |
| --- | --- | --- | --- | --- | --- | --- |
| MR-001 | R-01, A-01, S-13, 06 S2, D-142 | Blocker | Gateway | Installed box refuses every PHI prompt; model hashes null; every GPU run bypassed the gateway | branch (box policy `phi_on_box`, `pin_model --install`) | WS-01.1, WS-02.1 |
| MR-002 | R-02, B-01, R-31, B-09, D-142 | Blocker | Engine | Text lab values ("75 H", "<0.3", 陰性) excluded silently; row unit ignored | branch (`tb_common.labvalue`, censored values); unit mismatch (R-31) **open** | WS-01.1, WS-03.3 |
| MR-003 | R-06, B-02, B-18, D-142 | High | Cascade | Patient missing from the snapshot shown as excluded; raw English reasons | branch | WS-01.1 |
| MR-004 | R-07, P-04, O-04, owner "nothing excludes silently", D-143 | High | Product safety | No "excluded and why" page; weekly PI sample of ten | branch (`excluded_<study>.json` and page per study); weekly sample **open** | WS-01.1, WS-06.7 |
| MR-005 | R-08, 02 susp. 1, 06 S10, D-142 | High | SS-MIX2 | 疑い flag ignored; a suspected diagnosis could exclude | branch (PRB-13 read; `suspected_diagnosis` reason) | WS-01.1, WS-10.3 |
| MR-006 | R-09, P-02, P-03, O-03, D-143 | High | SAE | Fatal SAE leaves the banner; no PI acknowledgement; no 7/15-day clock | branch (`ae_ack`, reporting clock, JP/TW defaults); **site confirmation of the clocks open** | WS-01.1, WS-10.6, WS-11.6 |
| MR-007 | R-10, B-03, D-142 | High | REDCap | Longitudinal sync blanks consent and enrolment dates | branch | WS-01.1, WS-07.2 |
| MR-008 | R-37, A-06, 02 susp. 5, D-142 | Medium | Excerpts | A long newest note hides older evidence | branch | WS-01.1 |
| MR-009 | R-38, A-07, D-142 | Medium | Throughput | S3/S4 sequential; 2,000-pair budget truncates silently at 50k | branch (concurrency, explicit budget, listed not excluded) | WS-01.1, WS-02.1 |
| MR-010 | R-47, B-10 | Medium | Cascade | A pass at confidence 0.5 to 0.75 shown as "high" | open | WS-01.5 |
| MR-011 | R-44, B-04 | Medium | Lifecycle | `anchors()` uses undone steps; wrong due visits | open | WS-01.5 |
| MR-012 | R-48, B-15, B-16 | Medium | Pseudonym join | Leading zeros and hex case give phantom patients; unmatched sheet pseudonyms not listed | open | WS-03.3, WS-08.4 |
| MR-013 | R-33, B-07, B-08, E-05, 06 §6.9 | Medium | Encodings | Big5 read as CP932; U+FFFD labels; one shared detector missing | open | WS-01.2, WS-01.4 |
| MR-014 | R-85, B-13, R-94, B-11 | Low | Site set-up labs | mmol/L urate stored unconverted; unreadable lab cells vanish | open | WS-01.5 |
| MR-015 | R-95, B-12 | Low | Dates | `112年3月15日` unreadable | open | WS-01.4 |
| MR-016 | 02 susp. 6 | Low | Labs JP | HbA1c JDS before 2012-04 not converted | open | WS-04.3 |
| MR-017 | D-142 "not done" | Medium | SS-MIX2 | ICD-10 only from PRB-3 alternate, not PRB-10; PRB-14 states beyond resolved | open | WS-10.3 |
| MR-018 | D-142 "not done", F3 | Medium | CQL gate | CQL does not read censored values; "unreadable value" reason code not shown | open | WS-01.5 |
| MR-019 | holistic 01 §3, holistic 03 P0-12 | High | Missing-data model | No per-item reason for absence; "needs information" does not say what or whom to ask; outside care, deaths, EMR-since, NHI cloud, お薬手帳 all unmodelled | open | WS-06.9, WS-03.2 |
| MR-020 | D-141 FHIR-01, XL-02, MAP-01, DUMP-01 | High | Scenario run | FHIR scope 0; publish duplicated patients and spilled without bound; name suggestions wrong; undated rows decided | branch (fixed in D-142's scenario-run fixes) | WS-01.1 |
| MR-021 | D-141 "not done" | High | Scenario run | Model exclusions vs note truth, extraction precision and recall, tesseract: card only | open until G1 | WS-02.1 |

### 2.2 Privacy, roles and access

| MR | Sources | Sev | Area | Finding, short | Status | Plan |
| --- | --- | --- | --- | --- | --- | --- |
| MR-022 | R-03, P-01, P-32, S-19, O-02, D-143 | Blocker | Console | Chart number on the CASE job page to every role; `/jobs` and `/audit` across studies | branch (view by identifier authority, masked audit, `public_e2e` 7b sweep); viewer/investigator `/jobs` scope **check at merge** | WS-01.1 |
| MR-023 | R-04, S-02, P-23, O-13, F-04 (sec.), M1 | Blocker | Authentication | No second factor; no AD/LDAP; no forced password change; MHLW GL 7.0 needs two factors from FY2027 | open | WS-13.1 |
| MR-024 | R-11, S-03, F-06 (sec.) | High | SSO | Trusted-header SSO forgeable behind Docker NAT; audit flood | open | WS-13.1 |
| MR-025 | R-32, S-09, D-143 | Medium | Actor | Registry export without actor or audit; `X-TB-Actor` caller-asserted; reveal cap in memory | branch (signed actor, audited export) | WS-01.1 |
| MR-026 | R-52, S-14, F-22 (sec.) | Medium | Passwords | No breached list, no history, lockout per username only | open | WS-13.1 |
| MR-027 | owner (steward), design §4, holistic 03 P0-13 | Blocker | Roles | No `steward` role; admin sees PHI; no one permission function | decided, open | WS-06.1 |
| MR-028 | owner D-143, design §4.2 | High | Roles | PI sees everything for own studies, chart numbers included | branch (D-143) | WS-06.1 |
| MR-029 | owner, holistic 01 P0, holistic 03 P1-1 | Blocker | Delegation | Sub-PI by delegation log with tasks and training dates; monthly comparison with the office's signed log | decided, open | WS-06.2 |
| MR-030 | owner, holistic 01 P0, BD-19, M12 | Blocker | Referral | Referral object; treating physician suggested, typed, "outside TrialBox", department fallback; CRC records the answer; never stalls | decided, open ("Ask treating doctor" exists as three i18n strings only) | WS-06.3 |
| MR-031 | owner, holistic 01 P0 | Blocker | Staff directory | Steward-maintained practitioner and department directory; type-ahead | decided, open | WS-06.4 |
| MR-032 | owner, design §4.2 | High | Candidate view | PI and delegated sub-PI see everything needed to decide about any candidate found anywhere in the hospital; logged with study and purpose; rate-limited | decided, open | WS-06.5 |
| MR-033 | owner, design §4.2, standalone Q10 | High | Break-glass | Reason plus second person on the steward/admin rota; time-limited; audited | decided, open | WS-06.6 |
| MR-034 | owner, design Q5, holistic 01 Q8 | Medium | Monitor SDV | CRA sees enrolled subjects' cited items only | decided, open (print-only fallback allowed) | WS-07.6 |
| MR-035 | owner, holistic 01 Q7, 03 P1-9, F-04 (code) | High | Opt-out | Office-maintained opt-out register; S0 applies it; removal from screening, profiles, vectors, exports logged; count only, never the patient | decided, open (S0 reads a feed table; `except Exception` on consent fixed in D-127) | WS-06.8 |
| MR-036 | owner, holistic 01 Q6 | High | IRB gate | Missing IRB approval date or ICF version warns, does not block; override logged | decided (warning, not gate), open | WS-06.10 |
| MR-037 | holistic 01 P0 | Medium | IRB pack | One-page "what this system does with charts" generated from site settings, ja/zh-TW | open | WS-10.1, WS-11.1, WS-13.6 |
| MR-038 | R-100, S-21, holistic 02 P0-1 | High | Labelling | Intended-use statement and non-device line not in the code; no forbidden-word check | open | WS-13.7 |
| MR-039 | owner (revised), holistic 02 Q1, standalone Q4 | High | Clinician view | Setpoint and gap layers to clinicians only inside a study-referral context, numbers only, no disease name, switch off by default, until a written PMDA/MHLW 該当性 view and a TFDA view exist | decided, open | WS-05.6, WS-15.4 |
| MR-040 | owner, standalone Q6 | Medium | Steward notes | Steward may read all free text at any time; every view audited, kept 10 years | decided, open | WS-06.1 |
| MR-041 | owner | Medium | Clinician scope | Own patients = seen or ordered for in 24 months or booked in 90 days; privacy office may add ward inpatients | decided, open | WS-06.1 |
| MR-042 | R-35, S-15, F-17 (sec.), owner gap rules | Medium | Prompt injection | No "data not instructions" sentence; no injection suite; needed before model-proposed gap rules | open | WS-02.4 |
| MR-043 | R-86, S-22, F-23 (sec.) | Low | Logs | Scrubber misses names in exception text | open | WS-13.3 |
| MR-044 | R-99, S-20, F-18 (code) | Low | SSRF | REDCap `http://` allowed; `nct_id` unchecked in live mode | open | WS-13.3 |

### 2.3 Platform, data at rest, audit

| MR | Sources | Sev | Area | Finding, short | Status | Plan |
| --- | --- | --- | --- | --- | --- | --- |
| MR-045 | R-05, S-01, F-01 (sec.), F-31 (code) | Blocker | Windows/WSL2 | Hardening written for Ubuntu; no BitLocker, swap, hibernation checks; keys in clear beside data; uploads and `phi` outputs in clear | open | WS-13.2, WS-14.1 |
| MR-046 | R-50, S-11, F-10 (sec.) | Medium | Keys | Site keys created silently; a restore without them re-keys | open | WS-13.2 |
| MR-047 | R-18, S-04, A-20, F-08 (sec.), R-91 | High | Audit | Unkeyed hash chain; six writers; archive on the same box; NTP a warning; audit after state | open | WS-13.4 |
| MR-048 | R-12, S-05, F-07 (sec.), F-29 (code) | High | Mail | PPAP zip default; chart numbers mailed | open | WS-13.3 |
| MR-049 | R-13, A-02, A-11, E-11, D-142 | High | Stability | One connection per store, no reconnect; `/healthz` without DB; migrations split on `;` | branch (reopen, `ping()`; pool rejected); checksummed migrations **open** | WS-01.1, WS-03.1 |
| MR-050 | R-17, A-05, D-04 | High | Resources | No container memory, CPU, pids limits | open | WS-01.3 |
| MR-051 | R-34, S-10, F-11, F-21 (sec.) | Medium | Internal | HAPI unauthenticated, superuser roles, CREATEDB | open | WS-13.3 |
| MR-052 | R-49, S-08, F-12 (sec.) | Medium | Gateway | Routes on self-declared `X-TB-Caller`; GPU holds unbound | open | WS-13.3 |
| MR-053 | R-51, S-13, D-05, F-14 (sec.) | Medium | Images | vLLM by tag; no `cap_drop`, `read_only`; `ipc: host` undecided | open | WS-14.3 |
| MR-054 | R-53, S-16, D-29, F-09 (sec.) | Medium | TLS | No TLS in the product; Secure cookie default 0 | open | WS-13.1 |
| MR-055 | R-54, S-17, F-13 (sec.) | Medium | Egress | Docker DNS open; allowlist resolved at apply time | open | WS-13.3 |
| MR-056 | R-22, D-01, holistic 03 risk 12 | High | Egress | Table not persisted; open outbound after reboot | open | WS-01.3 |
| MR-057 | layer 2 §1.2, 03 P0-9 | High | Postgres image | `postgres:16-alpine` cannot take pgvector; musl to glibc later means a REINDEX | open | WS-03.1 |
| MR-058 | R-36, D-14 | Medium | Update | Plaintext dumps remain after a failed update | open | WS-14.2 |
| MR-059 | R-42, A-12, D-34, D-141 | Medium | Cloud | Key in the serial log; `tb-key` left in metadata; port 80 | branch (`set -x` removed); rest **open** | WS-02.5 |
| MR-060 | R-14, A-03, D-30..32, D-141 | High | Cloud run | No cap; today's VM ran 61 minutes by hand | branch (cap, watchdog, workload on VM); budget alert is an owner action | WS-02.5 |

### 2.4 Operations, release, engineering

| MR | Sources | Sev | Area | Finding, short | Status | Plan |
| --- | --- | --- | --- | --- | --- | --- |
| MR-061 | R-20, S-07, D-126 | High | Backup | Default target the same disk; HAPI not dumped | open | WS-08.6 |
| MR-062 | R-21, D-19, D-20, 03 P0-7 | High | Backup | Not scheduled; hand-run fails on compose; no age alert; no restore drill with the site | open | WS-08.6 |
| MR-063 | R-45, B-05; R-96, B-14; R-108, D-21 | Medium | Backup | Live-backup hash race; prune across sites; restore does not stop services | open | WS-08.6 |
| MR-064 | R-23, D-11 | High | Update | No crash marker, status, resume | open | WS-14.2 |
| MR-065 | R-24, D-12, D-18 | High | Update | No free-space check; 3× staging | open | WS-14.2 |
| MR-066 | R-25, D-13, S-12, F-15 (sec.) | High | Update | No anti-rollback, key id, expiry, rotation | open | WS-14.2 |
| MR-067 | R-46, B-06; R-59, D-16; R-60, D-17 | Medium | Update | Services left stopped; file stores not rolled back; refdata inflates rollback | open | WS-14.2 |
| MR-068 | R-26, D-15, O-06, 06 S5, S13, E-14 | High | Docker | Nothing has run in Docker: compose with tokens, egress, HAPI gate, mail, update and rollback, demo-VM commands | open | WS-14.4 |
| MR-069 | R-27, D-35, 03 P0-3 | High | Release | Everything `1.0.0`; no tag, changelog, `release.json` | open | WS-14.5 |
| MR-070 | R-28, E-01, E-18, 03 P0-1 | High | CI | One workflow, PR only; no pytest, lint, mypy, doclint, image build, audit, SBOM, nightly | open | WS-01.4 |
| MR-071 | R-29, E-02, E-04 | High | Tests | Autouse Postgres; leaked schemas and clusters; 18 min | open | WS-01.4 |
| MR-072 | R-19, S-06, E-03, D-36, 03 P0-4, layer 2 §3 | High | Supply chain | pypdf and pillow advisories; no hashes; no SBOM; nine LGPL packages unlisted | open | WS-14.6 |
| MR-073 | R-43, A-14, D-22, P-12, O-14, 03 P0-5 | Medium | Monitoring | No metrics, alerts, disk, GPU, backup age; admin tiles say "at install" | open | WS-08.5 |
| MR-074 | R-61, D-23, 03 P0-6 | Medium | Support | No PHI-free support bundle | open | WS-17.4 |
| MR-075 | R-16, A-04, A-13, 03 P0-15, Q4 | High | Mail | Stuck send keys; no resolve tool; outbox unwired | open | WS-01.3 |
| MR-076 | R-39, A-08; R-40, A-09 | Medium | Jobs | No cancel; no circuit breaker; restart repeats every call | open | WS-01.3 |
| MR-077 | R-41, A-10 | Medium | Reproducibility | "Byte-identical" false with the pair | docs, open (replay P1-17) | WS-12.5 |
| MR-078 | R-55, D-02; R-56, D-03; R-62, D-25, E-12; R-63, D-26; R-64, D-27 | Medium | Install/config | Exit 0 on FAIL; `.env.example` copied; 121 `TB_*`, 55 undocumented; unsafe defaults; rotation not atomic | open | WS-01.3, WS-14.1 |
| MR-079 | R-57, D-08; R-111, D-37 | Medium | WSL2 | `check_host` FAILs LUKS on WSL2; `SHA256SUMS.sig` unchecked | open | WS-14.1 |
| MR-080 | R-58, D-10; R-88, A-16; R-90, A-18; R-107, D-09 | Medium | Compose | One-shot start helpers; start order; canary churn; health wait | open | WS-01.3 |
| MR-081 | R-65, D-33 | Medium | Hosted demo | Shared password in metadata; unsigned `tb-patch` | open | WS-02.5 |
| MR-082 | R-66, E-05, layer 2 §1.1 | Medium | Parsers | HL7 parser ignores MSH-2, sub-components; six date modules | open (python-hl7 or 60-line fix) | WS-01.4, WS-10.3 |
| MR-083 | R-67, E-06, 03 P0-2, design step 0 | High | Goldens | No committed funnel goldens; integration files unmarked | open | WS-03.1 |
| MR-084 | R-68, E-07, E-15, 03 risk 15 | Medium | Code quality | CC 162 functions; `app.py` 1,724 lines; i18n in Python | open | WS-01.4 |
| MR-085 | R-69, E-08, E-09, 03 P0-14 | Medium | Repository | Auto-GPT root; no `trialbox/LICENSE`, notices; no CONTRIBUTING, CODEOWNERS | open | WS-14.6, WS-17.5 |
| MR-086 | R-70, E-10; R-98, S-18; R-102, E-13; R-103, E-16; R-104, E-17, P-31; R-105, D-06; R-106, D-07; R-109, D-24; R-110, D-28 | Low | Hygiene | Unused deps; SQL strings; bare excepts; flakiness; doc numbers; SELinux; shellcheck; log caps; network sheet | open | WS-01.4 |
| MR-087 | R-71, E-14, 06 S4, O-08, layer 2 §1.3 | Medium | OCR | Never run on a real scan; `chinese_cht` hard-coded; PaddleOCR 2.x API on 3.x; CPU only on the 5090 | open | WS-01.5, WS-10.5, WS-11.5 |
| MR-088 | R-87, A-15; R-89, A-17; R-93, A-22 | Low | Scale | Notes in one Arrow table; `--enforce-eager` unmeasured; audit page reads JSONL | open | WS-01.4 |
| MR-089 | R-92, A-21 | Low | State | Inventory of state outside Postgres in RUNBOOK and the drill | open | WS-08.6 |
| MR-090 | 03 P0-8, Q5 | High | Flags | No feature-flag mechanism; profile, OMOP dual-write, clinician layers all need one | open | WS-01.4 |
| MR-091 | 03 P0-10, P0-11, §3.4 | High | Model lifecycle | No `qualify` command; prompts are files; no qualification record; no drift baseline | open | WS-02.2, WS-02.3 |
| MR-092 | 03 P0-15, Q3, Q4 | Medium | Dead code | `dataplat` unwired; `db_pg.py` duplicate; Hermes remnants | open | WS-01.4 |
| MR-093 | 03 §2.5, Q2 | Low | Decomposition | Nine processes; merge to five | deferred to after go-live (owner question) | WS-01.6 |
| MR-094 | 03 P1-13, Q9 | High | Acceptance box | No site-acceptance environment; a hospital must not be the first Docker host | open | WS-14.4 |
| MR-095 | 03 risk 8, Q12 | High | Bus factor | One human merges; no second reader of the safety core | open (owner question) | WS-17.5 |

### 2.5 Product completeness for the pilot

| MR | Sources | Sev | Area | Finding, short | Status | Plan |
| --- | --- | --- | --- | --- | --- | --- |
| MR-096 | R-15, P-21, O-01, 06 S1, E-14, D-139 | High | Truth | Every gate runs the stub; the pair has never run `e2e_simple` | open: Gate G1 | WS-02.1 |
| MR-097 | R-30, P-05 | High | PI list | No priority; same pills; "First/Second check" unexplained | open | WS-01.5 |
| MR-098 | R-72, P-06, O-10 | Medium | Language | English labels on ja/zh-TW feasibility and approval pages | open | WS-01.5 |
| MR-099 | R-73, P-07, P-08, O-11, D-143 | Medium | Wording | "Nothing is ever written to REDCap"; two words per state | branch | WS-01.5 |
| MR-100 | R-74, P-09, O-12, M8 | Medium | Outcomes | Missing "treating doctor declined", "family declined", "patient wants time", "deceased" | open | WS-06.3 |
| MR-101 | R-75, P-10, P-28, O-15, D-143 | Medium | Confirmations | Disable, Reset, Keep/Take, Detach, Approve all | branch (confirm); undo for outcomes and conflicts **open** | WS-01.5 |
| MR-102 | R-76, P-11, O-16 | Medium | Consistency | PI pages do not refresh participants | open | WS-01.5 |
| MR-103 | R-77, P-13, P-14, P-29, O-10 | Medium | Feasibility honesty | Default rates behind the headline; "6 %" vs 3.1 %; §9 registry sentence | open | WS-01.5 |
| MR-104 | R-78, P-15, O-17 | Medium | Help | Ask TrialBox answers two canned questions | open | WS-17.2 |
| MR-105 | R-79, P-16, P-17, O-18 | Medium | Site set-up | First sheet only; five analytes; republish per tap; no temporary key | open | WS-08.4 |
| MR-106 | R-80, P-18, P-19, O-05, O-20, O-21, 06 S3 | High | REDCap | Arm 1 only; no repeating instruments; never run against a real REDCap; FHIR export internal only | open | WS-07.2, WS-10.4 |
| MR-107 | R-81, P-20, O-22 | Medium | CGRD | De-identified and yearly: feasibility only; say so | docs, open | WS-11.2 |
| MR-108 | R-82, P-22 | Medium | Phone | `mm/dd/yyyy` on ja/zh-TW; sheet opens under the list | open | WS-01.5 |
| MR-109 | R-83, O-09, P-27, M10 | Medium | Guides | No ja/zh-TW user guide or one-page role sheets | open | WS-17.1 |
| MR-110 | R-84, O-07, 06 S12, 02 susp. 2 | High | Real JP data | No vendor SS-MIX2 or real MEDIS/JLAC10/YJ file ever read; dotless ICD codes | open | WS-10.3 |
| MR-111 | R-112, P-24..26, O-24 | Low | Wording | Colon spacing; "第一次確認"; サインイン | open | WS-01.5 |
| MR-112 | R-113, P-30, O-19, U8 | Low | Visits | No "window closes in 2 days"; no `.ics`; no printed appointment card | open (owner: printed card and calendar file now) | WS-06.11 |
| MR-113 | holistic 01 U3, P1 | Medium | Sponsor trials | Double entry with the sponsor EDC; weekly CSV read of the visit log | open | WS-07.5 |
| MR-114 | holistic 01 P1, S1 | Medium | Workload | CRC minutes per candidate not measured; no work log | open (needed for Study A time-motion) | WS-16.2 |
| MR-115 | holistic 01 P1, Q12, C3 | Low | Questionnaire | Sponsor feasibility questionnaire filler | deferred P1 | WS-18.1 |
| MR-116 | holistic 01 P1, Q9 | Low | Stipend | Per-visit stipend row | deferred P1 | WS-18.1 |
| MR-117 | holistic 01 P1 | Low | Intake | Patient-initiated contact path; campaign record | deferred P1 | WS-18.1 |
| MR-118 | holistic 01 P2 | Low | Close-out | Study close-out, archive bundle, retention clock | deferred P2 | WS-18.1 |
| MR-119 | holistic 01 U2, 03 P1-3, Q10 | Medium | EMR launch | No link from a candidate to the EMR chart | open (site IT question) | WS-06.12 |
| MR-120 | holistic 03 P1-1, P1-2, Q11 | Medium | Tasks | No task and inbox engine; four queues | open (referral built as the first task type) | WS-06.3 |
| MR-121 | holistic 03 §1.5 | Low | Search | No search over studies, pseudonyms, numbers | deferred P1 | WS-18.1 |
| MR-122 | D-134 "not done" | Medium | Lifecycle | Unscheduled visits; several arms; schedule versioning; AE grading never automated (keep) | open | WS-07.2 |
| MR-123 | D-137 "not done" | Medium | SS-MIX2 | AllergyIntolerance not read; `_contents.xml` not used; real ADT meaning untested | open | WS-10.3 |
| MR-124 | D-139 "not done", O-27 | Medium | Documents | USER_GUIDE ja/zh-TW; independent re-review after the card run | open | WS-17.1, WS-12.6 |

### 2.6 Data core, OMOP, catalogue, profile, vectors, consortium

| MR | Sources | Sev | Area | Finding, short | Status | Plan |
| --- | --- | --- | --- | --- | --- | --- |
| MR-125 | owner, design §2.2, standalone §2, layer 2 rank 11 | Blocker (owner frame) | OMOP | OMOP CDM v5.4 in Postgres as store of record; lake exported with the same table names; counts identical | decided, open | WS-03.4, WS-03.5 |
| MR-126 | design step 2, 03 P1-7 | High | Provenance | Row-level `source_kind`, `source_system`, `source_record_id`, `trust`, `status_concept`, `value_text`; `lake_meta.schema_version` | open | WS-03.2 |
| MR-127 | design step 3, 03 P1-6, layer 2 §2.3 | High | Vocabulary | Terminology in five shapes; one `vocab` schema with versioned releases | open | WS-03.3 |
| MR-128 | owner, design step 6, 03 P1-8, standalone Q17, Q28 | High | Conflicts | Clinical conflict table; sheet vs feed as a conflict; unresolved = unknown; open conflict blocks "ready"; steward for all, PI for own study; resolution "at date" | decided, open | WS-03.6 |
| MR-129 | owner "all history now", 03 P2-9, standalone Q2 | High | Back-fill | Chunked, resumable, memory-bounded load of all history (adapter holds the batch in memory, 4.9 GB at 15k) | decided (all history), open | WS-03.7 |
| MR-130 | design step 11, standalone Q13 | Medium | HAPI | Out of the nightly path; gate in CI | open | WS-03.8 |
| MR-131 | design step 5 | Medium | Notes | NOTE and NOTE_NLP rows; publish writes to the CDM (closes FR-REP-02) | open | WS-03.5 |
| MR-132 | catalogue §6, Q1..Q10 | High | Catalogue | 469 items, 164 phenotypes, 26 scores delivered as data; no OMOP concept ids yet; JLAC10 unverified; LOINC lookups pending; Phenotype Library needs ICD-10-CM translation; 15 instruments' copyright unverified | delivered as data; loading **open** | WS-04.1..WS-04.5 |
| MR-133 | catalogue §2.3, §7; holistic 02 P0-11 | High | Licences (data) | WashU CDR licence; DAS28 permission (ePROVIDE); HAQ-DI permission (Stanford); HDS-R statement; HemOnc patient-care clause; MDS-UPDRS per study; SNOMED quote; MEDIS 使用許諾; JSLM/JLAC; jRCT; WHOCC ATC; JCOG CTCAE | open (owner and Aimedics actions) | WS-15.3 |
| MR-134 | design step 8, catalogue §3 | Medium | Scores | Score definitions as data; nine formula kinds; four without a worked example | open | WS-04.3 |
| MR-135 | owner, design 7a, standalone §3, 03 P2-2 | High | Vectors | pgvector `halfvec(1024)`, HNSW, note chunks with offsets; patient vector; backups include vectors; bge-m3 default, Qwen3-Embedding test | decided, open | WS-05.3, WS-02.6 |
| MR-136 | owner, design 7b, standalone §4 | High | Profile | Wiki page written by the judge at night, every sentence cited, abstain under 95 %; nobody edits; twin JSON; versions kept 10 years; study patients first | decided, open | WS-05.1, WS-05.2 |
| MR-137 | owner, design 2.7.2 | High | Annotations | Signed structured entry = confirmed data; free text = note; exclusion by annotation listed | decided, open | WS-05.4 |
| MR-138 | owner, design 7c, standalone §4.4, holistic 02 §6.4 | High | Setpoints and gap | Setpoints as numbers with a "check" mark; gap rules approved by a specialty PI; 7/10 switch-on plus rolling ≥ 70 % over 50 hits and a negative-control set; model-proposed rules only after the injection suite | decided, open | WS-05.5 |
| MR-139 | owner, catalogue Q10, standalone §4.7 | High | Patients like me | Structured items first, embedding re-rank, every match explained; scope by role | decided, open | WS-05.3 |
| MR-140 | standalone §0.2, Q39 | Medium | Tiers | The 5090 tier cannot host the narrative | docs; tier table | WS-05.1 |
| MR-141 | owner, standalone Q41 | Medium | GPU cost | One paid profile cost test on the PRO 6000 VM | decided, open | WS-02.6 |
| MR-142 | owner, design §3, 03 P2-5, holistic 02 P2-1 | High | Consortium | Shared code-map registry hosted at CGMH, Aimedics ships releases; counts as signed files; de-identified profiles k=5, ±180 days, no quotes, no vectors; first export dual review | decided, open (registry work starts now) | WS-09.1..WS-09.3 |
| MR-143 | design step 13, 03 P2-4 | High | De-identification | No k-anonymity, date shift, project pseudonyms, export manifest, re-identification test | open | WS-09.3 |
| MR-144 | design Q1, standalone Q17, owner | Medium | Sheets | PI sheet trusted as coded with source shown; disagreement is a conflict | decided, open | WS-03.6 |
| MR-145 | standalone Q16 | Medium | Point in time | `recorded_at` / `valid_to` on CDM rows for "facts as of" | open | WS-03.4 |
| MR-146 | standalone Q12 | Low | Trial facts | Mirrored read-only into OMOP for consortium queries | open (P2) | WS-09.2 |

### 2.7 EDC prefill and trial records

| MR | Sources | Sev | Area | Finding, short | Status | Plan |
| --- | --- | --- | --- | --- | --- | --- |
| MR-147 | owner (EDC), M5, S1, holistic 02 §5.7, Q5 | Blocker (owner frame) | EDC prefill | Model drafts eCRF values with citations; CRC confirms each; REDCap API; CDISC ODM import for others; file or copy-assist where no import; CDASH; no RPA; GAMP 5 CSV, full audit trail, ER/ES and Part 11-style controls | decided, open (the old FR-EDC design exists; nothing on master) | WS-07.1..WS-07.4, WS-12 |
| MR-148 | full review §6, holistic 01 Q5, holistic 02 Q5 | High | eCRF of record | Are the built-in forms a worklist or a record? | **resolved by the owner's EDC decision**: TrialBox is in the trial-data chain for prefilled values; built-in forms stay a worklist unless an IIT asks (see §3) | WS-07.4 |
| MR-149 | ICH E6(R3) matrix, S1 | High | E-signature | No name, meaning, re-authentication on approval; no record lock; no reason for change | open | WS-07.4 |
| MR-150 | holistic 01 §2 row 7, M9 | Medium | Consent record | Approved version list; explainer vs assistant; LAR/代諾者; witness; signature order; thinking time | open | WS-07.3 |
| MR-151 | owner | Medium | Randomisation | Not in TrialBox | decided; record "randomised on date by IWRS" as a step only | WS-07.2 |
| MR-152 | owner | Medium | Inputs only | Dispensing dates on the timeline; dated indexed ISF bundle; invoice-ready monthly activity report | decided, open | WS-08.3 |
| MR-153 | owner | Medium | Patient messaging | Printed reminder card and calendar file now; opt-in messages later via hospital SMS or LINE | decided, open | WS-06.11 |

### 2.8 Data operations, derived data, import and export

| MR | Sources | Sev | Area | Finding, short | Status | Plan |
| --- | --- | --- | --- | --- | --- | --- |
| MR-154 | owner (data-ops console, stats page) | High | Data ops | Steward console: feeds, loads, mapping coverage, conflicts, DQ, missingness per source per month; stats page | decided, open | WS-08.1, WS-08.2 |
| MR-155 | owner (derived data), design step 8, 03 §1.3 | Medium | Derived | Scores and derived values as data, versioned, recomputed forward, provenance | decided, open | WS-04.3, WS-08.2 |
| MR-156 | owner (import/export), D-129, D-134 | Medium | Import/export | ODM 1.3.2, REDCap CSV, XLSX, FHIR QR exist; ODM import, repeating groups, audit CSV, OMOP export, screening log in the sponsor's layout missing | partly done | WS-08.3 |
| MR-157 | owner (compression) | Medium | Storage | Compression and retention of notes, snapshots, backups, vectors; 2 TB sizing against all history | open, pending the data-flow review | WS-08.7 |
| MR-158 | baseline open data decisions 1..7, D-140 "not done" | Medium | Reference data | Full CT.gov pack not built; MEDIS application; JSLM; jRCT; ATC names; JCOG; NHI service codes; TW parsers on real files; wizard default offline (done D-140) | partly done | WS-08.8, WS-15.3 |
| MR-159 | baseline corrections 1, 3, 5 | Medium | JP masters | "Licensed" is the wrong word; WHO-only ICD-10 as a family; NHIA 2014 to 2023 map | open | WS-10.3, WS-11.2 |
| MR-160 | 03 §1.1 | Medium | Incremental | Lake rebuilt whole nightly; no row-level change log | open | WS-03.7 |

### 2.9 Site onboarding, procurement, legal, evidence

| MR | Sources | Sev | Area | Finding, short | Status | Plan |
| --- | --- | --- | --- | --- | --- | --- |
| MR-161 | owner frame | Blocker | Feeds | Neither site's data feed is known | open: site survey first | WS-10.2, WS-11.2 |
| MR-162 | owner frame, D-124, standalone Q40 | Blocker | Boxes | Not bought; 4 to 8 weeks; 2 TB and 128 GB confirmed per site; RTX PRO 6000 | open | WS-14.1, WS-10.1, WS-11.1 |
| MR-163 | owner frame, field research S5, M1 | Blocker | Hospital IT | Not engaged; device form, network segment, 2 to 6 weeks | open | WS-10.1, WS-11.1 |
| MR-164 | owner frame, holistic 02 P0-5, §5.5 | Blocker | Contracts | Platform licence, DPA (APPI 委託, PDPA Art. 27, EMR 辦法), 責任分界 sheet, insurance | open | WS-15.1, WS-15.2 |
| MR-165 | owner frame, holistic 02 P0-4, M4, M8 | Blocker | IRB | Approved at one site; the other's submission, opt-out notice, legal-basis memo | open | WS-10.1 or WS-11.1 |
| MR-166 | holistic 02 P0-2, P1-2, Q1, standalone Q36 | High | Regulatory view | Counsel review of TB-DS-16; written 該当性 view and TFDA inquiry before clinician layers | open | WS-15.4 |
| MR-167 | holistic 02 P0-6, M3, M7, M11 | High | Incident response | Plan with APPI 3–5 d / 30–60 d, PDPA 72 h, 資安法 1 h clocks; tabletop | open | WS-13.5 |
| MR-168 | holistic 02 P0-8, §5.6, owner (62304 light) | High | QMS | QMS-lite; 62304-shaped records for the profile module per release | decided, open | WS-12.1 |
| MR-169 | holistic 02 P0-9, §6.1, owner | High | Evidence | Study A protocol: retrospective accuracy at CGMH, PPV ≥ 0.75, wrong exclusion ≤ 2 %, opt-out/waiver; pre-registered | decided, open | WS-16.1 |
| MR-170 | holistic 02 P0-12, §5.1, P1-1 | High | Support | Named contact, hours, ticket channel, RMA; 開示書 + SLA; pentest | open | WS-17.4, WS-13.8, WS-15.5 |
| MR-171 | holistic 02 P0-7, P1-3, layer 2 §3.2 | High | Licences (code) | Gemma 4 licence file unread; vLLM/CUDA image redistribution on media; LGPL notices; THIRD_PARTY_NOTICES | open | WS-15.3 |

### 2.10 Data-flow lifecycle (from the data-flow review)

The data-flow review's P2 items (OMOP core, partitions, pgvector) move into the pilot because the owner wants OMOP, profiles and pgvector within the three months; they are listed here with the plan items that already hold them.

| MR | Sources | Sev | Area | Finding, short | Status | Plan |
| --- | --- | --- | --- | --- | --- | --- |
| MR-172 | DF P0-1, §0.1 item 3 | High | Deltas | Deletes do not propagate on a `--since` night; a record removed at the source stays in every later snapshot | open | WS-03.7 |
| MR-173 | DF P0-2, §3.2 | High | Validation | A failing validation still moves `CURRENT`; no quarantine (`HELD`) | open | WS-08.1 |
| MR-174 | DF P0-3, §7.3, R-20, R-21, R-45 | High | Backup | gzip -9 inside the `.tbbak` at 10–30 MB/s; whole lake volume in the backup (about 1 TB at 50k); zstd -3 multi-threaded, hashes from the stream, off-box nightly, age alert | open | WS-08.6 |
| MR-175 | DF P0-4, §6.6, MR-035 | High | Opt-out worker | Opt-out reaches S0 only; facts, chunks, vectors, pid map, snapshots, exports untouched; worker v1 with a consent register and tombstones | open | WS-06.8 |
| MR-176 | DF P0-5, §4.2, MR-016 | High | Derived | CRP assumed mg/L (JP and TW report mg/dL); no JSN eGFR; no same-visit rule; no worked-example tests; `derived_unit` and `derived_missing_input` reasons | open | WS-04.3 |
| MR-177 | DF P0-6, §7.1 | High | Vectors in snapshots | `document_chunk.embedding` copied into every snapshot file: about 700 GB at 50k with 39 snapshots; move embeddings out | open | WS-05.3, WS-08.7 |
| MR-178 | DF P0-7, MR-083 | Medium | Lake schema | No version in `lake_meta`; no `.sha256` sidecars | open | WS-03.1 |
| MR-179 | DF P0-8, §5.2 | Medium | Export ledger | No queryable record of what left the box, to whom, under which approval, at which identifier level | open | WS-08.3 |
| MR-180 | DF P1-9, MR-126, MR-128 | High | Record status | `tb_fact_status`, `tb_fact_provenance`, `tb_conflict` on the lake first, then OMOP; the screening view admits coded, confirmed, signed, derived with no open conflict | open | WS-03.2, WS-03.6 |
| MR-181 | DF P1-10, §3.2, MR-154 | High | Data-ops console | `dataops` schema: batch registry with a state machine, record status, flow ledger, consent register; the `/data-ops` page and `/api/v1/data/*` | open | WS-08.1 |
| MR-182 | DF P1-11, §3.3, MR-154 | Medium | Statistics page | Per source, department and year; coverage, completeness, timeliness, conformance, proposed vs confirmed, conflicts, derived, screening activity; k = 5 with rounding outside the study team | open | WS-08.2 |
| MR-183 | DF P1-12, FR-REP-02, R-79 | High | Snapshots | Publish rebuilds the current snapshot under the same id during a run; snapshot ids with job pinning; batched publish on `main`; pruning skips referenced snapshots | open | WS-03.7 |
| MR-184 | DF P1-13, §7.3 | Medium | PITR | No WAL archive or incremental backup; pgBackRest zstd, `wal_compression`, `default_toast_compression = lz4` | open | WS-08.6 |
| MR-185 | DF P1-14, MR-134, MR-155 | High | Derived framework | Definitions as data with units, windows, spread, versions pinned in the ruleset manifest, stored rows with provenance, recompute batch; derived-vs-documented conflicts | open | WS-04.3, WS-08.2 |
| MR-186 | DF P1-15, §5.3 | Medium | EXTRACT | "Prepare a database" for a PI: three de-identification profiles, data dictionary, manifest, k-check, steward release | open | WS-08.3 |
| MR-187 | DF P1-16, MR-127 | Medium | Terminology versions | Rulesets pin the terminology release; a "recompile needed" flag | open | WS-03.3 |
| MR-188 | DF P1-18, §6.7 | Medium | Retention | Retention per data kind as a table (originals 1 year after decision; undecided proposed facts 180 days; trace store 7 days in PRODUCTION; pid map crypto-shred at erasure) | open | WS-08.7 |
| MR-189 | DF P2-20, P2-24, §7.2 | Medium | Partitions and streaming | Partition by year; warm Parquet tier; incremental export by changed persons; streaming ingest with `COPY` for the back-fill | open (moved into the pilot for the 50k scale) | WS-03.7 |
| MR-190 | DF §0.2, §7.4, owner's question | Medium | Compression | CPU zstd (level 1–3, multi-threaded) everywhere; no GPU compression (nvCOMP proprietary; the card is spoken for) | decided by evidence; open | WS-08.7 |

### 2.11 User journeys end to end (from the journey review)

`docs/reviews/2026-11-09-user-journeys-e2e.md`: 37 journey runs, 2,247 steps, 48 fail, 308 warn, 50.4 % statement coverage, on master **without** wave 1b. J-11, J-12 and J-13 are the items D-143 fixes on the branch (PI reveal, excluded list, SAE acknowledgement); they are marked *branch* and are confirmed at the merge (WS-01.1). The rest is **wave 1c**: J-01 to J-04, J-07, J-26 and J-27 before G1; the others before feature complete.

| MR | Sources | Sev | Area | Finding, short | Status | Plan |
| --- | --- | --- | --- | --- | --- | --- |
| MR-191 | J-01 | High | Jobs | Who may request a job is decided by the sender's mailbox in `settings.yaml`, not by the console role; an account made on `/ops/users` is refused every FEAS/SCREEN with raw JSON | open | WS-01.7 |
| MR-192 | J-02 | High | Jobs | The 20-jobs-a-day limit per sender counts FEAS, SCREEN, CASE and consent of the one coordinator mailbox | open | WS-01.7 |
| MR-193 | J-03, J-04, J-05, S-19 | High | Roles | Viewer and CRO reach patient-level `/api/v1` lists and the screening log (200 where the page is 403); every job page, the registry, `/audit`, protocol, request, feasibility, set-up pages open to every role | open (D-143 masks identifiers but does not scope these routes) | WS-01.7, WS-06.1 |
| MR-194 | J-06 | Medium | Scope | Site set-up pages and APIs are per site, not per study; a study-scoped coordinator sees every site fact and chart | open (steward role decides) | WS-06.1 |
| MR-195 | J-07 | High | Charts | A PDF chart with CJK text fails with a NUL-byte 500; shown as "could not reach this information" | open | WS-01.7 |
| MR-196 | J-08 | Medium | Templates | The codes template download is a 500 (`out["name"]` on a list) | open | WS-01.7 |
| MR-197 | J-09, J-14, R-61, R-43 | Medium | Admin screens | No console screen for first-run set-up, backups and their status, update and rollback, logs, secrets, the network sheet; Reset password and Disable act at once | open (confirmations on branch, D-143) | WS-08.5, WS-14.7 |
| MR-198 | J-10, MR-027 | High | Steward | No steward role or screens; data actions are `coordinator` only; the admin cannot attach REDCap or import a dictionary | open | WS-06.1, WS-08.1 |
| MR-199 | J-11 | Medium | PI reveal | No Reveal control for the investigator | branch (D-143) | WS-01.1 |
| MR-200 | J-12 | High | Excluded | No list of the box's exclusions; `?list=excluded` falls back to `all` | branch (D-143, per-study page); the week-list filter **check at merge** | WS-01.1 |
| MR-201 | J-13 | Medium | SAE | Banner shows only "ongoing" AEs | branch (D-143) | WS-01.1 |
| MR-202 | J-15, J-16 | Low | Readiness | Readiness and site patients pages take 2 to 4 s on five patients; the readiness API answers for the first study, the page for the chosen one | open | WS-08.4 |
| MR-203 | J-17, J-20, J-25, R-112 | Low | Wording | Raw actor id `console:crc` on ja/zh-TW pages; the request box answers in English and names a study the site lacks; phone dates | open | WS-01.5 |
| MR-204 | J-18 | Low | Users page | Invalid `pattern` regular expression under Chrome's `v` flag | open | WS-01.7 |
| MR-205 | J-19 | Medium | Approval | After approval the per-criterion ticks and site labels are no longer viewable; the job page does not say "approved by … on …" | open | WS-01.5, WS-07.4 |
| MR-206 | J-21, J-22 | Low | PI pages | Mark bar below the fold on the patient page on a phone; feasibility page without site labels or Refresh for the PI | open | WS-01.5 |
| MR-207 | J-23 | Low | Notices | Admin notice settings explain nothing (digest time, who gets N1 and N2) | open | WS-01.5 |
| MR-208 | J-24 | Medium | Sources | No spreadsheet or FHIR bundle as a study source on the sources page; no data-quality page | open | WS-08.1, WS-08.4 |
| MR-209 | J-26 | High | SCREEN scope | A new study's SCREEN fails "No practitioners in scope"; nothing in the console sets `scopes.screen` (it lives in a YAML on disk) | open | WS-01.7 |
| MR-210 | J-27 | Medium | Approval | The PI cannot tick criteria (the tick is the requester's) and the page does not say why | open | WS-01.7 |
| MR-211 | J-28, J-29 | Medium | New study | REDCap connection registration is on the admin page with no link from the study set-up; a new study has no forms and nothing says the step is needed before the first outcome | open | WS-01.5 |
| MR-212 | journey §5, §6 | Medium | Coverage | `dataplat`, `deliverables`, `testbench`, `tracestore` at 0 %; `matching` 45 %; five orchestrator routes with no UI; 65 console routes unreached by any journey | open (test strategy) | WS-12.4, WS-01.4 |

Items closed before this head and not in the register: plan-review findings 1 to 10 (D-112 to D-122), design/code F-01 to F-32 except F-04 consent-swallow (D-127), F-05 (D-130), F-10 (D-130), F-18 (MR-044), F-31 (MR-045); UX top 15 except 11 (empty states), 13 (feasibility card first, MR-103), 14 (REDCap wizard, done D-133 T4), 15 (per-page help, MR-104); standards review F-02 (per-service secrets, D-138), F-03/F-16 (reveal bound to the list, D-127/D-130), F-05 (console in production, D-127).

## 3. Contradictions and how each is resolved

The owner decisions document wins. Where it is silent, the later review wins over the earlier, and the safer reading wins over the looser.

| # | Topic | Who says what | Resolution |
| --- | --- | --- | --- |
| C-01 | Clinician view of setpoints and gaps | Owner (morning): clinicians see them labelled research use. Standalone review Q4 and holistic 02 Q1: not until a written device view. Owner (revised, after holistic 02): restricted, study-referral context only, numbers, no disease name, switch off, until a written PMDA/MHLW and TFDA view | **Owner's revised decision.** Record, timeline, phenotype and eligibility layers to clinicians from the start; setpoints and gaps behind a flag per holistic 02 Q1(b). The device-qualification view is prepared (WS-15.4). |
| C-02 | History depth | Standalone review Q2: 5 years. Owner: all history now | **All history.** The plan adds the chunked, resumable back-fill (MR-129) and the storage sizing (MR-157) that make it possible, and loads by year, newest first, so screening runs on the last 5 years while older years load. |
| C-03 | Steward reads free text | Standalone Q6: only when needed. Owner: at any time, audited | **Any time, audited, 10 years.** The DPIA states the basis (the steward is the hospital's accountable person). |
| C-04 | PI reveal of chart numbers | D-133: investigators may not reveal. Owner D-143: PI sees everything for own studies | **D-143.** Viewer and CRO stay masked; N1 mail carries no chart number (D-143's point for the owner to confirm; recorded as question Q-07 in TB-PLAN-05). |
| C-05 | IRB approval before Approach | Holistic 01 Q6 recommends a hard gate. Owner: warning, not a gate; overrides logged | **Warning, logged.** The plan adds a monthly report of overrides for the steward and the office. |
| C-06 | Treating doctor's referral answer | Holistic 01 Q2 recommends all three routes. Owner: at the first site the CRC records it; mail buttons and doctor accounts later | **CRC records it at the first sites.** Mail with answer buttons is P1 (WS-18.1). |
| C-07 | Delegation log of record | Holistic 01 Q4: a copy. Owner: the office's signed log is the record; TrialBox holds a copy that grants rights; compared monthly | **Copy, compared monthly.** The comparison report is a plan item (WS-06.2). |
| C-08 | eCRF of record | Full review §6 and holistic 02 Q5: worklist only for the pilot. Owner: EDC prefill, CRC confirms, through REDCap API or ODM; GAMP 5, full audit, ER/ES and Part 11-style controls inside 3 months | **Both are true and compatible.** TrialBox becomes part of the trial-data chain for *prefilled values* (controls apply to the prefill path). The built-in forms stay a worklist and say so on the page unless a site declares them its record (owner question Q-05). |
| C-09 | Randomisation, drug accountability, TMF, invoicing | Holistic 01 "never". Owner: randomisation not in TrialBox; the others inputs only | **Owner.** Inputs only: dispensing dates on the timeline, ISF document bundle, invoice-ready activity report (WS-08.3). |
| C-10 | Patient messaging | Holistic 01 "never from the box". Owner: printed card and calendar file now; opt-in messages later through the hospital's SMS or LINE | **Owner.** Card and `.ics` in WS-06.11; messages are P1/P2 with ethics-approved templates. |
| C-11 | Break-glass second person | Design §4.2: steward confirms a PI, admin confirms a steward. Standalone Q10: steward or administrator only, on a rota. Owner: a second person on the steward/admin rota | **Owner.** Rota named in the DSA; admin confirming sees no patient data. |
| C-12 | SNOMED | Baseline open data: do not buy. Component layer 1 and 2: a fee of US$1,954 per hospital per system per year; write the no-licence decision down. Holistic 02 Q6: Aimedics holds for the product. Owner: ask for a licence; Aimedics holds it for the product, the consortium lead if the consortium buys; get a quote now; ICD-10-CM plus the WHO bridge until then | **Owner.** v1 ships `*_concept_id = 0` for conditions with source concepts filled; the quote is a W1 action (WS-15.3); the decision is recorded in DECISIONS with the fee. |
| C-13 | Connection pool | Full review R-13 and holistic 03 P0-9: `psycopg_pool`. D-142: reopen, not a pool, because the stores rely on one serialised connection and the package is not in the images | **D-142 for the pilot.** The pool is reconsidered in the service merge (MR-093) after go-live. `/healthz` touches the DB either way. |
| C-14 | HL7 v2 library | Layer 1: hl7apy. Layer 2 (measured): hl7apy 166 msg/s, python-hl7 3,817, home-grown 345,000; python-hl7 or the 60-line fix | **Layer 2.** The 60-line fix with hypothesis round-trips first (ingest speed matters on millions of files); python-hl7 as the oracle in tests. |
| C-15 | OCR language | Layer 1: `lang` per site. Layer 2: PP-OCRv5 covers zh-Hant, zh-Hans, ja, en in one model; CPU only; the 2.x API does not run on 3.x | **Layer 2.** One OCR module, CPU, PP-OCRv5 pinned, Tesseract fallback, NDLOCR-Lite evaluated for Japanese paper. |
| C-16 | Postgres image | Layer 1: pgvector/PGroonga with the profile work (rank 10). Layer 2: the image switch to Debian goes before any real data (REINDEX later) | **Layer 2.** WS-03.1 in W2, before any site data. |
| C-17 | Order of OMOP vs the P0 platform list | Owner: Wave 1 and G1 first; OMOP, catalogue and profile in parallel, merging after Wave 1. Holistic 03 Q1: P0 first, OMOP after, or parallel only with goldens done first. Standalone Q43: parallel by a second engineer | **Owner, with the holistic 03 condition.** Goldens (WS-03.1) and the flag mechanism (WS-01.4) land in W1–W2; OMOP work runs in parallel on branches and merges only after Wave 1 and G1 and with goldens identical. Agents are the second engineer. |
| C-18 | Cloud run cost | D-139: about 4.9 h, US$13.50 with FEAS-only re-run. D-141: about 8.9 h, US$24.3 with the scenario matrix and a 12 h cap; the owner allows parallel VMs and about US$50 with the profile and embedding tests | **Owner's budget.** G1 split across VMs; each capped and stopped; the profile cost test and the bge-m3 vs Qwen3 test are part of the same window. |
| C-19 | MEDIS, JLAC10, YJ "licensed" | D-122, D-137: licensed loader. Baseline open data: free downloads; a vendor needs 使用許諾 to distribute | **Baseline.** Call them standard masters; apply to MEDIS now; ship the loader and the message "free to download"; ship the 薬価 list now. |
| C-20 | WHO-only ICD-10 codes | D-137: used only where also an ICD-10-CM code. Baseline correction 3: treat as inside its ICD-10-CM category family (D-113 rule) | **Baseline.** Safer recall without WHO text; still fail-closed. |
| C-21 | Byte-identical re-runs | ARCHITECTURE §9 and acceptance step 6: identical. D-116 and R-41: about 9 % judge drift with the pair | **Both true on their paths.** FEAS and the structured part byte-identical; note judgements to the recorded agreement rate; replay from recorded answers (P1-17) makes the claim true later. The documents say so now. |
| C-22 | Container `ipc: host` | Review 03: replace with `shm_size`. Review 05: keep on vLLM only | **Measure first** (vLLM with `shm_size` on the PRO 6000 during G1); keep on vLLM only if it fails. |
| C-23 | 疑い field | Review 02: PRB-13. Review 06: PPR-01 flag | **Verified in D-142:** PRB-13 (JHSD 表 0005). |
| C-24 | Cause of the 2026-11-09 VM auth failure | Review 01: a bare access token. Review 05: a failed service-account refresh | **Unknown; fix is the same (D-141):** cloud cap, the VM's own credential, fresh auth per call. |
| C-25 | Severity of MFA | Review 03 Blocker, review 06 Medium, standards review High | **Blocker** (MHLW GL 7.0 from FY2027 is the first-site window; hospital IT questionnaires ask first). |
| C-26 | "Ask treating doctor" | USER_GUIDE §3 and BD-19 say it exists. Code: three i18n strings, not in `MARKS` | **Code is the truth.** The referral workflow is built in WS-06.3; the user guide is corrected when it lands. |
| C-27 | Site data arriving as a "feed" vs charts one by one | Plan v4 §3 assumes feeds. D-132 and holistic 01: a site may start with pasted charts; the box must say what it cannot do | **Both paths stay.** The site survey decides which path each site starts on; feasibility counts need a bulk source and the page says so (built, D-135). |
| C-28 | Pilot dates in the design set | TB-DS-15 and TB-DS-04 §12 plan JP IQ/OQ 2027-01-12 and CGMH 2027-02-15 with 1 × and 2 × RTX 5090 boxes, 256 GB RAM, 8 to 16 TB | **Superseded.** The owner's frame is both sites in parallel within 3 months on RTX PRO 6000 boxes with 2 TB and 128 GB. TB-PLAN-05 §4 holds the schedule; the design set stays a record. |

## 4. Coverage check: every owner intent, and where the plan holds it

Each row is an intent the owner stated in the decisions document or in an earlier request. "Plan" names the TB-PLAN-05 workstream item. Nothing here is dropped; "later" means a dated P1/P2 item exists in WS-18.

| # | Owner intent | Source | Status today | Plan |
| --- | --- | --- | --- | --- |
| I-01 | Full clinical repository now, trials first; Anamnesis layers later on the same base | decisions "Scope" | decided | WS-03 (all) |
| I-02 | Structured facts for every patient in the feed; written profiles for participating departments | "Who is in" | decided | WS-03.4, WS-05.1 |
| I-03 | All history now, structured and notes | "History" | decided | WS-03.7, WS-08.7 |
| I-04 | Data steward: named hospital staff; Aimedics never holds patient data | "Data steward" | decided; no role in code | WS-06.1, WS-13.6 |
| I-05 | Steward reads all free text at any time; every view audited, kept 10 years | "Steward and notes" | decided | WS-06.1, WS-13.4 |
| I-06 | PI sees everything for own studies' patients, chart numbers included | "PI", D-143 | branch | WS-01.1 (merge), WS-06.1 |
| I-07 | Clinician role from the start; own patients = 24 months or 90 days ahead; privacy office may add ward inpatients | "Treating physicians" | decided | WS-06.1 |
| I-08 | Profile access by role; every view audited 10 years | "Profile access" | decided | WS-05.1, WS-06.1 |
| I-09 | Monitors: SDV on enrolled subjects, cited items only | "Monitors" | decided | WS-07.6 |
| I-10 | Break-glass with a second person, time-limited, audited | "Break-glass" | decided | WS-06.6 |
| I-11 | Screen the entire database; candidates may belong to anyone | "Whole-hospital screening" | screening runs on the whole feed today; candidate view missing | WS-06.5 |
| I-12 | Sub-PI by delegation log, ticked tasks; only the PI approves criteria and signs off; every action records who | "Sub-investigators" | decided | WS-06.2 |
| I-13 | Candidate view: everything needed to decide; logged with study and purpose; rate-limited | "Candidate view" | decided | WS-06.5 |
| I-14 | Referral: treating physician asked first; agree / decline with reason / discuss; PI contacts only after agreement; counted in the screening log | "Referral" | decided | WS-06.3 |
| I-15 | Treating physician may be unknown: suggest, type from directory, "arranged outside TrialBox", department contact; never stalls; route recorded | "Referral target" | decided | WS-06.3, WS-06.4 |
| I-16 | CRC records the doctor's answer at the first site; mail buttons and doctor accounts later | "Site operations" | decided | WS-06.3; WS-18.1 (P1) |
| I-17 | IRB approval and ICF version: warning, not a gate; overrides logged | "Site operations" | decided | WS-06.10 |
| I-18 | Delegation log: office's signed log is the record; TrialBox copy grants rights with training dates; compared monthly | "Site operations" | decided | WS-06.2, WS-17.3 |
| I-19 | Opt-out kept by the office; recorded in TrialBox; removed from screening, profiles, vectors, exports; logged | "Site operations" | decided | WS-06.8 |
| I-20 | EDC prefill, CRC confirms; REDCap API; ODM for other EDCs; file or copy-assist; no RPA; CDASH; GAMP 5, audit trail, ER/ES Part 11-style | "Site operations" | decided | WS-07.1 to WS-07.4, WS-12 |
| I-21 | Randomisation not in TrialBox | "Site operations" | decided | WS-07.2 (a recorded step only) |
| I-22 | Drug accountability, TMF, invoicing: inputs only (dispensing dates, ISF bundle, invoice-ready report) | "Site operations" | decided | WS-08.3 |
| I-23 | Patient messaging: printed card and calendar file now; opt-in messages later via hospital SMS or LINE | "Site operations" | decided | WS-06.11; WS-18.1 |
| I-24 | OMOP CDM v5.4 in Postgres; FHIR for exchange; lake exported from OMOP with the same table names; counts identical | "Core" | decided | WS-03.4, WS-03.5 |
| I-25 | pgvector in the same Postgres | "Vectors" | decided | WS-05.3 |
| I-26 | All subspecialties, one generic model; items mapped through the catalogue (LOINC, OMOP, Phenotype Library, CDISC QRS, NIH CDE); first templates rheumatology, neurology, oncology, nephrology/GIM | "Specialties" | catalogue delivered as data | WS-04 |
| I-27 | PI spreadsheets trusted as coded, source shown; disagreement is a conflict, unknown until resolved | "PI spreadsheets", "Sheet vs feed" | decided | WS-03.6 |
| I-28 | Conflicts: steward for all, PI for own study; unresolved = unknown, never excludes | "Conflicts" | decided | WS-03.6 |
| I-29 | Local code maps by the steward; a specialty PI confirms the important ones | "Local code maps" | decided (D-135 maps by coordinator) | WS-03.3, WS-08.1 |
| I-30 | SNOMED: ask for a licence; Aimedics holds it; quote now; ICD-10-CM plus WHO bridge until then | "SNOMED CT" | decided | WS-15.3 |
| I-31 | Consortium: counts and de-identified profiles may leave under IRB and DSA; defaults k=5, ±180 days, no quotes, no vectors; signed count files; registry at CGMH, shipped by Aimedics; registry work starts now | "Consortium" | decided | WS-09.1 to WS-09.3 |
| I-32 | Profile: wiki page by the model, every sentence cited and verified; physician annotations beside it; twin JSON; pgvector | "Form" | decided | WS-05.1, WS-05.2, WS-05.4 |
| I-33 | v1 layers: cited record, timeline, phenotype, eligibility, setpoints, gap finder, similar patients | "v1 layers" | decided | WS-05.1, WS-05.5, WS-05.3 |
| I-34 | Clinician view of setpoints and gaps restricted until a written regulatory view; study-referral context, numbers only, flag off; PIs and stewards see them labelled research use; forecasts out | "SaMD and clinicians" (revised) | decided | WS-05.6, WS-15.4 |
| I-35 | Annotations: signed structured = confirmed; free text = note; nothing excludes silently; "excluded and why" page | "Physician annotations" | decided; excluded page on branch | WS-05.4, WS-06.7 |
| I-36 | Narrative: judge model at night, site language, English on request; nobody edits; abstain under 95 % cited | "Narrative" | decided | WS-05.1 |
| I-37 | Freshness: facts and twin within minutes; narrative nightly or on request | "Freshness" | decided | WS-05.2, WS-03.7 |
| I-38 | First build: study patients first, nights only | "First build" | decided | WS-05.1 |
| I-39 | Gap rules: specialty PI approves; live after 7 of 10 confirmed; model-proposed rules only after the injection and false-positive suite | "Gap rules" | decided | WS-05.5, WS-02.4 |
| I-40 | Patients like me: structured first, embeddings re-rank, every match explained | "Patients like me" | decided | WS-05.3 |
| I-41 | Embeddings: bge-m3 default; Qwen3-Embedding-0.6B tested on ja/zh-TW; all note types across history; vectors in backups | "Embeddings" | decided | WS-02.6, WS-05.3, WS-08.6 |
| I-42 | GPU cost: one paid profile cost test on the PRO 6000 VM, stopped and verified | "GPU cost", "GPU" | decided | WS-02.6 |
| I-43 | Hardware: 2 TB and 128 GB per box, confirmed per site | "Hardware and order" | decided | WS-14.1, WS-10.1, WS-11.1 |
| I-44 | Order: Wave 1 and G1 first; OMOP, catalogue, profile in parallel, merge after Wave 1 | "Hardware and order" | decided | TB-PLAN-05 §4 |
| I-45 | Accepted recommendations: profile versions 10 years; open conflict blocks "ready"; setpoints as numbers with a check mark, never alerts; counts as signed files; first export dual review; registry now | "Accepted as recommended" | decided | WS-05.2, WS-03.6, WS-05.5, WS-09.2, WS-09.3, WS-09.1 |
| I-46 | Light IEC 62304 records for the profile module from now on | "Regulatory and commercial" | decided | WS-12.1 |
| I-47 | Business model: platform licence; per-study activation fee; no per-patient fees | "Regulatory and commercial" | decided | WS-15.1 |
| I-48 | Study A protocol now: retrospective at CGMH, PPV ≥ 0.75, wrong exclusion ≤ 2 %, opt-out/waiver; no claims before | "Regulatory and commercial" | decided | WS-16.1 |
| I-49 | Plan frame "both, linked": requirement → risk → test under IEC 62304 light, ISO 14971, GAMP 5, ER/ES | "Master plan and pilot" | this plan | TB-PLAN-05 §5 to §8, `25-traceability.csv` |
| I-50 | Both sites in parallel; agents build; Changfu and Makoto review; go-live within 3 months with real patients | "Master plan and pilot" | this plan | TB-PLAN-05 §4 |
| I-51 | Pilot scope: everything; build all, use all; GAMP 5 of EDC prefill inside 3 months | "Master plan and pilot" | this plan | WS-07, WS-12 |
| I-52 | Data feeds unknown: plan starts with a site survey | "Master plan and pilot" | this plan | WS-10.2, WS-11.2 |
| I-53 | Boxes not bought, IT not engaged, contracts not signed, one IRB missing | "Master plan and pilot" | this plan | TB-PLAN-05 §4.3 critical path |
| I-54 | G1 split across parallel VMs with the profile and embedding tests, about US$50, capped and stopped | "Master plan and pilot" | this plan | WS-02.1, WS-02.6 |
| I-55 | Building continues while the plan is written | "Master plan and pilot" | Wave 1a/1b on branch | WS-01.1 |
| I-56 | Offline CT.gov and reference data; both modes; wizard default offline; NOTICE page | D-140 | done (full pack build not run) | WS-08.8 |
| I-57 | SAE clocks (7/15 days JP and TW) with PI acknowledgement | D-143, owner | branch; site confirmation open | WS-10.6, WS-11.6 |
| I-58 | Chart numbers for the PI on pages; N1 mail without | D-143 | branch; confirm N1 rule | Q-07 |
| I-59 | Easy for novices; one plain vocabulary; phone; wizard; glossary | D-131 to D-133 | done, with the "left for later" list | WS-01.5, WS-17.2 |
| I-60 | Windows workstation with WSL2; fully offline installer; apps after the platform; every action through an API | D-125 | groundwork done (D-138); installer and hardening open | WS-14.1, WS-13.2 |
| I-61 | Hospital AD/LDAP or local accounts per site | D-126 | open (no LDAP code) | WS-13.1 |
| I-62 | Three kinds of study at the first sites: IIT, sponsor, observational | D-126 | lifecycle supports; sponsor EDC read missing | WS-07.5 |
| I-63 | Inputs for drug accountability, TMF, invoicing (restated) | owner | decided | WS-08.3 |
| I-64 | Data-ops console and stats page; derived data; import/export; compression | owner's brief for the data-flow review | review delivered; nothing built | WS-08.1, WS-08.2, WS-08.3, WS-08.7; §2.10 |
| I-67 | "Is compression needed, since we have a GPU (zstd)?" | owner's question to the data-flow review | answered: yes, CPU zstd; no GPU compression | WS-08.7, Q-18 |
| I-65 | Clinical item catalogue across subspecialties | owner's brief | delivered as data; loading open | WS-04 |
| I-66 | User-journey end-to-end with code tracing | owner's brief | review delivered; wave 1c defined | §2.11; WS-01.7, WS-12.4 |

## 5. What the reviews agree is good and must not be broken

The safety core (fail-closed code families, the two-model rule, the quote check, unknown never excludes, the canary gate, the one rule for proposed facts); pseudonyms at the door and the encrypted pid map; schema-first contracts; the audit chain's mechanics; signed bundles and the backup to a key the box cannot read; measured tiers; DECISIONS as an evidence-bearing log; the three-language, phone-first console and the walk that holds it; the data core's field-level conflict model; the screening log and enrolment report. Every plan item that touches these carries a golden test.

## 6. Placeholders for the three reviews still being written

Each will be folded into §2 and §4 when its file arrives. Until then TB-PLAN-05 holds a workstream for each with the acceptance criteria the owner already stated.

| Review | Expected file | What the register will take from it | Plan |
| --- | --- | --- | --- |
| User-journey end to end with code tracing | `docs/reviews/2026-11-09-user-journeys-e2e.md` | **arrived; folded in** (§2.11, MR-191 to MR-212); the 37 journeys become the PQ / UAT script | WS-12.4, WS-01.7 |
| Clinical item catalogue | `docs/reviews/2026-11-09-clinical-item-catalogue.md` | **arrived; folded in** (MR-132 to MR-134, MR-016, catalogue Q1 to Q10 in TB-PLAN-05 §13) | WS-04 |
| Data-flow lifecycle (inputs, authority, audit, derived data, data-ops console, stats page, import and export, compression) | `docs/reviews/2026-11-09-dataflow-lifecycle-review.md` | **arrived; folded in** (§2.10, MR-172 to MR-190; its 12 owner questions are in TB-PLAN-05 §13) | WS-08 (all), WS-03.2 |

## 7. Corrections this review makes to earlier records

| Record | Says | True | Plan |
| --- | --- | --- | --- |
| Full system review §1 and D-139 | Gate G1 costs about US$13.50 | D-141 estimates US$24.3 with the scenario matrix; the owner's frame allows about US$50 with the profile and embedding tests across parallel VMs | WS-02.1 |
| Holistic 01 §0 | "Ask treating doctor" exists only as strings | still true at this head; the referral object is WS-06.3 | WS-06.3 |
| Holistic 03 §1.5 | Admin can view PHI by default | still true; D-143 widened PI access, not the admin's removal | WS-06.1 |
| TB-DS-15 §1 and TB-DS-04 §12 | JP IQ/OQ in January 2027, CGMH mid-February, 5090 boxes | superseded by the owner's frame (both parallel, PRO 6000, 3 months) | TB-PLAN-05 §4 |
| D-122, D-137 | MEDIS, JLAC10, YJ are "licensed" | free downloads; vendor distribution needs MEDIS 使用許諾 | WS-15.3 |
| Standalone review §0.2 | The owner's SNOMED decision is "ask" | the owner decided: ask for a licence, quote now, Aimedics holds it | WS-15.3 |
| Owner decisions, "SaMD and clinicians" (morning text) | Clinicians see setpoints and gaps labelled | revised the same day: restricted until a written view | WS-05.6 |
