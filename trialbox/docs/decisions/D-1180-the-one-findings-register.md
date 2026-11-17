# D-1180 The one findings register: one row per finding, appended by card, checked by a tool

- **Task:** lane V, card V-0 (plan 8, `docs/plan/44-plan-8-2026-11-17.md`: section 3 criterion 11, section 4 item 15,
  section 5b, section 8b lane R, section 8c): the one findings register
- **Date:** 2026-11-17
- **Status:** accepted

## Context

Plan 8 says what a verification finds goes into "the one findings register" with a severity (section 5b), that no
High may be open in it at release and every Medium needs a card done or a recorded ruling (criterion 11, proved by
V20), that lane R keeps it honest, "a finding closes when it is seen closed" (section 8b), and that it replaces the
stale problem log (section 8c). The full review of 2026-11-17 asks for the same (F25, K-M5, L-5). The register did not
exist. What played a part of it:

- `docs/validation/problems.csv`, the problem log of T-654 (D-344): 49 rows, stale since 2026-11-12 by the review.
- `docs/reviews/2026-11-10-critical-issues-register.md` and the deep reviews' own finding tables: records of what a
  review found on its day.
- Each card's own findings page, for example `docs/plan/measurements/runbook-install-2026-11-17.md` with its
  `findings.json`. There is no "start here" page yet (plan 8 gives it to Int).

Plan 8 gives the register to the integrator (section 4, item 15, "One open-findings register", lane Int). Card V-0
made it at the integrator's direction of 2026-11-17; the integrator keeps it, and lane R keeps it honest.

Several lanes now find things at once, and each of their pull requests will add rows. A register that every card
edits must not turn every pair of those pull requests into a conflict.

## Decision

1. **One file.** `docs/handover/findings-register.md`, one Markdown table row per finding, readable by a person and
   by `tools/findings_register.py`. The columns: Id, Date found, Source (a relative link to the page or record the
   finding comes from), Severity, Claim (one line), Lane, Basis, State.
2. **One section per card.** Each card's rows sit in one table under `## <card>: <words>`. A card adds rows only under
   its own heading, made at the end of the file the first time. Rows are never sorted or moved: a sort rewrites lines
   that other branches also touch. From the first card heading on, the file holds nothing but card sections: a
   heading, blank lines, the header, the rule and rows with no blank line among them, then blank lines.
3. **Ids.** `<card>-<local>`. The card is the card's name without its hyphen (H-20 is `H20`). Lane V's ids are the
   card and a number of two or more digits (`V2-07`), as the lane's rules say. A row from another source keeps the
   id the source gave after the card (`H20-F-16`, `H22-no-host-tree`); a source that gives none is numbered in its own
   order, two digits (`H18-01`). The id starts with its heading's card, is unique in the file, and is never reused or
   renumbered. A finding that turns out wrong stays, as `not a defect`.
4. **Severity.** High: a patient harmed or wrongly excluded, data leaked or not erased, a role doing what the matrix
   forbids, an audit trail that can be wrong, or a box that cannot be installed or restored. Medium: a person slowed or
   misled, or a document's claim not true. Low: wording only. A severity mapped from a source's other scale is written
   with " (mapped)", and is mapped by this rule from what the finding says, not from the source's word.
5. **Basis.** `shown`, `hypothesis` or `not_run`, as lane V's findings carry it; `not stated` for a seeded row whose
   source does not say.
6. **States.** Exactly one of `open`; `card issued #<pr>`; `fixed <sha>` (7 to 40 hex) with ", seen closed by <who>
   on <date>" once re-checked; `not a defect: <why>`. The lane that owns the finding proposes the new state in the
   pull request that changes it; lane R re-checks a fix and adds the "seen closed" words. A row is never deleted.
   `fixed <sha>` and `card issued #<n>` are checked for their form only: the tool does not look up the commit or the
   pull request.
