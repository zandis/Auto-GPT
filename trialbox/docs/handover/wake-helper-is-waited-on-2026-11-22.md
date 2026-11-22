# H-86: the 32 GB profile's wake helper is waited on, so `up --wait` reaches healthy

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders, so in one
language.

- **Card:** H-86 (Ring 0: the minimum release must install on the 32 GB profile)
- **Date:** 2026-11-22
- **Findings:** [`wake-helper-is-waited-on-2026-11-22/findings.json`](wake-helper-is-waited-on-2026-11-22/findings.json)
  (H86-01 to H86-03)
- **Tests:** `tests/unit/test_compose_one_shots_h86.py`

## Pull request body (draft)

### What changes for a box

On the 32 GB profile (`install.sh ... --gpu rtx5090`, and `--gpu rtx4090`, which uses the same overlay),
`model-guard` now starts only after the last start-up helper, `judge-wake-init`, has woken the judge and exited 0.
Nothing else changes: the rendered compose of the other 14 stacks that tests/unit/test_compose_limits.py lints is
identical to master's (`docker compose config --format json`, compared stack by stack).

### Why

The 32 GB start-up is a chain of one-shot helpers: `judge-sleep-init` (waited on by `llm-verifier`),
`model-swap-init` (waited on by `judge-wake-init`) and `judge-wake-init`, which no service waited on.
`docker compose up --wait` fails on a container that has exited, code 0 included, unless another service waits on it
with `condition: service_completed_successfully`; the message is the bench's, `container ... exited (0)` (the string
`container %s exited (%d)` is in the installed compose v5.7.1 plugin). So `install.sh` (line 872), `poc.sh` (352),
`tools/trialbox/update.py` (1622) and the boot unit `deploy/systemd/trialbox.service` (19) all stop with "the stack
did not become healthy" on this profile.

### Which service waits, and why the dependency is true

`model-guard`. It is the only way to the judge (D-177: the gateway reaches the vLLM servers through it alone), and
the gateway takes the judge for awake until its first swap (`services/gateway/swap.py`: `active` is `None`, "state
unknown, nothing held back", so `awake()` is true and a call is sent without a wake). Before `judge-wake-init` has
run, a call through the guard reaches a sleeping judge. The guard opening after the wake makes the gateway's
assumption true. No cycle: the helpers call the vLLM servers on `model-backend-net` by their `-vllm` aliases, not
through the guard, and nothing in the chain depends on `model-guard` (the guard test checks the graph).

The gateway was not chosen: it is in the base file with no profile, and a dependency on a `gpu`-profile helper would
tie every stack's gateway to it, and a `docker compose up gateway` (install.sh 974 restarts the gateway) would re-run
the whole swap chain.

### What a re-run of the helper does

Compose starts an exited dependency again on `up`. That already happens on master for every helper on every
`docker compose up` of the stack (install, update, boot); this change adds only `docker compose up model-guard`
(`docker compose restart model-guard` starts no dependency). On a re-run the chain posts `/sleep?level=1` to the
judge, then to the verifier, then `/wake_up` to the judge. In vLLM a sleep of a sleeping engine and a wake of an
awake one are logged and do nothing (read from vLLM's executor; not checked at the pinned release). Not safe while a
screening run holds the card for the verifier: the chain puts the verifier to sleep under the run, and the gateway
still believes the verifier awake (H86-02). That hazard is master's (any `up` mid-run); this change does not widen it
beyond `up model-guard`.

### Compose versions

`install.sh` and `poc.sh` check only that the plugin is there (`docker compose version`); they enforce no minimum.
The files themselves need 2.24 or newer (the `env_file` long form `{path, required}`; `tools/measure48-host.sh`
asks 2.24.4 for `!override`). The `up --wait` treatment of an exited one-shot (passed only when waited on with
`service_completed_successfully`) is not known to differ across the versions the files accept; it was not run here
against any version (no Docker daemon in the session).

### The sweep

Every compose file under `deploy/` was read for a service with `restart: "no"`:

- `docker-compose.rtx5090.yml`: `judge-sleep-init` (waited on by `llm-verifier`), `model-swap-init` (by
  `judge-wake-init`), `judge-wake-init` (now by `model-guard`).
- `docker-compose.acceptance.yml`: `acceptance-directory-seed`, waited on by `authelia`. Not affected.
- `platform/docker-compose.platform.yml`: `doctor`, profile `doctor`, started by `docker compose run --rm doctor`,
  never by `up`. Not affected; the test holds it only while the file says so.
- The other GPU profiles (`gb10`, `rtxpro6000`, `dgpu48`), test, poc, identity, box, monitoring, secrets,
  shared-quota, testbench and the two-device files have no one-shot service.

### The guard

`tests/unit/test_compose_one_shots_h86.py`, over every stack of test_compose_limits (its YAML merge, so it needs no
Docker and runs in every CI job): every active one-shot is waited on with `service_completed_successfully`, its
waiters reach a long-running service, and the `depends_on` graph has no cycle. On master's overlay it fails
(`test_every_one_shot_is_waited_on_and_no_cycle[...rtx5090.yml]`, the guard and planted cases: 3 failed, 16
passed); on this branch 19 passed. A planted one-shot nobody waits on, a chain of helpers that reaches no
long-running service and a cycle each fail it.

### For a box already installed

An update unpacks the new release and runs `up --wait` with the files of `COMPOSE_FILE` in `deploy/.env`, the
overlay among them, so it picks the new overlay up (read in `tools/trialbox/update.py`, not run).

### What a person must run to prove it

On a real 32 GB card, or the bench:

1. `deploy/install.sh <bundle> --mode gpu --gpu rtx5090 --rehearsal` reaches "every service healthy" with no
   `judge-wake-init exited (0)`; `docker compose ps -a` shows the three helpers `Exited (0)` and `model-guard`
   healthy.
2. A reboot: the boot unit's `up --wait` reaches healthy (`systemctl status trialbox`), and the first chat after it
   is answered by the judge.

Neither was run here.

## Findings

| Id | Severity | Claim | Basis |
| --- | --- | --- | --- |
| H86-01 | High | the 32 GB profile never reached healthy: `judge-wake-init` was waited on by no service, so `up --wait` failed on its exit 0; fixed | shown |
| H86-02 | Medium | a `docker compose up` while a screening run holds the card re-runs the swap chain and puts the verifier to sleep under the run | hypothesis |
| H86-03 | Medium | on `--gpu rtx4090` (`--scale llm-verifier=0`) `model-swap-init` waits for a verifier that is not there and fails after its 20-minute loop, so the judge is never woken and the stack does not reach healthy | hypothesis |

H86-03 is outside this card: with the verifier scaled to 0 the chain needs a branch that skips the verifier steps.
It was not run; the reading is from the overlay and install.sh line 791.
