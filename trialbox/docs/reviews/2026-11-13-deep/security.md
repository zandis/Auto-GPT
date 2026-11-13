# Deep review of 2026-11-13: security, privacy, access and audit

| Field | Value |
| --- | --- |
| Area | Who may act, patient data leaving the box, the audit trail, erasure, secrets, the model gateway, egress, supply chain, the scan allow lists |
| Code read | `master` at `c7dcd5e7` (train 8), and the open pull requests' file lists (to avoid their files) |
| Method | Five reviewers in parallel (identity and sessions; who may act; audit and erasure; patient data, egress and secrets; supply chain and allow lists), then one adversarial reviewer who tried to refute the top findings and to break the fixes. Its verdicts are applied below. |
| Branch | `claude/deep-review-security`: this file and six fixes, each with a test that fails before and passes after |
| Rules kept | Synthetic data only. No secret or key file read. Nothing that costs money. No new allow-list entry. No decision number taken: new decisions are `D-TBD`. |

## Terms

- **Verified by a run**: the reviewer reproduced it with a command or a script; the output is quoted.
- **By reading**: file and line only.
- **Lane**: the session that owns the fix (C2 trust and console, D box and CI, A2 decision and model, B2 night).
- **Report stage**: an orchestrator route that logs and lets through a call with no verified person (D-483).

## 1. Summary

The box's main controls are sound and should not be rebuilt: signed person claims (v3), per-service tokens bound to
routes, sessions, TOTP and OIDC, the append-only audit journal with one writer, signed heads, hashed installs and
digest-pinned images. The weak points are at the edges of those controls:

1. A secret leak that was called fixed on 2026-11-12 is still on master: the support bundle.
2. The administrator can make a patient-data account and hold both of its sign-in factors.
3. The two internet-facing images (Caddy, Authelia) are in every bundle and in no image scan.
4. One malformed audit row stopped the audit chain for good. **Fixed here.**
5. Several "closed" rows of the register are only half closed: CR-016, CR-023, CR-038, CR-045, CR-055, ROLE-006.

## 2. Findings

Severity follows the brief: Critical means a secret or patient data exposed, a wrong exclusion, data loss, or
who-may-act broken. Severities marked "(adv.)" were lowered by the adversarial reviewer, with its reason.

