# Supplier assessments

*Card T-215 (TB-ASSESS-01 WS-12.1; VMP §4). Decision D-344. Status: living; changed by the pull request that adds a
supplier or changes what one supplies. Versions, licences and known problems per component are in `soup.csv` (this
folder, card T-654); this page is about the supplier and how TrialBox relies on it, and does not repeat the versions.*

GAMP 5 category: 1 infrastructure, 3 standard product, 4 configured product, 5 custom (TrialBox's own). Assessment
kind: **record** (what is used and how it is pinned is recorded; behaviour is covered by TrialBox's own tests),
**tested** (TrialBox's tests exercise it directly), **site-owned** (the site's system; TrialBox records its
configuration and checks it at install, and does not test it functionally).

| Supplier or component | What it supplies | Category | Pinned by | Assessment | How TrialBox relies on it and checks it |
| --- | --- | --- | --- | --- | --- |
| Python and the PyPI packages | language runtime, libraries | 1 and 3 | `uv.lock`, `deploy/requirements.lock` | tested | the whole CI suite; pip-audit and the licence gate in the supply-chain workflow |
| PostgreSQL | the record store | 3 | `deploy/images.lock` | tested | integration tests against a real Postgres; the backup and restore drills |
| DuckDB | the lake's SQL engine | 3 | `uv.lock` | tested | engine-agreement tests against the Python and CQL engines (class B use) |
| Docker images (base images) | container runtime contents | 1 | `deploy/images.lock` (by digest) | record | hadolint; the image build and `demo-boot` jobs; the update path refuses an unpinned digest |
| vLLM | model serving | 3 | the serving record and `deploy/images.lock` | tested | the qualification record per build (D-313); the canary; a version change is CC1 |
| Model weights (judge, verifier, embedder) | the model pair and embeddings | 4 in TrialBox's use (custom sub-system, VMP §5) | `models/registry.yaml` (hash per build) | tested | `trialbox eval qualify`; the licence check per build (deep review LLM-012, DEP-011) |
| Caddy and Authelia | TLS and sign-in | 4 | `deploy/identity/` and `deploy/images.lock` | tested | second-factor tests on every sign-in route (T-505a); the identity compose file |
| HAPI FHIR (while present) | FHIR server | 3 | `deploy/images.lock` | tested | contract tests |
| REDCap (the site's) | the site's EDC | 4, site-owned | the site's version, recorded at install | site-owned | the simulator (`services/rc_sim/`) in CI; the round trip on the site's test project where one exists |
| CGMH B200 container platform | host OS, runtime, GPU driver, scheduler, storage class, network policy, the namespace | 1 (host) and 4 (namespace, quota, policies), site-owned | the platform team's versions, recorded at install | site-owned | `doctor --platform`; the isolation tests; a platform change re-runs both (TB-PLAN-05 WS-11.8) |
| Japan site appliance hardware and Windows, WSL2, Ubuntu, NVIDIA driver | the box | 1 | `release.json` and `check_host --wsl2` output | record | `doctor`; `deploy/check_host.sh` |
| GitHub (repository, Actions) | source control, CI | 1 (development tooling) | the workflow files under `.github/workflows/` | record | the CI results are the verification evidence; actions pinned by version |
| Public reference data (CT.gov, terminologies) | reference packs | 3 (data) | the pack manifest | tested | the pack verifies and loads (TST-UNIT-08); NOTICE lists every source |

## Rules

1. A new supplier gets a row here and its components get rows in `soup.csv` in the same pull request.
2. A **site-owned** component is never functionally tested by TrialBox; its configuration is recorded at install and
   checked by `doctor`. A change to it is a CC6 change for the site (`change-control.md`, this folder).
3. An advisory against a component is a row in `problems.csv` when it matters to TrialBox's use; the SOUP review at
   each release reads the advisory scan.
4. No supplier questionnaire, audit visit or signed assessment is part of development (D-311). A site may ask for one
   before real data is read; the answers then go in the release record.
