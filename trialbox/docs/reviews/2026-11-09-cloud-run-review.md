# TrialBox cloud GPU run: independent review before the next paid launch

Scope: `trialbox/deploy/gcp/complete-run.sh`, `complete-run-vm.sh`, `gcloud-auth.sh`, `tools/complete_run.py`,
`tools/scenarios.py`, `tools/pin_model.py`, `tools/serving_config.py`, `tools/bench_*.py`, the gateway and registry,
`models/routing.yaml`, D-139/D-141/D-148, RUNBOOK §11, the four failed runs of 2026-11-09 (artifacts of run 4 in
`.cache/complete-run/20261109T163523Z-de11cf2/`, driver logs `scratchpad/g1*.log`) and the fix on branch `gw404`
(commit `c65abec`). Review only: no repo file changed, no VM started, no gcloud command run. Everything executable was
done in `/tmp/claude-0/review-cloudrun/proto/` (a local rehearsal of the real VM script, section 5).

Paths below are relative to `/home/user/Auto-GPT/trialbox/`; line numbers are those of `master` at `9e8ae30`.

## Verdict

**NO-GO for a full 50,000-patient run as the path stands today; GO for a short, bounded rehearsal run (`--only` a few
model parts, `--hours 2`) once the items marked "gate" in section 7 are done.**