| # | Severity | Finding | Evidence | Run or read | Root cause | Fix | Lane |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SEC-01 | Critical | **The support bundle still leaks passwords.** `SMTP_PASS`, `IMAP_PASS`, `TB_DB_PW_ADAPTER` and `TB_KEK_PASSPHRASE` come out of `redact_secrets` in clear, in `env.redacted` and in the `docker compose config` output. OPS-002 is open: PR #324 is still a draft. It also misses flow mappings (`{client_secret: x}`). | `tools/support_bundle.py:69` | run (synthetic values through `redact_secrets`) | The redaction is a name pattern (`SECRET_KEY`); the names do not match it. | Land #324. Add flow-mapping redaction. As a last step, replace every value read from the secrets folder and `.env` by its literal, as `register_process_secrets` does for logs. | D |
| SEC-02 | High (adv.; claimed Critical) | **The administrator can provision a patient-data account.** `/ops/users` lets the admin create a coordinator, investigator or steward with every study, see its one-time password, reset any coordinator's password, and issue its TOTP enrolment code. CR-023 (D-280: the admin has no patient row) is defeated in practice. Lowered because it needs a trusted insider and leaves a named `console.user` event; on a default box (OD-12) owner, steward and admin are one person. | `services/console/app.py:1017-1060`; `services/console/identity.py:671-690`; `libs/tb_common/authz_matrix.yaml` has no `account.create` row | run: admin creates `shadow` (303), password shown, `shadow` reads a candidate page (200) | Account life sits with one role, outside the matrix. | Matrix rows `account.create.<role class>` and `account.scope`; a patient-data, steward or privacy account, or a reset of one, waits for a second person (steward or another admin). Owner's decision. | C2 |
| SEC-03 | High | **Caddy and Authelia are never image-gated, but every bundle carries them.** CVE-2026-111943 is invisible to the gate. `docs/security/08-supply-chain.md` says every third-party image is gated. | `Makefile:492` (`SC_THIRD_PARTY`: two compose files); `tools/make_bundle.sh:100-107`; master gate record lists 9 images | run (gate artifacts of master's run 43449399182) | The identity overlay was added after the gate's file list. | Land #381 (adds the identity overlay to `SC_THIRD_PARTY`); correct the page. | D |
| SEC-04 | High | **CR-045 is not closed.** All 81 vulnerability waivers lapse on 2026-12-10, and every one has `owner: security owner (to assign)`. In 27 days every image gate fails at once; vLLM cannot move without requalifying the model. | `deploy/supply-chain-allowlist.yaml` (counted with yaml) | read | OD-4 ("name one person") was never done. | Name the owner; stagger dates per image; open the vLLM requalification card before 2026-12-01. Owner's decision. | owner, D |
| SEC-05 | High | **One malformed journal row stopped the audit chain for good.** Any service role may call `audit.append`. Fields holding `ts` or `event`, a `detail` that is not an object, or a time with no zone made `Drain.step` raise TypeError or ValueError; `run()` caught only OSError; the journal is append-only, so every restart died on the same row. Services went on; their events never reached the chain. | `libs/tb_common/audit_writer.py:399-412` (before) | run (five bad rows; the chain stopped at 1 line; a restart died again) | The drain trusted the sender's field names and time. | **Fixed here**: the row is written, its values under `detail.sent_*`, marked `journal.unreadable` and flagged; the sent time is kept in the drain's own record. Test: `tests/unit/test_audit_drain_malformed_row.py`. | done; C2 to review |
| SEC-06 | Medium | **The CR-055 pattern remains: a change is committed before its audit event.** Fixed for opt-out, marks and site set-up, but not for accounts on the web (`app.py:1047-1107`), the delegation log (`team.py:731-741, 768-777`) or break-glass (`breakglass.py:205` before `:211`; if the write fails the grant is live and the privacy notice never goes). The console CLI turned a failed audit into a warning with exit 0, and its events did not name the account. | as listed; `services/console/cli.py:38-45` | read | The event goes to another store after the commit. | Use the `before_commit=` hook in `UserStore`, `TeamStore` and the break-glass store, as opt-out does. **The CLI part is fixed here** (exit 3 outside DEV and TEST, events name the account; test in `tests/console/test_identity_d279.py`). | C2 |
| SEC-07 | Medium (adv.; claimed High) | **Orchestrator data core and set-up routes still trust the body's `by`.** With the console's token alone they write trial data and export every record under any typed name. Known and documented (D-483, "report" stage, shrink-only). New here: the patient-level reads (`GET /studies/{rs}/data`, `/records`, `/export`, `/fhir`) carry no person or study check at the orchestrator. #478 moves only `study` to `refuse`. | `services/orchestrator/route_actors.yaml:25-28`; `datacore_api.py:214,223-231,410` | run (console token, no claim: 200; audit names `dr_tanaka`) | The console is the only check. | `require_actor` on data core and set-up; drop `by` from the bodies; a v3 claim whose study is `{rs}` on the reads. | C2 |
| SEC-08 | Medium (adv.; claimed High) | **The sign-in throttle counts every browser under Caddy's address.** Five bad guesses for `admin` lock it for everyone for 15 minutes; ten failures slow the whole hospital. ROLE-006 is marked fixed. D-279 says the setting is in the compose file; it is not. On the k8s base `--forwarded-allow-ips "*"` lets a client choose its address (network policy limits who can reach it; the 50-per-name ceiling and TOTP still hold). | `deploy/docker-compose.yml:343-344`; `deploy/platform/base/apps.yaml:445`; `services/console/identity.py:64-67` | run (uvicorn's proxy middleware with both settings) | The proxy trust setting was never wired to the real proxy address. | Fixed address for Caddy on `trialbox-net`, set `TB_CONSOLE_FORWARDED_ALLOW_IPS` to it in the identity overlay; the ingress CIDR in k8s; refuse `*` in PRODUCTION. | D with C2 |
| SEC-09 | Medium (adv.; claimed High) | **Chart numbers still reach the audit log in clear (CR-016 not closed).** The mail parser's error text repeats a bad option (`option '70000054' must be key=value`, `invalid value for mrn: '…'`) into `mail.rejected` `reason`; `mask_ids` masks only `key=value` forms with known key names. `/audit` and `--find-ids` use the same rule, so they neither mask nor find it. | `services/mail_gateway/intake.py:147-163`; `subject.py:93,102,107`; `gateway.py:351-357`; `libs/tb_common/audit.py:91-103` | run | Each caller masks for itself, by key name. | Store a reason code, never parser text; mask inside `AuditLog.append` and `DbAuditWriter.append` with the site's chart-number rule plus a long-digit rule (as `console/reveal.py:79-81`). | C2 |
| SEC-10 | Medium | **Any service can write `audit.*` events.** A compromised console can send a forged `audit.signing_key_rotated`; `verify --heads` then fails for good and the nightly signer refuses to sign again. It cannot hide events: integrity-check denial of service. | `libs/tb_common/audit_writer.py:274` (`_SHARED` has `audit`); `libs/tb_common/audit.py:495-496, 618-620` | run | The `audit` family is shared. | Reserve `audit.*` for `tb_audit_writer` and the admin role; `verify` ignores rotation records from other roles. | C2 |
| SEC-11 | Medium | **Signed heads cover only up to the last nightly signature.** Whoever can write the audit volume (the writer container or host root) can drop up to a day of the newest events and rewrite `HEAD.json`; `verify --heads` passes. | `libs/tb_common/audit.py` heads; `install.sh:566` (nightly) | run (truncate after a signature, rewrite HEAD: PASS) | `HEAD.json` is unkeyed; signatures are daily. | The drain signs a head every N events or every hour, or pushes the head to the share. | C2 |
| SEC-12 | Medium | **Names and dates of birth reach logs through exception text.** A pydantic error in `log.exception` logged `input_value='… Wang Xiao-Min … born 1950-03-04'`; the scrubber has rules for ids, phones and chart numbers, none for names or dates. `ServiceError` carries the callee's body (2,000 characters) into callers' logs. | `libs/tb_common/logging.py:137-138`; `libs/tb_common/http.py:228` | run (synthetic name) | Exception messages are logged. | Log the type and frames, not the message, for every record; `ServiceError` keeps status and code only. #492 covers only the unhandled-error line; `http.py` is in three open PRs. | C2 |
| SEC-13 | Medium | **Erasure reaches six stores.** Still owed: 46 tables, 9 lake entries, 2 object prefixes, the FHIR store and backups (`pidmap.identity`, `trace.traces`, snapshots, `embed_cache.duckdb`, job outputs). #278 holds only the decision and the registry. The registry also says the audit log keeps "counts only, never who"; `console.opt_out` and `console.chart_lookup` keep the `pid` and free-text reasons. | `libs/tb_common/erasure.py`, `:405-409`; `services/console/team.py:1087-1103` | run (registry dump) | Work not done yet (T-206b). | T-206b; correct the registry's audit line now. | C2 |
| SEC-14 | Medium | **A model call is audited after it went upstream.** If the journal fails the caller gets 500, retries, and makes a second unaudited call. | `services/gateway/core.py:831` | read | Order. | Write "call started" before sending. | A2 |
| SEC-15 | Medium | **The model-call guard's allow list is stale.** `tools/mlbench.py` ("bake-off harness") is the shared client that four evaluation tools use to send note text to a cloud host; `consent_live.py:47`, `canary.py:39`, `public_e2e.py:191` build `LlmClient(url, …)` directly and pass, because the check matches string literals only. `tools/` is copied into the box image. | `tests/unit/test_no_direct_model_calls.py:27`; `deploy/docker/python.Dockerfile:33` | read | Literal matching. | One entry per tool with its reason; an AST check for `LlmClient(` outside `libs/`, the gateway and tests; leave evaluation tools out of the image or refuse them in PRODUCTION. The test file is in lane G's #461. | A2 |
| SEC-16 | Medium | **Service containers have no `cap_drop` or `no-new-privileges`.** Only `model-guard` has them; Caddy listens on `0.0.0.0:443` with none. Images run as uid 10001, so the impact is limited. | `deploy/docker-compose.yml:22-45` (`x-py`), `:441-445`; `docker-compose.identity.yml:46` | read | Not added to the anchor. | `cap_drop: [ALL]` and `no-new-privileges:true` on `x-py`, Caddy (keep `NET_BIND_SERVICE`) and Authelia. | D |
| SEC-17 | Medium | **The mail gateway's and the model gateway's database roles can rewrite the box's flags** (`screening.after_restore`, `notes.reading`, `demo.mode`), or drop the table, without the audited `flags.set`. Neither service uses `Flags`. | `deploy/docker/db-init/30-service-roles.sh:77-78`; `libs/tb_common/flags.py:55,95-157` | read | Both roles are in `tbs_app`. | Owned-schema treatment for `app` (D-486): readers `tbr_app`, the console writes. | C2 |
| SEC-18 | Medium | **Licence budgets are slack or dead**: `trialbox-demo` maven 1 open of 67; vLLM 618 of 630; `postgres` no longer scanned. The gate only suggests a lower budget. | `deploy/supply-chain-allowlist.yaml:656-658, 664-666, 679` | run (master licence artifact) | No failure on an unused budget. | Lower to the open counts, remove `postgres`; the gate fails on an unused or loose budget. The file is in #381 and lane D alone may edit it. | D |
| SEC-19 | Low (adv.; claimed High) | **The orchestrator's verifier client can bypass the gateway.** With `LLM_VERIFIER_BASE_URL` set it builds a direct client with no PRODUCTION refusal, and the runbook recommends that variable as a fix. Lowered: no deploy file sets it, the orchestrator is not on `model-net`, egress drops other outbound traffic, and the doctor fails a direct pair. | `services/orchestrator/app.py:88-91`; `docs/runbook/04-troubleshooting.md:29` | run (`TB_ENV=PRODUCTION`: a direct client is built) | T-604 put the refusal in `from_config` only. | Refuse the direct branch outside DEV and TEST; fix the runbook line. `app.py` is in seven open PRs. | A2 |
| SEC-20 | Low (adv.) | **Opening a break-glass grant asks for no step-up.** The owner chose "no second person" (D-280, Q-20); a notice goes to every steward and the PI at once. | `services/console/breakglass.py:189-216` | read | — | Ask `step_up` (password and fresh TOTP) or OIDC re-auth before `bg.open`; it exists for e-signatures. | C2 |
| SEC-21 | Low (adv.; claimed Medium) | **Open redirect through `back=/\evil.example/x`** on `/help`, `/cmd`, `/ask`: a browser resolves it to another site. | `services/console/step4.py:97-98`; `site_pages.py:776` | run | Three copies of the check, two without the backslash rule. | **Fixed here** (`console/local_path.py`; test `tests/unit/test_console_local_path.py`). Left: `POST /lang` at `app.py:942` (needs the CSRF token; `app.py` is in open PRs). | done; C2 for `/lang` |
| SEC-22 | Low | **Cookie removals lack the flags they were set with** (no Secure, HttpOnly; SameSite Lax for Strict). | `app.py:889,890,901`; `identity.py:572,579,602`; `firstrun.py:230` | run | Starlette's `delete_cookie` defaults. | **`firstrun.py` fixed here** (test in `tests/console/test_firstrun.py`). The others: one `clear_cookie` helper; `app.py` and `identity.py` are in open PRs. | C2 |
| SEC-23 | Low | The first-run gate counts only enabled accounts: with every account disabled, a new host code reopens the wizard. | `services/console/firstrun.py:98-99`; `auth.py:408-411` | read | `count()` filters `disabled`. | Count every row. | C2 |
| SEC-24 | Low | Signing in over an existing session leaves the old token valid until its idle limit. | `app.py:852-891`; `identity.py:507` | read | — | End the presented `tb_console` token at login. | C2 |
| SEC-25 | Low | A callee missing from `CALLERS` accepts every service's token (model registry, guard, trace store); the trace store authorises reads by unsigned `X-TB-User`/`X-TB-Roles`; the adapter's `GET /run` and `/publish/{rid}` need no token. | `libs/tb_common/service_auth.py:85-94,198-201`; `services/tracestore/app.py:27-37`; `services/adapter/app.py:39,115-128` | read | Default allow. | Default refuse (only `operator`); list real callers; `protect_reads` on the adapter. | C2 |
| SEC-26 | Low | Missing audit events: API logout (`home.py:1425-1430`); KEK and pid-map key rotation (`tools/keys.py`). `DbAuditWriter._call` can write one event twice after a late `OperationalError` (`audit_writer.py:168-179`). `audit_verify --heads` without `--pubkey` trusts whatever keys the anchor folder holds. | as listed | read | — | Add the events; idempotent insert; require `--pubkey` or the box's pinned keys. | C2 |
| SEC-27 | Low | Secrets reach containers as environment variables (`TB_KEK_PASSPHRASE`, `TB_KMS_TOKEN`, `SMTP_PASS`, `IMAP_PASS`, `CLOUD_LLM_API_KEY`, passwords in `TB_DB_URL`), visible in `docker inspect`. | `deploy/docker-compose.secrets.yml`; `deploy/.env` | read | — | `*_FILE` compose secrets, as done for the model key. | D |
| SEC-28 | Low | A failed `network.sh apply` at install only warns, leaving `egress-net` with NAT out until the doctor fails it. | `deploy/install.sh:523-524`; `check_host.sh:226-229` | read | — | Fatal in VALIDATION and PRODUCTION. | D |
| SEC-29 | Low | Two bandit ignores matched nothing (`tools/trialbox/backup.py` B324, `logs.py` B103) and would let the next finding of that rule in that file pass; the scan printed only a note. | `tools/security_scan_ignores.yaml:93,107` (before); `tools/security_scan.py:103-107` | run | Dead entries were notes. | **Fixed here**: removed, and an ignore that matches nothing now fails (test in `tests/unit/test_security_scan.py`). Decision `D-TBD`. | done |
| SEC-30 | Low | `/healthz` answers the environment and schema name without sign-in (ROLE-007 still open). | `app.py:806-820`; `db.py:395` | read | — | Answer status only. | C2 |
| SEC-31 | Low | Documentation drift: `08-supply-chain.md` names MailHog and `SC_AMD64_ONLY`, old jar budgets, and says every image-changing PR is gated (since D-578 only trains). `known-image-findings.md` counts differ from the yaml. The hosted-demo Caddy pin is outside `images.lock`. | as named; `deploy/gcp/hosted-demo-startup.sh:46` | read | Counts copied by hand. | Correct; derive counts by a test. | D |
| SEC-32 | Info | The REDCap CSV has no formula guard (the XLSX has). If deliberate (REDCap import needs raw values) say so in `services/datacore/export.py`. `docker-compose.acceptance.yml:85,87` puts test mail passwords on a JVM command line. `poc.sh gpu` should refuse a real site folder. | as named | read | — | As stated. | E, D |

