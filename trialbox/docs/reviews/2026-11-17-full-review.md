# The full review: architecture, security, regulatory fit, code, AI governance, operations (lane R, 2026-11-17)

**Reader:** the owner, the integrator, and the lanes that take the cards at the end.

**What was reviewed:** master `8f5d429c` (train 66). Six areas, each by its own sub-session, merged and ranked here:
I architecture, J security and privacy, K regulatory and quality-system fit, L code quality and engineering
procedure, M AI and model governance, N operations at a hospital. The companion report,
`2026-11-17-journey-and-simplicity.md` (areas A to H), covers the screens, the users, the data's journey, the EDC
and install. The plan that follows from both is `docs/plan/44-plan-8-2026-11-17.md`.

**How to read it.**

- This is an engineer's reading of each standard, not legal or regulatory advice.
- Each control is judged with one of four words. **MEETS**: evidence was found. **PARTLY**: something named is
  missing. **DOES NOT MEET**: evidence shows the control is not met. **NO EVIDENCE FOUND**: we looked where named and
  found nothing; it may exist elsewhere. The last two are different and are kept apart.
- Standards are named with a clause or control. Where a clause number could not be checked from memory it says so.
  No text of a standard is quoted.
- "Seen" means seen in the running demo; "read" means read in code or a document; "counted" means a command was run.
- The owner has ruled no development gates. Every regulatory and quality gap below is **work for the pilot's
  validation**, not a blocker to coding.
- Earlier reviews were read first. Each area says what they found that is closed and what is still open.

---

## One-page summary

**The controls in the product are stronger than the evidence about them.** That sentence fits all six areas.

| Area | The strong part | The weak part |
| --- | --- | --- |
| I Architecture | A careful perimeter: one published port, one path to the model, one writer of the audit chain, a database role per service, checksummed migrations, an update that snapshots and rolls back | Inside, a "distributed monolith": services import each other's stores; 510 declared settings; one box with no standby; recovery targets written but never measured; no capacity statement |
| J Security and privacy | Per-service tokens, a tested role matrix, TOTP and OIDC, a signed hash-chained audit, digest-pinned images, signed updates, encrypted backups. Most earlier High findings are fixed | 94 vulnerability waivers lapse together on **2026-12-10** with no named owner; erasure is owed in 28 stores; the sign-in throttle can lock a whole hospital behind the proxy; prompt injection is unmeasured on the real model |
| K Regulatory fit | The signed-Send path into the EDC is close to what 21 CFR Part 11 asks; a well-shaped set of quality documents | **Nothing is executed**: no release record, no qualification record for a real model, no IQ/OQ/PQ record, a traceability table with "planned" on all 273 rows |
| L Code and procedure | Clean by every automatic measure: strict typing, lint with security rules, 8,337 tests, no mock library, a coverage ratchet | The console's pages live in one function of 1,986 lines that grows at every review; text keys silently override each other; the mutation score of the safety core is unrecorded since 66.6 %; 1.94 million words of documents and no single list of open findings |
| M AI governance | The model's role is well fenced and mostly enforced by code: one model path, pinned weights, a prompt registry, a rule that both models must agree and that a missing record never excludes | No real model pair has a qualification record; the compiler, the highest-risk use, has no accuracy gate; shadow mode has no code; nothing watches the model in use |
| N Operations | Watchdog, health mail, log retention, a scrubbed support bundle, a patch policy, an incident plan, a restore-drill command | Three different answers to "is the box healthy", and they disagreed in the demo; 13 of 14 named drills do not exist; one support person for two countries |

**The ten findings that matter most, in order:**

1. **Nothing is executed as validation evidence** (K-1). The hospital's validation group and a sponsor's auditor
   stop at the first question. Most of the pack can be *generated* from what the repository already has.
2. **No real model has a passing qualification record, and neither installer has finished on real hardware**
   (K-6, M-1). These are already the plan's proof runs; they are the head of the queue.
3. **94 waivers lapse on 2026-12-10 with no named owner** (J-1). On that day every image gate fails and no update
   bundle can be built. It is 23 days away.
4. **Erasure is not complete** (J-2): 28 stores still keep an opted-out patient's data, and "data may not be used"
   on a withdrawal is read by nothing (J-3, K-4).
5. **Two write paths into the EDC with different safeguards** (K-3): the signed Send, and an administrator's
   one-click tool write with no signature.
6. **The audit event is not in the transaction of the change it records** (I-M3, K-5), except on the EDC signing
   path, which does it right.
7. **No measured recovery, no standby, no capacity statement** (I-1, I-4).
8. **The tested and demonstrated shape is not the deployed shape** (I-2): most tests and the demo run every
   service in one process.
9. **"Is the box healthy" has three answers** (N-1), and on a box with no mail relay nobody is told.
10. **The process makes paper faster than product** (L-5): about 950 decisions, 23 plans, 44 reviews with about
    1,580 finding rows, and one stale problem log of 49 rows.

**What to stop** is in each area's last part and gathered in plan 8, section 5.

---

## I. Architecture

### The architecture as it is (from `deploy/docker-compose.yml` and the imports)

```
 clinic PC --https--> [caddy :443]* --> CONSOLE :8090   (the only published port)
                      [authelia]*        |  opens 16+ stores itself; its own timers
                                         |  (morning mail, REDCap pull, health mail)
        +--------------------------------+-------------------------------+
        v                                v                               v
  ORCHESTRATOR :8010 <-- jobs --   MAIL-GATEWAY :8015 --> IMAP/SMTP    GATEWAY :8020
  4 worker threads, 2 schedulers;                                      (registry, PHI guard, traces)
  in-process libraries: matching,                                        | internal model network
  datacore, edc, edc_backend,                                            v
  rc_bridge, sitesetup, ...                                        MODEL-GUARD --> judge, verifier (GPU)
        |           |            |                                 (or the stub on CPU)
        v           v            v
   ADAPTER :8016  CRITERIA-    DOC-PARSER :8011
   (JVM validator) COMPILER :8012 (JVM, CQL)
        |  +--------> FHIR-STORE (HAPI, Java)
        v
   LAKE :8013 (DuckDB) --> EMBED-SERVICE :8014

 every Python service --> DB (PostgreSQL 16: about 27 schemas, one role per service)
 every service -- audit.append() --> audit.journal --> AUDIT-WRITER --> hash-chain files --> signed heads
 host: systemd timers (watchdog, operations, egress, weights), cron backup, nftables egress filter
 * optional overlays
```

Only 12 of the 27 folders under `services/` are processes. Fifteen are libraries or test stand-ins loaded inside
them (`llm_stub` and `rc_sim` are stand-ins that ship under `services/`).

### Against a reference architecture for an on-premise clinical system

| Element (standard) | Verdict | Evidence, and what is missing |
| --- | --- | --- |
| Trust zones, single ingress (ISO/IEC 27001:2022 A.8.20, A.8.22; NIST SP 800-53 SC-7) | PARTLY | Networks meet it (`deploy/docker-compose.yml:487-510`; `deploy/network.sh`). Missing: data zones. The `objects-data` volume is read-write in five containers, including the two that parse outside files |
| Integration boundary for hospital data | PARTLY | One ingest boundary, the adapter, with four batch sources and a validator. The adapter and the lake share one folder under a file lock |
| System-of-record database, migrations, point-in-time recovery (ISO A.8.13) | PARTLY | Migrations meet it (`libs/tb_common/db.py:25-45`; `tools/trialbox/prestart.py:143-150`). Point-in-time recovery is built but off by default (`docker-compose.yml:72-75`) |
| Append-only audit store with outside anchoring (21 CFR 11.10(e); ISO A.8.15) | MEETS | One writer, a journal table, a hash chain, signed heads on hospital folders (`tools/trialbox/anchors.py`). One gap: I-M3 |
| Identity delegated to the hospital (ISO A.5.16, A.8.5) | PARTLY | An OIDC client exists (`services/console/oidc.py`), off by default. The shipped route puts Authelia inside the box, which the owner has declined |
| Job queue with retry and dead-letter | PARTLY | Jobs have attempts, a lease and a restart limit (`services/orchestrator/db.py:147-151`); mail has an outbox. No dead-letter view; three in-memory schedulers |
| Model-serving boundary, versioned artefacts (GAMP 5 2nd ed., the AI/ML appendix; number to be checked) | MEETS | The gateway is the only model path; images by digest; `models/registry.yaml` pins revision and manifest |
| High availability or a documented cold standby (ISO A.8.14; NIST CP-10) | PARTLY | One box by design. The standby is "a loaner box within five working days", marked "default until the owner answers" (`docs/runbook/22-…md:25-29`) |
| A validation environment identical to production (ISO A.8.31; 21 CFR 11.10(a)) | PARTLY | `TB_ENV=VALIDATION`, an acceptance compose file, a box rehearsal in CI. But most tests and the demo run in one process (I-2) |
| Time sync and one time zone (ISO A.8.17) | MEETS | `tools/trialbox/doctor.py:1088-1105`; `TB_TZ` is mandatory |
| Documented RPO and RTO (ISO A.5.30; NIST CP-2) | PARTLY | Targets written (24 h, 4 h, 5 working days); "No restore has been measured yet" |
| One source of configuration (ISO A.8.9) | DOES NOT MEET | Counted: 510 declared `TB_*` settings (366 on 2026-11-12), 739 distinct names across the code, plus `settings.yaml`, `deploy/.env`, the site folder and 13 compose files. `site_params.yaml` has no reader |
| Observability (ISO A.8.16) | PARTLY | Health endpoints, a watchdog, `/metrics`, health mail. NO EVIDENCE FOUND of one request or job id carried across services |

