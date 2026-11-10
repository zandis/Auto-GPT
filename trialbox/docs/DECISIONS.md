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
*Correction (D-86):* no Docling image is shipped in v1.0. Compose runs doc-parser on `trialbox-py`, so the lite
backend is the production parser; its heuristics were hardened for wrapped PDF lines. A site that builds an image
with Docling and its models (Hugging Face access needed) selects it with `TB_DOCPARSER_IMAGE` and `TB_PARSER=docling`.

**D-03 `$evaluate` vs `$evaluate-measure` (§12.2).** `Library/$evaluate` (HAPI JPA starter 8.12, CR module,
cql-to-elm 5.4.0). Spike result in this sandbox: ~77 ms per patient per library after warm-up, so 1,000 patients ×
1 call at 8-way concurrency ≈ 10 s of server time — well inside §11.3. `Measure/$evaluate-measure` is kept behind
`TB_CQL_EVAL_MODE=measure` (one cohort Measure per ruleset, individual report per subject).

**D-04 7z vs S/MIME (§12.2).** `ATTACH_PASSWORD_MODE=zip` (7z AES-256 via py7zr, password mailed separately) is the
default because it needs no recipient certificates; `smime` (CMS sign + encrypt with `cryptography`) is selectable.

**D-05 Python packaging and images.** One `pyproject.toml`; packages are discovered from `libs/` and `services/`.
All Python services share one base image (`trialbox-py`, multi-arch `python:3.12-slim`) and differ by command.
Heavy extras get their own images built FROM it: `doc-parser` (+docling; not shipped, see D-02), `embed-service`
(+sentence-transformers, CPU torch on arm64 and amd64), `criteria-compiler` (+JRE 17 + cql-to-elm jars). No x86-only wheels are used
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

**D-28 `ssmix2` source.** (Superseded by D-122: the reader exists.) Not in v1.0 for Taiwan sites; the reader raises an explicit `NotImplementedError` pointing to
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

**D-82 Reproducibility.** §11.2 asks that the same inputs and versions give identical output hashes.
- The job fixes its `run_date` when it starts (job schema 1.1.0). `Ctx.today()` returns it, so a job that runs
  across midnight, or a re-run, uses one date.
- Evaluation stamps in candidate rows use the job's receipt time, not the wall clock.
- The trial simulation reports `draft_compiled_on` instead of a cache flag that depended on cache state (ctgov
  schema 2.0.0: removing a field is a breaking change).

`python -m orchestrator.rerun <job ids>` re-executes finished FEAS, SCREEN, MICROBATCH, NAV, COHORT and CALIBRATION
jobs in a sandbox:
- same job id, inputs, options, run date and lake snapshot (queries pinned);
- a scratch object store, no mail, a temporary job DB (pool and trial cache copied);
- a `COHORT MERGE` gets the alliance tables as they stood when it ran: the sandbox replays, in job order, every
  earlier merge's attached tables and every root COHORT run's published table (all immutable objects). A site
  that re-submits later therefore cannot change an old merge's re-run (found on the compose stack, where the
  first version compared against the live table);
- it compares every output's sha256 with the audited original and audits a `rerun.checked` event.

Jobs with side effects are never re-run: SUBMIT, APPROVE, and FEAS with an attached protocol (which compiles). In
process, all five read-only scenarios re-run byte-identically and a changed output is detected.

**D-83 Acceptance runner.** `tools/acceptance.py` has one subcommand per §11.2 row; each writes `<check>.json`, and
`report` writes `acceptance_report.md`.

SCREEN has two parts:
- `screen-sample` draws a seeded, shuffled, blinded set of ≥ 100 patients from four strata (high, review, excluded,
  scoped but not listed): proportional allocation, at least 10 per stratum. The CRC workbook and the key are kept
  apart.
- `screen` unblinds and computes trial-level sensitivity and specificity, weighted by each stratum's inverse
  sampling fraction (the default tier is `high`; the review tier is `high` + `review`), criterion agreement
  (structured and note separately, against the CRC's per-criterion columns) and median CRC minutes.

The other rows reuse existing tools: FEAS (`funnel_compare`), NAV (`nav_retro`), reproducibility (`orchestrator.rerun`)
and audit (`tb_common.audit.verify`). TWPAS requires the real HL7 validator and a pre-check pass for every bundle.

**D-84 Site onboarding without code changes.**
- `tools/settings_wizard.py`, interactive or `--answers`, writes a schema-valid `settings.yaml` plus a 0600 `.env`
  with generated secrets. It also cross-checks what the schema cannot express: practitioner departments, recipients
  inside the internal domains, the MRN regex, the mapping file, and the TWPAS org code.
- Site mappings `extends` the shared TW Core mapping and declare only their `tables`. `rename` maps local to
  canonical columns, `values` maps local to canonical codes, `key`/`delta`/`identity` name canonical columns
  (`delta` is translated back to the local name for the source filter), and resources of undeclared tables are
  dropped.
- Templates (`csv_site.yaml`, `cgrd_sql_site.yaml`) and `CANONICAL.md` list every canonical column.
- `tools/mapping_check.py` distinguishes required columns (ids, keys, `where`, the patient link) from optional
  element columns, and reports unmapped codes.
- The DoD test: site C, with other file and column names, other codes and another MRN format, is onboarded with
  the wizard answers and the template only. Its lake is identical to site B's, and `FEAS GZQO` by mail succeeds.

**D-85 LLM layer and supporting tools.**
- §11.1's `ir_extract` set ("5 public protocols") uses five English eligibility texts with gold IR: the four
  synthetic registry records and GZQO. Real registry texts cannot be fetched into the repository, which is
  synthetic-only. `concept_map` uses 200 concepts from the terminology tables; the judge set has 300 items.
- These tests (`pytest -m llm`) need a real model.
- `tools/export_spec.py` renders an approved ruleset as a human-readable specification, with the sha256 of its
  CQL/ELM/SQL, for sponsor and IRB files.
- `tools/parser_compare.py` is the D-02 backend comparison: I/E and table-cell recall against optional gold files;
  Docling runs in the production image.

**D-86 Fixes from the post-merge deep review.** A max-effort correctness review of the merged code reported 15
findings. Each was confirmed (by running code where possible) and fixed with a test that fails on the old code.
- **SUBMIT is once per bundle.**
  - A live submission reserves the bundle atomically before the POST (DB lock plus a partial unique index on live
    `bundle_sha`).
  - The reservation is released only when the bundle provably never reached NHI: no connection, or HTTP 4xx.
  - A lost answer (read timeout, 5xx) keeps it as `uncertain`. A re-run after a restart never POSTs again.
  - The physician is told to check the NHI system.
  - The dry-run record is idempotent per job.
- **APPROVE after a restart.** If the version is already tagged, APPROVE resumes the waiting jobs instead of failing
  with "no draft" (the same happens for a duplicate approval mail).
- **Mail authentication alignment.** A command needs `dmarc=pass`, or an SPF/DKIM pass whose domain is aligned with
  the From: domain (equal or a parent/subdomain). Each result clause is parsed on its own.
  `TB_MAIL_AUTHSERV_ID` is asked by the wizard, set in `.env.example`, and the gateway warns at start when it is
  empty.
- **Audit chain across midnight.** An event stamped before midnight but written after an event of the next day goes
  into the newest day file. The files read in name order are the chain order; the event keeps its timestamp.
- **ValueSet names.** Concept names with non-ASCII letters (zh/ja) get a stable hash suffix instead of all
  collapsing into `VS_CONCEPT`, and postprocess never lets two concepts share one ValueSet. ASCII names are
  unchanged, so the shipped rulesets recompile identically.
- **Cloud routing.** The PHI clearance covers exactly the call's variables (`phi_guard.variables_text`: every
  scalar, unescaped, which the prompt templates embed). The LLM client checks the clearance against that text, so
  cloud routing, which could never trigger before, now works when enabled.
- **SQL comments.** Criterion text in a SQL `--` comment has its whitespace collapsed, so a newline cannot turn the
  rest of the text into SQL.
- **Medication duration.** An order with neither start nor authored date no longer counts as exposure over the whole
  window: CQL `Max`/`Min` and SQL `greatest`/`least` skip nulls. The generators require a start.
  - Approved rulesets keep their compiled artifacts: GZQO INC-06 and RA-BIO INC-03/04 v1.0.0.
  - The adapter therefore drops undated orders and reports them in `missing_required`. Neither engine sees them,
    whatever the ruleset version.
- **PDF parsing (lite backend).**
  - An enumerator is never followed by a digit: `1.5 mg/dL` on a wrapped line is not item 1.
  - A numbered line is a heading only if it reads like a title (capital letter or CJK first).
  - Inside an I/E section, a heading must also be a criteria heading or continue that section's numbering. Wrapped
    lines therefore no longer close the section and drop criteria.
- **fhir-store mirrors the snapshot.** A ledger of loaded ids (`<lake>/fhir_ledger`) drives the deletion of resources
  that left the source, dependents first.
  - The ledger is widened before loading.
  - HAPI no longer enforces referential integrity on delete.
  - Ingest report 1.1.0 adds `fhir_deleted`.
- **Small cells in aggregate outputs.**
  - SCREEN and MICROBATCH summaries (mail and PDF) suppress every count.
  - FEAS publishes controlled-rounded counts (`round_count`: `<5`, else the nearest multiple of 5). Dropped counts,
    percentages, deltas and the monthly mean are derived from the published counts, so a suppressed cell can no longer
    be recomputed from its neighbours. The exact counts stay in the box (raw JSON, simulation).
  - Calibration withholds a published rate whose numerator, complement or denominator is a small cell.
- **`POST /send` is not retried** once it may have reached the gateway (5xx, read timeout); only a refused connection
  is retried. A retry would mail the PHI archive again with a new password.
- **COHORT MERGE ownership.** A table may not claim the root's own site, and a site's tables come only from the
  address that first contributed them. The re-run replay applies the same rule.
- **Acceptance.** Criterion classes and labels come from the ruleset's IR (`--ruleset`). Candidate rows carry only
  id and verdict, so the criterion check could never pass before. The unit test now validates its rows against the
  contract.


**D-87 v4 services in compose; site model pins.**
- `gateway` (port 8020) is the only service on `model-net` (internal) with `llm-service` / `llm-stub`; orchestrator,
  criteria-compiler and doc-parser reach models through `TB_GATEWAY_URL` (the `tb_common.llm` shim). The gateway is
  also on `egress-net` for the external endpoints `deploy/egress.py` opens to it alone.
- Model registry, PHI guard and trace store run inside the gateway process rather than as services: all three are
  on the path of every model call and nothing else calls them over HTTP, so separate containers would add a network
  hop and a failure mode to a fail-closed path. The read-only registry view is mounted at `/registry/v1/builds`;
  traces go to the `traces-data` volume.
- `workflow-db` (Postgres 16, the multi-arch digest already pinned for `fhir-db`) holds the outbox and recall ledger.
  The product image does not yet ship `psycopg` (not in `deploy/requirements.lock`), so the e2e exercises it from the
  host venv.
- Site pins live in `deploy/site/registry.site.yaml` (not committed), written by `tools/pin_model.py`: the sha256 of
  the weight manifest (sha256sum lines of every visible file, sorted). An override may only set pin fields of
  existing builds; the merged registry version carries `+site.<hash>`. Unpinned builds stay unroutable.
- Route `dev-stub` lists `j-workhorse@serving` after the stub: on synthetic/open D0 data in DEV/TEST a caller may ask
  for the pinned on-box build (`TB_GATEWAY_MODEL=j-workhorse`). Unpinned, that call is refused, never served by the
  stub.

**D-88 Lightweight ruleset approval; outcome-first mail subjects.** Decided with the site owner on 2026-10-25.
TrialBox pre-screening stays outside the regulated record: it proposes candidates, a person confirms each one, and
the trial's own systems (EDC, eTMF, IRB) hold the regulated record. So ruleset approval is a working check by the
study team, not a 21 CFR Part 11 / ER/ES e-signature: one click on the console job page by an administrator, or a
reply to the review mail with the workbook. No re-authentication, no signature manifestation, no second approver.
The approver (requesting mailbox), time and workbook hash stay in the audit chain as before, and the approved mail
names the approver. The review mail and the console card say how each criterion will be checked, following the
compiler's class: a fixed filter on structured data (age, sex, codes, labs, drugs), the model reading reports and
notes, or a person at screening. The language model reads the criteria once to draft them; it never decides
eligibility on structured data.
Comparable products do the same: public material for Lind, Deep 6 AI (Tempus), TriNetX and NIH TrialGPT shows the
human check on the candidate or the query, not an e-signature on the criteria. The spec v2 sign page (§4.1) is
deferred until a stage that writes to a regulated record (eCRF, SAE) is built.
Box reply subjects lead with study, command and outcome and end with the job id
(`tb_common.subject.job_subject`): `[GZQO] FEAS done: 1–7 in 12 mo · job <id>`, `... received · job <id>`,
`... failed: at <step> · job <id>`, `[GZQO] ruleset v1.0.0 approved`. A reply to one never parses as a command.
The review mail keeps its `APPROVE <id> version=<v> -- …` subject so a plain reply approves.

## Clinical review build (2026-11)

**D-89 Two-model agreement in SCREEN and CASE.** Decided after the clinical review of 2026-11-05. The note judge used by
SCREEN (`NoteJudge`) runs the agreement rule the cascade already had: when a verifier build is configured, every decided
judge answer is asked of the verifier too, and a criterion is decided only when both agree; a disagreement becomes
`unknown` with the reason "judge/verifier disagree; needs a human look". The bake-off showed the pair blocking
wrongly on 0.9 % of criteria against a higher single-model rate, and a wrong exclusion is the costliest error in
pre-screening. `TB_SCREEN_JUDGE=single` restores the single judge for a measured comparison; the judge record in
every output names the mode, the verifier build and the disagreement count. No GPU cost at feasibility: structured
criteria never reach a model.

**D-90 Uncertain inclusion goes to review, never out.** The cascade's S2b stage used to exclude a patient when the
inclusion evidence was below threshold. Below threshold now means `unknown` in the review stratum, consistent with
the SCREEN rule that the box never excludes on silence (`services/matching/cascade/engine.py`). The independent
review of 2026-10-27 reported it (finding 6).

**D-91 CASE: one patient, one chart.** `CASE <ruleset> [mrn=<chart number>] [lang=en|ja|zh-TW]` with the chart
attached (PDF, DOCX, TXT or MD, several files allowed), by mail or on the console's "Single case" page. Structured
criteria come from the lake when the chart number resolves to a patient on the box (the number becomes the pseudonym
and is discarded); otherwise every criterion is read from the chart with the agreement rule, and the sheet says
which ones to check against the record. Human-review criteria stay `pending_human`. The eligibility sheet (HTML and
JSON) is PHI: it goes 7z-encrypted to the ruleset's `routing.list_to` (the study team) only; the requester gets a
counts-only mail when not on that list; viewers cannot open it on the console. Dates in charts are read in ISO,
slashed, Minguo (民國) and Japanese era (令和/平成) forms. Pilot default: a chart number is optional (a visiting
patient has none yet). Decision open to the site: whether CASE should also add the patient to the registry.

**D-92 Candidate registry (screening log).** Per approved ruleset the box keeps where the study team is with each
pseudonym: candidate, contacted, consented, enrolled, screen_fail, declined, withdrawn; every change is an event
(who, when, why) and an audit record; clerical corrections are allowed but enrolled is final unless withdrawn. Rows
arrive by hand with a chart number (resolved in-box, never stored), by promotion from the latest SCREEN pool (tiers
high and review), or later from CASE. The XLSX export resolves chart numbers from the pid map for the site's own
screening log (ICH E6(R3) 3.16) and is deterministic (D-82). It is not an EDC: no visit data, and the consent
status is the coordinator's note, not the consent record (D-88). Orchestrator API `/registry/...`; console pages
`/pilot/registry`.

**D-93 Coordinator role, hospital sign-in, users page.** Three console roles: administrator (everything, including
ingest, users, updates), study coordinator (requests, approvals, registry, consent drafts) and viewer (read only).
The pilot workspace's actions need coordinator or administrator; operations need administrator. A hospital reverse
proxy that authenticates staff (AD FS, Keycloak, Entra, Okta) can sign users in with a trusted identity header
(`TB_CONSOLE_SSO_HEADER`, groups in `TB_CONSOLE_SSO_ROLE_HEADER` mapped by `TB_CONSOLE_SSO_ROLE_MAP`, default role
`TB_CONSOLE_SSO_DEFAULT_ROLE`); the header counts only from the proxy addresses in `TB_CONSOLE_SSO_TRUSTED_PROXIES`,
anything else is audited as `console.sso_rejected`. Header accounts carry no console password and cannot be given
one; a local account is never changed by a header. Administrators manage accounts on `/ops/users` (one-time
password shown once; reset signs the person out everywhere). LDAP bind, OIDC in the console itself and TOTP remain
on the roadmap: the proxy pattern is what hospital IT already runs, and it keeps passwords out of the box.

**D-94 One-file install and the sizing estimate.** `tools/make_bundle.sh` (vendor) exports the images, models,
rulesets, installer and runbook into one Ed25519-signed bundle (D-77); `deploy/install.sh <bundle>` on the site
verifies it, loads it, runs the settings wizard, starts the stack with the GPU or stub profile, creates the first
administrator and runs the host check; re-running is idempotent and nothing leaves the host. The update audit event
is deferred until the orchestrator runs. `tools/gpu_sizing.py` holds the arithmetic behind the hardware table of the
clinical review (weights, KV cache from the model configurations, engine and stack allowances, bandwidth-bound
throughput); every figure is an estimate until measured (RUNBOOK §8). Its first result: the benchmarked pair fits
one DGX Spark only with the judge at 32k, the verifier at 16k and two sequences at a time; the spec v4 plan (64k/32k,
four sequences) is about 10 GB short once HAPI, Postgres, DuckDB and the embedder are counted.

**D-95 Consumer-card profiles and the note-block policy.** Filter first stays the pipeline (SPEC §8.2): CQL/SQL decide
every structured criterion, and the note judge reads notes only for patients the filters kept. The 2026-11-05
assessment (docs/reviews/2026-11-05-consumer-gpu-filter-first.md) replayed the TrialGPT benchmark that way. The LLM
then reads 42 % of criteria. Gemma 4 26B-A4B 4-bit + Qwen3.5-9B, both must block, lost 1/79 (en) and 2/79 (ja)
eligible pairs, against 5 and 4 for the Spark pair. This was measured through OpenRouter providers, with the filter
assumed perfect, on machine-translated Japanese notes. Two install profiles follow:
- `--gpu rtx5090` (deploy/docker-compose.rtx5090.yml): that pair resident on one 32 GB card, registry builds
  `gemma-4-26b-a4b-it-rtx5090` and `qwen3.5-9b-rtx5090`.
- `--gpu rtx4090`: the judge alone on a 24 GB card.

`TB_NOTE_BLOCK` sets whether a note answer may exclude a patient:
- `both_agree` (default) keeps D-89: with a verifier, a note criterion excludes only when both models agree.
- `never` (written by the installer for `rtx4090`) never lets a note answer exclude. A confident note fail keeps its
  verdict and quote, but the patient goes to review.

On one model the LLM therefore cannot cause a wrong exclusion; a weaker model costs coordinator minutes, not
patients. The installer picks the profile from `nvidia-smi` (aarch64 -> gb10, 5090 -> rtx5090, 4090/3090 ->
rtx4090) unless `--gpu` is given. Before go-live, the exact 4-bit files must be qualified on the card
(RUNBOOK §8).

**D-96 Suspected findings never exclude (judge v4).** The 2026-11-05 MedTxt run (215 real Japanese case and
radiology reports with English translations, docs/reviews/2026-11-05-public-data-validation.md) showed every model
reading "lung cancer is suspected" as lung cancer: suspected findings were excluded 37-80 % of the time, 41-67 % for
the pairs. `services/orchestrator/prompts/judge_v4.md` adds one paragraph: suspected / possible / rule-out is
`unknown` (so the patient goes to review), and a resolved or removed condition is history, judged against the
criterion's time frame. Measured with the same wording in `tools/medtxt_eval.py --variant suspected`: pairs exclude
on suspected findings 11-22 % of the time, at 2-8 points of recall on present findings. The cascade asks for `judge`
(newest version) and gets v4; the compiler writes `judge_v4` into new manifests. Approved rulesets keep their pinned
`judge_v3` until they are re-approved, because a prompt change in an approved ruleset is a change the approver signs.

**D-97 Never-exclude fallback without a verifier, and the models card.** `TB_NOTE_BLOCK=both_agree` (D-95) promises
that a note criterion excludes a patient only when two models agree. Where no verifier is wired (the OpenRouter POC
mode, a verifier scaled to zero, `TB_SCREEN_JUDGE=single`, a verifier that is down), the orchestrator used to run
the single judge and still let a confident note `fail` exclude, so the site believed two models had agreed when one
had. Now `evaluate.effective_note_block(judge)` decides per run: `both_agree` without a verifier becomes `never`,
and the run says so. The judging facts (judge model, verifier model, agreement mode, policy configured and in
force, disagreements, failures) travel with the run: the `screen.evaluated` audit event, the candidate-list JSON
(`judging`, optional), the summary PDF scope lines, the done mail, a new aggregate `screen_<stem>.json`, and
the orchestrator's `GET /models`, which the console shows on the Overview as "Models and policy" with a warning pill
when the fallback is in force. `trialbox doctor` gained the `note_block` check: WARN in DEV/TEST, FAIL in
VALIDATION/PRODUCTION when `both_agree` has no verifier. A site that wants single-model on purpose sets
`TB_NOTE_BLOCK=never`, as the rtx4090 installer profile does. Reviewed 2026-11-05 (Fable review H2, M9).

**D-98 Mixed criteria and the polarity check at import.** The 5 Nov 2026 validation routed about 27 % of real
criteria as "codes confirm when present, notes decide otherwise", which the v1 IR could not express (v4's cascade IR
already had a `mixed` class). Criterion IR 1.x now accepts `class: mixed`: the criterion carries `logic` and a
`note_question`. The compiler compiles its logic like a structured criterion (and demotes it to `note`, never to
`human`, when the logic does not compile). At screening the coded answer settles the criterion when it is true (an
inclusion met, an exclusion present); a false or null coded answer only says the codes were silent, so the patient
stays a candidate and the judge reads the notes. A verdict that came from the notes keeps the note rules
(confidence threshold, two-model agreement, D-95/D-97 note-block policy); a coded verdict is deterministic. FEAS and
cohort counts do not apply mixed criteria (their coded part is a lower bound, not a count), and say so. The same
validation found that a negated exclusion question ("Does the patient have no history of X?") inverts the judge's
answer and excludes exactly the patients to keep. The extraction prompt (ir_extract v2) forbids it, and the compiler
checks every exclusion question anyway: common English forms are rewritten to the positive
(`negated_question_rewritten`, the original kept in `note_question_source` and shown to the reviewer); anything else
is flagged `negated_question`. Both need review before approval. Reviewed 2026-11-05 (Fable review H5).

**D-100 Mail and reports in the requester's language.** The console and the front door accepted Japanese and
Traditional Chinese, but every reply, PDF and done mail was English, and the CASE sheet followed the site locale
although the console promised "same as the chart". A job now has one language: the `lang=` option when given (the
console adds the signed-in user's language to FEAS, SCREEN, CASE, NAV and MICROBATCH requests), else the site locale.
`services/orchestrator/i18n.py` holds the texts (received, failed and status mail; SCREEN and FEAS done mail and
headlines; every label of the feasibility and screening-summary PDFs) in EN, JA and zh-TW with one key set, checked
by a test. Subjects keep their ASCII kind tokens, since `is_job_mail` parses them. The CASE sheet detects the
chart's language from its script when no `lang=` is given. The stub model's "translations" are now tagged as samples
that are not translations. Reviewed 2026-11-05 (Fable review H4, M5).

**D-101 Approval record, investigator role, sponsor pack and report provenance.** The 5 Nov 2026 review found
the approval of a ruleset stored only the requester's address, that a protocol with 19 of 23 criteria routed to a
person could be approved in one click without a word of warning, and that the LLM router agreed with expert
annotators on the class of a criterion only about 6 times in 10 (kappa 0.34) on open trial data. The review mail now
says so and asks the approver to read the class column; when at least half of the criteria are left to a person it
opens with "Check this". The approval record (`manifest.review`) keeps who approved, via which channel (web console
or e-mail), the class split at approval and `routing_confirmed: true`, because the approval is the person's check of
the routing. The manifest gained an optional `population` block (disease stage, study arm): the AD audit showed a
criteria list alone does not say that a dementia patient is out of an MCI trial, so the stage is a named field that
FEAS and SCREEN mails print next to every count. The console gained the **investigator** role (PI / sub-I): reads
what a viewer reads, plus the CASE sheet and the pseudonymous candidate rows; no chart numbers (reveal and registry
export stay with coordinators), no requests. A finished FEAS job offers a **sponsor pack**: one zip with the
aggregate PDF, XLSX and JSON and a README naming the ruleset version, snapshot, approval record, population and the
models that ran; the download is audited (`console.export`). Report footers print the models that actually ran
(`no model (filters only)` for FEAS; judge and verifier, or judge alone with the note-block policy, for screening
runs) instead of the configured judge, and say when the box's clock was pinned (test stack). Reviewed 2026-11-05
(Fable review M1, M2, M6; PR #15 design points 1 and 3).

**D-102 One funnel, plain words, phones.** The 5 Nov 2026 review walked the console as a coordinator on a 390 px
phone and as a viewer and sponsor. Every results page now shows the same named funnel with the cascade's stage ids
(S0 in scope, S1 after the coded filters, S3 notes the model read, S4 candidates for a person, S5 confirmed): a
screening run writes it into `screen_<stem>.json`, the cascade page names its stages the same way and shows them
while the run is still going instead of an empty page, and its headline keys are words. The FEAS page opens with the
PDF's answer (participants in N months, biggest barriers) before the funnel. The New request page shows a viewer what
they can do instead of three greyed-out forms; its buttons say what they start ("Count eligible patients", "Find
candidates for the next visits"). The single-case form lists trial rulesets only and asks the user to pick one. Engine
words left the user's text (the proposal note, the health line). On phones the menu fades at the edge to show it
scrolls, every table scrolls inside its card, and controls stack. Reviewed 2026-11-05 (Fable review M3, M7, M8, L1,
L2, L3, L4).

**D-103 SCREEN runs the v4 cascade; GZQO re-approved with judge v4.** Until 5 Nov 2026 the v4 cascade (S0–S5,
`services/matching/cascade/`) ran only as `tools.cascade_e2e` on the synthetic drop, while a screening request went
through the v1 evaluator (per-patient CQL/SQL, then RAG and the judge on every structured candidate); D-102 unified
the names of the two funnels but not the engines. Changfu's decision of 5 Nov ("pilot = the full cascade as one named
funnel", "e2e, do it now"): a SCREEN job now scopes its patients as before (practitioner appointments and recent
encounters) and hands that population to `run_cascade` (`scenarios/screen_cascade.py`): S0 consent and scope, S1 the
approved ruleset's compiled SQL (filters first, never a model), S2 the bilingual lexicon on the notes in the window,
S2b the semantic ranking that picks the excerpts, S3 the judge in exclusion-power order with span verification, S4 a
second opinion on would-be strong candidates, tiers. S5 stays with the coordinator (console and workbook), so the
cascade runs without a reviewer. The judge is the orchestrator's own LLM client wrapped as the cascade's
`JudgeClient` (same gateway route, prompt pin, audit line and two-model agreement rule as before; the judge-failure
gate of v1 applies). Screening differs from feasibility in three settings the engine gained: the population is given
by the caller (`CascadeConfig.population`), nobody is sampled, and zero-hit pairs below the S2b threshold go to the
judge instead of taking absence semantics (`absence_semantics=False`: screening spends the tokens, the S2b
thresholds stay a feasibility economy until the LTT fit exists, D-90). The note-block policy in force (D-95/D-97)
becomes the engine's `note_block`: without a verifier a confident note `fail` is soft, keeps its quote and sends the
patient to review, never out. `mixed` criteria (D-98) now exist in the cascade too: a coded hit settles them at S1,
silent codes send them to S2/S3. The traces come back as the same `CandidateRow` verdicts, tiers and actions every
report, mail, pool, registry and console page already used (a null exclusion value the cascade keeps reads `unknown`
and makes the row a review row, as v1 did); `screen_<stem>.json` carries the engine's stage log under `cascade` and
the funnel of D-102 is now that log (S0, S1, S3 = patients whose notes the model read, S4). `TB_SCREEN_PIPELINE=v1`
restores the v1 evaluator for a measured comparison; `GET /models` and the console Overview say which pipeline runs.
MICROBATCH's per-criterion delta check keeps the v1 evaluator (it re-asks single criteria for pool patients); its
Monday re-screen goes through `run_screen` and so through the cascade. On the synthetic site the cascade reproduces
the planted structured truth at ≥ 98 % and the note truth at ≥ 90 % (the v1 acceptance tests, unchanged). With the
same decision Changfu re-approved GZQO with the judge v4 prompt (D-96): `rulesets/GZQO/manifest.yaml` pins
`judge_v4`, the review record names the approver, the channel (project chat, 6 Nov 2026 06:28 +08:00), round 2 and
the class split; criteria, SQL and CQL are unchanged, so the ruleset version stays 1.0.0. Changfu's "Switch" of
6 Nov 2026 07:11 +08:00 re-approved the four other shipped rulesets (GOUT-COH, RA-BIO, RA-COH, ONC-OSI) the same
way, so every shipped ruleset now pins `judge_v4`; only ONC-OSI has a note criterion, the three cohort rulesets
are filters only and the pin is recorded for consistency.

**D-104 Report-first pages per role.** Changfu's review of 5 Nov 2026 ("the general UX is too complex… sometimes they
just want a report and a patient list"): the pilot console gains one landing page per role and three report pages,
and the existing pages move under a "More" menu. Roles: `admin`, `coordinator` (hospital CRC or SMO coordinator),
`investigator`, `viewer`, and a new `cro` role. An account carries an affiliation (hospital, smo, cro), an optional
study allowlist and an optional end date (`services/console/auth.py`): a scoped account gets 404 on other studies, an
expired account cannot sign in, `cro` and `viewer` see aggregate pages only (feasibility report, sponsor pack), never
a patient. Pages (`services/console/home.py`, pilot workspace only; production keeps the D-12 rule of no study
content on the console): `/home` (study cards with the next action for coordinators; tiles for admins; investigators
go to `/week`, `cro`/`viewer` to `/reports`); `/studies/{rs}/feasibility`, a sponsor-style feasibility report in 12
sections built from the FEAS job and a new `feasprofile_*.json` aggregate (`scenarios/feas_profile.py`: rounded age
and sex bands, 90-day visits, a per-month projection path from the same Monte-Carlo draws), the criteria funnel with
"checked by" per criterion, barriers split into "value did not meet" and "no value on record", a GO / CONDITIONAL /
NO-GO reading against the sponsor target, and site fields the coordinator types (capabilities, competing trials,
target, screen-failure rate; `site.sqlite`), with a sponsor copy (`?view=sponsor`) that leaves out internal comments;
`/studies/{rs}/week`, the weekly PI list from the latest SCREEN/MICROBATCH candidate list (clinic date, doctor, met
and still-open criteria, a deterministic "why this patient fits" sentence, no model text); and
`/studies/{rs}/patients/{pid}`, every criterion with result, evidence quote and how it was checked. The investigator
marks a patient "approach", "not suitable" (with a reason) or "need info": marks are audited events in `site.sqlite`,
separate from the candidate registry statuses, and never change a screening result. Investigators may now reveal a
chart number on the patient page (audited `console.reveal_patient`), as coordinators could. `tools/role_demo.py`
runs the whole box in one process on the synthetic hospital with one account per role, for trying the product.
Review of 6 Nov 2026 (second pass, fixed in the same change): a study-scoped account can request jobs for its own
studies only and gets 403 on the cross-study lists (`/jobs`, `/audit`, mailbox, cascade runs; the registry index is
filtered); an account past its end date is refused at single sign-on too, not only at the password form; a failed
inclusion criterion shows as "Not met" on the weekly list; the GO reading compares the projection path at the
sponsor's own deadline (pro-rating only beyond the 12-month horizon); the report says which counts are over the
look-back window and which is the latest-month-end pool; a bad scope is refused before the account exists and an
administrator can edit scope and end date later. The "aggregate only, never a patient" rule is enforced for `cro`
accounts; the existing `viewer` role keeps its earlier read-only rights (job pages with patient files withheld,
registry pseudonyms) and only its new pages are aggregate. The CRO account downloads the sponsor pack of a study it
sees. Known gaps: age and sex are not on the weekly list (the candidate row does not carry them); the AD capability list
and the 60 % AD screen-failure default appear only for an early-AD ruleset, and none ships yet.

**D-105 Lake rebuild keeps embeddings as float32 and inserts in batches.** The 50,000-patient hospital simulation ran
out of memory in the lake rebuild: every note-chunk embedding was a Python list of 1,024 floats (about 32 KB a chunk)
and the whole `document_chunk` table was built as one Arrow table from Python rows. Embeddings are now NumPy float32
(4 KB), read from the embedding cache through Arrow, inserted in batches of 4,096 rows, and the resource dicts and
non-document flat rows are freed once their Parquet file is written. The stored values are unchanged (the column was
already FLOAT[1024]). Peak memory of a 5,000-patient cycle fell from 2.6 GB to 1.8 GB. Reviewed 2026-11-05.

## Simple build plan, step 1: feasibility (2026-11)

**D-106 Synthetic hospital for the build (TB-DS-21) and the paste-criteria feasibility path.** Build step 1 of
TB-PLAN-02 (`20-build-map.md` §2). (1) `tools/synth` becomes the generator of the synthetic hospital without changing
its default output: every planted-state rate moved unchanged into `tools/synth/rates.yaml` (TB-DS-21 §3.1, order
kept, so `tools/make_fixtures.py` still writes the committed `tests/fixtures/synthetic_patients` byte for byte); the
generator takes a record style (TW as before, or JP: kanji names from `names_ja.py`, 8-digit chart numbers, insurer
numbers with the never-issued 法別番号 00, Japanese phone format, Japanese practitioner names) and a note-language mix
(zh-TW, ja, en; templates `notes.py`, `notes_ja.py`, `notes_en.py` behind `lang.Lang`, same draw shape in every
language). With `gold=True` it also plants PHI spans (name, date, chart number, phone, address, insurer number,
hospital name; rates in `rates.yaml` `phi`, proposed in TB-DS-21 and adopted here: 70 % of notes carry PHI, 3 spans
each on average, so 2.1 per note overall), writes 10 % of note dates as 和暦 (JA) or 民國 years (zh-TW), never emits
a Taiwanese ID with a valid check digit or a reserved name (`tools/synth/reserved.py`), and records `gold/notes.jsonl`
(findings per §5.1 slot and PHI spans, Unicode code-point offsets). Language, date-form and PHI draws use their own
random streams, so the main stream is untouched. (2) `python -m tools.synth_hospital` writes one or more sites in
chunks of 10,000 patients (streaming CSV and truth files) and runs the §6 checks: determinism (sha256 manifest and
digest), every finding and PHI span re-found against the text after a CSV round trip, every note criterion of the
listed rulesets has a slot, no reserved identifier, every planted-state share within ±5 points (`--profile ci`, 5,000
patients: JP-A + TW-A) or ±2 points (`--profile full`, 500,000: JP-HEAD 300,000 + TW-A 200,000); a cell is compared
only when 3 binomial standard deviations fit in the tolerance (8 small cells such as pregnancy among women aged
18–45 are skipped on ci; none on full). Measured on the build container (2026-11-07): ci 2.9 s; full 291 s, 2.4 GB on
disk, 975 MB peak memory, 126 of 126 rate cells within ±2 points (largest gap 0.27 points). The full profile is not
run in CI. Synthea stays optional and off (`--synthea` only reports that). (3) Console S2: the protocol page takes
pasted criteria (`criteria`, one per line; a line that is only "Inclusion/Exclusion criteria", 選択基準/除外基準 or
納入條件/排除條件 switches list) and sends `FEAS <id>` with a `criteria.md` the parser reads; criteria that match the
approved ruleset of that id run at once and the browser lands on S3 (`/studies/{id}/feasibility`), anything else is
compiled for review as before (approval is step 2). (4) Settings: `ethics_gate` (always off with `TB_ENV` DEV or
TEST, else the value, on when unset; F6-03) and `schedule.mode` (`auto`: DEV runs on demand, no timed jobs, FR-OPS-12
/ F6-30; `nightly`; `on_demand`), with `orchestrator.scheduler.run_now` for the on-demand path. An unset `TB_ENV` is
read as PRODUCTION for both, so an install that forgets it keeps its schedule and its gate. (5) `python -m
tools.feas_demo` builds the ci hospital, joins the two sites into one 5,000-patient lake, signs in as the coordinator
in Japanese, pastes the GOUT-COH criteria on S2 and lands on the S3 funnel (5,000 → 1,485 gout diagnosis → … → 5);
`tests/integration/test_feas_demo.py` runs the same path. Not done here: JLAC10 lab codes, YJ drug codes and 保険病名
on JP sites (JP sites reuse the TW code columns so the existing `tw_core/demo_his.yaml` mapping and rulesets read
them; terminology is TB-DS-10 work); the SS-MIX2 folder writer (H); per-study expected eligible rate in the generator
summary (the FEAS funnel on the demo gives it); the GOUT-COH criterion labels stay as authored (zh-TW) inside a
Japanese report. TB-DS-21 §5 calls GZQO "the early-Alzheimer study"; in this repository GZQO is the gout trial.

## Simple build plan, step 2: list and mail (2026-11)

**D-107 Clinic workbench** (numbered D-105 on its branch; renumbered when it was taken into build step 2). Changfu tried the D-104 pages on 6 Nov 2026 and found them still not role-based or
clinical ("no work bench, patient list?"). He approved a clickable mockup modelled on clinical software (EMR clinic
lists and in-baskets, research pre-screening tools, trial management pipelines). The weekly list
(`/studies/{rs}/week`) becomes the PI's workbench: worklists on the left (clinic visits in the next 14 days, needs
my review, waiting for information, approved and contacted, all), a patient table in the middle (next visit,
doctor, criteria met as a count and bar, still needed, status), and a chart-style panel on the right with a banner,
the deterministic "why this patient" sentence, the three decisions (approve for contact, ask the coordinator, not
suitable with a reason and a note) and every criterion grouped by inclusion and exclusion with its result, source,
date and verbatim quote. A decision returns to the same list and patient with a confirmation. The coordinator's
home becomes "My work": a task list derived from the PI's decisions and the study state (contact a patient the PI
approved, due two days after the decision; find information the PI asked for, due in three days; prepare for a
candidate's visit in the next two days; approve a waiting run; fill the site fields), coming clinic visits of
candidates, and per study a pipeline (found, PI reviewed, contacted, consented, enrolled; cumulative) and the six-step
procedure bar (protocol in, criteria approved, feasibility report, weekly PI list, contact and screen, enrolled),
which also heads the PI's workbench. Tasks are computed on each view, never stored, so they cannot drift from the
marks and the registry. No scripts were added (the console's CSP stays `script-src 'none'`); selection is a link.
`tools/role_demo.py` seeds a few PI decisions and registry steps so the demo opens in a working state.

**D-108 Build step 2: one approval page, one mark vocabulary, the screening log and the clinic mail.** Build step 2
of `20-build-map.md` §2 (list and mail). What was decided, and why:

* **S20 approval** (`console/approval.py`, `/pilot/jobs/{id}/approval`): one page per draft, one row per criterion
  from the compiler's review workbook, the codes folded under the row, and one **Approve all**. Only the
  investigator approves (FR-AUTH-13): the approve route checks `User.can_approve` (role investigator); administrators
  and coordinators prepare the approval by ticking a row's codes as checked, which is its own audit event
  (`console.code_tick`) shown on the row. Amber rows (compiler flags, CQL/SQL equivalence below 100 %, left to a
  person, or new or changed since the approved version) must each be opened by the approving investigator before
  Approve all is offered; opening is a link the server records (`console.approval_open`), since the console runs no
  script. A re-approval shows **Changes since vN** (added, new wording, new check class, removed) against the
  approved ruleset. Approve all sends the same `APPROVE <study> version=<v>` with the stored workbook as a reply to
  the review mail; the orchestrator still checks the approver against `reviewers`. Line edits on the page
  (FR-FEAS-12b/c) are not built: an edited workbook still goes by mail. The old job-page approve buttons are gone.
* **Feasibility Refresh** (FR-FEAS-13): a button on S3 for the coordinator that runs `FEAS <study>` again with the
  approved criteria on today's snapshot.
* **No model confidence and no judge model name on clinical pages** (FR-UI-17): removed from S5, from the weekly
  list rows and from the SCREEN job page's quotes; the judge line on the job page shows for administrators only. The
  admin home keeps the models; the audit trail keeps everything.
* **One mark vocabulary** (FR-SCR-07, TB-DS-09 §6): Approach (声をかける / 邀請), Need info (情報が必要 / 需要更多資訊),
  Not suitable now (今回は見合わせる / 暫不邀請) with a per-study reason, and Not now, re-check on a date (後日再確認 /
  稍後再評估). No mark is ever labelled "not eligible" (FR-SCR-07f, tested). A new mark replaces the current one;
  **Withdraw** stores a `withdrawn` event so the history keeps both. "Not now" hides the patient until the date. The
  weekly-list status `not_eligible` is split into `set_aside` (a PI's mark) and `closed` (excluded by the records or a
  terminal registry status). Reasons per study come from study settings, defaulting by disease (FR-STUDY-09: AD,
  RA, other); the settings live in the console's site store until S21 (step 3) edits them.
* **Screening numbers and the ICH E6(R3) screening log**: Approach gives the patient the study's next screening
  number (`<STUDY>-0001`, prefix and first number per study; never re-used or moved); so does a first contact
  outcome. `/studies/{rs}/screening-log` (and `.xlsx` for the coordinator) lists everyone approached: number,
  pseudonym, first listed, the PI's mark, the last contact outcome and attempts, the registry status and reason. It is
  pseudonymous; chart numbers stay with the existing registry export.
* **Contact outcomes in two taps** (FR-SCR-10c, TB-DS-07 §4.1) for the coordinator on S5 and the list panel: reached,
  visit booked → contacted; reached, declined → declined; not reached → status unchanged, a retry date (default two
  days); not approached (physician decision) → unchanged, reason recorded; lost contact → screen_fail "lost contact".
* **Cohort list** for registry and observational rulesets (kind cohort or nhi: GOUT-COH, RA-COH, RA-BIO):
  `/studies/{rs}/cohort` lists the members a SCREEN run found that were never listed before; no marks, no contact
  step; a dynamic cohort also counts members who no longer meet the definition. A cohort ruleset has no
  `routing.list_to`, so SCREEN now sends its member list to the coordinator who asked (and only them); the SCREEN form
  takes the clinics (practitioner ids) a cohort list reads. Nothing in the evaluation changed.
* **N1, the investigator's list before clinic** (FR-NOTIF-01, `console/notify.py`): one mail per investigator across
  their studies on each clinic day, with today's candidates first and the rest of the week folded below. A clinic day
  is a day the investigator's practitioner id (set on the notice settings page) has a listed candidate booked, read
  from the appointment source the SCREEN run used; without an id the mail goes on Mondays with the next seven days.
  **N2, the coordinator's digest** (FR-NOTIF-02): working days, today's visits, next steps (call an approved patient,
  retry a call when due, find requested information), new pre-screens and the PI's marks since the last digest. Both
  carry pseudonyms, times and counts only, never a chart number, a name or a screening number (screening numbers
  added beside the pseudonym by D-136); each says why it was
  sent and links to the person's notice settings (FR-NOTIF-09). They leave through a new orchestrator `POST /notices`
  (aggregate tag, internal addresses only, audited `notice.sent`) and are sent at most once per person and day.
  Sending is `python -m console.notify` (for the site's 07:00 / 07:30 timer) or "Send today's notices now" for an
  administrator; the orchestrator's own scheduler does not send them yet.
* **Research office counts** (FR-REP-09): `/reports/research-office` and `.xlsx`, per study and calendar year:
  listed, reviewed by the PI, approached, contacted, consented, enrolled, screen fail, declined; counts 1 to 4 are
  shown as `<5`. Administrators, viewers and coordinators; not the CRO.
* **The clinic workbench (D-107) was merged in step 2, not step 4**, because the step-2 list, marks and S5 are built on
  its pages; merging it later would have rewritten the same templates twice.

Matching is unchanged: no file under `services/matching`, `services/criteria_compiler` or the evaluation in
`orchestrator/scenarios/screen.py` changed (the SCREEN edit is the cohort list's delivery address only), so the
SIGIR lost-pairs check was not rerun. Demo: `python -m tools.list_demo --dir /tmp/tb-list [--serve]`.

**D-109 Build step 3: the REDCap simulator, the read connector, the project link and the S-28 study store.** Build
step 3 of `20-build-map.md` §2 (REDCap link). What was decided, and why:

* **REDCap API simulator** (`services/rc_sim`, FR-RC-09/17, TB-DS-08 §4.4 ICD-04S): `POST /api/` with REDCap's form
  fields answers R1 version (configurable, default `16.0.10`), R2 project, R3 metadata, R7 flat record export
  (`records[]`, `fields[]`, `events[]`, `dateRangeBegin`, `exportDataAccessGroups`) and R8 dag; every other
  `content` answers 501 with a REDCap-style `{"error"}`; a wrong token answers 403 with REDCap's text; an optional
  rate limit answers 429. Two JSON fixture projects with differently named fields: A (classic, `record_id`,
  `tb_screening_no`, `consent_date`, `enrolled`, `sf_reason` radio, `subject_no`) and B (longitudinal, events
  `screening_arm_1` / `m12_arm_1`, DAGs, `rec_id`, `icf_dt`, `rand_yn`, `withdrawn`). `POST /sim/records` adds or
  edits records (stamped in the site zone) and `POST /sim/metadata/rename` renames a field, the demo's and tests'
  levers. Written from the public REDCap API documentation only. It is in the demo image (`COPY .`), reachable as
  `inproc://rc-sim` from the console only when `TB_ENV` is DEV or TEST (FR-RC-17a), or standalone as
  `python -m rc_sim` (port 8790). The fixtures live in `services/rc_sim/fixtures/`, not `fixtures/rc_sim/` as
  ICD-04S says, so the simulator ships as one package.
* **rc-bridge read connector** (`services/rc_bridge/client.py`, IR-03a): one httpx form post per method. The ICD names
  PyCap; it is not a dependency of the build and five read methods do not need it. Errors map to the register:
  403 → RC-TOKEN, 429/503 → RC-RATE, other errors → RC-UPSTREAM, majors other than 14–16 → RC-VERSION. The token
  is never logged, put in an error, an audit record or `studies.db`.
* **Project link** (`services/rc_bridge/link.py`, ICD-04 §4.1a, FR-RC-16) in the `tb_screening_no` mode only (the
  `mrn` mode is H and is refused with RC-LINK-MODE). Saving a link reads R1–R3 and checks every named field, the
  enrolment and withdrawal codes and the screen-fail choice map against the data dictionary (RC-LINK-FIELD, with the
  fields named). A read-back joins records by the screening number the console issued; a longitudinal record is
  merged across events and the consent date is taken only from `consent_event`; records outside the link's DAG are
  ignored. One status per record: withdrawn > enrolled > screen-failed (reason category from the choice map:
  inclusion, exclusion, consent_withdrawn, lost_contact, other) > consented. Two records with one screening number
  (in one read or against a record already joined) are RC-LINK-DUP and change nothing; a number no TrialBox patient
  has is "in REDCap, not in TrialBox".
* **Status read-back** (`orchestrator/study_api.py`): REDCap wins for its four statuses, written to the registry with
  `source=import` and `by=rc-bridge`; a patient goes through *consented* where the registry has no direct step (a
  new row starts as a candidate, so enrolment records the consent first). A transition the registry does not record
  (TrialBox *declined*, REDCap has a consent date) is a conflict listed for the coordinator, never forced. A renamed
  field turns the link off with its problem shown; the next good save turns it on. R7 reads changes since the last
  read minus one day (a clock or zone skew never loses a change; applying a status twice is a no-op).
* **S-28 study store** (`orchestrator/studystore.py`, `<data_dir>/studies.db`): `study_settings` (study type, cohort
  kind, consent scope, screening-number format and next number, "Not suitable" reasons, entered by/at),
  `rc_connection` (token name, base URL, version and project found, last test), `rc_project_link`, `rc_record`
  (record id, link value, pid, consent date, sponsor subject number) and `rc_read_log`. Tokens are 0600 files
  under `<secrets_dir>/redcap/<name>`. The console edits the store only through the orchestrator routes listed in
  the module docstring. **The step-2 study settings moved here**: S21 saves to S-28 and the list, the numbers and
  the reasons read S-28 first (`console/s28.py`, 5-second cache on the backend); a study never saved on S21 keeps
  its step-2 site-store value or the default by ruleset, so nothing changes until a coordinator saves. The
  screening numbers themselves stay in the console's site store, which issues them; each read sends the number →
  pid map.
* **S21 Study set-up** (`/studies/{rs}/setup`) in three sections: 1 Study (type, cohort kind, consent), 2 REDCap link
  (field map, Test link with the first three joins, the last read-back with changes, duplicates, conflicts and
  unmatched numbers, **Run now**), 3 Screening log (number prefix, next number, reason list). The coordinator edits;
  the investigator and others on the study read (the investigator's confirm step is H). **S36 REDCap connection**
  (`/admin/redcap`, administrators; viewers read): base URL and named tokens, entered once into a password field and
  shown masked (`••••8F90`), **Test connection** (R1 + R2). The screening log shows the REDCap record id and the
  subject number, the read-back block and Run now; its XLSX gains `redcap_record_id` and `subject_no`.
* **Site time zone** (step-2 follow-up): `console.timefmt.site_zone` prefers `site.tz` over `env.tz`, and the demo's
  in-process backend exposes the box's config, so demo pages no longer fall back to UTC.
* **Nightly read-back**: `python -m console.rc_read [--study RS]` for the box's timer after the nightly ingest, the
  same call as Run now; it skips links that are off.

Demo: `python -m tools.rc_demo --dir /tmp/tb-rc [--serve]` (after the step-2 run: S36 connect, S21 link, create then
change the record in the simulator, Run now twice, see consented then enrolled in the log).

**D-110 Build step 4: role homes, the header command field, three languages.** Build step 4 of `20-build-map.md` §2.
What was decided, and why:

* **Homes.** After sign-in every pilot role lands on `/home`, which is its work list: the investigator's "This week"
  (`/week`, S16), the coordinator's work list (S8), the administrator's S13 admin page, the viewer's and CRO's
  reports (S3/S4). The service overview at `/` stays for the administrator under More (its tests and the POC walk
  use it); it is no longer an entry page (S1).
* **Header command field** (`console/command.py`, S1, replaces S28): one box in the header of every pilot page.
  `interpret(text, studies, role)` is pure: first the mail grammar (`channels.grammar.parse_line`; FEAS, SCREEN,
  STATUS, APPROVE and REJECTGATE are also taken in lower case), then a ja/zh-TW/en phrase table (longest phrase
  wins), then search (study code, hex pseudonym prefix, screening number; never a chart number). **The field only
  opens pages**: SCREEN and FEAS NEW open their request page pre-filled and nothing runs until the user presses the
  button there; APPROVE / REJECTGATE are refused (approval is on S20 only, FR-AUTH-13); mail-only commands and mark
  aliases say where to go instead. Targets are limited by role and checked again by the target page. Text that is
  not understood shows examples and does nothing. The audit keeps `console.command` with the intent only, never
  the typed text. The phrase table is builder-written (F6-26); a site adds its own at install (H).
* **Command test set**: `tests/console/data/command_set.json`, 96 phrasings (40 en, 28 ja, 28 zh-TW) across the five
  roles, including role refusals and not-understood text. Right = expected action and study; wrong = a different
  page opened. Score in `command_set_score.json` (`python -m tools.command_score --write`): 96/96 right, 0 wrong.
  The set was written before it was first scored; that run had one wrong (`cohort HTN2` read as the v1 COHORT
  job), fixed by limiting lower-case grammar to the five commands above, and one expectation error.
* **S22 My account** (`/account`): name, role, affiliation, studies, expiry, last sign-in, language, password change
  (non-SSO; signs the account out everywhere, so the user signs in again). TOTP is H.
* **S29 Help panel** (`/help?back=`): the "?" in the header opens help for the page it came from (a page, not a
  side drawer), the role, the command field with the role's examples, and the site contact. User guide is H.
* **S37 Notices received** (`/notices/received`): the person's rows of the site store's `notify_log`, newest first,
  linking to the list as it is now. The notice bodies are not stored, so "last Monday's list as sent" is H.
* **S13 admin page** (`/admin?tab=health|jobs|sources`): Health (services, job queue, models, accounts, approvals,
  audit 24 h; GPU, disk, backup and audit-chain tiles are H), **S26 Jobs** with filters (study, type, state, day),
  Cancel on queued or running jobs (orchestrator `POST /jobs/{id}/cancel`, new `HttpBackend.cancel_job`) and Retry
  on failed jobs (a new job with the same type, ruleset, options, comment, requester and inputs); both ask to
  confirm and are audited (`console.operate` cancel / retry). **S24 Data sources** reads the adapter's
  `ingest.done` / `ingest.failed` audit records (source, last success, patients, records, validation error rate,
  last 30 runs; amber after 48 h) and keeps "Run ingest now".
* **Languages.** All step-4 strings in `console/i18n_step4.py` in en, ja and zh-TW; a test checks every key in every
  language with the same placeholders, and the step-4 pages in ja and zh-TW for English. The REDCap read-back note
  on the screening log is shown in the reader's language (the stored note stays language-neutral); the service
  state pills are translated. The TB-DS-09 §6 mark labels were already in step 2; "Ask treating doctor"
  (主治医に確認 / 詢問主治醫師) is added for FR-UI-15. Ruleset content (criterion labels, PI notes) and service
  details stay as written; native review of the JA and zh-TW wording is H (OQ-14).
* **Phone**: the header field takes the full width under the nav with "?" beside it; no page of the walk scrolls
  sideways at 390 px.
* **Browser walk**: `tests/e2e/role_walk.js` with `tests/e2e/test_role_walk.py` (marker e2e, no stack: it starts the
  role demo): 5 roles × 3 languages × desktop and phone, 210 checks (lands on the home, page language, field
  placeholder, the field opens help from a phrase in that language, My account, no sideways scroll on the phone).

Demo: `python -m tools.role_demo --fresh --dir /tmp/tb-roles` and sign in as admin, crc, pi, viewer or cra.

## Simple build plan, step 5: end to end and the demo (2026-11)

**D-111 Build step 5: `e2e_simple` is the build gate; the model gate replays offline; the demo is one image.** Build
step 5 of `20-build-map.md` §2, stub model, no keys, no cloud.

* **`e2e_simple`** (`tools/e2e_simple.py`, `make e2e-simple`, `tests/integration/test_e2e_simple.py`,
  `.github/workflows/trialbox-e2e.yml` on every pull request touching `trialbox/`; FR-OPS-11). One synthetic hospital
  (ci profile, 5,000 patients) through criteria pasted → FEAS report → investigator approval → SCREEN → list and
  cohort list → marks → N1/N2 mail → REDCap simulator record → Run now → screening log (HTML and XLSX). 48 checks in
  nine stages, each against something the step did not compute itself: the generator's counts, a recount of GZQO-INC-01
  and -INC-02 from the hospital CSVs (exact), the sent mail (no chart number, name or screening number), the raw audit
  chain (verified), and a byte-identical re-run of FEAS and SCREEN (FR-REP-02). About 75 s on one core (budget 15
  min). It runs with `TB_ENV=DEV` as the demo does; the pytest wrapper sets it, because the test conftest clears
  `TB_*`.
* **FR-REP-01.** The feasibility and screening JSON carry a `provenance` block: study, ruleset and version, snapshot,
  data sources, models that ran and prompt versions (none for FEAS, D-101), run date, clock, job id, language. It is
  built from the job only, so re-runs stay byte-identical.
* **FR-AUD-01b.** A chart-number reveal records its reason (contact, eligibility, consent, other) from a select on the
  patient page and the job page; a request without one is recorded as `not given`, never guessed.
* **FR-AUD-01e.** The REDCap read-back audits every registry status change by pseudonym (`redcap.read`
  `status_changes`), not only the count. Investigator marks (`console.pi_mark`) and contact outcomes were already
  audited.
* **Simulator routing.** The orchestrator's DEV/TEST registration of `inproc://rc-sim` no longer replaces a
  simulator a demo registered first, and `rc_demo` makes a fresh simulator per run. Before, a demo's records went to a
  simulator the box did not read whenever `TB_ENV=DEV` was set.
* **Model gate, offline** (`tools/parity_replay.py`, `eval/parity/replay.json`). N-11 replays the recorded SIGIR
  answers (both must block, filter first): deployed files on the card 4/79 EN and 3/79 JA (pass; = the recorded
  baseline), zh-TW **not recorded** for those files; the API 4-bit proxy of the same models 1 / 2 / 1 (zh-TW answers
  vendored byte for byte from the LLM-survey branch). N-12 recomputes the recorded TREC projection: 3.6 % (95 %
  2.1–5.6), pass on the point estimate, at API precision. Without NCBI's `trial_info.json` the replay scores all 1,015
  criteria; the lost-pair counts equal the committed 1,000-criterion tables on every recorded run.
* **FR-MOD-10 record** (`tools/serving_config.py`, `docs/SERVING_CONFIG.md`): card, vLLM version, `max-model-len`,
  `max-num-seqs`, eager flag, memory fractions, KV dtype and the sha256 of every model file; `validate` lists gaps.
  The GPU VM's startup script captures it once both servers answer and serves it on :80
  (`deploy/gcp/capture-serving-config.sh prepare|fetch`); not run (no GPU here). The 6 Nov configuration is recorded
  by hand without hashes.
* **Demo** (`tools/demo.py`, `make demo`, `make demo-bundle`, `demo/Dockerfile` now defaults to it,
  `deploy/gcp/demo-vm-startup.sh`, `docs/DEMO_VM.md`): seeds and checks the step 1–4 flow, then serves the console.
  How the CPU VM would be started is written down; no VM was started.
* **Not done, on purpose or by limit.** The PHI pass on note text (FR-DEID-01, the "D3 copy" of TB-DS-04 §3.4.1
  stage 0) is not built: the lake keeps the generator's planted names and phone numbers in note text, so stage 0
  checks only that structured tables carry no chart number, ID or phone column and that keys are pseudonyms. "Planted
  eligible patients are listed" has no generator truth list in the ci profile; stage 3 checks that no note answer can
  exclude a patient (single stub judge, `note_block` never) instead. The demo image was not built here (no Docker
  daemon in the build container).

**D-112 One RTX 5090: the sleep swap ships, the profile follows the 8 Nov measurement, install needs a real-card
record.** Fable review 2026-11-08 finding 1: the shipped `docker-compose.rtx5090.yml` was the resident pair measured
not to fit (35,810 MiB on the 8 Nov card run; "pair-tight" short of KV cache).

* **From PR #23** (LLM survey thread, branch `claude/project-thread-9eosz0`, merged here as is rather than rebuilt):
  the sleep swap (`services/gateway/swap.py`, `POST /v1/serving/activate`), the judge-then-verifier run
  (`services/orchestrator/twophase.py`, used by SCREEN and the cascade), the compose start order
  (`judge-sleep-init`, `model-swap-init`), vLLM v0.32.0, the night self-test (`orchestrator/selftest.py`, the
  54-case canary), weight re-check at install, the 30 s chat limit and the CJK quote-space fix
  (`tb_common/quotes.py`). Whichever of the two branches merges second carries no extra work.
* **Measured values.** Both servers at 0.81 of a 5090 (the 26.4 GB budget measured as 0.27 of 97,887 MiB on
  2026-11-08: judge awake 29.6 GB in all, asleep 1.3 GB; sleep 0.4–3.7 s, wake 0.3–0.5 s), 8k context, 4 sequences,
  eager, default guided backend.
* **Install guard.** `install.sh --gpu rtx5090` refuses to start the pair unless `deploy/site/serving_config.rtx5090.json`
  passes `tools.serving_config measured rtx5090` (complete record, a 5090 card that is not a capped larger card,
  `--enable-sleep-mode` on both servers), or the operator sets `TB_ACCEPT_UNMEASURED_GPU=1` for a first trial boot.
* **Not done.** The answers after a wake were not captured on the 8 Nov run (empty smoke answers in `fit.json`), and
  nothing has run on a physical 5090.

**D-113 A code-prefix grouper fails closed: coded inside the family but not in the list is unknown.** Fable review
2026-11-08, finding 2: on the public-data run 26 patients coded C80.1 / C50.9 / C25.9 were counted "not malignant"
because the demo terminology did not list those codes, and a structured inclusion false drops a patient outside the
two-model rule.

* **The grouper keeps its families.** A synonym row with `match=prefix` ("malignancy" = C0…C9 families) now records
  `(system, prefix)` on the ValueSet as the `code-family` extension (`terminology/mapper.py` `FAMILY_EXT`,
  `ValueSets.families`). Plain lists and exact synonyms carry none, and their SQL is unchanged byte for byte.
* **SQL.** For a presence atom on a grouper ValueSet the generator adds a `<atom>_off` CTE: records in the window
  coded inside a family but not listed. When the listed codes do not settle the atom and such a record exists, the
  atom is NULL (unknown), never false (or, for `none`, never true). FEAS, SCREEN v1 and the v4 cascade all read the
  same SQL. The unknown carries the records and the reason `code_outside_list` (cascade `CODE_OUTSIDE_LIST`,
  `structured_verdict`), so the reviewer sees which record caused it.
* **Terminology.** The demo `icd10cm_tw` adds C25.9, C50.9 (WHO ICD-10), C79.9, C80.0 and C80.1.
* **Evidence.** `tools/public_e2e.py` now recounts the malignancy step from `diagnosis.csv` by ICD-10 family, not by
  the list, and asserts that every cancer code in the data is listed (the always-true check is gone). Public run:
  INC-02 41 (was 15), SCREEN listed 90 (was 65).
* **Not done.** The CQL path (HAPI `$evaluate`) still reads the enumerated list only; the SQL engine is the default
  and the equivalence gate's fixtures have no off-list family codes. A family is matched within its own code system
  only, so a site exporting WHO ICD-10 under another system URI needs its mapping first.

**D-114 A service token on every changing call to the orchestrator; the audit actor comes from the caller's
header.** Fable review 2026-11-08, finding 3: `POST /jobs/{id}/reveal` returned a chart number to anything on the
compose network, with a free-text `by` as the audit actor.

* **Token** (`tb_common/service_auth.py`): one shared secret per box, `TB_SERVICE_TOKEN` in `deploy/.env`
  (`install.sh` and `poc.sh` generate it; a `change-me` placeholder counts as none) or a file named by
  `TB_SERVICE_TOKEN_FILE`. The orchestrator's middleware refuses every POST/PUT/PATCH/DELETE without
  `X-TB-Service-Token` (401) or with a wrong one (403, constant-time compare). With no token, DEV and TEST boxes
  stay open (tests, `make demo`); any other `TB_ENV`, and an unset one, refuses changing calls with 503.
* **Callers.** `ServiceClient` adds the token on calls to the orchestrator only (console, mail gateway); the channel
  relay adds it to its `POST /jobs`.
* **Actor.** Reveal, notices and cancel take the actor from `X-TB-Actor` (the console's signed-in user,
  percent-encoded so Japanese names pass), not from the body or query. A token holder that names no user gets 400.
  The body `by` is read only on a DEV/TEST box without a token.
* **Not done.** Reads (`GET /jobs`, pseudonyms and counts only) stay open on the internal network; no mTLS; no
  per-actor rate limit on reveals; registry writes still record the body's `by` (behind the token).

**D-115 The two-model rule is tested on both SCREEN paths; the canary scores the pair.** Fable review 2026-11-08,
finding 4: only the cascade's `AgreementJudge` had a disagreement test, and the 54-case canary was a one-off per
model.

* **Tests** (`tests/unit/test_note_pair_disagreement.py`) on v1 `NoteJudge.judge_excerpts` and the v4 cascade's
  `OrchestratorJudge`, with fake models: judge pass / verifier fail and the reverse → `unknown`, one disagreement,
  tier `review`; agreement → excluded at the threshold; verifier down → `unknown` and a failure, never an exclusion;
  judge `unknown` → the verifier is not asked.
* **Confidence.** When both agree the answer carries the lower of the two confidences (it was the judge's alone),
  so a confident judge and an unsure verifier send the patient to review rather than out.
* **Reason.** A verifier whose quote is not in the notes is named as such, not as a plain disagreement.
* **Canary as the pair.** The 54-case file is in the product (`orchestrator/canary/judge_canary.jsonl`, from PR #23)
  and the night self-test (`orchestrator/selftest.py`, run by the scheduler before LLM jobs) now also scores the
  pair as the box decides: `pair_report` counts the cases where both models give the same decided answer and it is
  wrong; more than `MAX_PAIR_WRONG` (1) fails the self-test, and the night's LLM jobs do not start. `make canary`
  runs it from a checkout against the configured models; the audit line carries the pair summary.
* **Not done.** The pair canary has not yet been run on the card; the 8 Nov per-model numbers (judge 53/54, verifier
  47/54 before the CJK quote fix) suggest it passes.

**D-116 One swap per screening run on the one-5090 box; the run holds the card and releases it.** TB-PLAN-03 step
1 (Fable review 2026-11-08, finding 1). PR #23's sleep swap (D-112) asked judge, verifier, judge for every run: two
swaps, and the judge woken at the end even when nothing needed it.

* **Hold and release** (`services/gateway/swap.py`). `POST /v1/serving/activate` takes `"hold": true`: a screening
  run keeps the card until `POST /v1/serving/release`. While held, a call to the sleeping model is refused as before
  (`model_busy` for chat, `model_asleep` for a batch caller). When nobody holds it, a call to the sleeping model
  wakes it on demand (`ModelSwap.ensure`, audited as `llm.gateway.swap` by `on-demand`); a batch call keeps the hold
  alive, and a hold that is never released lapses after `TB_SWAP_HOLD_S` (3600 s).
* **Lazy rounds** (`orchestrator/twophase.py`). The judge is woken only when a judge question has no memo answer,
  the verifier only when questions are pending, and a swap to the model already awake is skipped (`Gpu`). A run
  whose merge round opens no new path costs one swap (judge -> verifier); a run that opens one (the v1 full-record
  retry) adds a judge and a verifier batch. At the end the run releases the card instead of swapping back. The
  night canary does the same (`run_selftest(..., release=)`).
* **Fit script.** `deploy/gcp/gpu-fit-test.sh`'s `ask` ran `docker exec` without `-i`, so the model never saw the
  question and 8 Nov's `fit.json` stored every case unparsed; it now uses `-i`, escapes the log lines as JSON and
  writes `null` for a missing reading.
* **On the card** (`deploy/gcp/gpu-swap-run.sh`, `tools/wake_check.py`, `tools/public_e2e.py --swap`): the RTX PRO
  6000 capped to the 5090 (0.27 of 96 GB each, `--enable-sleep-mode`, vLLM v0.32.0). Results of the 2026-11-08b
  run (`eval/parity/*2026-11-08b*`, raw files in `trialbox-build/gpu-run-2026-11-08b/`):
  * *Answers after a wake.* SIGIR EN, filter first, both-block rule, 1000 calls a pass: the pair resident and the
    pair after a wake both lose 4 of 79 eligible pairs, false-block rate 0.00517, block recall 0.515: equal. Per
    model: verifier 4 and 4 (label agreement 0.998), judge 11 resident and 10 after the wake (agreement 0.904). A
    second judge pass after another wake agrees 0.912 with the first wake and 0.903 with resident, so the judge's
    ~9 % label drift is run-to-run nondeterminism, not the wake.
  * *Swap cost.* Sleep (level 1) 3.8 s first, 0.6 s after; wake 0.4-0.6 s; a pass of 1000 calls 317 s (judge),
    343-387 s (verifier). Peak card memory 29,631 MiB with the judge awake (5090: 32,607); verifier awake with the
    judge asleep 28,414 MiB.
  * *Boot to SCREEN* (`public_e2e --swap`): 94/94 checks in 1401 s; each SCREEN run 1 swap (0 when every answer was
    in the memo), no wake check failed; 8 swaps in all, 2 of them on-demand wakes.
  * *Found.* The CONSENT job asks the verifier inline, outside `two_phase`: on the box the gateway's on-demand wake
    covers it (a direct call to a sleeping vLLM hangs), and the harness drives the same `ensure` path.
  * `serving_config measured rtx5090` correctly refuses the record (capped card, not a 5090); a real 5090 is still
    needed for that profile's measured record.

**D-117 The pair canary gates note exclusions.** TB-PLAN-03 step 2 (Fable review 2026-11-08, finding 5). The 54-case
canary only held the night's LLM jobs; a box whose models had drifted could still exclude on a note answer by day.

* **The gate** (`orchestrator/canary_gate.py`). `effective_note_block` lets a note answer exclude only with a
  passing *pair* canary younger than `TB_CANARY_MAX_AGE_H` (36 h) and no failed wake check since; otherwise the run
  falls back to `never` (review, never out) and says why. The report is kept in `<data dir>/selftest.json`, so a
  restart keeps the gate. `MAX_PAIR_WRONG` is now 0: one case where both models agree on a wrong decided answer
  fails the canary (it was 1).
* **When it runs.** At orchestrator start in the background (`TB_CANARY_AT_START`, default on), before each night's
  LLM jobs (scheduler, as before), and from the admin Models tile's "Run now" (`POST /models/canary` on the
  orchestrator, behind the service token; `POST /admin/models/canary` in the console).
* **After each swap.** On a one-GPU box every woken model first answers six canary cases (`wake_cases`: one per
  criterion; each language and each expected answer twice). A flip, fewer than five right or more than one
  unanswered: the model is not used for the rest of the run (its answers become errors, so `unknown`) and the
  gate stays shut until the next full pass.
* **Switch.** `TB_CANARY_GATE` on | off; unset it is on except with `TB_ENV` DEV or TEST, whose stub models never
  pass a canary. The test suite sets it off and the gate's own tests switch it on.
* **Shown.** The admin Models tile shows the gate's state, the date and the pair's score, translated, with a Run now
  button; `GET /models` carries it as `canary`. `make canary` runs `tools/canary.py` from a checkout (environment
  models, or two servers directly with `--swap`, which also runs the wake check after each wake).
* **On the card** (2026-11-08b, `eval/parity/canary_pair_2026-11-08b.json`): the pair canary with swaps passes,
  pair 52 of 54 right, 0 decided wrong, 2 disagreements (left to review); judge 53/54 (`ja:preg:yes`), verifier
  49/54 (four silent cases answered `fail`, `ja:chemo:yes`), one flip each. The three wake checks (judge twice,
  verifier once) all pass; each swap measured 13-17 s by the tool (sleep of one plus wake of the other, after the
  long run). The start canary in `public_e2e --swap` gave the same pair score and opened the gate.
* **Test note.** `test_frontdoor_mcp::test_small_cells_are_suppressed_and_rounded` failed once in a full-suite
  order and did not reproduce alone or in its file order. Its counts and rounding are deterministic and the
  privacy accountant is per box, so the likely cause is shared rate-limit state left by an earlier frontdoor test
  (`test_roles_profiles_and_rate_limits`); not chased further, since Hermes and the front door go in step 6.

**D-118 One note-judge path; reasons are codes.** TB-PLAN-03 step 3 (Fable review 2026-11-08, findings 4, 6 and
10). Three copies of the two-model rule (v1 `NoteJudge`, the cascade's `OrchestratorJudge`, the tools'
`AgreementJudge`) and free-text reasons on every candidate row.

* **One rule.** `tb_common/pair.py` `combine()` is the only place a pair's answer is decided: an undecided judge
  answer is not put to the verifier; a verifier that did not answer → `unknown` / `model_down` (a failure for the
  >10 % gate); a verifier quote not in the notes → `verifier_quote_missing`; another verdict → `disagree`; agreement
  keeps `min` of the two confidences.
* **One judge.** `NoteJudge.judge_excerpts(criterion_text, note_question, index_date, excerpts, ...)` is the one
  method that puts a note question to the models (`grep -n "def judge_excerpts"` finds one). The v1 evaluator
  (`judge_patient`), CASE chart uploads and the cascade call it: `OrchestratorJudge` is now a `NoteJudge` subclass
  whose `judge(role=...)` only adapts the reply; `AgreementJudge` calls `combine()`.
* **Minimum confidence.** A decided answer below `MIN_CONFIDENCE` (0.5) is not used: `unknown` / `low_confidence`,
  so a person looks. The tier threshold (0.75, review below) is unchanged.
* **Reasons.** `Evidence.reason` on every candidate row is a `tb_common.reasons.Reason` code (`coded`, `note`,
  `data_gap`, `no_notes`, `not_mentioned`, `code_outside_list`, `abstained`, `quote_not_found`,
  `verifier_quote_missing`, `disagree`, `low_confidence`, `model_down`, `refused`, `human`, `not_evaluated`,
  `not_in_snapshot`), with words in en/ja/zh-TW in `LABELS`. The model's own sentence stays on `NoteResult.model_reason`
  (audit, debugging) and never reaches a page; an endpoint's error text never reaches a reason. The cascade keeps its
  stage strings internally; `code_of()` maps them where its traces become rows.
* **Not in the snapshot.** A scoped patient the lake does not hold is `review` with every criterion `unknown` /
  `not_in_snapshot`, on both paths (it was excluded).
* **CONSENT and the swap.** `consent.Models` is shaped like a judge (`llm`, `verifier`, counters) and the draft runs
  through `two_phase`: drafting and translation with the judge awake, every statement check with the verifier awake;
  no direct call to a sleeping model.
* **Not changed.** The v1 evaluator stays for NAV, MICROBATCH and CASE and the `TB_SCREEN_PIPELINE=v1` comparison;
  SCREEN runs the cascade (D-103). Both now share the judge, the rule and the reasons, which is what finding 4 asked.

**D-119 Every user-facing word in the page's language.** TB-PLAN-03 step 4 (Fable review 2026-11-08, finding 6).
Japanese and Chinese pages still carried English refusals, feasibility notes, engine tokens (`unknown_kept`, "no value
in the window", "abstained") and Markdown marks in the N1 mail's text part.

* **Refusals.** `console/refusals.py` holds the Japanese and Chinese words for every static refusal the console gives
  (38 today; a test scans the console for `problem(..., reason="...")` and fails on one without words). A refusal the
  table does not hold (an exception's own text) is never shown on a ja/zh-TW page: the page says the request could not
  be done and to ask the administrator; the English stays in the log.
* **Feasibility notes.** `FeasibilityResult` 1.2.0 adds optional `note_keys` (`{key, args}`); `notes` stays the
  English record (XLSX, audit). `tb_common/feas_notes.py` renders them in en/ja/zh-TW for the console and the PDF.
* **Reasons.** `unknown_kept` (an exclusion with no value: not excluded) is its own `Reason` code with words; the
  patient page shows `reason_label(code, lang)`, never the code.
* **Mail.** The text part of every outbound mail is rendered from the Markdown (`markdown_text`): no `##`, `**`,
  table rules or link brackets.
* **Walk check.** `tools/public_walk.js` fails a ja/zh-TW page with a visible leaf cell made only of ASCII words.
  Not counted: codes, ids, numbers, dates, file names (`data-file`), audit details and mail subjects (`data-src`),
  quotes from the notes, user names and anything `.mono`, a person's own typed note (`data-authored`), and the
  study's own words (criterion labels, texts, actions; listed in `walk.json` `authored`), which are shown as written.
  Walk on this head: 422 checks, 0 failures; screenshots in `trialbox-build/walk-2026-11-08/`.
* **Not changed.** An orchestrator failure message (the job's `error.message`) is still English inside a ja/zh-TW
  failure mail; criterion labels stay as the study wrote them (step 5 decides translated labels).

**D-120 PI and CRC lists you can work through; translated criterion labels at approval.** TB-PLAN-03 step 5 (Fable
review 2026-11-08, finding 8; plan §6). On real data the PI list was 65 patients, all "to review", unranked, in one
column, and the feasibility count (23) did not explain the list (65/90).

* **Ready vs needs information.** Two new worklists: *ready* (every criterion answered: no unknown, nothing not met)
  and *needs information* (at least one unknown). Every list but the clinic list (visit order) puts the fewest
  unknowns first, then the visit; 25 rows a page (`?page=`); each row shows its unknown count. `e2e_simple` stage 5
  asserts the split, the order, the page size, the rail counts and the S3 sentence against the rows.
* **Both quotes.** `candidate_list` 1.1.0 adds optional `evidence.opinions` (`role`, `verdict`, `quote`,
  `quote_date`); a disagreement keeps each model's answer and verified quote on both paths (v1 `NoteJudge`, the
  cascade through `JudgeReply.opinions`), and the patient page and the chart panel show both.
* **S3 explains the list.** Under the funnel: the coded-only count, each criterion's unknown inclusions (not counted,
  on the list as needing information) and unknown exclusions kept, the latest list's size split into ready / needs
  information, and the patients coded inside a grouper's family but outside its list (D-113).
* **CRC.** A patient the investigator approved has "Record the call" on its list row: open, tap the outcome (two taps).
  On the phone the menu wraps instead of scrolling sideways, so "More" is never clipped.
* **Public-data site.** `TB_CONSOLE_DATA_SOURCE=public` makes the banner say "public data only, no real patients
  (D0)", not "synthetic". `TB_CONSOLE_STUDIES` limits the request menu to the site's own studies (and the account's
  study scope always applies). The clinician's name comes from the records: the HIS practitioner name is mapped to
  `Practitioner.name` and the lake's `practitioner.name`; `settings.practitioners` only fills a missing name.
* **Translated labels (reverses D-110 for labels only).** At approval (S20), on a Japanese or Chinese page, the
  coordinator or investigator may give each criterion a short label in that language (`console.criterion_label`,
  audited; stored per study, criterion and language in the site store). Pages in that language show the site's
  label with the study's own label beside it and the protocol text under it; the ruleset, the engine and the
  reports keep the study's words. No machine translation: a person writes the label and sees the original.

**D-121 One conversation engine, one object store, one Postgres server; the box's own timers.** TB-PLAN-03 step 6
(plan §2; Fable review 2026-11-08, finding 10). The owner approved removing the Hermes agent layer (2026-11-08).

* **Removed:** the Hermes agent (`integrations/hermes/`, `deploy/hermes/`, `make poc-hermes`, `test-hermes-e2e`),
  the front-door MCP server (`services/frontdoor_mcp/`, `tools/mcp_snapshot.py`, `libs/tb_contracts/frontdoor.py`,
  `libs/tb_common/mtls.py`), the channel relay with its email and fake-Teams adapters (`services/channels/relay/`,
  `native/email.py`, `native/teams.py`, `tools/relay_send.py`), the stub's agent turn (`llm_stub/agent.py`), the
  chat survey tool (`tools/chat_eval.py`), the `hermes` and `frontdoor-mcp` gateway callers, and the doctor's
  `hermes_pin` check. The code stays in git history (before this commit).
* **Kept:** the native engine as the one engine. `NativeEngine(gateway, today=…)` classifies free text
  (`classify_intent` through the gateway, caller `converse-native`); the console's header command box turns the
  intent into a proposal line (D-110). Mail stays the mail gateway's subject grammar; free-text mail is no longer
  understood (it was only the relay's). `channels.engine: hermes` in a site file fails with the removal named.
* **Objects on the filesystem (ADR-16).** `TB_OBJECT_STORE` defaults to `fs:/data/objects`; `minio` is refused with
  a message. Compose drops the MinIO service and mounts one `objects-data` volume at `/data/objects` in doc-parser,
  criteria-compiler, orchestrator, mail-gateway and the POC console. The test stack bind-mounts it on the host
  (`TB_HOST_OBJECTS_DIR`, default `deploy/.objects`) so the compose tests read objects directly. The `minio`
  package left `pyproject.toml` and the lock (`uv pip compile`: minio, argon2-cffi, pycryptodome removed, nothing
  else moved). Contract field names `minio_key` stay (a rename would change every contract for no behaviour).
* **One Postgres server.** `fhir-db` and `workflow-db` become one `db` service with two databases, `hapi` and
  `trialbox_wf` (role `trialbox`, made by `deploy/docker/db-init/10-trialbox-wf.sh` on an empty volume). Volume
  `db-pg` replaces `fhir-pg` and `workflow-pg`: a POC that kept its volumes starts with an empty FHIR store and
  re-ingests. The orchestrator itself still keeps its state in SQLite (`orch-data`); moving it to `trialbox_wf` is
  left for step 10 (backup and restore), where one restore test covers both. `deploy/topology_a/` is unchanged.
* **The box's own timers** (`console/timers.py`). The console schedules N1 (07:00), N2 (07:30) and the REDCap
  read-back (03:00) in the site's zone; `TB_CONSOLE_TIMERS=auto` is on when `TB_ENV` is VALIDATION or PRODUCTION
  and off otherwise (`on`/`off` force it), `TB_NOTICE_N1_AT`, `TB_NOTICE_N2_AT`, `TB_REDCAP_READ_AT` move the times;
  a bad `HH:MM` fails at start. Each timer is the same call as its button and a notice still goes once per person
  and day. They live in the console, not the orchestrator scheduler, because both jobs need the console's site
  store (people, notice settings, project links). `python -m console.notify` / `console.rc_read` stay for scripts.
* **Secure cookie.** The doctor's `secure_cookie` check fails in VALIDATION and PRODUCTION unless
  `TB_CONSOLE_SECURE_COOKIE=1`, and warns in DEV/TEST.
* **Japanese PHI in the log scrubber** (`tb_common.logging.redact`): マイナンバー/個人番号 (12 digits, 4-4-4, ASCII or
  full-width), 保険者番号/被保険者番号/記号番号 after their label, 〒 postcodes, +81 and domestic JP phone numbers
  (mobile 0X0, landline 0X-XXXX-XXXX and 0XXX-XX-XXXX, full-width digits and dashes). The guard's recognisers already
  had them; logs did not.
* **Compose tests without a stack.** With `TB_INTEGRATION=1` and no stack answering on the lake port, the
  `*compose*` integration tests are skipped by name instead of erroring on a refused connection.

**D-122 The Japan data path: an SS-MIX2 reader, a JP mapping, the full ICD-10-CM list and delta FHIR loads.**
TB-PLAN-03 step 7 (`22-optimization-plan.md` §5, §10; finding 2's root cause; `23-fhir-platform-comparison.md`).

* **SS-MIX2 standardized storage reader** (`services/adapter/sources/ssmix2/`, replaces the D-28 stub). It walks
  `<id[0:3]>/<id[3:6]>/<id>/<date>/<type>/` and keeps the newest timestamp per (patient, type, order no); flag `0`
  deletes. HL7 v2.5 text, decoded by MSH-18 (`~ISO IR87` = ISO-2022-JP, or UTF-8), escapes undone. ADT-00 →
  patient, ADT-12/22 → encounter, PPR-01 PRB → diagnosis (標準病名 with the ICD-10 alternate code, or
  `byomei_to_icd10.csv`), OMP-01/02 ORC/RXE/TQ1 → medication (YJ with the ATC alternate code, or `yj_to_atc.csv`),
  OML-11 OBX → lab with the JLAC10 code as `local_code`. Rows are the canonical tables, so the mapping engine and
  `--since` delta work unchanged. Codes that resolve nowhere are counted on the reader (`missed`). Tables SS-MIX2
  does not standardize (vitals, notes, reports, claims, registry, staff, appointments) come from
  `<root>/extended/<table>.csv`. No MLLP listener: SS-MIX2 storage is what Japanese vendors expose.
* **JP mapping template** `mapping/jp_core/ssmix2_site.yaml`: extends the shared resources, tz Asia/Tokyo, YJ and
  JLAC10 code-system OIDs (JP Core), lab lookup `jlac10_to_loinc.csv`. The sample JLAC10, YJ and 標準病名 rows are
  synthetic and marked `verify`. Profiles stay the base mapping's TW Core URLs; a JP Core resource set is not done.
* **Full ICD-10-CM in the terminology.** `terminology/src/icd10cm_2026.csv.gz` (CMS/CDC NCHS 2026 order file, public
  domain, 98,186 header and billable codes) builds `icd10cm_full.parquet`. The mapper uses it for code lookups and
  prefix groupers only: "malignancy" now lists every code in its families (1,359), so a valid ICD-10-CM code is never
  off the list for want of a demo row. Name matching and LLM candidates still read the curated `icd10cm_tw`, so a
  header row such as M10 "Gout" never shadows the grouper. D-113's fail-closed family check stays for local codes.
  Rulesets already compiled keep their approved lists until they are recompiled; the ATOMS snapshots grew.
* **Delta FHIR loads** (`adapter/load_fhir.py`). The ledger now stores a content hash per id (sha256 of the
  canonical JSON without `meta`); a night PUTs only new or changed resources and deletes the ones that left.
  Changing 1 % of 1,000 patients reloads their 20 resources, not 1,000+. The ledger is widened before the load and
  rewritten after it, so a failed night reloads its changes the next night. Old ledgers (ids only) load everything
  once. `full=True` forces a full reload. A 500k reload took ~8 h on HAPI; a typical night is now its changes.
* **Evidence.** `tests/integration/test_ssmix2_path.py`: a 400-patient synthetic JP hospital exported by
  `tools/ssmix2_export.py` (ISO-2022-JP; every third message without the alternate code, so the lookups are used)
  gives the CSV path's GOUT-COH funnel exactly, with no missed 標準病名/YJ code and every JLAC10 code mapped.
  `tests/unit/test_fhir_delta_load.py`: the 1 % delta, a failed night and a legacy ledger.
* **Not done.** Real MEDIS/JLAC10/YJ releases (licensed; sites load theirs); WHO ICD-10 (Japan's 標準病名 maps to
  WHO ICD-10, mostly a subset of ICD-10-CM at category level); ADT-52 discharge and OMP-11/12 administrations;
  extended-storage `_contents.xml` documents; the CQL path still reads enumerated lists only.

**D-123 The data core, its importers and REDCap write-back: TrialBox holds its own trial data and syncs two-way only
with REDCap and spreadsheets (TB-PLAN-03 step 8, finished as TB-PLAN-04 step 3).**

* **The data core** (`services/datacore`, schema `datacore` of `trialbox_wf`, D-126). A REDCap data dictionary (or
  a built-in form) becomes FHIR Questionnaires; answers are rows, one per (study, record, event, field), with who
  changed it last and when, and for each source the value last seen and last pushed. Every change is in `history`.
  Identifier fields of a dictionary are dropped; a record is keyed by the screening number first, else the pseudonym
  (a chart number turned into the HMAC pseudonym with the site key at import), else the row is refused and listed
  with its place in the source, never guessed (`SyncResult.refused`).
* **Ownership and conflicts.** Each field is owned by TrialBox or by one source. A source-owned change is taken; a
  TrialBox-owned field is pushed when it changed; a different value at the source for a TrialBox field, or a source
  value against an earlier TrialBox value, is a conflict: listed once, never forced, closed by a person (keep
  TrialBox's or take the source's), and the trail kept.
* **Sources.** REDCap (two-way, through its API; `create` makes the missing records), a PI's spreadsheet (CSV in
  UTF-8, Shift_JIS or Big5, or XLSX; identifier columns dropped and listed; `POST /studies/{rs}/import/sheet`), a
  FHIR bundle of QuestionnaireResponses. Hospital systems stay one-way in (owner decision 2, 2026-11-08).
* **API** (`orchestrator/datacore_api.py`): forms, dictionary import, entry, REDCap attach and detach, sync,
  conflicts and resolution, sheet import, FHIR export; console pages Sources, Conflicts and Forms with `/api/v1`.
* **REDCap write-back of the screening fields** (below) stays the S21 link's job for now; folding it into the data
  core's TrialBox-owned fields is step 5 (lifecycle), so one writer owns each REDCap field.
* **Evidence (data core).** `tests/unit/test_datacore.py`, `tests/unit/test_datacore_api.py`; `e2e_simple` stage 9
  on the simulator's longitudinal project B: REDCap off → entries in TrialBox → REDCap attached → TrialBox's fields
  pushed and a missing record created → an earlier TrialBox value and a REDCap-side edit of a TrialBox field listed
  as conflicts → resolved → pushed; a PI's sheet with a name column imported with the column dropped, the chart
  number pseudonymised and a keyless row refused and listed.

**The write-back of the screening fields:**

* **What is written.** Three fields on TrialBox's own instrument (`write_form`, default `trialbox_screening`):
  `tb_screen_date` (the day the screening number was issued), `tb_status` (the registry status as a code,
  1 candidate … 7 withdrawn) and `tb_status_date`. Nothing else is ever sent for an existing record. A new record
  (create mode only) also carries the link field `tb_screening_no` and, in a multi-site project, the link's DAG.
* **Modes** (`write_mode` on the project link, S21 section 2): `off` (read only, the default and the old behaviour),
  `existing` (fill the records the coordinator created; screening numbers without a record are listed as waiting),
  `create` (also create a record per new screening number, auto-numbered by REDCap: a screening-log project).
* **Never overwrite.** Saving the link refuses (`RC-LINK-WRITE`) an instrument that holds any field the link reads
  (consent, enrolment, screen-fail, withdrawal, subject number, link field), so the fields TrialBox writes and the
  fields REDCap owns cannot overlap. The import uses `overwriteBehavior=normal` (a blank never erases). A screening
  number on two REDCap records is never written (RC-LINK-DUP stays the coordinator's call).
* **When.** Run now and the nightly read: the read first (REDCap's statuses into the registry), then the write
  (TrialBox's now current status into its instrument). A ledger (`rc_write`, hash per screening number) skips rows
  that did not change. A failed write is reported on the log and retried on the next run; the read stands.
* **API, no module.** The record import (`content=record` with `data`, `forceAutoNumber`, `returnContent=auto_ids`)
  is a form post like the reads (`RedcapClient.import_records`); no REDCap External Module or PHP on the site's
  REDCap. The simulator implements the import with REDCap's checks: unknown fields, unknown or missing events
  (longitudinal), fields on a form the event does not carry (`form_event_mapping`) and unknown DAGs are refused whole.
* **Evidence.** `tests/unit/test_rc_writeback.py` (import rules, plan modes, unchanged and duplicate handling, the
  link check, read-then-write leaving every REDCap-owned field as it was, create mode then consent read back).
  `e2e_simple` stage 8: write-back on through S21 → Run now → every screening number has its REDCap record with
  TrialBox's instrument filled and no REDCap-owned field changed → consent entered in REDCap → the next Run now
  shows *consented* on the log and `tb_status` follows → a third run writes nothing.
* **Not done.** The REDCap project's instrument is created by the site's REDCap builder from the three-field data
  dictionary in `services/rc_sim/fixtures/` (TrialBox does not change a project's design); repeating instruments.

**D-124 A hardware profile for every box we sell, each serving the measured pair.** TB-PLAN-04 step 1 (fixes F1).
D-123 is the data core on the step-3 branch (PR #31).

* **One pair everywhere.** Judge Gemma 4 26B-A4B-it NVFP4 (`j-workhorse`, endpoint `serving`), verifier Qwen3.5-9B
  AWQ 4-bit (`v-verifier`, endpoint `verifier`, thinking off). A note answer excludes only when both agree. One
  weights directory (`deploy/models/gemma-4-26b-a4b-it-4bit`, `qwen3.5-9b-4bit`) serves all profiles; the registry
  has a build per profile because the context differs.
* **Three profiles.**

  | `--gpu` | box | layout | context | compose |
  | --- | --- | --- | --- | --- |
  | `rtxpro6000` | RTX PRO 6000 96 GB (Japan head hospital, CGMH) | both resident, 0.40 + 0.20 of the card, `TB_MODEL_SWAP=off` | 32k | `docker-compose.rtxpro6000.yml` |
  | `gb10` | DGX Spark (medium tier) | both resident, 0.30 + 0.15 of unified memory | 16k | `docker-compose.gb10.yml` |
  | `rtx5090` | one RTX 5090 (small sites) | sleep swap, one awake (D-116) | 8k | `docker-compose.rtx5090.yml` |

  gpt-oss-120b is gone from the Spark (judge and front desk); the front desk is the judge's weights pinned again at
  the profile's context. `rtx4090` (judge alone, never excludes) and `default` stay.
* **Detection.** `deploy/gpu_profile.sh` maps the machine and card name to the profile; `install.sh` calls it.
  The RTX PRO 6000 used to fall to `default` (one base model, no pair).
* **Measured or refused.** `install.sh` starts a pair profile only on a serving-config record of that profile on its
  own uncapped card: `deploy/site/serving_config.<gpu>.json` (the site's) or `deploy/measured/serving_config.<gpu>.json`
  (the vendor's, shipped with the kit), checked by `tools/serving_config.py measured <gpu>`; otherwise only with
  `TB_ACCEPT_UNMEASURED_GPU=1`. The rule per profile: card name, not capped, judge and verifier both present, sleep
  mode on (rtx5090) or off (rtxpro6000, gb10), context at least the profile's. `install.sh` writes `TB_PROFILE`
  (`P-PRO6000`, `P-GB10`, `P-5090`).
* **Evidence.** `tests/unit/test_hardware_profiles.py` (detection, compose files, registry, record rule).
  The PRO 6000 record comes from `deploy/gcp/gpu-pro6000-run.sh` on `tb-gpu-sim` (uncapped, 32k), with `public_e2e`
  and the pair canary against it.
* **Not done.** The Spark is measured when a site orders one (owner decision 4, 2026-11-08). A physical 5090 record.
  `tools/gpu_sizing.py` keeps its old comparison rows (arithmetic, not a profile).

**D-125 Delivery on Windows, and apps after the platform.** Owner's answers, 2026-11-08.

* **Windows workstation, WSL2.** The box is a dedicated Windows workstation (version chosen by the hospital; the
  installer's pre-check accepts Windows 11 Pro/Enterprise and Server 2022+). The Linux stack runs unchanged inside
  WSL2 with GPU access; staff never see Linux.
* **Fully offline installer, installed by Aimedics on site.** One signed installer and a data file (images, models,
  rulesets; about 30 GB) on USB or a file share; no internet at install or after; updates the same way. Built after
  the platform is finished (after step 9); until then steps 2–9 build and test on Linux as planned.
* **Data in:** a LAN shared folder (EMR exports, SS-MIX2 storage), a FHIR or read-only database endpoint, and USB /
  console import, all one-way in; mail out through the hospital SMTP/Exchange server.
* **Apps after the platform:** a phone app for PI/CRC, a desktop app, a documented API for other systems, and an
  Aimedics admin app (box health and updates, no patient data). They must also work from outside the hospital, which
  needs a secure path in (hospital VPN or a relay) and the hospital's approval when real data is used.
* **Rule from now on:** every screen action goes through a documented, token-protected API, so the apps need no
  screen rework later.

**D-126 One trial database, backed up to the hospital's key.** TB-PLAN-04 step 2 (fixes F2), with the owner's
answers of 2026-11-08.

* **One database.** Everything TrialBox creates lives in PostgreSQL `trialbox_wf`, one schema per store:
  `wf` (durable steps, outbox, recall ledger), `orch` (jobs), `study` (REDCap link and records), `site` (marks,
  outcomes, labels, numbers), `auth` (users, sessions), `mail`, `pidmap`, `trace`, `mpi`, `library`. No SQLite file
  is left in `services/` or `libs/`. `tb_common.db` is the one access layer: `?` placeholders, versioned migrations
  under an advisory lock, `TB_DB_URL` for every service. HAPI keeps database `hapi` on the same server; the DuckDB
  lake and the object files stay as they are (clinical facts and documents).
* **Tests and demos run on real PostgreSQL.** `tools/pglocal.py` starts a socket-only throwaway cluster; each test
  and each work directory gets its own schema prefix (`tb_prefix`). No SQLite path for tests.
* **Backup and restore** (`trialbox backup`, `backup-verify`, `restore`, `backup-keygen`). One `.tbbak` file: a
  `pg_dump` of both databases, every data folder, and a manifest of hashes and row counts, encrypted with
  AES-256-GCM in chunks to an X25519 public key.
  * **Key custody:** the box holds only the public key. The private key is printed and put on a USB stick at install
    and kept by hospital IT in a sealed envelope. Aimedics never holds it, and the box cannot read its own backups.
  * **Targets:** the same file goes to every target the site configures: a hospital NAS share (default), a USB
    disk, a second disk and an off-site mount. Each target keeps the newest `--keep` (default 14).
  * **Restore:** every hash is checked before anything is touched, replaced folders are moved aside rather than
    deleted, and row counts are compared after.
* **Owner's answers recorded here.**
  * **Sign-in:** hospital AD/LDAP or local TrialBox accounts, chosen per site at install; local accounts stay as
    the fallback.
  * **First sites run all three kinds of study:** investigator-initiated, sponsor and observational/registry. The
    lifecycle (steps 4–5) must fit all three: for sponsor trials TrialBox does pre-screening and site tracking, not
    the sponsor's CRF.

**D-127 Step 2 widened: safe storage, delivery and recovery; the console becomes the product.** Owner's answers of
2026-11-08 to the design/code review (`docs/reviews/2026-11-08-fable-design-code-review.md`).

* **The PI/CRC console is the product console.** The pilot-only lock (DEV/TEST and D0 only) goes; the console runs
  in PRODUCTION in the compose stack with sign-in, roles and audit. Real-data use still waits for the owner's gates.
* **`/api/v1` from step 2 on.** Marks, outcomes and screening numbers move into Postgres behind a versioned,
  token-protected API that the console pages call; every later step adds its API with its pages (D-125).
* **Step 2 also fixes** delivery through the outbox, never twice (review F-02), audit-log repair after a torn line
  (F-03), runs that fail on consent or note query errors instead of skipping opt-outs (F-04), one environment rule
  with the installer writing PRODUCTION (F-06), one store of record for screening numbers (F-08) and a service token
  on every service (F-11). F-05 (SQL-only at runtime) and F-10 (unmapped code systems) go to step 6.

**D-128 Per-service secrets move to the hardening and installer work.** Owner's answer, 2026-11-08.

* The standards/security review found one `deploy/.env` with every secret (service token, mail passwords, database
  passwords, cloud-model keys) injected into every container. Splitting it into per-service secret files changes the
  installer, the PoC scripts and the settings wizard, which the Windows/WSL2 offline installer (D-125) replaces. So
  it is done there, after the platform is finished, with the rest of the Windows/WSL2 hardening (BitLocker, WSL swap,
  key custody, TLS and MFA). Until then the box is used on synthetic and public data only (no development gates).


**D-129 Built-in data capture.** TB-PLAN-04 step 4 (plan v4 §3 "Built-in capture"), 2026-11-08.

* **Seven built-in forms in ja, zh-TW and en.** Screening log, consent, enrolment, visit (done or missed, date,
  window, window note, weight), adverse event (term as written, onset, serious and why, severity chosen by a person,
  outcome, end date, related yes/no/unknown, description; nothing is graded automatically), deviation and withdrawal
  (date, reason). They are a REDCap data dictionary, `services/datacore/builtin/forms.csv`, with TrialBox's own
  language columns (`field_label:ja`, `select_choices_or_calculations:zh-TW`), read by the same
  `forms.read_dictionary` as a site's REDCap dictionary. Field names carry a form prefix (`ic_`, `vs_`, `ae_` ...) so
  they never shadow a REDCap dictionary's fields; adding them when another form already uses one of the names is
  refused (FORM-DUP). `POST /studies/{rs}/forms/builtin` (orchestrator), one button on the Forms page and
  `POST /api/v1/studies/{rs}/forms/builtin` add all seven in one call.
* **What the dictionary carries now.** `Field` gains `labels` and `option_labels` per language, `vmin`/`vmax`
  (`text_validation_min/max`) and `branching` (`branching_logic`); `required` was already read. On the FHIR
  Questionnaire: the core `translation` extension on `text`, `title` and the choices' `display`, the `minValue` /
  `maxValue` extensions, `required`, the rule as written in `urn:trialbox:fhir:branching-logic`, and `enableWhen`
  when the rule is one comparison or a plain and/or of comparisons. A REDCap dictionary without these columns reads
  as before.
* **Branching subset** (`datacore/branching.py`): `[field] = 'v'`, `<>` (and `!=`), quoted or numeric values, `and`,
  `or`, parentheses. Anything else (checkbox codes `[f(1)]`, `>`, functions, events, smart variables) is outside the
  subset: the field is always shown and its required check is skipped (TrialBox cannot know whether REDCap would hide
  it); the dictionary still imports unchanged.
* **Checks at entry** (`sync.save_form`, one whole form): branching on the stored values with the save laid over
  them; a hidden field is never required and a value sent for it is not written (a stored value stays); required
  only when shown; type (a real calendar date, whole number, number, choice) and range per field; ownership as in
  step 3. A refusal is whole: `DATA-FORM` with one `{field, code, ...}` per problem. The console shows each under its
  field in the reader's language; the API returns them with a message in the account's language.
* **Entry and History pages** (`console/entry_pages.py`, `data_entry.html`, `data_history.html`). The record is a
  screening number this study issued, its pseudonym, or a record the data core already holds; anything else (a chart
  number, a name) is refused and never stored. The event is a free lower-case name (`v1`, `week_4`), empty for a
  once-per-record form. Branching runs in the browser without a script (the console's CSP forbids scripts): a
  per-form stylesheet `/studies/{rs}/entry/{form}.css` hides a field by `#entry:not(:has(<checked radio>)) .q-<field>`
  for rules on choice fields; a browser without `:has` shows the field, and the server decides either way. Save leads
  to the record's history (who, when, event, field, old, new, source; newest first). Roles: the study's coordinator
  enters and adds forms; the investigator and the admin read; viewer and CRA accounts get 403, CRO and other-study
  accounts 404, as on the step-3 pages. `/api/v1`: `GET records`, `GET records/{record}`,
  `PUT records/{record}/forms/{form}`, `GET export/{odm|csv|xlsx}`, one shared action function per action.
* **Exports** (`datacore/export.py`), from the console (Entry and Forms pages), the orchestrator
  (`GET /studies/{rs}/export/{fmt}`) and `/api/v1`. **CDISC ODM 1.3.2** (Snapshot): `Study`/`MetaDataVersion` from the
  forms with REDCap's OIDs (`Project.<study>`, `Metadata.<study>_<stamp>`, `Event.<event>`, `Form.<form>`, item
  groups `<form>.<first field>`, the field name as `ItemOID`), code lists, range checks and `TranslatedText` in every
  language; `ClinicalData` from the values. **REDCap CSV**: flat, one row per record and event, `record_id`,
  `redcap_event_name` when any value has an event, checkboxes as `field___code`. **XLSX**: the same rows plus the
  dictionary with its languages. A value with no event sits on `event_1_arm_1`, REDCap's event of a classic project.
  Records are screening numbers or pseudonyms only.
* **The REDCap simulator takes ODM.** Record import with `format=odm` and `type=flat` turns `ClinicalData` into flat
  rows (SubjectKey = record id, `Event.<name>` = event, `field___code` = checkbox) and runs the same checks as a JSON
  import; a document with a DTD or an entity is refused. `POST /sim/projects` makes an empty project from a
  dictionary (longitudinal when events are given).
* **Evidence.** `e2e_simple` stage 10 "built-in data capture" (15 checks): the forms added in one call, the
  coordinator's consent and visit through the console, a required and a range refusal in the page's language, the
  edit in the history, the ODM export re-imported into a fresh `rc_sim` project with the same dictionary with every
  value equal, the REDCap CSV columns equal to the dictionary. `tests/unit/test_datacore_capture.py` and
  `tests/console/test_entry_pages.py`. The walk opens Entry (consent, visit v1) and History for the coordinator in
  three languages on desktop and phone; on a 390 px phone in ja it saves a consent and a visit, checks that the visit
  date appears only once the visit is marked done, edits the consent and finds old and new in the history.
* **Not done.** Repeating instruments (several AEs per record use one event each, e.g. `ae1`, `ae2`; ODM repeat keys
  are always 1); the schedule of events, visit windows and the subject state machine (step 5); calculated fields are
  shown but not computed; the browser applies only rules on choice fields (rules on free text are server-only);
  REDCap's "erase hidden values" prompt (a hidden field's stored value is kept); ODM import into TrialBox itself;
  field notes, section headers and matrix groups are not shown; an ownership refusal names the source by its id
  (`redcap`).

**D-130 The screening engine finished: unreadable codes are unknown, CQL fails closed in the gate, reads need the
token.** TB-PLAN-04 step 6 (plan v4 F3, F4; review findings F-05, F-10, F-14, F-27). F-05 (SQL the only runtime
engine, CQL only in the compile-time gate) is the first commit of the step (432de3c); F-12 (reveal only for a listed
patient, per-actor rate limit) was done in step 2.

* **Codes in a system nobody can read are not a "no" (F-10).** A structured inclusion that is FALSE is a hard
  exclusion outside the two-model rule. A diagnosis or medicine whose code no ValueSet can read used to make it FALSE
  silently: a 標準病名 with no ICD-10 alternate and no lookup row (the SS-MIX2 reader leaves the code empty), WHO
  ICD-10 or ICD-9-CM under their own URIs, a free-text diagnosis, a medicine without ATC (a YJ or local code).
  `matching/coverage.py` reads, from the same lake snapshot, the rows of `condition` whose system is neither
  ICD-10-CM nor a system of the ruleset's ValueSets (or that have no code) and the rows of `medication` without ATC.
  When the compiled SQL says FALSE for an inclusion with a positive condition / medication atom (not under `not`, not
  `none`) and the patient has such a row in that atom's window, the answer becomes `unknown` with the new reason code
  `unknown_code_system` (words in en / ja / zh-TW) and the rows as evidence, so a person checks. Both runtime paths
  do it: the SCREEN cascade at S1 (`_s1_outcome`; the S1 stage log counts the patients) and the SQL engine of NAV,
  MICROBATCH and CASE (`PatientEvaluation.reasons`, a new optional contract field, read by `structured_verdict`).
  The approved SQL is unchanged byte for byte, so no approved ruleset needs re-approval; exclusions are untouched.
* **Counts.** S3 (the feasibility page's list bridge) prints "Diagnoses or medicines in an unknown code system: n
  patients on the list"; the SCREEN report JSON has `unknown_code_system` and its summary PDF a scope line; FEAS adds
  the notes `feas.note.unknown_system.condition` / `.medication` with the rounded number of patients in the
  population (all three languages). `tools/mapping_check.py` reports the rows per table without ICD-10 / ATC and
  now accepts `--source ssmix2`.
* **CQL fails closed like SQL (F3).** The CQL generator adds, for a grouper ValueSet with code families, an `O_`
  query (records in the window coded inside a family and not in the ValueSet) and the same three-valued rule as the
  SQL's `_off` CTE (D-113): listed codes settle the atom, else an off-list family code makes it null. CQL stays
  compile-time only. The ATOMS library (no families) renders as before.
* **Fixtures with off-list codes** (`tests/fixtures/equivalence/offlist/`): 14 patients, a malignancy and a
  urate-lowering-therapy grouper, codes inside a family but off the list (C50.9Z, M04AA99), codes in unknown systems
  (WHO ICD-10, a MEDIS 病名 code, ICD-9-CM, free text, a YJ code without ATC, one outside the window), and the oracle
  `expected.json` both engines are held to.
* **Reads behind the token (F4).** `make_app(..., protect_reads=True)` puts GET and HEAD under the same rule as the
  writes (`service_auth.check`): 401 without the token, 403 with a wrong one, open on a DEV/TEST box without a token,
  503 on any other box without one; `/healthz` stays open. On for the orchestrator (jobs, outputs, registry, studies,
  rulesets, models, the data core API), the lake, the mail gateway (threads) and the trace store. `ServiceClient`,
  `LakeHttp` and the console backend already send the token on every call; the compose e2e test sends it on its reads.
  The orchestrator's own token middleware is gone (one rule, in `make_app`). The console's pages stay cookie-based.
* **Small review items.** F-14: both schedulers (orchestrator, console timers) run a missed cron run once within six
  hours and coalesce missed runs (`tb_common.config.SCHEDULER_JOB_DEFAULTS`). F-27: the note judge's counters are
  bumped under a lock (they come from the evaluator's worker threads).
* **Evidence.** `tests/unit/test_code_coverage.py` (SQL equals the oracle and is null on off-list codes; the CQL has
  the family check and translates with cql-to-elm 5.4.0 on the host; the SQL engine and the cascade keep the
  unreadable patients unknown with the reason, and still fail a readable code outside the family);
  `tests/integration/test_ssmix2_path.py::test_unmapped_diagnoses_are_not_silently_excluded`: the 400-patient SS-MIX2
  hospital read without the 標準病名 and YJ lookups (every third message has no alternate code): of 118 gout patients,
  15 had only code-less gout records and were "not gout" (excluded); all 15 are now unknown with the reason, readable
  non-gout patients still fail, and FEAS counts 287 patients with unreadable diagnoses and 276 with unreadable
  medicines. `tests/unit/test_service_auth.py` and `test_service_token_everywhere.py`: `GET /jobs` without the token
  is 401 (and every other orchestrator read), 403 with a wrong one, 503 without a token in PRODUCTION, open in DEV
  and TEST; the lake, mail gateway and trace store too; the clients send the token on reads.
  `tests/integration/test_compile_compose.py::test_offlist_gate_on_hapi` runs the gate on HAPI over the fixture
  (100 % and the oracle); it needs the compose stack and is skipped without it.
* **Not done.** N-12 (TREC on the deployed files) is the GPU run of this step and is recorded separately. The CQL side
  of the off-list fixture has been translated, not executed, here (no HAPI in this environment); the compose test
  executes it. A TRUE inclusion with a `none` atom (e.g. "no malignancy") is not widened when an unreadable row exists
  (the patient is listed, not excluded, and a person sees the record); exclusions are not widened either. YJ / local
  drug codes that are carried with an ATC count as readable; a JP Core profile for the unreadable 標準病名 code (so the
  local code reaches the lake instead of an empty code) belongs to step 7. Misfire: no catch-up run on start for a
  job missed by more than six hours, and no "last run" per timer on the admin page. Per-service tokens stay with
  D-128.
* **N-12 on the deployed files (2026-11-08).** TREC CT 2021/22, 1,700 pairs and 20,096 criteria, judge and verifier
  as deployed on the RTX PRO 6000 profile: eligible pairs wrongly dropped, audit-adjusted, **3.1 %** (95 % 1.8–5.0 %),
  gate ≤ 5 %: **pass** (API 4-bit was 3.6 %); excluded pairs caught 50.8 %. `eval/trec_ct/results/n12_deployed_2026-11-08.md`.

**D-131 Site setup and data harmonization: three questions, one rule, one readiness page.** Owner's answers,
2026-11-08; a new plan step 5b, after the lifecycle and before handover.

* **Three questions, in order.** (1) *Which trial?* A protocol file, paste or registry id; the LLM drafts the
  criteria and the PI approves each one (as today). (2) *Which patients could fit?* Any mix of a hospital feed
  (SS-MIX2, FHIR, CSV export; nightly), candidate spreadsheets, and charts one by one (text, Word or EMR print to PDF,
  scanned paper through OCR on the box, or text pasted from the EMR screen). (3) *Where do trial records live?*
  TrialBox's forms by default; REDCap or a sheet attached when the site wants it.
* **One rule.** Every fact has one home and the LLM never writes a fact silently. Coded data from the hospital or
  REDCap is used as is. Facts the LLM extracts from a chart are *proposed*: shown next to the quote they came from,
  confirmed or corrected by a CRC in one tap. A proposed fact can only send a patient to "needs information"; once a
  CRC confirms it, it counts like coded data and may exclude, with the confirmation in the audit. Note text stays
  notes, read by the two models at screening. A patient from two inputs is joined by pseudonym, never by name;
  disagreements are listed.
* **One readiness page** shows the three questions as green, amber or red with "what's missing" (unmapped local codes
  with a once-per-site mapping, sheet rows without a key, criteria not yet approved, the share of diagnoses in an
  unknown code system), and feasibility shows how much of each count rests on coded, confirmed or proposed facts.
* **Plan.** TB-PLAN-04 step 5b, about 1–2 weeks: the readiness page, chart upload with extraction (OCR included),
  the proposed-fact review list, the local code mapping, and the join by pseudonym; an `e2e_simple` stage that sets up
  a site from a protocol, a CSV feed, a sheet and two uploaded charts.

**D-132 Novice users and imperfect data: start small, fix what is safe, guide every step.** Owner's answers,
2026-11-08; widens step 5b.

* **No perfect data assumed.** A first site may have only EMR screens (copy, paste or print to PDF), a one-time IT
  dump in local formats, old Excel lists laid out differently by each PI, and past REDCap projects. CGRD-quality
  data is the exception. Every input path works on its own, and each one can be added later.
* **Start with the least.** A site starts with a protocol and charts pasted or uploaded one by one. Feeds, sheets
  and REDCap come later. The box says plainly what it cannot do yet (for example, feasibility counts need a bulk
  source) instead of failing.
* **Messy data: fix what is safe, ask the rest.** Unambiguous fixes are made and listed: Japanese era dates
  (令和5年 → 2023), 民國 years (民國112年 → 2023), full-width digits and letters, known unit conversions, unmerged Excel
  cells, header rows found below titles. Anything ambiguous (a date that could be D/M or M/D, an unknown unit, a column
  that might be the chart number) goes to a short "please check" list with a suggested answer. Nothing ambiguous is
  guessed silently.
* **Help.** (1) A step-by-step setup wizard: one question per screen, examples, what each answer means, and progress
  to "ready". (2) An ask-the-box assistant on every page ("what do I do next?", "why is this patient on the list?") in
  ja, zh-TW and en, run on the local model. It explains and links, and never changes data. (3) Excel templates and
  mapping sheets in the site's language, plus a synthetic practice site. (4) Remote help from Aimedics: screen
  guidance without patient data. It is built as an option that the hospital switches on (approval needed when real
  data is present).
* **Step 5b grows to L** (about 2–3 weeks). Its `e2e_simple` stage sets up a site the hard way: a protocol, a messy
  Excel sheet (era dates, full-width digits, merged cells, a title row), an IT dump with local codes, and two pasted
  charts. It ends with the readiness page green and a "please check" list that a scripted CRC works through.


**D-133 Step 4b: easy for novices.** Owner approved, 2026-11-08, after the novice UI/UX review
(`docs/reviews/2026-11-08-ux-review-novice.md`, 2.5 of 5) and the field research
(`docs/reviews/2026-11-08-field-research-tw-jp-sites.md`). Before the lifecycle (step 5), so every later page follows
the same patterns.

* **Safety first.** The one-time password leaves the URL and is shown in a readable form with hand-over steps. "Not
  suitable" needs a reason and has an undo. A contact outcome is recorded only after the PI has approved the patient.
  The PI's reveal follows the role text. (The chart number in job lines and subjects was fixed in PR #35.)
* **Phone.** A patient sheet with Back and Next and a sticky mark bar; compact headers; IDs that never wrap one
  character per line; touch targets of at least 44 px and text of at least 15 px.
* **Setup.** One wizard with an unsaved-changes guard; REDCap linking guided step by step, with the variable names
  read from the dictionary instead of typed.
* **Words.** One plain vocabulary per concept, from the review's glossary, checked against the field research
  (選択・除外基準 / 納入／排除條件, 処理 / 作業, 治験依頼者 / 試驗委託者); every label and name translated before the first run.
* **Sign-in and errors.** Lockout shown with a countdown and the admin to contact, plus a language choice; error pages
  with a heading and three clear buttons; unknown studies answer 404.
* **Guarded by tests.** axe-core in the walk (no serious or critical issue), a 44 px target check and an English-leak
  check on ja and zh-TW pages; tap counts for the core tasks recorded before and after.

*What was built (step 4b, 2026-11-08).*

* **One-time password (F-02).** `random_password()` now gives five groups of four from an alphabet without look-alike
  characters (`k7dm-q3xa-…`, about 99 bits; `0 O 1 l i` never appear). After Create or Reset the console keeps the
  password in memory, keyed by the administrator's session, and redirects to `/ops/users#made`; the page pops it once.
  It is never in a URL, a log line, the audit trail or a database, and a restart forgets it (reset again). The page
  shows it grouped, in a read-only field with Copy, with three hand-over steps (in person or by phone, change it at
  once, the page will not show it again).
* **"Not suitable now" (F-03).** The reason is a required list with an empty first choice; `apply_mark` (the one
  action behind the page and `/api/v1`) refuses a missing or unknown reason with `mark.reason_needed` instead of
  recording "other". After any mark the toast offers **Undo** (`mark=undo`): the state before the user's last mark is
  put back (the earlier mark with its reason and note, or no mark), as a new event with `undo` in the audit detail.
  After a mark the panel shows that patient's real state, even when the patient has left the list.
* **Contact outcomes (F-36).** `apply_outcome` refuses (409 `outcome.wait_pi`, audited `console.refused`) unless the
  patient's current mark is Approach, so the page and `/api/v1` refuse alike; the page shows "Waiting for the
  investigator's decision" instead of the outcome buttons.
* **The investigator's reveal (F-38). Choice: investigators may not reveal.** It is the safer and simpler rule: it is
  what the role text already says ("no chart numbers"), it matches the job page (requesters only since D-101), and the
  coordinator, who keeps the screening log and makes the call, is the one who needs the number. `User.can_reveal`
  (administrator, coordinator) guards the patient page's reveal; the form moved to the bottom of the page, needs a
  reason, and says "recorded with your name" on the button. `e2e_simple` now checks the investigator's 403 and has
  the coordinator reveal.
* **Unknown study (F-37).** Every study route (`home`, `study_setup`, `screening_log`, `data_pages`, `entry_pages`)
  checks `studies.known_study`: a ruleset of any status must exist, else the 404 page.
* **Phone.** The week list on a phone shows the list only; a tapped row opens the patient as a full-screen sheet with
  Back to the list, Next patient and a sticky mark bar (48 px buttons that reach their forms with the `form`
  attribute). The header is one line of banner, the brand, Help, a Menu button (a checkbox and label, no script) and
  the search field; the menu, language and Sign out sit behind Menu. IDs, dates and codes in tables never wrap (the
  table scrolls in its card; job ids show their last eight characters with the full id as a title). The audit trail is
  paged, 50 events a page (newest 1,000).
* **Targets and text.** Buttons, inputs, selects, menu items, table links and summaries are at least 44 px; checkbox
  and radio labels are 44 px rows; text is at least 15 px (16 px body); scroll regions are focusable.
* **Setup (F-04, F-11).** `/studies/{rs}/setup` is one form with one Save (`POST /studies/{rs}/setup`), step chips
  and a `data-guard` that warns before leaving with unsaved edits. "Read the fields from REDCap" (`action=read`)
  reads the project's data dictionary through a new read-only orchestrator route,
  `GET /redcap/connections/{ref}/dictionary`, and shows the page again with everything typed kept and each field as
  a list (label and variable name, grouped by form); nothing is saved until Save. Save stores the study and the
  numbering together and, when the link changed, checks it against the dictionary. The older per-section routes stay
  for scripts. The CSV import on Forms and the field-map text on Sources remain for the uncommon cases.
* **One script, by hash.** The guard, Copy and the error page's Back need a script. The console now inlines one
  first-party script (`static/console.js`) and the CSP allows exactly that script by its SHA-256 (`script-src
  'sha256-…'`, no `'self'`, no `'unsafe-inline'`); every page still works without it. A console test checks that the
  page's only script is the one the policy names.
* **Words (F-09, F-10, F-20–F-22).** The glossary was applied to the ja and zh-TW catalogues (219 replacements): 処理 /
  作業 (not ジョブ / 工作), 選択・除外基準 / 納入／排除條件, 読み込み / 讀取 (not コンパイル / 編譯), 治験依頼者 / 試驗委託者,
  ログイン, 役割, 金鑰, and TrialBox for the product (never 箱, 装置, 本機, 機器). A test fails if one of the old words comes
  back. The week list has one name everywhere (This week's patients / 今週の患者 / 本週病人); "Patients" in the menu is
  the Screening log. Mark labels stay as decided in D-108 (a "not suitable" label never reads as "not eligible").
  Words from the study or the hospital's data (criterion labels, doctors' names, departments) are shown as written
  and, on a ja or zh-TW page, marked "原文" with `lang="en"`. Help and the command page build their examples from
  the user's own first study, and each example is a link. A typed patient code finds patients on this week's list.
* **Sign-in and errors (F-05, F-12).** The sign-in page has a language choice (kept for the session it starts), says
  for how many more minutes and until when an account is locked, and names the administrator's mailbox. The 403, 404
  and other error pages have a heading, one sentence, and three buttons: home, back, help.
* **Tests.** `tests/console/test_step4b.py` (one test per safety change, the one-form set-up with the dictionary
  pickers, the sign-in page, the error pages, audit paging and the glossary). `tools/public_walk.js` injects axe-core
  (from `node_modules`, else `tools/vendor/axe.min.js`, 4.10.2, SHA-256 `b511cd9d…75e3`) with `addScriptTag` and fails
  on a serious or critical issue; fails on any target under 44 px (a link inside a sentence is WCAG 2.5.5's
  exception); keeps the English-leak check; and walks the six core tasks with taps counted into `walk.json` (`taps`),
  failing when a task needs more than the review's "could" column.

*Before and after* (before: the review's 696 page loads; after: the walk's 480 pages, 5 roles x 3 languages x 2 views).

| | Before | After |
|---|---|---|
| axe serious or critical | 6 pages (scrollable-region-focusable) | 0 (moderate 12, minor 72) |
| Interactive targets under 44 px | 28,272 of 28,750 (98 %) | 0 of 12,468 |
| T1 PI marks a patient, phone ja | 2 + an anchor jump and a long scroll back | 2, the sheet and mark bar in view (target 2) |
| T2 CRC records an outcome, desktop zh-TW | 4 + a date | 2 (target 2) |
| T3 CRC finds why a patient is listed, phone ja | 2 | 2 (target 2) |
| T4 CRC set-up and REDCap, desktop en | 14 clicks, ~20 typed fields | 5, fields picked from the dictionary (target ~10) |
| T5 admin adds a user and checks health, desktop ja | 7 | 5 (target 5) |
| T6 first day, phone zh-TW | 3 (+2 for the language) | 3, language from the browser or one tap (target 3) |
| Review score (novice) | 2.5 / 5 | not re-reviewed; our own reading: safety 4, accessibility 4, guidance 3 |

*Left for later.* A re-review by the novice panel (and of the Entry and History pages, F-42); first-run wizard and
forced password change (pattern 2, F-24); feasibility summary card first (F-14); job pages as result cards for PI and
CRC (F-23); plain service names on the admin pages (F-25); confirmations on Disable, Detach, Keep/Take and Start a run
(pattern 6); Undo for outcomes and conflict decisions; the command field as a real assistant (F-32, F-39); per-page
help with screenshots; translated (not only marked) criterion labels before the first run, which needs the label
editor made mandatory at approval; the mail gateway's own texts still say サインイン.

**D-134 Step 5, trial lifecycle v1.** TB-PLAN-04 step 5 (plan v4 §3 "Lifecycle for the pilot", owner decision 4:
the §3 list only; randomisation, drug accountability, SDV, eConsent and a patient portal come later), 2026-11-08.

* **One state per participant** (`services/datacore/lifecycle.py`, tables `subject`, `subject_step` and `schedule`
  in schema `datacore`, version 2 of its migrations, so they are in every backup). States: candidate → approached →
  consented → enrolled → on study → completed, or withdrawn, or screen failure. `NEXT` is the only list of legal
  steps; the three end states take none. An illegal step is refused (409 `LIFE-STEP` with `why`: `order`, `final`,
  `reason`, `future` ...) and the console and `/api/v1` say why in the reader's language with the states named and
  the possible next steps listed ("Enrolled cannot follow Candidate. Possible next steps: Approached, Screen
  failure."). Screen failure needs a reason (not eligible, declined, not reached, other), withdrawal one of the
  withdrawal form's six. **Undo** reverses the last step as a new step. Every change is a `subject_step` row (old, new,
  the day it happened, reason, note, who, when, source) and an audit record (`life.step`, `life.refused`,
  `console.life_step`).
* **Where a state comes from, in this order.** (1) The data core's answers, after every saved form
  (`datacore_api` → `lifecycle_api.derive_record`): screening log (`sl_approached`, `sl_eligible` 0 = screen
  failure), consent (`ic_date`), enrolment (`en_date` with `en_eligible`), the first visit done (on study), every
  scheduled visit done or missed with the last one done (completed), withdrawal (`wd_date`, `wd_reason`). A step the
  answers imply is taken too and says so ("follows from form: tb_consent"). (2) The screening log's status (the
  candidate registry, which the REDCap read-back feeds): this is how a **sponsor study** is tracked without TrialBox
  owning the CRF; the sponsor's REDCap or EDC says consented or enrolled and the participant follows. (3) A person's
  step on the participant page or `/api/v1`. Derivation never goes backwards and never past an end state; what does
  not fit is listed as `held`, not forced.
* **The screening log follows the lifecycle.** After every step the state is mirrored into the candidate registry
  (approached = contacted; enrolled, on study and completed = enrolled), through the registry's own recorded
  transitions, so the screening log, the enrolment report and the REDCap write-back's `tb_status` say the same.
  *Decision:* the mirror runs only after a step, never on a plain refresh, so a REDCap value that disagrees with an
  ended participant is not fought over on every Run now; it is shown as held.
* **Participants are the study's screening numbers.** Every lifecycle page asks the orchestrator to bring the
  participants up to date with the site store's screening numbers (`POST /studies/{rs}/subjects/refresh`) when the
  reader is the coordinator; the investigator's, the administrator's and the home pages only read. The REDCap read-back
  and the morning mail do the same. A record that only has forms (a pseudonym) becomes a participant when a lifecycle
  form is saved for it.
* **Schedule of events** per study: visit name, label per language, day from enrolment (or consent), days allowed
  before and after. Typed on the Visit schedule page (one form, empty rows to add) or read from REDCap's arms and
  events (`content=event`: `day_offset`, `offset_min`, `offset_max`; arm 1). The REDCap simulator answers `event` and
  `arm` for a longitudinal project (project B now carries day offsets: screening day 0, month 12 day 365 ± 30) and
  refuses them for a classic one, as REDCap does; TrialBox then says to type the visits in.
* **Visit windows** are computed for a given day, the site's local date (`site.tz`; `now()` of the orchestrator is in
  the site's zone, and the console turns its clock into the site's date): *coming* (the window has not opened),
  *in the window*, *overdue*, *done*, *missed* (the visit form), *not needed* (the participant ended). A test passes
  `today`, so the windows are deterministic: 00:30 in Tokyo is already the next day, the same instant in Taipei is not.
  A visit done outside its window is marked so.
* **The coordinator's visit list** (`/studies/{rs}/visits` and on the home page): today, this week (the next seven
  days), overdue. Each row has **Done today**, which opens the built-in visit form filled in for today (done,
  today's date, in or out of the window) so the coordinator checks it and taps Save, and **Open the visit form**.
  Save returns to the list (or to the participant) with a confirmation. Rows are cards on a phone, buttons 44 px or
  more; the participant page's next steps sit in a sticky bar like the patient sheet's mark bar (D-133).
* **AEs and deviations** use the built-in `ae_*` and `dv_*` forms on numbered events (`ae1`, `ae2` ..., `dv1` ...);
  "Add an adverse event" opens the next free one. Visit names may not look like these. An ongoing serious AE is a
  red banner at the top of the investigator's home page (the week list) and the coordinator's home page, with a link
  to the participant.
* **Enrolment report** (`/studies/{rs}/enrolment`, `.xlsx`, `.csv`, `/api/v1/studies/{rs}/enrolment[/csv|xlsx]`):
  participants per state now and ever reached, per month, screen-failure reasons, withdrawals with day and reason.
  Screening numbers only. The XLSX is deterministic OOXML (as the registry export); the form data itself is exported
  by the existing ODM / REDCap CSV / XLSX exports (D-129).
* **Morning mail.** N2 (coordinator) gains "Study visits today" and "Overdue study visits", N1 (investigator) the
  week's study visits of the investigator's studies and the number of serious AEs to review. Visits are named by the
  patient's pseudonym (8 characters) and the visit's name, never by the screening number or chart number (the N1/N2
  rule since D-108, checked by `e2e_simple` stage 4; the mail keeps pseudonyms only, screening numbers stay on the
  pages). The mail key (one notice per person and day) is unchanged.
* **REDCap write-back folded into the data core (one writer per field).** S21's three fields (`tb_screen_date`,
  `tb_status`, `tb_status_date`) are now TrialBox-owned values of the study's data core, written by TrialBox and
  pushed by the data core's sync through `rc_bridge.writeback.LinkSource` (the S21 link as a data-core source): a
  value is pushed when it changed since the last push. *Behaviour changes:* (1) a REDCap-side edit of one of these
  fields is now a **conflict** on the Conflicts page ("Values to check"), not silently left or later overwritten;
  the Run now line says how many; (2) a study whose data-core REDCap source also maps one of these fields gets no S21
  write (`RC-WRITE-OWNER`, the read stands). The result shape (updated, created, unchanged, waiting, duplicates,
  records) and every rule of D-123 (never a REDCap-owned field, `existing` and `create` modes, DAG, duplicates never
  written, unchanged rows skipped) are kept; the `rc_write` ledger is still written. The first run after an update
  takes REDCap's current values as the starting point, so nothing is re-pushed or listed by mistake.
* **Words.** New strings in `console/i18n_life.py` (en, ja, zh-TW, every key in all three, checked by a test), from
  the glossary and the field research: 被験者 / 受試者, 来院 / 訪視, 許容範囲 / 訪視窗口, 来院スケジュール / 訪視時程, 有害事象 /
  不良事件, 重篤 / 嚴重, 逸脱 / 偏差, 登録状況レポート / 收案報告, 声かけ済み / 已邀請 (the glossary's Approach), 已收案. The help
  page has a "Words used on these pages" glossary (participant, screen failure, visit window, overdue, AE, serious,
  deviation) in plain words. The old-word test still passes.

*Evidence.*

* `e2e_simple` stage 11 "trial lifecycle" (25 checks, 4.6 s; the whole run 76 s of its 15-minute budget): a new
  screening number is a candidate → an illegal step is refused with the plain reason in Japanese and nothing changes →
  approached by hand → consent and enrolment forms → enrolled → v1 is *coming*, *in the window*, *overdue* on three
  given days → the coordinator's visit list and home page show it under Overdue → N2 lists it by pseudonym, never the
  screening number → Done today, Save → done, on study → AEs on `ae1` (serious) and `ae2` → the serious AE on the
  investigator's home page → withdrawal form → withdrawn, a further step refused, the other visits not needed, the
  whole trail kept → Run now → **the screening log (XLSX), the enrolment report (CSV) and REDCap's read-back from the
  simulator agree on every count** (enrolled 1, consented 1, withdrawn 1) and the participant reads withdrawn
  (`tb_status` 7) in all three → the report downloads, carries no chart number → steps, refusals and the schedule
  in the audit. Stage 10's "nothing written" check now looks at the consent fields (the record already holds
  TrialBox's screening fields from stage 8).
* `tests/unit/test_lifecycle.py` (state machine, refusals, undo, derivation with implied and held steps, a sponsor
  study from the screening log, windows on given days, the Tokyo/Taipei date line, AEs on numbered events, the
  report, the registry path, the API with the mirror, a schedule from project B's events, the S21 write through the
  data core with a REDCap-side edit listed as a conflict and the one-writer refusal) and
  `tests/console/test_lifecycle_pages.py` (the console path, the refusal in Japanese through `/api/v1`, roles, N2 by
  pseudonym). `tests/unit/test_rc_writeback.py` passes unchanged; `tests/unit/test_rc_sim.py` now expects `arm` and
  `event` to be answered (400 "classic project" for project A) instead of 501.
* `public_e2e` 106/106 checks (stage 5b: a second participant enrolled through the forms with today's visit and a
  serious AE). The walk (`node tools/public_walk.js` against `public_e2e --serve`): 586 checks, 0 failures; 576
  pages, 5 roles x 3 languages x desktop and phone, with the five lifecycle pages for the coordinator and the
  investigator, two for the administrator and 403 for viewer and CRA; axe 0 serious or critical (84 minor); 14,910
  targets, 0 under 44 px.
  Task **T7** "the coordinator marks today's visit done" (phone, ja): Done today on the home page, Save: **2 taps**
  (target 2 to 3); T1 to T6 unchanged (2, 2, 2, 5, 5, 3).
* `tools/backup_drill`: PASSED; the new tables are in the backup, and participants, steps and the visit schedule read
  back the same after the restore (3 participants, 14 steps, 3 visits). Unit, console and testbench tests: 1258
  passed.

*Not done.* Randomisation, drug accountability, SDV, eConsent, a patient portal, sponsor EDC connectors (plan v4 §3);
visit bookings (a visit has a window, not an appointment time; the hospital's appointment source is not joined to
participants yet); unscheduled visits (any event name works on the Entry page but is not on the list); several arms
(arm 1 only from REDCap); repeating instruments in REDCap (AEs stay one event each); the schedule is not versioned
with protocol amendments (saving replaces it; the trail is in the audit); visits in the hospital calendar or LINE;
the AE is never graded or reported to the IRB or the sponsor by TrialBox; the investigator's confirmation of an SAE
is not recorded; a reminder when a window is about to close (only the overdue list and N2); the enrolment report's
small-cell rule (k) is not applied because it never leaves the study team.

**D-135 Step 5b, site setup and data harmonization.** TB-PLAN-04 step 5b (D-131, D-132; builds on D-123, D-126,
D-129, D-130, D-133, D-134), 2026-11-09.

*What was built.*

* **The one rule, in the lake and the engines** (`lake.flatten`, `matching/proposed.py`).
  * A fact the model read from a chart is *proposed*. It carries the tag `urn:trialbox:basis|proposed` and goes only
    to the lake's new `site_fact` table, never to `condition`, `observation` or `medication`. The compiled SQL never
    reads `site_fact`, so a proposed fact can never count as met and can never exclude. The approved SQL is
    unchanged byte for byte; no ruleset needs re-approval.
  * Beside the SQL, as with D-130, every decided answer is checked. If one of the patient's proposed facts could
    change it, the answer becomes `unknown`, with the new reason code `proposed_fact` (words in en, ja and zh-TW)
    and the fact as evidence.
  * "Could change it" is decided per atom of the criterion:
    * a condition or medicine that is present matters when the answer is FALSE;
    * the same under `not` or `none` matters when the answer is TRUE;
    * a value (a lab, eGFR, age, sex) matters either way.
  * The fact must also match the atom: its domain, its code in the ValueSet or one of its families (or no code at
    all), and its date inside the window.
  * Both runtime paths apply the check: the SQL engine (NAV, MICROBATCH, CASE, and the patient check on the
    readiness page) and the SCREEN cascade at S1. At S1 an exclusion left unknown keeps the patient, as D-18
    does.
  * A *confirmed* fact (the coordinator confirmed or corrected it; audited) is written to the coded tables like any
    coded record, and is also listed in `site_fact`.
* **Feasibility.** FEAS counts only coded and confirmed facts, by construction.
  * `FeasRaw.basis` gives, for each step: the patients still counted, how many of them rest partly on confirmed
    facts, and how many patients have proposed facts that are not counted.
  * Two new notes, `feas.note.basis.confirmed` and `.proposed` (three languages), appear only when a site has such
    facts. The hospital feed's reports are unchanged.
  * A lake built before this step has no `site_fact` table and reads as "no proposed facts". Any other lake error
    still stops the run (D-127).
* **Site setup service** (`services/sitesetup`, schema `sitesetup` of the trial database).
  * Tables: inputs; facts with their status (coded, proposed, confirmed, rejected; `before` keeps the model's version
    after a correction); local codes and their mapping; the "please check" list with its answers; the fixes made;
    settings; and what was last published.
  * Files sit in the orchestrator's data folder (`sitesetup/<space>/inputs/`): the original file, its text, and a
    redacted text for the lake. The folder is in every backup.
  * Spaces: `main` is the hospital, and its facts go to the box's own lake beside the nightly feed. Any other name is
    a separate site space with its own lake: the synthetic `practice` site, and the e2e stage's new site.
  * Every decision is audited (`setup.*`, `console.site_*`), without chart numbers or names.
  * APIs: the orchestrator's `/setup/...` (`orchestrator/setup_api.py`; reads behind the service token, as every read
    is), the console's `/api/v1/site/...` (readiness, facts, charts, codes, checks) and `/api/v1/ask`.
* **Messy data** (`sitesetup/messy.py`, a pure module).
  * Safe fixes are made and listed by kind and column:
    * era dates (令和, 平成, 昭和, 大正, 明治 and R, H, S, T, M; 元年);
    * 民國 years and NHI's 7-digit ROC dates;
    * Excel serial dates and other ISO date forms;
    * slashed dates whose day is over 12;
    * full-width digits and letters;
    * known unit conversions: urate and creatinine in µmol/L, HbA1c in mmol/mol, glucose in mmol/L, weight in lb;
    * merged cells, and title rows above the header.
  * The ambiguous rest goes to "please check" with a suggested answer. Nothing is guessed:
    * D/M against M/D: one question per column, suggested from the column's own unambiguous dates; the cells stay
      empty until it is answered;
    * an era date that does not exist (平成31年5月);
    * two-digit years and unreadable dates;
    * an unknown unit, suggesting the test's own unit when the value is plausible in it;
    * a column that might hold chart numbers: held back, and its values are never shown;
    * a sex value that cannot be read;
    * rows without a chart number.
  * Each answer re-reads the stored file, so the result always depends only on the file and the answers. Name,
    phone and address columns are dropped and listed.
* **Charts one by one** (`sitesetup/charts.py`, `ocr.py`).
  * Accepted: pasted EMR text, .txt, Word, a PDF with a text layer, and scans (an image, or a PDF without text whose
    page images are read).
  * Scans go through `TesseractOcr` (jpn, chi_tra, eng) when it is installed. Without OCR a scan is refused with a
    plain reason, and everything else still works. Tests use a fake OCR.
  * The local model returns facts with quotes (prompt `chart_facts_v1`, schema `llm_chart_facts_output`; the stub in
    tests and e2e). A fact is kept only when its quote is found in the chart (`tb_common.quotes`); it is then
    normalised through the messy module.
  * The chart number becomes the pseudonym on arrival and is never stored. Quotes and the lake's copy of the text
    are redacted by the box's guard (chart number, names, phones, IDs). Quotes keep a date of birth so the
    coordinator can check it.
  * The chart text becomes a note in the lake: note text stays notes, read by the two models at screening.
* **Local codes, mapped once per site** (`sitesetup/mapping.py`).
  * A local code lives in `urn:trialbox:local:<kind>`, where the kind is one of: a diagnosis code, a diagnosis as
    written, a lab code, a lab column, a drug code, a drug name.
  * Suggestions come from the adapter's JP-Core lookups (byomei, JLAC10, YJ), the hospital lab table, the analyte
    words, and the curated terminology by name (for example 痛風 → M10.9).
  * A coordinator or administrator confirms each code once, on the page or through a filled XLSX mapping sheet. A
    target must be a code of the domain's standard system.
  * Until a code is mapped it stays in an unknown code system, so D-130 keeps the patient unknown.
* **Join by pseudonym** (`sitesetup/publish.py`).
  * One Patient per pseudonym across dump, sheet and chart.
  * Counted demographic facts that disagree are listed and left out of the patient row. The patient stays unknown
    ("needs information") until a person keeps one value; the other values are rejected, and the choice is audited.
* **Readiness** (`sitesetup/readiness.py`, console `/site`). Three questions, each green, amber or red, with what is
  missing and a link to fix it:
  * Trial: no criteria, or not approved.
  * Patients: proposed facts to check; unmapped codes, with record counts; rows without a key; other checks;
    disagreements; the share of diagnoses not in ICD-10-CM; "feasibility needs a bulk source" when there are only
    charts.
  * Records: TrialBox's forms or REDCap.

  The page also shows the feasibility table (coded, confirmed and proposed columns) and the criteria check: each
  patient ready, needs information, or not eligible, with every criterion's reason.
* **Help (D-132).**
  1. The wizard `/site/start`: one question per screen, with examples, what each answer means, and progress steps.
     The shortest path is a protocol plus pasted charts.
  2. Ask TrialBox `/ask`, linked from every page's header.
     * It answers "what do I do next?" from the readiness page, and "why is this patient on the list?" from the
       week list's candidate row or the patient check, in ja, zh-TW and en.
     * The local model (prompt `assist_v1`) only phrases a draft built from the pages. When the model is down, the
       draft is the answer.
     * It reads only with GETs. Its one POST (`/assist`) reads and writes nothing; a test proves both.
     * CRO accounts may open it too (added to D-104's list) and get only the reader's answer.
  3. An XLSX candidate template in the site's language with a sheet explaining each column, the mapping sheet, and a
     synthetic practice site that loads and resets in one tap.
  4. Remote help from Aimedics: only a switch, off by default, with a plain warning. When the box may hold real data
     (not DEV or TEST, or not data class D0), turning it on needs "approved by". No networking.
* **Words.** `console/i18n_site.py` has about 330 keys in en, ja and zh-TW, in plain words, with a glossary on the
  help pages. The old-word test still passes, and a new test checks the new keys against the same banned words.

*Decisions the owner should know.*

* **The rule changes no existing answer.** Without site facts (every existing site), nothing differs. With them, a
  proposed fact can turn a decided answer into "unknown" in either direction, and can never decide one:
  * it can rescue a coded "no" into "needs information";
  * it can stop a coded "yes" from counting as ready.
* **Value facts are conservative.** A proposed value (a lab) touches value criteria in both directions. So a chart
  that repeats a coded value also sends the patient to "needs information" until the value is confirmed.
* **Spaces and reproducibility.** Every space other than `main` has its own in-process lake (hash embedder) under the
  orchestrator's data folder.
  * Publishing to `main` rebuilds the current snapshot under the same id. A job re-run after a same-day site change
    is therefore not byte-identical (FR-REP-02). The hospital feed alone is unaffected.
  * The e2e stage uses a separate space, and a check confirms the hospital lake is untouched.
* **Local codes always need one confirmation.** Coded data from sheets and dumps is used as is, but each local code
  needs one confirmation per site, even when the shipped lookup has it: the JP-Core lookups are marked "verify".

*Evidence.*

* **`e2e_simple` stage 12**, "site set-up and data harmonization": 23 checks in 20.6 s; the whole run took 99.9 s of
  its 15-minute budget. Everything goes through the console, in ja:
  1. A new study's protocol (SITE5B) is drafted and the investigator approves it.
  2. Two charts are pasted. The page says "feasibility needs a bulk source", and both chart patients are "needs
     information".
  3. A Shift_JIS IT dump with hospital codes is loaded. The unknown code system is listed, and the patients behind
     unmapped codes are unknown.
  4. The codes are mapped with one tap each. A coded-eligible patient with a proposed malignancy is "needs
     information", not excluded.
  5. The messy Excel list is loaded. The era, 民國, width, unit, merged-cell and title-row fixes are listed; the
     day/month, unit, ID-column and no-key questions are asked, and a scripted coordinator answers them.
  6. One pseudonym is shared across dump, list and chart. The two birth dates are listed, then resolved.
  7. FEAS shows the proposed facts as not counted.
  8. The coordinator confirms each fact in one tap. The malignancy now excludes, the chart-only patient is ready, and
     FEAS shows the confirmed basis.
  9. The built-in forms are added, and the readiness page is green.
  10. Ask TrialBox answers, and changes nothing.
  11. No chart number or name appears on the pages or in the audit, and the hospital lake is untouched.
* **`tests/unit/test_one_rule.py`** (the safety rule, on the SQL engine, cascade S1 and FEAS over one lake). Cases:
  proposed-only; a proposed exclusion; a confirmed exclusion; a confirmed chart patient; a value in both directions;
  outside the window; another code; no code; a rescued coded "no"; an old lake.
* **Other unit tests.**
  * `test_messy.py`: dates, units, layout, checks, answers.
  * `test_site_setup.py`: the whole set-up at service level; Word, PDF and fake-OCR scans; quotes not in the chart are
    dropped; joining by pseudonym, never by name; templates; the practice site.
* **`tests/console/test_site_setup_pages.py`.**
  * The pages, through to green.
  * Every page in three languages for coordinator and investigator, with no raw keys.
  * Roles: the investigator reads; viewer gets 403.
  * Templates, the practice site and the remote-help approval.
  * `/api/v1`, and the assistant's read-only rule.
* **Suites.** Unit, console and testbench tests: 1,316 passed, 2 skipped.
* **`tools/backup_drill`: PASSED.** After the restore the site set-up reads back the same: 4 inputs, 36 facts, 7
  codes, 4 checks, and the 6 chart files.
* **`public_e2e`: 112/112 checks.** Stage 5c: the practice site, a one-tap confirm, the hospital's space untouched,
  and Ask.
* **The walk** (`node tools/public_walk.js` against `public_e2e --serve`): 780 checks, 0 failures, over 768 pages.
  That is 5 roles × 3 languages × desktop and phone, now with:
  * the ten site pages for coordinator and investigator, three for the administrator, and 403 for viewer and CRA;
  * Ask for every role.

  axe: 0 serious or critical (84 minor). Interactive targets: 21,600, none under 44 px. Taps:
  * T8, "CRC confirms a proposed fact on a phone" (ja): **2 taps** (target 2).
  * T9, "CRC pastes a chart" (zh-TW, phone): **3 taps** (target 3).
  * T1 to T7 unchanged: 2, 2, 2, 5, 5, 3, 2.

*Not done.*

* **OCR and the real model.**
  * No real OCR run: tesseract is not installed here, so the interface and the refusal are tested with a fake.
  * The real local model's extraction quality on real charts is untested; the stub reads the synthetic charts by
    rules.
* **Inputs.**
  * Pasted text without a chart number cannot be joined, so it is refused.
  * Codes from the hospital feed itself are not mapped here; only sheets and dumps fill the code list. The JP Core
    profile for unreadable 標準病名 stays in step 7.
  * A sheet's cells cannot be edited in TrialBox: the site fixes the file and reads it again.
  * Only the five analytes and units listed above are known.
* **Screening and the lake.**
  * The patient check covers coded criteria only; the SCREEN run reads the note criteria.
  * Publishing is not batched: every decision rebuilds the space's lake. That is fine for a site space, but at the
    hospital's scale `main` needs a batched "apply".
  * The LakeHttp `/site` route is tested at unit level only, with no compose run.
* **Remote help.** Only the switch is built; screen sharing itself is not.


**D-136 The morning mail shows the screening number.** Owner, 2026-11-08. N1 and N2 show the study's screening number
beside the pseudonym once a patient has one (`a1b2c3d4 (GZQO-0041)`), in every row: this week's patients, next
steps, marks and study visits. A coordinator can then find the patient's record in REDCap or on the screening log
without opening the console. Chart numbers and names stay out of mail as before (D-108). Evidence:
`tests/console/test_step2.py::test_mail_shows_the_screening_number_beside_the_pseudonym`; `e2e_simple` and
`public_e2e` check that every pseudonym with a number in the sent mail carries it, and still that no chart number or
name is in the mail.

**D-137 Step 7, Japan completeness.** TB-PLAN-04 step 7 (plan v4 F5; D-122 "not done"; builds on D-130, D-135),
2026-11-09.

*What was built.*

* **JP Core profiles on the adapter's output** (`mapping/jp_core/ssmix2_site.yaml`, `mapping/engine.py`).
  * A mapping can now re-profile the shared resource set: `profiles` maps a base profile URL to its own (`""` drops
    the claim) and `overlay` adds or replaces elements of one type and table. The TW mapping is unchanged.
  * The Japan mapping claims JP Core 1.1.0: JP_Patient, JP_Practitioner, JP_Encounter, JP_Condition,
    JP_Observation_LabResult / _Common / _VitalSigns / _BodyMeasurement, JP_MedicationRequest, JP_Procedure and
    JP_DiagnosticReport_Common. DocumentReference claims none (JP Core 1.1.0 has no DocumentReference profile).
  * It adds what JP Core asks for: the lab specimen (from the JLAC10 material code) and code text; the Rp number and
    order-in-Rp identifiers of a MedicationRequest; the 標準病名 coding beside the ICD-10 (so a code nothing can read
    reaches the lake as itself, the item D-130 left for this step); the class history of a visit; the HOT code.
  * Code systems fixed: YJ is `urn:oid:1.2.392.100495.20.1.73` (D-122 had used HOT9's second OID); HOT9 is
    `urn:oid:1.2.392.200119.4.403.1`; a hospital lab code and a claim's product code now sit in
    `urn:trialbox:local:*` instead of being labelled JLAC10 or YJ (the check found both).
* **JP Core `$validate` at ingest, offline** (`adapter/validate/jpcore.py`, `tools/jpcore_rules.py`).
  * Choice: a pure-Python check, not the HL7 validator jar. JP Core's StructureDefinitions are differential-only; the
    jar needs the R4 core package as well to snapshot them, and the box and the tests must run without either.
  * `tools/jpcore_rules.py --fetch` downloads `jp-core.r4#1.1.0` at build time into `.cache/fhir/` (pinned URL,
    sha256 `60567c583943150c26275f156d63c181e5608efcdf0616289a7fe5c032457da1`, the registry's sha1 checked too) and
    writes `validate/jp_core_rules.json` (committed, 35 KB): per profile its parent and its differential
    (cardinalities, fixed and pattern values, slices and discriminators, bindings), and the codes of the ValueSets the
    package enumerates. The package itself is not in the repo; tests and the box need only the rules file. 1.1.0 is
    the newest release on the FHIR package registry.
  * Each resource: the claim (a profiled type must claim JP Core; a TW Core claim is an error); base R4
    (`fhir.resources` R4B models); the profile chain (cardinality per parent instance, fixed and pattern values,
    value and pattern slices, required bindings with enumerated codes); the code systems we hold (ICD-10-CM in the
    full list, the LOINC check digit, the JLAC10 / YJ / HOT / MEDIS / ATC shapes; a code missing from a loaded
    licensed release is a warning, never an error).
  * The ingest checks 50 resources of each type (`AdapterConfig.profile_sample_per_type`), writes every outcome to
    `jp_core_validation.json` beside the snapshot, puts the summary in the ingest report (`profile_validation`,
    schema 1.2.0) and fails the report over `validation_error_max_pct`, with the first failure in plain words.
    Nothing is dropped. `adapter validate` (CLI) and `POST /$validate` (adapter API; one resource gives its
    OperationOutcome) do the same on demand. The reader's counts go to `reader.json`.
* **Licensed MEDIS / JLAC10 / YJ loader** (`adapter/licensed.py`; schema `terminology` of the trial database, in every
  backup).
  * A site loads its own release: `python -m adapter.licensed load --kind medis|jlac10|yj --file … --version …`, or
    `POST /terminology/load`. CSV or tab-separated, Shift_JIS or UTF-8 (detected and recorded); columns by the
    vendors' header names after NFKC (MEDIS 病名基本テーブル, JLAC10's five part columns or one code column, the HOT
    master's YJ, HOT13 and names); `--columns` for a release without a header row. Rows with a malformed or repeated
    code are skipped and listed. Each release keeps its version, file name, sha256, encoding, rows and who loaded it;
    the older release stays, inactive. Every load is audited (`terminology.load`).
  * Used by the SS-MIX2 reader (a 標準病名 code with no ICD-10 alternate resolves through MEDIS, only to a code in the
    ICD-10-CM list, else it stays unknown), by site set-up suggestions (method `licensed`: the file's ICD-10, or the
    name it gives through the existing name rules), and by the JP Core check (membership warnings).
  * Without the files, `licensed status`, `GET /terminology`, the orchestrator's `GET /setup/terminology` and a new
    block on the hospital-codes page (en, ja, zh-TW) say "not loaded: its codes stay unknown", and D-130 keeps them
    unknown.
  * `tests/fixtures/licensed/` holds three made-up 10-row files in the vendors' layouts (MEDIS in Shift_JIS CSV,
    JLAC10 in UTF-8 TSV, the HOT master in Shift_JIS CSV with full-width headers). No licensed data is in the repo.
* **SS-MIX2 messages** (`sources/ssmix2/source.py`).
  * ADT-52 is read by its trigger event: `A03` ends the visit (PV1-45, `finished`); `A06` / `A07`, or any event with
    PV1-2, changes the patient class (患者区分変更) and keeps the old class and the time (`Encounter.classHistory`). A
    change for a visit the storage lacks is counted, never made into a visit. An admission without a discharge is
    `in-progress`. A delta night takes a visit changed or discharged after `since`.
  * OMP-11 / OMP-12 (実施, RAS^O17, ORC/RXA) become MedicationRequest, as the brief asked: folded into the order with
    the same ORC-2 (only empty fields are filled), else a medication of their own. YJ, HOT and ATC are read from the
    primary and alternate codes of RXE-2 / RXA-5, and all three stay coded. OMP-02 / OMP-12 are marked injections.
  * Extended storage (`<root>/extended_storage/<id>/<day>/<kind>/<file>`): text (UTF-8, Shift_JIS, ISO-2022-JP,
    EUC-JP), HTML / XML, Word and PDF with a text layer become note rows: a DocumentReference and note text for the
    two models. Standardized file names are versioned and deleted like the storage; a file without readable text (a
    scan, an image) is kept as a document without text and counted. The document id is a keyed hash: neither the
    chart number nor the path leaves the adapter.
  * `tools/ssmix2_export.py` writes all of these into the synthetic hospital, each so that it reads back as the CSV's
    rows: every 40th visit is an admission changed to outpatient (ADT^A07); injectables are OMP-02 orders; every
    fifth oral and fourth injection order is only a 実施, every seventh / third has both; every other drug is sent
    with a synthetic HOT9 primary code; a discharge summary (Shift_JIS) and an imaging report (PDF) go into extended
    storage.

*Decisions the owner should know.*

* **Validator: offline structural, not the HL7 jar.** It checks what JP Core 1.1.0's differentials state, plus the
  code systems we hold. It does not run FHIRPath invariants, `type` / `profile` / `url` slice discriminators
  (extension and choice-type slices), or bindings to ValueSets the package does not enumerate. A site that wants the
  HL7 jar's verdict can still run it on an NDJSON snapshot with `jp-core.r4#1.1.0` in a package cache.
* **ADT-52 and OMP-11/12 read differently from D-122.** D-122 (and the SS-MIX2 storage specification as we read it)
  calls ADT-52 the discharge (退院実施) and OMP-11/12 the 実施 records; the brief calls ADT-52 the patient class
  change and OMP-11/12 orders. The reader takes ADT-52 by its trigger event, so both readings work; OMP-11/12 go into
  MedicationRequest as asked (folded into their order), not MedicationAdministration. Check both on a site's real
  storage.
* **Injections claim JP_MedicationRequest**, not JP_MedicationRequest_Injection: that profile requires
  `medicationReference` (a contained Medication), and the lake and the SQL engine read `medicationCodeableConcept`.
* **A licensed MEDIS file gives WHO ICD-10.** A code is used only where it is also an ICD-10-CM code; any other code
  stays unknown (D-130). Suggestions from the files still need one confirmation by a person (D-135).
* **The MEDIS 病名交換用コード OID** (`urn:oid:1.2.392.200119.4.101.6`; JP Core 1.1.0 has no NamingSystem for it) and
  the vendors' column names are our reading; verify them against the site's releases.
* **GOUT-COH is pinned.** `e2e_simple` now checks the main run's GOUT-COH numbers against those recorded on master
  f5c78fb before this step (`GOUT_COH_BEFORE_STEP7`).

*Evidence.*

* **`e2e_simple` stage 13**, "Japan: SS-MIX2, JP Core and the licensed code lists": 16 checks in 11.0 s; the whole
  run PASSED in 107.8 s.
  * A 400-patient synthetic SS-MIX2 hospital: 68 ADT-52 class changes, all read into their visits; OMP-02 165,
    OMP-11 1,077 (392 with their order, 685 alone), OMP-12 109 (55 with, 54 alone); 30 extended-storage documents,
    all in the lake with their text.
  * Its patients, visits, medicines, diagnoses and results equal its CSV export's.
  * JP Core `$validate` at ingest: **612 resources sampled (50 per type, 15 types), 0 failed**, 48 warnings (codes not
    in the 10-row licensed samples). `$validate` over the written snapshot and `adapter validate` agree. The TW Core
    output of the same hospital fails, saying "claims a TW Core profile".
  * The licensed lists: "not loaded" for all three first; then each 10-row sample loads (Shift_JIS, UTF-8,
    Shift_JIS) with its version and source, and is audited. With the site lookups removed, the MEDIS sample resolves
    161 diagnoses; the codes it does not list stay unknown.
  * GOUT-COH FEAS funnel of the SS-MIX2 storage = its CSV export's.
  * **GOUT-COH of the main run, before and after: identical.** FEAS start 5,000; INC-02 1,210, INC-03 797, INC-04 237,
    INC-05 54, INC-06 26, INC-07 6. SCREEN S0 3,341, S1 9, S3 0, S4 9; listed 9 (5 high, 4 review; 3,332 excluded).
    Cohort list: 5 members.
* **`tests/unit/test_japan_completeness.py`** (26 tests): the loader on the three samples, its refusals and skipped
  rows, "not loaded"; D-130 with and without the MEDIS list (a WHO-only code stays unknown); suggestions; ADT-52
  discharge, class change, an unknown visit and the delta; OMP-11/12 folded and alone, with HOT and YJ;
  extended-storage versions, deletes, encodings, PDF and an image; a 120-patient hospital passing JP Core at ingest;
  the check failing on 13 kinds of fault; the `$validate` and terminology APIs. `tests/console/test_site_setup_pages`:
  the hospital-codes page shows each list loaded or not, in ja, zh-TW and en.
* `tests/integration/test_ssmix2_path.py` (CSV funnel = SS-MIX2 funnel; D-130's unmapped diagnoses) passes with the new
  messages.
* Suites: unit, console and testbench 1,344 passed, 2 skipped. `make lint` clean. `public_e2e --lang ja`: 112/112.
* `tools/backup_drill`: PASSED; a new check reads the licensed lists back after the restore (3 releases, 30 codes).
* The walk (`node tools/public_walk.js` against `public_e2e --serve`): 780 checks, 0 failures over 768 pages; axe 0
  serious or critical (84 minor); 21,618 targets, none under 44 px; taps T1 to T9 unchanged.

*Not done.*

* No real MEDIS, JLAC10 or YJ release was loaded (licensed); the column names and headerless layouts need a check
  against them. JLAC10 releases carry no LOINC: `jlac10_to_loinc.csv` stays the site's own table.
* No HL7 validator run against JP Core here (no R4 core package in the cache). Newer JP Core releases (1.1.2, 1.2.x)
  are not on the package registry.
* AllergyIntolerance (SS-MIX2 allergy messages) is not read, so no JP_AllergyIntolerance is produced; the rules cover
  it. MedicationAdministration and contained Medication resources are not produced.
* ADT-52's meaning at a real site, ADT-21/31/41/42/51 and vendors' RXA variants are untested on real storage. Extended
  storage is read by folder kind only (no `_contents.xml` index); scans without a text layer need OCR.
* The list status is on the hospital-codes page and the APIs, not on the readiness page or the admin home.

**D-138 Step 8, handover.** TB-PLAN-04 step 8 (plan v4 §4 row 8; D-124, D-125, D-126, D-128), 2026-11-09. Built in
a cloud container with no GPU and no Docker daemon, on synthetic data only.

* **Tiers from measured records only** (`tools/tiers.py`, `deploy/install.sh --tier`). `small` = `rtx5090` (one RTX
  5090, sleep swap, 8k), `medium` = `gb10` (DGX Spark, pair resident, 16k), `large` = `rtxpro6000` (RTX PRO 6000,
  pair resident, 32k): the three boxes of D-124. A tier installs only when its profile has a serving record of its
  own uncapped card (the site's `deploy/site/` or the vendor's `deploy/measured/serving_config.<gpu>.json`, the rule
  of `tools/serving_config.py measured`) and the machine's card is that card (`deploy/gpu_profile.sh`). The check runs
  first, with the host's python3, before Docker, the bundle or a setting is touched; a refusal (exit 3) names the
  missing file and the two ways to get a record. No override: `TB_ACCEPT_UNMEASURED_GPU=1` stays for a `--gpu` trial
  boot and does not open a tier. `--tier-check` asks only. Today `large` has a vendor record; `small` and `medium` are
  refused until a card of theirs is measured.
* **Per-service secrets** (D-128, review F-02; `tb_common/service_auth.py`, `tools/trialbox/svc_secrets.py`,
  `deploy/docker-compose.secrets.yml`). Each of the nine TrialBox services has its own token
  (`deploy/secrets/services/<service>.token`, 0600, owned by the container user, folder 0700), mounted into that
  service only; the administrator's `operator` token stays on the host. Every service reads a registry of the
  tokens' sha256 (`public/tokens.json`, not secret), knows which service is calling, and accepts only the callers of
  `CALLERS` (orchestrator: console, mail-gateway; mail-gateway and adapter: orchestrator, console; lake: orchestrator,
  criteria-compiler, adapter; doc-parser, criteria-compiler: orchestrator; embed-service: lake; gateway:
  orchestrator, criteria-compiler, doc-parser, console). A doc-parser token is now refused by the orchestrator (403).
  The overlay also clears the mail passwords outside mail-gateway, the cloud key outside the gateway, the database
  passwords in every service, and `TB_DB_URL` in doc-parser and embed-service. `make_app` keeps `protect_reads`,
  `/healthz` open and the `TB_ENV` rule (unset = PRODUCTION, which refuses without a token); a registry that is
  configured and unreadable refuses every call (503). Without a registry (tests, `make demo`, older boxes) the shared
  token rule is unchanged and the service warns once.
  * **Migration**: a box installed before step 8 keeps its `TB_SERVICE_TOKEN` working, its hash in the registry as
    `legacy`, with a warning in the log when it is used, until every token is rotated; then it is gone from the
    registry and from `deploy/.env`. A new box never gets a shared token.
  * **Rotation**, one place (RUNBOOK §5 "Secrets"): `python3 -m tools.trialbox secrets rotate [--service X]` writes
    the new token, keeps both hashes while the rotated services are recreated (`docker compose up -d --no-deps
    --force-recreate --wait`, file set from `COMPOSE_FILE` in `deploy/.env`), then drops the old one; `--service db`
    changes both database passwords with `ALTER ROLE` (password on stdin, never on a command line) and recreates
    their users. `secrets status` shows names, files, modes and ages, never a value.
* **One-page network, port and secret sheet** (`tools/network_sheet.py`;
  `docs/handover/network-sheet.{en,ja,zh-TW}.{md,html}`, A4 landscape). Generated from the five compose files a box
  runs (base, secrets, three GPU profiles): 17 services, every listening port (8010 to 8016, 8020, 8090, 5432, 8080,
  8000), the only published one (`127.0.0.1:8090`, the console), who may reach each (from `CALLERS`), the three
  networks, the outbound rules of `deploy/egress.py` with the setting that opens each, and 19 secrets by name, place
  and receiver. `install.sh` writes the site's own sheet from its file set and `deploy/.env` (host names only) to
  `deploy/site/`. **Outbound by default is not quite "none"**: criteria-compiler reaches `clinicaltrials.gov:443`
  while `TB_CTGOV_MODE=live`, the wizard's default (public registry, no patient data); the sheet says so.
* **The update path** (`tools/apply_update.sh` → `tools/trialbox/update.py`). Verify and stage as before (Ed25519 and
  sha256, D-77); then backup first (D-126; refused without `deploy/secrets/backup.pub` and `TB_BACKUP_TARGETS`; on a
  compose box the services stop, the db container dumps both databases, and a one-off container on trialbox-net
  writes the encrypted backup with every volume read-only, `TB_PG_DUMP_DIR`); a rollback point (replaced images
  tagged `<repo>:rollback-<bundle>`, overwritten models kept, the local dumps, 0600, removed after success, because
  the box cannot read its own encrypted backup); apply; `up -d --wait` (services migrate at start); rulesets; check;
  `update.applied`. Any failure after the rollback point: images, models and databases back, restart, check,
  `update.rolled_back`. Three boxes: compose (a site), demo (the demo VM's one container, checked by `e2e_simple` in
  the new container) and in-process (`tools/update_drill.py`). The demo image gained PostgreSQL (missing since D-126,
  so the image could not have started `tools.demo`); `demo-vm-startup.sh` now writes a recreate script and a
  root-only env file instead of putting the password on the command line.
* **Log retention** (`tb_common/retention.py`, `tools/trialbox/logs.py`, the RETENTION job; RUNBOOK §2 "Logs").
  Service logs collected nightly on the host per service and day, kept `logs_days`; the audit chain never deleted,
  copied nightly to `TB_AUDIT_ARCHIVE_DIR`, compressed, with a sha256 manifest, verified before and after (a chain
  that does not verify is not archived); mail logs (intake, sent, finished sends, the morning-mail log) pruned by the
  RETENTION job after `mail_log_days`, an unfinished send kept; job outputs and attachments as before. Install
  defaults by country (wizard `retention_rules`, from the report language): service logs 365 days, mail logs 5 years
  (JP, 医師法 §24) or 7 years (TW, 醫療法 §70), outputs 365 days, attachments 90 days, audit 10 years on the box
  (review §6 q.5 and q.25). `logs_days`' schema default moved from 180 to 365; `mail_log_days` is new.
* **Windows / WSL2 groundwork** (D-125): `docs/handover/OFFLINE-MEDIA.md` (the disk: WSL, the Ubuntu root file
  system, the NVIDIA driver, debs, the signed bundle of images, models and rulesets, measured records, printed
  sheets; nearer 40 GB than 30), `deploy/windows/preflight.ps1` and `preflight.sh` (Windows build and edition, CPU
  virtualisation, WSL2, GPU driver, disk, memory, systemd; one PASS or FAIL line each),
  `docs/handover/WINDOWS-INSTALL-CHECKLIST.md`.

*Evidence.*

* `tests/unit/test_install_tiers.py` (9): the mapping; `large` from the vendor record; `small` and `medium` refused
  with the file and how to measure; wrong card, no card, unknown tier; a capped or wrong-mode record refused; a site
  record of the card's own makes `small` installable; `install.sh` exits 3 before the host step, and the trial-boot
  switch does not help; `--tier-check`; `--tier` with `--gpu` or `--mode stub` refused.
* `tests/unit/test_service_secrets.py` (11): tokens 0600 and distinct, a registry of hashes only, `init` idempotent;
  the caller table on real `make_app` services (doc-parser to orchestrator 403, console to lake 403, operator
  everywhere, 401, 403, healthz open); the old token accepted with a warning that does not carry it, then refused
  after a full rotation; behaviour without a registry and `TB_ENV` unchanged; an unreadable registry 503; a
  one-service rotation restarts only it and keeps both hashes when the restart fails; the database rotation's
  passwords only on stdin; the overlay gives each service its own token and clears the rest; a scan of every
  service's clients against `CALLERS`.
* `tests/unit/test_network_sheet.py` (7): every service and port of the compose files, read independently of the
  sheet's code, is on the committed sheet in all three languages, which equals a fresh render; a site sheet shows its
  mail hosts and no secret value although its `.env` has passwords.
* `tests/unit/test_update_path.py` (13): the step order; a failed backup changes nothing; a failure at apply,
  restart, rulesets or check rolls back and is audited; a failed rollback says so; the compose commands in order
  (quiet box, dumps, backup container with passwords only in its environment, rollback tags, load, start) and their
  rollback (tags back, both `pg_restore --clean`, models back); no key, no update; the demo box; a first install only
  loads; the in-process box migrates, then rolls a migrated database back from its dump.
* `tests/unit/test_log_retention.py` (7) and `tests/unit/test_windows_preflight.py` (3).
* `tools/update_drill.py` (the in-process box, real bundles signed with a throwaway vendor key): PASSED, 13 checks in
  233 s: e2e_simple's box; a tampered bundle refused; the good bundle backed up (the hospital key opens it), applied,
  migrated, data unchanged, audited; a bad migration and an unhealthy release each rolled back to the same release,
  models, schema version 1 and data; the audit chain verifies with `update.applied`, `update.rolled_back`,
  `update.rolled_back`; no secret in the history; `e2e_simple` passes again on a fresh box afterwards.
* Suites: unit, console and testbench 1,394 passed, 2 skipped (1,344 at step 7; 50 new). `make lint` clean.
  `tools/e2e_simple.py`: PASSED in 110 s. `tools.backup_drill`: PASSED in 136 s. `public_e2e --lang ja`: 112/112
  (a first run, started while the full suite used the same throwaway Postgres, stopped on a page without a csrf
  token; run alone it passed). No page changed, so the walk was not re-run.

*Not done.*

* **Nothing ran on a GPU, in Docker or on the cloud.** `docker compose` with the secrets overlay, the compose and demo
  boxes of the update path, the network sheet inside the image at install, and the new demo image build were not
  executed here (no Docker daemon); they are tested against recorded commands. The demo-VM run below is the
  done-check that remains.
* fhir-store (HAPI) and Postgres have no per-caller token: network isolation and a password only (review F-11 for
  HAPI). The gateway still routes on the self-declared `X-TB-Caller`; the verified caller is in
  `request.state.tb_caller`, but the gateway's policy does not read it yet. No mTLS.
* The mail passwords and the cloud key still live in `deploy/.env` (cleared in the containers that do not need them),
  not in separate secret files; the hospital rotates them at their source. Key custody on Windows (BitLocker,
  DPAPI/TPM; review F-01, F-10) and the full offline installer wait for D-125's post-platform work.
* Anti-rollback, a key id and an expiry in the update manifest (review F-15) are not added; an older signed bundle
  still applies. A failed rollback leaves the box to a restore from the encrypted backup with hospital IT's key.
* `trialbox backup` run by hand on a compose box still needs `pg_dump` and the database reachable from where it runs;
  the update path's one-off container is the route that works and could become the default.
* The owner may want the wizard to default to `TB_CTGOV_MODE=cassette`, so that outbound is none by default.

*The demo-VM commands still to run* (owner's OK; about one hour of `trialbox-demo`, e2-standard-4, about US$0.15,
plus a few cents of storage):

```sh
deploy/gcp/demo-vm-update.sh build <bucket>   # a machine with Docker and about 15 GB free: images A, B (good), C (broken)
gcloud compute instances add-metadata trialbox-demo --zone asia-east1-b \
  --metadata-from-file startup-script=deploy/gcp/demo-vm-startup.sh,tb-demo-password=/mnt/project-files/trialbox-demo/password.txt \
  --metadata tb-demo-image=gs://<bucket>/step8/trialbox-demo.tar.gz
gcloud compute instances start trialbox-demo --zone asia-east1-b
deploy/gcp/demo-vm-update.sh run <bucket>     # apply B --target demo, e2e_simple in it; apply C, rolled back to B
gcloud compute instances stop trialbox-demo --zone asia-east1-b
```

**D-139 Step 9 preparation: run script and documents.** TB-PLAN-04 step 9 (plan v4 §4 row 9, §5; TB-PLAN-03 §9),
2026-11-09. Everything of step 9 except the paid GPU run and the independent re-review. Built in a cloud container with
no GPU and no Docker daemon, on synthetic and public data only.

*What was built.*

* **The complete-platform run** (`tools/complete_run.py`, `tools/stage_shots.js`). One command runs every stage of
  plan v4 §5 in ja and zh-TW and writes `report/report.md` and `report.json` with per stage the checks, the time, a
  screenshot and the git head. Each part runs in its own process, so one box at a time holds memory and environment:

  | Part | What it runs | §5 |
  | --- | --- | --- |
  | prepare | the synthetic hospital of `--patients` (`tools.synth_hospital`, a JP and a TW site, notes in ja, zh-TW, en), made once | — |
  | install | the vendor's (and on the card the live) serving record measures `rtxpro6000`; tier `large` resolves on the card; `small` is refused | install on a measured box |
  | hospital ja, zh-TW | the `e2e_simple` path on that hospital: data in, criteria, approval, SCREEN (with the pair and the canary gate on `--model pair`), lists, marks, N1/N2 mail, REDCap two-way, data core and conflicts, built-in forms and ODM/REDCap CSV, lifecycle, site set-up, Japan (SS-MIX2, JP Core), audit, byte-identical re-run | import, paste and approve, screen, lists, forms, sync, mail, export, audit |
  | public ja, zh-TW | `tools.public_e2e`: the same path in the console on real public notes | the same on real text |
  | walk | a fresh public console on the stub, then `tools/public_walk.js`: 5 roles × 3 languages × desktop and phone, axe-core, 44 px targets, tap counts | desktop and phone |
  | backup, update | `tools.backup_drill`, `tools.update_drill` | back up and restore; update |
  | scale | `tools.hospital_sim scale` at `--patients` (cascade S0–S5, DL-1 pack, recall certificate) | — |

  After each console part the console is served on a free local port and `tools/stage_shots.js` signs in as the role
  that does the stage, in the part's language, and photographs the page that shows its result (the state at the end
  of the part; the pages of earlier stages still show their results). Parts with no console of their own get a picture
  of their check table. Screenshots go to the run's folder and are never committed (`.gitignore`).
* **On the card** (`--model pair`): the judge and verifier clients of `public_e2e.real_models` go into the box
  (`public_e2e.attach_models`, now shared), `TB_CANARY_GATE=on`, and `e2e_simple.PAIR` turns its stage-3 checks from
  "stub, never excludes" to "the pair ran, the canary passed, a note excludes only when both agree". With the pair
  the re-run stage re-runs FEAS only (a second SCREEN doubles the paid time, and batched model answers are not
  bit-reproducible, as on the Spark), and the hospital's time limit is one night (8 h) instead of 15 minutes per 5,000
  patients. The GPU key comes from `TB_GPU_KEY` only; the console password from `TB_DEMO_PASSWORD` or made at
  random, never printed and never on a command line (the walk reads it from `TB_SHOT_PASSWORD` now).
* **The VM wrapper** (`deploy/gcp/complete-run.sh`): private `CLOUDSDK_CONFIG` required; the hospital is made before
  the VM starts; a fresh API key in a 0600 file; `gpu-pro6000-run.sh` as the startup script; wait for
  `PRO6000-RUN-READY`; live serving record checked; the run; `--after-models` stops the VM as soon as the last model
  part is done (the walk, backup, update and scale run on the stub and need no card); a trap stops it on any exit,
  waits for `TERMINATED` and puts `gpu-sim-startup.sh` back; `--stop` does it by hand; `--dry-run` prints the
  commands.
* **Fixes found by running it at other sizes.** `list_demo` signs the PI and CRC in again when the demo's clinic day
  is not the first day (sessions end after 8 hours; a 2,000-patient hospital's first clinic day is days later).
  `e2e_simple` stage 13 compares GOUT-COH with the numbers pinned before step 7 only on the gate's own hospital (5,000
  patients, stub); at another size or with the pair it checks that the FEAS and SCREEN funnels never grow.
* **Tests:** `tests/unit/test_complete_run.py` (the plan of parts, a page for every stage of both tools, the report,
  no password or key on a command line), `tests/unit/test_doclint.py`.

*The documents: 18 → 8.* The plan's "18 → 8" (TB-PLAN-03 §9) counted the design set in `docs/plan/design/`. That set
is frozen reference by the owner's build-stage rule (TB-DS-00R §1) and a record by this step's brief, so it stays as
it is. The maintained documents at the repository level also number 18 (README, SPEC, SPEC_v3 and fifteen in
`docs/`); they are the ones merged. The eight: `README.md`, `docs/ARCHITECTURE.md`, `docs/RUNBOOK.md`,
`docs/SECURITY.md`, `docs/DATA.md`, `docs/VALIDATION.md`, `docs/USER_GUIDE.md`, `docs/DECISIONS.md` (unchanged,
append-only). Records stay records: `docs/reviews/`, `docs/plan/`, `docs/research/`, `spec/v4/`, and the new
`spec/archive/` (with an index).

| Old | Went to |
| --- | --- |
| `README.md` | README (what it is, try it, map); the command table → USER_GUIDE §5; the POC → RUNBOOK §9; the Docker quickstart → RUNBOOK §9 "developer test stack"; site install → RUNBOOK §1 |
| `docs/ARCHITECTURE.md` | ARCHITECTURE, rewritten to head (one Postgres `trialbox_wf`, no MinIO, no Hermes, the pair, tiers, console roles, data core, site set-up); its test table → VALIDATION §1 |
| `docs/PLAN.md` (v1 plan) | module list and interfaces → ARCHITECTURE §2; data flows → ARCHITECTURE §4–6; test plan → VALIDATION §1; phase map and resolved §12.2 decisions dropped as stale (in DECISIONS D-02..D-04) |
| `docs/RUNBOOK.md` | RUNBOOK §1–10, same section numbers for install (§1), logs (§2), updates/backup/secrets (§5), acceptance (§6), Spark and pins (§8), POC (§9), 5090 (§10); mail commands and roles → USER_GUIDE |
| `docs/HARDENING.md` | SECURITY §1 (disk, TPM, swap, GB10), §2 (egress), §4 (TPM-sealed keys), §6 (updates, retention) |
| `docs/DEMO_VM.md` | RUNBOOK §11 (demo VM, its update path, cost) |
| `docs/SERVING_CONFIG.md` | the record and the model gate → VALIDATION §3; capture, GPU runs and cost → RUNBOOK §11; profiles → ARCHITECTURE §7 |
| `docs/BENCH.md` | VALIDATION §4 (the bench table, the first hosted-model run summarised; per-model table left in `eval/bakeoff/results/2026-10-25/`) |
| `docs/OPEN_DATA.md` | datasets, licences, the MIMIC notice → DATA §6; what runs, results, limits → VALIDATION §5; per-step funnel tables left in `.cache/open_data/report.md` (re-made by `make open-data-e2e`) |
| `docs/CONSENT.md` | USER_GUIDE §6 |
| `docs/HANDOFF.md` (2026-10-24) | the Test Bench rules → VALIDATION §6; how to run and the traps → RUNBOOK §4 and VALIDATION §1; licence traps (Mirth, Soda Core, Db2) and the LiteLLM compromise dropped as already applied (D-86 era); the v4 build order, phases and session rules dropped as stale (superseded by TB-PLAN-04) |
| `docs/NEXT_SESSION_PROMPT.md` | dropped as stale (the starter prompt of plan v4 is `docs/plan/design/STARTER-PROMPT-plan-v4.md`) |
| `docs/PROGRESS.md` | dropped as stale: the phase log duplicates DECISIONS D-01..D-111 and git history; its v1.0 checklist is done |
| `docs/INTEGRATION_SCENARIOS.md` | moved unchanged to `spec/archive/`; the scenario table and open gaps → DATA §5; the legal baseline → SECURITY §7 |
| `docs/LANDSCAPE.md` | moved unchanged to `spec/archive/` (corrected by `docs/research/2026-10_literature_competitors.md`) |
| `SPEC.md`, `SPEC_v3.md` | moved unchanged to `spec/archive/` (v1 contract and v3, superseded by `spec/v4/`) |

Words (counted with `wc -w`): the eighteen were 111,717 words (DECISIONS 33,426). The eight are 47,373 words (DECISIONS
35,965); the seven new documents 11,408 words where their sources had 24,550 (README, ARCHITECTURE, PLAN, RUNBOOK,
HARDENING, DEMO_VM, SERVING_CONFIG, BENCH, OPEN_DATA, CONSENT, HANDOFF, NEXT_SESSION_PROMPT, PROGRESS), 13,142 (53 %)
fewer. The 53,741 words moved to `spec/archive/` are records, kept whole. Links fixed in code, scripts and tests
(`Makefile`, `install.sh`, `check_host.sh`, the GCP scripts, `apply_update.sh`, `tiers.py`, `parity_replay.py`, the
open-data tools, fixtures and tests, the Test Bench, `channels/grammar.py`). The records keep their links as they were
written.

*doclint* (`tools/doclint.py`, in `make lint`): the set is exactly the eight and no other Markdown file sits in `docs/`;
one title, no skipped heading level, no heading twice; every relative link and `#anchor` resolves; every repository
path in backticks exists or is ignored by git (made on the box); no file outside the records names a retired document.
DECISIONS is checked for headings only (old entries name files removed later). The design-set linter
`docs/plan/design/tools/doclint.py` is untouched. Result: clean.

*The local run* (`python -m tools.complete_run --dir <dir>`, head a69b51b, a shared 4-CPU container, stub model,
5,000 patients): **PASSED, 581 of 581 checks, 60 of 60 screenshots, 19.6 minutes.** The report is committed as
`eval/complete_run/2026-11-09-stub-5000/report.md` and `report.json` (screenshots not committed).

| Part | Checks | Seconds | Numbers |
| --- | --- | --- | --- |
| install | 3/3 | 1 | vendor record measures `rtxpro6000`; `large` resolves on its card; `small` refused |
| hospital ja | 161/161 | 113 | SCREEN GZQO: S0 3,022 → S1 92 → S3 92 → S4 81; listed 81 (2 high, 79 review); stub, never excludes |
| hospital zh-TW | 161/161 | 112 | the same funnel |
| public ja | 112/112 | 44 | PUB-ONC: S0 268 → S1 90 → S3 90; listed 90 |
| public zh-TW | 112/112 | 44 | the same |
| walk | 5/5 | 422 | 780 checks over 768 pages, 0 failures; axe 0 serious or critical (84 minor); 21,600 targets, none under 44 px; taps T1–T9 2, 2, 2, 5, 5, 3, 2, 2, 3 |
| backup | 11/11 | 113 | 11,367 rows in `trialbox_wf` and 982 files restored equal |
| update | 12/12 | 248 | a good bundle applied; a tampered one refused; a bad migration and an unhealthy release rolled back |
| scale | 2/2 | 78 | cascade at 5,000 patients: 75 s, 127 model calls |

Earlier runs of the script at 2,000 patients found the two size-bound checks fixed above (the session timeout and the
pinned GOUT-COH numbers); at 2,000 the GOUT-COH cohort list is empty, so the local run uses 5,000, as the gate does.

*The other checks at this head.* `make lint` clean (with doclint). Unit, console and testbench suites: 1,405 passed,
2 skipped (1,394 at step 8; 11 new; the first full run found `eval/complete_run/` missing from `eval/DATASETS.yaml`,
now listed as D0 synthetic). `tools/e2e_simple.py`: PASSED in 115 s. `tools.backup_drill`: PASSED in 133 s.
`public_e2e --lang ja`: 112/112 in 55 s.

*The GPU run (not run: the owner's OK first).* Commands, from a checkout of the head to be measured:

```sh
export CLOUDSDK_CONFIG=$(mktemp -d); unset CLOUDSDK_AUTH_ACCESS_TOKEN
gcloud auth activate-service-account --key-file /mnt/project-files/uploads/hearth/<key file>   # in place, never copied
gcloud config set project trialbox-demo
cd trialbox && TB_COMPLETE_DIR=/tmp/tb-complete-gpu deploy/gcp/complete-run.sh --patients 50000
gcloud compute instances describe tb-gpu-sim --zone asia-east1-a --format='value(status)'   # must say TERMINATED
```

*Cost.* `tb-gpu-sim` is about US$2.74 an hour while it runs. The estimate, from the local timings above and the
2026-11-08 PRO 6000 run (`eval/parity/gpu-run-2026-11-08-pro6000/`: `public_e2e` with the pair 1,303 s, of which
PUB-ONC's SCREEN 563 s for 90 patients at S3, about 6.3 s a patient):

| Step | Basis | Hours |
| --- | --- | --- |
| hospital made before the VM starts | 4 s per 10,000 patients here | 0 |
| boot to `PRO6000-RUN-READY` | about 15 minutes with the weight hashes (the step-1 run) | 0.25 |
| hospital ja, 50,000 patients | non-model path 113 s at 5,000, linear: about 0.3 h; SCREEN GZQO at S3 92 × 10 = about 920 patients × 6.3 s: 1.6 h; the canary at box start: a few minutes | 1.95 |
| hospital zh-TW | the same | 1.95 |
| public ja and zh-TW | 1,303 s each with the pair | 0.72 |
| stop and check `TERMINATED` | the walk, backup, update and scale run after it | 0.05 |
| **in all** | | **about 4.9 h, US$13.50** |

Synthetic notes are shorter than the public case reports, so the model part may take half as long: then about 3.3 h,
US$9. A spot preemption costs another boot (US$0.70) and a re-run. With steps 1 and 6 (about US$1.50 and US$2.30)
this passes plan v4's "under US$15 of GPU time" by about US$2; the owner decides. A cheaper run at `--patients 20000`
is about 2.6 h, US$7. Adding N-11 zh-TW on the deployed files while the VM is up (VALIDATION §3) is about 0.2 h more.

*Self-review against the reviews' yardstick* (TB-PLAN-03 §9: complete; no stale references; built claims name a test
or commit; one owner, status and history; the named reader can act alone. 4.5 = five points with one minor residue).
This is the author's score; the independent re-review comes after the paid run.

| Document | Score | Below 4.5, or the residue |
| --- | --- | --- |
| README | 4.5 | residue: the repository map names packages, not their tests |
| ARCHITECTURE | 4.5 | residue: the C4 views are tables and text, not a model; "held by" covers each section, not each row |
| RUNBOOK | 4.5 | residue: the Windows/WSL2 install lives in `docs/handover/` (a second document for that reader) |
| SECURITY | 4.5 | residue: the law tables need the site's counsel by design (marked *legal review*) |
| DATA | 4.5 | residue: the canonical column list is `services/adapter/mapping/templates/CANONICAL.md` |
| VALIDATION | 4.5 | residue: the model-gate numbers are from the 2026-11-08 card runs, not from this head |
| USER_GUIDE | **4.0** | gap: written in English only, pointing to the in-console help in ja and zh-TW; no committed screenshots (they come from the complete run). A ja and zh-TW copy is not cheap: left for after the re-review |
| DECISIONS | **4.0** | gap: 35,000 words, entries of varying shape, old entries name removed files; append-only, so not fixed here |
| The build | **4.0** | gaps: the complete run on the card has not run (plan v4 §5: not complete until it passes); N-11 zh-TW on the deployed files not recorded; no TOTP; HAPI and Postgres have no per-caller token; only `large` is installable (Spark and 5090 unmeasured); OCR never run on a real scan; no anti-rollback in the update manifest |

Cheap gaps fixed in this step: an owner, status and history line on each of the seven new documents; the test that holds
each built claim named in ARCHITECTURE, RUNBOOK and SECURITY; VALIDATION's gate table refreshed from this head's
runs.

*Not done.*

* **The paid run** (above) and so the done-check's "run report with a screenshot per stage from head" on the card:
  only the stub run exists. Until it passes the platform is not complete (plan v4 §5).
* **The independent re-review** of the eight documents and the build.
* **Not run here:** nothing ran on a GPU, in Docker or on the cloud; `deploy/gcp/complete-run.sh` was checked
  with `--dry-run` only. The pair has never run the `e2e_simple` path; stage 12's chart reading and the hospital's
  SCREEN with the real models may show checks that only held for the stub. The time estimate rests on one public
  run's rate.
* **The documents.** USER_GUIDE in ja and zh-TW; DECISIONS stays long. The design set in `docs/plan/design/` keeps its
  own 18 documents and its own linter. `spec/v4/` still names the moved files as they were (a record).
* **Numbers in VALIDATION** that are not from this head: the model gate (2026-11-08 card runs) and the bench
  (2026-10).

**D-140 Reference data pack and the two CT.gov modes.** TB-PLAN-04 (owner decision 2026-11-09), 2026-11-09. Built in
a cloud container with network access through a proxy, no GPU, no Docker; tests on committed samples only.

*Owner decisions (2026-11-09).*

1. Keep both ClinicalTrials.gov modes; each hospital chooses at install, depending on its IT environment: **live**
   (the box may reach clinicaltrials.gov:443) or **offline** (no outbound access; the trials come from the data pack).
2. The release carries the full ClinicalTrials.gov data and the other essential reference data for Japan and Taiwan
   whose licences allow it.
3. The settings wizard and `install.sh` default to **offline**; live stays selectable at install and in the
   settings. The network sheet's default text says so.
4. A NOTICE / attribution page, generated from the pack manifest: `NOTICE.md` in every pack and the console's
   "Sources and licences" page (en, ja, zh-TW): every source, its licence, its terms and the credit it asks for.
5. ATC: no WHO ATC/DDD index. Only the ATC codes the Taiwan NHI drug list carries (`ATC代碼`, kept as given), plus
   TrialBox's own drug-class table later (not built here).

*Sources* (`tools/refdata_fetch.py sources` prints this table from the code; URLs pinned there).

| Source | Decision | Licence | Size | Refresh |
| --- | --- | --- | --- | --- |
| ClinicalTrials.gov, all studies (API v2 bulk JSON zip) | ship | NLM terms; NLM disclaimer in the attribution | ~2.8 GB zip, 10.6 GB unpacked, 610,756 studies (2026-11-06); ~2.2 GB in the pack | monthly in the pack (daily at source) |
| TFDA drug trials (data.gov.tw 177198, export 205) | ship | OGDL 1.0 | 44 MB zip, 5,983 trials | monthly |
| TFDA trial indications with codes (177212, export 206) | ship (lookup, joined by indication text) | OGDL 1.0 | 0.4 MB zip, 19,234 rows, 4,234 indications | monthly |
| MHLW 薬価基準収載品目リスト (4 workbooks) | ship | PDL 1.0 (MHLW site terms) | 1.3 MB, 12,442 items | monthly |
| NHI 健保用藥品項查詢項目檔 (data.gov.tw 23715) | ship | OGDL 1.0 | 97 MB CSV, 45,224 codes | monthly |
| ICD-10-CM FY2027 (CDC NCHS) | ship | public domain | 2.2 MB zip, 74,861 codes | yearly (Oct 1) |
| Taiwan ICD-10-CM/PCS 2023 Chinese edition (NHIA) | ship (vendor passes the workbook: `--file`) | OGDL 1.0 | ~10 MB | per Taiwan edition |
| LOINC (Regenstrief) | ship (notice + version; account download: `--file`) | LOINC licence | ~80 MB zip | twice a year |
| UMIN-CTR daily snapshot | site-fetch (`site-load umin_ctr --file`) | UMIN-CTR terms: no commercial use, no redistribution, no download by software on the user's behalf | ~30 MB gz | daily |
| jRCT | site-fetch / pending | jRCT terms: bulk use needs the help desk's permission | - | - |
| WHO ICTRP | not usable | no commercial use | - | - |
| JAPIC-CTI, JMACCT | not usable (nothing separate) | merged into jRCT on 2023-03-06 | - | - |
| TFDA sites / drugs / ingredients (177215, 177216, 177218) | not usable | OGDL 1.0, but no column links a row to a trial; the sites file carries investigators' names; 177218's columns are shifted | 4.9 / 0.2 / 0.4 MB | monthly |

* **ClinicalTrials.gov: API v2 bulk zip, not AACT.** The zip holds one API v2 record per study, the shape the box
  already reads (live mode, `to_study`, the registry mirror), published by NLM itself; AACT is a CTTI relational
  derivative (40+ pipe files to join back into a record) with its own terms. The pack keeps every record unchanged.
  JP + TW subset for scale: about 9,961 + 13,118 studies (parallel licence review); the release ships all.
* **TFDA metadata is wrong in places.** 177198's file has no 執行狀態 column although the metadata lists one (status
  is empty in the pack). 177212 is titled ICD-9 but has no trial key, empty ICD-9 descriptions in 73 % of rows and
  about 1,800 ICD-10-shaped codes; it is kept as an indication-text lookup and joined to 177198 by 適應症中文. No TFDA device-trial dataset was found in the TFDA series on data.gov.tw
  (177180 to 177225 checked; the search API needs POST); device trials registered on ClinicalTrials.gov are in the
  CT.gov part.
* **MHLW**: the list gives the 12-character 薬価基準収載医薬品コード; a YJ code that differs from it still needs the
  licensed YJ file of D-137, which this complements and does not replace.

*Pack format* (`tb_common/refdata.py`, `trialbox-refdata/1`). A directory `trialbox-refdata-<YYYYMMDD>/` shipped as one
deterministic tar: `manifest.json` (format, pack_id, data_as_of, sample, and per source: id, name, kind ctgov | trial
| term, URL, download date, download sha256, record count, licence and licence URL, terms, attribution, refresh,
distribution, files with sha256, bytes and records), `NOTICE.md` generated from it, and one `jsonl.gz` per source
(deterministic gzip). `verify` checks every file's size, sha256 and record count; unsafe tar members are refused.
The box loads it into the schema `refdata` of the trial database (D-126), so the backup and the update's rollback
dump carry it: one transaction per pack replaces the rows of its own sources; a hospital's site-fetch part (UMIN)
lives beside it and survives vendor packs. Offline queries: `ctgov_search(condition, countries, status)` (condition
or keyword part, any case; whole-country match), `ctgov_study(nct_id)` (the full record), TFDA trials, terms by
system and code. Size of a release pack: about 2.2 GB (CT.gov ~2.2 GB; everything else 18 MB, measured); in Postgres the CT.gov
records take several GB (JSONB, TOAST-compressed) and grow the backup by the same.

*Wiring.*

* `TB_CTGOV_MODE=live | offline | cassette` (`criteria_compiler/ctgov.py`); offline reads the pack, cassette stays
  for CI and the demo. The request takes `nct_id` (contract `ctgov` 2.1.0, additive; `source` gains `refdata`); live
  asks `GET /studies/<NCT id>`. The client, compose and the egress rules default to offline; clinicaltrials.gov:443
  opens only with live.
* Update path: payload kind `refdata` (`update_manifest` 1.1.0, `tools/sign_bundle.py`); `apply_update` loads the
  pack after the rulesets (compose: `docker compose cp` + `python -m tb_common.refdata load` in criteria-compiler;
  the in-process box loads it directly); the local database dump rolls it back. A first install keeps it in
  `deploy/refdata/pending/` and `install.sh` loads it once the database runs.
* Admin page: a "Reference data" tile with the "data as of" date, each source and its records, and a link to
  `/admin/notice` ("Sources and licences"), all strings in en, ja and zh-TW.

*Install choice.* `install.sh --ctgov offline|live`; without it, a box that already has `TB_CTGOV_MODE` keeps it, a
new box asks the wizard's question (plain words, en / ja / zh-TW: "may this box reach clinicaltrials.gov on the
internet?"), default offline; `--yes` or no terminal takes offline. Choosing live probes clinicaltrials.gov once; no
answer -> offline with a message (no internet -> offline). `install.sh --ctgov-check` only reports whether this host
has internet. The settings wizard asks the same question (`ctgov_mode`, default offline; `TB_CTGOV_MODE` from
install skips it). The site's network sheet (written at install) states the chosen mode in three languages; the
committed sheet says offline is the default.

*Evidence.*

* `tests/unit/test_refdata.py` (15) and `tests/console/test_refdata_pages.py` (3): the manifest's fields and NOTICE,
  a changed file or a missing attribution refused, a deterministic and safe tar; the parsers on the committed excerpts;
  every source has a decision and a site-fetch source cannot be fetched; offline answers by condition, Japan, Taiwan,
  status and NCT id and returns the full record, as the cassette of the same studies does; a second pack replaces its
  sources and keeps the hospital's UMIN part; no pack -> a plain error; the default is offline; live and cassette look
  up one id; the update bundle loads the pack; the wizard and install default and their three languages; the network
  sheet per mode; the admin tile and the sources page, admin only.
* `e2e_simple` stage 14: the sample pack built, verified, loaded; with every outbound TCP connection refused, NCT
  id, gout + Japan, gout + Taiwan found, and the criteria drafted from the pack's record by the box's compiler.
* Suites: unit, console and testbench 1,412 passed, 2 skipped. `make lint` clean. `tools/e2e_simple.py`: PASSED in
  110 s. `tools.backup_drill`: PASSED in 117 s. `public_e2e --lang ja`: 112/112. The walk (`/admin/notice` added for
  the administrator, 403 for the coordinator): 786 checks, 0 failures over 774 pages, axe 0 serious; an earlier run
  lost two screenshots to the browser ("Unable to capture screenshot") and a second walk on the same server failed on
  the state the first one left (the walk needs a fresh `--serve`).
* Fetched and parsed here (`.cache/refdata`, not committed): CT.gov one API page (200 JP/TW studies, 10.9 MB) and the
  first 60 MB of the bulk zip (13,318 studies, re-zipped and built: the bulk parser); MHLW four workbooks (12,442
  items); NHI drug list (96.6 MB, 45,224 codes); ICD-10-CM FY2027 (74,861 codes); TFDA 205 (44.4 MB, 5,983 trials)
  and 206 (4,234 indications); 207, 208, 209 inspected only. Built into one pack (19.6 MB tar), loaded into a
  throwaway Postgres in about 2 s and queried (cancer + Japan / Taiwan, an NCT id, TFDA gout trials, terms).
* Hosts: data.fda.gov.tw cut large transfers off mid-way from here (export 205 at 15 to 42 MB, five tries with
  curl) before the fetcher's streamed download completed (44.4 MB); the fetcher retries and refuses a partial zip. www.nhi.gov.tw and loinc.org
  answered 403; jrct.niph.go.jp and rctportal.niph.go.jp did not connect; info.nhi.gov.tw dropped one connection and
  then worked.

*Not done.*

* The full CT.gov download was not run here (7 GB free disk; ~2.8 GB zip plus ~2.2 GB pack). The vendor runs
  `fetch ctgov` and `build` on a machine with ~15 GB free.
* NHI medical service codes (醫療服務給付項目): the data.gov.tw dataset id was not confirmed (search API
  needs POST); no fetcher yet. NHIA PAS IG NHI-to-LOINC map (CC0): a ship candidate, not built.
* The Taiwan ICD-10 workbook and UMIN CSV parsers read columns by header name and were tested on made-up samples; check
  them against the real files at first use. LOINC is parsed from `LoincTableCore.csv` (not verified on a release).
* jRCT waits for the help desk's answer. Offline search is substring matching (no synonyms as the live API's
  `query.cond` has); trials of the TFDA and UMIN parts are queryable by the store but not yet used by COHORT.
* Not run: Docker, a compose box's `apply_update` with a real refdata payload, `install.sh` beyond `--ctgov-check`.

**D-141 Step 9: the scenario matrix and the fail-safe cloud run.** TB-PLAN-04 step 9 (owner decision 2026-11-09;
builds on D-123, D-131, D-132, D-135, D-137, D-139, D-140), 2026-11-09. Built in a cloud container with no GPU and no
Docker; no cloud resource was started.

*Owner decisions (2026-11-09).*

1. The complete run uses 50,000 synthetic patients as the bulk scale test, and only synthetic and public data.
2. Every way a site gives TrialBox data is its own scenario, screened with the real judge and verifier pair: the
   hospital database feed, the EMR (SS-MIX2 and FHIR), the site's own lists, a single chart pasted, chart files
   (PDF, Word, scans), REDCap and the built-in forms, an IT dump with local codes, the offline registry.
3. The real public datasets already downloaded run too, one scenario each where the licence allows it.
4. The cloud run must survive a dead driver: the VM stops itself.

*The scenario matrix* (`tools/scenarios.py`, run as `complete_run part scenario --scenario <name>`; one section per
scenario in the report: input, counts, expected and got, model calls, model exclusions, time, a screenshot).

| Scenario | Input (card / laptop) | Independent recount |
| --- | --- | --- |
| db-csv | the `hospital:<lang>` parts: CGRD-style CSV, 50,000 / 5,000 | lake = generator counts; FEAS INC-01/02 from the CSVs; model exclusions vs the note truth |
| emr-ssmix2 | SS-MIX2 storage (ADT-52, OMP-02/11/12, extended storage, 疑い diagnoses, flagged lab values), 5,000 / 500 | FEAS = recount and = the CSV path's; JP Core `$validate` on 50 per type |
| emr-fhir | FHIR bulk export (NDJSON with chart numbers, names, phones), 5,000 / 500 | every resource read; same pseudonyms as the feed; FEAS = recount and = CSV |
| site-excel | an Excel list (title row, merged cells, era dates, full width, µmol/L, dd/mm dates), a Shift_JIS CSV and a Big5 CSV (民國), 1,000 / 100 rows over a 5,000 / 500 feed | each patient's state (SITE5B) from the generator's feed and list values |
| chart-paste | EMR screen text, ja and zh-TW, 200 / 20 patients with a second chart for a quarter | precision and recall against the charts' facts; states from the confirmed facts |
| chart-files | the same as Word, a PDF with a text layer, PNG scans and image-only PDFs, 60 / 12 | as chart-paste; OCR `tesseract` (jpn, chi_tra, eng) on the VM, `fake` here |
| redcap | `rc_sim` project 202 (longitudinal, DAGs) two-way; the built-in forms; 500 / 50 records | every record in REDCap; REDCap's consent dates back; ODM export count |
| it-dump | a Shift_JIS dump with five local diagnosis codes, a JLAC10 lab code, a YJ drug code, 2,000 / 200 | each patient's state before (unknown) and after mapping |
| registry | the reference data pack sample, no network | trials by condition and country = recount of the raw records |
| public-mimic | MIMIC-IV demo on FHIR (100 patients, ODbL) | patients = the release's; FEAS invariants; the cascade S0..S5 |
| public-medtxt | MedTxt-CR case reports (ja, CC BY 4.0), 148 / 16, pasted as charts | the corpus's own positive / negative / suspected tags |
| public-trec | TREC CT 2021/22 topics, qrels and trial texts, 100 / 10 pairs | the qrels (eligible 2, excluded 1) |
| gateway | a judge and a chart-reading call through the gateway built as an installed box | none: a probe, reported as a finding |

Not run, and why (`tools/scenarios.py` `NOT_RUN`): Chia and open_cohorts are not in `.cache` on this machine;
Synthea has no mapping in this build; the full reference data pack is a box's install step.

*Rules the scenarios keep.*

* A proposed fact never excludes before confirmation (D-135): checked on every chart scenario, before the
  coordinator acts, as "no exclusion and no failed criterion rests on a proposed fact".
* Model exclusions are counted per scenario and checked against the generator's note truth (`note_truth.json`):
  a model-driven exclusion (a note criterion failed, no coded one, not consent or scope) is true when the truth
  blocks on that criterion; false exclusions must be 0. Each excluded patient is listed with its reason. On the stub
  no note may exclude (D-115), so the card is where this counts.
* With `--model pair` every model call goes through the gateway built as an installed box builds it
  (`TB_ENV=PRODUCTION`, `TB_PROFILE=P-PRO6000`, no `TB_DATA_CLASS`); `--direct` bypasses it. On the VM nginx adds the
  key on 127.0.0.1:8080, so the routing file stays the installed box's.
* Known findings of the 2026-11-09 review are reported, not fixed, and do not fail the run: each has an id, what was
  expected, what was seen.
* Every DuckDB connection of a scenario may spill at most 2 GB to disk (a harness guard, after XL-02 filled the disk).

*The fail-safe cloud run* (`deploy/gcp/complete-run.sh`, `deploy/gcp/complete-run-vm.sh`, `deploy/gcp/gcloud-auth.sh`).
After the 2026-11-09 incident (the wrapper ran detached in a sandbox that killed it; its EXIT trap never ran; the
service-account auth in the private config failed after about an hour; the VM ran 61 minutes until stopped by hand):

1. **Cloud-side hard cap.** Before the start: `gcloud compute instances set-scheduling <vm> --zone <z>
   --max-run-duration=<N>h --instance-termination-action=STOP`, N = the estimate × 1.3 rounded up (`--hours`).
   Flags checked against `gcloud compute instances set-scheduling --help` (Cloud SDK 570.0.0, no authentication).
2. **The VM stops itself.** The startup script starts a systemd hard cap and a watchdog before anything else: poweroff
   when the heartbeat file is not touched for 20 minutes (the run touches it as its log grows; the driver over HTTP),
   when setup passes 60 minutes, or when the done marker has stood 30 minutes (at once after the driver collects).
3. **The workload runs on the VM** (48 vCPU), not on the driver. Chosen over "restartable parts on the driver"
   because the incident's failure was the driver itself: with the workload on the VM, a dead driver costs at most the
   time to the done marker plus 30 minutes, or 20 minutes of no progress, or the cap; the driver only uploads `git
   archive` of HEAD, polls with short calls, downloads `results.tgz`, and runs the stub parts (walk, backup, update,
   scale) after the VM has stopped. `--collect <run id>` picks a run up again. The parts are also restartable.
4. **Fresh auth for every gcloud call.** `gc` re-activates the service account from `TB_SA_KEY_FILE` when a call fails
   with an authentication error and retries once; `gc_probe` checks the credential before the start. The key file's
   content is never printed.
5. **Idempotent and resumable.** `complete_run --resume` keeps every part whose `parts/<tag>.json` has every check
   passed; a part writes to a temporary file and renames it. A restarted VM resumes.
6. **`--estimate`** prints hours and US$ per scenario: note-stage patients × 6.3 s (VALIDATION §3), a chart read as
   one, criterion checks at 0.3 s, the canary per box, and the part's stub time scaled from the local run.
7. Review A-12: `set -x` removed from `gpu-sim-startup.sh` and `gpu-fit-test.sh` (the key was on traced command lines).

A billing budget with a kill switch is the last net; it needs billing permissions the project's service account does
not have, so it stays an owner action.

*Evidence (local, stub, 2026-11-09).*

* `python -m tools.complete_run --patients 5000` with the matrix: **PASSED, 662 of 662 checks, 84 of 84 screenshots**,
  22 parts in about 34 minutes (`eval/complete_run/2026-11-09-matrix-stub-5000/report.md`). Per scenario: db-csv
  338/338 (both languages); emr-ssmix2 9/9 (500 patients, JP Core 615 sampled, 0 errors); emr-fhir 9/9; site-excel 7/7
  (100 of 100 patients as the generator says); chart-paste 8/8 and chart-files 9/9 (precision and recall 1.0 on the
  stub); redcap 8/8; it-dump 3/3; registry 2/2; public-mimic 5/5; public-medtxt 3/3; public-trec 1/1; gateway 1/1.
* Known findings the run reports, each with what was seen: A-01 (the installed box's gateway refuses a judge call,
  `step_unconfirmed`); GW-02 (`chart_facts` has no role in `libs/tb_llm/v1_roles.yaml`); P-04 (5 of 5 疑い-only
  patients excluded by GZQO-EXC-07); FHIR-01 (SCREEN scope 0 on the FHIR path: Practitioner references hashed, ids
  kept); XL-02 (SCREEN on `main` after a site list is published spills without bound; stopped at the 2 GB guard);
  B-03 (a longitudinal REDCap link with no event: REDCap refuses every record); MAP-01 (name suggestions 胃癌 and 乳癌 to
  C22.0, 本態性高血圧症 to E78.5); DUMP-01 (2 of 3 patients with an undated cancer row are "ready"). B-01 (flagged lab
  values) holds on these paths: "8.2 H" and ">8.2" read as unknown, not FALSE, in the SQL engine and at S1.
* `deploy/gcp/complete-run.sh --dry-run --patients 50000`: probe, `set-scheduling --max-run-duration=12h
  --instance-termination-action=STOP` before `start`, metadata with the watchdog's limits, upload, poll, collect.
* `--estimate --patients 50000`: about 8.9 h, US$24.3; hard cap 12 h, at most US$32.9.
* Unit tests: `tests/unit/test_scenario_matrix.py` (the generators' truth, the stub against the chart traps, the
  recounts, the estimate, resume, report-only, `gc` re-activating once and never printing the key, the driver's cap
  before the start, the VM script's nets and no `set -x`). The stub now also treats 家族史 as a family history.

*Not done; only the card can show.*

* With the pair the default path is the installed box's gateway; until A-01 and GW-02 are fixed every model call of
  the card run is refused there (the canary, SCREEN, chart reading). `--direct` runs the pair straight, as D-139 did.
* Model exclusions against the note truth, extraction precision and recall of the real model in ja and zh-TW, and
  tesseract on the rendered scans run only on the card. The floors (precision 0.90, recall 0.70) are this run's own.
* The VM script, the watchdog, the HTTP door and the bucket path have not run on a VM; the gcloud flags were checked
  against the SDK's help only. No billing budget (an owner action).
* MIMIC's cascade uses `tools.cascade_e2e`'s own model path (the stub), TREC the evaluation client: neither goes
  through the box. Chia, open_cohorts and Synthea are not run (`NOT_RUN` in `tools/scenarios.py`).

**D-142 Review wave 1a: screening and data blockers fixed.** Pre-release review of 2026-11-09 (reports 01, 02 and 06;
consolidated items R-01, R-37, R-38), 2026-11-09. One commit per item, each with a test that fails before the fix.
Built in a cloud container, no GPU, no Docker; synthetic data only.

* **PHI prompts on an installed box (A-01).** The compose gateway has no step confirmer, so every D3 call (the judge,
  the verifier, chart facts: `phi: true` prompts, labelled D3 when `TB_DATA_CLASS` is empty, as install leaves it) was
  refused. Decision: a box policy in `models/routing.yaml` (`phi_on_box`) instead of wiring the orchestrator's job
  check first. On an on-prem box (topology A) in PRODUCTION, with **no** step confirmer wired, a D3 call from the
  orchestrator or matching is allowed and sent to **perimeter endpoints only**; the audit record says
  `step_basis: box_policy`. The data never leaves the box, which is what LLM-2's step check protects in the other
  topologies. D4, topologies B (cloud tenant) and C (model egress), every other caller, and a box where a confirmer is
  wired still need a live, delegated step; `may_reach` keeps D3/D4 off every external route as before; the loader
  refuses any `phi_on_box` with a topology other than A or a class other than D3. `chart_facts` gets a gateway role
  (`abstract_field`, it had none). Found on the way and fixed: `install.sh` wrote the compose profile (`gpu`) into
  `TB_LLM_MODE`, which every service's config refuses; it now writes `vllm`. A pair profile now names its verifier
  (`TB_GATEWAY_VERIFIER_MODEL=v-verifier`), else `both_agree` ran single-model.
* **Pins that PRODUCTION routes (R-01).** No committed build has a sha256, and a pin made by hand without
  `--status champion` does not route in PRODUCTION. `tools/pin_model.py --install <gpu>` pins the GPU profile's
  deployed pair from the site's own weights in `deploy/models` (the served names compose gives vLLM, status
  `champion`: the profile's measured release, D-112); `install.sh` runs it before `--verify-all`. Builds already
  pinned are kept; missing weights are reported and that model routes nothing. `test_gateway_box_phi.py` builds the
  gateway and the orchestrator's clients from `.env.example`, the lines install appends and the compose
  `environment:` blocks, pins as install does, and runs a judge, a verifier and a chart-facts call through the real
  gateway app; external, B, C, D4 and unlisted callers are refused.
* **Lab text (B-01).** One reader, `tb_common.labvalue`, for the mapping (CSV, CGRD, SS-MIX2 OBX-5) and the lake
  (FHIR `valueString`): "75 H" is 75; "<0.3", ">1000", "0.3未満", "100以上" are censored (`Quantity.comparator`, lake
  column `observation.value_cmp`). A censored value decides a comparison only when every value on that side of the
  bound does (the bound counts as reachable, so a borderline case stays unknown, never wrong). Text that is no number
  ("検出せず", "陰性") is NULL. The SQL quantifiers `any`, `none`, `all`, `count>=` and `latest` are unknown, not FALSE,
  when an unreadable row could change the answer; the CQL generator says the same for null values. Approved SQL of the
  committed rulesets is unchanged (they use `latest`, already NULL on text).
* **Patients without a base row (B-02).** A scoped patient the compiled SQL's `base` drops goes to review: reason
  `not_in_snapshot` when the snapshot does not hold the patient, `check_dates` (new, en / ja / zh-TW) when it holds
  them deceased or born after the screening date. The scope query reads the cascade's pinned snapshot. The run's
  `opted_out` count no longer includes them (`not_at_index` counts them).
* **疑い diagnoses (review 02, P-04, S10).** Verified against the SS-MIX2 標準化ストレージ仕様書 v1.2h, 表 3-47 (PRB, from
  JAHIS 病名情報データ交換規約 3.1C): PRB-13 is the 疑い病名フラグ, JHSD 表 0005, code `1` 疑いあり (code table v1.2i,
  表 95). The reader sets `suspected` from PRB-13, or from a 病名 whose text carries 疑い when a vendor sends no flag;
  the shared mapping (every TW, CSV, CGRD and JP mapping extends it) writes `Condition.verificationStatus =
  provisional`. The lake keeps provisional, differential and unconfirmed diagnoses (from any FHIR source too) out of
  `condition` and lists them in `site_fact` with basis `suspected`; D-135's rule then makes any answer they could
  change unknown, reason `suspected_diagnosis` (en / ja / zh-TW), in the SQL engine and the cascade. Refuted and
  entered-in-error diagnoses are dropped. Other inputs: FHIR carries the same `verificationStatus` (handled); a CSV or
  CGRD site can fill the canonical column `suspected`; Taiwan's CGRD and NHI exports have no such flag.
* **REDCap longitudinal projects (B-03).** With no event set, the rows of one record (one per event or repeat
  instance) are one row: a field takes its non-blank cell, a blank in another event is never a value, and a field with
  different values on two events is refused and listed ("set the REDCap event"), not guessed.
* **A lost database connection (A-02).** Decision: reopen, not `psycopg_pool`. Each store keeps one serialised
  connection (the stores rely on it), and the pool package is not in the images. `Database.transaction()` reopens a
  connection psycopg reports closed or broken, and retries `BEGIN` once on a fresh connection when the server dropped
  it (nothing of the transaction ran, so reads and writes alike are safe). A failure inside a transaction is raised,
  never repeated; the next call works. Advisory-lock `migrate` and `tb_prefix` are unchanged. `Database.ping()` backs
  the console's `/healthz` (503 when the store is gone), the mail gateway's and the model gateway's (trace store); the
  orchestrator's already reads its job store. Tests kill a backend and restart a throwaway cluster.
* **Excerpts (A-06, R-37).** A note over half the excerpt budget is cut to that half (its evidence sentences first,
  whole sentences of the note); a note that does not fit is skipped and the search goes on, so one long newest note no
  longer hides the older evidence.
* **S3/S4 throughput and the call budget (A-07, R-38).** The cascade runs patients' model calls `llm_concurrency` at
  a time (each patient's criteria still in order, CAS-3; the budget reserved under a lock; answers equal to the
  one-by-one run). SCREEN takes it from `TB_SCREEN_LLM_CONCURRENCY`, which the GPU compose files set to the judge's
  `--max-num-seqs`. SCREEN's call budget is explicit: job option `max_pairs`, else `TB_SCREEN_MAX_PAIRS`, else 20,000
  (was a silent 2,000). When it runs out, the summary says how many patients were not fully read (en / ja / zh-TW),
  and the report JSON and the audit carry the count; those patients are listed for review, never excluded.
* **Tests changed because they encoded the bug.** `test_gateway.py`: the D3-without-step refusals now run under
  topology B (the box policy applies to A only).

* **Evidence.** Suites: unit, console and testbench 1,460 passed. `make lint` clean (doclint clean).
  `tools/e2e_simple.py`: PASSED in 165 s. `tools.backup_drill`: PASSED in 128 s.

*Not done.*

* LLM-2 proper (the orchestrator confirms the job step, `X-TB-Step`) for topologies B and C; `trialbox doctor` does not
  yet fail when the gateway would refuse the judge.
* The SS-MIX2 reader still takes ICD-10 from PRB-3's alternate coding only; the spec's example carries it in PRB-10
  (`<ICD-10>^^I10^<診断種別>^...^JHSD0004`). PRB-14 is read as `R`/`resolved` only (HL7 0241 / JHSD0006 not mapped).
* The CQL side does not read censored values (`TB_Common.cql`'s `ObsValue` ignores the comparator); CQL runs only in
  the compile-time gate on fixtures, which have none. An "unreadable value" reason code (SQL NULL from text shows as a
  data gap) and the "Excluded by records" page of P-04 are not built. A lake snapshot built before this step has no
  `value_cmp` column: a ruleset compiled after the upgrade needs a rebuilt snapshot (the nightly rebuild makes one).
* With concurrency, which patients a budget that runs out leaves unread depends on timing (it is counted and shown).
* Not run here: Docker, `install.sh` on a box, a GPU pair. Other agents share this machine's Postgres.

*Scenario-run fixes (D-141's matrix on this wave, 2026-11-09).* The matrix now checks A-01, GW-02, P-04 and B-03 as
passed (the gateway probe pins the pair as `install.sh` does; B-03 also needed the push side: with no event set, each
field goes to the event its form is designated for). Four new findings fixed, each with a test that failed before:
XL-02, one `patient` row per pseudonym (a published site list duplicated every patient, and each criterion's join
on `base` multiplied that to 2^(criteria + 1) rows), and the lake's spill capped (`TB_LAKE_MAX_TEMP`,
`TB_LAKE_TEMP_DIR`, a `LAKE-LIMIT` error instead of a full disk); FHIR-01, the bulk import keeps a Practitioner's
staff id in its id and in every reference; MAP-01, a diagnosis name is matched whole (known names in ja, zh-TW and
en, then the ICD-10 title) with a confidence, never by a shared character, and nothing is suggested when unsure;
DUMP-01, an undated record leaves a criterion unknown where the dated ones do not settle it, so the patient needs
information (SQL and CQL; every input path reaches the lake that way). Committed rulesets' SQL is not recompiled
here (as for B-01): a ruleset compiled after this step carries the rule.

**D-143 Review wave 1b: console, safety and PI access (owner decision).** Pre-release review of 2026-11-09 (report
06, end to end: P-01 to P-04, P-07, P-08, P-10; report 03, security: S-09), and the owner's decision of the same
day: "PI can see everything, including chart number, patient information; they are the ones with full
authorization."

* **The study's PI may see and reveal identifiers (reverses D-133's "investigators may not reveal").**
  `User.can_reveal` is administrator, coordinator and investigator; `User.sees_ids(study)` adds the study scope, so an
  investigator of another study has no authority. The PI reveals on the patient page, the SCREEN job page and through
  `POST /api/v1/studies/{rs}/patients/{pid}/reveal` (a reason is required, as on the page); the screening-log export
  with chart numbers follows `sees_ids` too (it was any requester, unscoped). Kept: every reveal or view is audited
  (`console.reveal_patient`, `console.reveal`, `console.view_id`), the orchestrator's 60-per-hour cap applies, and a
  view on the console counts against the same cap. Viewer and CRO (sponsor, monitor) accounts stay masked everywhere.
* **P-01.** The CASE job page's "web request" row showed `mrn=…` to every role. It shows the chart number only to an
  account with identifier authority for the job's study, as one audited view under the cap (over the cap:
  `console.view_id_refused`, masked); everyone else sees `mrn=•••`. Audit tables (job page and `/audit`) mask
  identifiers for everyone. `public_e2e` stage 7b signs in as viewer and as CRA, opens every page the walk opens plus
  the job pages, and fails on any chart number or name of the site; it also checks that the study's PI sees the CASE
  request's chart number and that the view is audited.
* **Mail (N1): a point for the owner to confirm.** Decision: N1, the PI's own mail, carries **no** chart number. Mail
  leaves TrialBox (hospital mail servers, phones, forwarding); the PI sees the chart number on the page after sign-in,
  where it is audited and capped. N1 and N2 keep the pseudonym and the screening number (D-136).
* **P-02 / P-03, SAE.** A serious AE needs the investigator's acknowledgement, whatever its outcome (a fatal SAE,
  outcome 5, counted as "not ongoing" and left the banner and N1 the moment it was saved). One tap on the banner, the
  participant page or `POST /api/v1/studies/{rs}/aes/{record}/{event}/ack`; stored in the data core's `ae_ack` (schema
  version 3: who and when; the first acknowledgement stands) and audited (`life.sae_ack` with the time and the outcome,
  `console.sae_ack`). The coordinator sees "Waiting for the investigator's acknowledgement". N1 goes out on any working
  day while an SAE waits. The AE form gains the day the site learned of it (`ae_aware`) and the report dates for
  sponsor, IRB and regulator (`ae_rep_sponsor`, `ae_rep_irb`, `ae_rep_reg`, shown when serious). Each serious AE shows
  its reporting clock on the participant page and the AE form; an overdue report is on the PI's and the CRC's home
  pages and first in N2 (pseudonym, party and due day, never the AE term). Defaults, in days from the day the site
  learned of it (else the onset), as fatal or life-threatening / other serious, chosen by the site's zone (Asia/Tokyo is
  Japan) or `TB_SAE_RULES=jp|tw`, and overridden with `TB_SAE_REPORT_DAYS` (`sponsor=1,irb=7/15,regulator=0`; 0 turns
  a party off):

  | Report to | Japan (J-GCP art. 48; PMDA for investigator-initiated trials) | Taiwan (GCP; IRB SOPs; TFDA) |
  | --- | --- | --- |
  | Sponsor | 1 / 1 (直ちに) | 1 / 1 (at once) |
  | IRB and the head of the institution | 1 / 1 (直ちに, through the head) | 7 / 15 |
  | Regulator | 7 / 15 | 7 / 15 |

  **These defaults need site confirmation** before the first patient: the IRB's SOP, the protocol and, for a sponsor
  trial, the sponsor's SAE timelines decide; the regulator's report is usually the sponsor's duty (set it to 0 where the
  site does not file).
* **P-04.** Each SCREEN run stores `excluded_<study>_v<version>.json` with the job (tag phi, never mailed): every
  excluded patient, the failing criterion with its evidence, and the source: the coded records, a confirmed fact (a
  record whose id is a confirmed `site_fact`, D-135) or the notes with both models agreeing; a patient excluded by the
  run's own rules (scope, research-contact consent) shows that rule in plain words. `/studies/{rs}/excluded` (PI, CRC,
  administrator; 403 for viewer and CRO) shows them 25 to a page with a filter by source; "This is wrong, send to
  review" is stored (site store `excluded_review`, schema version 2), listed first with who and when, and audited
  (`console.excluded_review`). Linked from the week page and the study card; in the walk and in `public_e2e`.
* **S-09.** The console signs the user it names to the orchestrator: `X-TB-Actor-Assertion` is
  `v1.<expiry>.<session>.<hmac>`, HMAC-SHA256 over the actor, the console session (16 characters of the session
  token's hash, bound per request) and an expiry two minutes ahead, keyed with `HMAC(console token,
  "tb-actor-assertion/1")`, derived from D-138's per-service token, never the token itself. The orchestrator verifies it
  for reveal, export, notices and cancel: with one shared token both sides derive the key; with per-service tokens
  `trialbox secrets init` and `rotate` write the derived key to `deploy/secrets/services/actor/keys` (0600 in a 0700
  folder), which only the orchestrator mounts (`TB_ACTOR_KEYS_FILE`); a console rotation keeps the old key valid until
  the console runs on its new token. An unsigned or expired name is 403 and audited (`actor.refused`); no name is 400,
  as before. The reveal cap and the new export cap count per calling service and verified person.
  `GET /registry/{rs}/export.xlsx` now needs a verified user, is audited at the orchestrator (`registry.export`: actor,
  session, sha256 of the file) and is capped (`TB_EXPORT_MAX_PER_HOUR`, 10). A box updated past this decision runs
  `trialbox secrets init` once (RUNBOOK §5).
* **P-07.** The REDCap read text said "Nothing is ever written to REDCap" under the write-back switch. It now says
  TrialBox writes only when write-back is on, and then only its own three screening fields, never a field the study
  team owns (en, ja, zh-TW).
* **P-08.** The screening log's zh-TW "enrolled" is the glossary's 已收案 (was 已納入); the glossary test bans 已納入
  and checks that the screening log and the lifecycle pages use one word for enrolled.
* **P-10.** Disable account, Keep TrialBox's / Take the source's value, Detach REDCap and Approve all first show one
  confirmation sheet with the consequence in a sentence; Yes posts the form again with `confirm=yes`. Role and study
  checks come first. `/api/v1` calls are explicit and unchanged.

*Evidence.* `tests/console/test_console_app.py` (the CASE request row by role, the view cap, the PI's reveal on the job
page, the signed export), `tests/console/test_role_pages.py` (the PI's reveal on the page and through `/api/v1`, the
viewer's 403), `tests/console/test_step2.py` (N1 never carries a chart number), `tests/unit/test_service_auth.py` and
`tests/unit/test_service_secrets.py` (an unsigned, forged, expired or renamed actor refused; the per-person caps; the
export audited and capped; the key file, its rotation and its one mount), `tests/console/test_sae_pages.py` (the JP/TW
rules and the override; a fatal SAE stays until the PI acknowledges, on the pages, in N1 and N2, through `/api/v1`),
`tests/console/test_excluded_page.py` (the page, sources, send to review, roles, Japanese; the run's excluded list),
`tests/console/test_step4b.py` (P-07, P-08 and the new strings in three languages), `tests/console/test_data_pages.py`
(confirmations). Suites: unit, console and testbench 1,438 passed. `make lint` clean. `tools/e2e_simple.py`: PASSED in
166 s. `public_e2e --lang ja`: 117/117 (stage 7b: viewer and CRA on 50 pages each, no chart number or name).
The walk (`node tools/public_walk.js` against a fresh `public_e2e --serve` on port 8957, random password never printed):
810 checks, 0 failures over 798 pages (the excluded page for PI and CRC, 403 for viewer and CRA), axe 0 serious (84
minor), 22,650 targets, 0 under 44 px, taps T1 to T9 within target.

*Open.* Death does not move the participant to an end state, and an SAE is not linked to withdrawal; the reporting
clock is one setting per box, not per study; a patient sent back from the excluded list does not enter the PI's
weekly list by itself (the study team sees it on the page); the SS-MIX2 疑い flag (P-04's second half) is read by
D-142 (wave 1a, integrated on this branch); "approached" still has two words per language (連絡済み / 声かけ済み, 已聯絡 / 已邀請); the rate limits are per
process and in memory, not in Postgres; no Undo after a confirmed conflict decision; the owner confirms the N1
decision and the site confirms the SAE defaults.

**D-144 Owner decisions of 2026-11-09 on patient data, profile, roles, site operations, consortium and regulation (entered verbatim from the decisions record).** Owner, 2026-11-09; recorded here because the master plan (TB-PLAN-05) is under GAMP document control and its binding inputs must carry a sequence number (independent plan review PR-34). The source is `docs/reviews/2026-11-09-owner-decisions-data-and-profile.md`; this entry copies its decisions. Where a later entry changes one, the later entry says so.

* **Scope and roles.** A full clinical repository now, used first for trials; the later Anamnesis layers on the same base. Structured facts for every patient in the hospital feed; written profiles for the departments that take part. **All history now.** Data steward: named hospital staff at each site; Aimedics never holds patient data. The steward may read all free-text notes at any time; every view audited. PI sees everything for their own studies' patients, chart numbers included (D-143). Treating physicians (clinician role) have access from the start; "own patients" = seen or ordered for in the last 24 months or booked in the next 90 days; each site's privacy office can add the inpatients of the physician's ward. Profile access: steward all; PI own studies; CRC own study; clinician own patients; every view audited and kept 10 years. Monitors: SDV on enrolled subjects only, cited record items. Break-glass: a reason and a second person on the steward/admin rota confirms; time-limited and audited.
* **Whole-hospital screening, sub-PIs, referral.** A study screens the entire database. Sub-PI rights come by delegation (an ICH E6-style delegation log with ticked tasks: screen and see candidates, mark Approach, request referrals, enter data); only the PI approves criteria and signs off; every action records who did it. Candidate view: the PI and delegated sub-PIs see everything needed to decide about any candidate the screen finds anywhere in the hospital; each view logged with study and purpose and rate-limited. Referral: the treating physician is asked first through TrialBox (console and mail) and answers agree / decline with a reason / discuss; the PI contacts the patient only after agreement; each step logged and counted. The treating physician may be unknown to TrialBox: (1) a named attending is only suggested and the PI confirms or changes; (2) else the PI picks from a steward-maintained staff directory or types a name; (3) "arranged outside TrialBox" with the outcome recorded afterwards; (4) the steward's department contact list as the last fallback; a referral never stalls on a missing field.
* **Site operations.** At the first site the CRC records the treating doctor's answer; mail with answer buttons and doctor accounts come later. IRB approval and ICF version before Approach: a warning, not a hard gate; each override logged. Delegation log: the trial office's signed log stays the record; TrialBox holds a copy that grants rights, with training dates; compared monthly. Opt-out kept by the office and recorded in TrialBox; the patient removed from screening, profiles, vectors and future exports; the removal logged. EDC: prefill, then the CRC confirms; REDCap through its API; other EDCs through CDISC ODM import, or by file or a copy-assist screen; no screen-scraping or RPA; items mapped to CDASH; TrialBox is part of the trial-data chain and needs GAMP 5 validation, a full audit trail and ER/ES / Part 11-style controls. Randomisation not in TrialBox. Drug accountability, TMF, site invoicing: inputs only (dispensing dates on the timeline, a dated indexed ISF bundle, an invoice-ready activity report per study and month). Patient messaging: a printed reminder card and a calendar file now; later opt-in reminders through the hospital's own SMS or LINE.
* **Data model.** OMOP CDM v5.4 in Postgres is the store of record; FHIR (JP Core, TW Core) for exchange only; screening runs on a lake exported from OMOP with the same table names, counts identical. pgvector in the same Postgres. All subspecialties in one generic model; items mapped through the clinical item catalogue (LOINC, OMOP, OHDSI Phenotype Library, CDISC QRS, NIH CDE); first templates rheumatology, neurology, oncology, nephrology/general internal medicine. PI spreadsheets trusted as coded with the source shown; a sheet-vs-feed disagreement is a conflict and the item is unknown until the steward (whole database) or the PI (own study) picks a value; an unresolved conflict never excludes. Local code maps by the steward, a specialty PI confirms the important ones. SNOMED CT: ask about a licence; Aimedics holds it for the product, the consortium lead if the consortium buys its own; get a quote now; until then ICD-10-CM plus the WHO ICD-10 bridge. Consortium: counts and de-identified profiles may leave under IRB approval and a data-sharing agreement; export defaults project pseudonyms, dates shifted ±180 days, k = 5, no quotes, no vectors; a contract may only tighten; counts travel as signed files; the shared code-map registry is hosted at CGMH and shipped by Aimedics.
* **Profile.** A wiki page per patient written by the model, every sentence cited and verified; physician annotations beside it; a machine-readable twin (JSON) and pgvector. v1 layers: cited record, timeline, phenotype, eligibility, personal lab setpoints, gap finder, similar patients. SaMD and clinicians (revised the same day): restricted until a written regulatory view exists; clinicians see the setpoint and gap layers only inside a study-referral context, as numbers without a disease name, behind a switch off by default, until a written PMDA/MHLW 該当性 view and a TFDA view exist; PIs and stewards see them labelled research use; forecasts stay out. A signed structured annotation counts as confirmed data; free text is read as a note; neither excludes silently; every exclusion listed on the "excluded and why" page (renamed "criteria not matched" by TB-PLAN-05 v1.2). Narrative written by the judge model at night in the site's language, English on request; nobody edits; the model abstains under 95 % cited sentences. Facts and the twin update within minutes; the narrative nightly or on request. First build: study patients first, nights only. Gap rules: approved by a PI of the specialty; live after at least 7 of 10 sample hits confirmed; model-proposed rules only after a prompt-injection and false-positive suite passes. Patients like me: structured catalogue items first, note embeddings re-rank, every match explained. Embeddings: bge-m3 default; Qwen3-Embedding-0.6B tested on ja/zh-TW data; all note types across the history; vectors in backups. One paid GPU test (about US$15–30) measures the profile cost before the build at scale.
* **Hardware and order (morning).** First hospital box: 2 TB disk and 128 GB RAM, confirmed per site (changed by D-145). Order: Wave 1 and gate G1 first; OMOP, catalogue and profile in parallel, merging only after Wave 1.
* **Accepted as recommended** (standalone review §6): profile versions kept 10 years; an open conflict blocks "ready"; setpoints as numbers with a "check" mark, never alerts; counts transport as a signed file; the first export reviewed by the exporter's privacy office and the lead site; consortium registry work starts now.
* **Regulatory and commercial.** Light IEC 62304-shaped records for the profile module from now on. Business model: hospitals sign a platform licence; sponsors pay a per-study activation fee; no fees per enrolled patient. Evidence: draft the Study A protocol now (retrospective accuracy at CGMH, precision ≥ 0.75, wrong exclusion ≤ 2 %, opt-out/waiver route); no marketing claims before Study A.

**D-145 Owner decisions of 2026-11-09 on the master plan and the pilot: frame, sites, hardware, hosting, contacts, and the answers to the independent plan review (entered verbatim).** Owner, 2026-11-09 (three sittings). Source: `docs/reviews/2026-11-09-owner-decisions-data-and-profile.md`, sections "Master plan and pilot", "Hardware, interim hosting and contacts" and "After the independent plan review". TB-PLAN-05 v1.2 (`docs/plan/25-master-plan.md`) is the plan these decisions produce.

* **Frame.** "Both, linked": a product roadmap where every item traces to its regulatory record (requirement, risk, test; IEC 62304, ISO 14971, GAMP 5). Both pilot sites: CGMH (Taiwan) and Makoto's site (Japan). Claude agents build; Changfu and Makoto review and decide. Pilot scope "as complete as possible": screening, sub-PI delegation and referral, the OMOP core, study-patient profiles and REDCap EDC prefill. "Build all, use all": GAMP 5 validation of EDC prefill inside the pilot so prefill is live at go-live. Data feeds not known yet: the plan starts with a site survey. GPU budget approved; several GPUs may be used; the G1 run split across parallel capped VMs with the profile cost test and the bge-m3 vs Qwen3 embedding test (about US$50). Building continues while the plan is written.
* **Hardware, hosting, contacts (second sitting).** CGMH hosts TrialBox on its own B200 server, shared with other work; no appliance box for CGMH; TrialBox runs in containers on CGMH's platform with a fixed GPU quota and its own install checks. One box for Makoto's site; keep the current model pair; size the box so a larger model can be added later. Before the hardware is ready: the hospital's private cloud with GPU, where the site has one approved for patient data. Changfu and Makoto find the IT, privacy-office and data-feed contacts; Aimedics drafts the site survey and the hospital IT security pack in ja and zh-TW. Wave 1c (job permission by role, viewer/CRO data leaks, PDF upload, screening scope, PI criteria ticks) fixed before the G1 run. Both pilot sites have IRB approval; the site survey confirms coverage of whole-hospital screening and patient profiles. CGMH first, then Japan. All recommendations of TB-PLAN-05 §13 accepted (Q-05 to Q-27).
* **After the independent plan review (third sitting).** Full scope, later date: one go-live per site with everything in, CGMH about 2027-04-30, Japan about 2027-05-14; this replaces the February dates. Real patient data during the build: pseudonymised samples only, after the DPA is signed and where the IRB allows it; real data never goes into the repository, CI, logs, screenshots or review documents (the data-handling rule, `docs/plan/sites/data-handling-rule.md`). IRB amendments filed at both sites by 2026-11-20, covering profiles, vectors, cross-department identified views and the clinician role; Aimedics drafts them in ja and zh-TW. CGMH steward: Changfu for the pilot, with an independent CGMH second reviewer who co-signs validation and release records. B200 qualification: rent a cloud B200 in weeks 3 to 5 to qualify the model pair (about US$40–80, each VM capped and stopped); ask CGMH for a dedicated MIG partition, not a time-share. Review hours: about 14 hours a week each for Changfu and Makoto, plus the part-time safety-core engineer. Sponsor acknowledgement: EDC prefill is switched on per study only after the sponsor acknowledges in writing that TrialBox is in its source-data chain. Japan hardware: buy one DGX Spark now and benchmark it (model pair, 5k/50k screening, profile writer) before choosing between a Spark with a CPU-only workstation and an RTX PRO 6000 box; if the Spark is not enough, it becomes the development and demo machine.
* **Evidence.** TB-PLAN-05 v1.2 §14 answers each of the 40 findings of `docs/reviews/2026-11-09-master-plan-independent-review.md`; `tools/gen_traceability.py` derives the traceability matrix and the totals from the plan's tables (`tests/unit/test_gen_traceability.py`).

**D-146 Review wave 1c: the user journeys' high-risk findings (owner decisions).** User-journey review of 2026-11-09
(`docs/reviews/2026-11-09-user-journeys-e2e.md`: J-01 to J-05, J-07, J-08, J-16, J-17, J-18, J-22, J-26, J-27), and the
owner's decisions of the same day: a study must be able to screen the **whole hospital**, and **only the PI approves
criteria**. Builds on D-104, D-108, D-120 and D-143 (S-09's signed actor). The sub-investigator delegation and
referral work is on another branch and is not here; the role changes below are kept to `tb_common.authz`,
`console.app._scope_check` and the approval page.

* **J-01, a request is allowed by the person's role, not by a mailbox.** The console sends the signed-in person and
  role with `POST /jobs` (`X-TB-Actor`, `X-TB-Actor-Role`; the S-09 assertion now covers the role, so a changed role
  does not verify). The orchestrator then authorises by `tb_common.authz.ROLE_COMMANDS`: administrator and coordinator
  start FEAS, SCREEN, COHORT, NAV, MICROBATCH, CASE, CONSENT, RELEASE, STATUS, CANCEL and FEEDBACK; the investigator
  APPROVE and STATUS; viewer and CRO nothing. A mailed request (no person named) keeps the `settings.yaml` mailbox
  rules. The mailbox stays the reply address; the `job.state` audit names the person and role. A refusal is a page in
  the user's language (role, mailbox, or limit), never the orchestrator's JSON.
* **J-02, the daily limit counts heavy runs only.** `rate_limit_per_sender_per_day` (default 20) now applies to each
  heavy type on its own (FEAS, SCREEN, COHORT, NAV, MICROBATCH, CALIBRATION); CASE, CONSENT, STATUS, APPROVE and the
  others are not counted. `rate_limits_per_day: {TYPE: n}` overrides per type (0 = no limit). Reached, the console
  answers 429 with "Today's limit is reached" in en, ja and zh-TW. The mail gateway's own per-mail limit is unchanged.
* **J-03 to J-05, one role rule for pages and `/api/v1`.** An aggregate-only account (viewer, CRO; D-104) is refused,
  in one place (`console.app._aggregate_denied`, called from the page sign-in and from the API's bearer sign-in): every
  `/studies/{rs}/…` page and `/api/v1/studies/{rs}/…` route but the study's feasibility report, the runs list, every
  job page but a feasibility run's (the CASE job page printed a chart number line), the registry, the audit trail, the
  site set-up and `/api/v1/site/…`, and the REDCap connections (`/admin/redcap` is the administrator's only; the
  viewer read it). The patients and screening-log APIs check the page's `can_view_phi` too. The menus no longer offer
  those pages to a viewer. The D-143 masking is unchanged: viewer and CRO are masked everywhere.
* **J-07.** A PDF's text layer with NUL bytes (CJK fonts without a usable ToUnicode map) crashed the fact store
  (`psycopg.DataError`) and the console said "try again later". Chart text of every format, and every string the model
  writes back, is stripped of NUL, the other C0 controls but tab and line breaks, DEL and lone surrogates
  (`sitesetup.charts.clean`).
* **J-08.** `GET /setup/templates/codes` was read as the codes of a workspace named "templates" (a list; the console's
  download was a 500). The template route is declared before the `/setup/{ws}/…` routes.
* **J-26, Who to screen.** The study's set-up page has a "Who to screen" card (coordinator): **the whole hospital**
  (every patient with a booked appointment in the window or a visit in the last 12 months, whoever the doctor) or only
  some doctors' patients. Stored in S-28 (`study.screen_scope`, migration 3; `GET/PUT /studies/{rs}/screen-scope`,
  audited `study.screen_scope`). A SCREEN uses, in order: the request's `pract=` (or `scope=hospital`), the set-up
  page's choice, the ruleset's `scopes.screen`; with none it fails with "choose … under 'Who to screen' on the study's
  set-up page". The run's mail and JSON say "the whole hospital" (`whole_hospital`).
* **J-27, only the PI ticks and approves.** The per-criterion tick is the investigator's (was the coordinator's); the
  page says who does what in three languages. The coordinator (and the PI) give the site's labels.
* **Quick fixes.** J-17: the site pages show the account name, not `console:crc` (a `who` filter). J-22 / the draft
  in English: the approval page shows the site's label above the protocol's words, which are marked as written
  (`data-authored`, "as written in the protocol"); the feasibility funnel uses the site's label over the run's English
  one. J-18: the username `pattern` is valid under the `v` flag (`[a-z0-9._\-]+`); a test checks every pattern. J-16:
  `GET /api/v1/site/readiness` without `study=` answers 400 `study-required` (with the account's studies) when the
  account has more than one.

*Evidence.* `tests/unit/test_journey_rules.py` (role versus mailbox, the signed role, the heavy-only limit, NUL in a
chart and a PDF, the whole-hospital scope on a real lake, the S-28 scope API and its order),
`tests/console/test_journey_pages.py` (the person and role sent, the three refusals in three languages, every GET
route walked as viewer and CRO, the study team's pages kept, the codes template, the account name, the readiness API,
Who to screen, the strings, the site label, every `pattern`), and the updated `test_console_app.py` and
`test_data_pages.py` (the PI ticks, the viewer's 403s). Each new test fails on f9481a2 (34 failed) and passes here.
Also: `tests/conftest.py` restores `TB_SERVICE_TOKEN` after each test (the demo box set it for the process, and 5
HTTP-surface tests failed after `test_list_demo` in `make test`, also on f9481a2), and `test_list_demo` follows D-143
(N1/N2 carry the screening number). Checks: `make lint` clean; `make test` 1,640 passed, 2 skipped;
`tools/e2e_simple.py` PASSED in 111 s; backup drill PASSED in 117 s; `public_e2e --lang ja` 120/120; the walk
(`node tools/public_walk.js` on a fresh `public_e2e --serve`, random password never printed): 900 checks, 0 failures
over 888 pages (viewer and CRA 403 on the CASE job, registry, audit, runs, set-up, sources and REDCap pages), axe 0
serious (84 minor), 23,913 targets, 0 under 44 px, taps T1 to T9 within target.

*Open.* The mail gateway still limits mail per sender (all commands, 20 a day); a console account without its own
mailbox uses the administrator's address, so their limits are shared; the investigator does not refresh feasibility
(J-22's second half); the site set-up pages are per site, not per study (J-06); no screen yet for the IT work (J-09) or
the data steward (J-10).

**D-147 Sub-investigators by delegation, the whole-hospital candidate view and the referral to the treating doctor.**
Owner decisions of 2026-11-09 (`docs/reviews/2026-11-09-owner-decisions-data-and-profile.md`, "Whole-hospital
screening, sub-investigators and referral" and "Site operations"), with the clinical-operations assessment
(`docs/reviews/2026-11-09-holistic-01-clinical-operations.md` §2 rows 4–8, §3, §5 P0). Built 2026-11-09, no GPU, no
Docker.

*What the owner decided, and how it is built.*

1. **Rights by delegation.** The PI keeps the study's delegation log (`/studies/{rs}/team`): each person, role (PI,
   sub-investigator, CRC, other), the tasks the PI ticks (`screen` = see candidates, `approach` = mark Approach,
   `refer` = ask a treating doctor, `enter_data`), first and last day, GCP training date and certificate. It is the
   box's copy of the trial office's signed log, which stays the record; a monthly comparison is recorded on the page
   (match / differs), and the CRC's home and the week page remind when it is more than 30 days old. The rights are rows
   of D-146's role table (`libs/tb_common/authz.py`: `STUDY_TASKS`, `ROLE_STUDY_TASKS`, `study_tasks`); one function
   (`services/console/team.py` `standing`) reads the study's log into it for the pages and `/api/v1`: the logged PI
   has every task; a sub-investigator only the ticked ones, on the days the entry runs; an investigator not on a log that names
   a PI is refused (403) on the week list, the patient page and the candidates. Only the logged PI approves criteria
   (S20) and keeps the log. **Until a study's log names a PI, every investigator of the study acts as its PI**
   (screen, approach, refer: the behaviour before D-147), so a study without a log keeps working. Coordinators and
   administrators keep their role's rights; an investigator with the `enter_data` tick may also enter trial values
   (adding forms stays the coordinator's). Every change and every action carries its actor (rows and audit:
   `console.delegation`, `console.pi_mark`, `console.referral`, ...).
2. **Candidates across the hospital** (`/studies/{rs}/candidates`): every candidate of the study's latest screening
   run, whoever the treating doctor is, with the doctor as a *suggestion* from the data or "unknown", the referral
   state and the mark. Whose patients the run looked at comes from D-146's "Who to screen": the page says whether it
   was the whole hospital or some doctors' patients, and links the choice on the study's set-up. A candidate's page opens only with a purpose (decide fit, ask the doctor, prepare contact,
   other); each view is audited (`console.candidate_view`: study, pseudonym, purpose) and counted in the `team`
   schema, and limited per person (`TB_CANDIDATE_VIEWS_PER_HOUR`, default 60; over it, 429 and
   `console.rate_limited`). It shows the identifiers, why the patient fits or not, the cited record (the patient
   page's criteria table, now `_criteria.html`), the referral and its trail. **The chart number** goes through
   D-143's reveal and nothing else: the candidate page calls the patient page's `apply_reveal` (identifier authority
   `User.sees_ids`, a reason from the D-143 list, `console.reveal_patient` on the console and the orchestrator's audit,
   the orchestrator's per-person cap), adding only `via: candidates` and the view's purpose to the record; there is no
   second reveal route on `/api/v1` (`POST /api/v1/studies/{rs}/patients/{pid}/reveal` is the one). D-147 narrows
   D-143 by the delegation log: once a study's log names a PI, an investigator reveals, on the patient page, the
   candidate page and `/api/v1` alike, only as that PI or as a sub-investigator ticked `screen`. CRO and viewer
   accounts get 403 on every page and route.
3. **Referral; the treating doctor may be unknown.** From the candidate page the PI or a sub-investigator with
   `refer` sends a request: confirm the doctor the data names (TrialBox only suggests), pick from the steward's staff
   directory (`/site/staff`), type a name, choose "arranged outside TrialBox", or the department contact (the
   default when the data names nobody). **No field is required**: a request without a name is stored with the doctor
   unknown and the CRC finds them. The route, what the data suggested and what was chosen are kept. The patient gets
   a screening number at the request. At the first sites **the CRC records the doctor's answer** on the referrals
   page (agree to introduce / decline with a reason / discuss; by phone, in person, EMR message), so the doctor
   needs no account; for "arranged outside TrialBox" the PI or sub-investigator may record it too. The open
   referrals are on the CRC's home and in the N2 digest. **The PI contacts the patient only after agreement**: while
   the latest referral is open or declined, Approach is refused (409 `approach.wait_referral`) on the page and the
   API; a declined patient may be asked about again with a new request. The screening log (page, XLSX, `/api/v1`)
   carries each referral's route and outcome (`referral_route`, `referral_outcome`, reason, dates).
4. **IRB approval and the current consent-form version** (`/studies/{rs}/irb`: approval number, approved on, valid
   until, consent-form version and its date). Missing or expired is **a warning, not a gate**: it is shown beside the
   Approach button, and an Approach marked under it is recorded as an override (`approach_overrides` table,
   `console.approach_override` audit event, the IRB page and an `approach_irb_override` column in the screening log).
   An expired approval also expires the consent form approved under it. The clinical-operations review advised a hard
   gate (its Q6); the owner chose the warning.
5. **Opt-out register** (`/site/opt-outs`, `libs/tb_common/optout.py`, schema `optout`), kept by the research office
   or the steward (coordinator and administrator accounts, as the site set-up, until the steward role exists). A
   chart number typed there becomes the box's pseudonym through the orchestrator (`POST /setup/pseudonym`) and is
   never stored; the register is an event log (opt-out, taken back). An opted-out patient is removed from **screening**
   (the SCREEN and MICROBATCH scope, `screen.opt_out_removed` with the count), from **every candidate list and page**
   (week list, patient and candidate pages, referrals, cohort list, N1/N2, `/api/v1`) and from **later exports** (the
   screening log XLSX, the registry export). The register is read as it stood when a job was received, so a re-run
   of an old job stays byte-identical (D-82). Each registration is audited (`console.opt_out`); lists show only the
   count removed, never who.

*Stores.* `team` (delegation log and its history and comparisons, staff directory, department contacts, referrals
and their events, IRB records, Approach overrides, candidate views) and `optout`, each its own schema of the trial
database with versioned migrations (D-126); both are in the backup.

*Evidence.* `tests/console/test_team_pages.py` (13): the stores; the register's as-of reading; a sub-investigator
without the Approach tick refused and allowed once ticked, an investigator not on the log refused everywhere, the
sub-investigator unable to change their own ticks; only the logged PI approves; CRO and viewer masked on pages and
the API; the purpose before any patient-level content, the view audited with the purpose; D-143's reveal on the candidate
page (a reason required, `via` and purpose recorded) and on the patient page for the PI; the delegated sub-PI
revealing on the patient page and the investigator not on the log refused there and on `/api/v1`; the view limit
(429) and the orchestrator's cap reached from the candidate page (409, no chart number); an unknown doctor (department contact by default, a typed
empty name, the directory instead of the suggestion, "outside" answered by the PI through the API), Approach refused
until agreement and after a decline, the screening log's route and outcome; the IRB warning not a gate, each
override recorded, an expired approval warning again; the opt-out removing the patient from the list, the pages, the
log, its XLSX and the API, and back after it is taken back; the orchestrator's scope dropping the patient, and not
for a job received before the opt-out; every page in three languages. `e2e_simple` stage 15 (15 checks): the PI and
a sub-investigator on the log, the sub-investigator seeing every candidate and revealing a real chart number through
D-143's reveal with a reason and the purpose, Approach refused without the tick, an "outside TrialBox" referral numbered, the PI's Approach waiting, the
CRC's agreement, the override recorded, the XLSX route and outcome, the CRO and viewer refused, an opt-out entered
by chart number registered under the pseudonym, gone from the lists, and left out of the next SCREEN run with its
audit event. `tools/complete_run.py` maps stage 15 to the candidates page; the browser walk opens the new pages for
the PI and the CRC and expects 403 for the viewer and the CRO. Runs here: `make lint` clean; `e2e_simple` PASSED (184 checks, stage 15: 15); `tools.backup_drill` PASSED;
`public_e2e --lang ja` 120/120; the walk 1,002 checks, 0 failures, axe 0 serious, no target under 44 px. `make test`
in file order (`-p no:randomly`): 1,681 passed, 1 failed: `tests/unit/test_no_direct_model_calls.py` flags model API calls in
D-148's `tools/bench_profile.py` and `tests/unit/test_gpu_prep.py`, files this entry does not touch. With `pytest-randomly`, which is in this machine's shared
virtual environment but not in `pyproject.toml`, the order changes on each run and up to six integration tests fail:
`tests/integration/test_twpas_inproc.py`, `test_cohort_inproc.py` and `test_screen_inproc.py` share a module-scoped
box and need their tests in file order. The same tests fail on the base commit alone under that plugin.

*Not done.* FEAS counts do not read the opt-out register (the feed's consent
table still applies there), and the data core's own exports (ODM, REDCap CSV of consented participants) are not
filtered by it. The doctor's own console page and the mail with answer buttons are later (owner decision). No
steward role yet: the coordinator and the administrator keep the staff directory and the register.

**D-148 The next GPU runs: the complete run on several VMs, the embedding comparison and the profile cost stand-in.**
Owner's approval of 2026-11-09 (three runs, about US$50 in all, several GPUs allowed), 2026-11-09. Code and dry runs
only: built in a cloud container with no GPU; no VM was started or made and no gcloud call that changes anything was
run.

*Parallel complete run* (`deploy/gcp/complete-run.sh --vms N`, `tools/complete_run.py` `shard_plan`). The run is split
into N shards of whole parts (`complete_run --only` tags), longest part first onto the least-loaded VM. Chosen over a
split by patient range: each hospital part reads the whole 50,000-patient hospital (FEAS counts, SCREEN, the re-run's
byte identity), so a range split would change what is measured; a split by parts keeps every part as on one VM and
the merged report is the single-VM report. `prepare` goes with every shard that has a hospital part (same seed, same
hospital), `install` with the first. Each VM keeps D-141's nets unchanged: its own cap (its estimate × 1.3, rounded
up, set before its start), key, watchdog and heartbeat, its own run directory; the driver runs one child per VM (the
D-141 code path), waits, merges `parts/` and the screenshots, runs the stub parts once and writes one report.
`--collect` collects every VM of a run from its `plan.json`. VM 1 is `tb-gpu-sim`; VMs 2..N are clones
(`--provision`: a machine image, then `instances create` with SPOT, STOP, a 30-minute cap and a startup script that
powers off at once, because create starts the VM). Zones come from `--zones` (one per region where the GPU quota is
1 per region); the default list after `asia-east1-a` is candidates only, and the dry run prints the owner's read-only
zone and quota checks. `--estimate --vms N --parts ...` prints hours and US$ per VM and in all; the longest part
(`db-csv`, 2.14 h on the card) bounds the wall time, so four VMs reach about 2.8 h.

*Embedding comparison* (`tools/bench_embed.py`, part `embed`). bge-m3 (CLS pooling) against Qwen3-Embedding-0.6B
(last-token pooling, an instruction on queries), fp16, 1024 dimensions, in the vLLM image already on the card (its
torch and transformers run on the RTX PRO 6000). Corpus: every ja and zh-TW note of a 4,000-patient synthetic
hospital (about 6,400). Labelled queries per language: the generator's planted needles (relevant: every note with the
needle's sentence) and two paraphrased questions per note finding (relevant: every note with that finding; each
criterion's two values are a negation trap). Measured: docs/s and tokens/s, GPU memory (weights and peak, torch),
needle MRR@10 and recall@10, finding nDCG@10 and P@10, per language; halfvec size 2 × 1024 + 8 = 2,056 bytes a vector
(about 1.9 GiB per million, column value only).

*Profile cost stand-in* (`tools/bench_profile.py`, part `profile`). The judge writes a 4-8 sentence summary of one
synthetic patient from that patient's facts (diagnoses, latest labs, medicines, vitals, procedures, reports, the
three latest notes with their planted PHI masked), each sentence citing fact ids, through the installed box's
gateway (role `abstract_field`, D3); if the gateway refuses, the reason is recorded and the bench calls the judge
directly so the cost is still measured. 400 patients: 16 one at a time, the rest at 16 in parallel (the card's batch).
Reported: tokens in and out, seconds per patient, GPU-hours per 1,000, citation validity, and the extrapolation to
50,000 nightly, to the study patients (the generator's study archetypes, an upper bound) and to the note-stage
patients (S3, 92 of 5,000).

*Estimate* (`--estimate --patients 50000 --vms 4 --parts g1,embed,profile`): 10.95 VM-hours, US$30.00, wall about
2.8 h; each VM capped at 4 h, so at most US$43.84. The bench times are set high until the card measures them
(embeddings 0.25 h, profiles 400 s + 2 s a patient).

*Evidence.* `tests/unit/test_gpu_prep.py` (every part on exactly one VM for N = 1..4, the hospital parts after their
`prepare`, install on VM 1, the per-VM caps; the labelled set; retrieval metrics on known vectors; the hash-stub bench;
facts without identity; the stub profile run and its extrapolation; the gateway path and its fallback; the driver's
dry run for three VMs: each VM capped before its own start, its own `tb-only`, no VM made by a run; `--provision`).
`make lint` clean; `tools/e2e_simple.py` PASSED; `complete-run.sh --dry-run` and `--estimate` for N = 1, 2, 3, 4.

*Not done; only the card can show.* No bench number is measured yet. The clones, other zones and the quota are the
owner's to check; the G4 zones in the default list are not verified here.

**D-149 The data-flow lifecycle review's P0 fixes: deletes on delta nights, validation before `CURRENT`, one vector
store, lake schema version and sidecar hashes, the export ledger v1, derived-score units and the JSN eGFR, zstd
backups.**
Source: `docs/reviews/2026-11-09-dataflow-lifecycle-review.md` §9 P0 and §4, with the owner's answers of 2026-11-09
(D-144, D-145; the review's questions 1, 2, 4, 5 and 10 accepted as recommended: eGFR is JSN 2009 in Japan and
CKD-EPI 2021 in Taiwan and a protocol may name either; a lab unit missing on a row is the declared default per analyte
for a hospital feed and unknown for sheets and charts; embeddings in one store, not in snapshots; CPU zstd, no GPU
compression). Workstreams of TB-PLAN-05 (`docs/plan/25-master-plan.md`): WS-03.7, WS-08.1, WS-05.3, WS-03.1, WS-08.3,
WS-04.3 with WS-01.2, WS-08.6. Built in the cloud container on synthetic data; `deploy/gcp/` and
`tools/complete_run.py` are untouched.

1. *Deletes on delta nights* (P0-1, WS-03.7). `adapter/ndjson.write_snapshot` takes tombstones (type -> ids deleted
   at the source) and drops them from the merged snapshot; a record sent again in the same run wins. The ids dropped
   are written to `tombstones.json` beside the snapshot (absent when none, so a night without deletes is
   byte-identical), counted in `IngestReport.tombstoned` (schema 1.3.0) and in the audit. Sources: a `deleted` column
   on any CSV or SQL table (or the table's `deleted:` column; `1`, `true`, `y`, `d`, `deleted` count), which also keeps
   such a row out of a full run; SS-MIX2 records whose newest file has flag `0` (`Ssmix2Source.deleted_rows`, read and
   mapped like a live record to find its id; extended-storage documents the same); FHIR Bulk `deleted` Bundles
   (`DELETE Type/id` entries beside the export or under `deleted/`; a Bundle is never read as a resource). The id is
   computed exactly as for the record (`Mapper.tombstones`, `pipeline.bulk_id`). A Patient is never tombstoned by a
   feed delta: removing a person is the opt-out path's job (P0-4, not in this entry). fhir-store follows because its
   ledger already deletes what left the snapshot.
2. *Validation before `CURRENT` moves* (P0-2, WS-08.1). The night now runs NDJSON, then the sample validation and JP
   Core check, then fhir-store and the lake. Any error before loading (a mapping error, the 0.5 % limit, JP Core, a
   validator that did not run) *holds* the night: fhir-store and the lake are not loaded, `CURRENT` keeps the
   previous snapshot, `IngestReport.held` is true and the audit event is `ingest.held` (the console's Sources page
   reads it with `ingest.done` / `ingest.failed`). The held night's NDJSON stays for the steward; the next delta night
   merges over it, so no change of the source is lost. `Lake.rebuild` builds into `.building`, writes the sidecars,
   renames, and only then writes `CURRENT` atomically (`Lake.promote`); `promote=False` builds without serving.
3. *One vector store* (P0-6, WS-05.3; owner question 4 answer (b)). `document_chunk` keeps text, tokens and a new
   `sha` column; the vectors live only in `embed_cache.duckdb` (keyed by sha and model, as before). `Lake.search`
   reads the patient's chunk shas from the snapshot and their vectors from the store, ranks by cosine in NumPy with the
   SQL's order and tie-break, and fuses with BM25 as before. The store is opened per read or write under one process
   lock (DuckDB refuses a read-only and a read-write connection side by side) and waits up to 30 s for another
   process's write lock; the rebuild no longer holds all vectors in memory. A snapshot of schema 1 (vectors inside) is
   still searched with its own column. Saving: 4 KiB a chunk per kept snapshot (1,024 float32), the review's ~18 GB
   times 39 snapshots at 50,000 patients. The store is in the lake folder, so it is in every backup (owner: vectors
   in backups). pgvector (`note_chunk`) remains WS-05.3's P1 step.
4. *Lake schema version and sidecar hashes* (P0-7, WS-03.1). `lake_meta` gains `schema_version` (2),
   `schema_sha` (a hash of every table's columns and types and the chunk table), `embed_store` and `embed_model`.
   `Lake.connect` checks the version on every open and refuses a snapshot without `lake_meta` or outside 1..2 with
   `LAKE-SCHEMA: ... Rebuild it` / `... Finish the update`, instead of a missing-column error later. Every Parquet file
   and the DuckDB file get a `<file>.sha256` sidecar (`sha256sum` format); `Lake.verify(snapshot)` lists any file that
   does not match. Retention removes the sidecars with their snapshot.
5. *Export ledger v1* (P0-8, WS-08.3). `tb_common/flowledger.py`: every file that leaves the box is a `flow.export`
   event in the hash-chained audit with channel, file name, bytes, sha256, identifier level (`aggregate`,
   `pseudonymised`, `identified`), the approval it left under, recipients, actor, ruleset and job. An export without an
   approval reference or with an unknown level is refused before it leaves. Recorded today: every job output
   (`Ctx.publish`: a `phi` file is `identified`; approval = the ruleset version and the job's requester), the console's
   aggregate downloads, sponsor packs and D1 cascade files, the screening-log export with chart numbers, the data
   core's ODM/CSV/XLSX exports and every REDCap sync that pushed values (hashed over its summary). `python -m
   tools.trialbox exports [--days 30] [--json]` lists what left and to whom. The P1 `dataops.flow` table and page are
   fed from these events.
6. *Derived scores* (P0-5, WS-04.3 and WS-01.2). `tb_common/derived.py`:
   - **Units.** Each component is converted to the formula's unit with UCUM factors (`UNITS`: CRP `mg/dL` x 10 =
     `mg/L`, `ug/mL` = `mg/L`; creatinine `umol/L` / 88.4 = `mg/dL`; ESR `mm/h`; weight `g`, `[lb_av]`; height `m`,
     `mm`, `[in_i]`); counts and scores accept no unit or a UCUM annotation, the patient global `mm`. Any other unit,
     or a lab row with no unit (a sheet or chart value), gives no value and `derived_unit:<component>`. The hospital
     feed's declared unit per analyte is the mapping's lab lookup (as before) and, new, `unit_defaults` (LOINC ->
     UCUM) in the site mapping for a feed result that arrives without one, including FHIR Bulk
     (`pipeline.apply_unit_defaults`, tagged `urn:trialbox:unit-source|site-default`, counted in the audit). The CRP
     term no longer assumes mg/L whatever the row says.
   - **Same visit.** DAS28 takes its components from one visit: the newest TJC28 in the window, then SJC28 and the
     patient global on the same day and the ESR or CRP within 7 days of it (catalogue `das28_*.yaml` windows); BASDAI
     and ASDAS the same way (`SAME_VISIT`). An ESR at the visit is used when it exists; its unit must fit and an ESR
     of 0 is no value (the catalogue's zero rule), never a fall back to the CRP.
   - **JSN 2009 eGFR.** `egfr_jsn` (194 x Cr^-1.094 x age^-0.287, x 0.739 female) beside `egfr_ckd_epi`; both in the
     criterion IR (schema 1.1.0), the LLM extract schema, the SQL and CQL generators (`TB_Common.EGFRJSN`, per-unit
     `Conv_<component>`, `SameVisit`) and the v3 calculators (`egfr_jsn_2009@1.0.0`, `egfr_ckd_epi_2021@1.1.0`). A
     criterion that says only "eGFR" is compiled to `egfr_jsn` at a Japanese site (time zone or locale) and stays
     `egfr` (CKD-EPI 2021, as approved before) elsewhere (`CompilerDeps.egfr`, `postprocess(egfr=...)`); a protocol
     that names its equation keeps it, and the stored IR names it, so the approval covers the choice.
   - **No value with a reason, never FALSE** (D-130). The SQL template writes `derived_missing_input:<c>` or
     `derived_unit:<c>` as the atom's evidence when it has no value; the SQL engine and the cascade turn it into the
     reasons `derived_missing_input` / `derived_unit` (new `Reason` codes with en, ja and zh-TW words) and keep the
     patient (an unknown exclusion passes, an unknown inclusion is "needs information"). Before, the components' record
     ids were the evidence, which the cascade read as "a code outside the list".
   - **Worked examples** (`tests/unit/test_derived_scores.py`), in Python and in the compiled SQL on a small lake:
     CKD-EPI 2021 59.3 (F 55, Cr 1.1) and 69.2 (M 60, Cr 1.2), the same woman in µmol/L; JSN 63.1 (M 50, Cr 1.0,
     catalogue), 59.9 (M 60, Cr 1.0) and 40.9 (F 55, Cr 1.1: "eGFR >= 45" passes by CKD-EPI and fails by JSN);
     DAS28-ESR 4.26; DAS28-CRP 3.99 with CRP 10 mg/L and with 1.0 mg/dL (3.37 before the fix); CDAI 14.5, 27 and 1.5;
     SDAI 31 and 1.2; BMI 22.9 (height in metres); age at index 65 (born 1960-11-10, index 2026-11-09). CDAI and SDAI
     are Python reference functions only; their engine rows come with WS-04.3's stored derived rows.
   - The draft-document DAS28 (`orchestrator/scenarios/facts.py`) uses the same engine (`derived.compute`).
7. *Backups* (P0-3 codec part, WS-08.6; owner question 10 answer (a)). The tar inside a `.tbbak` is zstd level 3 on
   every core (`zstandard`, `threads=-1`, added to `pyproject.toml` and `deploy/requirements.lock`), then encrypted as
   before. The authenticated header says `"compression": "zstd"`; a backup without the key is gzip, so every backup
   made before D-149 verifies and restores unchanged (tested with a backup written in the old format). The layout
   changes, hashes from the stream, the schedule and the age alert of WS-08.6 are not in this entry.

*Evidence.* `tests/unit/test_dataflow_lake_p0.py` (tombstones in `write_snapshot`, a deleted CSV row on a delta
night is gone from NDJSON and lake, a deleted row never enters a full run, FHIR Bulk deleted Bundles, SS-MIX2 flag
0, a night over the validation limit leaves `CURRENT` and the lake untouched with `ingest.held`, no vectors in the
snapshot and search equal to brute force, a schema-1 snapshot still searched, an unknown schema refused, sidecars
catch a changed file); `tests/unit/test_export_ledger.py`; `tests/unit/test_derived_scores.py`; two new tests in
`tests/unit/test_backup.py`. Each of these fails on `origin/master` f4c56d0 and passes here. The ATOMS CQL and SQL
snapshots are regenerated for the unit, visit and reason columns; the CQL (with `TB_Common`) translates with the
cql-to-elm jars. `make lint` clean; `make test` 1,720 passed, 2 skipped; `tools/e2e_simple.py` PASSED; the backup
drill PASSED (its backup now zstd); `public_e2e --lang ja` 120/120.

*Not done here.* The opt-out worker (P0-4) and the rest of the backup row (layout, stream hashes, schedule, age
alert) are separate P0 items. Stored derived rows with provenance, `tb_score_definition` from
`catalogue/scores/*.yaml`, CDAI/SDAI in the engines and derived-vs-documented conflicts are WS-04.3 (P1). The
shipped mappings declare no `unit_defaults` yet: each site declares them in its survey (its lab lookup already
carries a unit per analyte). The R-31 check of a row's own unit against the lookup's (WS-01.2) is still open for
feed rows mapped through a lookup.

**D-150 The cloud run made reliable, and its local rehearsal as the gate before any paid launch.** Independent review
of the cloud GPU run (2026-11-09, 25 findings, after the four failed runs of that day), 2026-11-09. Built in a cloud
container with no GPU; no VM was started and no gcloud command was run. On top of `gw404` (the served-name fix, C-01).

*Why.* Every failure of 2026-11-09 lived where nothing had run before the paid VM: the VM script was tested by text
greps, the driver by a dry run that never executes the VM script, and the local stub accepts any model name. The
review's prototype ran the unchanged VM script in an Ubuntu 24.04 container against strict stand-ins and reproduced
run 4's 404 for nothing. That is now permanent (`tests/rehearsal`, `make rehearse`) and the gate before any paid
launch (RUNBOOK §11).

*The VM* (`deploy/gcp/complete-run-vm.sh`). A run directory per run id (`/var/lib/tb/runs/<id>`; other runs' state,
the old log and the old `results.tgz` are removed at boot; H-01, M-01). A pre-flight (docker with the NVIDIA runtime,
nvidia-smi, both weight folders, 50 GB free; M-08). Both model servers must be healthy, list exactly their served
name, answer one chat call through the run's own path and refuse a call without the key before `PRO6000-RUN-READY`;
else `TB-SERVING-FAILED` with their logs in `results.tgz` (H-02). The watchdog limits each phase (serving and setup 45
minutes, the code 35) instead of one hour from boot (M-04); docker is waited for, the door restarts on failure and is
checked through nginx with the key, an empty key powers off (M-05). The driver puts the archive's sha256 in the
metadata and the VM refuses anything else; `tar --no-same-owner` (M-06, the hardening part; HTTP stays). `git` is
installed (M-08); Chromium must launch (L-05). `results.tgz` is re-packed after every part, atomically (M-10). A
results-only boot (`tb-collect-only=1`: door and nginx, no models, no run) hands a stopped VM's results over (H-04,
L-03). Every failure ends with a marker line, a `results.tgz` that says why, and the done marker.

*The data git does not carry* (`tools/fetch_run_data.py`; C-02, C-03). The hospital parts crashed because the box
reads FHIRHelpers from `quick-5.4.0.jar`; the in-process box's translator is a fake, so no JRE and none of
`fetch_jvm_deps.sh`'s 770 MB are needed: the one jar (4.8 MB, Maven Central, sha256-pinned) replaces `gw404`'s maven
step (M-11). Its Maven path is `org/cqframework`; `hosted-demo-startup.sh` had `info/cqframework`, a 404, fixed.
MedTxt (1.4 MB) and TREC CT (topics, qrels, CT.gov fields, and the sampled trials streamed from NCBI's 275 MB corpus
without keeping it) are fetched for the parts that need them, once per disk. A part whose data is missing fails at
once with "data missing" and never builds a box, so it uses no card time (`complete_run.data_missing`).

*The run* (`tools/complete_run.py`). Each part's result records its run id, HEAD and host; `--resume` keeps a part
only when both match and removes the rest (H-01). While a part runs, the run touches the heartbeat whenever the
part's processes used CPU in the last 30 s: a silent 50,000-patient SCREEN stays alive with no driver, a stuck part
does not (H-03). The report takes HEAD, host and run id from the parts (the VM's, not the driver's at collect time);
the stub parts run at the run's `--patients` with OCR tesseract (M-02); a crashed or data-less part is named in the
headline with the number of its checks that never ran (from `--planned-from`, a full run's report; M-03); `profile`
has a check "the gateway answered" that fails on the direct fallback, with a finding (M-03); the path says "synthetic
weight pins" when the pins are of synthetic files (M-09). The driver's children used to ignore `--patients` (every
VM generated 50,000); they now read it from the plan.

*The driver* (`deploy/gcp/complete-run.sh`). `--no-wait`, then a short `--collect <run id>` as often as wanted: one
look, the results so far, the report so far; a stopped VM with uncollected results is started once results-only
(20-minute cloud cap); `--follow` keeps the old polling, `--detach` runs the driver under setsid/nohup (H-04). Before
any start or `--provision` the GPU quota (`GPUS_ALL_REGIONS`, the region's RTX PRO 6000 quota, PREEMPTIBLE when it has
a limit, else regular) and the CPU quota are read, and a too-small quota is refused before any machine image or VM is
made (H-05, L-04). `--only TAG,TAG` bounds a run: estimate, cap and plan hold only those parts.

*The rehearsal* (`tests/rehearsal/rehearse.sh`, `make rehearse`). The real driver at HEAD and the real VM script,
unchanged, in an Ubuntu 24.04 container (a private dockerd when none answers): fakes only for gcloud, the metadata
server, systemd, docker and nvidia-smi; vLLM stand-ins that check the key and answer 404 to any but the served name;
real nginx, apt, PyPI, Node.js, Playwright and data hosts. One disk, booted again and again: `run-a` (fresh disk,
bounded run at 500 patients), `run-b` (same disk, new run), and the negative cases `served`, `no-upload`, `hang`,
`busy`; `check.py` holds the pass criteria. Model quality is not rehearsed: the canary, the checks that need a passed
canary and TREC's verdicts may fail on the deterministic stub, by name; nothing else may.

*Evidence.* `make rehearse` on `8890532` (the code of this entry; later commits change only this entry's number and
text): **REHEARSAL PASSED**, all six cases, 94 of 94 criteria, 33 minutes, the private dockerd and its mounts removed
afterwards. `run-a`: setup on a fresh disk in about 4 minutes; `TB-DATA` cql, medtxt and trec ready (TREC in about one
minute); every part reported, none crashed: 326 of 331 checks, the 5 failing ones the canary and the checks that need
it and TREC's verdicts (the stub's answers); judge 868 and verifier 452 calls answered, **0 × 404, 0 × 401** besides the
pre-flight's own no-key refusal; the report's HEAD = the launched commit, "synthetic weight pins"; power-off one minute
after the driver collected. `run-b`: nothing kept, one boot in the log, the report's HEAD right. Negative cases, each
failing as it should: `served` stopped before any part with "TB-SERVING-FAILED: judge serves 'local/not-the-judge',
the run asks for 'local/gemma-4-26b-a4b-nvfp4'", the servers' logs in `results.tgz`; `no-upload`: TB-NO-CODE, power-off
after the grace; `hang`: "TB-WATCHDOG no heartbeat for 2 minutes in the run (a stuck part)", then `--collect` started
the stopped VM results-only and got the log; `busy`: a 5-minute silent part with a 2-minute idle limit finished
(PASS), power-off only after the grace, collected results-only. The rehearsal found three defects before they cost
money: the run exited 127 when started with a `${X:+VAR=v}` prefix; a VM stopped during its first part had no
`results.tgz`; and `--collect` restarted a VM with nothing to hand over at every call. Unit tests:
`tests/unit/test_cloud_run.py` (20), with `test_complete_run`, `test_gpu_prep`, `test_scenario_matrix`,
`test_served_names`, `test_no_direct_model_calls` green. `make lint` clean; `tools/e2e_simple.py` PASSED;
`complete-run.sh --dry-run` and `--estimate` (full plan 8.87 h, US$24.29, cap 12 h).

*Not done.* HTTPS or the bucket path for the door (M-06's transport part, M-07): the key still crosses plain HTTP and
the bucket path is not rehearsed. Real weight pins on the VM (M-09 is labelled instead). L-01, L-02 (the judge name
from config, the silent pin rename). The serving-record capture is not rehearsed (it needs `docker inspect`), so
`install` is not among the rehearsal's parts. The project's quota allows one GPU: `--vms N > 1` is refused until it
is raised.

**D-151 The OMOP CDM v5.4 core, first slice: the `omop` schema, the loader, the lake exported from OMOP behind
`TB_LAKE_SOURCE`, the equivalence test and DQD-style checks.** Owner decisions of 2026-11-09 (D-144, "Data model":
OMOP v5.4 in Postgres is the store of record, FHIR for exchange only, screening on a lake exported from OMOP with the
same table names so the counts stay identical, pgvector in the same Postgres, local concepts ≥ 2,000,000,000,
conflicts recorded and unknown never excludes); TB-PLAN-05 WS-03.4 and WS-03.5, first slice; the design
(`docs/reviews/2026-11-09-design-patient-data-and-roles.md` §2.2 to §2.6 and §5 step 4) and the two reviews of the
same day (standalone database review §2.3 to §2.5; data-flow review §2.1 and §2.2). Built 2026-11-09, no GPU, no
Docker.

* **Where.** Schema `omop` of the trial database (`TB_OMOP_DB_URL`, else `TB_DB_URL`; `tb_prefix` honoured), so it
  is in every backup with the other stores and pgvector can sit beside it. The box's lake (`TB_LAKE_DIR`) has
  `omop`; any other lake folder (a practice site's own space, a test, a tool run) has its own `omop_<hash>`, so two
  lakes never share a store of record. The plan's WS-03.4 says `cdm`; the brief for this slice says `omop`, and the
  code follows the brief (one constant, `omop.schema.SCHEMA`).
* **The DDL is the official one, pinned.** The four PostgreSQL files of OHDSI/CommonDataModel tag v5.4.2
  (`inst/ddl/5.4/postgresql/`, Apache-2.0) are copied unchanged into `services/omop/ddl/` with their sha256 in
  `pin.json`; a changed file is refused. Migration 1 is their CREATE TABLE, primary-key and index statements for
  PERSON, OBSERVATION_PERIOD, VISIT_OCCURRENCE, CONDITION_OCCURRENCE, DRUG_EXPOSURE, PROCEDURE_OCCURRENCE,
  MEASUREMENT, OBSERVATION, DEATH, NOTE, FACT_RELATIONSHIP, CARE_SITE and PROVIDER (the two a visit names),
  CDM_SOURCE and the ten vocabulary tables. The foreign-key file is not applied (the OHDSI ETL guidance allows it):
  the loader writes concept ids it does not own until the Athena bundle is loaded, and the keys are checked as data by
  DQD's `isForeignKey`, generated from that same file.
* **Extension tables, apart from the standard ones** (migration 2, prefix `tb_`). `tb_record`: one row per source
  record (kind, resource type, source id, part); the OMOP row it became; the **record status** (coded, proposed,
  confirmed, signed, derived, rejected, superseded, tombstoned) and the basis tag; **provenance** (source batch, file
  and row, first and last batch, content sha); `extra`, the FHIR fields OMOP v5.4 has no column for, named by the lake
  column they restore. `tb_record_event`: append-only (insert, update with the before-image, tombstone, restore,
  status change with actor and reason). `tb_conflict`: open, resolved or withdrawn, with the claims and their
  sources and the resolution's value, reason, authority and person. `tb_id_map`, `tb_load`, and the three lake tables
  OMOP has no table for (`tb_appointment`, `tb_claim`, `tb_consent`; design Appendix A). Status changes follow one
  state machine (`omop.schema.TRANSITIONS`); a person's change survives an unchanged re-load.
* **The loader** (`omop.load.load_batch`). One batch is one source kind's complete set: `feed` (a snapshot's NDJSON)
  or `site` (the site's published inputs). Field values come from the lake's own flattener, so the two lakes cannot
  read FHIR differently. Pseudonyms only: `person_source_value` is the pseudonym and `person_id` an integer minted
  once; no chart number reaches OMOP. Codes are kept verbatim in `*_source_value` (ICD-10, LOINC, ATC; the hospital's
  NHI code when there is no ATC) with a **local source concept** minted once per code system and code in the site
  block (`TB_OMOP_CONCEPT_BLOCK`, default 2,100,000,000; refused below 2,000,000,000), in one TrialBox vocabulary per
  code system whose reference is the FHIR system URI. `*_concept_id` is the standard concept where the vocabulary
  holds one (a LOINC code once Athena is loaded), else 0 (design question 2: no SNOMED; ICD-10-CM is the condition
  standard). TrialBox's own concepts (suspected diagnosis, the site-input and proposed-fact type concepts, the panel
  relationship) are 2,000,000,001 to 2,000,000,022, below the catalogue's 2,000,001,001. Re-loading the same batch
  changes nothing (every record `same`, ids stable); a changed record is replaced in place with its before-image; a
  record the batch no longer carries is deleted from the standard table and tombstoned, and comes back with the same
  id; a batch older than the last one loaded is refused. A proposed fact is loaded with the proposed type concept and
  never reaches a coded lake table; a refuted diagnosis is `rejected`; a suspected one has the suspected status
  concept. Two sources that give a patient different birth dates, sexes or dates of death open a conflict: OMOP keeps
  the hospital's value and the lake reads the item as unknown until a person resolves it (`resolve_conflict`, with a
  reason and an authority); the same disagreement on the next night does not reopen a resolved conflict, a corrected
  source withdraws it. A required OMOP date the source does not give is the date the record reached TrialBox,
  flagged (`date_imputed`); a person with no birth date is kept with `year_of_birth` 0, because OMOP's "drop the
  person" convention would turn an unknown into an exclusion. One batch is one transaction under an advisory lock.
* **The lake from OMOP** (`omop.export`, `lake.source`). `TB_LAKE_SOURCE=legacy|omop`, default `legacy`
  (`deploy/docker-compose.yml`, `.env.example`). With `omop`, `Lake.rebuild` loads the snapshot and the site inputs
  and exports the same 13 tables, columns and row order; Parquet, DuckDB, chunks, embeddings and `CURRENT` are the
  rebuild's own and unchanged. In `services/lake/store.py` only the line that makes the rows changed.
* **DQD-style checks** (`omop.dqd`, `python -m omop dqd`, 226 checks): conformance (isRequired, isPrimaryKey,
  isForeignKey, fkDomain, isStandardValidConcept; local concepts ≥ 2e9 and never standard; one live provenance record
  per row), completeness (person, source-concept and standard-concept record completeness) and plausibility (year of
  birth, after birth, before death, start before end, imputed dates). An expected gap is `known` with its reason (no
  standard concepts before the Athena bundle; persons without a birth date), never hidden.

*Equivalence.* `tools/omop_parity.py` rebuilds each data set's snapshot twice through `Lake.rebuild` (legacy and
omop) and compares the lake tables row for row and, for all seven committed rulesets (`rulesets/*` and the two
open-data rulesets), the FEAS funnel (start, remaining, unknowns, variants, first-eligible months, the prevalent
pool, unknown-code-system and basis counts) and every patient's screening outcome (`SqlEngine`: verdict, evidence and
reason per criterion, D-130 coverage and D-135 widening included). Results (`eval/omop_parity/report.json`, 2026-11-09, after D-149's lake changes): **identical everywhere**. The synthetic hospital (profile `ci`, the JP-style and TW-style sites of 2,500 patients each, with 40 planted site inputs per site: 180 `site_fact` rows and 8 open birth-date conflicts each): 13 of 13 lake tables identical (78,974 and 78,754 rows), FEAS identical and 0 of 2,500 patients different for each of the 7 rulesets. The public site (SIGIR and MedTxt, 268 patients, 120 without a birth date): 13 of 13 tables (1,044 rows), FEAS identical, 0 of 268 different, 7 rulesets. The MIMIC-IV FHIR demo (100 patients): 13 of 13 tables (51,668 rows), FEAS identical, 0 of 100 different, 7 rulesets. No difference was found, so none needed a cause. DQD on the loaded stores: 0 failures on the synthetic and public sets; one on MIMIC, a real finding: 100 of 415 visits have class `OBSENC` or `SS`, which have no visit concept until the vocabulary load (the lake reads the class, not the concept). `tools/e2e_simple.py` with `TB_LAKE_SOURCE=omop` also passes, stage 13's pinned GOUT-COH funnel included.

*Evidence.* `tests/unit/test_omop_core.py` (the pinned DDL, and a changed file refused; the schema; the concept
block; the export equal to the flattener and a re-load changing nothing; pseudonyms, source values and local
concepts; a standard concept used when present; tombstones, restore and in-place updates with before-images; an older
batch refused; site inputs, statuses and conflicts, resolved and withdrawn; a person's confirm within the state
machine; the setting; DQD clean and catching a broken reference; all seven rulesets equal on both lakes). Checks, on master with D-149: `make lint` clean; `make test` 1,733 passed, 2 skipped; `tools/e2e_simple.py` PASSED in 125 s, and PASSED in 137 s with `TB_LAKE_SOURCE=omop`; the backup drill PASSED, 12 checks in 149 s (the new one: the `omop` schema, 5,000 persons and 162,933 source records, reads back with the same rows and exports the same lake); `public_e2e --lang ja` 120/120; `tools/omop_parity.py` IDENTICAL.

*Open, for the next slices.* The adapter does not write OMOP itself yet: the load runs inside the lake rebuild, a whole
batch at a time (WS-03.4's dual write by `COPY` as feed files arrive, partitions by year and the 5k and 50k timings
are next). The vocabulary schema (WS-03.3: Athena, the terminology Parquet, the licensed masters and
`sitesetup.local_code` into `concept` and `source_to_concept_map`, with "Maps to" from the TrialBox source concepts)
is not built, so every `*_concept_id` but visits is 0. NOTE_NLP and METADATA are not loaded. Conflicts are detected
for patient demographics only (WS-03.6 adds the clinical kinds and the steward's page). An older snapshot is refused
rather than exported point-in-time. A delta night's deletes (D-149) leave the snapshot and so are tombstoned
here by absence; the event does not yet say "deleted at the source" from `tombstones.json`. The consortium's 10-million site blocks (design §2.4) fit only four sites below
the integer maximum of OMOP's `concept_id` (2,147,483,647): the block size must shrink (1 million gives 47 sites)
before a second site is given one.

**D-160 EDC prefill: drafts with citations, the CRC's review and signature, REDCap send and ODM export.** Owner
decisions D-144 ("EDC: prefill, then the CRC confirms; REDCap through its API; other EDCs through CDISC ODM; no
screen-scraping or RPA; items mapped to CDASH") and D-145 (prefill switched on per study only after the sponsor's
written acknowledgement); TB-PLAN-05 WS-07.1, WS-07.2 (code), WS-07.4 (part), WS-07.7 (switch).

* **Library `services/edc/`, schema `edc`.** `mapping` (the item map: per eCRF item a CDASH tag and one source:
  patient, observation with codes and unit, condition, medication, a note passage, or none; `check` refuses a map
  that could draft a wrong kind of value, and the record-id and link fields), `cdash` (tags, en/ja/zh-TW name hints;
  diagnosis and medicine codes are never suggested), `prefill` (drafts from the box's lake), `store` (switch, map,
  drafts and their fate, decisions, signatures, sends; nothing deleted), `odm` (CDISC ODM 1.3.2), `service`.
* **Rules, each tested.** Every drafted value has a citation (record row, snapshot and day; a confirmed fact; or a
  note with a verbatim quote checked against the note); no citation, no value. Proposed chart facts never count.
  Unknown never becomes "No": a yes/no item is only drafted as yes. Ties, another unit, a censored result, a value
  outside the window or failing the field's checks stay unknown with the reason. A value without a citation cannot be
  confirmed; an edit needs a reason and passes the field's checks; a value is sent or exported only when confirmed,
  signed and unchanged since (per-value hash). The REDCap send never overwrites a value TrialBox did not write (listed
  as a conflict), never creates a record, and reads every value back.
* **Switch.** Off by default. On needs the acknowledgement kind (sponsor letter, or the PI is the sponsor), its
  reference and date (not in the future) and the blind re-entry result (≥ 30 pages, ≥ 98 %, WS-16.4); only the PI
  turns it on; the PI or an admin turns it off. While off nothing is drafted, decided, signed, sent or exported.
* **Signature.** The signer types their password again (failures count toward the lockout and are audited), ticks
  that they read the meaning, and the signature keeps the printed name (delegation log), role, meaning text,
  language, time and a hash of what was signed. SSO-only accounts cannot sign yet. A second factor (WS-13.1) is not
  built; this is a known gap for WS-07.4.
* **Roles.** `authz.EDC_ACTIONS` / `edc_allowed`: the work needs the `enter_data` study task; switch on: the PI;
  switch off: the PI or an admin; viewer and CRO: nothing.
* **Surfaces.** Orchestrator `/studies/{rs}/edc/*`; console pages *EDC prefill*, *Item map*, *Review*, *Audit trail*
  (en, ja, zh-TW) and `/api/v1/studies/{rs}/edc/*`. Note items use the gateway prompt `crf_prefill` v1 (role
  `abstract_field`), output schema `llm_crf_prefill_output`; the stub has a rule handler.
* **Not done here.** Copy-assist screen, repeating instruments, arms, record lock after SDV, the second factor at
  signing, the accept-without-edit weekly report (WS-16.4 after go-live).

*Evidence.* `tests/unit/test_edc.py`, `tests/console/test_edc_pages.py`, `tools/e2e_simple.py` stage 16 (synthetic
data, REDCap simulator).

**D-161 Study A protocol, the intended-use statement and the SNOMED CT licence inquiry (documents).** Owner decision
D-144 ("draft the Study A protocol now"; "SNOMED CT: ask about a licence; Aimedics holds it") and the clinician-view
restriction; TB-PLAN-05 WS-16.1, WS-15.3, WS-13.7. New records under `docs/plan/`: `study-a-protocol.md`
(TB-STUDY-A-01: retrospective accuracy at CGMH, English and zh-TW, sample size with its reasoning, blinded two-reader
chart review with adjudication, endpoints, analysis, data handling, timeline), `intended-use.md` (TB-IU-01: the
non-device statement and the conditions that keep it true, mapped to the MHLW/PMDA 該当性 questions and the TFDA
questions, with the points a regulatory consultant must confirm) and `snomed-inquiry.md` (TB-LIC-01: a ready-to-send
inquiry). They are drafts for the owner; none is sent or submitted by this change.

**D-162 EDC prefill hardened after the independent code review (TB-REV-EDC-01).** Review
`docs/reviews/2026-11-09-edc-prefill-review.md` (1 Blocker, 10 High, 14 Medium, 3 Low); every Blocker and High
fixed with a test, the rest answered in the file. D-160 stays; this adds:

* **Who acts.** The orchestrator's EDC routes take the person and role from the console's signed assertion
  (`X-TB-Actor`, `X-TB-Actor-Assertion`, `X-TB-Actor-Role`), never from the body; the role must allow the action
  (`authz.edc_role_may`). A signature needs an assertion the console made right after the password check (session
  `reauth-...`). A body `by` counts only on a DEV or TEST box without a token (E-01).
* **Delegation log.** To sign, the person needs their own active log entry; its name is the printed name (never a
  login name). To switch on, the log must name the person as the study's PI (E-10).
* **What is signed.** The sign call carries the draft ids and hashes the page showed; any difference refuses it. The
  hash covers the pseudonym too; a record key stays bound to its first subject; the signature keeps each value's
  hash; an edit that withdraws a signature writes a `signature_void` row (E-02, E-11, E-12).
* **Drafts.** One current draft per item (rejected drafts are superseded by a new run; send and export refuse
  duplicates). A changed value needs the person's own source; the machine citation is kept as "replaces" (E-03,
  E-08). Medicine and diagnosis rows in `entered-in-error`, `cancelled`, `draft`, `refuted` or `not-taken` never count;
  the status is shown in the citation; short code prefixes and hospital codes match whole (E-09, E-19). From a note,
  only the yes code is drafted, and a number or date must appear in its quote; an over-long note is skipped, not the
  rest (E-18, E-26).
* **Send.** Refused for a project with repeating instruments or events; a screening number on two REDCap records, a
  visit that is not an event of the project, an opted-out patient, and a value changed since the send began are each
  listed and not sent (E-04 to E-07, E-17). The opt-out register is read at draft, decide, sign, send and export.
* **ODM.** An export with a signed value whose item left the map or the dictionary is refused, not silently short;
  user and file ids no longer collide (E-22, E-23, E-28). The `crf_prefill` prompt's purpose is `data_entry` (E-27).
* **Still open** (in the review file with reasons): record lock and the second factor at signing (WS-07.4), the
  switch's evidence as typed numbers (E-14), map and target versions on drafts (E-15, E-16), database-level
  protection of the trail tables (E-21), audit of every refusal (E-20), the remaining ODM conformance points (E-23).

*Evidence.* `tests/unit/test_edc.py` (tests named `test_e01_` to `test_e26_`), `tests/console/test_edc_pages.py`,
`tools/e2e_simple.py` stage 16.

**D-163 Study A protocol and intended use revised after the independent document review (TB-REV-SA-01).** Review
`docs/reviews/2026-11-09-study-a-intended-use-review.md` (2 Blocker, 7 High, 10 Medium, 4 Low). Study A v0.2: P1
design value 0.80 with the chance of meeting both parts of the target stated; P1 allocated in proportion to list
size with a floor and an effective-size rule, Wilson interval on the effective size; P2 named as a false-omission
rate with its design value on its own denominator, and the share of eligible patients lost added as the key
secondary; a reading manual with a fixed rule for silent charts; samples drawn by the independent statistician and
the key held by the CGMH second reviewer; every tuning sample left out; the release the claim covers; the IRB points
of PDPA Art. 6, identified charts, personnel, protected records, retention, security and publication. The PI question
is the owner's, to settle by G2 before submission. Intended use v0.2: the clinician own-patient view described as
planned (C2); "consultant's opinion" and "authority's written answer" named apart, and the C6 switch needs the
authority's answer in both countries. WS-06.7 and WS-16.4 of TB-PLAN-05 now leave their patients out of Study A.

**D-185 One hashed lock: `uv.lock`, exported to `deploy/requirements.lock` with sha256 hashes and checked in CI.**
Source: `docs/reviews/2026-11-09-component-review-layer2-verification.md` row 2 and R-19; master plan WS-14.6. The
lock was made with `uv pip compile` without hashes, and pip-audit found 60 advisories in it (pillow 12.3.0: 39, pypdf
6.19.0: 18, brotli, certifi, opentelemetry-api: 1 each).
1. `uv.lock` (uv 0.11.32) is the one lock: every file of every package with its sha256. `deploy/requirements.lock` is
   its `uv export` (runtime dependencies only, no extras, no dev, not the project), written by `make lock`; never
   edited by hand. Every entry carries `--hash=sha256:`, so the images' `pip install -r` runs in hash-checking mode
   and refuses a file whose bytes differ. pip-audit itself installs from its own hashed lock
   (`tools/supply_chain/pip-audit.lock`).
2. `make lock-check` (CI, every pull request) fails when `uv.lock` no longer satisfies `pyproject.toml`
   (`uv lock --check`), when `deploy/requirements.lock` is not the export of `uv.lock`, or when an entry has no sha256,
   is not pinned with `==`, is an option (`-e`, an index) or appears twice; when a `uv.lock` package comes from git or
   a URL or has a file without a hash; and when the pip-audit lock is unhashed or not pip-audit 2.9.0. A unit test
   compares the export byte for byte, so uv is pinned to 0.11.32 in the workflows.
3. Floors for the advisories: `pypdf>=6.21.4` in `pyproject.toml`, `pillow>=13` as a uv constraint. pip-audit on the
   new lock: none.
4. The base images are pinned by index digest (`python:3.12-slim@sha256:5e2bdb1b…`, amd64 and arm64) in
   `deploy/docker/python.Dockerfile` and `demo/Dockerfile`; the demo image installs pytest on its own pip line, since
   hash-checking mode refuses an unpinned extra requirement.

*Evidence.* `tests/unit/test_supply_chain.py` (lock part); `make lock-check` PASS; an environment installed from
`deploy/requirements.lock` with `--require-hashes` (73 packages on CPython 3.12 Linux).

*Not done here.* `make venv` still resolves from `pyproject.toml` (not `uv sync --frozen`).

**D-186 SBOM per release, pip-audit and offline Trivy as gates on every shipped image, an allow-list with reasons, a
licence report.** Source: the same review, row 2 and §3; WS-14.6; the independent review of PR #61 (6 High).
1. **pip-audit** (2.9.0, from its hashed lock, on Python 3.12; build side only) on `deploy/requirements.lock`: every
   advisory fails unless allow-listed; the audited set must equal the lock's entries for CPython 3.12 on Linux
   (markers evaluated); a package it could not audit fails; an empty or unreadable report fails.
2. **Trivy** (0.75.0) with the database loaded first (`make trivy-db`; on the media, `oras pull` of `trivy-db:2` and
   `trivy-java-db:1`) and the scan offline, with no ignore file, no config file and every `TRIVY_*` setting removed.
   CRITICAL or HIGH with a fixed version fails unless allow-listed; UNKNOWN (not scored yet) counts as HIGH; a missing or
   odd severity fails; unfixed findings
   and MEDIUM/LOW are listed. A report must show OS packages and the image's own language packages (Python; jars in
   the JVM image). The database (and the Java one) may be at most 7 days old.
3. **Release gates** (`make release-gates`): each image is pinned first, a local one by its image id, a third-party
   one by its registry digest for the platform, and Trivy and Syft must both name that image. They cover
   trialbox-py, trialbox-jvm, trialbox-demo and every third-party image compose pulls. `gates.json` and
   `dist/sbom/index.json` record per image the reference, platform, image id, digests, and the report and SBOM with
   their sha256. CI (`trialbox-images.yml`) runs them on amd64 and arm64 for pull requests that change what goes into
   an image, weekly and for a release tag, and for a tag also on both platforms of `make images-multiarch` by digest.
   `make release-bundle` bundles only images in a passing record at most 7 days old (`tools/make_bundle.sh --gates`).
4. **SBOM per release**: Syft (1.56.0) CycloneDX JSON per image and platform, and for the lock: Syft over an
   environment installed from the lock with hashes, so each package carries the licence of its installed metadata;
   it must name every locked package that installs on the box, at its version.
5. **Licence report** from the SBOMs (nested components, ids, names, expressions, URLs, full texts searched to the
   end; Licence and License): flags GPL, LGPL, AGPL, unknown and dual. Only a licence on the known permissive list
   counts as an `OR` choice; `LicenseRef-*`, `NOASSERTION`, `Proprietary` never do. Each flag of a package needs its
   own allow-list entry in the lock and our images; a dual entry names the branch taken, an unknown entry the licence
   a person verified. Unknown licences of jars and Go, Rust and other binaries in our images (Syft reads no licence
   there) are counted per image and ecosystem against a reviewed budget that fails when one more appears (Python and
   npm unknowns are never budgeted). Third-party images, redistributed unmodified, have one budget per image for all
   their open flags; their terms are reviewed as a whole. Distro packages of a base image are listed, not gated.
6. **The allow-list** `deploy/supply-chain-allowlist.yaml`: every entry needs its package, a reason (20 characters or
   more) and `review_by` at most 180 days ahead; a key given twice or a list given as anything else is refused; after
   `review_by` every gate fails until the entry is reviewed or removed; there is no date override. It starts with
   the eight LGPL packages of the review, dulwich under Apache-2.0, six packages whose licence the SBOM cannot read
   (duckdb, jinja2, kiwisolver, matplotlib, pycryptodomex, reportlab; each read in the wheel; reportlab ships a GPL
   font as data), the base image's interpreter and pip's Windows launchers, and no vulnerability entries.
7. Every GitHub action is pinned to a commit; Syft and Trivy are release archives with pinned sha256.
8. Two faults that broke `make images` before this decision are fixed: `python.Dockerfile` copied `integrations/`,
   removed in D-121; the root `.dockerignore` left out the JVM image's validator and FHIR packages
   (`deploy/docker/jvm.Dockerfile.dockerignore` now applies to that build). A test checks every COPY source. The
   build contexts also leave out the scanners and their outputs (the first CI run found Syft and Trivy, with their
   Go modules, inside the demo image), and the Python images take Debian's security updates of the base's packages.

*Evidence.* `tests/unit/test_supply_chain.py` (offline, fixtures trimmed from real Trivy and Syft output);
`make pip-audit`, `make licences` and `make lock-check` PASS; the first CI runs of the image gates (amd64 and arm64)
found real HIGH and CRITICAL findings with fixes: zlib1g in the base (now upgraded at build), jackson-databind,
the HL7 FHIR core libraries, commons-beanutils, guava and httpcore5 in the validator and cql-to-elm jars, and many
in the third-party images (MailHog alone over 1,500; MailHog has no arm64 image). Those are not allow-listed here:
moving the jar versions and the third-party digests, or accepting a finding, is the security owner's decision.

*Report mode* (owner decision of 2026-11-10, option (a)). Until the follow-up lands, CI runs the image gates with
`--vuln-mode report`: fixable CRITICAL/HIGH findings in trialbox-jvm, trialbox-demo, MailHog, vLLM, postgres, HAPI
and GreenMail (`VULN_REPORT_ONLY` in `tools/supply_chain/release.py`) are listed in the CI job summary per image and
platform (CVE, package, installed and fixed version) and do not fail a pull request. trialbox-py's vulnerability
gate, the licence gate, `make lock-check`, `make allowlist-check`, `make pip-audit` and every build, scan or report
error still block, and `tools/make_bundle.sh --gates` never bundles an image that passed only in report mode.
MailHog, published for amd64 only, is left out of the arm64 gates by name (`SC_AMD64_ONLY`). Each image's findings,
owner (security owner, to assign), target date (2026-12-10) and planned fix are in
`deploy/security/known-image-findings.md`; a test keeps that file and the report-mode set in step.

*Not done here.* `THIRD_PARTY_NOTICES.md`; the SBOMs inside the signed bundle; `--gates` mandatory in
`tools/make_bundle.sh` (optional with a warning, so the demo VM's update script keeps working).

**D-187 Backups, layout 2: one snapshot, stream hashes, what a backup leaves out, sidecars.**
Source: `docs/reviews/2026-11-09-dataflow-lifecycle-review.md` §6.3 and §7.1 to §7.3 (R-45, R-60) and WS-08.6, finishing the backup row D-149 left open.
1. *One snapshot.* For each database, one session exports a `REPEATABLE READ` snapshot. `pg_dump --snapshot` dumps it, and the same session counts and hashes every table and copies the site-fetch refdata rows. The manifest says `rows_from: snapshot`. A restore that differs from such a manifest fails; one from a live-counted backup (layout 1, the update path) warns.
2. *Stream hashes.* Every member's sha256 and size are those of the bytes written into the tar, from a single read. A file whose size, mtime or inode changes during the read is taken again (3 tries), and a file that shrinks fails the backup. The encrypted file's sha256 is taken while written and saved as `<file>.sha256`. Every target is read back once. A backup counts as complete only with its sidecar.
3. *Layout.* Header and manifest carry `layout: 2`. These are left out, and listed: the data of `refdata.ctgov_study`, `trial` and `term` (vendor packs, reloaded on restore), the `*.ndjson` of lake snapshots older than `CURRENT` and the two newest, and lake `tmp/` and `.building` files. `pack`, `source`, `_schema_version` and site-fetch rows are kept. The dump is `-Fc -Z0`, compressed once by the zstd stream.
4. *Restore.* Restore reads to the final chunk and checks the sidecar. It reloads the packs the manifest names from `deploy/refdata/loaded` (install and update keep them there), or exits 3 until they are given. A newer layout is refused. Layout 1 (gzip, and zstd from D-149) still restores.
*Evidence.* `tests/unit/test_backup.py`; `tools/backup_drill.py`.

**D-188 The backup schedule, the off-box rule, the age alert, and Postgres zstd/lz4 with pgBackRest PITR.**
Source: WS-08.6 and WS-08.5 (the admin tile turns red 36 h after the last backup), RSK-13 and RSK-24; dataflow review §6.2 and §7.3.
1. *Schedule.* `python3 -m tools.trialbox backup-nightly` runs from cron at 04:45 (`deploy/backup/trialbox-backup.cron`), one run at a time. It sweeps stale plaintext spools, checks free space, writes the `.tbbak` to every target, then runs pgBackRest when archiving is on: a full backup on the site's Sunday, a differential otherwise. The result goes to `deploy/site/backup-last.json` and the audit. Fewer targets written than configured is a failure.
2. *Off-box.* A target is off-box when it is a network share, a USB disk, or a `TB_BACKUP_OFFBOX` path on another device than `/` and the deploy folder, or marked with `.trialbox-offbox`. In PRODUCTION a run without one fails, and only off-box backups count as good.
3. *Age alert.* `backup-status` (hourly) is red when the recorded good backup is missing, changed, older than 36 h or more than 1 h in the future, or disagrees with its record. It is also red when the last run or pgBackRest failed, or when archiving is off, failing, stale or silent while configured on. Red is audited, repeated every 24 h, piped to `TB_BACKUP_ALERT_CMD` and mailed. The message has no error text and no patient data.
4. *Postgres.* `wal_compression=zstd`, `default_toast_compression=lz4`, data checksums for new clusters. WAL archiving (off by default) goes to pgBackRest: zst, an aes-256-cbc repository, 3 full backups plus 7 differentials, at least two weeks of point-in-time restore. It is turned on per site (RUNBOOK §5); the cipher pass is mounted into db only.
*Evidence.* `tests/unit/test_backup_schedule.py`; `tools/backup_drill.py`.
*Not done here.* The docker-side runs; `doctor` failing on a local-only target; `install.sh` installing the cron file; the admin tile (WS-08.5); review items M2, M7, the repo-path half of M8, and the open Lows.

**D-191 The SAE register: one record per serious AE on the one reporting clock (independent plan review PR-17).** The review found that the SAE clock had no system of record and no failure mode in the risk file. TrialBox now keeps an SAE register, schema `sae` of the trial database (`services/console/saerecord.py`), with a worklist at `/sae` and a case page at `/studies/{rs}/sae/{record}/{event}` (`services/console/sae_pages.py`).

* **One place per fact.** Onset, the day learned, seriousness and outcome, and the day each first report was sent stay on the AE form (D-134, D-143). "Record the report sent" writes only that field through the data core's form save. A second "sent" is refused; corrections are made on the AE form. For a case no longer serious, a late "sent" or "closed" is kept in the register.
* **One clock.** Deadlines are `datacore.lifecycle.report_clock` with `TB_SAE_RULES` / `TB_SAE_REPORT_DAYS` (D-143), on the site's local date. The rule's follow-up is due on day 0 + the first report's days + the follow-up days. A fatal or life-threatening case to the regulator is due on day 15 (ICH E2A 7 + 8; Taiwan 15-day report). `TB_SAE_FOLLOWUP_DAYS` overrides it. Receivers' requested follow-ups have their own due day.
* **States.** Due, overdue, sent, sent late (counted, alerted) and a sent date to check (not counted, alerted).
* **Trail.** Every create and change goes to `sae_trail` and the audit log (`console.sae`), dates and parties only. Changes read from the AE form are recorded as `system:sync` with the form's author and time; a person's own entries are recorded as that person.
* **Date checks, never silently fixed:** no start day; the day learned before the onset; an onset or day learned in the future; late awareness. Each is flagged on the page.
* **Downgrades.** A case no longer serious keeps its last clock. While it has open reports it stays in the alert, and they can be sent or closed.
* **Worklist.** Overdue and late reports first, under an alert, in ja / zh-TW / en, linked from the header menu. The page names who confirmed the site rule (`TB_SAE_RULES_CONFIRMED`) and says the trial office's SAE log and SOP still govern. It shows no AE term, chart number or name.
* **Access, deny by default** (`tb_common.authz.ROLE_SAE_ACTIONS`): the coordinator views and records (with `enter_data`); the investigator (with `screen` once a PI is named) and the administrator view; viewer and CRO get 403; another study gives 404; refusals are audited.
* **Risk.** RSK-50: the register and the office log disagree, or a register date is wrong; traced from WS-06.13.

*Evidence.* `tests/console/test_sae_record.py` (15 cases); PR #60 (review: 0 Blocker, 4 High fixed).
*Open.* The office's SAE log stays the inspected record; compare monthly. Not built yet: the write-path sync from the orchestrator, the copy to the office mailbox, the OQ wrong-clock test, follow-ups on home pages and in mail, the `/api/v1` route, void and correct for receipts and requested follow-ups, and review items M5, M7 and M8.

**D-192 Identity for the console: TOTP for local accounts by default, an optional OIDC sign-in through Authelia,
the administrator's audited recovery, and hardened sessions.** Component review 2026-11-09 layer 1 rows 30 and 36
and layer 2 item 1 (Authelia, Authlib, pyotp; corrections: the OIDC provider is beta, sign-out goes through
Authelia, the portal needs a hospital host name and certificate); the IT security pack (§A.4 sign-in, §B session
controls and password policy); master plan WS-13.1 (part), URS-ADM-01, RSK-07, TST-SEC-06 (part). Built 2026-11-09,
no Docker.

* **TOTP (RFC 6238) for local accounts, standard library only** (`services/console/totp.py`): HMAC-SHA1, 6 digits,
  30 s, one step of drift either side, a step accepted once (the last step is stored; a replay is refused and
  audited). pyotp was not added: the code is 30 lines and the supply-chain lock (task A) was being rebuilt in
  parallel. Default `TB_CONSOLE_MFA=totp` outside DEV and TEST; `off` is refused in PRODUCTION. An account without an
  authenticator enrols one at its next sign-in after the password (the first good code confirms it). The secret is
  AES-256-GCM sealed with the account name as associated data, under `totp.key` on the console volume, not in the
  database (`auth` schema version 2: `totp_secret`, `totp_step`, `idp_sub`, `pending_logins`, `oidc_pending`).
* **Sign-in in two steps.** A right password makes a ten-minute pending sign-in (a SameSite=Strict cookie, its hash
  stored), never a session. A wrong or replayed code counts as a failed sign-in, and with TOTP on a right password
  no longer clears the failure count, so knowing the password does not buy unlimited code guesses. Five failures in
  15 minutes lock the account for 15 minutes (as before); the lock is audited once (`console.lockout`).
* **Recovery.** `/ops/identity` (administrators; new page, the Users page is unchanged) and `console.cli unlock|
  reset-totp`: lift a lock early, or clear another account's authenticator after a confirmation sheet (never one's
  own on the page). Both are audited (`console.unlock`, `console.totp_reset`) and the reset signs the account out.
  The reset account enrols again after its password, so the identity check before a reset is a procedure (RUNBOOK
  §12), not code.
* **Sessions.** Idle timeout default 10 minutes (the IT pack's shared-PC lock; was 30), `TB_CONSOLE_IDLE_MINUTES`
  1-60; absolute 8 h, `TB_CONSOLE_SESSION_HOURS` 1-12. Cookies HttpOnly and SameSite=Strict as before; Secure is now
  on by default in PRODUCTION when `TB_CONSOLE_SECURE_COOKIE` is unset (the base compose file still passes `0` for
  the plain-http 127.0.0.1 port; the identity overlay passes `1`).
* **OIDC through Authelia, off by default** (`services/console/oidc.py`, `TB_OIDC_ENABLED`). Authorization-code flow
  with PKCE S256, state bound to the browser by a Lax cookie and single use within 10 minutes, nonce; the ID token's
  signature is checked against the provider's JWKS (RS256 or ES256 only; `none` and HS* refused), then issuer,
  audience, `azp`, expiry, issue time, nonce and subject; `amr` must report a second factor unless
  `TB_OIDC_REQUIRE_MFA=0`. No OIDC library was added (Authlib would need the lock regenerated): `httpx` and
  `cryptography` are already dependencies. Roles come only from `TB_OIDC_GROUP_ROLES` (group:role pairs into the
  existing five roles); a `role` claim or an unmapped group gives nothing, a person in no mapped group or in groups
  of two roles is refused, the role is refreshed at each sign-in, an OIDC account is bound to its subject and never
  takes over a local or header account of the same name. The callback answers with a same-origin page that moves on
  (a Strict cookie set on a cross-site redirect would not be sent on the next hop). Sign-out continues to Authelia's
  logout. Authelia's OIDC provider is OpenID Certified but beta (4.39): the console uses only the code flow, the
  discovery document, the JWKS, the token and userinfo endpoints and a plain logout link.
* **Unchanged:** the role table (`console.auth.User` properties, `tb_common/authz.py`), the signed actor assertion
  (S-09, D-143), the trusted-header SSO (D-93).

*Evidence.* `tests/console/test_identity.py` (35 tests: the RFC 6238 vectors; window, replay and input cleaning; the
sealed secret; the defaults and bounds; enrolment with no session before the code; a half-done sign-in expiring
after ten minutes; wrong and replayed codes; lock-out
by codes with the password not resetting the count; password lock-out and the audited unlock; the audited reset and
who may do it; one-step sign-in in TEST; idle and absolute expiry; Secure, HttpOnly and Strict cookies in PRODUCTION;
OIDC off by default; OIDC settings refused when unsafe; a mapped group's sign-in, the token request with PKCE, the
audited login and the provider logout; nine refusal cases including a `role` claim, unmapped and two-role groups, a
missing second factor, nonce, audience, issuer and expiry; userinfo about another subject; state single-use, bound to
the browser and expiring; no take-over of a local account; forged, `none`, HS256 and wrong-key tokens; ES256; the
deploy files). `tests/console/test_console_app.py`: the PRODUCTION control-plane test signs in with the TOTP step
over https.

*After the independent review (2026-11-10, four High findings).* (H1) The trusted-header SSO (D-93) is refused at
start unless TOTP and OIDC are both off (so only in DEV and TEST), a header never signs in a local or OIDC account,
and Caddy strips the common identity headers and the site's configured ones from every request. (H2) A password no
longer registers a device: an account without an authenticator (every account after the upgrade, and after a reset)
needs a one-time enrolment code an administrator issues on `/ops/identity` or with `console.cli enrol-code|reset-totp`
(24 hours, once, only its hash stored, never in the audit); without one it cannot sign in; the page lists the
accounts without an authenticator first; `console.totp_enrolled` says `first` or `reset`. The first administrator's
code comes from the shell on the box (the supervised path in RUNBOOK §12). (H3) A page's own 5-second refresh asks
with `auto=1` and does not move the idle clock. (H4) CI job `trialbox-identity` runs `caddy validate` in both modes,
`docker compose config` of the merged files (pytest asserts that only Caddy publishes, only 443) and Caddy in front of
a stand-in console (HSTS, headers stripped, 80 and 8090 closed, no query strings in the log). Also: an explicit
`TB_CONSOLE_SECURE_COOKIE=0` is refused in PRODUCTION and the base compose file leaves it unset; TOTP off only in DEV
and TEST; `TB_OIDC_LOGOUT_URL` required with OIDC; the Authelia cookie scoped to its own host; HTTP errors from the
provider caught; the OIDC state checked against the browser before it is used up; half-done sign-ins cleared on a
password change and on disable.

*Open.* WebAuthn in the console (Authelia offers it for directory users), step-up re-authentication before a reveal,
an export or a signature, the breached-password list, password history and the forced first change, `doctor`
failing without MFA (its `secure_cookie` check now follows the console's default), removing the trusted-header
SSO altogether, the `steward` role (the role table stays as it is here). The full stack with Authelia has not been
started on a box (no Docker daemon on the build machine).

**D-193 TLS on the console through Caddy: its internal CA by default, the hospital's certificate by a setting.**
Component review layer 1 row 36 and layer 2 item 1; IT security pack §A.3 (only 443 from the clinic PCs) and §B "In
transit"; master plan CP-2 and RSK-27 (the internal CA as the fallback while hospital IT issues a certificate).

* `deploy/docker-compose.identity.yml` adds Caddy 2.11.9 (pinned by digest) on 443 in front of the console, stops
  publishing the console's own port (`ports: !reset []`, Compose 2.24 or later) and turns on Secure cookies; Authelia
  4.39.28 (pinned by digest) is in the `oidc` profile with its own SQLite state, on the internal network plus the
  egress network for LDAPS (opened by `EGRESS_EXTRA`). New services only; the base compose file is not changed.
* `deploy/identity/Caddyfile`: `TB_TLS_MODE=internal` (default; `tls internal`, `local_certs`, never a public ACME CA)
  or `hospital` (`TB_TLS_CERT_FILE` and `TB_TLS_KEY_FILE` from settings, mounted read-only); TLS 1.2 and 1.3, HSTS, no
  Server header, admin API off. The CA keys stay in the `caddy-data` volume, which no other service mounts; the root
  certificate is copied out for the staff PCs and for the console's back channel to Authelia (`TB_OIDC_CA`).
* `python -m console.cli check-tls` (`console.identity.check_tls`) checks the hospital certificate before Caddy uses
  it: readable PEM, valid today (a note 30 days before the end), the key is the certificate's, the host name is in the
  SAN (wildcards one level), and a note when no intermediate is in the file.
* Hospital-IT settings: `deploy/identity/identity.env.example` (copied into `deploy/.env`; settings.yaml is not used,
  because the console and Caddy both read the environment and the settings schema is shared), the Authelia example
  `deploy/identity/authelia/configuration.example.yml` (`activedirectory` over LDAPS, two-factor policy, PKCE, no
  remember-me, the same 5/15/15 lock-out), RUNBOOK §12, SECURITY §2 and §3.

*Evidence.* `tests/console/test_identity.py` (internal mode, a hospital certificate good, for another host, a
wildcard, with a foreign key, expired, ending soon, missing; the CLI; the deploy files agree with the console).

**D-270 The console's "today" is the site's date, never the UTC date (integrity review DI-1, DI-2).** The console's clock is a UTC instant. Nineteen places took its `.date()` as "today", so in Japan the console lived in yesterday until 09:00 (08:00 in Taiwan).

* **What went wrong.** A PI whose delegation started today was refused until 09:00 (E-10, "no log entry"), and had no tasks. A delegation that ended yesterday still worked until 09:00. The 07:00 and 07:30 notices were built for yesterday: no Monday digest, one on Saturday, and the investigator's clinic list a day late.
* **One helper.** `Helpers.today()` in `services/console/home.py` gives the site's calendar date: `timefmt.local_today(clock(), site_zone(bk))`, the zone being `site.tz`. Every "today" in `home.py`, `team.py`, `edc_pages.py`, `notify.py`, `timers.py`, `step4.py` and `screening_log.py` (the research-office report's default year) asks it, and so do the drivers `tools/e2e_simple.py` and `tools/rc_demo.py`. `clock()` stays the source of timestamps. The monthly delegation-log check (`team.check_due`) reads the stored check time on the site's calendar too.
* **Accounts.** An account's end date is a site day too: `UserStore.today()` in `auth.py` reads the same zone (`console.app` sets it), so an ended account stops at 00:00 at the site, not at 09:00. The request classifier's "today" in `app.py` is the site's date, not the container's.
* **No silent UTC.** `timefmt.site_zone` raises `SiteZoneError` for a zone name that is not a zone, and for a configured backend with no zone. The console asks at start-up, so it does not start. (`tb_common.config.load` already refuses a settings file without a valid `site.tz`.) Only a test double with no configuration and no `TB_TZ` reads UTC.
* **Two more.** The orchestrator's night self-test result is kept per site date, not per container date (`scheduler.night_gate`). `python -m omop dqd` takes `--tz` (default `TB_TZ`) for its "today".
* **Guard.** A unit test reads the syntax tree of `services/console` and `services/orchestrator` and fails on a calendar day taken from an instant without converting it: `.date()`, `.year`, `.month`, `.day` or `isoformat()[:10]` on `clock()`, `datetime.now(...)` or a name bound to one, and `date.today` / `datetime.today` / `datetime.utcnow`. Comments, strings and docstrings do not count; no file is exempt.

*Evidence.* `tests/console/test_site_today.py` (00:30 in Tokyo and in Taipei on the start day and on the day after the end, for a delegation and for an account; E-10; the timers on Monday 07:00 and 07:30; the admin 30-day list; the monthly log check; a wrong zone; each form the guard catches and the forms it must not), `tests/unit/test_site_today_misc.py`. `tests/console/test_local_time.py` expected UTC for a wrong zone name and now expects the error.
*Open.* The rest of DI-14: `omop/load.py` batch and release dates (metadata), the `AuditLog('/data/audit')` one-liners in `tools/trialbox/backup_schedule.py`, `tools/trialbox/update.py` and `deploy/install.sh` (default zone Taipei on every box), `backup_schedule.config` reading `TB_TZ` instead of `site.tz`, and the "last 24 hours" text comparison on the admin pages. From the review: a `UserStore` built outside the console app (`console.cli`, update and demo tools) reads `TB_TZ` for an account's end date; `tools/trialbox/logs.py` archives audit day files by the UTC date; `omop dqd --tz` defaults to `TB_TZ`, not `site.tz`, and a bad name gives a traceback; the gateway classifier's "today" and the notify command line's default day have no test of their own.
