**D-271 The data pipeline never promotes nothing, never launders a held night, and the OMOP parity tool proves
something or fails (review DI-3, DI-7, DI-8; register CR-051, CR-052, CR-053).**

* DI-7, empty or broken input. `tb_common.feedguard`: one night may not remove all records of a kind, or more than
  `TB_FEED_MAX_DROP_PCT` (default 20, 0 to 100; a bad value is a refusal, not a crash) % of them when that is more
  than 5 records. Static rows the mapping writes every night (`Organization`, `Practitioner`, `Location`) never count
  as data. `TB_FEED_DROP_OVERRIDE='<snapshot>: <reason>'` lets that one night through; an override naming another
  night, or none, does nothing; the reason is recorded (ingest audit `drop_override`, `tb_load.counts.override`).
  The check runs in three places:
  * the adapter (`run_ingest`): the new snapshot's records per resource type against the last promoted snapshot; a
    night over the limit is held;
  * `Lake.rebuild`: once a lake has held a feed (`FEED` marker, an NDJSON folder, a recorded source, or a snapshot
    not marked `.siteonly`, so lakes from before this change count as fed), a missing folder, one with no patient or
    clinical record, or one that drops too much of `CURRENT`'s records is refused (`RebuildError`) before anything
    is written. A lake that never had a feed (the practice site, a box before its first night) is built from the
    site's inputs alone; the practice site passes `allow_empty`. A rebuild from a folder other than
    `ndjson/<snapshot>` records it (`db/<snapshot>.duckdb.source`), so "Publish" on a lake built by `dataplat`
    reads the same NDJSON again;
  * `omop.load`: a `feed` batch, against the live records of every CDM table (not persons only). A refusal loads
    nothing and leaves a `feed-refused` row in `tb_load`.
  The lake service answers 409 with the reason for a `RebuildError` or an `OmopError`. The adapter's HTTP client puts
  that reason in the ingest report, and a refusal holds the night.
* DI-8, held nights. A night that passes writes `passed.json` in its NDJSON folder. A delta night merges over the
  newest earlier folder that passed, or `CURRENT` for folders written before the marker
  (`adapter.pipeline.merge_base`), never over a held night's folder; the fhir-store sync diffs against the same base.
  A delta night with no promoted base while the lake has earlier folders or a `CURRENT` is held ("run a full load").
  A re-run of a promoted night (its folder has `passed.json`, or `CURRENT` names it) is written to
  `ndjson-rerun/<snapshot>` and moved into place only when it passes; a held re-run stays there for the steward and
  never touches the NDJSON that `CURRENT` was built from.
* DI-3, `tools/omop_parity.py`. Each run mints a random prefix `par<8 hex>_` (never the caller's; validated; URLs
  built with `urlencode`), runs the ingest, the flag reads and the OMOP stores under it (`TB_DB_URL` set to it
  inside the run and put back as it was after), and drops only the schemas that appeared under that prefix during the
  run, also when the run fails (a clean-up error is added as a note, never in place of the run's own error). A run
  fails (not IDENTICAL, exit 1) when the OMOP store has no person, the legacy lake no patient, the two counts differ,
  no ruleset ran or a ruleset evaluated nobody, no data set was compared, or a data set was skipped (unless
  `--allow-skip`).

*Tests.* `tests/unit/test_dataflow_lake_p0.py`: empty or missing folder refused and `CURRENT` kept; 409 from the lake
service; night 1 promoted, night 2 held, night 3 good delta, night 2's row not in `CURRENT`; `merge_base`; a delta
with no promoted base is held; an empty export (static rows only) is held; a night dropping 6 of 10 diagnoses needs an
override naming it; a held re-run of the `CURRENT` night reaches neither the next delta nor a Publish; a passing
re-run replaces the night; a delta on a lake with `CURRENT` and no NDJSON is held; a lake from before the marker
counts as fed; a lake refusal holds the night with its reason, and an OMOP refusal is a 409.
`tests/unit/test_omop_core.py`: a parity run writes and drops only its own schemas (passing and failing run, the
caller's schema and `TB_DB_URL` kept); parity over nothing fails; a feed batch that would tombstone the whole feed or a
third of it is refused, recorded, and passes only with an override naming it; a feed with patients but no conditions
or observations is refused; a bad threshold is a refusal; the threshold rule; an OMOP rebuild from a missing folder
leaves the store and `CURRENT`. Changed: the old parity test that expected the caller's prefix in front of the run's
prefix; the sidecar test now also lists `db/<snapshot>.duckdb.source`.

*Not done / Open.* The delta's `since` is still given by the operator or the schedule: after a held night it must
reach back to the promoted snapshot, or the held night's good changes are missing until the next full load (they are
never wrongly included). `services/lake/source.py` (owned elsewhere) does not pass an override to `load_batch`; the
override is the environment variable, bound to one snapshot. The adapter's guard counts records per type, not ids: a
night that replaces most records of a kind with as many new ones passes it. A box whose hospital lake was built from
the site's inputs alone before this change counts as fed, so its next "Publish" before the first night is refused
until a night arrives. A refusal shows in the ingest report, the audit and the 409; there is no console banner yet.