## 3. The register's rows checked against the code

| Row | Register says | Code says | How checked |
| --- | --- | --- | --- |
| CR-016 chart numbers in the audit | fixed by FG-C | **open**: SEC-09 | run |
| CR-022 `/ask` verdicts | open | closed: study, delegation and opt-out checks, a cap, an audit (`site_pages.py:317-336`) | read |
| CR-023 administrator holds patient rights | matrix done | matrix closed; defeated by SEC-02 | run |
| CR-024 permission sprawl | workstream | matrix exists; nine `study_or_404` copies remain (no gap found in the samples) | read |
| CR-033, CR-034, CR-039 identity | in progress / open | closed (TOTP default; forced change; header SSO refused with TOTP or OIDC). The audit flood of CR-039 remains in DEV and TEST (`app.py:526-528`) | read |
| CR-037 one database role | open | per-service roles in place; residue SEC-17 | read |
| CR-038 orchestrator trusts `by` | open | half closed: mail gateway refused; SEC-07 | run |
| CR-040 gateway caller | open | closed (`gateway/policy.py:307-325`) | read |
| CR-041 Windows keys and disks | open | largely present (KEK wrapping, BitLocker, page file, swap checks); not run on Windows | read |
| CR-043 egress not persisted | open | fixed in code (state file, boot restore, timer; `deploy/egress.py:41-48,363`); not run on a host | read |
| CR-044, CR-046, CR-047 supply chain and updates | open | closed (523 hashes, digests, `--gates` required, key id, expiry, anti-rollback) | run (pip-audit clean) and read |
| CR-045 image vulnerabilities | owner | **open**: SEC-03, SEC-04 | run |
| CR-048 cloud-run door key | open | TLS part closed; bucket path not checked | read |
| CR-054 audit head anchor | fixed | closed for the head; SEC-11 remains | run |
| CR-055 commit before audit | fixed | fixed where the register pointed; SEC-06 elsewhere | read |
| ROLE-001 API without second factor | fixed | closed | read |
| ROLE-006 lockout by address | fixed | **not closed in practice**: SEC-08 | run |
| OPS-002 support bundle | "fixed in #324" | **open on master**: SEC-01 | run |