### When a part is down (read from code; none was run)

| Down | What users see | Data at risk | Recovery |
| --- | --- | --- | --- |
| Console | No screens; no morning mail or health mail (they are console timers). Night jobs still run | None | Watchdog restart. At boot it waits for three other services: if one is sick, the one page that shows health never appears |
| Database | Everything stops | Up to 24 h, unless log archiving was switched on | The watchdog only reports. Restore by runbook 22 |
| Orchestrator | Pages that call it show an error; no night | None: jobs are queued again with kept answers | Watchdog restart; a lease prevents a double run |
| Model server or gateway | Screening waits, then stops with a named outage. Coded-data steps need no model | None | Restart; the job resumes |
| Mail gateway | No mail | None: an outbox | Restart; the outbox drains |
| The box | Everything | Since the last off-box backup | A loaner box (unconfirmed) |

### What scales and what does not

| Figure (all synthetic) | Value | Source |
| --- | --- | --- |
| Ingest to a published snapshot, 50,000 patients | 805 s | `docs/reviews/2026-11-12-deep-review/07-performance-scale-robustness.md:265` |
| One study screened, 50,000 patients, one card | 6,704 model calls in 8,584 s | `docs/plan/measurements/g1-2026-11-11/README.md:20-33` |
| Audit chain write rate | 53 to 70 events a second | the same review, ARCH-011 |
| 500,000 patients | An estimate only: 20 to 70 h for one full night | the same review, lines 267-268 |
| Restore time, RPO, RTO | Not measured | runbook 22 |

The repository says of itself: "No figure the repo quotes today was measured on what ships"
(`docs/plan/measurements/validation-reset-2026-11-14.md`). **Scales acceptably:** coded-data filtering, the
adapter's streamed load, model calls (bounded by the card, resumable). **Does not scale yet:** the night as a full
reload (T-694, T-702, T-703 are open); one database connection per store under one lock; four worker threads; fixed
clock times for the night's steps.

### Findings

**High**

- **I-1. No standby and no measured recovery.** Runbook 22. A hospital's IT reviewer asks for RPO and RTO with
  evidence before the first patient record goes in. *Fix:* one timed restore on the 50,000 set; log archiving on by
  default when a backup share is set; the owner's answer on the loaner box.
- **I-2. The tested and demonstrated shape is not the deployed one.** Counted: 57 test files use the in-process
  lake, 13 the HTTP one; `tools/demo.py:351-435` runs every service in one process. The demo is honest about screens
  and logic and silent about what failed on the GPU run (timeouts, roles, memory caps). *Fix:* one nightly compose
  run of the 17-step walk; the compose suite, not the in-process one, is the pilot's gate.
- **I-3. Process boundaries are not code or data boundaries** (ARCH-005 of 2026-11-12, still open). Counted: the
  orchestrator imports `matching` 29 times, `datacore` 21, and the console's own stores 3
  (`services/orchestrator/grants.py:44,75,87`). *Fix:* do not split further. Declare three layers; add an
  import-rule test with today's count frozen and ratchet it down (`tools/boundary_check.py` exists).
- **I-4. No capacity statement.** T-667 is unwritten. *Fix:* a one-page provisional statement at the size measured.

**Medium**

- **I-M1. No single source of configuration** (ARCH-013, worse). Stale examples:
  `deploy/settings.example.yaml:30` names models that `models/registry.yaml` does not ship. *Fix:* class the 510
  into site (about 30, written by the wizard), tuning and developer; hide the last two from a site.
- **I-M2. Three in-memory schedulers and four host timers order the night by the clock** (ARCH-003, open).
  *Fix:* one scheduler; night steps chained on completion.
- **I-M3. An audit event is not in the transaction of its change** (ARCH-010, open).
  `libs/tb_common/audit_writer.py:171` opens its own connection. A crash between the two loses the event
  (21 CFR 11.10(e)). *Fix:* for the dozen regulated writes, append in the same transaction, as the EDC signing
  path already does.
- **I-M4. The console waits for three services before it can show the box's health** (ARCH-018, open).
- **I-M5. Seven deployment forms for one product** (ARCH-017, open): 13 compose files, Kubernetes, two-device,
  Windows, 20 cloud scripts. *Fix:* name the pilot's form; mark the rest "not maintained".
- **I-M6. The FHIR store is loaded every night and read only at compile time** (ARCH-015, open). Plan v7.3
  section 3.1 already says "off the box"; it is still on. It costs 5 GB and a JVM.

**Low**

- I-L1. Product code imports the developers' `tools/` tree in five places, and the REDCap simulator in one.
- I-L2. Test stand-ins live in `services/`.

**Closed since the last review (verified):** job attempts, lease and restart limit; the unused step engine deleted;
migrations run before services start; roles for the profile and tuned schemas.

---

## J. Security and privacy

Standard: OWASP ASVS 4.0.3 at Level 2, and the OWASP Top 10 (2021). The demo was probed lightly and without harm.
No secret or key file was read.

### ASVS 4.0.3, by chapter

| Chapter | Verdict | The controls that fail or lack evidence |
| --- | --- | --- |
| V1 Architecture, threat model | PARTLY | V1.1.2: no current threat model found (looked in `docs/security/`, `docs/validation/`). A callee not listed accepts every service's token (`libs/tb_common/service_auth.py:201`). No ASVS checklist file |
| V2 Authentication | PARTLY | V2.2.1: behind the proxy every browser shares one address, so five bad guesses for one name lock it for everyone (`deploy/docker-compose.yml:364`; the identity overlay sets no trusted proxy). Passwords: 12 characters, history, breached list, scrypt (`services/console/auth.py:63-68`) |
| V3 Session management | PARTLY | Seen: the cookie is HttpOnly and SameSite=strict with a new token at sign-in. Cookie removals are sent without the original flags. An older session survives a new sign-in (read in the 2026-11-13 review; not re-verified) |
| V4 Access control | MEETS, one gap | Seen: viewer, CRO and administrator are refused the pages the matrix denies them. Gap: opening a break-glass grant asks no fresh password or code |
| V5 Validation, injection | PARTLY | A strict content policy; a select-only lake guard. The prompt-injection suite runs against the stub only: NO EVIDENCE FOUND of a run on the real model pair (looked in `eval/`, `docs/validation/`) |
| V6 Cryptography at rest | PARTLY | Keys are sealed (TPM, shares or a passphrase). V6.4.1: database, mail and cloud passwords are still environment variables. No record found of the key ceremony on a real host |
| V7 Errors and logging | PARTLY | V7.1.1: the audit mask is by key name (`libs/tb_common/audit.py:95-103`), so a chart number in free text passes. Heads are signed once a night |
| V8 Data protection | PARTLY | V8.3: erasure owed in 28 stores. No code reads the withdrawal's data-use answer |
| V9 Communications | PARTLY | TLS at the proxy with HSTS. Links inside the box are plain HTTP (acceptable for one host; say so). NO EVIDENCE FOUND of a TLS scan record |
| V10 Integrity, supply chain | PARTLY | Signed bundles, locked images and packages, an SBOM, scans in CI. 94 waivers with no named owner lapse together |
| V11 Business logic | PARTLY | A second person for protected accounts. Break-glass commits before its audit event |
| V12 Files | MEETS | Uploads refused in demo mode; the document parser is isolated (read) |
| V13 API | PARTLY | The trace store's reads trust unsigned headers (`services/tracestore/app.py:3`) |
| V14 Configuration | PARTLY | Seen: good headers. `/healthz` answers without sign-in with the environment and a schema name. Only one container drops capabilities |

