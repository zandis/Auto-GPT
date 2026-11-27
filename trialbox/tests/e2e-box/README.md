# e2e-box: the whole box, end to end, from a fresh install at the declared size

The standing gate of TRIAGE-1 G1. One run takes a bundle, makes a fresh VM, installs the bundle with its one command
as PRODUCTION on the site host profile (the questions answered at a terminal, the site kit at `/root/site`, the
site's size declared as `TB_SITE_PATIENTS`), with the host's real pinned model pair and never the rehearsal
stand-ins, loads a synthetic hospital of that size, and walks a hospital's day as scripts: accounts for every role, nights (full, delta, cut, shrunken,
identity), FEAS, SCREEN, CASE, the people journey, the route x role walk, three languages, EDC, backup and restore,
update and downgrade, model down, clock and zone, disk full, power cut. Every step is one row of
`metrics/steps.csv`; container CPU, memory and I/O are sampled every 20 s. About four hours on one VM.

Synthetic data only (`tools/make_fixtures.py`). No real patient data, no allow-list entry.

## Run

On the VM host, from a checkout:

```
E2E_BASE_IMG=~/vm/base/noble-server-cloudimg-amd64.img E2E_NODE_MODULES=~/walk/node_modules \
E2E_MODELS_ENV=~/vm/keys/hostmodels.env E2E_JUDGE_PORT=<port> E2E_VERIFIER_PORT=<port> \
BUNDLE=/dev/shm/e2e-box/dist/trialbox-<id>.tar SIZE=50000 E2E_CPUSET=112-175 \
  trialbox/tests/e2e-box/run.sh
```

| Input | Meaning |
|---|---|
| `BUNDLE` | the signed bundle; beside it `trialbox-bootstrap.sh`, its `.sig` and `vendor_ed25519.pub` (`bundle.sh` writes all) |
| `SIZE` | the hospital's patients (default 50,000): the feed's size and the install's declared size |
| `E2E_CPUSET`, `VCPU`, `VMEM` | the VM's host cores (default 112-175), vCPUs (24), memory (96G) |
| `NAME`, `PORTBASE` | the VM (default `vm-e2e`) and its two ports on 127.0.0.1 (ssh, console) |
| `E2E_FWD` | more host forwards of the VM's user network (`,hostfwd=tcp:127.0.0.1:P-:Q`), e.g. a file server's |
| `NEXT_IMG` | the next bundle's media image (and `NEXT_IMG.ready` holding its id): the update journey; else skipped |
| `E2E_MODELS_ENV`, `E2E_JUDGE_PORT`, `E2E_VERIFIER_PORT` | required: the host's served pinned pair (a 0600 `VLLM_API_KEY=` file and its two ports); without them the run refuses to start |
| `E2E_REDCAP_URL`, `E2E_REDCAP_TOKEN_FILE` | the REDCap bench: else the EDC journey is skipped |
| `BASELINE` | the previous run's `metrics/journeys.csv`: a journey with fewer passes or more product failures is red |
| `KNOWN` | the listed failures (default `known.tsv`) |
| `KEEP=1` | leave the VM running for a look; else it is stopped and its folder removed |

`bundle.sh ID SEQ OUTDIR` builds a signed rehearsal bundle of a checkout (`TREE`), as the integration builds do.
`VENDOR_KEY` must be a rehearsal-only key, never the release key: the build runs the code under test on the host.
The bundle is not a rehearsal bundle (no `--rehearsal`); the bundler stages about 62 GB under `TMPDIR_BUNDLE`
(default a private folder in `/dev/shm/e2e-box`, removed after), never on a host's shared `/`.
Nightly, from cron on the VM host (one run at a time):

```
0 18 * * *  flock -n ~/e2e-box/lock env BRANCH=master <inputs above> bash <checkout>/trialbox/tests/e2e-box/nightly.sh
```

