# Decision number registry

One row per decision number or range. A number belongs to the holder in its row and to nobody else. A pull request
that needs a number takes the next free one and adds its row, or writes "decision number needed" (D-311: no waiting
for the integrator; the old rule "the row is added before the branch is cut" is struck). Rules: D-306, D-311.

`python -m tools.decisions_index --check` (CI job `docs`) holds this table against the text: the frozen log
`docs/DECISIONS.md` (entries D-01 to D-270) and the files `docs/decisions/D-nnn-<slug>.md`. It fails only on a number
written twice; a file with no row, a new log entry or a gap is printed as a note (D-311).
`python -m tools.decisions_index` prints the full index with titles.

States:

| State | Meaning |
| --- | --- |
| `merged` | the text is on master (the log or a file) |
| `reserved` | held by a card, a pull request or a fix group; its file may land (the integrator flips the row to `merged` when convenient) |
| `unused` | never to be used: a gap, or a reservation that was voided |
| `missing` | cited on master, never written: the text is owed |

How to take a number: the integrator writes a `reserved` row naming the card (`T-nnn`) or pull request (`PR #n`). New
numbers start at **D-300** and go up by one. A decision file must name its card in its first lines when the row
names a card.

Collisions settled by TB-PLAN-06 §6.1 rule 3: a number belongs to whoever has it on master. D-201 stays test
isolation (PR #75 takes D-300); D-205 stays committed goldens (PR #82 takes D-301); D-204 is T-104's (merged from
the PR #83 version; PR #82 drops its copy). Reservations D-190 to D-207 of TB-ASSESS-01 are void (the numbers on
master stay); reservations D-208 to D-262 stay valid.

## The frozen log and the first files (D-01 to D-207)

