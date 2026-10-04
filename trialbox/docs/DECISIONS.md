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
