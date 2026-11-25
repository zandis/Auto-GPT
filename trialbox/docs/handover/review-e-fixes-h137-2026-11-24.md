# H-137: the outside review's fixes, checked and written anew

**Reader:** the people who build TrialBox: the lane H lead, the owning lanes (C2, D, E, J, K, U) and the integrator.
Findings for builders, so in one language.

- **Card:** H-137 (lane H, the integrator's comments 7146717829 and 7146812094 on #639; the go for every file
  outside the card, bodies only: 7147065106)
- **Date:** 2026-11-24
- **Base:** master a3739fca9f7cc9ede71a59347f068eefeb705822
- **Findings:** [`review-e-fixes-h137-2026-11-24/findings.json`](review-e-fixes-h137-2026-11-24/findings.json)
  (H137-01 to H137-16)
- **Tests:** `tests/unit/test_review_e_patches.py` (13 tests, 17 cases); for the owner's two decisions
  `tests/unit/test_mail_tls_verified.py` and `tests/unit/test_trusted_proxy_list.py`, and V3-01's test in
  `tests/console/test_asvs_evidence.py`, no longer a strict xfail. All in the existing jobs; no new CI job

## What this card is

An outside review model, called "model E" here, suggested ten small fixes; the owner's helper applied them on a draft
(#1476, closed). Nothing of that draft is taken over. Each fix was checked on master on its own, the fault reproduced
first, and only then written again, each with a test that fails on master. All ten faults are real.

## The ten fixes

| Id | Place (owning lane) | The fault on master | The fix |
|---|---|---|---|
| H137-01 | `services/model_guard/__init__.py:131` (D) | Two `Content-Length` headers: the guard reads the first, the forwarded headers keep the last. An unkeyed `GET /health` with a body that holds a second request: the model server parsed both, the second with no key | More than one `Content-Length` is a bad request (400), the connection closed, the refusal logged with its reason and never the body |
| H137-02 | `services/edc_backend/oidc.py:87,100` (E) | `TB_EDC_OIDC=1` with an empty client secret: tokens are signed under an empty HMAC key and any token so signed is accepted (`userinfo` answers it) | No token is signed or accepted under an empty secret |
| H137-03 | `services/edc_backend/events.py:50` (E) | A signature header with non-ASCII text raises in `hmac.compare_digest` (a 500, not a refusal) | Anything but 64 hex characters is refused before the compare |
| H137-04 | `services/edc_backend/config.py:125` (E) | `REDCAP_TOKEN_<ref>` overrode `TB_REDCAP_TOKEN_<ref>` and `TB_REDCAP_PROJECT_TOKENS`; `docs/data/13-redcap-and-the-edc-backend.md` says the shorter name works only when the `TB_` one is empty | The short name fills only a ref no `TB_` setting names |
| H137-05 | `services/edc_backend/linkmap.py:63` (E) | The map was created 0644 under umask 022 and chmodded after, and rewritten in place: a failed write (a lone surrogate from a JSON `\ud800` escape) left the saved map torn, which `load` reads as empty | A 0600 temporary file (`mkstemp`) beside the map, written, synced, renamed over it, and the folder synced; the temporary file removed on failure |
| H137-06 | `services/edc/prefill.py:374` (J) | An integer lost its trailing zeros: 70 was "shown" by a quote saying 7, 100 by "1", 0 by any quote | Only a decimal's fraction loses trailing zeros (7.50 to 7.5, 7.0 to 7, 0.0 to 0) |
| H137-07 | `services/adapter/app.py:295,385` (J) | The snapshot name was joined to the lake unchecked: `..`, `../outside`, `a/b` validated a folder outside `ndjson/` | A snapshot is a plain folder name, else 400 before anything is touched |
| H137-08 | `services/orchestrator/datacore_api.py:260` (C2) | `PUT /studies/{rs}/data/{record}` keyed a pseudonym in upper case; every other route keys it in lower case, so the values were under another record | `record_key()`, as the other routes |
| H137-09 | `services/console/audit_page.py:600` (C2) | The report file skipped the page's rule (D-380; D-771's review: a disclosure lookup's own lines never show the pseudonym) | The file's rows go through the same rule |
| H137-10 | `services/console/auth.py:1301` (K) | A CSRF value with non-ASCII text raised in `hmac.compare_digest` (a 500, not the refusal) | The compare is on UTF-8 bytes |

Each fix touches the body of one function in another lane's file; no interface changes. #813 (merged) made the four
`edc_backend` files; H137-02 to H137-05 fix its code and change nothing D-915 or D-916 decided.

## How each fix was shown

On master 15 of the 17 cases of `tests/unit/test_review_e_patches.py` fail, each on the fault named. The other two
hold what master already does right and must stay so: one `Content-Length` is forwarded, and `Transfer-Encoding`
beside `Content-Length` is refused with the connection closed. With the fixes all 17 pass.

Mutants: each fixed file put back to master's alone fails exactly that fix's test and no other. Single lines taken
out fail their test too: the guard's second-length check and its log line, the folder sync and the temporary file's
removal in the link map, the signing check and the verifying check in OIDC, the empty-value check and the decimal
point condition in prefill, the adapter's check on `/publish`, the alias's fill-only rule, the CSV's disclosure rule.

**RFC 9112 and the guard.** Section 6.3: two different `Content-Length` values are an unrecoverable error; the guard
answers 400 and closes the connection. Section 6.1: a request with both `Transfer-Encoding` and `Content-Length` may be
refused, or read by `Transfer-Encoding` alone, and the connection must be closed after the answer. The guard refuses
it (it refuses any `Transfer-Encoding`: it reads bodies by length only, as before this card) and closes.

The guard's test speaks HTTP/1.1 with keep-alive to its stand-in model server, as the real one does; on HTTP/1.0 the
hidden request would be dropped and the fault would not show. It uses `/v1/models`, not a model API path, so
`test_no_direct_model_calls` needs no exception.

## The highs not applied: triage

Model E's own text was not available (the draft's body was replaced); these are triaged from the integrator's
descriptions. H137-11 and H137-12 are built on the owner's decisions (below); the others are not built here.

