# D-839 the PoC brings the real pair up on a plain GPU VM in one command

- **Task:** I-9 of the independent examination (2026-11-15, #639; the owner asked for it)
- **PR:** this branch (`agent/I-9-the-poc-brings-up-the-real-pair`)
- **Date:** 2026-11-15
- **Status:** accepted
- **Builds on:** D-142 (pin_model --install), D-738 (--resolve), D-115 (the pair canary)

## Decision

1. `TB_LLM_MODE=gpu deploy/poc.sh` checks the host before it writes or starts anything: a GPU, Docker's nvidia
   runtime, the profile (rtxpro6000 or gb10: deploy/gpu_profile.sh, or TB_GPU_PROFILE), the two model folders and the
   chat template the profile's overlay names, free disk (TB_POC_MIN_FREE_GB, 30). One line per check.
2. It pins the pair from the weights (`pin_model --install`, then `--resolve`), starts the stack with the profile's
   shipped overlay (`docker-compose.<profile>.yml`), runs the 54-case pair canary inside the orchestrator, and prints
   a heartbeat through the hashing, the start and the canary. G-1 (`tools.complete_run --only chat-template`) needs
   the model server's image and is printed as the next step. No bundle, signature, seal or hardening.
3. `rand` no longer ends the script on a first run: under pipefail `X="$(rand)"` exited 141 when tr was stopped by the
   closed pipe.

## Test

`tests/unit/test_poc_gpu.py` with stand-ins for docker and nvidia-smi on a root of its own: before, a first run ended
at exit 141 and none of the GPU steps existed; after, all pass. Lane G runs it on the VM.