| Number | State | Holder | Note |
| --- | --- | --- | --- |
| D-01..D-98 | merged | phases 0 to 5, clinical review build | `docs/DECISIONS.md` |
| D-99 | missing | — | cited on master (exact counts inside the site, the coordinator's screen, one chart number shown once and audited: `services/orchestrator/scenarios/screen.py`, `services/console/app.py`, `services/console/home.py`, `services/console/backend.py`, `services/orchestrator/app.py`) but never written in the log; the text is owed |
| D-100..D-151 | merged | simple build plan steps 1 to 5 | `docs/DECISIONS.md` |
| D-152..D-159 | unused | — | gap recorded by TB-ASSESS-01 |
| D-160..D-163 | merged | EDC prefill, Study A documents | `docs/DECISIONS.md` |
| D-164..D-169 | unused | — | gap recorded by TB-ASSESS-01 |
| D-170..D-179 | merged | reference data, rehearsal, IT screens (PRs #66, #68, #76 and earlier) | `docs/DECISIONS.md` |
| D-180 | merged | PR #80 | catalogue completion with verified codes (file) |
| D-181 | merged | PR #64 | judge bake-off; `docs/DECISIONS.md` |
| D-182..D-184 | unused | — | held for the sibling session, which was given D-185 to D-193 instead |
| D-185..D-193 | merged | sibling session | supply chain, backups, derived scores, SAE register, identity, TLS; `docs/DECISIONS.md` |
| D-194..D-200 | unused | — | TB-ASSESS-01 reservations for T-006 to T-012, void (T-012 takes D-305) |
| D-201 | merged | T-003 | test isolation and disk (file) |
| D-202 | unused | — | TB-ASSESS-01 reservation for T-102, void (T-102a takes D-302) |
| D-203 | merged | T-005 | data-handling scan (file) |
| D-204 | merged | T-104 | database image and checksummed migrations (file) |
| D-205 | merged | T-006 | committed goldens (file) |
| D-206 | merged | T-007 | CI gate v1 (file) |
| D-207 | merged | T-008 | feature flags (file) |

## Reservations of TB-ASSESS-01 that stay valid (D-208 to D-269)

| Number | State | Holder | Note |
| --- | --- | --- | --- |
| D-208 | reserved | T-108 | Wave-3 operations in code |
| D-209 | reserved | T-110 | Release identity and supply chain |
| D-210 | merged | T-111, PR #83 | update safety (file) |
| D-211 | reserved | T-113 | The shared-quota profile, doctor --platform and the platform manifests |
| D-212 | reserved | T-114 | Cloud B200 qualification record |
| D-213 | reserved | T-115 | EDC prefill follow-ups from TB-REV-EDC-01 (the tracked items) |
| D-214 | reserved | T-117 | Backups: layout, stream hashes, off-box schedule, age alert, … |
| D-215 | merged | T-118 | wave-1 leftovers: unit mismatch, one encoding detector, one dates module |
| D-216 | reserved | T-119 | Cloud hygiene remainder |
| D-217..D-219 | unused | — | no card of TB-ASSESS-01 took them |
| D-220 | reserved | T-103 | One reveal path |
| D-221 | unused | T-107 | The catalogue loaded as data (voided: T-107 took D-353) |
| D-222 | reserved | T-109 | Identity v1: Caddy, Authelia, local TOTP, step-up, forced password … |
| D-223 | reserved | T-112 | The data-operations console v1 |
| D-224 | reserved | T-116 | "Criteria not matched", the forbidden-word check and the intended-use … |
| D-225 | reserved | T-201 | Clinical conflicts and the conflicts page |
| D-226 | reserved | T-202 | The lake exported from OMOP: parity in CI and the flag flip on the … |
| D-227 | reserved | T-203 | pgvector, the chunker and "patients like me" |
| D-228 | unused | T-204 | The twin: T-204 took D-440 instead |
| D-229 | reserved | T-205 | Second factor at signing and the record lock |
| D-230 | reserved | T-206 | Opt-out worker v1 |
| D-231 | reserved | T-207 | The derived-data framework: stored rows and definitions as data |
| D-232 | unused | T-208 | was reserved for T-208, which took D-346 |
| D-233 | reserved | T-209 | Monitoring, admin screens and the support bundle |
| D-234 | reserved | T-210 | Windows/WSL2 hardening, keys under a KEK, the unseal path |
| D-235 | reserved | T-211 | Audit integrity: signed heads, one writer, NTP as a FAIL, the audit … |
| D-236 | reserved | T-212 | Boundary and egress |
| D-237 | reserved | T-213 | The acceptance environment and the Docker drills |
| D-238 | reserved | T-214 | arm64 builds, the gb10 profile measured, the two-device link |
| D-239 | reserved | T-214 | arm64 builds, the gb10 profile measured, the two-device link (the owner's decision) |
| D-240 | reserved | T-215 | QMS-lite records, change classes, the FS, the risk file, the VMP for … |
| D-241 | reserved | T-216 | Missing data as the normal case |
| D-242 | reserved | T-301 | Wave 5 product completeness, help, card and .ics |
| D-243 | reserved | T-302 | REDCap arms and events, repeating instruments, copy-assist, ODM … |
| D-244 | reserved | T-303 | Monitor SDV |
| D-245 | reserved | T-304 | Statistics page and the export set: EXTRACT, Define-XML, audit CSV, … |
| D-246 | reserved | T-305 | All-history back-fill, content-addressed snapshots, batched publish, … |
| D-247 | reserved | T-306 | HAPI out of the nightly path |
| D-248 | unused | T-307 | Catalogue gaps and the instrument copyright register (voided: T-307 took D-375) |
| D-249 | reserved | T-308 | Specialty templates |
| D-250 | reserved | T-309 | Break-glass |
| D-251 | reserved | T-310 | Weekly "criteria not matched" sample, the per-study IRB-text gate on … |
| D-252 | reserved | T-311 | The cited profile page and the Study C/D protocol drafts |
| D-253 | reserved | T-312 | Physician annotations |
| D-254 | reserved | T-313 | Setpoints and the gap finder, flags off |
| D-255 | reserved | T-314 | The clinician view, restricted |
| D-256 | reserved | T-315 | Test strategy executed: the journeys as the PQ script, IQ/OQ/PQ … |
| D-257 | reserved | T-315 | Test strategy executed: the journeys as the PQ script, IQ/OQ/PQ … (second record) |
| D-258 | reserved | T-316 | Consortium: the shared code-map registry, signed counts, the … |
| D-259 | reserved | T-317 | Documents made true, role guides in ja and zh-TW, the independent … |
| D-260 | unused | T-318 | TB-ASSESS-01 reservation for T-318, void: T-318 takes D-411 |
| D-261 | reserved | T-319 | Shared-host isolation on the acceptance cluster and the platform KEK … |
| D-262 | reserved | T-320 | Site set-up limits, the EMR launch link, the work log, admin console … |
| D-263..D-269 | unused | — | below the fix-group block; never given |

## The critical-issues fix groups (D-270 to D-289)

| Number | State | Holder | Note |
| --- | --- | --- | --- |
| D-270 | merged | fix group D-270 (PR #86) | the console's "today" is the site's date; `docs/DECISIONS.md` (its last entry) |
| D-271 | merged | fix group D-271 (PR #97) | the data pipeline never promotes nothing; `docs/decisions/D-271-data-pipeline-integrity.md` |
| D-272 | merged | fix group D-272 (FG-C) | audit integrity: no chart number in the audit chain, a head anchor, an archive that never overwrites (file) |
| D-273 | merged | fix group D-273 | console privacy guards: one reveal path, delegation and opt-out on every patient-level reader, signed role and study (file) |
| D-274 | merged | fix group D-274 with card T-117b | backups and restore: one point in time, a content hash of any size, a copy and an audit row on restore, the cron at install; `docs/decisions/D-274-backup-restore-wiring.md` |
| D-275 | merged | fix group FG-F (PR #115) | structured criteria: unusable data is unknown, never an exclusion; `docs/decisions/D-275-criteria-unusable-data-unknown.md` |
| D-276 | merged | fix group FG-G (PR #101) | the two-model check needs two different models; `docs/decisions/D-276-two-model-check.md` |
| D-277 | merged | fix group D-277 (FG-H) with card T-602 | the SAE clock: the 24-hour report in hours, named rule sets per study, no quiet fallback, the register on the write path; `docs/decisions/D-277-sae-clock-and-register.md` |
| D-278 | reserved | critical-issues fix groups | TB-REG-01; the fix-group session allocates inside the block |
| D-279 | merged | fix group D-279 | identity follow-ups: forced first password change, sign-in lock per account and address, OIDC session lifetime, second factor at signing; `docs/decisions/D-279-identity-follow-ups.md` (file) |
| D-280 | merged | fix group D-280 (FG-K) | the administrator sees no patient data; break-glass for one patient or one job, 60 minutes, reviewed by the steward; a steward role; `docs/decisions/D-280-steward-and-break-glass.md` (file) |
| D-281 | merged | fix group FG D-281 (built as a card, branch `agent/FG-D281-signing`) | EDC signature controls: record lock, keyed signature over the whole act checked before send and export, append-only trail tables, audit inside the transaction, audited refusals, plain ODM legal reason, REDCap version as text; `docs/decisions/D-281-edc-signature-controls.md` (file) |
| D-282..D-289 | reserved | critical-issues fix groups | TB-REG-01; the fix-group session allocates inside the block |
| D-290..D-299 | unused | — | below the new block; never given |

## New numbers (from D-300)

| Number | State | Holder | Note |
| --- | --- | --- | --- |
| D-300 | merged | T-101 | prompt registry, renumbered from the PR's D-201 (file) |
| D-301 | merged | T-105, PR #82 | vocabulary schema (renumbered from the PR's D-205) (file) |
| D-302 | unused | T-102a | was reserved for the permission matrix; T-102a took D-366 (the integrator gave it) |
| D-303 | unused | T-106 | was reserved for the OMOP schema name; T-106 took D-339 (the integrator gave it) |
| D-304 | unused | T-106 | was reserved for the dual write; T-106 took D-339 (the integrator gave it) |
| D-305 | unused | — | was reserved for T-012a, which took D-313 |
| D-306 | merged | T-002 | decisions as files, one number registry, CODEOWNERS and CONTRIBUTING (file) |
| D-307 | unused | T-508 | was reserved for T-508, which took D-332 (the integrator gave D-332) |
| D-308 | reserved | T-501 | held for T-501 |
| D-309 | merged | T-507 | criterion labels in the site's languages, the label step at approval, the test-model label (file) |
| D-310 | reserved | the integrator | given to other cards and pull requests; their own rows replace this one as they land |
| D-311 | merged | owner rule, branch `agent/no-dev-gates` | no development gates; gates apply only when real patient data is read; CGMH covered by the existing CGRD approval (file) |
| D-312 | merged | T-611 | feed completeness gate before publish (file) |
| D-313 | merged | T-012a | `trialbox eval qualify` and the qualification record (file) |
| D-314 | merged | T-614 | Japan ICD-10 as WHO ICD-10: WHO URI, ICD-10-CM twin only for the same code, WHO-only grouper categories (file) |
| D-315 | merged | T-656 | site time zone as one setting (file) |
| D-316 | reserved | the integrator | given to other cards and pull requests; their own rows replace this one as they land |
| D-317 | merged | T-618 | reference data remainder (file) |
| D-318 | merged | T-101b | the approved ruleset pins its prompt and terminology release; approval needed on a change (file) |
| D-319 | merged | T-655 | the review fixes of PR #71: what changes from D-205 and D-207 (file) |
| D-320 | merged | T-505a | the API sign-in asks for the second factor; one channel per session (file) |
| D-321 | merged | T-504 | scenario rulesets: SQL checked on planted gold, CQL recorded by a local engine (file) |
| D-322 | merged | T-613a | the shipped rulesets recompiled offline from their cassettes, and the CI drift check (file) |
| D-323 | merged | T-515 | recorded first and second checks on the demo from a fixture (DEV and TEST only), each opinion marked synthetic, recorded run or test model; the G1 short-run file drops in later (file) |
| D-328 | merged | T-502 | PoC demonstration mode behind the audited flag `demo.mode`: uploads and chart paste refused, banner, `demo.ack`, the scan of stored input (file) |
| D-329 | merged | T-513 | one demo clock: the demo day is the real day in the site's time zone; dates moved, one clock (file) |
| D-330 | merged | T-509 | the PoC host: one VM, the image by digest, Cloudflare Access through a tunnel, kept data on its own disk, daily snapshot, purge (file) |
| D-331 | merged | T-510 | in-product feedback: a flag, a rating and a comment on every page, stored with path, language, role and time; CSV export to issues; the comment in the demo scan (file) |
| D-332 | merged | T-508 | the clinician PoC is product evaluation, not research: no protocol, subject consent or committee step; the acknowledgement only (file) |
| D-333 | merged | T-601 | the gateway never answers one role with another role's model: `fallback: none` unless a route says `any`, one retry on the same build, no fallback on 400/404, build and fallbacks in the response, `tb_llm` raises on an unexpected alias, doctor `judge_route` (file) |
| D-334 | merged | T-613b | lab units read per row: one conversion table in labvalue (engines' factors reused), mapping_check unit pairs and raw values, one presence reader in ja, zh-TW, en (file) |
| D-337 | merged | T-600 | note text masked (names, phones, chart and ID numbers, length kept) before chunks, full-text search and embeddings; the original stays in the lake under `phi` (file) |
| D-340 | merged | T-110b | release identity and bundle gates: version in one place, `release.json` and its schema, `--gates` mandatory, SBOMs in the bundle, no test mail servers, the image gate blocking with dated per-image exceptions, pinned build downloads, one Java version (file) |
| D-342 | merged | T-617b | the licence register as data (`docs/licences/register.csv`) and its build check; model licence rows backed by it; no SNOMED CT ships; the ATC request written, not sent (file) |
| D-343 | merged | T-649b | N-12 gates on the unadjusted figure; every model change follows the model change protocol, and every qualification record cites it (file) |
| D-344 | merged | T-215 | QMS-lite records in `docs/validation/`, VMP v1.1 without signatures, change classes CC1 to CC6, staged roll-out, standards position (file) |
| D-346 | merged | T-208 | the prompt-injection and false-positive suite: facts not words, a stub that obeys as the negative control, the fence escaped, hidden text flagged, traces 7 days in PRODUCTION (file) |
| D-347 | merged | T-210b | the site keys under a KEK: wrapped files, three back ends, the unseal, the key inventory (file) |
| D-339 | merged | T-106 | OMOP second slice: schema name stays `omop`; the adapter's dual write behind the flag `omop.dual_write` (a failure never holds the night); the large CDM tables partitioned by year; the Relational checks after every load in the ingest report; parity timings (file) |
| D-348 | merged | T-673 | third-party images in `deploy/images.lock` by digest, no image by tag, the GPU host checked against the vLLM image (arch, driver, compute capability), Mailpit for MailHog (file) |
| D-349 | merged | T-512 | the PI starts FEAS, SCREEN and CASE on own study; a sub-investigator with the `run` tick; one table `authz.INVESTIGATOR_RUNS`; "data as of" on the patient lists (file) |
| D-353 | merged | T-107 | the clinical item catalogue loaded as data: one concept per item at stable ids, LOINC unmapped never invented, the storable gate in chart extraction, the steward items page (file) |
| D-366 | merged | T-102a | one permission function `authz.permit` over `authz_matrix.yaml`; the old helpers and the console role properties are wrappers; the role x route matrix regenerated as a test (file) |
| D-367 | merged | T-631 | the host tree in the signed release: one payload of kind `host`, `releases/<id>` and the `current` link, the install folder's release files as links through it, rollback switches back (file) |
| D-354 | merged | T-210c | uploads and outputs sealed at rest: AES-GCM per object under objects.key wrapped by the KEK, the seal file, seal-objects (file) |
| D-370 | merged | T-659 | one ingest stack: the adapter stays, dataplat is deleted by T-659b; the pid rule stays HMAC(site key, chart number); contracts, row quarantine, the gate record, the MPI as a `pid_alias` table and lineage move into the adapter (file) |
| D-355 | merged | T-211a | signed audit heads with the KEK-wrapped Ed25519 key, write-once off-box anchor folders, key rotation, the clock a doctor FAIL (file) |
| D-352 | merged | T-669 | hot documents as section files with a generated index; RUNBOOK section numbers in one table (file) |
| D-357 | merged | T-603 | prompt budgets from the model's context: the gateway gives each alias's context and refuses `prompt_too_long` before dispatch; callers size excerpts, full record, chart and the retry from it; the cache keeps complete answers only and keys on `max_tokens`; a note over the budget is flagged (`notes_over_budget`) (file) |
| D-351 | merged | T-116 | one forbidden-word list checked on every page, role, catalogue and template; a record field takes a neutral word; the intended-use statement on every PDF, XLSX, sheet and mail (file) |
| D-358 | merged | T-012b | `champion` only through `qualify`: expected weights per build, no trust on first use, install pins candidate, `--promote` from a record, PRODUCTION refuses an unqualified champion (file) |
| D-359 | merged | T-606 | injection hardening: every prompt a new version with the "text is data" rule; the guard's planted-instruction screen; contact lines masked before the criteria locator; PRODUCTION serves the newest qualified version (file) |
| D-360 | merged | T-108a | compose limits: a memory and a pids cap on every service, health checks, capped logs, the lake sized from its cap, the host watchdog that restarts an unhealthy service and audits it (file) |
| D-361 | merged | T-684 | clinical layout in ja and zh-TW: a font stack per language, CJK labels kept whole, the full page's sticky mark bar, the week page's first screen, registry words (file) |
| D-362 | merged | T-514 | a coded criterion row shows the record's own value, unit, date and code (evidence.coded, display only; latest first, at most three; an empty list says no record is behind the answer) on the patient page and the not-matched list (file) |
| D-363 | merged | T-643 | record inventory in `docs/validation/record-inventory.md`, mapped to every table the code creates; the release record carries it (file) |
| D-364 | merged | T-621 | amendment handling: effective date and IRB record per criteria version (a record, not a gate), screening on the version in force, the version on every mark, the re-screen list, schedule versions judged by visit date (file) |
| D-368 | merged | T-115 | EDC prefill controls: map row, dictionary entry and target on each draft and in the signed hash; map change supersedes, send re-reads the dictionary and holds back with reasons; one study per REDCap connection; stored re-entry result; signature beside each value; REDCap validation formats; ODM by the CDISC schema; https only; cassettes (file) |
| D-371 | merged | T-104b | one PostgreSQL major (16) for the db image, the demo and CI: `postgres_major` in `deploy/images.lock`, Debian 13 base, pgBackRest pinned from PGDG in the db image, `tools/ci_postgres.sh` checks `pg_config --version` (file) |
| D-372 | merged | T-676 | the FHIR package set from packages.fhir.org; TWPAS by `profiles.twpas_version` (1.2.5 until CGMH answers), the cache holds that version; extensions 5.4.0 and terminology 7.5.0 for the whole cache; supersedes D-63 (file) |
| D-369 | merged | T-212a | the mail boundary: `link` the default for patient files, no password zip for them outside DEV and TEST, the guarded download for named recipients, sender authentication fails closed and a failed check sends nothing (file) |
| D-373 | merged | T-214 | the GB10 profile as data (unmeasured), memory limits on the Spark, the dated driver hold, the two-device link (mutual TLS relay, the gateway no listener) (file) |
| D-376 | merged | T-676b | the TWPAS route is SNOMED CT `26643006` (oral), the code the IG's required value set lists, with no SNOMED CT description; amends D-342 item 4 (file) |
| D-377 | merged | T-108b | systemd units: the egress table saved by `apply` and restored closed before Docker at boot, the stack unit after it, the egress refresh and watchdog timers (file) |
| D-380 | merged | T-102b | roles: privacy office, monitor grant per study (enrolled subjects only), administrator without patient rows; opt-out and staff registers kept by steward or privacy only; SMO and CRO accounts name studies; delegation bootstrap closed (steward writes the first PI); IRB dates by hospital coordinator or logged PI with number and reason; role descriptions and menu from the matrix (file) |
| D-381 | merged | T-659b | one ingest stack, the removal: `services/dataplat` deleted from the tree; contracts, row quarantine, one gate record per night, `pidmap.pid_alias` and `lineage.json` in the adapter (`adapter/governance.py`); the e2e tools run the adapter (`tools/ingest_local.py`) (file) |
| D-383 | merged | T-305a | snapshot pinning: every job reads the lake snapshot it pinned at its first lake call (`Job.snapshot_date`); a snapshot older than `TB_LAKE_MAX_SNAPSHOT_AGE_DAYS` (3 in production compose, 0 = off) is refused with `LAKE-STALE` (file) |
| D-385 | merged | T-516 | PoC workflow fixes: the screening log follows the participant's consent state; a referral asked after Approach pauses it (no call task, no contact outcome) until the doctor agrees; the reason where Approach is absent; the demo seeds the IRB approval date and consent-form version; no consent implied by a TrialBox form (file) |
| D-386 | merged | T-622 | study state (start-up, open, paused, closed) as an event log; lists (SCREEN, MICROBATCH, COHORT) and N1/N2 mails only for an open study, a paused study still mails its participants' visits and SAEs; sponsor, protocol number, SIV date and registry ids (NCT, jRCT, UMIN-CTR, Taiwan) validated and printed on the screening log (file) |
| D-387 | merged | T-623 | the pre-screen log: every investigator mark is a row, approached or not, with its criteria version; a "not eligible" screen failure names the criterion not met and keeps its criteria version; five added screening-log columns (file) |
| D-375 | merged | T-307 | catalogue gaps after PR #80 and T-107: the instrument copyright register from public sources with site switches that need a licence reference, the phenotypes with a status (seven checked on the synthetic hospital), the Athena licence acknowledgements recorded (file) |
| D-382 | merged | T-632 | site inputs and a finished install: the site's mapping folder `deploy/site/mapping` looked up before the image, the feed folder `TB_SOURCE_DIR` mounted at `TB_SOURCE_MOUNT`, TLS on with the identity overlay, both cron files, the enrolment code printed, the judge named from the registry, an `https://` URL checked, exit 1 on a FAIL; the network sheet renders every overlay (file) |
| D-379 | merged | T-209a | box health: five checks (canary, backup, backup verified, disks, certificate) with thresholds in `tb_common.metrics`; one line in N2, a daily `HEALTH` mail to administrators, `/metrics` on the console and an optional Prometheus overlay; `backup-verify` writes `deploy/site/backup-verified.json` (file) |
| D-384 | merged | T-202 | the lake from OMOP: CI runs goldens and e2e-simple on both lake sources; the flip on the box is `tools.omop_parity flip` on an IDENTICAL report (its sha256 in the flag reason); export as of a time from record before-images (migration 6); site chart facts to NOTE_NLP (file) |
| D-389 | merged | T-108d | job cancel reaches the model calls; the SCREEN breaker (5 failures in a row, 300 s window); one declared `TB_*` list with a lint test; provisional, unmeasured container log caps (100 MB × 10) with a daily gap check; host log rotation (file) |
| D-390 | merged | T-635 | operations documents: RUNBOOK §21 to §25 (support model and the supervised remote session, DR targets until T-213b measures them, the lost-box list, patch policy, leavers), the missing pages as parts of §4, §12 and §22, each naming its T-213b drill; `docs/DEVELOPING.md` as the ninth document; the support sheet and a tabletop record per site; defaults until the owner answers TB-DR-09 Q1, Q2, Q5, Q6 (file) |
| D-378 | merged | T-212c | one PostgreSQL role per service (`tb_<service>`), each schema owned by a group `tbs_<schema>` that only the services in its list join; `trialbox` keeps the database for the host tools, without `CREATEDB`; passwords from `TB_DB_PW_<SERVICE>`; the `hapi` database closed to them (file) |
| D-402 | merged | T-685 | clinical UX polish: plain desktop banner, codes under technical details, one not-matched line per patient and criterion, coordinator worklist words, the 8-character code with the full pseudonym to copy, access keys A and I, no empty table header, the date format beside every date field, western calendar only (no 和暦 until a site asks, then in the XLSX export only) (file) |
| D-392 | merged | T-674 | model provenance: source, revision, recipe and licence file per local build (verifier: own copy of the publisher's quantisation, the default until the owner answers); the judge's chat template from the developer at a pinned revision, passed with `--chat-template` and recorded in the pin and the serving record; the challenger build queued (ledger S4); a second verifier candidate unmeasured (file) |
| D-393 | merged | T-677 | dependency batch 3: the monthly lock refresh, image digests checked, axe-core 4.14.0 and Playwright in a lock, REDCap versions per site; weights verified beyond install (`doctor --verify-all`, the nightly timer, the update) and the gateway comparing `/v1/models` with the pin at start (file) |
| D-395 | merged | T-310b | the study's PI records on the study set-up page whether the approved IRB text covers identified pre-screening across departments before referral (approval number, version, date; audited); without it the candidate page, its reveal and the API candidate are refused (403), on by default in VALIDATION and PRODUCTION (file) |
| D-396 | merged | T-619b | AE grading by CTCAE: an oncology study names its CTCAE version (5.0 or 6.0) and the built-in AE form records grade 1 to 5 with it; AE terms verbatim, MedDRA coding is the sponsor's; the `cdisc` ODM export adds CDASH tags and IE (the criterion a screen failure did not meet) and DS rows from the screening log; EX, SDTM, Define-XML and CT out of scope (file) |
| D-408 | merged | T-634 | host baseline: Ubuntu 24.04 LTS as the host system until the owner answers; the disk opens only with the TPM and a hospital Tang server (no TPM-only unlock, `luks_policy.py` FAILs one); the site keys sealed at install (`seal_keys.sh`, a TPM-sealed KEK by default); the input firewall and SSH (`deploy/hardening/apply.sh`); offline OS patch bundles (`apply_update.sh ospatch`); a stricter `check_host` (file) |
| D-391 | merged | T-205 | second factor at signing for a directory (OIDC) account: a fresh sign-in at the provider (`prompt=login`, `max_age=0`, `auth_time`, a second factor in `amr`, same subject), method `oidc+mfa`; a `reauth-` assertion counts only with the console's own key (SEC-16); neutral signature meaning text pinned in three languages (file) |
| D-397 | merged | T-624 | screening cadence: MICROBATCH screens new in-scope patients every week and, after each ingest, the new patients booked in its window; bounded by `TB_MICROBATCH_NIGHT_BUDGET` (patients a night, all studies; carry-over reported); MICROBATCH stores the console's candidate list (file) |
| D-398 | merged | T-511 | PoC-path words: help examples name the tester's own study (page, then delegation log) and the candidate, referral and EDC pages get help text; the referral selects say "Choose a doctor" / "Choose a department"; the EDC review shows the item name in the reader's language first, coded values with their words, a readable source line and the next step after "no REDCap record" (file) |
| D-399 | merged | T-302a | consent record: approved ICF versions as a list with history rows (team store version 2); the consent version checked on save as a logged warning; an enrolment or visit before consent flagged; re-consent on `rcN` events and the re-consent list; one way to record consent (the consent form) (file) |
| D-400 | merged | T-616 | inbound FHIR contract: the subset read is a table (`lake.flatten.READ`, DATA §1 part); `patient.deceased` (lake schema 4), the base cohort leaves out a deceased patient with no date, OMOP `death` dated the load night with type `death-date-imputed`; `medicationReference` resolved, MedicationStatement read, therapy period from `boundsPeriod` first; Observation by `effectivePeriod.start`; a source offset kept; `fhir_unread` in the ingest report (file) |
| D-401 | merged | T-108c | the mail outbox: a send key leaves `sending` in the same call (queued, failed, uncertain), a stale one becomes uncertain; an outage answers 202 so the job stays done; back-off retries; `trialbox mail status` and `mail resolve`; 200 mails per recipient a day, 10 refusal replies per sender a day; the mail intake limit per heavy job type (D-146 J-02) (file) |
| D-403 | merged | T-305b | all-history back-fill by year, newest first, resumable, the same NDJSON bytes as a full night (`adapter backfill`); a job's pin holds its snapshot (never rebuilt, never pruned while held); site publishes on `main` batched by `TB_SITE_PUBLISH_BATCH_SECONDS` and after the jobs that hold the snapshot; OMOP tombstones say `deleted at the source` (file) |
| D-405 | merged | T-209b | the support bundle: `trialbox support-bundle` writes one 0600 archive with a manifest; TrialBox's own service logs only (never PostgreSQL, HAPI or vLLM logs, `/data`, volumes, secrets, keys, backups or the audit chain); scrubbed, every line the data-handling scan flags removed and reported, the finished archive scanned again or nothing is written (file) |
| D-406 | merged | T-209c | admin screens remainder: backup and update tiles on `/admin`; links to `/ops/identity`, `/ops/flags` and the unused-account report `/admin/accounts` (also in the Monday health mail); local accounts end within 365 days; third-party logs collected apart as D3, kept 30 days; PostgreSQL logs no failed statement (file) |
| D-409 | merged | T-113b | the shared-quota profile on two MIG instances: `gpu_profile.sh` knows a B200 (`b200-no-mig`), registry builds and a pin job, the serving rule keyed on the MIG profile, `doctor --platform` checks `mig_instances` (not time-sliced, two of them) and `model_key` (model-guard and the key on the platform; a call without the key is refused); stand-in devices on kind (file) |
| D-394 | merged | T-211b | one audit writer: the services call `audit.append` (SECURITY DEFINER, owned by `audit_writer`) into the append-only `audit.journal`, no direct INSERT, UPDATE or DELETE; the `audit-writer` service alone writes the hash chain; the six service mounts read-only (file) |
| D-410 | merged | T-213a | the acceptance environment: `deploy/docker-compose.acceptance.yml` after the identity overlay with a test directory (LLDAP, LDAPS, digest-pinned), a real-shaped mail server (GreenMail, sign-in and TLS) and a test CA (hospital TLS mode); `tools/acceptance_env.py` prepares the files (the Authelia site template with acceptance values, synthetic accounts, 0600 secrets never printed), starts, checks and records (file) |
| D-411 | merged | T-318 | privacy documents per site in `docs/plan/sites/privacy/` and the incident plan `docs/plan/sites/incident-response.md`: severity S1 to S4, roles, clocks C1 to C9 (the vendor tells the hospital within 1 hour for S1), the six cases, first-hour list, templates in ja and zh-TW; the legal-basis memo is a slot (D-311 B26); the one-pager rendered by `tools/onepager.py` (file) |
| D-412 | reserved | the integrator | given to other cards and pull requests; their own rows replace this one as they land |
| D-413 | merged | T-628 | close-out and decommissioning (RUNBOOK §20): freeze by the audit chain, archive with SHA-256 sums verified on the hospital store, handover, crypto-erase before the NIST SP 800-88 Rev. 1 purge by medium, one certificate per medium (en, ja, zh-TW); `trialbox decommission-plan` lists every store and changes nothing (file) |
| D-407 | merged | T-620 | trial lifecycle Mediums: contact attempts per study (limit and days between, refused with a plain reason; at the limit the investigator decides); the request for the treating doctor as copy text and a one-page print in the doctor's language, the chart number only after a recorded reveal; randomisation fields on the enrolment form (no arm); possible deviations from the box's facts, confirmed as an entry or dismissed with a reason; deviation class and sponsor-report date (file) |
| D-414 | merged | T-302b | REDCap arms, events and repeating instruments: a visit names one row (`<event>`, `<event>__<instrument>__<n>`, `<event>__<n>`); the send places each value or holds it back with the reason (arm, designation, repeating instrument); a small evaluator of REDCap logic (never `eval`) holds back hidden values and compares calculated fields; erase hidden values only for what TrialBox wrote; ODM repeat keys; the simulator repeats (file) |
| D-415 | merged | T-629 | site realities: a death in the lake (`patient.deceased` or a date) takes the patient off every list at once and refuses marks and calls, a failed check stops contacts; the same patient in another study shown (named only to who may see it), enrolled elsewhere goes to "needs information"; the SAE type of the site's country only and required to open the study; a chart-number column Excel turned into numbers refused at import, naming the column (file) |
| D-388 | merged | T-604 | the perimeter is checked: the gateway stops in PRODUCTION on topology A when a perimeter endpoint resolves off the box and re-resolves while it runs; `EGRESS_EXTRA` for the gateway only to routing-table endpoints; no cloud egress rule; egress re-applied on container start; no direct model client in PRODUCTION; job step sent as `X-TB-Step`; gateway reads need the token (file) |
| D-416 | merged | T-633 | day 2 on the platform: CronJobs for the nightly backup (the appliance's `.tbbak`, the dump by the database image in one snapshot, to the claim `backup-share`), the daily logs and audit archive, a suspended restore run through a pg spool; digest updates by an update overlay and its rollback; the database's claim on a block class; `doctor --platform` checks `backup_job`, `log_job`, `db_storage`, `pod_limits` (file) |
| D-417 | merged | T-619a | standards conformance in CI: TW Core slices with TW Core code systems (ICD-10-CM TW edition by date, NHI drug, service and department codes) behind `fhir_profiles: tw-core`, `boundsPeriod` written; `twcore_rules.json` from the pinned package (no SNOMED CT codes); JP Core 1.2.0 diff printed (pin stays 1.1.0); instants in the site offset at ingest (STD-070); CQL reads `Quantity.comparator` as the SQL does; CI job `standards` (HL7 validator on 200 resources, five rulesets translated and evaluated, UTC and censored edge cases) (file) |
| D-418 | merged | T-619c | data and standards Mediums, one PR per part: (a) units of one kind (mass, substance, number, enzyme, international units) convert by definition in the Python, SQL and CQL engines within a factor of 1,000, one UCUM and scale table in `labunit`; (b) a `fhir_bulk` presence word (`valueString` 陽性, 陰性, Non-reactive) read into the LOINC answer, tagged, counted; (c) a numeric lab criterion with no unit or an unconvertible unit flagged `value_unit_missing` / `value_unit_unconvertible` at compile (file) |
| D-419 | merged | T-316b | the consortium code-map registry: layout (`registry.json`, `concepts.csv`, `maps/`, `releases/`), TB-SHARED registry band 2,005,000,000 to 2,009,999,999 with a range per owner, ids never renumbered nor reused, only code systems the licence register lets ship, releases as a refdata pack part with a signed record (author and approver two people), loaded in one transaction; `omop.vocab.release` names it (file) |
| D-421 | merged | T-210a | Windows with WSL2: `host_facts.ps1` reads language-neutral facts, `wsl2_policy.py` is the one judge for `preflight.ps1` and `check_host --wsl2`; BitLocker with TPM+PIN, page file, hibernation, WSL swap FAIL always; recovery escrow, RDP, Windows Update restarts, the start-at-boot task FAIL in VALIDATION and PRODUCTION (file) |
| D-423 | merged | T-119 | cloud hygiene remainder: the GPU run's door key and TLS key in Secret Manager (`tb-gpu-door`, one version per VM and run, destroyed once collected), never metadata; the door HTTPS on 443 with the driver's self-signed certificate pinned, no port 80 (the older GPU scripts on loopback); the driver refuses a firewall that opens tcp:80 to the VM; the demo VM's password from Secret Manager, the hosted demo refuses a secret in its metadata; the rehearsal gains the `bucket` case and captures the serving record (file `D-423-cloud-hygiene.md`) |
| D-425 | merged | T-102c | every console call site asks `permit`: no inline role check (grep test), the team fallback (`h.may is None`) removed; new rows `report.sponsor_form`, `report.office`, `study.setup`, `site.setup`, `sae.ack`, `delegation.check`, `referral.answer`; screening-log page, XLSX and API ask one question (ROLE-017) (file `D-425-permit-call-sites.md`) |
| D-426 | merged | T-201 | clinical conflicts: a conflict is withdrawn only when two or more sources agree again, never when one goes silent (DATA-011); the steward's page `/data/conflicts` (matrix action `conflicts.resolve`, steward only) keeps a claimed value or unknown with a reason; the study's REDCap page renamed "Trial-record differences" (FIT-018) (file `D-426-clinical-conflicts.md`) |
| D-427 | merged | T-112a | data operations, first half: schema `dataops` with `batch` (one row per ingest run: source, snapshot, attempt) and the append-only `batch_step`; states LANDED, VALIDATED, MAPPED, PSEUDONYMISED, PUBLISHED, HELD, FAILED and REJECTED (a steward's reject); HELD is left only by a steward's accept or reject with a reason; a batch row without its step is refused at commit; the adapter writes the row with the night's audit event (file `D-427-dataops-batches.md`) |
| D-428 | merged | T-114 | G1b on the owner's B200: an offline bundle (`tools/b200_qualify.py build`, code by `git archive`, images, weights, a manifest of sha256) and one script the owner or the named operator runs (`tools/b200_qualify.sh`, no gcloud, no network); a host fingerprint stamped into each serving record; two MIG layouts; the G1b record says the host is not CGMH's and passes only from a commit without stand-ins; `doctor --platform` `host_match` warns when the host differs (file `D-428-g1b-on-the-owners-b200.md`) |
| D-429 | merged | T-607 | the embedder under control: one mode name the wizard and the embed service share (`model`, `hash`, `http`); `hash` refused by the embed service in PRODUCTION; one registry build `e-embed-1` pinned by `pin_model` on the `embed` endpoint, safetensors only; the service loads only weights that match the site pin; criterion for the choice "safetensors weights from the publisher", the choice itself from G1 (file `D-429-embedder-under-control.md`) |
| D-430 | merged | T-309 | break-glass to OD-5, one rule: an account outside its own rights (administrator, or an investigator the delegation log does not reach) reads one patient or one job only under its own 60-minute grant with a reason; no second person; a grant for what the account already reads is refused; every use is a row the steward's review list shows; rows `breakglass.open`, `.read`, `.study` (file `D-430-break-glass-one-rule.md`) |
| D-431 | merged | T-605 | prompt text out of stores: no D3/D4 prompt or output text in the PRODUCTION trace store (sha256 and size only); a prune on every write at most hourly; prunes touch only rows written from now on (`policy` 1), existing rows wait for the owner's ruling; schema-violation audit detail and error hold path and rule only; vLLM log level WARNING; a gateway allow-list of upstream body fields (file `D-431-trace-hygiene.md`) |
| D-432 | merged | T-319 | shared-host isolation drills: three more live probes (no egress outside the allowlist, a pod over the GPU quota refused, running images are the release digests); one extra egress host fails `doctor --platform` in CI; the platform KEK as a `kms` back end of `kek.py` (Vault / OpenBao transit, `TB_KMS_TOKEN`, https only, tested against a mock); `tools/trialbox/noisy_neighbour.py`; the drill record "not run" in RUNBOOK §17 (file `D-432-isolation-drills-and-platform-kek.md`) |
| D-438 | merged | T-103 | one reveal path: `console.reveal` is the only console code that obtains a chart number (patient page, `/api/v1`, job page, candidate page, referral print; the EMR link calls it next); `permit` (`id.reveal`, the delegation log) or the break-glass rule, no inline role; a reason on every surface and words for "other"; one per-person hourly cap across all surfaces in the team store, the orchestrator's cap in `orch.id_limits`; one audit shape for a reveal and for a refusal (file `D-438-one-reveal-path.md`) |
| D-441 | merged | T-206a | opt-out worker v1: one register (the hospital registry's refusals copied in by the worker), read by every screening path (NAV and CASE added); a tick every `TB_OPTOUT_WORKER_MINUTES` clears the stores of a registry later cards add to: the candidate pool, open candidates withdrawn (consented and enrolled kept, OD-8), OMOP `tb_withheld` with an immediate tombstone and later loads keeping the patient out; a lift restores nothing by itself (file `D-441-optout-worker.md`) |
| D-447 | merged | T-109b | identity leftovers: an offline breached-password list (operator file, binary search), password history of five, `doctor` check `console_mfa` (FAIL in PRODUCTION without MFA), WebAuthn through the identity provider with a stricter `amr` rule, a single-use actor assertion (SEC-17) (file `D-447-identity-leftovers.md`) |
| D-446 | merged | T-310a | the weekly PI sample of ten "criteria not matched" patients per study (schema `tuned`, table `tuned_patients`), send-back to the PI list, the list held in PRODUCTION until the site's check is recorded; rows `notmatched.sample`, `.send_back`, `.check` (file `D-446-pi-sample-not-matched.md`) |
| D-435 | merged | T-302d | ODM import and sponsor readers: an imported ODM value is an open draft citing the file (sha256, path), confirmed and signed by a person, never a signed row; only the same item's open draft is replaced; the file is read with expat (no DTD, no entity), bounded, decoded by D-215, refused whole with a named reason (duplicate OIDs and values, repeat keys, unknown items, a failed check); D-414 visit names; the sponsor's layout per study (`sponsor_layout`, datacore version 8) names the screening log's columns and reads the weekly sheet into lifecycle step proposals a person confirms (file) |
| D-436 | merged | T-303 | the monitor's SDV page: the console reads the data core's nested `subject` (the grant opened no enrolled subject); `/studies/{rs}/monitor` lists enrolled subjects and the visit records; `/studies/{rs}/monitor/{record}` shows per decided CRF value its EDC citation and trail, nothing else of the record, printable as the source-reference sheet; the visit record (`team.monitor_visits`, team version 3: date, CRA, subjects verified, findings) through row `monitor.visit`; every read audited with the visit; opted-out never shown; no chart number (file `D-436-monitor-sdv.md`) |
| D-437 | merged | T-212b | the gateway routes on the verified caller: `X-TB-Caller` must be a name the token's service may claim (`service_callers` in `models/routing.yaml`), else `caller_unverified` (403, audited); no token identity outside DEV/TEST is refused; `/v1/serving/activate` and `release` for `serving_control` services only; the model key in `deploy/secrets/model/llm.key` (a compose secret for the gateway and model-guard) and in `trialbox secrets rotate` (file `D-437-gateway-verified-caller.md`) |
| D-445 | merged | T-608 | the gateway under load: one timeout budget (gateway to model 5 s / 180 s, 210 s per call, callers 240 s), one retry on a dropped connection only; slots per endpoint from the serving record; chat on its own thread limit, `model_busy` at once when full; a breaker per endpoint on `/readyz`; the swap hold names its service (no on-demand wake or `touch` across a hold); `service` on every gateway audit record; the judge schema checked in `GatewayJudge`; judge_eval and bakeoff say what they do not measure; the model key's `.env` copy refused when it differs (file `D-445-gateway-under-load.md`) |
| D-443 | merged | T-112b | data operations, second half: the steward's `/data-ops` page (sources as lights, held nights, the ingest history filtered and paged by the store, one night's trail) and `/api/v1/data/*` (session checked before the body); rows `dataops.view` (steward, administrator) and `dataops.decide` (steward); reject now, accept refused until the lake's promotion is wired; the readiness page reads the held light from `dataops` and names the feed tier it serves (file `D-443-dataops-console.md`) |
| D-439 | merged | T-203a | the vector store in pgvector: schema `vec` (`embedding` one vector per masked chunk sha and model, `note_chunk` with offsets), the dimension from the embedder (unsized `halfvec`, an HNSW expression index per model), chunks made after the T-600 PHI pass by a sentence-aware chunker, `VecStore.search` for T-203b and `VecStore.delete_patient` for T-206b, in the backup drill (file `D-439-vector-store.md`) |
| D-440 | merged | T-204 | the patient twin: `tb_patient_profile` v1 (schema `profile`), one canonical JSON per patient and version from a pinned lake snapshot, every layer stamped (`null` until built), every item citing table, row hash and date; never assembled for an opted-out patient (`ProfileStore.erase` for the opt-out worker); built after each passed ingest for study patients; `GET /api/v1/studies/{rs}/patients/{pid}/twin` through `permit` (`profile.read`, `Helpers.reads`, break-glass), one `console.twin_view` audit event per read, `setpoint` and `gap` only with `profile.research_layers` (file `D-440-patient-twin.md`) |
| D-449 | reserved | T-203b | S2b reads the vector store behind the flag `vec.s2b` (off by default): the pinned snapshot's notes checked against the stored chunks, the vectors of one model, else the on-the-fly path, recorded per patient; the parity record (file `D-449-s2b-vector-store.md`) |
| D-448 | merged | T-315a | the journeys as the PQ script: one automated journey per role on the in-process box (`tests/e2e/journeys/`), steps with expected results, expected failures naming their card; the re-run list after a long break (RSK-64) as data beside them (file `D-448-journeys-pq-script.md`) |
| D-444 | merged | T-657 | API twin check: every state-changing `/api/v1` route checks the session (and the permit that does not need the body, declared with `@before_body`) in a dependency before body validation (ROLE-019); a route-walk test pairs every state-changing page route with an `/api/v1` twin or a line with a reason (FIT-019, the gap listed to shrink); a study-scoped account naming another study on `/site` and `/api/v1/site/*` gets 404 (ROLE-020) (file `D-444-api-twin-check.md`) |
| D-448 | reserved | T-691 | held for T-691: the nightly backup without a pause: what "point in time" means when the services keep running (review 2026-11-11-scale-timeouts F-02) |
| D-449 | reserved | T-689 | held for T-689: what a batch model call does on a refusal or an outage: wait and retry bounded per job, the failure share checked while the job runs, the pair and token budgets (F-04, F-13, F-16; T-698 reads it too) |
| D-450 | reserved | T-693 | held for T-693: the ingest gate's validation sample: an absolute cap per resource type beside the 1 % (F-06) |
| D-451 | reserved | T-704 | held for T-704: the night as a chain: order of ingest, weekly jobs, backup and retention; the microbatch allowance and its sharing (F-32, F-33) |
