# D-1050 The ingest report times each connector per message

- **Task:** plan 10 card 10E-9 (Track E; review 13-10). It is proved by the measurement run S-8.
- **PR:** this branch (`agent/10E-9-ingest-report-per-connector`)
- **Date:** 2026-11-19
- **Status:** proposed (merges on green CI)
- **Builds on:** SPEC 4.6 (the ingest report), T-692 (rows to disk as they are read)

## Decision

1. **The report gains `connector`** (`ingest_report.json`, schema 1.6.0, `ConnectorReport`). It gives the source kind, then the messages, seconds and 95th percentile per message, both for the whole source and per table (`TableReadTimes`), each with its histogram.
   - **A message** is what the connector hands the night one at a time: a CSV or SQL row, an SS-MIX2 message, or a FHIR resource. A FHIR bulk night's tables are its resource types.
   - **The time is the connector's own.** `adapter.read_timing.ReadTimes.timed` wraps the connector's iterator and times only the step that produces each message (reading and parsing), never the mapping that runs after it.
   - **The histogram has fixed buckets,** from 0.05 to 2500 ms and then above, so the memory is the same for ten messages and ten million. The 95th percentile is the upper bound of the bucket the 95th-percentile message falls in, so it never understates. Above the last bound it is null, and the last bucket shows it.
   - **Counts and times only.** No value of a row is kept: the section's keys are fixed, and a test checks them.
   - The registry's table, read from another source, is timed under its table name like the others.
2. **`tools/bench.py --tasks ingest` prints the connector's line:** messages, seconds, p95, and the three slowest tables. It is S-8's reading, once per source type.
3. **Runbook 04** says where to look when the night's read is slow.

## Not in this card

- **The S-8 run itself** (`--ingest-patients 20000` once per source type: CSV, SS-MIX2, FHIR files) is a measurement for whoever runs the free series S-1 to S-8. This card gives it the numbers to record.
- **The bench reads CSV today.** An SS-MIX2 or FHIR-files source in the bench is part of that run.
