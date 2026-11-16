# The external worker: drafting small cards with an outside model (2026-11-16)

The owner gave the project an API key for an outside model on 2026-11-15, to move building work off the lane
sessions: the outside model drafts, a session checks and audits. This page is the procedure. The tool is
`tools/external_worker.py`; where the model lives is the caller's setting and is never named in the repository.

## What the trial showed (2026-11-15, three cards)

| Card | Kind | Rounds | Tokens in / out | Result |
| --- | --- | --- | --- | --- |
| `decisions_index --flip-merged` and its tests | code and tests, two files | 1 | 6,640 / 6,524 | passed lint, types and tests; audit found nothing to change; 223 registry rows flipped |
| A handbook page in three languages | documents, three new files | 3 | 43,047 / 2,651 | the English text was good; it failed a house rule it had not been told (the document linter's "Reader" line) and did not repair it in three rounds; held for lane W |
| Tests for the tool itself | tests, one new file | 2 | 17,212 / 3,580 | passed on the second round; seven tests, no network |

- A ready-made coding agent was tried first and was the wrong tool: it applied nothing (the model did not answer in
  the agent's edit format) and pulled a large file into the request by itself.
- The larger model of the same vendor stalled for more than ten minutes on the documents card and was stopped; the
  small coding model answered each round in under a minute.
- Cost: the three cards used about 67,000 tokens in and 13,000 out. At the vendor's listed prices that is a few
  cents; the account's usage page is the figure to trust.

## What goes to the external worker, and what never does

| Goes | Never goes |
| --- | --- |
| A card that is small (one to three files, each under about 600 lines), has a check a command can run, and can be stated in one page | Exclusion logic, the cascade, the judge's prompts and the pair rule |
| Tools, tests for existing code, document pages, mechanical clean-ups | Masking and the PHI guard, key sealing, the opt-out and erasure paths, the gateway's refusals |
| Repository code (it is public) and synthetic test data | Anything read from a hospital source: a count, a code list, a finding, the carve; anything from the private bucket |
| | A secret, a key, an address or a sign-in code |

A card that needs judgement across many files, or whose check is "a person reads it", stays with a lane.

## The procedure

1. **Write the task** as one Markdown page: what to change, what must not change, the tests wanted, the house rules
   that apply (line length 120; no model or vendor names; for a document, the linter's "Reader" line and the known
   readers). The model knows nothing the page does not say.
2. **Name the files.** `--edit` and `--new` are the only paths that can be written; `--read` gives context. Give
   whole files; keep the total under about 15,000 tokens.
3. **Name the check**: the commands the card must pass (`ruff check`, `ruff format --check`, `mypy`, the card's own
   tests; for a document, `tools/doclint.py`). The check is what the model is graded on, so a rule the check does
   not run is a rule the model will break.
4. **Run it** in a throwaway worktree, up to three rounds:
   `XW_API_URL=<the chat-completions address> XW_MODEL=<the model> python tools/external_worker.py --task T.md
   --root . --edit a.py tests/unit/test_a.py --check "<commands>" --log /tmp/a.log`
   The credential is added by the session's network; where it is not, `XW_API_KEY` is set in the shell from a file
   and never echoed, written or committed.
5. **Audit before anything is committed.** The session reads every changed line, runs the card's tests and
   `make lint`, and, for a tool that rewrites files, runs it and checks what changed. A failed third round goes back
   to step 1 with a better page, or to a lane; it is never patched up blind.
6. **Commit as the session.** The session that audited commits, with the project's trailer. The pull request says
   "drafted by an external model through the harness; checked and audited by <the session>" and names no model.
7. **Train as usual.** The card posts its train-ready line; CI and the integrator treat it like any other card.

## Who runs it

Any lane may, for its own files, under the table above. The integrator runs it for the registry, the plan pages and
cards nobody owns. A lane that drafts with it still owns the card: the audit, the red, the fix.

## Limits found so far

- It follows the page and the check, not the project's habits: house rules must be written in the task or run by the
  check.
- On a failed check it tends to repair the first complaint and leave the others; put every command in one check so
  each round shows all failures.
- It cannot see the repository beyond the files it is given, so it cannot find a caller, a second place that needs
  the same change, or a test elsewhere that pins the old behaviour. The auditing session does that with `grep`.
