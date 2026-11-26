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
10. `key-escrow --secrets <the secrets folder> [--deploy deploy]` (INT-M5, R22-33, D-894): the box's KEK opens on new
    hardware. A TPM-sealed KEK (back end `file`) needs its escrow set (`python -m tools.keys escrow-shares`) on the
    newest signed ceremony record; no KEK, no set, a set of an older KEK or a record that does not list it is a FAIL,
    and `report` says NOT YET until this criterion has passed. On the host the secrets folder is the box's
    `tb-secrets` volume (`TB_SECRETS_HOST_DIR`). `trialbox doctor` shows the same as `key_escrow`, a WARN naming
    `[go-live gate key-escrow: open]`.

Also run `make test-egress` (§1 of [Security](../SECURITY.md)) and keep the host check output.

**Keys (IQ-05, D-893).** Keep the signed key ceremony record (`deploy/site/key-ceremony-<time>.md`, made by `python -m
tools.keys ceremony-record`, TB-SOP-03 in [security §10](../security/10-key-ceremony-and-escrow.md)) with the
acceptance; `trialbox doctor` (`key_ceremony`) shows it is there for the box's KEK. And one restore drill that
passed (`trialbox restore-drill`, §5, D-892).

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
