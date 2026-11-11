# D-367 The host tree in the signed release: `releases/<id>`, `current`, links

- **Task:** T-631 (wave 1, lane 2E, `docs/plan/28-master-plan-v6.md` §6.2.4)
- **PR:** this branch (`agent/T-631-host-tree`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** OPS-010; OPS-020 (the host-tree part)
- **Builds on:** D-77 (signed bundle), D-138 (update path), D-210 (update safety), D-340 (release record)

## Context

The deep review of 2026-11-10 (`docs/reviews/2026-11-10-deep-review/09-operations.md`, OPS-010) found that the
compose files, the host tools and the release's configuration came from an unsigned copy ("copy the release to
`/opt/trialbox`") and that no update ever replaced them. `copy_other` wrote the bundle's loose files to
`deploy/updates/<bundle>/files`, and nothing read them back. A release that adds a service, a volume or a compose
variable could not be shipped.

## Decision

1. **One payload of kind `host`.** `tools/make_bundle.sh` packs the host tree into every bundle:
   `trialbox-host.tar` (`tools/host_tree.py pack`). It holds what git holds under `deploy/`, `tools/`, `libs/` and
   `schemas/`, plus `.env.example`, `pyproject.toml`, `NOTICE` and `CHANGELOG.md`. Its first member is
   `HOST-SHA256SUMS`. It never holds the site's own files (the STATE list: `deploy/.env`, `settings.yaml`, `secrets/`,
   `keys/`, `updates/`, `refdata/`, `models/`, `site/`, `ops/`, `logs/`, `backups/`, `image-pins.json`,
   `pgbackrest/repo`). The tar is deterministic: sorted, owner 0, a fixed mtime.
2. **Checked like any payload, and then some.** The manifest names the tar's sha256, so a changed byte anywhere in it
   is refused before anything is staged. `verify_update.py` then checks the tree itself before staging completes:
   `HOST-SHA256SUMS` first, regular files only (no link, no device), safe paths inside the tree, no STATE path, every
   file listed with a matching sha256, and `deploy/docker-compose.yml` present. A bundle may hold at most one host
   tree. Manifest schema 1.3.0 and release schema 1.1.0 add the kind.
3. **The layout on the box.** The install folder `BASE` (`/opt/trialbox`) holds:
   - `releases/<bundle id>/` with the tree as signed;
   - `current`, a link to `releases/<bundle id>`;
   - links `BASE/tools`, `libs`, `schemas` and the top-level files, pointing to `current/...`;
   - the real folder `BASE/deploy/` with the site's files, where every release entry is a link to
     `../current/deploy/...`.

   Folders that hold a STATE path (such as `deploy/pgbackrest`) stay real, with links inside them. Inside each
   release, every STATE path links back to `BASE/deploy/<path>`. A tool that resolves its own path into the release
   (`Path(__file__).resolve()`) still finds the site's files. Every path the box already used keeps working: `deploy/.env`,
   `tools/apply_update.sh`, `COMPOSE_FILE`, the cron lines and `docker compose --project-directory deploy`.
4. **Switch and roll back.** The install or update unpacks the tree into `releases/.<id>.partial`, renames it, and
   switches `current` with one rename of a new link. Then it refreshes the links. A link to a path the new release
   dropped is removed. A real file or folder that a release path replaces (a copied install) is moved to
   `releases/.replaced-<time>/` and is never deleted. In the update path, the host tree is applied first. So the
   restart and the check run the new compose files. The rollback point records the previous release before
   anything moves. A rollback (after a failed check, or `apply_update.sh rollback` after a crash) names the previous
   release again before the restart, and removes the release it unpacked. On the first host tree of a copied install,
   it removes the links and moves the copied files back.
5. **The first install runs from the signed tree.** `deploy/install.sh` from the media copy verifies and loads the
   bundle, which switches `current`. It then runs again as `deploy/install.sh`, now a link into the signed tree, with
   the same arguments (`TB_INSTALL_SIGNED` names the release so the second run does not load again). A bundle
   without a host tree is refused by the installer.
6. **Status.** `python3 -m tools.host_tree status --base /opt/trialbox` names the current release and checks it against
   its `HOST-SHA256SUMS` (exit 1 on any difference).

## Consequences

- An update can change a compose variable, add a service or replace a host tool, and a failed check puts the old one back.
  The drill is `tests/unit/test_host_tree.py`: a stand-in `docker` records which compose file each `up` ran.
- A box verifier older than manifest 1.3.0 refuses the kind `host`. The first release with a host tree goes onto
  an older box through `deploy/install.sh`, not `apply_update.sh`.
- The demo VM (`--target demo`) and the in-process drill box ignore the host tree: they have no host compose files.
- Remaining: the doctor does not yet run `host_tree status`. The Windows checklist still says "copy the release"
  (the copy is now only the bootstrap). No real Docker rehearsal has run with a host tree yet (T-213b).
