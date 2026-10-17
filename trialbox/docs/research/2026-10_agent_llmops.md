# TrialBox v4: Agent Shell (Hermes Agent) and the LLM Platform / LLMOps Layer

*Research date: 2026-10-17. This document supersedes and extends an earlier Hermes note written the same day and carries its still-valid findings forward here. Claims link to primary sources where possible.*

*Markers: **[Unverified]** means I found only a secondary source, the sources conflict, or I could not confirm the claim on 2026-10-17. **[Prior notes]** means the value comes from the earlier notes file and was not re-checked in this pass.*

*Method note: during this pass the session's web-search budget ran out. Some framework version numbers (vLLM, Temporal, Pydantic AI, LangGraph, OpenAI Agents SDK, Claude Agent SDK, Letta) are therefore carried over from the earlier notes, and they are marked [Prior notes]. The Hermes, MCP, cloud-residency and regulatory facts below were re-fetched from primary pages on 2026-10-17 unless marked otherwise.*

---

## 0. What changed since the earlier notes (delta)

- **Hermes hooks:** there are four hook systems, not one. `pre_tool_call` can block, approve or modify a call, **block beats approve**, and it fails closed. `pre_gateway_dispatch` is *unbounded*, and `post_gateway_admission` fails *open* (§A2).
- **Hermes CVEs:** the list now includes **CVE-2026-82021** (Critical, a supply-chain issue in the MCP catalogue) and **CVE-2026-14628** (a webhook path traversal with a public exploit), along with several other 2026 advisories (§A5).
- **Delegation and cron:** child agents cannot use memory, send messages or schedule cron jobs. Scheduled agents cannot manage cron by default (`cron.allow_agent_scheduling: false`).
- **MCP 2026-07-28:** the spec is now stateless, deprecates DCR in favour of CIMD, and deprecates sampling (§B12).
- **Gateways:** LiteLLM's PyPI packages were compromised in March 2026, Envoy AI Gateway reached 1.0, and Palo Alto Networks is buying Portkey (§B2).
- **Residency:** this was not covered before. In Taipei, Bedrock serves Claude only through Global routing, and Azure Taiwan North is not GA (§B13).

---

# PART A: Hermes Agent as TrialBox's conversational front end and agent shell

## A1. Snapshot

