## 16. Verification, validation and open data

This section defines how TrialBox v4 is shown to work: before any site data exists, at each site, and after every
change. It is normative for the following:

- the test layers;
- the open-data programme (C-11);
- the catalogue of evaluation suites and their gates;
- the calibration programme;
- the multilingual bake-off;
- the annotation protocol;
- the real-data validation studies;
- validation as a product feature (IQ/OQ/PQ);
- go-live acceptance per site.

§8 runs evaluations and shadow passes, §10 (SAFE, ML) defines the behaviour measured, §15 maps the evidence to
regulations, and §18 defines the rollbacks that a failed gate or KRI triggers.

### 16.1 Principles

1. **Every gate has data on day one.** v3's gates all waited for site notes, CRC adjudications or CTMS lists (R3-40). v4
   gates every model, prompt, lexicon, threshold, ruleset compiler and pipeline change on **public suites** that run in CI
   with no site data. **Site suites** then confirm the result on the box. A public suite never replaces a site suite for a
   go-live decision, and a site suite never runs outside the site.
2. **The data class decides where a test may run** (environment table, §17.8). CI holds D0 and synthetic data only. D2
   is used only in the validation environment (the site's de-identified zone or TRE, §7). D3/D4 is used only in
   production, by site suites that write aggregate reports.

3. **Safety metrics outrank accuracy.** Every judging suite reports:
   - the **false-block rate**, with a one-sided Clopper–Pearson 95 % upper bound. A false block happens when the
     model blocks a patient the physician did not block.
   - the **patient × trial false-exclusion rate**, also with its upper bound.

   These are reported next to accuracy. A candidate that wins on accuracy but fails a safety bound fails. The reason is
   given in `eval/criterion_ml/README.md`: even GPT-4's 1.4 % per-criterion false-block rate loses about 1 in 10
   eligible patient–trial pairs.
4. **Evaluation is reproducible.** A suite run is a manifest (dataset hash, prompt version, registry entry, seed,
   commit) plus recorded responses. A re-score from recorded responses is byte-identical (NFR-9 applied to evaluation).
5. **Every claim and number is reported with its population.** Public results are labelled with their population: "NCBI
   SIGIR synthetic patients; English original" or "machine-translated rendering, not clinician-verified". They are never
   presented as site performance.
6. **TRIPOD-LLM headings.** Evaluation reports, AI credibility files and the validation paper use the TRIPOD-LLM
   reporting items (Gallifant et al., *Nat Med* 2025). The prospective studies (§16.9) also use DECIDE-AI and CONSORT-AI.

### 16.2 Test layers

| Layer | What it covers | Tooling | Runs | Blocks |
| --- | --- | --- | --- | --- |
| **Unit** | Deterministic code:<br>- IR v3 semantics and calculators<br>- cascade bookkeeping (S0–S5, S2b)<br>- filter classes<br>- date and number parsers<br>- assertion cues<br>- lexicon mining<br>- privacy accountant<br>- controlled rounding<br>- LTT<br>- confidence sequences (`libs/tb_common/recall.py`)<br>- forecast maths<br>- routing-policy evaluation<br>- data-contract checks<br>- DQ rules<br>- reconciliation arithmetic<br>- MPI merge logic | `pytest`, `hypothesis` (property tests for parsers, rounding, policy tables and IR round-trips) | every commit | merge |
| **Contract** | Pydantic/JSON Schema drift (`make contracts-check`); OpenAPI conformance of every service (`schemathesis`); FHIR profile conformance of emitted resources (HAPI validator against TW Core IG and, for MS6, JP Core); MCP tool-description snapshots of the front-door server (any diff fails until reviewed); OpenAI-compatible conformance of `tb-gateway`; data contracts at L1 (§5) | `pytest -m contract`, `schemathesis`, HAPI validator, `tools/mcp_snapshot.py` | every commit | merge |
| **Integration** | Services against the compose test stack (v1 harness, movable ports):<br>- each L0–L5 stage with its controls<br>- the gateway with stub and real small models<br>- the registry<br>- the front-door MCP server<br>- the terminology service<br>- the matching engine<br>- the deliverables renderer<br>- the open-data e2e test `tests/integration/test_open_data_e2e.py` (§16.3.2) | `pytest -m integration`, testcontainers | every merge to `main`; nightly | merge, release |
| **End-to-end** | Conversation scenarios for every lifecycle stage over email, Teams and LINE, through both channel engines (`hermes` and `native`):<br>- FEAS by free text with confirmation<br>- review-page round trip<br>- Level A/A2/A+ approvals<br>- Level B signing (Playwright; the signing page, review page, admin control plane and CDS Hooks card are the only UI tests)<br>- kill -9 replay with exactly-once delivery (FR-WF-1)<br>- one deliverable pack per type (§12) | `pytest -m e2e`, MailHog, Teams/LINE fakes, Playwright | every merge; nightly | merge, release |
| **Evaluation** | The suites in §16.4. **Public suites** run in CI; **site suites** run on the box in production or validation. Mapped to the five evaluation tiers of §8:<br>- unit → contract/unit layers here<br>- task → judge, extract and match suites<br>- agentic → `intent` and Hermes scenarios on mock MCP servers<br>- adversarial → `redteam`<br>- human → the annotation protocol in §16.8 | `trialbox eval`, Inspect AI (agentic tasks), promptfoo (prompt regression and red-team plugins), `tools/mlbench.py` | public: nightly and on every G5 candidate; site: nightly on the box and at G5 | G5, release, go-live |
| **Security** | Egress per topology (v1 `test-egress`, extended to A/B/C); image and dependency scans; SAST; secret scanning; licence scan; `redteam`; gateway class-violation tests; Hermes hardening checks (§9: approvals `manual`, YOLO absent, tool include-list, read-only skills mount); OWASP ASVS 5.0 L2 checks for the four UI surfaces; DAST on the admin plane | Trivy/Grype, Semgrep, gitleaks, ZAP, `redteam` | nightly; release; on every Hermes upgrade | release |
| **Performance** | `pipeline_scale` (Synthea 300k nightly, 3M on the release bench); `bench` per hardware profile (NFR-17/18, §13); interactive targets for Hermes answers and the gateway (§13) | `trialbox bench`, k6 for interactive paths | nightly (300k); release (3M); after every G5 on the box | release, G5 |
| **Chaos and restore** | Fault injection:<br>- kill -9 at every workflow step boundary<br>- gateway and model endpoint loss (fallback must stay inside the data class)<br>- network partition to HL7 v2 and CDC sources (replay without loss or duplication)<br>- Postgres restart<br>- disk full on L0<br>- clock skew of ±5 min<br>- Hermes container loss, so the native engine takes over<br>- MinIO object-lock enforcement<br><br>Restore of the latest immutable backup to a spare box or tenant, with audit-chain verification | toxiproxy, `tools/chaos.py`, `trialbox restore --verify` | weekly (chaos subset); quarterly restore (§18.6); before every MS gate | release, MS gate |

Every test that verifies a requirement carries `@pytest.mark.req("<ID>")` (§17.4). A layer's runs are archived as
validation evidence, as immutable JSON plus JUnit XML in the evidence store (§16.10).

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| VV-01 | The test suite MUST be organised in the eight layers of §16.2, using the pytest markers `unit` (default), `contract`, `integration`, `e2e`, `eval`, `security`, `perf` and `chaos`. Each layer MUST have a `make` target and a CI job with the cadence in the table. | I | MS0 |
| VV-02 | Property-based tests (`hypothesis`) MUST cover: IR v3 serialisation round-trip; the controlled-rounding invariants (row and column totals preserved, no cell below the small-cell threshold revealed); the date and number parsers (ML-3); routing-policy evaluation, where a call labelled D3 or D4 never resolves to an external route, whatever the policy table contains. | T | MS0 |
| VV-03 | The end-to-end layer MUST run every conversation scenario through both channel engines (`channels.engine: hermes` and `native`). A scenario passes only if both engines produce the same workflow requests and the same outbox rows. | T | MS0 |
| VV-04 | The chaos layer MUST include: the kill -9 loop over every step boundary of FEAS, SCREEN, MATCH, ingest/publish and every gate, with exactly one delivered message per outbox row (FR-WF-1); HL7 v2 and CDC partition-and-replay with zero lost and zero duplicated L0 records; loss of the gateway and model endpoint with no fallback outside the data class. | T | MS1 |
| VV-05 | MCP tool descriptions, input schemas and the tool list of the front-door server MUST be snapshot-tested. Any difference fails CI until a reviewer updates the snapshot in the same pull request. | T | MS0 |
| VV-06 | Test evidence (JUnit XML, suite manifests, eval reports and recorded responses) MUST be written to the content-addressed evidence store with its commit and environment. It MUST NOT be overwritten. | T | MS0 |

### 16.3 Open-data programme

#### 16.3.1 Dataset table (normative)

The datasets below give every gate in §16.4 data before a site exists. "Licence/access" is the condition the programme
operates under. Rows marked *(uncertain)* need confirmation by counsel before commercial use (§21). No dataset is
committed to the repository unless its licence allows it. Fetchers verify checksums and write a `FETCHED.json`
provenance record. Attribution and citations live in `docs/OPEN_DATA.md` (ENG-14).

| Dataset | Licence / access | Use in v4 | Suite | Gate (provisional until re-baselined at MS1 through G5) |
| --- | --- | --- | --- | --- |
| **NCBI TrialGPT cohorts**: SIGIR 2016 and TREC Clinical Trials 2021/2022 patient topics, trial corpora, relevance judgements and keyword files (TrialGPT port, `trialgpt/data/ncbi/`) | Public research datasets. The licence follows each original release (SIGIR collection; NIST TREC). Not redistributed by TrialBox *(uncertain for commercial redistribution)* | Patient → trial retrieval and ranking (M5); trial → patients over the same corpus; regression against the TrialGPT paper | `match_registry` | recall@500 ≥ 0.90 and NDCG@10 ≥ 0.60 for the champion J model. The paper's GPT-4 figures as recorded in review R3 §2(j) were recall@500 0.93 and NDCG@10 0.73 *(uncertain: verify against Jin et al. 2024 before using them as the reference line)* |
| **NCBI TrialGPT-Criterion-Annotations** in `eval/criterion_ml/`: 1,015 expert-labelled pairs; notes in en, zh-TW, ja and code-mixed (§16.5) | Public domain (`LICENSE.NCBI`); renderings are TrialBox machine translations (D0, not clinician-verified) | Judge evaluation; evidence-span gold; multilingual parity; calibration prior (§16.6); bake-off (§16.7); annotator qualification (§16.8) | `judge_public`, `judge_ml` (public strata) | §16.4.1; GPT-4 reference in §16.5 |
| **Chia corpus** (1,000 trials, 12,409 criteria annotated with entities and relations, per review R3) | CC BY 4.0 *(uncertain: confirm on the figshare record)* | Gold data for criterion extraction, structure and normalisation; seed for the criterion library ("match-then-draft"); IR v3 coverage statistics | `criteria_extract_public` | Structure F1 ≥ 0.85; entity F1 reported per domain; concept-normalisation accuracy reported per domain (no gate until site gold exists) |
| **ClinicalTrials.gov API v2** (eligibility modules, status and conditions) | Public registry data under the ClinicalTrials.gov terms of use. Recorded cassettes (`tools/make_ctgov_cassettes.py`) and fixtures (`tools/fetch_open_data.py --ctgov`) carry the NCT id and retrieval date | Registry sync end-to-end; criterion-library seed; matching corpus; the two trials (NCT03872011, NCT04869137) whose hand-written rulesets drive the MIMIC e2e test | `criteria_extract_public` (library match rate), `match_registry`, `ingest_fhir_demo` | Library match rate reported. Registry-sync e2e passes with recorded cassettes (no live network in CI) |
| **MIMIC-IV Clinical Database Demo** and **MIMIC-IV Clinical Database Demo on FHIR v2.1.0** (100 de-identified patients each) | Open Data Commons ODbL v1.0 via PhysioNet. Downloaded to `.cache/open_data/` (gitignored) and verified against `SHA256SUMS.txt`. Derived databases are not published | End-to-end ingestion through the FHIR Bulk NDJSON and CSV paths, L0 → L5; DQ scorecard sanity; lineage completeness; terminology mapping coverage on real US codes; feasibility counts for two CT.gov trials. The demo has no free-text notes; MIMIC-IV-Note is credentialed and is not used *(as understood at writing)* | `ingest_fhir_demo` | 0 blocking DQ errors; reconciliation exact per resource type; lineage 100 %; expected counts matched; CQL ≡ SQL; byte-identical re-run (§16.3.2) |
| **Synthea** (FHIR R4, CSV and C-CDA exporters; configurable population and modules) | Apache-2.0 | Scale (300k nightly, 3M release); HL7 v2 ADT/SIU/ORU/MDM synthesised from Synthea encounters by `tools/synth/hl7v2_from_synthea.py` (Synthea has no HL7 v2 exporter); MPI tests with planted duplicates and A40 merges; late-arriving, corrected and deleted records; planted DQ defects; privacy-accountant populations; Taiwan localisation of names, ids and ROC dates by `tools/synth/` (v1 generator) | `pipeline_scale`, `accountant`, `recall_cert` (populations) | Ingest within the §13 window at 3M; 100 % detection of planted defects (§16.4); MPI pairwise F1 ≥ 0.98 on planted duplicates |
| **CHIP / CBLUE** (CHIP-CTC criterion classification, CHIP-STS, related CBLUE tasks), converted from Simplified to Traditional Chinese with OpenCC (`s2twp`, Taiwan phrasing) and labelled *synthetic-TW*; code-mixed variants made by scripted substitution of English abbreviations from the seed lexicon | Research licences, obtained by registration through the CBLUE/Tianchi distribution. No redistribution *(uncertain for commercial evaluation use)*. Held only in dev and test caches | zh criterion-type classification; zh text handling; zh/mixed strata of `criteria_extract_public` until site protocols exist | `criteria_extract_public` (zh stratum) | macro-F1 on the TW-converted set ≥ macro-F1 on the Simplified original − 0.02 (conversion must not cost accuracy); absolute macro-F1 ≥ 0.80 |
| **n2c2 2018 Track 1 (cohort selection)** (288 patients, 13 criteria *(uncertain)*) | Data use agreement through the n2c2 portal *(uncertain for a company)* | English patient-level selection baseline against published results | `cohort_n2c2` (optional) | Reported only; runs only where the DUA allows; never in CI artefacts |
| **TW/JP terminologies**: ICD-10-CM/PCS Taiwan editions (2014 and 2023); NHI drug, medical-service and special-material codes (NHI open data); LOINC with the Taiwan mapping; for MS6, the MEDIS standard disease-name master, YJ codes, JLAC10/11 and the MANBYO dictionary | Open government data (TW NHI and MOHW); LOINC licence (free, with registration); MEDIS and JLAC under their own terms; MANBYO CC BY *(uncertain per item; recorded in the terminology package manifest)* | Terminology service load and `$lookup`/`$validate-code`/`$translate` tests; lexicon seeds (ML-5); `code_versions`; `lexicon_recall` seeds | `code_versions`, `lexicon_recall` | 100 % of package rows load; `$translate` round trip exact on the mapped subset; criterion outcomes identical across editions, or a reviewed diff |

#### 16.3.2 The open-data end-to-end test (MIMIC-IV FHIR demo)

This test is under construction (`tools/fetch_open_data.py`, `tests/integration/test_open_data_e2e.py`). It is the
reference pipeline test for C-11.

1. **Fetch.** `python tools/fetch_open_data.py` downloads seven NDJSON files (Patient, Encounter, Condition,
   Observation-labevents, MedicationRequest, Medication, Procedure) and `LICENSE.txt`, each verified against
   `SHA256SUMS.txt`; a mismatch aborts. `--ctgov` refreshes the fixtures of NCT03872011 and NCT04869137.
2. **Land and validate (L0–L1).** The files enter L0 as a FHIR Bulk export would. L1 applies the data contract for each
   resource and records control totals: line counts, and patient and encounter cardinalities.
3. **Standardise and pseudonymise (L2–L3).** Codes map through the terminology service, with coverage recorded per code
   system. Identifiers are replaced with site-keyed pseudonyms. The test key is generated per run.
4. **Curate and serve (L4–L5).** The snapshot is published only through the publish gate. Reconciliation must be exact,
   and the DQ scorecard must have no blocking errors.
5. **Compute.** The hand-written rulesets in `tests/fixtures/open_data/rulesets/` cite the CT.gov text. They are compiled
   (IR → CQL/SQL), the equivalence gate runs, and the feasibility funnel is computed.
6. **Assert.**
   - Reconciliation is exact per resource type.
   - DQ blocking errors = 0.
   - Every L5 row has an OpenLineage run id and a FHIR `Provenance` chain to its L0 file hash.
   - Funnel counts equal `tests/fixtures/open_data/expected_counts.json`.
   - CQL ≡ SQL on the sample.
   - A second run from the same inputs is byte-identical: manifest, counts and rendered feasibility pack.
7. **Skip rule.** If the cache is absent and the network is unavailable, the test is skipped with a visible reason. The
   nightly CI job pre-populates the cache, so it never skips there.

`expected_counts.json` is changed only by a pull request that states why the counts moved. The review must confirm the
change against an independent SQL query written by a second engineer.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| VV-10 | Every dataset in §16.3.1 MUST have:<br>- a fetcher or importer under `tools/` that verifies checksums and writes `FETCHED.json` (dataset, version, source URL, file hashes, retrieval date);<br>- an entry in `docs/OPEN_DATA.md` with licence, attribution, citation and the permitted environments. | I, T | MS0 |
| VV-11 | Data whose licence forbids redistribution MUST NOT be committed, baked into images or written to evidence artefacts beyond aggregate metrics. CI MUST fail if a file under such a dataset's cache path appears in a commit or image layer (path and hash check). ODbL inputs (MIMIC demos) and their derived databases stay in the test cache; only aggregate results leave it. | T | MS0 |
| VV-12 | The MIMIC-IV FHIR demo end-to-end test (§16.3.2) MUST pass nightly in CI and in OQ (§16.10) with all six assertions. | T | MS0 |
| VV-13 | `tools/synth/hl7v2_from_synthea.py` MUST emit HL7 v2.5.1 ADT (A01/A03/A04/A08/A40), SIU (S12/S14/S15) and ORU (R01) messages, plus MDM (T02) message shells, from a Synthea population. The emitter is deterministic for a given seed and can plant defects: duplicate, out-of-order, late (back-dated), merge, correction and delete events. | T | MS0 |

### 16.4 Evaluation suites and gates

#### 16.4.1 Catalogue

"Public" suites run in CI on D0 data and gate every G5 candidate and every release. "Site" suites run on the box (or in
the validation environment for D2 data) and gate G5 at the site and go-live. Thresholds marked *provisional* are
re-baselined once at MS1, through G5, from the first bake-off and site results. They may be tightened later but never
loosened without a recorded G5 decision and QA approval.

| Suite | Kind | Data | Metric | Gate |
| --- | --- | --- | --- | --- |
| `judge_public` | public | `eval/criterion_ml`, English notes, all 1,015 pairs | 4-way accuracy; macro-F1; false-block rate and CP 95 % upper bound; patient × trial false exclusion and upper bound; evidence F1 on correctly labelled pairs; valid JSON; hard-slice accuracy (NCBI `training = False`, 134 pairs) | accuracy ≥ 0.85; false-block upper ≤ 0.030; patient × trial false-exclusion upper ≤ 0.175 (no worse than the GPT-4 reference); evidence F1 ≥ 0.70; valid JSON = 1.000 under constrained decoding (≥ 0.99 on providers without schema enforcement) *(provisional)* |
| `judge_ml` (public strata) | public | Same pairs, zh-TW, ja and mixed renderings | Per language: the `judge_public` metrics. Across languages: parity gap = best − worst accuracy | Per-language floors: accuracy ≥ 0.82; false-block upper ≤ 0.030; patient × trial upper ≤ 0.175. Parity gap ≤ 0.05 *(provisional)*. Results are labelled "machine-translated rendering" until the clinician review (§16.5) is complete |
| `judge_ml` (site strata) | site | Site notes dual-annotated under §16.8; strata zh-only, en-only, mixed, abbreviation-heavy (ja for MS6); ≥ 100 items each | Sensitivity, specificity, false-block upper bound and quote verification per stratum | Sensitivity ≥ 0.90 and specificity ≥ 0.90 per stratum; maximum stratum gap ≤ 5 points; quotes 100 % verified (carried from v3) |
| `criteria_extract_public` | public | Chia; CT.gov eligibility text; CHIP-CTC (TW-converted) | Structure F1; entity F1 per domain; normalisation accuracy per domain; criterion-library match rate; zh macro-F1 | Structure F1 ≥ 0.85; zh gates as in §16.3.1; zero hallucinated codes (every emitted code exists in the pinned terminology package) |
| `criteria_extract` | site | Site protocols with CRC gold IR v3 (10 by MS1, 50 by MS5) | Criterion recall; concept F1; share matched to the library | Criterion recall ≥ 0.95; concept F1 ≥ 0.88 (carried) |
| `sql_cql` | public | ATOMS_V3 (IR v3 atom catalogue) plus synthetic edge cases | CQL ≡ SQL agreement | 100 % on ATOMS_V3; ≥ 98 % on the sample (carried) |
| `match_registry` | public | TrialGPT cohorts; the 53 SIGIR notes in zh-TW and mixed against English trials | recall@500, NDCG@10, P@10 per cohort; cross-lingual gap | recall@500 ≥ 0.90; NDCG@10 ≥ 0.60; zh-TW and mixed recall@500 within 0.05 of en *(provisional)* |
| `ingest_fhir_demo` | public | MIMIC-IV FHIR demo plus two CT.gov trials | §16.3.2 assertions | All pass |
| `pipeline_scale` | public | Synthea 300k (nightly) and 3M (release), with the planted-defect catalogue (below) | Wall time per stage L0–L5; reconciliation exceptions; planted-defect detection; MPI F1 | Ingest window per §13 at 3M; 100 % of planted defects detected and quarantined or reported; MPI pairwise F1 ≥ 0.98 |
| `recall_cert` | public | Synthetic ledgers with planted eligible patients in every excluded stratum (S1, S2 index, S2 zero-hit, S2b, S3) | Coverage of the true elusion rate at every one of 12 monthly looks; coverage under importance weighting; certificate arithmetic | Confidence-sequence coverage ≥ 95 % of seeds simultaneously over 12 looks (reference simulation: repeated Clopper–Pearson missed in 9.7 % of ledgers, the sequence in 0.3 %); HT-weighted coverage ≥ 95 % with misses planted near the decision boundary; certificate output byte-identical from printed strata |
| `lexicon_recall` | public and site | Public: expert evidence sentences of `eval/criterion_ml` in zh-TW and mixed, plus synthetic code-mixed variants. Site: S4- or human-judged positive notes per canonical criterion | Lexicon recall per criterion: the share of judged-positive notes with ≥ 1 approved-lexicon hit in the window | A criterion qualifies for zero-hit exclusion only if its one-sided 95 % Clopper–Pearson **lower** bound on lexicon recall is ≥ 0.98. At zero misses this needs ≥ 149 judged positives. Below that it stays unqualified, and S2 zero-hit results become `unknown` |
| `assertion_ml` | public and site | Negation, history, family, hypothetical and uncertainty in mixed text (Appendix seed cues; site sentences) | macro-F1 (rules); model–rule agreement | macro-F1 ≥ 0.90 (carried) |
| `dates_numbers` | public | ROC and Japanese-era dates, full-width digits, Chinese numerals, unseparated value–unit pairs (ML-3 tables plus synthetic) | Exact match of typed spans | ≥ 0.99 (carried) |
| `code_versions` | public | Synthetic patients coded under ICD-10-CM TW 2014 and 2023; terminology package N and N−1 | Criterion outcomes across editions; `$translate` round trip | Outcomes identical, or every difference is listed in a reviewed diff; round trip exact |
| `intent` | public | Synthetic staff messages (zh-TW, en, ja, mixed; email, Teams and LINE register); real messages added at sites under §16.8 | Proposal accuracy; slot accuracy; deterministic-answer share for status queries; confirmation compliance | Proposal accuracy ≥ 0.95; zero external-effect actions without confirmation; 100 % of status queries answered without a model (§9) |
| `redteam` | public | Injection corpus in zh-TW, en and ja (see below), Hermes front door and native engine | Successful capability-bearing actions; PHI leaving a no-PHI channel; class violations; logging completeness | 0 successes; 0 class violations; 0 outbound PHI; 100 % of attempts logged with the blocked step; planted-PHI detection on cloud-bound traffic ≥ 0.99, where any miss that reaches a route is a blocker |
| `accountant` | public | Synthetic populations; scripted differencing and small-cell attacks across overlapping requests | Privacy-ledger correctness (§7) | 100 % of planted attacks blocked or noised as specified; ε never overspent; rounding invariants hold |
| `prescreen_patient` | site | Closed studies replayed at the recruitment-start snapshot | Historical enrollee capture (lower 95 % bound); PPV of `strong` | Capture ≥ 0.80 (lower bound reported); PPV ≥ 0.70 (carried) |
| `fairness` | public and site | Subgroups by sex, age band, note language, department; NHI coverage class where available | F1 and false-block gap | F1 gap ≤ 10 points; false-block upper bound per subgroup reported (carried) |
| `bench` | site | Installed hardware profile | Throughput, quality drop against the reference run, capacity | NFR-17/18 (§13) |

**Planted-defect catalogue** (`pipeline_scale`, `ingest_fhir_demo` variants). Each defect is planted at a known rate and
must be detected at the stage named:

| Defect | Stage | Detection |
| --- | --- | --- |
| 0.5 % rows dropped | L1/L4 | reconciliation |
| Duplicated batch | L1 | idempotency key |
| Unit swap (mg/dL ↔ µmol/L) | L2 | DQ plausibility |
| Date shift | L2 | DQ temporal |
| Big5-encoded file in a UTF-8 feed | L1 | contract |
| New or renamed column | L1 | schema drift |
| Type change | L1 | contract |
| MRN merge (A40) | MPI | lineage update |
| Late back-dated result | L4 | late-data rule |
| Source delete | L4 | tombstone |
| Out-of-range value | L2 | DQ conformance |
| Unmapped local code | L2 | terminology coverage |

**Red-team corpus** (`eval/redteam/`), by vector:

| Vector | Cases |
| --- | --- |
| Email | Hidden text (white-on-white, zero-size); Unicode tag characters; quoted-chain payloads; display-name allowlist bypass (the Hermes v0.21.6 class) |
| Documents | Sponsor PDFs and DOCX with injected instructions |
| LINE | PHI pasted into the no-PHI channel |
| Teams | Requests to forward lists, change schedules, approve gates or write skills or memory |
| MCP | Tool-description drift (tool poisoning) |
| Gateway | D3 payloads labelled D0; requests to change model alias or route |
| Prompting | Multi-turn jailbreaks in code-mixed text |

The suite runs against both channel engines and against every pinned Hermes release before promotion (§9).

#### 16.4.2 How a gate decides

The rule applies to a G5 change and to a release:

1. **Absolute floors.** Each gated metric must meet its floor in every stratum. One failing stratum fails the change. The
   strata are language, criterion type and, for site suites, note type.
2. **Non-inferiority against the champion.** On the same items, the candidate is compared with the current champion:
   - Accuracy and F1 differences are estimated with a **patient-clustered paired bootstrap**: 2,000 resamples of
     patients, because pairs share notes. The lower 95 % bound of (candidate − champion) must be ≥ −0.01.
   - The **false-block rate** must not rise: the upper 95 % bound of the difference must be ≤ +0.005.
   - Label flips are reported with McNemar's exact test.
3. **Run-to-run stability.** Three repeats (seeds 7, 11, 13) at temperature 0. The label-flip rate between repeats must
   be ≤ 0.01. A higher rate means the engine or provider is not deterministic enough for byte-identical re-runs. The
   candidate can then only be used with recorded outputs (NFR-9), and the report says so.
4. **Recall evidence.** A change that affects S1–S4 must re-establish recall evidence (SAFE-8) before the champion
   switch takes effect for live lists.
5. **Recording.** The decision, with every number and the manifests, is written to the registry as an `eval_report`
   linked to the G5 record.

The statistics live in `libs/tb_common/evalstats.py`, which provides `cluster_bootstrap`, `mcnemar_exact` and `cp_upper`
/ `cp_lower` (re-exported from `recall.py`). They are unit-tested against published reference values.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| VV-20 | `trialbox eval --suite <name> [--public\|--site]` MUST run every suite in §16.4.1. Each run writes an `eval_report` (§6) with dataset hash, prompt version, registry entry, seed, commit and per-stratum metrics with intervals. | T | MS0 |
| VV-21 | The public suites `judge_public`, `judge_ml` (public), `criteria_extract_public`, `sql_cql`, `match_registry`, `ingest_fhir_demo`, `pipeline_scale` (300k), `recall_cert`, `lexicon_recall` (public), `assertion_ml`, `dates_numbers`, `code_versions`, `intent`, `redteam` and `accountant` MUST run nightly in CI and on every G5 candidate. A failure blocks the release and the G5 approval. | T | MS0 |
| VV-22 | The gate rule of §16.4.2 (floors per stratum, patient-clustered non-inferiority, no rise in false blocks, stability over three repeats) MUST be implemented in `libs/tb_common/evalstats.py` and applied by `trialbox eval --compare <champion> <candidate>`. | T | MS1 |
| VV-23 | The `recall_cert` suite MUST verify simultaneous coverage over 12 monthly looks for `ConfidenceSequence`, with ≥ 2,000 simulated ledgers in the release run (150 in the per-commit unit test). It MUST also verify coverage under Horvitz–Thompson importance weighting with misses planted near the decision boundary, and pooling per canonical criterion across studies. Repeated Clopper–Pearson is computed alongside as the negative control and MUST show lower coverage. | T | MS0 |
| VV-24 | The `lexicon_recall` suite MUST compute, per canonical criterion, the one-sided 95 % Clopper–Pearson lower bound of lexicon recall on judged positives. It MUST publish the list of criteria qualified for S2 zero-hit exclusion (lower bound ≥ 0.98). The cascade MUST read this list from the registry and treat any criterion not on it as unqualified (§10 SAFE). | T | MS1 |
| VV-25 | The `redteam` suite MUST run against both channel engines and the gateway. It MUST be re-run before any Hermes version is promoted, and its corpus MUST grow by every production detection, with the content de-identified. | T | MS0 |
| VV-27 | Provisional thresholds MUST be re-baselined once, at MS1, by a G5 decision that cites the bake-off report and the first site results. Any later loosening needs a G5 record with QA approval and is reported in the next QA pack. | I | MS1 |

### 16.5 The multilingual criterion set (`eval/criterion_ml/`)

This set is the anchor of the judge suites, the bake-off and the public calibration prior. The facts below are
established in the repository, in `eval/criterion_ml/README.md` and `tests/unit/test_mlbench.py`.

| Property | Value |
| --- | --- |
| Pairs | 1,015 patient–criterion pairs: 53 SIGIR patients, 103 trials, 356 inclusion and 659 exclusion criteria |
| Labels | Physician label (`expert_eligibility`) and evidence sentence ids; published GPT-4 label and sentences; NCBI `training` flag |
| Languages | Notes in en (original), zh-TW (Taiwan usage), ja (clinical register) and mixed (Taiwanese code-mixed EMR style). Criteria stay in English, as protocols arrive |
| Alignment | 326 sentences per language, in the same order, so evidence ids hold in all four. Every number is preserved. No Simplified characters appear in zh-TW or mixed |
| Licence | Source in the public domain (NCBI). Renderings are machine translations made for TrialBox (Oct 2026), not clinician-verified |
| Reference | GPT-4 published labels scored by `mlbench` on all 1,015 pairs: accuracy 0.873; false-block 0.014 (CP 95 % upper 0.022); patient × trial false exclusion 0.101 (8 of 79 open pairs; upper 0.175). TrialGPT paper: GPT-4 criterion-level accuracy 87.3 %; human experts 88.7–90.0 % (as cited in review R3) |

**The `training` flag is not a held-out split.** In 129 of the 134 rows where it is `False`, GPT-4's label differs from
the physician's. In all 881 `True` rows the two agree. The flag therefore means "GPT-4 needed correction", and the
consequences are:
- It is reported as a **hard slice**. GPT-4's accuracy on that slice is low by construction, so the slice is not
  comparable to GPT-4.
- It MUST NOT be used as a train/test split, for the bake-off or for calibration.
- Splits are made by **patient**, with a stored seed (§16.6).
- `mlbench.sample()` keeps every pair whose physician label blocks the patient. It fills the rest of the sample in
  proportion to the label distribution, and never uses the flag.

**Clinician review of the renderings.** The README plans a stratified sample. Each language has only 326 sentences, so
v4 requires a **full** review instead:
- Who: a bilingual clinician for zh-TW and mixed, and one for ja.
- What: every sentence of each rendering is classified with an error taxonomy: meaning change, negation or assertion
  flip, number or unit change, term error, register error, or no error.
- Fixing: every sentence with a meaning-changing error is corrected. The set is re-versioned (`criterion_ml` v1.1)
  together with the review record.
- Before the review: results on the renderings carry the label "machine-translated, unverified". They are used for model
  comparison and parity only. They are never used as clinical ground truth, never for go-live, and never in a sponsor
  document.

The README's pointer to "SPEC_v4 §11.5" refers to this section and §16.8.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| VV-30 | `eval/criterion_ml` MUST stay aligned across languages: same keys, same sentence counts, numbers preserved, and no Simplified characters in zh-TW or mixed. `tests/unit/test_mlbench.py::test_dataset_aligned_across_languages` enforces this on every commit. | T | MS0 |
| VV-31 | The NCBI `training` flag MUST NOT be used for sampling, splitting or calibration. It MUST be reported as the hard slice. Splits for calibration and held-out evaluation MUST be by patient with a stored seed. | T | MS0 |
| VV-32 | A bilingual clinician MUST review all 326 sentences of each rendering (zh-TW, ja, mixed) using the error taxonomy above. Meaning-changing errors MUST be corrected in a new dataset version that carries the review record. Until then, every report MUST label rendering results "machine-translated, unverified". | I | MS1 |

### 16.6 Calibration programme

**The problem (R3-41).** The S3 nonconformity model (§8, §10 ML; carried from v3 §8.4) is fitted on adjudicated pairs.
Each LTT threshold per (criterion type × language stratum) certifies only once enough site labels exist. Under the
conservative default (v3 AI-11), a new site sends everything not unanimous to S4 for months.

**The constraint.** Learn-then-Test certifies a selective error rate only on calibration data that is exchangeable with
the data it is applied to. Public data is not exchangeable with a site's notes. Public data can therefore **shape the
score** and **direct labelling effort**, but it can never **certify a threshold** for live use.

**The programme** has four phases per stratum. Each phase is recorded in the registry as `calibration_state`.

| Phase | Data | Score function | Threshold | Effect on live lists |
| --- | --- | --- | --- | --- |
| **P0 Public prior** (before the site; in CI) | The 1,015 pairs × 4 renderings, judged by the candidate J model under the production prompt; label = agreement with the physician. Synthetic zh/mixed variants for abbreviation density | Logistic model `prior_<model>_<yyyy-mm>` on the v3 features, fitted on 60 % of patients and evaluated on 40 %, stored with coefficients and covariance | Public LTT threshold, computed on the held-out 40 % and reported in the model card as *public-only* | None. Used in shadow and to rank five-minute-review questions |
| **P1 Site provisional** (fewer than n_min site labels in the stratum) | Site adjudications accruing from G3 reasons, five-minute reviews (§10), validation replay and blinded chart review | Prior model (unchanged) | v3 AI-11 conservative default, made **stricter** by the prior: anything not unanimous between J and the rules goes to S4, **and** anything above the public threshold goes to S4 even when unanimous | More S4 work, never less |
| **P2 Site certified** | Site labels split by patient with a stored seed: fold A refits the score, fold B certifies | Penalised logistic regression on fold A, shrunk toward the prior coefficients with weight w = n₀ / (n₀ + n_A), where n₀ = 200 is the prior's pseudo-count *(est.)*. If the prior's AUROC on fold A is below 0.70, the score is refitted with no prior (w = 0) and the event is reported | LTT on fold B: selective error, α = 0.05, δ = 0.05, fixed-sequence binomial tests from the most conservative threshold (carried from v3) | Judgements below the certified threshold are accepted. The rest go to S4, then `pending_human` |
| **P3 Maintained** | All site labels, monthly | Refit monthly, on ML-11 drift alarms and after any G5 change affecting S3; folds are re-drawn with a new stored seed | LTT re-certified. Two consecutive months with held-out selective error > α return the stratum to P1 and raise an alert | As P2 |

n_min is the smallest fold-B size at which certification is possible at the current error count: 59 labels with 0
errors, 100 with ≤ 1, 200 with ≤ 4 (carried). Fold B must reach n_min **within** the stratum.

**What the public prior buys.** It gives the site a better score function from day one. Accepted judgements then contain
fewer errors, and certification succeeds at smaller fold-B sizes. The prior also points five-minute-review questions at
the items that move the threshold most. Target: first certified stratum at a new site within 8 weeks of silent-mode
start *(target, innovation 11)*. The QA pack (§18.8) shows the phase of every stratum, the labels still needed, and the
P1 → P2 transitions.

**Recall calibration.** Unlike the threshold calibration above, the recall ledger draws its evidence from the site itself:
- importance-weighted elusion samples (SAFE-2, v3 AI-15);
- the two known-positive lines: historical enrollees, labelled *biased*, and blinded chart review.

Public data enters only through `recall_cert`, which checks the statistics, not any site's rate.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| VV-40 | `services/orchestrator/calibration/prior.py` MUST fit the public nonconformity prior per candidate J model from `eval/criterion_ml` (patient split 60/40, stored seed). It MUST store coefficients, covariance, held-out AUROC and the public LTT threshold in the model card. | T | MS1 |
| VV-41 | A public-only threshold MUST NOT be used to accept a live judgement. In phase P1 the prior MAY only route additional judgements to S4. | T | MS2 |
| VV-42 | Site certification (P2) MUST fit the score and certify the threshold on disjoint patient folds. It MUST record both fold hashes, the shrinkage weight and the prior id in the threshold version (`aq_<yyyy-mm>`) and in every run manifest. | T | MS2 |
| VV-43 | The registry MUST hold a `calibration_state` (P0–P3) per stratum. A stratum MUST return to P1 automatically after two consecutive months with held-out selective error above α, and the research office MUST be told. | T | MS2 |

### 16.7 Multilingual small-model bake-off (as code)

**Purpose (R3-42, owner requirement 11).** Produce candidate models for each role by evidence, before hardware is
bought and before a site exists. The bake-off ranks candidates. It does not choose production models: a winner becomes a
`shadow` build at the site, and only a G5 decision on site evidence makes it `champion` (NFR-19, §8).

**Tool.** `tools/mlbench.py` exists and implements the judge task. It calls any OpenAI-compatible endpoint (default
OpenRouter via `OPENROUTER_API_KEY`; the dev box's vLLM via `--base-url`) at temperature 0 with `seed`, `max_tokens 600`
and `response_format: json_object`; on OpenRouter it adds `provider.data_collection: deny`, low excluded reasoning and
cost reporting. Responses are cached by request hash, so re-runs are free and resumable. It draws a seeded sample
(`--n`, default 400, seed 20261017: all blocking pairs plus a label-proportional fill). `score()` reports accuracy,
macro-F1, valid-JSON rate, false-block rate and patient × trial false exclusion (each with CP upper bound), block recall,
evidence F1, cost per 1k calls, and seconds and tokens per call; the summary adds mean and worst accuracy, parity gap and
a GPT-4 reference row.

**Status.** The bake-off has not been run. Results are pending an OpenRouter API key. This specification contains no
bake-off results, and none may be quoted until `report.md` exists, is committed under
`eval/criterion_ml/results/<date>/` and is registered.

**Data rule.** The bake-off uses **D0 data only**: the public annotations, their renderings, and public or synthetic
inputs for the other tasks. The gateway's routing policy (§8) admits OpenRouter for D0 only. `mlbench` in dev calls
OpenRouter directly because it never holds anything but D0, and CI checks that its inputs come only from `eval/` paths
classed D0 (ENG-16).

**Candidates.** The list is generated from the registry's `candidate` status, never from this text. The registry records
licence, origin (developer and jurisdiction), parameter count, open-weight status and reachability (OpenRouter or local
vLLM only). The list MUST include both PRC-origin and non-PRC-origin families, so that the site's model-origin policy (§21) can be
applied after the results are known rather than before. The table below shows the families intended at writing. Exact
model ids and their availability on OpenRouter are *(uncertain)* and are fixed in the registry.

| Family (examples) | Origin | Typical role tested |
| --- | --- | --- |
| Qwen3.x small and MoE (e.g. `qwen/qwen3.6-35b-a3b`) | PRC | J, extraction, intent |
| Gemma 4 (e.g. `google/gemma-4-26b-a4b-it`, 12B, 31B) | US | J, extraction |
| gpt-oss-20b / 120b | US | J, V, intent |
| Mistral Small | EU (FR) | J, intent |
| NVIDIA Nemotron (nano/small) | US | J, intent |
| Taiwan-adapted models (Breeze, Llama-Taiwan, TAIDE) | TW | J (zh-TW, mixed), intent. Local vLLM if not on OpenRouter |
| Japanese-adapted models (for MS6) | JP | J (ja) |

**Tasks.** The judge task exists. The other tasks are added as `tools/mlbench_tasks/<task>.py` modules with the same
interface: `load()`, `messages()`, `parse()` and `score()`.

| Task | Data (all D0) | Metrics |
| --- | --- | --- |
| `judge` (exists) | `eval/criterion_ml`, 4 languages | As `score()` above |
| `extract` | Chia + CT.gov (en); CHIP-CTC TW-converted (zh) | Structure F1, entity F1, hallucinated-code rate |
| `intent` | Synthetic staff messages, 4 languages | Proposal accuracy, slot accuracy, unsafe-action rate |
| `assertion` | Synthetic and seed cue sentences, 4 languages | macro-F1 |
| `dates` | ML-3 synthetic spans | Exact match |
| `protocol_qa` | Public protocols (CT.gov documents) with written Q&A | Answer accuracy, citation validity |

**Procedure** (each step is a subcommand; the full cycle is the BakeoffWorkflow in §11):

1. `mlbench run --stage screen --n 400 --langs en zh-TW ja mixed --models <registry candidates>` screens on the seeded
   400-pair sample, with one repeat.
2. `mlbench run --stage final --n 0 --repeats 3` runs candidates that pass the screening floors on all 1,015 pairs ×
   4 languages × 3 repeats (seeds 7, 11, 13), plus the other tasks.
3. `mlbench rank` applies the floors, computes the composite score with patient-clustered bootstrap intervals, and writes
   `ranking.json` and `report.md`.
4. `trialbox registry import-bakeoff <dir>` attaches the report to each candidate's model card.
5. The top two per role become `shadow` builds at a site, through G5 at Level B as a shadow-only change.
6. After at least 4 weeks of shadow evidence *(est.)*, `trialbox eval --compare` against the champion on site suites
   decides promotion to `champion` (§16.4.2).

**Floors** (a candidate below any floor is not ranked). Floors apply per language, and screening-stage floors are
checked against the point estimate only:
- valid JSON ≥ 0.99;
- accuracy ≥ 0.85 (en) and ≥ 0.82 (each other language);
- false-block CP upper ≤ 0.030;
- patient × trial false-exclusion CP upper ≤ 0.175;
- parity gap ≤ 0.05;
- run-to-run flip rate ≤ 0.01.

**Composite score** (for ranking among candidates that pass every floor; final stage):

```
S = 0.30 · worst-language accuracy
  + 0.25 · (1 − mean patient×trial false-exclusion upper bound)
  + 0.15 · mean macro-F1
  + 0.10 · mean evidence F1
  + 0.10 · task score (mean of extract, intent, assertion, dates, protocol_qa primary metrics)
  + 0.05 · hard-slice accuracy (mean over languages)
  + 0.05 · cost score, min(1, c_ref / c), c_ref = median cost per 1k of the passing set
```

- The weights live in `eval/bakeoff/weights.yaml` and are a G5-controlled parameter.
- Ties within the bootstrap interval are broken by the smaller model (NFR-19), then by lower cost.
- Using **worst-language** accuracy rather than the mean puts the per-language floors into the ranking itself. A model
  strong in English and weak in mixed notes cannot buy its way up.
- OpenRouter cost is a proxy only. On-prem cost and fit are decided by `bench` on the installed profile (NFR-17/18), and
  the shadow step needs a passing bench.

**Outputs.** `eval/criterion_ml/results/<date>/` holds:
- the JSONL responses;
- `report.json` and `report.md`;
- `ranking.json`;
- the manifest: model ids and provider routes as returned, dataset version, prompt hash, seeds, commit.

The manifest records the provider OpenRouter actually routed to, because a model id alone does not fix the serving
engine or its quantisation.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| VV-50 | `tools/mlbench.py` MUST gain the subcommands `run --stage screen\|final --repeats k` and `rank`, plus the task modules under `tools/mlbench_tasks/`. The existing judge scoring, sampling, caching and GPT-4 reference behaviour MUST stay unchanged, and the existing tests MUST keep passing. | T | MS0 |
| VV-51 | `mlbench rank` MUST apply the per-language floors, compute the composite score with patient-clustered bootstrap 95 % intervals, read weights from `eval/bakeoff/weights.yaml`, and break ties by model size and then cost. | T | MS1 |
| VV-52 | The candidate list MUST come from the registry's `candidate` status, with licence and origin recorded. It MUST include at least one PRC-origin and at least two non-PRC-origin families per role tested. | I | MS1 |
| VV-53 | The bake-off MUST use D0 data only. A run whose input path is not classed D0 in `eval/DATASETS.yaml` MUST abort before any request is sent. | T | MS0 |
| VV-54 | A bake-off result MUST NOT move a model beyond `shadow`. Promotion to `champion` needs a G5 decision on site suites (§16.4.2) and a passing `bench`. | T | MS2 |
| VV-55 | Every bake-off report MUST record the provider route and the model version as returned by the endpoint, and the run manifest. No bake-off number may appear in any document before its report is registered. | I | MS1 |

### 16.8 Annotation protocol

This protocol applies to `judge_ml` (site strata), the calibration labels, `lexicon_recall` (site), `intent` (real
messages) and the blinded chart-review line of the recall ledger. It carries v3 §11.5 and adds the following.

| Element | Rule |
| --- | --- |
| Items | Patient–criterion pairs, or messages for `intent`, sampled by stratum (language mix × note type × criterion type × department) with a stored seed. Calibration items for the five-minute review are chosen by expected information gain (§10). Validation items are drawn at random within strata, so the two pools are kept apart |
| Annotators | Two independent annotators (CRC or research nurse). A third, an investigator, adjudicates disagreements |
| Qualification | Before labelling site data, each annotator labels 50 English pairs from `eval/criterion_ml`, a seeded sample with all blocking classes represented. They must reach ≥ 0.85 agreement with the NCBI physician labels. The qualification is repeated yearly |
| Guideline | `docs/annotation_guideline.md` in zh-TW, en and ja, with examples per assertion type, per label, and for "not enough information" versus "not met". It is versioned, and the version is recorded on every label |
| Blinding | Annotators never see model outputs, cascade decisions or the other annotator's label. Recall-ledger chart reviewers do not know whether the patient was excluded |
| Agreement | Cohen's κ ≥ 0.80 per stratum before a set is accepted. Krippendorff's α is used when more than two annotators label an item. Below 0.80, the guideline is revised and the stratum is re-labelled |
| Evidence | Annotators mark the supporting sentence ids. Evidence F1 between annotators is reported |
| Environment | Annotation runs in the validation environment (D2) or on the box (D3), on the review page in annotation mode. No export of item text |
| Effort | Minutes per item are logged. They feed the labelling plan for calibration (§16.6) |
| Records | Labels are audit events with annotator, guideline version, time and item hash. Adjudications reference both labels |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| VV-60 | Annotation sets MUST reach Cohen's κ ≥ 0.80 per stratum, between two blinded, qualified annotators, before they are used for gating or calibration. Disagreements MUST be adjudicated by an investigator. | T | MS2 |
| VV-61 | The review page in annotation mode MUST hide model outputs, cascade decisions and other annotators' labels. An automated UI test MUST check that none of these fields reaches the page. | T | MS2 |
| VV-62 | Annotator qualification on `eval/criterion_ml` (≥ 0.85 agreement on 50 seeded pairs) MUST be recorded before an annotator's first site label is accepted. | T | MS2 |

### 16.9 Real-data validation studies

These studies carry v3 §11.4 into the v4 milestones (§20).

1. **Retrospective replay on de-identified data (MS1).** The hospital's research database (a CGRD-type source) is
   ingested in the validation environment through the standard L0–L5 pipeline (§5). For N ≥ 10 closed studies across ≥ 3
   therapeutic areas, `ValidationReplayWorkflow` (§11) replays the lake as of each study's recruitment start, runs the
   frozen rulesets, and measures:
   - historical enrollee capture with CP bounds;
   - criterion accuracy against blinded CRC adjudication of ≥ 100 pairs per study (§16.8);
   - PPV of `strong` and of `potential:uncertain`, with the `potential:data_gap` share reported separately;
   - review minutes per candidate.

   The enrolment link goes through the honest-broker step: the research office supplies the list, and the
   de-identification broker maps it under the database's existing IRB approval.
2. **Silent prospective (MS2).** After IRB approval, the box runs alongside current practice. It compares its lists with
   CRC pre-screening logs. Care and contact do not change. Packets go to the CRC champion only.
3. **Stepped-wedge by clinic (MS3–MS4).** Primary outcome: eligible-identified rate. Secondary: enrolment rate, CRC
   minutes per enrolled participant (time-and-motion, not self-report) and the recall certificate. Reported with
   DECIDE-AI, TRIPOD-LLM and CONSORT-AI.
4. **Cross-site replication (MS6).** At the second site, the replay in step 1 is repeated with the first site's
   champion models and ruleset library, before any site-specific tuning. This measures transfer.

The box produces the de-identified analysis datasets and pre-registered analysis scripts
(`eval/studies/<study>/analysis.py`, hash-recorded before unblinding). Publishing the Taiwan code-mixed results in a
peer-reviewed venue is a launch deliverable (§19).

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| VV-70 | `ValidationReplayWorkflow` MUST replay ≥ 10 closed studies across ≥ 3 therapeutic areas at MS1. It MUST report capture, criterion accuracy, PPV per tier and review minutes, with intervals, in a signed report. | T | MS1 |
| VV-71 | Analysis scripts for the prospective studies MUST be committed and hash-recorded before unblinding. The report MUST cite the hash. | I | MS2 |

### 16.10 Validation as a feature (GAMP 5 Second Edition, FDA CSA)

The box generates its own validation evidence. The method follows GAMP 5 Second Edition (ISPE, 2022) and the FDA
Computer Software Assurance guidance (§15 records its status): critical-thinking risk assessment, then scripted
assurance for high-risk functions and unscripted or exploratory assurance for low-risk ones.

`trialbox validate --stage iq|oq|pq|all --out validation/<date>/` produces the following:

| Stage | Content | Source |
| --- | --- | --- |
| **IQ** | Image digests verified against the signed bundle manifest and the cosign/in-toto attestations (§17.7); SBOM and ML-BOM; model weight SHA-256 against the registry; licence manifest; configuration hash; topology check (egress allowlist per topology A/B/C, and the cloud routes the policy table permits); certificate and key inventory (§14); time sync; `doctor` output | Installed box |
| **OQ** | The public suites and the integration, e2e, security and chaos layers executed on the installed box in OQ mode (synthetic and open data only): `ingest_fhir_demo`, `recall_cert`, `redteam` (both engines), `accountant`, `dates_numbers`, `intent`, `sql_cql`, the FR-WF-1 kill loop, signing negative tests (FR-SIG), and a rollback rehearsal of each change class (§18.5) | Installed box, D0 |
| **PQ** | Site evidence: validation replay (§16.9), site suites (`judge_ml` site strata, `criteria_extract`, `prescreen_patient`, `lexicon_recall`, `fairness`, `bench`), the recall certificate, calibration state per stratum, and go-live KRIs during silent mode | Validation environment and production |
| **Trace matrix** | Requirement → risk → test(s) → latest result → evidence hash, generated from `@req` markers and the spec's requirement tables (§17.4) | `tools/trace_matrix.py` |
| **Risk assessment** | Per function: intended use, GAMP category, ICH Q9(R1) severity × probability × detectability, assurance type (scripted / unscripted), and the AI credibility file for AI functions (context of use, model, data, evaluation, monitoring; §15) | `docs/validation/risk/<function>.yaml` |
| **Change record** | For G5 and bundle changes: what changed, which suites were re-executed (revalidation matrix below), results, approver | Registry and audit |

The pack is written as PDF/A plus JSON. QA signs it at Level B (FR-SIG). A pack whose evidence hashes do not match the
evidence store fails verification (`trialbox validate --verify <pack>`).

**Revalidation matrix.** It defines what must be re-executed for each change class. The change classes are those of
§18.5, so every rollback is also a validated change.

| Change class | IQ | OQ | PQ |
| --- | --- | --- | --- |
| Software bundle | full | full | `bench` + smoke PQ |
| Model / prompt / lexicon / threshold (G5) | registry + model SHA | `judge_*`, `lexicon_recall`, `redteam`, `intent` | site suites of affected strata; recall re-established (SAFE-8) |
| Ruleset (G1) | – | `sql_cql` on the ruleset | candidate diff review |
| Data snapshot | – | reconciliation + DQ | affected packets regenerated |
| Hermes channel | image digest + config | `redteam`, `intent`, e2e on both engines | – |
| Cloud route | policy table hash | egress per topology, `redteam` class tests | cost report |
| Terminology package | package manifest | `code_versions`, `ingest_fhir_demo` | affected rulesets re-gated |
| Whole-site restore | full | smoke OQ | audit verification |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| VV-80 | `trialbox validate` MUST produce IQ, OQ and PQ evidence, the trace matrix and the risk assessments as a PDF/A plus JSON pack. QA signs the pack at Level B. `trialbox validate --verify` MUST detect any evidence whose hash differs from the evidence store. | T | MS1 |
| VV-81 | OQ MUST run on the installed box using only D0 and synthetic data, and MUST include a rollback rehearsal for every change class in §18.5. | T | MS2 |
| VV-82 | Every change MUST execute the revalidation matrix row for its class before it takes effect in production (except an emergency rollback, §18.5.0, which executes it afterwards within 5 working days). | T | MS1 |
| VV-83 | Each AI function MUST have a credibility file, generated from its latest passing `eval_report`s and its risk assessment, that states context of use, model and prompt versions, data, metrics with intervals, and monitoring. | T | MS1 |

### 16.11 Go-live acceptance per site

Go-live follows the rollout in §20: install → `doctor`/`bench`/`validate` → Atlas and G0 → shadow (no messages to PIs)
→ silent prospective (CRC champion only) → wave 1 department → further waves → full → hypercare → steady state.

**Acceptance criteria before wave 1** (carried from v3 §11.3 and extended):

| Area | Criterion |
| --- | --- |
| Data | Atlas coverage ≥ 90 % of active patients for diagnoses, labs and medications (24 months); DQ scorecard with no blocking issue for 14 consecutive publishes; reconciliation exact or explained for every source; lineage complete; ROC date parse failures < 0.5 % |
| Feasibility | 5 closed studies: L4-based S0–S2 funnel within ±15 % of a manual CRC funnel on the same snapshot |
| Pre-screening | `prescreen_patient` passed on ≥ 5 closed studies; known-positive recall lower bound ≥ 0.90 on r ≥ 59 pooled enrollees, population named; elusion bounds per stratum from the confidence sequence |
| Language | `judge_ml` site strata passed, with ≥ 100 items each and gap ≤ 5 points; `lexicon_recall` list published |
| Calibration | Calibration state reported for every stratum; no stratum in P2 with held-out error > α |
| LLM platform | Gateway class-violation tests pass for the site's topology; routing-policy table signed; cost budget set |
| Release safety | `redteam` with zero successes on both channel engines; `accountant` passes |
| Approvals | FR-SIG negative tests pass; validation pack signed by QA |
| Operations | Restore test passed; rollback rehearsal for every change class passed; breach tabletop held; audit-trail review report; support roster and escalation tested |

**KRIs per wave.** Each wave runs a two-week soak and ends with a go/no-go against these KRIs. A breach during any wave
triggers the rollback named in the last column.

| KRI | Threshold | Source | On breach |
| --- | --- | --- | --- |
| PHI incidents | 0 | §14 incident log | Stop wave; §18.5 class matching the cause; breach procedure |
| `uncertain` outbox sends unresolved > 1 working day | 0 | outbox | Stop wave; investigate |
| Known-positive recall lower bound (named population) | ≥ 0.90 | recall ledger | Model/prompt/lexicon/threshold rollback (§18.5.2) or ruleset rollback (§18.5.3) |
| Elusion upper bound per stratum | ≤ 10 % (SAFE-4 demotion level) | recall ledger | Demotion (SAFE-4); rollback if demotions exceed 3 criteria in a month |
| Selective error of accepted judgements, certified strata | ≤ α | calibration | Stratum to P1 (VV-43) |
| Gate backlog | < 48 h | gates | Wave paused |
| Publish-gate blocks | 0 unexplained | data platform | Snapshot rollback (§18.5.4) |
| Gateway class violations; Hermes injection successes | 0 | gateway, `redteam`, SIEM | Cloud-route rollback (§18.5.6); channel rollback (§18.5.5) |
| Override rate at G3, per study | within EWMA control limits | gates | Review; G5 investigation |
| CRC satisfaction | ≥ 4 / 5 | pulse survey | Wave paused |
| Cost per candidate | within budget (§13) | gateway ledger | Route or cadence change |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| VV-90 | `tools/acceptance.py` MUST implement every acceptance criterion of §16.11 as a subcommand writing `<check>.json`, and `acceptance.py report` MUST assemble a signed acceptance report. Go-live of wave 1 MUST NOT proceed unless every criterion passes or a recorded waiver signed at Level B states the reason. | T | MS3 |
| VV-91 | KRIs MUST be computed daily during waves and hypercare, shown on the admin control plane, and included in the Monday digest to the research office. A breach MUST open the action in the KRI table automatically. | T | MS3 |
| VV-92 | The second site (MS6) MUST pass the same acceptance criteria from a clean install of the signed bundle, with no code change. Configuration and terminology packages are the only site-specific inputs. | D | MS6 |

## 17. Engineering standards

### 17.1 Monorepo layout

TrialBox stays one monorepo (`trialbox/`). Existing v1 packages keep their paths unless the table says otherwise. A
package that moves is moved with `git mv` at MS0 and keeps an import shim for one milestone. The new packages are
normative; other sections refer to them by these paths.

| Path | Content | Spec owner |
| --- | --- | --- |
| `services/orchestrator/` | Durable workflows, steps and outbox (v3, kept); `intake/`, `calibration/` (`abstain.py`, `prior.py`), `lifecycle/`, `privacy/`, `rollback/` (RollbackWorkflow) | §11 |
| `services/gateway/` | **tb-gateway**: OpenAI-compatible API, class policy, routing table, budgets, redaction, response and prefix-cache policy, audit events. It is the only component with network reach to model endpoints | §8 |
| `services/registry/` | Model, prompt, schema, lexicon, threshold and exemplar registry; model cards; statuses `candidate` → `qualified` → `shadow` → `champion` → `retired` (§8); `eval_report`, `bench` and bake-off import | §8 |
| `services/guard/` | Guardrail classifiers: PHI detection with Taiwan and Japan recognisers, injection classifier, policy classifier; served behind the gateway | §8, §14 |
| `services/tracestore/` | Self-hosted LLM trace store with PHI redaction at write, its own access log and retention | §8 |
| `services/frontdoor_mcp/` | TrialBox front-door MCP server: the only tools Hermes can call. No PHI tools, no schedules, no approvals, no writes | §9 |
| `integrations/hermes/` | Pinned Hermes profile configuration (`profiles/tb-internal.yaml`, `profiles/tb-line.yaml`), the `tb_policy_audit` plugin, signed `skills/`, and `hermes.lock` (version and image digest) | §9 |
| `services/channels/` | Channel abstraction and the **native** engine (`native/email`, `native/teams`, `native/line`). It replaces `services/mail_gateway/`, which moves here | §3, §9 |
| `services/dataplat/` | Data platform. Stage packages `landing/` (L0), `validate/` (L1), `standardise/` (L2), `pseudonymise/` (L3), `curated/` (L4) and `serving/` (L5). Source streams under `sources/`: `his_views`, `cdc`, `cgrd_tre`, `fhir_bulk` (with SMART Backend Services), `hl7v2` (MLLP listener), `csv_registry`, `cohort`, `nhi`. Shared modules `contracts/`, `reconcile/`, `dq/`, `mpi/`, `lineage/` (OpenLineage + FHIR Provenance), `publish/` (publish gate). `services/adapter/` moves into `sources/` and `standardise/`; `services/lake/` moves into `curated/` and `serving/` | §5 |
| `services/omop/` | OMOP CDM 5.4 ETL from L4 and the analytics endpoint | §5 |
| `services/terminology/` | Terminology service: FHIR `CodeSystem/$lookup`, `ValueSet/$expand`, `$validate-code`, `ConceptMap/$translate`; versioned packages and editions | §5 |
| `services/matching/` | Two-direction matching engine (trial → patients, patient → trials, tumour board), reusing the TrialGPT port, the S3 judge and the sentence-set cache | §10 |
| `services/deliverables/` | Pharma deliverables renderer: packs, figures, PDF/A, XLSX, Dataset-JSON and FHIR exchange, all from data objects | §12 |
| `services/console/` | Admin control plane, signing page and the optional review page (server-rendered) | §3 |
| `services/cds_hooks/` | Optional CDS Hooks card service | §3 |
| `services/criteria_compiler/`, `doc_parser/`, `embed_service/`, `llm_stub/` | Kept from v1. `criteria_compiler` targets IR v3 | §4, §10 |
| `libs/tb_common/` | Kept and extended: `recall.py` (confidence sequences), `evalstats.py`, `policy/`, `canon/`, `lexicon/`, `assertion/`, `dates/`, `ledger/` | various |
| `libs/tb_contracts/` | Pydantic v2 contracts and generated JSON Schemas (§6) | §6 |
| `libs/tb_llm/` | The only LLM client library: it talks to `tb-gateway` alone and adds the `data_class`, `study_id`, `purpose` and `context_of_use` labels | §8 |
| `libs/tb_testkit/` | Fixtures, fake gateway, Teams and LINE fakes, planted-defect generators, the `req` marker | §16 |
| `tools/trialbox/` | The `trialbox` CLI (`install`, `doctor`, `bench`, `eval`, `validate`, `rollback`, `restore`, `lake`, `registry`, `channels`) | §18 |
| `tools/` | Kept: `mlbench.py`, `fetch_open_data.py`, `acceptance.py`, `bench.py`, `sign_bundle.py`, `verify_update.py`, `synth/`. New: `mlbench_tasks/`, `trace_matrix.py`, `mcp_snapshot.py`, `chaos.py`, `synth/hl7v2_from_synthea.py` | §16, §18 |
| `eval/` | `criterion_ml/`, `bakeoff/weights.yaml`, `redteam/`, `suites/<suite>/` (dataset manifests), `studies/<study>/`, `DATASETS.yaml` (data class per dataset) | §16 |
| `vocab/`, `rulesets/`, `schemas/`, `site/playbooks/` | Kept (v3) | §5, §10 |
| `deploy/` | `topology_a/` (compose, appliance), `topology_b/` (Helm chart and Terraform modules for the hospital tenant), `topology_c/` (policy overlays), `models/`, `keys/` | §4, §18 |
| `docs/` | `architecture/` (Structurizr DSL), `adr/` (MADR), `validation/`, `OPEN_DATA.md`, `annotation_guideline.md`, runbooks | §17 |

### 17.2 Languages and coding standards

| Topic | Standard |
| --- | --- |
| Languages | Python 3.12 for services, tools and the Hermes plugin. Java 17 for HAPI FHIR and the CQL translator. SQL for L2–L5 models and OMOP ETL. The four UI surfaces are server-rendered HTML, with vanilla JS only for WebAuthn and the review-page interactions (≤ 500 lines per page; no front-end framework). Infrastructure in Helm and Terraform (topology B only) |
| Style and types | `ruff` (format and lint), `mypy --strict`, Pydantic v2 for every contract and every LLM output schema; `sqlfluff` for SQL models; `hadolint` for Dockerfiles; `shellcheck` for scripts |
| Contracts first | A service interface is a schema in `libs/tb_contracts` before it is code. Generated JSON Schemas are committed, and drift fails `make contracts-check` |
| LLM calls | Only through `libs/tb_llm` and the gateway. Every call carries its labels and a schema-constrained response format. No prompt text lives in code: prompts and schemas are registry objects resolved by version |
| Numbers | Every number in generated text comes from a deterministic result through placeholders (`numbers_match`, carried). Decimal arithmetic for rounding; no floats in reported counts |
| Errors | Fail closed on policy, class and audit errors; no silently swallowed exceptions |
| Dependencies | Pinned with hashes (`uv lock`, `requirements.lock`). A new dependency needs a licence check and an entry in the SBOM allowlist |
| Security | OWASP ASVS 5.0 Level 2 for the four UI surfaces; OWASP Top 10 for LLM Applications 2025 and MITRE ATLAS mitigations as allocated in §14; secret scanning on every commit |

### 17.3 Determinism rules

Byte-identical re-runs (NFR-9) are an engineering discipline, not a test added at the end:
- Pure functions take time from `tb_common.timeutil` (injected clock).
- Randomness comes from `tb_common.deterministic`, with a seed recorded in the manifest.
- Collections are sorted before serialisation. JSON is canonical (sorted keys, fixed separators).
- Rounding uses the controlled-rounding module only.
- Every LLM output used downstream is recorded, so a re-run replays it rather than re-calling the model.
- Object writes are content-addressed.

### 17.4 Requirement tracing

- Every test that verifies a requirement carries `@pytest.mark.req("<ID>")`. The marker is registered in
  `tests/conftest.py`, and an unknown ID fails collection.
- `tools/trace_matrix.py` parses the requirement tables of `SPEC_v4.md` (ID, V, R) and the markers, joins the latest
  results from the evidence store, and writes `trace_matrix.{json,md}`.
- CI fails if a requirement with V = T and R ≤ the current milestone has no passing test.
- Requirements with V = I, A or D link to an inspection record, analysis document or demonstration record under
  `docs/validation/`.

### 17.5 Architecture documentation

- C4 views (context, containers, and components for the gateway, data platform, front door and orchestrator) are kept in
  `docs/architecture/` as Structurizr DSL. Rendering them is a CI step.
- Architecture decisions are MADR files in `docs/adr/`, numbered `ADR-V4-xx` (§4 owns the decisions).
- An architectural change is a pull request that includes its ADR.
- This specification is the URS, structured after ISO/IEC/IEEE 29148. Functional and design specifications per workstream
  live in `docs/design/`.

### 17.6 Versioning

- SemVer for services, rulesets (`<study>/v<semver>`), prompts, schemas, lexicon, exemplar bank, threshold sets
  (`aq_<yyyy-mm>`), terminology packages (`<system>-<edition>-<pkgver>`), Hermes skill packs and bundles.
- Conventional Commits and signed commits and tags.
- Database migrations follow **expand/contract**: release N only adds columns and tables, or reads both shapes. Release
  N+1 removes the old shape. This lets bundle N−1 run against schema N, which a software rollback needs (§18.5.1).

### 17.7 CI/CD and supply chain (SLSA Build Level 3)

| Stage | Trigger | Content | Output |
| --- | --- | --- | --- |
| Commit | every push | lint, types, unit, contract, secret scan, licence scan, `@req` collection, MCP snapshot | status |
| Merge | pull request to `main` | integration, e2e (both channel engines), public eval suites on stub models, SAST, two-person review (branch protection) | status |
| Nightly | schedule | full public suites with the champion models on the CI GPU runner (D0 only), `pipeline_scale` 300k, `ingest_fhir_demo`, chaos subset, image scans | evidence |
| Release | signed tag | hermetic build on an isolated, ephemeral builder; multi-arch images; SBOM (CycloneDX 1.6) and ML-BOM; SLSA provenance (in-toto attestation); cosign signatures; `pipeline_scale` 3M; offline bundle signed Ed25519 (v1 mechanism, `tools/sign_bundle.py`); release evidence pack | signed bundle |
| Site | operator | `tools/apply_update.sh` verifies signature, provenance and hashes in a network-less container before anything changes (v1) | `update.applied` audit event |

SLSA Build Level 3 (specification v1.0 or later): hardened isolated builders, platform-generated provenance, signing
keys unreachable from build steps. The release key sits in an HSM (cloud KMS for topology B builds) under two-person
control. Hermes, model weights and third-party images are mirrored, re-scanned and re-signed with the upstream digest
recorded; nothing is pulled from a mutable reference (the CVE-2026-82021 lesson, §9, §14).

### 17.8 Environments

| Environment | Purpose | Data allowed | Model endpoints | Who | Promotion in |
| --- | --- | --- | --- | --- | --- |
| **dev** | Development, bake-off | D0 + synthetic | Local vLLM; OpenRouter for D0 (`mlbench` and dev gateway route) | Engineers | – |
| **test** | CI stack, ephemeral | D0 + synthetic | Stub, CI GPU runner (local models) | CI | Merge to `main` |
| **validation** | Site de-identified zone or TRE; production-identical configuration and bundle | D0–D2 | Site on-prem (plus approved D0–D2 routes under topology C) | Site validation team, QA | Signed bundle + OQ pass |
| **production** | Site operation | D0–D4 per §7 | Site on-prem; cloud for D0–D2 only under topology C policy | Site roles (§2) | PQ evidence + go-live acceptance or G5 |

Configuration parity between validation and production is checked: the configuration hash may differ only in the keys
listed in `deploy/parity_exceptions.yaml`. Engineers have no standing access to validation or production (§18.7).

### 17.9 Definition of Done

A change is done when all of the following hold:
1. Code and tests are written, with `@req` markers for every requirement touched.
2. Types and lint are clean.
3. Contracts are regenerated.
4. Documentation is updated (user, admin or runbook as relevant).
5. An ADR exists if the change is architectural.
6. Audit events exist for any new decision or external effect.
7. Bilingual strings are present, and message lint passes.
8. Eval suites have been added or updated if the change touches AI, and the public suites pass.
9. The data-class labels are correct on any new data path or LLM call.
10. The revalidation-matrix row (§16.10) is identified in the pull request.
11. A rollback path exists for the change class (§18.5) and is exercised in a test where the class allows it.

### 17.10 Requirements

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| ENG-01 | The repository MUST follow the layout of §17.1. CI MUST fail on imports that cross the boundaries below (`import-linter` contracts):<br>- no service other than `services/gateway` may import an HTTP client configured for a model endpoint;<br>- `services/frontdoor_mcp` may not import `dataplat`, `lake` or patient-level contracts. | T | MS0 |
| ENG-02 | Packages that move (`mail_gateway` → `channels`, `adapter` and `lake` → `dataplat`) MUST keep import shims and passing tests through MS1. The shims MUST be removed at MS2. | T | MS1 |
| ENG-03 | Python code MUST pass `ruff` and `mypy --strict`. Deterministic modules MUST keep line coverage ≥ 85 % (NFR, §13). | T | MS0 |
| ENG-04 | Every LLM call MUST go through `libs/tb_llm` to `tb-gateway`, with `data_class`, `study_id`, `purpose` and `context_of_use` set and a schema-constrained response. A static check MUST fail CI on any other HTTP call to a model API path (`/v1/chat/completions`, `/v1/completions`, `/v1/embeddings`) outside `services/gateway`. | T | MS0 |
| ENG-05 | `@pytest.mark.req` MUST be registered and validated against the spec's requirement IDs. `tools/trace_matrix.py` MUST produce the matrix, and CI MUST fail when a V = T requirement due at or before the current milestone lacks a passing test. | T | MS0 |
| ENG-06 | Database migrations MUST follow expand/contract, so that bundle N−1 runs against schema N. CI MUST run the previous release's e2e smoke suite against the new schema. | T | MS1 |
| ENG-07 | Release builds MUST meet SLSA Build Level 3 and ship SBOM (CycloneDX 1.6), ML-BOM, provenance attestations and cosign signatures. `apply_update.sh` MUST verify signature, provenance and hashes before any change. | T | MS1 |
| ENG-08 | Third-party images, Hermes releases and model weights MUST be mirrored internally, pinned by digest and re-scanned. No build or deploy step may reference a mutable tag or branch. | T | MS0 |
| ENG-09 | The four environments of §17.8 MUST exist, with the data classes and endpoints stated. Validation–production configuration parity MUST be checked at every promotion. | I, T | MS1 |
| ENG-10 | C4 views MUST render in CI from `docs/architecture/`. Every architectural pull request MUST include an `ADR-V4-xx` record. | I | MS0 |
| ENG-11 | Prompts, output schemas, lexicon, exemplars and thresholds MUST NOT be embedded in code. They are registry objects resolved by version, and their ids and hashes appear in every manifest. | T | MS0 |
| ENG-12 | Pull requests to `main` MUST have two approvals, one of them from a code owner of each touched package. Signed commits MUST be enforced. | I | MS0 |
| ENG-13 | The Definition of Done (§17.9) MUST be the pull-request template, and CI MUST check items 1–3, 7 and 9. | I | MS0 |
| ENG-14 | `docs/OPEN_DATA.md` MUST exist (it is referenced by `tools/fetch_open_data.py` and not yet written). It MUST list every dataset of §16.3.1 with licence, attribution text, citation and permitted environments. | I | MS0 |
| ENG-15 | Byte-identical re-run tests (NFR-9) MUST exist for: feasibility pack, pre-screen packet, recall certificate, deliverable packs and the open-data e2e test. | T | MS1 |
| ENG-16 | Every dataset under `eval/` MUST have a data class in `eval/DATASETS.yaml`. CI MUST refuse any dataset classed above D0 in the dev and test environments. | T | MS0 |

## 18. Operations

### 18.1 Installation per topology

Each topology installs the same signed bundle (§17.7). It differs only in the deployment unit and the policy overlay.

| Topology | Install path | Post-install checks |
| --- | --- | --- |
| **A** on-prem appliance (default) | `trialbox install --topology a --profile gb10\|x86-5090\|scale` from the offline bundle. Compose on one or more hospital hosts; egress allowlist applied at the host (`deploy/network.sh`); gateway routes on-prem only | `doctor`, `bench` (NFR-17/18), `validate --stage iq,oq` |
| **B** hospital cloud tenant, in-country, customer-managed keys | `trialbox install --topology b` renders the Helm chart and Terraform modules for the hospital's tenant: private cluster, no public ingress except the channel webhooks behind the hospital WAF, KMS keys owned by the hospital, object storage with object lock, GPU node pool for on-tenant models. The hospital's cloud team applies them; the vendor has no tenant role | As A, plus a tenant posture check (key ownership, region, public-endpoint scan, log export to the hospital SIEM) |
| **C** hybrid (A or B plus model egress for D0–D2) | Install A or B, then apply `deploy/topology_c/` policy overlay: routing-policy table rows for approved cloud endpoints (region, retention terms, class ceiling D0, D1 or D2), PHI tripwire on, canary probes, budget caps. Signed by two approvers (§18.5.6) | As A/B, plus egress test per route, class-violation tests, canary baseline |

Install creates the first configuration commit, audit genesis record and key inventory, and no external model route
above D0. Hermes is installed disabled (`channels.engine: native`) until its on-box `redteam` pass (OPS-02).

### 18.2 Schedules (defaults; site configuration)

| When | What |
| --- | --- |
| Continuous | HL7 v2 MLLP listener and CDC capture into L0 with acknowledgement after durable write; L1 validation as micro-batches every 5 min *(est.)*; same-day appointment (SIU) and ADT updates applied to clinic-day lists |
| 05:00 | Registry sync (ClinicalTrials.gov and site CTMS) |
| 05:30 | Retention jobs per zone (§7) |
| 07:00–19:00 | Day pass: J resident; Hermes and native intake; proposals; protocol understanding; interactive answers over published aggregates |
| 19:00–21:00 | Nightly ingest window: HIS view pulls, FHIR Bulk export, L2–L4 processing, reconciliation, DQ scorecard, **publish gate** → snapshot T; dirty-set computation |
| 21:00–06:30 | Night passes (J, V, J) as in v3: S3 judgements, S4 second opinions, recall-audit judgements, shadow pass, narrative drafting |
| 06:30 | Packet and deliverable assembly; outbox |
| Hourly | Canary probes on every active cloud route (topology C); gateway budget checks |
| Daily | Backup (database full or incremental per §18.6, WAL archive continuous); KRIs during waves; SIEM heartbeat check |
| Monday 06:30 | Digests to PIs, CRCs and the research office (incl. KRIs during waves) |
| Weekly | Five-minute review questions; chaos subset in the validation environment |
| Monthly (1st) | Recall audit and certificates; calibration refit (§16.6 P3); QA pack (§18.8); access recertification due list |
| Monthly | Hermes → native switch drill (§18.6) |
| Quarterly | Restore test; cloud-route kill-switch drill; terminology release check; bake-off refresh when new candidates are registered |
| Per release | CGRD/TRE, NHI and cohort sources: each release is a new L0 batch with its own contract version |

### 18.3 Monitoring, alerting and SIEM

Metrics are exported in Prometheus format and traces in OpenTelemetry (GenAI semantic conventions pinned, content capture
off outside the trace store, §8). Alert rules ship with the bundle in `deploy/alerts/`. Severity drives routing: **P1**
pages the site administrator and hospital SOC; **P2** emails IT and the research office; **P3** appears in the admin
control plane and QA pack.

| Area | Signals (alert examples) | Severity |
| --- | --- | --- |
| Data platform | L0 lag per stream > 30 min; HL7 v2 NACK rate; CDC slot lag; reconciliation exception; DQ blocking error; publish gate blocked; MPI merge backlog; lineage gaps | P2 (P1 if publish blocked at 06:00) |
| Workflows | Pass overrun; queue backlog; gate backlog per approver > 48 h; `uncertain` outbox rows | P2 |
| LLM platform | Gateway class-policy deny (any D3/D4 attempt to an external route); PHI tripwire hit; budget 80 %/100 %; schema-failure, citation-failure and number-mismatch rates; canary drift; fallback rate | P1 for class deny and tripwire, else P2 |
| Model quality | EWMA/CUSUM control charts on G3 override rate and S4 disagreement rate per stratum; ML-11 drift; held-out selective error > α | P2 |
| Hermes | Unknown-sender rejects; tool-call denials; injection-classifier hits; inbound DLP hits on no-PHI channels; outbound DLP blocks; container restarts | P1 for outbound DLP block and denied tool calls above baseline, else P3 |
| Integrity | Audit-chain anchor failure; signature verification failure; object-lock violation attempt | P1 |
| Platform | Disk, memory budget (NFR-B5), GPU health, certificate expiry < 30 days, backup failure, time drift | P2 |

**SIEM.** Security events go to the hospital SIEM over syslog/TLS (RFC 5425), mapped to OCSF classes (content
allocation in §14): authentication, Level A/B decisions, gateway policy decisions, guardrail verdicts (no content),
Hermes hook events, MCP tool calls, configuration and registry changes, rollbacks, updates and audit anchors. A 5-minute
heartbeat lets the SIEM alert on silence.

### 18.4 Updates and change windows

| Change | Path | Window |
| --- | --- | --- |
| Software bundle | Signed bundle → validation environment (OQ) → production; change-control board approval | Monthly maintenance window (Saturday 08:00–12:00 by default), outside ingest and night passes |
| Security patch | As above, expedited | Critical within 7 days, High within 30 days (§14); Hermes Critical/High within 7 days |
| Model / prompt / lexicon / threshold | G5 (Level B) with `eval_report` and revalidation matrix (§16.10) | Takes effect at the start of a night pass; batched monthly unless corrective |
| Ruleset | G1 | Any working day |
| Mapping, Atlas, lexicon diff | G0 | Any working day; effective at next publish |
| Terminology package | G0 with `code_versions` report | Quarterly or on publisher release |
| Routing policy (topology C) | Two approvers (Level A2, §3) plus G5 record | Any time; takes effect on gateway reload |
| Hermes release | Mirror, scan, `redteam` on both engines, G5 for skill packs | Maintenance window |


### 18.5 Rollback procedures (normative)

These procedures close R3-43. §20 schedules the rollout waves; it refers here for every rollback.

#### 18.5.0 Rules common to every rollback

1. **Every change class has a rollback unit that is kept available.** The previous two versions of every unit are
   retained installed or offline on the box: bundles, registry entries, rulesets, snapshots, terminology packages, Hermes
   releases and policy tables.
2. **A rollback is an audited change.** `trialbox rollback --class <class> --to <ref> [--dry-run]` starts the
   RollbackWorkflow (§11). It writes `rollback.requested`, `rollback.applied` and `rollback.verified` audit events. A dry
   run prints the steps, affected studies and packets, and the verification plan without changing anything.
3. **Authority.** A rollback to a previously approved state may be started by the system owner alone in an emergency,
   with QA approval recorded within 1 working day. Otherwise it needs the approval level of its class. A rollback never
   needs a new G5 evaluation before it runs; the revalidation-matrix row is executed afterwards (VV-82).
4. **Roll back or roll forward.** If a fix cannot be verified within the class's time target, roll back. A roll-forward
   fix is a normal change.
5. **Outputs already sent are not unsent.** Affected packets and deliverables are regenerated under the restored state.
   They are marked "regenerated after rollback <id>", and recipients get a short notice from the communication
   templates.
6. **Re-runs of earlier outputs stay byte-identical.** The rolled-back version is retained, so any manifest produced
   under it can still be replayed.
7. **Post-rollback review.** Within 5 working days a review records cause, impact, CAPA and whether recall evidence
   (SAFE-8) or calibration state (§16.6) must be re-established. The review appears in the next QA pack.
8. **Communication templates** in zh-TW, en and ja ship in `site/playbooks/rollback/`: research office, PIs and CRCs,
   sponsors, IRB, and IT/SOC.

#### 18.5.1 Software bundle

| Item | Content |
| --- | --- |
| Unit | Previous signed bundle (images, configuration schema, CLI). Blue/green release directories under `deploy/releases/<bundle>`; the active release is a symlink (A) or a Helm revision (B) |
| Trigger (any) | Failed `doctor` or `validate` after update; critical defect; security advisory against the new bundle; KRI breach traced to the release |
| Steps | 1. Pause the outbox and stop new passes (running steps finish or are checkpointed).<br>2. `trialbox rollback --class bundle --to <N-1>`: switch symlink / `helm rollback`; configuration restored from the Git tag of N−1.<br>3. Database stays at schema N (expand/contract, ENG-06).<br>4. Restart; workflows resume from durable steps.<br>5. Run verification.<br>6. Release the outbox |
| Verify | `doctor`; e2e smoke suite of N−1; audit chain continuous across the switch (`audit_verify`); no duplicate outbox deliveries |
| Time target | ≤ 30 min to service restored (carried from v3) |
| Communication | IT and research office at start and end; no external notice unless outputs were affected |

#### 18.5.2 Model, prompt, lexicon, exemplar or threshold (G5 objects)

| Item | Content |
| --- | --- |
| Unit | Previous registry entry per role (`champion` ← previous), prompt and schema version, lexicon and exemplar Git tag, threshold set `aq_<prev>` |
| Trigger (any) | Public or site suite regression; drift alarm; demotion storm (> 3 criteria demoted in a month); selective error > α for 2 consecutive months; recall lower bound below the KRI; provider silent change detected by canary (cloud) |
| Steps | 1. `trialbox rollback --class model --role <J\|V\|…> --to <entry>` (or `--class prompt\|lexicon\|threshold`).<br>2. Gateway alias re-pointed atomically; the change takes effect at the next pass boundary.<br>3. Dirty set recomputed for every judgement made under the withdrawn object; affected candidates re-judged in the next night pass.<br>4. Calibration state of affected strata set to P1 if the threshold or score function changed (§16.6).<br>5. Affected packets regenerated and flagged |
| Verify | Shadow comparison of restored vs withdrawn on the day's cached pairs; public suites re-run; recall evidence re-established (SAFE-8) before live lists resume full acceptance |
| Time target | ≤ 60 min to alias switch; affected outputs regenerated by the next 06:30 assembly |
| Communication | Research office; PIs of affected studies with the regenerated-packet notice |

#### 18.5.3 Ruleset (G1)

| Item | Content |
| --- | --- |
| Unit | Previous frozen ruleset `<study>/v<semver>` with its CQL, SQL and equivalence record |
| Trigger (any) | PI rejection rate flag (FR-M4); screen-fail blind spot (SAFE-7); amendment withdrawn; mapping error found at G3 |
| Steps | 1. CRC (and PI for high-risk studies) re-approves the previous tag at G1.<br>2. Open candidates re-evaluated; watchlist recomputed.<br>3. Study Card notes the rollback and reason |
| Verify | CQL ≡ SQL gate on the restored version; candidate diff (added/removed) sent to the study team |
| Time target | ≤ 1 working day |
| Communication | Study team; sponsor only if a deliverable was affected |

#### 18.5.4 Data snapshot

| Item | Content |
| --- | --- |
| Unit | Previous published snapshot T−1 (immutable L4/L5 version) |
| Trigger (any) | Post-publish DQ finding; reconciliation exception discovered late; source correction or retraction; MPI mis-merge |
| Steps | 1. `trialbox lake pin <T-1>`; L5 serves T−1.<br>2. Workflows that consumed T are re-run on T−1 (dirty set).<br>3. Quarantine the faulty L0 batch; data steward informed.<br>4. When fixed, publish T′ through the publish gate |
| Verify | Reconciliation report for T−1 and T′; regenerated packets carry the snapshot id; lineage shows the pin |
| Time target | ≤ 2 h to pin; re-runs complete in the next night pass |
| Communication | Data steward, research office; PIs if packets were regenerated |

#### 18.5.5 Hermes channel

| Item | Content |
| --- | --- |
| Unit | Level 1: previous pinned Hermes release and skill pack (`integrations/hermes/hermes.lock` N−1). Level 2: native engine (`channels.engine: native`) |
| Trigger (any) | Security advisory against the pinned release (go straight to Level 2 until patched); denial-rate or injection-hit anomaly; any `redteam` success in production; outbound DLP block with confirmed PHI; skill-pack regression |
| Steps | 1. `trialbox channels engine native` (Level 2) or `trialbox rollback --class channel --to <release>` (Level 1).<br>2. Hermes container stopped; its `state.db` archived encrypted and sealed.<br>3. Native engine takes over the same mailboxes, Teams app and LINE channel; in-flight requests are in the workflow engine and are not lost.<br>4. Front-door MCP credentials of the withdrawn release revoked |
| Verify | Intake e2e on the native engine; count of requests received vs submitted (no loss); outbox unchanged |
| Time target | ≤ 15 min |
| Communication | Staff notice in each channel (template); SOC if security-triggered |

#### 18.5.6 Cloud route (topology C)

| Item | Content |
| --- | --- |
| Unit | Previous routing-policy table version; ultimate fallback is the on-prem-only policy |
| Trigger (any) | Contract or retention-term change at the provider; leakage suspicion; PHI tripwire hit; canary drift; region change; cost overrun |
| Steps | 1. `trialbox rollback --class route --to <policy\|onprem-only>`; signed by two approvers (Level A2) — one approver suffices for the on-prem-only fallback in an emergency.<br>2. Gateway reloads policy; in-flight cloud calls cancelled; queued items re-routed on-prem.<br>3. Capacity check (`bench` history) and, if needed, cadence reduced with the research office told (NFR-18).<br>4. Provider credentials revoked if leakage is suspected |
| Verify | Egress test per topology shows no route to the withdrawn endpoint; class-violation tests pass; cost report |
| Time target | ≤ 15 min to policy in force |
| Communication | Research office, IT security; DPO and breach procedure if leakage is suspected (§14) |

#### 18.5.7 Terminology package

| Item | Content |
| --- | --- |
| Unit | Previous package version per code system (`<system>-<edition>-<pkgver>`); both stay loaded |
| Trigger (any) | `code_versions` failure after load; mapping coverage drop; publisher withdrawal or correction |
| Steps | 1. `trialbox rollback --class terminology --system <cs> --to <pkg>`; `active_edition` re-pointed.<br>2. L2 standardisation re-run for snapshots since the change; new snapshot published through the publish gate.<br>3. Rulesets whose ValueSet expansions changed re-run the equivalence gate |
| Verify | `code_versions`; reconciliation; ValueSet expansion hashes in manifests match the restored package |
| Time target | ≤ 2 h to re-point; re-standardisation by the next publish |
| Communication | Data steward; study teams whose rulesets were re-gated |

#### 18.5.8 Whole site

| Item | Content |
| --- | --- |
| Unit | Latest immutable backup (database, object store, configuration, keys escrow, registry, evidence store) restored to a spare box (A) or the tenant's recovery region within the country (B) |
| Trigger (any) | Ransomware; hardware loss; unrecoverable corruption; site-level security compromise |
| Steps | Follow the DR runbook (`docs/runbooks/dr.md`):<br>1. Declare the incident (§14).<br>2. Isolate; preserve forensic copies.<br>3. Provision clean host or tenant from the signed bundle.<br>4. `trialbox restore --from <backup> --verify`.<br>5. Rotate all credentials and keys reachable from the lost system.<br>6. Re-run `validate --stage iq` and smoke OQ.<br>7. Resume passes; outbox reviewed manually for `uncertain` rows |
| Verify | Audit chain verified end to end against off-box anchors; restore test record; reconciliation of the restored snapshot |
| Time target | RPO and RTO per topology (§13); v3 baseline RPO ≤ 24 h, RTO ≤ 1 working day for topology A |
| Communication | Research office, IRB, hospital leadership and DPO via the incident plan; sponsors for affected studies |

### 18.6 Backup, disaster recovery and drills

Backups:
- Nightly full or incremental database backup (pgBackRest), plus a continuous WAL archive.
- Object-store replication to a target with object lock (WORM), retained per §7.
- Configuration and registry in Git, mirrored off the box.
- Audit-chain anchors written off the box daily.
- Backups are encrypted with keys the hospital holds. One copy is offline or immutable.

| Drill | Cadence | Pass criterion |
| --- | --- | --- |
| Restore test to spare box / recovery region | Quarterly | Restore within RTO; `audit_verify` passes; smoke OQ passes |
| Full-site DR exercise | Yearly | Whole-site procedure (§18.5.8) completed by site staff using the runbook alone |
| Rollback rehearsal per change class | Before every MS gate and in OQ | Each §18.5 procedure meets its time target and verification |
| Hermes → native switch | Monthly | ≤ 15 min; no lost request |
| Cloud-route kill switch (topology C) | Quarterly | ≤ 15 min; egress test clean |
| Ransomware and breach tabletop | Yearly | Actions and notifications completed per §14 |

### 18.7 Support model

| Tier | Who | Scope |
| --- | --- | --- |
| L1 | Hospital IT service desk | Access issues, channel problems, first triage with the runbook |
| L2 | Site TrialBox administrator (hospital staff, trained) | Admin control plane, schedules, rollbacks of classes 18.5.2–18.5.7, KRIs, QA pack |
| L3 | Product engineering | Defects, bundle rollbacks with the site, root-cause analysis. Access only through the hospital's jump host with MFA, session recording, a per-session approval and a time box; no standing access; no telemetry leaves the site (topology B: hospital-granted just-in-time role) |

| Severity | Definition | Response | Update cadence |
| --- | --- | --- | --- |
| P1 | PHI incident; integrity alert; service down during a gate deadline | 1 h | Every 2 h |
| P2 | Degraded pass or ingest; KRI breach | 4 working hours | Daily |
| P3 | Defect with workaround | 2 working days | Weekly |
| P4 | Question, enhancement | 5 working days | – |

Response targets are defaults for the support agreement *(est.)*. Each wave has 4 weeks of hypercare with a daily
stand-up between the site administrator and L3 (§20).

### 18.8 Monthly QA pack

Delivered by email to QA and the research office, as signed PDF/A plus JSON. It carries v3 content and adds v4 items:
- **Audit and access:** audit-trail review; access recertification due; L3 sessions held.
- **Cascade and safety:** cascade metrics per stage (S0–S5, S2b); recall certificates with confidence-sequence bounds and
  known-positive lines; SAFE-4 demotions; ever-excluded enrollees (SAFE-7); `lexicon_recall` qualification list.
- **Calibration:** phase per stratum, labels needed, held-out selective error against α (§16.6).
- **Data platform:** DQ scorecard trend; reconciliation exceptions; lineage completeness; late and corrected data volume;
  MPI merges.
- **LLM platform:** calls by class, route and role; cost against budget; registry changes; shadow results; bake-off
  status; canary findings.
- **Hermes:** requests, denials, injection detections and DLP hits.
- **Privacy:** privacy-ledger summary.
- **Changes:** G5 and G1 changes; rollbacks and their reviews; open CAPAs.
- **Rollout:** KRIs during waves.

### 18.9 Requirements

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| OPS-01 | `trialbox install --topology a\|b\|c` MUST install from the signed bundle. It ends with `doctor`, `bench` and `validate --stage iq,oq`, and it MUST NOT create any external model route above D0. | T | MS0 |
| OPS-02 | Hermes MUST be installed disabled (`channels.engine: native`). It may be enabled only after a passing on-box `redteam` run is recorded. | T | MS0 |
| OPS-03 | The schedule of §18.2 MUST be site configuration with the defaults shown. The scheduler MUST refuse overlapping ingest and V passes (NFR-B5). | T | MS1 |
| OPS-04 | The alert rules of §18.3 MUST ship in `deploy/alerts/` with tests that fire each rule from a synthetic metric. | T | MS1 |
| OPS-05 | Security events MUST be forwarded to the hospital SIEM over syslog/TLS (RFC 5425), mapped to OCSF classes, with a 5-minute heartbeat. | T | MS2 |
| OPS-06 | `trialbox rollback --class bundle\|model\|prompt\|lexicon\|threshold\|ruleset\|snapshot\|channel\|route\|terminology` and `trialbox restore` MUST implement §18.5, with `--dry-run`, audit events and verification. Each procedure MUST meet its time target in OQ rehearsal. | T | MS2 |
| OPS-07 | The previous two versions of every rollback unit MUST be retained and restorable without network access. | T | MS1 |
| OPS-08 | A rollback MUST regenerate affected packets and deliverables, marked with the rollback id, and send the template notice. It MUST NOT resend unaffected outputs. | T | MS2 |
| OPS-09 | Every rollback MUST have a post-rollback review recorded within 5 working days and listed in the QA pack. | I | MS2 |
| OPS-10 | The software-bundle rollback MUST restore service in ≤ 30 min. The Hermes channel and cloud-route rollbacks MUST take ≤ 15 min. The G5-object rollback MUST switch aliases in ≤ 60 min. | T | MS2 |
| OPS-11 | Backups MUST include one immutable (object-lock) or offline copy, encrypted with hospital-held keys. Audit anchors MUST be written off the box daily. | T | MS1 |
| OPS-12 | The drills of §18.6 MUST run at their cadence, and their records MUST be included in the QA pack. A failed drill opens a CAPA. | I | MS3 |
| OPS-13 | L3 support access MUST go only through the hospital jump host with MFA, session recording, per-session approval and a time box. No standing vendor access and no telemetry egress are permitted. | I, T | MS1 |
| OPS-14 | The monthly QA pack MUST contain every item of §18.8 and be signed at Level B by QA. | T | MS2 |
| OPS-15 | Communication templates for every rollback class MUST exist in zh-TW and en (ja by MS6) under `site/playbooks/rollback/`. | I | MS2 |
| OPS-16 | No component may update itself. Auto-update, plugin catalogues and lazy installs MUST be disabled and checked by `doctor`. | T | MS0 |