- **H137-11, SMTP and IMAP do not verify TLS (real).** `services/mail_gateway/outbound.py:75,83` and
  `services/mail_gateway/gateway.py:452` pass no TLS context, so the standard library uses one with
  `verify_mode` CERT_NONE and no host check. Anyone on the path can show any certificate and read the relay's password
  and the mail. The owner chooses: verify on with a CA pinned per relay (a setting and a doctor check per site; a relay
  with a self-signed certificate stops mail until pinned), off and said so (no set-up; password and mail open on the
  path), or on by default with an audited per-relay switch to off.
- **H137-12, the trusted proxy for `X-Forwarded-For` (real).** `deploy/platform/base/apps.yaml:449` trusts every
  sender's header (`--forwarded-allow-ips "*"`): a client changes it on each try and passes the per-address lock
  (D-279), and writes the audit's source address. Compose trusts only 127.0.0.1, so behind Caddy every browser is one
  address (the known open ASVS row V3-01). The owner chooses: trust exactly the proxy's address (a fixed address and an
  install step), trust all and rely on a network rule that only the proxy reaches the console (cheap; one wrong route
  reopens it), or trust none (V3-01 stays).
- **H137-13, an opted-out count for one record (hypothesis).** `services/edc/service.py:505` writes `opted_out: n`
  beside `record: <one record>` when one record is sent; n = 1 says that patient opted out (D-147). Not run.
- **Consent release permission (no defect found).** The console route (`need_requester`) and the matrix row
  `command.RELEASE` agree: administrator and coordinator. Whether the administrator should release a patient page
  (D-280) is a policy question.
- **H137-14, the twelve-digit pattern (real).** `libs/tb_common/phi_guard.py:228`: `1234  5678  9012` (two spaces)
  and `1234_5678_9012` are not matched; one space, a dash, a dot, a slash and full-width digits are.
- **H137-15, the administrator's mailbox as a fallback (real as routing).** `services/console/app.py:1024`:
  a job of an account with no mailbox is mailed to the administrator's mailbox. What that mail holds per job type is
  not verified.

One more, seen while checking H137-06 and filed on the integrator's ruling: **H137-16**, the converse of the prefill
check: an integer 7 is still "shown" by a quote saying 70 (a substring). Not built.

## The owner's two decisions (#639, 7156806411 items 6 and 7)

