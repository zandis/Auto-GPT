# D-1381 The support bundle as a button: allow-listed fields only, the administrator only, audited (10K-5)

- **Task:** lane K, plan 10 row 10K-5 (review 18, SO-5: "`doctor` on the console, grouped, in three languages, with
  the next action; the support bundle as a button"). This decision is the second half only, the button; `doctor` on
  the console is not in it. · **Date:** 2026-11-20
- **The owner's ruling:** the button is an export, so it waited for the owner. The owner ruled on 2026-11-19 at
  20:20 UTC: "10K-5 support-bundle button: yes." This decision builds that and no more.
- **Decision:**
  - **Allow-list, not leave-out (the review of 48b3210c):** three reviews (of 83a0640a, 31935cc4 and 48b3210c) each
    found another free-text source that reached the button's bundle through a leave-out list: the service logs, the
    update history's error texts, `.env` values the redaction did not know, then the audit chain's re-anchor reason
    a person typed, typed and mounted paths and command lines. So the button's bundle is built the other way round.
    Every member is made by `tools/trialbox/ops_support.py` from an explicit list of allowed fields
    (`tools/trialbox/support_fields.py`, `SCHEMAS`), and every allowed value is of a closed kind: a number (never a
    yes/no), a yes/no, null, a time (an ISO date or date and time and nothing else), a value from a fixed set, or a
    string matching a strict pattern declared next to the field. Anything else, a key not on the list or a value not
    of its kind, is dropped and counted: `MANIFEST.json` lists `"<member>: N field(s) not on its allow-list"`. No free
    text, path, file name a person chose, setting, command line, command output, log line, audit event or bundle id
    travels.
  - **The fixed sets, each known when the module is imported:** the update steps (the string literals of
    `tools/trialbox/update.py`'s step calls, plus `recover from step` and `other`); the health checks (the literals of
    `tb_common.metrics`' checks; `disk:<path>` is `disk`); error types (Python's own exception names, the
    `class ...(…Error|Exception|Failed|Refused|Exit|Interrupt|Warning)` names of this tree's tools and libraries, and
    the database driver's error classes when it is installed; anything else is `other`, an empty text `none`); the
    service names (the service keys of the vendor's `deploy/docker-compose*.yml`; anything else `other`); container
    states and health; the secret names (`tools.trialbox.svc_secrets.IDENTITIES` and `model key`); the backup
    problems as kinds (`no_target`, `too_old`, `drill_failed`, ... from the sentences `backup_schedule.status` writes;
    their words never travel); levels; length ranges (`0`, `1-99`, `100-999`, `1000+`). Labels instead of names:
    a bundle id becomes `installed` (the one `installed.json` names) or `bundle-1`, `bundle-2` ... in the order first
    seen; a path or a mount becomes `system` (/), `data` (/data), `docker`, `deploy`, `backup`, `backup-2` ... (each
    backup target), else `other-1`, `other-2` ....
  - **The allowed fields, member by member:**
    - `ops-snapshot.json`: `at`, `box`; `version` (`trialbox` by a version pattern, `bundle` as a label,
      `applied_at`); `updates[]` (`bundle` label, `first`, `last`, `step`, `ok`, `steps`, `outcome`, `detail_type`,
      `detail_length`); `rollback_points[]` (`bundle` label, `images`, `dumps_kept`, `at`); `incoming[]` (`bytes`,
      `at`); `backups` (`targets[]`: `label`, `reachable`, `files` as a count, `newest`, `total`, `used`, `free`;
      `newest`, `key`, `stale_hours`); `secrets[]` (`name` from the fixed set, `present`, `age_days`, `registered`,
      `mode` `0o` and three octal digits); `logs.days[]` (`day`, `files`, `bytes`); `disk[]` (`label`, `total`,
      `used`, `free`); `health` (`at`, `error` type; `backup`: `level`, `age_hours`, `max_age_hours`, `problems[]` as
      kinds; `verified`: `at`, `sha256`, `created_at`, `drill_failed_at`, `drill_error_type`, `drill_error_length`,
      `drill_databases` as a count; `disks[]`: `label`, `used_pct`, `free`; `cert`: `mode`, `not_after`, `error` as
      `not_set`, `not_pem` or `other`; `gpu`: `used_mib`, `total_mib`, `models_mib`); `error` type.
    - `health.json`: `at`, `level`; `checks[]` (`name` from the fixed set, `level`, `value`); never a check's text.
    - `release.json`: `trialbox` version; `installed` (`format`, `release_seq`, `bundle` label, `manifest_sha256`,
      `key_id` `ed25519:` and 16 hex, `applied_at`, `dirty`, `state`: `vocabulary_release`, `model_pin`,
      `prompt_registry`, `schema` by their patterns); `release` (`release_seq`, `created_at`, `commit` 40 hex,
      `dirty`).
    - `history.jsonl`, one line per update step: `at`, `bundle` label, `box` (`compose`, `demo`, `in-process`,
      `other`), `step`, `ok`, `detail_type`, `detail_length`. A line that is not JSON is dropped and counted.
    - `audit-verify.json`: `state` (`verified`, `not_here`, `unreadable`, `failed`), `ok`, `files`, `lines`, `errors`
      and `notes` as counts, `error` type. Never a note: `audit.verify` puts the detail of `audit.anchored` and
      `audit.reanchored` events, the reason a person typed among them, into its notes (the review of 48b3210c, H1).
    - On a site box only: `services.json` (`service`, `state`, `health`, `restarts`, `since`), from `docker inspect`
      with a fixed format over the ids of `docker compose ps --all -q`: no command line, port or container name;
      `disks.json` (`label`, `total`, `used`, `available`) from `df -P -B1`: no device or mount; `gpu.json`
      (`memory_used_mib`, `memory_total_mib`, `utilization_pct`, `temperature_c`, `driver` by a version pattern) from
      `nvidia-smi --query-gpu=...`: no process list. The commands' outputs are parsed and thrown away.
    - `MANIFEST.json` (the builder's): each member with its size and sha256, the `left_out` rows (the reasons below
      and the counts of dropped fields), what never goes in.
  - **What is never in the button's bundle (each in the MANIFEST with its reason):** the service logs (a log line is
    free text and can carry a pseudonym), `env.redacted`, `docker compose config`, `doctor` and `check_host.sh`
    (settings are redacted by name, and these print setting values and texts a person typed: doctor prints the
    gateway and verifier URLs, the backup-alert watcher, who confirmed the TLS root, the serious adverse event
    office's mail address, the hold-after-restore reason from the database, rule sets' flagged criteria), and the raw
    ops snapshot, update history, audit verification and command outputs. Never, as for the host tool: `/data` or
    any volume, any database table, the secrets folder, a key, a backup or rollback dump, the audit chain, the pid
    map, the lake, `settings.yaml`, the logs of PostgreSQL, HAPI FHIR and vLLM. The host tool
    (`sudo python3 -m tools.trialbox support-bundle`, root) still makes the fuller bundle.
  - **The builder:** `tools/support_bundle.py` (lane H's file) gets three keywords that the console cannot pass:
    `given` (the members made here; the builder then reads nothing of the box for them, and refuses an `--add`),
    `given_left_out` (the MANIFEST rows) and `scanned` (the sha256 and size of the copy its last look scanned). Left as
    their defaults (`None`, `()`, `None`), the host tool's bundle is made exactly as before (the review of 48b3210c
    compared it byte for byte with the merge base's builder); the keywords of the earlier rounds (`logs_left_out`,
    `left_out`, `texts_marked`) are gone. The builder still runs its line scan, credential and secret-value checks
    and the last look over the given members: a second line, **not the protection**. The protection is the
    allow-list; neither scan is proof of anything.
  - **Who may:** the matrix row that opens the operations pages, `ops.view` (`tb_common.authz.admin_allowed`: the
    administrator only). The card names no role, so the row that already governs these pages governs the button and
    the download. **No new matrix row.** Every other role of the matrix (coordinator, investigator, viewer, CRO,
    steward, privacy) gets 403 on the tab, the making and the download, audited as `console.denied`.
  - **The making:** `POST /admin/ops/support_bundle` with the session's CSRF token; first the confirmation sheet
    that says which kinds of values go in and what never does, then the request. One request at a time (a pending one
    answers 409). The console's audit event `console.ops` `support_bundle` names who and the request.
  - **No make event, no bundle:** the runner makes the bundle in `<ops>/support/.making` (root alone, 0700), hashes
    it, and writes `console.ops` `support_bundle.made` (the request, the file name, its size and its SHA-256) BEFORE
    the file is moved to its final name in `<ops>/support/`. The request is the one the runner is running
    (`OpsRunner.run_one` sets `request_id` from the request itself; the review of 48b3210c, L5: a stale marker of an
    earlier request is no longer taken for it). On a site box the event is written inside the orchestrator and a
    non-zero exit is a failure; on the in-process box (the demo, the tests) through the console's own writer. If the
    event cannot be written the file is removed, the result is `BundleNotAudited: not released` and the tab says so
    (en, ja, zh-TW).
  - **The file scanned is the file released:** the runner hashes the made file through the fd it opened in
    `.making`, refuses it unless the hash and size equal those of the copy the builder's last look scanned
    (`BundleChanged`, the file removed, nothing released), and after the move checks that the name in
    `<ops>/support/` is that fd's file (device and inode).
  - **The folder:** `<ops>` is opened without following a link (`O_DIRECTORY|O_NOFOLLOW`) and must belong to the
    runner's user (root on the host) and not be writable by group or others; `support` and `.making` are made through
    that fd, refused when a link or not a folder, and their owner and mode are set on fds. Otherwise nothing is made,
    the result is `SupportFolderRefused` and the tab says the operations folder is not set up as it must be.
  - **A bundle that fails the scan is not handed out:** the builder raises `BundleRefused` and writes nothing; the
    result's summary names pattern ids and member names, never a value; the tab says so (en, ja, zh-TW).
  - **The download (the review of 48b3210c, L8):** `POST /admin/ops/support/{rid}`, a form with the session's CSRF
    token and nothing typed (an action form for `tools/form_fields.py`, D-1384; no list raised); GET and HEAD answer
    405, so a link on another site cannot make a signed-in browser fetch it. It hands out only the file the
    runner's successful result for that request names (a file name of the builder's exact form, size, SHA-256), read
    from `<ops>/support/` without following a link, and only when the file still has that size and SHA-256;
    otherwise it answers 303 back to the tab, which says the bundle is not on the box as it was made (a changed file
    is also `support_bundle_download.refused`). Each download is `console.ops` `support_bundle_download.started` with
    who, when, the request, the file name, its size and its SHA-256, written before the bytes are sent; it records
    the start, not that every byte arrived. When that event cannot be written, the open file is closed and the answer
    is 503 with no byte. A `Range` header gets the whole file with 200.
  - **The right, stated:** the matrix row `ops.view` now also covers making and downloading this export, the
    administrator only. Any administrator can download a bundle another administrator made, as often as they like,
    while it is kept.
  - **Kept on the box (the review of 48b3210c, L6):** `<ops>/support/` (0750, root and the console's group; each file
    0640); the newest three bundles, none older than 14 days (`MAX_AGE_DAYS`): each runner pass removes the others,
    each removal the event `console.ops` `support_bundle.removed` with the file name and why (`count` or `age`).
    Removing is the safe direction, so a bundle is removed even when that event cannot be written.
  - **The role walk (the review of 48b3210c, L7):** the download's administrator cell is decided: a request id the
    walk supplies answers 303 to the tab (allowed), every other column 403; it is off the unclear list.
  - **Words:** the tab, the button, the confirmation and the tab's texts (the kinds of values; the member list with
    what each holds; what never goes in; that a field off a list is dropped and counted; that the scan is a second
    check and not what keeps texts out; the age limit), who may, the refusal, the unaudited making and download, the
    folder's refusal, the bundle no longer on the box and the failure, in en, ja and zh-TW
    (`services/console/i18n_support_bundle.py`, joined into the catalogues; the core words as `core_words.yaml`
    spells them).
