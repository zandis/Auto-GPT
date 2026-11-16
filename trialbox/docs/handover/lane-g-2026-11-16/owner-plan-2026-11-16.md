# Owner's plan for the rest of PoC-1 and the VM hand-over (2026-11-16, received about 02:05 UTC)

This replaces the owner's earlier note of today. Work through it in one go, without waiting for the owner between steps. Bring the owner only a decision, a spend over the line, or a stop.

## Rules that hold throughout

- **Budget.** US$210 in total (D-516).
  - Before each launch, post on #639: the estimate, the worst case, and the running total.
  - Stop any launch that runs more than 50 % over its estimate.
  - Hard stop for all of part B: a running total of US$130. If part B cannot finish under that, stop, post what is left with its estimate, and ask the owner.
- **Data.** Public and synthetic data only; nothing from a hospital source. The demo's address, stop time and sign-in codes stay in this session only: never in the repository, never on GitHub.
- **Figures.**
  - Every figure names its commit, and the two columns are never mixed.
  - A set that did not finish is labelled "partial: X of Y answered".
  - A step that did not run says "not run" and why.
  - No figure is rounded up.
  - Beside every pair-level figure, report `judging.may_block` and `judging.note_block_code` for that job.
- **Compiles and logs.** Compile each protocol once per column and score that compile. Keep, per set, the criteria-compiler's log, the gateway's log, and the trace store.
- **Faults.** A product fault is a "red:" on #639, with file and line, the moment you see it. Keep the workaround, record it, and carry on.
- **Ownership.** Product code in another lane's files goes through that lane. Lane G's driver and results are its own.
- **External code model.** Follow docs/plan/41-external-worker.md. Name no model anywhere.

## Where things stand (so nothing is redone or waited for)

