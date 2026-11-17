# The full qualification on paper, 2026-11-17 (card H-15)

**Reader:** the people who build TrialBox, and the integrator deciding when to run a full `qualify --box`

This page plans the run of `trialbox eval qualify --box` on real weights that has never finished, as card H-12 did
for trec2023. Nothing was launched and no model was called. Every command quoted here was run on this branch, made
from master `8f5d429c` (train 66), with its output trimmed, not edited. A figure not found in the repository says
"not measured". Section 6 lists the findings and section 8 the questions for the integrator.

## 1. What qualify is and what its record is for

### The command and its gates

`python -m tools.trialbox eval qualify` is `tools/qualify.py` (D-313; `tools/trialbox/__main__.py:39-46`). With
`--box` it goes through `tools/box_qualify.py` first (D-737). That wrapper asks the running box, through
`docker compose ps -q` and `docker inspect`, for:

- each model server's weight folder (`--model-dir`);
- each model server's json-file log (`--server-log`);
- the gateway's audit folder (`--audit-dir`).

It prints what the box could not say and does not guess it. In the box's Python image (`services/` is there) it runs
`qualify.main` itself. On the host it starts that image with the release tree mounted read-only (D-881;
`tools/box_qualify.py:102-190`).

The 15 gates run in this order (`tools/qualify.py:101-117`). Each one ends `passed` or `failed`, and a gate that
raises is `failed` with the exception's class (`tools/qualify.py:1224-1251`).

| # | Gate | What it asks of the served pair | Models? | Pass condition (code) |
| --- | --- | --- | --- | --- |
| 1 | `pin` | the gateway lists both aliases; one judge call each way answers from the pinned build and weight hash; two different builds | yes, 2 calls | no problem in `tools/qualify.py:386-425`; a rehearsal placeholder pin or a rehearsal box is refused (D-887) |
| 2 | `serving_record` | none: the code identity, git dirty, driver and CUDA, routing, registry and prompt versions, the model server image of `deploy/images.lock`, the judge's chat template sha256 | no | the code is named; the tree is clean; a driver is there (`tools/qualify.py:516-544`; D-881, D-889) |
| 3 | `licence` | none: the registry's licence rows against `docs/licences/register.csv` and the licence file in each weight folder | no | `tools/qualify.py:582-614` |
| 4 | `schema` | every prompt of the active set, once, with an adversarial line | yes, one call a prompt | every answer valid on the first try and not cut off (`tools/qualify.py:627-697`) |
| 5 | `longest_prompt` | the longest judge and chart prompt the profile allows | yes, 2 calls | fits the context, answered, not cut off, no retry (`tools/qualify.py:738-766`) |
| 6 | `log_marker` | a planted marker in a note excerpt | yes, 2 calls | the marker is in no audit file, process log or server log (`tools/qualify.py:789-814`) |
| 7 | `canary` | the 54-case pair canary (`orchestrator.selftest`) | yes, 54 cases | the canary's own `ok` (`tools/qualify.py:837-860`) |
| 8 | `pair_gate` | each item of the sources through `NoteJudge` with the verifier, `--workers` in flight (default 4) | yes, 2,986 items on the box | per gated source (synthetic, medtxt): wrong exclusions at most 2 %, at least 20 exclusions, at least 50 answered, no answer at most 10 %; and the run's no answer at most 10 % (`tools/qualify.py:980-1004`; `tools/judge_bakeoff.py:107`, `tools/judge_bakeoff.py:498-502`, `tools/judge_bakeoff.py:639-649`) |
| 9 | `determinism` | the first 200 items with notes, twice, 16 in flight, no cache | yes, 400 items | 0 changed exclusions and 0 cache hits (`tools/qualify.py:1007-1031`) |
| 10 | `throughput` | none: the pair gate's own times | no | at least one answered item (`tools/qualify.py:1034-1053`) |
| 11 | `injection` | the 70 cases of `eval/injection/cases.yaml` (56 attacks, 14 controls) | yes | 0 changed facts; at most 2 % false positives (`tools/qualify.py:1056-1071`) |
| 12-14 | `n12`, `public_e2e`, `goldens` | none: a JSON result file each (`--evidence`) | no | says `passed` or `ok`; names this run's code (`head`); n12 says `basis: unadjusted` and `source: screen` (D-343, D-826; `tools/qualify.py:1074-1109`) |
| 15 | `planted_defect` | the same pair with every decided verdict flipped: the canary again, then the whole pair set again | yes, 54 cases and 2,986 items | both the canary and the pair gate fail (`tools/qualify.py:1112-1138`) |

