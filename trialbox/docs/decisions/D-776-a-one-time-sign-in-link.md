# D-776 A person sets their own password from a one-time link

- **Task:** the owner's ruling D-509 of 2026-11-15 (the demo VM of 2026-11-17: the owner and Wenn each set their own
  password from a one-time link); due on master by 2026-11-16, ahead of other work
- **PR:** this branch (`agent/D-509-a-one-time-sign-in-link`), from master after train 17
- **Date:** 2026-11-15
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-719 (NEW-SEC-3: a protected account is opened by a one-time enrolment code, confirmed by a second
  person; the holder chooses the password at `/enrol`), D-279 (a password someone else set is replaced first)

## The problem

D-509 asks that each person set their own password from a one-time link, that a link work once, that an unused one
expire, and that wrong passwords be slowed or locked out. D-719's first sign-in already holds all of it but the link:

- the holder chooses the password at `/enrol`, and the administrator never sees it;
- the code is spent at use, and a second use is refused (401) and audited (`console.enrol_code_reused`);
- an unused code expires (`TB_CONSOLE_ENROL_CODE_HOURS`);
- wrong attempts are slowed per source (429) and lock the account (401), each one counted and audited.

What was missing is the link: the holder typed the user name and the code. **Shown by tests** before the change.

## The decision

- **Where a new account's code is shown once,** the link is shown beside it, with a Copy button:
  `<box>/enrol#u=<name>&c=<code>`. These are the administrator's page (an account opened without a second person) and
  the confirming person's page (a request confirmed). A reset password is not a link; it is typed at the sign-in
  page, as before.
- **The code sits after `#`.** A browser never sends that part to the server, so the code is in no request line, no
  server or proxy log, and no Referer. The console's script (allowed by its hash, as before) fills the two fields
  from it and removes it from the address bar, and so from the history.
- **The link is the code.** It works once, expires with the code, and is slowed and locked out by the same rules.
  Nothing of D-719 changes. Without a script the page opens empty, and the holder types the two values the link
  shows.

## Held by

`tests/console/test_a_one_time_sign_in_link.py`, with D-719's own tests unchanged.

## Remains

- The demo VM's accounts are made by lane G's script; it hands the owner and Wenn the link instead of the code.
- A link's channel is the person's: the page says to hand it over in person or on a channel only the holder reads.

## Dropped (D-311)

No sign-off step.
