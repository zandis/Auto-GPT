# The 48 GB measuring run on the GPU VM, under the ballast (H-47, 2026-11-19)

**Reader:** the integrator, who posts the running total and launches; lane J, whose draft 48 GB class (#1100) this
run measures; the owner, who approved it (2026-11-19 14:00 Taipei: "about US$7 to 11 at spot")

Lane H launched nothing, spent nothing and made no cloud call for this page. Every figure says where it comes from;
a figure that was not measured says so. Read on master `cebd9b8e` (train 93). The form is the W-2 sheet's
(`install-rehearsal-sheet-2026-11-18.md`): free checks first, numbered commands, an estimate per stage, a stop line,
a cap.

## 1. What it answers, and what it cannot

One rented RTX PRO 6000 (97,887 MiB) is held by the ballast (`tools/ballast.py`, plan 10's 10E-28) at the free
memory of a 48 GB card (49,140 MiB, the owner's RTX A6000 as `nvidia-smi` showed it:
`deploy/dgpu48-profile.yaml` `card.memory_total_mib`). On it, lane J's draft class runs exactly as its measuring
run starts it (`tools/dgpu48.py measure`, behind its switch `TB_UNMEASURED_DGPU48_MEASURING_RUN=1`), through a
lane H wrapper made for this card (`tools/ballast48.py`, section 4). It records:

| What | Where it comes from | Answers |
| --- | --- | --- |
| Resident memory per server: card memory at peak, each server's host memory at peak | `measure.<option>.json` `card_peak_mib`, `host_peak_mib` (lane J's sampler: card every 2 s, host every 10 s); the serving record's `memory_used_mib` | 10E-29's O-8 (the head-box fit), 10E-31's utils; review 19 section 1.3's figures checked at 48 GB |
| Free card memory at peak | `measure.<option>.json` `ballast.free_at_peak_mib` (49,140 minus the peak as a 48 GB card sees it) | review 19's A1 (at least 1,024 MiB free at peak) |
| Sequences and context that fit | the option that starts (the ladder of section 3, step 6 and step 9) and the engine's own cache lines, `engine_log.<role>.kv_cache_tokens`: full-context sequences that fit = cache tokens / max context | the 48 GB class's option, and whether 16 sequences at 32k are memory, not only a setting |
| Seconds per judged call | the 54-case pair canary, one call at a time (`services/orchestrator/selftest.py` `check_model`, sequential): `canary.<option>.json` judge `seconds` / `cases` | the head box's judge speed at one in flight |
| A small screen's wall time | the hospital part of `tools/complete_run.py` (the e2e path: data in, criteria, approval, SCREEN, lists) on a synthetic hospital of 1,000 patients, Japanese, study GZQO, 16 calls in flight, against the class's two servers; `parts/hospital-ja.json` (`wall_seconds`, model calls, calls a second) and `screen-during.json` (wall time, card peak during the screen) | the head box screening a small synthetic site, beside the measured 5,000-patient rows of `tools/complete_run.py` `HOSPITAL_MEASURED` |

**Optional (stage O, H-49):** the verifier with the server flag `disable_any_whitespace`: whether it starts, its
seconds per call, and its verdict changes on the 54 canary cases. The replay of the stored tcga calls (the flagged
calls by `tools.public_accuracy.waste`) is **not included**, with the reason in section 3. A measurement, not a
serving change.

It **cannot** prove:

- **A tier record.** Every record says `capped_to: "48 GB class (49,140 MiB), by ballast"`;
  `tools/serving_config.py measured_for` refuses it, as it must (D-1320 rule 4: a stand-in is never a tier record; D-1322: a reader
  takes a tier value only when it is measured). The class stays `status: unmeasured`.
- **The owner's machine.** That is an IGX Orin developer kit (Arm, Ubuntu 22.04, driver 535) with an RTX A6000:
  Ampere, where the judge's 4-bit format runs a weight-only path whose memory, speed and answers nobody has measured
  (`deploy/dgpu48-profile.yaml` `options[].unknown`; runbook 29 "What this page does not verify"). This card is
  Blackwell, where the format is native; the engine is the pinned one, forced (`--engine pinned`), not a probe's
  verdict. The memory figures here are the class's on the measured architecture; the A6000's own run (runbook 29)
  is still needed.
- **A 53 GB host.** The VM has far more host memory (its size is not in the repository's notes). Option `pair-32k-host53` caps the servers at 12 + 10 GiB of host memory with
  Docker's limits, which answers whether they live within those caps, not how a 53 GB machine behaves overall.
- **Speed on the owner's card.** Seconds per call and the screen's wall time are this card's under the class's
  layout; on Ampere they will be slower by an unmeasured factor.
- A display on the card, the vendor's driver, Arm, Ubuntu 22.04, the real embedder (runbook 29 step 4 is not here).

## 2. Free checks before any cost

From this checkout, on any machine (nothing created, nothing paid; run on master here except where marked):

```sh
python3 tools/dgpu48.py arith                         # free: each option's arithmetic at 49,140 MiB (table below)
python3 -m tools.fetch_weights --profile rtxpro6000 --dry-run    # free: the three hub addresses, about 27.9 GB
.venv/bin/python -m tools.complete_run --estimate --only hospital-ja --patients 1000 --llm-concurrency 16   # free
.venv/bin/python -m pytest tests/unit/test_ballast48_h47.py tests/unit/test_ballast_stand_in.py tests/unit/test_dgpu48_draft.py -q
```

`tools/dgpu48.py arith` (run here): `pair-32k` uses 45,128 of 49,140 MiB, 4,012 spare, judge room 5,564 MiB;
`pair-16k` 42,179, 6,961 spare; `judge-alone` 42,482, 6,658 spare. The estimate (run here): the 1,000-patient `ja`
hospital part is 0.13 h of card time at this card's measured rates at 16 in flight. And on the integrator's machine
(free, read only), as the W-2 sheet does:

```sh
gcloud compute images describe-from-family ubuntu-2404-lts-amd64 --project ubuntu-os-cloud --format='value(name)'
gcloud compute machine-types describe g4-standard-48 --zone asia-east1-a --format='value(name,guestCpus)'
```

## 3. The exact run

**H-53 (2026-11-19):** the integrator's container has no outbound SSH (the IAP tunnel is refused too) and the
region's disk quota refuses this section's 250 GB disk. The run as it is launched is section 9: the same steps,
unattended, through `deploy/gcp/measure48-run.sh`. This section stays the reference for a person on SSH.

**The machine.** A **new** VM, `tb-h47-48gb`, created for this run and deleted after it. Never `tb-gpu-sim`,
`tb-demo-vm`, `tb-preview-vm` or `tb-steps-vm`; no script in `deploy/gcp/` is used to make it (they start the kept
VMs). Shape and image as W-2: `g4-standard-48` with one RTX PRO 6000, zone `asia-east1-a`, SPOT, plain Ubuntu 24.04.
The disk is 250 GB, not W-2's 500: weights 27.9 GB, the engine image about 25 GB unpacked, the box's images, the
screen's tools. The user is the launcher's own OS Login user with sudo, never root. `<sha>` is master's commit
once this card has merged. Work inside `tmux new -s h47` on the VM: a dropped SSH must not end a measuring run.
Write each stage's start and end in UTC to `~/h47/clock.txt` (`date -u +%FT%TZ >> ~/h47/clock.txt`).

Each command exists in the repository today (cited) or is **NEW** (this card's `tools/ballast48.py`).

**1. Launcher: create the VM** (from the integrator's machine; the form of the W-2 sheet's step 1):

```sh
gcloud compute instances create tb-h47-48gb --zone asia-east1-a --machine-type g4-standard-48 \
  --provisioning-model SPOT --instance-termination-action STOP --max-run-duration 4h \
  --image-family ubuntu-2404-lts-amd64 --image-project ubuntu-os-cloud \
  --boot-disk-size 250GB --boot-disk-type hyperdisk-balanced \
  --shielded-vtpm --shielded-integrity-monitoring --no-shielded-secure-boot \
  --labels trialbox=h47-48gb --metadata enable-oslogin=TRUE
gcloud compute ssh tb-h47-48gb --zone asia-east1-a
```

**2. The host: driver, Docker, the container toolkit** (the driver as H-38's sheet,
`install-rehearsal-sheet-2026-11-18.md` line 440, with Ubuntu's utilities package for `nvidia-smi`; Docker and the
toolkit as `deploy/gcp/gpu-sim-startup.sh` lines 12 to 20, with `sudo`):

```sh
tmux new -s h47
mkdir -p ~/h47 ~/h47-raw && chmod 700 ~/h47-raw && date -u +%FT%TZ >> ~/h47/clock.txt
sudo apt-get update && sudo apt-get install -y git make curl python3-yaml python3-venv
sudo ubuntu-drivers install --gpgpu nvidia:580-server && sudo apt-get install -y nvidia-utils-580-server
sudo reboot
```

SSH again, `tmux new -s h47`, then:

```sh
nvidia-smi --query-gpu=name,memory.total,compute_cap,driver_version,ecc.mode.current --format=csv > ~/h47/o0-card.csv
nproc >> ~/h47/o0-card.csv && free -g >> ~/h47/o0-card.csv      # O-0 (review 19 section 4.3)
curl -fsSL https://get.docker.com | sudo sh
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker
sudo usermod -aG docker "$USER"
```

Exit, SSH again, `tmux new -s h47`, then `docker run --rm --gpus all ubuntu:24.04 nvidia-smi` (the card's table).

**3. The checkout and the weights** (`tools/fetch_weights.py`, W-1; runbook 27 step 10; the same pinned builds every
profile serves, `tools/dgpu48.py` `PIN_BUILD`):

```sh
git clone https://github.com/zandis/Auto-GPT.git ~/Auto-GPT && cd ~/Auto-GPT/trialbox && git checkout <sha>
python3 -m tools.fetch_weights --profile rtxpro6000
```

The screen's tools (step 7) may be installed now in a second tmux window (`Ctrl-b c`), while the weights download.

**4. The box's images and `deploy/.env`, once, on the stub** (`tools/dgpu48.py measure` refuses without
`deploy/.env` and its canary runs in `trialbox-py:1.0.0`: runbook 29 step 6 starts from a stub box; the database
image first, because #1130 is not on master and the start does not build it, finding W2-db-image of the W-2 sheet):

```sh
docker build -f deploy/docker/db.Dockerfile -t trialbox-postgres:16-1 deploy/docker
TB_POC_SKIP_INGEST=1 deploy/poc.sh > ~/h47-raw/poc-up.txt 2>&1
deploy/poc.sh status
deploy/poc.sh down
```

`~/h47-raw/poc-up.txt` holds the administrator's password: it never leaves the VM.

**5. The engine image, then the ballast on** (the ballast never pulls, `tools/ballast.py` `image-not-local`; its image
is the pinned engine, `tests/unit/test_ballast48_h47.py` holds that):

```sh
docker pull "$(python3 -c 'import tools.engine_probe as p; print(p.pinned_ref())')"
setsid python3 -m tools.ballast hold --target-mib 49140 > ~/h47/ballast.log 2>&1 < /dev/null &
until grep -q -e '^ready' -e '^refused' ~/h47/ballast.log; do sleep 5; done; cat ~/h47/ballast.log
python3 tools/ballast48.py plan | tee ~/h47/plan.txt                                   # NEW
```

`hold` must print `ready`; `plan` must print the card at 49,140 MiB free (within 512) and, for `pair-32k`,
`JUDGE_GPU_MEM_UTIL=0.286 (class 0.57)` and `VERIFIER_GPU_MEM_UTIL=0.135 (class 0.27)`: the class's MiB of this
card's total. The ballast's own log also prints the 5090 profile's two `export` lines and "RTX 5090 (32 GB), by
ballast": they are its defaults and are not used here (no `--env-file`); the records' text comes from
`tools/ballast48.py` (question H-1 below).

**6. The class's first option, kept running for the screen** (lane J's measuring run, unchanged, through the
wrapper):

```sh
TB_UNMEASURED_DGPU48_MEASURING_RUN=1 python3 tools/ballast48.py measure --option pair-32k --dry-run    # NEW; starts nothing
TB_UNMEASURED_DGPU48_MEASURING_RUN=1 python3 tools/ballast48.py measure --option pair-32k --keep       # NEW
```

It writes `~/tb-dgpu48-pair-32k/`: `measure.pair-32k.json`, `serving_config.dgpu48.pair-32k.json`,
`canary.pair-32k.json`, and `down.json` (the command that stops the two servers; no key in it). The last line is the
`outcome`, starting "BY BALLAST". If it did not start (`OUT OF CARD MEMORY`, `FAILED TO LOAD`, `DID NOT START IN
TIME`), run the ladder now, in lane J's order (runbook 29 step 7): `--option pair-16k --keep`, then
`--option judge-alone --keep`, **stopping at the first that starts**; the screen (step 8) runs on that one.

**7. The screen's tools** (as `deploy/gcp/complete-run-vm.sh` lines 452 to 490, the paid complete run's own setup,
with `sudo` and in the user's home):

```sh
cd ~/Auto-GPT/trialbox
sudo apt-get install -y postgresql tesseract-ocr tesseract-ocr-jpn tesseract-ocr-chi-tra tesseract-ocr-eng xz-utils
python3 -m venv ~/uvenv && ~/uvenv/bin/pip install -q uv
~/uvenv/bin/uv venv --python 3.12 .venv && ~/uvenv/bin/uv pip install --python .venv/bin/python -e ".[dev]"
curl -fsSL https://nodejs.org/dist/v22.23.4/node-v22.23.4-linux-x64.tar.xz | sudo tar -xJ -C /opt
sudo ln -sf /opt/node-v22.23.4-linux-x64/bin/node /opt/node-v22.23.4-linux-x64/bin/npm /opt/node-v22.23.4-linux-x64/bin/npx /usr/local/bin/
sudo mkdir -p /opt/node-tools && sudo chown "$USER" /opt/node-tools
(cd /opt/node-tools && npm i -s playwright@1.63.0 && npx playwright install --with-deps chromium)
.venv/bin/python tools/fetch_fonts.py
.venv/bin/python -m tools.fetch_run_data --cache ~/h47-cache --only hospital-ja
```

**8. The small screen against the class's two servers** (`tools/complete_run.py` `--model pair`, as its docstring's
second line; the servers are reached on Docker's local bridge, which only this VM can reach; the key read from the
servers' own file into the environment, never printed, as `tools/dgpu48.py` `_vllm_key` reads it):

```sh
cd ~/Auto-GPT/trialbox
docker network connect bridge trialbox-llm-service-1 && docker network connect bridge trialbox-llm-verifier-1
J=$(docker inspect -f '{{.NetworkSettings.Networks.bridge.IPAddress}}' trialbox-llm-service-1)
V=$(docker inspect -f '{{.NetworkSettings.Networks.bridge.IPAddress}}' trialbox-llm-verifier-1)
TB_GPU_KEY="$(sed -n 's/^VLLM_API_KEY=//p' deploy/secrets/model/vllm.env 2>/dev/null | tr -d "\"'")"
export TB_GPU_KEY="${TB_GPU_KEY:-measuring-run-no-key}"
python3 tools/ballast48.py during --out ~/h47/screen-during.json -- \
  .venv/bin/python -m tools.complete_run --dir ~/h47-screen --model pair --patients 1000 --langs ja \
  --only prepare hospital-ja --llm-concurrency 16 --judge-url "http://$J:8000/v1" --verifier-url "http://$V:8000/v1"   # NEW wrapper
```

Then, **unless the optional stage O below is taken now** (it needs the kept servers):

```sh
docker network disconnect bridge trialbox-llm-service-1; docker network disconnect bridge trialbox-llm-verifier-1
python3 tools/ballast48.py down --out-dir ~/tb-dgpu48-pair-32k                       # NEW (the option step 6 kept)
```

The screen's records: `~/h47-screen/parts/prepare.json`, `~/h47-screen/parts/hospital-ja.json` (the part's
`wall_seconds`, its calls and calls a second, its checks) and `~/h47/screen-during.json` (the wrapper: wall time,
exit code, card peak, free at peak, whether the ballast still held). A part check that fails does not void the wall
time; write it on the form.

**O. OPTIONAL: the verifier's whitespace flag (H-49), on the kept servers.** The integrator takes it or leaves it;
it has its own line in the estimate. **A measurement, not a serving change:** no compose file under `deploy/` is
edited, the flag lives only in a one-off file in the run's folder, and every figure is by ballast and never a tier
record. Background: H-49 (branch `claude/lane-h-49-verifier-constrained-decoding`,
`docs/plan/measurements/verifier-constrained-decoding-2026-11-19.md`) found that the verifier's wasted calls of H-40
(prompt `judge@5`, tcga, launches P2b and P3) pad whitespace between JSON tokens after a string closes early, and that
on the pinned image the one control is a verifier start-up flag,
`--structured-outputs-config={"backend":"xgrammar","disable_any_whitespace":true}` (read from the server's source at
the pinned tag, never run).

**Not included: the replay of the stored tcga verifier calls**, and so the flagged-call count by
`python -m tools.public_accuracy.waste` with and without the flag. The reason: no command in the repository sends
stored calls again to a model server, and a new one is more than a small addition here. The guard
`tests/unit/test_no_direct_model_calls.py` (ENG-04, LLM-1) refuses a model API call from any file outside its
allow-list, and this card may add no allow-list entry. The two client paths it allows do not fit: `tb_llm`'s
`GatewayClient` refuses an answer without the gateway's `tb.alias` (`libs/tb_llm/client.py` `_check_alias`), and
`tb_common.llm.LlmClient` renders the current prompt from variables and asks again with a repair message, so it
cannot send the stored calls as they were sent. What would provide it: a replay tool with a reviewed allow-list
entry (the lead's call), or a probe in `tools/g_probes.py`, whose entry already covers timing the server with
decoding settings on and off but names synthetic excerpts only (its owner's call).

**What is included instead (small, and composed from existing commands plus two NEW subcommands):** the verifier
alone recreated with the flag at the same settings, and the existing 54-case pair canary run against it, compared
with step 6's canary (the same servers, without the flag). It answers whether the pinned image starts the verifier
with the flag; the verifier's seconds per call with and without it (54 calls, one at a time); and how many of the
verifier's 54 verdicts change. On the VM, with `TB_GPU_KEY` exported as in step 8:

```sh
cd ~/Auto-GPT/trialbox
python3 tools/ballast48.py verifier-flag --out-dir ~/tb-dgpu48-pair-32k                                       # NEW: the verifier alone, with the flag
docker run --rm --network trialbox-model-backend -e TB_GPU_KEY -v "$PWD/tools/canary.py:/app/tools/canary.py:ro" \
  trialbox-py:1.0.0 python -m tools.canary --judge-url http://llm-service-vllm:8000/v1 \
  --verifier-url http://llm-verifier-vllm:8000/v1 > ~/h47/canary-verifier-flag.json                            # the canary as tools/dgpu48.py runs it
python3 tools/ballast48.py canary-diff ~/tb-dgpu48-pair-32k/canary.pair-32k.json ~/h47/canary-verifier-flag.json \
  --json ~/h47/canary-verifier-flag-diff.json                                                                  # NEW
docker network disconnect bridge trialbox-llm-service-1; docker network disconnect bridge trialbox-llm-verifier-1
python3 tools/ballast48.py down --out-dir ~/tb-dgpu48-pair-32k
```

It records (`canary-verifier-flag-diff.json`): for each of the two reports, the verifier's cases, answered, correct,
flips, seconds and seconds per call; `verdicts_differ` and the case ids; `exact` (true while each run left at most
10 cases wrong and answered all 54, because a canary report lists at most 10 wrong cases). The canary's own
`ok`, `pair` and `problems` are in `canary-verifier-flag.json`. If the verifier does not start with the flag
(`verifier-flag` exits 1), write that down (the flag as written is refused by this release: a result in itself),
skip the canary, and go on to `down`. It cannot show: the flagged calls of H-40 (the stored tcga inputs are not
sent), the gateway's own path (its retry with four times the room), the judge with the flag, or a serving change's
effect on the recorded-answer gates. The canary's verifier output is not scrubbed by `tools/dgpu48.py` here; it holds
case ids and verdicts of the stored synthetic cases, no key.

**9. One more option, if the clock allows** (the stop line, section 5): if `pair-32k` started, the 53 GiB question,
`TB_UNMEASURED_DGPU48_MEASURING_RUN=1 python3 tools/ballast48.py measure --option pair-32k-host53` (NEW wrapper; no
`--keep`); if the ladder ran in step 6, nothing more. Each writes `~/tb-dgpu48-<option>/`.

**10. The ballast off, the records back, the VM deleted:**

```sh
pkill -TERM -f 'tools.ballast hold'; sleep 35; cat ~/h47/ballast.log     # must end "released"
python3 -m tools.ballast release                                        # only if it did not
cd ~ && tar czf h47-records.tgz h47 tb-dgpu48-*/measure.*.json tb-dgpu48-*/serving_config.dgpu48.*.json tb-dgpu48-*/canary.*.json h47-screen/parts/*.json
```

From the integrator's machine:

```sh
mkdir -p h47 && gcloud compute scp --zone asia-east1-a tb-h47-48gb:~/h47-records.tgz ./h47/
gcloud compute instances delete tb-h47-48gb --zone asia-east1-a --quiet
```

**Never brought back:** `~/h47-raw` (the stub start's output, with the administrator's password), `deploy/.env`,
`verifier-flag.yml` (no secret, not needed),
`deploy/secrets/`, `down.json`, the containers' logs, the screen's work folders and screenshots. The records hold no
key: `tools/dgpu48.py` scrubs the record and the canary (`sanitize`, `scrub_json_text`: host name and device ID
withheld); the wrapper writes the command line without the environment. Look at them before posting anyway.

## 4. The tool change: `tools/ballast48.py` (NEW, lane H)

`tools/dgpu48.py measure` cannot run under the ballast as it is: it refuses a card whose total is outside 44,000 to
52,000 MiB (`tools/dgpu48.py:292-294`), and the ballast leaves the reported total at 97,887 MiB; and the class's
utilisations are shares of the total (`--gpu-memory-utilization`), so 0.57 of 97,887 MiB would ask vLLM for more
than the 49,140 MiB the ballast leaves free. The wrapper runs lane J's `measure` unchanged with a runner that

- answers `nvidia-smi` as a 49,140 MiB card would (total = the target; used = the card's minus what the ballast holds),
  so the class's own range check, arithmetic and memory sampler apply as written;
- scales `JUDGE_GPU_MEM_UTIL` and `VERIFIER_GPU_MEM_UTIL` on the start to the same MiB of the real total
  (`tools/ballast.py` `util_on`, rounded down: 0.57 to 0.286, 0.27 to 0.135);
- adds `--capped-to "48 GB class (49,140 MiB), by ballast"` to the serving record's capture; the record keeps the real
  card's name and total;
- writes a `ballast` block into `measure.<option>.json` (card, target, held, scaled utils, `tier_record: false`,
  whether the ballast still held at the end, free at peak) and prefixes the `outcome` with "BY BALLAST" (or "BALLAST
  LOST").

For the optional stage O, `verifier-flag` recreates only the verifier of a `--keep` run at the same settings (from
`down.json`), with a one-off compose file in the run's folder (`verifier-flag.yml`: the overlay's own verifier command
restated, since compose replaces a command list, plus H-49's flag); `--off` recreates it without. `canary-diff`
compares one role's answers and seconds per call in two canary reports. Tests: `tests/unit/test_verifier_flag_h47.py`,
on stand-ins.

It refuses before lane J's `measure` is called when no `tb-ballast` container runs or the card's free memory is not
49,140 within 512 MiB. `during` runs a command and records its wall time and the card's peak; `down` replays the stop
command a `--keep` run left. Lane J's class, overlay and switch are unchanged; the switch is still what `measure`
checks. Tests: `tests/unit/test_ballast48_h47.py`, on stand-ins (no card, no Docker).

## 5. The estimate

US$2.74 a VM hour, SPOT (`tools/complete_run.py:1635`, `PRICE_PER_HOUR`); US$8.22 on demand
(`ON_DEMAND_PRICE_PER_HOUR`, 3x). **No stage of this run has been timed on this VM as a whole**; the parts that were
measured elsewhere say where.

| Stage | Low | Estimate | High | Source |
| --- | --- | --- | --- | --- |
| 1. VM created, booted, SSH | 0.05 h | 0.10 h | 0.25 h | `BOOT_HOURS` 0.25 h as the high (`tools/complete_run.py:1683`); a plain boot not measured |
| 2. Driver (one reboot), Docker, toolkit | 0.20 h | 0.35 h | 0.75 h | **not measured**; W-2's stage 2 range (0.25 / 0.40 / 0.75 h), with exact commands instead of outside pages |
| 3. Checkout, weights 27.9 GB | 0.08 h | 0.20 h | 0.47 h | W-2.5: clone 0.01 / 0.03 / 0.10 h; the hub at 25 to 150 MB/s, not measured into a Google VM |
| 4. Database image, stub start once, down | 0.11 h | 0.43 h | 1.05 h | `make images` 160 to 250 s with Maven (GPU VM hand-over), the builder path not measured; pulls 0.03 / 0.08 / 0.20 h (W-2); the database image "5 to 15 minutes" (runbook 28 step 6, Arm) |
| 5. Engine image (9.2 GB compressed), ballast on | 0.04 h | 0.10 h | 0.25 h | the pull as W-2's step 11 pulls; the ballast's allocation not measured |
| 6. `pair-32k` with `--keep` | 0.13 h | 0.25 h | 0.80 h | weights hashed twice (check and record) at 140 to 440 MB/s, 63 to 200 s each; the servers ready in 199 s on this card (`gpu-run-2026-11-08/fit.json`), at most the overlay's 35 min; the canary 124 to 300 s (`CANARY_SECONDS`) |
| 7. The screen's tools | 0.15 h | 0.25 h | 0.40 h | `tools/complete_run.py --estimate`'s "VM setup: packages, venv, browser, fonts", 0.25 h; 0 when done during stage 3 |
| 8. The screen, 1,000 patients, ja, 16 in flight | 0.12 h | 0.20 h | 0.50 h | `--estimate` (run here): 0.13 h from the measured 5,000-patient rows (run `20261113T044219Z-2b9eec74`) scaled; the synthetic hospital's generation not measured |
| O. OPTIONAL: the verifier flag (H-49) | 0.06 h | 0.12 h | 0.25 h | the verifier recreated (part of the pair's 199 s, `fit.json`; at most the overlay's 35 min if it hangs, but a refused flag ends at once) and one canary, 124 to 300 s (`CANARY_SECONDS`); not measured with the flag |
| 9. One more option | 0.13 h | 0.25 h | 0.80 h | as stage 6 (the image is there) |
| 10. Records back, VM deleted | 0.03 h | 0.05 h | 0.10 h | not measured |
| **In all, without O** | **1.04 h, US$2.85** | **2.18 h, US$5.97** | **5.37 h, US$14.71** | |
| **In all, with O** | **1.10 h, US$3.01** | **2.30 h, US$6.30** | **5.62 h, US$15.40** | |

- **The estimate to post: US$6.0 (2.2 h) without the optional stage; US$6.3 (2.3 h) with it.**
- **The stop line, 50 % over the estimate: US$9.0 (3.3 h) without O; US$9.5 (3.5 h) with O.** O runs only when the
  clock at its start leaves its high (0.25 h) before the stop line; else skip it. At the stop line: Ctrl-C whatever runs (the measuring
  run stops its servers and writes what it measured), then step 10. Stages 5 and 6 (the memory records) come before
  the screen, so a stop at the line still brings them back.
- **The cap: `--max-run-duration 4h`**, US$10.96 SPOT; the VM stops (not deleted) at the cap. Copying the records
  from a stopped VM means starting it again for a few minutes (about 0.1 h, US$0.27, outside the cap); then delete
  it. The high (5.37 h) is above the cap: it needs every stage at its slowest and the ladder's failures.
- **The worst case:** the cap at spot, **US$10.96**, plus the disk (250 GB `hyperdisk-balanced` for 4 h at US$0.093
  a GiB-month, the hand-over's Taiwan list price: about US$0.13) = **about US$11.09**. On demand the same cap is 4 h
  at US$8.22, **US$32.88**. A spot pre-emption stops the VM (termination action STOP): restart it, or delete it and
  take what `~/tb-dgpu48-*` holds.
- **Not in these figures:** the external address; people's time; network out (the records are a few hundred kB).

## 6. The form

| Stage | Start (UTC) | End (UTC) | Seen, or what differed |
| --- | --- | --- | --- |
| 1 VM | | | |
| 2 host (driver version printed) | | | |
| 3 checkout (commit), weights | | | |
| 4 stub once | | | |
| 5 engine, ballast (`ready` line, `plan` output) | | | |
| 6 option(s) and each `outcome` | | | |
| 7 screen tools | | | |
| 8 screen (`wall_seconds`, failed checks) | | | |
| O optional: verifier flag (taken or not; started with the flag or not) | | | |
| 9 one more option, `outcome` | | | |
| 10 records, ballast `released`, delete | | | |

## 7. Questions

- **H-1 (lane H, this card's follow-up):** `tools/ballast.py hold` always prints the 5090 profile's utils and
  "RTX 5090 (32 GB), by ballast", whatever `--target-mib`; a later card can give it a `--capped-to` and take the utils
  from the class it stands in for. Not needed for this run (the wrapper stamps the records).
- **J-1 (lane J):** should `tools/dgpu48.py measure` take a ballast itself (a `--ballast-target` that reads the card
  as the target and scales the utils), so the wrapper can go? Until then the wrapper is the only way to run the class
  on a larger card, and it changes nothing of the class.
- **J-2 (lane J):** the measuring run forces no engine probe here (`--engine pinned`, the pinned engine measured on
  this card). Is that the form you want for a Blackwell card, or should the probe run first (up to 1 h)?
- **J-3 (lane J):** is "full-context sequences that fit = `kv_cache_tokens` / max context" the reading you want for
  "sequences that fit", or should a later option raise `*_MAX_SEQS` past 16 to try it?
- **I-2 (integrator):** take the optional stage O or not.
- **L-1 (the lead):** the replay of the stored tcga verifier calls needs a tool with an entry in
  `tests/unit/test_no_direct_model_calls.py`'s allow-list (or a probe in `tools/g_probes.py` by its owner, whose entry
  names synthetic excerpts only). Approve an entry for a lane H card, or leave the flagged-call count to the next
  launch after a serving change (H-49's "what the next launch must show")?
- **I-1 (integrator):** the VM name `tb-h47-48gb`, the zone and the 250 GB disk; who runs it; `<sha>` once merged.

## 8. Not shown

- Nothing on this page ran on a GPU, a VM or the hub; `tools/ballast48.py` is tested on stand-ins only.
- That vLLM accepts the scaled utilisations with the ballast's memory on the card (the 5090 stand-in's premise,
  `ballast-stand-in-2026-11-18.md`, also unrun); that `ubuntu-drivers install --gpgpu nvidia:580-server` gives a
  working driver for this card on this image; that the stub start reaches `deploy/.env` and `trialbox-py:1.0.0` with
  the database image built first; that the hospital part runs from the user's home with the servers on the bridge.

## 9. Unattended, through the driver (H-53)

Lane H made no cloud call and spent nothing for this section; nothing of it has run on a VM. Read on master
`73835e62`. **Why a driver of its own, not `box-run.sh --steps measure48`:** `deploy/gcp/box-run.sh` drives one kept
VM (`tb-gpu-sim`, whose 400 GB disk holds the driver and the weights) that it starts and puts back; it never makes or
deletes a VM, and this run may not use `tb-gpu-sim`. Its VM script is the box's install harness (bundles, the wizard,
the owner's sessions). This run needs a new VM from a plain image with a 100 GB disk, so it has a script of its own
with the same conventions: `gcloud-auth.sh`'s `gc`, `TB_BUCKET`, the records up after every step, a cap, power-off
on every way out, `--estimate`, `--preflight`, `--collect`, `--resume`.

| File | What |
| --- | --- |
| `deploy/gcp/measure48-run.sh` | the driver: `--estimate`, `--preflight`, the launch, `--collect`, `--resume`, `--stop`, `--delete` |
| `deploy/gcp/measure48-vm.sh` | the VM's start-up script: steps 2 to 10 of section 3, unattended |
| `deploy/gcp/measure48_vm.py` | its helper (standard library): the estimate, the gate, the ladder, the disk guard, the upload allow-list, the summary, the quota |
| `tests/unit/test_measure48_vm_h53.py`, `tests/unit/test_measure48_run_h53.py` | the VM script rehearsed on stand-ins; the decisions and the driver against a stand-in gcloud |

### 9.1 The commands (the integrator's machine)

```sh
export CLOUDSDK_CONFIG=<a private folder> TB_SA_KEY_FILE=<the deployer's key file> TB_BUCKET=gs://trialbox-demo-runs
deploy/gcp/measure48-run.sh --estimate                          # free, no gcloud call
deploy/gcp/measure48-run.sh --preflight --commit <sha>          # read-only gcloud calls; nothing uploaded or made
deploy/gcp/measure48-run.sh --commit <sha>                      # the launch: uploads the archive, makes the VM, returns
deploy/gcp/measure48-run.sh --collect <run id>                  # now and then; the one that finds the run ended deletes the VM
```

`<sha>` is master's full commit once this card has merged; the run id is `m48-<UTC time>-<commit12>`, printed by the
launch. `--no-o` leaves stage O out (question I-2; the stop line is then 192 minutes). The VM is `tb-h47-48gb` in
`asia-east1-a` (the driver's defaults, as `box-run.sh`'s zone; `[VM] [ZONE]` after the options change them), made as
step 1 made it: `g4-standard-48`, SPOT, `--instance-termination-action STOP`, `--max-run-duration 4h`,
`ubuntu-2404-lts-amd64`, **100 GB** `hyperdisk-balanced`, vTPM, `--scopes storage-rw`, label `trialbox=h53-48gb`,
`block-project-ssh-keys=TRUE`. `--preflight` checks, before any cost: the commit, its archive (`git archive` with
`TB_HEAD.json`, as `complete-run.sh` uploads it), the weights' pinned list (`tools/fetch_weights.py --profile
rtxpro6000 --dry-run`, no network), no VM of that name, the bucket readable, and the quota with read-only calls: one
Spot RTX PRO 6000 and 48 CPUs (`tools/complete_run.py quota_problems`, the complete run's own reading) and **100 GB
free in the region's `HDB_TOTAL_GB`** (exit 4 otherwise). The weights are not in the bucket: the only copy the
project has is on `tb-gpu-sim`'s disk, which this run may not use, so the VM fetches them from the public hub.

### 9.2 What the VM does, and what it decides alone

At every boot it reads its metadata and goes on from its last finished step (`state/`); every step writes a line of
`steps.json` (step, started, ended, exit code, note) and its log, and every decision a line of `decisions.json` (what,
choice, why, the clock).

| Step | Section 3's step | What, and the rule |
| --- | --- | --- |
| `s01-host` | 2 | apt (git, make, curl, python3-yaml, python3-venv), `ubuntu-drivers install --gpgpu nvidia:580-server`, `nvidia-utils-580-server`, **one reboot** (decision `reboot`), then Docker and the toolkit with `gpu-sim-startup.sh`'s own lines (a test holds them equal) |
| `s02-card` | 2 | `o0-card.csv` (the card, CPUs, memory); the card inside a container |
| `s03-source` | 3 | the commit's archive from the bucket: its sha256 and its `TB_HEAD.json` against the metadata, else a stop |
| `s04-weights` | 3 | `tools/fetch_weights.py --profile rtxpro6000`, `HF_TOKEN` unset: a gated or refused file fails the step with the tool's words; nothing waits for input |
| `s05-stub` | 4 | `TB_POC_SKIP_INGEST=1 deploy/poc.sh`, status, down. **The database image is not built first:** #1130 (train 96) is on master and `deploy/poc.sh` `build_db_image` builds `trialbox-postgres:16-1` itself when it is missing (card 24-2). Its output (the administrator's password) stays in `raw/` on the VM; its last 15 lines go to the step's log redacted and masked. Then the build cache, the dangling layers and the stub's volumes are freed |
| `s06-engine` | 5 | `docker pull` of `tools/engine_probe.py pinned_ref` |
| `s07-ballast` | 5 | `tools.ballast hold --target-mib 49140` until `ready` (a `refused`, or neither in 15 minutes, ends the run), `ballast48 plan` |
| `s08-ladder` | 6 | `ballast48 measure --keep`: pair-32k; on exit 1 (did not start) pair-16k; then judge-alone. The first that starts is kept (decision `kept`). Exit 2 (refused before any server) or a stop at the line ends the ladder: the next option would meet the same refusal. None kept: the end |
| `s09-tools`, `s10-screen` | 7, 8 | on a kept **pair** only, and only when stages 7 and 8 together (0.90 h high) end before the line: the tools as `complete-run-vm.sh` sets them up, then 1,000 patients, ja, 16 in flight, `ballast48 during`. A failed screen is a record, not the end |
| `s11-o` | O | only when pair-32k is kept, `tb-o=1`, and O's high (0.25 h) ends before the line: `verifier-flag`; exit 1 is the result (decision `O result: flag refused`), the canary skipped; else the canary and `canary-diff` |
| `s12-down` | 8 / O | `ballast48 down` (always, when an option was kept) |
| `s13-host53` | 9 | only when pair-32k was kept and its high (0.80 h) ends before the line; it comes last, so it is the first dropped (decision `step 9: dropped`) |
| `s14-release` | 10 | SIGTERM to the ballast; `tools.ballast release` when it did not say `released` |

**The clock.** The VM counts its own seconds up over every boot (`used-s`). A stage starts only when its high
estimate ends before the stop line (`tb-stop-line-minutes`, 204: the line of section 5, 3.5 h, less stage 1's 0.10 h,
which passes before the script's first line). At the line the running tool gets SIGINT (lane J's measure writes what
it has and stops its servers; the screen's `complete_run`, so `during` writes its record), and 3 minutes later
SIGTERM; then the end: `down`, the release, the records up, power off. A failure of a needed step (1 to 7, or a
ladder with nothing kept) goes straight to the same end. The VM's own cap (`tb-cap-minutes`, 240) powers it off
whatever runs, after one last upload; the cloud's `--max-run-duration 4h` is the hard cap. A pre-emption stops the VM
(STOP): `--collect` says so; `--resume <run id>` starts it again with the minutes left of the 4 h as its cloud cap,
and the ballast is held again before any later step.

**The records, as it goes** (`$TB_BUCKET/m48runs/<run id>/`, after every step and every minute of a long one):
`steps.json`, `decisions.json`, `disk.jsonl` (free and used bytes before each step, and after each freeing),
`clock.txt`, `vm.log`, `logs/<step>.log` (last 400 lines), and under `records/`: `o0-card.csv`, `plan.txt`,
`ballast.log`, `head.json`, `tb-dgpu48-<option>/measure.*.json`, `serving_config.dgpu48.*.json`, `canary.*.json`,
`screen-during.json`, `screen/parts/prepare.json`, `screen/parts/hospital-ja.json`, `canary-verifier-flag.json`,
`canary-verifier-flag-diff.json`. The allow-list is `measure48_vm.py` `ALLOW`; `DENY` refuses `raw/`, any `.env`, any
path with `secrets`, `down.json`, `verifier-flag.yml`, the stub's output, key files and hidden files whatever ALLOW
says. Every text is masked (the values of `deploy/.env` and of each file under `deploy/secrets/`, the servers' key
among them) and each log line naming a password, token, key or secret is replaced whole; a JSON record is masked only.

`--collect` prints the summary (`summary.json`): which option started and was kept, each option's free memory at
peak, the sequences that fit (each role's `kv_cache_tokens` over the option's max context), seconds per judged call
(the canary's judge seconds over its cases), the screen's wall time and free memory at peak, O's verdicts that differ
(or why O did not run), and every step and decision.

### 9.3 The disk (100 GB)

GB as `df` counts them; "measured" means a figure in the repository, the rest are estimates the first run's
`disk.jsonl` replaces.

| After | Added | On disk | Source |
| --- | --- | --- | --- |
| boot | Ubuntu 24.04 | about 3 | not measured here |
| `s01-host` | driver 580-server, utilities, Docker, toolkit | about 5 | not measured |
| `s03-source` | the archive, unpacked | about 5.2 | archive 47 MB (measured here, `git archive` of master) |
| `s04-weights` | 27.9 GB, staged on the same disk and renamed into place (no second copy, no hub cache) | about 33 | `tools/fetch_weights.py --dry-run` |
| `s05-stub` | the box's images 3.7 GB, build cache 4.0 GB, base images about 2 GB | about 43 at its peak | measured: `docs/handover/installer-first-contact-2026-11-15/launches/box-20261115T085016Z-876ff6506/facts-vm.txt` (`trialbox-py` 0.82, `-jvm` 1.61, `-postgres` 0.57, hapi 0.60, caddy and authelia 0.15; build cache 4.02); base images not measured |
| freed | the build cache, dangling layers, the stub's volumes | about 39 | |
| `s06-engine` | the engine image 23.4 GB (layers in flight: a few GB more while it pulls) | about 62 (65 at the pull's peak) | measured: the same facts file, `vllm/vllm-openai:v0.32.0` 23.4 GB (the pinned ref's tag) |
| `s09-tools` | apt, the venv (0.65 GB here), node, Chromium, fonts, the hospital's data | about 66 after uv's and apt's caches are freed | the venv measured here (`make venv`); the rest not measured |
| `s10-screen` | PostgreSQL for 1,000 synthetic patients, the part's folder | about 67 | not measured |

**Peak about 67 GB of the root file system's about 97: it fits, with about 30 GB to spare.** The guard
(`measure48_vm.py` `NEED_GB`) checks free space before each big step and fails the step with `DISK-SHORT` in its
note: 30 GB before the weights, 14 before the stub, 30 before the engine image, 6 before the tools, 3 before the
screen, 1 before step 9. If the first run's `disk.jsonl` shows less room than this, the smallest change is to leave
the screen out (its tools, about 3 GB, and its data), then step 9 (no disk of its own).

### 9.4 The estimate, the stop line, the cap

**Unchanged stage by stage** (section 5): the same steps in the same order; the unattended form spends no time on
SSH and the screen's tools still come after the ladder. `deploy/gcp/measure48-run.sh --estimate` prints it from
`measure48_vm.py` `STAGES` (a test holds them equal to section 5's table):

- **The estimate: US$6.3 (2.30 h) with O; US$6.0 (2.18 h) without.** 2.30 h x US$2.74 = US$6.30.
- **The stop line: 3.5 h, US$9.5 with O** (2.30 h x 1.5 = 3.45 h, rounded up to a tenth; US$6.30 x 1.5 = US$9.45);
  3.3 h, US$9.0 without (2.18 x 1.5 = 3.27). On the VM's own clock: 204 and 192 minutes (less stage 1's 0.10 h).
- **The cap: `--max-run-duration 4h`, US$10.96** (4 x 2.74); the VM's own cap at 240 minutes of its clock.
- **The worst case: about US$11.0**, not section 5's US$11.09: the cap US$10.96 plus the 100 GB disk for 4 h at
  US$0.093 a GiB-month, 100 x 0.093 x 4 / 730 = US$0.05 (250 GB was US$0.13). On demand the same cap is US$32.88.
  A collect after a stopped VM costs nothing now (the records are in the bucket; no start to copy them).

### 9.5 What changed from the SSH sheet, and why

- No SSH, no tmux, no person: the VM's start-up script does steps 2 to 10 and every choice of the sheet (the reboot,
  the ladder's next option, O or not, step 9 or not, a stop at the line) is made from the clock and the exit codes and
  written to `decisions.json`. Why: the integrator's container has no outbound port 22.
- The disk is 100 GB, not 250 (the quota); section 9.3 shows it fits.
- Step 1 is the driver's, same shape; the VM is deleted by the `--collect` that finds the run ended (or `--delete`).
- Step 3: the commit's `git archive` from the bucket (as `complete-run.sh`), not a clone; the weights with no token.
- Step 4: no separate database image build (#1130 is on master; `deploy/poc.sh` builds it).
- Steps 7 and 8 run as root (a start-up script), with the tools where `complete-run-vm.sh` puts them, and the screen
  passes `--ocr tesseract`, as the paid complete run does (the sheet installed tesseract and left the default
  `fake`; the measured 5,000-patient rows it is compared with ran with tesseract; question H-2).
- The screen runs on a kept pair only: judge-alone serves no verifier, so `--model pair` has nothing to call (the
  sheet said to screen on whatever was kept; question H-3).
- Step 10: the records come through the bucket as the run goes, not by `scp` at the end.

### 9.6 What the first real run is the first to exercise

Everything on a VM: the driver's install by `ubuntu-drivers` on this image and the reboot from a start-up script;
`gcloud` on the VM (the image's snap) writing to the bucket with `--scopes storage-rw`; `deploy/poc.sh` as root from
a start-up script with no terminal; the hub serving the weights to this VM without a token; the ballast, lane J's
measure, the screen and stage O on the card (section 8's list stands); SIGINT reaching lane J's measure at the line
and its servers stopped by its own handler; the disk figures marked "not measured"; the quota reading of
`HDB_TOTAL_GB` from `gcloud compute regions describe` (the metric's name is the integrator's report).

### 9.7 Questions (H-53)

- **H-2 (integrator, lead):** `--ocr tesseract` in the screen (as the paid complete run), or the sheet's default
  `fake`?
- **H-3 (lane J):** with judge-alone kept, leave the screen out (as now), or screen with the judge alone by some
  other model setting?
- **I-2 stands:** stage O is in by default (`tb-o=1`); `--no-o` leaves it out.