The size options (`tools/qualify.py:1336-1338`):

- `--items N` cuts the pair gate's item list to its first N. `determinism` and `planted_defect` read the same cut
  list (`tools/qualify.py:879-889`).
- `--repeat-items M` is determinism's number of items (default 200).
- `--workers W` is the pair gate's items in flight (default 4). The driver passes none of the three unless
  `--qualify-args` names them.

### The record

`finalize` makes the record `failed` unless all 15 gates are in it and `passed`. `qualifies_production` is true only
for a passed record on real weights that is not a stub run (`tools/qualify.py:1164-1173`). `check_record`
recomputes the status, the body sha256 and the profile, and refuses a stub or synthetic record for PRODUCTION
(`tools/qualify.py:1184-1206`). The schema is `schemas/qualification_record.schema.json`. Its required fields are
format, record_id, profile, stub, gateway, builds, git_head, driver, cuda, operator, started, finished, steps,
status, failed_steps, qualifies_production, change_protocol and sha256.

What the record is for (D-569; `deploy/qualification/README.md`):

- A pair ships as `candidate`. A PRODUCTION gateway routes only a `champion`, and a build becomes champion only from
  a passing record of exactly its pinned weights (T-012b).
- The vendor's record goes into `deploy/qualification/<profile>/` in the release's pull request, where the bundle's
  signature covers it. `pin_model --promote-shipped` promotes the pair at install. The folder has no record yet.
- A VALIDATION box may make the record: qualify's calls have a route there (D-823 point 3). A record qualifies
  PRODUCTION when it passed with real weights, whatever environment made it.

### How the driver runs it

Steps 08 to 12 run in a `start` or a `dev` launch (`deploy/gcp/box-install-run.sh:2188-2212`):

