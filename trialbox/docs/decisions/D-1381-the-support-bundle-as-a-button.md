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
    D-962). No `--add` file, the default three log days, and the request's arguments are never read (the console's
    user writes the request file). On a site box the commands run as the command runs them (doctor, docker, df,
    nvidia-smi); the in-process box runs none (`--no-commands`).
  - **What the bundle holds** (the builder's own list, unchanged): `ops-snapshot.json` (what the Operations page
    shows: version, updates, rollback points, backups by name and age, secrets by name, presence and age, never a
    value), `health.json`, `release.json`, the last 400 lines of the update history, `env.redacted` (`deploy/.env`
    with every secret-like value replaced), `audit-verify.json` (counts and errors, no event), `cmd/*.txt` on a site
    box, the last three collected days of TrialBox's own service logs (scrubbed), and `MANIFEST.json`. Never: `/data`
    or any volume, any database table, the secrets folder, a key, a backup or rollback dump, the audit chain, the pid
    map, the lake, `settings.yaml`, and the logs of PostgreSQL, HAPI FHIR and vLLM. No patient data: the builder
    reads no database and no data folder, and every file passes the log scrubber and the data-handling scan.
  - **Who may:** the matrix row that opens the operations pages, `ops.view` (`tb_common.authz.admin_allowed`: the
    administrator only). The card names no role, so the row that already governs these pages governs the button and
    the download. **No new matrix row.** Every other role of the matrix (coordinator, investigator, viewer, CRO,
    steward, privacy) gets 403 on the tab, the making and the download, audited as `console.denied`.
  - **The making:** `POST /admin/ops/support_bundle` with the session's CSRF token; first the confirmation sheet
    that names what goes in and what never does, then the request. One request at a time (a pending one answers
    409). The console's audit event `console.ops` `support_bundle` names who and the request; on the in-process box
    `support_bundle.done` follows with the result; on a site box the runner writes `support_bundle.done` and
    `support_bundle.made` with the file name, its size and its SHA-256 into the box's chain.
  - **A bundle that fails the scan is not handed out:** the builder raises `BundleRefused` and writes nothing; the
    result's summary names pattern ids and member names, never a value; the tab shows "Not handed out: the finished
    bundle did not pass the data-handling scan" (en, ja, zh-TW) and no download link; the download route answers 404.
  - **The download:** `GET /admin/ops/support/{rid}` hands out only the file the runner's successful result for that
    request names (file name of the builder's exact form, size, SHA-256, from the result file root writes), read from
    `<ops>/support/` without following a link, and only when the file on disk still has that size and SHA-256 (else
    404 and `support_bundle_download.refused`); `no-store`. Each download is the audit event `console.ops`
    `support_bundle_download` with who (the actor), when (the event's time), the request, the file name, its size
    and its SHA-256; never a line of the bundle.
  - **Kept on the box:** `<ops>/support/` (0750, root and the console's group; each file 0640); the newest three
    bundles stay, an older one is removed when a new one is made.
  - **Words:** the tab, the button, the confirmation, what goes in and what never does, who may, the refusal and the
    failure in en, ja and zh-TW (`services/console/i18n_support_bundle.py`, joined into the catalogues).
- **Not in this card (follow-ups):**
  - **The refusal while a support session is on:** the switch (10K-15, pull request #1170, D-1364) is not on master
    on 2026-11-20, so it is not built here and nothing of it is copied. When #1170 lands, the download (and the
    making) must be refused during a session: `ops.view` is in its `SUPPORT_SESSION_OPEN`, so the route needs its own
    check, and `GET /admin/ops/support/{rid}` joins the walk's reviewed list.
  - On the in-process box the making's size and SHA-256 are in the result and in the download's event, not in an
    event of their own (the runner writes `support_bundle.made` on a site box only).
  - `doctor` on the console, grouped, with the next action (the card's first half).
- **Held by:** `tests/console/test_support_bundle_button.py` (the happy path with the same builder spied, the
  confirmation, the download and its audit events; each other role of the matrix refused the tab, the making and the
  download; a bundle failing the scan not handed out and the page saying so; a file changed on disk not handed out;
  another result or a bad id; CSRF; the texts in three languages; the runner's record, pruning, ignored arguments and
  the site box's audit event); the row in `tests/console/data/route_actions.yaml` and
  `tests/console/data/role_route_matrix.md`. Synthetic data only.
