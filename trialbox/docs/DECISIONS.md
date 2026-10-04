# Decisions log

Each entry: decision, reason, consequence. Entries are appended per phase; nothing is silently dropped.

## Phase 0

**D-01 Repository location.** TrialBox lives in `trialbox/` inside this repository (the host repo's existing content is
untouched). The spec's monorepo root `trialbox/` is that directory. `rulesets/` is a plain directory in the monorepo
(not a submodule) holding the checked-in rulesets; at runtime the compiler works on a git repository initialised from it
in the `rulesets` volume (`TB_RULESETS_DIR`).

**D-02 Docling vs marker (§12.2).** Docling. Production `doc-parser` image installs `docling` and bakes its layout/table
models at build time. CI and the sandbox cannot download Docling models (Hugging Face is unreachable), so
`doc_parser` has a deterministic *lite* backend (pypdf + python-docx + heading heuristics) that is selected
automatically when Docling is not importable (`TB_PARSER=auto|docling|lite`). Both return the same `ParsedDoc`
contract. The 5-Chinese-PDF table-recall comparison is scripted in `tools/parser_compare.py` for site runs.

**D-03 `$evaluate` vs `$evaluate-measure` (§12.2).** `Library/$evaluate` (HAPI JPA starter 8.12, CR module,
cql-to-elm 5.4.0). Spike result in this sandbox: ~77 ms per patient per library after warm-up, so 1,000 patients ×
1 call at 8-way concurrency ≈ 10 s of server time — well inside §11.3. `Measure/$evaluate-measure` is kept behind
`TB_CQL_EVAL_MODE=measure` (one cohort Measure per ruleset, individual report per subject).

**D-04 7z vs S/MIME (§12.2).** `ATTACH_PASSWORD_MODE=zip` (7z AES-256 via py7zr, password mailed separately) is the
default because it needs no recipient certificates; `smime` (CMS sign + encrypt with `cryptography`) is selectable.

**D-05 Python packaging and images.** One `pyproject.toml`; packages are discovered from `libs/` and `services/`.
All Python services share one base image (`trialbox-py`, multi-arch `python:3.12-slim`) and differ by command.
Heavy extras get their own images built FROM it: `doc-parser` (+docling), `embed-service` (+sentence-transformers,
CPU torch on arm64 and amd64), `criteria-compiler` (+JRE 17 + cql-to-elm jars). No x86-only wheels are used
(verified: duckdb, duckdb-extension-fts, pyarrow, cryptography, numpy, matplotlib all ship manylinux aarch64 wheels).

**D-06 FHIR ids for ValueSets.** FHIR ids may not contain `_`, so ValueSet resource ids are `<RULESET>-<NAME>` with
`_` → `-` (e.g. `GZQO-VS-URATE`); canonical url `http://trialbox.local/fhir/ValueSet/<id>`. CQL keeps the
`valueset "VS_URATE"` local name, and the IR keeps `"valueset": "VS_URATE"`.

**D-07 Reserved ValueSet id `NONE`.** The IR schema requires `valueset` on every atom; demographic atoms (age/sex)
have no codes and use the reserved id `NONE`. Derived atoms reference a ValueSet listing their component codes
(e.g. `VS_BMI_COMPONENTS`).

**D-08 Tag naming.** One git repository holds all rulesets, so `v{version}` would collide; tags are
`<RULESET>/v<version>` and draft branches are `draft/<job_id>`.

**D-09 Pseudonymous patient id.** `pid = hex(HMAC-SHA256(site_key, MRN))[:32]` (128 bits). Full 64-hex ids exceed
the subject-grammar value limit (32 chars) used by `SUBMIT ... pid=<pid>`; 128 bits keeps collision probability
negligible (< 1e-25 for 10^7 patients).

**D-10 pid map encryption.** SQLCipher has no maintained linux/arm64 wheel, which would break the GB10 build.
`secrets/pid_map.sqlite` stores `pid → AES-256-GCM(MRN)` using `cryptography`; the 32-byte key file is sealed by the
TPM (`systemd-creds encrypt --with-key=tpm2`) and unsealed into tmpfs at boot (RUNBOOK §Secrets).

**D-11 FHIR model library.** `fhir.resources` ≥ 7 ships R5 + R4B + STU3 only (no R4 4.0.1). TWPAS bundles are built
with the R4B models (identical for the resources used: Bundle, Claim, Patient, Coverage, Practitioner, Organization,
MedicationRequest, Condition, Observation, DiagnosticReport, DocumentReference) and validated as R4 by the HL7 validator.

**D-12 Embeddings in CI.** Hugging Face is unreachable from CI, so `embed-service` has `TB_EMBED_MODE=bge-m3|hash`.
`hash` is a deterministic 1024-d signed feature-hash of CJK bigrams and Latin tokens (L2-normalised). Same API,
same dimension; retrieval quality is lower but sufficient for synthetic fixtures. Production uses bge-m3.

**D-13 LLM modes.** `TB_LLM_MODE=vllm|llamacpp|stub`. `stub` (`services/llm_stub`) is an OpenAI-compatible server that
replays cassettes keyed by `(prompt_id, input_sha)` and otherwise answers with deterministic rules (judge: pattern
rules over excerpts that always quote an exact excerpt sentence; concept_map: exact/synonym match; draft_doc:
template sentence over the input facts; ir_extract: cassette or "every line is a `human` criterion"). It exercises the
exact same `chat_json` code path, schemas and post-processing. LLM-quality tests (`-m llm`) need a real model.