- **08-qualify** (`step_qualify`, `deploy/gcp/box-install-run.sh:1469-1511`):
  - fetches the evidence files of `--qualify-evidence`;
  - waits for the stack to be healthy on the direct route;
  - fetches qualify's medtxt items (`d_medtxt`);
  - mounts the commit's `tests`, `docs`, `eval` and `deploy/images.lock` read-only (F13, F36);
  - runs `d_qualify` (`deploy/gcp/box-install-run.sh:687-718`). That is qualify `--box` in the box's image on
    `trialbox-net`, with the host's Docker socket and CLI, the operator's token, `TB_HOST_PROFILE=poc`,
    `TB_CODE_IMAGE` (the image's id) and `TB_HOST_GPU`.
- **In validation mode:**
  - `--qualify-args` adds qualify's own options;
  - `--qualify-timebox N` ends the step after N seconds, with no record;
  - the step is watched with the card's use as a heartbeat (`WATCH_GPU`) and writes a checkpoint line;
  - a failed gate is a result, not a stop (D-511).
- **In production mode:** the step is a plain `need`. A failed gate stops the run (G-2's rule;
  `deploy/gcp/box-install-run.sh:1509`).
- **09 and 10, promote:** promote a role's build only from a passing record. In validation mode a record that did not
  pass is "not promoted" (`deploy/gcp/box-install-run.sh:1512-1529`).
- **11, resolve:** `pin_model --resolve` (D-738) says which build PRODUCTION routes each role to. Outside validation
  mode it stops unless that is the promoted build.
- **12, doctor:** `trialbox doctor --live --json`. It runs from the host, so its serving FAIL is not real (hand-over
  T15).

## 2. The plan

### The launch line

Qualify needs an installed box with both model servers loaded. The one route measured end to end on this VM is
`dev`: the commit's images are built on the VM, its tree becomes the box's, and the stack comes up by the direct
route (hand-over 4.3 and 4.4). A `start` launch needs a signed bundle. The only one built was signed with a
throwaway key and is not a release (hand-over 4.3).

The launch, in the driver's own form. Each line is free except the last; the last starts the paid VM and waits for
the owner's yes (D-505):

    python -m tools.box_run src-bundle --commit <full sha> --out /tmp/src.bundle
    deploy/gcp/box-run.sh --preflight --mode validation --steps dev --release-id dev-<commit12> \
        --commit <full sha> --src-bundle /tmp/src.bundle
    deploy/gcp/box-run.sh --estimate --mode validation --steps dev
    deploy/gcp/box-run.sh --mode validation --steps dev --release-id dev-<commit12> \
        --commit <full sha> --src-bundle /tmp/src.bundle --no-wait

- With no `--qualify-args` and no `--qualify-timebox`, qualify runs every item.
- `--qualify-evidence "n12=gs://... public_e2e=gs://... goldens=gs://..."` adds the three evidence files. Section 5
  says why, on this route, they still cannot pass.
- The run is followed with `deploy/gcp/box-run.sh --collect <run id> --follow`.

### Gates and checkpoints

- **Order.** The gates run in the order of section 1 inside one process. Pin to canary are short. The pair gate,
  then determinism, injection and planted_defect hold the time.
- **What is visible.**
  - The pair gate prints `qualify: pair_gate: <answered>/<items> items answered (<s> s)` every 30 s (D-838;
    `tools/qualify.py:934-970`).
  - Each gate prints `qualify: <gate>: passed|failed` when it ends.
  - Every 60 s the driver writes a line to `logs/08-qualify.checkpoints.jsonl` and a `TB-PROGRESS` line to the
    console, then uploads `results.tgz` (`deploy/gcp/box-install-run.sh:580-592`). The line holds the gate qualify
    is in, the gateway's audited calls since the step began, and the card's use.
- **What a resume keeps.**
  - A resume keeps the finished steps, 01 to 07 included. Step 08, cut by a pre-emption, the cap or the watchdog,
    runs again from its first gate: qualify keeps no state between attempts and writes its record only at the end.
    The rehearsal case `reboot` shows that the cut 08 ran again (`attempts == 2`; section 4).
  - The checkpoints and the step log of the cut attempt stay in the bucket.

### The cap

- **The group cap.** `GROUP_CAP_HOURS["dev"]` is 3 h. The driver gives the cloud `--max-run-duration=3h`, and the
  VM its own `tb-max-minutes` = 3 x 60 - 5 = 175 minutes (`tools/box_run.py:67-75`, `tools/box_run.py:464`;
  `deploy/gcp/box-run.sh:386`).
- **What it covers.** The comment on `dev` names "the stack, G-1, canary, qualify (unmeasured)".
- **Whether the full run fits.** It fits only if the pair gate keeps the rate B8 measured. At lane G's "about 75
  minutes" it does not (section 3).

## 3. The estimate

US$2.74 a VM hour, spot (`tools/complete_run.py PRICE_PER_HOUR`; the driver prints it). One `dev` launch.

### What the driver prints

    $ deploy/gcp/box-run.sh --estimate --mode validation --steps dev
    Prices: g4-standard-48 + RTX PRO 6000, spot US$2.74/h, on demand US$8.22/h (tools/complete_run.py). Mode: validation.
    Launch: dev
      VM start                                                               900  constant: tools/complete_run.py BOOT_HOURS (...)
      b01-b03 clone, venv, images (this VM, 2026-11-15)                      198  measured: box-20261115T091037Z-ac36aa21f parts b01-b03
      02 the stack up by the direct route (this VM, 2026-11-15)              281  measured: box-20261115T094747Z-4c7c47017 part 02-install (direct)
      03-07 env, pins, serving record, G-1, canary                           260  measured: the same run, parts 03-07
      08 trialbox eval qualify --box (full)                              unknown  unknown: never finished on real weights
      known part 0.46 h (US$1.25 spot); 1 step(s) unmeasured, bounded by the cap: 3 h = US$8.22 spot / US$24.66 on demand
    In all at the caps: 3 h = US$8.22 spot / US$24.66 on demand

The driver has no `qualify` group:

    $ deploy/gcp/box-run.sh --estimate --mode validation --steps dev,qualify
    box_run: unknown step groups ['qualify']: one or more of build, start, g6, g9, g10, acc, probe, dev

The `start` estimate (production and validation alike) has 08 as "unknown: never run on real weights", 09-12
"unknown" and a 4 h cap (US$10.96 spot).

### The parts, each with its source

| Part | Seconds | Kind | Source |
| --- | --- | --- | --- |
| VM start, models resident | 900 | constant (an upper bound) | `tools/complete_run.py BOOT_HOURS`, as the driver prints it |
| b01-b03 | 198 | measured | the driver's row (run ac36aa21f) |
| 02, the stack up (direct) | 281 | measured | the driver's row (run 4c7c47017) |
| 03-07 | 260 | measured | the driver's row |
| 07g, the canary through the box's gate | 180 to 240 | measured, "about 3 to 4 minutes" | hand-over 4.6; not in the driver's estimate (finding F5) |
| 08: the medtxt fetch | not measured | | `d_medtxt` runs inside 08, before qualify |
| 08: pin to canary (gates 1 to 7) | 300 at most | measured bound | L8: six of them passed inside a 300 s probe; B8: the pair gate stood at 1,500 s of its own clock inside a 1,800 s box (run log, 04:15 row) |
| 08: pair_gate, 2,986 items | 3,051 | measured rate | B8: 1,468 items in 1,500 s = 0.979 items a second, 4 in flight (`--workers` 4) |
| 08: pair_gate, lane G's figure | 4,500 | stated, no derivation | lane G's README: "It needs about 75 minutes" |
| 08: determinism, 400 items, 16 in flight | 409 to 603 | not measured; a projection | 400 items at the pair gate's rate, low and high |
| 08: throughput | about 0 | no calls | the pair gate's rows |
| 08: injection, 70 cases | 285 to 337 | not measured; a projection | 70 cases at the canary's measured rate (54 cases in 220 to 260 s, hand-over 4.6) |
| 08: n12, public_e2e, goldens | about 0 | file reads | they fail at once without evidence |
| 08: planted_defect | 3,271 to 4,760 | not measured; a projection | the canary again (220 to 260 s), then 2,986 items again at the pair gate's rate |
| 09-12 | about 2 | measured | hand-over 4.7: 11-resolve 1 s, 12-doctor 0.3 s; 09 and 10 do nothing without a passing record |

About the items:

- Within an item, the judge's call comes first and the verifier's follows it. The pair gate runs 4 items at once
  (`ThreadPoolExecutor(workers)`, `tools/qualify.py:964`), so the rate is the rate at 4 in flight.
- B8's rate is the mean over its first 1,468 items only. Whether the other 1,518 are slower or faster is not
  measured. Offline, the synthetic source alone is 300 items (the stub run in section 4); the rest are medtxt items,
  which are not fetched offline.
- Lane G's 75 minutes is 0.66 items a second, slower than the rate it measured.

### Low, high and at the cap

| | Qualify (08) | The launch (boot to 12) | VM hours | US$ spot |
| --- | --- | --- | --- | --- |
| Low: the measured rate | 7,316 s | 1,639 + 180 + 7,316 = 9,135 s | 2.54 | 6.95 |
| High: lane G's 75 minutes a pair run | 10,500 s | 1,639 + 240 + 10,500 = 12,379 s | 3.44 | 9.42, never reached: the cap cuts it |
| At the cap | | 3 h (the VM powers itself off at 175 minutes) | 3.00 | 8.22 |

- **Low.** 300 + 3,051 + 409 + 285 + 3,271 = 7,316 s. It fits the VM's 175-minute cap (10,500 s) with about
  23 minutes to spare. The medtxt fetch and the time between steps are not measured and come out of that margin.
- **High.** 300 + 4,500 + 603 + 337 + 4,760 = 10,500 s for qualify alone. The VM powers off during planted_defect,
  with no record, so the money of the cap buys the gates reported up to then.
- **The rate that fits.** Before the pair gate: 1,639 + 240 + 300 = 2,179 s. That leaves 8,321 s under the VM's cap.
  Less injection and the defect's canary (337 + 260 s), 7,724 s remain for 2 x 2,986 + 400 = 6,372 items, which
  needs at least 0.83 items a second. Read on the checkpoints: **fewer than about 1,240 items answered at 1,500 s
  into the pair gate means the run will not finish under the cap.**
- **Not measured.** The pair gate past item 1,468; determinism; injection; planted_defect; the medtxt fetch;
  qualify's whole run on any commit.

### Against the money

The cap is US$200 (the owner, 2026-11-16; `docs/plan/42-plan-2026-11-16.md` section 3). The running total and the
confirming launch's figures below are the integrator's on #639 (2026-11-17 05:35 UTC), as card H-15 quotes them.
This card did not read them again on GitHub.

| | Running total | Left of US$200 |
| --- | --- | --- |
| Now (at most) | US$117.7 | US$82.3 |
| After the confirming launch, estimated US$6.9 | US$124.6 | US$75.4 |
| After the confirming launch, worst case US$10.7 | US$128.4 | US$71.6 |
| Then this run, low US$6.95 | US$131.6 to US$135.4 | US$64.6 to US$68.4 |
| Then this run, at its cap US$8.22 | US$132.8 to US$136.6 | US$63.4 to US$67.2 |

On demand (US$8.22 an hour) the cap would cost US$24.66. The driver launches SPOT unless `TB_PROVISIONING=STANDARD`
(`deploy/gcp/box-run.sh:51`).

## 4. The free checks before the VM starts

Each one is a command run on this branch, with what it must print.

### The source bundle and the preflight

    $ python -m tools.box_run src-bundle --commit 8f5d429cd2199aae5795def0f48db1a5921b352c --out <file>
    { "commit": "8f5d429c...", "ok": false,
      "why": "this checkout is shallow: its bundle would lack the history (git fetch --unshallow first)" }   # rc 5

After `git fetch --unshallow`: `"ok": true`, `"head": "8f5d429c..."` (rc 0). The proof of that file,
`src-bundle --commit <sha> --check <file>`, also gave `"ok": true` (rc 0). A cloud session's checkout is shallow, so
the integrator unshallows first.

    $ deploy/gcp/box-run.sh --preflight --mode validation --steps dev --release-id dev-8f5d429cd219 \
          --commit 8f5d429cd2199aae5795def0f48db1a5921b352c --src-bundle <file>
    preflight: ok     the steps are known
    preflight: ok     the launch's options would hold on the VM (filter, tag, streams, budgets, commit)
    preflight: ok     the source bundle is proved (D8): cloned as the VM clones it, the commit checked out
    preflight: ok     the metadata builds (every key the steps need, no key-like value)
    (the estimate of section 3)
    preflight: every free check passed (nothing was uploaded or started; ...)          # rc 0

It must print four `ok` lines and "every free check passed". Any other line is a refusal, exit 6.

### The validation-check

    $ PYTHONPATH=libs:services:. .venv/bin/python -m tools.box_run validation-check
     "environment": "VALIDATION",
     "qualify's calls (class D0, tools/qualify.py)": { "role": "judge", "class": "D0", "route": "qualify", ... },
     "pair_routes_in_validation": { (both builds): true },
     "can_run": true,
     "blockers": []                                                                    # rc 0

It must print `"can_run": true` and a route for qualify's D0 calls. The driver runs it only for a launch with `acc`.
A `dev` launch alone does not, so the integrator runs it by hand.

### qualify offline

`eval qualify` has no `--list` or `--dry-run`. `--help` lists the options of section 1 (rc 0). The offline run is
the stub pair on profile `ci`, through an in-process gateway in TEST. It needs `TB_ENV=TEST`; without it, an unset
`TB_ENV` means PRODUCTION (D-127), and the run fails 8 gates on "no service token" and "prompt_unqualified":

    $ TB_ENV=TEST TB_CANARY_GATE=off PYTHONPATH=libs:services:. .venv/bin/python -m tools.trialbox \
          eval qualify --profile ci --stub --out <folder>
    qualify: pin: passed
    ... (every gate passed)
    qualify: pair_gate: 300/300 items answered (17 s)
    qualify: injection: passed (56 attacks, 0 changed facts; 0/14 false positives)
    qualify: n12: passed (wiring only (--stub))
    qualify: planted_defect: passed (the planted defect was caught)
    { "status": "passed", "failed_steps": [], ... }                                    # rc 0, 75 s wall

    $ python -m tools.qualify --check <that record> --profile ci --environment PRODUCTION
    refused: synthetic weights or a stub run cannot qualify a PRODUCTION champion
    does not qualify                                                                   # rc 1

What the offline run proves:

- every gate's code runs;
- the record is written and checked;
- the planted defect is caught.

What it does not prove: the box, the models, any time.

### The unit tests of qualify

    $ PYTHONPATH=libs:services:. .venv/bin/python -m pytest -q tests/unit/test_qualify.py \
          tests/unit/test_box_qualify.py tests/unit/test_qualify_code_identity.py tests/unit/test_qualify_host_gpu.py \
          tests/unit/test_qualify_in_the_image.py tests/unit/test_qualify_n12_from_screen.py \
          tests/unit/test_champion_qualify.py tests/unit/test_g1_b3_qualify_marker.py tests/unit/test_g1_box_run.py \
          tests/unit/test_b200_qualify.py
    125 passed, 9 warnings in 127.43s

### The rehearsal of the driver

    $ tests/rehearsal/box-run/rehearse-box-run.sh happy qualify-timebox acc-qualify-fails
    check happy: passed
      ok   qualify-timebox: ended at its time box, said, the run went on
      ok   qualify-timebox: 2 checkpoint(s) with the gate it was in, in the bucket's results
    check qualify-timebox: passed
      ok   08: the failed gate is a result: which step and its figure
      ok   11: PRODUCTION routes no judge (a candidate pair)
    check acc-qualify-fails: passed
    rehearse-box-run: all cases passed: happy qualify-timebox acc-qualify-fails
    $ tests/rehearsal/box-run/rehearse-box-run.sh dev reboot
      ok   dev: b01-b03, the tree, then the start from 02 (no bundle), in that order
      ok   the cut step (08-qualify) ran again in the next boot
    rehearse-box-run: case reboot passed                                               # both rc 0

What the rehearsal proves (the VM script runs unchanged; the box is a stand-in):

- the driver's handling of 08: a failed gate stops a production run (`step-fails`) and is a result in validation;
- the time box ends the step and writes checkpoints;
- promote and resolve follow the record;
- a pre-emption runs 08 again from its start.

What it does not prove:

- The box's qualify is `tests/rehearsal/box-run/standins/box.py`. It prints "qualify: item" lines and writes a record
  of its own (lines 623-651). No gate, no model, no item count and no duration is real.
- The checkpoint's gate name is not checked against a real pair gate log. Finding F2 is the case it misses.

### Lane H's caller guard (H-13)

`tests/unit/test_h13_driver_callers.py` is not on master. It is on `claude/lane-h-13-gate-read` at `839b06e3`, read
there and not run here. By reading it:

- It holds the HTTP calls into the orchestrator (`http://orchestrator:8010`) found in the driver's `in_svc`
  snippets, and onbox.py's reads, against the orchestrator's route table.
- Step 08's calls are not among them. `d_qualify` is not an `in_svc` snippet, and qualify calls the gateway
  (`http://gateway:8020/v1`), not the orchestrator.
- The operator's token claiming the callers qualify uses (orchestrator, doc-parser, testbench) is covered elsewhere:
  `models/routing.yaml:164` gives the operator `"*"`, and `tests/unit/test_gateway_verified_caller.py:179-185`
  holds that map.
- The host's Docker socket and CLI in the qualify container are held by no test except the stand-ins of
  `tests/unit/test_box_qualify.py` and the rehearsal.

B8 is the evidence that those calls are accepted on a real box: pin's gateway listing, schema, canary and the pair
gate answered. That was on train 37 (`b266f9b7`). Finding F6.

## 5. What a pass must show, and when the record counts

### A pass

Every one of the 15 gates `passed` (the pass conditions of section 1), so `status: passed`. With real weights and no
stub, `qualifies_production: true`. Then:

- 09 and 10 promote each role's build with `pin_model --promote <build> --record <record>`;
- 11 shows PRODUCTION resolving judge and second_opinion to the promoted builds (D-738);
- 12 has no FAIL beyond `tb-doctor-expected`.

On a VALIDATION box "promoted" means champion in the box's own site pins. It is not a shipped record.

### When it counts as the product's qualification record

D-569 and `deploy/qualification/README.md` ask for all of these:

- `python -m tools.qualify --check <record> --profile rtxpro6000 --environment PRODUCTION` says "qualifies";
- the record names both builds of the pair and qualified exactly the pinned weight manifests (`pin` checks the
  answers' build sha against the pinned hash);
- `steps.serving_record.detail.model_server_image` is the image `deploy/images.lock` names in the release;
- `steps.serving_record.detail.chat_template_sha256` is the template in the judge's pin;
- it is committed into `deploy/qualification/rtxpro6000/` in the pull request that ships the release, under the
  bundle's signature.

The prompt set is not matched (D-569, "What this does not do").

### What makes this run's record not count

- **The three evidence gates cannot pass on this route (finding F1).**
  - Without `--qualify-evidence`, `n12`, `public_e2e` and `goldens` fail with "no --evidence ..."
    (`tools/qualify.py:1079`).
  - With evidence, each file must name the record's own code (`tools/qualify.py:1103-1106`). `d_qualify` sets
    `TB_HOST_PROFILE=poc` and `TB_CODE_IMAGE` and no `TB_RELEASE_TREE` (`deploy/gcp/box-install-run.sh:707-713`).
    In the image there is no git, so the record's code is `image:<the image's id>` (`tools/code_identity.py:27-44`).
  - `tools/n12_screen.py` writes `"head"` as a git commit (`tools/n12_screen.py:55-62`,
    `tools/n12_screen.py:140`). Its head can never equal an image id made on the VM.
  - So the record is `failed`, `qualifies_production` is false, and nothing is promoted. This holds in production
    mode too, where the same `d_qualify` runs.
- **The code is named by an image built on the VM, not by a release.** Nothing refuses such a record downstream:
  `check_record` and `pin_model --promote-shipped` do not read `git_head` (no use of it in `tools/pin_model.py`).
  Finding F4.
- **A cut run.** A record made with `--qualify-args "--items N"` is a cut run. Nothing in the record says so beyond
  `pair_gate.detail.items`.
- **The pair gate's sources.** A first N items may hold no medtxt item, so the medtxt checks would fail.

What the run gives, then, is a **measurement**: the verdict of gates 1 to 11 and 15 on the shipped serving. It is
not the qualification record. That is worth having, since pair_gate, determinism, injection and planted_defect have
never run on real weights (lane G's audit A, rows "Qualify" and "Determinism").

## 6. Findings

None was fixed here; each is for its owning lane.

| # | Finding | Where | Owner (by the file) |
| --- | --- | --- | --- |
| F1 | On every driver route the record's code is `image:<id>`, while the evidence files name a git commit: the three evidence gates cannot pass, so no full qualify through the driver can pass | `deploy/gcp/box-install-run.sh:707-713`, `tools/qualify.py:1103-1106`, `tools/n12_screen.py:140` | lane D (qualify, code identity) with lane G (the driver) |
| F2 | The checkpoint's "qualify gate X (n of 15 reported)" counts the pair gate's 30-second heartbeat lines as gates. Run on a log of seven gate lines and two heartbeat lines, it printed "qualify gate determinism (9 of 15 reported);" while the pair gate was running. On a real run n keeps growing past 15. The `gates_reported` note of a time box is not affected (its pattern needs a letter after the colon) | `deploy/gcp/box-install-run.sh:1461-1467` against `tools/qualify.py:953` | lane G (the driver) |
| F3 | `planted_defect` puts the whole pair set through the pair a second time. The full qualify is about two pair gates plus determinism, not one, and that is what makes it overrun the `dev` cap at lane G's rate | `tools/qualify.py:1112-1138` | lane D (whether the defect run may use a sample) |
| F4 | Nothing downstream refuses a record whose code is an image id made outside a release: `check_record` and `--promote-shipped` do not read `git_head` | `tools/qualify.py:1184-1206`, `tools/pin_model.py` | lane D |
| F5 | The `dev` estimate leaves out 07g (about 3 to 4 minutes) and 08's medtxt fetch, and has no row for qualify's parts. The driver has no qualify group to estimate, and the 3 h cap of `dev` covers bring-up and qualify together | `tools/box_run.py:226-245`, `tools/box_run.py:67-75` | lane G |
| F6 | Step 08's calls (the operator's token into the gateway, the host's Docker socket) are not covered by H-13's guard, which holds calls into the orchestrator only. The token half is covered by the gateway's caller map and its test; the socket half only by stand-ins | section 4 | lane H (whether to extend the guard) |
| F7 | In production mode 08 has no checkpoints, no time box and no GPU heartbeat: it is a plain `need`. The hand-over's 4.7 ("It writes ... `logs/08-qualify.checkpoints.jsonl`") holds in validation mode only | `deploy/gcp/box-install-run.sh:1493-1509` | lane G |

## 7. Risks and the recommendation

### Risks

- **L7's 1 h 52 min with no visible progress.**
  - L7 (run `box-20261115T123832Z-1157c9bfa`) ran images of `1157c9bf`, master train 28. The pair gate's 30-second
    heartbeat came with D-838, in train 30, so L7's pair gate printed nothing between gates. The run log's 14:44
    row says only "qualify full ran 1 h 52 min invisible -> stopped by lane G". L8 ran the same images, and six
    gates passed inside 300 s.
  - So L7 was past the canary within minutes, and it most likely spent the rest in the pair gate or later. At B8's
    rate, the gates through planted_defect would end at about 7,300 s; 1 h 52 min is 6,720 s. That is an inference:
    which gate L7 was in is not in the repository.
- **Progress is visible now**, with one fault. On master the pair gate prints its count every 30 s (B8 showed 1,468
  of 2,986), and validation mode writes checkpoints. F2 makes the checkpoint name the wrong gate during any pair run.
  Read the `qualify: pair_gate: n/2986` lines in the step log, not the gate name.
- **Spot pre-emption.**
  - The VM boots again only on `--resume` (hand-over T13).
  - 08 then runs again from its first gate: nothing of a cut qualify is kept, and each resume costs a boot and the
    stack's start (about 2.5 minutes to `TB-STACK up`, plus the model loads; hand-over 4.10).
  - At 2.5 h of 08, a pre-emption late in planted_defect costs most of the money.
  - `--qualify-args`, `--qualify-timebox` and `--skip` must be given again on a resume (F34, hand-over T19).
- **The idle watchdog** (20 minutes, `deploy/gcp/box-install-run.sh:234`). In validation mode 08 keeps it fed in two
  ways: the card's use, and the step log growing (a heartbeat line every 30 s in every pair run). Injection and the
  defect's canary print no line for some minutes, but the card is busy. Not a risk in validation mode. In production
  mode only the log counts (F7).
- **The cap.** Section 3: the run fits only at about the rate B8 measured or faster.

### Recommendation

1. **After the confirming launch, not before.** The confirming launch carries the plan's targets and has a measured
   estimate. This run cannot make the product's record anyway (F1), so it does not block R2 by being first.
2. **One launch, with a decision point on the checkpoints**, rather than a time-boxed probe first:
   - A probe only re-measures B8's first 1,500 s, which are measured already. A second launch pays another boot
     and bring-up (0.46 h, US$1.25 by the driver).
   - The integrator reads the pair gate's count at 1,500 s. At fewer than about 1,240 items, stop the run with
     `--stop`: it will not finish under the cap. The plan's rule "stop any launch more than 50 % over its estimate"
     falls at 3.8 h, later than the cap, so the cap decides first.
3. **If the integrator wants the run to fit with room:** two launches.
   - First: `--qualify-args "--items 1500 --repeat-items 200"`. Pair gate and defect run then take about half the
     time; it measures every gate's verdict on half the set.
   - Second: the full set, with the rate then known.
   - That costs a second bring-up and still gives no record that counts.

## 8. Questions for the integrator

1. F1: should lane D make qualify's evidence gates accept a record whose code is an image id, under the poc host
   profile only? Or should the driver mount the release tree (`TB_RELEASE_TREE`), so that a qualification record can
   come out of a `start` launch from a signed release? Until one of them lands, no driver run can produce a passing
   record.
2. Is the full run, as a measurement of gates 1 to 11 and 15 without a record, worth US$6.95 to US$8.22 now? Or
   should it wait for F1, so that the paid run is also the record?
3. Which evidence files would the run carry? `n12` must come from `tools.n12_screen` on SCREEN's own run (D-826).
   Is there a public_e2e and goldens result in the form qualify reads (`passed` or `ok`, and `head`)? This card
   found no option of `tools/public_e2e.py` or `tools/goldens.py` that writes one; that was found by reading, not
   verified.
4. May the run use `--qualify-args "--workers 8"` to shorten the pair runs? It is not measured. It changes the
   record's throughput figures, and it is not the concurrency the box screens with.
5. Should the `dev` group's cap stay 3 h for a launch that carries a full qualify? The estimate at lane G's rate is
   3.44 h. The cap is code (`tools/box_run.py:73`), so changing it is a card.
6. Should `planted_defect` run on a sample of the pair set (F3)? That needs lane D's change and a decision, since
   it is a gate of the record.
