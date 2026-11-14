# D-764 A serious adverse event is told at once, and every day

- **Task:** NEW-LIFE-7 (plan v7.3, wave 4, lane C: lifecycle repairs, "mail at entry and daily"; the deep review of
  2026-11-12, LIFE-007; `37-remaining-work-split.md`, lane C2's queue)
- **PR:** this branch (`agent/NEW-LIFE-7-an-sae-is-told-at-once`), from master after train 15
- **Date:** 2026-11-14
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-191 and D-277 (the SAE register; FIT-025, the copy of a new case to the trial office), D-143
  (P-02, P-03: the SAE count in N1, the overdue reports in N2), D-415 (a study that reports SAEs opens only with its
  type), D-386 (the mails follow the study's state)

## The problem

Nobody was told when a serious AE was entered unless the optional office mailbox (`TB_SAE_OFFICE_MAILBOX`, empty by
default and asked by no installer step) was set. The investigator's unacknowledged-SAE mail went on working days
only, and the coordinator's digest, with its overdue reports, skipped weekends whole. An SAE typed on Friday 18:00
has its 24-hour sponsor report due Saturday 18:00; the PI's first mail was Monday 07:00. **Confirmed by a test**
before the change (kept failing output: `life7-fail.txt`).

## The decision

- **At once, to the PI and the office.** When the register writes a new serious case (the AE form's save through the
  console, the coordinator's "bring up to date", the daily job), one mail goes to the trial office's mailbox and to
  the study's PI on the delegation log that day, by the mailbox of their account (enabled, not expired). The same
  pseudonymous text as the office copy: the study, the screening number, the event, the dates, the rule set and
  each report's due time, never the AE term, a chart number or a name. Nobody to tell is audited (`notice_nobody`).
- **Every day.** The investigator's mail (N1) carries an unacknowledged SAE every day, weekends too. The coordinator's
  digest (N2) goes on a weekend day when an SAE report is overdue, and then carries only those reports (no list,
  visit or call items on a day off).
- **The office mailbox is a required answer on a box.** On a box that is not DEV or TEST, a study whose type
  reports SAEs does not open while `TB_SAE_OFFICE_MAILBOX` is unset (`sstate.sae_mailbox`, in the three languages),
  beside D-415's check of the SAE type. The installer's question for it is lane D's (asked on the inbox); this check
  holds until it exists.

## Reuse check

The register's own new-case path (`office_copy`, now `told_at_once` for the recipients), the delegation log's
`pi_of`, the account store's `get` (enabled and not expired), the notice builders' existing sections, D-415's open
check. No new store, route or permission.

## Dropped (D-311)

No sign-off step.
