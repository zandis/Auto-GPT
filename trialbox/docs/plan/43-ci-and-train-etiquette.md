# CI and train etiquette (2026-11-16)

How a lane's card goes through CI and onto a merge train. The integrator points the lanes here; the rules came from the
CI throughput measurement on #639 (2026-11-16: 682 runs in 24 hours, a full run 118 to 182 runner-minutes, the limit
concurrency) and the integrator's answers there. Decisions: D-564 (the tiers), D-578, D-969, D-970, D-1119 (the guard
step).

## The tiers

- **Fast tier**: `changes`, `checks`, `data-scan`, `cross-card`, `powershell`, `differential`. Minutes, on every push.
  `checks` ends with the **guard step** (D-1119): the test files marked `guard`, static readers of the tree that fail
  when something that must not be there is (a site time zone in code, a direct model call, an undeclared setting),
  with no database and no service, about a minute; then the collection check, which collects a pull request's
  changed test files twice and fails on an id that differs (the clock or random bytes in a parametrize id). Every
  tier runs both; `make guard` runs the first locally.
- **Full tier**: the fast tier plus `unit-shard` (six), `unit`, `property`, `goldens`, `e2e-simple`, `demo-boot`,
  `security`, `standards`, `images`.

Which a run gets is decided by `tools/ci_tier.py` in the `changes` job, and its log line says why:

| Run | Tier |
| --- | --- |
| A merge train (`train/*`), a push to master, a run by hand | everything (a master push at a tree a green train proved: fast, D-578) |
| A card's pull request that is a draft | fast |
| A card's pull request that changes only documents (D-969) | fast, plus the tests that read those documents |
| A card's pull request that changes a path on the full-tier list | full |
| A card's pull request labelled `ci:full` | full |
| Any other card's pull request (D-970, the trial of E) | fast: the train runs the rest |

The full-tier list is `FULL_TIER` in `tools/ci_tier.py`: what decides about a patient (matching, the criteria compiler,
the rulesets, the scenarios, the scoring and derived-value modules), the gateway and the guards, what guards patient
data (masking, small cells, access, the adapter, the lake's query guard and tombstones, the doc parser), erasure,
consent and opt-out (datacore), what sends patient files out (mail, the sponsor bridges), key sealing, the schemas,
and the gate itself. A test fails when a pattern on it no longer matches a file. Changing the list is a change to a
file on the list.

## Draft first

Open every card's pull request as a **draft**. A push to a draft runs the fast tier only, so push as often as you
need. Mark it **ready for review** once, when the card is done and your own local run is green. To have CI run the
full tier on a card that would not get it, add the label `ci:full` and re-run the workflow (or push): the labels are
read when the run starts.

## The guard marker

A test file whose job is "no X, only X, never X in the code or the tree" and that needs no database, no network and
no service gets the marker on the whole file: `pytestmark = [pytest.mark.guard, pytest.mark.nodb]`. The list lives
with the tests, not in the workflow. `tests/unit/test_ci_guard.py` fails if a marked file is not `nodb` or asks for
a database fixture, so the step never starts PostgreSQL. Keep the step under three minutes on a runner: run
`make guard` and give its time when you mark a file.

## The train-ready line states your own full local run

The train runs everything, but a card that reaches it red costs a whole train. So a `train-ready:` line on #639
carries your own full local run **on the merged head** (your branch merged with the base you name). A line without it
is not taken:

```
train-ready: #<PR> <full head sha> base <full sha>
local: <n> passed, <n> failed, <n> skipped (make test, or the cross-card list plus the card's tests: say which);
       make lint clean; make guard clean; data_scan, decisions_index, doclint, security_scan sast and secrets clean
```

Report a failure as it is: name each failed test and say why it is not this card's.

## The trial and its revert

The fast tier for ordinary cards (E) is a trial. The integrator reverts it if more than one train in five goes red
from a single card, by setting `CARD_TIER: touched` in `.github/workflows/trialbox-ci.yml`, nothing else. Under
`touched` (D) every ready card runs the full tier again, except that a card whose every change is under
`trialbox/deploy/`, `trialbox/tools/` or `.github/` (and on no full-tier path) skips `goldens`, `e2e-simple` and
`demo-boot`.