Refusals stay refusals when the audit write fails: checked for `console.denied`, `console.refused`,
`reveal_refused` and `login_failed`. A failed write raises, the request is 500, and a retry never turns it into a
success. Failure counting at sign-in happens before the audit write. Verified by reading.

## 4. What is good and should not be changed

- **Who may act**: the v3 person claim (action, study, method, path, body hash, nonce, replay guard); `route_callers.yaml` with `assert_staged`; fail-closed tokens; the shared token refused outside DEV and TEST; the reveal path (audit first, cap in one transaction).
- **Sessions**: 256-bit tokens stored as SHA-256; a new token at every sign-in step; idle and absolute limits; sessions ended on password change, disable and authenticator reset; the role re-read on every request; CSRF on every changing cookie route; strict CSP, `X-Frame-Options DENY`.
- **TOTP and OIDC**: ±1 step with a strictly increasing step; PKCE S256, state, nonce, `iss`/`aud`/`azp` checks, `amr` required, the subject pinned.
- **Audit**: one writer through an append-only journal; `session_user` per row; the volume read-only for services; torn-line repair that keeps the evidence; signed heads with endorsed rotation; the archive refusing a changed closed day.
- **Data and egress**: `model_guard`'s fixed path list; internal networks; egress opened to the gateway only, with a doctor check; the tripwire on D0 to D2; backups always encrypted.
- **Supply chain**: hashed installs, digest pins, actions pinned by SHA, no `pull_request_target`, `contents: read`; fail-closed `bundle-check`; data scan reports unreadable files as unscanned; 180-day maximum on review dates.

