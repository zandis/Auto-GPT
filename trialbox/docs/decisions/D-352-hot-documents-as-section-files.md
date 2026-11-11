# D-352 Hot documents are section files with a generated index; RUNBOOK numbers come from one table

- **Task:** T-669 (wave 2 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.1 rule 5, §6.2.5)
- **PR:** this branch (`agent/T-669-doc-sections`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** PLAN-033 (the document part), OPS-073 (part: each RUNBOOK section is marked `site` or `team`)

## Context

`docs/RUNBOOK.md`, `docs/DATA.md`, `docs/USER_GUIDE.md` and `docs/SECURITY.md` were single files that about 25
cards edit. Two branches that each added a RUNBOOK section both appended at the end of the file and conflicted, and
section numbers were taken by guess: §14 was claimed three times in open pull requests (PLAN-033, plan §6.5). The
RUNBOOK also mixes the site's pages with the team's (OPS-073).

## Decision

1. **One file per section.** Each numbered section of the four documents is its own file:
   `docs/runbook/`, `docs/data/`, `docs/user-guide/`, `docs/security/`, named `NN-<slug>.md` and starting
   `# N. Title`. Another `NN-<slug>.md` whose title is not `N. ...` is a part of section N
   (`docs/runbook/11-qualify.md`). The text moved unchanged; headings went one level up and relative links were
   rewritten for the new folder.
2. **The document stays.** `docs/RUNBOOK.md` and the others keep their title and opening and hold a generated index
   between two marker lines: one `## N. Title` heading per section, so every old link such as
   `RUNBOOK.md#9-proof-of-concept-with-docker` still resolves, and "RUNBOOK §N" in code and text still means the same
   section. `python -m tools.doclint --write` writes the index; `doclint` fails when it is out of date.
3. **RUNBOOK numbers in one table.** The `## Section numbers` table at the end of `docs/RUNBOOK.md` lists every number
   with its holder and audience. The integrator gives a number by adding its row; a reserved number with no file shows
   in the index as a placeholder block, so the branch that writes it changes only its own block (blocks are separated
   by unchanged lines, so git merges two of them). `doclint` fails on a section file with no row, a number written
   twice, a file whose name and title disagree, and a part with no section. Rows 19 to 26 are reserved now for T-609,
   T-628, T-635 and T-633 (T-633's plan row says §14, which is the judge bake-off on master).
4. **One file when needed.** `python -m tools.doclint --whole RUNBOOK` prints the document as one file, for a release
   bundle or a printout.

## Consequences

- A card that changes a section edits one file; a card that adds a RUNBOOK section adds one file and runs
  `--write`. `tests/unit/test_doclint.py` merges two branches that each add a RUNBOOK section and a row to a DATA
  table with no conflict.
- Open pull requests that still edit the single files (#146 and #147 on RUNBOOK, #147 and #159 on SECURITY) move
  their lines into the section file at merge: take this branch's hub, put the lines in the section file, run
  `--write`.
- `tools/make_bundle.sh` ships `docs/RUNBOOK.md`, which is now the index; the bundle card (T-110b) should ship the
  output of `--whole RUNBOOK` or the `docs/runbook/` folder.
- Moving the `team` sections out of the RUNBOOK is T-635's (`docs/DEVELOPING.md`).
