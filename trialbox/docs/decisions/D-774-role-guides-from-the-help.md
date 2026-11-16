# D-774 The role guides are generated from the console's help

- **Task:** T-317, lane C2's half (the help source and the printable guides; the integrator's split of 2026-11-15:
  lane D keeps T-317a, the acceptance part)
- **PR:** this branch (`agent/T-317-role-guides-from-the-help`), from master after train 15
- **Date:** 2026-11-15
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** T-301 (the help panel), D-398 (UX-029: the help text per page), ROLE-018 (D-380: a role's rights in
  words, from the matrix), T-102a (D-366: the generated role-route table)

## The problem

WS-17.1 asks for a guide per role in Japanese and Chinese, as the training handout. None existed. The help panel
promised one ("the full user guide for each role comes with the hospital installation"). A guide written by hand
would drift from the screens it describes, and the steward and the privacy office had no help text of their own.
Shown by tests before the change: the guides, their builder and the page did not exist.

## The decision

- **One source.** A role's guide is built from the help catalogue (`console.guides`):
  - what the role does (`help.role.<role>`);
  - what the matrix lets it do (`console.app.role_description`, ROLE-018's words);
  - its pages, each with Help's own text for that page (`help.page.<slug>`);
  - the glossary, for a role that sees patients (`life.gloss.*`);
  - the commands to try (`cmd.ex.<role>.<n>`, the study's code written as STUDY);
  - where to ask.

  Only the headings and the page names are new words (`console.i18n_guides`).
- **Printable files.** `PYTHONPATH=libs:services:. python -m tools.role_guides --out docs/guides` (from `trialbox/`) writes `<role>.<lang>.md` for the seven roles in
  en, ja and zh-TW. They are generated: a test fails when a help text changes and the files do not.
- **Served from Help.** `/help/guide` shows the signed-in account's own guide in its language, ready to print. Help
  links it in place of the old promise. The CRO account reaches it too (its scope list).
- **A role's pages are the pages it opens and may act on.** Each help page names the route its text describes and,
  for a page that exists to act (start a request, send a protocol, keep the opt-outs, add users), the route of that
  action (`guides.PAGES`). A role's guide lists the page only when the role passes both in the generated role-route
  table. A page that answers but refuses every action, or a redirect to a page the role cannot open, is not the
  role's. A test holds `guides.ROLE_PAGES` to the table.
- **Pages only some accounts of a role open are marked.** Two columns per role: the narrowest account (an
  investigator the study's log does not name; the SMO's study-scoped coordinator) and the widest (the named PI; the
  hospital's coordinator). A page only the widest opens says "(where your account and the study's delegation log
  allow)".
- **The steward's, the privacy office's and the administrator's own pages get help text** (users, account requests,
  break-glass, audit trail, clinical conflicts, data operations, the opt-out register, the staff register). The help
  panel shows it on those pages too; they showed the generic text before.
- **Every command to try works for its role:** a test reads each through the command field and checks that the role
  opens its page. It found the Japanese administrator's example 処理 not understood (the field knew only ジョブ, which
  the glossary had replaced) and the viewer's example "audit" leading to a page the viewer is refused. Both are fixed,
  and so is the viewer's help line, which said it reads the audit trail.
- **No English in a ja or zh-TW guide,** and no catalogue key: every key a guide uses is in that language's own
  catalogue (so the English fallback cannot fire), and every line of prose has the language's own words. It found the steward's and the
  privacy office's names missing outside the running console; the builder now loads the whole catalogue.
- The steward and the privacy office get their `help.role.*` text, so Help's "Your role" says what they do.

## Scope

T-317's card says "must not touch: code"; the integrator's split of 2026-11-15 gives lane C2 the help source and the
guides built from it, which is code (the builder, the page, the help text). The card's documents half stays as it is.

## Adversarial review

NOT SOUND on the first pass:
1. The page lists came from any route of a help page that answered, so roles were told about pages they cannot use.
   Examples: "This week's patients" for the administrator by a redirect; "Site set-up" for the steward through
   another page; "Start a request" for roles refused every request.
2. The steward's and the privacy office's own pages were missing.
3. The viewer's help line and one of its examples named the audit trail, which the viewer cannot open.
4. Every investigator was given the named PI's pages without a condition.
5. The language test allowed a fifth of the lines in English.
6. This record overstated its scope.

All are fixed as above and held by tests.

## Held by

`tests/console/test_role_guides_from_the_help.py`; the role-route table regenerated (`TB_WRITE_ROLE_MATRIX=1`).

## Remains

- Screenshots from the complete run, and a native reader's review of the ja and zh-TW text: T-317's review step.
- The eight documents "made true" and the independent re-review: the rest of T-317.
- The acceptance (training with the guides at go-live): lane D's T-317a.
- WS-17.1 also names the clinician, the sub-investigator, the monitor and the trial office. The guides cover the
  seven console roles. The sub-investigator is the investigator's guide with its marked pages. The monitor's pages
  (a CRO account under a grant) need their help text, and the clinician and the trial office have no console role.
- The steward and the privacy office have no commands to try yet (`cmd.ex.steward.*`, `cmd.ex.privacy.*`).

## Dropped (D-311)

No sign-off step.