**D-14 DuckDB FTS offline.** DuckDB downloads extensions at runtime, which the deny-by-default egress forbids. The FTS
extension is installed from the `duckdb-extension-fts` wheel (version-locked to `duckdb`), amd64 and arm64.
Chinese/Japanese text is pre-tokenised into character bigrams (Latin words kept whole) before indexing because the FTS
tokenizer splits on whitespace.

**D-15 Subject grammar extensions.** The spec uses `SUBMIT` (§8.4), CRC feedback CSV (§8.2) and `COHORT MERGE` (§8.3)
but the ABNF omits them. Added: `cmd += "SUBMIT" / "FEEDBACK"`, `key += "pid" / "bundle" / "site"`; `COHORT MERGE`
is `COHORT` with the reserved ruleset token `MERGE`. Job `type` enum gains `SUBMIT`, `FEEDBACK`, `CANCEL`,
`RETENTION`, `CALIBRATION` (all scheduled/command jobs are first-class jobs so they are audited).

**D-16 Mail servers in test.** MailHog has no IMAP, so the test profile runs GreenMail (intake IMAP + SMTP) and
MailHog (sink for the box's outbound SMTP, inspected over its HTTP API).

**D-17 Shared date semantics (CQL ≡ SQL).** All windows are inclusive day windows on the hospital-local calendar date
of the event (`date from` in CQL, `::DATE` in DuckDB). Missing window ⇒ `(-∞, IndexDate]`. `latest` ties are broken by
resource id. Code-presence atoms (condition, medication, procedure, encounter, claim, report, observation without
`value`) are never null (absence = false); value atoms (`observation` with `value`, `derived`, `demographic`) are null
when the needed data is absent. Medication exposure clips each validity period to the window, merges periods whose gap
≤ `gap_days`, and returns the longest island in days (inclusive).

**D-18 Unknowns in FEAS funnels.** Funnel `remaining` counts patients for whom every applied inclusion is `true` and no
applied exclusion is `true` (unknown inclusion ⇒ not remaining; unknown exclusion ⇒ not excluded). The count of
patients dropped only because of unknowns is reported per step in `notes`, and an automatic sensitivity variant
`unknown_as_pass` is always included.

**D-19 Bounded LLM extract schema.** `llm_extract_output.schema.json` limits boolean nesting to depth 3 (no recursive
`$ref`) so regex-based guided-decoding backends (outlines) can compile it; the Criterion IR schema itself stays
recursive.

**D-20 Criterion id pattern.** The spec's id pattern `^[A-Z0-9]+-(INC|EXC|REN|DOC)-…` cannot express its own
`RA-BIO` ruleset; it is widened to `^[A-Z0-9]+(-[A-Z0-9]+)*-(INC|EXC|REN|DOC)-[0-9]{2,3}$` (strict superset).

**D-21 MinIO image.** `minio/minio` is no longer pullable from Docker Hub (and quay.io/cgr.dev are unreachable from the
build network). The `minio` service runs the multi-arch community MinIO build `pgsty/minio` (amd64 + arm64, MinIO
RELEASE.2026-08-04), pinned by digest; the S3 API and the `minio` Python client are unchanged. Sites with a licensed
MinIO image override `MINIO_IMAGE`.

**D-22 Small-cell zero.** Counts 1–4 are suppressed to `<5`; 0 is shown (it identifies nobody and keeps funnels readable).

**D-23 No OS packages in Python images.** Debian mirrors are unreachable from the build network used for this
implementation and every OS package is extra attack surface on the appliance. Images therefore install wheels only:
git operations use `dulwich` (pure Python), 7z AES-256 uses `py7zr`, PID 1 is compose `init: true` (tini), PDF fonts
are copied from the repository's `deploy/fonts/` (fetched by `tools/fetch_fonts.sh`), and the compiler's JRE 17 is
copied from the multi-arch `eclipse-temurin:17-jre` image in a multi-stage build.

## Phase 1

**D-24 Synthetic codes.** ICD-10-CM and ATC codes in fixtures are real classification codes; NHI drug codes and NHI
order codes are synthetic placeholders in the NHI format (the site loads its own tables). LOINC codes marked
`verify` in `lab_local_to_loinc.csv` (anti-HBc 16933-4, IGRA 71774-4) must be confirmed by the site laboratory.
DAS28 components (TJC28, SJC28, patient global) use the TrialBox local system
`https://trialbox.local/fhir/CodeSystem/clinical-score` because no LOINC code was confirmed for them.

**D-25 Verdict semantics.** `C_<ID>` is always the criterion *predicate* (for exclusions: "the excluded condition is
present"). The `judge` prompt answers the criterion's yes/no `note_question` (`pass` = yes, `fail` = no). Candidate
lists show verdicts from the eligibility perspective: inclusion pass = predicate true; exclusion pass = predicate
false. Note ground truth in fixtures is stored as yes/no/unknown of the predicate.

**D-26 Offline FHIR package cache.** packages.fhir.org is unreachable from the build network and the appliance has no
egress, so `tools/fetch_fhir_packages.py` builds the HL7 validator cache from the npm mirror of HL7 packages
(`@hl7/hl7.fhir.r4.core`, `hl7.terminology.r4`, `hl7.fhir.uv.extensions.r4`, `tw.gov.mohw.twcore`, ...). The validator
pins some dependency versions the mirror does not carry; those are installed as version aliases (relative
symlinks) of the nearest available release, and two cyclic/unused dependencies are dropped (terminology ↔ extensions;
TW Core → IPS/SDC, used only by profiles TrialBox never claims). The validator runs with `-tx n/a -no-http-access`,
so terminology bindings are reported as warnings, not errors (documented limitation; sites with a local terminology
server can pass `-tx`).

**D-27 Code-system URIs.** TW Core 1.0.0 publishes its local code systems (ICD-10-CM-TW, NHI medication, ...) as
`content: complete` with example-sized concept lists, so emitting those URIs makes the validator reject real codes.
TrialBox emits `http://hl7.org/fhir/sid/icd-10-cm`, `http://www.whocc.no/atc`, LOINC/UCUM, and
`https://trialbox.local/fhir/CodeSystem/{nhi-drug,nhi-order,department}` for NHI lists; TWPAS bundles re-code to the
IG's required systems at build time (phase 6).

**D-28 `ssmix2` source.** Not in v1.0 for Taiwan sites; the reader raises an explicit `NotImplementedError` pointing to
the CSV route with a JP Core mapping (`services/adapter/mapping/jp_core/README.md`). `fhir_bulk` is implemented
(pseudonymises ids/references and drops direct identifiers).

**D-29 Vital signs as panels.** The HL7 validator enforces the R4 vital-signs profiles: blood pressure is emitted as a
85354-9 panel with 8480-6/8462-4 components (TW Core `Observation-bloodPressure-twcore`), body height/weight with
exactly one LOINC coding. The lake flattens components into their own `observation` rows (`oid = <id>.<code>`), and
the CQL compiler retrieves component codes through the panel (phase 2).

**D-30 Resource ids.** All non-Patient resource ids are `HMAC-SHA256(site_key, "<Type>|<source key>")[:32]`, so no HIS
key (encounter number, order number) leaves the adapter; Practitioner ids stay the staff id (needed for scoping).
Patient resources carry one pseudonymous identifier (`https://trialbox.local/fhir/sid/pid/<site>`), never MRN or
national ID; names, phone numbers and national IDs in the source are dropped.

**D-31 Volumes.** Compose uses one named volume per concern (lake, audit, orchestrator, rulesets, mail, secrets) mounted
only into the services that need them; mount points are pre-created in the image with the service uid (10001).

## Phase 2

**D-32 What is compiled.** Only `class=structured` criteria are compiled to CQL/SQL. `note` criteria are decided by the
`judge` prompt over retrieved excerpts and `human` criteria are asked; their `logic` (required by the IR schema)
documents the structured proxy used in `fallback` text and is never evaluated. Reviewer-rejected criteria stay in
`ir/` with `review.status=rejected` and are excluded from the compiled artifacts.

**D-33 Equivalence population.** The §6.4 gate samples 200 patients (100 random + 100 with any hit, seeded by
ruleset|version) from the current lake snapshot and evaluates the same patients in fhir-store (the two are loaded from
the same NDJSON snapshot). For vendor-shipped rulesets `tools/build_rulesets.py` additionally records the synthetic
sample as `tests/patients.ndjson` and the CQL verdicts as `tests/expected.json` (keyed by synthetic MRN); CPU CI
replays the checked-in SQL against `expected.json` on every run (`tests/integration/test_ruleset_expected.py`), so
CQL≡SQL is regression-tested without a JVM.

**D-34 Content-addressed CQL versions.** HAPI CR caches compiled libraries by name+version and ValueSet expansions by
url+version. Library versions are `<semver>-b<sha8(cql)>` and ValueSet versions `<semver>-v<sha8(compose)>`, and the
CQL `valueset` declarations pin the version, so any content change is evaluated fresh (found when a stale expansion
made the gate fail).

**D-35 Terminology mapping order.** (1) exact match on the concept name; (2) curated synonym/grouper table on the
concept name, then on the model's synonyms; (3) exact match on the synonyms (flagged `needs_review`); (4) LLM
`concept_map` over the top-20 lexical candidates (`needs_review`). Groupers must win over example drugs listed as
synonyms (the planted-state oracle caught "urate-lowering therapy" losing benzbromarone).

**D-36 Ruleset profiles.** Site configuration of a ruleset (title, sponsor, scopes, routing, variants, TWPAS program)
lives in `rulesets/profiles/<ID>.yaml` and is merged into the manifest at compile time; compiled artifacts are never
hand-edited.

**D-37 Review decisions.** `review.xlsx` pre-fills `decision=approve`. An explicit approve resolves
concept-mapping review flags; equivalence failures and missing ELM always block. `edit` with `edited_text`
re-extracts that line; `edited_class` alone switches the class (and creates a default question). Max 3 rounds
(`max_rounds` status). Changed criteria keep their id across versions; new criteria get the next id per kind.

**D-38 ParsedDoc extensions.** `ie_block` also carries `renewal` and `documentation` lists (NHI rules) and `refs`
(text -> section reference); `ParsedDoc.warnings` reports OCR/density issues.

**D-39 Stub cassettes.** The stub's `ir_extract` returns the gold extraction for known ruleset ids (and test aliases
`<ID>-<suffix>`), matching criteria by normalised text; unseen lines go through a small pattern extractor
(BMI/eGFR/DAS28/HbA1c/urate/age) and otherwise become `human` criteria. Gold extractions double as the LLM-layer
gold set (`services/llm_stub/cassettes/ir_extract/`).

## Phase 3

**D-40 FEAS funnel semantics.** The approved ruleset SQL is evaluated at every month-end of the lookback (default 36)
and reduced per patient inside the lake in one query. Population = patients with ≥1 encounter in the lookback
(optionally restricted to departments: `dept=` option or `scopes.feas.population=department`). A patient *remains*
after step *k* when inclusions 1..k are `TRUE` and exclusions 1..k are not `TRUE` at **some** month-end (D-18).
`note`/`human` criteria are listed with `applied=false` ("not applied in counts"). The `unknown` column counts, for an
inclusion, patients who reached the step, never passed and never had a known value there; for an exclusion, patients
kept only because no value was recorded. Monthly new-eligible = first eligible month-end per patient, shown for the
last 24 months after a 12-month wash-out (so prevalent cases do not inflate month 1).

**D-41 Sensitivity variants and simulation.** Threshold variants (`variant=bmi:24,25,27`, manifest `variants:`; the
subject option replaces the manifest entry with the same key) are applied to modified IR copies rendered by the *same*
SQL template generator and joined to the approved SQL (no LLM, no hand SQL); keys are a derived value (`bmi`, `egfr`,
`das28`, …) or a criterion id (`INC-08`). `unknown_as_pass` is always added. Enrolment simulation (1,000 seeded
iterations; seed = sha of ruleset|version|snapshot|run date|lookback): reach ~ Beta(r·κ, (1−r)·κ), accept ~
Beta(a·κ, (1−a)·κ) with κ = 20 (default rates) or the number of contacted patients (calibrated); prevalent eligible
patients present uniformly over 12 months, new eligible arrive Poisson(mean of the last 12 months); enrolment capped
by the summed investigator capacity with carry-over; low/mid/high = P10/P50/P90.

**D-42 Unsuppressed counts stay inside.** The FEAS job also writes `<stem>.raw.json` (unsuppressed counts), tagged
`phi` and never mailed, so the manual-vs-system harness (`tools/funnel_compare.py`) can compare exact numbers. It is
hashed and audited like every output.

**D-43 Reports.** PDFs are built with reportlab (`rl_config.invariant=1`) and embedded Noto Sans TC/JP static
instances generated from the OFL variable fonts by `tools/fetch_fonts.py` (copied into the image at
`/opt/trialbox/fonts`); charts are matplotlib PNGs without metadata; XLSX/DOCX are re-zipped with fixed timestamps
(`tb_common.deterministic`). Re-rendering a job is byte-identical; `feasibility_result.json` is identical across jobs
with the same inputs (PDF/XLSX differ only by the job id in the footer). Suppressed months are drawn as an open marker
with a 1..t−1 range bar, never as a value.

**D-44 Review mails carry a valid command.** The review mail subject is `APPROVE <ID> version=<v> -- review round n,
job <id>`, so a plain reply (`Re: …`) parses; a reply with any other subject is matched through `In-Reply-To` against
the gateway's sent-message index. `APPROVE` without `version=` targets the newest draft awaiting approval.

**D-45 Mail authentication and replies.** The top-most `Authentication-Results` header must show `spf=pass` or
`dkim=pass` and no `dmarc=fail`; with `TB_MAIL_AUTHSERV_ID` set, headers from other servers are ignored (forged
headers). Unknown senders get a generic reply only when their domain authenticated (no backscatter). Allowlisted
senders get the precise reason (grammar, permission, rate limit). Gateway and orchestrator both enforce permissions and
the 20 jobs/sender/day limit. Received/Failed/Status mails never go outside internal domains.

**D-46 Attachment encryption mode.** `settings.attachment_encryption` (site policy) wins over `ATTACH_PASSWORD_MODE`.
`zip`: one 7z (AES-256, encrypted headers) per message, a fresh random password per message, mailed separately to
each recipient. `smime`: CMS signed with `secrets/smime/site.{crt,key}` and enveloped (AES-256-CBC) for every
recipient certificate in `settings.smime_certs`; a recipient without a certificate fails the send. Any `phi`
attachment forces encryption; `phi` to an address outside `internal_domains` is refused by the gateway (422) and by
the orchestrator before anything is sent (routes are checked for all deliveries first).

**D-47 Job execution.** SQLite job store (`jobs` mirrors the Job contract; `queued`/`cancel` flags), 4 worker threads,
FIFO. `STATUS`/`CANCEL` run in a fast lane at creation (never queued behind long jobs). A job interrupted by a restart
is re-run from the start (scenarios are idempotent: outputs are keyed by job id). Jobs waiting for approval are
re-queued by the `APPROVE` that approves their ruleset version; a rejection or the 3-round limit fails them.
Scheduled runs are jobs requested by `scheduler` (no Received/Done mails; failures go to `settings.site.contact`);
types whose scenario is not yet implemented are not scheduled.

**D-48 GreenMail login.** GreenMail's login for `trialbox:trialbox@hospa.test` is the local part (`IMAP_USER=trialbox`);
production uses the mailbox's real login name.

## Phase 4

**D-49 Structured engine for screening.** SCREEN/MICROBATCH evaluate structured criteria with CQL
`Library/$evaluate` per patient in fhir-store (8 concurrent calls), loading the approved Library/ValueSets first when
fhir-store lacks that exact content-addressed version. `TB_SCREEN_ENGINE=sql` (and in-process tests without
fhir-store) evaluates the *same approved ruleset SQL* in the lake; the §6.4 gate guarantees ≥98 % agreement. Every
evaluation is audited (`screen.evaluated`: engine, index date, patients, tiers, judge model/prompt).

**D-50 Tiers.** Per D-25 verdicts are from the eligibility perspective. `excluded`: any structured criterion fails or a
note criterion fails with confidence ≥ `tier_high_confidence`; `high`: every structured and note criterion passes
(note confidence ≥ t), only `human` criteria pending; `review`: everything else (unknowns, low-confidence notes, a
low-confidence note *fail*). Actions = the IR `action` of every unknown / pending / low-confidence criterion.
Excluded patients are not listed (counted in the summary). Rows sort by next appointment, then tier.

**D-51 Note retrieval.** Query = `note_question` + zh-TW/ja equivalents of the criterion's English keywords
(`scenarios/terms.py`); window `[index−365 d, index]` narrowed to the IR window; k = 5; ≤ 2,500 tokens (CJK ≈ 1
token/char, Latin ≈ 4 chars/token), newest first. When the structured candidate set is ≤ 100, an `unknown` verdict is
retried on the full record (all notes in the window, ≤ 28k tokens, newest first).

**D-52 Lists and referrals.** The candidate workbook (+ `candidate_list.json`) goes to `routing.list_to`; patients whose
scoped department has a `routing.referral_to[dept]` entry also go, in a separate workbook, to that address; the
aggregate summary PDF goes to `aggregate_to` + requester. All three are separate mails; PHI ones are encrypted. MRNs
are resolved from the in-box pid map only while rendering.

**D-53 Pool and microbatch.** The pool keeps the full per-criterion verdicts (with evidence) of every listed patient.
MICROBATCH re-evaluates only `time_sensitive` criteria for pool patients with a booked appointment in the next
`microbatch_window_days` (14), recomputes the tier from old + new verdicts, highlights changed cells and lists them in
`changes`; on the first Monday of a month (or `incident=1`) new in-scope patients are screened and appended.
Scheduler: one MICROBATCH job per ruleset with a pool, one CALIBRATION job per ruleset with feedback.

**D-54 Calibration.** `reach = reached / (reached + not_contacted)`, `accept = enrolled / reached` (the per-reached
enrolment probability the FEAS simulation multiplies), screen-fail reasons counted by `reason_code` (criterion id).
Rates are used by FEAS only from 10 reached patients on (Beta concentration = reached); the mailed
`calibration_<ID>.json` is small-cell suppressed, the in-box copy is not.

**D-55 Judge test set.** `tools/make_judge_set.py` builds 300 labelled items (100 each for GZQO-INC-05, GZQO-EXC-11,
RA-BIO-REN-02) from the synthetic sites (full-record excerpts in the criterion window, gold = planted note truth);
`tools/judge_eval.py` runs them through `chat_json` + the production quote check. CPU CI runs the stub (rules written
for the synthetic sentence templates, so 100 % says only that the plumbing works); `pytest -m llm` with
`TB_JUDGE_LLM_URL` measures a real model against the ≥ 90 % target.

**D-56 DuckDB connections.** DuckDB shares one database instance per file within a process; the lake hardens a fresh
instance (FTS, no external access, locked configuration) under a process lock and skips hardening when it is already
locked (found by concurrent note retrieval).

## Phase 5

**D-57 RA-BIO source and design.** `tools/make_nhi_docs.py` writes, from one definition, a fictional zh-TW rule
document modelled on the structure of the NHI RA-biologic benefit rule (sections 初次申請給付條件 / 不得申請情形 /
續用條件 / 申請應檢附資料), the stub's gold extraction and the 附表十五 template. The ruleset is then compiled and
approved through the real pipeline (`tools/build_rulesets.py`, CQL≡SQL 100 % on HAPI). 19 criteria: 6 inclusion
(age, RA ≥ 6 months, MTX ≥ 180 d and another csDMARD ≥ 180 d with gaps ≤ 30 d, DAS28 > 5.1 in [−90, 0] and in
[−180, −90] — two separate assessments), 7 exclusion (active TB, IGRA+ without prophylaxis, HBsAg+ without antiviral,
malignancy ≤ 5 y, pregnancy, serious infection ≤ 30 d, heart failure), 2 renewal (DAS28 assessed ≤ 90 d; response
judged from notes with a structured fallback), 4 documentation (HBsAg, anti-HBc, TB screening, ESR/CRP, each with a
suggested order code). Claims are matched by the ruleset's `twpas.drug_codes`.

**D-58 NAV lists.** Active approval = an approved claim whose `approval_end ≥ run date`; an application in the last
`application_lookback_days` (90) suppresses `likely_eligible`. With an active approval, any failing renewal criterion
(note: confidence ≥ t) → `maybe_ineligible` (precedence), else ending within `renewal_lead_days` → `renewal_due`.
Without one: all inclusions pass and no exclusion fails → `likely_eligible` (unknown exclusions are listed as
"確認：…" missing items). `doc_gaps` = rows of the first two lists with a missing documentation criterion. Every
scoped patient's note criteria are judged (`all_candidates`).

**D-59 Application drafts.** docxtpl template per ruleset (`manifest.docx_template` under
`orchestrator/reports/templates/`); every field is a RichText `{{r …}}` so values are escaped and unknowns render as
bold, yellow-shaded `[待補]`; tables loop with `{%tr %}` rows. Facts are read from the lake with the ruleset's own
ValueSets (diagnosis, DMARD courses with dose text, corticosteroids, DAS28 components and scores per required
window, HBsAg/anti-HBc/IGRA/CXR, current approval). The `draft_doc` paragraph receives de-identified facts only and
is replaced by `[待補]` when it contains a number absent from them. Draft file names carry a pid prefix (never an
MRN) because file names are audited. Drafts are never signed.

**D-60 Lake medication columns.** `medication` gains `name` and `dose` (dosage text) for drafts and bundles.

**D-61 Retrospective harness.** `tools/nav_retro.py` evaluates the approved SQL at each application date in the last
12 months (pending skipped) and compares "eligible" (structured inclusions TRUE, no exclusion TRUE) with the NHI
outcome; the safety metric re-checks coded exclusion conditions with an independent code-presence query. On the
synthetic claims the harness runs with 0 safety violations but low agreement (≈ 23 %), because the generator plants
clinical data relative to the reference date, not to past application dates (most inclusions are unknown there);
the ≥ 85 % acceptance target applies to a site's real claims.

**D-62 Ruleset repository at start-up.** The compiler initialises the git ruleset repository in its lifespan hook,
so a fresh box materialises the vendor-shipped approved rulesets (and their tags) before the orchestrator reads them
(found when the NAV E2E ran on a new volume).

**D-63 TWPAS IG and package set.** SPEC names `tw.gov.mohw.nhi.pas#1.2.5`; the public package registry only has
`#1.2.0`, so the box validates against 1.2.0 (`twpas.ig_spec`: settings `profiles.twpas_version` when that package is
installed, else 1.2.0; `TB_TWPAS_IG` overrides). The offline cache (`tools/fetch_jvm_deps.sh`) holds its
dependencies: `tw.gov.mohw.emr#0.2.0` (its ips/sdc dependencies dropped, unused by the profiles), TW Core 1.0.0
aliased as the declared `0.3.2`, terminology/extensions aliases, and a subset package `hl7.fhir.us.davinci-pas#2.1.0`
holding only the `diagnosisRecordedDate` extension from `2.2.0-ballot` (the IG references it; no 2.1.0 package is
published). The hospital code is the IG's example `0101090517`, because Organization.identifier must come from the
IG's organisation code system; a site sets its own code in `settings.twpas.org_id`.

**D-64 Partial code systems.** The TW Core ICD-10-CM/PCS CodeSystems declare `content = complete` but describe
themselves as "僅擷取部分代碼" (a partial extract). With `-tx n/a` the validator then rejects valid codes that are
missing from the extract. `fetch_fhir_packages.py` relabels such CodeSystems `fragment` at install time, which turns
an unknown code into a warning. This is only needed offline; with a terminology server the relabel does no harm.

**D-65 Whole-number body measurements.** The validator's BigDecimal evaluation of the IG's weight/height invariant
rejects one-decimal values such as 60.5, so bundles carry whole kg and cm (Python `round`, half to even). This is
clinically irrelevant for the program's checks. Revisit it if NHI's own validator accepts decimals.

**D-66 Identity for NHI submissions.** TWPAS needs the patient's name and national id, which the pseudonymised lake
never holds. The adapter mapping's `patient.identity` columns are encrypted at ingest into a pid-map `identity`
table (AES-GCM, same key and pid as associated data as the MRN; D-10). Only `twpas.build_one` reads it. Identity
never appears in lists, file names, the audit chain or LLM prompts; a unit test checks that the national id appears
only in the Patient resource. Settings schema 1.1.0 adds the practitioner's `license` (Practitioner.identifier) and
`national_id`.

**D-67 ONC-OSI program.** The cancer-drug program for phase 6 is a fictional NHI rule 9.20 for osimertinib
(first-line, EGFR-mutant NSCLC). Like RA-BIO it is generated by `tools/make_nhi_docs.py` and compiled and approved
through the pipeline. It has 7 criteria: age, NSCLC diagnosis, latest EGFR result positive, ECOG 0–1 (note), no
EGFR-TKI in the last year (first-line), and two documentation items. TWPAS is enabled with the program's NHI drug
codes.

The bundle contains:
- Claim, Encounter, Patient and Practitioner;
- hospital and NHI Organizations, and Coverage;
- MedicationRequest-apply;
- the gene test (lab Organization, Specimen, Observation-diagnostic);
- ECOG (Observation-pat-assessment), whose value comes from the judge's verbatim evidence quote.

A patient without a gene result gets no bundle; the row's pre-check lists the gap. The generator now records
`osi` (the planted osimertinib course) in `states.json`. This only adds a state and consumes no randomness, so the
patient data is byte-identical, and the ONC-OSI oracle can check EXC-01.

**D-68 Pre-check and validation per NAV run.** NHI publishes no pre-check CQL. TrialBox ships a stand-in,
`orchestrator/precheck/TWPAS_Precheck_OSI.cql`, which checks diagnosis, EGFR positive, weight and height, and the
requested drug.
- It is translated once per content hash, loaded with FHIRHelpers, and evaluated on HAPI with
  `Library/$evaluate`, `data` = the bundle and `useServerData = false`, so nothing is written to the store.
- An NHI-published library would replace it by name (`manifest.twpas.precheck_library`).
- The HL7 validator runs once per NAV job over all bundles, because loading the IG takes about 40 s. Errors are
  mapped back to each bundle through the `rNNNNN-` file names, and R4B structural findings count as errors.
- Without the JVM, the report says `validator: structural`.

**D-69 SUBMIT.** The command is `SUBMIT <ruleset> pid=<pid> bundle=<NAV job id>`.
- The subject grammar limits option values to 32 characters from `[A-Za-z0-9,.:-]`, so `bundle` names the NAV
  job, not the object key.
- If `bundle` is omitted, the latest finished NAV run holding that patient's bundle is used.

Checks, all made before anything is sent:
- `permissions.SUBMIT` passes, at intake and again in the scenario, since jobs can also be created through the API.
- The requester is on the ruleset's `list_to`, because the receipt is phi.
- The NAV job is done and at most 14 days old.
- The stored bundle still hashes to its audited sha256.
- The bundle has 0 validator errors and its pre-check did not fail.
- A live submission additionally needs the real HL7 validator and a pre-check that passed; a dry run only notes
  their absence.
- A bundle already submitted live is refused (`submissions` table).

Modes:
- Dry run (`settings.twpas.dry_run`, or no `NHI_TWPAS_BASE_URL`): nothing leaves the box; a simulated
  ClaimResponse is returned with outcome `queued`.
- Live: `POST {NHI_TWPAS_BASE_URL}/Claim/$submit` with the Bundle (the Da Vinci PAS convention), and the returned
  ClaimResponse is stored. NHI's production transport is site-specific and is adapted at installation.

Each submission is audited as `twpas.submit` with the bundle hash, mode, endpoint and outcome.

**D-70 Required nulls in contract JSON.** `tb_contracts.dump` used `exclude_none`, which dropped required-but-nullable
fields (`Precheck.passed`, `FunnelStep.pct`, `Disagreement.cql/sql`), so the JSON no longer validated against its own
schema. `dump` now drops `None` only for optional fields.

**D-71 Cohort rulesets.** A cohort definition document has two sections, both parsed as inclusion criteria (the
parser headings gain `世代定義|計數條件`):
- `世代定義`: the population.
- `計數條件`: the characteristics counted inside it.

`manifest.cohort.population_criterion` names the population. Every other structured criterion, plus each configured
combination (AND), is counted inside that population; note and human criteria are not counted.

GOUT-COH (7 criteria, 2 combinations) and RA-COH (6 criteria, 1 combination) come from
`tools/make_cohort_docs.py` and are compiled and approved with `tools/build_rulesets.py --kind cohort`
(CQL≡SQL 100 % on HAPI). Supporting change: the terminology gains a type 2 diabetes synonym (E11).

**D-72 Consent registry.** `settings.registry_source` becomes FHIR R4 Consent at ingest:
- scope `research`, category LOINC 59284-0, policyRule `OPTIN`;
- `provision.type` = permit/deny;
- `dateTime` = the consent date.

How the source is chosen:
- unset: the data source's own `registry` table (the demo mapping);
- `csv` / `sql`: a separate source;
- `none`: skipped.

The lake gets a `consent` table (pid, status, contact_ok, date), which the SQL guard allows. `n_contactable` counts
the population whose latest active consent dated on or before the quarter end permits contact. Without a registry
the value is `n/a`.

**D-73 Alliance exchange and merge.** The CSV has exactly the v1 columns, with
`definition_version = <ruleset>@<version>`.

Producing a table:
- Quarters are the last N completed quarter ends on or before min(today, snapshot): `lookback=N`, default 4, max 12.
- Small cells are suppressed before anything leaves the box.
- A member box (`cohort.root_address` set, `alliance_root` false) mails its table to the root as an aggregate
  attachment with subject `COHORT MERGE -- <site> <ruleset> <quarter>`.

Accepting tables at the root (`alliance_root`):
- Only senders allowed by `permissions.COHORT` (the `alliance_sites` group); one site per file.
- The header and each row are validated against `cohort_table.schema.json`.
- Tables are stored per (site, disease, quarter, definition), each replacing the previous one.
- The root's own COHORT runs are stored as its own site.

The merged CSV holds the site rows plus an `ALLIANCE` total per (disease, quarter, definition, criterion).
Different definition versions are never summed. Suppressed cells are handled as follows:
- all site counts exact: the plain sum, suppressed again if small;
- otherwise compute a range in which each `<k` counts as 1..k−1:
  - publish `lo-hi` when lo ≥ k;
  - publish `<hi+1` when the total could itself be small;
  - publish `<k` when even hi is below k.

The merged table goes to the sending site and to the root's site contact.

**D-74 Trial simulation.** Recruiting studies are fetched through the criteria-compiler's `/ctgov/search`
(contract `ctgov.schema.json` 1.0.0): ClinicalTrials.gov API v2 `/studies` with `query.cond`,
`query.locn=Taiwan OR Japan` and `filter.overallStatus=RECRUITING`.
- The compiler fetches because it is the service with egress. This is public data and no PHI is sent.
- `TB_CTGOV_MODE=cassette` replays fictional studies (`NCT990000xx`, titles `[SYNTHETIC]`) in CI and the test stack.
- Studies without eligibility text or an exact last-update date are skipped.
- Ranking: a Taiwan site first, then later phase, larger target, newer update, NCT id. `top_n_trials` come from the
  manifest.

Each study's eligibility text goes through doc-parser (plain text) and the compiler (kind `trial`, ruleset id = NCT
id, not incremental).
- The result is an unapproved draft, labelled as an automatic compile in every output.
- SQL is still template-generated, so the determinism rule holds.
- Drafts are cached in the orchestrator's `trial_cache` by NCT id + last update for `ctgov_cache_days`.

