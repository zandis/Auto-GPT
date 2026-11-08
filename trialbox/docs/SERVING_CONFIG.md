# Serving-configuration record and the model gate on a card (FR-MOD-10, NFR-PERF-08/09, D-111)

## The record

`tools/serving_config.py` defines the record (schema `tb-serving-config/1`, one JSON object per GPU run):

| field | what |
| --- | --- |
| `card` | name, total memory (MiB), driver, CUDA, card count, `capped_to` (for example "RTX 5090 (32 GB)") |
| `memory_used_mib` | `nvidia-smi` with both servers loaded |
| `servers[]` | one per vLLM container: role, image, `vllm_version`, `model`, `served_model_name`, `quantization`, `max_model_len`, `max_num_seqs`, `enforce_eager`, `gpu_memory_utilization` (the memory fraction), `kv_cache_dtype`, other flags, `model_files` (path, bytes, sha256 of every file) and `model_files_sha256` (one hash over them) |
| `captured_at`, `host`, `notes` | when and where |

`--api-key` is never recorded. `python -m tools.serving_config validate <file>` lists what a record is missing.

`eval/parity/serving_config_2026-11-06.json` is the 6 Nov run, written by hand from `deploy/gcp/gpu-sim-startup.sh`
and the review: complete except the model-file hashes, which that run did not record (`validate` lists the four).

## Capturing it (needs the GPU VM; not run in step 5)

`capture` runs on the GPU box itself: `docker inspect` of each vLLM container, `nvidia-smi`, `vllm.__version__`
inside the container and the sha256 of every file of each model's snapshot under `/models`. This container reaches
the VM over HTTP only, so the VM's startup script does the capture and serves the JSON on port 80:

```sh
deploy/gcp/capture-serving-config.sh prepare            # attach tools/serving_config.py as VM metadata (VM may be stopped)
gcloud compute instances start tb-gpu-sim --zone asia-east1-a   # only with the owner's OK: costs money
deploy/gcp/capture-serving-config.sh fetch              # -> eval/parity/serving_config_<date>_tb-gpu-sim.json
gcloud compute instances stop tb-gpu-sim --zone asia-east1-a
```

## The model gate offline

`python -m tools.parity_replay` (no model, no network) replays the recorded answers:

| | EN | JA | zh-TW |
| --- | --- | --- | --- |
| N-11 gate (lost of 79) | ≤ 5 | ≤ 4 | ≤ 2 (provisional) |
| deployed files on the card (6 Nov) | **4** | **3** | **missing** |
| same models, API 4-bit (proxy) | 1 | 2 | 1 |

N-12 (TREC CT, filter first, audit-adjusted): **3.6 %** projected (95 % 2.1–5.6 %), gate ≤ 5 %, pass on the point
estimate. Measured at API provider precision, not on the deployed files.

The replay scores all 1,015 annotated SIGIR criteria when NCBI's `trial_info.json` is not cached; on every recorded
run that gives the same lost-pair count as the 1,000 comparable criteria (`--check` verifies it against the committed
tables).

### What a GPU run must add

| recording | for | how |
| --- | --- | --- |
| `eval/trialgpt_compare/results/raw/trialbox__local__gemma-4-26b-a4b-nvfp4__zh-TW.jsonl.gz` and `trialbox__local__qwen3.5-9b-awq__zh-TW.jsonl.gz` | N-11 zh-TW on the deployed files | `python -m tools.trialgpt_compare run --pipelines trialbox --langs zh-TW --base-url http://<vm>/judge/v1 ...` then the same for the verifier (as on 6 Nov) |
| `eval/trec_ct/results/raw/local__gemma-4-26b-a4b-nvfp4.jsonl.gz`, `local__qwen3.5-9b-awq.jsonl.gz` | N-12 on the deployed files | `python -m tools.trec_ct_eval fetch` (NIST qrels, NCBI corpus) then `run` against the VM |
| a record from `capture-serving-config.sh` | FR-MOD-10 hashes | above |
| a run at 32 GB (`--gpu-memory-utilization` for 29.8 GiB total, or 4k context / 2 sequences) | the 32 GB fit (6 Nov used 35.0 GiB) | edit the caps in `gpu-sim-startup.sh`, rerun the SIGIR EN set |

### Cost (owner's OK first)

`tb-gpu-sim` is a `g4-standard-48` Spot VM (one RTX PRO 6000) in asia-east1-a at about US$2.74 an hour; its disk with
the model weights is kept, so boot to serving is about 10 minutes.

| run | time | about |
| --- | --- | --- |
| boot, capture with hashes, zh-TW SIGIR on both models (2,030 checks at 4.8 a second) | 0.5–0.75 h | US$2 |
| plus the 32 GB fit tries (two or three cap settings, SIGIR EN each) | +1 h | US$3 |
| plus TREC CT on the deployed files (40,192 checks) | +2.5 h | US$7 |
| all of it | about 4 h | US$11, plus a few cents of disk |

A real RTX 5090 (FR-MOD-10 asks for one) is not offered on GCP; the RTX PRO 6000 capped to 32 GB is the stand-in.
A rented 5090 elsewhere was not priced here.

## Profiles and the record install.sh asks for (D-124)

`python -m tools.serving_config measured <gpu> <record>` says whether a record measures a profile on its own card:

| profile | card name contains | judge and verifier | context at least |
| --- | --- | --- | --- |
| `rtxpro6000` | `RTX PRO 6000` | both resident (no `--enable-sleep-mode`) | 32,768 |
| `gb10` | `GB10` | both resident | 16,384 |
| `rtx5090` | `5090` | both with `--enable-sleep-mode` | 8,192 |

A record taken on a capped card never counts. `install.sh` looks for `deploy/site/serving_config.<gpu>.json`, then
the vendor's `deploy/measured/serving_config.<gpu>.json`.

### The RTX PRO 6000 run (TB-PLAN-04 step 1; owner's OK first, about US$6)

```sh
gcloud compute instances add-metadata tb-gpu-sim --zone asia-east1-a \
  --metadata-from-file startup-script=deploy/gcp/gpu-pro6000-run.sh,tb-serving-config=tools/serving_config.py
gcloud compute instances start tb-gpu-sim --zone asia-east1-a
# when the serial log says PRO6000-RUN-READY (about 15 min with hashing):
python -m tools.public_e2e --dir /tmp/tb-pro6000 --lang en \
  --judge-url http://<vm>/judge/v1 --verifier-url http://<vm>/verifier/v1      # 94/94
python -m tools.canary --judge-url http://<vm>/judge/v1 --verifier-url http://<vm>/verifier/v1 --out <file>
curl -fsS http://<vm>/record/serving_config.json -o deploy/measured/serving_config.rtxpro6000.json
python -m tools.serving_config measured rtxpro6000 deploy/measured/serving_config.rtxpro6000.json
gcloud compute instances stop tb-gpu-sim --zone asia-east1-a       # then check it shows TERMINATED
```

Then put the usual startup script back (`--metadata-from-file startup-script=deploy/gcp/gpu-sim-startup.sh`).
