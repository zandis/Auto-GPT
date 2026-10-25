# Hermes advisories (spec v4 §9.5, HER-19)

Reviewed at each upgrade. Pin: **v0.22.2**, commit `d923a5eb487a17c0a68801bba9ef0f56c81040a8`, image index
`sha256:36099926da316742423544e055d4734777105ffe6341873af5459b957d0c2919` (see `hermes.lock`).

## Pin decision (2026-10-25)

v0.22.2 is the spec's initial pin and is above the floor v0.21.6. It was cut from `release/0.22.1` and fixes the
v0.22.1 wrong-commit build; both platform images were checked file by file against the tagged commit.

v0.22.5 (`bf0203a794a07aac3ff764972ab9087baa4e4f4e`, 2026-10-22) was considered and **not** taken:

* It is not a patch release. `git log v0.22.2..v0.22.5` has 3,291 commits, including new surfaces (connector sign-in,
  guest hand-off, desktop plugin updates). Taking it would move the reviewed hardening baseline without a §9.12 review.
* No Hermes-code advisory published against v0.22.2 applies to TrialBox. The fixes after v0.22.2 are either in
  surfaces TrialBox removes (dashboard plugin gate) or in third-party dependencies whose exploit paths the
  configuration closes (table below).
* v0.22.5 is the next upgrade candidate. It needs the full §9.12 pass: contract test, configuration diff,
  E3/E4 and image verification.

GitHub's release and advisory pages were not reachable from the build container (the session's GitHub access is
limited to its own repositories). The evidence below comes from the git history of the tags themselves. Before
production, re-check https://github.com/NousResearch/hermes-agent/security/advisories (HER-34).

## Advisories published after the pin that touch v0.22.2

| Advisory | Where | Fixed in | TrialBox posture |
| --- | --- | --- | --- |
| GHSA-mcfc-hp25-cjv7 (PLG-8/PLG-9, commit `876e37c077`) | dashboard plugin gate, secondary profiles | after v0.22.2 (in v0.22.5) | dashboard never started; `multiplex_profiles: false`; one profile per container; port 9119 not published |
| GHSA-8g5g-8vmr-9782, GHSA-332p-7hrc-92wf, GHSA-w889-685w-c8fh (critical) + 25 others | Pillow 12.3.0 (image decode/encode) | Pillow 13.0.0 (v0.22.5) | vision, browser, image_gen, computer_use toolsets off; relay sends text only (no `media_urls`); MCP results are JSON |
| GHSA-6q48-6c7w-9gw2 (critical) | certifi 2026.5.20 trusts compromised emSign roots | certifi 2026.10.19 (v0.22.5) | no public egress (network policy); MCP and relay use `ssl_verify` / the internal CA; the gateway is plain HTTP inside the namespace |
| GHSA-9xw5-w5jj-pvcg + 7 (high) | aiohttp 3.14.3 (messaging extras) | aiohttp 3.14.5 (v0.22.5) | no messaging platform adapters enabled; no aiohttp listener exposed |
| GHSA-xpv3-w29h-x7cv (medium) | oauthlib 3.3.1 | 4.0.0 (v0.22.5) | no OAuth providers or MCP OAuth configured; `auth.adopt_external_logins: false` |
| npm advisories (vite, webpack-dev-middleware, simple-git, tinypool, …) | web/desktop/website build tooling | v0.22.5 | not on the runtime path (no dashboard/web UI/desktop) |
| shai-hulud-2026-05 (in-tree catalog) | mistralai 2.4.6 | n/a (2.4.6 not in v0.22.2's lock) | not affected |

## Historic advisories (spec §9.5 table)

Everything in the §9.5 table is fixed at or below the floor, or made inapplicable by the configuration (catalogue,
webhooks, dashboard, API server, adapters, terminal/file/code tools off; signed read-only skills; manual approvals).

## Spec settings the release cannot express (S1-11)

* `delegation.max_spawn_depth: 0`: v0.22.2 floors it at 1 (`_MIN_SPAWN_DEPTH = 1`). The control is the disabled
  `delegation` toolset (§9.6 item 12 already says so).
* MCP `catalogue: false`: there is no remote MCP catalogue setting in this release. The catalogue is the in-repo
  `optional-mcps/` list, used only by `hermes mcp add`. The control is the read-only managed config.
* Per-call identity assertion to the front door (HER-15): the MCP client sends only static or profile headers
  (`identity_header`), never a per-conversation one. **Implemented route (S1-11 serving path):** `tb_policy_audit`
  answers an allowed `pre_tool_call` with a `modify` directive that sets `_tb_identity: {assertion, conv}` in the
  call's arguments (the current turn's relay-minted ES256 assertion, kept in the plugins' shared context by
  `tb_relay_adapter.inject`); v0.22.2 merges `modify` args before dispatch and hands them to `session.call_tool`
  unchanged (contract test checks the branch). `frontdoor_mcp.listener` strips the key before validation, so the tool
  contract and the audited argument hash are unchanged, and the server refuses and alarms any call without a valid
  assertion bound to the conversation, whatever the client certificate. The plugin overwrites the key on every call,
  so a value the model writes is discarded; the key is not in any tool schema and was not found in the model context
  of the live run (gateway traces). `tools/list` is answered on the mTLS certificate alone (CN `hermes` or
  `channel-relay`): the client lists tools when it connects, before any conversation exists.
  **Residual risk** (as §9.4 states): code running inside Hermes can read the shared context and replay another
  active conversation's assertion within its 5-minute life (T0/T1 at that user's permission; aggregates still
  accountant-checked). Prompt injection alone cannot: the model never sees an assertion. Tightening options: a
  relay-side forwarder that holds assertions out of Hermes, or binding assertions to the live turn at the front door.
* Model streaming: tb-gateway answers chat completions as JSON, never SSE, so the profiles set `model.streaming:
  false`; `display.interim_assistant_messages: false` keeps one reply per turn (channel-relay sends the last one).
* Inbound authorisation: the `tb_relay` platform is registered `trusted_inbound` (channel-relay authenticated the
  sender; the directory export is the allowlist, HER-16), so Hermes' own allowlists and pairing are not used;
  `pre_gateway_dispatch` still drops anything that is not an adapter-injected, checked envelope, and the inject
  listener accepts only the `channel-relay` client certificate.
* Hermes' gateway log records a preview of each inbound (tokenised) message (`inbound message: ... msg='...'`) under
  `/opt/data/logs`; the volume's encryption and the 30-day retention (HER-24) cover it.
* Approvals `deny: ["*"]` matches shell-command patterns (`approvals.deny`), not tool names. With terminal off it
  only backs up the disabled toolsets.
* HER-21 OTel spans and the hash-chained ledger over mTLS are not wired. Audit events go to the logger as JSON lines.
