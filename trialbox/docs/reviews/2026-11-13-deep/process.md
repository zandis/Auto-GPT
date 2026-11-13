# Deep review 2026-11-13, lane "process": how TrialBox is worked on, and whether agent-skills helps

*Session `session_013CtyYTBntvcvXz8P3Tr1J3`, opened by lane G's collecting session. Branch
`claude/deep-review-process`. Plain English; "verified" means I ran or read the thing named, "inferred" means I did
not. Evidence is from `origin/master` at `c7dcd5e7` (train 8), the pull request list and the CI run list of
2026-11-13 up to about 16:00 UTC.*

## 1. Summary

**Verdict on addyosmani/agent-skills.** It is a well-made, MIT-licensed set of 25 general engineering skills for
Claude Code. TrialBox already practises the disciplines that matter most here (test first, an adversarial review by a
fresh subagent, decision records, ratchets, CI tiers), in a stricter, project-specific form. Installing the plugin
whole would add about 7,000 lines of general advice that sessions would load and weigh against the owner's rules: noise.
Two ideas are worth taking, rewritten: the "Prove-It" pattern for bug fixes and the extract, doubt, reconcile, stop
loop of an adversarial review. I adapted both into one project skill, with the MIT notice. Adopt nothing else.

**Where time, tokens, CI minutes and the owner's attention are lost** (ranked; section 3 has the evidence):

| # | Loss | Verified? | Fix | Built here? |
| --- | --- | --- | --- | --- |
| 1 | No local command equals CI's fast tier; each written list misses steps | verified | `tools/prepush.py` + parity test | yes |
| 2 | The owner's rules live only in briefs; repository docs contradict two of them | verified | root `CLAUDE.md`; CONTRIBUTING fixed | yes |
| 3 | Six of ten red CI runs on 2026-11-13 were GitHub refusing to start jobs (billing or spending limit) | verified | owner checks the limit | no (owner) |
| 4 | Eleven open draft pull requests are already on master | verified | close them; a helper command | listed |
| 5 | Cloud sessions lack PostgreSQL on PATH, shellcheck and CI's uv version, so cross-card, shellcheck and lock-check fail or are skipped locally | verified | session-start hook | yes |
| 6 | A head is handed over with no check of the push rules | verified (no tool) | `tools/train_ready.py` | yes |
| 7 | Deep reviews read and write about 500,000 words in four days; each new one starts from scratch | verified (sizes), inferred (allowance) | a review reads the open-findings register, not old reviews | proposed |
| 8 | The integrator's train scripts are not in the repository; each new integrator rewrites them | verified (handover §8) | `prepush --train` profile, a train script | proposed |
| 9 | The nightly was red three nights running and nobody read it | verified (handover §3; run list) | a scheduled reader, or a mail on red | proposed (owner, lane D) |
| 10 | Messages between sessions go through the owner by hand | verified (handover §2) | integrator opens lanes itself so it can message them | proposed (owner) |

## 2. Terms

* **Lane**: a long-running agent session that builds cards in one area (A2, B2, C2, D, E, W, G).
* **Card**: one item of the plan; one branch `agent/<card>-<slug>`, one draft pull request.
* **Train**: the integrator's branch `train/<n>`, a `--no-ff` merge of several cards' heads; the full CI tier runs
  once on it, then it merges to master.
* **Fast tier / full tier**: the two sets of CI jobs (D-564). A draft card pull request runs the fast tier; a train
  runs the full tier.
* **Job-minute**: one runner minute of one CI job. GitHub bills each job, rounded up to the minute.

## 3. Evidence: how the project is really run

### 3.1 The local checks differ from CI's (verified)

CI's fast tier for a card is `checks` (12 steps), `data-scan`, `cross-card`, `powershell`, `differential`, and the
supply-chain `lock` job when the lock, the Makefile, `deploy/` or a workflow changes
(`.github/workflows/trialbox-ci.yml:94-162`, `trialbox-supply-chain.yml:9-25`). The local lists:

