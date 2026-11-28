# Run ledger schema (bench/invest)

One run writes two fact tables, a timing table and a run header as Parquet, partitioned `run_id/<table>/protocol=<id>/`.
Analysis is DuckDB over those files (`ledger.connect(root, run_id)` gives a view per table), never a re-read of logs.
Real-data ledgers stay on the machine that holds the data; only `ledger_agg` output (below) leaves it.

## Reproducibility contract

- `run_id` is a hash of the run header (code sha, pins, snapshot sha, ruleset hashes, set ids): same inputs, same id.
- `row_key` is the sha256 of every other column of the row. A re-run on unchanged input writes the same rows.
- Rows are sorted, compression is fixed, no clock is written into a table. Two runs on the same input give the same
  sha256 per file (`MANIFEST.json` lists file, rows, sha256). The write time goes only to `run_clock.json`.
- Wall-clock figures (`ms_wall`, `ms_model`, `queue_depth`) are not reproducible, so they are a separate table,
  `match_timing`, joined on `row_key`. This differs from the first sketch, which had them in `match_stage`.
- Patient ids are salted hashes (`p-<16 hex>`) when a salt is given; the salt stays with the ledger.

## `match_stage`: one row per patient x protocol x criterion x stage x attempt

| column | content |
|---|---|
| row_key, run_id | content address; run id |
| pid, protocol_id, criterion_id | patient key; ruleset id; criterion id (empty on the patient-level `S0` and `tier` rows) |
| card_id, card_version | null until criteria carry cards (IR 3.1); the adapter reads them when present |
| canonical_hash | the criterion's canonical hash from the cascade |
| stage, attempt | `S0 S1 S1b S2 S2b S3 S4 S5 tier`; attempt 0 today |
| inputs_hash | hash of the stage's inputs (patient, protocol, criterion hash, stage, snapshot, evidence refs), not of its output |
| atoms_json | the criterion's IR atoms as compiled |
| sql_sha, cql_sha | sha of the ruleset's compiled SQL and of its CQL library (the whole ruleset, not split per criterion) |
| row_evidence_json | what the outcome kept: record refs for a coded answer, document refs and quote for a note answer |
| passages_json, passage_k, code_checks_json | null today (the cascade keeps only the chosen quote) |
| model_raw_json | the model call ids behind the answer; no raw text is kept by the cascade |
| verdict | `T F U not_applicable` (`pending_human` is `U` with `unknown_kind = pending_human`) |
| unknown_kind, reason_code, basis | `data_gap / uncertain / pending_human`; the product's reason code; `coded pair single person` |
| final, affirmed, opinions_json, confidence | the product's `CriterionVerdict` fields, read through `verdict_of` |
| gold, gold_quote_rank | a gold label when the set has one (`gold` argument), else null |

Row layout per protocol: one `S0` row per patient in the candidate list (`T` in scope, `F` out of scope with reason
`out_of_scope`), one row per active inclusion and exclusion criterion for each patient in scope (the outcome at the stage
that decided it; `not_applicable` / `not_evaluated` when the cascade stopped before it), one `tier` row per patient
(`reason_code` = the cascade tier, `final` = on the final list).

`match_adapter.reconcile` checks these against the cascade's own candidate list: S0 rows = traces, tier rows = traces,
criterion rows = in-scope patients x criteria, tier counts, final-list size, no duplicate row key.

## `match_timing`: `row_key, run_id, protocol_id, ms_wall, ms_model, queue_depth`

Filled by a runner that times its stages. The cascade does not time per row, so a dry run leaves it empty.

## `trial_stage`: one row per nct x line x stage

`row_key, run_id, nct, source, section_region, line_id (nct:line), line_text_sha, stage, inputs_hash, output_json,
model_raw_json, status (ok | CompileError | uncompiled_construct | no_card), reason_code, ms, gold`.
Stages: `region split atoms template card_proposal instantiate compile_sql compile_cql equivalence`.
`trial_adapter.add_records(writer, stage, records)` reads the JSONL records the trial-side tools already write (lines,
atoms, template assignments, card proposals, compile and equivalence results); it imports none of them.

## `run`: one row

`run_id, code_sha, bench_sha, model_pins_json, prompt_shas_json, schema_shas_json, terminology_sha, lake_snapshot_sha,
ruleset_hashes_json, sets_json, tz, run_date`
(the lake's time zone and the cascade's run date: both change which day a record falls on, so both are in the run id).

## What leaves a real-data machine: `ledger_agg`

Counts per (protocol, criterion, stage, verdict, reason code, unknown kind), per (family, reason code), the data-gap
matrix (unknown by reason code), latency quantiles per (protocol, stage). Every count below 10 is `null`.
`write_agg` raises `Refused` and writes nothing when a value is not a closed identifier (a quote or free text), is not
in the closed lists (stage, verdict, reason code, unknown kind) or the rulesets' own ids, contains a patient id (whole
or between separators), contains a day-level date (ISO, slashed, `YYYYMMDD`, `年月日`), or is a count below 10.
The product's counts-file writer is not built yet; these are the same refusals plus the small-cell rule. Not done:
secondary suppression (two tables that together difference a suppressed cell), cluster labels (the battery's job).

## Known gaps (the cascade does not keep them; adding them is a change to the cascade, outside this directory)

Lake rows behind a coded answer (values, units, dates), passage scores and ranks, per-check results, raw model text,
per-stage timing, per-criterion SQL and CQL shas, card ids.

## Run the dry run

    python -m bench.invest.dry_run --source <synthetic site dir> --work <dir> --out <ledger root> --tz <zone> --repeat

Ingests the site once, runs every live ruleset through the coded stages (no judge), writes the ledger, reconciles,
writes `ledger_agg.json`, and with `--repeat` runs it all again and compares the file hashes.
