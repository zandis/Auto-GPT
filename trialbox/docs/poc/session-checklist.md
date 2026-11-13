# PoC session checklist

For the facilitator and the operator (the project owner, or a person he names). Tick each line on a copy kept
outside the repository. Secrets (passwords, enrolment codes, the host name, the front door's settings) never enter
the repository, an issue, a chat or this checklist.

## Once per site, after seeding (before the first session)

- [ ] The host runs the image built from the tag (`poc-1`), by digest, with `TB_DEMO_KEEP=1`, a data volume and
      `TB_DEMO_ACCOUNTS` pointing at the accounts file outside the image (`demo/README.md`).
- [ ] Demo mode is on: `TB_DEMO_MODE=on` at the console's first start, or switched on at `/ops/flags` with a reason
      (D-328). The banner shows on the sign-in page.
- [ ] The site's scenario data is loaded: Japan site AD-MAB and NEUR-COH lists; Taiwan site RA-JAK and GZQO lists,
      the GZQO amendment waiting on S20, the GOUT-COH registry linked to REDCap with one member taken on (as
      `tests/integration/test_poc_scripts.py` seeds them).
- [ ] Each tester has three accounts (PI, sub-investigator with the ticks "screen" and "refer" only, CRC), with the
      tester's language and an end date; the owner holds the only admin account.
- [ ] `issued-credentials.txt` handed to each tester out of band (theirs only), then deleted from the data folder.
- [ ] Write the baseline of the stored-input scan, once, after seeding, inside the container (where `TB_DB_URL`
      names the trial database; `--db` adds every text column of it to the data folders):
      `python -m console.demo_guard scan --db <data folders> --write-baseline <baseline file>`
      The baseline file stays on the host, outside the repository. Re-write it only after a reseed.
      `TB_DB_URL` must carry the box's admin role (`trialbox`), which reads every store. With a service's own
      role (the console's, inside its container) the scan reads that service's stores only: it names the stores it
      could not read and exits 1, and writes no baseline (D-711).
- [ ] Smoke test: the front door lets in only the testers' and the owner's addresses; `/login` answers over HTTPS;
      an upload is refused with "Not accepted in the demonstration".
- [ ] The data-handling statement ([data-handling.en.md](data-handling.en.md) or its translation), the notice on the
      tester's own data ([testers-data.md](testers-data.md)) and the guide ([guide.en.md](guide.en.md) or its
      translation) sent to the tester.

## Before each session

- [ ] The tester's script open: [scripts/jp.ja.md](scripts/jp.ja.md) or [scripts/tw.zh-TW.md](scripts/tw.zh-TW.md),
      and the English one beside it for the facilitator.
- [ ] A blank session record and finding forms ([forms.md](forms.md)).
- [ ] Recording only if the tester ticked it in the acknowledgement and agrees again today.
- [ ] Remind the tester: synthetic data only; do not type anything from a real patient; think aloud; the facilitator
      does not help unless asked.

## During the session

- [ ] Note per task: done or not, time, ease (1 to 7), where the tester stopped, short quotes.
- [ ] Nothing is fixed live; a defect is logged and the session goes on with the next task.
- [ ] Each request for help is a finding.
- [ ] If the tester enters or describes real patient information: stop; run the purge; record the event without the
      content; tell the tester what was done; the tester follows the hospital's own rule.
- [ ] If the demo is down for more than 15 minutes, rebook the session.

## After each session (the same day)

- [ ] Run the stored-input scan against the baseline:
      `python -m console.demo_guard scan --db <data folders> --baseline <baseline file>`
      Exit 0 is clean. Exit 1 means something was not scanned (the message names it). Exit 2 is a new hit (printed masked, with its place): treat it as real data entered (purge,
      record without the content, tell the tester). Exit 1 means `TB_DB_URL` was not set, or a column
      the scan must read (the feedback comment, T-510) was not reached: fix and run again.
- [ ] Export the in-product feedback (`/feedback/export.csv` as an admin, or `python -m console.feedback export`)
      and add each entry to the finding forms.
- [ ] Fill the finding forms from the session record; one finding per form.
- [ ] Rate each finding with the tester's rating if the tester gave one ([severity.md](severity.md)).
- [ ] Anything rated "would cause a wrong patient decision": tell the integrator the same day.
- [ ] Session record and recordings stored outside the repository.

## After the last session

- [ ] Exit review: triage every finding (severity and outcome); write gp-findings.md (this folder) with tester codes only.
- [ ] Reply to the testers within a week: what will change, when, and what will not, with the reasons.
- [ ] Destroy the host and delete its snapshots and the recordings (or keep the host for step 2 if the owner says
      so); record the deletion.
- [ ] Accounts and logs deleted within 90 days of the PoC's end.
