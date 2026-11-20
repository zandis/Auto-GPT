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
    what is taken out or marked (below) is fixed by constants of `tools/trialbox/ops_support.py` that the console
    cannot pass or change. On a site box the commands that stay run as the command runs them (docker compose ps,
    docker inspect, df, nvidia-smi); the in-process box runs none (`--no-commands`).
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
  - **The texts of the history and the ops snapshot marked (the review of 31935cc4, item 1):** a failed update step
    writes `UpdateFailed: <the last 600 characters of the command's stderr>` into the history
    (`tools/trialbox/update.py` `_history`, from `_run`'s error), and a failed migration's database error quotes the
    key that clashed, a pseudonym among them; `trialbox ops` copies the last line's detail into the snapshot. The
    free-text fields, read from their writers: in `history.jsonl` (`update.py` `_history`: `at`, `bundle`, `box`,
    `step`, `ok`, `detail`) the `detail`, any key the writer does not write, and a line that is not JSON; in
    `ops-snapshot.json` (`tools/trialbox/ops.py` `snapshot` and `health_facts`, `tb_common.metrics.host_facts`, the
    builder's fallback) the builder's `error` when the snapshot fails (the exception's text), `updates[].detail` (the
    history's detail, 200 characters), `health.verified.drill_error` (a failed restore drill's error, 300 characters,
    `metrics.record_drill`), the restore drill's sentence in `health.backup.problems` (it quotes that error,
    `backup_schedule.drill_failure`), `health.error` (a type name) and `health.cert.error` (fixed words); the builder
    marks every `error`, `detail`, `drill_error`, `why`, `reason` and `message` value wherever it stands, and the
    drill's error inside its problem sentence. The other backup problems are sentences of fixed words with setting
    names, numbers and times, and stay. For the button the builder (keyword `texts_marked`, the constant
    `TEXTS_MARKED`) replaces each such text with `[text left out: <the error's type name, when the text starts with
    one>, <length> characters]`; the structured fields (time, step, bundle id, box, release, result, counts, names,
    paths) stay, `health.json` is evaluated from the marked snapshot, and `MANIFEST.json` lists what was marked under
    `left_out` with the reason. Held by a planted synthetic pseudonym-like token in a history line, a non-JSON line,
    an unknown key, a restore drill's error and a failing snapshot: absent from every member of a button-made bundle.
  - **The .env file, compose config, doctor and check_host.sh left out (the review of 31935cc4, items 2 and 4):** the
    builder redacts secret-looking NAMES (`SECRET_KEY`), the user:password of a URL (`USERINFO`) and the values of
    the box's known secret settings and files (`SECRET_SETTINGS`, `_SECRET_VALUE_NAME`, D-723); a password in a URL's
    query or a secret under a name none of these knows (the review's probe: `TB_SMTP_LOGIN`) went through in
    `env.redacted` and in `docker compose config`. `doctor` prints setting values without that redaction (the
    gateway's and the verifier's URLs among them) and texts it reads from the database (below), and
    `check_host.sh` runs doctor and prints what it prints. So a bundle made from the button holds none of the four
    (keyword `left_out`, the constant `LEFT_OUT`, each with its reason in `MANIFEST.json`'s `left_out`); doctor,
    check_host.sh and compose config are not even run. Leaving doctor out is wider than marking its restore-hold
    line (item 4's narrower choice), but item 2 alone already takes doctor out: the URLs it echoes cannot be
    redacted by name, so its line-by-line output is not stated here as safe. Held by a planted `?password=` URL, an
    unlisted secret-like setting, a named watcher and doctor output that echoes them: absent from every member.
  - **What the button's bundle holds:** `MANIFEST.json`, `ops-snapshot.json` (what the Operations page shows:
    version, updates, rollback points, backups by name, age and folder path, secrets by name, presence and age, never
    a value, disks; texts marked), `health.json` (evaluated from the marked snapshot), `release.json`, the last 400
    lines of the update history (texts marked; only when an update has run), `audit-verify.json` (counts and errors,
    no event), and on a site box `cmd/compose-ps.txt` (`docker compose ps --all`: containers, their published
    addresses and ports), `cmd/restarts.txt`, `cmd/df.txt` and `cmd/nvidia-smi.txt`. It carries the site's host
    names, addresses, ports and folder paths as these print them (compose ps, df's mounts, the backup targets'
    paths). With doctor and the .env file out it no longer carries the named staff (`TB_BACKUP_ALERT_WATCHER`,
    `TB_TLS_ROOT_CONFIRMED_BY`) or the serious adverse event office's mail address, which doctor prints. **Left
    out, with the reason in the MANIFEST:** the service logs (patient pseudonyms), `env.redacted` and
    `cmd/compose-config.yaml` (the redaction is by name and can miss a secret), `cmd/doctor.json` and
    `cmd/check_host.txt` (setting values and database texts, above). Never: `/data` or any volume, any database
    table, the secrets folder, a key, a backup or rollback dump, the audit chain, the pid map, the lake,
    `settings.yaml`, and the logs of PostgreSQL, HAPI FHIR and vLLM.
  - **What is checked, and what is not claimed:** the builder's line scan (`tools.data_scan`, the exits' patterns),
    its credential shapes and the box's own secret values run on every member, and the last look scans the finished
    archive; a hit means no bundle. Neither is proof that a file holds nothing personal or secret: the texts above
    therefore say what is checked, not "no patient data" or "every secret value replaced".
  - **What doctor can print (read for this decision; correcting the earlier text, which said its only database reads
    were the site key's fingerprint and the chart-number rule):** its checks' verdicts and facts, with setting values
    (topology, environment, time zones, the chart-number rule, model ids, the gateway's and the verifier's URLs), the
    backup targets, the serious adverse event office's mail address and the staff named in the settings
    (`TB_BACKUP_ALERT_WATCHER`, `TB_TLS_ROOT_CONFIRMED_BY` and `_ON`). Its database reads: the pid map's site-key
    fingerprint and chart-number rule (`check_chartno_rule`); the flags' seed drift (`check_flags`,
    `tb_common.flags.env_drift`: each seed variable's value and its flag's value); the hold after a restore
    (`check_restore_hold`: the newest event's `reason` of `screening.after_restore`, free text that the restore tool
    writes or a person types on `/ops/flags`); the provenance index against the chain (`check_provenance_index`:
    counts of missing and extra rows, an error's type name); and the rule-set repository (`check_negated_inclusions`:
    rule set id, version and criterion id of each flagged inclusion). For the host tool's bundle this is lane H's to
    weigh; for the button, doctor is left out (above).
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
  - **The file scanned is the file released (the review of 31935cc4, item 5):** the builder reports the sha256 and size
    of the copy its last look scanned (keyword `scanned`); the runner hashes the made file through the fd it opened
    in `.making`, refuses it unless the two agree (`BundleChanged`, the file removed, nothing released), and after the
    move checks that the name in `<ops>/support/` is that fd's file (device and inode). So the hash in the make event,
    the result and every download check is the hash of the scanned copy: a checked fact, not a consequence of the
    folder's permissions.
  - **The download:** `GET /admin/ops/support/{rid}` hands out only the file the runner's successful result for that
    request names (file name of the builder's exact form, size, SHA-256, from the result file root writes), read from
    `<ops>/support/` without following a link, and only when the file on disk still has that size and SHA-256 (else 404
    and `support_bundle_download.refused`); `no-store`. Each download is the audit event `console.ops`
    `support_bundle_download.started` with who (the actor), when (the event's time), the request, the file name, its
    size and its SHA-256, written when the response starts, before the bytes are sent; it records the start, not that
    every byte arrived, as the console's other files (the feedback and audit CSVs) record theirs. When that event cannot
    be written the open file is closed and the answer is 503 ("Not handed out: the download could not be recorded", en,
    ja, zh-TW) with no byte. Never a line of the bundle. A `Range` request gets the whole file with 200; HEAD answers
    405; signed out gets no bytes; a link at the bundle's place is not followed (404).
  - **The right, stated:** the matrix row `ops.view` now also covers making and downloading this export, the
    administrator only. Any administrator can download a bundle another administrator made, as often as they like,
    until it falls outside the newest three.
  - **Kept on the box:** `<ops>/support/` (0750, root and the console's group; each file 0640); the newest three
    bundles stay, an older one is removed when a new one is made.
  - **Words:** the tab, the button, the confirmation and the tab's texts (the member list; that it carries the site's
    host names, addresses, ports and folder paths; what is left out of a bundle made here and why: the service logs,
    the .env file and compose config, doctor and check_host.sh with what doctor prints, the marked error texts; what
    is never copied; that a credential scan and a data-handling scan run and neither is proof), who may, the
    refusal, the unaudited making and download, the folder's refusal and the failure in en, ja and zh-TW
    (`services/console/i18n_support_bundle.py`, joined into the catalogues; the core words as `core_words.yaml`
    spells them).
- **Not in this card (follow-ups):**
  - **The refusal while a support session is on:** the switch (10K-15, pull request #1170, D-1364) is not on master
    on 2026-11-20, so it is not built here and nothing of it is copied. When #1170 lands, the download (and the
    making) must be refused during a session: `ops.view` is in its `SUPPORT_SESSION_OPEN`, so the route needs its own
    check, and `GET /admin/ops/support/{rid}` joins the walk's reviewed list.
  - `doctor` on the console, grouped, with the next action (the card's first half).
  - **The service logs:** whether, and how, a bundle made from the button may carry them again (a scrub that
    catches pseudonyms and screening numbers, or the owner's ruling) is the question with the owner; until then
    they are left out.
  - **The builder's own gaps, reported to the integrator for lane H** (`tools/support_bundle.py` is lane H's file;
    this card changes nothing the host tool's bundle holds, its new keywords default to the bundle as before): secrets
    are redacted by name, so a password in a URL's query or a secret under an unlisted name goes through
    `env.redacted`, `docker compose config` and doctor's output; the update history's and the ops snapshot's error
    texts are copied verbatim (`scrubbed=False`) and can quote a pseudonym; the service logs' scrub does not catch a
    pseudonym. **Follow-up, not built:** when lane H's cures for these are on master, the button's left-out members
    (`env.redacted`, compose config, doctor, check_host.sh, the logs) and the marked texts come back in a card of
    their own, each against its cure's tests.
- **Held by:** `tests/console/test_support_bundle_button.py` (the review of 31935cc4: a planted pseudonym-like token in
  the history, an unknown key, a non-JSON line, a restore drill's error and a failing snapshot, marked with their length
  and type; a `?password=` URL, an unlisted secret setting and a named watcher absent; on a site box doctor,
  check_host.sh and compose config not run; the download's open file closed when its event cannot be written; a file
  changed after the scan not released; the happy path with the same builder spied: the confirmation, the exact member
  list, no log member and the MANIFEST's reason, the download and its audit events in order; each other role of the
  matrix refused the tab, the making and the download; signed out; a bundle failing the scan not handed out; the make
  event before the final name; no make event, no bundle, on the in-process box and on a site box; a link planted at
  `<ops>/support`, a linked or group-writable `<ops>`, a file in the folder's place; a file changed on disk or a link at
  its place not handed out; HEAD and Range; another result or a bad id; CSRF; the texts in three languages; the runner's
  record, pruning, ignored arguments and the site box's audit event); the row in `tests/console/data/route_actions.yaml`
  and `tests/console/data/role_route_matrix.md`; the builder's own tests (`tests/unit -k support_bundle`) for the host
  tool, unchanged. Synthetic data only.
