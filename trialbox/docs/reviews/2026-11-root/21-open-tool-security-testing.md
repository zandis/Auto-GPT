# Security testing in-house with open tools, before any paid penetration test (lane J, root review 21, 2026-11-18)

*Branch `agent/B23-root-open-security-tools`, from master `6be0f8c0`. Reader: the owner first, then lanes D, C2, B2, G
and the integrator. An engineer's reading, not a tester's report: nothing was attacked, no box was started, nothing was
installed. The only tools run were the ones already in the main checkout's environment (bandit, detect-secrets, ruff,
the repository's own scanners), read-only against the source tree, outputs under `/var/tmp/trialbox-0/b23/`.*

**Marks.** [R `file:line`] read in this repository; [M n] measured, the command in the measurement log (section 10);
[S link] a source opened for this review on 2026-11-18; [O] opinion; **not verified** where a source could not be
opened or a fact could not be checked. Licences are from the project's own licence file, opened on 2026-11-18.

**Read first and not repeated** (cited by id): review 16 (threat model §2.1, CI gates §2.6, pen-test scope §2.7, ASVS
V10–V13 sample §3, cards 16-2 to 16-32, decisions 16-D1 to 16-D8); review 10 §4.1 (CI tiers); review 07 (validation,
OQ access matrix §4.8, V19, V30); the full review's area J (J-1 to J-5, J-M1 to J-M8, J-L1 to J-L3,
`docs/reviews/2026-11-17-full-review.md:224-284`); the ASVS L2 checklist (`docs/plan/measurements/asvs-l2-checklist-2026-11-17.md`);
`docs/security/01` to `10`; plan 10's track G (`origin/agent/B18-plan-10`, cards 10G-1 to 10G-21, decisions 80 to 87);
review 18 §6 (the capability page, `origin/agent/B20-root-setup-operation`).

**Owner's rulings this document works under (2026-11-18).** On the outside penetration test (¥1.5–4 M): "Ok but there
are many open tools you can use." ISO 27001: "not now", taken up when a hospital asks. The hospital's IT team is small;
set-up must be simple. The first site gets one complete release.

**Lane boundary.** Sign-in, accounts, roles, the permission matrix, audit and break-glass are lane C2's. This document
writes test plans for them and proposes tests; it never says what a role may do. Every such card says "C2 decides".

---

## Summary for the owner (one page, plain words)

**What is tested today is good for the code's text and its parts, and missing for the running product.** Every merged
change passes a secret scan and a Python security scan, every image is checked for known vulnerabilities and
licences before it can enter a bundle, and every role is tried against every console page in the unit tests [R
`.github/workflows/trialbox-ci.yml:689-708`, `trialbox-images.yml:150-153`, `tests/console/test_role_route_matrix.py:1-24`].
What nobody does yet: **attack the running console** (no dynamic scan), **look for injection by data flow** (no
general static analyser; the SQL-building class is switched off in one linter and reviewed by count in the other),
**throw malformed files at the readers** (HL7, SS-MIX2, CSV, the update bundle, the rule-set zip), **check the host
and containers against a benchmark**, **check the TLS set-up**, and **scan the git history for secrets** [M 1–6].

**Your instinct is right: open tools can do most of a tester's first week, for free, offline.** The ones worth taking
are all permissively licensed and run at build time only; nothing new ships in the box. In order:

1. **A dynamic scan of the running console every night** (OWASP ZAP, Apache-2.0), signed in as two roles, on the
   test stack the nightly already starts [S zaproxy.org baseline; R `trialbox-e2e.yml:278-287`]. About 10 CI minutes.
2. **In-house static rules for the patterns that matter here** (Semgrep's open engine, LGPL-2.1, with rules we write;
   its registry rules are for internal use only and may not be copied into this public repository) plus a
   one-time hand review of the 164 places where SQL is built from strings [M 3; S semgrep rules licence].
3. **Malformed-input tests for the seven readers** with Hypothesis, which is already a pinned dev dependency
   [R `pyproject.toml:71`]: today it fuzzes only the encoding detector [R `tests/unit/test_encoding.py:292-320`].
4. **A secrets scan of the git history** (gitleaks, MIT), the image layers' secrets and configuration (the Trivy the
   repository already pins, with two more scanners switched on), and a lint of all six Dockerfiles (three are not
   linted today) [R `trialbox-ci.yml:733-738`; `tools/supply_chain/vulns.py:413-414`].
5. **A release checklist a second person can follow**: a full active ZAP scan per role, TLS (testssl.sh), host and
   containers against a CIS-derived open profile (OpenSCAP with the ComplianceAsCode Ubuntu 24.04 profiles, BSD-3),
   the prompt-injection suite with a Japanese hostile-note set on the qualified model pair, and the hand checks no tool
   does (business-logic access, break-glass, audit tamper evidence, restore, update rollback).

**Three licence traps found** [S]: **CodeQL may not be used** on TrialBox's code without a paid GitHub Advanced
Security licence (its terms allow only OSI-licensed codebases; TrialBox is "Proprietary" [R `pyproject.toml:7`]);
**CIS-CAT Lite** is for "internal, non-commercial use", so a vendor certifying its product with it is outside the
terms; **promptfoo** sends red-team generation to its own service by default. Each is avoided below.

**What open tools do not replace.** Independence and a letter. A Japanese hospital's IT department or a sponsor's
supplier audit treats a vendor's own scan as the vendor's word [O]; a third party's report with zero open High is what
plan 10's criterion F6 and decision 82 ask for. The in-house record does not cancel the paid test; it **shrinks it**:
a tester given a clean scan record, the threat model and the ASVS L2 self-assessment spends the days on business logic,
chained attacks and the model path instead of finding missing headers. My estimate is 5–6 tester days instead of 8–10
[O, no quote obtained].

**Five changes that matter most:** (1) ZAP baseline nightly as two roles (S); (2) Hypothesis malformed-input tests on
the seven readers (M); (3) in-house Semgrep rules + the one-time review of 164 SQL sites (M); (4) gitleaks over history,
Trivy secret/config on images, hadolint on all Dockerfiles, one SARIF folder per run (S); (5) the release security
checklist, its evidence in the bundle and one "security tested" row per release on the capability page (M).

