# 6. Go-live acceptance

`tools/acceptance.py` writes one result per criterion under `acceptance/`; `tools/acceptance.py report` sums them.

1. `ingest --report <ingest_report.json>`
2. `feas --system <FEAS raw json> --manual manual_counts.csv` (the CRC's own funnel)
3. `screen-sample --candidates <candidates.json> --ruleset rulesets/<ID> --scoped scoped.txt --n 120` makes the
   blinded `adjudication.xlsx`; when the CRC has filled it: `screen --candidates … --adjudication adjudication.xlsx
   --key adjudication_key.json`
4. `nav --lake <lake> --ruleset rulesets/RA-BIO` (12 months against NHI outcomes)
5. `twpas twpas_validation_*.json`
6. `reproduce --results rerun.jsonl`, after `docker compose exec orchestrator python -m orchestrator.rerun <job ids>
   > rerun.jsonl`
7. `audit --dir <audit copy>`

Also run `make test-egress` (§1 of [Security](../SECURITY.md)) and keep the host check output.

## 6.1 The lake from OMOP: the flip (T-202, D-384)

The screening lake is built from the NDJSON (`legacy`) until the `lake.source` flag says `omop`. CI builds the goldens
and `e2e_simple` from both sources on every pull request. On the acceptance box the flip is done once, before G3:

1. Run the parity test on the box: `python -m tools.omop_parity --json acceptance/omop_parity.json`. It must print
   `IDENTICAL`. Attach `acceptance/omop_parity.json` to the release record.
2. Flip: `python -m tools.omop_parity flip acceptance/omop_parity.json --actor ops:<your name>`. It refuses a report
   that is not `IDENTICAL` or compared nothing. Otherwise it sets `lake.source` to `omop` as an audited flag change
   whose reason holds the report's sha256 (seen on `/ops/flags` and as a `flag.set` audit event).
3. The next lake rebuild (the next night, or a site publish) builds from OMOP; a rebuild or job already running keeps
   its source. `<lake>/source.jsonl` names the source of every snapshot.
4. To go back, set `lake.source` to `legacy` on `/ops/flags` with a reason. Nothing in the OMOP store is lost.

An older snapshot can be exported from OMOP as it stood at a time: `omop.export.export_rows(db, as_of=<aware time>)`.
It changes nothing in the store. Changes made before migration 6 have no record before-image; an export as of a time
before them is refused.
