# 2. Network

`trialbox-net` and `trialbox-model-net` are internal (no route out). `deploy/network.sh apply` loads an nftables
table that drops every packet from the box's networks to the outside, except:

| From | To | When |
| --- | --- | --- |
| mail-gateway | `SMTP_HOST:SMTP_PORT`, `IMAP_HOST:IMAP_PORT` | always |
| gateway | the routing table's open model endpoints (zone external or dev_public) | only when the URL is set and the endpoint is open in `TB_ENV`; never for D3/D4 data. `CLOUD_LLM_BASE_URL` opens nothing (D-388) |
| criteria-compiler | clinicaltrials.gov:443 | `TB_CTGOV_MODE=live` (public registry; `cassette` closes it) |
| orchestrator | `NHI_TWPAS_BASE_URL` | only when set (SUBMIT) |
| any service | `EGRESS_EXTRA` entries | site additions, listed on the network sheet; none gives a service other than the gateway a model host, and one for the gateway must be a routing-table endpoint above (D-388) |

Kept across a reboot (D-377): `apply` writes the box's subnets to `/var/lib/trialbox/egress-state.json`.
`trialbox-egress.service` runs `network.sh restore` before `docker.service` and `trialbox.service`: the closed table for
those subnets, with no allow rule, so a container Docker restarts by itself has no way out. `trialbox.service` starts
the stack, then runs `apply` for the new container addresses; `trialbox-egress-refresh.timer` re-applies every two
minutes when the table would change (a restarted container gets a new address), and `trialbox-egress-watch.service`
(`network.sh watch`, D-388) does it at once when a container of the stack starts. With the stack down, `apply` loads the
closed table, never an empty one. `sudo make test-egress`
proves it on a running stack: a fake outside host is reachable before the rules and only the allowed pairs after,
the gateway's model endpoint included.

The perimeter is checked (D-388): in PRODUCTION on topology A the gateway does not start when a perimeter endpoint
(`TB_EP_SERVING_URL`, `TB_EP_VERIFIER_URL`, `TB_EP_EMBED_URL`) resolves to an address that is not loopback or private,
resolves the names again every minute while it runs and refuses every call while one is off the box.
`trialbox doctor` prints each endpoint's addresses (check `perimeter_addresses`).

Only the console is published, on `127.0.0.1:8090`. For the hospital LAN the identity overlay
(`deploy/docker-compose.identity.yml`, D-193) puts Caddy on 443 in front of it and stops publishing 8090: TLS 1.2 or
1.3 with Caddy's internal CA (its root installed on the staff PCs) or the hospital's certificate (`TB_TLS_MODE`,
`TB_TLS_CERT_FILE`, `TB_TLS_KEY_FILE`; `console.cli check-tls` checks the files, the key and the host name first),
HSTS, and Secure session cookies. Authelia, when used, reaches the hospital AD by LDAPS only through an
`EGRESS_EXTRA` entry (`authelia=<domain controller>:636`). Steps: [Runbook §12](../RUNBOOK.md#12-identity-and-tls-d-192-d-193). HAPI and Postgres have no per-caller token yet: network isolation and a password only
(D-138, not done).
