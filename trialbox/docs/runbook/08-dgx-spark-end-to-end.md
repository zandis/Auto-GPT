# 8. DGX Spark end to end

**Reader:** Aimedics (an other install form: the DGX Spark by hand).

```sh
make spark-e2e                       # GB10: the pinned judge and verifier
TB_LLM_MODE=stub make spark-e2e      # any Docker host, no GPU: the stub
```

`tools/spark_e2e.sh` runs: host check (`deploy/check_host.sh --gb10`) → `make images` → `tools/pin_model.py` pins both
models into `deploy/site/registry.site.yaml` → compose up with `docker-compose.gb10.yml` → gateway probe → `trialbox
doctor` → ingest → `FEAS GZQO` by mail → `tools/cascade_e2e.py` through the gateway → `make eval-public` → workflow
store tests. PASS means every step passed and every answer came from the pinned build (sha256). The report is in
`build/spark-e2e/<time>-<mode>/report.md`.

**Prerequisites.** Driver 580.142 held (`apt-mark hold`; later 580.x builds break vLLM on GB10, D-79);
`nvidia-container-toolkit`; amd64 emulation for MailHog (test profile only); weights (safetensors or GGUF, never
pickle or Python files) in `deploy/models/gemma-4-26b-a4b-it-4bit` and `deploy/models/qwen3.5-9b-4bit`; about 55 GB of
disk. Spark memory as set, not yet measured on a Spark: `JUDGE_GPU_MEM_UTIL` 0.30, `VERIFIER_GPU_MEM_UTIL` 0.15, and a
memory limit per service (`deploy/gb10-profile.yaml`, D-373). The driver hold is re-tested every 28 days (D-373).

**A 64 GB Spark is refused.** These settings are for the 128 GB Spark. On a Spark with under 96 GiB of memory
(`MemTotal`), `deploy/install.sh`, `deploy/poc.sh` and `make spark-e2e` stop in GPU mode and say why, and the box plan
makes a box without a model. No profile of the 64 GB class is measured, so none is guessed (card 10E-5, D-1335).
Install it with `--mode stub` (structured criteria only), or use a 128 GB Spark.

**Pinning by hand.**

```sh
python -m tools.pin_model --build gemma-4-26b-a4b-it-spark --model-dir deploy/models/gemma-4-26b-a4b-it-4bit \
    --served-name local/gemma-4-26b-a4b-nvfp4
python -m tools.pin_model --build qwen3.5-9b-spark --model-dir deploy/models/qwen3.5-9b-4bit \
    --served-name local/qwen3.5-9b-awq --endpoint verifier
# RTX PRO 6000: the same with the -rtxpro6000 builds
```

`deploy/install.sh` does this for the GPU profile's pair (`python -m tools.pin_model --install <gpu>`, D-142): the
sha256 of the weights under deploy/models, which must be the release `models/registry.yaml` expects (a folder of other
files is refused), the served names compose gives vLLM, and status `candidate` (D-358). A candidate routes in DEV and
TEST only. PRODUCTION routes a `champion`, and only `python -m tools.pin_model --promote <build> --record <record>`
makes one, from a passing qualification record (`docs/runbook/11-qualify.md`). A build already
pinned is kept; missing weights are reported and that model routes nothing until install runs again.

`--verify` re-checks the weights. Restart the gateway after a new pin. `make verify-models` checks every pin at
install.

| Symptom | Fix |
| --- | --- |
| host check fails on driver or runtime | install and hold 580.142; `nvidia-ctk runtime configure --runtime=docker` |
| pin refuses the files | safetensors or GGUF only; remove `.bin` and `.py` files |
| llm-service or llm-verifier times out | first load takes up to 10 min; out of memory: lower `JUDGE_GPU_MEM_UTIL` or `JUDGE_MAX_LEN` |
| gateway `build_unpinned` | the gateway started before the pin: `docker compose restart gateway` |
| gateway `served_model_mismatch` | `JUDGE_MODEL` / `VERIFIER_MODEL` must equal the pin's `--served-name` |
| mailhog `exec format error` | install amd64 emulation (`tonistiigi/binfmt --install amd64`) |

A `public_agency: true` site needs non-PRC builds for every role; the default pair qualifies.

The Spark beside a CPU workstation, two devices with one encrypted link: [the two-device section](08-two-device.md)
(D-373).
