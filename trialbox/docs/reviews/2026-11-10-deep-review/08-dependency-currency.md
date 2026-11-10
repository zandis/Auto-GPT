# TB-DR-08 Library and component currency

| Field | Value |
| --- | --- |
| Date | 2026-11-10 |
| Code read | `origin/master` ca8f287 (the deep-review branch); PR #78 head 417d70e7 for the jar pins only |
| Method | Every pin was listed from `uv.lock` (202 entries, 201 third-party), `deploy/requirements.lock` (73 packages, the runtime image), `pyproject.toml`, `deploy/docker/*.Dockerfile`, `demo/Dockerfile`, `deploy/pgbackrest/Dockerfile`, every `deploy/docker-compose*.yml` and `deploy/topology_a/podman-compose.yml`, `tools/fetch_jvm_deps.sh` and the translator `pom.xml`, `tools/fetch_fhir_packages.py`, `tools/jpcore_rules.py`, `tools/fetch_fonts.py`, `tools/vendor/`, `services/console/static/`, `models/registry.yaml`, `tools/pin_model.py`, `tools/supply_chain/scanners.py`, `services/rc_bridge/client.py` and the five `.github/workflows/trialbox-*.yml`. Each pin was then looked up online. |
| What was run | PyPI JSON API for all 201 packages (latest stable, upload dates, licence); OSV `querybatch` for all 201 PyPI pins and for the 103 resolved CQL-translator jars (master pom and PR #78 pom, resolved with `mvn dependency:list` into my scratch folder); `pip-audit 2.9.0` (from the repo's hashed `pip-audit.lock`, in a scratch venv) on `deploy/requirements.lock` and the repo's `pip-audit-gate`; `uv lock --check`; `python -m tools.supply_chain lock-check` and `allowlist-check`; Docker Hub tag API and the registry v2 API (manifests and image configs: OS release, `PG_VERSION`, `JAVA_VERSION`, `CUDA_VERSION`, `TORCH_CUDA_ARCH_LIST`); Maven Central metadata; endoflife.date (Python, PostgreSQL, Temurin, Alpine, Debian, Ubuntu, Caddy); `git ls-remote --tags` for vLLM, Caddy, Authelia, pgvector, PGroonga, pgBackRest, cqframework, org.hl7.fhir.core and the seven GitHub Actions; packages.fhir.org and the npm registry for FHIR packages; the Hugging Face API (model metadata, files, commit history); the Alpine APKINDEX for pgBackRest; `raw.githubusercontent.com` for the Actions' `action.yml` runtime. Evidence files: the reviewer scratch folder `scratchpad/dep-currency/` (not in the repo) (`pypi.json`, `pip-audit.json`, `mvn-master/deps.txt`, `mvn-pr78/deps.txt`, `mvn-hits.json`). |
| What was not run | No Docker pull or build, no Trivy or Syft scan (the image findings are taken from `deploy/security/known-image-findings.md`, dated 2026-11-10); `make lock-sbom` and `make licences` (they download Syft/Trivy and build an env; the licence data here comes from PyPI metadata). No GPU, so the vLLM/CUDA rows are by image metadata, not by a run. `api.github.com` is refused for repositories not attached to this session (HTTP 403 "GitHub access to this repository is not enabled"), so GitHub release notes and dates of vLLM, Caddy and Authelia were not read; tags came from `git ls-remote`, dates from Docker Hub. Not verified online (training knowledge, marked in the rows): the GitHub-hosted runner Node 20 retirement, the Debian 13 PostgreSQL major, the Groonga and Temurin licences, the REDCap release lines, the DuckDB 2.0 change list. No test suite run (not owned). |

## 1. Summary

The Python side is in very good shape: 176 of 201 locked packages are at the latest stable release, OSV reports no advisory on any of the 201 pins, and `pip-audit` on the runtime lock is clean. The lock checks pass. Third-party images are digest-pinned, except vLLM.

The risk sits outside the Python lock: in the JVM jars, in the GPU serving images, in the model weights and in the build tools.

Counts: **Blocker 0, Critical 1, High 7, Medium 10, Low 10** (28 findings).

Top 5:
1. **DEP-001 Critical (registered CR-045, in PR #78)**: the CQL translator ships 20 vulnerable jars, one CRITICAL (XXE in HL7 FHIR core utilities 6.9.4.1) and many HIGH. PR #78 fixes all but three moderate ones and is untested.
2. **DEP-003 High (new)**: the DGX Spark compose file pins a vLLM image built for the DGX **Station** (`TORCH_CUDA_ARCH_LIST=10.3a`), not for GB10 (sm_121). The Japan Spark benchmark would start on the wrong build.
3. **DEP-007 High (new)**: the judge's weights repository (`nvidia/Gemma-4-26B-A4B-NVFP4`, last change 2026-05-11) carries an older chat template. Google fixed the Gemma 4 chat template on 2026-07-15 (null handling, reasoning preservation, turn tags). No `--chat-template` override is set.
4. **DEP-008 High (partly registered CR-097)**: the verifier comes from a personal Hugging Face account (`cyankiwi/Qwen3.5-9B-AWQ-4bit`) whose history was squashed on 2026-07-21; registry `revision` and `sha256` are null.
5. **DEP-006 High (new)**: the build pins uv 0.11.32, which has CRITICAL advisory GHSA-hq85-5cpj-mr62 (compromised CA root in its bundled trust store; fixed in 0.13.4).

## 2. Findings

### 2.1 JVM components (CQL translator, HL7 validator, HAPI, JRE)

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
|---|---|---|---|---|---|---|
| DEP-001 | Critical | The CQL translator classpath (`cql-to-elm-cli` 5.4.0 and 102 transitive jars, copied into `trialbox-jvm` and the demo image) has 20 vulnerable jars on master. Worst: `org.hl7.fhir.utilities` 6.9.4.1 CRITICAL CVE-2026-55471 (XXE in `XsltUtilities.saxonTransform`, fixed 6.9.10); `org.hl7.fhir.r4/r5/...` 6.9.4.1 HIGH ReDoS and DEFLATE DoS (fixed 6.9.12); `jackson-databind` 2.21.1 with 16 advisories (6 HIGH, incl. polymorphic-type allowlist bypass CVE-2026-54513; fixed 2.21.7); `jackson-core` 2.21.1 3 HIGH; `commons-beanutils` 1.9.3 3 HIGH (CVE-2014-0114, CVE-2019-10086, CVE-2025-48734); `ucum` 1.0.8 HIGH XXE; `guava` 33.2.1 HIGH; `httpcore5`/`-h2` 5.1.3 HIGH. Reachability is limited (the translator reads CQL the compiler writes, not hospital XML), but the release gate is in report mode for this image. | By a run: `mvn dependency:list` on `services/criteria_compiler/compile_cql/translator/pom.xml`, then OSV querybatch; output in `scratchpad/dep-currency/mvn-hits.json`. `deploy/security/known-image-findings.md` rows trialbox-jvm, trialbox-demo (32 each). | Merge PR #78 after its tests run (CQL unit tests, the e2e build gate, the Trivy gate in block mode for trialbox-jvm), plus DEP-002. Acceptance: OSV/Trivy on the resolved classpath shows 0 HIGH/CRITICAL; `VULN_REPORT_ONLY` loses trialbox-jvm and trialbox-demo. | registered CR-045; in PR #78 (partial, untested) | no |
| DEP-002 | Medium | PR #78's pom still leaves three vulnerable jars: `opentelemetry-api` 1.60.1 (2 MODERATE, fixed 1.67.0), `junit` 4.7 **on the runtime classpath** (MODERATE CVE-2020-15250), `commons-compress` 1.24.0 (2 MODERATE, fixed 1.26.0). | By a run: PR #78 pom (commit 417d70e7) resolved with Maven and checked with OSV; `scratchpad/dep-currency/mvn-pr78/deps.txt` line with `junit:junit:jar:4.7:runtime`. | Add `opentelemetry-api` ≥ 1.67.0 and `commons-compress` ≥ 1.26 (current 1.2x) to `dependencyManagement`; exclude `junit` from the translator dependency. Acceptance as DEP-001. | new | no |
| DEP-015 | Medium | The JVM image uses Temurin **17** JRE (`17.0.20.1`, digest from 2026-10-02), while all CI jobs use Java **21**. The October 2026 Java CPU (17.0.21, 2026-10-22) is not in the pinned digest. Temurin 17 ends 2027-10-31, inside the studies' run. | `deploy/docker/jvm.Dockerfile:6`; `.github/workflows/trialbox-ci.yml:156,193`, `trialbox-images.yml:69`; registry config of the pinned digest shows `JAVA_VERSION=jdk-17.0.20.1+1`; endoflife.date Temurin 17 EOL 2027-10-31. | Move the image to `eclipse-temurin:21-jre` (digest-pinned, EOL 2029-12-31) so build and CI test the same JRE. Acceptance: CQL and validator tests pass in the rebuilt image; `java -version` in the image equals CI. | new | no |
| DEP-020 | Low | Version gaps with no advisory: HL7 validator CLI 6.10.4 (2026-09-30) vs 7.0.5 (2026-11-05, new major); `cql-to-elm` 5.4.0 vs 5.5.0 (kept equal to HAPI 8.12's CQL engine on purpose); HAPI image `v8.12.0-2` is the newest image (Maven has 8.12.1); the HAPI image itself has 24 fixable findings. | `tools/fetch_jvm_deps.sh:9`; translator `pom.xml:2`; Maven Central metadata; Docker Hub tags; OSV Maven queries returned none for these three versions. | Keep `cql-to-elm` aligned with the HAPI CQL engine; move both together. Evaluate validator 7.x after go-live, unless 6.10.x stops getting fixes. Take the next HAPI image that clears its findings. | card T-110 covers (gates); HAPI findings registered CR-045 | no |

### 2.2 GPU serving: vLLM, CUDA, drivers

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
|---|---|---|---|---|---|---|
| DEP-003 | High | `docker-compose.gb10.yml` pins `eugr/spark-vllm:station-20261001@sha256:f5700f…`. Its image config says `TORCH_CUDA_ARCH_LIST=10.3a` (DGX Station / GB300), not 12.1a (GB10). The comment beside it says "GB10 build … sm_121". The same account's `latest`/`nightly-*` tags are `12.1a`. The image is a personal account's build, not the vLLM project's. | By a run: registry v2 config of the pinned digest (created 2026-10-01) and of `nightly-20261107`, `station-20261104`, `muse-spark`; `deploy/docker-compose.gb10.yml:37-38,61`. Not run on a Spark. | Replace with the official `vllm/vllm-openai` arm64 image (index digest; its arch list includes 12.0, binary-compatible with 12.1 per CUDA rules, to be confirmed on the Spark) or a 12.1a build pinned by digest with a dated exception. Add a start check in `check_host.sh --gb10` that the image's arch list covers the device's compute capability. Acceptance: the Spark benchmark's serving record names the image digest and `torch.cuda.get_device_capability()`. | new | no |
| DEP-004 | High | vLLM is pulled by tag `vllm/vllm-openai:v0.32.0` with no digest in four compose files (the only third-party image not digest-pinned). v0.33.0 is out (2026-11-02). Both images are CUDA 13.0.2. The v0.32.0 image has 29 fixable HIGH/CRITICAL OS/Python findings. OSV has no vLLM advisory for 0.32.0. | `deploy/docker-compose.yml:257`, `docker-compose.rtxpro6000.yml:31`, `docker-compose.rtx5090.yml:49,101,127,137`; Docker Hub tag digest `sha256:befccf0e7e4089aa23926bb6f887a85c0d46c2a99e6de5c5ffdf5cb7957c5b34` (v0.32.0) and `sha256:d825baf9ce4b1b6bfc5ecc7b79880c7e6748c65a72d697ce3d47607aafa84c6e` (v0.33.0). | Pin `v0.32.0@sha256:befccf0e…` now (the version the G1 run uses), in one place (`deploy/images.lock`, T-104/T-110) referenced by every compose file. Move to a newer vLLM only together with a requalification (WS-02.2). Acceptance: `grep -E 'image:.*vllm' deploy/*.yml` shows only digests; the bundle refuses a mismatch. | registered CR-044 (tag pull) and CR-045 (findings) | no |
| DEP-005 | High | The CUDA 13 vLLM images need an NVIDIA driver from the R580 line or newer on the host (`NVIDIA_REQUIRE_CUDA=cuda>=13.0`, compat only via the datacenter compat package, `VLLM_ENABLE_CUDA_COMPATIBILITY=0`). `check_host.sh` checks the driver only for GB10 (exactly 580.142). There is no check for RTX PRO 6000 or B200, and no B200 compose profile. CGMH's B200 is a shared hospital server whose driver the hospital controls. | `deploy/check_host.sh:72-77`; image config of `vllm/vllm-openai:v0.32.0` amd64 (`CUDA_VERSION=13.0.2`, `TORCH_CUDA_ARCH_LIST=7.5 … 10.0 12.0`); `ls deploy/docker-compose.*.yml` (gb10, rtx5090, rtxpro6000 only). | `check_host.sh`: FAIL when the driver major is below the image's CUDA requirement (read from the image label at install). Write the driver and CUDA requirement into the CGMH IT request now. Add a `b200` profile (or document that `rtxpro6000` is used on B200) with memory fractions for a shared GPU. Acceptance: `check_host.sh` on a host with driver 575 fails with a plain message. | new | no |

### 2.3 Model weights and licences

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
|---|---|---|---|---|---|---|
| DEP-007 | High | The judge's weights come from `nvidia/Gemma-4-26B-A4B-NVFP4` (last commit 2026-05-11; its chat template from 2026-05-07). Upstream `google/gemma-4-26B-A4B-it` changed the chat template on 2026-07-15 ("null handling, reasoning preservation, turn-tag") and the tokenizer config on 2026-07-20. vLLM uses the template inside the model folder; no `--chat-template` is passed. Judge prompts may be rendered with the old template. | Hugging Face commit lists of both repos (2026-11-10); `deploy/docker-compose.rtxpro6000.yml:55-72` (no `--chat-template`); `models/registry.yaml:84`. | Take `chat_template.jinja` and `tokenizer_config.json` from the Google repo at a pinned revision, store them with the site pin (they enter the weight manifest), and pass `--chat-template`. Re-run the judge canary and N-12 before G1b. Acceptance: the serving record names the template sha256; a test renders one judge prompt and compares it with the upstream template's output. | new | no |
| DEP-008 | High | The verifier's weights come from a personal account, `cyankiwi/Qwen3.5-9B-AWQ-4bit` (191,931 downloads). The repo's history was squashed on 2026-07-21 and the model card regenerated on 2026-10-19, so an older revision id may no longer exist. Every registry build has `revision: null` and `sha256: null`; the licence is "Apache-2.0 (to confirm), verified: false". The quantisation recipe is public (`recipe.yaml`, llm-compressor AWQ, int4, group 32). | Hugging Face API (commits, files); `models/registry.yaml:97-104,144-151,191-198`. | Either quantise `Qwen/Qwen3.5-9B` (revision `c20223623576`) ourselves with the same public recipe, or copy the community files into the vendor's own model store at revision `e4d2d39cede8`; in both cases record source repo, revision, the weight-manifest sha256 (`tools/pin_model.py`) and the licence file. Acceptance: no `null` revision for any build that a site profile deploys. | registered CR-097 (hashes); provenance part new | no |
| DEP-009 | Medium | The judge challenger (Gemma 4 31B, official) has no build in `models/registry.yaml`. Official 4-bit forms exist: `google/gemma-4-31B-it-qat-w4a16-ct` (compressed-tensors, 2026-06-04) and `nvidia/Gemma-4-31B-IT-NVFP4` (2026-07-13, licence tag "other"). | `grep -i 31b models/` finds nothing; Hugging Face model list for `google` and `nvidia`. | Add a candidate build with source repo and revision; prefer Google's own QAT checkpoint (same publisher as the template, Apache-2.0). Acceptance: `trialbox eval qualify` can run it by build id. | new | no |
| DEP-010 | Medium | The planned embedder `BAAI/bge-m3` (MIT, last change 2024-07-03) ships only pickle weights (`pytorch_model.bin`, `colbert_linear.pt`, `sparse_linear.pt`) plus ONNX; its safetensors file was deleted upstream on 2024-04-02. `tools/pin_model.py` refuses `.bin` and `.pt` (SEC-63), so the official folder cannot be pinned. `Qwen/Qwen3-Embedding-0.6B` (Apache-2.0, safetensors, 1024-d, updated 2026-04-20) fits the planned `halfvec(1024)` column. | Hugging Face file list; `tools/pin_model.py:41-42`; `services/embed_service/embedder.py:42-44`; WS-02.6 row in `docs/plan/25-master-plan.md:146`. | Add "safetensors weights available from the publisher" as a criterion of the WS-02.6 embedder decision (T-009). If bge-m3 wins, convert once to safetensors in a recorded step and pin the converted manifest. Acceptance: `pin_model --build <embedder>` succeeds on the chosen folder. | card T-009 covers (add the criterion) | no |
| DEP-011 | Low | Registry licence rows still say "terms to confirm". Checked on 2026-11-10: Gemma 4 26B-A4B-it and 31B-it model cards declare `license: apache-2.0` (link `ai.google.dev/gemma/docs/gemma_4_license`); NVIDIA's NVFP4 26B card says Apache-2.0; Qwen3.5-9B Apache-2.0; bge-m3 MIT; Qwen3-Embedding Apache-2.0; gpt-oss-safeguard-20b Apache-2.0. None is a non-commercial or use-restricted licence. | Hugging Face `cardData` of each repo; `models/registry.yaml:89,104`. | Set `verified: true` with source URL, revision and date for each build that ships; keep the licence file in the weight folder (it enters the manifest). Counsel confirms once (WS-15.6). | registered CR-096 (model licences open) | no |

### 2.4 Database and other infrastructure images

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
|---|---|---|---|---|---|---|
| DEP-013 | Medium | The DB stays on PostgreSQL **16**, and card T-104 plans `postgres:16-bookworm`. Debian 12 left regular support on 2026-07-11 (LTS to 2028-06-30); PostgreSQL 16 ends 2028-11-09. PostgreSQL 18.6 (EOL 2030-11-14) and 17.11 (EOL 2029-11-08) are current; pgvector 0.8.7 and PGroonga 4.1.0 publish images for 16, 17 and 18. A major upgrade after go-live means `pg_upgrade` or dump/restore on hospital boxes with patient data. | endoflife.date (postgresql, debian); Docker Hub `pgvector/pgvector` and `groonga/pgroonga` tags (2026-10-31, 2026-10-09); `docs/reviews/2026-11-09-assessment-and-tasks.md:471`; `deploy/docker-compose.yml:43`. | In T-104 build the `db` image on Debian 13 (`trixie`) with PostgreSQL 17 or 18 (owner question Q1), pgvector 0.8.7, PGroonga 4.1.0 and pgBackRest from the PGDG apt repository, all versions pinned. Do it before any site data (already the T-104 rule). Acceptance: T-104's acceptance plus `SELECT version()` shows the chosen major; `backup_drill` passes. | card T-104 covers (change the base and major); CR-083 registered | no |
| DEP-014 | Medium | The PostgreSQL major is not the same everywhere. Compose: 16.15. Demo image: Debian `postgresql` from the trixie base (17, not verified online). CI: whatever `ubuntu-latest` installs (24.04 gives 16; 26.04 gives 18). This dev host: 16. Dumps and `pglocal` behaviour can differ between majors. | `deploy/docker-compose.yml:43`; `demo/Dockerfile:22-23`; `.github/workflows/trialbox-ci.yml:169,206,232` with `runs-on: ubuntu-latest`; `ls /usr/lib/postgresql` → 16. | One declared major (`TB_PG_MAJOR`) used by the db image, the demo (`postgresql-<major>` from PGDG) and CI (`apt-get install postgresql-<major>` from PGDG, `runs-on: ubuntu-24.04` pinned). Acceptance: a CI step prints `pg_config --version` and fails on a mismatch. | new | no |
| DEP-016 | Medium | FHIR packages: the validator cache gets TWPAS `1.2.0` from the npm mirror, while settings default to `1.2.5` and `packages.fhir.org` now has 1.2.5, 1.2.6, 1.2.7 and 1.3.0 (the repo's own fixture is 1.3.0). D-63's premise ("the public registry only has 1.2.0") is out of date. Extensions are pinned to a ballot (`5.3.0-ballot-tc1`) although 5.4.0 is published; terminology is 7.0.1 vs 7.5.0. TW Core 1.0.0 and JP Core 1.1.0 are current. | `tools/fetch_jvm_deps.sh:21-24`; `tools/fetch_fhir_packages.py:47-56`; `deploy/settings.example.yaml:29`; `tests/fixtures/refdata/nhi_pas_sample/package.json:3`; packages.fhir.org listings; `docs/DECISIONS.md:342`. | Fetch from packages.fhir.org (not the npm mirror) with the version in settings; ask the CGMH NHI contact which TWPAS version the 2027 submissions use (likely 1.3.0); move extensions to 5.4.0 and terminology to the version TW Core 1.0.0 declares. New decision superseding D-63. Acceptance: the TWPAS validation tests pass on the chosen version; `twpas_version` in settings equals the cached package. | new | no |
| DEP-027 | Low | pgBackRest comes from `apk add pgbackrest` with no version: Alpine 3.24 has 2.58.0, upstream is 2.60.0. | `deploy/pgbackrest/Dockerfile:8`; Alpine v3.24 APKINDEX; `git ls-remote` pgbackrest tags. | Superseded by T-104's Debian image: install `pgbackrest=<version>` from PGDG. | card T-104 covers | no |
| DEP-021 | Low | Test-profile mail servers: MailHog v1.0.1 (abandoned since 2020, 1,590 findings, no arm64); GreenMail 2.1.3 (2025-02) vs 2.1.15 (2026-10-25), 16 findings. Test-only. | `deploy/docker-compose.test.yml:8,17`; Docker Hub tags; `deploy/security/known-image-findings.md`. | Replace MailHog with Mailpit; move GreenMail to 2.1.15 by digest. | registered CR-045 | no |

### 2.5 Python runtime and packages

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
|---|---|---|---|---|---|---|
| DEP-012 | High | The heavy extras are locked but installed in **no** image. `doc-parser` and `embed-service` run on `trialbox-py`, built only from `deploy/requirements.lock` (73 packages: no docling, torch, sentence-transformers). So `_docling()` and the bge-m3 embedder ("production image only") never run in production; `TB_EMBED_MODE` is unset in compose, so the embedder is the hash fallback. PaddleOCR is not in `uv.lock` at all; the OCR branch logs "PaddleOCR not installed". The 128 packages outside the runtime lock (extras, dev, test) are also outside the `pip-audit` gate (OSV over them was clean today). | `deploy/docker/python.Dockerfile:21-24`; `deploy/docker-compose.yml:116-131`; `services/doc_parser/parser.py:128-131,213-216`; `services/embed_service/embedder.py:83-89`; `pyproject.toml:43-46`; `grep -c` of the runtime lock. | Decide per extra: (a) a `trialbox-ml` image built from a second exported lock (`--extra docling --extra embed`, hashed) for `doc-parser` and `embed-service`, audited by the same gates; or (b) drop the extra and its code path. Lock PaddleOCR (or Tesseract) if OCR stays. Acceptance: `docker run trialbox-ml python -c "import docling, sentence_transformers"` passes; `pip-audit` covers both locks; compose sets `TB_EMBED_MODE`. | new | no |
| DEP-022 | Low | Python 3.12.16 is security-only (since 2025-04) and ends 2028-10-31. 3.13 left bugfix support on 2026-10-01; 3.14 is the active line (bugfix to 2027-10-01, security to 2030-10-31). All runtime C-extension wheels in the lock have cp313 and cp314 builds (except `backports-zstd`, which 3.14 does not need). vLLM 0.33 supports up to 3.14. | endoflife.date; PyPI file lists for the 29 binary runtime packages; `pyproject.toml:6` (`>=3.12,<3.13`). | Stay on 3.12 through go-live. Move to 3.14 after go-live (batch 5), before 2028. | new | no |
| DEP-023 | Low | `duckdb` and `duckdb-extension-fts` are hard-pinned to 1.5.5; DuckDB 2.0.0 came out 2026-10-21 (FTS 2.0.0 on 2026-11-01). No advisory on 1.5.5. Change list and storage format of 2.0 not verified here. | `pyproject.toml:21-22`; PyPI. | Stay on 1.5.x for go-live. After go-live, test 2.0 on a copy of the lake (open old files, FTS index rebuild, goldens unchanged). | new | no |
| DEP-028 | Low | Extras-only transitive packages behind a major: `huggingface-hub` 1.33.0 (2.4.0), `semchunk` 3.2.5 (4.1.1), `isort` 8.0.1 (9.0.2, dev); the NVIDIA CUDA wheels are one CUDA minor behind because `torch` 2.15.0 pins them. No advisories. | Table B below. | Let them move with their parents in the monthly lock refresh; no direct action. | new | no |

### 2.6 Build tools, CI and front-end assets

| ID | Severity | Finding | Evidence | Fix proposal | Status | PoC path |
|---|---|---|---|---|---|---|
| DEP-006 | High | uv 0.11.32 (pinned in CI and in `tools/supply_chain/lock.py`) has CRITICAL GHSA-hq85-5cpj-mr62 / PYSEC-2026-4321 (2026-10-20): its bundled CA store trusts the `emSign ECC Root CA - G3` root, under which eight intermediate CAs have compromised keys; fixed in 0.13.4 (latest 0.13.7). Hash-checked installs (`uv sync --frozen`) still reject a swapped wheel, but `uv lock` and any unhashed fetch could accept a forged PyPI certificate. | OSV query `uv 0.11.32`; `.github/workflows/trialbox-ci.yml:62` (and 9 more lines); `git ls-remote astral-sh/uv`. | Move uv to ≥ 0.13.4 in CI, `lock.py UV_VERSION` and the dev machines; re-run `uv lock` (no version change expected) and `make lock-check`. Until then, run uv with `--native-tls`/`UV_SYSTEM_CERTS` (this host already does). Acceptance: `uv --version` in CI ≥ 0.13.4. | new | no |
| DEP-017 | Medium | Several build downloads are not verified against a pinned hash: `validator_cli.jar` from GitHub releases (the hash is written after download, never compared); FHIR package tarballs from the npm registry (no `dist.integrity` check); the Noto fonts from `google/fonts` branch **main** (no commit, no hash); Maven jars (no lock or checksum policy). JP Core (`tools/jpcore_rules.py:33-37`) and Syft/Trivy do this right. | `tools/fetch_jvm_deps.sh:12-17`; `tools/fetch_fhir_packages.py:66-72`; `tools/fetch_fonts.py:18-22`. | Pin the validator jar's sha256 next to `VALIDATOR_VERSION`; check npm `dist.integrity` (sha512) and record it in a packages lock; fetch fonts by commit URL with sha256; run Maven with `-C` (strict checksums) and a pinned `maven-dependency-plugin`. Acceptance: a tampered file fails the fetch. | new | no |
| DEP-018 | Medium | GitHub Actions are pinned by SHA (good) but are two to three majors behind and run on the `node20` runtime: checkout v4.4.0 (latest v7.0.1, node24), setup-uv v5.4.2 (v10.3.3), setup-java v4.9.1 (v6.2.0), cache v4.3.0 (v6.1.0), upload-artifact v4.6.2 (v7.0.2), setup-qemu v3.7.0 (v4.4.0), setup-buildx v3.12.0 (v4.4.1). GitHub has been retiring Node 20 on hosted runners in 2026 (not verified online); a forced runtime switch can break CI without a code change. | `grep uses:` in `.github/workflows/trialbox-*.yml`; `git ls-remote` tag-to-SHA match; `action.yml` of the pinned SHAs says `using: node20`. | Move each action to its current major by SHA in one PR; run every workflow once. Acceptance: no `node20` action in the workflows. | new | no |
| DEP-019 | Medium | No update bot is configured (no `.github/dependabot.yml`, no `renovate.json`), so digests age silently: the pinned `postgres:16-alpine` digest is from 2026-09-17 (Alpine 3.24.2; the tag now has 3.24.4), the Temurin digest from 2026-10-02. Only the Python base digest is current (3.12.16 on Debian 13, 2026-11-05). | `ls .github/`; registry configs of the pinned digests vs the tags. | Adopt the policy in section 3.2 (Renovate, monthly, digest pinning, grouped, security owner approves). Acceptance: the bot's first PRs refresh the stale digests and pass the gates. | new | no |
| DEP-024 | Low | Scanner and audit tools are one minor behind with no advisories: Syft 1.56.0 (1.57.1), Trivy 0.75.0 (0.76.2), pip-audit 2.9.0 (2.10.1). | `tools/supply_chain/scanners.py:31-32`; `tools/supply_chain/pip-audit.in:2`; OSV (none). | Bump in batch 0 with their sha256 sums, per the file's own rule. | new | no |
| DEP-025 | Low | Front-end: the console and the site load no third-party JS or CSS (only own `console.js`, `app.js`, CSS); no CDN links. The only vendored library is `tools/vendor/axe.min.js` axe-core **4.10.2** (MPL-2.0, test-only; latest 4.14.0). Playwright for the walk tests has no pinned version in the repo (no `package.json`). | `head tools/vendor/axe.min.js`; `grep` for CDN hosts → none; npm registry. | Move axe-core to 4.14.0 (more WCAG 2.2 rules) with its sha256 recorded; record the Playwright version the tests use in a small `package.json` + lock under `tools/`. | new | no |
| DEP-026 | Low | REDCap: `SUPPORTED_MAJORS = (14, 15, 16)` says "LTS lines the connector is tested on", but the tests run only against `rc_sim`. The sites' REDCap versions are not recorded. REDCap release lines not verified online (the vendor site needs a login). | `services/rc_bridge/client.py:17,123-129`; `docs/plan/design/08-interface-control.md:44`. | Ask each site's REDCap admin for the version (`content=version`) and record it in the site file; reword the comment to "accepted" until a real instance is tested; test once against a REDCap sandbox before go-live. | new | no |

### 2.7 Licence summary (no new risk found)

- Python: the runtime set has 8 LGPL packages and one dual (dulwich) already in `deploy/supply-chain-allowlist.yaml`; MPL-2.0 (certifi, tqdm, pathspec) is file-level and unmodified. No GPL or AGPL in the runtime image. The NVIDIA CUDA wheels (proprietary EULA) appear only in the extras (torch); if DEP-012 builds a `trialbox-ml` image, their licence terms go into `THIRD_PARTY_NOTICES`.
- Images: Temurin is GPLv2 with Classpath Exception; Groonga (inside PGroonga) is LGPL-2.1; PostgreSQL, pgvector, PGroonga use the PostgreSQL licence; Caddy, Authelia, HAPI, vLLM, GreenMail Apache-2.0; pgBackRest and MailHog MIT (training knowledge, not verified online in this review). None blocks on-premises redistribution of unmodified images; all go into the notices (T-110).
- Fonts: Noto Sans TC/JP under SIL OFL 1.1 (the script fetches `OFL.txt`). Embedding subsets in reports is allowed.
- FHIR packages: HL7 packages CC0; TW Core / TWPAS `CC0-1.0` (fixture `package.json`); JP Core licence not read here.
- Models: all Apache-2.0 or MIT (DEP-011). No Gemma "prohibited use" terms apply to Gemma 4 under Apache-2.0, per the model card on 2026-11-10.

## 3. Dependency upgrade plan

### 3.1 Batches (in order)

| Batch | When | Contents | Test evidence required | Findings closed |
|---|---|---|---|---|
| 0 Build tools | this week (before PoC) | uv → ≥ 0.13.4 (lock re-run, no package change); pip-audit 2.10.1; Syft 1.57.1, Trivy 0.76.2 with sums; GitHub Actions to current majors by SHA | `uv lock --check`, `make lock-check`, `allowlist-check`, every workflow green once; `pip-audit` gate PASS | DEP-006, 018, 024 |
| 1 JVM jars and JRE | before PoC (by 2026-11-27) | PR #78 + DEP-002 residuals; JRE 21 by digest | CQL unit tests (`tests/unit/test_cql_*`), validator sample test, e2e build gate; Trivy gate in **block** mode for trialbox-jvm and trialbox-demo; OSV on the resolved classpath = 0 HIGH/CRITICAL | DEP-001, 002, 015 |
| 2 Third-party images | before PoC | vLLM `v0.32.0` by digest; GB10 image corrected; postgres/temurin digests refreshed; Mailpit; GreenMail 2.1.15; `deploy/images.lock` as the one list | Trivy gate per image; compose integration test; on the GPU VM only a canary (no version change, so no requalification) | DEP-003, 004, 021 (part of CR-044/045) |
| 3 Data plane and models | before G2 design freeze 2027-01-08 | T-104 db image (Debian 13, PostgreSQL 17/18, pgvector 0.8.7, PGroonga 4.1.0, pgBackRest pinned); one PG major in demo and CI; FHIR packages (TWPAS per site answer, extensions 5.4.0, terminology); model provenance (own copies, revisions, manifests), Gemma chat template from upstream, 31B challenger build, embedder decision with safetensors; `trialbox-ml` image or extras dropped; build-download hashes | `backup_drill` on the new image; goldens unchanged (`make goldens-check`); TWPAS validation tests; G1b qualification record per build (WS-02.2) naming image digest, template sha and weight manifest; `pin_model --verify-all` | DEP-005, 007–010, 012–014, 016, 017, 027 |
| 4 Pre-go-live patch window | 2027-01-08 → 2027-03-26 | monthly lock refresh (patch and minor within the lock); image digest refreshes; nothing that changes a model, vLLM or the DB major | full test suite, e2e, update drill, gates; release notes list every changed package | DEP-019 (running) |
| Freeze | 2027-03-29 → 2027-05-27 (4 weeks before CGMH go-live to 2 weeks after Japan go-live) | security fixes only: a fixable HIGH/CRITICAL that is reachable, or any CRITICAL; each as its own signed bundle | the failing advisory's test or scan, full suite, update drill; owner and security owner sign | — |
| 5 After go-live | from 2027-06 | Python 3.14; DuckDB 2.x; validator 7.x with `cql-to-elm`/HAPI together; vLLM moves with requalification; Temurin 21 → 25 later | as batch 3 for anything touching data or models | DEP-020, 022, 023 |

Hard deadlines inside the study period: Temurin 17 ends 2027-10-31 (closed by batch 1); Python 3.12 ends 2028-10-31; PostgreSQL 16 ends 2028-11-09 (closed by batch 3 if the major moves); Debian 12 LTS ends 2028-06-30.

### 3.2 Standing policy

- **Tool**: Renovate (it handles `uv.lock`, Dockerfiles, compose files, GitHub Actions, Maven and, through regex managers, `VALIDATOR_VERSION`, `scanners.py`, `fetch_fhir_packages.py` and the `${VAR:-image@sha256}` defaults). Dependabot is the fallback if Renovate cannot be installed on the repo.
- **Config sketch** (`renovate.json` at repo root, scoped to `trialbox/`):
  - `extends: ["config:recommended", ":pinDigests", "helpers:pinGitHubActionDigests"]`, `dependencyDashboard: true`, `lockFileMaintenance: {enabled: true, schedule: ["before 6am on the first Monday of the month"]}`.
  - `packageRules`: group "python-runtime" (packages in `deploy/requirements.lock`) monthly; group "python-dev" monthly; group "actions" monthly; group "jvm" (translator pom + validator) monthly; `vllm/vllm-openai`, `eugr/*`, model files and `postgres` major: `enabled` but `automerge: false` and label `requalify` (never merged without WS-02.2); `matchUpdateTypes: ["major"]` → separate PRs, label `major`.
  - `vulnerabilityAlerts: {enabled: true, schedule: ["at any time"], labels: ["security"]}`; `osvVulnerabilityAlerts: true`.
  - No automerge anywhere (regulated product: every change is reviewed and appears in the release record).
- **Cadence**: monthly batch PRs; security alerts within 7 days for reachable HIGH/CRITICAL, 30 days for the rest; allow-list entries keep their 180-day `review_by`.
- **Freeze windows**: from 4 weeks before a site go-live to 2 weeks after (first: 2027-03-29 to 2027-05-27), and 1 week before each gate run (G1b, G2, G3): security-only, via a signed bundle.
- **Who approves**: the security owner (to be named, OD-4) approves every dependency PR and every allow-list change; the safety-core engineer co-approves anything touching vLLM, model weights, prompts' chat templates, the DB major or the six safety-core files; the owner signs the release record. An agent may open and test the PRs but never merges them.
- **Evidence kept per release**: the lock diff, SBOMs per image, pip-audit and Trivy reports, OSV on the JVM classpath, and the qualification record when serving changed (T-110 `release.json`).

## 4. What is good (do not change)

- `uv.lock` with hashes, `deploy/requirements.lock` exported from it, `--require-hashes --only-binary=:all:` in both Dockerfiles, and `make lock-check` in CI. All checks passed today.
- 176 of 201 Python packages are at the latest stable release; OSV has no advisory on any pin; pypdf and pillow floors are met.
- The supply-chain allow-list format (reason, `review_by` ≤ 180 days, one flag per entry) and its CI check.
- Every third-party image except vLLM is pinned by index digest, with the reason to move it in a PR.
- `tools/pin_model.py` refusing pickle weights and hashing a weight manifest; `jpcore_rules.py` checking sha256 and sha1 of JP Core; Syft/Trivy fetched by pinned sums.
- GitHub Actions pinned by commit SHA.
- No third-party JS in the console or the site; the CSP allows only the page's own script by hash.
- The Python base image is current (3.12.16 on Debian 13) and gets `apt-get upgrade` at build.

## 5. Proposed task cards for TB-PLAN-06

| Id | Goal | Files it touches | Acceptance tests | Depends on | Size | PoC prerequisite |
|---|---|---|---|---|---|---|
| T-110 (add) | Batch 0 and the policy: uv ≥ 0.13.4, scanner and pip-audit bumps, Actions to current majors, `renovate.json` per §3.2, build-download hashes (validator jar, npm integrity, fonts by commit, Maven strict checksums) | `.github/workflows/trialbox-*.yml`, `tools/supply_chain/lock.py`, `scanners.py`, `pip-audit.in/.lock`, `renovate.json`, `tools/fetch_jvm_deps.sh`, `tools/fetch_fhir_packages.py`, `tools/fetch_fonts.py` | every workflow green; a tampered jar/tarball/font fails the fetch; Renovate dashboard issue opens | — | M | yes (uv advisory) |
| T-DEP-1 (finish PR #78) | Batch 1: jar bumps incl. otel, commons-compress, junit exclusion; JRE 21 by digest; image gate to block mode for jvm and demo | translator `pom.xml`, `deploy/docker/jvm.Dockerfile`, `tools/supply_chain/release.py` (`VULN_REPORT_ONLY`), `deploy/security/known-image-findings.md` | CQL and validator tests; Trivy block mode PASS; OSV classpath 0 HIGH/CRITICAL | — | S | yes (demo image carries the jars) |
| T-DEP-2 | Batch 2: `deploy/images.lock` as the single digest list; vLLM by digest; GB10 image corrected and arch check in `check_host.sh`; driver ≥ CUDA requirement check; B200 profile or note; Mailpit, GreenMail bump | `deploy/docker-compose*.yml`, `deploy/check_host.sh`, `deploy/images.lock` (new), `deploy/install.sh` (read it) | no image by tag; `check_host` fails on a low driver and on an arch mismatch; compose integration test | T-104 contract for `images.lock` | M | no |
| T-104 (add) | Debian 13 base, PostgreSQL 17 or 18 (Q1), pgvector 0.8.7, PGroonga 4.1.0, pgBackRest pinned from PGDG; one PG major for demo and CI | as T-104 plus `demo/Dockerfile`, CI workflow, `deploy/pgbackrest/` removed | T-104 acceptance + `pg_config --version` equal in db image, demo, CI | — | M | no (but before any site data) |
| T-DEP-3 | Model provenance: own copies or own quantisation of the verifier, revisions and manifests for every deployed build, Gemma template from upstream with `--chat-template`, 31B challenger build, licence rows verified | `models/registry.yaml`, `models/cards/*`, compose `command:` blocks, `tools/pin_model.py` (template files in manifest), `tools/serving_config.py` | no `null` revision in a deployed build; serving record names template sha; canary and N-12 pass | WS-02.2 | M | no (before G1b) |
| T-009 (add) | Embedder decision criterion "safetensors from the publisher"; conversion step if bge-m3 | decision record, `services/embed_service/embedder.py` | `pin_model` succeeds on the chosen embedder | WS-02.6 | S | no |
| T-DEP-4 | Extras: `trialbox-ml` image from a second hashed lock (docling, embed, OCR) or remove the code paths; set `TB_EMBED_MODE` in compose | `pyproject.toml`, `tools/supply_chain/lock.py`, new `deploy/docker/ml.Dockerfile`, `deploy/docker-compose.yml`, `Makefile` | import test in the image; pip-audit over both locks; doc-parser converts a fixture PDF with docling | T-DEP-2 | M | no |
| T-DEP-5 | FHIR package set: fetch from packages.fhir.org by settings version; TWPAS per CGMH answer; extensions 5.4.0; terminology aligned; decision superseding D-63 | `tools/fetch_fhir_packages.py`, `tools/fetch_jvm_deps.sh`, `deploy/settings.example.yaml`, `docs/DECISIONS.md` | TWPAS validation tests on the chosen version; settings version = cached version | Q3 answer | S | no |

## 6. Questions only the owner can decide

| # | Question | Recommended answer |
|---|---|---|
| Q1 | PostgreSQL major for the new db image (T-104): 16 as planned, or 17/18? | **18** if the PGDG packages for pgvector, PGroonga and pgBackRest are available for it on Debian 13 at T-104 time; otherwise 17. Decide before T-104 starts; never move the major after site data exists without a planned window. |
| Q2 | Source of the DGX Spark vLLM build: the official vLLM arm64 image, or the community `eugr/spark-vllm` build? | The official image, pinned by digest, measured in the Spark benchmark; the community image only with a dated exception and its digest. |
| Q3 | Verifier weights: our own AWQ quantisation of `Qwen/Qwen3.5-9B`, or a mirrored copy of the community files? | Our own quantisation with the published recipe (same method, provenance under our control), compared with the community files on the judge set before switching. |
| Q4 | Freeze window and approvers. | Freeze 2027-03-29 to 2027-05-27 (security fixes only); the security owner approves dependency changes, the safety-core engineer co-approves serving/model/DB-major changes, the owner signs releases. Name the security owner now (OD-4). |

## 7. Assumptions

- "Latest stable" excludes pre-releases, dev builds and fully yanked versions; for FHIR packages it is the registry's `latest` tag; for images it is the newest version tag (not `latest`/nightly).
- Advisory status is OSV as of 2026-11-10; image findings are the 2026-11-10 Trivy report in the repo, not a fresh scan.
- CUDA binary compatibility within a compute-capability major (12.0 code on a 12.1 GB10) is assumed from NVIDIA's rules, not tested.
- GitHub's Node 20 runner retirement, the Debian 13 PostgreSQL major (17), the Groonga, Temurin, pgBackRest and MailHog licences, and the REDCap release lines are from training knowledge and are marked as not verified online.
- G2 design freeze is 2027-01-08 (from the prompt); go-live dates are the owner's (2027-04-28 CGMH, 2027-05-13 Japan).

## 8. Component currency tables

### 8.1 Images, servers and infrastructure

| Component | Current pin | Latest stable (2026-11-10) | Gap | Advisories / findings | EOL | Licence | Upgrade risk | Effort | Action and when |
|---|---|---|---|---|---|---|---|---|---|
| Python base `python:3.12-slim` | 3.12.16, Debian 13, digest `5e2bdb1b…` (2026-11-05) | 3.12.16 (same digest); 3.14.10 | none on 3.12; 2 minors to 3.14 | trialbox-py gate blocks (clean) | 3.12: 2028-10-31; Debian 13: 2030-06-30 | PSF | 3.14: rebuild, run suite | M | keep; 3.14 after go-live (DEP-022) |
| `postgres:16-alpine` | 16.15 on Alpine 3.24.2, digest from 2026-09-17 | 16.15 on Alpine 3.24.4; 18.6 | digest stale ~2 mo; 2 majors | 30 (gosu Go stdlib, musl, zlib) — CR-045 | PG16 2028-11-09 | PostgreSQL | major: pg_upgrade | M | refresh digest (batch 2); new image in T-104 (DEP-013) |
| pgvector | not deployed (planned 0.8.x) | 0.8.7 (2026-10-31) | — | none known | — | PostgreSQL | none yet | S | 0.8.7 in T-104 |
| PGroonga | not deployed (planned 4.1.x) | 4.1.0 (2026-10-09) | — | none known | — | PostgreSQL (Groonga LGPL-2.1, not verified online) | none yet | S | 4.1.0 in T-104 |
| pgBackRest | Alpine package 2.58.0, unpinned | 2.60.0 | 2 minors | none known | — | MIT (not verified online) | low | S | PGDG pinned in T-104 (DEP-027) |
| `eclipse-temurin:17-jre` | 17.0.20.1, digest 2026-10-02 | 17.0.21 / 21.0.13 / 25.0.5 | patch (Oct CPU) / 1 LTS | Oct 2026 CPU missing | 17: 2027-10-31; 21: 2029-12-31 | GPLv2+CE | CI already on 21 | S | 21 in batch 1 (DEP-015) |
| `caddy:2.11.9-alpine` | 2.11.9, Alpine 3.24.4 | 2.11.9 | current | OSV none | — | Apache-2.0 | — | — | keep |
| `authelia/authelia:4.39.28` | 4.39.28 (2026-09-17) | 4.39.28 | current | OSV none | — | Apache-2.0 | OIDC provider beta in 4.39 | — | keep |
| `hapiproject/hapi:v8.12.0-2` | v8.12.0-2 (2026-10-02) | v8.12.0-2 (Maven 8.12.1) | current image | 24 (expat, zlib, jackson, guava, spring) — CR-045 | — | Apache-2.0 | CQL engine version tied to translator | S | next image that clears findings |
| `vllm/vllm-openai:v0.32.0` | v0.32.0, **no digest**; CUDA 13.0.2, torch 2.13 | v0.33.0 (2026-11-02), CUDA 13.0.2, torch 2.14 | 1 minor | 29 image findings; OSV none for vllm | — | Apache-2.0 | any move = requalify | S (pin) / M (move) | pin digest now (DEP-004); move only with WS-02.2 |
| `eugr/spark-vllm:station-20261001` | arm64 digest, sm_103a build | official vLLM arm64 v0.33.0 or eugr nightly 12.1a | wrong target | not scanned | — | community | Spark benchmark | S | replace (DEP-003) |
| `greenmail/standalone:2.1.3` | 2.1.3 (2025-02) | 2.1.15 (2026-10-25) | 12 patches | 16 — CR-045 | — | Apache-2.0 | test only | S | bump (batch 2) |
| `mailhog/mailhog:v1.0.1` | v1.0.1 (2020) | abandoned | — | 1,590 — CR-045 | abandoned | MIT | test only | S | Mailpit (batch 2) |
| NVIDIA driver (host) | GB10: exactly 580.142; others unchecked | R580+ needed for CUDA 13 images | — | — | — | NVIDIA | hospital-controlled on CGMH B200 | S | check in `check_host` (DEP-005) |
| REDCap (site) | accepts majors 14/15/16 | not verified online | — | — | — | REDCap licence (site's) | API `content=version` checked | S | record site versions (DEP-026) |

### 8.2 JVM, FHIR packages, fonts, JS, CI tools

| Component | Current pin | Latest stable | Gap | Advisories | Licence | Action and when |
|---|---|---|---|---|---|---|
| `cql-to-elm-cli` | 5.4.0 | 5.5.0 (2026-10-23) | 1 minor | none on the artifact; 20 vulnerable transitive jars (DEP-001) | Apache-2.0 | keep 5.4.0 with HAPI 8.12; fix transitive (batch 1) |
| HL7 validator CLI | 6.10.4 (2026-09-30) | 7.0.5 (2026-11-05) | major | none in OSV for the core artifact; fat jar not scanned | Apache-2.0 | pin sha256 now (DEP-017); 7.x after go-live |
| hl7.fhir.r4.core | 4.0.1 | 4.0.1 | current | — | CC0 | keep |
| hl7.terminology(.r4) | 7.0.1 | 7.5.0 | 5 minors | — | CC0 | align (DEP-016) |
| hl7.fhir.uv.extensions(.r4) | 5.3.0-ballot-tc1 | 5.4.0 | ballot → release | — | CC0 | 5.4.0 (DEP-016) |
| tw.gov.mohw.twcore | 1.0.0 | 1.0.0 | current | — | CC0 | keep |
| tw.gov.mohw.nhi.pas (TWPAS) | 1.2.0 cached; settings 1.2.5 | 1.3.0 | 1 minor | — | CC0-1.0 | per CGMH answer (DEP-016) |
| jp-core.r4 | 1.1.0 (hash-pinned) | 1.1.0 (1.1.1-rc exists) | current | — | not read | keep |
| Noto Sans TC / JP | `google/fonts` main, unpinned | — | — | — | OFL-1.1 | pin by commit + sha256 (DEP-017) |
| axe-core (vendored, tests) | 4.10.2 | 4.14.0 | 4 minors | — | MPL-2.0 | bump (DEP-025) |
| uv | 0.11.32 | 0.13.7 | 2 minors | **CRITICAL GHSA-hq85-5cpj-mr62** | MIT/Apache-2.0 | ≥ 0.13.4 now (DEP-006) |
| pip-audit | 2.9.0 | 2.10.1 | 1 minor | none | Apache-2.0 | batch 0 |
| Syft / Trivy | 1.56.0 / 0.75.0 | 1.57.1 / 0.76.2 | 1 minor each | none | Apache-2.0 | batch 0 |
| actions/checkout | v4.4.0 (SHA) | v7.0.1 | 3 majors (node20) | — | MIT | batch 0 (DEP-018) |
| astral-sh/setup-uv | v5.4.2 (SHA) | v10.3.3 | 5 majors | — | MIT | batch 0 |
| actions/setup-java | v4.9.1 (SHA) | v6.2.0 | 2 majors | — | MIT | batch 0 |
| actions/cache | v4.3.0 (SHA) | v6.1.0 | 2 majors | — | MIT | batch 0 |
| actions/upload-artifact | v4.6.2 (SHA) | v7.0.2 | 3 majors | — | MIT | batch 0 |
| docker/setup-qemu-action | v3.7.0 (SHA) | v4.4.0 | 1 major | — | Apache-2.0 | batch 0 |
| docker/setup-buildx-action | v3.12.0 (SHA) | v4.4.1 | 1 major | — | Apache-2.0 | batch 0 |

### 8.3 Model weights

| Build role | Repository (registry) | Revision pinned | Upstream state 2026-11-10 | Licence (card) | Newer / better checkpoint | Action |
|---|---|---|---|---|---|---|
| Judge (Gemma 4 26B-A4B, NVFP4) | `nvidia/Gemma-4-26B-A4B-NVFP4` | null | last commit 2026-05-11 (`a19cfe00be84`); upstream Google template fixed 2026-07-15 | Apache-2.0 | Google `gemma-4-26B-A4B-it` rev `4d7ae4984b7d` (template); `RedHatAI/gemma-4-26B-A4B-it-FP8-dynamic` (2026-08-13) | template override + pin (DEP-007) |
| Verifier (Qwen3.5-9B, AWQ 4-bit) | `cyankiwi/Qwen3.5-9B-AWQ-4bit` | null | squashed 2026-07-21; card 2026-10-19 (`e4d2d39cede8`) | Apache-2.0 | no official Qwen 9B quant; Qwen3.6 has 27B and 35B-A3B only | own quant or mirror (DEP-008) |
| Challenger (Gemma 4 31B) | none | — | `google/gemma-4-31B-it` `842da3794eaa` (2026-07-20); `-qat-w4a16-ct` (2026-06-04) | Apache-2.0 | — | add build (DEP-009) |
| Embedder | bge-m3 (path only) | none | `BAAI/bge-m3` `5617a9f61b02` (2024-07-03), pickle weights only | MIT | `Qwen/Qwen3-Embedding-0.6B` `97b0c614be4d` (1024-d, safetensors) | decide in WS-02.6 (DEP-010) |
| Guard candidate | `openai/gpt-oss-safeguard-20b` | null | `8a11e17b25c9` (2026-01-14) | Apache-2.0 | — | pin if deployed |

## 9. Python package tables (uv.lock, 201 third-party packages)

Scope: R = in `deploy/requirements.lock` (runtime image); X = extras only (docling, embed); D = dev or test group. Advisories: OSV querybatch on 2026-11-10 (none found for any pin); `pip-audit` on the runtime lock: "No known vulnerabilities found" (73 packages).

### A. Direct dependencies (pyproject.toml)

| Package | Scope | Pin (uv.lock) | Latest stable | Gap | Advisories (OSV, 2026-11-10) | Licence | Note / action |
|---|---|---|---|---|---|---|---|
| pydantic | R | 2.14.3 (2026-11-05) | 2.14.3 (2026-11-05) | current | none | MIT | Keep; current. |
| pyyaml | R | 6.0.3 (2025-09-25) | 6.0.3 (2025-09-25) | current | none | MIT | Keep; current. |
| jsonschema | R | 4.26.0 (2026-01-07) | 4.26.0 (2026-01-07) | current | none | MIT | Keep; current. |
| jinja2 | R | 3.1.6 (2025-03-05) | 3.1.6 (2025-03-05) | current | none | BSD License | Keep; current. |
| httpx | R | 0.28.1 (2024-12-06) | 0.28.1 (2024-12-06) | current | none | BSD-3-Clause | Keep; current. |
| fastapi | R | 0.162.2 (2026-11-07) | 0.162.2 (2026-11-07) | current | none | MIT | Keep; current. |
| uvicorn | R | 0.54.0 (2026-09-25) | 0.54.0 (2026-09-25) | current | none | BSD-3-Clause | Keep; current. |
| python-multipart | R | 0.0.33 (2026-10-31) | 0.0.33 (2026-10-31) | current | none | Apache-2.0 | Keep; current. |
| duckdb | R | 1.5.5 (2026-07-22) | 2.0.0 (2026-10-21) | major; pin 3.7 mo old | none | MIT License | Pinned `==1.5.5` in pyproject. 2.0 is a new major (storage format and API changes not verified here). Stay on 1.5.x for go-live; trial 2.0 after go-live with a lake round-trip test. |
| duckdb-extension-fts | R | 1.5.5 (2026-08-10) | 2.0.0 (2026-11-01) | major; pin 3.0 mo old | none | MIT | Moves with duckdb (same version). py3-none wheel. |
| pyarrow | R | 26.0.1 (2026-11-03) | 26.0.1 (2026-11-03) | current | none | Apache-2.0 | Keep; current. |
| sqlglot | R | 30.30.0 (2026-11-06) | 30.30.0 (2026-11-06) | current | none | MIT | Keep; current. |
| sqlalchemy | R | 2.1.8 (2026-11-04) | 2.1.8 (2026-11-04) | current | none | MIT | Keep; current. |
| psycopg | R | 3.3.8 (2026-11-04) | 3.3.8 (2026-11-04) | current | none | LGPL-3.0-only | LGPL-3.0 (allow-listed, unmodified wheel). |
| openpyxl | R | 3.1.5 (2024-06-28) | 3.1.5 (2024-06-28) | current | none | MIT | Keep; current. |
| reportlab | R | 5.1.0 (2026-10-22) | 5.1.0 (2026-10-22) | current | none | BSD License | Keep; current. |
| matplotlib | R | 3.11.2 (2026-09-11) | 3.11.2 (2026-09-11) | current | none | Python Software Foundation License | Keep; current. |
| docxtpl | R | 0.20.2 (2025-11-13) | 0.20.2 (2025-11-13) | current | none | LGPL-2.1-only | LGPL-2.1 (allow-listed). |
| python-docx | R | 1.2.0 (2025-06-16) | 1.2.0 (2025-06-16) | current | none | MIT | Keep; current. |
| pypdf | R | 7.0.0 (2026-11-06) | 7.0.0 (2026-11-06) | current | none | BSD-3-Clause | Floor >=6.21.4 (R-19) met. |
| py7zr | R | 1.1.4 (2026-10-12) | 1.1.4 (2026-10-12) | current | none | LGPL-2.1-or-later | LGPL-2.1+ (allow-listed); R-12 may remove. |
| cryptography | R | 50.0.2 (2026-09-30) | 50.0.2 (2026-09-30) | current | none | Apache-2.0 OR BSD-3-Clause | Keep; current. |
| apscheduler | R | 3.11.3 (2026-06-28) | 3.11.3 (2026-06-28) | current | none | MIT | Capped <4 in pyproject; 3.11.x is the stable line. |
| numpy | R | 2.5.4 (2026-10-10) | 2.5.4 (2026-10-10) | current | none | BSD-3-Clause AND 0BSD AND MI | Keep; current. |
| fhir-resources | R | 8.3.0 (2026-07-03) | 8.3.0 (2026-07-03) | current | none | BSD license | Only R4B/R5/STU3 models (D-11). |
| python-dateutil | R | 4.0.0 (2026-11-01) | 4.0.0 (2026-11-01) | current | none | BSD-3-Clause | Keep; current. |
| tzdata | R | 2026.6 (2026-10-28) | 2026.6 (2026-10-28) | current | none | Apache-2.0 | Keep; current. |
| markdown | R | 3.11.3 (2026-11-05) | 3.11.3 (2026-11-05) | current | none | BSD-3-Clause | Keep; current. |
| dulwich | R | 1.2.21 (2026-11-05) | 1.2.21 (2026-11-05) | current | none | Apache-2.0 OR GPL-2.0-or-lat | Dual Apache-2.0/GPL-2.0+; Apache branch taken (allow-listed). |
| zstandard | R | 0.25.0 (2025-09-14) | 0.25.0 (2025-09-14) | current | none | BSD-3-Clause | Keep; current. |
| docling | X | 2.149.0 (2026-11-08) | 2.150.0 (2026-11-10) | minor; pin 0.1 mo old | none | MIT | Locked but in no image (see DEP-012). |
| sentence-transformers | X | 6.2.0 (2026-10-21) | 6.2.0 (2026-10-21) | current | none | Apache-2.0 | Locked but in no image (see DEP-012). |
| ruff | D | 0.17.4 (2026-11-05) | 0.17.4 (2026-11-05) | current | none | MIT | Keep; current. |
| mypy | D | 2.4.1 (2026-10-28) | 2.4.1 (2026-10-28) | current | none | MIT | Keep; current. |
| pytest | D | 9.2.0 (2026-10-27) | 9.2.0 (2026-10-27) | current | none | MIT | Keep; current. |
| pytest-timeout | D | 2.4.0 (2025-05-05) | 2.4.0 (2025-05-05) | current | none | MIT | Keep; current. |
| pytest-cov | D | 7.1.0 (2026-03-21) | 7.1.0 (2026-03-21) | current | none | MIT | Keep; current. |
| pytest-xdist | D | 3.8.0 (2025-07-01) | 3.8.0 (2025-07-01) | current | none | MIT | Keep; current. |
| datamodel-code-generator | D | 0.91.0 (2026-11-07) | 0.92.0 (2026-11-10) | minor; pin 0.1 mo old | none | MIT | Take in the next batch. |
| types-pyyaml | D | 6.0.12.20261103 (2026-11-03) | 6.0.12.20261103 (2026-11-03) | current | none | Apache-2.0 | Keep; current. |
| types-openpyxl | D | 3.1.5.20261017 (2026-10-17) | 3.1.5.20261017 (2026-10-17) | current | none | Apache-2.0 | Keep; current. |
| types-reportlab | D | 5.1.0.20261104 (2026-11-04) | 5.1.0.20261104 (2026-11-04) | current | none | Apache-2.0 | Keep; current. |
| types-python-dateutil | D | 2.9.0.20261104 (2026-11-04) | 2.9.0.20261104 (2026-11-04) | current | none | Apache-2.0 | Keep; current. |
| types-jsonschema | D | 4.26.0.20261006 (2026-10-06) | 4.26.0.20261006 (2026-10-06) | current | none | Apache-2.0 | Keep; current. |
| types-markdown | D | 3.11.3.20261108 (2026-11-08) | 3.11.3.20261108 (2026-11-08) | current | none | Apache-2.0 | Keep; current. |
| pillow | R | 13.0.0 (2026-10-16) | 13.0.0 (2026-10-16) | current | none | MIT-CMU | Constraint >=13 met. |

### B. Transitive packages that are behind latest

| Package | Scope | Pin | Latest | Gap | Advisories | Licence | Note |
|---|---|---|---|---|---|---|---|
| cuda-toolkit | X | 13.2.2 | 13.5.0 (2026-11-04) | minor; pin 3.8 mo old | none | see wheel | Bound by its parent (torch/docling); moves with it. |
| docling-slim | X | 2.149.0 | 2.150.0 (2026-11-10) | minor; pin 0.1 mo old | none | MIT | Bound by its parent (torch/docling); moves with it. |
| huggingface-hub | X | 1.33.0 | 2.4.0 (2026-10-29) | major; pin 1.5 mo old | none | Apache-2.0 | Transitive of docling/transformers; major 2.x out; extras only. |
| isort | X | 8.0.1 | 9.0.2 (2026-09-28) | major; pin 8.4 mo old | none | MIT | Dev only (via datamodel-code-generator). |
| mpmath | X | 1.3.0 | 1.4.1 (2026-03-15) | minor; pin 44.2 mo old | none | BSD-3-Clause | Transitive of sympy (torch); extras only. |
| nvidia-cublas | X | 13.4.1.3 | 13.10.0.20 (2026-11-04) | minor; pin 3.8 mo old | none | LicenseRef-NVIDIA-Proprietar | Bound by its parent (torch/docling); moves with it. |
| nvidia-cuda-cupti | X | 13.2.86 | 13.5.25 (2026-11-04) | minor; pin 3.8 mo old | none | LicenseRef-NVIDIA-Proprietar | Bound by its parent (torch/docling); moves with it. |
| nvidia-cuda-nvrtc | X | 13.2.86 | 13.5.37 (2026-11-04) | minor; pin 3.8 mo old | none | LicenseRef-NVIDIA-Proprietar | Bound by its parent (torch/docling); moves with it. |
| nvidia-cuda-runtime | X | 13.2.86 | 13.5.37 (2026-11-04) | minor; pin 3.8 mo old | none | LicenseRef-NVIDIA-Proprietar | Bound by its parent (torch/docling); moves with it. |
| nvidia-cudnn-cu13 | X | 9.26.0.51 | 9.28.1.4 (2026-11-06) | minor; pin 2.0 mo old | none | see wheel | Bound by its parent (torch/docling); moves with it. |
| nvidia-cufft | X | 12.2.0.57 | 12.5.0.14 (2026-11-04) | minor; pin 3.8 mo old | none | LicenseRef-NVIDIA-Proprietar | Bound by its parent (torch/docling); moves with it. |
| nvidia-cufile | X | 1.17.1.22 | 1.20.0.107 (2026-11-04) | minor; pin 6.9 mo old | none | LicenseRef-NVIDIA-Proprietar | Bound by its parent (torch/docling); moves with it. |
| nvidia-cusolver | X | 12.2.0.11 | 12.4.1.2 (2026-11-04) | minor; pin 3.8 mo old | none | LicenseRef-NVIDIA-Proprietar | Bound by its parent (torch/docling); moves with it. |
| nvidia-cusparse | X | 12.7.10.12 | 12.9.4.2 (2026-11-04) | minor; pin 3.8 mo old | none | LicenseRef-NVIDIA-Proprietar | Bound by its parent (torch/docling); moves with it. |
| nvidia-cusparselt-cu13 | X | 0.8.1 | 0.10.0 (2026-09-30) | minor; pin 14.2 mo old | none | NVIDIA Proprietary Software | Bound by its parent (torch/docling); moves with it. |
| nvidia-nccl-cu13 | X | 2.30.7 | 2.32.3 (2026-09-22) | minor; pin 5.1 mo old | none | see wheel | Bound by its parent (torch/docling); moves with it. |
| nvidia-nvshmem-cu13 | X | 3.7.2 | 3.8.0 (2026-09-22) | minor; pin 3.8 mo old | none | see wheel | Bound by its parent (torch/docling); moves with it. |
| nvidia-nvtx | X | 13.2.86 | 13.5.25 (2026-11-04) | minor; pin 3.8 mo old | none | LicenseRef-NVIDIA-Proprietar | Bound by its parent (torch/docling); moves with it. |
| semchunk | X | 3.2.5 | 4.1.1 (2026-06-13) | major; pin 12.4 mo old | none | MIT | Transitive of docling; extras only. |
| soupsieve | X | 4.0.1 | 4.1 (2026-11-10) | minor; pin 0.2 mo old | none | MIT | Bound by its parent (torch/docling); moves with it. |
| typer | X | 0.27.3 | 0.29.0 (2026-11-09) | minor; pin 1.2 mo old | none | MIT | Transitive of docling; extras only. |

### C. Transitive packages that are current and advisory-free (134)

Scope R (in `deploy/requirements.lock`, the runtime image) unless marked X (not in the runtime image: docling/embed extras, dev or test): accelerate 1.15.0 (X); annotated-doc 0.0.5; annotated-types 0.8.0; anyio 4.16.0; argcomplete 3.7.2 (X); ast-serialize 0.13.1 (X); attrs 26.1.0; backports-zstd 1.8.0; beautifulsoup4 4.15.0 (X); black 26.10.1 (X); brotli 1.2.1; brotlicffi 1.2.1.0; certifi 2026.10.23; cffi 2.1.1; charset-normalizer 3.5.2; click 8.5.1; cloudpickle 3.1.2 (X); colorama 0.4.6 (X); colorlog 6.12.0 (X); contourpy 1.4.0; coverage 7.17.2 (X); cuda-bindings 13.5.0 (X); cuda-pathfinder 1.8.6 (X); cycler 0.12.1; defusedxml 0.7.1 (X); dill 0.4.1 (X); doclang 0.9.0 (X); docling-core 2.106.0 (X); docling-ibm-models 4.0.4 (X); docling-parse 7.25.0 (X); et-xmlfile 2.0.0; execnet 2.1.2 (X); faker 40.52.0 (X); fhir-core 1.1.12; filelock 4.2.10 (X); filetype 1.2.0 (X); fonttools 4.68.0; fsspec 2026.9.0 (X); genson 1.4.0 (X); h11 0.16.0; hf-xet 1.8.0 (X); httpcore 1.0.9; idna 3.20; inflate64 1.0.4; inflect 7.6.0 (X); iniconfig 2.3.1 (X); jaraco-functools 4.6.0 (X); joblib 1.6.0 (X); jsonref 1.1.0 (X); jsonschema-specifications 2025.9.1; kiwisolver 1.5.1; langcodes 3.5.1 (X); latex2mathml 3.81.1 (X); librt 0.16.0 (X); lxml 6.1.3; mail-parser 4.10.0 (X); markdown-it-py 4.2.0 (X); marko 2.2.5 (X); markupsafe 3.0.4; mdurl 0.1.2 (X); more-itertools 11.2.1 (X); mpire 2.10.2 (X); multiprocess 0.70.19 (X); multivolumefile 0.2.3; mypy-extensions 1.2.0 (X); narwhals 2.28.0 (X); networkx 3.7 (X); nvidia-cuda-cccl 13.3.5.0.6 (X); nvidia-nvjitlink 13.5.37 (X); olefile 0.47 (X); omegaconf 2.4.0 (X); opencv-python-headless 5.0.0.93 (X); opentelemetry-api 1.45.2; packaging 26.3; pandas 3.1.1 (X); pathspec 1.1.1 (X); platformdirs 4.14.5 (X); pluggy 1.7.0 (X); polyfactory 3.5.0 (X); psutil 7.2.2; psycopg-binary 3.3.8; pybcj 1.0.8; pyclipper 1.4.0 (X); pycparser 3.12; pycryptodomex 3.24.2; pydantic-core 2.50.4; pydantic-settings 2.16.2 (X); pygments 2.21.0 (X); pylatexenc 2.11 (X); pyparsing 3.3.3; pypdfium2 5.15.2 (X); pyppmd 1.3.1; python-dotenv 1.2.4 (X); python-oxmsg 0.0.2 (X); python-pptx 1.0.2 (X); pytokens 0.4.1 (X); pywin32 312 (X); rapidocr 3.10.0 (X); referencing 0.37.0; regex 2026.11.9 (X); requests 2.34.2 (X); rich 15.0.0 (X); rpds-py 2026.9.1; rtree 1.4.1 (X); safetensors 0.8.0 (X); scikit-learn 1.9.1 (X); scipy 1.18.1 (X); setuptools 84.2.1 (X); shapely 2.2.0 (X); shellingham 1.5.4 (X); six 1.17.0 (X); starlette 1.10.0; sympy 1.14.0 (X); tabulate 0.10.0 (X); texttable 1.7.2; threadpoolctl 3.8.0 (X); tokenizers 0.23.3 (X); torch 2.15.0 (X); torchvision 0.29.2 (X); tqdm 4.70.1 (X); transformers 5.22.2 (X); tree-sitter 0.26.1 (X); tree-sitter-c 0.24.2 (X); tree-sitter-javascript 0.25.0 (X); tree-sitter-python 0.25.0 (X); tree-sitter-typescript 0.23.2 (X); triton 3.9.0 (X); typeguard 4.6.0 (X); typing-extensions 4.16.0; typing-inspection 0.4.5; tzlocal 5.4.5; urllib3 2.8.0; websockets 17.4 (X); xlsxwriter 3.3.1 (X).

Licences needing a record among the transitive set: LGPL — inflate64, multivolumefile, pybcj, pyppmd (allow-listed); MPL-2.0 — certifi, pathspec, tqdm (file-level copyleft, unmodified: no action beyond notices); NVIDIA proprietary — nvidia-* CUDA wheels (extras only, pulled by torch; redistribution in an image needs the NVIDIA EULA terms in the notices); PSF — typing-extensions, defusedxml, backports-zstd.
