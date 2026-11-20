# D-1381 The support bundle as a button: the same builder and scan, the administrator only, audited (10K-5)

- **Task:** lane K, plan 10 row 10K-5 (review 18, SO-5: "`doctor` on the console, grouped, in three languages, with
  the next action; the support bundle as a button"). This decision is the second half only, the button; `doctor` on
  the console is not in it. · **Date:** 2026-11-20
- **The owner's ruling:** the button is an export, so it waited for the owner. The owner ruled on 2026-11-19 at
  20:20 UTC: "10K-5 support-bundle button: yes." This decision builds that and no more.
- **Decision:**
  - **The same builder and scan, nothing added:** the button is the operations action `support_bundle` of
    `/admin/ops` (D-178), on a tab of its own (`?tab=support`). The console never makes the bundle: it writes a
    request into the operations folder, and the host's runner (`tools/trialbox/ops_support.py`) calls
    `tools.support_bundle.build`, the builder of `trialbox support-bundle` (T-209b, D-405), with its scrubbers, the
    line scan, the credential and secret-value checks and the last look at the finished archive (D-723, D-747,
    D-962). No `--add` file, the request's arguments are never read (the console's user writes the request file), and
    one thing is taken out (below): the service logs. On a site box the commands run as the command runs them
    (doctor, docker, df, nvidia-smi); the in-process box runs none (`--no-commands`).
  - **No service logs from the button (the review of 83a0640a, an interim narrowing while a question is with the
    owner):** TrialBox's own service logs can carry patient pseudonyms (for example a failed twin build is logged
    with the patient's pseudonym), and the builder's scrub is a deny-list of patterns (national ids, phone numbers,
    chart numbers) that catches neither a pseudonym nor a screening number. D-280 keeps pseudonyms off the
    administrator's pages, so a bundle made from the button holds **no service log**: the runner passes the builder
    a fixed `logs_left_out` reason (`tools/trialbox/ops_support.py` `LOGS_LEFT_OUT`; the console cannot pass any
    option), no log is read, `MANIFEST.json` lists `logs/` under `left_out` with that reason and `log_days` is
    empty. The logs stay available only through the host tool, `sudo python3 -m tools.trialbox support-bundle`,
    which needs root on the box. The keyword's default leaves the host tool's bundle exactly as before
    (`tools/support_bundle.py`, its own tests unchanged).
  - **What the button's bundle holds:** `ops-snapshot.json` (what the Operations page shows: version, updates,
    rollback points, backups by name and age, secrets by name, presence and age, never a value), `health.json`,
    `release.json`, the last 400 lines of the update history, `env.redacted` (`deploy/.env` with every secret-like
    value replaced), `audit-verify.json` (counts and errors, no event), `MANIFEST.json`, and on a site box the command
    outputs `cmd/doctor.json` (`doctor --json`), `cmd/check_host.txt`, `cmd/compose-config.yaml` (`docker compose
    config`), `cmd/compose-ps.txt`, `cmd/restarts.txt`, `cmd/df.txt` and `cmd/nvidia-smi.txt`. **Not in it:** the
    service logs (above). Never: `/data` or any volume, any database table, the secrets folder, a key, a backup or
    rollback dump, the audit chain, the pid map, the lake, `settings.yaml`, and the logs of PostgreSQL, HAPI FHIR and
    vLLM.
  - **What the command outputs can print (read for this decision):** `doctor` prints its checks' verdicts and
    facts: settings by name and value (topology, environment, time zone, chart-number rule), model build ids and
    hashes, the site key's fingerprint (never the key), the backup targets, the SAE office's mail address and the
    names given for the site's named choices (staff, not patients); its only database reads are the site key's
    fingerprint and chart-number rule. `check_host.sh` prints PASS/WARN/FAIL lines about the host (kernel, disk
    encryption, ssh settings, time zone, docker, GPU) and reads the same fingerprint and rule. `docker compose config`
    prints every service's resolved settings, environment values included: the builder redacts every secret-like
    name's value and the user:password of URLs (`redact_secrets`), then, as in every file, replaces each of the box's
    own secret values in every form (D-723) and credentials of well-known shapes, and the last look refuses a bundle
    that still holds one; so it shows what `env.redacted` shows, and it stays in. `compose ps`, the restart counts,
    `df -h` and `nvidia-smi` print container, disk and GPU state. None of them reads a patient row, a pseudonym or a
    note; every file still passes the data-handling scan line by line.
  - **Who may:** the matrix row that opens the operations pages, `ops.view` (`tb_common.authz.admin_allowed`: the
    administrator only). The card names no role, so the row that already governs these pages governs the button and
    the download. **No new matrix row.** Every other role of the matrix (coordinator, investigator, viewer, CRO,
    steward, privacy) gets 403 on the tab, the making and the download, audited as `console.denied`.
  - **The making:** `POST /admin/ops/support_bundle` with the session's CSRF token; first the confirmation sheet
    that names what goes in and what never does, then the request. One request at a time (a pending one answers
    409). The console's audit event `console.ops` `support_bundle` names who and the request.
  - **No make event, no bundle:** the runner makes the bundle in `<ops>/support/.making` (root alone, 0700), hashes
    it, and writes `console.ops` `support_bundle.made` (the request, the file name, its size and its SHA-256) BEFORE
    the file is moved to its final name in `<ops>/support/`. On a site box the event is written inside the
    orchestrator and a non-zero exit is a failure; on the in-process box (the demo, the tests) through the console's
    own writer. If the event cannot be written the file is removed, the result is `BundleNotAudited: not released`
    and the tab says "Not handed out: the making could not be recorded in the audit trail" (en, ja, zh-TW). The
    result's event `support_bundle.done` stays as every operation's (best effort on a site box): the durable record
    of the making is `support_bundle.made`.
  - **The folder:** `<ops>` is opened without following a link (`O_DIRECTORY|O_NOFOLLOW`) and must belong to the
    runner's user (root on the host) and not be writable by group or others; `support` and `.making` are made through
    that fd, refused when a link or not a folder, and their owner and mode are set on fds. Otherwise nothing is made,
    the result is `SupportFolderRefused` and the tab says the operations folder is not set up as it must be.
  - **A bundle that fails the scan is not handed out:** the builder raises `BundleRefused` and writes nothing; the
    result's summary names pattern ids and member names, never a value; the tab shows "Not handed out: the finished
    bundle did not pass the data-handling scan" (en, ja, zh-TW) and no download link; the download route answers 404.
  - **The download:** `GET /admin/ops/support/{rid}` hands out only the file the runner's successful result for that
    request names (file name of the builder's exact form, size, SHA-256, from the result file root writes), read from
    `<ops>/support/` without following a link, and only when the file on disk still has that size and SHA-256 (else
    404 and `support_bundle_download.refused`); `no-store`. Each download is the audit event `console.ops`
    `support_bundle_download.started` with who (the actor), when (the event's time), the request, the file name, its
    size and its SHA-256, written when the response starts, before the bytes are sent; it records the start, not that
    every byte arrived, as the console's other files (the feedback and audit CSVs) record theirs. Never a line of the
    bundle. A `Range` request gets the whole file with 200; HEAD answers 405; signed out gets no bytes; a link at the
    bundle's place is not followed (404).
  - **The right, stated:** the matrix row `ops.view` now also covers making and downloading this export, the
    administrator only. Any administrator can download a bundle another administrator made, as often as they like,
    until it falls outside the newest three.
  - **Kept on the box:** `<ops>/support/` (0750, root and the console's group; each file 0640); the newest three
    bundles stay, an older one is removed when a new one is made.
  - **Words:** the tab, the button, the confirmation (what goes in, that the service logs are left out for now and
    why, and what never goes in), who may, the refusal, the unaudited making, the folder's refusal and the failure in
    en, ja and zh-TW (`services/console/i18n_support_bundle.py`, joined into the catalogues).
- **Not in this card (follow-ups):**
  - **The refusal while a support session is on:** the switch (10K-15, pull request #1170, D-1364) is not on master
    on 2026-11-20, so it is not built here and nothing of it is copied. When #1170 lands, the download (and the
    making) must be refused during a session: `ops.view` is in its `SUPPORT_SESSION_OPEN`, so the route needs its own
    check, and `GET /admin/ops/support/{rid}` joins the walk's reviewed list.
  - `doctor` on the console, grouped, with the next action (the card's first half).
  - **The service logs:** whether, and how, a bundle made from the button may carry them again (a scrub that
    catches pseudonyms and screening numbers, or the owner's ruling) is the question with the owner; until then
    they are left out.
- **Held by:** `tests/console/test_support_bundle_button.py` (the happy path with the same builder spied: the
  confirmation, no log member and the MANIFEST's reason, the download and its audit events in order; each other role
  of the matrix refused the tab, the making and the download; signed out; a bundle failing the scan not handed out;
  the make event before the final name; no make event, no bundle, on the in-process box and on a site box; a link
  planted at `<ops>/support`, a linked or group-writable `<ops>`, a file in the folder's place; a file changed on disk
  or a link at its place not handed out; HEAD and Range; another result or a bad id; CSRF; the texts in three
  languages; the runner's record, pruning, ignored arguments and the site box's audit event); the row in
  `tests/console/data/route_actions.yaml` and `tests/console/data/role_route_matrix.md`; the builder's own tests
  (`tests/unit -k support_bundle`) for the host tool, unchanged. Synthetic data only.
