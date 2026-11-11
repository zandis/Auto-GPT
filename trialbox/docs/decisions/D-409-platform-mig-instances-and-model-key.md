# D-409 The shared-quota profile on two MIG instances, its pins, and the model key on the platform

- **Task:** T-113b (wave 1 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2.4; the follow-up to PR #85, T-113)
- **PR:** this branch (`agent/T-113b-platform-followup`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Builds on:** D-142 (install pins the profile's pair), D-177 (model-guard and the model key), D-211 (the
  platform form), D-392 (model provenance, the judge's chat template), D-311 (no development gates)
- **Closes:** LLM-011, LLM-027, LLM-028, OPS-067 and the rest of CR-084 (deep review of 2026-11-10)

## Context

PR #85 put TrialBox on a hospital platform (Kubernetes manifests, `doctor --platform`). The deep review found five
gaps. The B200 had no profile, no registry build and no pin step: `gpu_profile.sh` printed `default` for it and
`pin_model --install` had no pair (LLM-011). The pair needs two GPU devices in Kubernetes, one per container, so
the request to CGMH must be two MIG instances, not "a dedicated MIG partition"; a time-slice or MPS share gives no
memory isolation and must be refused (LLM-027, OPS-067). The platform manifests started vLLM with no key and no
model-guard, so the NetworkPolicy alone stood between other pods and the model servers (LLM-028).

## Decision

1. **The B200.** `deploy/gpu_profile.sh` prints `shared-quota` for a card with MIG on (as before) and
   `b200-no-mig` for a B200 or GB200 with MIG off (before the arm64 rule, so a GB200 is never a GB10). `install.sh`
   refuses both with a sentence that says what to do: a B200 serves TrialBox only as two MIG instances on the
   platform form.
2. **Builds and pins.** `models/registry.yaml` has `gemma-4-26b-a4b-it-sharedquota` (judge),
   `qwen3.5-9b-sharedquota` (verifier) and `gemma-4-26b-a4b-it-frontdesk-sharedquota`: the same expected weights
   and provenance as every other profile, `context_length: null` until measured on the instances.
   `tools/pin_model.py` `PROFILE_PAIRS["shared-quota"]` names the pair. The shared-quota overlay has the job
   `trialbox-pin` (`pin_model --install shared-quota` from the `models-data` claim into a new `model-pins` claim);
   the gateway reads its override from that claim (it no longer reads the optional ConfigMap `trialbox-site`) and is
   restarted after the job. The interim-cloud overlay has no pin job until it has builds of its own.
3. **The serving rule keyed on the MIG profile.** `tools/serving_config.py` has a `shared-quota` rule: each server
   on its own MIG instance (`gpu_devices` one `MIG-` UUID, the two different), each naming its `mig_profile`
   (captured from `nvidia-smi -L` and the container's device request), the card's MIG mode on, and each server's
   context at least `MIG_MIN_LEN[profile]`: 8k on a 23 GB class instance, 16k on 45 GB class, 32k on 90 GB and
   larger (the same steps as the 32 GB, GB10 and 96 GB profiles). These are minimums the profile asks for, not
   measured values; the record of T-114 says what the instances reach. `TB_MIG_PROFILE` is one profile or
   `judge=<profile>,verifier=<profile>`; `doctor --platform` `serving_record` checks the record against it.
4. **"MIG instance, not time-sliced" (`mig_instances`).** A GPU check of `doctor --platform`. It fails on a shared
   resource name (`nvidia.com/gpu.shared`, MPS), a node labelled `nvidia.com/gpu.sharing-strategy=time-slicing|mps`
   or `nvidia.com/gpu.replicas` above 1, a declaration `TB_PLATFORM_GPU_SHARING=time-slicing|mps`, fewer instances
   on the nodes than the pair asks for, or a pair pod the scheduler cannot place for `Insufficient nvidia.com/...`
   (one slice: the message says so and says to ask for two). In `shared-quota` MIG must be shown by the resource
   name, a node's `nvidia.com/mig.strategy` label, or the declaration `TB_PLATFORM_GPU_SHARING=mig` with
   `TB_PLATFORM_GPU_EVIDENCE` (the MIG configuration dump). Reading Nodes needs a cluster-scoped grant, so it is the
   optional `components/node-read`; without it the scheduling state and the declaration are the evidence.
5. **"Server refuses a call without the key" (`model_key`).** The gpu-pair component runs model-guard in front of
   both servers as on the appliance: the Services `llm-service` and `llm-verifier` select model-guard, vLLM sits
   behind `llm-service-vllm` and `llm-verifier-vllm`, and only model-guard reaches it (NetworkPolicies). The key is
   the Secret `trialbox-model-key`; the two servers, model-guard and the gateway read it, nothing else. The check
   fails when a server has no key or a plain one, model-guard is missing, a Service goes around it, the gateway has
   no key, they read different keys or another workload holds it; in the cluster it calls model-guard without the
   key and with another key (401 required) and on vLLM's unkeyed `/invocations` (404 required). It needs no GPU, so
   it runs with `--no-gpu` too. The doctor holds no key; the call with the key is the canary's. The compose form
   (`docker-compose.shared-quota.yml`) now keeps both servers on `model-backend-net` with the key, behind the base
   file's model-guard. The judge on the platform gets `--chat-template` (D-392).
6. **Stand-in devices.** A test cluster has no GPU. `TB_PLATFORM_GPU_STANDIN=1` (refused in VALIDATION and
   PRODUCTION, like `--no-gpu`) says the devices are advertised by hand: `gpu_serving`, `mig_instances` and
   `model_key` run; `serving_record` and `canary` are `skipped: stand-in device`. `deploy/platform/kind-check.sh`
   advertises `SLICES` (1 or 2) devices on the kind node with a B200 MIG node's labels and runs the vLLM stand-in
   of `tests/rehearsal` behind model-guard: two pass, one fails `mig_instances` with the scheduler's reason.
7. **The documents.** The IT and security pack (EN, JA, zh-TW) and the site survey (question 51) ask for two MIG
   instances, one per model (about 45 GB class and 23 GB class), never a time-slice or MPS share. RUNBOOK §17 has
   the model key, the pin job, the record rule and the kind check with `SLICES`.

## Consequences

- A site applies one more Secret (`trialbox-model-key`) and restarts the gateway after the pin job.
- The request to CGMH (owner action, LLM-027) is now the two instances; the pack and survey say so.
- Not done here: the real kind run (no Docker or kind on the build machine; listed as remaining in the PR), the
  measured shared-quota record and the B200 rows of `tools/gpu_sizing.py` (T-114), the challenger's per-profile
  build, day-2 jobs on the platform (T-633).
