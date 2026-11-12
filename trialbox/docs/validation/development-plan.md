# Software development plan

*Card T-654 (deep review ENG-001, ENG-003, ENG-004, ENG-008). Status: living; a light plan shaped after IEC 62304
§5.1. No signature and no owner step: D-311 removed every development gate. The full plan of work is
`docs/plan/28-master-plan-v6.md`; this page says how a change is made, checked and recorded.*

## 1. Scope

All of `trialbox/`. The class of each part is in `software-safety-classification.md` (this folder): the screening
core is internal class B, the rest class A. Building, testing and sharing use synthetic or public data only.

## 2. How a change is made

1. **One card, one branch, one pull request.** A card of the master plan (§6.2) names its goal, files, acceptance
   tests and the findings it closes. The branch is `agent/<card id>-<slug>`, cut from current `master`.
2. **The pull-request template** (`.github/PULL_REQUEST_TEMPLATE.md`) asks for the card, whether a class B path is
   touched, the decision number if any, the tests that show the change, and the problems it closes.
3. **Decisions are files**: `docs/decisions/D-nnn-<slug>.md` and one row in `docs/decisions/REGISTRY.md`.
4. **Merge on green CI.** A class B change also gets one automated adversarial review (D-311). No human approval is
   required.

## 3. Verification: what CI runs

Workflow `.github/workflows/trialbox-ci.yml`, on every pull request and every push to `master`:

| Job | What it checks |
| --- | --- |
| `lint`, `types` | ruff (with the `S` security rules), ruff format, actionlint, mypy strict |
| `docs` | doclint and decision numbers |
| `contracts`, `trace` | generated contracts and rulesets match their sources; the traceability CSV (warnings) |
| `unit` | the test suite, including property, mutation-killing and engine-agreement tests, and the journeys: one per console role on the in-process synthetic site, the PQ script a site walks (`tests/e2e/journeys/`, D-448); the journeys a site re-runs after a long break are listed in `rerun_after_break.yaml` beside them (RSK-64) |
| `e2e-simple`, `goldens` | the whole path on a synthetic hospital; the committed goldens do not move unasked |
| `data-scan` | no real patient data or identifier in the tree or the test log |
| `security` | secret scanning (detect-secrets) and a static security scan (bandit), `tools/security_scan.py` |
| `shell`, `images`, `demo-boot` | shellcheck, hadolint, the demo image boots and every seeded account signs in |

The supply-chain workflow adds the hashed lock check, pip-audit and the licence gate. Reviewed exceptions of the
security scans are in `tools/security_scan_ignores.yaml`, each with its reason and a count, so that a new finding
in a listed file still fails.

## 4. Records

| Record | Where |
| --- | --- |
| Safety classification | `software-safety-classification.md` (this folder) |
| SOUP list | `soup.csv` (this folder) |
| Problems and their resolution | `problems.csv` (this folder) |
| Decisions | `docs/decisions/` |
| Test evidence | the CI run of each commit; `docs/VALIDATION.md` for the drills |
| Dependencies | `uv.lock` (hashed), `deploy/requirements.lock`, the SBOM of `make licences` |

## 5. Problem resolution

GitHub Issues are off on this repository, so the problem log is `problems.csv`. A problem is any defect, review
finding or failed check that is not fixed in the pull request that finds it.

* **Columns**: `id`, `title`, `found_by`, `severity` (high, medium or low), `class` (A or B), `state` (open, fixing,
  fixed, wont_fix), `fix_pr`, `verifying_test`, `notes`.
* **Opening**: the pull request or review that finds the problem adds the row, state `open`.
* **Closing**: the pull request that fixes it sets `fixed`, its own number in `fix_pr`, and the test node id that
  fails without the fix in `verifying_test`. A `wont_fix` row says why in `notes`.
* **Release**: a release is blocked only by an open wrong-answer, data-loss or security problem (D-311 S5).

## 6. SOUP

Software of unknown provenance is every third-party component the product runs. `soup.csv` lists the ones on the
path of the screening core and the box's security, with purpose, version, class of the unit that uses it, and the
known problems that matter. Versions come from `uv.lock`, the JVM build files and the Dockerfiles; a pull request
that moves one of them updates its row. The full component list is the SBOM; pip-audit and the image scans report
known vulnerabilities.

## 7. Changes to this plan

In the same pull request as the change of process it describes.
