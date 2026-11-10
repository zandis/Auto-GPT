# Committed goldens

The numbers the data core must keep producing from fixed synthetic and public inputs (T-006, D-205, TST-GOLD-01).
They are the merge gate for every branch that touches the adapter, the lake, OMOP, the code lists or an engine.

| File | What it pins |
| --- | --- |
| `funnels/<ruleset>@ci.json` | the FEAS funnel of the ruleset on every data set: start, remaining per step, unknowns, variants, the monthly first-eligible counts, the prevalent pool |
| `screen/<ruleset>@ci.candidates.json` | the SCREEN candidate set after the coded filters (S1): the pids, per criterion the met / not met / unknown counts, a hash of every patient's verdicts, evidence and reasons |
| `feas/basis@ci.json` | the FEAS basis table (coded, confirmed, proposed per step, D-135) and the unknown code systems (D-130) |
| `lake/tables@ci.json` | every lake table of every data set and the chunk table (text, tokens, sha): rows and a hash per column (a time-zone, deletes or chunking drift shows here first) |
| `lake/schema@<version>.json` | the lake schema: tables and columns, the chunk columns, `schema_sha` |
| `funnels/<ruleset>@50k.json` | the 50k numbers of a paid run, written only from its `report.json` with the run id in the file (after T-004) |

The data sets of profile `ci`: `synthetic-jp-a` and `synthetic-tw-a` (`tools.synth_hospital`, seed 42, 2,500
patients each, Asia/Tokyo and Asia/Taipei, with planted site inputs), `synthetic-jp-a-deletes` (the next night of
the JP site in the same lake with a tenth of its clinical records and half of its site inputs gone, and every 25th
remaining numeric result corrected: the OMOP store tombstones and updates them), `ssmix2-jp` (400 synthetic patients as SS-MIX2 storage, HL7 v2 through the JP Core
mapping) and `public-en` (the 53 SIGIR notes, a notes-only site). The site key is fixed, so the pseudonyms
are the same on every machine. No model, no network.

## Checking

    make goldens-check                          # both lake sources side by side, about 2.5 minutes; exit 0 / 1
    TB_LAKE_SOURCE=omop make goldens-check      # one source only (about 2.5 minutes; legacy about 2)

A difference prints, per file, the changed values by path (`synthetic-jp-a.remaining.GOUT-COH-INC-03: 372 -> 371`)
and a unified diff. Only `meta.head`, `meta.reason` and `meta.written_with_source` (and, at 50k, which run) are not
compared. Each run builds in a database prefix of its own (so no seeded `lake.source` flag can change its source,
and its clean-up drops only its own schemas). The check also verifies that the lakes came from the source in force: from OMOP, every store holds its
persons and the deletes set's store holds tombstones; flattened, no OMOP store was loaded.

## The regeneration rule

A golden changes only on purpose, in the pull request that moves the numbers, together with the decision that says
why:

    make goldens REASON="D-nnn: what changed and why the numbers move"

`--write` without a reason naming a decision is refused, and a golden whose content did not change keeps its file.
The reviewer reads the golden diff as part of the change. Never edit a golden by hand, and never regenerate one to
make a failing branch pass without that decision.

The 50k goldens come from run 5 and later paid runs only: `python -m tools.goldens --write --profile 50k
--from-report <report.json> --reason "D-nnn: ..."`; they are never generated locally.
