# P31: the command line adds an account of every role, a CRO account with its studies

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders, so in one
language.

- **Card:** P-31 (the integrator's R1+1 batch D, part H, comment 7210967559 on #1504)
- **Date:** 2026-11-27
- **Base:** int/r1plus1
- **Findings:** [`cli-every-role-p31-2026-11-27/findings.json`](cli-every-role-p31-2026-11-27/findings.json) (P31-01)

## What was there

`console.cli add-user` took six roles (`steward` and `privacy` were there already); `cro` was not a choice, and the
command set no study scope, so a CRO account could not be made from the shell at all.

## Change

- `services/console/cli.py`: `add-user --role` takes every role of `console.auth.ROLES`. New `--studies` (ruleset ids
  separated by commas) and `--affiliation` (default `cro` for a CRO account, else `hospital`). The scope is checked
  with `scope_values` before the account exists (D-380): a CRO account, or an SMO or CRO affiliation, without a study
  is refused with exit 2 and no account. The account is saved with `set_scope`, and the `console.user` create event
  names its affiliation and studies, as the users page does.
- `tests/console/test_cli_add_user_roles_p31.py`: every role (parametrised over `ROLES`, not a hand list), the refusal
  without studies, and a CRO account made on the command line that sees its own study's feasibility page (200) and
  not another study's (404).

## What ran

The new test on the base: 9 failed (`cro` not a choice; no scope in the audit event). At the head: 9 passed, with
`tests/console/test_identity_d279.py`. The checks of the hand-back ran from `trialbox/`.

## Not done

- The command line saved no end date for a non-operator account; the users page saves one at most 12 months ahead
  (D-406). P31-01, fixed in the review round (P31-R2): `add-user` now calls `end_date` and writes the date in the
  account-and-scope transaction.
- The runbook line in `docs/runbook/03-accounts.md` names `add-user NAME --role ROLE` without `--studies`; the
  command's help says it. Not changed (no runbook change in this card).