Counting and simulation:
- Counts are FEAS counts over 12 months at the run date. The simulation uses `calibration_defaults`, seeded by NCT
  id + update + snapshot.
- Human and note criteria are not counted, and the workbook reports them as not counted.
- A suppressed eligible count publishes no simulation figures.

**D-75 COHORT schedule.** Quarterly, on the 1st of January, April, July and October at `settings.schedule.cohort`,
for `settings.cohort.rulesets` (else every approved cohort ruleset).

**D-76 Egress allowlist.** `deploy/network.sh` (a wrapper around the standard-library `deploy/egress.py`) renders
one nftables table, `inet trialbox_egress`, from `docker inspect` of the compose project. Its forward hook runs at
priority −10, before Docker's own chains.
- It allows established traffic, traffic between the box's own subnets, and the allowlisted source-container →
  destination-IP:port pairs.
- It drops everything else leaving any TrialBox subnet.
- Host names are resolved when the rules are applied. Re-applying after a restart is the operator's job (a systemd
  unit; docs/HARDENING.md).
- The compose network `trialbox-net` is also `internal: true`, so services that are not on `trialbox-egress` have
  no route out at all.

The allowlist follows §10.1. On top of it:
- criteria-compiler → clinicaltrials.gov:443 when `TB_CTGOV_MODE=live`, because §8.3 needs the public registry;
- `EGRESS_EXTRA` for site-specific additions.