- Master is 2d354036 (train 37). Train 38 (#781, lane D's restore drill) is in CI and changes nothing lane G calls.
- Already fixed on master:

| Fix | Decision | Train |
|---|---|---|
| G-1's extra token | D-880 | 30 |
| The negated exclusion and the empty code list | D-796 | 32 |
| The embed service, and its 6 GB limit | D-900, D-890 | 33 |
| SCREEN waiting out an embed outage | D-902 | 34 |
| Qualify's files, code identity and host GPU facts | D-838, D-881, D-889 | 30 and 32 |
| The site settings file on every start path | D-888 | 35 |
| Skipping S2b when the window fits | D-904 | 36 |
| Duplicate notes shown once | D-905 | 36 |
| The terminology update: generic diabetes mellitus and the C50 breast-cancer synonyms now map (release TR-7cedf1a45e79) | D-906 | 37 |

- The launch of 01:59 UTC runs on 93b6c945 (train 36), so it does **not** have train 37's terminology.
  - Let it finish.
  - Keep its figures as a third, clearly named column ("master at train 36") or as an appendix.
  - The master column proper is on 2d354036 or later (part B).
- **Why the box excluded nobody.** Lane A2 answered on #639 at 01:13 UTC. A note-read "not met" excludes only when note_block is on, and that needs all three of:
  - `TB_NOTE_BLOCK=both_agree` (the default);
  - a second, different verifier;
  - the box's **own** canary gate holding a passing record under 36 hours old, with no failed wake check since.

  An approved ruleset then excludes without a person when the pair agrees. The cause was not D-478 and not a review flag.
- **Lane A2's queue:**
  1. six compiler cards from lane G's red, with the wrong age and sex exclusions first;
  2. D-907: the load at start, numpy similarities, and the criterion text in the judge cache key;
  3. the judged-pair store, which the owner has approved (D-519).
- #772 is closed: lane A2 has taken what it wants from it.

## Part A: close the frozen column (commit 1157c9bf; no VM cost; do this first)

- **A1.** From one finished tcga job's screen JSON, post on #649 the values of `judging.note_block_code` and `judging.may_block`. Label the frozen column's pair-level row with that cause.
- **A2.** Post on #649 the 10 wrong age and sex exclusions from trec2023 (public data), one line each. Lane A2 is waiting for this. Each line gives:
  - the protocol and criterion id;
  - the criterion's source line;
  - the compiled atom: operator, bound, unit, inclusive or not, inclusion or exclusion;
  - the patient's age and sex, both as the set gives them and as the box's lake holds them;
  - the index date the box used;
  - the qrel.

  Say which lines, if any, are the scorer's reading and not the box's answer.
- **A3.** For the five compile failure classes in the red of 01:53, add what can be read without a launch:
  - the lengths (characters, lines, criteria) of the protocols that failed in each class, against those that passed;
  - any saved response body of the HTTP 422s and 500s.
- **A4.** Close #772 (done by the lead). Merge master 2d354036 or later into claude/lane-g-box-accuracy.

## Part B: the master column

Commit: lane G's branch with master 2d354036 or later merged. Freeze that commit and name it.

Build the images on the VM from that commit and bring the stack up by the direct route. Use new ruleset ids. Leave the embed service at master's own default memory limit (6 GB). Then, in this order:

- **B1. G-1.**
  - Identity: the served chat template's sha; the model server image digest against images.lock; the weights against their pins; the served prompt ids.
  - Token half: with D-880, the server's ids must equal the offline tokenizer's on all 20 prompts.
  - Post, for one prompt with a system message, the ids and token texts at positions 20 to 24, served and offline. If they still differ, that is a red.
- **B2. The pair canary, through the box's own gate.** Use `make canary`, or `python -m tools.trialbox selftest`, or the admin "Run now" (`canary_gate.run_canary`).
  - Post the judge's, the verifier's and the pair's counts.
  - Confirm the gate holds a passing record.
  - Every SCREEN below must start within 36 hours of it.
- **B3. jmed, 2 protocols.** Does the wrong-exclusion count fall with D-796 and the new terminology? Report:
  - how each of the two protocols compiled (structured, mixed or for a person);
  - what its value sets mapped to;
  - the same four figures as the frozen column.
- **B4. tcga BRCA, 500 patients.** This row is the product's real exclusion rate. Report:
  - wall time;
  - the stage breakdown: S0/S1, note read, S2, S2b, judge calls, report;
  - the share of patient windows that fit the excerpt budget and so skipped S2b;
  - embed requests, embed seconds, the embed service's memory sampled every second, and its restart count;
  - judge calls and latency (median, p95, max);
  - the criterion-level figures;
  - the pair-level figures, with `may_block`.
- **B5. tcga, the other four protocols** run before (COAD, HNSC, KIRC, LIHC), if B4's time says they fit.
- **B6. sigir and trec2023 in full.** sigir: all 104 protocols. trec2023: all 297 protocols and 500 pairs. Each runs within its own budget. Report:
  - "X of Y answered";
  - the criterion-level and pair-level figures;
  - every failure, sorted into the five classes or a new one, with the compiler's and gateway's log lines for each class.

  Do not wait for lane A2's compiler fixes.
- **B7. chia, jrct and tfda, compile-level.** Report how many protocols compile and into which classes, how many negated atoms the post-process rewrote, how many value sets mapped to nothing, and how many compiles failed and why.
- **B8. qualify --box**, time-boxed at 30 minutes, with `TB_HOST_PROFILE=poc` and the host GPU facts passed as lane D posted them on #649. List each step as passed, failed (with the reason), or "not run in this phase":
  - pin, licence, schema, longest prompt, log markers;
  - canary, serving_record;
  - the pair gate, determinism, planted defects, injection;
  - the three evidence steps that need TREC 2021/22 (D-826).
- **B9. Determinism.** Run tcga BRCA's SCREEN a second time on the same compile, and report how many patient-criterion answers differ between the two runs.
- **B10. The one-command route,** once, on a clean start: `TB_LLM_MODE=gpu deploy/poc.sh` (lane D's D-839). Does it pass its preflight, pin, bring the pair up and pass the canary by itself? Report the time to healthy. Every stop is a red with the exact message.
- **B11. A restart.** With the stack up, reboot the VM once. Does it come back by itself, on the SITE settings file (D-888), with the weights mounted and both models answering? Report the time to healthy, then confirm which settings file each service has mounted.
- **B12. Lane D's disk estimates,** on this VM, sizes and versions only:
  - the summed docker image sizes of the bundle's images;
  - the size of a `docker save` of them;
  - Docker root's size before and after a load;
  - `docker version`'s server version;
  - `docker info`'s storage driver.

If time or money runs short, drop in this order, starting with the first: B12, B9, B5, B7, B10, B11, B8. Never drop B1 to B4 or B6.

## Part C: after lane A2's compiler fixes land

The integrator will say so on #649. Do not wait for this before finishing parts B, D and E.

- **C1.** Re-run only the trec2023 and sigir protocols that failed to compile or to screen, plus the 10 age and sex cases, on the master that carries the fixes. That makes one more column, named by its commit.
- **C2.** When the judged-pair store is on master, run tcga BRCA's SCREEN twice and report the store's hit rate and the second run's wall time.

## Part D: write it up

- **D1.** docs/plan/measurements/poc-1-evidence.md, one page, in this order:
  - what was run, on what hardware and by which route, and that the bundle, signature, key sealing and installer were **not** exercised;
  - the table: one row per set, with a column for the frozen commit and one for master. Each cell gives the figure with its interval, what the row measures (the compiler, the judge at criterion level, or the product's rule at pair level), `may_block`, and "partial: X of Y" where it applies;
  - speed: per 500-patient SCREEN before and after, with the stage breakdown and the share of windows that fit;
  - what broke, in two lists:
    - product faults, each with its D-number and train, or "open" with its red;
    - lane G's own tooling faults, F1 to F30, in one line each or by group;
  - what it cost: VM hours and US$ by phase, the disk and the bucket, and the running total;
  - what was not run and why: TREC 2021/22, G-6, G-9, G-10, promotion;
  - which chat rendering each column served.
- **D2.** The walkthrough's closing table (docs/handover/demo-2026-11-17.md), filled from the evidence page.
- **D3.** The final report on #639, in five parts. The integrator turns it into five lines for the owner.
  1. What the evidence shows.
  2. What broke.
  3. What it cost.
  4. What is ready for Tuesday.
  5. What lane G advises next.
- **D4. The demo, before 12:30 UTC:**
  - rebuild the demo image from Monday's master;
  - seed it in the language it will be shown in;
  - switch to one-time links;
  - walk the 17 steps again, as owner and as guest;
  - fix or report anything that breaks.

  Give the owner the address, the stop time and the links in this session only.
- **D5.** Post train-ready for #628 and then #649 when the chain ends, each with its full head sha. Before that, apply lane A2's four review points on the scorers:
  - the absolute TREC line against the qrels, beside the reproducibility check;
  - MedTxt denial tested in the mention's own clause, before "treated";
  - a treated mention proposed as current counted as an error.

## Part E: hand the VM over to the integrator (after D1 to D3 are posted)

- **E1. State of the machines.**
  - Leave the GPU VM stopped (TERMINATED).
  - Leave the demo VM as Tuesday's walkthrough needs it, with its stop time.
  - List everything that still bills while stopped (disks, the bucket, any reserved address), with the rate of each, verified from the console or the price list, not estimated.
  - Say whether the 400 GB disk should be shrunk or kept.
- **E2. docs/handover/gpu-vm-handover-2026-11-16.md**, with no secret, key, address or sign-in code in it. It covers:
  - the project, zone, VM names, machine types, disks, the GPU, the image, and what is installed on it;
  - how to start, stop and check each VM, and how to tell it is healthy;
  - the driver: every step run, with its exact command and flags (probe, build, bring-up by the direct route, G-1, the canary through the box's gate, qualify, each accuracy set, collect, resume), plus what each writes and where, how long each took, and what it cost;
  - where results, checkpoints, logs and the bundle are in the bucket, and the layout of a run folder;
  - the frozen commit of each column;
  - every workaround still in force, each with the master fix that replaces it (D-number, train) or "none yet";
  - the watchdog, the checkpoints, the time budgets and the stop rules;
  - the spend log, launch by launch, with the running total;
  - the known traps:
    - the root file system growing only at boot;
    - the mail intake keeping one job per mail id;
    - the box keeping an approved ruleset version;
    - the weights mount after a reboot;
    - the kernel's limit on one command-line argument;
    - any others met;
  - what to run next, in order, with an estimate for each.
- **E3. Access for the integrator's session.** Document:
  - the exact Google Cloud roles it needs, on which project and resources;
  - which kind of credential lane G's own session uses and where it comes from;
  - the one-time steps the owner must take to give the integrator the same.

  Do not create, copy or share any key or token, and write none into the repository, a PR or a comment.
- **E4.** Post "done: hand-over" on #639, with links to D1, D3 and E2. From then on, start no launch and change nothing on either VM unless the integrator asks on #649. Stay reachable there for questions, and for C1 and C2 if the integrator asks for them to be run before it has access.

## What the owner expects back, and when

- Part A on #649 within the hour.
- A status line on #639 at the end of each of B4, B6 and B8, with the figures so far and the running total.
- Parts D1 to D3 as soon as part B ends.
- D4 before 12:30 UTC.
- Part E right after D3.
