# D-1101 Every stated limit at its edge: what a stated limit is, what "before work starts" and "plain words" mean

- **Task:** lane H, card H-35 (was lane V's V-16; the integrator): "every stated limit at the limit, one over and far
  over: refused before work starts, in plain words." A findings card: it reports and fixes nothing.
- **PR:** this branch (`claude/lane-h-35-limits-at-and-over`)
- **Date:** 2026-11-18
- **Status:** reserved
- **Builds on:** D-1180 (the one findings register), D-1137 (H-23's size test: scale is not this card), D-471 and
  D-534 (the limits lint and its register `tools/limits_allow.yaml`), D-119 (the words of every refusal in the page's
  language), D-854 (a long text is refused, never cut)

## Context

The product states many limits: in decisions, the user guide, the runbook, the security pages, the specification,
the declared settings and the limits register. Nobody had driven them at their edge. A limit that holds in its unit
test can still accept one over, refuse only after it has stored something, or refuse in words that do not say what
the limit is.

## Decision

1. **A stated limit** is a number that a document, a decision file, a declared setting (`libs/tb_common/config.py`)
   or the limits register writes down as a bound on what a person, an operator or another service may do. Its row in
   `tools/limits_edge.py` (`STATED`) names the file and a phrase that must stand in it; the line is found again on
   every run, so a row whose phrase is gone fails the list. A bound that only the code states (a module constant
   with `MAX` in its name that no row claims) is **unstated**: it is listed apart and not tested. A capacity target
   (studies per site) or a performance condition (FR-CASE-03) is listed as stated and not driven: it is not a
   refusal.
2. **Three cases.** At the limit (must be accepted and work), one over (for a floor, one under), and far over: ten
   times the limit, or less where the box would hold the whole request in memory (said per row).
3. **Before work starts** means that a refused request left nothing behind: no job row, no stored file or object, no
   stored record, no call to another system, and no audit record of work. A refusal after a download, a stored row
   or a call to another system is "after work began" and is a finding.
4. **Plain words** name the limit's value and say what to do, in the page's language: no stack trace, no exception
   name, no text key or code-like token, and no run of three or more English words on a zh-TW or ja page. A page that
   says only "this could not be done; ask the administrator" does not name the limit. A service-to-service refusal
   (an API, the mail gateway, a setting at start-up) is judged in English only.
5. **The box** is in-process: the console app on the console tests' stand-in orchestrator with its own PostgreSQL,
   the real orchestrator's `create`, and the services' enforcement functions; a row driven on a function says so.
   Compose is not used. Findings go to the card's page and to a JSON in the register's `--add-from` form; lane V
   enters them in the register.

## Consequences

- `tools/limits_edge.py` builds the list (35 stated rows, the register's 74 rows, the bound settings, the unstated
  constants) and drives 18 rows; `make limits-edge` runs the drivers and fails only when a verdict differs from the
  page's.
- The page `docs/plan/measurements/limits-edge-2026-11-18.md` and `limits-edge-2026-11-18/findings.json`.
