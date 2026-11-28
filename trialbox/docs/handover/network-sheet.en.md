# TrialBox network, port and secret sheet

**Reader:** hospital IT (the box owner hands it to IT with IT's one page, it-one-page.en.md).

Generated from the compose files below by tools/network_sheet.py (D-138). Nothing on the box is reachable from outside except the console port. No secret value is on this sheet.

**Compose files:** `deploy/docker-compose.yml`, `deploy/docker-compose.secrets.yml`, `deploy/docker-compose.identity.yml`, `deploy/docker-compose.rtx5090.yml`, `deploy/docker-compose.gb10.yml`, `deploy/docker-compose.rtxpro6000.yml`

## Listening ports

| Service | Port | On the host | Networks | Who may reach it | Runs |
| --- | --- | --- | --- | --- | --- |
| adapter | 8016 | not published | fhir-net, trialbox-net | with its own token, only: console, orchestrator; the administrator on the host (operator token) | always |
| audit-writer | none (listens on no port) | not published | trialbox-net | - | always |
| authelia | 9091 | not published | egress-net, trialbox-net | console and Caddy only (sign-in with the hospital account) | oidc (identity) |
| caddy | 443 | 0.0.0.0:443:443 | edge-net, trialbox-net | clinic PCs on the hospital LAN, port 443 only (https://TB_TLS_HOSTNAME) | always |
| console | 8090 | not published | console-net, trialbox-net | staff browsers: 127.0.0.1 by default; the hospital LAN only through the site's TLS proxy | always |
| criteria-compiler | 8012 | not published | egress-net, fhir-net, trialbox-net | with its own token, only: orchestrator; the administrator on the host (operator token) | always |
| db | 5432 | not published | fhir-net, trialbox-net | TrialBox services and fhir-store, with a password | always |
| doc-parser | 8011 | not published | trialbox-net | with its own token, only: orchestrator; the administrator on the host (operator token) | always |
| embed-service | 8014 | not published | trialbox-net | with its own token, only: lake, orchestrator; the administrator on the host (operator token) | always |
| fhir-store | 8080 | not published | fhir-net | adapter, orchestrator, criteria-compiler, db (network only, no token yet) | always |
| gateway | 8020 | not published | egress-net, model-net, trialbox-net | with its own token, only: console, criteria-compiler, doc-parser, orchestrator; the administrator on the host (operator token) | always |
| judge-sleep-init | none (listens on no port) | not published | model-backend-net | - | GPU profile (rtx5090) |
| judge-wake-init | none (listens on no port) | not published | model-backend-net | - | GPU profile (rtx5090) |
| lake | 8013 | not published | trialbox-net | with its own token, only: adapter, criteria-compiler, orchestrator; the administrator on the host (operator token) | always |
| llm-service | 8000 | not published | model-backend-net | model-guard only (model-backend-net; the key on every call, D-177) | GPU profile |
| llm-stub | 8000 | not published | model-net | gateway only (model-net) | no-GPU profile |
| llm-verifier | 8000 | not published | model-backend-net | model-guard only (model-backend-net; the key on every call, D-177) | GPU profile (rtx5090, gb10, rtxpro6000) |
| mail-gateway | 8015 | not published | egress-net, trialbox-net | with its own token, only: console, orchestrator; the administrator on the host (operator token) | always |
| model-guard | 8000 | not published | model-backend-net, model-net | gateway only (model-net) | GPU profile |
| model-swap-init | none (listens on no port) | not published | model-backend-net | - | GPU profile (rtx5090) |
| orchestrator | 8010 | not published | egress-net, fhir-net, trialbox-net | with its own token, only: console, mail-gateway; the administrator on the host (operator token) | always |

## Networks

| Networks |  |
| --- | --- |
| trialbox-console | the console's published port only: no NAT out, no outside names; nftables drop the rest (deploy/network.sh) |
| trialbox-edge | out of the box only to the hosts below (nftables, deploy/network.sh) |
| trialbox-egress | out of the box only to the hosts below (nftables, deploy/network.sh) |
| trialbox-fhir | internal: no route out of the box |
| trialbox-model-backend | internal: no route out of the box |
| trialbox-model-net | internal: no route out of the box |
| trialbox-net | internal: no route out of the box |

## Outbound

With no site settings the box reaches nothing outside. ClinicalTrials.gov is offline by default: the trials come from the reference data pack of each signed update (TB_CTGOV_MODE=offline). A hospital that chose live at install (TB_CTGOV_MODE=live) opens criteria-compiler to clinicaltrials.gov:443 (public registry, no patient data). Each line below opens only when its setting is filled in.

| Service | Destination | Why | Opened by |
| --- | --- | --- | --- |
| mail-gateway | SMTP_HOST:SMTP_PORT | outbound mail (hospital SMTP / Exchange) | SMTP_HOST |
| mail-gateway | IMAP_HOST:IMAP_PORT | intake mailbox | IMAP_HOST |
| gateway | external model endpoints of models/routing.yaml | model endpoint (refused for D3/D4 data) | the endpoint's URL |
| criteria-compiler | clinicaltrials.gov:443 | ClinicalTrials.gov public registry (COHORT) | TB_CTGOV_MODE=live (chosen at install; the default is offline) |
| orchestrator | NHI_TWPAS_BASE_URL | NHI TWPAS (SUBMIT only) | NHI_TWPAS_BASE_URL |
| orchestrator | host:port of TB_REDCAP_API_URL | REDCap server (https only) | TB_REDCAP_API_URL |
| any | EGRESS_EXTRA | site additions | EGRESS_EXTRA |

## The host (outside the containers)

| From -> to | Why | Opened by |
| --- | --- | --- |
| clinic PCs -> TB_TLS_HOSTNAME:443 (caddy) | the console over https; nothing else is published | docker-compose.identity.yml, TB_TLS_HOSTNAME |
| authelia -> domain controller:636 (LDAPS) | sign-in with the hospital account (optional) | EGRESS_EXTRA authelia=<dc>:636, profile oidc |
| host -> hospital NTP server, UDP 123 | the clock of every audit row (check_host: clock in sync) | the host's time service (systemd-timesyncd or chrony) |
| host -> backup share (TB_BACKUP_TARGETS), NFS 2049 or SMB 445 | the off-box backup copy (RUNBOOK §5) | TB_BACKUP_TARGETS, a share mounted on the host |

## Secrets (names and places only)

| Secret | Kept in | Given to |
| --- | --- | --- |
| actor-signing key | deploy/secrets/services/actor-sign.key (0600) | console only, at /run/secrets/tb_actor_sign_key; its copy for verification (deploy/secrets/services/actor/keys) in the orchestrator only |
| model key | deploy/secrets/model/llm.key (0600) | gateway, model-guard only, at /run/secrets/tb_llm_key |
| model key, the vLLM servers' copy (VLLM_API_KEY) | deploy/secrets/model/vllm.env (0600, root) | llm-service, llm-verifier only |
| oidc_client_secret | deploy/secrets/authelia/oidc_client_secret.txt (0600, root) | console only, at /run/secrets/oidc_client_secret (OIDC on) |
| service token: adapter | deploy/secrets/services/adapter.token (0600) | adapter only, at /run/secrets/tb_service_token |
| service token: console | deploy/secrets/services/console.token (0600) | console only, at /run/secrets/tb_service_token |
| service token: criteria-compiler | deploy/secrets/services/criteria-compiler.token (0600) | criteria-compiler only, at /run/secrets/tb_service_token |
| service token: doc-parser | deploy/secrets/services/doc-parser.token (0600) | doc-parser only, at /run/secrets/tb_service_token |
| service token: embed-service | deploy/secrets/services/embed-service.token (0600) | embed-service only, at /run/secrets/tb_service_token |
| service token: gateway | deploy/secrets/services/gateway.token (0600) | gateway only, at /run/secrets/tb_service_token |
| service token: lake | deploy/secrets/services/lake.token (0600) | lake only, at /run/secrets/tb_service_token |
| service token: mail-gateway | deploy/secrets/services/mail-gateway.token (0600) | mail-gateway only, at /run/secrets/tb_service_token |
| service token: orchestrator | deploy/secrets/services/orchestrator.token (0600) | orchestrator only, at /run/secrets/tb_service_token |
| operator token | deploy/secrets/services/operator.token (0600) | the host only; never in a container |
| token registry (sha256 of each token) | deploy/secrets/services/public/tokens.json | every TrialBox service (hashes only, not secret) |
| POSTGRES_PASSWORD (role hapi) | deploy/.env (0600, root) | db, fhir-store |
| POSTGRES_WF_PASSWORD, TB_DB_URL (role trialbox) | deploy/.env (0600, root) | db; adapter, console, criteria-compiler, gateway, lake, mail-gateway, orchestrator |
| TB_DB_PW_<SERVICE> (one role per service) | deploy/.env (0600, root) | db; each service its own only |
| IMAP_PASS, SMTP_PASS | deploy/.env (0600, root) | mail-gateway |
| KEK passphrase | a root-only file (--kek-passphrase-file, 0600) or stdin (RUNBOOK §16) | the host only; never in a container's configuration, the environment or a file other than the operator's root-only one (removed once used) |
| TB_KMS_TOKEN | KMS token (RUNBOOK §17) | adapter, orchestrator |
| CLOUD_LLM_API_KEY (empty by default) | deploy/.env (0600, root) | gateway |
| site_hmac.key, pid_map.key, REDCap API tokens | volume tb-secrets (/run/secrets/trialbox) | adapter, orchestrator |
| Caddy's internal CA keys (TB_TLS_MODE=internal) | volume caddy-data | caddy only; never copied out |
| Authelia secrets and the LDAP bind password | deploy/secrets/authelia/ (0600, root) | authelia only |
| backup public key | deploy/secrets/backup.pub | the backup (encrypts only) |
| backup private key | USB stick | hospital IT, sealed envelope; never on the box |
| vendor update key (public) | deploy/keys/vendor_ed25519.pub | tools/apply_update.sh |

Rotate: sudo python3 -m tools.trialbox secrets rotate [--service NAME] (RUNBOOK §5 'Secrets').
