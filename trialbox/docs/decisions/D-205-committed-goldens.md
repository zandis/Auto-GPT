**D-205 Committed goldens: the merge gate for every data-core branch (T-006, WS-03.1, TST-GOLD-01).**
Task T-006 of `docs/reviews/2026-11-09-assessment-and-tasks.md`; branch `wave0-goldens`; pull request: opened by
the integrator. Numbered by the coordinator's note in that document (cards take D-200 upward in card order, so T-006
is D-205; the card's own "D-194" is superseded by the note). Holistic contradiction C-17, plan WS-03.1. Built
2026-11-09, synthetic and public data only, no model, no network, no cloud.

* **What is pinned** (`tests/golden/`, JSON sorted by key). Per committed ruleset (the five of `rulesets/` and the
  two open-data ones): the FEAS funnel (`funnels/<ruleset>@ci.json`: start, remaining per step, unknowns, variants,
  first-eligible months, the prevalent pool and a hash of its pids) and the SCREEN candidate set after the coded
  filters (`screen/<ruleset>@ci.candidates.json`: S1 as `structured_candidate` decides it, the pids, per criterion
  the met / not met / unknown counts and a hash of every patient's verdicts, evidence and reasons). The FEAS basis
  table and the unknown code systems (`feas/basis@ci.json`, D-135, D-130). Every lake table of every data set, rows
  and a hash per column (`lake/tables@ci.json`). The lake schema (`lake/schema@2.json`: `SCHEMAS`, the chunk columns,
  `schema_sha`). 17 files, 236 KB.
* **The data sets** (profile `ci`, about 5,450 patients). `synthetic-jp-a` and `synthetic-tw-a`: the synthetic
  hospital of `tools.synth_hospital` (profile `ci`, seed 42; CSV feeds, Asia/Tokyo and Asia/Taipei) with the planted
  site inputs of `tools.omop_parity` (proposed, confirmed, suspected and refuted diagnoses; a birth-date conflict).
  `synthetic-jp-a-deletes`: the next night of the JP site rebuilt into the same lake with every tenth clinical record
  and every second site input gone, so the OMOP store tombstones them (the check verifies it did). `ssmix2-jp`: 400
  synthetic patients written as SS-MIX2 standardized and extended storage (`tools.ssmix2_export`) and read through
  the JP Core mapping. `public-en`: the 53 SIGIR notes of `tools.public_site` (a notes-only site; never MedTxt, whose
  presence depends on a fetch). One golden per source kind (CSV feed, site inputs, deletes, HL7 v2 storage, public
  text) and both time zones, as the review asked. The site key is a fixed synthetic constant, so the pseudonyms and
  every pid hash are the same on every machine.
* **One set of goldens for both lake sources.** The goldens do not say which source wrote them (only
  `meta.written_with_source`, not compared): `make goldens-check` and `TB_LAKE_SOURCE=omop make goldens-check` must
  both pass, so the OMOP parity of D-151 is now a committed golden, tombstones included. The check also verifies the
  lakes came from the source in force (from OMOP, every lake's store holds its persons and the deletes set's store
  holds tombstones; flattened, no OMOP store was loaded), so a flag that silently does nothing cannot pass it.
* **The rule.** `tools/goldens.py --check` exits 0 or 1 and prints, per file, the changed values by path and a
  unified diff; only `meta.head`, `meta.reason` and `meta.written_with_source` (and, at 50k, the run id) are not
  compared, so a ruleset version, the seed or the lake schema version moving fails it too. A deliberate change
  regenerates the goldens in the same pull request (`make goldens REASON="D-nnn: ..."`); `--write` without a reason
  naming a decision is refused, and an unchanged golden keeps its file. The 50k goldens are written only from a paid
  run's `report.json` (`--profile 50k --from-report`, refused for fewer than 50,000 patients or no run id), never
  generated locally: they follow run 5 (T-004) as a separate commit.
* **In every `make test`** (`tests/unit/test_goldens.py`, 23 tests): the comparison passes on identical, fails on one
  count with the criterion named, on a missing ruleset, a ruleset without a golden, a `schema_sha` change, a new
  schema version, a column drift and a changed candidate; `--write` without a reason is refused; the 50k path; and
  two live checks that need no build (the lake schema golden equals the code, and every committed ruleset has its
  funnel and candidate goldens at its current version).

*Evidence.* `make goldens-check` IDENTICAL from both sources in 2 min 19 s (legacy 115 s and omop 139 s, side by side).
Acceptance (2): removing the one row `('VS_URATE_LOWERING_THERAPY', 'http://www.whocc.no/atc', 'M04AA03')` from the
approved `rulesets/GOUT-COH/sql/GOUT-COH.sql` fails the check (exit 1) on `funnels/GOUT-COH@ci.json`,
`screen/GOUT-COH@ci.candidates.json` and `feas/basis@ci.json`, with lines such as
`sets.synthetic-jp-a.remaining.GOUT-COH-INC-03: 372 -> 263` and `sets.synthetic-jp-a.verdicts.GOUT-COH-INC-03.met:
521 -> 363`. A finding on the way: the same row removed from `valuesets/VS_URATE_LOWERING_THERAPY.json` instead
changes no number, because the screening SQL carries its own copy of the value sets; the goldens pin what screens,
and the duplication is a question for the compiler's owner, not this card.

*Not done.* The CI job (T-007 owns `.github/workflows/*`; the `goldens-check` target is ready for it). The 50k files
(after T-004). The MIMIC demo is not a golden data set: it needs a fetch, and a golden must not depend on what a
machine has downloaded.

*Fable adversarial review (2026-11-09, a fresh session on the branch diff), and what changed.* No Blocker.
**H2** (a seeded `lake.source` flag in the caller's database would decide the source of the goldens' lakes) and
**H4** (the clean-up dropped every schema under the caller's `tb_prefix`, all of them with an empty prefix): each
run now builds in a prefix of its own (`private_url`, derived from the work directory and appended to the caller's
URL), refuses to build if that prefix holds a `lake.source` flag, sets `TB_LAKE_SOURCE` itself, checks that the
rebuild used the source asked for, and never drops an empty prefix. **H3** (the default gate never exercised OMOP):
`make goldens-check` now checks both sources side by side in two processes (2 min 19 s on this 4-core machine);
`TB_LAKE_SOURCE=omop|legacy` checks one. **M1** (the reported source came from the variable): it is the rebuild's
own (`rebuild_source`), and `TB_OMOP_DB_URL` points at the private prefix during the run. **M7** (width): the chunk
table (text, tokens, sha) is hashed too, and the next night also corrects every 25th remaining numeric result in
place, so OMOP's update path is pinned beside its tombstones. Not changed: the H2 risk in `tools/omop_parity.py`
itself (a parity run against a database where a console has seeded the flag compares one source with itself); that
file is outside this card, so it is handed to the integrator with the fix (a private prefix, or assert that the OMOP
store holds persons, as `tools/goldens.py` does). Lows: `SEED` is the generator's own default (42) and recorded, not
passed (`omop_parity.synthetic` takes no seed); `--write` does not delete the golden of a removed ruleset (the check
then fails naming it, which is the intended signal); `REASON_RE` checks the form `D-nnn` only.