7. **No counts in the file.** `python -m tools.findings_register --counts` prints them (open High, open Medium, open
   Low, total; "open" is `open` or `card issued`). A counts line in the file would change in every pull request that
   adds a row and so conflict in every pair of them. A generated block has the same fault.
8. **Merges.** `.gitattributes` gives the file `merge=union`, so appends never conflict: two cards appending to one
   table, to two tables, or each adding a new card at the end of the file merge cleanly and pass `--check` (shown by
   real merges in `tests/unit/test_findings_register.py`). A state change does not merge cleanly in meaning: when one
   branch changes a row's state and the other changes a neighbouring row's state or appends right after that row
   (also a new card at the end of the file after its last row), the union keeps both copies of the changed row, and
   `--check` fails on the id used twice and says to run `--resolve`. The integrator runs
   `python -m tools.findings_register --resolve` on the merged tree: when the copies differ only in the state and
   exactly one state other than `open` is among them, one row with that state stays in the place of the first copy
   (copies identical in every cell are folded too). Two different states other than `open`, or copies that differ in
   another cell, are left for a person. Whether GitHub's merge button reads the union setting is not checked; the
   trains merge with git.
9. **The check.** `--check` is strict, so that it cannot read fewer rows than the file holds without failing. In the
   head, a `|` outside a code span is an error. Below the first card heading, every line that is not blank, a card
   heading, the header, the rule or a row is an error, and so are a card heading with no table, a table with no row,
   a second section of one card, a header that is not exactly the register's and a missing rule. A parse error names
   its line; a row error names its line and its id. The rules of a row: the id's pattern and uniqueness, a real
   calendar date, a relative source link to a file inside `trialbox/`, the severity set, the lane set (A2, B2, C2,
   C2a, C2b, D, E, G, H, W, R, Int, V; G because P2b's review names lane G), the basis set and the state grammar. It
   runs in `make lint`, in `make ci` and in CI's `checks` job (the fast tier).
10. **The release.** `--check --release` is criterion 11: a High passes only as `fixed <sha>, seen closed by <who> on
    <date>` or `not a defect: <why>`; a Medium passes only as `fixed <sha>` or `not a defect: <why>` (a card issued is
    not a card done); a Low never stops it. It is not wired into CI now.
11. **A card's findings file.** `--add-from <findings.json>` appends a card's rows. The file is the form of
    `docs/plan/measurements/runbook-install-2026-11-17/findings.json` with these fields: `card` (else the first id's
    card), an optional `title`, optional defaults `date` and `source`, and per finding `id`, `date`, `source` (a path
    below `trialbox/` to an existing file), `severity`, `claim`, `lane`, `basis` and an optional `state` (`open` when
    absent). Every field is a string with no line break or control character. Other fields are the page's and are not
    copied. Every new row is checked first; nothing is written when one fails or an id is already in the register;
    after writing, the whole register is checked again and the old file is put back if the check fails.
12. **The older registers.** They are not changed or deleted. The problem log and the review registers stay as the
    records of their day. A finding of theirs that is still open enters this register when a card picks it up; this
    register does not copy them wholesale.
13. **The seed.** The findings of three pages of 2026-11-17: lane H's life-cycle walk (21), the install runbook
    followed alone (12) and launch P2b's review (14: its 8 proposed cards, then 6 more statements of something wrong
    or unproven in its sections 1 and 2 and its "Not shown" list). A row is `fixed` only where a commit on master
    plainly fixes it (H18-01: `0ee24331a`; H18-02: `f549bfb8b`), else `open`.

## Consequences

- A card that finds something adds its rows in its own pull request; lane V's coordinator adds its workers' rows
  from their `findings.json`.
- After a merge train, the integrator runs `--resolve` and then `--check` on the merged tree.
- The register is the record that V20 reads at release; the stale problem log is replaced by it for new findings.

## Used by

`tools/findings_register.py`, `tests/unit/test_findings_register.py`, `docs/handover/findings-register.md`, the
`lint` and `ci` targets of the `Makefile`, the `checks` job of `.github/workflows/trialbox-ci.yml`, `.gitattributes`.