### OWASP Top 10 (2021)

| Item | Verdict | Note |
| --- | --- | --- |
| A01 Broken access control | MEETS, residue | Enforced on the server (seen) |
| A02 Cryptographic failures | PARTLY | Passwords in environment variables |
| A03 Injection | PARTLY | SQL and HTML sound; the model path unmeasured on the real pair |
| A04 Insecure design | PARTLY | No current threat model |
| A05 Security misconfiguration | PARTLY | Container hardening on one service |
| A06 Vulnerable components | PARTLY | Strong gates; the waivers |
| A07 Authentication failures | PARTLY | The throttle counts the proxy's address |
| A08 Integrity failures | MEETS | Signed bundles with rollback refusal; pinned actions |
| A09 Logging and monitoring | PARTLY | Identifiers in free text; nightly signing |
| A10 Server-side request forgery | NO EVIDENCE FOUND | No specific review found; default-deny egress bounds it |

### Earlier High and Critical findings: their state today

| Finding | Source | State on `8f5d429c` |
| --- | --- | --- |
| The support bundle leaks passwords | 2026-11-13 | **Fixed** (`tools/support_bundle.py`, with a test) |
| An administrator alone makes a patient-data account | 2026-11-13 | **Fixed** in the matrix (a second person confirms) |
| The proxy and identity images never scanned | 2026-11-13 | **Fixed** |
| Any service writes `audit.*` names | 2026-11-13 | **Fixed** |
| The orchestrator trusts a name in the request body | 2026-11-13 | **Fixed** |
| No second factor; header sign-on; no TLS; one shared secret | 2026-11-08 | **Fixed** |
| Waivers lapse with no owner | 2026-11-13 | **Still open, larger**: 94 entries (81 then) |
| The throttle counts the proxy's address | 2026-11-13 | **Still open** |
| Heads signed nightly only | 2026-11-13 | **Still open** |
| Chart numbers in audit text | 2026-11-13 | **Partly** |
| Erasure reaches few stores | 2026-11-13 | **Partly**: 87 cleared, 28 owed |
| DNS as a leak path; no capability drop | 2026-11-08 | **Still open** |
| The password-zip mail path | 2026-11-08 | **Partly**: a sign-in link is the default; the old path still ships |

### Privacy duties (as an engineer reads Taiwan's PDPA and Japan's APPI for a system a hospital runs)

| Duty | Verdict | Evidence and gap |
| --- | --- | --- |
| Purpose limitation | PARTLY | Data classes, study scope, aggregate-only roles. The withdrawal's answer is unused |
| Access logging | PARTLY | Reveal, break-glass and sign-in are chained events; the audit pages are for the steward and privacy office only |
| A patient's access request | PARTLY | A one-patient audit report exists. NO EVIDENCE FOUND of an end-to-end procedure for the privacy office |
| Erasure and opt-out | DOES NOT MEET (yet) | 28 owed: backups, the FHIR store, the encrypted identity, lake snapshots |
| Retention | MEETS | Country defaults; audit 10 years (`docs/security/06-audit-retention-updates.md`) |
| Breach notification support | PARTLY | An incident plan exists as a draft; no tabletop record |
| No cross-border transfer | MEETS | Default-deny egress. The egress test needs root and no CI job runs it; DNS is open |

### Findings

**High**

- **J-1. 94 waivers lapse on 2026-12-10 with no named owner** (`deploy/supply-chain-allowlist.yaml`: every row
  "security owner (to assign)"). The owner's yes for the model server's waiver is recorded in
  `docs/plan/38-handover-2026-11-15.md:80` as still to be typed in lane D's session. *Fix:* name one person;
  stagger the dates per image; open the re-qualification card this week.
- **J-2. Erasure is not complete** (`docs/validation/erasure-registry.md`: 28 owed). A hospital cannot tell a
  patient "your data are gone". *Fix, in this order:* the FHIR store, the identity's crypto-shred, lake snapshots,
  then a written rule for backups (they age out in N nights; a restore re-applies the opt-out list).
- **J-3. The withdrawal's data-use answer has no effect.** *Fix:* one flag on the participant, read by the lake
  scope, the EDC send and exports, with a test.
- **J-4. The sign-in throttle can lock a whole hospital.** *Fix:* a fixed proxy address in the overlay; `doctor`
  refuses a wildcard in production.
- **J-5. Prompt-injection resistance is unmeasured on the real model.** *Fix:* run the suite on the pilot's pair
  and file the result with the release record.

**Medium**

- J-M1. Audit text still carries identifiers. Mask inside the audit writer with the site's chart-number rule.
- J-M2. Signed heads once a night: up to a day of the newest events could be dropped by host root unseen. Sign hourly.
- J-M3. Break-glass: no fresh password, and committed before its audit event.
- J-M4. Containers lack capability drop and no-new-privileges (all but one).
- J-M5. Passwords and the key passphrase in environment variables; use secret files, as the model key does.
- J-M6. A callee not listed accepts any service's token; the trace store trusts unsigned headers. Default to refuse.
- J-M7. DNS left open as a slow leak path.
- J-M8. No ASVS self-assessment, no dynamic scan and no outside penetration test are on file.

**Low**

- J-L1. `/healthz` shows the environment and a schema name without sign-in (seen).
- J-L2. Cookie removals without the original flags (seen).
- J-L3. The password-zip mail path still ships. Remove it.

---

## K. Regulatory and quality-system fit

An engineer's reading. Every gap here is work for the pilot's validation.

### 21 CFR Part 11 (a closed system)

| Control | Verdict | Evidence, and what is missing |
| --- | --- | --- |
| 11.10(a) validation | DOES NOT MEET | No executed record: `docs/validation/release-records/` holds only a README; `eval/qualification/` holds no record; `25-traceability.csv` says "planned" on 273 of 273 rows |
| 11.10(b) accurate and complete copies | PARTLY | Exports exist. The ODM header has no software version and no exporter (`services/edc/odm.py:85`) |
| 11.10(c) protection over the retention period | PARTLY | A record inventory with keeper and retention; no restore record on real hardware |
| 11.10(d) access limited to authorised people | MEETS | The role matrix; account end dates |
| 11.10(e) audit trail | PARTLY | Hash-chained and append-only. The event is not in the change's transaction for general writes; no procedure for reviewing the trail was found |
| 11.10(f) sequence checks | MEETS | Decide, sign, send; a signed value is locked |
| 11.10(g) authority checks | PARTLY | The signed Send needs role, delegation and a fresh password. The tool path (`services/console/edc_door.py:118-133`) writes with administrator rights only |
| 11.10(h) device checks | PARTLY | Acceptable for a web system if the site's assessment says so |
| 11.10(i) training | PARTLY | User training is "read from the audit chain"; no export yet |
| 11.10(j) signature-accountability policy | NO EVIDENCE FOUND | A site document; a template is missing |
| 11.10(k) control of system documentation | PARTLY | Version history and lint; stale pages are not caught |
| 11.50 signature manifestation | PARTLY | Seen: name, role, time, meaning. The time is to the minute with no zone |
| 11.70 signature and record linking | MEETS | A keyed hash over signer, meaning, time and every value (`tests/unit/test_edc_signing_d281.py`) |
| 11.100 unique to one person | PARTLY | Unique names; identity proofing is the site's matter; no template |
| 11.200 two components | PARTLY | The password again, plus a code; sign-on by header cannot sign |
| 11.300 password controls | PARTLY | Length, history, breached list, lockout, idle limit. No alert on lockout |

Taiwan and Japan: the repository cites TFDA's 2024 guideline on computerised systems (D-859) and Japan's ER/ES
guideline. NO EVIDENCE FOUND of an assessment against Taiwan's Electronic Signatures Act or the ER/ES guideline.
**The TFDA pre-fill rule** named in plan 42 as a design card *has* been checked, in D-859
(`docs/validation/edc-data-flow.md`): the repository reads TrialBox's send as a "transfer" made after a person
decides and signs, so the rule against pre-filled fields does not apply. That is an interpretation with no outside
view behind it; it belongs with the questions for a regulatory consultant.

### ICH E6(R3): data governance (section 4 and Annex 1; clause numbers to be checked)

