# D-1253 Lake ids are per patient: one patient's record never takes another's place

- **Task:** lane J, card "lake ids are per patient". · **Date:** 2026-11-19
- **Builds on:**
  - D-812: an empty key gave every row one id, so a row without its key is refused;
  - D-806: links by day;
  - D-528: a delta night's row that leaves the feed;
  - D-594: SS-MIX2 `per_day` order keys;
  - D-271: the drop guard;
  - D-677 / NEW-B-36: chart merges.
- **The fault.**
  - `Mapper.row_id` made the id of a record from an id spec `{hid: <column>}` as `HMAC(site key, "<type>|<number>")`.
    The patient was not in it.
  - The shared definitions use it for every clinical record type: `tw_core/demo_his.yaml`, which the SS-MIX2, CSV
    and SQL site mappings extend.
  - Hospital systems reuse such numbers across patients: an SS-MIX2 order number is unique per patient, day and data
    type only.
  - So two patients' order "RX1" were one id. The lake kept one MedicationRequest, under the second patient; the
    first patient's was gone, with no error and no count.
  - A tombstone for one patient deleted the other's record. A reference by number (a diagnosis's visit) named the
    other patient's record.
  - TrialBox's own synthetic writers always emitted site-unique numbers, so no test or golden showed it.
- **Decision:**
  - **The rule (rule 2).** The id of every record that belongs to a patient is
    `HMAC(site key, "<type>|<pid>|<suffix>|<number>")[:32]` (`adapter.mapping.engine.patient_resource_id`).
    - `pid` is the patient's pseudonym, derived from the chart number exactly as the Patient record's own id is
      (`pid_for_mrn`). It is fixed-length hex with no `|`.
    - The suffix has its own part and holds no `|`. So a suffixed id never equals a plain number's: "1" with suffix
      "a" is not "a1".
    - Each resource spec gets its patient column when the mapping loads: the column of its one
      `{ref: {type: Patient, pid: <col>}}`, or `id.patient` when the record names several.
  - **Refused when the mapping loads** (no opting out by forgetting, review D):
    - an `hid` id whose record names no patient and is not declared site-wide;
    - `id: {column: ...}` on a patient's record (the source's number as the id, the same fault by another door);
    - any id that is not `pid`, `hid` or `column` (a template carries no patient);
    - an `id.patient` that is not a chart number of a patient the record names (a clinician's id);
    - a record of no patient (site-wide) that names a patient's record by number;
    - a drug, device, substance or group declared site-wide that a patient's record names by number (it is per
      order, so the patient's);
    - one record type under two id rules;
    - a suffix with `|`;
    - any `id.unique` (review round 3, below);
    - a suffix on a site-wide id, or on a link by number to a site-wide record (round 3: a suffix never runs into
      a number).
  - **Records of no patient.**
    - A clinician, a role, an organisation, a place or a service must say `id: {hid: <col>, site_wide: true}`. Its
      id is `HMAC("<type>|<number>")`.
    - A Medication, Device, Substance or Group may say it, when it names no patient. One that names its patient has
      its patient's per-patient id.
  - **No site-wide id for a patient's record (review round 3).**
    - Review C offered `id: {hid: <col>, unique: site}`; round 3 removed it, with its count, its card line and its
      docs. It was the original fault by opt-in. It let a delete for one chart remove the record now under another,
      let a link name another patient's record uncounted, and let a suffix run into a number again.
    - The loader refuses `id.unique`. A patient's record is always its patient's, without exception: a delete, a
      link by number and a suffix can never reach another patient's record.
  - **A record the hospital re-files to another chart: the stated limit (review round 3).**
    - A record re-filed from chart A to chart B is a new record of B, with B's id.
    - A **full night** (every table read whole) holds B's record only.
    - A **delta night** sends the changed rows only. It does not see that A's row left, so the lake holds A's stale
      copy beside B's until the next full night. The stale copy is A's own record: it is never deleted by B's rows,
      and no link of B's names it. This holds for every source.
    - Pinned, not hidden:
      `test_a_record_re_filed_to_another_chart_is_corrected_by_the_next_full_night_not_by_a_delta`.
    - **The advice.** The box's scheduled night reads every table whole: the timer's ingest job sends no `since`. A
      delta night is one asked for with `since` (`adapter run --since`, or an ingest job's `since` option). A site
      that runs delta nights runs a full night (a scheduled night, without `since`) at least once a week. There is
      no separate interval setting, and none is added here.
  - **Merged charts (review C).**
    - A chart merged into another (`pidmap.merge`) keeps making its records' ids under its own pid. The merge moves
      every reference to the patient, and the Patient, to the surviving pid as the snapshot is written (NEW-B-36,
      unchanged).
    - So a delta night after a merge holds what a full night holds. Two charts that each had a visit "E1" keep two
      visits of one patient.
    - The exception is the limit above. When the hospital also re-files the absorbed chart's rows under the surviving
      chart, a delta night holds the carried-over records (ids under the absorbed chart) and the re-filed ones (ids
      under the surviving chart): duplicate Encounters and Conditions of one patient, until the next full night,
      which holds the re-filed ones only.
    - Ids under the surviving pid were tried and dropped, for three reasons:
      - a lake record keeps no source number, so a delta night could not make the ids of the records it carries
        over again;
      - reading such a night whole drops every row a delta export does not send again;
      - the two "E1" visits would become one record.
    - The limit: a row of the surviving chart that names by number a record filed under the absorbed chart links
      to its own chart's number, and the link is counted when that record is not there.
  - **A row without its patient** is rejected and counted (`rejected_no_patient`), as D-812 rejects a row without
    its key. It never gets an id another patient's row could have too.
  - **References.**
    - A reference by number to a patient's record (`{ref: {type: Encounter, hid: enc_no}}`, the template token
      `{hid:T:col}`, the Encounter's own identifier) is always to **the row's own patient's** record:
      `<type>|<own pid>|<suffix>|<number>`, the suffix as the record's own id has it.
    - It never depends on the order of tables or rows, and it can never name another patient's record.
    - A link to a patient's record the lake does not hold is counted per source table and type
      (`links_to_absent_records`):
      - over the merged snapshot, after the night, in bounded memory (sorted runs, as the merge);
      - so a delta night whose visit came an earlier night counts nothing.
    - The count cannot tell why a record is absent: never sent, sent for another patient, or deleted.
    - A reference to a record of no patient keeps the site-wide id.
    - The index of "numbers seen tonight" of the first version is gone. With it went its scratch file and the claim
      "every link that resolved before resolves now": a link the old ids resolved to another patient's record no
      longer resolves, by design.
  - **Deletes.**
    - A tombstone is built from the deleted row's own patient, so a delete removes that patient's record only.
    - **A deleted row without its chart number removes nothing** and is counted (`deletes_without_patient`): the same
      number may be another patient's.
    - This changes behaviour for a CSV site that sent bare-key deletes. It must now send the chart number with every
      delete (`docs/data/02-mapping-a-site.md`, `CANONICAL.md`).
    - SS-MIX2 must key the diagnoses already tombstoned by patient and number (review E), so one patient's deleted
      diagnosis never hides another patient's diagnosis dropped from a newer snapshot. #1189 (10B-2b) carries that
      change to the reader, with its tests. **This card lands after #1189** (on master since train 100), and this
      branch leaves the reader as master has it. Its own test of the case
      (`test_ssmix2_third_review.py::test_8_one_patients_tombstones_never_hide_anothers_diagnosis_gone_from_a_newer_snapshot`)
      holds on master's reader.
  - **Collisions.**
    - Two records with one id and different content are counted per record type (`id_collisions`): two different
      source rows of one night, or of one back-fill, with the same patient and number. The last row still wins
      (DATA-017).
    - The same row sent twice is not a collision.
    - A record that changes from one night to the next is an update, never counted.
  - **Where a person reads the counts.** There are four counts:
    - `id_collisions`;
    - `links_to_absent_records`;
    - `deletes_without_patient`;
    - `rejected_no_patient`.

    Where they appear:
    - a night's counts are in `completeness.json`, the night's audit detail, the data-ops batch row
      (`datacore.dataops.DETAIL_KEYS`) and a log warning;
    - the back-fill counts all four (review F; `links_to_absent_records` since round 3), in its report, its
      completeness record and its audit event;
    - the console's data-ops batch page shows them in a card, counts only, in en, ja and zh-TW, only when one is
      above zero. Otherwise the page is as before.

    `IngestReport` (a contract) is unchanged.
  - **SS-MIX2 version handling is unchanged** (cards #1095 and #1189 own it).
    - The reader keeps the newest version per (patient, data type, order number[, day]) before the mapper sees a row.
    - With `per_day` keys the number an id is made from is `<order>@<day>`, with the patient added.
    - This card does not change the SS-MIX2 reader. The diagnosis tombstones keyed by patient (above) come with
      #1189, which lands first.
  - **fhir_bulk is not affected.** A FHIR server's id is unique per server and type. `pipeline.bulk_id` keeps
    `HMAC("<type>|<server id>")`, pinned by `test_fhir_bulk_ids_stay_the_servers_unique_ids`. Patient ids (pids) are
    unchanged everywhere.
- **The one-time consequence.** Every id of a patient's record changes once. These stores outside the lake keep such
  ids:
  - the OMOP store of record: `tb_record.source_record_id` and the before-images;
  - the derived store: anchors, inputs, conflicts;
  - the vector store: `note_chunk.did`;
  - the patient twin's documents;
  - the candidate pool's verdicts;
  - the EDC drafts' citations: the signature over `final_citation`, and the ODM `SourceID`;
  - fhir-store, through its ledger (it follows by itself);
  - published job outputs.

  No old-to-new map is built: it would have to be built from the very collisions that lost data. Instead the rule is
  recorded and never mixed:
  - **Recorded.**
    - Every snapshot carries `id_rule.json`; only the integer 2 is this rule.
    - The OMOP, derived, vector, twin and pool stores each have a `tb_id_rule` table (their own migration). Each
      checks it in its own write transaction (`tb_common.id_rule.ensure`):
      - an empty store is stamped under an advisory lock (two first writes stamp once);
      - a store that holds lake ids and says no rule refuses, naming itself, the runbook step and its command;
      - a store of a newer rule refuses with "update the box", never "rebuild".
    - The derived store's documented-score check refuses too.
  - **The night fails closed.** Before it reads or writes anything, a night (and a back-fill) is refused when the
    lake's snapshots, the OMOP store or the derived store hold ids of another rule.
    - The adapter's role is meant to read the OMOP and the derived store (D-378). When their rule cannot be read
      there ("not readable", or the probe fails), the night refuses as for an old rule (review round 3).
    - A snapshot is never merged over another rule's base.
    - The night's data-ops batch row is opened first. The refusal is **one** `ingest.failed` event
      (`refused: id_rule`), which closes that row as failed. A back-fill's refusal is one `ingest.backfill` event
      (`state: failed`, `refused: id_rule`).
    - The adapter's role is not meant to read the vector store, the twin or the pool (D-378): "not readable" is
      expected there, so the night never probes them. Each is caught **at its own first write after the night,
      not before it** (`tb_common.id_rule.ensure`): a night can complete while those three still hold old ids.
  - **Readers refuse (review G1).** No lake reader opens a snapshot whose NDJSON is not rule 2 (`Lake.db_path`: every
    query, pin, hold and promote). It answers 503: "the lake cannot serve it", never "no data".
    - A snapshot served with no NDJSON left (the byte budget takes the NDJSON first, NEW-B-38) is checked by
      `db/<snapshot>.duckdb.id_rule`, which every build writes (round 3). A file without one was built before
      D-1253, so it is of the earlier rule.
  - **One place where a snapshot is opened (review round 3).** Every entry point that reads a lake snapshot's NDJSON
    goes through `tb_common.id_rule.open_snapshot`, which refuses a snapshot of another rule before anything is
    read or written:
    - the night and the back-fill: their merge base (`adapter.ndjson.write_snapshot`);
    - the lake build (`lake.store.Lake._source_or_refuse`), whoever asks for it: the night's publish, a re-publish
      of a held night, the lake service's rebuild, a build from a folder of its own;
    - the OMOP load: `python -m omop load` and the dual write (`adapter.dual_write`);
    - the FHIR load (`adapter.load_fhir.load_snapshot`);
    - the snapshot validation (`adapter validate`, the adapter's validate route: `adapter.validate.jpcore`).

    Not entry points:
    - the night's site-profile stamp (`adapter.site_profile`), which reads no record id;
    - the backup and restore, which copy files as they are (a restored lake of the earlier rule is refused by the
      above);
    - the development tools that build a synthetic lake of their own in a scratch folder: `tools/scale_gate.py`,
      `scenarios.py`, `e2e_simple.py`, `omop_parity.py`, `backup_drill.py`, `build_rulesets.py`, `ingest_local.py`,
      `imperfect_feed.py`, `trialbox/memcaps.py`.
  - **EDC keeps the rule per study** (`edc.tb_id_rule_study`). EDC is the one place old ids stay on a box, by design.
    - The migration stamps rule 1 on every study that has drafts when it runs. A study with none starts at rule 2
      at its first draft run.
    - **What freezes a study** has one definition, used by EDC and by the rebuild alike (`edc.store.cites_old_rows`,
      review round 3): a draft that cites a lake row (`citation` or `final_citation`) and is decided, signed, sent
      or named by any act on a draft (`edc.store.TRAIL_TABLES`, held to the schema by a test). A value decided
      "not found" cites no lake row, so it freezes nothing.
    - **Frozen studies.** A rule-1 study with such a draft is frozen for prefill. Every write of its values is
      refused with the reason, in that write's own transaction:
      - a draft run;
      - an ODM import;
      - a decision;
      - a copy-assist tick;
      - a signature (second review, finding 12);
      - a send;
      - REDCap's erase of hidden values.
    - What happens to a frozen study's records:
      - they stay, readable and exportable;
      - its signatures still verify;
      - nothing marks a value `source_changed` because of the change of rule;
      - its EDC page says why prefill is stopped, in one line in en, ja and zh-TW, shown only for a frozen study.
    - A person closes a frozen study in EDC or starts it again under a new study key.
    - Any other rule-1 study waits for the rebuild. The rebuild clears its open drafts (no trail), keeps a decided
      value that cites no lake row as it is, and stamps the study rule 2. No study is left waiting for good.
  - **The rebuild is one explicit operator step** after the update: `python3 -m tools.trialbox id-rule-rebuild`
    shows the plan, and `--yes` does it. It is `tools/id_rule_rebuild.py`, run in a one-off adapter container as the
    box's admin, and written up in RUNBOOK §5, "Lake ids per patient".
    - **A later release's box.** It refuses, changing nothing, when anything says a rule above 2: a snapshot
      record, or one that cannot be read (a rule-1 snapshot has none), a store, or an EDC study. It says "update
      the box" (review round 3), and never moves such a snapshot aside as rule 1.
    - **Writers stopped.** It refuses, changing nothing, unless the writers are stopped. It checks this itself:
      - it takes the adapter's run lock;
      - no lake build runs;
      - no service role is connected to the trial database or the OMOP database.

      It holds the lake lock.
    - **Kept, never deleted:** what cannot be made again or what a person decided.
      - Retention's month-end snapshots are moved aside to `<lake>/id_rule_1/`. They are kept, never read, pruned by
        retention as before, and registered for erasure (`lake:id_rule_1`).
        - They are chosen from every place a snapshot is: its NDJSON, its DuckDB file and generations, its Parquet
          folder. A month-end served without its NDJSON is a month-end too. What an earlier run cut short moved
          already counts as well (round 3).
        - Every part moves, one file or folder at a time: the NDJSON, the Parquet, the DuckDB file with its
          sidecars, and its generations' files and records (`db/gen/<s>.g<n>.*`).
      - A resolved derived conflict and its score row stay, marked `id_rule = 1`; the row is superseded, so it is
        never read as a score.
      - EDC's trail stays.
      - So do the site key, the pid map, the site facts, the embedding cache and the FHIR ledger.
    - **In order:**
      1. it moves the month-ends aside;
      2. it clears what is served (`CURRENT`, the DuckDB and Parquet copies, the holds);
      3. it clears the rest of the lake;
      4. it clears the stores, each stamped rule 2 in the same transaction:
         - the OMOP store the night probes (`TB_OMOP_DB_URL` when set): its feed records of patients' clinical
           data. The persons and the practitioners stay (#1258), and so does every record a person decided
           (ruling 1, below).
         - the derived scores, inputs, open conflicts and batch runs;
         - the note chunks, the twin's documents and the pool;
         - the data-ops `built` and `built_kept` rows;
         - the rule-1 EDC studies' open drafts.

      A crash after any step, or between any two moves aside, loses nothing kept and serves nothing of the old
      rule, and a second run finishes the work.
    - The plan names every kind of thing kept, moved and cleared, with counts.
    - The rebuild writes one audit event of a kind the box already has, `lake.rebuild.source` (`source: id_rule`),
      and the same to `<lake>/id_rule_rebuild.json`: counts, snapshot dates and the EDC study keys it froze or
      stamped; no patient (`lake:id_rule_rebuild.json` in the erasure registry). There is no audit schema or role
      change; the rebuild runs as the admin.
    - **Deep review (4a059fca), folded in:**
      - **Nothing to do.** When no snapshot, store, back-fill spool or EDC study holds ids of the earlier rule, the
        plan and the rebuild say "nothing to do" and change nothing (exit 0).
      - **Retention's month-ends.** The month-end a month keeps is retention's own: its last night that passed
        (`adapter.pipeline.good_snapshots`, one definition with the nightly prune), by the site's date (`TB_TZ`),
        never the container's UTC date.
      - **A record that cannot be read.** `id_rule.json` is written to a temporary file and renamed into place. A
        record that cannot be read (a write cut short, a damaged disk) is its own state, with one instruction from
        the night, the readers and the rebuild alike: move that unfinished snapshot out of the lake and run the
        night again.
      - **The back-fill's spool.** A spool kept from before the update is never reused: its fingerprint holds the
        id rule (#1258), so a spool of the earlier rule misses and is read again from the source.
      - **Backups.** The backup takes `id_rule_1/<ndjson|db|parquet>` by the rules of the live folders: a month-end
        aside is an older snapshot (its NDJSON and older generations left out; its DuckDB, generation records and
        Parquet kept), as before the move.
      - **Kept out.** `adapter run` and `adapter backfill` from the command line hold the run lock, so the rebuild
        keeps them out as it keeps out the service's nights. The night's FHIR step checks the snapshot's rule before
        its ledger is read or written. An EDC store not yet migrated refuses the rebuild (start the services once
        first), as the derived store does. A link by day must name the record's patient among its keys.
    - **The integrator's review (#1258) and the owner's rulings (2026-11-20).** Twelve findings: eight fixed by
      the integrator's builder with failing-first tests (`tests/unit/test_id_rule_review.py`), four ruled.
      - **Fixed (#1258).** A practitioner survives the rebuild. A back-fill spool of the earlier rule is never
        resumed. A mapping cannot give a patient's record an id of its own choosing (`elements` or `$merge` setting
        `id`, `id.pid` on a record that is not a Patient, `column` on a record that names its patient). A link by
        day names the record's patient among its keys. A chart number keys a record however it is spelt
        (`chartno.normalise`). The month-end kept is the last night that passed. The rebuild's later-release check
        reads the DuckDB files' rule records too. A confirmed value an ODM import cited survives the rebuild.
      - **Ruling 1: a steward's decision on an id two patients shared.** Which chart the decision meant cannot be
        told, so it is never carried over by guess and never deleted. The rebuild keeps every OMOP feed record a
        person decided (a status change), with its whole history, as `source_kind = 'feed:id_rule_1'` (out of the
        feed's reach, no OMOP row, one more event saying why). It lists their earlier ids in
        `<lake>/id_rule_review.json` (`lake:id_rule_review.json`: record-number pseudonyms, no patient). Every
        record a night or a back-fill makes from such a number, for each patient, is a proposed fact (D-135's
        basis tag, never coded in the lake, status `proposed` in OMOP) and carries the tag
        `urn:trialbox:review|id-rule-steward-review`. The night counts them (`steward_review_needed`, kept on the
        data-ops batch row). A steward reviews each in OMOP (`proposed` to `confirmed` or `rejected`); an unchanged
        night keeps that status.
      - **Ruling 7: one record from a mapped feed and from a FHIR bulk export.** A site changes source only with a
        full night: a delta night over a snapshot read from another source is held, both ways, with that message.
      - **Ruling 9: the DuckDB file's own rule record.** For 1.0 the rebuild and the readers keep today's evidence
        (the snapshot's `id_rule.json`, and `db/<s>.duckdb.id_rule` for a file served without its NDJSON).
        `test_id_rule_review.py::test_duckdb_owns_its_rule` stays a strict expected failure.
      - **Ruling 11: SS-MIX2 order ids.** The key is the reader's, owned by #1238 (it keys `<number>@<type>`). Each
        SS-MIX2 snapshot records the key form its order ids were made from (`id_rule.json` `keys.ssmix2_order`). A
        snapshot of another form is one the rebuild clears (a delta night over it is held), and the next full
        night reads every order under the reader's key.
  - **A box with real data** follows the same steps.
    - Nothing a person decided and nothing retention keeps is deleted.
    - What is cleared is made again from the sources: the first night after the rebuild reads every table whole,
      and the jobs fill the stores again.
    - If the hospital's export no longer holds the history the lake held, the history comes back by the back-fill
      (D-403), not by this rebuild.
    - Published job outputs cite the old ids and cannot be traced into the rebuilt lake. The audit chain is not
      touched.
  - **Backups.** A backup made after the update is restored on this release or a later one: update first, then
    restore. A backup made before the update is of rule 1, is refused like any old store, and needs the rebuild.
  - **Not touched:**
    - published job outputs;
    - the audit chain;
    - permissions: no database role was changed;
    - the audit schema.

    The console changes only by the counts card and the frozen study's line, each shown only when it has something
    to say.
- **Goldens.**
  - **The next night.** The goldens' next night (the `-deletes` set) chose its records by their place in the
    id-sorted snapshot. It now chooses them by their content with the ids blanked (`tools/golden_nights.py`).
  - **The proof is `tools/goldens_id_proof.py`.**
    - It builds the goldens' data sets with master's code and with this change, both with the new next night.
    - It compares every lake row, chunk, funnel, candidate list and full outcome, per data set, with one one-to-one
      map from old ids to new. Every pid must map to itself.
  - **The proof fails** (review H):
    - on an empty dump;
    - on a data set or file with nothing compared;
    - on a file found on one side only;
    - on a list whose order changed. Only a list whose items hold record ids (the lake and the engine list them in
      the order of the ids) may be in another order after the mapping.
  - **The new golden set** `ssmix2-jp-per-patient` holds the same 400 synthetic patients, with every number a
    running number per patient (`tools.synth_hospital.per_patient_numbers`). So the goldens hold the repeated-number
    case from now on.
    - It is **not covered by the old-to-new comparison**: master's code would merge its patients' records.
    - Its check is that its funnels and candidate lists equal `ssmix2-jp`'s, and its own `make goldens-check`.
- **Held by:**
  - `tests/unit/test_lake_ids_per_patient.py`:
    - two patients sharing every number through the CSV, SQL and SS-MIX2 doors, full and delta nights (records,
      content, tombstones, references);
    - the mapper's rules and each load-time refusal;
    - links in any order, and absent links;
    - re-filing to another chart (the delta limit pinned), merged charts (full and delta), the refusal of
      `unique` and of a site-wide suffix;
    - collisions, and the fhir_bulk pin.
  - `tests/unit/test_lake_id_rule.py`:
    - snapshots and integer-only rules;
    - the night's one refusal, a newer rule, a probe that fails, a store the adapter reads but cannot read;
    - each store's stamp and refusal, through the OMOP load, the derived recompute and documented check, the twin's
      put and the pool's upsert.
  - `tests/unit/test_id_rule_rebuild.py`:
    - the plan, the rebuild and the writer checks;
    - month-ends aside and their pruning;
    - a month-end served without its NDJSON, with its sidecars;
    - a crash after each step, and between each two moves aside;
    - a lake, a store or an EDC study of a later release, refused;
    - resolved conflicts kept, the data-ops reset;
    - `TB_OMOP_DB_URL`, the audit event;
    - the frozen EDC study, the host command.
    - ruling 1 (two charts sharing a number, a steward's rejection), ruling 11 (SS-MIX2 orders under the reader's
      key);
  - `tests/unit/test_edc_id_rule_freeze.py`: the migration's stamp, every write path of a frozen study, no
    `source_changed`, open drafts waiting, a study whose decided value cites no lake row (not frozen, freed by the
    rebuild), the trail tables held to the schema.
  - `tests/unit/test_backfill_completeness.py`: the back-fill's counts (`id_collisions`, `rejected_no_patient`,
    `deletes_without_patient`, `links_to_absent_records`) and its one event when refused for the id rule.
  - `tests/unit/test_lake_snapshot_opened_once.py`: every entry point above refuses a snapshot of the earlier rule
    and of a later one; a served snapshot without NDJSON.
  - `tests/unit/test_ssmix2_third_review.py::test_8_one_patients_tombstones_never_hide_anothers_diagnosis_gone_from_a_newer_snapshot`
    (the reader change is #1189's).
  - `tests/unit/test_goldens_id_proof.py`.
  - `tests/console/test_id_rule_pages.py`.
  - `tests/integration/test_vec_store.py::test_new_chunks_are_refused_beside_chunks_of_the_earlier_id_rule`.
  - `tools/goldens_id_proof.py`.
  - `tests/unit/test_id_rule_review.py` (#1258: one test per finding; `test_duckdb_owns_its_rule` a strict expected
    failure, ruling 9).
- **Remains.**
  - Ruling 9: a DuckDB file does not carry its own rule. Today's evidence stands for 1.0 (above); no code.
  - Ruling 1: no tool yet takes a reviewed record off the review list. While its earlier id is listed, the lake keeps
    it out of the coded tables, whatever the steward decided in OMOP; OMOP itself counts it once confirmed.
    A follow-up card (lane J) builds it: a steward's confirmation takes the record off `id_rule_review.json` and the
    next night codes it, audited.
