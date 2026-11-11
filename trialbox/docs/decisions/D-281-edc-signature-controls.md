# D-281 EDC signature controls: a signed value is locked, the signature is keyed over the whole act and checked before use

- **Card:** FG D-281 (fix group FG-L of the critical-issues register; TB-PLAN-06 `docs/plan/28-master-plan-v6.md`
  §6.2.1), built as a card on branch `agent/FG-D281-signing`
- **Date:** 2026-11-11
- **Status:** accepted
- **Builds on:** D-160 (EDC prefill), D-162 (the person from the signed assertion; review E-01 to E-11), D-279 (forced
  first change and the second factor at signing), D-204 (checksummed migrations)
- **Closes:** CR-035 (P-3), CR-036 (P-4), SEC-6 (P-5), SEC-7 (P-6) of `docs/reviews/2026-11-10-critical-issues-register.md`;
  deep-review findings LIFE-021 (lock and signature part), REG-021, STD-060

## The problem

Any account with `enter_data` could change or withdraw a value another person had signed, even one already sent; the
signature was unlinked quietly (CR-035). The signature's `content_sha` was an unkeyed SHA-256 over the value hashes
only, kept in the row it protects: it did not cover the signer, the printed name, the meaning or the time, send and
export never compared with it, and the trail tables could be updated and deleted (CR-036). The `edc.sign` audit line
was written after the commit (SEC-6), and several refusals were not audited at all (SEC-7). The ODM file stated "21
CFR Part 11 electronic signature; ER/ES guideline (Japan)" as the legal reason of every signature, a conformance
claim with no assessment behind it (REG-021). The REDCap client read the answer to `content=version` as JSON, which a
real REDCap sends as plain text, so the first call to a real REDCap failed (STD-060).

## The decision

1. **Record lock (CR-035).** `EdcStore.decide` refuses any action on a signed value (`edc.locked`, HTTP 423) unless
   the caller says the person re-authenticated just before (`unlock`) and gives a reason. The orchestrator sets
   `unlock` only from an actor assertion whose session starts `reauth-` (the console signs one right after the
   password check, as for signing); on a DEV or TEST box without a token the console's `unlock` in the body counts,
   as `by` does. The console's review page shows a password field (and a code field with TOTP on) on each signed
   row's change and withdraw forms; the console re-authenticates exactly as for signing (D-279: no password someone
   else set, the code with TOTP on, each failure toward the lockout). A sent value stays locked the same way. Each
   change of a signed value writes a row in the new append-only table `signature_void` (signature, value, action,
   reason, who, when), next to the existing `signature_void` decision row.
2. **Keyed binding over the whole act (CR-036).** A new signature (`sig_version` 2) stores
   `content_sha = HMAC-SHA256(key, canonical JSON of study, record, visit, signer, printed name, role, meaning, the
   meaning's words, language, method, time and every value's hash)` and the key's fingerprint (`key_id`). Before a
   value is sent to REDCap or written to the ODM file, `EdcStore._covered` checks that the value's hash still matches,
   that the signature row lists that value with that hash, and that the row's `content_sha` re-made with the key is
   equal. A row changed by anyone, or checked under another key, covers nothing: its values are not sent or exported
   until signed again, and the trail page marks it. Version 1 rows (before this decision) are checked by their own,
   unkeyed rule; any other version never passes.
3. **The key** is read by the orchestrator only: the file `TB_EDC_SIGN_KEY_FILE`, else `edc_sign.key` in the
   orchestrator's secrets folder, made once with 32 random bytes and mode 0600. The console and the other database
   writers do not mount that folder; in `deploy/docker-compose.yml` the adapter shares the volume today, so a file
   mounted into the orchestrator alone through `TB_EDC_SIGN_KEY_FILE` is the stronger set-up (left to the deploy
   cards; T-210b's key-encryption key may wrap it later). A DEV or TEST box without either uses a
   fixed test key; any other box without either refuses to open the EDC store. A lost or replaced key does not fail
   silently: old signatures stop verifying and their values wait for a new signature.
4. **Append-only trail tables.** `decision`, `signature`, `signature_void`, `sent`, `switch_event` and `map_event`
   each carry a trigger that refuses UPDATE, DELETE and TRUNCATE. The triggers are made by `EdcStore` after its
   migrations (idempotent, under an advisory lock), not in a migration, because a plpgsql body holds `;` and
   `Database.migrate` splits on it. They hold against every role except a table owner who drops or disables them;
   separate database roles are SEC-4's. The keyed hash is what still holds then.
5. **Audit inside the transaction (SEC-6).** `EdcStore.sign` and `EdcStore.decide` take a `before_commit` hook; the
   service writes its `edc.sign` or `edc.decide` line there. If the line cannot be written, the transaction rolls back
   and nothing is signed or decided. The other failure order (line written, commit fails) leaves an event without a
   row, which is the safe and visible direction. The `edc.sign` line now names the method.
6. **Audited refusals (SEC-7).** The service audits refusals of `decide` before the store (switch off, no such
   draft, a value that does not fit the field) and of `sign` (switch off). The orchestrator router audits `edc.refused`
   with the code for a role that may not act (`edc.role`) and for a signature without re-authentication
   (`edc.reauth_needed`). The console audits `console.edc_refused` with the code before each refusal of the signing
   and unlocking steps (visit, single sign-on account, meaning not acknowledged, password someone else set, no
   delegation-log entry, nothing shown).
7. **Method recorded.** The signature row's `method` is `password+totp` when the console checked a code, else
   `password` (D-279's tail: the row said `password` always).
8. **Plain legal reason (REG-021).** The ODM `SignatureDef/LegalReason` is "Electronic signature of the person named;
   see the site's validation summary" (`edc.odm.LEGAL_REASON`), pinned by a test. It changes only when an assessment
   of 21 CFR Part 11 and the Japanese ER/ES guideline is on file.
9. **REDCap version call (STD-060).** `RedcapClient.version` reads the answer as text (a JSON string is read too);
   the simulator answers `content=version` with plain text, as REDCap does.

## Not in this decision

- The second factor itself and the forced first change are D-279. Signing with a directory account (OIDC) stays
  refused (T-205, REG-025).
- Arms and repeating instruments in REDCap (CR-062, the rest of LIFE-021) are T-115 and T-302.
- A run of the ICD-04 list against a real REDCap test project with recorded cassettes (the rest of STD-060) needs a
  site REDCap sandbox (owner question 2): T-115.
- The nightly anchoring of the EDC trail heads into the audit chain (REG-026 addition) is T-211.
- Database roles that do not own the tables (SEC-4).

## Evidence

`tests/unit/test_edc_signing_d281.py`, `tests/console/test_edc_pages_d281.py`; `tests/unit/test_edc.py` (two tests
now unlock before changing a signed value); `tests/unit/test_rc_sim.py` (plain-text version);
`tests/unit/test_migrations.py` pins the new `edc` version 2.