| Topic | Verdict | Evidence and gap |
| --- | --- | --- |
| Validation proportionate to risk | PARTLY | The validation plan rates each function; nothing is executed |
| Data life cycle and metadata | PARTLY | A solid record inventory (22 records); exports lack exporter and version |
| Audit trail and its review | PARTLY | Three trails per participant; only the steward opens the audit page |
| Attributable and contemporaneous | PARTLY | The actor comes from the verified session; the audit is not atomic with the change |
| Access control | MEETS | 75 actions, 7 roles, a matrix test |
| Investigator oversight and delegation | PARTLY | The delegation log is checked before signing; the PI has no path to participants (journey review A-4) |
| Essential records | PARTLY | Many are "page only"; no site-file bundle |
| Consent and withdrawal | DOES NOT MEET | The data-use answer is read by nothing |
| Safety reporting | PARTLY | An SAE register with clocks and receipts |
| Transfer to the EDC | PARTLY | D-859; the unsigned tool path is outside this control |

### GAMP 5 (second edition): the deliverables

| Deliverable | Exists? | Thin or solid |
| --- | --- | --- |
| Validation plan | `docs/plan/25-vmp.md` v1.1 | Solid as a plan. Its trigger is too narrow (K-2) |
| User requirements | 92 requirements in a superseded plan | Thin for what was built since (the EDC link, the data pages, cohorts) |
| Functional and design specification | `docs/validation/functional-spec.md` | Thin: an index of paths |
| Risk assessment | Two files on two scales, dated 7 and 12 November | Stale; no hazard for withdrawal or the tool write |
| Traceability matrix | `25-traceability.csv`, `tools/gen_traceability.py` | Thin: the status is hard-coded "planned" (line 131) |
| IQ, OQ, PQ | Tools only (`doctor`, the CI suite, `tools/acceptance.py`, runbook 06) | No protocol and no record |
| Model qualification | `tools/qualify.py` and runbook 11 | A solid tool; no passing record for real weights |
| Validation report | None | Missing |
| Change control | `docs/validation/change-control.md`, the decision registry | Solid design |
| Release record | A README only | Missing. Seen on `/about`: "Built from commit: not recorded" |
| Supplier assessment | `supplier-assessments.md`, `soup.csv` | Fair; none of the vendor itself |
| Problem log | `docs/validation/problems.csv`: 49 rows, 41 open | Stale since 2026-11-12 |

### IEC 62304 and ISO 14971 (as good practice; not claimed)

| Clause | Verdict | Evidence and gap |
| --- | --- | --- |
| 62304 4.3 safety classification | MEETS | The screening core is class B, the rest A |
| 5.1 development plan | MEETS | `docs/validation/development-plan.md` |
| 5.2 requirements | PARTLY | They live in a superseded plan |
| 5.5 to 5.7 verification | PARTLY | CI is real; no test report tied to a release |
| 5.8 release | DOES NOT MEET | No release record |
| 6 maintenance; 9 problem resolution | PARTLY | Written; the log is stale |
| 8 configuration management | PARTLY | Locks and digests are strong; the third-party list has 23 rows against 189 locked packages |
| 14971 hazard analysis | PARTLY | Good structure; dated 7 November |
| 14971 residual risk; post-production | NO EVIDENCE FOUND | No review after the build |

**Intended use.** The statement is in the footer of every page (seen) and supports the position that screening
support is not a medical device. Inconsistencies: `docs/plan/intended-use.md` is a draft of 9 November whose own
status rows are stale; it does not say that the product also keeps trial records, signs values and tracks SAE
clocks; "Estimated eligible" and "Count eligible patients" sit in the same screens as "does not decide whether a
patient is eligible"; no consultant's or authority's view is on file.

### The validation pack a hospital would ask for, in the order asked

| # | Document or record | State | Can it be generated from the repository? |
| --- | --- | --- | --- |
| 1 | System description, intended use, scope | Thin | Partly |
| 2 | Supplier assessment of the vendor | Thin | Yes |
| 3 | Validation plan for this site | Generic | A site copy by hand |
| 4 | Requirements and functional specification | Thin | Partly: the route list, the role matrix, the on-screen help |
| 5 | Risk assessment with controls | Thin, stale | No: it needs a person |
| 6 | Traceability matrix with test results | Thin | **Yes**: extend the generator to read the tagged commit's CI results |
| 7 | IQ record | Missing | **Yes**: `doctor`'s output, the release file, the key-ceremony record |
| 8 | OQ protocol and record | Missing | **Mostly**: CI results and the acceptance report |
| 9 | PQ, go-live acceptance | Missing | The tool exists; it needs the site's data and people |
| 10 | Model qualification record | Missing | **Yes**, once run on real weights |
| 11 | Part 11, ER/ES and Electronic Signatures Act assessment | Missing | The table above is a start |
| 12 | Release record with SBOM and open problems | Missing | **Yes** |
| 13 | Procedures: change, backup and restore, incident, audit-trail review | Thin | Audit-trail review is missing |
| 14 | Training records; validation summary | Missing | Training from the audit chain; the summary by hand |

### Findings

**High**

- **K-1. Nothing is executed.** *Fix:* one generator, a "release record" command, that writes the record from
  the tag, the CI results, the SBOM, the qualification record and the problem log. Generate; do not hand-write.
- **K-2. The validation plan's trigger is too narrow.** `docs/plan/25-vmp.md` section 0 brings formal records
  back only when pre-fill writes to a sponsor's EDC. But the box already holds essential records without pre-fill
  (the screening log, the SAE register, consent checks). *Fix:* one sentence: formal records return at the first
  real trial record of any kind.
- **K-3. An unsigned second write path into the EDC.** *Fix:* route it through the signed path, or leave the
  write tool off for the pilot (the journey review recommends the latter).
- **K-4. Withdrawal is not enforced.** *Fix:* block decide, sign, send and export for that participant.
- **K-5. The audit is not atomic for general writes.** *Fix:* the pattern the EDC signing path already uses.
- **K-6. No real-model qualification record; no installer finished on hardware.** Already known; it heads the
  pilot's validation.

**Medium**

- K-M1. The traceability status is hard-coded. Map each test id to a test and fill the status from results.
- K-M2. Exports lack exporter, time zone and software version; `/about` shows no commit.
- K-M3. Three trails and one reader. One per-participant report; let the PI read it for his own studies; write a
  review procedure.
- K-M4. The risk file is stale and split in two. One file; add hazards for withdrawal, the tool write and "Ask".
- K-M5. The problem log is stale. Make it the single register (L-5).
- K-M6. The intended-use paper is stale.

**Closed since earlier reviews:** the false Part 11 claim in the ODM file; the signature lock; keyed linking;
append-only trail tables; a second factor at signing; the intended-use statement in the footer; the clock check.

---

## L. Code quality and engineering procedure

### Figures

| Metric | Value | Source |
| --- | --- | --- |
| Product code (services and libraries) | About 157,000 lines; the console 40,770, of which 13,744 are text strings | counted |
| Tools | 228 files, 94,037 lines | counted |
| Tests | 943 files, 8,337 test functions: unit 7,157; console 959; integration 120; platform 32; e2e 21; property 17 | counted |
| Longest functions | `create_app` 1,986 lines; `home.register` 1,301; `team.register` 1,082. 31 functions over 200 lines | a syntax-tree script |
| The same on 2026-11-12 | 1,728; 1,252; 943. 24 over 200 | `docs/reviews/2026-11-12-deep-review/03-code-quality-se.md` |
| `except Exception` in product code | 271; one bare `except` | counted |
| `# fmt: skip` in product code | 1,341 | counted |
| TODO or FIXME in product code | 0 | counted |
| Decision or card numbers cited in code | 5,134 lines; 186 in `console/app.py` | counted |
| Lint | Ruff with security rules; all size and complexity rules off; strict typing over code and tests | `pyproject.toml` |
| Lint on the console | Clean, 0.08 s | run in this review |
| Coverage baseline | 81.6 % line, 74.8 % branch; the ratchet fails on a drop over half a point | `tools/coverage_baseline.json` |
| A safety-core outlier | `criteria_compiler/equivalence/gate.py`: 26.8 % line, 0 % branch | the same file |
| Mutation score of the safety core | 66.6 % on 2026-11-11; target 90 %, floor 60 %; no later figure is stored | `tools/mutation.toml:5-9` |
| Text keys | 43 modules, 3,086 keys, equal in three languages; 2,109 keys defined more than once, 15 with different English text | a script |
| CI | 8 workflows, 33 jobs; a full run is 118 to 182 runner-minutes; 682 runs in one day | `docs/plan/43-ci-and-train-etiquette.md:4` |
| Documents | 1,060 Markdown files, 1.94 million words | counted |
| Decisions | 684 files plus 270 log entries (about 950) | counted |
| Plans; reviews | 23 numbered plan files; 44 review entries with about 1,580 finding rows | counted |
| Problem log | 49 rows, 41 open, untouched since 2026-11-12 | `docs/validation/problems.csv` |