`make test-egress` (root) builds a fake outside host in a network namespace, shows it is reachable without the
rules, and asserts that with the rules only orchestrator → NHI and mail-gateway → SMTP connect.

**D-77 Offline update bundles.** A bundle is an uncompressed tar with exactly `manifest.json` (UpdateManifest),
`manifest.json.sig` (base64 Ed25519 over the manifest bytes) and `files/<path>` per entry.
- `tools/verify_update.py` rejects: links, absolute or `..` paths, duplicate, extra or missing members, a bad
  signature or wrong key, a schema violation, and a size or sha256 mismatch.
- It stages payloads re-hashed as `.part` files and removes them all on any rejection.
- `tools/apply_update.sh` runs verification in a network-less trialbox-py container, or with the host's Python
  when `cryptography` is present.
- It applies by kind: images with `docker load`, models into `TB_MODELS_DIR`, rulesets through
  `criteria_compiler.import_ruleset`. Imported rulesets must be approved and at or above the equivalence gate;
  existing tags are immutable and the same content is idempotent.
- It writes an `update.applied` audit event. `--dry-run` verifies and stages only.

The box ships no vendor key: the site installs `deploy/keys/vendor_ed25519.pub` at commissioning. Tests use
ephemeral keys.

**D-78 Retention.** The daily `RETENTION` job deletes objects by `last_modified`:
- `attachments/` after `attachments_days`;
- `outputs/` and `ctgov/` after `outputs_days`.

