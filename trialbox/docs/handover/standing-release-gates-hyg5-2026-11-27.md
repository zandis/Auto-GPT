# HYG5: standing release gates over the tree, measured against a baseline that only goes down

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders, so in one
language.

- **Card:** release hygiene item 5 (the integrator's 7211450855; ruled in 7213778687): a code-pattern scan with a
  pinned rule set, two secret scanners with no verification, a platform-manifest scan of `deploy/platform`, and the
  Dockerfile linter in the release build
- **Date:** 2026-11-27
- **Base:** int/r1plus1 ae2d17c7
- **Findings:** [`standing-release-gates-hyg5-2026-11-27/findings.json`](standing-release-gates-hyg5-2026-11-27/findings.json)
  (HYG5-01 to HYG5-05)
- **Baseline:** `deploy/security/standing-gates-baseline.json` (counts by rule only)

## Files outside the card

None. Lane H's own: `tools/supply_chain/standing_gates.py` (new), `tools/supply_chain/__main__.py` (the
`standing-gates` command), `deploy/security/standing-gates-baseline.json` (new), `Makefile` (`standing-gates`),
`.github/workflows/trialbox-images.yml` (one step in the `images` job, and its reports kept with the gate record).

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

**What fails (the integrator's ruling 7213778687).** The step blocks the release build.

- **New findings, from the first day.** Each tool's counts by rule are compared with the baseline file: a count above
  its line fails, and a rule the file does not name counts against 0. The file holds today's counts by rule only,
  never matched text or a path. A line may only go down: the test holds every line at or below the first baseline,
  written into the test itself, so raising one means changing what the test asserts.
- **Every finding, by date:** the two secret scanners now (they have no baseline line), the code-pattern scanner and
  the Dockerfile linter from 2026-12-17 (with D-1343). The platform-manifest scanner has no date: it stays on its
  baseline until the platform path it scans ships.
- A scan that did not run, or a tool's ignore file in the tree, fails too.

The dates are in the code (`BLOCKS_FROM`), so the build starts failing on 2026-12-17 without a change, unless the
counts are at zero by then. No decision number was taken: D-1465 and up are handed out by the lead.

## What they find now (counts by rule, never the matched text)

Measured in this session on int/r1plus1 ae2d17c7, with the same tool versions, flags and rule commit, run from their
Python packages (no container engine here). These are the baseline file's lines.

- **Code patterns: 162** (HYG5-01): dangerous-subprocess-use-audit 133, use-defused-xml 18,
  dangerous-subprocess-use-tainted-env-args 3, dangerous-os-exec-audit 2, subprocess-shell-true 2,
  use-defused-xml-parse 2, php-version-usage 1, missing-user 1. Most are audit rules that flag every subprocess call.
- **Platform manifests: 152 failed, 1665 passed** (HYG5-02): CKV_K8S_21 (default namespace) 41, CKV_K8S_14 (image
  tag) 20, CKV_K8S_11 (CPU limits) 20, CKV_K8S_43 (image digest) 20, CKV_K8S_35 (secrets as environment) 14,
  CKV_K8S_8 (liveness probe) 14, CKV_K8S_22 (read-only root) 14, CKV_K8S_40 (high UID) 4, CKV_K8S_23 (root admitted)
  3, CKV_K8S_38 (service account token) 2. The image tag and digest ones may be the overlays' image overrides that a scan
  of the raw files cannot see.
- **Dockerfile linter: 22** (HYG5-03), its ignore pragmas not honoured: DL3006 7, DL3008 4, SC2086 4, DL4006 2,
  DL3010 1, DL3013 1, DL3015 1, SC1091 1, SC2046 1. Nine ignore pragmas are already in five Dockerfiles; the rules
  they waive (DL3006, DL3008, DL3013, SC2086) are among these counts.
- **Both secret scanners: not run here.** Fetching and running them was refused by this session's permission check,
  so the first run of either is CI's (HYG5-04). They block now, so a finding there fails the first run, and the
  finding list goes to the lead.

## What was not verified

- Any of the five in a container: no container engine here. The commands are checked by the unit test with a fake
  runner. Whether each image's entry point takes them as written is first shown by CI (HYG5-05). A scan that does
  not run fails the step, so that first run can be red for this reason alone.
- The secret scanners' findings.
- The counts from the images against the counts from the Python packages: the same versions and flags, not the same
  runtime. A difference shows as a count above the baseline on CI's first run.