Not re-checked today: branch protection, CI run history and minutes per pull request (no GitHub calls were made
for this area; the figures are from plan 43 and the review of 2026-11-12).

### ISO/IEC 25010: maintainability

| Sub-characteristic | Verdict | Evidence |
| --- | --- | --- |
| Modularity | PARTLY | Separate packages with typed contracts. Console routes are closures inside five functions of 650 to 1,986 lines; product code imports `tools/` |
| Reusability | PARTLY | A shared library, 94 % covered. Text copied across modules; six demo scripts seed overlapping data |
| Analysability | PARTLY | Strict typing, docstrings, no TODOs. 5,134 lines cite a number a reader must look up among 950 |
| Modifiability | DOES NOT MEET | `create_app` grew 1,518, then 1,728, then 1,986 lines over three reviews. A text change can be silently undone by a later module |
| Testability | PARTLY | 8,337 tests on a real database, property tests, goldens that need a reason. Closures cannot be tested alone; the mutation score is unknown |

### What a new engineer meets on day one

A repository whose root is another project; TrialBox is one folder inside it. `README.md` and `CONTRIBUTING.md`
are short and clear, but `CONTRIBUTING.md` names plan v6 as the working plan: 53,896 words, three plans old.
`make venv` works; the first run stops with a clear message to fetch the Java parts and the fonts. Lint passes in a
minute. To change a page they open one function of 1,986 lines with 186 references such as "D-553". To change a
word they must find which of 43 text modules wins. To learn why, there are 684 decision files with no "start
here". To learn what is broken, 44 reviews and no single list. To merge, they write a line on pull request #639
and wait. Estimate: a first safe one-line change in one to two days; a first safe change to a page in about a week.

### The process: keep, change, stop

| Practice | Verdict | Why and how |
| --- | --- | --- |
| Merge trains (66 so far) | Change | Keep the train as the one place where everything runs. The train, not a lane's own report, is the proof; make its checks required |
| One card, one branch, one pull request | Keep | Standard short-lived branches |
| No human review (D-311) | Change, for the pilot's release only | Fine for building. For what goes to a hospital, the 18 safety-core files need one named human reviewer |
| The decision registry | Change | About 950 decisions in five weeks is a change log, not a decision record. Keep the files as history. Stop requiring a number for every card. Write one page: "the 20 decisions that shape TrialBox" |
| Decision numbers in code comments | Change | Keep them where a safety rule is enforced; elsewhere say the reason in words |
| Plans (23 files) | Stop adding | One living plan and one backlog; archive the rest |
| Reviews (44 entries) | Change | No new broad review until there is one open-findings register. This review should be the last to add findings without one |
| The problem log | Keep and revive | It is the right tool for IEC 62304 clause 9; it must be the single register |
| Goldens with a reason; the coverage ratchet; no-mock tests; doc lint | Keep | Better than most small teams |

### Findings

**High**

- **L-1. No recorded mutation score for the safety core.** The only figure is 66.6 %; the floor is 60 %. A third
  of small changes to the rules that decide about a patient may pass every test. *Fix:* the nightly writes its
  score to a small file in the repository; the floor follows it.
- **L-2. A safety-core file is almost untested in the unit job** (`equivalence/gate.py`, 26.8 %). It is the gate
  that compares the two engines. *Fix:* unit tests, or say where it is tested and count that.
- **L-3. Console pages cannot be changed safely.** Flagged on 2026-11-10 and 2026-11-12; grew each time. This is
  also why the screens became complex: adding a page is easier than restructuring. *Fix:* a size ratchet in CI at
  today's values; each card that touches a page moves it to its own module.
- **L-4. Text keys override each other silently.** `services/console/i18n.py:1169-1236` merges modules with a
  plain update; a missing key shows raw (`i18n.py:1152`). This produced two bugs seen in the journey review (the
  `/admin/edc` title; "life.vstate.unplanned" on the participant page). The only test checks that three languages
  have the same keys. *Fix:* fail on a key defined twice with different text; test that every key a template uses
  exists; in test mode a missing key is an error.
- **L-5. No single register of open findings.** Nobody can say what is open (IEC 62304 clause 9). *Fix:* one
  register (id, severity, state, card, the test that closes it), seeded from the register of 2026-11-10 and the
  two reviews of today.

**Medium**

- L-M1. Product code imports tools and simulators in six places. If `tools/` is left out of an image, a page
  fails at the click, not at the start.
- L-M2. Still open from 2026-11-12, verified today: the log scrubber skips structured fields
  (`libs/tb_common/logging.py:136`); the PHI guard runs without the site's chart-number pattern when settings
  cannot be read (`services/guard/guard.py:49-56`); skipped tests fail only in the compose jobs.
- L-M3. Onboarding points at the wrong plan (`CONTRIBUTING.md:4`).
- L-M4. CI cost: 118 to 182 runner-minutes per full run, and a billing stop already happened
  (`docs/plan/38-handover-2026-11-15.md:61`). The two-tier rule of plan 43 is the right answer; record minutes per
  train.
- L-M5. All complexity rules are off, and all security rules are off for the tools, which include the backup,
  update and install code that runs as root on the box.

**Fixed since 2026-11-12 (verified):** the console reads the effective opt-out list; the table of 33 known path
differences is empty; the derived-value batch has a caller.

---

## M. AI and model governance

The frameworks used as good practice: the FDA's 2025 draft guidance on AI supporting regulatory decisions for
drugs (its seven-step credibility framework), the EMA's 2024 reflection paper on AI in the medicinal product life
cycle, the Good Machine Learning Practice principles (2021), GAMP 5 second edition (the AI/ML appendix), the NIST AI
Risk Management Framework 1.0, and CONSORT-AI / SPIRIT-AI for reporting. Pre-screening is arguably "operational"
and outside the FDA draft's strict scope; pre-fill of trial data is inside it. Clause numbers marked "tbc" are to
be checked.

### Where a model is used, and how much rides on it

| Model use | Context of use | Influence | If it is wrong | Risk |
| --- | --- | --- | --- | --- |
| **Criteria extraction** from a protocol (the compiler, the document parser) | Drafts coded criteria and code lists; an investigator approves each rule set before any patient is screened | High in practice: the draft is what gets approved, and errors are silent | One wrong criterion mis-screens every patient of a study | **High** |
| **Reading the notes** (judge and verifier) | Answers met, not met or unknown with a quote; excludes only if both models agree, the quote verifies and the gate is open | Exclusion: high (few people re-read the "not matched" list). Other answers: medium | A missed eligible patient | **Medium** |
| Retrieval of note excerpts (embeddings) | Chooses what the judge sees | Indirect: a miss gives "unknown", which goes to a person | Extra review work | Low to medium |
| **Pre-fill of CRF values** | Drafts trial-record values for a qualified person to confirm | Medium | Trial data sent to a sponsor | **Medium to high** |
| Consent explanation and translation | Drafts patient-facing text; a second model checks; a person sends | Medium | A patient's understanding | Medium |
| The command field | Turns a sentence into a proposed command; the user confirms | Low | A wrong job, seen before it runs | Low |
| "Ask" | Re-phrases an answer the console built itself | Low | Misleading help | Low |

`docs/validation/ai-governance.md` lists these uses with no risk reading, and each model card says "Contexts of
use: None approved".

### The checklist

