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
3. **A box seeded before this card.** Its working copy holds the examples already. There the approval that came from
   seeding is no approval: `load_approved` refuses the ruleset on a site box ("a shipped example, not approved at
   this site"). Every job reads its ruleset through `load_approved`, and the console lists a ruleset it refuses as
   not approved. How a seeded approval is told (`seeded_approval`):
   - with the compiler's repository, the version's approval tag is the one the first start wrote, "(vendor-shipped,
     approved)". The site's own approval writes "approved by <who>" and an installed update writes "(offline update,
     <by>)" (D-77): those stand, whatever the manifest says;
   - without a repository (the copy `seed_working_copy` made; no approval ever tagged it), the manifest is the
     shipped one byte for byte.
   Nothing is deleted from a box: the files stay, the study pages show them as not approved, and the site approves
   its own version or removes them.
4. **The timers ask the same question.** `scheduler.nav_rulesets` and `cohort_rulesets` read the manifest's status
   themselves; they now also ask `approved_here` (`load_approved`), so a timer starts no job for a ruleset the job
   would refuse. (Two lines in lane B's file.)

## What this does not do

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
none as approved; the site's own approval tag and an installed update's tag stand; a folder without a repository
whose manifest is not the shipped one is read as before.
