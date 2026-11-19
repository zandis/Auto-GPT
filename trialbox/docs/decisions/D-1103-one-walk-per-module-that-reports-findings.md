# D-1103 One walk per module of the life cycle that H-10 and H-20 do not cover, reporting findings and fixing nothing

- **Task:** lane H, card H-29 (the integrator): "V16, one walk per module. H-10 and H-20 cover start-up to erase. Add
  the module walks they do not: feasibility alone on a no-GPU box (D-1066); safety; monitoring; an amendment."
- **PR:** this branch (`claude/lane-h-29-module-walks`)
- **Date:** 2026-11-17
- **Status:** reserved
- **Builds on:** D-1121 (H-10's walk of a new study), D-1135 (H-20's walk of a study's life), D-1062 (steps mode),
  D-1066 (a box without a GPU is a product form), D-415 and D-277 (the SAE type and its rules), D-764 (the SAE
  notice), D-380 and D-436 (the monitor grant and the monitor's pages), D-364 (amendments), D-1180 (the findings
  register)

## Context

Plan 8's V16 asks for one scripted walk per module of the life cycle, each for the roles that use it, in three
languages. H-10 and H-20 walk a study from its protocol to the erase. Four modules had no walk: feasibility on its
own (and on a box without a GPU), safety, monitoring and an amendment.

## Decision

1. **Four walks, one plan each.** `tests/e2e/module_walk_{feasibility,safety,monitoring,amendment}_plan.py`, with
   what they share in `tests/e2e/module_walk_common.py` and the test in `tests/e2e/test_module_walks.py` (ids
   `<module>-<language>`). Each step is done by the role that owns it in the permission matrix (its row is named in
   the step and held by a fast test); every role boundary is a refusal, a real request with the page's form token,
   answered 403. Every text a person clicks is a key of the console's catalogue or a label of a built-in form
   (`services/datacore/builtin/forms.csv`, whose three language columns are the forms' catalogue); a fast test holds
   that each has its zh-TW and ja form.
2. **Where they begin.** Safety and amendment begin a new study per language (`SAFEWALK`, `AMENDWALK`, with `ZH` and
   `JA`) with H-10's steps 1 to 11 and H-20's 12 to 15, imported from H-20's plan, not copied; a fast test holds them
   equal. Feasibility walks the seeded study `AD-MAB` (approved criteria, no report) and monitoring the seeded study
   `GZQO` with the seeded CRO account `cra` (named for it), each language adding its own monitoring visit.
3. **Feasibility on a box without a GPU.** Lane D's D-998 pins the embedder on a PRODUCTION box installed with
   `--mode stub` and says in RUNBOOK §1 what such a box does; a steps-mode box is not such an install. The walk is
   the feasibility user's path on the box master has (the stub model) and stops, as a finding of
   lane D, where the box would have to say what it cannot do without a GPU.
4. **One driver.** The browser is H-20's driver, `tests/e2e/life_cycle_walk.js`. It gains a small exported extension
   point: `extend({acts, holds})` registers extra act and expectation kinds, which the driver's two `default:`
   branches call before they refuse an unknown kind, and `main()` runs the walk; run as a script it behaves as
   before. `tests/e2e/module_walk.js` requires it, adds the acts a module's forms need (a field by the start of its
   label, a choice in a group by its legend, a check box, an "absent" expectation) and runs `main()`. H-10's and
   H-20's plans and tests are unchanged.
5. **It reports and does not fix.** No product file changes. A step that cannot go on because the product does not
   do what its documents say stops with the product's own words (a finding that blocks the step); the walk never
   asserts the fault as correct. The findings by step, the walk by step and what a steps-mode box cannot complete
   are on `docs/handover/module-walks-findings-2026-11-17.md`, in English, written from the plans and held equal by a
   fast test. The same findings are in `docs/handover/module-walks-findings-2026-11-17.json` in the findings
   register's `--add-from` form (card `H29`, the walk's severities mapped: blocks and slows to Medium, cosmetic to
   Low). They are not added to the register here: it is pinned to its seed rows until lane V takes new cards' rows.
6. **Logs.** Per module and language a JSON log outside the repository (`TB_WALK_LOG_DIR`, else the box's scratch
   folder), H-20's form: the page reached, the clicks, the time, the guesses, the refusals, any stop; chart numbers
   and whole pseudonyms masked.
7. **How it runs.** `make walk-modules` (one box, four modules, three languages) and `make walk-<module>`. The
   targets are added to the Makefile only. CI is not changed: like H-10's and H-20's walks, the nightly compose job
   would collect the e2e tests once merged; the integrator decides whether its budget takes them.

## After lane C2's WALK-1 (card H-29b)

A new study starts in start-up and opens only after its SAE type is chosen (D-1153). The imported steps 1 to 15
follow H-30's change of H-20's plan; the safety walk's steps 19 and 20 read the open state and the rule set instead
of pausing and reopening the study. SAF-02, SAF-04 and SAF-05 were walked again and are no longer seen: a module's
findings that a later run no longer sees are listed as such (`Closed`, with the decision that changed them) and their
ids are never given again. The findings page says so.