| Step of CI's fast tier | CONTRIBUTING "Checks before a push" | DEVELOPING "Before a push" | `make lint` | `make ci` |
| --- | --- | --- | --- | --- |
| ruff check, format | yes | yes | yes | yes |
| mypy (whole tree) | **no** | changed files only | yes | yes |
| doclint, decision numbers | yes | yes | doclint only | yes |
| licence register | **no** | **no** | **no** | yes |
| limits lint | **no** | **no** | **no** | **no** |
| contracts, rulesets | **no** | **no** | contracts only | yes |
| shellcheck | **no** | **no** | **no** | yes |
| cross-card | **no** | mentioned | **no** | via the whole suite |
| data scan | yes | yes | **no** | yes |
| `TB_TZ` on the test line | **no** (`CONTRIBUTING.md:70`) | yes | n/a | yes |

`make ci` is the closest but runs the whole suite (about 12 minutes on four cores) and still has no limits lint
(`Makefile:203-222`). The handover says the cost plainly: "On 2026-11-12 each of these, when it was missing from the
local set, let a red reach CI" (`35-handover-2026-11-13.md` §3 point 4). A red on a train costs a rebuild and a second
full-tier run, about 180 job-minutes for the CI workflow alone (train 8's run `43430131581`: 179 job-minutes) and
about 30 minutes of wall time, plus the lane's and integrator's turns.

### 3.2 Rules repeated in every brief, and contradicted in the repository (verified)

* There is no `CLAUDE.md` or `AGENTS.md` anywhere in the repository. The owner's standing rules exist in the
  handover (§1, a partial list) and in each session's opening brief. This review's own brief spends about 330 of its
  1,250 words on them; the lane brief is reused "word for word" (§4).
* `CONTRIBUTING.md:21-22` told a session to "take the next free number" for a decision. The owner's rule is the
  opposite (a lane's block or `D-TBD`). Two sessions taking a number at once already cost a renumbering
  (`2b2b1dec`: "decision renumbered D-589: D-584 was taken") and registry merges in trains (`7f112450`).
* `CONTRIBUTING.md:70` runs pytest without `TB_TZ`; D-315 says there is no default zone, so tests that need it fail
  for a session that copies the line.
* "Never pipe into `tail`" and "never read `secrets.env`" are written in no repository file.
* Kept well: every one of 506 non-merge commits on master since 2026-11-08 ends with the `Claude-Session` line;
  none names a model. 44 squash merges from before the trains end with GitHub's own `Co-authored-by` block: harmless.
  The push rule is kept too: no card branch ran CI more than three times on 2026-11-13 (85 card runs, 77 branches).

### 3.3 CI minutes (verified)

* The 30,000 runner minutes of 2026-11-12 came mostly before the cost fixes landed that evening: tiers (D-564,
  `5de2e19c`, 13:57 local time), one job for the short checks and no image gates on cards (D-578, `acbb9784`,
  19:35), shards (D-475, 19:36). After them a card push costs about 10 job-minutes (five runs measured: 9 to 10) and
  a train about 180 in the CI workflow. 1,532 runs of `trialbox-ci.yml` exist in total; 100 ran on 2026-11-13 up to
  15:47 UTC.
* **Six of the ten red runs that day were not code.** Runs `43378478894`, `43378764091`, `43379606688`,
  `43379981893`, `43384415146`, `43384753962` failed in the `changes` job with no step run; the annotation reads
  "The job was not started because recent account payments have failed or your spending limit needs to be
  increased." Later runs passed, so it was a window around 07:18 UTC. A lane that reads only "red" can lose a turn
  chasing a fault that is not there.
* The other four reds: `cross-card` on a card (#429, the card that added two cross-card tests), a shard and a demo
  walk on train 5, the demo image build on train 7, the coverage ratchet on train 8. The first could have been seen
  locally; the coverage ratchet cannot be (it needs every shard's coverage).

### 3.4 Pull requests passed over (verified)

43 pull requests are open, all drafts. Eleven of them (#377, #378, #412, #419, #422, #426, #431, #437, #448, #458,
#466) have their head commit already on `origin/master` (`git merge-base --is-ancestor`), most from train 5 or 8,
yet GitHub shows them open. The other card pull requests of the same trains show as merged. *Inferred cause:* the
lane pushed its head after the train had merged an earlier head, or the train merged a later sha than the pull
request's head at that moment; GitHub marks a pull request merged only when its head is in the pushed base at that
push. Effect: the integrator and the owner see 43 open items where 32 are live; old ones (#3, #6, #22, #71, #246,
#278, #324, #354) add more. The command to list them:

```sh
git fetch -q origin master
for pr_sha in <number>:<head sha> ...; do git merge-base --is-ancestor "${pr_sha#*:}" origin/master && echo "${pr_sha%%:*} is on master"; done
```

### 3.5 Cloud sessions cannot run the fast tier as they are (verified, this machine)

On a fresh cloud session of this environment: no `.venv` (8 s to build from the uv cache); PostgreSQL 16 installed
but not on `PATH`; no `shellcheck`; uv 0.11.32 while CI pins 0.13.7, so `make lock-check` fails here and passes in
CI; no Docker daemon (the Caddyfile check and image steps cannot run; lane D has the same gap, handover §2); Maven
Central refuses some artifacts, so the local CQL engine for `differential` cannot be fetched; no `pwsh`, no
`actionlint`. With the hook of section 5 the first four are fixed; the rest show as "skipped" in prepush.

### 3.6 Hand-relayed messages and the owner's attention (verified from the handover; effect inferred)

Lane G "cannot be reached session to session; the owner relays" (§2). Rule changes reach a lane only when the
owner types them in that lane's session (§2, §3: the whole-suite rule "he types that in each lane's session"); the
scan allow-list needs his yes typed in lane D's session. Eleven questions wait on him (§5). Each relay is a context
switch for the owner and a turn for two sessions. The rules that must be typed per lane are a real safety property
(a lane does not take rule changes from a peer), so the fix is fewer changes, not fewer safeguards: rules that are
standing go in `CLAUDE.md` once, through a pull request the owner approves.

### 3.7 Duplicated reviews (sizes verified, allowance inferred)

Reviews of 2026-11-09 hold about 252,000 words, the deep review of 2026-11-10 about 135,000, that of 2026-11-12
about 120,000; plan v7 is 12,000 and the handover 2,600. Seven review sessions spent their allowance in about eleven
minutes on 2026-11-13 (from the brief). *Inferred:* a deep-review brief that says "read the earlier reviews" makes
each session load a large share of half a million words before it finds anything; the findings register
(`docs/validation/problems.csv`, 50 rows) is not the single list of open findings, so each review re-derives them.

## 4. addyosmani/agent-skills, skill by skill

Read at commit `301b02b1` (2026-11-01). Licence MIT, "Copyright (c) 2025 Addy Osmani"; adaptation is allowed with the
notice kept. It installs as a Claude Code plugin (`/plugin marketplace add`, `/plugin install`), which brings 25
skills and 9 slash commands; its four hooks are optional and wired by hand. I ran none of its scripts.

"TrialBox has" names where the same discipline already lives.

| Skill | What it does | TrialBox has | Decision | Why |
| --- | --- | --- | --- | --- |
| using-agent-skills | meta-router to the other skills | no router | skip | routes to skills we do not install |
| interview-me | one question at a time until intent is clear | the owner's briefs | skip | the owner writes full briefs; sessions are told not to ask about gates |
| idea-refine | diverge and converge on an idea; writes docs/ideas | plan v7 | skip | planning is the integrator's; adds a docs folder doclint refuses |
| spec-driven-development | spec before code, gated phases | cards with acceptance in plan v7 | skip | the plan is the spec |
| constraint-driven-development | writes a quality bar into CONSTRAINTS.md, ratchets | limits lint, coverage ratchet, cross-card list | skip | already stricter and enforced by CI |
| planning-and-task-breakdown | spec into tasks with acceptance | plan v7 cards, backlog.csv | skip | same |
| incremental-implementation | thin slices, always compilable | one card one PR, three pushes | skip | same |
| test-driven-development | red, green, refactor; Prove-It for bugs | "test first" in the lane brief | **adapt** | the Prove-It step is not written down; now in `trialbox-card` |
| context-engineering | rules file, spec, packing context | no rules file | adapt the idea | the root `CLAUDE.md` is this skill's main advice, done once |
| source-driven-development | fetch official docs, cite versions | pinned packages, standards from packages | skip | general; lanes already cite sources |
| doubt-driven-development | fresh-context adversarial review loop | "one adversarial review by a fresh subagent" | **adapt** | the extract, doubt, reconcile, stop steps make our review sharper; its cross-model step needs the owner's yes and costs money: left out |
| frontend-ui-engineering | components, design systems, WCAG | console's own pages and UX reviews | skip | web-app advice; the console is server-rendered |
| api-and-interface-design | contract first, Hyrum's law | generated contracts, `contracts-check` | skip | enforced already |
| browser-testing-with-devtools | Chrome DevTools MCP workflows | Playwright walks | skip | needs an MCP server we do not use |
| debugging-and-error-recovery | reproduce, localise, fix root cause, guard | Prove-It covers it | skip | merged into the adapted step |
| code-review-and-quality | five-axis review, ~100-line changes | adversarial review | skip | a balanced review dilutes the adversarial one |
| code-simplification | behaviour-preserving cleanups | none | skip | a card changes behaviour; Claude Code's own `/simplify` exists |
| security-and-hardening | threat model, OWASP list | SECURITY.md, bandit, secret scan, authz matrix | skip | ours is domain-specific and enforced |
| performance-optimization | measure first, Core Web Vitals | scale gate, bench | skip | web-vitals focus does not fit |
| git-workflow-and-versioning | trunk-based, atomic commits, save points | trains, push rule | skip | conflicts: it encourages frequent commits pushed early; our push rule caps pushes |
| ci-cd-and-automation | quality-gate pipelines, previews, staged rollout | CI tiers, trains | skip | ours is tuned for billed minutes |
| deprecation-and-migration | expand and contract, announce, remove | migrations, D-records | skip | general |
| documentation-and-adrs | ADRs, the "why" | decisions as files | skip | same, stricter |
| observability-and-instrumentation | logs, RED metrics, tracing | audit records, doctor | skip | general |
| shipping-and-launch | pre-launch checklist, staged rollout | release gates, IQ/OQ | skip | general |

| Other part | Decision | Why |
| --- | --- | --- |
| 9 slash commands (`/spec`, `/plan`, `/build`, `/test`, `/review`, `/code-simplify`, `/constraints`, `/ship`, `/webperf`) | skip | `/build auto` commits per task and `/ship` starts three reviewer agents: both spend allowance and clash with the push rule; `/review` clashes with the built-in |
| 4 agent personas (code-reviewer, security-auditor, test-engineer, web-performance-auditor) | skip | balanced personas; our review is adversarial |
| hooks: session-start (injects the router), sdd-cache (HEAD requests on every WebFetch), simplify-ignore (rewrites source files in place until Stop) | skip | the last one can leave code replaced on disk if a session stops; the cache one makes network calls |
| its `CLAUDE.md`, `AGENTS.md` | skip | they say "don't copy it into another project" |

## 5. What I built (this pull request)

| File | What it does | Tested |
| --- | --- | --- |
| `CLAUDE.md` (root) | the owner's 11 standing rules once; the push rules; where things are. A brief may add, nothing relayed may relax. Changes only with the owner's yes | read against the brief and the handover |
| `trialbox/tools/prepush.py` | every step of CI's `checks` job, the fast-tier jobs, the offline supply-chain steps and the security scans; each into a log; every step runs after a failure; exit 0 / 1 failed / 2 skipped; writes `summary.json` for the head | `tests/unit/test_prepush.py` (15): fails when CI's `checks` job or fast tier gains a step the list lacks, or a command differs |
| `trialbox/tools/train_ready.py` | refuses a head that is dirty, unpushed, lacks the two closing lines, names a model, merges master, or has no complete passing prepush run; else prints `train-ready: #<n> <sha>` | `tests/unit/test_train_ready.py` (13), on throwaway repositories |
| `.claude/skills/trialbox-card/SKILL.md` | how a card lands: claim, test first (Prove-It), one adversarial review (extract, doubt, reconcile, stop), the local set, hand-over. So the lane brief can shrink to the lane, its block and its first cards | read |
| `.claude/skills/NOTICE.md` | the MIT notice of the two adapted ideas | text compared with upstream |
| `.claude/hooks/session-start.sh`, `.claude/settings.json` | cloud sessions only: uv at CI's pin, shellcheck, PostgreSQL 16 on PATH, the venv when the lock changed. 6 s first run, 0.06 s after | run twice, run after a lock change, run outside the cloud (does nothing) |
| `trialbox/CONTRIBUTING.md`, `docs/DEVELOPING.md` | `D-TBD` instead of "the next free number"; `TB_TZ`; one prepush command instead of partial lists | doclint |
| `.github/PULL_REQUEST_TEMPLATE.md` | plan v7, `D-TBD`, the prepush line, a "For the owner" section, the closing line | read |

My own local set on the final head: see the pull request body.

## 6. Proposals, ranked by benefit for the work

Savings are estimates from the numbers in section 3.

| # | Proposal | Work | Expected saving | Who |
| --- | --- | --- | --- | --- |
| 1 | Lanes run `tools.prepush` before every push and `tools.train_ready` before the hand-over (in this PR) | none after merge | each red caught locally saves a train rebuild: about 180 job-minutes and 30 to 60 minutes of wall time; on 2026-11-12 several | lanes |
| 2 | The owner checks the GitHub spending limit and payment state, and tells lanes that a red `changes` job with no step is billing, not code | minutes | stops lanes chasing phantom reds; keeps CI running | owner |
| 3 | New lane briefs say only: the lane, its block, its first cards, "follow CLAUDE.md and the trialbox-card skill" | none | about 330 words of rules and the card procedure per brief; one place to change a standing rule | integrator, owner |
| 4 | Close the eleven open pull requests already on master; the integrator runs the command of §3.4 after each train | minutes | a true queue of 32, not 43 | integrator |
| 5 | Merge this PR on the next train, so the session-start hook runs in every cloud session | none | cross-card, shellcheck and lock-check runnable locally in every session (they fail or are skipped today) | integrator |
| 6 | A deep review starts from one open-findings register and writes only what is new or changed; a review session's brief names at most a few files to read first | a register card | most of the reading of half a million words per review; the allowance problem of 2026-11-13 (inferred) | owner, integrator |
| 7 | `tools.prepush --train`: the integrator's list of handover §3 point 4 (goldens `--check --profile ci`, `test_e2e_simple.py`, the whole unit suite, the demo walks) as a profile of the same tool; and the integrator's `train.sh` as a tested `tools/train_build.py` | a card each | the rewrite every new integrator does (handover §8) and the reds of train 5 that came from a missing step | lane D or the integrator |
| 8 | The integrator opens lane sessions with `create_session`, so it can send them messages itself; the owner still types rule changes in a lane's own session | none | most hand relays of status and findings (handover §2) | owner decides |
| 9 | A scheduled reader of the nightly: one short session at 20:50 UTC that reads `trialbox-e2e.yml`'s run and posts the red jobs to the integrator | small; costs model allowance each night | three red nightlies went unread (handover §3) | owner decides (cost) |
| 10 | CI changes for lane D (not made here): a `checks` step `python -m tools.prepush --list` is not needed, but (a) run `test_prepush.py` in the fast tier so the parity holds on every card, (b) nothing in a workflow can report a job GitHub refused to start, so the owner's billing alert is the fix for 3.3, (c) pin `actionlint` as a binary download so sessions can run it too | small | parity enforced before trains; clearer reds | lane D |

## 7. What I chose not to do

* **Install the agent-skills plugin, its commands or its personas** (section 4). General advice that competes with
  the owner's rules; two commands spend allowance and commits freely.
* **Change a CI workflow.** The brief forbids it; proposal 10 lists what lane D could do.
* **A hook that blocks a push** (a git pre-push hook). It would run 3 to 5 minutes on every push of every person and
  surprise the owner; `train_ready` checks the same at the hand-over instead.
* **Give the session-start hook the Maven CQL engine fetch or Docker.** Maven Central refuses artifacts here and
  Docker has no daemon; both stay "skipped" in prepush and CI runs them.
* **Close stale pull requests or touch other sessions' branches.** Listed for the integrator.
* **Take a decision number.** The decision that lanes use prepush and train_ready is `D-TBD` below.

## 8. For the owner

| Question | Recommendation |
| --- | --- |
| The GitHub spending limit or payment state (six runs refused at about 07:18 UTC on 2026-11-13) | check it in Billing; nothing for the sessions to do |
| Is the root `CLAUDE.md` your standing rules as you mean them? It changes only with your yes | read its eleven rules once; correct any word |
| `D-TBD`: lanes run `tools.prepush` before a push and `tools.train_ready` before a hand-over | yes; the integrator numbers it |
| Lane briefs shrink to lane, block and first cards, with `CLAUDE.md` and the skill | yes |
| The integrator opens lanes itself so it can message them (proposal 8) | yes |
| A nightly reader session (proposal 9) | yes, if its allowance cost is acceptable to you |

## 9. Limits of this review

I could not read the lane brief itself (lane A2's session is not reachable from here); I used this session's brief
as the sample. I could not see billed minutes, only job durations. I read the 100 newest CI runs, not all 1,532.
The cause of the eleven stale pull requests is inferred. The allowance figures are from the brief.
