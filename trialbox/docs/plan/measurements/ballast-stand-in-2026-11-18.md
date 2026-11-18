# The ballast stand-in, 2026-11-18 (card 10E-28)

**Reader:** the integrator and the owner, who run O-0 to O-9 (card 10E-29) on the owner's card; lane D, who owns the
installer and the 5090 profile this page refers to

Plan 10's row 10E-28 (review 19's card 19-2 and its section 4.1): "a script that holds a larger card at a 5090's free
memory and sets the utilisations; the record says 'by ballast' and is never a tier record". Done when: "on a 48 GB
card, free memory before the servers start is 32,607 MiB ± 512". The script is `tools/ballast.py`; its tests are
`tests/unit/test_ballast_stand_in.py`. **It has never run on a card.** Everything below that needs a GPU was shown on
stand-ins (an injected command runner and allocator, and a fake `nvidia-smi` and `docker` on PATH) and is to be
confirmed in O-1.

## 1. What it does

- `python3 -m tools.ballast plan` reads the card with `nvidia-smi`, checks it, and prints the card, the ballast it
  would hold, the two utilisations as `export` lines and the `--capped-to` text. It allocates nothing.
- `python3 -m tools.ballast hold [--env-file deploy/.env]` does the same checks, then starts one container,
  `tb-ballast`, from the vLLM image the 5090 profile serves with (`VLLM_IMAGE`, else the default in
  `deploy/docker-compose.rtx5090.yml`), with `--network none` and `--pull never`. Inside it, torch allocates until
  `torch.cuda.mem_get_info()` reports 32,607 MiB free, the figure vLLM itself reads, so the holder's own CUDA context
  is counted (the stand-in is never looser than the target). `nvidia-smi` then confirms the free memory is 32,607 MiB
  ± 512, else it releases at once (`off-target`). It prints what it holds and what is left, and waits.
- With `--env-file`, it writes `JUDGE_GPU_MEM_UTIL` and `VERIFIER_GPU_MEM_UTIL` into that file, each under a
  `# tb-ballast:` line naming the value it replaced, and puts the old values back on release.
- The utilisations: vLLM's utilisation is a share of the card's total, so the profile's 0.81 of 32,607 MiB (26,412
  MiB) becomes 26,412 ÷ total, rounded down to three places: **0.537 on a 49,140 MiB card** (review 19 section 4.1).
  The 0.81 is read from the profile's compose file, not repeated in the script.
- Ctrl-C, SIGTERM or SIGHUP release everything: `docker rm -f tb-ballast`, the env file put back, "released" printed.
  If the holder dies while held, it says `ballast-lost` and exits 1: records taken after that are not "by ballast".
  If the script itself is killed with SIGKILL, `python3 -m tools.ballast release --env-file deploy/.env` removes the
  container and puts the values back from the marked lines.
- Every record taken under it is captured with `--capped-to "RTX 5090 (32 GB), by ballast"`, which
  `tools/serving_config.py measured_for` refuses as a tier record, as it should.