One `retention.deleted` audit event per job lists each key with the sha256 recorded when it was created.

Pools and feedback are deleted for rulesets that are no longer approved on the box and untouched for
`pool_months_after_ruleset`. The box does not record a retirement date, so the last evaluation stands in for it.

After each successful ingest the adapter prunes NDJSON, parquet and DuckDB snapshots. It keeps the last
`nightly_snapshots`, the last snapshot of each of the `month_end_snapshots_months` completed months, and always
`CURRENT`.

Containers log through json-file with 5 × 50 MB rotation; logs hold no PHI. The audit chain is never deleted by the
box.

**D-79 GB10.** `deploy/docker-compose.gb10.yml` sets `platform: linux/arm64` on every service.
- vLLM is `eugr/spark-vllm` station 2026-10-01, pinned by its arm64 manifest digest, run with `vllm serve`, memory
  fraction 0.60 (unified memory).
- HAPI gets an explicit heap.
- The embedder runs on CUDA (`TB_EMBED_DEVICE`).
- The pinned third-party digests (MinIO, Postgres, HAPI, Temurin) are multi-arch indexes that include arm64. MailHog,
  used only by the test profile, is amd64-only.
- NVIDIA driver 580.142 is pinned and held; `deploy/check_host.sh --gb10` fails otherwise.

