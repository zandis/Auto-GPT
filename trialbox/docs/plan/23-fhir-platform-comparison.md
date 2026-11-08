# TB-REC-02 FHIR platform comparison: HAPI FHIR vs Medplum

| Field | Value |
| --- | --- |
| Document ID | TB-REC-02 |
| Version | 1.0 |
| Date | 2026-11-08 |
| Owner | Changfu Kuo (Aimedics) |
| Author | Claude for Aimedics |
| Status | Recommendation, measured; feeds TB-PLAN-03 §7 and step 9 |
| Basis | Both servers run side by side in the build container (4 vCPU, 16 GB RAM, Docker 29.9), same data, same loader |

## 1. Answer

**Keep HAPI FHIR as the one FHIR store, and build trial conduct on it.** Do not adopt the Medplum server.

On our data, HAPI did everything trial conduct needs (Questionnaire, QuestionnaireResponse, CarePlan, Appointment, rest-hook Subscriptions, Japanese and Chinese search). It loaded 2.3 times faster. It is also the only option that runs the CQL our SCREEN engine and equivalence gate depend on.

Medplum's real strengths are its built-in login, its access policies and its React kit. They don't outweigh the costs: no CQL, UUID-only ids, a third runtime (Node and Redis), stricter validation that rejects some of our resources, an English-only UI kit, and a subscription path that did not deliver in our test. TrialBox already has its own roles and SSO.

Sections 6 and 7 below record what Medplum would cost if it were chosen anyway, and how to revisit the decision later.

## 2. What was compared