## 5. Needless weight

- Nine copies of `study_or_404` with three rules; legacy permission wrappers (`study_tasks`, `edc_allowed`, `edc_role_may`) beside `permit`.
- Three ways to name a person (v2 assertion, v3 claim, body `by`) and two tables (`route_callers.yaml`, `route_actors.yaml`) over the same route groups. When the report stage is gone, one table and one claim are enough.
- Three copies of the safe-return-path check (now one helper for two of them; `demo_guard._back` and `feedback.py:94` keep theirs).
- About 30 copies of the same HAPI and vLLM waiver reason and nine entries for one gnupg CVE; one block per image with a list of ids would be shorter to review.
- `known-image-findings.md` repeats counts the yaml already holds.

## 6. Fixes on this branch

| Fix | Files | Test (fails before, passes after) |
| --- | --- | --- |
| The first-run cookie is removed with its own flags (SEC-22) | `services/console/firstrun.py` | `tests/console/test_firstrun.py::test_the_first_run_cookie_is_removed_with_the_flags_it_was_set_with` |
| A `back=` path stays on the console (SEC-21) | `services/console/local_path.py`, `step4.py`, `site_pages.py` | `tests/unit/test_console_local_path.py` |
| A malformed journal row is written, marked and flagged; the drain never stops on it (SEC-05) | `libs/tb_common/audit_writer.py` | `tests/unit/test_audit_drain_malformed_row.py` |
| The console CLI names the account and exits 3 when its audit is lost outside DEV and TEST (SEC-06, part) | `services/console/cli.py` | `tests/console/test_identity_d279.py::test_the_command_line_names_the_account_and_fails_when_its_audit_is_not_written` |
| Two dead bandit ignores removed; an ignore that matches nothing fails the scan (SEC-29) | `tools/security_scan.py`, `tools/security_scan_ignores.yaml` | `tests/unit/test_security_scan.py::test_an_ignore_that_matches_nothing_fails` |

