# D-388 The perimeter is checked

- **Task:** T-604, the perimeter is checked (`docs/plan/28-master-plan-v6.md` §6.2.4)
- **PR:** this branch (`agent/T-604-perimeter`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** LLM-036, LLM-037 (b) and (d), LLM-038 (the PRODUCTION half), LLM-043; the `X-TB-Step` half of the D-142
  "not done" line
- **Builds on:** D-142 (`phi_on_box`), D-377 (T-108b, egress state and units), D-130 (`protect_reads`)

## Context

`phi_on_box` (D-142) lets D3 go to the perimeter endpoints without a study step, because on an on-prem box they are the
box itself. That was a label in `models/routing.yaml`: the address came from `TB_EP_SERVING_URL` and the others and was
never checked. With `EGRESS_EXTRA=gateway=<host>:443` the egress table opened the gateway to that host, so two lines in
`deploy/.env` sent every note prompt off the box while the audit said `zone: perimeter` (review LLM-036). The egress
rules resolved names only at apply time (LLM-037 b), `CLOUD_LLM_BASE_URL` opened the gateway to a host it never calls
(LLM-037 d), a service without `TB_GATEWAY_URL` still called `LLM_BASE_URL` itself (LLM-038), and the gateway's reads
needed no token (LLM-043).

## Decision

1. **A box address.** A perimeter endpoint is on the box when every address its host resolves to is loopback or a
   private range (`127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `::1`, `fc00::/7`). A one-label name
   that does not resolve is a compose service name (Docker's DNS answers it on the box networks only). A dotted name
   that does not resolve cannot be shown to be on the box and counts as off it. TEST-NET and public addresses are off
   the box. One function (`gateway.policy.perimeter_addresses`) serves the gateway and `doctor`.
2. **The gateway does not start** in PRODUCTION on topology A when a perimeter endpoint open in that environment is off
   the box (`SystemExit`, audited `llm.gateway.perimeter_refused`, phase `start`). Topology B is not checked: its
   perimeter is the tenant's serving router.
3. **Names are resolved again** while the gateway runs, at most every `TB_PERIMETER_RECHECK_S` seconds (default 60).
   When a name has moved off the box, every chat call is refused `perimeter_unverified` (HTTP 403, audited, phase
   `call`) and `/healthz` is 503 until it is back.
4. **Egress.** An `EGRESS_EXTRA` entry for the gateway is refused unless it is one of the routing table's open model
   endpoints (zone external or dev_public, open in `TB_ENV`, with a G5 record), host and port. `network.sh print`
   and `apply` exit 1 on it before Docker is asked anything. `CLOUD_LLM_BASE_URL` opens nothing (it stays a model host,
   so no other service may be given it). `network.sh watch` applies the table at once and again whenever a container
   of the stack starts (`docker events`); `trialbox-egress-watch.service` runs it, and the two-minute refresh timer of
   D-377 stays as the fallback.
5. **The client.** In PRODUCTION `LlmClient.from_config` refuses to build without `TB_GATEWAY_URL`. A call made for
   a job sends the job id as `X-TB-Step` (unless `TB_STEP_ID` names a step), so a gateway with a step confirmer has
   the step to check.
6. **Reads need the token.** The gateway app is built with `protect_reads`; `tb_llm.GatewayClient` sends the service
   token on `GET /v1/models`.
7. **doctor** has one new check, `perimeter_addresses`: each perimeter endpoint's host and the addresses it resolves to
   now; FAIL in PRODUCTION on topology A when one is off the box, WARN elsewhere.

## Not done

* LLM-037 (c): the services on `egress-net` can still resolve outside names (a resolver that answers the allowlist
  only).
* LLM-038 second half: the cloud branch of `LlmClient` is still there for DEV and TEST, and `verifier_client` in the
  orchestrator can still build a direct verifier from `LLM_VERIFIER_BASE_URL`.
* LLM-2 proper: the gateway has no step confirmer wired in the compose stack; the header is sent, not yet checked.
