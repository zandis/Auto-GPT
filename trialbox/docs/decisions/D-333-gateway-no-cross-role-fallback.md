# D-333 The gateway never answers one role with another role's model

- **Task:** T-601 (wave 1 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2.4)
- **PR:** this branch (`agent/T-601-gateway-no-fallback`)
- **Date:** 2026-11-10
- **Status:** accepted
- **Closes:** deep review LLM-002 (gateway half), LLM-003, LLM-004 (gateway half), LLM-006 (in part), CR-002 (gateway
  half); D-142 "not done" item 1 (the doctor and the judge refusal). Builds on D-276, which it does not change.

## Context

D-276 stopped the `patient` roles from falling back to another alias and made the pair compare the builds that
answered. Three gaps were left (deep review LLM-003). Every other route still fell back on any upstream error, with
no retry of the same build first, so a timeout, a 400 (prompt over the context) or a 404 (a served name the server
does not have) quietly gave the call to the next build. The caller was not told, except in the body's `tb.alias`.
And the D-276 rule kept "the first alias left after the filters": a filter that dropped the judge build (an endpoint
not allowed in this environment, a perimeter-only call) left the verifier build first, and it then answered the
judge.

## Decision

1. **A per-route flag, `none` unless a route says `any`.** `fallback: none | any` on each route of
   `models/routing.yaml`; left out, it is `none` (it was `any` for a route that did not serve only patient roles).
   The shipped file says `any` on `converse`, `documents-d1`, `protocol`, `mapping`, `aggregate` and `ops`, and
   `none` on every other route. A route that serves a patient role may not say `any` (D-276), and a patient role
   never falls back on any route.
2. **The declared first build.** A call that may not fall back gets the alias it named, or the route's first
   *declared* build, never the first one left after the filters. If that build is filtered out, the call is
   refused (`no_eligible_build`).
3. **One retry on the same build.** A transport error (connection refused, reset) or an HTTP 5xx is tried once more
   on the same build after `TB_GATEWAY_RETRY_DELAY_S` (default 0.5 s). A timeout is not tried again: the server may
   still be working on it, and a person may be waiting (interactive roles answer `model_busy`).
4. **No fallback on 400 or 404.** An upstream 4xx other than 408 and 429 ends the call: no retry and no other build,
   on every route. A 400 or 413 whose text says the prompt is over the context is `prompt_too_long` (HTTP 413);
   any other is `upstream_failed` (HTTP 502), naming the status and, for a 404, the served name sent.
5. **The response says who answered.** The body's `tb` adds `expected_alias`, `fallbacks` and `retries` next to
   `build_id` and `build_sha`; headers `X-TB-Build-Id`, `X-TB-Build-Sha`, `X-TB-Fallbacks` and `X-TB-Retries`. A
   refusal carries `X-TB-Fallbacks` and `X-TB-Retries` too. The audit record adds `retries` and `expected_alias`.
6. **`tb_llm` raises on an unexpected alias.** `GatewayClient` raises `GatewayUnexpectedAlias` (a `GatewayError`)
   when an answer comes from another alias than the one the call named (always), when another build answered after
   the expected one failed (`tb.fallbacks`, `X-TB-Fallbacks`, or `tb.alias` other than `tb.expected_alias`) unless
   the client was made with `allow_fallback=True`, or when the answer does not say which alias gave it. The
   `tb_common.llm` shim turns it into `LlmError`, which the note judge counts as `model_down`, a failure.
7. **The note judge fails closed on an answer with no build.** Through the gateway every answer names its build
   (`tb.build_sha`); one that does not cannot be compared by the pair, so it is no answer (`model_down`).
8. **`trialbox doctor` check `judge_route`.** The gateway built from the box's settings (routing file, registry with
   the site pins, `TB_ENV`, `TB_TOPOLOGY`, `TB_PROFILE`, no step confirmer, as compose runs it) takes one synthetic
   judge call as the orchestrator sends it, and one verifier call when `TB_GATEWAY_VERIFIER_MODEL` is set, against a
   stand-in model server. FAIL in VALIDATION and PRODUCTION (WARN in DEV and TEST, a box being set up) when it would
   refuse either, naming the refusal code, or when another alias answers. PASS when the judge does not use the
   gateway.

## Consequences

* With the judge's server down, the pair now gives `unknown` / `model_down` with a counted failure through three
  separate layers (the gateway's rule, `tb_llm`'s alias check, the pair's build comparison). The tests remove each
  layer in turn; any one alone is enough, and with all three removed the pair reports agreement (the defect).
* A caller of a route that says `any` (protocol extraction, drafting, the front desk) now gets an error, not another
  build's answer, unless it passes `allow_fallback=True`. No shipped caller does. The front desk's engine already
  treats a gateway error as "model not available".
* In DEV and TEST, a stub that is down is an error: the `dev-stub` route no longer falls to the on-box build.
* `shadow` and `bakeoff` no longer fall back: a shadow or bake-off answer is the named build's or none.

## Open

* The role `degraded:` column (LLM-006) is still read by no code: this decision makes a failed build an error for
  the caller to handle, but the gateway does not yet return the role's degraded mode with the refusal.
* The gateway does not measure prompts against the build's context before dispatch (T-603): it only maps the
  server's own 400 to `prompt_too_long`.
* The gateway cannot tell a judge-role call that names the verifier's alias on purpose (the v1 verifier asks role
  `judge` with `model: v-verifier`) from a judge client misnamed as the verifier (`TB_GATEWAY_MODEL=v-verifier`).
  The doctor's `note_block` check and the pair's build comparison catch the second; binding roles to aliases
  (`judge` to the judge build, `second_opinion` to the verifier) needs the v1 verifier to ask as `second_opinion`.
