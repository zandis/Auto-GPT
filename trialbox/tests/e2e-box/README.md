# e2e-box: the whole box, end to end, from a fresh install at the declared size

The standing gate of TRIAGE-1 G1. One run takes a bundle, makes a fresh VM, installs the bundle with its one command
(the questions answered at a terminal, the site's size declared as `TB_SITE_PATIENTS`), loads a synthetic hospital
of that size, and walks a hospital's day as scripts: accounts for every role, nights (full, delta, cut, shrunken,
identity), FEAS, SCREEN, CASE, the people journey, the route x role walk, three languages, EDC, backup and restore,
update and downgrade, model down, clock and zone, disk full, power cut. Every step is one row of
`metrics/steps.csv`; container CPU, memory and I/O are sampled every 20 s. About four hours on one VM.

Synthetic data only (`tools/make_fixtures.py`). No real patient data, no allow-list entry.

## Run

On the VM host, from a checkout:

```
E2E_BASE_IMG=~/vm/base/noble-server-cloudimg-amd64.img E2E_NODE_MODULES=~/walk/node_modules \
BUNDLE=/dev/shm/e2e-box/dist/trialbox-<id>.tar SIZE=50000 E2E_CPUSET=112-175 \
  trialbox/tests/e2e-box/run.sh
```

| Input | Meaning |
|---|---|
| `BUNDLE` | the signed bundle; beside it `trialbox-bootstrap.sh`, its `.sig` and `vendor_ed25519.pub` (`bundle.sh` writes all) |
| `SIZE` | the hospital's patients (default 50,000): the feed's size and the install's declared size |
| `E2E_CPUSET`, `VCPU`, `VMEM` | the VM's host cores (default 112-175), vCPUs (24), memory (96G) |
| `NAME`, `PORTBASE` | the VM (default `vm-e2e`) and its two ports on 127.0.0.1 (ssh, console) |
| `NEXT_IMG` | the next bundle's media image (and `NEXT_IMG.ready` holding its id): the update journey; else skipped |
| `E2E_MODELS_ENV`, `E2E_JUDGE_PORT`, `E2E_VERIFIER_PORT` | the host's served model pair (a 0600 file with its key): else the box keeps its stand-ins |
| `E2E_REDCAP_URL`, `E2E_REDCAP_TOKEN_FILE` | the REDCap bench: else the EDC journey is skipped |
| `BASELINE` | the previous run's `metrics/journeys.csv`: a journey with fewer passes or more product failures is red |
| `KNOWN` | the listed failures (default `known.tsv`) |
| `KEEP=1` | leave the VM running for a look; else it is stopped and its folder removed |

`bundle.sh ID SEQ OUTDIR` builds a signed rehearsal bundle of a checkout (`TREE`), as the integration builds do.
Nightly, from cron on the VM host (one run at a time):

```
0 18 * * *  flock -n ~/e2e-box/lock env BRANCH=master <inputs above> bash <checkout>/trialbox/tests/e2e-box/nightly.sh
```

where `nightly.sh` fetches the newest head of the branch under test into its own checkout, runs `bundle.sh`, makes
the media of a second bundle of the same tree (seq + 1) for the update journey, and calls `run.sh` with the last
run's `journeys.csv` as `BASELINE`. The same run, once, on every release candidate before signing.

## Verdict (`verdict.py`)

GREEN only when the install passed, every product failure is listed in `known.tsv` (journey, step, finding, owner,
release note), no journey regressed against the baseline, and every setting that differs between the box as
installed and the box before the update journey is named by a DEVIATION row. A failure the driver caused or a
refusal the product is meant to give at that point is counted apart (`HARNESS`, `BY_DESIGN` in `verdict.py`).

## Deviations (G5)

The gate runs the box as the installer left it. When a step fails on that box and a later journey cannot run
without a change, the change is made through `deviate()` only, after the failure is in the results, and it is a
DEVIATION row: P-09 (the site mapping declares no table), P-02 (the adapter's cap), P-10 (no mail relay), the
served models, the REDCap bench's egress (`EGRESS_EXTRA` and `deploy/network.sh apply`, the product's documented way).
`verdict.py` compares hashes of the box's settings (never their values) before and after and refuses a change no
DEVIATION row names.

## Secrets (G6)

The install shows the first administrator's password and enrolment code once on its terminal. `ptyinstall.py` cuts
them out of every line it writes (`<redacted>`); the transcript and prompts are 0600; the two values go only to a
root-only file that the harness moves into the run's `creds/` (0700, files 0600) and deletes on the VM. Account
passwords, authenticator keys and the bench's token live only in `creds/`; no driver prints or screenshots them.
`tests/unit/test_e2e_box_harness.py` holds the redaction and the verdict.

## Files

`run.sh` (install and order), `journeys.sh` (shell journeys), `actions.py` (browser journeys, walk, languages),
`lib.sh` (rows, waits), `vmctl.sh` (the VM), `ptyinstall.py`, `pw.sh` and `pw/` (Playwright drivers), `jrun.sh`,
`modelproxy.py`, `verdict.py`, `known.tsv`, `bundle.sh`, `nightly.sh`.
