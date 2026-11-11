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

**REDCap version per site** (DEP-026, D-393). The connector accepts REDCap 14, 15 and 16 (`SUPPORTED_MAJORS` in
`services/rc_bridge/client.py`) but has been tested only against the simulator (`rc_sim`). Before go-live, ask the
site's REDCap administrator for the version, or read it with the project's token (`content=version`, which the
bridge also reads at connect and refuses outside those majors with `RC-VERSION`), and record it here. Then run one
export and one import against the site's REDCap sandbox.

| Site | REDCap version | Read on | How |
| --- | --- | --- | --- |
| CGMH | not read yet | | ask the REDCap administrator (`content=version`) |
| Demo and CI | `rc_sim` (answers 16.x) | | the simulator |
