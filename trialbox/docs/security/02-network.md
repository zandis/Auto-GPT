# 2. Network

`trialbox-net` and `trialbox-model-net` are internal (no route out). `deploy/network.sh apply` loads an nftables
table that drops every packet from the box's networks to the outside, except:

| From | To | When |
| --- | --- | --- |
| mail-gateway | `SMTP_HOST:SMTP_PORT`, `IMAP_HOST:IMAP_PORT` | always |
| gateway | a cloud model (`CLOUD_LLM_BASE_URL`) | only when set; never for D3/D4 data; the PHI guard runs first |
| criteria-compiler | clinicaltrials.gov:443 | `TB_CTGOV_MODE=live` (public registry; `cassette` closes it) |
| orchestrator | `NHI_TWPAS_BASE_URL` | only when set (SUBMIT) |
| any service | `EGRESS_EXTRA` entries | site additions, listed on the network sheet |

Container addresses change on restart, so re-apply from a systemd unit after Docker starts
(`ExecStart=/opt/trialbox/deploy/network.sh apply`, plus a path unit or a 5-minute timer). `sudo make test-egress`
proves it on a running stack: a fake outside host is reachable before the rules and only the allowed pairs after.

Only the console is published, on `127.0.0.1:8090`. For the hospital LAN the identity overlay
(`deploy/docker-compose.identity.yml`, D-193) puts Caddy on 443 in front of it and stops publishing 8090: TLS 1.2 or
1.3 with Caddy's internal CA (its root installed on the staff PCs) or the hospital's certificate (`TB_TLS_MODE`,
`TB_TLS_CERT_FILE`, `TB_TLS_KEY_FILE`; `console.cli check-tls` checks the files, the key and the host name first),
HSTS, and Secure session cookies. Authelia, when used, reaches the hospital AD by LDAPS only through an
`EGRESS_EXTRA` entry (`authelia=<domain controller>:636`). Steps: [Runbook §12](../RUNBOOK.md#12-identity-and-tls-d-192-d-193). HAPI and Postgres have no per-caller token yet: network isolation and a password only
(D-138, not done).