**What it costs.** No licence fee. About 20 to 30 extra CI minutes a night and 3 to 5 a pull request [O, from the
measured local times in section 10 and the tools' own descriptions]; the release checklist about 2 person-days per
release on the integrator's stub box. Cards: 8 S, 12 M, 2 L (section 7).

---

## 1. What is tested today, measured from the workflows and the Makefile

### 1.1 Every security check that exists, where, how often, on what

| # | Check | Tool and version | Where | When | On what | Gate | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C1 | Secrets in files | detect-secrets 1.5.0 [R `pyproject.toml:60`] | CI job `security` [R `trialbox-ci.yml:689-705`]; `make security-scan` [R `Makefile:206-208`] | full tier: trains, master, by hand, cards on the full-tier list (D-564, D-970) [R `trialbox-ci.yml:86-90`] | every tracked file under `trialbox/` | fails on a finding not in the ignore file | entropy and keyword plugins off (32,129 hash false positives) [R `tools/security_scan.py:12-14`]; **files only, not git history** |
| C2 | Python security patterns | bandit 1.9.4 [R `pyproject.toml:59`] | same job | same | `libs services tools deploy eval`, generated contracts out | medium+ severity **and** medium+ confidence (`-ll -ii`) [R `tools/security_scan.py:153`] | tests/ not scanned; inline `# nosec` honoured (16 lines in 10 files) [M 4] |
| C3 | Python lint security rules | ruff 0.17.4, `S` rules [R `pyproject.toml:117`] | job `checks` [R `trialbox-ci.yml:132-134`] | every tier, every push | all Python | any finding | **S608 (SQL built from strings), S105/S106 (hard-coded passwords), S324 (weak hash), S104 (bind all), S603/S607, S311 ignored globally**; `tools/**` exempt from all S [R `pyproject.toml:118-138`] |
| C4 | Real identifiers in files and logs | `tools/data_scan.py` | job `data-scan` [R `trialbox-ci.yml:669-683`]; pre-commit | every tier | tracked files, the unit log | exit 2 on a hit | JP/TW IDs with check digits, names beside dates, archives by content [R `tools/data_scan.py:1-23`] |
| C5 | Dependency advisories (Python) | pip-audit 2.10.1 from a hashed lock [R `tools/supply_chain/lock.py:28`] | `trialbox-supply-chain.yml` [R `:63-69`] | PRs touching locks, `deploy/`, the gate code; weekly Mon 03:17 UTC [R `:10-27`] | `deploy/requirements.lock` | any advisory not allow-listed | review 10 asks for daily (§4.1) |
| C6 | Image vulnerabilities | Trivy 0.76.2, offline DB ≤ 7 days old [R `tools/supply_chain/scanners.py:32`; `vulns.py:40`] | `trialbox-images.yml` [R `:150-153`] | trains, master when image inputs change, release tags, weekly Mon 04:41 UTC (amd64 only weekly) [R `:20-57`, `:73-74`] | every image a bundle carries, both platforms | fixable CRITICAL/HIGH not allow-listed | **`--scanners vuln` only**: no secret or misconfiguration scan of the images [R `vulns.py:413-414`] |
| C7 | SBOM | Syft 1.57.1 [R `scanners.py:31`] | same; `make lock-sbom` | same | images and the Python lock | the SBOM must name the image | CycloneDX, rides in the bundle [R `docs/security/08-supply-chain.md`] |
| C8 | Licences | `tools/supply_chain/licences.py` | supply-chain and image jobs | same | SBOMs | copyleft, unknown, dual need an allow-list entry | budgets for jars [R `08-supply-chain.md`] |
| C9 | Dockerfile lint | hadolint 2.12.0 (container, by digest) | job `images` [R `trialbox-ci.yml:727-738`] | full tier | **3 of 6 Dockerfiles** (python, jvm, demo); `embed`, `db`, `backup` not linted in CI; `make ci` lints `backup` too [R `Makefile:234`; M 8] | warnings fail | |
| C10 | Workflow lint | actionlint 1.7.7 (container, by digest) | job `checks` [R `trialbox-ci.yml:135-139`] | every tier | `.github/workflows/trialbox-*.yml` | any finding | catches script injection in workflow expressions [O] |
| C11 | Shell lint | shellcheck, warning level | job `checks` [R `:174-177`] | every tier | every tracked `*.sh` | warnings fail | |
| C12 | Role × route matrix | pytest | unit shards | full tier | every console route × 9 columns of roles, GET and changing calls with CSRF and bearer tokens, one study (GZQO) [R `tests/console/test_role_route_matrix.py:1-24`] | a cell differs from `tests/console/data/role_route_matrix.md` (320 table lines [M 9]) | vertical access; **one study only** |
| C13 | Patient reads checked per person and study (orchestrator) | pytest | unit shards | full tier | every GET route of the orchestrator: no claim, a claim for another study, a role without the right → 403 [R `tests/unit/test_patient_reads_check_person_and_study.py:1-16`] | | horizontal access at the API |
| C14 | Permission function | pytest | unit shards | full tier | `permit()` over `authz_matrix.yaml`, odd roles refused [R `tests/unit/test_authz_matrix.py:1-35`] | | |
| C15 | Prompt-injection suite | `tools/injection_eval.py` | unit test against the stub [R `tests/unit/test_injection_suite.py:30`]; `tools/qualify.py` step `injection` against a pair [R `tools/qualify.py:1060`] | full tier (stub); by hand (pair) | 70 cases: 56 attacks, 14 controls; ja 12 + 3, zh-TW 24 + 5, en 20 + 6 [M 7] | 0 changed facts | **never run on the real pair** (J-5) |
| C16 | Update path | `tools/update_drill.py` | nightly [R `trialbox-e2e.yml:89-91`] | nightly | signed good, tampered, older, incompatible bundles; bad migration; kill -9 at each step; rollback [R `tools/update_drill.py:1-25`] | any check | strong; runs on a throwaway key |
| C17 | Backup and restore | `tools/backup_drill.py` | nightly [R `trialbox-e2e.yml:86-88`] | nightly | in-process box | | never on box hardware (review 16 §2.5) |
| C18 | Egress default-deny | `tests/integration/test_egress.py` | `make test-egress` only [R `Makefile:337-338`] | **never in CI** (needs root) [M 5] | | | J-M7 (DNS) open |
| C19 | Audit chain | `tools/audit_verify.py` | `make audit-verify` [R `Makefile:450-451`] | by hand | | | |
| C20 | ASVS L2 self-assessment | `tools/asvs_checklist.py --check` | doc check | – | 133 lines; **V10 1, V11 1, V12 2, V13 3 lines**; 11 "not assessed" [M 6] | | review 16 §3's 26-line sample not yet in the json |

**[O] Reading.** The gates on what goes **into** the box (locks, images, licences) are better than most hospital
vendors'. The gates on what the box **does when attacked** are unit tests written by the authors. Review 16 §2.6 said
"no dynamic scan, no CodeQL/Semgrep": confirmed from the files [M 5], with three more gaps it did not list: the
SQL-building class is out of both static tools' reach (C2, C3), image layers are not scanned for secrets or settings
(C6), and three Dockerfiles are not linted (C9).

### 1.2 Measured here (read-only, against the source tree)

| What | Result | Basis |
| --- | --- | --- |
| The repository's bandit gate | 89 findings in 12 rules, all in reviewed ignores, PASS, 24 s [M 1] | as CI |
| The repository's secret gate | 6 findings (5 Basic Auth, 1 Private Key), all reviewed, PASS, 1 min 56 s on 4 cores [M 2] | as CI |
| bandit with **no** severity or confidence filter | **895** findings: HIGH/HIGH 6 (B701 2, B602 2, B324 2: all in the reviewed ignores), MEDIUM/HIGH 23, MEDIUM/MEDIUM 60, **MEDIUM/LOW 163 — all B608 (SQL built from strings)**, LOW 643 (B101 211, B603 149, B404 76, B607 76, B311 55, B105 52, …) [M 3] | what `-ll -ii` hides |
| ruff `S` with none of the project's ignores, shipped code (`libs services deploy`) | 330: **S608 164**, S101 123, S603 19, S607 8, S311 8, **S105 6**, S701 1, S104 1 [M 3] | what the global ignores hide |
| Inline suppressions in shipped/tool code | `# nosec` 16 lines in 10 files; `# noqa: S…` 8 lines in 8 files [M 4] | not counted by the ignore ledger |
| Jinja escape bypasses | 3: `console_js|safe` (the inline script, CSP-hashed) [R `services/console/templates/base.html:71`] and two `Markup(...).format(...)` (format escapes its arguments) [R `services/console/app.py:839-840`] | [O] all three safe |
| OpenAPI exposure | the console disables `/docs` and `/openapi.json` [R `services/console/app.py:589`]; every other service is made by `tb_common.http` with FastAPI's defaults [R `libs/tb_common/http.py:239`], so `/openapi.json` answers on the internal network, behind the service token only where `protect_reads` is set [R `:264-277`] | Low (CWE-200) finding, and an asset for API fuzzing (2.6) |
| Hypothesis use | 9 test files import it; on the readers, only the encoding detector (`st.binary`, 500 examples) [R `tests/unit/test_encoding.py:292-320`] [M 10] | HL7 `parse`, SS-MIX2 source, CSV source, bundle verifier, rule-set zip, REDCap dictionary: none |
| Dynamic scan, TLS scan, host benchmark, history secret scan, API fuzzing in any workflow | none [M 5] | |

**[O] The single most useful number here is 164.** SQL text built from strings in shipped code is CWE-89, rank 2 of
the CWE Top 25. Ruff ignores the rule everywhere; bandit sees 39 of them at medium confidence (all reviewed) and
163 at low confidence that nobody reviews. Most are surely identifiers from code (schema names, column lists) and
safe; nobody has shown it. A one-time hand review with a data-flow rule (Semgrep, 2.1) settles it and then a ratchet
keeps it settled (card OT-4).

### 1.3 Coverage by weakness class

**By ASVS 4.0.3 chapter** (the repository's version; 5.0 is review 16's card 16-13). "Today" = section 1.1's checks.

| ASVS chapter | Today | Gap | Open tool or hand test that adds most |
| --- | --- | --- | --- |
| V1 Architecture, threat model | review 16 §2 as text; ASVS 1.1.2 "does not meet" [R checklist:262] | no maintained threat model (16-16 / 10G-4) | none: a document; section 3 of this review maps tests to it |
| V2 Authentication | L2 checklist scored V2 (52 lines) [M 6]; unit tests | no dynamic test of throttling (J-4), MFA flow, reset | ZAP authenticated scans; hand checklist A1–A6 (3.3) |
| V3 Session | V3 scored (18 lines) | cookie flags read, not observed on the wire through Caddy | ZAP passive rules (cookie flags, CSRF tokens); hand A7–A9 |
| V4 Access control | C12, C13, C14 | horizontal access in the **console** across two studies and two patients; break-glass step-up (J-M3) | extend C12 to two studies (OT-6, C2 decides); hand B1–B6 |
| V5 Validation, injection | pydantic contracts; bandit/ruff partly; autoescape; CSP | SQL class unreviewed (1.2); no malformed-input tests on readers; no active injection test | Semgrep in-house rules + hand review (OT-4); Hypothesis readers (OT-5); ZAP full scan; sqlmap only on a confirmed point |
| V6 Cryptography | bandit B324 (2 reviewed); hand review in V3 checklist | no check of TLS parameters as served | testssl.sh before release (OT-12) |
| V7 Errors, logging | data scan on logs (C4); scrubber | identifiers in audit text (J-M1); no test that errors leak nothing under attack | ZAP "application error disclosure" rules; hand C3 |
| V8 Data protection | data scan; egress test exists but not in CI | DNS leak (J-M7); `/healthz` disclosure (J-L1) | egress test on the stub box per release (OT-13); hand C1–C2 |
| V9 Communications | Caddy TLS 1.2/1.3 by configuration [R `docs/security/02-network.md:41`] | not measured; two-device link mTLS selftest exists (images job) | testssl.sh on the stub box (OT-12) |
| V10 Malicious code, supply chain | C5–C8, signed bundle, pinned actions | 1 line in the checklist; no history secret scan; no provenance (16-15) | gitleaks (OT-2); Scorecard once; cosign/SLSA (with 10G-7) |
| V11 Business logic | EDC row locks; reveal rate limit (review 16 §3) | no tool can test it | hand checklist B (3.3); WSTG 4.10 |
| V12 Files and resources | 50 MB cap, type sniff, safe filenames (review 16 §3) | zip-bomb (16-23 / 10G-6); no malformed-file tests; no AV (decision 83: rely on the hospital's) | Hypothesis on readers (OT-5); ZAP upload rules |
| V13 API | contracts; service tokens | no API fuzzing; internal OpenAPI exposed (1.2) | Schemathesis in-process (OT-8) |
| V14 Configuration | hadolint (3 of 6), check_host, compose memory limits | 1 of 15 containers drops privileges (16-17 / 10G-1); no image config scan; no CIS-mapped host scan | Trivy config + Dockle (OT-3); OpenSCAP CIS-derived profile, Lynis, docker-bench before release (OT-11) |

**By CWE Top 25 (2025)** [S https://cwe.mitre.org/top25/archive/2025/2025_cwe_top25.html]. TrialBox's own code is
Python, Java (the CQL translator) and Jinja; memory-safety weaknesses reach it only through native dependencies.

| Rank, CWE | Today | Gap | Adds most |
| --- | --- | --- | --- |
| 1 CWE-79 XSS | autoescape; CSP `default-src 'self'`, script by hash (review 16 §2.1); 3 escape bypasses, safe [M 3] | no active test | ZAP full scan; Semgrep rule "no new `|safe` / `Markup` with f-string" |
| 2 CWE-89 SQL injection | 39 reviewed bandit findings | **164 S608 sites unreviewed**, ruff rule off [M 3] | Semgrep taint rules + hand review (OT-4); ZAP active; sqlmap on a confirmed point only |
| 3 CWE-352 CSRF | matrix test posts with tokens [R `test_role_route_matrix.py:12-14`]; SameSite=Strict [R `services/console/app.py:609`] | no test that a changing call **without** the token is refused across all routes | extend C12 with a "no token" column (OT-6) |
| 4 CWE-862, 17 CWE-863, 19 CWE-284, 24 CWE-639 access control | C12–C14 | console horizontal (other study, other patient id in the URL) | OT-6 (C2 decides); hand B1–B6 |
| 6 CWE-22 path traversal | filenames reduced to `[\w.-]` (review 16 §3); `_safe` member names in the bundle verifier [R `tools/verify_update.py:67`] | not fuzzed | Hypothesis on the verifier (crafted tar names); Semgrep rule on `open()`/`Path` joins of request data |
| 9 CWE-78, 23 CWE-77 command injection | bandit B602 (2 reviewed); S603/S607 off in ruff | low-severity subprocess calls unreviewed (B603 149) [M 3] | Semgrep rule "no `shell=True`, argv lists only"; review once |
| 10 CWE-94 code injection | bandit/ruff (eval, exec) | – | – |
| 12 CWE-434 unrestricted upload | size cap; type sniff; attachments served sandboxed | no AV; zip-bomb | Hypothesis (OT-5); 10G-6 |
| 15 CWE-502 deserialisation | bandit B506 (2 reviewed, `yaml.load` with SafeLoader) | – | Semgrep rule pins `yaml.safe_load`, no `pickle` on request data |
| 18 CWE-20 input validation | pydantic at the contracts | readers not fuzzed | OT-5, OT-8 |
| 20 CWE-200 information exposure | data scan; scrubber | `/healthz` (J-L1); internal `/openapi.json` [M 3 read]; audit text (J-M1) | ZAP information-disclosure rules; hand C1 |
| 21 CWE-306 missing authentication | service token middleware [R `libs/tb_common/http.py:264-277`] | an unlisted callee accepts any token (J-M6) | ZAP unauthenticated crawl per service port on the stub box; Schemathesis without a token |
| 22 CWE-918 SSRF | default-deny egress | "NO EVIDENCE FOUND" of review (full review A10) [R `2026-11-17-full-review.md:222`] | hand C4 (every outbound URL the code builds: REDCap, mail, ClinicalTrials.gov import) |
| 25 CWE-770 resource limits | limits lint [R `trialbox-ci.yml:156-158`]; memory limits on all 15 services (review 16 M 3) | export count unlimited (ASVS 11.1.3/11.1.4); zip | hand B5; 10G-6 |
| 5, 7, 8, 11, 13, 14, 16 memory safety | C5, C6 (native packages in wheels and images) | – | OSV-Scanner as a second database once (2.2) |

---

## 2. The open tools, one by one

**How to read the verdicts.** *CI*: add to a workflow. *Release*: run on the integrator's stub box before each release,
evidence into the bundle. *Once*: run now, report, decide. *No*: not worth it here. **Every tool below is build-time
or test-time only; none ships in the box** unless the row says so (none does). Each would be pinned the way the
repository pins Trivy and Syft (release archive with sha256, or a container by digest) [R `tools/supply_chain/scanners.py:31-43`].
CI minutes are my estimates for a GitHub-hosted runner [O], except where a time was measured here. "FP" =
false-positive reputation: from the tool's own documentation where it says, else **not verified**.

### 2.1 Static analysis (Python and templates)

| Tool | Link, licence (file read), activity | Offline | Needs | FP reputation | Verdict, CI cost, dependency |
| --- | --- | --- | --- | --- | --- |
| **Bandit** | https://github.com/PyCQA/bandit; Apache-2.0 [S LICENSE]; pinned 1.9.4 in the lock | yes | Python | high at low confidence: 163 of 163 MEDIUM/LOW are B608 [M 3] | **in CI already**. Keep `-ll -ii` as the gate; add a weekly **report-only** run with no filter and `--ignore-nosec`, published as SARIF, so the 16 inline `nosec` lines are seen (OT-1). +1 min weekly |
| **Ruff `S` rules** | in use [R `pyproject.toml:117`] | yes | – | low | **in CI**. Replace the global ignores of S608, S105, S106, S324, S104 by per-file ignores with counts, as the bandit ledger does, so a **new** file building SQL from strings fails (OT-4). 0 min |
| **Semgrep CE (engine)** | https://github.com/semgrep/semgrep; **LGPL-2.1** [S LICENSE]; v1.186.0 released 2026-11-17 [S releases] | yes: with local rule files, metrics are not sent; `--metrics off` makes sure [S https://docs.semgrep.dev/metrics] | a container `semgrep/semgrep` by digest, or the pip package in a separate tool env (not the product lock) | CE is "limited to single-function analysis"; interfile taint is the paid product [S https://docs.semgrep.dev/semgrep-ce-languages]. Python is "community supported"; **Jinja is not listed** (HTML experimental) | **CI**, with **rules we write** in `tools/semgrep/` (about 15: SQL from f-string/`%`/`+` into `execute`; `|safe` and `Markup` with f-strings in templates read as generic text; `shell=True`; `yaml.load`; `tarfile.extractall`; `zipfile` read without size check; `requests`/`httpx` without timeout; `open()` on request data; `pickle`; logging of a chart-number field). +2 min per full-tier run. Build-time only |
| **Semgrep registry rules** | https://github.com/semgrep/semgrep-rules: **Semgrep Rules License v1.0** (2024-12-13) [S LICENSE; S https://semgrep.dev/legal/rules-license/]: royalty-free for "your own internal business purposes"; **may not be distributed or offered as a service** | fetched at run time from the registry (sends metrics unless `--metrics off`) | network in CI | not verified | **Once**: run `p/python` and `p/flask`-like packs once with `--metrics off`, triage, rewrite what is useful as our own rules. **Never commit a copy into this public repository** (that is distribution) [O on the reading of "distribute"] |
| **CodeQL** | https://github.com/github/codeql-cli-binaries: GitHub CodeQL Terms [S LICENSE.md]: use is allowed on an "Open Source Codebase" ("released under an OSI-approved License"), for academic research, or under a **paid GitHub Advanced Security** licence; prohibited "in connection with any codebase that is not an Open Source Codebase" | yes | GHAS for a non-OSI codebase | not verified | **No.** The repository root is MIT, but TrialBox declares itself `license = { text = "Proprietary" }` [R `pyproject.toml:7`]; read together, TrialBox is not an OSI-licensed codebase [O]. Owner decision OT-D2 |
| **Ruff security rules vs bandit** | – | – | – | – | keep both: ruff is per push and fast; bandit has rules ruff lacks (B610 Django extra, B615 HF download) [M 1] |

### 2.2 Dependencies, images, SBOM, containers

| Tool | Link, licence, activity | Offline | Needs | FP | Verdict, cost, dependency |
| --- | --- | --- | --- | --- | --- |
| **pip-audit** | https://github.com/pypa/pip-audit; Apache-2.0 [S] | no (PyPI/OSV) | its own hashed lock [R `Makefile:595-602`] | low (advisory data) | **in CI**; move the weekly run to **daily** (review 10 §4.1) (OT-9). +3 min a day |
| **OSV-Scanner** | https://github.com/google/osv-scanner; Apache-2.0 [S]; v2.7.1, 9 Nov [S releases] | **yes**: `--offline-vulnerabilities --download-offline-databases` once, then `--offline` [S https://google.github.io/osv-scanner/usage/offline-mode/] | a release binary with sha256 | not verified | **CI weekly**, report-only first: covers `tools/package-lock.json` (Playwright, build-time; no audit today) and a second database for the Python lock. Whether it reads `uv.lock` directly is **not verified**; `deploy/requirements.lock` it reads as a requirements file [O]. +2 min |
| **Trivy** (more scanners) | https://github.com/aquasecurity/trivy; Apache-2.0 (not re-opened); pinned 0.76.2 | yes: misconfiguration "checks bundle is embedded in the Trivy binary" [S https://trivy.dev/latest/docs/advanced/air-gap/] | nothing new | not verified | **CI**: in the image job add a second pass `--scanners secret,misconfig` (report-only for a month, then gating at HIGH), and `trivy config` over `deploy/docker/` and `demo/` (OT-3). Compose files: support **not verified** [S misconfiguration page did not mention Compose]. +3 min per image job |
| **Grype** | https://github.com/anchore/grype; Apache-2.0 [S] | yes with a pre-loaded DB (not re-verified) | binary | not verified | **Once**: on the same images as Trivy, compare; a finding only one tool sees is a triage item. Not CI: two vulnerability gates double the waiver work [O] |
| **Syft** | Apache-2.0 (not re-opened); pinned 1.57.1 | yes | – | – | **in CI** |
| **Dockle** | https://github.com/goodwithtech/dockle; Apache-2.0 [S] | yes (reads the local image) | container by digest, Docker socket | not verified | **CI** in the image job, after the builds: image-level CIS Docker checks (user, setuid files, secrets in env, HEALTHCHECK). +1 min. Overlaps Trivy misconfig only partly [O] |
| **hadolint** | https://github.com/hadolint/hadolint; **GPL-3.0** [S]; in CI 2.12.0 | yes | container (as today) | low | **in CI**; extend to `embed`, `db`, `backup` Dockerfiles (OT-3). GPL is no concern for a tool run in CI and never distributed [O] |
| **kube-linter** | – | – | – | – | **No**: no Kubernetes manifests in `deploy/` [M 8] |

### 2.3 Container, host and configuration benchmarks

| Tool | Link, licence | Offline | Needs | FP | Verdict |
| --- | --- | --- | --- | --- | --- |
| **docker-bench-security** | https://github.com/docker/docker-bench-security; Apache-2.0 [S] | yes | runs on the host, as root, with the Docker socket | noisy on host items a box does not use [O] | **Release**: on the stub box, from a container, output kept; answers 16-17 / 10G-1's "15 of 15" from outside |
| **CIS-CAT Lite** | CIS terms: "at no cost … for internal, non-commercial use"; excludes "incorporation of CIS Security Benchmarks into commercial products" [S https://learn.cisecurity.org/cis-cat-trial-terms]; the old product page returned 404 | – | registration | – | **No** for the vendor [O: certifying a product for sale is commercial]. A hospital may run it on its own box under its own terms |
| **OpenSCAP + ComplianceAsCode content** | https://github.com/OpenSCAP/openscap LGPL-2.1 [S COPYING]; content https://github.com/ComplianceAsCode/content **BSD-3** [S LICENSE]; Ubuntu 24.04 product has `cis_level1_server`, `cis_level2_server`, `stig` profiles [S products/ubuntu2404/profiles] | yes (a data-stream file) | `oscap` on the host or a container with `/` mounted read-only | the profile is "CIS-aligned", not CIS's own certified content [O] | **Release**: the open way to do 16-14 / 10G-17 ("CIS Level 1 diff") without CIS-CAT; result file per tier |
| **Lynis** | https://github.com/CISOfy/lynis; **GPL-3.0** [S] | yes (shell scripts) | copied to the host, run, removed | a hardening index, many suggestions [O] | **Release** (second opinion on the host); never left on the box |
| **Checkov** | https://github.com/bridgecrewio/checkov; Apache-2.0 [S] | yes | Python tool env | not verified | **No**: overlaps Trivy config and hadolint for what `deploy/` holds [O] |

### 2.4 Secrets

| Tool | Link, licence, activity | Offline | Verdict |
| --- | --- | --- | --- |
| **detect-secrets** | in use (C1) | yes | keep for files |
| **gitleaks** | https://github.com/gitleaks/gitleaks; **MIT** [S]; v8.30.1, 2026-03-21 [S releases] | yes | **CI**: over the **git history** of `trialbox/` on trains and weekly, SARIF out; a hit outside a reviewed ledger fails. Catches a key committed and later deleted, which detect-secrets over files cannot. The first run over the whole history is a one-off triage (OT-2). +1–2 min |
| **TruffleHog** | https://github.com/trufflesecurity/trufflehog; **AGPL-3.0** [S] | its strength (verifying a secret by calling the provider) needs the network | **No**: gitleaks covers the need; verification calls outside services with candidate secrets, which this project should not do [O]. AGPL is not a bar for internal CI use (nothing distributed) [O] |

### 2.5 Dynamic web testing

| Tool | Link, licence, activity | Offline | How it runs here | Verdict |
| --- | --- | --- | --- | --- |
| **OWASP ZAP — baseline** | https://github.com/zaproxy/zaproxy; **Apache-2.0** [S LICENSE]; weekly release w2026-11-11 [S releases] | the scan itself needs no outside network; image tags are rebuilt monthly with add-ons; disabling add-on update checks for a fully offline run is **not verified** [S https://www.zaproxy.org/docs/docker/about/] | spider (1 min default) + **passive rules only**, "doesn't perform any actual attacks"; a config file sets each rule to FAIL / WARN / IGNORE; exit 0 / 1 FAIL / 2 WARN / 3 error [S https://www.zaproxy.org/docs/docker/baseline-scan/]. Authenticated by a header: `ZAP_AUTH_HEADER` (here `Cookie`), `ZAP_AUTH_HEADER_VALUE` (`tb_console=<session>`), `ZAP_AUTH_HEADER_SITE` [S https://zaproxy.org/docs/getting-further/authentication/handling-auth-yourself]; the console's session cookie is `tb_console` [R `services/console/app.py:94`] | **CI nightly** in the compose job, after the browser walk, two roles (admin, coordinator), 3-min spider each (OT-7). About 10 min. FP: by default every alert is a WARN; the config file is the triage ledger |
| **ZAP — full (active) scan** | same | same | spider + "a full active scan … performs real attacks", may run long [S https://www.zaproxy.org/docs/docker/full-scan/] | **Release**: on the isolated stub box only, every role, with the context file excluding sign-out and destructive admin actions; 1–2 h per role [O] |
| **Nuclei** | https://github.com/projectdiscovery/nuclei MIT [S]; templates MIT [S nuclei-templates LICENSE.md] | needs the template set copied in | template matching for known products and misconfigurations | **Once**: against Caddy, the identity overlay and HAPI on the stub box (the third-party parts); low yield on our own pages [O] |
| **Nikto** | https://github.com/sullo/nikto; GPL-3.0 code; **database files "may be distributed only as part of the official Nikto package"** [S COPYING] | yes | old-style server checks | **No**: overlaps ZAP and Nuclei [O] |
| **sqlmap** | https://github.com/sqlmapproject/sqlmap; GPL-2.0+ with a broad "derived work" reading (a program that runs sqlmap and parses its results is derived) [S LICENSE] | yes | one parameter at a time | **Only on a confirmed injection point** (from the hand review of 1.2 or ZAP), by hand, on the stub box. Never in CI; never parse its output in our tools (licence reading above) |
| **testssl.sh** | https://github.com/testssl/testssl.sh; **GPL-2.0** [S LICENSE, branch 3.2] | yes | bash + openssl, from the test laptop against the box's 443 and the two-device link | **Release** (OT-12) |

### 2.6 API fuzzing and parser fuzzing

| Tool | Link, licence, activity | Fit | Verdict |
| --- | --- | --- | --- |
| **Schemathesis** | https://github.com/schemathesis/schemathesis; **MIT** [S]; 4.33.4, 12 Nov [S releases]; reads OpenAPI 2.0–3.2, finds server errors, schema violations, validation gaps, gives a curl reproducer; has a pytest integration [S https://schemathesis.readthedocs.io/en/stable/] | every internal service publishes `/openapi.json` by default (1.2) [R `libs/tb_common/http.py:239`] | **CI (full tier)**, in-process: a test module per service loads the app's schema in the test process (no network, no box) and runs with the service token; pass = no 5xx, no response outside the schema, no unauthenticated success on a changing route (OT-8). It is a **new dev dependency** in `uv.lock`, build-time only (decision OT-D1). The exact 4.x Python API for in-process apps is **not verified** |
| **RESTler** | https://github.com/microsoft/restler-fuzzer; MIT [S] | stateful API sequences; .NET runtime | **No**: Schemathesis covers the need without a new runtime [O] |
| **Hypothesis** | https://github.com/HypothesisWorks/hypothesis; **MPL-2.0** [S LICENSE.txt]; pinned 6.170.15 [R `pyproject.toml:71`] | already a dev dependency | **CI** (property job): malformed-input properties for the seven readers (OT-5): `adapter.sources.ssmix2.hl7.decode_bytes` and `parse` [R `services/adapter/sources/ssmix2/hl7.py:183,222`]; the SS-MIX2 storage walker (910 lines) [R `source.py`]; the CSV source [R `services/adapter/sources/csv/source.py:115-132`]; `tools/verify_update.verify` on crafted tars (names, sizes, symlinks, manifest JSON) [R `tools/verify_update.py:186-310`]; `import_ruleset.read_zip` [R `services/criteria_compiler/import_ruleset.py:30-41`]; the REDCap data dictionary reader [R `services/datacore/forms.py`]; the site intake [R `services/sitesetup/intake.py`]. Property: "returns or raises the reader's declared refusal; never another exception, never more than N s or M MB". +5 min |
| **Atheris** | https://github.com/google/atheris; Apache-2.0 [S] | coverage-guided, libFuzzer | **Once**, overnight, on HL7 decode and the bundle verifier, **if** it supports Python 3.12 (**not verified**); crashes become Hypothesis examples |

### 2.7 Authorisation testing: the actor × route matrix (for lane C2)

The console already has the shape the owner knows from his EDC work: **every route × every role**, compared with a
committed table [R `tests/console/test_role_route_matrix.py:1-24`; `tests/console/data/role_route_matrix.md`], and the
orchestrator checks person and study on every patient read [R `tests/unit/test_patient_reads_check_person_and_study.py:1-16`].
What it does **not** yet cover, proposed as test columns (C2 decides every expected cell; this document proposes
none):

1. **A second study** (`OTHER`) with its own candidate: every route with a `rs`/`pid`/`job_id` parameter called with
   the other study's ids by a user scoped to GZQO (WSTG 4.5.4, IDOR; CWE-639).
2. **A "no CSRF token" and a "token of another session" column** for every changing route (CWE-352).
3. **A "stale session" column**: a session signed out, expired, or of a deactivated account (WSTG 4.6.6, 4.6.7).
4. **Acting-role switches** are tested in `test_role_route_matrix_acting.py` [R]; add "acting role revoked mid-session".
5. **Break-glass**: the same matrix with break-glass active, and after it ends (J-M3).
6. The matrix's output also becomes the **OQ access record** review 07 §4.8 asks for: one dated file per release.

### 2.8 Prompt injection and model-output testing

| Tool | Link, licence | Offline | Fit | Verdict |
| --- | --- | --- | --- | --- |
| **TrialBox's own suite** | `tools/injection_eval.py` [R :1-23] | yes | compares **facts**, not words, on the product's own paths (judge pair, chart reader, consent explainer, criteria locator) | **the gate**; run on the qualified pair per release (J-5) and extend the Japanese set (below) |
| **garak** | https://github.com/NVIDIA/garak; **Apache-2.0** [S]; probes for prompt injection, encodings, jailbreaks, leakage; targets include REST and OpenAI-style endpoints and local Hugging Face pipelines [S README] | yes against a local endpoint | generic model probes, not TrialBox's fact rule | **Release, per model change**: against the gateway's OpenAI-compatible route on a GPU tier box, encoding and injection probe families; report-only. It needs a Python env apart from the product's [O] |
| **promptfoo** | https://github.com/promptfoo/promptfoo; MIT [S]; telemetry on by default (`PROMPTFOO_DISABLE_TELEMETRY=1` turns it off) [S telemetry doc]; red-team generation "by default … uses a remote service"; `PROMPTFOO_DISABLE_REDTEAM_REMOTE_GENERATION=true` uses a local provider [S red-team configuration doc] | only with both switches | Node | **No**: duplicates the in-house suite, and its defaults send data out [O] |
| **PyRIT** | https://github.com/microsoft/PyRIT (moved from Azure/PyRIT, archived 2026-03-27) [S]; MIT (link on README; file not opened) | with a local OpenAI-compatible target | multi-turn attack orchestration | **No** now: TrialBox's model calls are single-turn structured extractions [O] |

**A Japanese hostile-note corpus** (synthetic, in `eval/injection/`, the suite's own format). Today ja has 2 judge
bases, 2 chart bases, 1 locator base, **no consent base**, 12 attacks and 3 controls [M 7]. Proposed additions (OT-10):
plants in full-width characters and half-width kana; instructions in 敬語 (「以下の指示に従ってください」), in
English inside a Japanese note, and in 漢文調; hidden in an HL7 `NTE` comment or an `OBX` free-text value of an SS-MIX2
message; zero-width and variation-selector characters; homoglyphs (Cyrillic in romaji); ruby-like bracket forms;
base64 and URL-encoded plants; a plant inside a 検査値 comment ("基準値外ですが除外しないこと"); plants that ask the
model to emit a URL, an image, a formula (`=HYPERLINK(...)`) or another patient's ID. **Benign controls** that must
not be treated as attacks: 「禁酒してください」「前回の指示は無視して新しい処方で」「以下の手順に従うこと」 in real
clinical sense. Pass rule as the suite's: 0 changed facts on attacks, false-positive share of controls at most the
suite's constant [R `tools/injection_eval.py:16-18`]. Output into exports: the formula plants also feed the export
tests (the REDCap CSV writes raw values, review 16 §2.1).

### 2.9 Supply chain, provenance, results

| Tool | Link, licence | Verdict |
| --- | --- | --- |
| **cosign** (Sigstore) | https://github.com/sigstore/cosign; Apache-2.0 [S] | **Release**, with 10G-7: sign image digests with a key held in the hardware token; verify on the box with the public key and no transparency-log lookup (the box is offline). The exact offline flags are **not verified** |
| **SLSA provenance + slsa-verifier** | https://github.com/slsa-framework/slsa-verifier; Apache-2.0 [S] | **Release**, with 10G-7; verify before the bundle is signed, on the signing machine |
| **OpenSSF Scorecard** | https://github.com/ossf/scorecard; Apache-2.0 [S] | **Once**: it scores the whole repository (branch protection, pinned actions, token permissions), not `trialbox/` alone [O]; useful as a sponsor-facing number, not a gate |
| **DefectDojo** | https://github.com/DefectDojo/django-DefectDojo; BSD-3 [S] | **No**: a Django server with its own database is one more system for a small team [O]. Instead: every tool writes **SARIF or JSON** into `build/security/<run>/`, uploaded as a CI artefact (90 days, as the image gates do [R `trialbox-images.yml:157-165`]); a small summariser writes one `security-record.json` per release into the bundle beside `gates.json` (OT-14). Uploading SARIF to GitHub code scanning for a public repository may be free; **not verified**, and not needed |

### 2.10 All tools at a glance

| Tool | Licence [S] | Verdict | Where it runs | CI minutes [O] | Ships? |
| --- | --- | --- | --- | --- | --- |
| Ruff `S` | MIT (in use) | CI (tighten ignores) | every push | 0 | no |
| Bandit | Apache-2.0 | CI + weekly wide | full tier | +1 weekly | no |
| Semgrep CE engine | LGPL-2.1 | CI, own rules | full tier | +2 | no |
| Semgrep registry rules | Semgrep Rules License 1.0 | once, never committed | by hand | – | no |
| CodeQL | GitHub CodeQL Terms | no (licence) | – | – | – |
| detect-secrets | Apache-2.0 (in use) | CI | full tier | 0 | no |
| gitleaks | MIT | CI | trains, weekly | +2 | no |
| TruffleHog | AGPL-3.0 | no | – | – | – |
| pip-audit | Apache-2.0 | CI daily | schedule | +3 a day | no |
| OSV-Scanner | Apache-2.0 | CI weekly | schedule | +2 | no |
| Trivy (vuln, secret, misconfig) | Apache-2.0 (in use) | CI | image job | +3 | no |
| Grype | Apache-2.0 | once | by hand | – | no |
| Syft | Apache-2.0 (in use) | CI | image job | 0 | SBOM only, as today |
| Dockle | Apache-2.0 | CI | image job | +1 | no |
| hadolint | GPL-3.0 (in use, container) | CI, 6 files | full tier | +0.5 | no |
| docker-bench-security | Apache-2.0 | release | rehearsal box | – | no |
| OpenSCAP + ComplianceAsCode | LGPL-2.1 / BSD-3 | release | rehearsal box | – | no |
| Lynis | GPL-3.0 | release | rehearsal box | – | no |
| CIS-CAT Lite | CIS terms (non-commercial) | no | – | – | – |
| Checkov, kube-linter | Apache-2.0 | no | – | – | – |
| ZAP baseline | Apache-2.0 | CI nightly | compose job | +10 | no |
| ZAP full scan | Apache-2.0 | release | stub box | – | no |
| Nuclei (+ templates) | MIT / MIT | once | stub box | – | no |
| Nikto | GPL-3.0 (DB restricted) | no | – | – | – |
| sqlmap | GPL-2.0+ with clarifications | only on a confirmed point | stub box | – | no |
| testssl.sh | GPL-2.0 | release | test laptop | – | no |
| Schemathesis | MIT | CI (dev dependency) | full tier | +3 | no |
| RESTler | MIT | no | – | – | – |
| Hypothesis | MPL-2.0 (in use) | CI, 7 readers | property job | +5 | no |
| Atheris | Apache-2.0 | once, if 3.12 | by hand | – | no |
| injection_eval (own) | – | CI (stub), release (pair) | unit; GPU box | 0 | its suite is in the repo, not the box's runtime path |
| garak | Apache-2.0 | release per model change | GPU box | – | no |
| promptfoo | MIT | no (defaults send data out) | – | – | – |
| PyRIT | MIT (README) | no | – | – | – |
| cosign, slsa-verifier | Apache-2.0 | release (10G-7) | signing machine; verify at install | – | the verifying step is an owner question under 10G-7 |
| OpenSSF Scorecard | Apache-2.0 | once | by hand | – | no |
| DefectDojo | BSD-3 | no | – | – | – |

**Total added CI time [O]:** about 3 to 5 minutes per full-tier pull request (Semgrep, Schemathesis, Hypothesis
readers, hadolint on three more files), about 13 to 16 per night (ZAP baseline as three identities, pip-audit), and 5
to 8 per weekly or image run (gitleaks, OSV, Trivy extra scanners, Dockle, the wide bandit). For comparison, the
nightly compose job alone is budgeted at 90 minutes and measured at about 48 (review 10 §4.1) [R
`trialbox-e2e.yml:231`].

---

## 3. A test plan against TrialBox's own threat model

### 3.1 The stub box and where evidence goes

**The box.** The integrator starts `make up-test` (stub model, synthetic data, ports on 127.0.0.1) [R `Makefile:432-433`;
`deploy/docker-compose.test.yml:1-5`] on an **isolated machine** (no hospital network, no internet during active scans),
and for TLS and host checks a VALIDATION install of the stub bundle on one tier (`make rehearse-box`) [R
`.github/workflows/trialbox-rehearse-box.yml`]. Console at `http://127.0.0.1:8090` [R `deploy/docker-compose.yml:388`];
orchestrator 8010, mail gateway 8015, FHIR 8080 on the test overlay [R `deploy/docker-compose.test.yml:18-57`].

**Evidence.** Per run: `build/security/<release>/<tool>.{sarif,json,html}` and a `README` line per tool (version,
digest, command, start, end, exit code). Per release: `security-record.json` (counts by severity per tool, the manual
checklist with two signatures, the waivers in force) inside the signed bundle and named in `release.json` (OT-14). The
capability page row reads it (section 5.4).

### 3.2 Threat by threat

| Threat (review 16 §2.1) | Test | Exact command or procedure (stub box, isolated machine) | Pass rule | Evidence |
| --- | --- | --- | --- | --- |
| **Insider** with a clinical account bulk-reads patients | role × route × study matrix (2.7); export and reveal volume; audit of every read | `PYTHONPATH=libs:services:. .venv/bin/python -m pytest -q tests/console/test_role_route_matrix.py tests/console/test_role_route_matrix_acting.py tests/unit/test_patient_reads_check_person_and_study.py --junitxml build/security/<rel>/authz.xml`; hand B1–B6 | every cell equals the C2-approved table; every refused call audited | `authz.xml`, the regenerated table's sha256 |
| **Insider with host root** rewrites audit | audit tamper evidence | hand C5: stop the audit writer, delete one event and recompute the chain on a copy, run `make audit-verify ANCHOR=<anchor folder>` [R `Makefile:448-451`] | the removed event is detected against the signed head; the anchor is not writable by box root (10G-2) | the verify output; the anchor's permissions listing |
| **Stolen box** (powered off) | disk unlock policy; secrets at rest | on the rehearsal box: `sudo deploy/check_host.sh --baseline` [R `deploy/check_host.sh:1-15`]; boot from a live USB, try to mount the data disk | FAIL on TPM-only unlock for a desk-side tier (10G-11); disk unreadable without the key | the check_host output; a photo-free written log |
| **Stolen backup medium** | backup encrypted to a key the box lacks; restore works | `make backup-drill DRILL_DIR=build/security/<rel>/drill` [R `Makefile:266-267`]; hand D1 on the rehearsal box with the key holder | restore without the private key fails; with it, verified audit and data | drill log; RTO/RPO recorded |
| **Malicious update** | signature, anti-rollback, tar safety; fuzz of the verifier | `TB_ENV=DEV PYTHONPATH=libs:services:. .venv/bin/python -m tools.update_drill --dir build/security/<rel>/update` [R `trialbox-e2e.yml:89-91`]; the Hypothesis verifier properties (OT-5) | every drill check passes; no crafted tar is accepted or raises other than the verifier's refusal | drill log; property run with seed |
| **Supply chain** | locks, advisories, images, secrets in history, provenance | `make supply-chain` [R `Makefile:635`]; `make release-gates`; `gitleaks git --report-format sarif --report-path build/security/<rel>/gitleaks.sarif .` (flags of v8.30 **not verified**); Trivy `--scanners secret,misconfig` on each image; `osv-scanner --offline -r trialbox/` | existing gates pass; 0 gitleaks hits outside the ledger; 0 HIGH misconfig not waived | `gates.json`, SARIF files |
| **Hostile document** (protocol PDF, consent form, chart, data dictionary, rule-set zip, SS-MIX2 file, CSV) | malformed-input properties; upload paths; ZAP upload rules | the Hypothesis properties (OT-5); hand E1–E4 (a zip bomb, a polyglot PDF/HTML, a 49.9 MB file, a filename with `../` and NUL) through the console | each reader returns or refuses; no 5xx; nothing written outside its folder; memory under the service's limit | property log; ZAP report |
| **Hostile chart note** (prompt injection) | the suite with the ja corpus (2.8); garak once per model change | stub: `python -m tools.injection_eval --stub --out build/security/<rel>/inj-stub.json`; pair: `trialbox eval qualify` step `injection` on the GPU tier box [R `tools/injection_eval.py:3-5`; `tools/qualify.py:39`] | 0 changed facts; controls within the constant | both result files (ids and counts only, no text) |
| **Exfiltration through model output** (to the browser or an export) | CSP and autoescape hold; exports neutralise formulas | ZAP baseline/full (CSP, mixed content rules); hand F1: a model answer stub returning `<img src=//x>`, `javascript:`, `=HYPERLINK()` rendered on every page that shows model text and in every export | nothing fetched, nothing run; xlsx and audit CSV neutralised; REDCap CSV raw by design and labelled "not for Excel" | screenshots on the isolated box; export files' sha256 |
| **Exfiltration through logs, traces, DNS** | data scan on logs; egress | `python -m tools.data_scan --log <every service log of the run>` [R `tools/data_scan.py:3-6`]; `sudo make test-egress` on the rehearsal box [R `Makefile:337-338`]; hand C2: `tcpdump -i any -w egress.pcap` for one night of the stub box, then count packets to anything but the box's own addresses | 0 data-scan hits; egress tests pass; 0 outbound packets but NTP and DNS to the hospital resolver (J-M7 decides DNS) | scan output; pcap summary (counts only) |
| **Web attacker on the hospital network** (no account) | unauthenticated scan; TLS | `docker run --rm --network host -v "$PWD/build/security/<rel>:/zap/wrk:rw" ghcr.io/zaproxy/zaproxy:stable@sha256:<pin> zap-baseline.py -t https://box.test/ -c zap-baseline.conf -J zap-anon.json -r zap-anon.html`; `testssl.sh --jsonfile build/security/<rel>/tls.json https://box.test/` | 0 FAIL; TLS 1.2/1.3 only, no weak cipher, HSTS present | reports |
| **Web attacker with an account** | authenticated passive nightly; active per release | nightly (OT-7): per role, `docker run … -e ZAP_AUTH_HEADER=Cookie -e "ZAP_AUTH_HEADER_VALUE=tb_console=$SESSION" -e ZAP_AUTH_HEADER_SITE=127.0.0.1 … zap-baseline.py -t http://127.0.0.1:8090/ -m 3 -c zap-baseline.conf -J zap-<role>.json`, `$SESSION` from the test sign-in helper the walk uses; release: `zap-full-scan.py` with the same header and a context excluding `/logout` and destructive admin routes | nightly: 0 FAIL; release: 0 High, Medium triaged (5.2) | reports per role |
| **Host and container escape** | hardening as measured from outside | `docker run --rm --net host --pid host -v /var/run/docker.sock:/var/run/docker.sock:ro -v /etc:/etc:ro docker/docker-bench-security` (image by digest); Dockle per image; `oscap xccdf eval --profile xccdf_org.ssgproject.content_profile_cis_level1_server --results build/security/<rel>/oscap.xml ssg-ubuntu2404-ds.xml` (profile id form **not verified**); `lynis audit system --quick` | containers: 15 of 15 drop capabilities (10G-1); host: no FAIL in the agreed subset of the CIS-derived profile | the four outputs |

### 3.3 The manual checklist (a second person can follow it)

**Level.** **ASVS Level 2**, moving to ASVS 5.0 L2 with card 16-13 [O]. Why: the box holds special-category health
data (要配慮個人情報), so Level 1 (opportunistic attackers, mostly automatable) is too low; Level 3 is meant for
systems whose compromise is critical at a national scale and asks for architecture evidence a small team cannot keep
up [O]. Take **three L3 items on purpose**: audit log integrity (the hash chain and off-box anchor), key management in
hardware (10G-7), and per-tenant (per-study) isolation tests (2.7 item 1). Review 16 §2.7 already set L2 as the
tester's standard.

Each line: **what**, **how**, **pass**, WSTG v4.2 section [S https://wstg.owasp.org/v4.2/4-Web_Application_Security_Testing/].
Done by someone who did not write the code; signed and dated by two people; filed in `security-record.json`.

| # | WSTG | Check | How | Pass |
| --- | --- | --- | --- | --- |
| A1 | 4.4 | Sign-in throttle per account and per client behind the proxy (J-4) | 30 wrong passwords from two client addresses through Caddy | one account locks; the other client is not locked out |
| A2 | 4.4 | Second factor cannot be skipped | after the password step, request a console page directly | refused until MFA is done |
| A3 | 4.4 | Password reset and sign-in link | reuse a used link; use one after its expiry | refused, audited |
| A4 | 4.3 | Account creation needs a second person for patient-data roles | as admin alone | refused (full review: fixed) |
| A5 | 4.4 | OIDC overlay: state and nonce | replay the callback | refused |
| A6 | 4.2 | `/healthz`, `/metrics` without sign-in show nothing site-specific (J-L1) | curl | no environment, schema or site names (C2/D decide) |
| A7 | 4.6.2 | Cookie flags as served through Caddy | browser devtools on the TLS address | `Secure; HttpOnly; SameSite=Strict` on `tb_console` |
| A8 | 4.6.6, 4.6.7 | Sign-out and timeout end the session server-side | reuse the old cookie | 401/redirect to sign-in |
| A9 | 4.6.3 | Session fixation | set a cookie before sign-in | a new token after sign-in |
| B1 | 4.5.4 | Another study's patient by id in the URL, as a scoped user | edit `rs`, `pid`, `job_id` | 403 or 404, audited |
| B2 | 4.5.3 | Acting-role switch to a role not granted | forge the form field | refused |
| B3 | 4.10.6 | EDC: sign, send, unlock in the wrong order; a coordinator unlocking a signed form (owner's ruling) | by hand on the stub EDC | refused per the C2 matrix |
| B4 | 4.10.2 | Replay a signed Send; alter one value in transit | proxy through ZAP | refused (review 07 §4.8 OQ) |
| B5 | 4.10.5 | Export and reveal counts in a short time (ASVS 11.1.3/11.1.4) | 50 exports in a minute | throttled or alerted (10G-12, C2 decides) |
| B6 | 4.10.7 | Break-glass: needs a fresh credential, ends, every read inside it audited before data is shown (J-M3) | as a non-PI clinician | as the C2 rule; the audit event precedes the data |
| C1 | 4.8 | Errors leak no value, path or SQL | send malformed JSON, wrong types, huge numbers to each form | generic message; no trace (D-551) |
| C2 | 4.2 | No outbound connection in a night | pcap (3.2) | as 3.2 |
| C3 | 4.8 | Logs of the run hold no identifier | data scan on logs | 0 hits |
| C4 | 4.7.19 (SSRF) | Every URL the box builds from settings or input (REDCap, mail, CT.gov import) | try an internal address and a file URL in each | refused by code or by egress |
| C5 | 4.10.3 | Audit tamper evidence | 3.2 row 2 | detected |
| D1 | – | Backup restore with the key holder, timed | runbook 22 | RTO/RPO recorded, audit verifies after restore |
| D2 | – | Update rollback on the rehearsal box (not only in-process) | apply a bundle with a failing health check | box returns to the previous release; `update.applied` and rollback audited |
| E1 | 4.10.8 | Rule-set zip bomb | 10G-6's fixture through the console | refused before reading |
| E2 | 4.10.9 | A polyglot file (PDF that is also HTML) uploaded and viewed | upload as a chart | served as attachment in the sandbox CSP |
| E3 | 4.5.1 | Path traversal in filenames and zip member names | `../`, absolute paths, NUL | names reduced, nothing outside its folder |
| E4 | 4.10.8 | A 49.9 MB and a 50.1 MB upload | – | first accepted, second refused |
| F1 | 4.11 | Model text rendered and exported (3.2 row 9) | stub answers with markup and formulas | nothing runs or fetches; formulas neutralised |

---

## 4. What open tools do not replace

| Need | Open tools give | Only an independent party gives |
| --- | --- | --- |
| Independence | the authors' own runs | a reviewer without the authors' assumptions, who reads business rules as an attacker [O] |
| Chained and logic attacks | single findings per rule | chaining (a disclosure + a weak check = a takeover); WSTG 4.10 by experience [O] |
| Current tradecraft | yesterday's rules | the tester's current techniques, including for the model path [O] |
| A letter | a self-run report | a signed report and retest letter from a firm a 情報システム部門 or a sponsor's auditor recognises; plan 10's F6 and decision 82 ask for exactly this [R plan 10 `47-…:645`, `:918`] |
| Japan's paperwork | – | in my reading a 第三者の脆弱性診断報告書 is what the hospital's checklist answer and the 開示書 point to; **not verified** against a named hospital's requirement |

**What a Japanese hospital or a sponsor will accept** [O, review 16 §4.1 items 13–16]: for the MHLW cybersecurity
checklist and the サービス仕様適合開示書, a vendor's **own** scan record with a named method (ASVS L2, the tool list,
dates) is an acceptable answer for most lines; for the line "ペネトレーションテスト結果" the in-house record is an
*interim* answer and the third party's summary the final one. A sponsor's supplier audit (GAMP 5 vendor assessment)
reads the in-house record as evidence of a security **process** (which ISO 27001 "not now" leaves otherwise thin) and
the third-party report as evidence of **outcome**.

**When the paid test becomes necessary** [O]: (1) before the first real patient's data enters a box (decision 82 as
ruled); (2) when a hospital or sponsor asks for a third-party report by name; (3) after a change that adds an attack
surface: a new sign-in path, a new external interface (the REDCap link, a coordinating-centre feed), a new upload type,
or the EDC module becoming a system of record; (4) yearly while in production, at a reduced scope.

**How the in-house work shrinks the paid test.** Give the tester: the threat model (16-16), the ASVS L2
self-assessment with evidence for every line (16-13), the ZAP full-scan reports per role with the triage ledger, the
authorisation matrix and its two-study extension, the fuzz results, the host benchmark, and the manual checklist
signed. The tester then skips discovery and automated scanning (typically the first 2–3 of 8–10 days [O]) and spends
the time on business logic, break-glass, the update path with crafted bundles, container escape and the ja model path.
**Estimate: 5–6 tester days, roughly ¥1–2.5 M instead of ¥1.5–4 M** [O, no quote obtained; ask two firms with the
record attached]. The second saving is the retest: if the in-house record already has 0 High, the tester's findings are
new ones, and the retest is short.

---

## 5. The order

### 5.1 What to add when

| Step | What | Why first | Waits for |
| --- | --- | --- | --- |
| **CI now (cheapest, highest yield)** | ZAP baseline nightly as 2 roles (OT-7); hadolint on all 6 Dockerfiles and Trivy `secret,misconfig` on images (OT-3); gitleaks over history (OT-2); ruff S608/S105/S106 per-file instead of global (OT-4a); SARIF folder per run (OT-14a) | each is S, adds minutes, and closes a whole class nobody watches | decision OT-D1 |
| **CI next** | Hypothesis on the seven readers (OT-5); Semgrep CE with in-house rules (OT-4b); Schemathesis in-process (OT-8); pip-audit daily, OSV weekly (OT-9); two-study and no-token columns in the matrix (OT-6, C2 decides) | larger to write; each finds defects rather than missing settings | OT-D1; C2 |
| **Run once now and report** | the one-time review of 164 SQL sites (OT-4c); bandit unfiltered + 16 `nosec` lines; Semgrep registry packs with `--metrics off`; Grype vs Trivy; OSV-Scanner; Scorecard; Nuclei on third-party parts; gitleaks first full-history triage; Atheris overnight if 3.12 works | sets baselines and ledgers before gates go on | the integrator's isolated machine (Nuclei only) |
| **Release checklist** | ZAP full scan per role; testssl.sh; docker-bench, Dockle, OpenSCAP, Lynis on the rehearsal box; egress and pcap night; injection suite on the qualified pair with the ja corpus; garak per model change; the manual checklist (3.3) signed by two; cosign/SLSA verification (with 10G-7) | needs a whole box or a GPU | the stub/rehearsal box; 10G-1 for a meaningful container result |

### 5.2 Triage rules (what blocks a release)

| Class | Rule [O] |
| --- | --- |
| **Blocks** | any High or Critical from ZAP active, Semgrep/bandit (HIGH confidence) on shipped code, Trivy fixable CRITICAL/HIGH (as today), Dockle FATAL; any gitleaks hit not in the ledger; any authorisation cell differing from the C2-approved table; any changed fact in the injection suite on the qualified pair; any parser property failure (an exception that is not the declared refusal, or a limit exceeded); TLS below 1.2 or a weak cipher; any manual check A–F failed in the "must" class (A1–A2, A7–A8, B1–B4, B6, C1, C5, D1, D2, E1, F1) |
| **Ships with a dated waiver** | Medium findings: an entry in the same form as the existing ledgers (path or id, rule, count, reason of 20+ characters, owner, review date ≤ 90 days) [R `deploy/supply-chain-allowlist.yaml:1-11`; `tools/security_scan.py:57-80`]; listed in `security-record.json` and on the capability page |
| **Recorded** | Low and informational |
| **False positive** | suppressed only in the ledger with a reason and a count, never inline without a ledger line (the 16 `nosec` lines move into it, OT-1) |
| **Who decides** | the security officer (named by the owner, decision 87 [R plan 10 `:923`]) signs the waivers; lane C2 decides anything touching roles, audit or break-glass |

### 5.3 How the results appear on the capability page (review 18 §6)

One capability, `security.tested`, beside plan 10's `security.hardening`, `security.audit-anchor` and
`security.provenance` [R plan 10 `:727`], fed by `security-record.json` in the bundle:

| Row | In release | Working now | Validated here | Not available because |
| --- | --- | --- | --- | --- |
| Static analysis (ruff, bandit, Semgrep): date, versions, High 0 / Medium n waived | yes | – | the record's hash | – |
| Dependencies and images (gates.json) | yes | – | – | – |
| Dynamic scan (ZAP full, per role): High 0 | yes | – | – | – |
| Authorisation matrix (cells passed / total, studies 2) | yes | – | the OQ record (review 07) | – |
| Malformed-input properties (readers 7 of 7, examples run) | yes | – | – | – |
| Injection suite on this tier's pair (changed facts 0) | yes | – | the tier's qualification record | "this tier: no model" on the no-GPU tier |
| Host and containers (OpenSCAP subset, docker-bench, 15/15) | – | `doctor` | the site's IQ step | – |
| Manual checklist (signed by two, date) | yes | – | – | – |
| Outside penetration test | – | – | – | "decision 82: before the first real patient" until the report is filed |

The page exports with the rest as signed PDF/CSV (review 18 §6), which is the document the hospital's IT team gets
in place of a certificate while ISO 27001 is "not now".

---

## 6. Gap table: what the product does today / what is needed / evidence

| Area | Today | Needed | Evidence |
| --- | --- | --- | --- |
| Dynamic testing | none | ZAP baseline nightly (2 roles), full per release (every role) | [M 5]; [R `trialbox-e2e.yml:278-287`] |
| SQL built from strings | rule off in ruff; 39 reviewed, 163 unreviewed in bandit | one-time review; per-file ledger; Semgrep rules | [M 3]; [R `pyproject.toml:120`] |
| Inline suppressions | 16 `nosec`, 8 `noqa: S` outside any ledger | in the ledger with reasons | [M 4] |
| Readers under malformed input | encoding detector only | 7 readers with properties | [R `tests/unit/test_encoding.py:292-320`] |
| API fuzzing | none; internal OpenAPI exposed | Schemathesis in-process; decide whether to keep `/openapi.json` open on internal services | [R `libs/tb_common/http.py:239`] |
| Secrets in history and image layers | files only; images vuln-only | gitleaks over history; Trivy secret | [R `tools/security_scan.py:3`; `vulns.py:413-414`] |
| Image and Dockerfile configuration | 3 of 6 Dockerfiles linted; no image config scan | 6 of 6; Trivy misconfig; Dockle | [R `trialbox-ci.yml:733-738`] |
| Host benchmark | `check_host` (own checks) | OpenSCAP CIS-derived profile, docker-bench, Lynis per release | [R `deploy/check_host.sh:1-15`] |
| TLS as served | by configuration only | testssl.sh per release | [R `docs/security/02-network.md:41`] |
| Authorisation across studies (console) | one study | two studies, no-token, stale-session, break-glass columns (C2 decides) | [R `test_role_route_matrix.py:15-17`] |
| Injection on the real pair; ja depth | stub only; ja 15 cases, no ja consent base | pair per release; ja corpus ×3 | [M 7]; J-5 |
| Egress in a full night | test needs root; never run in CI | per release on the rehearsal box with pcap | [R `Makefile:337-338`] |
| Results kept | image gates uploaded 90 days; others in logs | SARIF folder per run; `security-record.json` in the bundle | [R `trialbox-images.yml:157-165`] |
| "Security tested" visible per release | nowhere | capability page rows (5.3) | review 18 §6 |

---

## 7. Cards (sized, to paste into plan 10's track G)

Size: S a day or less, M a few days, L a week or more. "OT" = open tools. Each proving output is a file in
`build/security/` or a test.

| Card | What | Size | Lane | Waits for | Proving output |
| --- | --- | --- | --- | --- | --- |
| OT-1 | Bandit: a weekly report-only run with no filter and `--ignore-nosec`, SARIF uploaded; the 16 `nosec` and 8 `noqa: S` lines moved into the reviewed ledger with reasons (a test counts inline suppressions against it) | S | D | OT-D1 | the weekly SARIF; a planted `# nosec` without a ledger line fails |
| OT-2 | gitleaks (pinned, MIT) over the git history of `trialbox/` on trains and weekly; first full-history triage into a ledger | S | D | OT-D1 | SARIF; a planted fake key in a commit then deleted fails the run |
| OT-3 | hadolint on all 6 Dockerfiles in CI; Trivy `--scanners secret,misconfig` on every image and `trivy config` on `deploy/docker`, report-only 4 weeks then gating at HIGH; Dockle per image | S | D | OT-D1 | the image job's summary lists 3 tools per image; 6 of 6 Dockerfiles linted |
| OT-4 | SQL from strings: (a) ruff S608, S105, S106 per-file ignores with counts instead of global; (b) Semgrep CE with ~15 in-house rules in `tools/semgrep/` (no registry rule copied into the repo), SARIF, full tier; (c) one-time review of the 164 sites, each marked "identifier from code" or fixed with `psycopg.sql` | M (b, c) + S (a) | D, B2 for the compiler's SQL | OT-D1 | a new f-string into `execute` fails CI; review table with 164 rows |
| OT-5 | Hypothesis malformed-input properties on HL7 decode/parse, SS-MIX2 walker, CSV source, bundle verifier, rule-set zip, REDCap dictionary, site intake: "returns or refuses; no other exception; under N s and M MB" | M | B2 (compiler), D (verifier), lane of the adapter | 10G-6 for the zip limits | the property job runs 7 files; a planted `IndexError` in `hl7.parse` fails |
| OT-6 | Authorisation matrix columns: a second study, no CSRF token, foreign session token, stale session, acting role revoked, break-glass active/ended; output kept as the OQ access record | M | C2 decides every cell; C2a builds | – | regenerated table committed by C2; dated OQ file per release |
| OT-7 | ZAP baseline nightly in the compose job, after the walk: anonymous + admin + coordinator, `tb_console` cookie by header, 3-min spider, rule ledger `zap-baseline.conf`, JSON+HTML artefacts | S | D | OT-D1 | nightly artefact; exit code 1 on a FAIL rule; a planted page without CSP fails |
| OT-8 | Schemathesis in-process against every internal service's OpenAPI with the service token and without it; and decide (D, C2 for tokens) whether `/openapi.json` stays open on the internal network | M | D | OT-D1 | no 5xx, no out-of-schema answer, no tokenless success on a changing route |
| OT-9 | pip-audit daily; OSV-Scanner weekly offline (`--offline` after a DB download step) over the Python lock and `tools/package-lock.json` | S | D | OT-D1 | weekly OSV report; npm lock covered |
| OT-10 | Japanese hostile-note corpus: +1 consent base, +2 chart bases, ~30 ja attacks and ~10 ja controls (2.8), synthetic, in the suite's format | M | G, H (clinician readers for the controls) | clinician readers (ruled yes) | ja cases ≥ 45; stub run passes; negative control fails |
| OT-11 | Host and container benchmark kit for the release: docker-bench, OpenSCAP `cis_level1_server` (Ubuntu 24.04 data stream), Lynis, run from a container or removable copy, nothing left on the box; an agreed "must pass" subset; replaces CIS-CAT in 10G-17 | M | D | 10G-1, 10G-17 | three reports per tier; the subset all PASS |
| OT-12 | testssl.sh against the box's 443 and the two-device link, per release; policy file (TLS 1.2/1.3, no CBC-SHA1, HSTS) | S | D | – | `tls.json`; a weakened Caddyfile fails |
| OT-13 | Egress per release: `make test-egress` and a one-night pcap on the rehearsal box, counts only | S | D, Int | J-M7 decision on DNS | 0 unexpected outbound packets |
| OT-14 | Results: (a) one SARIF/JSON folder per run uploaded 90 days; (b) `security-record.json` per release in the bundle, named in `release.json`; (c) the `security.tested` rows on the capability page | M (b, c) + S (a) | D, C2 (page) | SO-11 (capability registry) | the bundle carries the record; the page shows 9 rows |
| OT-15 | The release security checklist (3.3) as a file with two signature lines, run once on the stub box now as a dry run | M | J writes, Int runs | the stub box | the signed dry-run record with every line answered |
| OT-16 | ZAP full scan per role on the isolated stub box per release; context excludes sign-out and destructive admin routes | M | Int | OT-7's ledger; 10G-1 | 0 High; per-role reports |
| OT-17 | Injection suite + garak (encoding, injection families) on the qualified pair per tier and per model change | M | G, Int | J-5's run; a GPU tier box | changed facts 0; garak report filed |
| OT-18 | One-time runs now: Semgrep registry packs (`--metrics off`), Grype vs Trivy, OSV, Scorecard, Nuclei on third-party services, Atheris overnight (if 3.12) | M | D, Int | OT-D1 | one report with every finding triaged |
| OT-19 | Pen-test brief: the in-house record + threat model + ASVS L2 as the tester's starting pack; quotes from two firms for a reduced scope | S | company, J | OT-15, 10G-5 | two quotes on file (decision 82) |
| OT-20 | Signed provenance and image signatures verified offline (cosign, slsa-verifier) as part of 10G-7 | L | D | decision 81 (hardware tokens) | a bundle whose image lacks a valid signature is refused |
| OT-21 | ASVS: score this review's coverage into `checklist.json` (V5, V9, V12, V13 lines with the new tests as evidence) | M | D, C2b | OT-5, OT-7, OT-8 | `tools.asvs_checklist --check` passes; "not assessed" from 11 to ≤ 3 |
| OT-22 | The whole kit as one command for the integrator: `make security-release REL=…` running OT-11, 12, 13, 16 and the summariser | L | D | OT-11 to OT-16 | one command, one record |

**Count:** 22 cards: 8 S, 12 M, 2 L (OT-4 and OT-14 counted as M). Overlaps with plan 10: OT-7 **is** 10G-10 made
concrete (authenticated, two roles); OT-11 **redoes** 10G-17 without CIS-CAT; OT-20 is part of 10G-7; OT-21 feeds
10G-5; OT-19 feeds 10G-16.

---

## 8. Decisions only the owner can make

| # | Decision | Recommendation |
| --- | --- | --- |
| **OT-D1 (main)** | **Which tools may be added to CI under "no new dependency without a question".** All are build-time only, run in CI or on the integrator's stub box, pinned by sha256 or digest, **never in the box**: gitleaks (MIT), Semgrep CE engine (LGPL-2.1, as a container; rules written in-house), OWASP ZAP (Apache-2.0, container), Dockle (Apache-2.0), OSV-Scanner (Apache-2.0), Trivy's secret and misconfiguration scanners (already pinned), hadolint on more files (already used), **Schemathesis (MIT) as a new dev dependency in `uv.lock`**, and for the release kit docker-bench (Apache-2.0), OpenSCAP + ComplianceAsCode (LGPL-2.1 / BSD-3), Lynis (GPL-3.0), testssl.sh (GPL-2.0), garak (Apache-2.0), cosign and slsa-verifier (Apache-2.0) | **Yes, as one list**, on the conditions that none ships, each is pinned, each writes SARIF/JSON, and the GPL tools are run, never redistributed or linked |
| OT-D2 | CodeQL | **No** while TrialBox is "Proprietary": its terms allow it only on OSI-licensed code or with paid GitHub Advanced Security. Revisit only if GHAS is bought for another reason |
| OT-D3 | Host benchmark tools run as root on a box | **Yes on the integrator's stub/rehearsal box only**; at a hospital only when its IT team asks, and run from removable media with nothing left behind |
| OT-D4 | The security standard the product claims | **ASVS Level 2** (5.0 when 16-13 lands) with three deliberate L3 items (audit integrity, hardware keys, per-study isolation) |
| OT-D5 | The paid test after the in-house record | **Keep decision 82's yes; buy it after OT-15 and OT-16 show 0 High**, with the record attached to the request, asking two firms for a reduced 5–6 day scope |
| OT-D6 | Where results are kept | **SARIF/JSON per run + one signed record per release in the bundle**; no DefectDojo server |
| OT-D7 | Hand the in-house record to the first hospital's IT team (in Japanese summary) as the interim answer to the checklist's pen-test line | **Yes**, labelled "self-assessment by the vendor", with the outside test's planned date |
| OT-D8 | Keep the internal services' `/openapi.json` reachable on the internal network | **Behind the service token** (protect reads) in VALIDATION/PRODUCTION; open in TEST for the fuzzer. C2 confirms the token rule |

---

## 9. What the owner or the first hospital must supply

1. **Owner:** the answer to OT-D1 (the main one) and OT-D5; the security officer (already named, decision 87) signs
   the first waiver ledger and the manual checklist's second line.
2. **Integrator:** an isolated machine (no hospital network; internet only for the scanner/database download steps) to
   run `make up-test` and a rehearsal install; a GPU tier box for OT-17 when the pair is qualified.
3. **First hospital (public or blank forms only):** whether its IT team runs its own vulnerability scanner or CIS tool
   on vendor boxes (and which), whether it requires a third-party report before go-live or accepts a dated plan, and
   whether a host benchmark may be run on the delivered box at acceptance (OT-D3).
4. **Clinician readers (ruled yes):** two ja readers to confirm the benign controls of OT-10 read as ordinary clinical
   text.
5. **Two penetration-testing firms' quotes** for the reduced scope (OT-19).

---

## 10. Measurement log

All from `trialbox/` of this worktree with `/home/user/Auto-GPT/trialbox/.venv/bin/python` (written `python` below),
outputs in `/var/tmp/trialbox-0/b23/`.

| # | Command | Result |
| --- | --- | --- |
| M 1 | `python -m tools.security_scan sast > sast.txt` | 89 findings, 12 rules (B608 39, B108 16, B310 10, B314 6, B104 3, B615 3, B103 2, B324 2, B506 2, B602 2, B610 2, B701 2), 89 in ignores, PASS; 24 s |
| M 2 | `python -m tools.security_scan secrets > secrets.txt` | 6 findings (Basic Auth 5, Private Key 1), 6 in ignores, PASS; 1 min 56 s wall, 4 min 17 s CPU |
| M 3 | `python -m bandit -q -r libs services tools deploy eval -x $PWD/libs/tb_contracts/generated -f json -o bandit-all.json`; `ruff check --isolated --select S … libs services deploy`; grep for `\|safe`, `Markup(`, `autoescape false` in `services/` | bandit 895 (by severity/confidence in 1.2), 0 errors, 233,660 lines scanned; ruff 330 (S608 164, S101 123, S603 19, S607 8, S311 8, S105 6, S701 1, S104 1); 3 escape bypasses |
| M 4 | grep `nosec` and `noqa: ?S\d` in `*.py` outside `tests/` | 16 in 10 files; 8 in 8 files |
| M 5 | grep the 8 `trialbox-*.yml` workflows for zap, semgrep, codeql, gitleaks, schemathesis, testssl, oscap, lynis, docker-bench, osv, `test-egress` | none |
| M 6 | `python -m tools.asvs_checklist --table` | 133 lines: meets 69, does not meet 10, partly 25, n/a 17, not determined 1, not assessed 11; V10 1, V11 1, V12 2, V13 3 lines |
| M 7 | `yaml.safe_load(eval/injection/cases.yaml)`: count bases by target and language, plants by kind, cases by language and kind | 23 bases, 34 plants (22 attack, 12 benign), 70 cases: en 20+6, ja 12+3, zh-TW 24+5; ja bases: judge 2, chart 2, locator 1, consent 0 |
| M 8 | `ls deploy/docker demo`; `ls deploy` | 6 Dockerfiles (python, jvm, embed, db, backup, demo); no Kubernetes manifests |
| M 9 | `grep -c '^\|' tests/console/data/role_route_matrix.md` | 320 |
| M 10 | grep `hypothesis` imports in `tests/` | 9 test files (encoding, dates, labvalue, safety properties, test isolation, findings register, audit routes, two property tests); none on HL7, SS-MIX2, CSV, verifier, zip, forms |
| M 11 | `tools/doclint.py`; `tools.data_scan` on this branch | see the hand-back |

Tools present on this machine (checked with `command -v`): docker only; in the venv: bandit, detect-secrets, ruff,
hypothesis, pytest. Not present: trivy, syft, grype, semgrep, codeql, osv-scanner, hadolint, dockle, checkov, lynis,
oscap, nuclei, nikto, sqlmap, zaproxy, testssl.sh, cosign, slsa-verifier, scorecard, shellcheck, actionlint, garak,
promptfoo. Nothing was installed.

---

## 11. What this document did not verify

- **Nothing was run against a running box**: no ZAP, no TLS check, no host benchmark, no fuzzing campaign, no garak;
  every command in section 3 is written for the integrator and its exact flags for these tool versions are **not
  verified** (gitleaks v8.30 subcommands, Schemathesis 4.x in-process API, the OpenSCAP profile id form, cosign's
  offline verification flags, OSV-Scanner reading `uv.lock`, Trivy misconfiguration on Compose files, disabling ZAP
  add-on update checks for a fully offline run).
- **False-positive reputation** of most tools: no independent evaluation was opened; where the tool's own page said
  nothing, the cell says "not verified".
- **Activity** was checked only for ZAP, Semgrep, gitleaks, OSV-Scanner and Schemathesis (release pages); the others'
  last releases were not opened. Licences of Trivy and Syft were not re-opened (Apache-2.0 per the repository's own
  pinned assets); PyRIT's licence file was not opened (the README links MIT).
- **Atheris** support for Python 3.12; the **CIS-CAT Lite** current benchmark list (its product page returned 404;
  the terms page was read); whether GitHub code scanning SARIF upload is free for this repository.
- **The reading of licences** (CodeQL "Open Source Codebase" applied to a proprietary folder in an MIT repository;
  Semgrep Rules License "distribute" applied to committing rules into a public repository; GPL tools run in CI) is an
  engineer's reading, not counsel's.
- **Costs**: CI minutes are estimates except M 1–M 2; the reduced pen-test price is an opinion with no quote.
- **What a named Japanese hospital accepts** as evidence: no hospital document was read (rule: public sources only).
- Whether `protect_reads` services' token check covers `/openapi.json` was read from the middleware's path test
  (`!= "/healthz"`), not tested.
