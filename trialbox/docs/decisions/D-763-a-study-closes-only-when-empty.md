# D-763 A study closes only when it is empty

- **Task:** NEW-LIFE-6 (plan v7.3, wave 4, lane C: lifecycle repairs; the deep review of 2026-11-12, LIFE-006;
  `37-remaining-work-split.md`, lane C2's queue)
- **PR:** this branch (`agent/NEW-LIFE-6-close-only-an-empty-study`), from master after train 15
- **Date:** 2026-11-14
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-386 (the study's state: start-up, open, paused, closed; closed is final), D-277 (the SAE register),
  D-134 (visit and SAE mails of enrolled participants), D-415 (a study that reports SAEs opens only with its type)

## The problem

"Closed" was one form post, final, with no check of subjects on study or of open SAE reports, and a closed study
mails nothing (`notify.CARE_STATES` is open and paused). At last-patient-in a coordinator picks "closed", the natural
word, and every subject in follow-up loses their visit and overdue-SAE mails, for good. There was no "closed to
recruitment" state in the words of the page. **Confirmed by a test** before the change (kept failing output:
`life6-fail.txt`).

## The decision

- **`closed` is refused while the study is not empty.** A subject consented, enrolled or on study
  (`datacore.lifecycle.ON_STUDY`), or a serious AE not done with (through `Helpers.sae_open`: every report still to
  send, `saerecord.OPEN`; every serious AE with no reporting clock, which has no report row; every serious AE the
  investigator has not acknowledged),
  keeps the study in its state: 409, and the page names the two counts and says to choose "Closed to recruitment /
  paused" to stop recruiting. A study store or SAE register that cannot be read, whatever the failure, refuses too
  (`sstate.close_unknown`, audited `close_unread`): never closed by default. A box without the study store has no subjects nor register to count (as D-415's check).
- **"Paused" reads "Closed to recruitment / paused"** in the three languages (募集終了／一時停止, 停止收案／暫停).
  The state and its effect are unchanged: no new lists nor list mails; visits and SAEs of enrolled participants are
  still mailed.
- **The study's PI may take back a close made the same site day**, with a reason (`POST /studies/{rs}/state/take-back`,
  matrix row `study.reopen`, investigator `[pi]` only). The study returns to the state the close left, read under the
  store's lock (`set_study_state(..., take_back=True)`); the step is kept in the state history and audited
  (`console.study_state` with `take_back: true`) in the same transaction. Nobody else may, and not on a later day
  (409). "Closed" stays final after that day: a study that recruits again is a new study set-up (D-386).

- **After the close, nobody goes back on study through the console, and anyone who does is still mailed.** The
  console refuses a step into consented, enrolled or on study, and any undo, in a closed study (`life.why.closed`).
  The orchestrator does not know the console's study state, and a REDCap read-back derives steps of its own; so a
  closed study stays in the mail round's care states (`notify.CARE_STATES`): it gives no list, but a participant on
  study after the close is mailed their visits and serious AEs. With the close check, a closed study normally has
  nobody to mail.

## The review

One adversarial review: NOT SOUND on the first pass. A closed study could gain subjects on study after the close
(undo, a step, the read-back) and then mailed nothing; serious AEs with no clock counted as zero; a failure inside
the register came back as a 500; the closed state's text still said "final"; the tests stubbed the SAE count. All
fixed as above and held by tests: the undo and the step refused after the close, a register failure refused with its
reason, the count over the real register (an unacknowledged serious AE with no rule set), a sub-investigator refused
the take-back, the take-back's audit event, and the closed study's care mail (`test_study_state_d386.py`).

## Reuse check

The SAE register's own open-report count (`saerecord.OPEN` in each case view) and the lifecycle's `ON_STUDY`; the
state store's one write path with its lock; the page's existing error line. One new matrix row and one route.

## Dropped (D-311)

No sign-off step.
