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
  `<box>/enrol#u=<name>&c=<code>`. `<box>` is the box's own public address (`TB_CONSOLE_PUBLIC_URL`, which the demo
  VM sets), never the request's Host: an administrator who reaches the console through a tunnel, or a forged Host,
  would otherwise hand out a link to the wrong place. Without that address no link is made, and the page says so. These are the administrator's page (an account opened without a second person) and
  the confirming person's page (a request confirmed). A reset password is not a link; it is typed at the sign-in
  page, as before.
- **The code sits after `#`.** A browser never sends that part to the server, so the code is in no request to the box,
  no box or proxy log, and no Referer. The console's script (allowed by its hash, as before) fills the two fields from
  it on the first sign-in. On every page it then removes it from the address bar and the Back history, including the
  home page a signed-in person is sent to. The browser's own history still holds the visited link until the code is
  spent or expires, and a mail link-rewriter or a chat tool may keep it. So the page tells the holder to finish at
  once, best in a private window, and to take the link only over a channel they alone read.
- **The link is the code.** It works once, expires with the code, and is slowed and locked out by the same rules.
  Nothing of D-719 changes. Without a script the page opens empty, and the holder types the two values the link
  shows.

## Adversarial review

NOT SOUND on the first pass:
1. The link was built from the request's Host.
2. A signed-in person who opened the link was sent on to the home page with the code still in the address bar.
3. This record claimed the code left "the history" and was in "no log", which is not true of the browser's own
   history or of mail link-rewriters.
4. A test's name claimed a case it did not check.

All are fixed and held by tests. The console's own script is now run in the tests (in Node, with a stand-in page) for
the fill, the clear on any page, and a user name already typed.

## Held by

`tests/console/test_a_one_time_sign_in_link.py`, with D-719's own tests unchanged.

## Remains

- The demo VM's accounts are made by lane G's script; it hands the owner and Wenn the link instead of the code.
- A link's channel is the person's: the page says to hand it over in person or on a channel only the holder reads.

## Dropped (D-311)

No sign-off step.
