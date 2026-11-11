# 4. Troubleshooting

| Symptom | Check | Fix |
| --- | --- | --- |
| No reply to a mail | `docker compose logs mail-gateway --since 1h` | sender not allowed, SPF/DKIM failed, or the rate limit; the log says which (no PHI) |
| "Today's limit is reached" on the console | `settings.yaml`: `rate_limit_per_sender_per_day`, `rate_limits_per_day` | the limit counts each heavy run type (FEAS, SCREEN, COHORT, NAV, MICROBATCH, CALIBRATION) per sender per 24 h; raise it, or set `rate_limits_per_day: {SCREEN: 40}` (0 = no limit) and restart the orchestrator (D-146) |
| "Ruleset X has no approved version" | `git -C /data/rulesets tag` | paste the protocol, then the investigator approves on S20 |
| Ingest `passed: false` | `ingest_report.json` → `errors` | the hospital changed its export: run `mapping_check.py`, fix the site mapping |
| Equivalence gate under 98 % | the review sheet "equivalence" | edit or reject the flagged criteria |
| SUBMIT refused | the reply names the check | NAV older than 14 days: rerun NAV |
| Lake slow or out of memory | `docker stats` | raise `TB_LAKE_MEMORY_LIMIT` (default 40 % of RAM; spills to `/data/lake/tmp`) |
| A job fails with `LAKE-LIMIT` | the job's error; `df -h /data` | the query hit its spill cap (`TB_LAKE_MAX_TEMP`, default a quarter of the free disk, at most 50 GB; `TB_LAKE_TEMP_DIR` moves the spill) and was stopped before it filled the disk. Usually a join that multiplies rows: report it; raise the cap only for data that really is that large |
| A job fails with `LAKE-STALE` | the job's error; `trialbox doctor`; the adapter's last runs | the newest lake snapshot is older than `TB_LAKE_MAX_SNAPSHOT_AGE_DAYS` (3 in the production compose file; 0 turns the check off) before the job's run date, so the nightly ingest has not published for days (D-383). Fix the ingest and let a night publish, then run the job again; raise the limit only when a gap in the feed is known and accepted |
| Containers lost egress after a restart | `deploy/network.sh status` | `deploy/network.sh apply` |
| `CERTIFICATE_VERIFY_FAILED` | hospital TLS inspection | put the hospital CA on the host, set `TB_EXTRA_CA=/abs/path/ca.pem` in `deploy/.env`, `docker compose up -d` |
| Many patients "need information" with "a result is in a unit that cannot be compared" | the lab's unit in the feed against the criterion's unit (`mapping_check.py`; `unit_defaults` in the site mapping) | declare the site's unit for that analyte, or ask the vendor for a tested factor (D-275); the patients are never excluded for it |
| Many orders or results read as unknown after an ingest | `mapping_check.py` lists status codes outside the map; the lake's `medication.status` = `unknown` | the HIS sends a status code the site mapping does not know: add it to the `status` / `result_status` map (an unknown code never counts as given or as final; D-275) |
| Many patients "need information" with "a medicine order has no end date" | the feed's order rows: no end date, or no date at all | map the order's end (or days of supply) in the site mapping (D-275) |
| Notes never exclude | `selftest.failed` in the audit, the admin health tile | the pair canary failed: check the models (§8, §10) |
| Notes never exclude; the run says "the verifier is not a second model" | `llm.pair.same_model` in the audit, `trialbox doctor` (`note_block` FAIL) | the verifier is the judge again (the same model name, alias, build or weights), or its endpoint does not say which weights it serves (`/models`). A note answer needs two different models (D-276): name a different verifier (`TB_GATEWAY_VERIFIER_MODEL`, or `LLM_VERIFIER_BASE_URL` with its own `LLM_VERIFIER_MODEL`), or set `TB_NOTE_BLOCK=never` on purpose |
| A screening run fails "the model did not answer"; rows say "not checked (system busy)" | the gateway log (`upstream_failed` on a judge call), `llm.gateway.call` with `fallbacks` | the judge's server is down or erroring. A judge call is never answered by the verifier build instead (D-276, LLM-002): bring the judge back, then send the request again |
| A tool imports the wrong code | the venv has another checkout installed | set `PYTHONPATH=libs:services:.` (the Makefile does) |
| Test ports taken | | `TB_HOST_<NAME>_PORT` in `deploy/.env` |

A failed job names its step (received, parsing, compiling, running, reporting) and the requester gets a plain
"Failed" mail.