where `nightly.sh` fetches the newest head of the branch under test into its own checkout, runs `bundle.sh`, makes
the media of a second bundle of the same tree (seq + 1) for the update journey, and calls `run.sh` with the last
GREEN run's `journeys.csv` as `BASELINE`. The same run, once, on every release candidate before signing.

## Verdict (`verdict.py`)

GREEN only when the install passed, every product failure and every skipped step is listed in `known.tsv` (journey,
step, finding, owner, release note: all five), the run is conclusive (no driver failure, no deviation that failed to
apply), no journey of the baseline regressed or vanished, and every setting that differs between the box as
installed and the box before the update journey is named by an applied DEVIATION row. A refusal the product is meant
to give at that point is counted apart (`BY_DESIGN` in `verdict.py`: two messages). A refusal the journeys provoke
(a cut, shrunken or two-person night, a full disk) passes only with the lake's published snapshot unchanged; every
planned browser action has a row (no result is a failure); every remote command runs with `pipefail`.

## The site kit and the models

`run.sh` puts the kit at `/root/site` before the install, as runbook 01 has the site bring it: the synthetic
hospital A's answers (`tools/rehearse_box/site_answers.yaml`, feed folder `/srv/his-export`) and `mapping/`, the
host baseline (`site/hardening.conf`), the site's compose override (`site/host-models.yml`, `TB_COMPOSE_OVERRIDE`)
and `modelproxy.py`. A VM has no GPU, so the override runs the box's two model servers as forwarders to the host's
served pinned pair on card 0: a `/v1` call needs the box's own key and goes on with the host servers' key
(`/root/site/hostkey`, 0600). The answers are the real models'; selftest and doctor must name no stand-in.

## Deviations (G5)

The gate runs the box as the installer left it. When a step fails on that box and a later journey cannot run
without a change, the change is made through `deviate()` only, after the failure is in the results, and it is a
DEVIATION row: site-needs (a PRODUCTION install that refused: the anchor, backup and log folders, the backup alert
route, `hardening.conf` and the model forward on the egress table, `EGRESS_EXTRA` and `deploy/network.sh apply`;
then the same command again), env-validation (this release's rc1 table refuses the backup key, the held-night
accept and SCREEN on PRODUCTION: the refusal is a row, the rest runs as VALIDATION on the same host profile and
models; it stops applying once rc1 allows them), P-09 (the site mapping fails its check), P-02 (the adapter's cap),
P-10 (no mail relay), P-01 (no backup key from the install), the REDCap bench's egress (after the EDC journey ran on the box as installed; `EGRESS_EXTRA += orchestrator=host:port` and
`deploy/network.sh apply`, the product's documented way). A STARTED row precedes each change.
`verdict.py` compares hashes of the box's settings (never their values) before and after and refuses a change no
DEVIATION row names.

## Secrets (G6)

The install shows the first administrator's password and enrolment code once on its terminal. `ptyinstall.py` cuts
them out of every line it writes (`<redacted>`); the transcript and prompts are 0600; the two values go only to a
root-only file that the harness copies into the run's `creds/` (0700, files 0600), checks, and only then deletes on
the VM. The KEK passphrase is typed only at a prompt that names it (or its repeat) and is cut from every written
line too. After the install the gate searches the box's transcripts and this run's folder for the two values (by
value, not by format). The host model pair's key goes only to `/root/site/hostkey` (0600). Account passwords, authenticator keys and the
bench's token live only in `creds/`; the token
reaches the browser runner as a 0600 file, never an environment variable, and every printed line is scrubbed of it;
no driver prints page text where a secret is shown, and none takes a screenshot.
`tests/unit/test_e2e_box_harness.py` holds the redaction and the verdict.

## Files

`run.sh` (install and order), `journeys.sh` (shell journeys), `actions.py` (browser journeys, walk, languages),
`lib.sh` (rows, waits), `vmctl.sh` (the VM), `ptyinstall.py`, `pw.sh` and `pw/` (Playwright drivers), `jrun.sh`,
`modelproxy.py`, `site/`, `verdict.py`, `known.tsv`, `bundle.sh`, `nightly.sh`.
