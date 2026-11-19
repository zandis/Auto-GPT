# Where an approval's seconds go: launch P3's records and a local stub run, 2026-11-19 (card H-41)

**Reader:** the integrator, and lane A2 (criteria-compiler's `/approve` route)

In launch P3 the sigir set ran 66 of its 104 protocols in its 7,200 s budget, and card H-36
(`p3-review-2026-11-17.md`) placed the extra time in APPROVE: about 41 s more per approval than on P2b on one stream
(30 s to 71 s), about 219 s per approval with three streams. H-36 did not say which step inside the approval costs
it: no record holds a step's time. This card says where the seconds go per protocol from the stored records, and
inside the approval from a local stub run, and names the fix. It builds none of it.

**The answer, in short.**

- **Per protocol (shown, P3 sigir, the 66 protocols run):** FEAS (the compile) median 42.0 s, APPROVE median 217.9 s,
  SCREEN median 6.2 s; APPROVE is 75 % of the 19,328 s of job time. On one stream (jmed, tcga) APPROVE is 71 s against
  9.5 s to 17.5 s for FEAS.
- **Inside the approval, on the stub run (shown, local):** 4.45 s per approval, of which 4.33 s (97 %) is
  `build_artifacts`, three cold JVM runs of the CQL-to-ELM translator. Every other step of `Compiler.approve` together
  is 0.12 s. `refresh_installed` costs about 30 µs per row of installed tables (0.25 s at 10,000 rows, 3.1 s at
  100,000). The FHIR load sends 6 resources, 1.90 MB, per approval; 1.54 MB of it is the two shared libraries
  (FHIRHelpers, TB_Common), the same bytes the compile loaded.
- **So most of the box's 71 s is not in the compiler's own steps (shown by elimination; the step is a hypothesis).**
  The compile pays the same translation and the same FHIR load, plus the model calls and the equivalence run, in 9.5 s
  to 17.5 s on one stream. That leaves at least about 53 s of each P3 approval in what a local run cannot reproduce:
  the FHIR server's handling of the load, the audit journal, the rulesets volume, and the orchestrator's part of the
  job. Which of them is in no record.
- **The fix (named, not built):** lane A2, size S, record each step's seconds of `Compiler.approve` (and of the
  orchestrator's APPROVE scenario around it) in the APPROVE job's metrics, so the next launch's `box-calls.log` names
  the step; and, size S, skip the second translation and the second load of the unchanged shared libraries when the
  review changed nothing. Section 4 sizes both.

## The records and the commands

Launch P3 is run `box-20261117T153147Z-15108f46` (branch `integrator/p3-artefacts` at `7b2d96a8`, folder
`trialbox/.p3-artefacts/`); launch P2b is `box-20261117T073759Z-57263236` (`integrator/p2b-artefacts` at `2bcf5ca9`).
Both were read with `git archive` into a scratch folder outside the repository; nothing from them is copied here
beyond the figures quoted. The data is public: SIGIR 2016 (NCBI TrialGPT), JMED-Personas (CC BY 4.0), TCGA-Reports
(CC BY 4.0). The stub run uses the synthetic GZQO fixture protocol, the repository's stub model in process, no GPU,
no network.

From `trialbox/` (`P2B`, `P3` the two artefact folders):

```
# (1) per protocol, per stage: H-36's tool, read again on P3
python -m tools.public_accuracy.timing P2B/sigir.tgz P3/sigir.tgz --json timing-sigir.json
python - <<'PY'
import json, statistics as st
rows = [r["after"] for r in json.load(open("timing-sigir.json"))["rows"] if (r.get("after") or {}).get("wall")]
for k in ("FEAS", "APPROVE", "SCREEN"):
    xs = [r["wall"][k] for r in rows if k in r["wall"]]
    print(k, len(xs), round(sum(xs)), round(st.median(xs), 1), round(min(xs), 1), round(max(xs), 1))
PY
# (2) one stream: each job's own wall time, jmed and tcga (tar -xzf P3/jmed.tgz into an empty folder first)
grep '^{"job"' work/box-calls.log | grep '"metrics"' | python -c 'import json,sys; [print(j["type"], j["metrics"]["wall_seconds"]) for j in map(json.loads, sys.stdin)]'
# (3) inside the approval: the stub run (needs `make jvm-deps` once for the real translator)
python -m tools.public_accuracy.approve_profile --runs 3 --top 12 --json approve-profile.json
python -m tools.public_accuracy.approve_profile --runs 3 --site-list-rows 10000 --json approve-profile-10000.json
python -m tools.public_accuracy.approve_profile --runs 3 --site-list-rows 100000 --json approve-profile-100000.json
```

`tools.public_accuracy.approve_profile` is new (this card; its test is
`tests/unit/test_h41_approve_profile_2026_11_19.py`). It compiles the protocol, then approves it from the review
workbook as sent (the launch driver mails it back unchanged), each approval on a fresh copy of the compiled
repository, with a timer around each step of `Compiler.approve`. A recording stand-in takes the FHIR load: it
counts the resources and bytes and sends nothing.

## 1. Per protocol, from the records (shown)

P3 sigir, the 66 protocols run, three streams (command 1; each job's `metrics.wall_seconds`):

| Stage | Jobs | Sum (s) | Median (s) | Min (s) | Max (s) |
|---|--:|--:|--:|--:|--:|
| FEAS (the compile, with its model calls) | 66 | 4,330 | 42.0 | 14.9 | 495.5 |
| APPROVE | 66 | 14,442 | 217.9 | 76.2 | 316.3 |
| SCREEN | 66 | 557 | 6.2 | 0.6 | 38.8 |

One stream, each job alone (command 2):

| Set | Launch | FEAS (s) | APPROVE (s) | SCREEN (s) |
|---|---|---|---|---|
| jmed | P2b | 13.5, 8.3 | 30.4, 29.4 | 1.6, 1.5 |
| jmed | P3 | 17.5, 11.8 | 71.6, 70.8 | 1.5, 1.6 |
| tcga | P2b | 8.5 | 29.7 | 323.8 |
| tcga | P3 | 9.5 | 71.3 | 119.7 |

- **Compile is not separable from FEAS in the records.** The FEAS job is the compile; its model calls are in the
  traces with their end times only, and the job's start is not recorded. The stub run's compile of a 23-criterion
  protocol is 4.3 s to 5.6 s here, with the stub model.
- **APPROVE calls no model** (`metrics.llm_calls` 0 on every APPROVE job, H-36), so the traces hold nothing of it.
- **The approval's time is near constant alone**: 70.8 s to 71.6 s on P3 for protocols of 1 and 2 criteria, 29.4 s to
  30.4 s on P2b. A constant that does not follow the protocol's size points at a fixed cost per approval.

## 2. Inside the approval, from the stub run (shown, local)

Command 3, three approvals of GZQO (23 criteria), the real CQL-to-ELM translator (JVM), mean seconds per approval:

| Step of `Compiler.approve` | s per approval |
|---|--:|
| `build_artifacts` (CQL generation, CQL-to-ELM translation) | 4.327 |
| `ai.confirmed` records (one per criterion with model calls, 23) | 0.033 |
| repository: promote, draft read, write, read, tag | 0.064 |
| files | 0.010 |
| audit records (`approve.done`) | 0.002 |
| `refresh_installed` (installed folder empty) | 0.0002 |
| `stamp_differs`, `site_list_blocks`, equivalence enforce, flag | < 0.001 |
| other (the rest of `approve`) | 0.016 |
| **approve, total** | **4.452** |

- **Which calls (`--top`):** `translator.translate` runs `subprocess.run` 3 times per approval (9 over 3 approvals),
  one cold JVM each for FHIRHelpers, TB_Common and the ruleset's library, about 1.4 s each; the process waits in
  `select.poll` for 4.30 s of the 4.45 s. `provenance.confirmed` writes 23 audit lines (69 over 3 approvals).
- **Which queries:** none to the lake or a model. The equivalence gate does not run again when nothing was rejected
  or edited: the approval reads the compile's report (`equivalence enforce`, under 1 ms).
- **The FHIR load (recorded, not sent):** 1 load per approval, 6 resources, 1,901,864 bytes: Library/FHIRHelpers
  1,201,946 bytes, the ruleset's library 363,497, Library/TB_Common 335,368, and 3 value sets of under 400 bytes each.
  The compile loaded the same two shared libraries, byte for byte, before the equivalence run.
- **`refresh_installed` against the installed tables' size:** 0.0002 s with none, 0.252 s with a made-up 10,000-row
  site list, 3.081 s with 100,000 rows (about 30 µs per row: every table is read, hashed and parsed again on each
  approval). The compiler on P3 mounts `/data/terminology` (added to `deploy/docker-compose.yml` between `57263236` and
  `15108f46`, D-991); what the launch box held there is not in the stored sets. The compile calls the same refresh, and
  FEAS on one stream grew only 1 s to 4 s (H-36), so it is not the 41 s unless the box's tables differ between the two.

## 3. What the stub run cannot say, and the elimination

- **Not reproduced here:** the FHIR server's time to take the load (no server; no Docker daemon in this container),
  the audit journal (`DbAuditWriter`, one connection behind one lock per process: the local run writes a file), the
  box's rulesets volume, the orchestrator's part of the APPROVE job (`parse_review_xlsx`, `ctx.publish` of the
  manifest with its two audit records, `resume_awaiting`), and approvals waiting on each other (one at a time here).
- **The elimination (shown on the records, the step a hypothesis).** The compile on the box runs the same
  `build_artifacts` (three translations) and the same FHIR load of the shared libraries, then the equivalence run on
  the FHIR server, plus its model calls: 9.5 s to 17.5 s per FEAS job alone on P3. The approval does the translation
  and the load once more, without the model or the equivalence run, and takes 71 s. So at least about 53 s of each P3
  approval (70.8 s, the shortest, less 17.5 s, the slowest FEAS) is in steps the compile does not share: the approval's audit records
  (`ai.confirmed` per criterion, new in `15108f46`, D-989 step 2b; `approve.done`), the repository's write, tag and
  promotion, and the orchestrator's part. On P2b the same reasoning leaves at least about 16 s (29.4 s less 13.5 s). Which one is in no
  record; the stub run times the compiler's share of them at under 0.12 s on a local disk.
- **Three streams:** an approval took 219 s on average against 71 s alone (H-36). One process-wide audit lock and the
  repository's single working tree are both places approvals would queue; neither is measured.

## 4. The fix, named and sized (not built)

| # | What | Owner | Size | Files | What it saves |
|---|---|---|---|---|---|
| 1 | Record each step's seconds of `Compiler.approve` (the steps of section 2) in `ApproveResult`, and the orchestrator's own steps around it, in the APPROVE job's `metrics` | lane A2 | S | `services/criteria_compiler/service.py`, `services/orchestrator/scenarios/approve.py`, their tests | Nothing by itself; it names the step that costs the ≥ 53 s on the next launch, which no offline run can |
| 2 | When the review changed nothing (no edit, no reject), reuse the compile's ELM from the draft branch instead of translating again, and load to the FHIR server only the ruleset's library and value sets, not FHIRHelpers and TB_Common unchanged | lane A2 | S | `services/criteria_compiler/service.py` (`approve`, `build_artifacts`), its tests | 3 JVM runs and 1.54 MB per approval: 4.3 s of 4.45 s locally; on the box at most what the compile pays for the same work (under 17.5 s alone) |
| 3 | Read the installed tables again only when their manifest changed (compare the manifest's sha256 lines before re-reading) | lane E | S | `services/criteria_compiler/terminology/mapper.py`, `installed.py`, their tests | About 30 µs per installed row per compile and per approval; 0 when nothing is installed |

Item 1 first: items 2 and 3 are real savings, measured here, but together they are bounded well below the 53 s the
elimination leaves, and the 41 s added between P2b and P3 is in neither of them on a local disk. Until item 1 lands, a
sigir launch on three streams needs about 104 s per protocol (H-36), 10,800 s for 104.

## Not shown

- Which step on the box costs the ≥ 53 s per approval (no record holds a step's time; the stub run cannot reproduce
  the FHIR server, the journal or the box's volumes).
- What the P3 box held in `/data/terminology`.
- Whether approvals wait on each other in the compiler, and where.
- The FHIR server's time for the 1.9 MB load.

## Findings

The page's three findings (H41-01 to H41-03) are in `approve-profile-2026-11-19/findings.json`, in the form
`python -m tools.findings_register --add-from` reads. They are not rows of the register; lane V adds them.
