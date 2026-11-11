# D-437 The gateway routes on the verified caller; the model key in a secret file and in `secrets rotate`

- **Task:** T-212b (`docs/plan/28-master-plan-v6.md` §6.2)
- **PR:** this branch (`agent/T-212b-gateway-verified-caller`)
- **Date:** 2026-11-11
- **Status:** proposed (merges on green CI)
- **Closes:** CR-040, LLM-039 (the parts left after PR #68 / D-177)
- **Builds on:** D-128 / D-138 (one token per service, `tb_common.service_auth`), D-142 (`phi_on_box`), D-177 (the
  model key and model-guard), D-116 (the one-GPU swap)

## Decision

1. **The caller comes from the token.** `X-TB-Caller` is a claim. The service the request's
   `X-TB-Service-Token` identifies (`request.state.tb_caller`, set by `make_app` through
   `service_auth.authorize`) must be allowed to make that claim. `models/routing.yaml` gains `service_callers`: the
   caller names each verified service may use (`orchestrator`: `orchestrator`, `matching`; `criteria-compiler`;
   `doc-parser`; `console`: `converse-native`; `operator`, the administrator's host token: any). A claim outside
   the map is refused `caller_unverified` (HTTP 403) and audited (`llm.gateway.refuse`, with the verified
   service). The role and purpose rights stay on the caller entry, so they are now bound to the verified service:
   a doc-parser token cannot use role `judge`, neither as `doc-parser` (`role_not_allowed`) nor by claiming
   `orchestrator` or `testbench` (`caller_unverified`).
2. **No identity, no claim, outside DEV and TEST.** Where the gateway cannot tell which service called, the header
   is believed in DEV and TEST only (synthetic data). The old shared token (`legacy`) is believed only when the
   gateway's own environment is DEV or TEST; a call with no token at all reaches the gateway only where the token
   layer runs open (`TB_ENV` DEV or TEST, as `service_auth` decides). Everywhere else such a call is refused
   `caller_unverified`: run `trialbox secrets init` / `rotate`. A call made inside the gateway's own process
   (`trialbox doctor`'s judge route check) has no network boundary and is not bound.
3. **The GPU swap belongs to its owners.** `POST /v1/serving/activate` and `/v1/serving/release` are allowed only to
   the verified services in `serving_control` (`orchestrator`, `operator`), with a caller they may claim that may
   use the judge role. A refusal is audited (`llm.gateway.swap_refused`).
4. **The model key is a secret file.** `trialbox secrets init` writes the key of the on-box model servers to
   `deploy/secrets/model/llm.key` (0600, the service user; taken over from `deploy/.env` when the box has one).
   The secrets overlay mounts it as a compose secret into the gateway and model-guard only
   (`TB_LLM_API_KEY_FILE`, read before the environment variable) and clears `TB_LLM_API_KEY` in every container.
5. **The model key rotates.** `trialbox secrets rotate --service model` (and a rotation of everything) writes a new
   key, puts it where the vLLM servers read it, and recreates the model servers, model-guard and the gateway in
   one command. The old key is refused from then on; the new one works.

## Consequences

- A new service that calls the gateway needs a `service_callers` row (and a `service_auth.CALLERS` entry); a test
  holds the two together.
- The legacy shared token no longer reaches a model outside DEV and TEST.
- Every gateway audit record carries `service` (the verified service, or empty).
- `trialbox update` makes the key file from `deploy/.env` on a box with per-service tokens, because the compose
  secret needs its file. The network sheet lists the key file.

## Open

- The vLLM servers still read the key from `deploy/.env` (compose interpolation into `VLLM_API_KEY`), and so do the
  host tools (`doctor --serving`, `noisy_neighbour`, `update`). `secrets` keeps that copy equal to the file. Moving
  them off `.env` (an `env_file` per vLLM service in every GPU overlay) is a follow-up.
- The box rehearsal's "the gateway loses the key" drill (`tools/rehearse_box/box.sh`) empties `TB_LLM_API_KEY` in
  `deploy/.env`; with the secrets overlay the gateway now reads the file, so the drill must empty the file instead.
  Not changed here (it runs only on a rehearsal box).