Hermes Agent (Nous Research, MIT licence) is a long-running, server-resident, "self-improving" agent. You can reach it from a CLI, TUI or desktop app, from an editor via ACP, through an OpenAI-compatible API server, and from more than 20 messaging platforms ([repo](https://github.com/NousResearch/hermes-agent), [docs](https://hermes-agent.nousresearch.com/docs/)).

**Current state (2026-10-17):**
- **Latest release:** v0.22.2 (2026-10-15).
- **Recent releases:**
  - **v0.22.0 "Threshold"** (2026-10-13) added stable SemVer channels, signed desktop packages, a catalogue of about 600 reviewed plugins, local models through llama.cpp, and memory providers split out into plugins.
  - **v0.22.1** was built from the wrong commit and replaced a day later.
  - **v0.21.6** (2026-10-08) fixed dashboard auth bypasses, git filter-program execution from untrusted repos, and an **email allowlist bypass via a crafted display name**.
  ([releases](https://github.com/NousResearch/hermes-agent/releases))
- **Pace:** releases arrive about weekly, and hotfixes are frequent.
- **Scale [Prior notes]:** about 254k stars and about 25k tests.

**What this means for TrialBox:** the project has strong functionality and a large community, but high churn and a non-trivial vulnerability history (§A5). It belongs *outside* the validated core, behind a narrow, audited interface.

## A2. Architecture (current)

Sources: the [architecture guide](https://hermes-agent.nousresearch.com/docs/developer-guide/architecture) and the feature pages cited in each row.

| Subsystem | What it does | Notes for TrialBox |
|---|---|---|
| **Agent loop** | One `AIAgent` class serves the CLI, gateway, cron, ACP and API server. It speaks `chat_completions`, `codex_responses` or `anthropic_messages`. | Point it at the LLM gateway's OpenAI-compatible URL. |
| **Gateway** | Authorises the user, resolves the session, and runs one agent per conversation. More than 25 platform adapters, including Email, Teams, Slack and LINE. | Default deny: `<PLATFORM>_ALLOWED_USERS` and `unauthorized_dm_behavior` ([security](https://hermes-agent.nousresearch.com/docs/user-guide/security)). |
| **Tools / toolsets** | More than 70 tools in about 28 toolsets. Turn them off with `agent.disabled_toolsets` (global) or `platform_toolsets` (per platform) ([configuration](https://hermes-agent.nousresearch.com/docs/user-guide/configuration)). | Keep only the front-door MCP toolset. |
| **MCP client** | `mcp_servers.<name>` over stdio or HTTP. Per-server `tools.include`/`exclude` globs (include wins), OAuth, **mTLS**, `identity_header`. **Sampling and elicitation are on by default** ([MCP](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp)). | Turn sampling and elicitation off. Use mTLS. |
| **MCP server mode** | `hermes mcp serve` (stdio only) exposes 10 tools, including `messages_send` and `events_poll`. | Lets the **workflow engine deliver notifications through Hermes channels**. |
| **API server** | `/v1/chat/completions`, `/v1/responses`, and `/v1/runs` with an `/approval` endpoint. A bearer key is required. It runs with the full toolset, "including terminal commands" ([API server](https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server)). | Disable it. Never publish port 8642. |
| **Skills** | `SKILL.md` files. The agent creates and patches its own skills. Controls: `skills.write_approval`, `guard_agent_created` and `auto_load` ([skills](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills)). | Treat skills as reviewed procedures (§A8.1). |
| **Memory** | `MEMORY.md` and `USER.md` snapshots, plus transcripts in `state.db`. External providers became plugins in v0.22.0 ([memory](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory)). | `state.db` holds PHI whenever users type PHI. Encrypt it and set retention. |
| **Cron** | `jobs.json` and `executions.db`. Each run is a fresh agent with per-job `enabled_toolsets`. `cron.allow_agent_scheduling` defaults to `false`, and `hermes pause` stops all jobs ([cron](https://hermes-agent.nousresearch.com/docs/user-guide/features/cron)). | Not for regulated work. |
| **Delegation** | `delegate_task` with `max_spawn_depth` 1 and 10 concurrent children by default. Children inherit toolsets and cannot use memory, `send_message`, cronjob or clarify ([delegation](https://hermes-agent.nousresearch.com/docs/user-guide/features/delegation)). | Turn it off. Multi-step work belongs in the engine. |
| **Approvals** | `approvals.mode: smart\|manual\|off`. The default, `smart`, uses an auxiliary LLM. Headless modes default to `deny`. `approvals.deny` globs beat YOLO. | Use `manual`, and never answer "always". |
| **Hooks** | Four kinds: (1) gateway event hooks, which are observers and **load without approval**; (2) plugin hooks, including `pre_tool_call` (block, approve or modify; fails closed), `pre_gateway_dispatch` (unbounded), `transform_llm_output` and observers; (3) shell hooks; (4) signed outbound webhooks ([hooks](https://hermes-agent.nousresearch.com/docs/user-guide/features/hooks)). | The main control surface (§A8.6). Make `hooks/` read-only. |
| **Prompt caching** | The system prompt is built once per session. Anthropic "system_and_3" breakpoints, set by `prompt_caching.cache_ttl`. Changing model or provider resets the cache ([caching](https://hermes-agent.nousresearch.com/docs/developer-guide/context-compression-and-caching)). | vLLM caches prefixes server-side (§B11). |
| **Fallback** | `fallback_providers`, at most once per turn, triggered by 429/5xx or 401/403/404 ([fallback](https://hermes-agent.nousresearch.com/docs/user-guide/features/fallback-providers)). | **A cloud fallback silently moves data off-site.** Allow on-prem aliases only. |
| **Profiles** | `hermes -p <name>` gives isolated config, memory and gateway. | Use one profile per channel class. |

**No native "smart routing" in Hermes.** I found no Hermes-native cheap/expensive model router. The closest features are `auxiliary.<task>` models, `cron.model` and `delegation.model`. Do model routing in the LLM gateway instead (§B2/B3). [Unverified: the "Provider Routing" docs page was not read; it may describe OpenRouter-style provider preferences rather than a classifier router.]

## A3. Reference configuration for a TrialBox front-end profile

The sketch below shows intent. Key names come from the pages cited in §A2. Keys I could not confirm are marked `# [Unverified]`.

```yaml
# ~/.hermes-trialbox/config.yaml   (profile: trialbox-internal)
model:
  provider: custom
  base_url: https://llm-gw.trialbox.local/v1      # LiteLLM/Envoy, never a cloud URL
  default: tb-frontdesk                           # gateway alias -> pinned on-prem model
  context_length: 65536                           # Hermes refuses < 64k
fallback_providers:                               # on-prem only
  - {provider: custom, model: tb-frontdesk-backup, base_url: https://llm-gw.trialbox.local/v1, key_env: TB_GW_KEY}
auxiliary:
  approval:    {provider: custom, model: tb-guard-small, base_url: https://llm-gw.trialbox.local/v1}
  compression: {provider: custom, model: tb-router-small, base_url: https://llm-gw.trialbox.local/v1}
agent:
  disabled_toolsets: [terminal, file, browser, web, code_execution, delegate, cronjob, skills_manage, memory, image_gen, tts]   # names [Unverified] - verify with `hermes tools`
approvals:
  mode: manual
  cron_mode: deny
  single_query_mode: deny
  unattended_mode: deny
  deny: ["*"]                                     # no shell at all
security:
  allow_private_urls: false
  allow_lazy_installs: false
auth:
  adopt_external_logins: false
memory:
  memory_enabled: false                           # or true + write_approval for staff prefs only
  user_profile_enabled: false
  write_approval: true
skills:
  write_approval: true
  guard_agent_created: true
  auto_load: [tb-frontdesk-sop]                   # from signed, read-only dir
cron:
  allow_agent_scheduling: false
delegation:
  max_spawn_depth: 0                              # [Unverified] whether 0 is accepted; else disable toolset
plugins:
  hook_callback_timeout: 5                        # pre_tool_call fails closed on timeout
prompt_caching:
  cache_ttl: auto
mcp_servers:
  trialbox-frontdoor:
    url: https://mcp-frontdoor.trialbox.local/mcp
    client_cert: /run/secrets/hermes-client.pem
    client_key:  /run/secrets/hermes-client.key
    identity_header: {name: X-TB-End-User, value_from: profile}   # semantics [Unverified]
    tools:
      include: ["submit_request", "get_request_status", "get_approved_report_link", "list_my_studies", "search_sop"]
      prompts: false
      resources: false
    sampling:    {enabled: false}
    elicitation: {enabled: false}
    timeout: 30
```

Environment settings:
- `EMAIL_ALLOWED_USERS`, `TEAMS_ALLOWED_USERS` and similar are generated from the hospital directory group `TB-Staff`.
- `GATEWAY_ALLOW_ALL_USERS` is unset.
- `HERMES_ENABLE_PROJECT_PLUGINS` is unset (project plugins are off by default).
- `HERMES_YOLO_MODE` is absent, and CI asserts that it stays absent.

## A4. Deployment

- **Image:** use `nousresearch/hermes-agent:<X.Y.Z>@sha256:<digest>` ([Docker docs](https://hermes-agent.nousresearch.com/docs/user-guide/docker)).
  - The image is stateless, and state lives in `/opt/data`.
  - It runs as UID 10000 under s6-overlay, and the gateway refuses to run as root.
  - Port 8642 serves the API and health endpoint, and port 9119 the dashboard. Publish neither.
  - Expose only the channel webhooks you use (for example, the Teams Bot endpoint), behind the hospital WAF. Leave the dashboard off: it needed auth fixes as recently as v0.21.6.
- **Local models:** point `base_url` at the **LLM gateway** (§B2), not straight at vLLM, so that aliases, budgets and data-class routing apply to the front end too. You need a context window of at least 64k and server-side tool parsing (vLLM `--enable-auto-tool-choice --tool-call-parser …`, SGLang, or llama.cpp `--jinja`) [Prior notes].
- **Network:** run Hermes in a "channel DMZ" namespace. Allow egress only to the LLM gateway, the front-door MCP server, and the mail, Graph/Bot Framework or LINE endpoints. This makes SSRF protection a second line rather than the only one.
- **High availability:** the gateway is a singleton per profile [Prior notes]. Run it active/passive with a lease, or as one replica with fast restart. v0.22.2 fixed a start-after-reboot failure under supervisors, which is one reason to smoke-test every upgrade.

## A5. Security history (2025–2026)

| ID | Component / class | Affected → fixed | Severity | Source |
|---|---|---|---|---|
| CVE-2026-7112 / 7113 | API-server key check; webhook auth bypass | 0.8.0 → later [Unverified fix version] | Moderate | [GHSA-r7hr-pvjh-r4p3](https://github.com/advisories/GHSA-r7hr-pvjh-r4p3), [GHSA-mq9g-m88j-mmvx](https://github.com/advisories/GHSA-mq9g-m88j-mmvx) |
| CVE-2026-7396 / 7397 | WeChat Work path traversal; symlink following in file tools | 0.8.0 → 0.9.0 (7397) | 4.0 / 4.8 | [CSA note](https://labs.cloudsecurityalliance.org/research/csa-research-note-hermes-agent-cves-20260504-csa-styled/) |
| CVE-2026-6829 | hermes-webui path traversal | < 0.50.34 | 5.3 | CSA note |
| Audit of v0.8.0 (no CVEs) | 4 Critical and 9 High in the default config: bypassable regex shell guard, no file-read denylist, container mode skipping approvals, persistent skill injection, injectable LLM auto-approval, unsandboxed hooks and plugins, unpinned git dependencies | partly fixed later | — | CSA note |
| CVE-2026-9368 | `execute_code` leaked secrets in the environment | < 0.11.0 | Moderate | [GHSA-wm96-9gfh-vvgq](https://github.com/advisories/GHSA-wm96-9gfh-vvgq) |
| CVE-2026-9366 | Prompt injection via the context scanner | < 0.15.0 | Moderate | [GHSA-pgp4-xr4j-h5cg](https://github.com/advisories/GHSA-pgp4-xr4j-h5cg) |
| CVE-2026-9353 | Skills Guard bypass | [Unverified version] | — | [Prior notes] |
| CVE-2026-53870 | DB and webhook files created world-readable (exposes conversation history) | < 0.16.0 | 6.8 | [HOL entry](https://hol.org/guard/security/cves/CVE-2026-53870-hermes-agent-0160-sensitive-file-permission) [secondary] |
| CVE-2026-10222 | `.env` sanitiser injection | < 0.18.0 | Low | [GHSA-mv8x-fg99-32mf](https://github.com/advisories/GHSA-mv8x-fg99-32mf) |
| CVE-2026-10224 | Feishu webhook resource exhaustion | ≤ 2026.4.30 | — | [GitLab advisory](https://advisories.gitlab.com/pypi/hermes-agent/CVE-2026-10224/) |
| CVE-2026-9369 | Dashboard plugin discovery, incorrect comparison (local) | 2026.4.23 | Low | [GHSA-cv5c-mh6j-wvp9](https://github.com/advisories/GHSA-cv5c-mh6j-wvp9) |
| CVE-2026-14628 | **Webhook gateway `extract_media` path traversal**; public exploit; vendor did not respond | ≤ 2026.5.16; fix version not stated | 5.5 (v4) | [GHSA-85cr-q769-68x2](https://github.com/advisories/ghsa-85cr-q769-68x2) (unreviewed) |
| **CVE-2026-82021** | **Supply chain: the MCP catalogue referenced an upstream through a mutable branch, enabling RCE if the upstream was compromised (CWE-494)** | 0.18.2 → 0.19.0 (tag v2026.7.20) | **Critical, 9.0 (v4)** | [GHSA-w9gw-vgmg-q67h](https://github.com/advisories/GHSA-w9gw-vgmg-q67h) |
| (no CVE) v0.21.6 fixes | Dashboard `X-Forwarded-For` rate-limit bypass, unlimited `/auth` body size, login codes sent to a non-loopback redirect (session takeover), git filter programs, **email allowlist bypass via a quoted display name** | → 0.21.6 | — | [releases](https://github.com/NousResearch/hermes-agent/releases) |

**Patterns.** Most of these issues sit in the gateway, webhook, dashboard and plugin code, which is exactly what a channel front end exposes. Several advisories say the vendor did not respond to disclosure. Supply-chain risk is real: the CVE-2026-82021 catalogue issue, unpinned git dependencies, and a catalogue of about 600 plugins. OpenClaw's nine CVEs from March 2026 fall into the same classes, which suggests these risks are **inherent to persistent, self-extending agents** ([CSA](https://labs.cloudsecurityalliance.org/research/csa-research-note-hermes-agent-cves-20260504-csa-styled/)).

## A6. Hardening options (checklist)

1. **Version discipline:** pin the tag and digest, and mirror the image internally. Run SCA, SAST and a container scan before each upgrade. Subscribe to the repo's GHSA feed. Patch High/Critical within 7 days, and never track `main`.
2. **Minimal surface:** enable only the adapters you need. Turn off the dashboard, API server, plugin catalogue, Connectors, lazy installs and external logins.
3. **Tools:** keep only the TrialBox MCP toolset, with an explicit `tools.include` list. Turn sampling and elicitation off, and use mTLS.
4. **Integrity:** mount `hooks/`, `plugins/` and `skills/` read-only from a signed artifact, and verify a hash manifest at start-up. Leave project plugins and `hooks_auto_accept` off. The TrialBox policy plugin is the only plugin.
5. **Identity:** use directory-based allowlists. Keep the email DMARC/SPF check, and use Entra tenant restriction for Teams. Pass the user identity to MCP as a signed assertion, not as plain text.
6. **Approvals:** `manual`, all headless modes set to `deny`, `approvals.deny: ["*"]`, no "always" answers, and a CI check that YOLO is absent.
7. **Data at rest:** encrypt `/opt/data`. Purge `state.db` with an ops-owned job. Fix file permissions (the CVE-2026-53870 class of bug), and redact logs before shipping them.
8. **Network and runtime:** egress allowlist (§A4) and a WAF on the channel webhooks. Read-only root filesystem, seccomp, resource limits, and no Docker socket.
9. **Monitoring:** send hook audit events and gateway logs to the SIEM. Alert on unknown senders, blocked tool calls, injection-scanner hits and volume spikes.

## A7. Using Hermes as the channel front end without PHI tools or regulated scheduling

**Design rule: Hermes is a *concierge*, not a *clerk*.** It may hold conversations, understand intent, collect parameters, and show status and links. It may not hold PHI-capable tools, own schedules for regulated work, or produce regulated records.

**Allowed tool surface (the "front-door MCP")**
- `submit_request(type, params, justification)` creates a typed request in the workflow engine and returns a ticket ID. The request types are Feasibility, PreScreen, Report and Question. The params schema forbids patient identifiers, and the server validates this with regex and Presidio.
- `get_request_status(ticket_id)` returns the status, the next human gate and the assignee, with no data payload.
- `get_approved_report_link(ticket_id)` returns an SSO- and role-gated portal URL, never the content.
- `list_my_studies()` and `search_sop(query)` serve non-PHI reference data.
- Nothing else: no patient-level reads, no CTMS/EDC/IRB writes, no free-form SQL, and no email beyond in-thread replies.

**Who owns the schedule.** All regulated timers (enrollment digests, visit-window and IRB reminders) belong to Temporal/DBOS. When a timer fires, the engine pushes a **pre-rendered, DLP-checked** message through `hermes mcp serve` → `messages_send`, or through a thin notification service. Hermes delivers the message but decides nothing. Hermes cron is either disabled or limited to non-regulated nudges.

**Keeping PHI out of the channel.** Staff *will* paste patient names or chart numbers into chat.
1. A `pre_gateway_dispatch` hook runs Presidio with Taiwan recognisers on every inbound message.
   - In **no-PHI channels** (LINE, external email), a match skips the message and sends a canned reply ("use the TrialBox portal").
   - In **PHI-tolerant channels** (internal Teams or email), it replaces identifiers with tokens.
   - This hook has no timeout of its own, so give it an internal one.
2. A `transform_llm_output` hook runs outbound DLP and blocks replies that contain ID or chart-number patterns.
3. The front end's model alias resolves only to on-prem models (§B3).
4. `state.db` is encrypted and has a retention limit (§A6.7).

**Prompt injection.** The front end serves only allowlisted internal senders. External sponsor or CRO mail goes to a quarantine workflow in the core that extracts content without tools [Prior notes §4.7]. Because Hermes has no consequential tools, an injection can at worst file a junk request, which a human gate then rejects.

## A8. Optimising Hermes for this role

### A8.1 Skills as reviewed procedures
- Treat each `SKILL.md` as a **controlled document**: owner, version, effective date, and the SOP it implements, all in the YAML frontmatter.
  - Examples: "How to submit a feasibility request", "Explaining pre-screen status", "Escalation to the study coordinator".
- Store skills in Git, review them through a PR with QA sign-off, sign them, and deploy them read-only. Use `skills.auto_load` for the persona SOP.
- `skills.write_approval: true` and `guard_agent_created: true` turn agent-proposed improvements into **staged drafts**. A nightly job exports them as PRs (`/skills pending|diff` [Prior notes]), and nothing auto-applies.
- Optional: run offline GEPA/DSPy evolution (`hermes-agent-self-evolution`) against the evaluation set, and send its output only as PRs.

### A8.2 Memory governance
- **Default:** memory off.
- **If on:** only staff preferences (language zh-TW/en, digest time, preferred study list) with `write_approval: true`, and a `pre_tool_call` rule that rejects memory writes containing Presidio hits.
- No external memory plugins.
- Fix the transcript (`state.db`) retention, and document it in the data inventory as "operational, non-GxP record".

### A8.3 Approval mode
- Use `manual`. Do **not** use `smart`: an auxiliary-LLM judge is prompt-injectable (CSA audit).
- Because there are no shell or file tools, approvals rarely fire. Real approvals happen in the workflow engine with e-signature semantics. Do not reuse Hermes' `/v1/runs/{id}/approval` as a Part 11 signature.

### A8.4 Tool allowlists
- Defence in three places:
  1. Hermes `disabled_toolsets` plus MCP `tools.include`.
  2. The `pre_tool_call` policy plugin, which checks tool name, argument schema and the user's role via OPA/Cedar.
  3. The MCP server's own authorisation (OAuth scopes plus row-level checks).
- Any one of these can fail without exposure.

### A8.5 Rate limits
- Hermes has no per-user rate-limit keys that I could confirm.
- Enforce rate limits in:
  - the `pre_gateway_dispatch` hook (per sender, per minute and per day);
  - the LLM gateway (virtual key per profile with RPM/TPM and budgets);
  - the MCP server (per user and per tool, for example at most 5 `submit_request` calls per hour).

### A8.6 Audit hooks
- Write a single plugin `tb_audit`. It uses `pre_tool_call` (decide and log, fail closed), `post_tool_call`, `pre_llm_call`/`post_llm_call` (log hashes, not content) and `on_session_start`/`subagent_stop`.
- It emits OTel GenAI spans (§B10) and **appends hash-chained events** to the TrialBox audit service over mTLS.
- Gateway event hooks (`agent:start`/`agent:end`, `session:*`) are observers. Use them for metrics only, because their errors are swallowed.
- `hooks.outbound` signed webhooks can be a secondary feed to the SIEM [Unverified: signature scheme].

### A8.7 Model routing
- Hermes sends everything to one gateway alias. The gateway maps:
  - `tb-frontdesk` → a mid-size, tool-capable on-prem model (for example Qwen3.6-35B-A3B or gpt-oss-120b) [Prior notes];
  - `tb-guard-small` → gpt-oss-safeguard-20b or Qwen3Guard-8B for the auxiliary approval and classification tasks;
  - `tb-router-small` → a 4–8B model for compression and summaries.
- Disable `fallback_providers` that point anywhere except on-prem aliases.

### A8.8 Prompt caching
- Keep `SOUL.md`, the skills snapshot and tool schemas byte-stable so vLLM automatic prefix caching hits on every turn.
- Avoid mid-session `/model` switches.
- Set a per-profile `cache_salt` at the gateway if several tenants share a vLLM instance (§B11).
- For Claude via a cloud provider (only for non-PHI classes), set `cache_ttl: auto`.

### A8.9 Small local models for routing
- An intent classifier (4–8B, or a ModernBERT-class classifier such as vLLM Semantic Router's signals) runs *before* the main model in `pre_gateway_dispatch` or at the gateway.
- It sorts each message into {status query → deterministic answer with no LLM, submit request → structured form fill, SOP question → retrieval answer, out of scope → canned reply}.
- Deterministic answers to status queries cut cost and latency and remove hallucination risk for the most common question.

## A9. Alternatives for the *regulated core* (brief)

Versions are [Prior notes] unless stated.

| Framework | Strengths for the regulated core | Weaknesses / caveats | Verdict |
|---|---|---|---|
| **Temporal + Pydantic AI** | Event-sourced, replayable workflows; Signals/Updates for human gates; typed outputs; deferred-tool approvals; native durability and OTel | Two stacks to run (DBOS is a Postgres-only alternative) | **Recommended core** |
| **LangGraph** (1.2.x) | State graph, `interrupt()` for human-in-the-loop, Postgres checkpointer | Checkpointing rather than event sourcing; LangChain coupling | Strong alternative inside activities |
| **OpenAI Agents SDK** (0.24) | Small; handoffs and guardrails; Temporal integration ([blog](https://temporal.io/blog/introducing-temporal-and-agentic-sandboxes-openai-agents-sdk)) | Tracing exports to OpenAI by default, so turn it off | Acceptable |
| **Claude Agent SDK** (0.2.x) | Best permission model: PreToolUse hooks, allow/deny/ask ([docs](https://docs.claude.com/en/api/agent-sdk/permissions)) | Designed for Claude, and Claude is Global-only on Bedrock in Taipei (§B13) | Dev and non-PHI work only |
| **Google ADK** (v2.12.0, 2026-10-13) | `before_`/`after_tool_callback`, `require_confirmation` workflow nodes, LiteLLM support ([releases](https://github.com/google/adk-python/releases)) | Gemini-centric defaults; no workflow engine | Viable, but no advantage on-prem |
| **Letta** (0.34) | Tiered memory | Autonomous memory conflicts with validated state | Not for the core |
| **Hermes Agent** | Channels, cron, skills | No replay and no Part 11 primitives | **Front end only** |

## A10. Implications for the spec (Part A)

### Requirements

- **REQ-AG-01:** The conversational front end (CF) SHALL hold no tool that reads identified patient data or writes to any system of record. Its only callable tools SHALL be the front-door MCP tools listed in §A7, enforced in three layers (CF config, CF policy hook, MCP server authorisation).
- **REQ-AG-02:** The CF SHALL NOT schedule, trigger or modify regulated work. All regulated timers SHALL be owned by the workflow engine. The CF MAY only *deliver* pre-rendered notifications that the engine pushes to it.
- **REQ-AG-03:** The CF SHALL be deployed from a pinned version and image digest. A security-patch SLA SHALL apply (Critical/High within 7 days). SCA, SAST and container scans SHALL pass before promotion. Plugin catalogues, lazy installs, project plugins, dashboard and API server SHALL be disabled.
- **REQ-AG-04:** The CF SHALL use `approvals.mode: manual`, deny all headless approvals, set `approvals.deny: ["*"]` and forbid YOLO (checked in CI and at runtime).
- **REQ-AG-05:** Skills SHALL be controlled documents (Git, review, signature, read-only mount). Agent-authored skill or memory writes SHALL be staged and SHALL only take effect through change control.
- **REQ-AG-06:** Memory SHALL be disabled, or limited to non-PHI staff preferences with write approval. External memory providers SHALL be disabled. Transcript stores SHALL be encrypted, retention-limited and listed in the data inventory.
- **REQ-AG-07:** Inbound DLP (on the gateway dispatch hook) and outbound DLP (on the output transform hook) SHALL run with Taiwan-specific recognisers. Channels SHALL be classed as PHI-tolerant or no-PHI.
- **REQ-AG-08:** A `pre_tool_call` policy plugin SHALL call the central policy engine. It SHALL fail closed within 5 s and emit hash-chained audit events plus OTel spans for every tool call and LLM call (hashes, not content, at this layer).
- **REQ-AG-09:** All CF model calls SHALL go through the LLM gateway under aliases that resolve only to on-prem models. Fallback chains SHALL contain only on-prem aliases.
- **REQ-AG-10:** The CF SHALL authenticate senders (directory allowlist; DMARC/SPF for email; tenant restriction for Teams) and SHALL pass a signed end-user identity to the MCP server.
- **REQ-AG-11:** The CF SHALL be replaceable. The front-door MCP contract is the stable interface, so a thin in-house gateway can replace Hermes without changing the core.

### Component list (Part A)
- Hermes Agent (pinned) with profiles `tb-internal` (Teams + internal email) and optionally `tb-line` (LINE, no-PHI).
- The `tb_policy_audit` Hermes plugin.
- The front-door MCP server (FastAPI + MCP SDK, mTLS, OAuth client credentials or internal JWT).
- A notification relay (the engine calls `hermes mcp serve` or a thin sender).
- An OPA/Cedar policy service.
- A Presidio service with Taiwan recognisers.
- A signed skills repository.
- Temporal/DBOS as the scheduler of record.

### Recommended architecture (Part A)

```
Staff ─Teams/email/LINE─▶ [Hermes CF (pinned, DMZ ns)]
                             │ pre_gateway_dispatch: authN map + Presidio + rate limit + intent router
                             │ LLM calls ─▶ LLM gateway (alias tb-frontdesk → on-prem only)
                             │ tools ─▶ front-door MCP (mTLS, include-list, pre_tool_call → OPA, audit)
                             ▼
                     [Workflow engine (Temporal/DBOS)] ── owns schedules, human gates, e-sign
                             │ notifications (pre-rendered, DLP-checked)
                             └──▶ hermes mcp serve: messages_send ─▶ channel
```

---

# PART B: LLM platform and LLMOps for a regulated hospital deployment

## B1. Reference architecture (overview)

The platform has four planes:
- **Serving:** vLLM/SGLang on the DGX B200, plus optional cloud endpoints.
- **Gateway:** authentication, data-class routing, budgets, guardrails and logging.
- **Control:** the model and prompt registries, evaluation, policy and releases.
- **Observability and assurance:** traces, metrics, drift monitoring and the audit ledger.

Every LLM call goes through the gateway with a **data-classification label**. A call without a label fails closed.

## B2. Model gateway patterns

| Gateway | Strengths | Risks / notes |
|---|---|---|
| **LiteLLM Proxy** (Python, MIT core + Enterprise) | OpenAI-compatible, 100+ providers. Virtual keys, budgets, RPM/TPM limits, fallbacks and guardrail hooks. **Tag routing:** `!tag` excludes and `&tag` requires a tag. Team-inherited tags are an Enterprise feature, and `allow_fail_open` *can route to excluded deployments* ([tag routing](https://docs.litellm.ai/docs/proxy/tag_routing)). | **PyPI 1.82.7 and 1.82.8 were trojaned on 2026-03-24** with a `.pth` credential stealer, after the CI pipeline was compromised through Trivy ([Arthur](https://www.arthur.ai/column/litellm-supply-chain-attack-pypi-compromise-2026), [NetSPI](https://www.netspi.com/?p=32614)). Pin by hash, and never use fail-open on data-class tags. |
| **Envoy AI Gateway** (CNCF, Apache-2.0) | **1.0 on 2026-06-23:** stable API, 16 providers and token-aware quotas ([v1.0](https://aigateway.envoyproxy.io/release-notes/v1.0/)). Its **MCP Gateway** (`MCPRoute`, OAuth, multiplexing, tool filtering) has existed since v0.4 ([MCP](https://aigateway.envoyproxy.io/docs/0.6/capabilities/mcp/)). Works with ext_authz to OPA and with mTLS. | Requires Kubernetes and Envoy skills. Fewer LLM-specific features than LiteLLM. |
| **Portkey** (TypeScript gateway, MIT) | Retries, fallbacks, conditional routing and guardrail hooks. | **Palo Alto Networks announced its intent to acquire Portkey (~2026-05-01)** for Prisma AIRS ([NAND Research](https://nand-research.com/palo-alto-networks-portkey-acquisition-anchors-its-agentic-security-stack/)). Whether the deal has closed, and which features stay self-hostable, is [Unverified]. |
| **vLLM Semantic Router** | An Envoy ext-proc router. It combines signals (domain, keyword, embedding and others) with per-decision plugins (jailbreak, PII, semantic cache, hallucination detection). **v0.3 "Themis" shipped 2026-06-05** ([Themis](https://vllm.ai/blog/2026-06-05-v0.3-vllm-sr-themis-release), [paper](https://arxiv.org/html/2603.04444v1)). | The project is young, and its classifiers are not validated PHI detectors. Use it for cost and quality routing only. |
| **vLLM production-stack / llm-d** | Prefix- and KV-aware routing across replicas. | Belongs behind the policy gateway. Versions [Unverified]. |

**Recommended pattern: two tiers.**
1. **Policy gateway (north-south):** LiteLLM Proxy, pinned by hash and built from source into an internal image, *or* Envoy AI Gateway if the platform team is Kubernetes-native. It holds identity, data-class routing, budgets, guardrails, logging, and the alias → pinned-model map.
2. **Serving router (east-west):** vLLM production-stack/llm-d or the SGLang router for KV/prefix-aware load balancing. Optionally add vLLM Semantic Router for intent-based selection *within* an already-authorised pool.

**MCP traffic** goes through a separate **MCP gateway**: Envoy AI Gateway `MCPRoute`, or an in-house proxy, with OAuth/mTLS, tool allowlists and audit.

## B3. Routing between on-prem and cloud by data classification

**Classification scheme.** Assign the label at the *source*: the workflow activity or the CF policy hook. Never let the model infer its own label.

| Class | Examples | Allowed targets | Required controls |
|---|---|---|---|
| **D0 Public** | ClinicalTrials.gov text, published protocols, guidelines | On-prem; cloud (any approved region) | Standard logging |
| **D1 Internal non-PHI** | SOPs, internal protocol drafts, sponsor documents under CDA | On-prem; cloud **in-country or Japan with ZDR** if the contract allows | ZDR or abuse-monitoring exemption, no training use, regional endpoint only |
| **D2 De-identified / aggregate** | Feasibility counts with small cells suppressed, de-identified cohort statistics | On-prem; cloud only with a documented re-identification risk assessment, in-country, ZDR, and preferably a confidential-computing endpoint | Small-cell suppression enforced *before* the gateway |
| **D3 Identified PHI** | Clinical notes, patient lists, chart numbers, Taiwan national ID | **On-prem only** (DGX B200 / GB10) | Presidio/regex pre-check; deny if the label is missing |
| **D4 Highly sensitive** | Genomic data, psychiatric/HIV/substance-use notes, minors | On-prem only, dedicated model pool, `cache_salt` per study, reduced logging | Extra approvals |

**Enforcement at the gateway**
1. Each request carries a signed `x-tb-data-class` header, plus the study ID and purpose.
2. The gateway routes on tags such as `&dc:D3` and `&loc:onprem`, with fail-open turned off.
3. An **independent PHI tripwire** runs on every cloud-bound request: Presidio, Taiwan national-ID (`[A-Z][12]\d{8}`), NHI and chart-number patterns, and name heuristics. A hit blocks the request and raises an alert, whatever the label says.
4. Cloud responses are logged with the region and the provider's request ID.
5. A fallback can never cross into a different data class.

## B4. Model registry and pinning

**Registry record.** Each model version is an immutable record containing:
- `alias@version`;
- the HF repo and commit SHA, plus a SHA-256 for every weight file;
- the tokenizer and chat-template hashes;
- the quantisation recipe and its calibration-data hash;
- the engine version and container digest;
- the serving flags: tool parser, structured-output backend, `max_model_len` and the prefix-cache hash algorithm;
- the licence, the context of use (COU), the evaluation report ID, the approval signature and a retirement date.

**Tooling.** MLflow Model Registry or a Git-backed YAML registry plus an OCI artifact store (Harbor) work. The key properties are immutability and the alias → version mapping being the *only* thing the gateway reads.

**Cloud models** are pinned by dated version ID (for example a Bedrock model ID or an Azure deployment with a fixed model version, with auto-upgrade off). Provider deprecation calendars are tracked as change-control triggers.

**Promotion flow:** `candidate` → evaluation suite pass (§B8) → QA review → `approved` → canary (5%) → `production`. Rollback means re-pointing the alias, which is itself an audited change.

## B5. Prompt management and versioning

**Storage.** Prompts are code: Jinja/Markdown templates in Git, each with an ID, semantic version, owner, linked context of use, input schema, output schema, and the eval suite that gates it.

**Resolution.**
- Use **Langfuse** prompt management (self-hosted) or LiteLLM prompt management *only as a read-through cache* of the Git source of truth.
- Production resolves `prompt_id@version`, never "latest".
- Every LLM call logs `prompt_id`, `prompt_version` and `template_sha`, plus the rendered prompt hash.

**Cache-friendly layout:** stable system block → tool schemas → retrieved static context → volatile user/task content. This maximises prefix-cache hits (§B11).

**Change control.**
- A prompt change counts as a **minor change** when the evaluation suite shows no regression.
- A change that alters the context of use or the risk tier requires a **revalidation** record. This mirrors the "risk-based performance assessment" and "life cycle management" principles in the FDA–EMA principles ([FDA](https://www.fda.gov/about-fda/artificial-intelligence-drug-development/guiding-principles-good-ai-practice-drug-development)).

## B6. Guardrails

**Layered design.**
1. **Deterministic first:** schema validation, regex/ID detectors, allowlists, number-consistency checks, citation-span verification.
2. **PHI detection:** [Presidio](https://microsoft.github.io/presidio/) with Taiwan recognisers for the national ID (with checksum), ARC/UI number, NHI card, chart/MRN formats, zh-TW addresses and Chinese names. Name detection uses a dictionary plus NER [Unverified: best zh-TW NER]. Presidio's anonymiser provides reversible tokenisation inside the hospital.
3. **Policy classifiers**, run on input and output at the gateway:
   - **gpt-oss-safeguard-20b/120b** ([HF](https://huggingface.co/openai/gpt-oss-safeguard-20b)): Apache-2.0, MoE with 3.6B or 5.1B active parameters. You supply the policy as a prompt, it has a reasoning-effort setting, and it requires the harmony format. Use it to enforce **hospital-written rules** such as "no eligibility determinations", "no dosing advice" and "no disclosure of other patients".
   - **Qwen3Guard** ([GitHub](https://github.com/QwenLM/Qwen3Guard)): Gen and token-level Stream variants at 0.6B, 4B and 8B, covering 119 languages. It has three severity levels and nine categories, including PII and jailbreak. It is the best fit for **zh-TW streaming moderation**. Licence [Unverified].
   - **Llama Guard 4** (12B) ([HF](https://huggingface.co/meta-llama/Llama-Guard-4-12B)): a general hazard taxonomy, so it is less useful for hospital policy.
4. **Flow rails:** [NeMo Guardrails](https://github.com/NVIDIA/NeMo-Guardrails) (Colang) keeps the front end on topic, calling the classifiers above as actions.
5. **Injection detection** on email, PDFs and tool outputs, combined with structural defences: spotlighting, the dual-LLM pattern and capability containment [Prior notes §4.7].

**Placement.** Guardrails run in the gateway (central, uniform) *and* at the workflow boundary (context-specific). Classifier verdicts are logged as span events.

**Budget.** A safeguard call at low reasoning effort on a 20B MoE adds roughly tens to hundreds of milliseconds on a B200 slice [Unverified estimate]. Run it in parallel with the main call and gate the *release* of the output, not its generation.

## B7. Structured output

- **Server-side constrained decoding.** vLLM and SGLang support JSON Schema, regex and grammar via xgrammar (the default), guidance or Outlines [Prior notes].
  - Use `response_format: {type: json_schema, strict: true}` for every agent → system boundary.
  - For gpt-oss, use harmony-native structured output.
- **Validation.** Pydantic models define the schema, and a validator rejects anything that fails. Use a bounded retry (at most 2) with an error-feedback message, then escalate to a human.
- **Numbers and identifiers are never free-generated.** They are template-injected from deterministic results, and a post-check verifies that every number in the narrative equals the result object [Prior notes §4.4].
- **Tool-call reliability.** Choose the parser per model family (`hermes`, `qwen3_coder`, `openai`/harmony, `llama3_json`), and add a regression test per model release.
- **Contract.** Store JSON Schemas in the prompt registry with versions, so that outputs are reproducible against a schema version.

## B8. Evaluation harnesses

| Tool | Use in TrialBox | Notes |
|---|---|---|
| **Inspect AI** (UK AISI, MIT) ([site](https://inspect.aisi.org.uk/)) | **Primary agentic and regulated eval harness.** Tasks/solvers/scorers, sandboxed tool environments, MCP support, log viewer, and reproducible eval logs to store as validation evidence. | Good fit for "context of use" test packs. [Version not re-verified] |
| **promptfoo** ([site](https://www.promptfoo.dev/)) | Prompt regression in CI, red-teaming plugins (prompt injection, PII leakage, excessive agency), side-by-side comparisons. | **OpenAI announced its acquisition on 2026-03-09.** The founders say it stays open source and multi-model ([TechCrunch](https://www.techcrunch.com/2026/03/09/openai-acquires-promptfoo-to-secure-its-ai-agents/), [SDxCentral](https://www.sdxcentral.com/news/openai-acquires-ai-testing-firm-to-beef-up-agentic-security/)). Pin the version, and watch the licence. |
| **lm-evaluation-harness** (EleutherAI) ([GitHub](https://github.com/EleutherAI/lm-evaluation-harness)) | Capability smoke tests for each new weight or quantisation (MMLU-Pro, GSM8K, zh-TW sets such as TMMLU+ [Unverified availability]) to detect **quantisation regressions**. | Not agentic. |
| **HELM / MedHELM** (Stanford CRFM) ([MedHELM arXiv](https://arxiv.org/abs/2505.23802)) | Medical-task coverage: 5 categories, 22 subcategories, 121 tasks, 35 benchmarks. LLM-jury scoring reached ICC 0.47 against clinicians (clinician–clinician 0.43). The weakest categories were **Clinical Decision Support** and **Administration & Workflow**, the latter being the category closest to TrialBox. | Use it as an external reference for model selection, not as validation evidence for TrialBox's specific context of use. |
| **Langfuse datasets/experiments** (self-hosted) | Ties production traces to eval datasets; human annotation queues. | Already in the stack [Prior notes]. |

**Evaluation tiers**
1. **Unit:** schema and parser tests per model × prompt.
2. **Task:** gold sets, including criteria extraction F1, SQL/CQL execution accuracy on synthetic cohorts, note-evidence citation faithfulness, and zh-TW email intent accuracy.
3. **Agentic:** Inspect tasks with mock MCP servers. Metrics are tool-call correctness and **policy violations (target 0)**.
4. **Adversarial:** promptfoo/Inspect red-team packs covering email/PDF injection, tool poisoning, PII exfiltration and jailbreaks in zh-TW and English.
5. **Human:** clinician and coordinator review samples with inter-rater agreement.

**Gates.** Every change to model, prompt, rule or guardrail must show no statistically meaningful regression on tiers 1–4. A risk-tier change requires tier 5. Evaluation logs are archived immutably as validation evidence.

## B9. Online monitoring and drift

**Signals**
- **Input drift:** embedding shift by intent, plus the mix of languages, document types and therapeutic areas.
- **Output quality:** schema-failure, retry, guardrail-block, citation-failure and number-mismatch rates. Also the **human-override rate at each gate**, which is the strongest signal, and reviewer edit distance.
- **Operations:** TTFT and p95 latency, tokens per workflow, prefix-cache hit rate, queue depth, GPU utilisation, fallback rate, and cloud cost.
- **Safety:** injection detections, PHI-tripwire hits on cloud-bound traffic (target 0), and unknown-sender rejects.

**Methods**
- Daily **shadow evaluation** on de-identified production samples.
- Hourly **canary probes** to catch silent changes in a model or engine, especially in the cloud.
- **EWMA/CUSUM control charts** on override and block rates.

**Response.** A breach opens a QMS deviation or CAPA, and the affected function can degrade to manual-only mode.

**Tooling.** OTel to Langfuse, Prometheus/Grafana, drift jobs (Evidently or custom), and the SIEM.

## B10. OpenTelemetry GenAI semantic conventions

- **Status.** As of mid-2026 every `gen_ai.*` attribute, span, metric and event is still **"Development"**, not Stable ([Greptime](https://greptime.com/blogs/2026-05-09-opentelemetry-genai-semantic-conventions), [dev.to](https://dev.to/azena-ai/opentelemetrys-genai-semantic-conventions-are-not-stable-yet-heres-what-actually-shipped-in-2026-3mke)).
- **Repository move.** In June 2026 the GenAI, provider-specific and **MCP** conventions moved to a dedicated repository so they can version independently [secondary source].
- **Attribute rename.** `gen_ai.provider.name` replaced `gen_ai.system` in v1.37.0. Query both during migration.
- **Agent operations** include `create_agent`, `invoke_agent`, `invoke_workflow`, `plan` and `execute_tool` ([spec](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans)).

**For TrialBox**
1. Pin the semconv version in the collector and SDKs, and use a collector `transform` processor to map old to new names.
2. **Content capture is opt-in.** Default to capturing no prompt or response content in traces sent to general observability. Capture content only into the PHI-zone Langfuse with its own access log and retention.
3. Add custom attributes under `tb.*`: `tb.data_class`, `tb.study_id`, `tb.workflow_id`, `tb.context_of_use`, `tb.prompt_id/version`, `tb.model_alias/version`, `tb.guardrail.verdicts`.
4. Traces are **engineering telemetry, not the Part 11 audit trail**. The audit ledger receives its own hash-chained events, and the trace ID is cross-referenced [Prior notes].

## B11. Cost control, caching and batching

**Cost control**
- On-prem cost is GPU-hours. Use a small model for routing, an MoE workhorse with few active parameters for agents, and a large model only for planning and CQL drafting [Prior notes].
- Set gateway budgets per key, team and workflow, plus caps on max tokens and reasoning effort.
- For D0/D1 cloud traffic, use batch tiers. Azure Global and Data Zone Batch cost 50% less, with a 24 h target ([Azure](https://learn.microsoft.com/en-us/azure/ai-foundry/foundry-models/concepts/deployment-types)).

**Prefix/KV caching**
- **How vLLM caches:** it hashes full KV blocks (the parent hash, the tokens, and extras such as LoRA ID and `cache_salt`) and evicts least recently used blocks first. The default hash is `sha256`; `sha256_cbor` is reproducible across versions. The vLLM docs warn that **non-cryptographic hashes can collide and leak data between tenants**, and that **`cache_salt` isolates tenants and reduces timing side channels** ([vLLM](https://docs.vllm.ai/en/latest/design/prefix_caching.html)).
- **TrialBox rule:** keep a cryptographic hash, salt per data class and per study for D3/D4, and never share a cache between the front end and PHI workflows.
- **Other caching layers:**
  - SGLang RadixAttention suits workloads where many requests share prefixes ([paper](https://arxiv.org/abs/2312.07104)).
  - LMCache offloads KV to CPU or disk ([GitHub](https://github.com/LMCache/LMCache)). Offloaded KV counts as derived PHI, so encrypt it.
  - Put the stable prefix first, and keep reused protocol text right after the system block.
- **Response (semantic) caching:** only for D0/D1 FAQ traffic. Never use it for PHI or regulated workflows.

**Batching for overnight jobs**
- Use the vLLM offline `LLM.generate` / batch API, or SGLang offline engine, for bulk jobs: re-running pre-screen evidence summaries, re-indexing protocols, nightly shadow evaluation.
- Schedule them from the **workflow engine** (not Hermes cron) on the GB10/B200 during off-hours, using a lower-priority queue at the serving router.
- Make each job **idempotent and resumable** (Temporal activity per chunk), with results written to a staging area and gated before use.

## B12. MCP security

**Spec evolution**

| Spec | Key security changes |
|---|---|
| **2025-06-18** | Authorization rewrite: MCP servers became OAuth 2.1 **resource servers**, with Protected Resource Metadata (RFC 9728) and **Resource Indicators (RFC 8707)** to stop token mis-redemption. Added a security best practices page, structured tool output and elicitation [prior knowledge; see [spec](https://modelcontextprotocol.io/specification/2025-06-18)]. |
| **2025-11-25** | **Client ID Metadata Documents (CIMD)** became the preferred registration (Keycloak marks CIMD SHOULD, DCR MAY), with a CIMD security section (SSRF, localhost redirects). OIDC discovery, incremental scope consent, and PKCE S256 expected ([authorization](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization), [den.dev](https://den.dev/blog/mcp-november-authorization-spec/), [Keycloak](https://www.keycloak.org/securing-apps/mcp-authz-server)). Tasks (experimental) [Unverified detail]. |
| **2026-07-28** (current) | Stateless protocol. **`Mcp-Method`/`Mcp-Name` headers** let gateways and WAFs route and rate-limit without parsing bodies. **RFC 9207 `iss` validation** is required. `application_type` in DCR. Credentials are bound to the issuer. **DCR deprecated → CIMD**. **Sampling, Roots and Logging deprecated** (12-month window). MRTR (`input_required`) replaces server-initiated elicitation and sampling. Tasks moved to an extension. Legacy HTTP+SSE deprecated ([blog](https://blog.modelcontextprotocol.io/posts/2026-07-28/)). |

**Threats.** The [OWASP MCP Top 10](https://owasp.org/www-project-mcp-top-10/) (2025 list, still in beta) runs from MCP01 token mismanagement through **MCP03 tool poisoning**, MCP04 supply chain and MCP08 missing audit, to MCP09 shadow servers and MCP10 context over-sharing.

Tool poisoning (malicious instructions hidden in tool descriptions or outputs; the Invariant Labs demonstration had an "add" tool exfiltrating `~/.ssh/id_rsa`) is the most agent-specific item ([Speakeasy](https://www.speakeasy.com/resources/mcp-tool-poisoning)). Hermes CVE-2026-82021 is a live example of MCP04.

**Controls for TrialBox**
1. **First-party, inventoried servers only.** No public catalogues (MCP09).
2. **Pin and sign server images.** CI snapshots the `tools/list` output (names, descriptions, schemas), and any diff needs review. Lint descriptions for imperative instructions, URLs and invisible Unicode (MCP03/04).
3. **Authorization:** OAuth 2.1 with the hospital IdP as authorization server, CIMD registration (no DCR), audience-bound short-lived tokens (RFC 8707), `iss` validation, per-tool scopes, mTLS workload identity, and **no token passthrough** (MCP01/02/07).
4. **MCP gateway** (Envoy `MCPRoute` or in-house): routes and rate-limits on `Mcp-Method`/`Mcp-Name`, calls OPA via ext_authz, and audits every call (MCP08).
5. **Tool results are untrusted.** Spotlight them, and run injection classifiers on free-text results (MCP06/10).
6. **Disable sampling, roots and server-initiated elicitation.** Return the minimum fields, and enforce row-level security in the database rather than in the prompt.

## B13. Hybrid cloud with Taiwan/Japan data residency

### B13.1 Provider status (2026-10-17)

| Provider | Taiwan | Japan | Notes |
|---|---|---|---|
| **AWS** | **Asia Pacific (Taipei) `ap-east-2`**, GA with 3 AZs ([AWS blog](https://aws.amazon.com/blogs/aws/now-open-aws-asia-pacific-taipei-region/)). Bedrock runtime endpoint exists ([endpoints](https://docs.aws.amazon.com/bedrock/latest/userguide/endpoints-region-availability.html)). | Tokyo `ap-northeast-1`, Osaka `ap-northeast-3`. | Per the [region compatibility table](https://docs.aws.amazon.com/bedrock/latest/userguide/models-region-compatibility.html), Claude Haiku/Sonnet/Opus 5.5 are **Global-only from Taipei** (no in-region or Geo), so Taiwan-origin calls may be processed anywhere. From Tokyo/Osaka, Claude Haiku/Opus 5.5 are available via **Geo** (Sonnet 5.5 Global-only), and in-region options are limited to some Nova models and Rerank. Whether the Geo profile is JP-only or APAC is [Unverified]. Tables change often, so verify with `ListFoundationModels` and the inference-profile APIs. |
| **Google Cloud** | `asia-east1` (Changhua, Taiwan). Vertex AI's data-residency page lists Taiwan with in-region ML processing for some partner models (Claude, Mistral, per search snippets) ([data residency](https://cloud.google.com/vertex-ai/generative-ai/docs/learn/data-residency)). Gemini in-region in Taiwan is [Unverified]; I could not fetch the page. | Tokyo `asia-northeast1`, Osaka `asia-northeast2`. | **The global endpoint gives no location guarantee.** Use regional endpoints. Unlisted region/model pairs carry no guarantee. |
| **Microsoft Azure** | **Taiwan North is operational for selected early customers but not GA, and no timetable has been given** (Focus Taiwan, Sept 2026). It "may not yet have the full capabilities" of the Japan or Singapore regions ([Focus Taiwan](https://focustaiwan.tw/business/202609010030)). Foundry model availability there is [Unverified]. Azure Local (on customer hardware) is an option. | Japan East / Japan West. | Foundry deployment types: **Global** = any region; **Data Zone** = US/EU/**APAC** (multi-country, and Microsoft may add regions without notice); **Standard/Regional Provisioned** = the customer-specified geography. Data at rest stays in the geography for all types ([deployment types](https://learn.microsoft.com/en-us/azure/ai-foundry/foundry-models/concepts/deployment-types)). A Japan-only option therefore needs **Standard or Regional Provisioned in Japan East/West**, where flagship-model availability is reportedly limited ([timewell](https://timewell.jp/en/columns/azure-openai-data-zone-japan-2026)) [Unverified]. Azure Policy can forbid `GlobalStandard`/`DataZone*` SKUs. |

### B13.2 Retention and zero-retention terms

- **Amazon Bedrock** does not store or log prompts and completions, does not use them for training, and model providers have no access to Bedrock's per-region deployment accounts. Invocation logging is opt-in and goes to *your* S3/CloudWatch ([Bedrock data protection](https://docs.aws.amazon.com/bedrock/latest/userguide/data-protection.html)).
- **Vertex AI** has three items to handle for zero data retention ([ZDR doc](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/vertex-ai-zero-data-retention)):
  - Gemini **in-memory caching** (24 h TTL, project-level) must be **disabled**.
  - **Abuse-monitoring prompt logging** applies to some customers (GCP ToS without invoiced billing). Others can request an exception.
  - **Session Resumption** (Live API) must stay off.
- **Azure OpenAI / Foundry**
  - Abuse monitoring is on by default. Retention of flagged content is often cited as up to 30 days, but there are reports that the documentation wording changed [Unverified].
  - Customers who meet Limited Access criteria can apply for **modified abuse monitoring**, after which prompts and completions are not stored ([abuse monitoring](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/concepts/abuse-monitoring)).
  - Approval is per subscription and must be in place *before* any D1/D2 traffic.

### B13.3 Confidential computing and GPU TEEs

- **NVIDIA Hopper (H100/H200)** supports confidential-computing mode with a CPU TEE (AMD SEV-SNP or Intel TDX) and an encrypted bounce buffer for CPU↔GPU traffic. On Hopper multi-GPU, **NVLink GPU↔GPU traffic is not hardware-encrypted** [secondary: [Superprotocol](https://superprotocol.com/resources/gpu-cpu-tee-requirements)].
- **Blackwell** is described by NVIDIA as its first **TEE-I/O-capable GPU**, with **inline NVLink protection** and "nearly identical" throughput to unencrypted mode (vendor claim) ([NVIDIA Blackwell](https://www.nvidia.com/en-us/data-center/technologies/blackwell-architecture/), [whitepaper](https://docs.nvidia.com/nvidia-secure-ai-with-blackwell-and-hopper-gpus-whitepaper.pdf)).
- **RTX PRO 6000 Blackwell Server Edition** TEE support arrived with driver R580 TRD1 [secondary].
- NVIDIA maintains a Secure AI compatibility matrix and attestation tooling ([NVIDIA CC docs](https://docs.nvidia.com/confidential-computing/index.html)).
- **Cloud availability:**
  - Azure **NCCads H100 v5** confidential GPU VMs (SEV-SNP + H100) have been GA since Sept 2024 in limited regions ([Azure GPU options](https://learn.microsoft.com/en-us/azure/confidential-computing/gpu-options), [NVIDIA blog](https://blogs.nvidia.com/blog/azure-confidential-vm-h100-general-availability)).
  - Google Cloud offers confidential A3 (H100) VMs [Unverified: GA status and regions].
  - Availability in Taiwan or Japan regions is [Unverified].
- **On-prem implication:** CC mode with remote attestation matters mainly when a cloud-burst or vendor-managed node must process D2/D3 data, because the hospital can then require attestation before releasing keys. For purely on-prem serving it is optional and adds operational load [Unverified: DGX B200 8-GPU CC performance].

### B13.4 Regulatory notes for residency [mostly Unverified, needs legal review]

- **Taiwan:** the Personal Data Protection Act and the MOHW rules on electronic medical records (which allow cloud storage under conditions) govern where PHI may go. Sector regulators can restrict cross-border transfer. In practice, **D3/D4 stay on-prem, and D2 may go to a Taiwan region only after legal sign-off**. Today that means GCP `asia-east1` partner models or Nova in AWS `ap-east-2` (Geo).
- **Japan:** APPI, the "3 ministries 2 guidelines" for medical information systems, and the 2025 AI Promotion Act apply [Unverified details]. Prefer Standard/Regional deployments, or Bedrock Geo profiles if they are JP-only.

## B14. Governance frameworks and how they map to the platform

| Framework | Status (2026-10-17) | What TrialBox must do |
|---|---|---|
| **NIST AI RMF 1.0 + Generative AI Profile (NIST AI 600-1, July 2024)** | Voluntary. 600-1 lists 12 GAI risks (for example confabulation, data privacy, information security, value chain) with actions mapped to Govern/Map/Measure/Manage ([AI RMF](https://www.nist.gov/itl/ai-risk-management-framework), [600-1](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf)). | Use it as the **risk register taxonomy** and map each risk to a control. For example, confabulation maps to deterministic numbers and citation checks. |
| **ISO/IEC 42001:2023 (AIMS)** | Certifiable AI management-system standard ([ISO](https://www.iso.org/standard/81230.html)). Companions are 42005 and 42006 [Unverified dates]. | Fold the AI policy, impact assessments and supplier controls (model vendors, Hermes) into the QMS/ISMS. |
| **EU AI Act** | **GPAI obligations apply from 2 Aug 2025**, and Commission enforcement starts **2 Aug 2026** ([EC](https://digital-strategy.ec.europa.eu/en/policies/guidelines-gpai-providers)). The Digital Omnibus (provisional, May 2026) defers high-risk duties to **2 Dec 2027** (Annex III) and **2 Aug 2028** (Annex I). Its formal adoption is [Unverified] ([Gibson Dunn](https://www.gibsondunn.com/eu-ai-act-omnibus-agreement)). | TrialBox is a **deployer**, not a GPAI provider, unless it substantially modifies a model. If EU parties are involved, collect the providers' documentation and analyse whether **pre-screening** is high-risk. |
| **Taiwan AI Basic Act** | **In force since 2026-01-14.** The NSTC is the competent authority, MODA owns the risk-classification framework, and sector regulators (MOHW) write the rules. High-risk AI must carry warnings, and liability rules are to be defined. The Act has no penalties ([Lee and Li](https://www.leeandli.com/EN/NewslettersDetail/7566.htm), [CASRAI](https://casrai.org/guides/taiwan-ai-basic-act-explained)). The MODA framework was still unpublished in Sept 2026 [Unverified]. | Track the MODA and MOHW rules. Build high-risk-ready features now: AI-generated notices, human-in-the-loop, remedy procedures and data minimisation. |
| **FDA–EMA Good AI Practice principles (2026-01-14)** | 10 non-binding principles, including **context of use**, a risk-based approach, **risk-based performance assessment** and **life-cycle management** ([FDA](https://www.fda.gov/about-fda/artificial-intelligence-drug-development/guiding-principles-good-ai-practice-drug-development), [NSF](https://www.nsf.org/life-science-regulatory-news/fda-and-ema-release-guiding-principles-of-good-ai-practice-in-drug-development)). The Jan 2025 FDA draft guidance (7-step credibility assessment) has [Unverified] final status. | Keep a **context-of-use (COU) record per function**, each with a risk tier, evaluation evidence (§B8) and a life-cycle plan. |
| **CHAI** | An applied model card ("nutrition label", aligned to HTI-1) and draft assurance-lab certification (2024) ([CHAI](https://chai.org/chai-advances-assurance-lab-certification-and-nutrition-label-for-health-ai/)). The 2026 status is [Unverified]. | Publish a CHAI-style model card for each function and model alias. |
| **GxP / Part 11 / ICH E6(R3)** | Unchanged from prior notes. | Audit ledger, e-signatures, validation (CSA risk-based), change control, as in [Prior notes §4]. |

## B15. Implications for the spec (Part B)

### Requirements

- **REQ-LP-01 (Single gateway).** Every LLM call SHALL go through the policy gateway with workload identity, a `data_class`, `study_id`, `purpose` and `context_of_use`. Calls without a label SHALL be rejected.
- **REQ-LP-02 (Class-based routing).** D3/D4 SHALL resolve only to on-prem deployments. D2 SHALL go to the cloud only with documented legal approval, an in-country regional endpoint, ZDR or modified abuse monitoring, and optionally attested confidential computing. D0/D1 MAY go to an approved cloud region. Fallback chains SHALL stay within the class. A PHI tripwire SHALL scan all cloud-bound traffic and block on detection.
- **REQ-LP-03 (Supply chain).** Gateway, serving, guardrail and evaluation components SHALL be pinned by hash or image digest, built or mirrored internally, scanned, and accompanied by an SBOM. The LiteLLM March-2026 incident and Hermes CVE-2026-82021 are the reference threat cases.
- **REQ-LP-04 (Model registry).** Models SHALL be registered immutably (weights SHA-256, chat template, quantisation, engine digest, flags, licence, COU, eval report, approval). Gateway aliases SHALL map to registry versions, and alias changes SHALL be audited change-control events. Cloud models SHALL be pinned to dated versions with auto-upgrade disabled.
- **REQ-LP-05 (Prompt registry).** Prompts and output schemas SHALL be versioned in Git and resolved by explicit version at runtime. Each call SHALL log prompt ID, version and hash.
- **REQ-LP-06 (Guardrails).** Deterministic validators, Presidio with Taiwan recognisers, a policy classifier (gpt-oss-safeguard and/or Qwen3Guard) with a hospital-authored policy, and an injection classifier SHALL run on the paths defined per COU. Verdicts SHALL be logged, and output release SHALL be gated on them.
- **REQ-LP-07 (Structured output).** All agent → system boundaries SHALL use schema-constrained decoding plus server-side validation. Numbers and identifiers in narratives SHALL be template-injected and cross-checked.
- **REQ-LP-08 (Evaluation).** A five-tier evaluation suite (unit, task, agentic, adversarial, human) SHALL gate every model, prompt, rule or guardrail change. Evaluation logs SHALL be retained as validation evidence. MedHELM and lm-eval-harness results MAY inform selection but SHALL NOT replace COU-specific validation.
- **REQ-LP-09 (Monitoring).** Override rate, guardrail-block rate, schema-failure rate, citation-failure rate, PHI-tripwire hits, drift metrics and canary probes SHALL be monitored with control limits. A breach SHALL open a QMS deviation, and a pre-defined degradation to manual mode SHALL be available.
- **REQ-LP-10 (Telemetry).** OTel GenAI conventions SHALL be used with a pinned version. Content capture SHALL be off by default outside the PHI zone, and `tb.*` attributes SHALL carry governance context. Traces SHALL NOT be treated as the audit trail.
- **REQ-LP-11 (Caching).** Prefix caching SHALL use a cryptographic block hash and a per-class/per-study `cache_salt` for D3/D4. KV offload storage SHALL be encrypted. Response caching SHALL be limited to D0/D1 non-regulated traffic.
- **REQ-LP-12 (Batch).** Overnight bulk inference SHALL be scheduled by the workflow engine, run idempotently per chunk on a low-priority queue, and write to a gated staging area.
- **REQ-LP-13 (MCP).** Production MCP servers SHALL be first-party and inventoried. They SHALL conform to MCP 2026-07-28 (stateless, `iss` validation, CIMD, no DCR, sampling disabled), use OAuth 2.1 with audience-bound short-lived tokens and per-tool scopes, and sit behind an MCP gateway with OPA authorisation and audit. Tool descriptions SHALL be snapshot-diffed and linted in CI. Token passthrough SHALL be prohibited.
- **REQ-LP-14 (Governance).** Maintain a NIST AI 600-1-based risk register, an ISO/IEC 42001-aligned AIMS (policy, roles, impact assessments, supplier control), a COU record per function per the FDA–EMA principles, CHAI-style model cards, and a tracker for Taiwan AI Basic Act subsidiary rules (MODA/MOHW) and EU AI Act obligations where EU parties are involved.

### Component list (Part B)

| Function | Recommended | Alternative |
|---|---|---|
| Policy gateway | LiteLLM Proxy (source-built, hash-pinned, tags with fail-open off) | Envoy AI Gateway 1.x (if Kubernetes-native) |
| MCP gateway | Envoy AI Gateway `MCPRoute` + OPA ext_authz | In-house FastAPI proxy |
| Serving | vLLM (primary) + SGLang (large MoE) on DGX B200; GB10 for dev/eval [Prior notes] | TensorRT-LLM/NIM |
| Serving router | vLLM production-stack / llm-d (prefix-aware) | SGLang router |
| Intent/cost router | Small local classifier; optionally vLLM Semantic Router v0.3 | Rules only |
| Model registry | MLflow registry or Git-YAML + Harbor OCI | — |
| Prompt registry | Git + Langfuse prompt management (read-through) | LiteLLM prompts |
| Guardrails | Presidio (+ TW recognisers), gpt-oss-safeguard-20b, Qwen3Guard-8B (Gen/Stream), NeMo Guardrails for CF flow, injection classifier | Llama Guard 4 |
| Structured output | vLLM/SGLang xgrammar + Pydantic validators | Outlines |
| Evaluation | Inspect AI (agentic/COU packs), promptfoo (CI and red-team), lm-eval-harness (quant regressions), MedHELM (reference), Langfuse datasets | — |
| Observability | OTel SDK/Collector (pinned semconv) → Langfuse (PHI zone) + Prometheus/Grafana + SIEM | Arize Phoenix |
| Drift | Scheduled shadow evaluation + EWMA/CUSUM on override/block rates | Evidently |
| Cloud (D0–D2) | AWS Bedrock (Tokyo Geo / Taipei Nova Geo), Vertex regional `asia-east1` partner models with ZDR, Azure Standard/Regional in Japan (or Taiwan North once GA) with modified abuse monitoring | None (on-prem only) |
| Confidential compute | Optional: Azure NCCads H100 v5 / NVIDIA CC mode with attestation for any off-prem D2 | — |

### Recommended architecture (Part B)

```
               ┌──────────────────────── Control plane ───────────────────────────┐
               │ Model registry · Prompt/schema registry · Eval harness (Inspect, │
               │ promptfoo, lm-eval) · Policy (OPA) · Change control/QMS links   │
               └───────────────┬──────────────────────────────────┬───────────────┘
                               │ alias→version, policies           │ eval gates
Callers (Hermes CF, Temporal activities, batch jobs)               │
   │ OpenAI API + x-tb-data-class + workload identity              │
   ▼                                                               │
[Policy gateway: LiteLLM/Envoy]  authN · class routing · budgets · guardrails (Presidio,
   │                             safeguard, Qwen3Guard, injection) · PHI tripwire · logging
   ├── D0–D4 ─▶ [Serving router (prefix-aware)] ─▶ vLLM/SGLang pools on DGX B200
   │                                               (cache_salt per class/study)
   └── D0–D1 (D2 w/ approval) ─▶ Cloud regional endpoints (Bedrock Geo/Tokyo, Vertex asia-east1,
                                  Azure Standard Japan / Taiwan North when GA), ZDR / modified
                                  abuse monitoring, optional confidential GPU
[MCP gateway: Envoy MCPRoute + OPA] ─▶ first-party MCP servers (OMOP de-id, FHIR, CQL, docs, CTMS-write via engine only)
Observability: OTel GenAI (pinned) → Langfuse (PHI zone), Prometheus, SIEM; drift jobs; canaries
Audit ledger (hash-chained, WORM) ← gateway + MCP + workflow + CF hook events
```

---

## Appendix 1. Items marked [Unverified] to close before procurement

1. Hermes: exact toolset names for `disabled_toolsets`; whether `delegation.max_spawn_depth: 0` is accepted; `identity_header` semantics; signature scheme of `hooks.outbound`; fix versions for CVE-2026-7112/7113/14628/9353.
2. Portkey acquisition closing and the self-hosted feature set; LiteLLM Enterprise-only features needed (team tag enforcement, some guardrails).
3. Bedrock Geo profile scope for Tokyo/Osaka (JP vs APAC); Vertex Gemini in-region in `asia-east1`; Azure Taiwan North GA and Foundry model availability; Azure Japan Standard/Regional availability for target models; current Azure abuse-monitoring retention wording.
4. Confidential-computing GA status for GCP A3 and in Taiwan/Japan regions; DGX B200 8-GPU CC-mode performance.
5. EU Digital Omnibus formal adoption and OJ publication; MODA risk-classification framework publication; FDA Jan-2025 AI credibility guidance final status; CHAI lab certification status in 2026; ISO/IEC 42005/42006 dates.
6. Versions not re-checked in this pass (vLLM, SGLang, Temporal, Pydantic AI, LangGraph, OpenAI Agents SDK, Claude Agent SDK, Letta, NeMo Guardrails, Presidio, Inspect AI, Llama Guard 4); Qwen3Guard licence.

*All sources are cited inline. The starting points are the [Hermes docs](https://hermes-agent.nousresearch.com/docs/), the [MCP 2026-07-28 changelog](https://blog.modelcontextprotocol.io/posts/2026-07-28/), the [OWASP MCP Top 10](https://owasp.org/www-project-mcp-top-10/), the [vLLM prefix-caching design](https://docs.vllm.ai/en/latest/design/prefix_caching.html), [Azure Foundry deployment types](https://learn.microsoft.com/en-us/azure/ai-foundry/foundry-models/concepts/deployment-types), [Bedrock region compatibility](https://docs.aws.amazon.com/bedrock/latest/userguide/models-region-compatibility.html) and the [FDA–EMA principles](https://www.fda.gov/about-fda/artificial-intelligence-drug-development/guiding-principles-good-ai-practice-drug-development).*
