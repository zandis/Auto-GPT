**D-206 CI gate v1: one workflow of stable jobs on every pull request and push, the drills nightly, `make ci` the
same list locally.** Task T-007 of TB-ASSESS-01 (`docs/reviews/2026-11-09-assessment-and-tasks.md` §3.1; WS-01.4
part, WS-12.2, WS-13.8; URS-ADM-06, RSK-14, TST-CI-01, TST-UNIT-01), branch `wave0-ci`, no pull request yet (the
integrator opens it). 2026-11-09. On top of D-201 (xdist, the lock, `TB_TEST_DB_URL`) and D-203 (the scan).

*Why.* No CI job ran `pytest`, `make lint` or `mypy` (P-34f): the only workflow ran `e2e_simple` and the backup drill
on pull requests, so a broken unit test or a type error reached master unseen, and every agent re-ran the 18-minute
suite on a laptop as the only gate.

*What.* `.github/workflows/trialbox-ci.yml`, on every pull request that touches `trialbox/` or a TrialBox workflow
and on every push to master, with `permissions: contents: read`, superseded runs cancelled, each job at most 15
minutes, the venv built by `make venv` from `uv.lock`. Jobs, by stable name: `lint` (ruff check and format, and
actionlint on the two workflows), `types` (mypy strict), `docs` (doclint), `contracts` (`make contracts-check`),
`trace` (`tools/gen_traceability.py --check`), `unit` (`make test PYTEST_N=auto` against a `postgres:16` service
through `TB_TEST_DB_URL`, its server tuned as `pglocal`'s are, then the data scan of the test log), `e2e-simple`
(the D-111 gate), `goldens` (`make goldens-check` once T-006 adds it; until then a warning that says so),
`audit` (pip-audit of the locked dependencies), `data-scan` (D-203), `shell` (shellcheck) and `images` (hadolint).
`trialbox-e2e.yml` becomes the nightly: `public_e2e`, the backup drill and the update drill, each on its own runner.
`make ci` runs the same list locally, in the same order. RUNBOOK §3 "Build gate: the CI jobs" has the table.

*Not gating yet, with the date (2026-11-10).* `audit` is `continue-on-error` until T-110 (supply chain) sets the
policy: the card expected pypdf and pillow findings (seen on the shared venv), but against `uv.lock` pip-audit 2.9.0
reports none today. `images` is `continue-on-error`: hadolint has never run on these Dockerfiles; its first findings
are triaged before it gates. `shell` gates on shellcheck errors (none today) and lists the warnings: ten, all in
`deploy/` scripts (`deploy/gcp/*` is out of this card's reach), open as findings. `goldens` passes with a warning
until T-006 lands.

*Owner actions.* The required checks on `master` (GitHub branch protection): `unit`, `lint`, `contracts`,
`goldens`, `data-scan`, `e2e-simple`. The job names are stable so that this list does not change.

*Evidence.* `make ci` on this branch, with `TB_TEST_DB_URL` pointing at one server for all four xdist workers as
the `unit` job does: ruff clean, mypy clean (621 files), doclint clean, contracts up to date, traceability clean,
`make test` 1,791 passed and 10 skipped in 11 min 29 s, the data scan of its log clean, `e2e_simple` PASSED in
128 s, pip-audit no findings, `make data-scan` clean (1,733 files), shellcheck errors none; 14 min 32 s in all.

*After the adversarial review* (Fable, 2026-11-10). H6: with `paths:` filters on the triggers, a pull request that
does not touch `trialbox/` never starts the workflow and its required checks wait for ever; the triggers now have no
filter and a first job, `changes`, compares the pull request with its base and lets the others skip (a skipped job
satisfies a required check). Pushes to master are no longer cancelled by a newer push. The unit job tests as a role
with LOGIN CREATEDB only, as `pglocal` does, not as the image's superuser (M15), and its server tuning step finds the
container by `job.services.postgres.id` and fails if the server does not come back. Not changed: the unit job's
15-minute limit assumes a four-core runner (`ubuntu-latest` has four cores on public repositories, two on private
ones: if the first runs are slower, the limit or the runner size is raised); actions and images are pinned by tag,
not by digest (T-110's supply-chain card); the nightly has no failure notification yet.

*On merging master and wave0-goldens* (2026-11-10). One copy of each job: `goldens` now runs `make goldens-check`
(T-006 landed through wave0-goldens; its separate `trialbox-goldens.yml` is dropped, since that workflow's `paths:`
filter would leave a required check waiting); `audit` is dropped, because the supply-chain workflow of D-185/D-186
(`trialbox-supply-chain.yml`, job `lock`) gates pip-audit against an allow-list, with the lock check and the licence
gate; `make ci` runs `lock-check` and `allowlist-check` in its place. Every action is pinned to a commit and the
`unit` service image by digest (D-186), and uv is the lock's 0.11.32. The test group of D-201 is in the one `uv.lock`
(regenerated with `make lock`); it is not in the runtime export `deploy/requirements.lock`, so the images do not
carry it; its packages are MIT or Apache-2.0.

*Limits.* actionlint and hadolint were not run here (no binaries may be fetched in this session), and no GitHub run
exists yet: acceptance (1) green on master, (2) red within five minutes on a lint break, (3) red on a stale golden
and (5) the required checks are shown by the first runs after merge and by the owner's setting. Not in this card:
the rehearsal in CI (needs a runner with docker and 4 GB, review §5.4), the nightly random-order run (the sibling
session's order-independence work), the per-feature registration files of review §5.2 (5).
