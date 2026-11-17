# 14. EDC integration handoff

For the person or the coding assistant preparing TrialBox against the owner's EDC, `trialbox-edc` (its own private
repository). This note came with #895 (stacked on #813) and was brought onto master by lane E in E-EDCB-3 (D-1045).
The TrialBox side is `services/edc_backend/` and `services/console/edc_door.py`, written up in
[§13](13-redcap-and-the-edc-backend.md); #813 reached master as E-EDCB-1 (D-1043).

**The firewall (D-1060).** The TrialBox side is written only from #813, #895 and the EDC behaviour their tests and
fixtures record. Nobody working on TrialBox reads, clones, writes to or comments on the EDC's repository. A
question that needs the EDC's source or behaviour goes to the integrator, who passes it to the owner.

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
| `POST /api/` answers version `14.0.0` | `EdcConnection.ensure_version` accepts major 14 (13 to 17, as the study link since D-852) |
| `POST /api/v1/tools` | Snake_case names in `services/edc_backend/tools.py`: `find_patient`, `explain_field`, `draft_form`, `quality_check`, `summarize_queries`, `apply_draft`, `open_query`. The answer has `deidentified: true`. A write is refused until `confirm: true`. The door is off until the EDC sets `EDC_TOOLS=1`. TrialBox's token is `TB_EDC_TOOL_TOKEN`, not the `/api/` token. An answer without `deidentified: true` is refused (D-1043) |
| Events | Spec `trialbox.edc.event.v1`, a stable `id`, header `X-TrialBox-Signature: sha256=<hex HMAC-SHA256 of the raw body>`. `events.signature_ok` checks it with `TB_EDC_EVENT_SECRET`. The route is `POST /api/edc/events/v1`. Types: `record.saved`, `form.completed`, `query.opened`, `ae.reported` |
| Study, site, subject | The same JSON object `linkmap.save` writes: `studies`, `sites`, `subjects` |

## How the EDC delivers events

Delivery is a durable `trialbox_outbox` table, not work done inside the request that saved the record. A tick every
1 s sends due rows. Retries are 1 s, 5 s, 30 s, then 5 min, and each retry reuses the same event id. TrialBox treats
that id as one event: it is kept in the trial database with its re-read in one transaction (D-1044), so a retry, a
second console process or a restart reads nothing twice. The event secret may hold `current,previous` while it is
changed ([§13, Changing the event secret](13-redcap-and-the-edc-backend.md#changing-the-event-secret)). The EDC's admin page is `/p/{id}/trialbox`. The desktop and
the phone read `GET /api/v1/trialbox/status`.

## Sign-in

The EDC accepts the HS256 `id_token` that `oidc.sign_id_token` already builds. It posts
`{"id_token": "..."}` to `POST /api/v1/trialbox/oidc/{project}`. `sub` must be a username that already exists in the
EDC. TrialBox does not share its console cookie.

## The gap that was open on TrialBox, now closed

#895 noted that `services/edc_backend/oidc.py` kept authorization codes in a process-local dict: a code issued in
one worker was invisible to another and gone on a restart. E-EDCB-2 (D-1044) keeps them in the trial database (schema
`edcdoor`), single use and 120 seconds, in any process; the held writes and the event ids are kept there too.
E-EDCB-3 (D-1045) binds a code to the client and the redirect it was issued for and checks both at
`POST /api/edc/oidc/token`, still the one redeeming route.

## Contract test and the release

The EDC repository's end-to-end test (as #895 reported it) imported the real client from the #813 branch. Against the
release server it checked version, metadata, events, capabilities, a de-identified `find_patient`,
confirm-before-write, signed delivery, the map round-trip, and an OIDC subject `admin`. That test is the owner's: it
should now take the client from master. Since D-1045 the token exchange also needs `redirect_uri`, so a test or a
client that left it out is refused (400) until it sends it.

Release timings measured there, not remeasured in this repository: login 26.8 ms; one Patient POST p50 1.75 ms and
p95 3.32 ms; 10,000 Patients in 3.3 s (3,026/s); a family search 13.2 ms over those 10,000.

The server now locks an account after 5 failures, drops an idle session after `EDC_IDLE_SECS` (15 min), enforces a
password policy, writes FHIR changes onto the hash-chained `audit_log` as the real user, and has SMART 2.x scopes,
JWT/JWKS, and refresh-token rotation.

Still on the EDC side, not here: a full Synthea re-import on the release, persisting MLLP PID and OBX, and strict CI
lint gates.

## Checklist

1. Leave `POST /api/edc/oidc/token` as the one redeeming route.
2. Set `TB_EDC_EVENT_SECRET`, `TB_EDC_TOOL_TOKEN`, and `TB_EDC_OIDC` (with issuer, client id, client secret, and the
   redirect list) on the box that will talk to the EDC. Leave `TB_EDC_BACKEND` unset on the demo. The trial database
   (`TB_DB_URL`) must be set: without it the door answers 503.
3. Run the EDC repository's contract test on a machine that has the EDC, after its compose file has brought the
   server up (the owner's side; TrialBox's CI does not run it).