| # | Control (source) | Verdict | Evidence |
| --- | --- | --- | --- |
| 1 | Context of use stated per model use (FDA draft steps 1-2; NIST MAP 1.1) | PARTLY | A table of uses; no statement per use |
| 2 | Model risk assessed as influence by consequence (FDA step 3; EMA, risk-based approach, tbc) | DOES NOT MEET | No risk reading anywhere |
| 3 | A credibility plan with fixed acceptance criteria (FDA step 4; GAMP 5 AI/ML appendix) | MEETS | `docs/validation/model-change-protocol.md` section 3; thresholds in `tools/qualify.py`, held by a test |
| 4 | The plan executed and documented (FDA steps 5-6) | DOES NOT MEET | No record in `eval/qualification/`; plan 42 section 4b still waits for a full `qualify --box` |
| 5 | Adequacy for the context of use decided (FDA step 7) | DOES NOT MEET | "No figure the repo quotes today was measured on what ships" |
| 6 | Model identity fixed and verifiable (GMLP 2) | MEETS | `models/registry.yaml`; the gateway refuses unexpected weights and an unqualified build |
| 7 | Prompt versions controlled; a change tied to approval (GAMP 5 AI/ML appendix; ISO/IEC 42001 Annex A, tbc) | MEETS | `libs/tb_llm/prompt_registry.py`; rule sets pin their prompts |
| 8 | One controlled path to the model; no patient text leaves (EMA, data protection) | MEETS | `tests/unit/test_no_direct_model_calls.py`; `models/routing.yaml` |
| 9 | Test data represent the intended population (GMLP 3) | DOES NOT MEET | Every set is public or synthetic; the gold set waits for the hospital carve; Taiwan's charts are mainly English and are measured on none |
| 10 | A sound reference standard (GMLP 5) | PARTLY | In launch P1b the answer key was wrong in 5 of 11 "wrong exclusions" |
| 11 | Performance per subgroup and language (GMLP 3; NIST MEASURE 2.11) | PARTLY | The self-test has 18 cases per language but one pooled threshold |
| 12 | Human-and-AI team performance measured (GMLP 7) | NO EVIDENCE FOUND | Shadow mode (D-988) is designed; no code was found |
| 13 | Clear information on each output (GMLP 9; EMA, transparency) | PARTLY | Seen: the quote, its source, a "test model" mark. With a real model the row names no model or prompt version |
| 14 | Traceability from an output to model, prompt, input, time and confirmer (ICH E6(R3) on metadata, tbc; D-989) | PARTLY | Call ids and hashes are recorded. Not built: the index, the "AI used" and "AI confirmed" events, search, the pre-fill pointer |
| 15 | Human oversight; fail-safe on missing data (EMA; NIST MANAGE) | MEETS | Both must agree; unknown never excludes; a missing record never excludes |
| 16 | Automation bias considered (GMLP 7) | PARTLY | A disclaimer on every page. But lists are pre-sorted "fewest unknowns first" and show "16/23" before the person's own view |
| 17 | Monitoring in use (GMLP 10; GAMP 5, operation phase) | PARTLY | A nightly self-test and a hold switch (runbook 19). No trend of unknowns, disagreements or overrides |
| 18 | Change control with re-qualification triggers | PARTLY | Covers model, prompt, template, engine, routing. Not: a terminology release, the note-mask version, the embedder, thresholds, the site's data shape |
| 19 | Robustness to adversarial input (NIST MEASURE 2.7) | PARTLY | An 80-case suite as a `qualify` step; the hardened prompts are the unqualified ones |
| 20 | Prompt and response logs minimised and erasable | PARTLY | Production keeps 7 days, patient text as hash and size only; erasure of traces on opt-out is still owed |

### What must be re-run when something changes

| Change | What must be re-run | Enforced by |
| --- | --- | --- |
| Model weights or revision | Verify the pin, a full `qualify`, promote, self-test | **Code** |
| Prompt text | A new version, a full `qualify`, the investigator re-approves each rule set | **Code** |
| Chat template; serving image | A full `qualify` | **Code** at install; flags by habit |
| Terminology release | Recompile and re-approve every rule set | **Code** for the recompile; no accuracy re-run |
| Note-mask version, thresholds, embedder | Nothing defined | **Neither** |
| The site's data shape (a new note type, the language mix) | Nothing defined | **Habit** |

### What a pilot's evaluation report would need (CONSORT-AI style)

| Item | Can the product produce it today? |
| --- | --- |
| The algorithm and its version | Yes, per call in the audit chain; not in one query, not on the page |
| How input data were chosen; handling of missing input | Mostly; yes |
| Human-and-AI interaction: who saw what, when | No: needs shadow mode's worksheet |
| How the output contributed to the decision | Partly: marks exist; no per-criterion human answer |
| Performance with intervals, per language and study | No |
| Error analysis by criterion | No, only the off-box scorer |
| Changes to the algorithm during the pilot | Yes |

### Findings

**High**

- **M-1. No qualification record exists, so the shipped prompt set has never been accepted.**
  `libs/tb_llm/prompts/registry.yaml`: all 14 current versions have no qualification; the rule sets still pin the
  earlier judge prompt (`rulesets/*/manifest.yaml`) while the owner ruled the newer one ships. A production box
  today would serve the old baseline prompts and may not exclude on notes. *Fix:* the first proof run is one
  passed `qualify --box` on the shipped box with the shipped prompt set, and the rule sets re-pinned.
- **M-2. The compiler has no accuracy gate.** It is the highest-risk model use and the least gated: `qualify`
  has no extraction step, and the four causes of launch P1b sit here (58 of 1,273 concepts mapped; 370 criteria
  demoted to a person; 30 of 103 protocols failed before screening). A 110-line check exists
  (`tools/ir_extract_canary.py`) and is not wired in. *Fix:* an `extraction` step in `qualify` with a threshold.
- **M-3. `docs/validation/ai-governance.md` still presents withdrawn figures** as "the deployed pair" and "the
  gate result", while `docs/VALIDATION.md` section 3 now calls them "not product evidence". This note is what a
  hospital's AI committee would be handed. *Fix:* replace its section 6 with plan 42's "what may and may not be
  said"; add the risk table above.
- **M-4. Shadow mode is the pilot's only planned proof of value and has no code** (D-988). *Fix:* the screening
  half first (seal, an answers table, the report); the console's worksheet can be one form.
- **M-5. Nothing watches the model in use.** *Fix:* one administrator page from data the job summaries already
  hold: share unknown, pair disagreements, overrides, per notes language, per week; an alarm on a step change.

**Medium**

- M-M1. A real-model answer does not say which model (also journey review C-M6).
- M-M2. Provenance stops before the record: finish D-989's second step.
- M-M3. A clinician's disagreement is not captured per criterion and feeds nothing. A "this answer is wrong"
  control on each criterion row, stored with the call id.
- M-M4. The self-test can pass with one language failing. Apply the thresholds per language.
- M-M5. The change protocol leaves out four things that change answers (the table above).
- M-M6. Automation bias is unmeasured. For the pilot's first weeks, let the coordinator answer before seeing the
  box's answer; say "records agree on 16 of 23", not a score.

**Low**

- M-L1. Every new prompt is "approved by: no named reviewer" (consistent with D-311). Record the qualifying
  operator.
- M-L2. Erasure of traces on opt-out is owed (mitigated by 7-day, hash-only storage).

**Closed since earlier reviews:** one model answering twice; no `qualify`; the verifier answering as the judge.
Still open in substance: the real pair has never passed the gate.

### Cards for area M

| # | Card | Size | Lane | Band |
| --- | --- | --- | --- | --- |
| G1 | The first qualification record on the shipped box; the shipped prompts qualified; rule sets re-pinned | M | Int, D | Before |
| G2 | An `extraction` step in `qualify` | S | A2 | Before |
| G3 | Rewrite `ai-governance.md`: context of use, the risk table, only the allowed claims | S | Int | Before |
| G4 | Shadow mode: the screening half, then the console's worksheet | L | A2, C2 | Before |
| G5 | Provenance, second step, and the model named on the page | M | A2, C2, E | Before |
| G6 | Self-test thresholds per language | S | A2 | Before |
| G7 | A model-in-use page: unknown, disagreement and override rates per language | M | C2 | During |
| G8 | "This answer is wrong" per criterion | S | C2 | During |
| G9 | Four more change classes in the change protocol | S | A2, H | During |
| G10 | The gold set per language from the carve; a subgroup table | L | H | During |

**Stop or delete:** stop quoting any figure of 2026-11-08 in `ai-governance.md` and the model cards; stop adding
bake-off candidates until one pair is qualified; retire from the "must qualify" set the prompts nobody will use in
the pilot, so the first record is smaller.

**Exit criteria:** (1) `qualify --check` answers "qualifies" for the shipped pair and the shipped prompt set on a
box installed from the signed bundle, and every approved rule set pins those prompts. (2) For any listed patient,
one query returns the model build, the prompt version and the confirmer of each note answer in under a minute.

**Questions for the owner:** Should the pilot's first weeks run with the coordinator answering first?
*Recommend:* yes, for the first study. Is CRF pre-fill in the pilot? *Recommend:* leave it out until its prompt is
qualified and its provenance pointer is built; it is the one model use that touches trial data.

---

## N. Operations at a hospital

Builds on the journey review's area H (install, restore, runbook) and on area I above; neither is repeated.

**The operations design is far better than on 2026-11-10:** most of that review's 77 operations findings are
closed. The weak point is now *telling a person*.

