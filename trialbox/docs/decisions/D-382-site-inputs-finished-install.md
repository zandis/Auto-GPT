# D-382 Site inputs and a finished install

- **Task:** T-632 (wave 1, `docs/plan/28-master-plan-v6.md` §6.2.4)
- **PR:** this branch (`agent/T-632-site-inputs`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** OPS-011, OPS-012, OPS-013, OPS-014 (`docs/reviews/2026-11-10-deep-review/09-operations.md`)
- **Builds on:** D-138 (installer and network sheet), D-176 (box rehearsal), D-192 and D-193 (identity and TLS),
  D-274 (backup cron, T-117b), D-367 (host tree in the signed release)

## Context

The deep review found that a real site could not give the box its mapping file or its feed (OPS-011): the adapter
read mappings only from the image, the feed mount defaulted to a test fixture and its mount point was fixed. The
RUNBOOK's answers example failed (OPS-012). After `install.sh` no clinic PC could use the box: no TLS, an `http://`
URL, no enrolment code for the first administrator (OPS-013). The network sheet crashed on the identity overlay and
the installer hid the error (OPS-014).

## Decision

1. **The site's mapping folder.** A site's mapping lives in `deploy/site/mapping/` (site state, kept by every
   update, D-367). Compose mounts it read-only into the adapter at `/etc/trialbox/mapping`. A relative
   `data_source.mapping` (`mapping/tw_core/<site>.yaml`) is looked up there first (and in `TB_MAPPING_DIR`), then in
   the image (`services/adapter/mapping/site.py`). A relative `extends` that the site folder does not hold is taken
   from the image, so the templates work unchanged. The wizard and `doctor` look the same way. The installer copies a
   `mapping/` folder beside the answers file into `deploy/site/mapping/`, never over a file already there. The
   identity overlay's images ride in every bundle (`tools/make_bundle.sh`).
2. **The feed folder.** The wizard asks for the host folder (`data_source_host_dir`, written as `TB_SOURCE_DIR`) and
   writes the settings' `data_source.path` as `TB_SOURCE_MOUNT`; compose mounts the one at the other. In PRODUCTION
   `install.sh` stops without `TB_SOURCE_DIR` or when it is not a folder.
3. **A finished install.** The wizard asks the console's DNS name and the certificate mode (`TB_TLS_HOSTNAME`,
   `TB_TLS_MODE`, the hospital's files). `install.sh` asks for the name when it is missing and stops without one in
   PRODUCTION. It runs `console.cli check-tls` before the stack starts and adds `docker-compose.identity.yml`. Both
   cron files (log retention, backups) are installed or, in PRODUCTION, the install stops. The first administrator's
   enrolment code is printed once. The install ends with the `https://` URL, which it fetches from the box with the
   certificate the clinic PCs will see (Caddy's root, copied to `deploy/secrets/tls/caddy-root.crt`, in internal
   mode). Remaining FAIL lines (the host check, the network sheet, the URL, the enrolment code) are listed and the
   install exits 1.
4. **The judge is named from the configuration.** `tools/pin_model.py --name-judge <gpu>` prints the judge role's
   alias, the registry's `model_name` of the build the profile serves, and the site's pin. The installer prints that
   line; no model name is written into the installer.
5. **The network sheet renders every overlay.** It reads compose's `!reset` and `!override` as compose does. The
   identity overlay is part of the vendor sheet. A new section lists the host's own flows: 443 from the clinic PCs,
   LDAPS from Authelia, NTP and the backup share.
6. **Every RUNBOOK §1 command runs in a test** (`tests/unit/test_runbook_install_commands.py`). A command the test
   machine cannot run whole (the installer, `make` builds, `network.sh apply`) runs as far as it can, and the test
   says how.

## Consequences

- A box installed before this change keeps its settings; re-running the installer in PRODUCTION now asks for
  `TB_SOURCE_DIR` and `TB_TLS_HOSTNAME` in `deploy/.env`.
- The console's own port is no longer published on a PRODUCTION box: the box rehearsal reaches the console through
  Caddy (`tools/rehearse_box/box.sh`).
