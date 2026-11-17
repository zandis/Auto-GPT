# D-1180 The one findings register: one row per finding, appended by card, checked by a tool

- **Task:** lane V, card V-0 (plan 8, `docs/plan/44-plan-8-2026-11-17.md`: section 3 criterion 11, section 5b,
  section 8b lane R, section 8c): the one findings register
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

Several lanes now find things at once, and each of their pull requests will add rows. A register that every card
edits must not turn every pair of those pull requests into a conflict.

## Decision

1. **One file.** `docs/handover/findings-register.md`, one Markdown table row per finding, readable by a person and
   by `tools/findings_register.py`. The columns: Id, Date found, Source (a relative link to the page or record the
   finding comes from), Severity, Claim (one line), Lane, Basis, State.
2. **One heading per card.** Each card's rows sit in one table under `## <card>: <words>`. A card adds rows only under
   its own heading, made at the end of the file the first time. Rows are never sorted or moved: a sort rewrites lines
   that other branches also touch.
3. **Ids.** `<card>-<local>`. The card is the card's name without its hyphen (H-20 is `H20`). Lane V's ids are the
   card and a number of two or more digits (`V2-07`), as the lane's rules say. A row from another source keeps the
   id the source gave after the card (`H20-F-16`, `H22-no-host-tree`); a source that gives none is numbered in its own
   order, two digits (`H18-01`). The id starts with its heading's card, is unique in the file, and is never reused or
   renumbered. A finding that turns out wrong stays, as `not a defect`.
4. **Severity.** High: a patient harmed or wrongly excluded, data leaked or not erased, a role doing what the matrix
   forbids, an audit trail that can be wrong, or a box that cannot be installed or restored. Medium: a person slowed or
   misled, or a document's claim not true. Low: wording. A severity mapped from a source's other scale is written
   with " (mapped)"; the head of the file says how each seeded source was mapped.
5. **Basis.** `shown`, `hypothesis` or `not_run`, as lane V's findings carry it; `not stated` for a seeded row whose
   source does not say.
6. **States.** Exactly one of `open`; `card issued #<pr>`; `fixed <sha>` (7 to 40 hex) with ", seen closed by <who>
   on <date>" once re-checked; `not a defect: <why>`. The lane that owns the finding proposes the new state in the
   pull request that changes it; lane R re-checks a fix and adds the "seen closed" words. A row is never deleted.
7. **No counts in the file.** `python -m tools.findings_register --counts` prints them (open High, open Medium, open
   Low, total; "open" is `open` or `card issued`). A counts line in the file would change in every pull request that
   adds a row and so conflict in every pair of them. A generated block has the same fault.
8. **Merged as a union.** `.gitattributes` gives the file `merge=union`: when two branches add rows at the same place
   (two new cards at the end of the file), git keeps both sides. When two branches change the same row, the union
   keeps both lines, and `--check` fails on the id used twice, so the conflict is caught and not lost.
9. **The check.** `--check` fails, naming the line and the id, on a row that breaks the form: the id's pattern and
   uniqueness, an ISO date, a relative source link to a file that exists, the severity set, the lane set (A2, B2, C2,
   C2a, C2b, D, E, H, W, R, Int, V), the basis set and the state grammar. It runs in `make lint`, in `make ci` and in
   CI's `checks` job (the fast tier). `--check --release` fails while a High is `open` or `card issued`, or a Medium
   is `open` (criterion 11); it is not wired into CI now.
10. **A card's findings file.** `--add-from <findings.json>` appends a card's rows. The file is the form of
    `docs/plan/measurements/runbook-install-2026-11-17/findings.json` with these fields: `card` (else the first id's
    card), an optional `title`, optional defaults `date` and `source`, and per finding `id`, `date`, `source` (a path
    below `trialbox/`), `severity`, `claim`, `lane`, `basis` and an optional `state` (`open` when absent). Other fields
    are the page's and are not copied. Every new row is checked first; nothing is written when one fails.
11. **The older registers.** They are not changed or deleted. The problem log and the review registers stay as the
    records of their day. A finding of theirs that is still open enters this register when a card picks it up; this
    register does not copy them wholesale.
12. **The seed.** Every finding of three pages of 2026-11-17: lane H's life-cycle walk (21), the install runbook
    followed alone (12) and launch P2b's review (its 8 proposed cards, as it gives no ids). A row is `fixed` only where
    a commit on master plainly fixes it (H18-01: `0ee24331a`; H18-02: `f549bfb8b`), else `open`.

## Consequences

- A card that finds something adds its rows in its own pull request; lane V's coordinator adds its workers' rows
  from their `findings.json`.
- The integrator's merges keep both sides of the file. GitHub's own merge button does not read `merge=union`; a
  conflict there is resolved the same way, by keeping both sides, and `--check` then says whether an id is twice.
- The register is the record that V20 reads at release; the stale problem log is replaced by it for new findings.

## Used by

`tools/findings_register.py`, `tests/unit/test_findings_register.py`, `docs/handover/findings-register.md`, the
`lint` and `ci` targets of the `Makefile`, the `checks` job of `.github/workflows/trialbox-ci.yml`, `.gitattributes`.
