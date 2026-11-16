# 14. EDC integration handoff

For the person or the coding assistant preparing TrialBox against the internal EDC. The EDC is
[chang-fu-kuo/trialbox-edc](https://origin.cursor.com/git/chang-fu-kuo/trialbox-edc) on Cursor Origin. This note is
from its PR #1 (`cursor/windows-desktop-edc-e1e7`, architecture §20) and PR #2 (`cursor/e2e-quality-review-e1e7`).
The TrialBox side it talks about is PR #813 (`cursor/redcap-edc-backend-b879`), written up in
[§13](13-redcap-and-the-edc-backend.md). This pull request is based on that branch because §13 and
`services/edc_backend/` are not on `main` yet.

Nothing here changes the running box. With `TB_EDC_BACKEND` unset, the demo and the study link stay as they are.

## What the EDC is

A Rust server is the system of record. It uses Postgres, a built-in FHIR R4 view, and a REDCap-compatible
`POST /api/` whose version string is `14.0.0`. The Windows desktop and the mobile client are Tauri. Features are
modules grouped into bundles. The `trialbox` module ships on in the Clinical Trial bundle and the Hospital bundle.
`GET /api/v1/capabilities` lists the enabled modules, including one whose `id` is `trialbox`.

## Already matched

These TrialBox pieces already speak the EDC's contract. Do not rework them.

| EDC | TrialBox |
| --- | --- |
| `POST /api/` answers version `14.0.0` | `EdcConnection.ensure_version` accepts major 14 (and 13, 15, 16, 17) |
| `POST /api/v1/tools` | Snake_case names in `services/edc_backend/tools.py`: `find_patient`, `explain_field`, `draft_form`, `quality_check`, `summarize_queries`, `apply_draft`, `open_query`. The answer has `deidentified: true`. A write is refused until `confirm: true`. The door is off until the EDC sets `EDC_TOOLS=1`. TrialBox's token is `TB_EDC_TOOL_TOKEN`, not the `/api/` token |
| Events | Spec `trialbox.edc.event.v1`, a stable `id`, header `X-TrialBox-Signature: sha256=<hex HMAC-SHA256 of the raw body>`. `events.signature_ok` checks it with `TB_EDC_EVENT_SECRET`. The route is `POST /api/edc/events/v1`. Types: `record.saved`, `form.completed`, `query.opened`, `ae.reported` |
| Study, site, subject | The same JSON object `linkmap.save` writes: `studies`, `sites`, `subjects` |

## How the EDC delivers events

Delivery is a durable `trialbox_outbox` table, not work done inside the request that saved the record. A tick every
1 s sends due rows. Retries are 1 s, 5 s, 30 s, then 5 min, and each retry reuses the same event id. TrialBox must
treat that id as one event, which the log already does. The EDC's admin page is `/p/{id}/trialbox`. The desktop and
the phone read `GET /api/v1/trialbox/status`.

## Sign-in

The EDC accepts the HS256 `id_token` that `oidc.sign_id_token` already builds. It posts
`{"id_token": "..."}` to `POST /api/v1/trialbox/oidc/{project}`. `sub` must be a username that already exists in the
EDC. TrialBox does not share its console cookie.

## The gap still open on TrialBox

`services/edc_backend/oidc.py` keeps authorization codes in a process-local dict, `_CODES`. `discovery()` advertises
`{issuer}/api/edc/oidc/token`.

On this branch the redeeming route is already mounted, in `services/console/edc_door.py`: `POST /api/edc/oidc/token`
reads the form, calls `oidc.take_code`, refuses a bad secret with 401, and returns
`{"id_token": oidc.sign_id_token(username), "token_type": "Bearer"}` (it also repeats the token as `access_token`).
Do not add a second route.

What is still open is the dict. A code issued in one worker is invisible to another, and it is gone when the process
restarts. Persist the codes (and keep them single-use and short-lived) before more than one console worker redeems
them.

## Contract test and the release

The EDC repository's end-to-end test, tests/e2e/trialbox_contract.py, imports the real client from the #813 branch.
Against the release server it checked version, metadata, events, capabilities, a de-identified `find_patient`,
confirm-before-write, signed delivery, the map round-trip, and an OIDC subject `admin`. That repository's CI clones
the branch.

Release timings measured there, not remeasured in this repository: login 26.8 ms; one Patient POST p50 1.75 ms and
p95 3.32 ms; 10,000 Patients in 3.3 s (3,026/s); a family search 13.2 ms over those 10,000.

The server now locks an account after 5 failures, drops an idle session after `EDC_IDLE_SECS` (15 min), enforces a
password policy, writes FHIR changes onto the hash-chained `audit_log` as the real user, and has SMART 2.x scopes,
JWT/JWKS, and refresh-token rotation.

Still on the EDC side, not here: a full Synthea re-import on the release, persisting MLLP PID and OBX, and strict CI
lint gates.

## Checklist

1. Leave `POST /api/edc/oidc/token` as the one redeeming route. Persist `_CODES` if the console runs more than one worker.
2. Set `TB_EDC_EVENT_SECRET`, `TB_EDC_TOOL_TOKEN`, and `TB_EDC_OIDC` (with issuer, client id, client secret, and the redirect list) on the box that will talk to the EDC. Leave `TB_EDC_BACKEND` unset on the demo.
3. Resolve the merge conflicts on PR #813 before it joins `main`.
4. Run tests/e2e/trialbox_contract.py on a machine that has the EDC, after its compose file has brought the server up.