The `gw404` fix is correct for the 404 (verified independently: code reading, its 12 tests, and a local rehearsal that
reproduces the 404 on `master` and clears it with `gw404`'s source, section 5.4). But run 5 would still not pass:
the hospital parts crashed on a second, unrelated cause (the CQL translator jars) that `gw404` addresses with a boot-time
maven download that has never run; the four public-corpus parts cannot pass on the VM at all (their corpora are not
shipped); the persistent VM disk carries `parts/` across runs so a passed part is silently kept under a new HEAD;
the model servers' health is never asserted; and the driver, as operated today (a background shell capped at 2 h),
dies in every full run, after which the VM's own liveness signal (log growth) is the only thing between a silent
two-hour SCREEN and a 20-minute power-off.

## 1. Findings, by severity

Severity: C = critical (the run cannot pass or costs money for nothing), H = high (wrong result or lost run likely),
M = medium (wrong report, wasted time, or a real but bounded risk), L = low.

| ID | Sev | Where | What fails | Evidence | Fix |
| --- | --- | --- | --- | --- | --- |
| C-01 | C (fixed on `gw404`) | `tools/pin_model.py:206-226` (PROFILE_PAIRS), `tools/scenarios.py:168-186,207-226`, `services/gateway/core.py:362,410-412`, `services/registry/registry.py:192-196` | The installed-box gateway pins the compose defaults `gemma-4-26b-a4b-it` / `qwen3.5-9b` as served names and sends them as `model`; the VM's vLLM serves `local/gemma-4-26b-a4b-nvfp4` / `local/qwen3.5-9b-awq` (`complete-run-vm.sh:167,169`) and answers 404. Every gateway call of run 4 was `upstream_failed: serving: HTTP 404; verifier: HTTP 404`. | `parts/profile.json` (`gateway_refused`), `parts/scenario-gateway.json`, `shard-1/vm.log:631`; rehearsal boot 2: judge stand-in logged 117 × `404 for model 'gemma-4-26b-a4b-it'` (section 5.4) | `gw404` `c65abec`: one pair of served-name constants used by pins, compose, VM script, `complete_run`; `install_pins` renames old pins. Verified. Add the VM-side pre-flight of H-02 so a name drift is caught before the parts run. |
| C-02 | C (partly on `gw404`) | `services/criteria_compiler/compile_cql/translator.py:35-54`, `service.py:232-233,265,756`, `complete-run-vm.sh:200-202` | `hospital-ja` / `hospital-zh-TW` crashed before any check: the GOUT-COH FEAS job failed in compiling with `FileNotFoundError: FHIRHelpers-4.0.1.cql not found in the cql-translator jars`. The jars live in `.cache/jvm` (git-ignored, not in `git archive`); the VM installs no JRE. Independent of the 404: run 5 crashes here again unless fixed. | `shard-1/vm.log:632,638`, `parts/hospital-*.json` (`AssertionError(('GOUT-COH','failed'))`); `git ls-files` has 0 `.cache/` entries; `tar -tzf src.tgz` has 0 `.cache/` entries | `gw404` adds `apt maven` + `tools/fetch_jvm_deps.sh` at boot (validator 192 MB + maven deps 156 MB + FHIR packages 421 MB, three new egress hosts, re-fetched every boot because `rm -rf $SRC`, only syntax-checked). Prefer: ship `.cache/jvm/cql-translator/lib` (156 MB) in the upload or bake it into the disk once, `apt default-jre-headless`; `deploy/gcp/hosted-demo-startup.sh:43-45` already does the minimal variant (one `quick-5.4.0.jar` curl). Whichever is chosen must be rehearsed (section 5) before paying. |
| C-03 | C | `tools/public_e2e.py` (reads `.cache/medtxt`), `tools/scenarios.py:1838,1918-1919`, `tools/medtxt_eval.py:49-75`, `tools/trec_ct_eval.py:48-76` | `public-ja`, `public-zh-TW` crash (`FileNotFoundError .cache/medtxt/Test collection`), `scenario-public-medtxt` and `scenario-public-trec` fail "the corpus is here". The corpora are in the laptop's `.cache` only; nothing fetches them on the VM; the estimate still bills 0.36 h × 2 + 0.38 h + 0.32 h for them. Four parts that can never pass on this path, in every run so far. | `parts/public-ja.json`, `parts/scenario-public-medtxt.json`, `parts/scenario-public-trec.json`; `plan.json` rows | Either fetch in setup (`medtxt_eval.fetch()`, `trec_ct_eval.fetch()` exist; MedTxt is 1.4 MB, TREC 429 MB; `hosted-demo-startup.sh:39-42` shows the MedTxt curl) or ship them in the upload, or drop them from the VM plan and the estimate honestly. Gate for run 5. |
| H-01 | H | `complete-run-vm.sh:25,29,242-244` (`--dir $TB/run --resume`, always), `tools/complete_run.py:591-593,660-662` | `/var/lib/tb/run/parts/*.json` persists on the VM disk across runs and `--resume` keeps any part that passed earlier, whatever run id or git HEAD produced it. Run 5 will print "done earlier, kept (--resume)" for `prepare`, `install`, `it-dump`, `registry`, `public-mimic`, `redcap`, `embed`, `profile` from run 4's code and report them under run 5's HEAD. The `profile` row (which passed only by falling back to direct calls, M-03) would never be re-measured through the gateway. | rehearsal boot 2 → boot 3: `scenario-it-dump` kept from boot 2 under boot 3's different HEAD (section 5.4); `vm.log` of run 4 shows no "kept" only because runs 1-3 never reached a part | Key the run directory by run id (`$TB/run/$RUN_ID`), or wipe `parts/` when `tb-run-id` differs from a marker file; record the producing HEAD in each `parts/<tag>.json` and refuse to keep a part from another HEAD. Also a `--fresh` metadata flag. |
| H-02 | H | `complete-run-vm.sh:166-171,179` | The health loops (`for _ in seq 240; healthy && break`) time out after 20 min each and the script continues regardless; `PRO6000-RUN-READY` is printed unconditionally; the serving record capture is `\|\| true`. A judge that never comes up (OOM, image pull failure, missing NVIDIA runtime, cold HF download) gives a full paid run in which every model part fails. Nothing checks that the servers serve the names `complete_run` expects. | code; no test exercises the loop's exit | After each loop: `healthy judge \|\| setup_failed "judge not healthy"` (needs `setup_failed` moved above, and a results.tgz with the serving log). Then an authenticated pre-flight: `GET /v1/models` on both servers must list exactly `local/gemma-4-26b-a4b-nvfp4` and `local/qwen3.5-9b-awq`, and one `chat/completions` each through `127.0.0.1:8080/{judge,verifier}/v1` must return 200 — else fail loudly. This alone would have stopped run 4 after 15 minutes. |
| H-03 | H | `tools/complete_run.py:586,673,683`, `complete-run-vm.sh:55-56,234-238` | The VM's own liveness signal is "the run log grew in the last minute"; the run prints only at part boundaries and `logging.disable(INFO)` silences the services. A 50,000-patient hospital part is estimated at 2.14 h of mostly silent SCREEN. While the driver heartbeats every 60 s this is masked; once the driver is gone (H-04), the 20-minute idle watchdog powers the VM off mid-part. The result is a lost part and a restart (~30 min of setup again). | `plan.json` (db-csv 7,706 s), `complete-run-vm.sh:240-245` (no in-run heartbeat besides `--heartbeat` before each part) | Heartbeat from inside the run: the part process touches `$HB` on every model call / stage (pass `--heartbeat` down to parts, or have `tb_common.llm` touch `TB_HEARTBEAT_FILE`); or make the idle limit during phase `run` the part's budget (8 h for hospital) and keep 20 min for setup. |
| H-04 | H | operator practice; `complete-run.sh:108,144,147-163` | The driver is started in the operator's background shell, capped at 2 h; a 9.45 h run outlives it in every case (run 4's driver survived only because the run failed in 36 min). After the driver dies: no heartbeats (H-03); when the VM finishes, DONE + 30-min grace → power-off; `--collect` then finds `natIP` empty (TERMINATED) and cannot fetch `results.tgz` — the results sit on the stopped disk. Getting them needs a manual VM start: models load (~15 min), the door serves the old `results.tgz`, then TB-NO-CODE after 30 min, 30 min grace → about US$2-3 and 45-75 min for a download. | `g1c.log`, `g1-collect.log` ("results not reachable" path at `complete-run.sh:160`), RUNBOOK §11 step 4 | Run the driver detached (`setsid nohup`, or `systemd-run --user`), or `--no-wait` plus a scheduled `--collect` every hour; make `--collect` able to start a stopped VM in a results-only mode (`tb-collect-only=1`: no models, serve `/results.tgz`, power off on `collected`); or set `TB_BUCKET` (needs the VM service account's storage scope — check `instances describe --format='value(serviceAccounts[0].scopes)'`, read-only) so results leave the VM as they are made. |
| H-05 | H | `complete-run.sh:244-264` (no quota check), `226-239` (`--provision`), RUNBOOK §11 "Several VMs" | The project has `GPUS_ALL_REGIONS = 1` and `PREEMPTIBLE_CPUS = 0`. Spot VMs draw on the *regular* quota when the preemptible quota is 0, so `tb-gpu-sim` already uses the project's one GPU. `--vms N>1` cannot start a second GPU VM; `--provision` would create the machine image (billed storage of the whole disk, including the 28 GB of weights) and then fail on the clones' `instances create`; a `--vms 4` run starts VM 1, the other three children fail, the merge reports three shards "did not report". The dry run only *prints* the quota commands for the owner. | project quota as stated; `complete-run.sh:246-251` | Before `--provision` or a multi-VM start, read `gcloud compute project-info describe --flatten=quotas --filter='quotas.metric~GPUS_ALL_REGIONS'` and each region's `NVIDIA_RTX_PRO_6000_GPUS`/`CPUS` and refuse when `limit - usage < N` (read-only calls, through `gc`). Request the quota increase first; until granted, D-148's multi-VM plan is not runnable. |
| M-01 | M | `complete-run-vm.sh:21,193` (`tee -a`, `>>$LOG`), `251` (`$TB/out/results.tgz` never removed), `32` (only DONE/collected removed) | Logs and results persist across boots: the driver's `/progress` tail shows the *previous* boot's last lines for the whole setup phase (run 4: `g1c.log` 16:36-16:39 showed run 3's `TB-SETUP-FAILED: playwright`; rehearsal boot 2 showed boot 1's git traceback); `vm.log` in `results.tgz` contains every earlier run; after TB-NO-CODE the driver downloads the *previous* run's `results.tgz`. | `g1c.log:10-20`, `shard-1/vm.log:1-237` (run 3's setup inside run 4's log), rehearsal section 5.4 | At boot: truncate `/var/log/tb-complete-run.log` (or name it by run id), `rm -f $TB/out/results.tgz $TB/run-ended`. |
| M-02 | M | `complete-run.sh:307-308,310-311`; `tools/complete_run.py:712,727,733,736` | The stub parts run on the driver without `--patients`: `scale` ran at **5,000**, not 50,000 (owner decision 1 of D-141, "the bulk scale test"), while the report header says "Hospital: 50,000". `--report-only` is also run without `--ocr tesseract` (header says "OCR: fake"; the VM used tesseract), and takes git head, dirty flag and host CPUs from the driver machine at collect time ("Host: x86_64, 4 CPUs"). | `report.md` header vs `parts/scale.json` ("cascade at 5000 patients"), `g1c.log` | Pass `--patients "$PATIENTS" --ocr tesseract` to both; record the VM's HEAD (from `src.tgz`'s commit, write it into the archive) and host in `results.tgz` and use those in the report. |
| M-03 | M | `tools/complete_run.py:597-601,739-745`; `tools/bench_profile.py:190-224` | Report truthfulness: a crashed part counts as **one** failed check, so "86 of 111" hides about 700 checks that never ran (hospital ja/zh-TW alone are 338 locally); `profile` is a green PASS although the gateway path was refused and it fell back to direct calls (the refusal is only in the stage name and the JSON). No false PASS was found among executed checks; the verdict FAILED is right. | `report.md` rows "crashed 0/1"; `parts/profile.json` `"path": "direct (the gateway refused: ...)"` | Count a crashed part with its planned checks (or add "N parts crashed, M checks not run" to the headline); give `profile` a check "the gateway path answered" that fails on fallback. |
| M-04 | M | `complete-run-vm.sh:53-54` (60 min from boot in phase `setup`), `168,171` (2 × 20 min), `188` (30 min code wait), setup 8-15 min (+ maven on `gw404`) | The setup watchdog counts from boot and covers model loading, the code wait and the whole setup. Cached weights: ~20 min total today. Cold cache (a new disk, a clone, a vLLM image pull) or a slow upload can exceed 60 min and the VM powers itself off during a legitimate setup, which `--collect` then reports as "no results". | code | Per-phase limits (serving ≤ 40 min, code ≤ 30 min, setup ≤ 30 min) or 120 min; print the phase change to the console. |
| M-05 | M | `complete-run-vm.sh:77-78,115,124-125,144` | No wait for the docker daemon (the startup script can run before `docker.service` is ready on first boot); if `docker0` is absent the door falls back to `172.17.0.1`, which may be unbindable, and the `tb-door` unit dies silently (`systemd-run`, no restart); `docker run front` failures are not fatal. Outcome: the driver's 30-min upload loop fails, the VM waits 30 min for code, TB-NO-CODE, 30 min grace → ~1 h paid for nothing. | code; rehearsal exercised the fallback branch only (section 5.3) | `until docker info >/dev/null; do sleep 2; done` with a timeout; `--property=Restart=on-failure` for the door; before READY, the VM curls its own `http://127.0.0.1/tb/progress` with the key and fails loudly if not 200. |
| M-06 | M | `complete-run.sh:112,139`; `complete-run-vm.sh:97-103,144,190-191,240` | Plain HTTP on the public address: the key travels in cleartext ~600 times per run, and the same key authorizes `PUT /tb/upload`, whose tarball is extracted and executed **as root** (`tar -xzf` as root, no `--no-same-owner`, no integrity check). An on-path attacker gets root on the VM; the model servers are also reachable from the internet with the key. Synthetic data only, so no privacy exposure; the risk is the VM and the key. | code; `setup-gcp.sh:9` (a firewall rule for the VM, port 80 open for the demo) | Prefer `TB_BUCKET` (code and results never touch the public port), or HTTPS with a self-signed cert whose fingerprint the driver pins (`curl --cacert`), or an IAP TCP tunnel; put the upload's sha256 in metadata and verify before extracting; `tar --no-same-owner` into a non-root user's tree. |
| M-07 | M | `complete-run-vm.sh:183-189,253` (bucket branch), `237` (`gcloud storage rsync` of `parts/` every minute, errors dropped) | The bucket path has never run; the VM's service account scopes are unknown; failures are `\|\| true` / `>/dev/null 2>&1`, so a run with `TB_BUCKET` set could end with no `results.tgz` in the bucket and the driver waiting for nothing (`complete-run.sh:159`). | D-141 "the bucket path has not run on a VM" | Rehearse with a fake `gcloud` (section 5) and verify the scope read-only before use; make the final `cp` fatal-loud (`TB-UPLOAD-FAILED` on the console). |
| M-08 | M | `complete-run-vm.sh` (whole), `tools/complete_run.py:122-128` | Undeclared base-image assumptions: `docker` with the NVIDIA runtime (installed by an earlier `gpu-sim-startup.sh` boot, not by this script), `git` (needed by `complete_run.git_head()` — the run dies before any part without it), `gcloud` (bucket path), `/models` with both weights (28 GB; a fresh disk downloads from the HF hub inside the 20-min health loop), GCE apt mirrors, outbound access to PyPI, nodejs.org, astral.sh, GitHub, Maven Central, playwright's CDN, PhysioNet. A clone from a machine image inherits them; a re-created `tb-gpu-sim` does not. | rehearsal boot 1: `FileNotFoundError: 'git'`, `TB-RUN-EXIT 1`, results.tgz with only `vm.log` (section 5.4) | A pre-flight block at the top of the script: `command -v docker git nvidia-smi`, `docker info \| grep -qi nvidia`, `ls /models/hub/models--nvidia--Gemma-4-26B-A4B-NVFP4 /models/hub/models--cyankiwi--Qwen3.5-9B-AWQ-4bit`, `df` ≥ 50 GB free; each failure a loud `TB-PREFLIGHT-FAILED` marker and DONE. Add `git` to the apt list. |
| M-09 | M | `tools/scenarios.py:168-186` (`installed_registry`) | On the VM `deploy/models` does not exist, so the "installed box" gateway pins **synthetic weights** (`model.safetensors` = `b"synthetic ..."`). The weight pin, the registry's main identity control, is therefore a fiction in the cloud run; only the served-model echo (`check_served`) is real. The report calls the path "gateway (installed box)". | code | Say so in the report (`path: gateway (installed box, synthetic weight pins)`), or point `installed_registry` at `/models/hub/...` snapshots so the pins are of the real weights (the serving record already hashes them: `serving_config.rtxpro6000.live.json`). |
| M-10 | M | `complete-run-vm.sh:251` (one `tar` at the very end), `complete-run.sh:36-37` | No partial results: `results.tgz` is made only when the run ends. A Spot preemption, the cloud cap or the watchdog leaves `parts/` on the disk but nothing to collect; without `TB_BUCKET` the driver gets "results not reachable". The documented restart (`TB_RUN_ID=<id> --shard i`) re-runs setup (~10 min) and relies on `--resume` (H-01). | code | Re-pack `results.tgz` after every part (cheap), so a stopped VM's disk always has a current archive for a results-only start (H-04). |
| M-11 | M | `gw404` `complete-run-vm.sh:202,221-223` | The fix's maven step runs `tools/fetch_jvm_deps.sh` at every boot (`set -euo pipefail`): three new network dependencies in the paid window (GitHub releases, Maven Central, the FHIR package registry), ~770 MB, ~5 min, inside the 60-min setup limit (M-04); a transient failure is `setup_failed` → a wasted boot. Never executed. | diff of `c65abec` | See C-02: ship the jars or bake them; at minimum rehearse once (section 5) and move it before the Playwright step so the slow downloads overlap less with the setup limit. |
| L-01 | L | `libs/tb_common/config.py:124`, `deploy/docker-compose.yml:237` | On a real box the orchestrator's judge client is built from `LLM_MODEL` (default `qwen3.5-35b-a3b-q4`), so judging records and the canary name the wrong judge; the gateway's `check_served` still guarantees the real identity. Not a run-5 blocker (the harness names its clients on `gw404`). | the other agent's open item, confirmed | Derive the reported name from the gateway's response (`payload["model"]`, `X-TB-Model-Alias`) instead of config. |
| L-02 | L | `gw404` `tools/pin_model.py` (`install_pins` → `set_served`) | A champion pin's served name is now rewritten silently at every install when compose's name differs; fine for the run, but on a site this is a registry change without `--verify` or an audit line. The committed `models/registry.yaml` still has `served: {serving: null}` for every build, so the override is the only source of the name. | diff | Log the rename on the console/audit; consider committing the measured names in `registry.yaml`. |
| L-03 | L | `complete-run.sh:106,208-216` | `--stop` restores `gpu-sim-startup.sh`; a later by-hand `instances start` (e.g. to collect) runs both vLLM servers with **no watchdog** until the last `max-run-duration` (13 h ≈ US$35). Every scripted path is under the cloud cap; this by-hand path is covered by the cap only. | code | A results-only startup script for collection (H-04), and a RUNBOOK line. |
| L-04 | L | `complete-run.sh:227-228` | `--provision` creates a machine image of the whole disk before the quota check that would fail (H-05); the image is billed until `--teardown`. | code | Quota check first; print the image's size and monthly cost. |
| L-05 | L | `complete-run-vm.sh:218` | Setup never verifies that the browser launches; a half-installed Chromium is found only when every screenshot fails (rehearsal boot 1: ENOSPC during `playwright install`, setup still "done"). | rehearsal | `node -e "require('playwright').chromium.launch().then(b=>b.close())"` after the install, else `setup_failed`. |
| L-06 | L | `tests/unit/test_scenario_matrix.py:216-241`, `tests/unit/test_gpu_prep.py:267-293`, `tests/unit/test_gateway_box_phi.py:109-110`, `services/llm_stub/app.py:57` | Why four bugs passed every check: the VM script is tested by **text greps**; the driver by `--dry-run`, which never runs the VM script; the stub echoes whatever `model` it is asked for, so the served-model check passes for any pin; and a unit test asserted the wrong served names as correct. | code | Section 4: a rehearsal that runs the real VM script against vLLM-faithful stand-ins; `gw404` adds `test_served_names.py` (good) — keep the stand-in strict about `model`. |

