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
    - a suffix with `|`, and a `unique` other than `site`.
  - **Records of no patient.**
    - A clinician, a role, an organisation, a place or a service must say `id: {hid: <col>, site_wide: true}`. Its
      id is `HMAC("<type>|<number>")`.
    - A Medication, Device, Substance or Group may say it, when it names no patient. One that names its patient has
      its patient's per-patient id.
  - **A number unique across the site (review C).**
    - A mapping may declare `id: {hid: <col>, unique: site}` when the source guarantees the number is the site's,
      for all time. The id is then the number's alone.
    - A record the source re-files to another chart keeps its id and moves to that patient. The merge counts it
      (`moved_to_another_patient`).
    - Undeclared (the default), a re-filed record is a new record of the new patient. The old one stays under the
      first patient until the next full night.
    - The shipped mappings declare none; when unsure, leave it out (`docs/data/02-mapping-a-site.md`).
  - **Merged charts (review C).**
    - A chart merged into another (`pidmap.merge`) keeps making its records' ids under its own pid. The merge moves
      every reference to the patient, and the Patient, to the surviving pid as the snapshot is written (NEW-B-36,
      unchanged).
    - So a delta night after a merge holds what a full night holds. Two charts that each had a visit "E1" keep two
      visits of one patient.
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
    - SS-MIX2 keys the diagnoses already tombstoned by patient and number (review E), so one patient's deleted
      diagnosis never hides another patient's diagnosis dropped from a newer snapshot.
  - **Collisions.**
    - Two records with one id and different content are counted per record type (`id_collisions`): two different
      source rows of one night, or of one back-fill, with the same patient and number. The last row still wins
      (DATA-017).
    - The same row sent twice is not a collision.
    - A record that changes from one night to the next is an update, never counted.
  - **Where a person reads the counts.** There are five counts:
    - `id_collisions`;
    - `moved_to_another_patient`;
    - `links_to_absent_records`;
    - `deletes_without_patient`;
    - `rejected_no_patient`.

    Where they appear:
    - a night's counts are in `completeness.json`, the night's audit detail, the data-ops batch row
      (`datacore.dataops.DETAIL_KEYS`) and a log warning;
    - the back-fill's three (review F) are in its report, its completeness record and its audit event;
    - the console's data-ops batch page shows them in a card, counts only, in en, ja and zh-TW, only when one is
      above zero. Otherwise the page is as before.

    `IngestReport` (a contract) is unchanged.
  - **SS-MIX2 version handling is unchanged** (cards #1095 and #1189 own it).
    - The reader keeps the newest version per (patient, data type, order number[, day]) before the mapper sees a row.
    - With `per_day` keys the number an id is made from is `<order>@<day>`, with the patient added.
    - The one change in the reader is the diagnosis tombstones keyed by patient (above), a minimal change on lines
      #1189 also edits.
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
    lake's snapshots, the OMOP store or the derived store hold ids of another rule, or when that cannot be read.
    - A snapshot is never merged over another rule's base.
    - The night's data-ops batch row is opened first. The refusal is **one** `ingest.failed` event
      (`refused: id_rule`), which closes that row as failed.
    - The adapter's role reads only its own schemas (D-378). So the vector store, the twin and the pool are caught
      **at their own first write after the night, not before it**: a night can complete while those three still
      hold old ids.
  - **Readers refuse (review G1).** No lake reader opens a snapshot whose NDJSON is not rule 2 (`Lake.db_path`: every
    query, pin, hold and promote). It answers 503: "the lake cannot serve it", never "no data".
  - **EDC keeps the rule per study** (`edc.tb_id_rule_study`). EDC is the one place old ids stay on a box, by design.
    - The migration stamps rule 1 on every study that has drafts when it runs. A study with none starts at rule 2
      at its first draft run.
    - **Frozen studies.** A rule-1 study with a decided, signed or sent value is frozen for prefill. Every write of
      its values is refused with the reason, in that write's own transaction:
      - a draft run;
      - an ODM import;
      - a decision;
      - a copy-assist tick;
      - a send;
      - REDCap's erase of hidden values.
    - What happens to a frozen study's records:
      - they stay, readable and exportable;
      - its signatures still verify;
      - nothing marks a value `source_changed` because of the change of rule;
      - its EDC page says why prefill is stopped, in one line in en, ja and zh-TW, shown only for a frozen study.
    - A person closes a frozen study in EDC or starts it again under a new study key.
    - A rule-1 study with open drafts only waits for the rebuild, which clears those drafts and stamps it rule 2.
  - **The rebuild is one explicit operator step** after the update: `python3 -m tools.trialbox id-rule-rebuild`
    shows the plan, and `--yes` does it. It is `tools/id_rule_rebuild.py`, run in a one-off adapter container as the
    box's admin, and written up in RUNBOOK §5, "Lake ids per patient".
    - **Writers stopped.** It refuses, changing nothing, unless the writers are stopped. It checks this itself:
      - it takes the adapter's run lock;
      - no lake build runs;
      - no service role is connected to the trial database or the OMOP database.

      It holds the lake lock.
    - **Kept, never deleted:** what cannot be made again or what a person decided.
      - Retention's month-end snapshots are moved aside to `<lake>/id_rule_1/`. They are kept, never read, pruned by
        retention as before, and registered for erasure (`lake:id_rule_1`).
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
           data. The persons stay.
         - the derived scores, inputs, open conflicts and batch runs;
         - the note chunks, the twin's documents and the pool;
         - the data-ops `built` and `built_kept` rows;
         - the rule-1 EDC studies' open drafts.

      A crash after any step serves nothing of the old rule, and a second run finishes the work.
    - The plan names every kind of thing kept, moved and cleared, with counts.
    - The rebuild writes one audit event of a kind the box already has, `lake.rebuild.source` (`source: id_rule`),
      with counts only. There is no audit schema or role change; the rebuild runs as the admin.
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
    - `unique: site` and re-filing, merged charts (full and delta);
    - collisions, and the fhir_bulk pin.
  - `tests/unit/test_lake_id_rule.py`:
    - snapshots and integer-only rules;
    - the night's one refusal, a newer rule, a probe that fails;
    - each store's stamp and refusal, through the OMOP load, the derived recompute and documented check, the twin's
      put and the pool's upsert.
  - `tests/unit/test_id_rule_rebuild.py`:
    - the plan, the rebuild and the writer checks;
    - month-ends aside and their pruning;
    - a crash after each step;
    - resolved conflicts kept, the data-ops reset;
    - `TB_OMOP_DB_URL`, the audit event;
    - the frozen EDC study, the host command.
  - `tests/unit/test_edc_id_rule_freeze.py`: the migration's stamp, every write path of a frozen study, no
    `source_changed`, open drafts waiting.
  - `tests/unit/test_backfill_completeness.py::test_the_first_load_counts_what_the_night_counts_of_record_ids`.
  - `tests/unit/test_ssmix2_third_review.py::test_8_one_patients_tombstones_never_hide_anothers_diagnosis_gone_from_a_newer_snapshot`.
  - `tests/unit/test_goldens_id_proof.py`.
  - `tests/console/test_id_rule_pages.py`.
  - `tests/integration/test_vec_store.py::test_new_chunks_are_refused_beside_chunks_of_the_earlier_id_rule`.
  - `tools/goldens_id_proof.py`.
