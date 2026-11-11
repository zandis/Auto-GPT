# D-391 Signing with a directory account, a `reauth-` session a shared token cannot forge, and a neutral meaning text

- **Card:** T-205 (second factor at signing, rewritten; TB-PLAN-06 `docs/plan/28-master-plan-v6.md` §6.2.4), branch
  `agent/T-205-signing-second-factor`
- **Date:** 2026-11-11
- **Status:** accepted
- **Builds on:** D-160 (EDC prefill), D-192 (OIDC through the hospital's identity provider), D-279 (the second factor
  at signing for local accounts), D-281 (record lock, keyed signature, plain ODM legal reason), D-138 (one token per
  service)
- **Closes:** REG-025; REG-021 (text half); CR-034 (signing part); CR-035 (rest); SEC-16 of
  `docs/reviews/2026-11-10-critical-issues-register.md`

## The problem

A person who signs in through the hospital directory (OIDC) has no console password, so the signature step refused
them and told them to ask for a local password: a second identity for one person, with a password an administrator
set (REG-025, CR-034). With one shared service token every container can derive the key that signs actor assertions,
so any of them could write a `reauth-` session and sign or unlock a value as anyone (SEC-16). The words of the
signature said the signer checked each value "against the cited hospital record" and that the values "are correct";
the signer compares with a quote TrialBox shows, which is a copy, and confirms what they typed or accepted
(REG-021, REG-024).

## The decision

1. **Signing with a directory account.** On the review page an OIDC account (on a console with OIDC on) sees no
   password field. The button keeps what the page showed (the values' hashes, the meaning acknowledged), checks the
   delegation-log entry, and sends the person to the provider with `prompt=login` and `max_age=0`
   (`Identity.start_reauth`). The provider's answer comes back through the one registered callback
   (`/auth/oidc/callback`), bound to the browser by the state cookie. It counts only when the ID token verifies as
   for a sign-in, names the same account and the same subject, has `auth_time` no earlier than 30 seconds before the
   round trip began, and reports a second factor in `amr` (required here whatever `TB_OIDC_REQUIRE_MFA` says). The
   callback opens no session. It gives the page a single-use proof that lives two minutes; the page signs only in
   the same console session that pressed the button, within twelve minutes. The signature row's method is
   `oidc+mfa`. Failures are audited (`console.reauth_failed`, `console.edc_reauth_failed`).
2. **The API.** `/api/v1/.../edc/sign` still refuses a directory account (`edc.sign_oidc_page`): a bearer token
   cannot do the provider's round trip. A header single sign-on account (no password the console can ask again)
   still cannot sign; the text now says to move it to OIDC, never to make a local account.
3. **SEC-16.** The orchestrator counts a `reauth-` session (to sign, or to change a signed value) only when it
   checks actor assertions with the console's own key (`TB_ACTOR_KEYS_FILE`, per-service tokens), or on a DEV or
   TEST box. A box that still runs on one shared token refuses with `edc.reauth_shared_token` until
   `trialbox secrets init` has run.
4. **Meaning text.** `edc.service.ODM_MEANING` and `edc.sign.meaning` say: "With this electronic signature I confirm
   that I compared each value with the source cited beside it on this page, and that these are the values I
   confirmed for this subject and visit. A passage quoted by TrialBox is a copy of the hospital record, not the record
   itself." The same in Japanese and Traditional Chinese. No regulation is named and no correctness is claimed. A
   unit test pins the three texts. The ODM legal reason stays D-281's plain text.
5. **Small extra.** The data-entry page gives a reason in three languages for the problem codes `decimals`, `time`,
   `email` and `phone`.

## Not in this decision

- Changing or withdrawing a signed value with a directory account still needs the password path; a directory
  account gets `edc.sign_sso` there. The same round trip can serve it later.
- The pending signature and the proof live in the console's memory: a console restart drops them and the person
  presses the button again. The console runs as one process.
- The Part 11 and ER/ES assessment and the sponsor letter that quotes the meaning (T-648, struck by D-311 B27).
