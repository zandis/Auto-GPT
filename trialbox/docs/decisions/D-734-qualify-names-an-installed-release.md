# D-734 Qualify and goldens name an installed release when there is no git checkout

- **Task:** QUALIFY-BOX, lane G's blocker 1 for R4 (the qualification on the box)
- **PR:** this branch (`agent/QUALIFY-BOX-qualify-on-an-installed-box`)
- **Date:** 2026-11-15
- **Status:** accepted
- **Builds on:** D-313 (one qualify command), D-367 (the signed host tree, `HOST-SHA256SUMS`)

## Context

`tools/qualify.py` named the code a record is for by `git rev-parse HEAD` and stopped with "no git HEAD" otherwise.
A box installed from a signed bundle has no git checkout, so qualification could not run where it has to run.
`tools/goldens.py` named its result the same way, and qualify compares the two.

## Decision

1. `tools/code_identity.head(root)` names the code: a git commit (dirty when `git status` lists a tracked change), or,
   without git, `release:<sha256 of HOST-SHA256SUMS>` of the installed release tree (dirty when
   `tools.host_tree.check_dir` finds a changed, missing or added file), or `unknown` and dirty.
2. `qualify.git_head()` and `goldens.git_head()` both use it, so evidence made on the box names the same code as the
   record. A changed release fails the serving step as a changed checkout does, with its own words.
3. No new setting, no new dependency (standard library and `tools.host_tree`).

## Test

`tests/unit/test_code_identity.py`: before, a collection error (no `tools.code_identity`); after, 7 passed, with the
existing qualify and goldens tests unchanged.
