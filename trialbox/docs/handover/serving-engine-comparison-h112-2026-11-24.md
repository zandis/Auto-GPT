# The serving engine comparison, ready for the bench host (2026-11-24)

**Reader:** the people who build TrialBox: lane H, the integrator, the walk and the independent reviewer.

Card H-112 (the owner's go, #639 7121371183, where it is called H-111). A second serving profile behind a switch, and
a harness that sends the same synthetic chart set through each serving engine. Everything here is proved with
stand-ins only: no engine, no GPU and no model ran in this card. Every patient is synthetic. Candidate models are
named A to D here; the walk gets their names privately, in the bench host's settings file.

## Pull request body (draft)

**How the box serves today.** `llm-service` (the judge) and `llm-verifier` (the verifier, defined by each GPU
overlay) run the current serving engine on `model-backend-net` under their backend aliases, port 8000. `model-guard` answers for them on `model-net` (the key on every call, `/health`, the `/v1` routes), and the
gateway calls `llm-service` and `llm-verifier` (`models/routing.yaml`). Their image is pinned in
`deploy/images.lock`, and `tools/images_lock.py check-compose` checks every `deploy/docker-compose*.yml` against it.

**The second profile.** `deploy/docker-compose.serving-second.yml` is added last, over the GPU overlay. It changes
only what runs inside the two servers: the image, the program and its arguments. The names, port 8000 and the aliases
behind `model-guard` stay the same. The card, the memory caps, the networks, the four controls and the health check
stay the GPU overlay's (tested on every GPU stack's rendering). The second serving engine answers the same
`/v1` chat routes and `/health` as the current one, so the gateway, `model-guard` and the services do not change. Every value
comes from the bench host's settings file, `deploy/site/serving-second.env` (not in the repository).
`deploy/serving-second.example.env` lists the keys with placeholders.

**The image: by digest only, never by a tag** (the integrator's ruling 3 on #1459, 7122790579). The overlay and the
settings file name it `<repository>@sha256:<digest>`. It is never pulled (`pull_policy: never`) and never tagged: the
bench host loads it, and `check-image` checks that the local image carries that digest. A tag, or a tag before the
digest, is refused by the switch and by `tools/images_lock.py`. Nothing bench-only reaches a signed bundle:

- `images_lock`'s lock check refuses any `deploy/images.lock` entry for the bench image's variable, and the lock's
  entries are the only third-party images a box's compose files may name. `make_bundle.sh` takes the engine images
  for the model pack from the lock's GPU entries;
- `check-compose` lets only the file marked as the bench profile name that variable;
- the settings file lives under `deploy/site/`, which the host tree never packs.

Each harness run records the digest it ran (`--image-digest`, from `python3 -m tools.serving_profile image`).

**Finding H112-01 stays open by design** (the ruling): bench use on the owner's machine goes ahead; whether
the second engine may ever ship to a hospital box is decided only if the bench shows it is worth it.

No engine build is needed per card or per model: the second engine's
default backend loads a checkpoint folder directly (per its source; not run here).

**The switch.** `SERVING_ENGINE` is set in the settings file, never in `deploy/.env`, because every service reads
`deploy/.env` as its env file. It is `current` when the line or the file is absent, or `second`. `python3 -m
tools.serving_profile files` prints the compose file list:

- **Off:** the box's own `COMPOSE_FILE`, unchanged. Tested: on every GPU stack, `docker compose config` from the
  switch's list renders byte for byte what compose renders reading the box's `.env` itself.
- **On:** that list with the profile added last, only when all of these hold:
  - the box is a TEST or VALIDATION box (`TB_ENV` of `deploy/.env`; absent is PRODUCTION);
  - the settings file is root's or the user's, not writable by group or others, and fills every key;
  - the image is pinned by digest, with no tag;
  - the box's files define both servers.

  Otherwise the switch is refused with the reason. A caller's environment variable decides nothing (tested).
  `compose` runs `docker compose` with the two env files, after clearing every `COMPOSE_*` and `SERVING2_*` variable.
  `trialbox doctor` has a new check, `bench_serving`: the profile's file in `COMPOSE_FILE` FAILs on a box that is
  not TEST or VALIDATION, and is a standing WARN on one that is.

**The harness.** `python -m tools.engine_compare run` puts the frozen synthetic set to one served model, by default
three times. The set is `python -m tools.judge_bakeoff --write-set`: the synthetic hospital's note criteria. Each item
goes through the product's own judge (`judge_bakeoff.judge_item`: the registry prompt, structured output, the quote
check).

What it measures:

- **Time per chart:** the sum of the chart's own call times, as R1-P2 counts a chart's model time. It reports the p50
  and p95 (`run_metrics.percentile`) over the charts that were asked, pooled over the repeats.