None of these changes who is excluded, who may act, restore, or what the night publishes. The adversarial reviewer
passed fixes (a) to (d) and found three defects in them (a planted `sent_ts`, an unflagged malformed row, the CLI's
ingest path); all three are fixed in the last commit.

## 7. For the owner

| Question | Recommendation |
| --- | --- |
| May the administrator alone create a patient-data or steward account and hold its factors (SEC-02)? | No: a second person (steward, or another admin) confirms such an account and any reset of one. `D-TBD`. |
| Who owns the 81 waivers that lapse on 2026-12-10 (SEC-04)? | Name one person now; stagger the dates per image; requalify vLLM before 2026-12-01. |
| Land #324 (support bundle) and #381 (identity images in the gate) | Yes, before any bundle leaves a box. |
| The sign-in throttle behind Caddy (SEC-08) | A fixed Caddy address on `trialbox-net`, trusted by the console; `*` refused in PRODUCTION. |
| A scan ignore that matches nothing now fails (SEC-29) | Keep it. `D-TBD`. |
| Reserve `audit.*` events for the audit writer (SEC-10) | Yes. |

## 8. Not run

No Docker daemon: no image scan was run locally (the CI gate artifacts of master were read instead), no compose box,
no network rules applied. The PostgreSQL-backed console tests could not start a local cluster for one reviewer (a
directory permission of the sandbox); its findings there are by reading and by scripts against the project's code.
Windows checks were read, not run.

`tests/integration/test_e2e_simple.py` failed here before reaching any changed code: the first FEAS job stops in the
criteria compiler with "the CQL translator is not installed (FHIRHelpers-4.0.1.cql not found in its jars)", and
`make jvm-deps` could not resolve its Maven artifacts through this machine's proxy. It needs a machine with the jars.

What passed locally on this branch: ruff check and format, mypy (1,273 files), doclint, the data scan, both security
scans, the Makefile's cross-card list (229 passed), and the 20 test files that touch the changed modules (412 passed).
