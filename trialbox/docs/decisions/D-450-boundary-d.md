# D-450 Boundary, part d: one SSRF guard, the scrubber on in every service, secrets out of the shared env file, the mTLS position

- **Task:** T-212d (`docs/plan/28-master-plan-v6.md` §6.2, "as TB-ASSESS-01" T-212)
- **PR:** this branch (`agent/T-212d-boundary-d`)
- **Date:** 2026-11-11
- **Status:** proposed (merges on green CI)
- **Closes:** OPS-057 (in part, see Open); PV-10 (the scrubber's chart-number rule); the D-114 and D-138 "Not done"
  items of plan §6.2.9 (the mTLS position; the model key's copies in `deploy/.env`)
- **Builds on:** T-212b / D-437 (the model key file), T-212c / D-378 (a database role per service), T-604 / D-388
  (the perimeter check, `deploy/egress.py`), T-654 (secret and static scans in CI), T-608 / D-445 (the two model
  key copies must agree), D-128 / D-138 (one token per service), T-109b (signed actor assertions with a nonce)

## What was there and what is built here

| Item | State before | Here |
| --- | --- | --- |
| SSRF guard | none: REDCap, OIDC, ClinicalTrials.gov and NHI calls used a plain `httpx` client; only REDCap refused `http://` | built: `tb_common.http.guarded_client` |
| Scrubber rule on | the identifier patterns ran in every `make_app` service, but the chart-number rule was never switched on (`set_mrn_regex` had no caller, PV-10); the console and the audit writer did not set up the JSON logger at all; no secret pattern | built: `setup_logging` switches every rule on; console, audit writer, model-guard wired |
| "gitleaks in CI" | already there in substance: T-654's `security` job runs detect-secrets over every tracked file (`tools/security_scan.py secrets`) | nothing added (see 4) |
| Secrets out of `env_file` | the overlay cleared a deny list; the eight `TB_DB_PW_*` (D-378), the KEK passphrase and KMS token, the host tools' keys and every secret in `llm-stub` reached every service; the vLLM servers took the model key from `deploy/.env` interpolation | built: the overlay clears them, vLLM reads `secrets/model/vllm.env`, the host tools read the key file, a rendered-config test |
| mTLS position (D-114) | "not done" | recorded (5) |

## Decision

1. **One guard for steerable outbound calls.** Every outbound HTTP call whose address a person or an outside document
   can set goes through `tb_common.http.guarded_client` (`EgressGuard` + `GuardedTransport`): the REDCap URL an
   administrator types (S36, `rc_bridge.client`), the OIDC discovery document and every endpoint it names
   (`console.oidc`), ClinicalTrials.gov in live mode (`criteria_compiler.ctgov`) and the NHI endpoint (SUBMIT). The rule:
   - the scheme is `https`; `http` only with `TB_ENV` DEV or TEST;
   - a host that the C resolver would read as an IPv4 address written another way (`2130706433`, `0x7f000001`,
     `0177.0.0.1`, `127.1`) is refused;
   - the name is resolved when the connection is made, every address it gives is checked, and the connection goes to
     exactly the checked address (the name stays in the Host header and the TLS server name, so the certificate is
     still checked against the name). A name that answers a public address at one moment and the box's at the next
     (DNS rebinding) cannot pass. Each redirect hop is a new request to the transport and is checked again;
   - metadata addresses (169.254.169.254, fd00:ec2::254, 100.100.100.200, 169.254.170.2, 192.0.0.192), link-local,
     unspecified, multicast and broadcast are refused always, declared or not; IPv6 spellings of an IPv4 address
     (mapped, 6to4, Teredo, NAT64) are judged by the IPv4 address they carry;
   - loopback, the private ranges (the box's networks, the hospital LAN), carrier NAT and reserved ranges are allowed
     only when the destination (host and port) is declared: the calling service's rows of the box's egress table (the
     same settings `deploy/egress.py` reads: SMTP/IMAP, ClinicalTrials.gov in live mode, `NHI_TWPAS_BASE_URL`,
     `EGRESS_EXTRA`; a test holds the two together) or the operator's own setting for that caller (the OIDC issuer,
     which is Caddy on the box). A REDCap server on the LAN is therefore an `EGRESS_EXTRA` row
     (`orchestrator=redcap.hospital:443`), as the host firewall already requires;
   - the proxy variables are not used (a proxy would connect on the guard's behalf).
   A refusal is `EgressRefused` (an `httpx.ConnectError`: nothing was sent), logged as `egress refused` with the host
   and the reason, and each caller turns it into its own error (`RC-UPSTREAM`, `OidcError`, `CtgovError`,
   `NotSubmitted`). The gateway's model endpoints stay with the gateway's own perimeter check (T-604); the service
   clients between the box's own services (`ServiceClient`, the lake and embed clients) are not steerable and are not
   guarded.
2. **The scrubber is on in every service.** `setup_logging`, which every service runs at start (through `make_app`, and
   now in the console's factory, the audit writer and, for its request lines, model-guard), switches on the site's
   chart-number rule (`settings.mrn_regex`; the contract's default `^\d{8}$` when no site configuration is readable,
   so the rule is never off) and the secret rules: a value after a secret's name (`token=`, `"api_key": "..."`,
   `X-TB-Service-Token:`), a bearer or basic credential, the password inside a database URL (between the user name and the `@`), and every
   secret value the process holds (the environment variables and `*_FILE` files named like a password, key, token or
   secret, at least 8 characters). The gateway's mounted registry app no longer relabels the gateway's log lines as
   `model-registry`.
3. **Secrets out of the shared env file, as far as compose allows.**
   - The secrets overlay now clears the eight `TB_DB_PW_*` in every TrialBox service (each reads its own password
     only inside its own `TB_DB_URL`), `TB_KEK_PASSPHRASE` and `TB_KMS_TOKEN` outside the adapter and the
     orchestrator (the two services that unwrap the site keys), the host tools' keys (`TB_BAKEOFF_API_KEY`,
     `TB_GPU_KEY`, `TB_RC_CASSETTE_TOKEN`, `TB_DEMO_PASSWORD`, `TB_KEK_NEW_PASSPHRASE`, the acceptance mail passwords)
     everywhere, `OPENROUTER_API_KEY` outside the gateway, and everything in `llm-stub` (which had every secret).
   - **The vLLM servers' key moves out of `deploy/.env`.** vLLM has no `*_FILE` setting, so each vLLM service in the
     base file and every GPU overlay (gb10, rtx5090, rtxpro6000, shared-quota) reads its own env file
     `deploy/secrets/model/vllm.env` (`VLLM_API_KEY=<key>`, 0600, root), written by `trialbox secrets init` and
     `rotate --service model` with `llm.key`, and rewritten from `llm.key` whenever it is missing or differs.
     `trialbox update` makes both files on every GPU box. The file is `required: false` so that every compose render
     (tests, CI, a stub box) works without it; a GPU box without it runs vLLM open behind model-guard, which
     `doctor --serving` FAILs at install and update in PRODUCTION.
   - **The host tools read the key file first:** `doctor --serving` (through `gateway.policy.endpoint_key`, with
     `TB_LLM_API_KEY_FILE=/app/deploy/secrets/model/llm.key` set by `install.sh` and `trialbox update`) and
     `noisy_neighbour`.
   - **The rehearsal's `missing-key` drill** empties `deploy/secrets/model/llm.key` instead of `deploy/.env`'s copy
     (the gateway reads the file), and its `doctor` reads the file as the gateway does; its `guard` phase reads the
     key from the file too (it read the cleared variable since D-437).
   - **What stays in `deploy/.env`, and why.** `deploy/.env` is still every TrialBox service's `env_file`: it carries
     dozens of ordinary settings, and replacing it by an explicit list per service is a change only a compose run can
     prove. The passwords that compose interpolates (`POSTGRES_PASSWORD`, `POSTGRES_WF_PASSWORD`, `TB_DB_PW_*` into
     each `TB_DB_URL` and the db container) and the mail and cloud keys stay there: the db and HAPI images and the
     mail settings take them as variables. The model key's `TB_LLM_API_KEY` copy stays for model-guard on a box
     started without the secrets overlay (no container under the overlay receives it); `secrets` keeps it equal to
     the file and a copy that differs is still refused (D-445).
   - **The test.** `tests/unit/test_compose_secret_reach.py` renders eight compose file sets with
     `docker compose config`, every secret the box knows (every `.env.example` name, every declared `TB_*` setting and
     every interpolated variable named like a password, key, token or secret) set to its own marker, and fails when a
     marker reaches a service off that secret's list, under any variable name. A new declared secret fails it until
     the overlay clears it or the list names its service.
4. **No second secret scanner.** T-654's detect-secrets job covers the tracked tree with the plugins for real key
   formats. gitleaks would add a scan of the git history; it could not be run in this session (fetching its binary
   was not allowed), so no finding shows it is needed. Adding it is a supply-chain change (a pinned action or
   binary) with no evidence today; left as a finding for the owner (see Open). No waiver was added.
5. **mTLS position (D-114).** Service-to-service calls on the box are protected by: a token per service, read from a
   compose secret, the callee accepting only its own callers (D-128, D-138); the gateway routing on the verified
   caller (D-437); the console naming a user to the orchestrator only by a signed assertion with a nonce
   (T-109b, PR #269); the services on internal Docker networks with no route out and the host's nftables table
   (D-377, D-388); one database role per service (D-378). The traffic never leaves one kernel's bridges, so TLS
   between the containers would protect against nobody the tokens do not already stop (a process that can read the
   bridge can read the token files too). **mTLS is added when a service-to-service call crosses a physical network
   or a host boundary**: the two-device form (T-214: the Spark link is WireGuard or mTLS, keys from the install
   ceremony), a platform deployment whose network policy is not enforced (T-319's drill fails), or any service moved
   off the box. Until then it is not built.

## Consequences

- A REDCap server, an OIDC provider or a registry mirror on a private address works only when it is declared; the
  error names the reason (`private`, `loopback`, `metadata` ...). The host firewall already lets the orchestrator
  reach a REDCap server only through an `EGRESS_EXTRA` row; the same row now satisfies the guard.
- Log lines lose any 8-digit number standing alone where no site pattern is configured (a date written `20261111`
  becomes `[MRN]`).
- A GPU box's `deploy/secrets/model/` holds `llm.key` and `vllm.env`; backups and the lost-box list already cover the
  folder (the network sheet lists both).

## Open

- **OPS-057, the structural half.** A secret the box does not know of (a new name that is neither declared, nor in
  `.env.example`, nor interpolated) put into `deploy/.env` still reaches every TrialBox service; the test shows it
  (`test_a_new_secret_is_caught`). Per-service env files instead of the shared one need a compose run to prove.
- The `TB_LLM_API_KEY` copy in `deploy/.env` can go once `install.sh` stops writing it and the box rehearsal stops
  checking it.
- A scan of the git history for secrets (gitleaks or detect-secrets over `git log -p`): the owner decides.
- Only a compose run proves: the vLLM servers start with `vllm.env`, the rehearsal drills pass, the guard reaches a
  real REDCap over TLS with the pinned address and the name as SNI.

## Dropped (D-311)

No security sign-off or owner review step.
