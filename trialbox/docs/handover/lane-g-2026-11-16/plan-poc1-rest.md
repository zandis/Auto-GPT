# PoC-1: plan for the rest of step 1 (evidence), with gates

Written 2026-11-15 by the lead, on the owner's order: plan carefully; after the
checkpointed probes, improve automatically, review, and if all is set, run the
whole plan without stopping to ask.

Evidence commit (frozen): 1157c9bf (master as of train 28 merged into lane G's
run tooling). No merge of master until the evidence page is written.

Money (D-505): limit US$150. Spent about US$74.0 before phase A.
Reserve, never spent by this plan: US$15 (Tuesday's demo VM and a margin).
So this plan may spend at most US$61 in all, across every phase below.
Spot price US$2.74 per VM hour. Every launch's estimate and the running total
go on #639 before it starts. A launch more than half over its estimate stops.

## Phase A: checkpoints (no cost)

Build into every long step (start, qualify, each accuracy set):
- a console line and a packed partial in the bucket at least every 60 s:
  step, elapsed, current gate or set, item n of N, model calls since the step
  began (gateway audit), calls per minute, slowest call in flight and its age,
  GPU use;
- a stop of any kind leaves the last checkpoint and every finished item;
- per-call timeout and the cause of any call over 60 s (queue, timeout,
  retry, refusal) recorded.
Rehearse once locally: a step killed mid-way must leave its checkpoints.
Push. Gate A: rehearsal passes and the partial is in the fake bucket.

## Phase B: probes (one launch, about 25 minutes, about US$1.15)

On the running 1157c9bf stack:
- qualify for 5 minutes at full documented sizes, then stop cleanly;
- accuracy for 5 minutes on jmed, then stop cleanly.
Collect, stop the VM, verify TERMINATED.

## Gate B: review the probes (no cost)

Answer from the numbers, in the log:
1. Did the checkpoints appear every minute, and did the partials survive the
   stop? If not: fix, rehearse, rerun phase B once.
2. Calls per minute, latency median / p95 / max, for short and long prompts.
3. Any call over 60 s, and its cause.
4. Any refusal (tripwire, limits, mail, routing), and its cause.
5. Do the first jmed rows score sanely against the gold (no all-empty, no
   all-unknown, no impossible counts)?
6. From 2: expected time for full qualify and for each accuracy set.

Automatic improvement, before the next launch:
- a fault in lane G's tooling: fix it, rehearse, push;
- a stall caused by too much in flight or by long prompts: lower the
  concurrency or set a per-call timeout, using a product setting if one
  exists; record the choice;
- a fault in product code: post `red:` on #639 with file:line, labelled
  "not demo", skip the path it blocks, and go on;
- scoring that looks wrong: stop, trace it on the stand-in locally, fix,
  and do not spend VM time until it scores a known tiny case right.

Go on to phase C only when all six answers are recorded and nothing in 1, 3,
4 or 5 is unexplained. Otherwise fix and repeat phase B once. If phase B fails
twice, stop and report to the lead.

## Phase C: the full run (one launch, sized to fit)

Budget for phase C: US$61 minus what A and B spent, minus US$2 margin.
From gate B's speeds, size the run to fit that budget:
1. Accuracy sets, cheapest first: jmed, tcga, chia, jrct, sigir, trec2023,
   tfda. Each set has its own time budget from the measured speed and is
   stopped at 1.5 times its estimate, keeping what it finished.
   If the full sizes do not fit, shrink every set by the same proportion and
   record the sizes.
2. Qualify after the accuracy sets, only if at least 40 minutes of budget
   remain: reduced sizes (--items 60 --repeat-items 40), sizes recorded.
3. Raw answers kept in the bucket and the run folder; never committed.
Collect each set as it finishes. Stop the VM, verify TERMINATED.

## Gate C: review the results (no cost)

For each set: counts add up, intervals computed, refusals counted, the figure
plausible against what the set is known to contain. A set that fails this
check is reported as "not scored, because", never shown as a figure.

## Phase D: write-up (no cost)

1. docs/plan/measurements/poc-1-evidence.md: the commit, the models (registry
   aliases and manifest hashes), served prompt versions, chat-template hash,
   G-1 and canary results, each set's figure with its count and interval,
   qualify's gates if run, what was skipped and why, how this setup differs
   from a hospital install, every fault in one table, and the cost against
   every estimate.
2. Fill the demo walkthrough's closing table from the page.
3. Post train-ready for #628, then #649.
4. Final report on #639, in the five parts the integrator asked for.

## Stop rules (any of these stops the plan and reports to the lead)

- the running total would pass US$135 (US$150 minus the reserve);
- phase B fails twice;
- a product fault blocks every accuracy set;
- anything would touch a secret, real patient data, or the demo VM.
