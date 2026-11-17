# ASVS Level 2 checklist, filled against the code, 2026-11-17 (card V-3)

**Reader:** the integrator, and lanes C2 (console, accounts, sessions, roles, audit) and D (deploy, proxy, hardening)

**Verdict.** Plan 8's exit for V9 ("no 'does not meet' left in authentication, session and access control") is not
met. Access control (V4) meets every Level 1 and Level 2 requirement judged, and 8 of its 9 lines are shown by a test
that ran. Session management (V3) has two "does not meet": the cookie has no `__Host-` prefix (V3-02) and a person
cannot see or end their other sessions (V3-03). Authentication (V2) has six: the sign-in lock behind Caddy can be
turned against a named person (V3-01, the full review's J-4), a password history the standard advises against but a
decision chose (V3-06), no pepper (V3-09), service passwords in environment variables (V3-13), and two password-page
aids (V3-08). Nineteen findings in all: two High (a chart number in free audit text that is never erased, V3-14; a
break-glass grant stored before its audit event, V3-18), sixteen Medium, one Low.

The standard is OWASP ASVS 4.0.3, as the full review used (`docs/reviews/2026-11-17-full-review.md`, area J), at
the level of the single requirement. The requirement texts here are this card's own short paraphrases, not ASVS's
words. Line numbers are for master `d7c91fc3` (the commit `checklist.json` names); `python -m tools.asvs_checklist
--check` fails when a named file is shorter than its line or a named test is gone.

## What was judged, and how

- V2, V3 and V4 in full: every Level 1 and Level 2 requirement of 4.0.3 that I could name, one line each (Level 3
  only lines are left out). V1, V5 to V9, V12 to V14 in part; V10 and V11 not assessed. A chapter or part not
  reached is a line "not assessed", never a guess.
- "Meets" needs a file and line that was read. **Basis** says how sure: *shown* (a test named on the line ran and
  showed it; for "does not meet" or "partly" the test shows the gap), *hypothesis* (read from code, not run),
  *not_run*. Where the box hands a control to Authelia and the hospital directory (directory accounts through
  OIDC), the line says "Delegated" and the evidence is the configuration line that sets it
  (`deploy/identity/authelia/configuration.example.yml`, `deploy/docker-compose.identity.yml`).
- Tests that ran (the outputs are in the card's scratch folder, named in the report): the new
  `tests/console/test_asvs_evidence.py` (10 passed, 6 xfailed: the six findings it shows), and the 26 existing tests
  this page cites (46 cases with their parameters, all passed). Nothing was run against a live stack, Caddy or
  Authelia; no scanner ran.
- The data: `asvs-l2-checklist-2026-11-17/checklist.json` (one object per requirement: id, chapter, level, the
  paraphrase, verdict, basis, file, line, further evidence, tests, note, finding) and `findings.json`.

## The counts

Per chapter and verdict, printed from `checklist.json` by `python -m tools.asvs_checklist --table`; `--check` fails
when this table and the json differ. A "-rest" line stands for the unlisted part of a chapter.

<!-- counts:start -->
| Chapter | meets | does not meet | partly | not applicable | not determined | not assessed | lines |
|---|---|---|---|---|---|---|---|
| V1 | 1 | 1 | 1 | 0 | 0 | 1 | 4 |
| V2 | 17 | 6 | 13 | 15 | 1 | 0 | 52 |
| V3 | 13 | 2 | 1 | 2 | 0 | 0 | 18 |
| V4 | 9 | 0 | 0 | 0 | 0 | 0 | 9 |
| V5 | 5 | 0 | 0 | 0 | 0 | 1 | 6 |
| V6 | 5 | 1 | 1 | 0 | 0 | 1 | 8 |
| V7 | 5 | 0 | 3 | 0 | 0 | 1 | 9 |
| V8 | 2 | 0 | 1 | 0 | 0 | 1 | 4 |
| V9 | 3 | 0 | 1 | 0 | 0 | 1 | 5 |
| V10 | 0 | 0 | 0 | 0 | 0 | 1 | 1 |
| V11 | 0 | 0 | 0 | 0 | 0 | 1 | 1 |
| V12 | 1 | 0 | 0 | 0 | 0 | 1 | 2 |
| V13 | 2 | 0 | 0 | 0 | 0 | 1 | 3 |
| V14 | 8 | 0 | 1 | 0 | 0 | 1 | 10 |
| all | 71 | 10 | 22 | 17 | 1 | 11 | 132 |
<!-- counts:end -->

**V2 Authentication (52 lines):** 17 meets, 6 does not meet (2.1.8, 2.1.10, 2.1.12, 2.2.1, 2.4.5, 2.10.3), 13
partly, 15 not applicable (no look-up secrets, no out-of-band or cryptographic verifier in the console, PBKDF2 and
bcrypt not used), 1 not determined (2.5.7, identity proofing at a reset: a procedure, not code).

**V3 Session management (18 lines):** 13 meets, 2 does not meet (3.3.4, 3.4.4), 1 partly (3.7.1: break-glass asks
for no fresh credential), 2 not applicable (3.5.1, 3.5.3: no OAuth grants to other applications, no stateless
tokens).

**V4 Access control (9 lines):** 9 meets. The console's whole router table, walked by nine roles, equals the design
table and the matrix (`tests/console/test_role_route_matrix.py`); a new walk of every changing page route as three
roles, with no CSRF token, finds no route that acts (`test_v4_2_2_every_changing_page_route_refuses_a_post_without_the_csrf_token`).

## Findings

Severity by the integrator's rule of 2026-11-17 13:30: High = a patient harmed or wrongly excluded, data leaked or
not erased, a role doing what the matrix forbids, an audit trail that can be wrong, or a box that cannot be installed
or restored; Medium = a person slowed or misled, or a document's claim not true; Low = wording. A gap against ASVS
with none of the High harms is Medium here, because plan 8's V9 claims the box resists attack. `findings.json` adds
`blocks_v9_exit` (true for the findings behind a "does not meet" or "partly" in V2, V3 or V4).

| Id | ASVS | Place | Expected | What happened | Severity | Lane | Basis | Full review |
|---|---|---|---|---|---|---|---|---|
| V3-01 | 2.2.1 | `deploy/docker-compose.identity.yml:93` | ASVS 2.2.1: anti-automation must not allow a lock-out attack; D-279 counts failures per account and address. | **Behind Caddy every browser shares one address, so five wrong guesses lock a named person out on every PC.** Neither the identity overlay nor deploy/install.sh sets TB_CONSOLE_FORWARDED_ALLOW_IPS; uvicorn keeps its default 127.0.0.1 (deploy/docker-compose.yml:366), so the console sees Caddy's address for everyone. Test: `test_v2_2_1_the_console_behind_caddy_trusts_the_proxy_address` (xfail). | Medium | D | shown | J-4 (confirmed) |
| V3-02 | 3.4.4 | `services/console/app.py:93` | ASVS 3.4.4: a session cookie named __Host-..., Secure, Path=/, no Domain. | **The session cookie has no __Host- prefix.** The cookie is named tb_console; a sibling host name (Authelia's is a sub-name in the example) could set one. Test: `test_v3_4_4_the_session_cookie_has_the_host_prefix` (xfail). | Medium | C2 | shown | new |
| V3-03 | 3.3.4 | `services/console/auth.py:840` | ASVS 3.3.4: a person can list active sessions and end any or all. | **A person cannot see or end their other sessions, and a new sign-in leaves older ones alive.** No page lists sessions; UserStore.end_sessions is called by no page; new_session (auth.py:748) ends nothing. | Medium | C2 | hypothesis | J V3 'an older session survives a new sign-in' (confirmed by reading) |
| V3-04 | 3.7.1 | `services/console/breakglass.py:189` | ASVS 3.7.1: a sensitive action asks for a fresh sign-in or second check, as signing does (identity.py:306). | **A break-glass grant opens on the session alone, with no fresh password or code.** POST /breakglass needs only the CSRF token, a reason and a note. Test: `test_v3_7_1_break_glass_asks_for_a_fresh_credential` (xfail). | Medium | C2 | shown | J-M3, first half (confirmed) |
| V3-05 | 2.1.2, 2.1.3 | `services/console/app.py:1033` | ASVS 2.1.2 and 2.1.3: long passwords allowed, more than 128 may be refused, none cut short. | **A password longer than 256 characters is accepted when chosen and never signs in.** check_password_policy has no maximum; the sign-in passes password[:256], which never matches the hash of the whole password, so the owner is locked out of their own account. Test: `test_v2_1_2_a_long_password_that_is_accepted_also_signs_in` (xfail). | Medium | C2 | shown | new |
| V3-06 | 2.1.10 | `services/console/auth.py:616` | ASVS 2.1.10: no history rule. D-447 chose a history of five after the MHLW guideline v7.0: a recorded ruling. | **A password history of five is enforced, which ASVS 2.1.10 says not to do.** The owner's own change refuses the last five passwords. Plan 8's exit for V9 asks for no 'does not meet' in V2, so the ruling and the plan disagree: the owner rules which holds. Test: `test_the_last_five_passwords_cannot_be_chosen_again`. | Medium | C2 | shown | new |
| V3-07 | 2.1.7 | `services/console/breached.py:14` | ASVS 2.1.7: every new password is checked against a breached list. | **In PRODUCTION no breached-password check runs unless the operator supplies the list; nothing warns.** Unset TB_CONSOLE_BREACHED_PASSWORDS_FILE means no check; no list ships; no doctor or installer check names it (grep of tools/ and deploy/ found no 'breached'). | Medium | D | hypothesis | new |
| V3-08 | 2.1.4, 2.1.8, 2.1.12 | `services/console/templates/account.html:36` | ASVS 2.1.4, 2.1.8, 2.1.12. | **The password fields have no strength meter and no show-password control, and refuse spaces at the ends.** None of the three in login, account, first sign-in or first-run pages; check_password_policy refuses white space at either end (auth.py:248). | Medium | C2 | hypothesis | new |
| V3-09 | 2.4.5 | `services/console/auth.py:216` | ASVS 2.4.5: a second derivation with a secret kept apart from the hashes. | **Password hashes have no secret pepper.** scrypt over the password and its stored salt only; a copy of the auth schema is enough for offline guessing. | Medium | C2 | hypothesis | new |
| V3-10 | 2.3.2 | `docs/decisions/D-447-identity-leftovers.md:55` | ASVS 2.3.2: security keys can be enrolled and used. | **Local accounts cannot use a security key; only directory accounts can (through Authelia).** TOTP only for local accounts (D-447 'Open'); the administrator's own account is local. | Medium | C2 | hypothesis | new |
| V3-11 | 2.2.3, 2.5.5, 2.8.5 | `services/console/account_rules.py:135` | ASVS 2.2.3, 2.5.5, 2.8.5: the holder is told after a change of a factor and of a replayed code. | **The holder is not told of a replayed code, of their own password change or of a new sign-in.** Notices exist only when someone else resets or opens the account (D-719); a replayed code is audited only (identity.py:502). | Medium | C2 | hypothesis | new |
| V3-12 | 3.4.1-3.4.3 | `services/console/app.py:1067` | The removal carries Secure, HttpOnly and SameSite=Strict like the cookie (firstrun.py:243 does). | **Sign-out removes the session cookie without the flags it was set with.** Set-Cookie: tb_console=""; Max-Age=0; Path=/; SameSite=lax. The session row is deleted on the server first, so no session survives; Low because nothing is exposed. Test: `test_v3_4_sign_out_removes_the_cookie_with_the_flags_it_was_set_with` (xfail). | Low | C2 | shown | J-L2 (confirmed) |
| V3-13 | 2.10.3, 2.10.4, 6.4.1, 6.4.2, 2.8.2 | `deploy/docker-compose.yml:368` | ASVS 6.4.1: a secrets-management solution; 2.10.3: service passwords resist offline recovery. | **Database, mail and KEK passwords are environment variables; the TOTP key is a plain file in the console volume.** deploy/.env reaches every container (env_file, docker-compose.yml:31); each service's database password is in its TB_DB_URL. Tokens and the model key are files (docker-compose.secrets.yml), the rest is not. | Medium | D | hypothesis | J-M5 (confirmed) |
| V3-14 | 7.1.2 | `libs/tb_common/audit.py:106` | ASVS 7.1.2: no identifying data in logs; plan 8 criterion 8: nothing of a person stays after erasure. | **A chart number typed in free text (a break-glass note, a reason) stays in the audit, which is never erased.** mask_detail masks by key name and 'key=value' only; breakglass.py:211 writes the typed note into the audit detail (path read from code; the mask shown by the test). Test: `test_v7_1_2_a_chart_number_in_a_free_text_note_is_masked` (xfail). | High | C2 | shown | J-M1 (confirmed) |
| V3-15 | 1.2.2 | `libs/tb_common/service_auth.py:201` | The module's own docstring (line 11): a callee 'accepts only the callers of CALLERS (403 otherwise)'. | **A service not listed in CALLERS accepts any service's token.** allowed() returns True for an unlisted callee. Every deployed service is listed today, so the gap is latent; the trace store's HTTP app (unsigned role headers) is started by no compose file. | Medium | D | hypothesis | J-M6 (confirmed in code; latent) |
| V3-16 | 1.1.2 | `docs/security/01-the-host.md:1` | ASVS 1.1.2: a threat model for the design and each change. | **No threat model is on file.** docs/security/ has ten files and none is a threat model; none in docs/validation/. | Medium | D | hypothesis | J V1 (confirmed) |
| V3-17 | 2.3.1 | `services/console/account_rules.py:132` | ASVS 2.3.1: a system-made first or reset secret expires after a short time. | **A password an administrator resets never expires until it is used.** random_password() with must_change, but no expiry; a new account's code expires in 24 hours. | Medium | C2 | hypothesis | new |
| V3-18 | 7.1.3 | `services/console/breakglass.py:205` | The 13:30 severity rule: an audit trail that can be wrong is High; ASVS 7.1.3 security events are logged. | **A break-glass grant is stored before its audit event is written, so a failed write leaves an open grant the audit trail does not show.** bg.open commits at line 205; au.append('console.breakglass_open') follows at line 211. The steward's review list reads the grant store, so the grant is still seen there. | High | C2 | hypothesis | J-M3, second half (confirmed by reading) |
| V3-19 | 8.2.2 | `services/console/static/console.js:56` | ASVS 8.2.2: data in browser storage is cleared when the session ends. D-777 keeps the note on purpose. | **A typed mark note stays in the tab's session storage after sign-out and is put back for the next person who opens that patient in that tab.** Nothing clears tb-note:* at sign-out; on a shared clinic PC the next account sees the earlier person's note. | Medium | C2 | hypothesis | new |

The xfail tests are `xfail(strict=True)` with the finding's id in the reason: each turns the build red the day the
product is fixed, until its mark is removed.

## Against the full review's area J

| Full review | State on `d7c91fc3` | Here |
| --- | --- | --- |
| J-4 the sign-in throttle can lock a whole hospital | **Confirmed**, shown: the overlay and the installer set no trusted proxy | V3-01 |
| J-M1 identifiers in audit free text | **Confirmed**, shown on the mask; Medium there, High here by the 13:30 rule (never erased) | V3-14 |
| J-M3 break-glass: no fresh password; committed before its audit event | **Both confirmed**: the first shown, the second read | V3-04, V3-18 |
| J-M5 passwords and the key passphrase in environment variables | **Confirmed** (read) | V3-13 |
| J-M6 an unlisted callee accepts any token; the trace store trusts unsigned headers | **Confirmed in code, latent**: every deployed service is in `CALLERS`, and no compose file starts the trace store's HTTP app | V3-15 |
| J-L2 cookie removals without the original flags | **Confirmed**, shown | V3-12 |
| J V1 no threat model | **Confirmed** (ten files in `docs/security/`, none a threat model) | V3-16 |
| J V3 an older session survives a new sign-in | **Confirmed** by reading `auth.py:748` | in V3-03 |
| J-M8 no ASVS self-assessment, no dynamic scan, no outside test | The self-assessment is this page; the scan is the next section; the outside test is not this card's | - |
| J-M4 containers lack capability drop | **Confirmed** by reading: only `model-guard` has `cap_drop` (`deploy/docker-compose.yml:469`); no single ASVS L2 line, so not a line here | - |
| J-L1 `/healthz` shows the environment without sign-in | **Confirmed** by reading `services/console/app.py:968`; no ASVS L2 line names it | - |
| J-L3 the password-zip mail path still ships | **Still partly**: `zip` mode exists; a patient file is refused in it unless `allow_phi_zip` (`services/mail_gateway/outbound.py:233`). Not a line here | - |
| "No second factor; header sign-on" (2026-11-08) | **Fixed, shown** (`test_trusted_header_never_skips_the_password_or_the_second_factor`, `test_totp_is_the_default_outside_dev_and_test_and_cannot_be_turned_off_in_production`) | 4.3.1 |
| J V4 "meets, one gap" | **Agreed**: V4 meets; the gap (break-glass) is judged under 3.7.1 | V3-04 |
| J-1, J-2, J-3, J-5, J-M2, J-M7 | Not assessed by this card (waivers, erasure, withdrawal, the model pair, head signing, DNS) | - |

New here: V3-02, V3-05, V3-06, V3-07, V3-08, V3-09, V3-10, V3-11, V3-17, V3-19. None of the review's area J
findings that this card looked at was found closed.

## Every line

The paraphrases are short and in this card's words. "Delegated" names the party whose control it is. Tests are named
by function; their files are in `checklist.json`.

#### V2

| ASVS | Lvl | Requirement (paraphrase) | Verdict | Basis | Evidence | Finding |
|---|---|---|---|---|---|---|
| 2.1.1 | L1 | A password a person chooses has at least 12 characters. *Local accounts. Directory accounts: the hospital directory's own policy. Delegated: Authelia and the hospital directory, for directory (OIDC) accounts.* | **meets** | shown | `services/console/auth.py:246`; `services/console/auth.py:63`; `test_a_listed_password_is_refused_at_creation_and_change` |  |
| 2.1.2 | L1 | Passwords of 64 characters or more are allowed; more than 128 may be refused. *Up to 256 characters work. Nothing refuses more than 128: the change page takes any length, but the sign-in reads only 256, so a longer password never signs in.* | **partly** | shown | `services/console/app.py:1033`; `services/console/templates/login.html:23`; `services/console/templates/account.html:36`; `test_v2_1_2_a_password_of_200_characters_signs_in`; `test_v2_1_2_a_long_password_that_is_accepted_also_signs_in` | V3-05 |
| 2.1.3 | L1 | A password is never cut short before it is checked. *The sign-in cuts at 256 characters; the stored hash is of the whole password, so a cut password is refused, never accepted (V3-05).* | **partly** | shown | `services/console/app.py:1033`; `services/console/auth.py:609`; `test_v2_1_2_a_long_password_that_is_accepted_also_signs_in` | V3-05 |
| 2.1.4 | L1 | Any printable Unicode character, spaces included, is allowed in a password. *Any character is allowed inside the password; white space at either end is refused.* | **partly** | hypothesis | `services/console/auth.py:248` | V3-08 |
| 2.1.5 | L1 | A person can change their own password. *Directory accounts change it at the directory (the console refuses: account.err.sso). Delegated: Authelia and the hospital directory, for directory (OIDC) accounts.* | **meets** | shown | `services/console/step4.py:216`; `test_v3_7_1_a_password_change_asks_for_the_current_password`; `test_the_last_five_passwords_cannot_be_chosen_again` |  |
| 2.1.6 | L1 | Changing a password needs the current one and the new one. | **meets** | shown | `services/console/step4.py:235`; `test_v3_7_1_a_password_change_asks_for_the_current_password` |  |
| 2.1.7 | L1 | A new password is checked against a list of breached passwords. *The check works when the operator gives the list (TB_CONSOLE_BREACHED_PASSWORDS_FILE). Unset, there is no check, in PRODUCTION too; no list ships and no doctor check was found (grep of tools/ and deploy/).* | **partly** | hypothesis | `services/console/auth.py:250`; `services/console/breached.py:14`; `test_a_listed_password_is_refused_at_creation_and_change`; `test_a_configured_list_that_cannot_be_used_refuses_every_password` | V3-07 |
| 2.1.8 | L1 | A strength meter helps the person choose a stronger password. *No meter in the change, first sign-in or first-run pages (grep for 'strength' in templates and static).* | **does not meet** | hypothesis | `services/console/templates/account.html:36` | V3-08 |
| 2.1.9 | L1 | No rule demands kinds of characters (upper case, digits, symbols). *check_password_policy asks for length, no white space at the ends and the breached list only.* | **meets** | hypothesis | `services/console/auth.py:241` |  |
| 2.1.10 | L1 | No forced periodic change and no password-history rule. *No periodic change. A history of five is enforced on the owner's own change: a recorded ruling (D-447, after the MHLW guideline v7.0) that goes against this requirement.* | **does not meet** | shown | `services/console/auth.py:616`; `docs/decisions/D-447-identity-leftovers.md:31`; `test_the_last_five_passwords_cannot_be_chosen_again` | V3-06 |
| 2.1.11 | L1 | Pasting and password managers work in password fields. *autocomplete names the field; no script blocks paste (grep for onpaste found none).* | **meets** | hypothesis | `services/console/templates/login.html:23`; `services/console/templates/account.html:35` |  |
| 2.1.12 | L1 | The person can see the masked password, or its last character, for a moment. *No show-password control on any password field.* | **does not meet** | hypothesis | `services/console/templates/login.html:23` | V3-08 |
| 2.2.1 | L1 | Anti-automation stops credential stuffing, brute force and lock-out attacks. *The lock is per account and address (D-279). Behind Caddy every browser is Caddy's address, because the identity overlay and the installer never set TB_CONSOLE_FORWARDED_ALLOW_IPS: five wrong guesses for a name lock that person out for every PC, which is the lock-out attack this requirement names. Directory accounts: Authelia's regulation (5 in 15 min) applies too. Delegated: Authelia and the hospital directory, for directory (OIDC) accounts.* | **does not meet** | shown | `services/console/identity.py:68`; `services/console/auth.py:677`; `services/console/auth.py:694`; `deploy/docker-compose.yml:366`; `deploy/docker-compose.identity.yml:93`; `test_v2_2_1_the_console_behind_caddy_trusts_the_proxy_address`; `test_v2_2_1_five_wrong_passwords_lock_the_name_from_that_address`; `test_password_lockout_and_the_audited_unlock` | V3-01 |
| 2.2.2 | L1 | Weak authenticators (SMS, e-mail) serve only as a second step and never replace a stronger one. *No code is sent by SMS or mail. The enrolment code and its link are shown on screen once (D-776). **Id to be checked.*** | **meets** | hypothesis | `services/console/identity.py:710`; `deploy/identity/authelia/configuration.example.yml:22` |  |
| 2.2.3 | L1 | The person is told after a change to their sign-in details (reset, new address, new sign-in). *A reset or opening by someone else is told at the next sign-in and to the steward and PI (D-719). The holder is not told of their own password change, of a sign-in from a new place, or of a replayed code.* | **partly** | hypothesis | `services/console/account_rules.py:135`; `services/console/auth.py:1102` | V3-11 |
| 2.3.1 | L1 | First or reset passwords made by the system are random, short-lived, and must be replaced. *Random (about 99 bits) and replaced at first sign-in (must_change). A new account's code expires in 24 hours, but a password an administrator resets has no expiry: it works until used.* | **partly** | hypothesis | `services/console/account_rules.py:132`; `services/console/auth.py:271`; `services/console/auth.py:961`; `services/console/auth.py:1160` | V3-17 |
| 2.3.2 | L2 | Security keys and similar devices (FIDO, U2F) can be enrolled and used. *Directory accounts: WebAuthn at Authelia. Local accounts: TOTP only (D-447 'Open'). Delegated: Authelia and the hospital directory, for directory (OIDC) accounts.* | **partly** | hypothesis | `deploy/identity/authelia/configuration.example.yml:30`; `docs/decisions/D-447-identity-leftovers.md:55` | V3-10 |
| 2.3.3 | L2 | Renewal notices are sent in time for authenticators that expire. *No authenticator here expires by date (no client certificate, no password expiry).* | **not applicable** | hypothesis | - |  |
| 2.4.1 | L2 | Passwords are stored salted and hashed with an approved slow one-way function. *scrypt N=2^14, r=8, p=1.* | **meets** | hypothesis | `services/console/auth.py:218`; `services/console/auth.py:76` |  |
| 2.4.2 | L2 | The salt has at least 32 bits and is unique per password. *16 random bytes per hash.* | **meets** | hypothesis | `services/console/auth.py:217` |  |
| 2.4.3 | L2 | With PBKDF2, the iteration count is high enough. *scrypt, not PBKDF2.* | **not applicable** | hypothesis | `services/console/auth.py:218` |  |
| 2.4.4 | L2 | With bcrypt, the work factor is high enough. *scrypt, not bcrypt.* | **not applicable** | hypothesis | `services/console/auth.py:218` |  |
| 2.4.5 | L2 | A second derivation with a secret salt (a pepper) kept apart from the hashes. *No pepper: the hash depends on the password and its stored salt only. **Id to be checked.*** | **does not meet** | hypothesis | `services/console/auth.py:216` | V3-09 |
| 2.5.1 | L1 | A first-use or recovery secret is never sent in clear text. *Shown once on the administrator's page; the link keeps the code after '#', so no request line or log holds it.* | **meets** | shown | `services/console/identity.py:710`; `services/console/auth.py:1011`; `test_the_link_works_once_like_the_code` |  |
| 2.5.2 | L1 | No password hints or secret questions. *None exist (grep for 'hint' and 'question' in the sign-in and account code).* | **meets** | hypothesis | `services/console/auth.py:241` |  |
| 2.5.3 | L1 | Recovery never shows the current password. *Only hashes are stored; a reset gives a new code or password.* | **meets** | hypothesis | `services/console/auth.py:870` |  |
| 2.5.4 | L1 | No shared or default accounts (root, admin, sa). *The first administrator is named 'admin' unless the operator names it, but it has no default password: random or from a secret file, and replaced at first sign-in. The first-run wizard names it from the owner's user name.* | **partly** | hypothesis | `services/console/auth.py:1154`; `services/console/cli.py:133` |  |
| 2.5.5 | L1 | The person is told when a factor is changed or replaced. *Told when someone else resets it (D-719). Not told of their own change.* | **partly** | hypothesis | `services/console/account_rules.py:135`; `services/console/auth.py:1102` | V3-11 |
| 2.5.6 | L1 | Forgotten-password and recovery paths use a secure mechanism. *Recovery is an administrator's reset with a one-time code; for a protected account a second person confirms and nobody holds both factors (D-719). The code is about 79 bits, stored as unsalted SHA-256, alive 24 hours.* | **meets** | shown | `services/console/identity.py:716`; `services/console/account_rules.py:132`; `test_admin_resets_an_authenticator_and_only_an_admin_may`; `test_the_administrator_never_holds_both_factors_within_30_days` |  |
| 2.5.7 | L2 | A lost factor is replaced only after identity proofing as strong as at enrolment. *A procedure, not code: would be determined by the runbook's identity steps and a site's record of one reset.* | **not determined** | not_run | `services/console/identity.py:716` |  |
| 2.6.1 | L2 | Look-up secrets work once. *No list of look-up (recovery) codes; the single enrolment code is judged under 2.5.* | **not applicable** | hypothesis | - |  |
| 2.6.2 | L2 | Look-up secrets are random enough or salted and hashed. | **not applicable** | hypothesis | - |  |
| 2.6.3 | L2 | Look-up secrets resist offline attack. | **not applicable** | hypothesis | - |  |
| 2.7.1 | L1 | No clear-text out-of-band verifier (SMS, phone) by default. *The console has no out-of-band verifier (no code by SMS, phone or mail).* | **not applicable** | hypothesis | - |  |
| 2.7.2 | L1 | An out-of-band request expires within 10 minutes. *The console has no out-of-band verifier (no code by SMS, phone or mail).* | **not applicable** | hypothesis | - |  |
| 2.7.3 | L1 | An out-of-band code works once. *The console has no out-of-band verifier (no code by SMS, phone or mail).* | **not applicable** | hypothesis | - |  |
| 2.7.4 | L1 | The out-of-band channel is secure and separate. *The console has no out-of-band verifier (no code by SMS, phone or mail).* | **not applicable** | hypothesis | - |  |
| 2.7.5 | L2 | Only a hash of an out-of-band code is kept. *The console has no out-of-band verifier (no code by SMS, phone or mail).* | **not applicable** | hypothesis | - |  |
| 2.7.6 | L2 | An out-of-band code has at least 20 bits of entropy. *The console has no out-of-band verifier (no code by SMS, phone or mail).* | **not applicable** | hypothesis | - |  |
| 2.8.1 | L1 | Time-based one-time codes have a defined life. *30 s steps, one step either side.* | **meets** | hypothesis | `services/console/totp.py:26`; `services/console/totp.py:66` |  |
| 2.8.2 | L2 | The keys that check one-time codes are well protected. *Sealed with AES-GCM under totp.key, a file in the console's volume, not an HSM or the OS key store; D-447 notes it shares a backup with the database.* | **partly** | hypothesis | `services/console/totp.py:110`; `services/console/identity.py:98` | V3-13 |
| 2.8.3 | L2 | One-time codes are made and checked with approved algorithms. *RFC 6238 HMAC-SHA1, 160-bit secret.* | **meets** | hypothesis | `services/console/totp.py:31`; `services/console/totp.py:41` |  |
| 2.8.4 | L2 | A time-based code works only once in its window. | **meets** | shown | `services/console/auth.py:861`; `test_a_totp_code_is_refused_when_wrong_or_replayed` |  |
| 2.8.5 | L2 | A replayed code is logged, refused, and its holder told. *Logged and refused; the holder is not told.* | **partly** | hypothesis | `services/console/identity.py:499`; `services/console/identity.py:502`; `test_a_totp_code_is_refused_when_wrong_or_replayed` | V3-11 |
| 2.8.6 | L2 | A lost or stolen one-time-code device can be revoked. | **meets** | shown | `services/console/auth.py:870`; `test_admin_resets_an_authenticator_and_only_an_admin_may` |  |
| 2.9.1 | L2 | Keys of cryptographic verifiers are protected. *The console has no cryptographic verifier; security keys are Authelia's (WebAuthn). Delegated: Authelia and the hospital directory, for directory (OIDC) accounts.* | **not applicable** | hypothesis | `deploy/identity/authelia/configuration.example.yml:30` |  |
| 2.9.2 | L2 | Challenges of cryptographic verifiers are unique and long enough. *The console has no cryptographic verifier; security keys are Authelia's (WebAuthn). Delegated: Authelia and the hospital directory, for directory (OIDC) accounts. **Id to be checked.*** | **not applicable** | hypothesis | `deploy/identity/authelia/configuration.example.yml:30` |  |
| 2.9.3 | L2 | Cryptographic verifiers use approved algorithms. *The console has no cryptographic verifier; security keys are Authelia's (WebAuthn). Delegated: Authelia and the hospital directory, for directory (OIDC) accounts.* | **not applicable** | hypothesis | `deploy/identity/authelia/configuration.example.yml:30` |  |
| 2.10.1 | L2 | Services do not authenticate to each other with fixed passwords or keys. *One token per service, from a file, with a rotation command; still a long-lived bearer secret.* | **partly** | hypothesis | `libs/tb_common/service_auth.py:88`; `deploy/docker-compose.secrets.yml:32` | V3-13 |
| 2.10.2 | L2 | A service account with a password is not a default one. *Each service has its own database role (tb_console, ...).* | **meets** | hypothesis | `deploy/docker-compose.yml:368` |  |
| 2.10.3 | L2 | Service passwords are stored so that they resist offline recovery. *Database passwords come from deploy/.env into environment variables and the database URL.* | **does not meet** | hypothesis | `deploy/docker-compose.yml:368`; `deploy/docker-compose.yml:31` | V3-13 |
| 2.10.4 | L2 | Secrets are managed safely and never in source code. *Tokens and keys are files mounted per service; database, mail and KEK passwords stay in deploy/.env.* | **partly** | hypothesis | `deploy/docker-compose.secrets.yml:32`; `deploy/docker-compose.yml:31` | V3-13 |

#### V3

| ASVS | Lvl | Requirement (paraphrase) | Verdict | Basis | Evidence | Finding |
|---|---|---|---|---|---|---|
| 3.1.1 | L1 | Session tokens never appear in URL parameters. *Cookie for pages, bearer header for /api/v1. The re-authentication proof in a URL (identity.py:610) is a one-time 2-minute proof, not a session token.* | **meets** | hypothesis | `services/console/app.py:648`; `services/console/auth.py:777` |  |
| 3.2.1 | L1 | A new session token is made at sign-in. | **meets** | shown | `services/console/auth.py:752`; `services/console/app.py:1046`; `test_v3_2_1_sign_in_makes_a_new_token_and_ignores_a_planted_one` |  |
| 3.2.2 | L1 | Session tokens have at least 64 bits of entropy. *256 random bits.* | **meets** | shown | `services/console/auth.py:752`; `test_v3_2_1_sign_in_makes_a_new_token_and_ignores_a_planted_one` |  |
| 3.2.3 | L1 | The browser keeps the session token only in a secure cookie or session storage. | **meets** | shown | `services/console/app.py:1054`; `test_production_cookies_are_secure_httponly_and_strict` |  |
| 3.2.4 | L2 | Session tokens come from an approved random generator. *Python secrets.* | **meets** | hypothesis | `services/console/auth.py:752` |  |
| 3.3.1 | L1 | Sign-out and expiry end the session on the server. | **meets** | shown | `services/console/app.py:1064`; `services/console/auth.py:783`; `services/console/app.py:589`; `test_v3_3_1_sign_out_ends_the_session_on_the_server`; `test_session_expires_when_idle_and_at_the_absolute_limit` |  |
| 3.3.2 | L1 | Sessions need a new sign-in after a set time (L2: 12 hours, or 30 minutes idle). *Idle 10 minutes (1 to 60), absolute 8 hours (at most 12); directory sessions 60 minutes. Delegated: Authelia and the hospital directory, for directory (OIDC) accounts.* | **meets** | shown | `services/console/identity.py:124`; `services/console/auth.py:782`; `deploy/identity/authelia/configuration.example.yml:64`; `test_session_expires_when_idle_and_at_the_absolute_limit` |  |
| 3.3.3 | L2 | After a password change, every other session can be ended. *Every session of the account ends at once (not an option: always).* | **meets** | hypothesis | `services/console/auth.py:626` |  |
| 3.3.4 | L2 | A person can see their active sessions and end any of them. *No page lists sessions; end_sessions is never called by a page (grep). A new sign-in leaves older sessions alive.* | **does not meet** | hypothesis | `services/console/auth.py:840` | V3-03 |
| 3.4.1 | L1 | Session cookies carry Secure. *Set with Secure in PRODUCTION and behind Caddy. The removal at sign-out lacks the flags (V3-12).* | **meets** | shown | `services/console/identity.py:134`; `deploy/docker-compose.identity.yml:93`; `test_production_cookies_are_secure_httponly_and_strict` | V3-12 |
| 3.4.2 | L1 | Session cookies carry HttpOnly. | **meets** | shown | `services/console/app.py:1054`; `test_production_cookies_are_secure_httponly_and_strict` |  |
| 3.4.3 | L1 | Session cookies carry SameSite. *Strict.* | **meets** | shown | `services/console/app.py:1054`; `test_production_cookies_are_secure_httponly_and_strict` |  |
| 3.4.4 | L1 | Session cookies use the __Host- prefix. *The cookie is 'tb_console'.* | **does not meet** | shown | `services/console/app.py:93`; `test_v3_4_4_the_session_cookie_has_the_host_prefix` | V3-02 |
| 3.4.5 | L1 | With other applications on the same name, the cookie path is as narrow as it can be. *The console is the only application on its host name; Authelia has its own name and cookie domain.* | **meets** | hypothesis | `deploy/identity/Caddyfile:59`; `deploy/identity/Caddyfile:85` |  |
| 3.5.1 | L2 | A person can revoke OAuth grants given to linked applications. *The console grants no OAuth access to other applications; it is only an OIDC client.* | **not applicable** | hypothesis | - |  |
| 3.5.2 | L2 | Session tokens are used rather than fixed API keys. */api/v1 opens a session with a sign-in (POST /api/v1/session) and refuses a page cookie.* | **meets** | shown | `services/console/auth.py:762`; `test_v4_the_api_refuses_a_page_cookie_as_a_bearer_and_a_bearer_as_a_cookie` |  |
| 3.5.3 | L2 | Stateless tokens are signed and checked against tampering and replay. *Sessions are server-side rows. The actor assertion between services (D-447) is signed and single-use, but it is no session token.* | **not applicable** | hypothesis | `services/console/auth.py:755` |  |
| 3.7.1 | L1 | Sensitive actions need a full session plus a fresh sign-in or second check. *Password change asks for the current password; a signature asks for a fresh code (step_up). Opening a break-glass grant asks for neither.* | **partly** | shown | `services/console/breakglass.py:189`; `services/console/identity.py:306`; `services/console/step4.py:235`; `test_v3_7_1_break_glass_asks_for_a_fresh_credential`; `test_v3_7_1_a_password_change_asks_for_the_current_password`; `test_a_patient_grant_opens_one_patient_for_60_minutes` | V3-04 |

#### V4

| ASVS | Lvl | Requirement (paraphrase) | Verdict | Basis | Evidence | Finding |
|---|---|---|---|---|---|---|
| 4.1.1 | L1 | Access rules are enforced on the server. *Every route walked by nine roles; the answers equal the design table and the matrix.* | **meets** | shown | `libs/tb_common/authz.py:157`; `services/console/app.py:731`; `test_the_generated_matrix_equals_the_design_table` |  |
| 4.1.2 | L1 | People cannot change the attributes access decisions read. *The role comes from the account row on the server. The acting role is granted only by a boot tool on a test box (D-877).* | **meets** | hypothesis | `services/console/auth.py:788`; `services/console/auth.py:817` |  |
| 4.1.3 | L1 | Least privilege: each role reaches only what it needs. *One matrix; the administrator reads no patient row except by break-glass (D-280).* | **meets** | shown | `libs/tb_common/authz_matrix.yaml:1`; `test_d380_the_administrator_reads_no_patient_row_at_all`; `test_the_generated_matrix_equals_the_design_table` |  |
| 4.1.5 | L1 | Access control fails closed, also on an error. *Unknown role or action: refused. Between services an unlisted callee accepts any token (V3-15, under 1.2.2): no deployed callee is unlisted today.* | **meets** | shown | `libs/tb_common/authz.py:160`; `test_a_role_or_an_action_not_in_the_matrix_is_refused` |  |
| 4.2.1 | L1 | Records are protected against direct object reference (another study's job or patient). | **meets** | shown | `services/console/app.py:683`; `services/console/app.py:924`; `test_a_scoped_coordinator_cannot_run_another_study`; `test_a_scoped_coordinator_cannot_ask_status_or_cancel_of_another_studys_job`; `test_the_generated_matrix_equals_the_design_table` |  |
| 4.2.2 | L1 | A strong anti-CSRF control protects every changing request. *A per-session token on every changing page route (walked as three roles) and SameSite=Strict; /api/v1 takes a bearer token only.* | **meets** | shown | `services/console/auth.py:1163`; `services/console/app.py:732`; `services/console/app.py:1021`; `test_v4_2_2_every_changing_page_route_refuses_a_post_without_the_csrf_token`; `test_v4_the_api_refuses_a_page_cookie_as_a_bearer_and_a_bearer_as_a_cookie` |  |
| 4.3.1 | L1 | Administrative pages need a second factor. *TOTP cannot be turned off outside DEV and TEST; directory sign-ins must report MFA. Delegated: Authelia and the hospital directory, for directory (OIDC) accounts.* | **meets** | shown | `services/console/identity.py:113`; `services/console/identity.py:120`; `deploy/docker-compose.identity.yml:95`; `test_totp_is_the_default_outside_dev_and_test_and_cannot_be_turned_off_in_production`; `test_doctor_fails_production_without_a_second_factor` |  |
| 4.3.2 | L1 | No folder listing; no metadata files (.git) are served. | **meets** | shown | `services/console/app.py:575`; `services/console/app.py:572`; `test_v4_3_2_no_folder_listing_and_no_api_description_page` |  |
| 4.3.3 | L2 | Step-up checks or separation of duties guard high-value actions. *Signatures ask for a fresh code; protected accounts need a second person (D-719). Break-glass asks for neither (3.7.1, V3-04) but is told to the steward at once and reviewed.* | **meets** | shown | `services/console/identity.py:306`; `services/console/account_rules.py:112`; `test_the_administrator_never_holds_both_factors_within_30_days` |  |

#### V1

| ASVS | Lvl | Requirement (paraphrase) | Verdict | Basis | Evidence | Finding |
|---|---|---|---|---|---|---|
| 1.1.2 | L2 | A threat model exists for the design and its changes. *No threat model in docs/security/ (ten files) or docs/validation/ (grep for 'threat model', 'STRIDE').* | **does not meet** | hypothesis | `docs/security/01-the-host.md:1` | V3-16 |
| 1.2.2 | L2 | Calls between the parts of the application are authenticated. *Every call carries a service token, but a callee not in CALLERS accepts any service's token. Every deployed service is listed today, so the gap is latent (the trace store's HTTP app, which trusts unsigned role headers, is not started by any compose file).* | **partly** | hypothesis | `libs/tb_common/service_auth.py:201`; `libs/tb_common/service_auth.py:88` | V3-15 |
| 1.4.1 | L2 | Access is enforced at trusted points on the server, never in the client. | **meets** | shown | `libs/tb_common/authz.py:157`; `test_the_generated_matrix_equals_the_design_table` |  |
| V1-rest | - | The rest of V1 (1.1.1, 1.1.3-1.1.7, 1.2.1, 1.2.3, 1.2.4, 1.4.4, 1.4.5, 1.5-1.14). *Not reached.* | **not assessed** | not_run | - |  |

#### V5

| ASVS | Lvl | Requirement (paraphrase) | Verdict | Basis | Evidence | Finding |
|---|---|---|---|---|---|---|
| 5.1.5 | L1 | Redirects go only to allowed places. *The language switch checks '/' and '//' only, but the redirect percent-encodes a backslash, so it stays a path.* | **meets** | shown | `services/console/next_page.py:23`; `services/console/app.py:1126`; `test_v5_1_5_the_language_switch_stays_on_the_console` |  |
| 5.3.1 | L1 | Output is encoded for its context (HTML here). *Jinja autoescape on for .html; the one '|safe' is the console's own script constant.* | **meets** | hypothesis | `services/console/app.py:508`; `services/console/templates/base.html:70` |  |
| 5.3.3 | L1 | Encoding prevents reflected, stored and DOM cross-site scripting. *Autoescape, plus a CSP with a script hash and no 'unsafe-inline'.* | **meets** | shown | `services/console/app.py:110`; `test_v14_4_security_headers_on_the_sign_in_page_and_a_signed_in_page` |  |
| 5.3.4 | L1 | Database queries are parameterised. *The stores bind values with '?'. Criteria SQL is generated, not parameterised (5.3.5); the lake runs a SELECT-only guard.* | **meets** | hypothesis | `services/console/auth.py:730`; `services/lake/sqlguard.py:60`; `test_non_select_rejected` |  |
| 5.3.5 | L1 | Where parameters are impossible, values are escaped for the query language. *String literals double their quotes, names are quoted, criterion text in a comment is put on one line.* | **meets** | hypothesis | `services/criteria_compiler/compile_sql/generator.py:67`; `services/criteria_compiler/compile_sql/generator.py:153` |  |
| V5-rest | - | The rest of V5 (5.1.1-5.1.4, 5.2, 5.3.2, 5.3.6-5.3.10, 5.4, 5.5). *Not reached. The prompt-injection suite on the real model pair (full review J-5) is outside ASVS.* | **not assessed** | not_run | - |  |

#### V6

| ASVS | Lvl | Requirement (paraphrase) | Verdict | Basis | Evidence | Finding |
|---|---|---|---|---|---|---|
| 6.2.1 | L1 | Cryptographic modules fail safely and errors are handled. *A wrong TOTP key file is a refusal, never a pass.* | **meets** | hypothesis | `services/console/identity.py:416`; `services/console/totp.py:114` |  |
| 6.2.2 | L2 | Proven algorithms and libraries are used. *AES-GCM, scrypt, Ed25519, HMAC-SHA256 from the cryptography package and the standard library.* | **meets** | hypothesis | `libs/tb_common/crypto.py:103` |  |
| 6.2.5 | L2 | No insecure modes or weak padding. | **meets** | hypothesis | `libs/tb_common/crypto.py:105` |  |
| 6.2.6 | L2 | Nonces and IVs are not reused. *A fresh 96-bit random nonce per encryption.* | **meets** | hypothesis | `libs/tb_common/crypto.py:104` |  |
| 6.3.1 | L2 | Random values come from a cryptographically secure generator. | **meets** | hypothesis | `services/console/auth.py:752`; `services/console/auth.py:217` |  |
| 6.4.1 | L2 | A secrets-management solution creates, stores and controls secrets. *Service tokens and keys are files; database, mail and KEK passwords stay in deploy/.env (full review J-M5).* | **does not meet** | hypothesis | `deploy/docker-compose.yml:368`; `deploy/docker-compose.secrets.yml:32` | V3-13 |
| 6.4.2 | L2 | Key material is not exposed to the application (an isolated module or vault). *Site keys can be sealed by TPM or shares (tools/key_ceremony.py, not read for this line); the TOTP key is a plain file the console reads.* | **partly** | hypothesis | `services/console/totp.py:104` | V3-13 |
| V6-rest | - | The rest of V6 (6.1, 6.2.3, 6.2.4, 6.3.2). *Not reached.* | **not assessed** | not_run | - |  |

#### V7

| ASVS | Lvl | Requirement (paraphrase) | Verdict | Basis | Evidence | Finding |
|---|---|---|---|---|---|---|
| 7.1.1 | L1 | Logs hold no credentials or session tokens. *Sessions stored as SHA-256; Caddy drops Cookie and Authorization from its log.* | **meets** | hypothesis | `services/console/auth.py:757`; `deploy/identity/Caddyfile:52`; `services/console/identity.py:710` |  |
| 7.1.2 | L1 | Logs hold no other sensitive data under privacy law. *Masked by key name and 'key=value'; a chart number in free text (a note) is kept.* | **partly** | shown | `libs/tb_common/audit.py:106`; `services/console/app.py:942`; `test_v7_1_2_a_chart_number_in_a_free_text_note_is_masked` | V3-14 |
| 7.1.3 | L2 | Security events are logged (sign-in, failure, denial, lock). *Break-glass writes its audit event after the grant is stored (V3-18). Sign-in, failure, denial and lock are logged.* | **partly** | hypothesis | `services/console/app.py:1036`; `services/console/app.py:1047`; `services/console/identity.py:300`; `services/console/app.py:735`; `services/console/breakglass.py:211` | V3-18 |
| 7.1.4 | L2 | Each event has what an investigation needs (who, when, from where). | **meets** | hypothesis | `services/console/identity.py:303`; `services/console/app.py:1037` |  |
| 7.2.1 | L2 | Every authentication decision is logged, without tokens or passwords. | **meets** | shown | `services/console/app.py:1036`; `services/console/identity.py:502`; `test_a_totp_code_is_refused_when_wrong_or_replayed` |  |
| 7.2.2 | L2 | Access-control decisions can be logged and failures are logged. | **meets** | hypothesis | `services/console/app.py:735`; `services/console/app.py:709` |  |
| 7.3.1 | L2 | Log content is encoded so that it cannot inject into the log. *Canonical JSON per line.* | **meets** | hypothesis | `libs/tb_common/audit.py:144` |  |
| 7.3.3 | L2 | Security logs are protected from change. *A hash chain and a head anchor detect a change. How often the heads are signed (full review J-M2: nightly) was not read for this card.* | **partly** | hypothesis | `libs/tb_common/audit.py:144`; `test_tamper_detected`; `test_rewriting_and_rehashing_everything_fails` |  |
| V7-rest | - | The rest of V7 (7.1.? not listed, 7.3.2, 7.3.4, 7.4). *Not reached.* | **not assessed** | not_run | - |  |

#### V8

| ASVS | Lvl | Requirement (paraphrase) | Verdict | Basis | Evidence | Finding |
|---|---|---|---|---|---|---|
| 8.2.1 | L1 | Sensitive pages tell the browser not to cache them. | **meets** | shown | `services/console/app.py:589`; `test_v14_4_security_headers_on_the_sign_in_page_and_a_signed_in_page` |  |
| 8.2.2 | L1 | Data in browser storage is cleared when the session ends. *A typed mark note stays in the tab's session storage after the session ends, on purpose (D-777), and is put back for whoever signs in next in that tab and opens that patient.* | **partly** | hypothesis | `services/console/static/console.js:56`; `docs/decisions/REGISTRY.md:591` | V3-19 |
| 8.3.1 | L1 | Sensitive data travel in the body or headers, not the query string. *Chart numbers are posted. Pseudonyms (not identifying) appear in paths; Caddy drops query strings from its log.* | **meets** | hypothesis | `services/console/templates/case.html:10`; `services/console/templates/audit.html:18` |  |
| V8-rest | - | The rest of V8 (8.1, 8.2.3, 8.3.2-8.3.8). *Not reached. Erasure (full review J-2) is lane V's card for criterion 8.* | **not assessed** | not_run | - |  |

#### V9

| ASVS | Lvl | Requirement (paraphrase) | Verdict | Basis | Evidence | Finding |
|---|---|---|---|---|---|---|
| 9.1.1 | L1 | TLS for every client connection; no fallback to plain HTTP. *Behind the overlay only Caddy's 443 is published. Without the overlay the console listens on the box's loopback only (deploy/docker-compose.yml:388).* | **meets** | hypothesis | `deploy/identity/Caddyfile:59`; `deploy/docker-compose.identity.yml:91`; `deploy/docker-compose.identity.yml:46` |  |
| 9.1.2 | L1 | Only strong TLS versions and ciphers. *TLS 1.2 and 1.3 (Caddy's defaults in internal mode). No TLS scan record found: a scan would show it.* | **meets** | hypothesis | `deploy/identity/Caddyfile:35` |  |
| 9.2.1 | L2 | Outbound and server connections use trusted certificates. *LDAPS checked against the hospital CA only (D-722); the OIDC client against a CA file. **Id to be checked.*** | **meets** | hypothesis | `deploy/docker-compose.identity.yml:74`; `deploy/identity/authelia/configuration.example.yml:47` |  |
| 9.2.2 | L2 | Every connection, internal ones too, is encrypted. *Between containers on one host the calls are plain HTTP on internal networks: a recorded rationale (no mTLS on one host; added when a call crosses a physical network).* | **partly** | hypothesis | `docs/security/02-network.md:41`; `deploy/docker-compose.yml:370` |  |
| V9-rest | - | The rest of V9 (9.1.3, 9.2.3-9.2.5). *Not reached.* | **not assessed** | not_run | - |  |

#### V10

| ASVS | Lvl | Requirement (paraphrase) | Verdict | Basis | Evidence | Finding |
|---|---|---|---|---|---|---|
| V10 | - | Malicious code and supply chain (whole chapter). *Not reached. The supply-chain gates are their own part of plan 8's V9.* | **not assessed** | not_run | - |  |

#### V11

| ASVS | Lvl | Requirement (paraphrase) | Verdict | Basis | Evidence | Finding |
|---|---|---|---|---|---|---|
| V11 | - | Business logic (whole chapter). *Not reached.* | **not assessed** | not_run | - |  |

#### V12

| ASVS | Lvl | Requirement (paraphrase) | Verdict | Basis | Evidence | Finding |
|---|---|---|---|---|---|---|
| 12.1.1 | L1 | Large files are refused before they fill storage. *50 MB in the console, 60 MB at Caddy.* | **meets** | hypothesis | `services/console/app.py:2056`; `services/console/app.py:98`; `deploy/identity/Caddyfile:62` |  |
| V12-rest | - | The rest of V12. *Not reached.* | **not assessed** | not_run | - |  |

#### V13

| ASVS | Lvl | Requirement (paraphrase) | Verdict | Basis | Evidence | Finding |
|---|---|---|---|---|---|---|
| 13.1.3 | L1 | API URLs carry no key or session token. *The API token is a bearer header.* | **meets** | hypothesis | `services/console/auth.py:777` |  |
| 13.2.3 | L1 | Changing API calls are protected against CSRF. *The API never accepts the browser's cookie.* | **meets** | shown | `services/console/auth.py:777`; `test_v4_the_api_refuses_a_page_cookie_as_a_bearer_and_a_bearer_as_a_cookie` |  |
| V13-rest | - | The rest of V13. *Not reached.* | **not assessed** | not_run | - |  |

#### V14

| ASVS | Lvl | Requirement (paraphrase) | Verdict | Basis | Evidence | Finding |
|---|---|---|---|---|---|---|
| 14.3.2 | L1 | Debug modes and API description pages are off in production. | **meets** | shown | `services/console/app.py:572`; `test_v4_3_2_no_folder_listing_and_no_api_description_page` |  |
| 14.3.3 | L1 | Headers do not show component versions. *Caddy removes Server.* | **meets** | hypothesis | `deploy/identity/Caddyfile:44` |  |
| 14.4.1 | L1 | Each response names its content type and character set. | **meets** | shown | `services/console/app.py:858`; `test_v14_4_security_headers_on_the_sign_in_page_and_a_signed_in_page` |  |
| 14.4.3 | L1 | A Content-Security-Policy is set. | **meets** | shown | `services/console/app.py:110`; `test_v14_4_security_headers_on_the_sign_in_page_and_a_signed_in_page` |  |
| 14.4.4 | L1 | X-Content-Type-Options: nosniff. | **meets** | shown | `services/console/app.py:585`; `test_v14_4_security_headers_on_the_sign_in_page_and_a_signed_in_page` |  |
| 14.4.5 | L1 | Strict-Transport-Security with includeSubDomains. *One year, without includeSubDomains (D-447 'Open'). **Id to be checked.*** | **partly** | hypothesis | `deploy/identity/Caddyfile:42` |  |
| 14.4.6 | L1 | A suitable Referrer-Policy. | **meets** | shown | `services/console/app.py:586`; `test_v14_4_security_headers_on_the_sign_in_page_and_a_signed_in_page` |  |
| 14.4.7 | L1 | Framing by other sites is refused. | **meets** | shown | `services/console/app.py:584`; `test_v14_4_security_headers_on_the_sign_in_page_and_a_signed_in_page` |  |
| 14.5.3 | L1 | CORS allows only trusted origins. *No CORS middleware anywhere (grep CORSMiddleware): no cross-origin read is allowed.* | **meets** | hypothesis | `services/console/app.py:572` |  |
| V14-rest | - | The rest of V14 (14.1, 14.2, 14.3.1, 14.4.2, 14.5.1, 14.5.2, 14.5.4). *Not reached. Container hardening (full review J-M4: only model-guard drops capabilities, deploy/docker-compose.yml:469) has no single L2 line; listed with the comparison.* | **not assessed** | not_run | - |  |

## Ids to be checked

The level or the exact number of these lines is from memory and was not checked against the standard's text (no
download was made): **2.2.2**, **2.4.5**, **2.9.2**, **9.2.1**, **14.4.5**. The lines are marked on the page.

## What a dynamic scan in the nightly would need

Nothing here adds a scanner. What the repository already has:

- **Static and supply-chain scanners, none dynamic.** `make security-scan` (secrets and bandit, `tools.security_scan`),
  `make scanners` (Syft and Trivy release archives with pinned sha256, `tools/supply_chain/scanners.py`),
  `make pip-audit` (from a hashed lock). A search of `uv.lock`, `pyproject.toml`, `tools/package.json`,
  `deploy/images.lock` and `.github/workflows/trialbox-*.yml` for ZAP, nuclei, nikto, wapiti or schemathesis finds
  none.
- **What could drive a scan already:** Playwright 1.63.0 and axe-core 4.14.0 (`tools/package.json`, used by the
  walks), httpx 0.28.1 and hypothesis in `uv.lock`, and the test fixtures that sign in synthetic accounts of every
  role (`tests/console/test_role_route_matrix.py`).
- **Where it would run:** the `compose` job of `.github/workflows/trialbox-e2e.yml` (nightly, 19:17 UTC; a 90-minute
  ceiling, measured at about 37.5 to 48 minutes), after `make up-test` and the walks. That stack has no Caddy: the
  console answers on plain HTTP. Caddy runs only in `trialbox-identity.yml` (a smoke run with a stand-in console, on
  pull requests that touch the identity files), so headers and TLS at the edge would need the identity overlay added
  to the compose job, or that workflow scheduled.

| | A: OWASP ZAP baseline (and API scan) | B: a probe set written in the repo |
| --- | --- | --- |
| What it downloads, when | The ZAP image, pulled by a pinned digest at the start of the job, as `trialbox-identity.yml` pulls Caddy; nothing else (its add-on updates switched off) | Nothing: Python with httpx from `uv.lock` |
| Licence | Apache-2.0 | the project's own |
| Where | the compose job, `docker run` on the stack's network | the compose job, as a pytest file marked `e2e` |
| Run time (estimate, not measured) | baseline (spider plus passive rules) a few minutes; an active scan of every route far longer, so weekly at most | a few minutes |
| Pointed at | the console (`console:8090`; through Caddy if the overlay is added) and `/api/v1` | the same |
| Sign-in | a small step signs in synthetic accounts (one per role, TOTP off in TEST) and hands ZAP the session cookie or bearer token as a header | the same fixtures the walks use |
| What it finds | known classes ZAP's rules hold (headers, cookies, reflected script, errors, redirects) | only what is written: headers and cookies on every GET route, the CSRF walk of this card, reflected markers in every field, redirect payloads, TLS versions at Caddy |
| "No High" as a gate | zero alerts of risk High in the JSON report; any rule the project overrides is a file in the repo, which counts as an allow-list | every probe passes |

The questions the coordinator should put to the integrator:

question: May the nightly compose job (`trialbox-e2e.yml`, job `compose`) pull the OWASP ZAP image by a pinned digest and run a baseline scan of the console signed in as synthetic roles, a few minutes a night? (yes or no)

question: If yes, may a reviewed ZAP rules file (each overridden alert with its reason) live in the repository, given the rule that no new scan allow-list entry is added? (yes or no)

question: If no to the first, should lane D write the probe set in the repository instead (no download), with "no High" meaning every probe passes? (yes or no)

## What did not run, and what could not be proved

- No live stack, no Caddy, no Authelia, no TLS scan, no scanner. Every line about Caddy, Authelia or compose is read
  from configuration (basis *hypothesis*), except V3-01, which a test reads from the files.
- The "Delegated" lines rest on `configuration.example.yml`; a site's own copy (`deploy/site/authelia/`) is not
  committed and was not seen.
- V1, V5 to V9 and V12 to V14 are judged in part; V10 and V11 are not assessed.
- How often the audit heads are signed (J-M2) was not read; 7.3.3 stays "partly".

## How the check works

`python -m tools.asvs_checklist --check` (and `tests/unit/test_asvs_checklist.py`, which calls it) fails when: the
count table above differs from `checklist.json`; a named `file:line` is missing or shorter than its line; a named
test is not a `def` in its file; a verdict or basis is not one of this page's words; a "meets" names no file and
line; a "shown" names no test; a finding is in one json and not the other; a finding or a requirement id is not on
this page. Line numbers are for the commit `checklist.json` names: after a change to a named file, re-read the line
and move the number.
