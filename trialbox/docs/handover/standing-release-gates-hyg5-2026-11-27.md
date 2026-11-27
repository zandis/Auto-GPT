# HYG5: standing release gates over the tree, report-only until a dated switch

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders, so in one
language.

- **Card:** release hygiene item 5 (the integrator's 7211450855; rule set and landing ruled through the lead,
  7213761934): a code-pattern scan with a pinned rule set, two secret scanners with no verification, a platform-manifest
  scan of `deploy/platform`, and the Dockerfile linter in the release build
- **Date:** 2026-11-27
- **Base:** int/r1plus1 ae2d17c7
- **Findings:** [`standing-release-gates-hyg5-2026-11-27/findings.json`](standing-release-gates-hyg5-2026-11-27/findings.json)
  (HYG5-01 to HYG5-05)

## Files outside the card

None. Lane H's own: `tools/supply_chain/standing_gates.py` (new), `tools/supply_chain/__main__.py` (the
`standing-gates` command), `Makefile` (`standing-gates`), `.github/workflows/trialbox-images.yml` (one step in the
`images` job, and its reports kept with the gate record).

The card's own: `tests/unit/test_standing_release_gates_hyg5.py`, this page and its findings.

## What runs

`make standing-gates` in the `images` job (the release build), once per run (amd64; the tree is the same on both
platforms):

| Scan | Pinned image | On | Flags that matter |
| --- | --- | --- | --- |
| code patterns | version 1.187.0, by digest | `trialbox/`, `.github/` | rule set at commit `a5ad1714` (security folders for Python, Dockerfiles, shell), severity ERROR, comment pragmas not honoured, no metrics |
| secrets, first scanner | v8.30.1, by digest | the whole tree | its inline allow comments not honoured |
| secrets, second scanner | 3.100.1, by digest | the whole tree | no verification (no secret leaves the runner) |
| platform manifests | 3.4.11, by digest | `trialbox/deploy/platform` | no download |
| Dockerfile linter | v2.12.0, by digest (the one D-1343 pins) | all 9 Dockerfiles | ignore pragmas not honoured |

Each tool runs with no network and the tree mounted read-only. The rule set is fetched beforehand at its commit, and
another commit is refused. No ignore file, allow-list or configuration file is given to any tool. The test holds the
tree free of their ignore files (a planted one is found and counted as a finding).

**Report-only until 2026-12-17. That date is a placeholder, "date: by ruling":** the integrator sets it. Until then
the step may not fail the job. From that date the workflow sets `STANDING_GATES_ARGS="--fail-at any"` and drops
`continue-on-error`, and any finding, or any scan that did not run, fails it. The same pattern as D-1343. No decision
number was taken: D-1465 and up are handed out by the lead.

## What they find now (counts by rule, never the matched text)

Measured in this session on int/r1plus1 3390bf74, with the same tool versions and rule commit run from their Python
packages (no container engine here). The base has since moved to ae2d17c7, so the counts may differ by a few.

- **Code patterns: 162** (HYG5-01): dangerous-subprocess-use-audit 133, use-defused-xml 18,
  dangerous-subprocess-use-tainted-env-args 3, dangerous-os-exec-audit 2, subprocess-shell-true 2,
  use-defused-xml-parse 2, php-version-usage 1, missing-user 1. Most are audit rules that flag every subprocess call.
- **Platform manifests: 152 failed, 1665 passed** (HYG5-02): CKV_K8S_21 (default namespace) 41, CKV_K8S_14 (image
  tag) 20, CKV_K8S_11 (CPU limits) 20, CKV_K8S_43 (image digest) 20, CKV_K8S_35 (secrets as environment) 14,
  CKV_K8S_8 (liveness probe) 14, CKV_K8S_22 (read-only root) 14, CKV_K8S_40 (high UID) 4, CKV_K8S_23 (root admitted)
  3, CKV_K8S_38 (service account token) 2. The image tag and digest ones may be the overlays' image overrides that a scan
  of the raw files cannot see.
- **Dockerfile linter: not run here** (no container engine). Nine ignore pragmas are already in five Dockerfiles
  (`demo/Dockerfile` 2, `backup.Dockerfile` 2, `embed.Dockerfile` 2, `jvm.Dockerfile` 2, `python.Dockerfile` 1).
  The gate does not honour them, so the rules they waive (DL3006, DL3008, DL3013, SC2086) will count (HYG5-03).
- **Both secret scanners: not run here.** Fetching and running them was refused by this session's permission check,
  so the first run of either is CI's (HYG5-04).

## What was not verified

- Any of the five in a container: no container engine here. The commands are checked by the unit test with a fake
  runner. Whether each image's entry point takes them as written is first shown by CI (HYG5-05).
- The secret scanners' and the Dockerfile linter's findings.
