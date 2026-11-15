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
**Confirmed by tests** before the change (kept failing output: `t317-fail.txt`).

## The decision

- **One source.** A role's guide is built from the help catalogue (`console.guides`):
  - what the role does (`help.role.<role>`);
  - what the matrix lets it do (`console.app.role_description`, ROLE-018's words);
  - its pages, each with Help's own text for that page (`help.page.<slug>`);
  - the glossary, for a role that sees patients (`life.gloss.*`);
  - the commands to try (`cmd.ex.<role>.<n>`, the study's code written as STUDY);
  - where to ask.

  Only the headings and the page names are new words (`console.i18n_guides`).
- **Printable files.** `python -m tools.role_guides --out docs/guides` writes `<role>.<lang>.md` for the seven roles in
  en, ja and zh-TW. They are generated: a test fails when a help text changes and the files do not.
- **Served from Help.** `/help/guide` shows the signed-in account's own guide in its language, ready to print. Help
  links it in place of the old promise. The CRO account reaches it too (its scope list).
- **Each role's pages are the help pages the role opens,** held by a test against the generated role-route table:
  - the investigator is the one the study's delegation log names;
  - the coordinator is the hospital's own.
- **No English in a ja or zh-TW guide,** and no catalogue key: a test holds both. It found the steward's and the
  privacy office's names missing outside the running console; the builder now loads the whole catalogue.
- The steward and the privacy office get their `help.role.*` text, so Help's "Your role" says what they do.

## Held by

`tests/console/test_role_guides_from_the_help.py`; the role-route table regenerated (`TB_WRITE_ROLE_MATRIX=1`).

## Remains

- Screenshots from the complete run, and a native reader's review of the ja and zh-TW text: T-317's review step.
- The eight documents "made true" and the independent re-review: the rest of T-317.
- The acceptance (training with the guides at go-live): lane D's T-317a.

## Dropped (D-311)

No sign-off step.