### The operations calendar (assembled from ten runbook pages; the minutes are estimates)

| When | Task | Who | Min | Reminded by the product? |
| --- | --- | --- | --- | --- |
| Daily | Read the health mail, or open `/admin` on a box with no mail | Administrator | 2 | Mail: yes. No-mail box: no |
| Daily | Backup, logs, signing of audit heads, weights check, the model's self-test | The box | 0 | Red in the mail on failure |
| Weekly | The unused-accounts list; disable leavers | Administrator, PI | 5 | Yes, Monday's mail |
| Weekly | Break-glass grants reviewed within 7 days | Steward | 5 | A mark on the steward's list only |
| Monthly | Operating-system patches in the hospital's window, then `doctor` and the self-test | Hospital IT | 60 | No |
| Per release | Apply the signed update; return the check output to the vendor | Administrator | 45 | No: the box cannot know a release exists |
| Quarterly | Restore drill with the private key | IT, the key holder | 60 | Yes: warn at 90 days, red at 100 |
| Quarterly | Access review of all accounts with the PI | Administrator, PI | 20 | No |
| Yearly | Full restore; key inventory; escrow shares check | IT, key stewards | 240 | No |
| Yearly | Certificate renewal (hospital CA) | Hospital IT | 30 | Yes: 45 and 30 days |
| Yearly | Firmware, UPS, a planned power cut | Hospital IT | 60 | No |

`docs/runbook/02-daily-operation.md` holds none of the rows a person does. There is no single calendar.

### What is watched

| Signal | Watched? | Who is told | On a box without mail |
| --- | --- | --- | --- |
| The model's self-test | Yes | Administrators; a line for coordinators | A tile only |
| Backup age or failure | Yes | The backup mail address | A tile and the audit |
| Disk; certificate; the opt-out worker | Yes | Administrators | **Nobody** |
| A service the watchdog gave up on | An audit event | **Nobody** | Nobody |
| Database unhealthy | "Report" only | **Nobody** | Nobody |
| Clock offset; audit chain break; egress filter | Only when someone runs `doctor` | **Nobody** | Nobody |
| GPU hardware fault; model latency | No | – | – |
| Night overrun into clinic hours | Measured afterwards, never judged | Nobody | – |
| Failed sign-ins | Counted | Nobody | A tile |

### ISO/IEC 27001:2022 operational controls

| Control | Verdict | Evidence, and what is missing |
| --- | --- | --- |
| A.8.6 Capacity | PARTLY | Disk thresholds; a capacity check at go-live. Missing: a growth forecast, a night-overrun signal, the capacity statement |
| A.8.13 Backup | PARTLY | Encrypted nightly backups to a key the box lacks; a restore drill. Missing: a timed restore; the restic rehearsal (D-977: "Remains: R4") |
| A.8.14 Redundancy | DOES NOT MEET | See I-1 |
| A.8.15 Logging | PARTLY | Structured logs with a scrubber, retention, gap detection. Missing: the syslog forwarder the IT pack promises; an audit event when a support bundle is made |
| A.8.16 Monitoring | PARTLY | The table above |
| A.8.17 Clock | PARTLY | Checked by `doctor`, not continuously |
| A.8.8 Vulnerabilities | PARTLY | A patch policy and the supply-chain gate. Missing: a named owner; a plan for 2026-12-10 |
| A.8.19 Software installation | MEETS | Signed bundles; digests checked before any change |
| A.8.32 Change management | PARTLY | Staged roll-out is written. Missing: how a site without remote access returns its evidence; a PostgreSQL major-version procedure |
| A.5.18 Access review | PARTLY | End dates, the unused-accounts page. The quarterly review is a shell command with no record |
| A.5.24 to A.5.26 Incidents | PARTLY | `docs/plan/sites/incident-response.md` is a draft, never exercised |
| NIST SP 800-34, plan testing (clause number to be checked) | DOES NOT MEET | 13 of 14 named drills have no test |

### Support, as written today

| Level | First answer | Gap |
| --- | --- | --- |
| P1: console down, backup red over a day, box lost | 1 working hour | One person covers both countries, "no backup named yet" |
| P2: one run type fails, GPU down | 4 working hours | – |
| S1 incident: data left the hospital | Word to the hospital within 1 hour, at any time | Cover is working days only |
| Records | Tickets by mail; the vendor's problem log | No link from a ticket to a problem; no site-side form |

### Findings

**High**

- **N-1. Three different "is the box healthy" answers, and they disagreed in the demo.** Seen: `/metrics` gave
  health level 2 (red) while the administrator's Health tab showed "System 3/3 OK".
  `services/console/templates/admin.html:12-14` counts reachable services; the computed level is used only by the
  mail and the metrics page; `doctor` is a third set of 39 checks. (In the demo the red is partly an artefact; the
  structural point stands: no page shows the computed level.) *Fix:* one banner on every administrator page with
  the level and its red lines; `doctor`'s failures count as one check.
- **N-2. Procedures are named as drilled, but the drills do not exist.** Fourteen runbook pages carry "Drill:
  `test_runbook_…`"; one exists. *Fix:* build the four that matter (a timed restore, disk full, GPU fault, morning
  mail missing); mark the others "tabletop, not yet held".
- **N-3. One person, two countries and a one-hour clock** (runbook 21). With no remote session, the promise that
  the vendor "checks each site's Operations page every working morning" cannot be kept at all. *Fix:* name a
  backup; promise one hour in cover hours only; replace the morning check by the site sending the health line.