**Mail TLS, option 2 (H137-11).** The SMTP relay's and the IMAP server's certificates and host names are checked by
default (`services/mail_gateway/tls.py`: `ssl.create_default_context()`, which reads the bundle `tb_common.extra_ca`
builds when the hospital's CA is mounted as `TB_EXTRA_CA`). One switch per server turns the check off,
`SMTP_TLS_VERIFY=false` or `IMAP_TLS_VERIFY=false`. The audit records each start of the mail gateway that runs with a
switch off (`mail.tls_unverified`, the server and its host) and each start that speaks to a server with no TLS
(`mail.plaintext`: `SMTP_STARTTLS=false` on a port other than 465, `IMAP_SSL=false`). The switch is read once at the
start and holds until the next, so "every use" is recorded per start, not per connection (the IMAP poll runs every
minute). The install check (`preflight` `mail_relay`) tests the relay's certificate as the gateway will, with the
hospital's CA file when `TB_EXTRA_CA` names one; it fails an untrusted certificate and warns when the switch is off or
there is no TLS.

**The trusted proxy, option 3 (H137-12).** One named list, `TB_CONSOLE_FORWARDED_ALLOW_IPS`
(`libs/tb_common/trusted_proxy.py`). On a box behind Caddy the identity overlay gives the internal network a fixed range
(`TB_NET_SUBNET`, default 172.31.252.0/24) and Caddy a fixed address in it (`TB_PROXY_ADDR`, default 172.31.252.250);
the installer writes that address into the list, and the console's command trusts it. The base file, without Caddy,
still trusts only 127.0.0.1, so parallel compose projects without the overlay never meet one fixed range. The install
check (`preflight` `name_cert`) fails when the fixed range clashes with a range this host is on (its addresses and
routes, container bridges left out). On the cluster form `apps.yaml` no longer trusts `*`: the console trusts
`$(TB_CONSOLE_FORWARDED_ALLOW_IPS)`, which the site names in `site.env` (empty trusts no one). "All" (`*`, `all`,
`0.0.0.0/0`, `::/0`) stops the console at start in PRODUCTION; the doctor's new line `trusted_proxy` fails it there,
warns elsewhere, and warns behind Caddy when the list lacks Caddy's address. That closes V3-01: its strict-xfail test is
a plain test now, with Caddy at its configured address. That is an assertion-state change, for the integrator to rule.

Costs, as found: a box behind Caddy needs its internal network recreated once (`docker compose down`, then `up`) for
the fixed range; a host already on 172.31.252.0/24 sets another range in `deploy/.env`.

## Files outside the card

`services/model_guard/__init__.py` (lane D); `services/edc_backend/oidc.py`, `events.py`, `config.py`, `linkmap.py`
(lane E); `services/edc/prefill.py`, `services/adapter/app.py` (lane J); `services/orchestrator/datacore_api.py`,
`services/console/audit_page.py` (lane C2); `services/console/auth.py` (lane K). For the owner's two decisions:
`libs/tb_common/config.py` (lane N); `services/mail_gateway/gateway.py`, `deploy/docker-compose.yml` (lane U);
`services/mail_gateway/app.py` (lane C2); `services/mail_gateway/outbound.py`, `deploy/platform/base/site.env` and
`tools/trialbox/doctor.py` (no owner in the ledger); `tools/trialbox/preflight.py`, `tests/unit/test_preflight.py`
(lane K: two probe stubs added to its fixture); `deploy/platform/base/apps.yaml` (lane D);
`tests/console/test_asvs_evidence.py` (lane V: V3-01's test). Lane H's own: the identity overlay, `deploy/install.sh`,
`services/console/app.py`, `services/console/i18n_audit.py`, and `tests/unit/test_trialbox_doctor.py` (one check name
added to its expected set: an assertion change, for the integrator to rule). Owners from the OCR ledger on #639.

## Not done here

The register is not edited (its keeper adds this card's `findings.json`). H137-13 to H137-16 are not built. The whole
unit and integration run was not run. The installer's new lines and the overlay's fixed range were not run on a box
(no Docker here): they are shown by reading and by the tests' reading of the files.

Outside the diff: `tests/unit/test_site_key.py::test_a_box_from_before_the_record_is_checked_against_its_pid_map` and
`::test_a_lost_site_key_refuses_the_second_night_and_the_opt_out_survives` fail on master c3a5b2b2 as on this card's
head, as root and as an ordinary user under CI's conditions; the card touches none of their files.