Verified here:
- every lock entry resolves to an aarch64 wheel;
- the trialbox-py and trialbox-jvm images build for linux/arm64 under QEMU emulation;
- the arm64 image imports and serves.

Not possible here: running vLLM on a GB10, since the host has no GPU (platform fallback).

**D-80 Bench method.** `tools/bench.py` runs the real code path of each §11.3 job at a size the host can hold,
then projects linearly to the target size by patients and criteria.
- FEAS runs on a lake amplified to 300k patients (DuckDB copies with suffixed ids) with GZQO over 36 month-ends.
- SCREEN measures CQL `$evaluate` on fhir-store for every loaded patient.
- NAV, MICROBATCH and compile run in process or against the compose stack.

The LLM share (judge, ir_extract, draft_doc) needs the reference GPU. With the stub it is reported as not
measured, so here the bench covers the deterministic share only. `--llm-url` points the same tasks at a real model.

Two findings from the bench run (docs/BENCH.md):
- **Lake memory cap.** DuckDB had no `memory_limit`, and a 300k-patient FEAS OOM-killed the host. Lake connections
  now set `memory_limit` (`TB_LAKE_MEMORY_LIMIT`, default 40 % of RAM) and spill to `/data/lake/tmp`.
- **Ingest memory.** Ingest is in-memory, about 0.33 GB per 1,000 patients. A 50k nightly delta needs the reference
  box's RAM; smaller hosts must ingest in `--since` chunks. Streaming the mapping is the improvement to make if a
  site's delta outgrows its RAM.

**D-81 Secrets at rest.** SPEC mentions SQLCipher for the pid map. TrialBox encrypts each pid-map row with
AES-GCM under `pid_map.key` (D-10, D-66), which avoids a native SQLCipher build. That key and the site HMAC key are
TPM-sealed at rest with `systemd-creds --with-key=tpm2` and decrypted into the secrets volume at start. The disk is
LUKS2 with TPM2 unlock, and swap is off (docs/HARDENING.md; checked by `deploy/check_host.sh`).