- **N-4. The site pack promises monitoring that is not built** (`docs/plan/sites/it-security-pack.md:79`: disk,
  GPU, every timer's last run, a syslog forwarder). *Fix:* correct the sentence now.
- **N-5. The waivers lapse on 2026-12-10** (the same as J-1, from the operations side: no bundle can be built).

**Medium**

- N-M1. No operations calendar. Ship the table above as one page in three languages and as a "Due" tile.
- N-M2. A service the watchdog gave up on alerts nobody.
- N-M3. Night overrun is measured but never judged.
- N-M4. Retention is stated two ways (`record-of-processing.md:43` gives the lake's rule for backups), and no site
  document tells the privacy office that an opted-out patient stays in backups for up to 14 nights and in month-end
  lake snapshots for 36 months.
- N-M5. The support bundle leaves no audit trace and needs no second person.
- N-M6. Incremental backup falls back to the full one quietly; the tile does not say which is on.
- N-M7. Access review and break-glass review are not reminded.
- N-M8. How a site learns that an update or a security notice exists is one sentence.

---

## Proposed cards

Sizes: S small, M medium, L large. Lanes: A2 screening and the compiler; B2 lake and masking; C2 console; D
installer and CI; E EDC and terminology; W Windows; H driver, benchmark, terminology loader and tools; Int the
integrator. Bands: **before** a hospital pilot; **during** the pilot; **after**.

| # | Card | From | Size | Lane | Band |
| --- | --- | --- | --- | --- | --- |
| F1 | Name the waiver owner; stagger the dates; type the agreed model-server waiver; open its re-qualification | J-1, N-5 | S | D, owner | Before, and before 2026-12-10 |
| F2 | A release-record generator and the first record (tag, CI results, SBOM, qualification record, open problems) | K-1 | M | D | Before |
| F3 | Traceability with real test results | K-M1 | M | H | Before |
| F4 | The validation plan 1.2: a wider trigger; IQ, OQ, PQ generated from `doctor`, CI and the acceptance tool | K-2 | M | Int | Before |
| F5 | Finish erasure: FHIR store, identity shred, lake snapshots, the backup rule | J-2 | L | B2, C2 | Before real data |
| F6 | The withdrawal's "data may not be used" blocks decide, sign, send and export | J-3, K-4 | M | C2, E | Before |
| F7 | The EDC tool write: signed, or off for the pilot | K-3 | S | E | Before |
| F8 | The audit event inside the transaction for regulated writes (data entry, consent, SAE, marks, accounts, break-glass) | I-M3, K-5, J-M3 | M | C2 | Before |
| F9 | A timed restore drill on the compose box; fill runbook 22; log archiving on by default with a backup share | I-1 | M | D | Before |
| F10 | A nightly compose run of the 17-step walk; the compose suite is the pilot's gate; cross-card tests against the HTTP lake | I-2 | M | D, B2 | Before |
| F11 | A provisional capacity statement at the measured size | I-4 | S | H | Before |
| F12 | An import-rule test with a frozen baseline | I-3 | M | Int | Before (the test); during (the removals) |
| F13 | Settings in three classes; refresh stale examples; delete `site_params.yaml` | I-M1 | M | D | Before |
| F14 | The console starts on the database alone | I-M4 | S | C2 | Before |
| F15 | A trusted proxy address for the throttle; refuse a wildcard | J-4 | S | D | Before |
| F16 | The injection suite on the real pair, filed with the release record | J-5 | S | A2 | Before |
| F17 | Mask inside the audit writer; reason codes | J-M1 | M | C2 | Before |
| F18 | Container hardening on every service; secrets as files | J-M4, J-M5 | M | D | Before |
| F19 | An ASVS Level 2 checklist file; a dynamic-scan baseline in the nightly | J-M8 | M | D, Int | Before |
| F20 | The export stamp: who, when, version, commit; `/about` shows the commit | K-M2 | S | C2, E | Before |
| F21 | Intended use 0.3 and one risk file | K-M4, K-M6 | S | Int | Before |
| F22 | The mutation score written nightly to the repository; the floor follows it | L-1 | M | A2 | Before |
| F23 | Unit tests for `equivalence/gate.py` | L-2 | S | A2 | Before |
| F24 | Text keys: fail on conflicting doubles; every template key exists; fix the 15 conflicts | L-4 | S | C2 | Before |
| F25 | One open-findings register; retire the others by link | L-5, K-M5 | M | Int | Before |
| F26 | A function-size ratchet in CI; pages move to their own modules as they are touched | L-3 | S, then ongoing | C2, D | Before (the ratchet) |
| F27 | Move the five `tools` imports into libraries; guard the simulator import | L-M1, I-L1 | S | C2, E | Before |
| F28 | The log scrubber for structured fields; the guard's default pattern; strict skips in the unit job | L-M2 | S | B2, D | Before |
| F29 | A "start here" page: the current plan, the 20 key decisions, how a card lands; fix `CONTRIBUTING.md` | L-M3 | S | Int | Before |
| F30 | One health banner on administrator pages; `doctor` failures, watchdog gave-up, database, clock, audit-head age and night overrun as checks | N-1, N-M2, N-M3 | M | C2, D | Before |
| F31 | Four real drills; mark the rest "tabletop" | N-2 | L | D | Before |
| F32 | Correct the IT pack and the record of processing to what is built; privacy wording on backups and snapshots | N-4, N-M4 | S | Int, B2 | Before |
| F33 | An operations calendar page in three languages and a "Due" tile | N-M1 | M | C2 | Before |
| F34 | The support bundle: an audit event, an approver, a manifest summary | N-M5 | S | D | Before |
| F35 | The Backups tile shows incremental on or off and why; the restic rehearsal | N-M6 | S | D | Before |
| F36 | Hourly signed heads; default-refuse callees; a DNS allow-list | J-M2, J-M6, J-M7 | M | C2, D | During |
| F37 | One outside penetration test | J-M8 | M | Int | During |
| F38 | One per-participant combined trail; the PI may read it; an audit-trail review procedure | K-M3 | M | C2 | During |
| F39 | Training-record export; the Part 11, ER/ES and Electronic Signatures Act assessment page | K | S | C2, Int | During |
| F40 | One scheduler; night steps chained on completion | I-M2 | M | B2 | During |
| F41 | The FHIR store on demand, off the box | I-M6 | M | B2 | During |
| F42 | Access-review and break-glass reminders with a recorded "Reviewed"; a release-notice template; a GPU fault signal | N-M7, N-M8 | S | C2, D, Int | During |
| F43 | `/healthz`, cookie flags, the old session's end; remove the password-zip mail path | J-L | S | C2 | During |
| F44 | Security lint for the tools that run as root | L-M5 | S | D | During |
| F45 | Fold the 27 service folders into about 8 packages | I | L | Int | After |

Cards G1 to G10 for area M are listed in its section.

---

## What to stop or delete (gathered)

- **Stop** adding compose overlays and deployment forms. Freeze or delete `deploy/platform`, `deploy/two-device`
  and the unused cloud scripts until a site asks. Drop the Prometheus overlay from the pilot's supported forms (it
  has rules and no alert sender).
- **Stop** adding `TB_*` settings without a class. **Delete** `site_params.yaml` and, once the console's matrix
  covers it, the mail-sender permission table.
- **Stop** new imports across services (the ratchet test). **Move** the test stand-ins out of `services/`.
- **Delete** the password-zip mail path, the old actor assertion and the shared legacy token once every route is
  on the current one, and the direct verifier address outside development.
- **Stop** keeping two risk files and two homes for requirements. **Stop** calling the traceability file a matrix
  until it carries results. **Regenerate or retire** the stale problem log.
- **Stop** writing new plan documents; keep one. **Stop** giving a decision number to every card. **Stop** broad
  reviews until the open-findings register exists.
- **Stop** writing "Drill: `test_…`" on a runbook page before the test exists. **Stop** the promises the IT pack
  cannot keep (the syslog forwarder, every timer's last run, the vendor's morning check).
- **Stop** quoting scale figures from before the reset of 2026-11-14 without the "superseded" label.
- **Remove** the Auto-GPT tree at the repository's root (plan v7.3 section 3.1 already says so), or move TrialBox
  to its own repository.

---

## Exit criteria each area proposes for "ready for a hospital pilot"

| Area | Criterion |
| --- | --- |
| I | A box installed from the signed bundle is wiped and restored from its off-box backup, and the measured RPO and RTO are written into runbook 22 |
| I | Under compose, each of console, orchestrator, gateway, mail gateway and one model server is killed during a screening night, and the night ends with no lost job, no duplicate mail and an intact audit chain |
| J | The erasure registry shows no owed entry for a store inside the box, and a test opts a synthetic patient out and finds the pseudonym nowhere; backups have a written age-out rule |
| J | No waiver has an unnamed owner or a date inside 30 days; the release record holds an injection-suite result on the pilot's pair and a filled ASVS Level 2 checklist with no "does not meet" in V2, V3, V4 |
| K | For the release the pilot runs, a generated release record exists, naming commit, image digests and a passing qualification record, with no open wrong-answer, data-loss or security problem |
| K | After a withdrawal with "data may not be used", decide, sign, send and export are each refused and audited, on both write paths |
| L | The safety core's nightly mutation score is recorded and at least 85 %; every safety-core file meets its coverage target or has a written exception |
| L | One open-findings register exists with no open High item without a card |
| N | With a planted fault on a box with no mail relay, an administrator who signs in sees a red line on the first page within an hour, and the page, the mail and `/metrics` agree |
| N | One timed full restore on the pilot's hardware form is on file, and the hospital's own key holder has done the quarterly drill once |

Plan 8 judges these against the integrator's six and proposes one list.

---

## Questions only the owner can answer (gathered; plan 8 holds the short list)

1. Who is the named security owner for the waivers, and may the dates be staggered now? *Recommend:* name one
   person today.
2. Will Aimedics keep one loaner box per country? *Recommend:* one shared loaner; say "5 working days" in the IT
   pack.
3. Hospital sign-in: the shipped route to a hospital directory puts an identity provider in the box, which you
   declined. *Recommend:* local accounts with a code for the pilot; connect the console straight to the hospital's
   own provider where one exists.
4. Should formal validation records return at the first real trial record of any kind, not only at pre-fill?
   *Recommend:* yes; generate them.
5. Who signs the site's validation summary? *Recommend:* the hospital's own validation group or trial office,
   with the generated pack.
6. For the pilot's release only, may one named human review changes to the 18 safety-core files? *Recommend:* yes.
7. May the plan, review and decision folders be frozen as an archive, with one living plan and one findings
   register? *Recommend:* yes.
8. Who is the second support person, and is the one-hour incident clock round the clock? *Recommend:* name a
   backup per language; promise one hour in cover hours only.
9. On a box with no mail relay, who looks every working day? *Recommend:* the box owner, with the health line
   shown to coordinators at sign-in.

---

## Limits of this review

- Reading reviews, with cheap measurements. No install, no full test suite, no mutation run, no model, no GPU.
- Area J did not re-read every earlier register row; rows marked "not re-verified" above rest on the review of
  2026-11-13.
- Area I's failure table is from code; none of those failures was produced.
- Area L made no GitHub calls: branch protection and CI history are from earlier records. The clone is shallow.
- Area N's minutes are estimates. The health disagreement was seen on the demo, where one red check is an
  artefact of the demo's shape.
- Clause numbers marked "to be checked" should be checked against the standards before this page is shown to a
  hospital's validation group.
- No product code and no test was changed.
