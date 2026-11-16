# D-891 the box rehearsal has one check a branch rule can require

- **Task:** REHEARSE-REQUIRED, the integrator's yes on #639 (2026-11-16) to lane D's plan after train 35
- **PR:** this branch (`agent/REHEARSE-REQUIRED-one-check-to-require`)
- **Date:** 2026-11-16
- **Status:** accepted

## Decision

1. `.github/workflows/trialbox-rehearse-box.yml` runs on every pull request (and by hand). Its trigger has no `paths:`
   any more: a required check that never starts leaves every other pull request waiting on "Expected".
2. A `changes` job lists the pull request's files (`gh api .../pulls/<n>/files`, the job's token with
   `pull-requests: read`; no new action) and matches them against the installer path, which now lives there only
   (the list of D-887, plus `tools/fetch_jvm_deps.sh`). By hand it always says yes.
3. The two legs (`rehearse (test)`, `rehearse (validation)`) run only when it says yes.
4. `rehearse-result` always runs after both and is the one name a branch rule requires: it passes when the legs
   passed (an installer change) or were skipped (none), and fails on a failed, cancelled or timed-out leg, on an
   installer change whose legs did not run, and when the changes job could not say. One aggregate avoids GitHub's
   handling of skipped matrix jobs as required checks.
5. `tools/fetch_jvm_deps.sh` names `maven-dependency-plugin` with its version (3.7.0) instead of the bare
   `dependency:` prefix, so Maven never asks Central which version is the newest; the rehearsal's CI stopped once on
   that lookup ("Error resolving version for plugin"). The same 102 jars with the same sums as
   `tools/jvm-deps.sha256` were fetched with it.

Making `rehearse-result` required is a repository setting (Settings, Branches, `master`, required status checks:
`TrialBox box rehearsal / rehearse-result`). This session cannot read or change branch protection; the integrator
brings it to the owner once this is on master. A pull request without an installer change pays only the seconds of
the two small jobs; one with it waits for the legs (15 to 19 minutes, in parallel). The repository is public: the
hosted runners cost nothing.

## Test

`tests/unit/test_rehearsal_required_check.py` runs the changes job's own script with a stand-in `gh` (seven file
lists, and by hand), the aggregate's own script on eight outcomes, and checks the plugin pin: all failed before (no
such jobs, the bare prefix), all pass after. `test_rehearsal_workflow.py` reads the installer path from the changes
job and asserts the trigger has none; `test_fetch_jvm_deps.py` splits on `:copy-dependencies` for the pinned form.