- **Not in this card (follow-ups):**
  - **The refusal while a support session is on:** the switch (10K-15, pull request #1170, D-1364) is not on master
    on 2026-11-20, so it is not built here and nothing of it is copied. When #1170 lands, the download (and the
    making) must be refused during a session: `ops.view` is in its `SUPPORT_SESSION_OPEN`, so the route needs its own
    check.
  - `doctor` on the console, grouped, with the next action (the card's first half).
  - **The builder's own gaps, reported to the integrator for lane H** (this card changes nothing the host tool's
    bundle holds): secrets are redacted by name, so a password in a URL's query or a secret under an unlisted name
    goes through `env.redacted`, `docker compose config` and doctor's output; the update history's and the ops
    snapshot's error texts are copied verbatim and can quote a pseudonym; `audit-verify.json` copies the chain's
    notes, a re-anchor reason a person typed among them; typed and mounted paths and command outputs are copied; the
    service logs' scrub does not catch a pseudonym. Whether the button may ever carry more than its allow-lists is a
    question for the owner, not a follow-up of this card.
- **Held by:** `tests/console/test_support_bundle_button.py`: every source the button reads seeded with planted
  markers (a pseudonym, a chart number, a name, a login name, a mail address, a study id, a password-shaped value, a
  type-like name) on a site box with every command's output seeded too: no marker in any member, raw or JSON-escaped,
  and every value of every member of its declared kind (`support_fields.check_member`); the re-anchor reason (H1);
  paths and mounts as labels (M1); command outputs parsed, no process list or command line (M2); the error mark's
  known types and length ranges (L1); release.json's fields (L3); the request id from the request (L5); the age
  limit and the audited removals (L6); the download as a CSRF POST, GET and HEAD 405, a form with nothing typed (L8);
  a pending request answering 409 (L9); the happy path with the same builder spied (the confirmation, the exact
  member list, the MANIFEST, the download and its audit events in order); each other role refused; signed out; a
  bundle failing the scan not handed out; the make event before the final name; no make event, no bundle, on the
  in-process box and on a site box; the folder's checks; a changed file or a link at its place not handed out; the
  scanned file is the released file; a download whose event cannot be written closes its file; the builder's given
  members; the texts in three languages. The role walk (`tests/console/test_matrix_role_walk.py`) decides the
  download's cells; the rows in `tests/console/data/route_actions.yaml` and `role_route_matrix.md`; the builder's own
  tests (`tests/unit -k support_bundle`) for the host tool, unchanged. Synthetic data only.