It refuses with a named reason, before allocating anything: `production` (TB_ENV is PRODUCTION, from the process or
the env file; a rehearsal box is VALIDATION, a developer's DEV or TEST), `driver-tool-missing` or `driver-tool-failed`
(no working `nvidia-smi`), `no-such-card`, `card-too-small` (total below 32,607 MiB), `card-is-the-target` (a real 32
GB card: run without a ballast), `memory-already-held` (a compute process it was not told to expect with
`--expect-process`, or more than `--expect-used` MiB in use, default 1,024, or not more than the target free),
`docker-missing`, `image-not-local` (it never pulls), `ballast-already-running` (a `tb-ballast` container exists, or
the env file already holds marked values). After allocating: `allocation-failed`, `off-target`. Exit 2 on a refusal.

It is a measurement aid. The installer, compose files and services never start it; a test fails if any file under
`deploy/`, `services/`, `libs/`, `console/` or `orchestrator/` names it. It needs no network and uses only the Python
standard library on the host, so it runs on Arm as on x86.

## 2. The commands for each run

From `trialbox/`, on a rehearsal box (TB_ENV VALIDATION), public or synthetic data only. Terminal A holds the
ballast; terminal B runs the run. Do the `plan` step **before** `hold` (with the ballast up, `plan` refuses:
`memory-already-held`). The `export` lines matter where `deploy/install.sh` runs the settings wizard on a fresh box,
which may rewrite `deploy/.env`; shell variables win over `deploy/.env` in compose.

Setup for every run under ballast:

```
# terminal B: the numbers, and the two utilisations into this shell
python3 -m tools.ballast plan
eval "$(python3 -m tools.ballast plan | grep '^export ')"
# terminal A: hold until the run is done; Ctrl-C releases
python3 -m tools.ballast hold --env-file deploy/.env
```

| Run | Under ballast | Terminal B, once terminal A says "ready" (from review 19 section 4.1) |
| --- | --- | --- |
| O-0 | no | `nvidia-smi --query-gpu=name,memory.total,compute_cap,driver_version,ecc.mode.current --format=csv`; `nproc`; `free -g`; then `python3 -m tools.ballast plan` (which case applies; nothing held) |
| O-1 | yes | `TB_COMPOSE_OVERRIDE= deploy/install.sh <bundle> --gpu rtx5090 --rehearsal`; then `python3 tools/serving_config.py capture --container judge=trialbox-llm-service-1 --container verifier=trialbox-llm-verifier-1 --models-dir deploy/models --capped-to "RTX 5090 (32 GB), by ballast" --out <file>`; once at `JUDGE_MAX_SEQS=4`, once at 16 |
| O-2 | yes | `python3 -m tools.trialbox selftest`; then a tcga:500 and a jmed run at `JUDGE_MAX_SEQS` 4, 8, 16 (a local accuracy driver is card 10E-29's) |
| O-3 | yes | `TB_MODEL_SWAP=off`, and override the printed utilisations with the split, e.g. `export JUDGE_GPU_MEM_UTIL=0.42 VERIFIER_GPU_MEM_UTIL=0.20` (shares of the 49,140 MiB total: 30,467 MiB, inside the 32,607 held free); 8k, 2 to 4 sequences |
| O-4 | yes | `python -m tools.trialbox eval qualify --profile rtx5090 --gateway-url http://127.0.0.1:8010/v1 --model-dir judge=<weights> --model-dir verifier=<weights> --server-log <log> --operator <name>` |
| O-5 | yes | `python -m tools.medtxt_eval run --models <served names> --base-url <the box's model endpoint>`, then `score` |
| O-6 | yes, at 8k | the synthetic Japanese hospital's charts through SCREEN at 8k; the 32k half is the head-box profile, without ballast (as O-8) |
| O-7 | yes | the judge alone (`--scale llm-verifier=0`), `JUDGE_MAX_LEN=16384` then 32768, `JUDGE_MAX_SEQS=2`; compile the 104 SIGIR protocols |
| O-8 | **no** | no `hold`: the head-box profile on the whole card; leave `--capped-to` out |
| O-9 | no | the verifier on the host CPU; no card involved |

After each run under ballast: Ctrl-C in terminal A, and check it printed "released" and that
`grep tb-ballast deploy/.env` finds nothing.

## 3. What was shown on stand-ins

`tests/unit/test_ballast_stand_in.py`, 25 tests, no card:

- the arithmetic: 0.81 read from the 5090 compose file; 0.537 on 49,140 MiB, never a larger budget than the 5090's;
  the ballast is free minus 32,607;
- each refusal by name, and that none of them reaches the allocator (production from the process and from the env
  file; a stranger process; memory in use; a card below and a card at the target; no `nvidia-smi`; a missing index);
- a hold on a fake 48 GB card: it prints what it holds and what is left, the env file holds 0.537 while held and is
  byte for byte as before after release; an off-target hold and a failed allocation are released, with the env file
  put back;
- SIGTERM in process, and SIGTERM and SIGINT to the real CLI with a fake `nvidia-smi` and `docker` on PATH: the
  container is removed (`docker rm -f tb-ballast`), the fake card's memory is free again, the env file is put back,
  exit 0;
- a lost holder exits 1 with `ballast-lost`; an env file already marked is left alone;
- nothing in the box starts it.

## 4. What only a real card can show

- **The Done-when itself**: that on the 48 GB card the free memory before the servers start is 32,607 MiB ± 512. The
  script checks it and refuses otherwise; that check has only met a fake card.
- That torch in the vLLM image allocates the ballast in one block or a few, and that `mem_get_info` and `nvidia-smi`
  agree within the tolerance on that card and driver.
- That vLLM v0.32.0 starts with a utilisation computed on the card's total while another process holds memory
  (review 19 section 11 lists it as not verified), and that 0.537 then leaves the same budget a 5090 would.
- That `docker run --gpus device=0` works there (the NVIDIA container toolkit), and that SIGKILL of the script leaves
  only the container behind (`release` removes it).
- Everything a stand-in cannot be: a 5090's speed, its arithmetic, its heat and power (review 19 section 4.1).

## 5. The owner's machine: what is unknown

The integrator states the owner's machine is Ubuntu on Arm, an IGX Orin with an RTX A6000 (48 GB) and driver 535;
lane D states the x86 rc1 bundle cannot install there. Not checked by this card, and unknown:

- whether the pinned vLLM image has an arm64 build under the pinned digest; if not, `hold` refuses with
  `image-not-local` or `allocation-failed`, and the runs need another holder image;
- whether that image's CUDA runs on driver 535 (a CUDA 13 build needs a newer driver); if not, the holder cannot
  start, and neither can the model servers;
- whether `nvidia-smi` on the IGX lists the A6000 alone, at which index, and what it reports as used with the display
  (`--gpu`, `--expect-process`, `--expect-used` exist for this);
- whether the NVIDIA container toolkit is installed there;
- that the A6000 is Ampere, not the Ada card review 19 assumed: the judge's 4-bit path and speed differ further from
  a 5090's;
- O-1's install path, which lane D says cannot run there with the x86 bundle; O-1 then needs another way to start the
  pair under the ballast, which is card 10E-29's question, not this one's.