- **Throughput:** charts per hour and generated tokens per second, over the summed wall time.
- **GPU memory:** the peak of the card's used memory, from the GPU monitor `run_metrics.Monitor` samples.
- **Repeat agreement, as E2-9 counts it:** the (patient, criterion) answers that differ between runs of the same
  input (the integrator's ruling 2, 7122790579). `run_metrics.lists_compare`, called as is, counts exactly that: a
  pair differs when its answers are not all equal, and a pair missing from a run counts as an answer of its own.
  The table reports it in the walk's form (7117120038), so the two read side by side:
  "differences from run 1 in (patient, criterion) answers: run 2 28 (27 on X, 1 on Y); run 3 22 (22 on X)". It also
  gives, over all the runs, the pairs that differ and the patients with such a pair.
- **The image:** the digest the engine ran.

`table` joins the runs into one table of counts and times. The engine, the candidate and the quantization are short
labels, refused if they look like anything else. No patient id, criterion text, excerpt or quote reaches a file or
the console (the stand-in test scans every written file and the output). Criterion ids of the synthetic set appear,
as in the walk's line.

**Files outside the card.**

- `tools/trialbox/doctor.py` (the check `bench_serving`, added to `CHECKS`).
- `tests/unit/test_compose_limits.py`: one stack added to `STACKS` (the bench host's shared-quota stack with the profile),
  so the limits and the hardening tests lint and render the new file. No assertion changed.
- `tests/unit/test_trialbox_doctor.py`: `bench_serving` added to the set of check names that
  `test_default_install_passes` enumerates. Allowed by the integrator's ruling 1 (7122790579).
- `tools/images_lock.py`: the bench image's rules (above).

**Tests.** `tests/unit/test_serving_engine_h112.py`; the invariant is
`test_the_switch_off_renders_the_same_bytes_as_compose_reading_the_box`.

## The walk's commands on the bench host

Run from the repository checkout, as root, with the walk's own copies (never committed):

1. Load the second engine's image from the file whose licence was read (`docker load -i <file>`). Copy
   `deploy/serving-second.example.env` to `deploy/site/serving-second.env` (`chmod 600`) and fill it: the image's
   `<repository>@sha256:<digest>`, its server program, and per server the candidate's folder, the served name the
   gateway's registry expects and the engine's options file. Keep `SERVING_ENGINE=current` for now.
2. Freeze the set once: `python -m tools.judge_bakeoff --write-set <results>/h112-set.jsonl`. Note its sha256.
3. The current engine, for each candidate X (A to D) and its quantization label Q:

   ```
   python -m tools.engine_compare run --engine current --candidate X --quant Q \
       --image-digest "$(python3 -m tools.serving_profile image --deploy deploy)" \
       --base-url <the judge's /v1, as R1-P2's walk reaches it> --served-name <served name> \
       --key-file <root-only key file> --set <results>/h112-set.jsonl --expect-set-sha <sha256> \
       --out <results>/h112/current-X
   ```

4. Set `SERVING_ENGINE=second` in `deploy/site/serving-second.env`, then:

   ```
   python3 -m tools.serving_profile check-image --deploy deploy
   python3 -m tools.serving_profile compose --deploy deploy -- --profile gpu up -d --wait llm-service llm-verifier
   ```

   Then run step 3 again with `--engine second` and `--out <results>/h112/second-X`.
5. Make the table: `python -m tools.engine_compare table <results>/h112/* --out <results>/h112/table.md`. Post
   `table.md` only.
6. Put the box back: set `SERVING_ENGINE=current`, then run `python3 -m tools.serving_profile compose --deploy deploy
   -- --profile gpu up -d --wait llm-service llm-verifier`.

## What is not proven until the walk runs it

These are untested: no engine, GPU or model ran in this card.

- **Start-up:** that the second engine starts with this command line at the release the walk loads (the program,
  `serve`, `--served_model_name`, `--log_level`, `--config`, read from its source today).
- **The served name:** that the engine's `/v1/models` and its answers give the served name.
- **Structured output:** that it honours the judge's JSON schema.
- **Weights:** that the candidates' 4-bit formats load in it with the same quantization as the current engine.
- **Memory and size:** that its memory share and sequence length fit the card or its partition.
- **Chat template and decoding:** that its chat template matches the current engine's, and that its sampling
  defaults give the same deterministic decoding.
- **The digest on the host:** that the loaded image keeps its repository digest, which `check-image` and compose
  look for. An image store that keeps no digests for a loaded file would refuse it (finding H112-08).
- **Timing:** any time, throughput or memory figure.

The harness's timing is the client's own measure of each call. R1-P2 also uses the gateway's audit and the servers'
counters; that work is PR #1451, which is not on master. The definitions match, but the timing points do not: R1-P2
measures through the gateway, and this harness calls the engine directly.

## Licences checked

| Artefact | Licence | Where it was read |
| --- | --- | --- |
| The second serving engine's source | Apache-2.0 | The `LICENSE` file at the root of its source repository |
| Its installable package | "a vendor software licence agreement, Apache License 2.0, and others" | The package index's metadata for the package |
| A proprietary runtime component the package depends on | Proprietary | The package index's classifier |
| The vendor's release container | Not read | Its registry asked for a sign-in |

This card adds no artefact: no image, no package and no weights. The image is a placeholder that the bench host
fills. The walk reads the container's licence before using it.

## Findings

In `serving-engine-comparison-h112-2026-11-24/findings.json` (card H112).