Privacy and secrets (section 6) found nothing wrong: only synthetic and public data reach the VM, and no key or
password is printed or committed.

## 2. The VM, step by step (what can fail, is it loud, is it tested)

`complete-run-vm.sh`, in order. "Loud" = the driver or the results say so; "Tested" = anything beyond a text grep.

| # | Step (lines) | Can fail when | Loud? | Tested? | Notes |
| --- | --- | --- | --- | --- | --- |
| 0 | `exec > >(tee -a ...)`, `mkdir $TB/...`, `rm -f DONE collected` (21-32) | — | — | grep | Appends to last boot's log (M-01); `run/`, `out/results.tgz`, `run-ended` survive (H-01, M-01) |
| 1 | hard cap `systemd-run --on-active` (35-39) | metadata missing → defaults | n/a | grep | OK; `tb-max-minutes` = cap − 5 min |
| 2 | watchdog (40-61) | setup > 60 min (M-04); silent part > 20 min (H-03) | console only | grep; **rehearsal: fires correctly on `collected`** | Grace path verified in the rehearsal (section 5.4) |
| 3 | `KEY=$(md tb-key)` (63) | metadata server slow at boot → empty key → vLLM started with `--api-key ""`, nginx checks `Bearer ` | no | no | Add `[ -n "$KEY" ] \|\| poweroff` |
| 4 | door on docker0 (75-115) | docker0 absent/late (M-05); port 8081 taken | no (unit dies silently) | grep; **rehearsal: works, 401 on bad key** | |
| 5 | `docker rm/network/run front` (124-145) | docker not ready; port 80 busy (old `front` with `--restart unless-stopped` is removed first, fine) | stderr only | no | nginx config has the key, 0600 (fine) |
| 6 | GPU peak sampler (146-159) | nvidia-smi missing → loops silently | no | no | harmless |
| 7 | start judge/verifier, health loops (160-171) | image pull, NVIDIA runtime, OOM, cold HF download > 20 min, wrong names | **no** (H-02) | no | The biggest silent gap |
| 8 | serving record capture (172-178) | `docker inspect`/`nvidia-smi` failures | `\|\| true` | unit tests of `serving_config.py` | `--api-key` never recorded (`SECRET_FLAGS`) |
| 9 | `PRO6000-RUN-READY` (179) | printed even if 7 failed | — | — | |
| 10 | bucket copy / code wait 30 min (183-189) | upload late, driver dead | TB-NO-CODE + DONE | **rehearsal** | after TB-NO-CODE the old `results.tgz` is served (M-01) |
| 11 | `rm -rf $SRC; tar -xzf` (190-191) | tarball tampered (M-06) | exit 1 + DONE | rehearsal | |
| 12 | apt (200-202) | mirror/apt lock; no JRE (C-02); `maven` on `gw404` | `setup_failed` (loud, PR #53) | **rehearsal** | |
| 13 | uv + venv (205-212) | PyPI, PEP 668 (fixed), python 3.12 absent | loud | **rehearsal** | |
| 14 | Node from nodejs.org (214-217) | egress, checksum not verified | loud | **rehearsal** | |
| 15 | playwright + chromium (218) | CDN, apt deps, disk | loud, but no launch check (L-05) | **rehearsal** | |
| 16 | fonts (220) | egress | `\|\| true` | — | |
| 16b | (`gw404`) `fetch_jvm_deps.sh` | GitHub, Maven Central, FHIR registry (M-11) | loud | **never run** | |
| 17 | `tb-embed-py` wrapper (225-230) | — | — | grep | runs in the vLLM image; passed on the card |
| 18 | heartbeat-on-log-growth loop (234-238) | silent part (H-03) | poweroff | no | |
| 19 | the run (240-245): `--resume`, `--dir $TB/run` | stale parts (H-01); `git` missing (M-08); corpora missing (C-03); jars (C-02); 404 (C-01) | per-part FAIL rows; a crash is 0/1 (M-03) | **rehearsal** | |
| 20 | pack results, DONE (246-256) | tar members missing → still an archive | — | rehearsal | once only (M-10) |

Ordering and races found: 3 (key before metadata is ready is theoretical on GCE but unguarded), 4/5 (door before
docker/docker0; the door is started before the `front` container, which is right, but nothing re-checks the pair),
7→9 (READY before healthy), 2 vs 7+10+12-16 (one 60-min budget for everything).

## 3. The model-serving and gateway chain, end to end

```
complete_run part ... --judge-url http://127.0.0.1:8080/judge/v1 --verifier-url http://127.0.0.1:8080/verifier/v1
  └ tools/scenarios.models()  (TB_ENV=PRODUCTION, TB_TOPOLOGY=A, TB_PROFILE=P-PRO6000, no TB_DATA_CLASS)
      installed_env(): TB_EP_SERVING_URL=<judge-url>, TB_EP_VERIFIER_URL=<verifier-url>
      installed_registry(): pin_model.install_pins("rtxpro6000", <fake weights>, registry.site.yaml)
          → builds gemma-4-26b-a4b-it-rtxpro6000 (alias j-workhorse, endpoint serving, served = PROFILE_PAIRS default)
            qwen3.5-9b-rtxpro6000              (alias v-verifier,  endpoint verifier, served = PROFILE_PAIRS default)
      gateway_client(): in-process tb-gateway, caller "orchestrator"
  └ gateway.core._chat: route `patient`/`documents-d3` (D3, PRODUCTION, A) → phi_on_box allows D3 for orchestrator/matching
      registry.resolve(alias, endpoint) → Resolved.served_name  = the pin's served name            ← C-01 was here
      upstream["model"] = res.served_name; no Authorization (serving/verifier have no api_key_env)
      POST http://127.0.0.1:8080/judge/v1/chat/completions
  └ nginx (front container, 127.0.0.1:8080): rewrite /judge/(.*) → /$1, proxy_set_header Authorization "Bearer $KEY",
      proxy_pass http://judge:8000  (docker DNS 127.0.0.11)
  └ vLLM judge: --served-model-name local/gemma-4-26b-a4b-nvfp4 --api-key $KEY
      model != served name → 404 {"type":"NotFoundError"} ; else echoes "model": served name
  └ gateway: status ≥ 400 → errors "serving: HTTP 404" → tries the next candidate (v-verifier@verifier) → 404 → Refusal
      502 upstream_failed  → LlmError "gateway refused judge: upstream_failed" → canary 0/54 → SCREEN "did not answer N of N"
```

**Root cause of run 4's 404** (independently confirmed): `tools/pin_model.py:206-226` on `master` pins the served names
`gemma-4-26b-a4b-it` and `qwen3.5-9b` (the compose defaults of `deploy/docker-compose.rtxpro6000.yml`), and
`services/gateway/core.py:362` sends the pin's served name as the request's `model`. The VM starts vLLM with
`--served-model-name local/gemma-4-26b-a4b-nvfp4` / `local/qwen3.5-9b-awq` (`complete-run-vm.sh:167,169`;
confirmed by `serving_config.rtxpro6000.live.json`). vLLM answers 404 to a name it does not serve. The direct profile
bench worked because `tools/bench_profile.py:235` sends `JUDGE = "local/gemma-4-26b-a4b-nvfp4"` itself. The canary's
"empty model name" is `tools/scenarios.py:223` building `LlmClient("http://unused/v1", "", gateway=...)` and
`services/orchestrator/selftest.py:91` reporting `client.model`. The local stub never showed it because
`services/llm_stub/app.py:57` echoes whatever `model` it is asked for, so `check_served` passes for any pin, and
`tests/unit/test_gateway_box_phi.py:109-110` asserted the wrong names as expected. Reproduced locally in the rehearsal
(section 5.4: 117 + 225 stand-in 404s for exactly those names on `master`; 0 with `gw404`).

Other points on the same chain, checked:

* URLs and paths are right: `/judge/v1` + `/chat/completions` → `/v1/chat/completions` on `judge:8000`; nginx's
  `resolver 127.0.0.11` with a variable upstream works on a user-defined docker network (rehearsed with a DNS stand-in).
* The key: nginx adds it on 8080; the gateway sends none (no `api_key_env` on perimeter endpoints) — correct. On :80
  nginx checks the key for `/tb/` and vLLM checks it for `/judge/`, `/verifier/`; `/record/` is unauthenticated and
  contains no secret (`serving_config.py:69 SECRET_FLAGS`).
* `phi_on_box`: topology A, PRODUCTION, D3, callers orchestrator/matching — `gateway_client` uses "orchestrator";
  `bench_profile` uses role `abstract_field`, which `callers.orchestrator.roles` lists. Fine. GW-02 (`chart_facts`
  role) is fixed: run 4 reached the upstream.
* Served-model echo (`check_served`): vLLM echoes the served name, so with `gw404`'s names it passes. The stand-in
  used in `test_served_names.py` and in my rehearsal both enforce the name; keep them strict.
* `e2e_simple.PAIR` checks (`tools/e2e_simple.py:1084-1099`) compare the judging record's model names with the pair:
  on `master` the gateway clients had `model=""` → these checks would have failed even without the 404; `gw404`
  names the clients (`scenarios.py:220-226`). Good.
* Pins are of synthetic weights on the VM (M-09).
* `gw404` also changes compose defaults for GB10 and RTX 5090: the existing *pinned* boxes of those profiles keep working
  only because `install_pins` now renames old pins (L-02) — any box that does not re-run install after the update
  would 404 like run 4. Worth a RUNBOOK line.

## 4. The driver side

* **Heartbeats vs the 20-minute watchdog.** Alive driver: a heartbeat every 60 s (`complete-run.sh:151`), fine.
  Dead driver: only log growth keeps the VM alive (H-03). The long parts are silent (`complete_run.py:586,673,683`).
* **Operator session dies / the 2-hour background shell.** Every full run outlives the shell (H-04). The VM finishes
  on its own and powers off after 30 min; `--collect` cannot reach a TERMINATED VM's results (`complete-run.sh:108,
  159-160`). The disk keeps them; getting them costs a manual start (L-03, M-10).
* **`--collect` resume and keys.** `plan.json` drives everything; the key file is kept until `results.tgz` is here
  (`complete-run.sh:163`), then removed, so a second `--collect` says "no key" and only re-merges — fine. A `--shard i`
  restart writes a new key and metadata — fine. `--collect` while the VM is RUNNING polls until DONE (again > 2 h).
* **Cost caps.** Every scripted start is preceded by `set-scheduling --max-run-duration --instance-termination-action=STOP`
  (`complete-run.sh:125`, verified in `g1*.log`: `46800 STOP`), `--provision` creates clones with a 30-min cap, and the
  VM has the systemd cap and the watchdog. Uncovered: a by-hand start after `--stop` (L-03: cap only), the machine
  image's storage (L-04), and the clones' disks between runs (documented). The watchdog's `collected` path works
  (rehearsal).
* **Spot preemption.** STOP keeps the disk; `TB_RUN_ID=<id> --shard i` re-caps and restarts; `--resume` continues.
  But no partial `results.tgz` exists (M-10), the restart repeats setup, and H-01 applies.
* **Quota / `--vms N`.** Not runnable today (H-05): one GPU project-wide, Spot drawing on the regular quota. The
  script never checks; the dry run prints the commands for the owner.

## 5. Why four bugs passed, and the local rehearsal

### 5.1 Why they passed

`--dry-run` prints gcloud commands and never executes `complete-run-vm.sh`. The unit tests for the VM script are text
greps (`test_scenario_matrix.py:235-241`, `test_gpu_prep.py:267-293`). The local stub runs use an in-process stub that
accepts any model name, needs no nginx, no door, no apt, no venv, no Node from nodejs.org, and has the laptop's
`.cache` (jars, corpora) and `git`. Nothing ever executed the VM script's steps 4-19 off the paid VM. Bugs 1-4 (door
address, PEP 668, Node version, served names) and the two still-unfixed ones (jars, corpora) all live in that gap.

### 5.2 Design: run the real VM script locally against faithful stand-ins

Run `deploy/gcp/complete-run-vm.sh` **unmodified** inside an Ubuntu 24.04 container (or chroot) with:

1. **Metadata**: a `curl` wrapper first in PATH that answers `http://metadata.google.internal/computeMetadata/v1/
   instance/attributes/<key>` from files (`tb-key`, `tb-run-id`, `tb-only`, `tb-patients`, `tb-max-minutes`,
   `tb-idle-minutes`, `tb-done-grace`, optional `tb-serving-config`, `tb-bucket`); a missing key is exit 22, as on GCE.
2. **systemd**: `systemd-run` → background process (a `--on-active` timer sleeps first); `systemctl poweroff` → records
   who powered off and when, then kills everything (the "VM" stops; its disk stays for inspection).
3. **docker**: `docker run --name judge|verifier` → a **vLLM stand-in** (FastAPI over the repo's deterministic
   `llm_stub`) that enforces `--api-key` (401), answers **404 to any `model` but the served name**, echoes the served
   name, and reports `/health` only after a configurable load delay; `--name front` → the real nginx with the script's
   own `/root/nginx.conf`; a DNS stand-in on `127.0.0.11:53` for `resolver 127.0.0.11` (judge → 127.0.0.2, verifier →
   127.0.0.3); `docker exec … /health` → curl; `--entrypoint python3` (the embed bench) → the host venv.
4. **GPU**: `nvidia-smi` prints a fixed `used, total`.
5. **docker0**: `172.17.0.1` on an interface (the sandbox kernel has no dummy module, so on `lo`; the fallback branch
   `DOOR_HOST=${DOOR_HOST:-172.17.0.1}` is what ran) and `host.docker.internal` in `/etc/hosts`.
6. **Driver side**: the same `curl` calls `complete-run.sh` makes (heartbeat, `PUT upload` of `git archive HEAD`,
   `GET progress`, `GET results.tgz`, `POST collected`) against `http://127.0.0.1/tb/`.
7. **Egress**: real apt, PyPI, nodejs.org, npm, Playwright CDN, fonts (and, on `gw404`, GitHub, Maven Central, the
   FHIR registry) — i.e. the real setup, through the sandbox proxy with its CA installed.
8. Boot the same container **twice** with a different `tb-run-id` to see what the kept disk does (logs, `out/`, `parts/`).

Pass criteria for a rehearsal: door up and 401 on a bad key; `PRO6000-RUN-READY`; upload accepted; setup done with no
`TB-SETUP-FAILED`; both stand-ins report 0 × 404 and 0 × 401; `complete run PASSED` for the chosen `--only` parts;
`results.tgz` with `parts/`, `report/`, `vm.log`; the watchdog powers off within 60 s of `collected`; on the second
boot nothing is "kept (--resume)" from the first unless intended, and the first boot's log is not in the second's
`vm.log`. Add negative cases: a stand-in with a wrong served name (must fail before the parts, once H-02 is in),
`docker` returning errors (must be loud), no upload for 31 min (TB-NO-CODE then power-off), a silent run for 21 min
(watchdog). With `TB_BUCKET`, a `gcloud` shim that copies to a folder. Cost: 0; time: ~5 min per boot plus the parts.

Where: a `tests/rehearsal/` folder with the shims and `rehearse.sh`; run it in CI on the Ubuntu 24.04 image before
any change to `deploy/gcp/*` is merged, with `--only scenario-gateway scenario-it-dump` (3 min) and nightly with the
whole plan on a small hospital.

### 5.3 What was prototyped here

Everything above except `tb-serving-config` (the capture needs `docker inspect`) and the bucket shim, in
`/tmp/claude-0/review-cloudrun/proto/rehearsal/` (shims, `vllm_standin.py`, `dns_standin.py`, `prep.sh`,
`driver_side.sh`). Docker's daemon is not running in this sandbox; a private `dockerd --bridge=none --iptables=false
--storage-driver=vfs --data-root <scratch>` starts fine. Docker Hub is rate-limited here, so the Ubuntu 24.04 rootfs
came from `cdimage.ubuntu.com` (`docker import`). The container runs with `--network host --cap-add NET_ADMIN`; the
host venv and repo are mounted read-only for the stand-ins only. The VM script under test is the byte-identical copy of
`master`'s (`sha256 44f26cc5…`), metadata `tb-only="scenario-gateway scenario-emr-fhir scenario-it-dump"`,
`tb-done-grace=2`.

### 5.4 Results

| Boot | Source uploaded | What happened | What it shows |
| --- | --- | --- | --- |
| 1 | `master` 9e8ae30, 5,000 patients | Door up in < 10 s, wrong/no key → 401, 27 MB upload OK, READY after the stand-ins' 20 s "load", apt + uv venv + Node + Playwright + fonts done in 3 min (`== setup done`), then **the run crashed before any part: `FileNotFoundError: 'git'`** (`complete_run.git_head`), `TB-RUN-EXIT 1`, `results.tgz` = `vm.log` only, DONE, driver collected, **watchdog powered off 57 s later** (`TB-WATCHDOG done, results collected…` on the console). Also: ENOSPC during the Playwright install (sandbox disk), setup still "done". | M-08 (undeclared `git`), L-05, the collected→poweroff path works, the door fix of PR #52 works, PR #53's venv/Node fixes work on real Ubuntu 24.04. |
| 2 | `master`, same disk, 500 patients, `git` added to the base | Driver's progress tail showed **boot 1's traceback for the whole setup phase**; old `out/results.tgz` still present; setup again (venv rebuilt from the kept uv cache); run: `emr-fhir` 6/6 then **SCREEN "did not answer 7 of 7 note checks"**, `it-dump` 5/5, **gateway probe 1/3: judge and chart_facts `upstream_failed`** → `complete run FAILED: 12/16`; **judge stand-in: 117 × `404 for model 'gemma-4-26b-a4b-it' (serving 'local/gemma-4-26b-a4b-nvfp4')`, verifier 225 × 404 for `qwen3.5-9b`**; power-off after collected. | **Run 4's failure reproduced locally in 29 s of run time, for US$0.** M-01 (stale log and results). |
| 3 (attempts 3, 3b, 3c) | `gw404` c65abec (same VM script, i.e. without its maven step), same disk, new `tb-run-id`, 500 patients | Attempts 3 and 3b exposed two bugs in **my stand-in**, not in the VM path (a middleware consumed the request body → nginx 502; `X-TB-Prompt-*` headers were not forwarded → the repository stub answered 400); both fixed. **3c: 0 × 404, 0 × 401, 122 × HTTP 200 through nginx**; `scenario-gateway` **3/3 PASS** (A-01 and GW-02 answered); `emr-fhir` SCREEN ran with `judge_model: local/gemma-4-26b-a4b-nvfp4`, 12 model calls, funnel S0 124 → S4 4; **`scenario-it-dump: done earlier, kept (--resume)` from boot 2, under a different HEAD and a different `tb-run-id`**; verdict 18/19 — the one failure is `may_block: False` because the 54-case pair canary cannot pass against the deterministic stub (the reason now *names* the model: `gw404`'s canary change working); **watchdog powered off 58 s after `collected`**. | C-01 is fixed end to end through the real pins → gateway → nginx → served-name chain; **H-01 demonstrated** (a passed part carried into a new run); the harness is ready to be the pre-launch gate (5.2). |

Evidence kept in `/tmp/claude-0/review-cloudrun/proto/rehearsal/`: `run-master/{boot1,boot2}.console`, `driver1.log`,
`driver2.log`, `results1/`, `results2/` (boot 2's report with the `upstream_failed` rows), `run-gw404/boot3*.console`,
`driver3*.log`, `results3b/`, `results3c/`, `units/*.log` (stand-in 404 lines), `evidence/vm-run-log-all-boots.log`
(the one appended log of all five boots — M-01 in one file), `evidence/nginx-access.log` (342 × 404 then 122 × 200),
`evidence/POWEROFF` (every watchdog power-off with its caller), `shim.log`. The container, image and private dockerd
were removed afterwards to give the sandbox its disk back; `prep.sh` rebuilds the "VM" in about two minutes.

Harness limits worth knowing: the serving-record capture (`tb-serving-config`) was not rehearsed (it needs `docker
inspect`); the embed bench would need torch; `docker0` discovery ran its fallback branch (no dummy netdev in this
kernel); the stand-in answers with the stub's determinism, so the canary and model-quality checks are not meaningful
here — only plumbing, names, keys, setup, state and timing are. That is exactly the layer the four failures lived in.

## 6. Safety and privacy

* **Data to the VM**: `git archive HEAD trialbox` (tracked files only; `git ls-files` shows no `.env`, key, PEM or
  credential file; `.cache/`, `deploy/.env`, `.venv/` are ignored) and metadata. The VM generates its own synthetic
  hospital and fetches public datasets itself (MIMIC demo from PhysioNet, sha256-checked). Nothing from the laptop's
  `.cache` (which holds the real-note public corpora) is uploaded; if C-03 is fixed by shipping corpora, ship only the
  CC BY / NIST ones named in D-141 and nothing else from `.cache`.
* **Results back**: `parts/*.json`, screenshots of synthetic consoles, `vm.log`, the serving record — synthetic.
* **Keys**: the VM key is made with `secrets.token_urlsafe(32)` into a 0600 file under `.cache/` (ignored), passed to
  gcloud by file, to the VM as metadata, to curl by a header file (never argv). On the VM: `door-key` 0600,
  `nginx.conf` 0600, vLLM's `--api-key` on a docker command line (local root only), never recorded in the serving
  record (`SECRET_FLAGS`), no `set -x` anywhere (test). The four driver logs contain no `Bearer` token (grep).
  `TB_SA_KEY_FILE` is read by gcloud only. `--dry-run` prints the key *path*. OK.
* **Exposure**: the key crosses the public internet in cleartext HTTP and authorizes root-level code upload (M-06).
  Synthetic data, so a privacy non-issue; a VM-integrity issue.
* **Secrets never committed**: `.gitignore:9,15` (`deploy/.env`, `.cache/`); `plan.json`, `tb-key`, `src.tgz` all under
  `.cache/`.

## 7. Go/no-go checklist for the next paid launch

Gate = must be true before `complete-run.sh` without `--dry-run`.

**Code (gate)**
1. [ ] `gw404` merged (C-01) and `tests/unit/test_served_names.py` green on `master`.
2. [ ] C-02 settled one way: jars + JRE shipped/baked **or** `gw404`'s maven step **rehearsed to completion** (5.2).
3. [ ] C-03 settled: MedTxt and TREC fetched or shipped (`hosted-demo-startup.sh:39-45` pattern) **or** `public-*`,
   `scenario-public-medtxt`, `scenario-public-trec` removed from the VM plan and the estimate.
4. [ ] H-01: the VM's run directory keyed by run id (or `parts/` wiped on a new run id); the part JSON carries the HEAD.
5. [ ] H-02: both servers must be healthy **and** list exactly the two served names, and one authenticated call through
   `127.0.0.1:8080/{judge,verifier}/v1` must return 200, before `PRO6000-RUN-READY`; otherwise a loud marker and DONE.
6. [ ] M-08 pre-flight: `docker`, NVIDIA runtime, `git`, `/models` weights, disk ≥ 50 GB, else loud.
7. [ ] M-01: run log truncated per boot, `out/results.tgz` and `run-ended` removed at boot.
8. [ ] M-02: `--patients "$PATIENTS" --ocr tesseract` on the stub parts and the report; the VM's HEAD in the report.
9. [ ] H-03: an in-run heartbeat (per model call or per stage) **or** a run-phase idle limit of the part budget.
10. [ ] M-10: `results.tgz` re-packed after every part.

**Rehearsal (gate)**
11. [ ] The local rehearsal (5.2) passes on the exact commit to be launched, both boots, with `--only scenario-gateway
    scenario-emr-fhir scenario-it-dump hospital-ja` at 500 patients: 0 stand-in 404/401, `PASSED`, power-off on
    `collected`, nothing kept across boots.

**Operations (gate)**
12. [ ] Driver started detached (`setsid nohup … > log 2>&1 &`, or a terminal multiplexer), not in a 2-hour shell;
    or `--no-wait` plus `--collect` scheduled hourly. Confirm with `ps` after 5 minutes.
13. [ ] First launch bounded: `--only install prepare hospital-ja scenario-gateway scenario-emr-fhir --hours 3`
    (cap US$8.22); read `report.md`; only then the full plan.
14. [ ] `--vms 1` only until the GPU quota is raised (H-05); no `--provision`.
15. [ ] Private `CLOUDSDK_CONFIG`, `TB_SA_KEY_FILE` in place, `gc_probe` green; `tb-gpu-sim` `TERMINATED` before start.
16. [ ] Decide on `TB_BUCKET` (check the VM SA's storage scope read-only first) — recommended for results (H-04, M-06).

**After the run**
17. [ ] VM `TERMINATED` within 35 min of `COMPLETE-RUN-DONE` (console: `TB-WATCHDOG done…`); `report.md`'s HEAD equals
    the launched commit; no "kept (--resume)" line in `vm.log` unless this was a restart of the same run id.
18. [ ] Any `profile` row that says "direct (the gateway refused…" is a FAIL for the gateway chain, whatever the colour.

**Should fix soon (not gates)**: M-03 (crashed-part counting, profile fallback as a check), M-04 (phase limits),
M-05 (docker wait, door restart, self-check), M-06 (HTTPS or bucket, upload hash), M-07 (bucket path rehearsed),
M-09 (real weight pins or an honest label), M-11, L-01..L-06.
