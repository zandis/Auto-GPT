# D-1462 The judge and verifier servers start without the prefix cache unless the box chooses it (H-146)

- **Task:** lane H, card H-146 (the integrator's 7163554019 on #1504) · **Date:** 2026-11-25
- **Status:** proposed (row reserved; the integrator flips it when merged)
- **Builds on:** D-389 (every `TB_*` setting declared once), D-1460's lane H block
- **Amends:** spec 04 (`spec/v4/04_architecture_llm_hermes.md`, "Prefix caching is on") and LLM-23, which
  assume the cache is on: the shipped default is now off (review 1514-4)

## Decision

1. Every GPU overlay's judge and verifier server command (`deploy/docker-compose.yml`, `.gb10`, `.rtx5090`,
   `.rtxpro6000`, `.dgpu48`, `.shared-quota`) carries one line,
   `--${TB_LLM_PREFIX_CACHING:-no-enable}-prefix-caching`. By default it renders `--no-enable-prefix-caching`.
2. `TB_LLM_PREFIX_CACHING` is a declared setting (`libs/tb_common/config.py`, default `no-enable`) in
   `deploy/.env`. Compose can only tell a set variable from an unset one, so the value is the flag's own first
   word. Absent, empty or `no-enable` means off. `enable` means on, the only explicit choice. Any other value
   renders an argument the model server refuses, so it does not start: never a silent on, never a silent off.
3. `trialbox doctor` has a `prefix_cache` line. Off is a PASS. On is a standing WARN ("runs may differ"). Another
   value is a FAIL. Given the rendered compose (`--compose-config`), a server whose command does not carry the flag
   the setting names is a FAIL.
4. The runbook (page 19, last section; page 17 for the platform) says how to choose the cache and that runs may
   then differ.
5. The cluster manifests (`deploy/platform/components/gpu-pair/llm.yaml`, both servers) carry
   `--$(TB_LLM_PREFIX_CACHING)-prefix-caching`, filled from ConfigMap `trialbox-serving`; each overlay's
   `serving.env` sets `no-enable`, a site overlay merges `enable` to choose the cache. A missing key leaves the
   argument as written, which the server refuses (the integrator's go on H146-02, 7165504439).
6. Sampling, prompts and limits are not changed. The bench-only second engine's overlay
   (`docker-compose.serving-second.yml`) replaces the command with another engine's and is not covered here.

## Why

On the integrator's bench copy of the judge, the same 58 extraction calls gave 9 and then 4 agreeing with the cache
on. With `--no-enable-prefix-caching` as the only change, four runs gave four identical results. A screening result
that changes from run to run on the same chart cannot be reviewed or reproduced. What the cache costs in time is
measured by the integrator on the bench copy, not by this card.

## Tests

`tests/unit/test_no_prefix_cache_h146.py`: the compose the product renders (`tools.serving_profile.compose_argv`,
deploy/.env and its `COMPOSE_FILE`) for every GPU stack, by default and by the explicit choice; the declared default;
doctor's line; each cluster overlay's servers with `$(VAR)` filled from their ConfigMaps.
`tests/unit/test_trialbox_doctor.py` names the new check.
