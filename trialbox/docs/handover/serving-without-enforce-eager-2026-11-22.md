# H-80: the model servers run with CUDA graphs (`--enforce-eager` off)

**Reader:** the people who build TrialBox: the lane H lead, the integrator and the bench. Findings for builders, so
in one language.

- **Card:** H-80 (the integrator, 2026-11-22 10:09 UTC; not high-risk)
- **Date:** 2026-11-22
- **Decision:** [D-1359](../decisions/D-1359-the-model-servers-run-with-cuda-graphs.md)
- **Findings:** [`serving-without-enforce-eager-2026-11-22/findings.json`](serving-without-enforce-eager-2026-11-22/findings.json)
  (H80-01 to H80-03)
- **Tests:** `tests/unit/test_serving_without_eager.py`; `tests/unit/test_hardware_profiles.py` (one assertion)

## Pull request body (draft)

### What changes for a box

- The judge and the verifier start without `--enforce-eager` in every profile: `rtxpro6000`, `rtx5090`, `dgpu48`,
  `shared-quota`, `gb10` (compose) and the platform's `gpu-pair` manifest. The engine captures CUDA graphs at
  start: a longer start and some card memory for the graphs, inside each server's memory fraction. Nothing else of
  the command lines changes.
- The two runs that take a profile's records (`deploy/gcp/gpu-pro6000-run.sh`, `deploy/gcp/complete-run-vm.sh`)
  start their servers the same way, so their next records are of the new setting.
- The install is not refused: the vendor's record of the RTX PRO 6000 (taken eager) still passes
  `tools/serving_config.py measured`, which now prints on stderr that the record ran eager and that start time,
  memory and rate of the new setting are to be re-measured. Stdout and the exit code are unchanged.
- To put the flag back on a site: a compose override with the servers' `command` plus `--enforce-eager` (D-1359).

### Why

No record says why the flag was set; it came with the GPU simulation of 2026-11-06 and was copied into every
profile. The bench (#639, 2026-11-22 10:08 UTC): the same label on 91.5 % of 20,096 criteria eager against graphs,
and two eager runs agree on 91.5 % too, so the difference is run-to-run noise; first token 0.123 s against 0.020 s;
4 to 9 times the throughput at 8 to 64 in flight. The bench ran at a memory fraction of 0.9, not the profiles'.

### What awaits the bench, before the line (each on the new setting, per profile it holds)

1. Start to healthy, each server, from `docker compose up` (the compose health checks and the install's wait below).
2. Card memory at start (after the graphs' capture) and at peak, at the profile's own fractions (0.40 / 0.20 on the
   RTX PRO 6000; 0.81 / 0.81 with sleep on the 5090; 0.57 / 0.27 on dgpu48; 0.30 / 0.15 on gb10).
3. Throughput at the profile's sequences (16 on the RTX PRO 6000), and the 5090's wake time from sleep.
4. Label agreement against the eager record of the same set (done by the bench at 0.9; once more at the profile's
   fractions is what the integrator's "re-measured once" asks).

Records: the serving record (`deploy/gcp/capture-serving-config.sh` on the box, i.e.
`python3 tools/serving_config.py capture --container judge=... --container verifier=... --models-dir /models --out
serving_config.json`), checked by `python3 tools/serving_config.py measured rtxpro6000 <file>`; the card-memory peak
file of the same run; the qualification record (`python3 -m tools.trialbox eval qualify --box --profile rtxpro6000
...`); then `python3 tools/tier_record.py check` after the tier record's sources are moved to the new files.

## Where the flag was, and what was done

| Place | Whose | Done |
| --- | --- | --- |
| `deploy/docker-compose.{rtxpro6000,rtx5090,dgpu48,shared-quota,gb10}.yml`, judge and verifier | lane H | removed |
| `deploy/platform/components/gpu-pair/llm.yaml:84,133` | lane H | removed |
| `deploy/gcp/gpu-pro6000-run.sh:68` (takes the RTX PRO 6000 record) | lane H | removed |
| `deploy/gcp/complete-run-vm.sh:349` | lane H | removed |
| `deploy/gcp/box-install-run.sh:1475` (tuned mode filters the flag out) | lane H | kept; comment says it is a no-op since D-1359 |
| `deploy/gcp/gpu-sim-startup.sh:29,40` (the 2026-11-06 simulation) | lane H | kept: the script of a past run that the records of `eval/parity/` name |
| `deploy/measured/serving_config.rtxpro6000.json:18,100` (`enforce_eager: true`) | lane H | kept: what was measured; README notes it |
| `tools/serving_config.py` (parses the flag; `enforce_eager` is a required field) | lane H | kept; adds `setting_notes`, printed by `measured` on stderr |
| `tools/g_probes.py:15,350-353` (eager probe "not run") | lane G | not touched |
| `tests/rehearsal/b200/docker:49` (stand-in `docker inspect` output) | rehearsal | not touched (a stand-in's reply; question to the lead) |
| `eval/parity/*`, `docs/plan/measurements/*` records | records | not touched (past measurements) |
| tests: `test_serving_config.py`, `test_vllm_standin.py`, `test_images_lock.py`, `test_g4_g8_probes.py`, `test_three_low_follow_ups.py`, `test_dgpu48_draft.py`, `test_model_provenance.py`, `test_fallback_card_measured.py`, `test_hardware_profiles.py:116` | various | not touched: parser inputs and record fixtures, not the profiles |
| `tests/unit/test_hardware_profiles.py:78` | lane H | `in` to `not in`: it pinned this flag on the resident profiles, the card's subject |

## Assumptions made with eager on: to check on the bench

| File and line | Assumption |
| --- | --- |
| `deploy/docker-compose.rtxpro6000.yml:55`, `rtx5090.yml:74`, `dgpu48.yml:55`, `shared-quota.yml:47` | health check `start_period: 300s` for the model servers |
| `deploy/docker-compose.gb10.yml:71,119` | `start_period` 600 s and 900 s |
| `deploy/platform/components/gpu-pair/llm.yaml:93,142` | startup probe 40 x 30 s |
| `deploy/install.sh:869,872` | the install's wait (`tools/trialbox/bootwait.py`, else 900 s) |
| `deploy/gcp/box-install-run.sh:1460` | `--wait-timeout 900` |
| `deploy/gcp/gpu-pro6000-run.sh:74,79`; `deploy/gcp/complete-run-vm.sh:64` | 240 x 5 s per server; `HEALTH_WAIT_S=1200` |
| `deploy/docker-compose.rtx5090.yml:116,146` | 0.81 each with sleep: graphs of both on a 32 GB card |
| `deploy/docker-compose.dgpu48.yml:69,84`, `gb10.yml:59,90`, `rtxpro6000.yml:70,85` | the memory fractions |
| `models/tiers/rtxpro6000.json` `free_memory_at_peak_mib` 35299 | the peak of the eager run of 2026-11-08 |
| `models/tiers/*.json` `wake_seconds_p95` (declared), `startup_minutes` (not measured) | the 5090's wake and every start |
| `tools/ballast48.py`, `tools/measure48*` | start the stack by its compose file: they now measure graphs on |
| `tools/gpu_sizing.py:10` | a serving-engine allowance for CUDA graphs is already counted |

## Not done, not verified

- Nothing was launched; no GPU here. The start time, the memory and the rate of the new setting are not measured.
- Whether `measured` should refuse a record whose eager flag differs from the profile's: not done, since it would
  refuse the RTX PRO 6000 install until the bench's record lands (finding H80-01).
