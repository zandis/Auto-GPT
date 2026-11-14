# D-719 Nobody holds both factors of a patient-data, steward, privacy or administrator account

- **Task:** NEW-SEC-3 (the owner's critical 3 of 2026-11-13; the deep review's SEC-02)
- **PR:** this branch (`agent/NEW-SEC-3-no-one-holds-both-factors`), cut from train 14
- **Date:** 2026-11-14
- **Status:** proposed (merges on green CI and one adversarial review)
- **Decided by:** the owner on 2026-11-14, on the integrator's advice, relayed: (b) everywhere, (c) where a second
  person exists, (a)'s notices always; yes, an administrator may open a steward or privacy-office account under the
  same rules (a box needs a way to make its first steward)
- **Builds on:** D-192 (TOTP, enrolment codes), D-279 (a password someone else set), D-280 (the administrator has no
  patient row), D-380 (the matrix), D-133 (shown once, never in a URL or the audit)

## The problem

The deep review found, by running, that `/ops/users` let the administrator open a coordinator `shadow` with every
study, be shown its password, issue its authenticator code, and read a candidate page as `shadow` (SEC-02): D-280's
"the administrator has no patient row" was defeated in practice. A reset of an existing coordinator's password and
then of its authenticator gave the administrator both factors the same way.

## The decision

- **Classes and rows.** `console.account_rules.CLASS_OF`: `patient-data` (coordinator, investigator), `steward`,
  `privacy`, `admin` and `aggregate` (viewer, CRO). The matrix has `account.create.<class>` for each (the
  administrator's) and `account.confirm` (the administrator and the steward). Every class but `aggregate` is
  *protected*. `admin` is a class of its own, beyond the owner's four: a second administrator is a confirming person,
  so opening one is held as the others are (said here for the owner to see).
- **(b) everywhere: one factor at a time.** A protected account is opened with an enrolment code only; no password is
  shown or known to anyone. Its holder signs in once at `/enrol` with the code, chooses the password and, with TOTP
  on, sets up the authenticator on their own device next (the code is not asked twice). The code is good for
  `TB_CONSOLE_ENROL_CODE_HOURS` (a declared setting, 1-72, default 24; also for the codes of `/ops/identity`).
  Afterwards someone else sets one factor at a time: a new password, or a new authenticator code, never the other
  within 30 days unless the holder signed in in between (`UserStore.factor_held`; `console.factor_refused` audits a
  refusal). A password for an account whose holder has not yet used the code is refused at any time (a new code is
  given instead). The command line records its resets and holds the same rule.
- **(c) where the box has a second person.** Opening a protected account, changing its studies or resetting a factor
  is a request (`console.account_request`) that takes effect only when another person with `account.confirm`
  confirms it on `/ops/accounts/requests` (`console.account_confirmed`, or `console.account_refused`); nothing changes
  before. Nobody confirms their own request; a person the requester opened (was shown the first code of) or who
  opened the requester is no second person, so an administrator who opened a second administrator alone cannot have
  it confirm their requests, and with no other person (b) alone applies. The code or password goes to the person who
  confirms, never to the one who asked; that person hands it over.
- **(a) always: the holder and the steward are told.** At the next sign-in the holder reads, once, on the first
  page: "your password / authenticator was reset by <name> at <time>" or "your account was opened at <time> (code
  given by <name>); if that was not you, tell <steward>". The stewards and the PI of each of the account's studies get
  a mail, as for break-glass (`console.account_notice` counts what was sent; a failed mail is an audit event). A code
  already used shows when it was used and is audited (`console.enrol_code_reused`); the try counts as a failure.
- **The review's shadow sequence fails** at the step the rule names: on a one-person box no password is shown (only a
  code, and the holder's first sign-in is told to the steward); with a second person, `shadow` does not exist until
  the steward confirms, and the code is shown to the steward, not to the administrator. A password reset followed by
  an authenticator reset is refused at the second step (`tests/console/test_no_one_holds_both_factors.py`).

## What an existing box's accounts become

Accounts made before the update keep their passwords, authenticators and studies; nobody has to enrol again. The
30-day rule starts with the first reset after the update (no earlier reset is on record). Viewer and CRO accounts are
made and reset as before.

## What it does not do

- **On a box where one person holds both the administrator's and the steward's account, misuse is seen, not
  impossible.** That person can confirm their own request from the other account, or open an account and use its code
  themselves; the mail to the steward and the PI, the notice to the holder and the audit trail show it.
- **The command line** (`python -m console.cli`) runs in the console container: whoever has that shell has the
  database and the key file. It records its resets and refuses the other factor within 30 days, but `add-user` still
  sets a password for any role (the box's installer and its tests use it). It is a record there, not a wall.
- **The first-run wizard** opens the owner's own first accounts before any account exists (D-466); unchanged.
- **Disable and enable** of an account change no factor and are not held.
- Directory (OIDC) and trusted-header accounts have no console factors; unchanged.

## Review

See "What the adversarial review changed" when the review is in.

## Reuse check

The enrolment code and its store (`issue_enrol_code`, `check_enrol_code`, `reset_totp`, D-192), the confirmation
sheet (`confirm_step`), the break-glass mail pattern (`bk.send_notice`), `permit` and the matrix, the session's
one-time display (`keep_once`). Added: `console.account_rules` (classes, the second person, `/enrol`, the requests
page), schema V6 of `auth` (who opened an account, factor resets, requests, notices) and the strings
`console.i18n_accounts` (en, ja, zh-TW).

## Dropped (D-311)

No sign-off step: the second person is the owner's rule for the product, not a gate on development.
