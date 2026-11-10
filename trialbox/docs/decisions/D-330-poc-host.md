# D-330 The PoC host: one VM, image by digest, Cloudflare Access through a tunnel, kept data on its own disk

- **Task:** T-509 (wave P of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2.3)
- **PR:** this branch (`agent/T-509-poc-host`)
- **Date:** 2026-11-10
- **Status:** accepted
- **Closes:** OPS-008; OPS-003 (the front door); UX-002 (the always-on host; persistence itself is T-505b)

## Context

TB-POC-01 §3 asks for one GCP VM with two demo sites, HTTPS with a real host name, an identity front door that lets
in only the testers' and the owner's addresses, data that survives a restart, a daily snapshot, and a scripted end
of life. The old hosted-demo script built the image on the VM from a git clone at every boot, pulled `caddy:2` by
tag, and served `sslip.io` names open to anyone who knew them (OPS-008, OPS-003). The owner keeps Render on the free
plan, which cannot run the demo (`demo/README.md`). Q-03 approved about US$110 a month; each paid step is still shown
first.

## Decision

1. **One script for the owner, one for the VM.** `deploy/gcp/poc-host.sh` (cost, image, door, create, rebuild,
   status, reset, purge) and `deploy/gcp/hosted-demo-startup.sh` (the boot script). A command that changes the cloud
   runs only with `--yes`; without it, and with `--dry-run`, it prints every command and runs none. The tests use
   that mode only.
2. **Image by digest, built once.** `image` builds from a clean `git archive` of tag `poc-1` on the owner's machine
   and pushes to Artifact Registry in `asia-east1`; it refuses to build the tag a second time without `--force`. The
   VM gets `REGISTRY/…@sha256:<digest>` in metadata and refuses anything else. Caddy and `cloudflared` are pinned by
   digest in the boot script.
3. **Front door: Cloudflare Access through a Cloudflare Tunnel**, not Google IAP. Access sends a one-time PIN to a
   listed address, so the testers need no Google account; Access and Tunnel are free under 50 users, where IAP
   needs a load balancer (about US$18 a month) and Google accounts. The VM's own network allows only SSH from
   Google's IAP range: no web port is open, so there is no path around the door. `cloudflared` checks the Access
   token for the app before it forwards (`access.required`); Caddy refuses any request without the token header,
   before the console. Without a front-door session the URL shows Cloudflare's sign-in, never `/login`.
4. **TLS.** The public certificate of the real host name is served at Cloudflare's edge. The tunnel reaches Caddy
   over TLS with Caddy's local CA (`tls internal`), whose root `cloudflared` is given as its CA pool. A public
   certificate on the VM itself would need an open port 80 or a Caddy build with a DNS plugin; neither is worth it
   behind the tunnel. Secure cookies stay on.
5. **Kept data on a separate disk.** Each site runs with `TB_DEMO_KEEP=1` (T-505b) on `/srv/trialbox/<site>`, a
   persistent disk that is not deleted with the VM. A boot never formats a disk that has a file system and never
   deletes data. A snapshot schedule copies the disk daily at 17:00 UTC and keeps 70 days; `rebuild` takes one more
   snapshot first. Resetting a site is a separate command.
6. **Secrets.** The accounts files, the owner's password and the tunnel token live in Secret Manager; only the VM's
   own service account may read them, into root-only files. They are never in metadata, on a command line, or in
   output. The Cloudflare API token travels in a header read from a pipe; the testers' addresses are read from the
   environment and never printed.
7. **End of life.** `purge` deletes the VM, the data disk, every snapshot (by label and by source disk), the schedule,
   the network, the image repository, the secrets, the service account and the Cloudflare entries; then it lists
   VMs, disks and snapshots again and fails unless none is left. It writes a record without names or secrets.
8. **Dropped from the old script.** The public-data site (`tools.public_e2e`, which needs MedTxt in the build
   context) and the `sslip.io` names are not on the PoC host.

## Consequences

The host needs a domain on Cloudflare (about US$10 a year) and a Zero Trust team. Nothing here was run against a
cloud: the Cloudflare and GCP calls are checked as printed commands only, and the first real run may need small
fixes. Per-address sign-in throttling behind the proxy sees one address until the demo server reads forwarded
headers (a finding for the identity cards). T-119 (cloud hygiene) builds on the same boot script.
