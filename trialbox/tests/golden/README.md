# Committed goldens

The numbers the data core must keep producing from fixed synthetic and public inputs (T-006, D-205, TST-GOLD-01).
They are the merge gate for every branch that touches the adapter, the lake, OMOP, the code lists or an engine.

| File | What it pins |
| --- | --- |
| `funnels/<ruleset>@ci.json` | the FEAS funnel of the ruleset on every data set: start, remaining per step, unknowns, variants, the monthly first-eligible counts, the prevalent pool |
| `screen/<ruleset>@ci.candidates.json` | the SCREEN candidate set after the coded filters (S1): the pids, per criterion the met / not met / unknown counts, a hash of every patient's verdicts, evidence and reasons |
| `feas/basis@ci.json` | the FEAS basis table (coded, confirmed, proposed per step, D-135) and the unknown code systems (D-130) |
| `lake/tables@ci.json` | every lake table of every data set: rows and a hash per column (a time-zone or deletes drift shows here first); the chunk table `document_chunk` (text, tokens, sha) the same way; the schema version and sha each snapshot's `lake_meta` declares |
| `lake/schema@<version>.json` | the lake schema: tables and columns, the chunk columns, `schema_sha` |
| `funnels/<ruleset>@50k.json` | the 50k numbers of a paid run, written only from its `report.json` with the run id in the file (after T-004) |

The data sets of profile `ci`: `synthetic-jp-a` and `synthetic-tw-a` (`tools.synth_hospital`, seed 42, 2,500
patients each, Asia/Tokyo and Asia/Taipei, with planted site inputs), `synthetic-jp-a-deletes` (the next night of
the JP site in the same lake with a tenth of its clinical records and half of its site inputs gone and every seventh
remaining Observation and Condition corrected: the OMOP store tombstones and updates them),
`synthetic-jp-a-restored` (the night after, everything back as on the first night: the tombstones are lifted; lake
tables only), `ssmix2-jp` (400 synthetic patients as SS-MIX2 storage, HL7 v2 through the JP Core
mapping) and `public-en` (the 53 SIGIR notes, a notes-only site). The site key is fixed, so the pseudonyms
are the same on every machine. No model, no network.

## Checking

    make goldens-check                          # both lake sources; exit 0 identical, 1 different
    make goldens-check GOLDENS_SOURCE=omop      # one source (legacy or omop), while working on it

The gate is **both sources**: the data sets are generated once, then every lake is built from the flattened NDJSON
and from the OMOP store and each is compared with the same committed files. A branch that breaks only the OMOP
loader, the export or the tombstones cannot pass on the legacy lake alone. The run forces its source
(`lake.source.force`), so neither the `lake.source` flag nor `TB_LAKE_SOURCE` can make it build from another one,
and it works in database schemas of its own (also inside a `TB_DB_URL` that is already set), which are the only
ones it drops. `TZ=UTC` is set by the make target: the result must not depend on the machine's time zone.

A difference prints, per file, the changed values by path (`synthetic-jp-a.remaining.GOUT-COH-INC-03: 372 -> 371`)
and a unified diff. Only `meta.head`, `meta.reason` and `meta.written_with_source` (and, at 50k, which run) are not
compared. The check also verifies that each lake came from its source: from OMOP, every store holds its persons
and the deletes set's store holds tombstones; flattened, no OMOP store was loaded; and the lake's own
`source.jsonl` names the source.

## The regeneration rule

A golden changes only on purpose, in the pull request that moves the numbers, together with the decision that says
why:

    make goldens REASON="D-nnn: what changed and why the numbers move"

`--write` without a reason naming a decision that exists (`docs/decisions/D-nnn-*.md` or `docs/DECISIONS.md`) is
refused; both sources must agree before anything is written; a golden whose content did not change keeps its file,
and one that nothing computes any more (a ruleset removed, an old schema version) is deleted by the same command.
The reviewer reads the golden diff as part of the change. Never edit a golden by hand, and never regenerate one to
make a failing branch pass without that decision.

The 50k goldens come from run 5 and later paid runs only: `python -m tools.goldens --write --profile 50k
--from-report <report.json> --reason "D-nnn: ..."`; they are never generated locally.
