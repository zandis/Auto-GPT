# 6. Go-live acceptance

**Reader:** Aimedics and the box owner, who sign the acceptance together.

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
8. `capacity --jobs night.json` (T-317a, D-730): one night of the site's own data, the jobs as the orchestrator lists
   them (`GET /jobs?limit=500`) saved as one JSON list. The night's chain (its ingest, then screen, nav and
   retention) must end `done` before the first morning notice (`TB_NOTICE_N1_AT`, 07:00 by default, in `TB_TZ`)
   with at least an hour to spare. `--night <name>` picks a night other than the newest.
9. `power-cycle --doctor doctor-after.json --audit-dir <audit copy>` (T-317a, D-730): during the planned power cut
   of §22, or a test of it before go-live. After the power comes back, run `trialbox doctor --json > doctor-after.json`:
   no FAIL, and the audit chain verifies.

Also run `make test-egress` (§1 of [Security](../SECURITY.md)) and keep the host check output.

**REDCap version per site** (DEP-026, D-393). The connector accepts REDCap 14, 15 and 16 (`SUPPORTED_MAJORS` in
`services/rc_bridge/client.py`) but has been tested only against the simulator (`rc_sim`). Before go-live, ask the
site's REDCap administrator for the version, or read it with the project's token (`content=version`, which the
bridge also reads at connect and refuses outside those majors with `RC-VERSION`), and record it here. Then run one
export and one import against the site's REDCap sandbox.

| Site | REDCap version | Read on | How |
| --- | --- | --- | --- |
| CGMH | not read yet | | ask the REDCap administrator (`content=version`) |
| Demo and CI | `rc_sim` (answers 16.x) | | the simulator |

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