| | HAPI FHIR | Medplum |
| --- | --- | --- |
| Version | `hapiproject/hapi:v8.12.0-2`, the TrialBox pin, with CR (CQL) on | `medplum/medplum-server:5.2.15`, the current release, 2026-11-06 |
| Stack | Java (Spring) + PostgreSQL 16 | Node 24 + PostgreSQL 16 + Redis 7 |
| Licence | Apache-2.0 | Apache-2.0. Paid: Medplum-hosted cloud, support and enterprise contracts ([open-source page](https://www.medplum.com/open-source), [GitHub](https://github.com/medplum/medplum)) |
| arm64 image (Spark tier) | Yes (multi-arch manifest) | Yes (multi-arch manifest) |

**Data loaded into both:**
- The real public site: 268 patients, 1,314 resources, Japanese and English text.
- The synthetic hospital slice used by `e2e_simple`: 5,000 patients and 154,931 resources across 15 types (109 MB NDJSON).
- Both were loaded with the same loader, using the TrialBox method: 500-entry PUT transaction bundles, 4 workers.

## 3. Measured results

| Measure | HAPI 8.12 | Medplum 5.2.15 | Note |
| --- | --- | --- | --- |
| Bulk load, 154,931 resources | **294.5 s (526/s)** | 685.7 s (226/s) | Medplum is about 2.3× slower, CPU-bound in one Node process |
| Bulk load, public site (1,314) | 8.8 s | 12.2 s | |
| Database size after both sets | 1,063 MB | 970 MB | Similar |
| Server memory after load | 1.96 GB (JVM, `-Xmx3g`) | 0.77 GB Node + 0.26 GB Redis | Plus PostgreSQL (0.6 GB / 0.3 GB) |
| Restart to healthy | 45 s | 8 s (first boot with migrations: 65 s) | |
| Installed images | 1.06 GB + PG 0.42 GB | 0.85 GB + PG 0.42 GB + Redis 0.06 GB | Both fine offline once pulled |
| `Condition?code=M06.9` count | 11 ms, 3,317 | 26 ms, 3,317 | Same answer |
| `Observation?code=4548-4&value-quantity=gt6.5` | 14 ms, 3,075 | 16 ms, 3,075 | Same answer |
| `Encounter?date=ge2026-01-01` | 9 ms, **34,338** | 45 ms, **19,088** | **Different answers.** Our encounters have a start and no end. HAPI follows the spec and treats an open end as ongoing; Medplum does not. |
| One patient's `$everything` | 130 ms, 76 resources | 693 ms, 71 | Different compartment contents |
| Japanese/Chinese names (`name=山田`, `family=陳`, `name=ヤマダ`, `name:contains=太郎`, `given=大文`) | All found | All found | Both handle CJK, kana and kanji |
| Questionnaire (JA text) → QuestionnaireResponse → search | Works | Works | |
| CarePlan with a visit window, Appointment | Works | Works, but stricter: an Appointment participant without actor/type is refused (invariant app-1) | Our adapter output would need fixing for Medplum |
| Client ids like `0001bf7e4e1b46edeb9873f91c098792` | Accepted | **Refused ("Invalid id")**; only UUIDs are accepted | Every id and reference must be rewritten |
| CQL `Library/$evaluate`, `$cql` | Yes. A test library ran in 0.3 s per patient once warm | **None** | SCREEN's default engine and the CQL↔SQL equivalence gate need CQL |
| Rest-hook Subscription (`Appointment?status=booked`) | **Delivered** to the listener within 2 s, with retries | Created as `active`, **nothing delivered** in 3 tries, in both the super-admin project and a new project | Medplum's dispatch jobs ran but matched no subscription. Not resolved within the time box; it may be configuration, but it is unproven |
| Login, roles, SSO | None built in (interceptors only); TrialBox has its own (PR #13) | OAuth2/OIDC, SMART, access policies, external OIDC built in | Medplum's clearest advantage |
| Air-gapped behaviour | No outbound calls seen | Creating a user failed with "fetch failed" (it tried an outside service with no network) | Needs a check or a patch for hospital networks |
| UI kit | None | `@medplum/react` 5.2.15 (Apache-2.0, React 18/19 + Mantine 8): QuestionnaireForm, QuestionnaireBuilder, Scheduler, CalendarInput, SearchControl, ResourceTable, PatientTimeline, PlanDefinitionBuilder | It only talks to a Medplum server, has no translation layer (labels are English), and our console is server-rendered Python |

## 4. Extrapolation to 500,000 patients (one site)

These are linear estimates from the 5,000-patient slice, about 15.5 M resources. They have not been measured.

| | HAPI | Medplum |
| --- | --- | --- |
| Database | ≈ 100 GB | ≈ 95 GB |
| Full reload at today's rate (4 vCPU, 4 workers) | ≈ 8 h | ≈ 19 h |
| Server memory | 6–8 GB heap, plus PostgreSQL 16 GB shared buffers | 2–4 GB Node (more with replicas), plus Redis 1 GB, plus PostgreSQL 16 GB |

**Finding for both platforms:** a full nightly reload of 500k patients does not fit the night window on either. The adapter must move to **delta loads** (changed resources only, plus the existing ledger deletes) before a 500k site goes live. This belongs in step 7 (data path) of TB-PLAN-03.

## 5. Scoring for TrialBox

| Criterion (weight) | HAPI | Medplum |
| --- | --- | --- |
| Screening: CQL, terminology, equivalence gate (30) | 5 | 1 |
| Trial conduct: forms, visits, events (20) | 4 | 4 (stronger UI kit, but subscriptions unproven here) |
| Fits the current build, migration cost (15) | 5 | 2 |
| Auth and roles (10) | 2 (ours) | 5 |
| Throughput at 500k (10) | 4 | 2 |
| Japanese/Chinese (5) | 5 | 4 (search yes, UI kit English only) |
| On-prem, offline, arm64 (5) | 5 | 3 |
| Licence (5) | 5 | 5 |
| **Weighted total (of 5)** | **4.5** | **2.6** |

**How to build trial conduct on HAPI** (step 9):
- Visits are Appointment and CarePlan resources, with windows taken from REDCap events and arms.
- Visit outcomes are QuestionnaireResponse resources.
- An HAPI rest-hook Subscription feeds the orchestrator for "visit due" and "overdue".
- The screens are our own server-rendered pages in three languages, reusing the role-home design.

## 6. If Medplum were chosen anyway: migration size

Today 23 non-test modules (about 8,300 lines) and 6 test modules touch the FHIR store.

| Work | Size |
| --- | --- |
| Replace CQL: run the 12 CQL libraries with `cql-execution` in a Node sidecar, or drop CQL and make SQL the only engine. Rework the equivalence gate either way | 2–3 builder-weeks |
| Rewrite ids to UUIDs in the adapter, the lake joins and the ledger, with a migration of existing snapshots | 3–5 days |
| Fix adapter output to pass Medplum invariants (for example Appointment app-1); re-run all fixtures | 2–3 days |
| Map TrialBox roles and SSO onto Medplum ProjectMembership and AccessPolicy | 1 week |
| Prove rest-hook delivery and air-gapped user creation; patch or configure | 2–4 days |
| Use `@medplum/react` for CRC visit screens: a React front end next to the Python console, plus a JA/zh-TW translation layer | 2 builder-weeks |
| **Total** | **≈ 6–8 builder-weeks**, with no screening gain |

## 7. When to look again

Reconsider Medplum only if a site requires SMART-on-FHIR apps or patient-facing logins. If that happens, run Medplum next to TrialBox as an optional auth and forms front end that syncs to HAPI, never as a second store of record.

## 8. Commands used (reproducible)

```sh
# scratch dir; compose file with both stacks
docker pull medplum/medplum-server:5.2.15 hapiproject/hapi:v8.12.0-2 postgres:16-alpine redis:7-alpine
docker compose -p fhircmp up -d          # medplum: command ["env"], MEDPLUM_* env; hapi: CR + rest-hook on
python mptoken.py > token.txt            # /auth/login -> /oauth2/token (PKCE plain)
python load.py hapi    <ndjson-dir>      # 500-entry PUT transactions, 4 workers, TrialBox load order
python load.py medplum <ndjson-dir>      # same, ids and references rewritten to UUID form
python feat.py                           # searches, CJK, Questionnaire/QR, CarePlan, Appointment, Subscription
curl -X POST localhost:8090/fhir/\$cql -d @cql.json   # inline CQL on one patient
docker stats --no-stream; psql ... pg_database_size  # memory and size
```

The scripts and raw outputs were kept in the session scratch directory. The containers were removed afterwards.

## Change history

| Seq | Version | Date | Author | Change |
| --- | --- | --- | --- | --- |
| 1 | 1.0 | 2026-11-08 | Claude for Aimedics | First issue; measured head-to-head on 154,931 synthetic + 1,314 public resources. |
