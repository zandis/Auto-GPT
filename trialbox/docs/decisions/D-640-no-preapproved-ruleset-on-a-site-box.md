# D-640 No pre-approved ruleset on a site box: the shipped rulesets are examples for DEV and TEST

- **Task:** NEW-LIFE-1 (TB-PLAN-07 v7.3, wave 0, lane A); deep review 2026-11-12, finding LIFE-001 (Critical)
- **PR:** this branch (`agent/NEW-LIFE-1-no-preapproved-ruleset`)
- **Date:** 2026-11-12
- **Status:** proposed (merges on a green train and one adversarial review)
- **Builds on:** D-469 (the shipped folder is a read-only seed), D-127 (an unset `TB_ENV` is PRODUCTION), D-77
  (a ruleset from a verified offline update)

## Context

A new box copied the eight shipped rulesets into its working copy: three synthetic sponsor trials, three cohort
definitions and two NHI rule sets, each `status: approved`, approved by the project owner "via project chat" or by a
synthetic coordinator account. The seeding had no environment check. Under `TB_ENV=PRODUCTION` the weekly timer
then ran NAV for the two NHI rulesets and the quarterly timer ran COHORT for the three cohorts, on the hospital's
data, notes included, for studies nobody at the site approved. The rule "only the delegated PI approves" was passed
by the installer.

## Decision

1. **Only a DEV or TEST box is seeded.** `tb_common.ruleset.examples_allowed()` is the one rule: `TB_ENV` is DEV or
   TEST (the demo runs DEV). Every other name is a site box: VALIDATION, PRODUCTION, an unset `TB_ENV` (D-127) and
   a name nobody knows. It is a list of where examples may be, not of where they may not: a new environment name
   gets no examples until someone adds it here.
2. **Both seeders ask it.** `seed_working_copy` (console, orchestrator) copies nothing on a site box. The criteria
   compiler builds its repository through `criteria_compiler.app.ruleset_repo`, which gives a new repository no
   seed on a site box: it starts with its README and no ruleset.
3. **A box seeded before this card.** Its working copy holds the examples already. On a site box an approval is
   an annotated tag of the compiler's repository that says who gave it: the site's own approval writes "approved by
   <who>", an installed update writes "(offline update, <by>)" (D-77). `load_approved` refuses, on a site box, a
   version whose approval names nobody (`seeded_approval`):
   - the tag the compiler's first start wrote on a seeded example, "(vendor-shipped, approved)";
   - a bare tag (no message);
   - a folder with no repository at all (the copy `seed_working_copy` made): nothing in it is approved, whatever
     its manifests say. The first version of this card compared the manifest with the shipped one byte for byte;
     the review showed a box seeded by an earlier release differs by bytes (D-103 re-approved manifests in place).
   Every job reads its ruleset through `load_approved`, and the console lists a ruleset it refuses as not approved.
   Nothing is deleted from a box: the files stay, the study pages show them as not approved, and the site approves
   its own version, installs an update, or removes them.
4. **The timers ask the same question.** `scheduler.nav_rulesets` and `cohort_rulesets` read the manifest's status
   themselves; they now also ask `approved_here` (`load_approved`), so a timer starts no job for a ruleset the job
   would refuse. (Two lines in lane B's file.) A ruleset that cannot be read (a tag that points at nothing) is
   skipped with a warning; the timer goes on.
5. **An update installed over a seeded example** of the same content used to say "installed" and leave the seeded
   tag. `import_ruleset.install` now writes the operator's install on the tag (`RulesetRepo.retag`; the commit is
   not moved).
6. **Test boxes.** A fixture that builds a PRODUCTION box on the synthetic studies approves them the site's way
   (`tests.rulesets_guard.approve_at_site`, used by `tests/orch_box.py`).

## What this does not do

- **The compose test and POC stacks** (`deploy/docker-compose.test.yml`, lane D) leave `TB_ENV` unset for the
  criteria compiler and the orchestrator, which is PRODUCTION, while their console and gateway are TEST. With this
  card those two services hold no example study. The stack needs `TB_ENV: TEST` for both (as D-560 did for the
  embed service) or an import step; that is with the integrator and lane D, and was not run here.
- The compiler's own "previous approved version" (`service.py` `_approved`, used by compile reuse and `diff`) and
  `omop/vocab_load.py` still read a seeded example's manifest status. Neither runs a study; reused criteria go back
  to draft for the PI.

- The images still carry `/app/rulesets` (`deploy/docker/python.Dockerfile:34`, lane D). The review asks for the
  three synthetic trials to ship only in the demo image and the test tree; with this card they are inert on a site
  box, not absent.
- An offline update (D-77) may still install a ruleset its manifest calls approved, by an operator's act with a
  verified bundle. Whether a site box should take any approval but its own PI's is the owner's question; this card
  does not change D-77.
- It does not check that the approver of a tagged version is an account of this box (the review's third proposal):
  that needs the account store, which is lane C's.
- A site-box run on synthetic data that wants an example study (a GPU run, a rehearsal) gets it by `TB_ENV=TEST`,
  by the console's approval journey, or by `criteria_compiler.import_ruleset`; it no longer finds one at start.

## Test

`tests/unit/test_new_life_1_no_preapproved_ruleset.py`: a site box (PRODUCTION, VALIDATION, unset, lower case, an
unknown name) seeds nothing by either seeder; DEV and TEST are seeded as before; on a box seeded before, by the copy
or by the compiler, every shipped ruleset is refused by `load_approved`, the timers list none and the console shows
none as approved; the site's own approval tag and an installed update's tag stand. From the review: a folder with
no repository approves nothing on a site box (a manifest changed by a byte, CRLF, another title); a bare tag is no
approval; a tag that points at nothing stops no timer; an update installed over a seeded example stands and its
tag says so; the fixture's site approval. `tests/console/test_backend_contract.py` and the other tests on
`tests/orch_box.py` failed on the first version of this card and pass.
