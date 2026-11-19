# D-1253 Lake ids are per patient: one patient's record never takes another's place

- **Task:** lane J, card "lake ids are per patient". · **Date:** 2026-11-19
- **Builds on:** D-812 (an empty key gave every row one id: a row without its key is refused), D-806 (links by day),
  D-528 (a delta night's row that leaves the feed), D-594 (SS-MIX2 `per_day` order keys), D-271 (the drop guard).
- **The fault.** `Mapper.row_id` made the id of a record from an id spec `{hid: <column>}` as
  `HMAC(site key, "<type>|<number>")`: the patient was not in it. The shared definitions (`tw_core/demo_his.yaml`,
  which the SS-MIX2, CSV and SQL site mappings extend) use it for Encounter, Appointment, Condition, Observation (lab
  and vitals), MedicationRequest, Procedure, DiagnosticReport, DocumentReference, Claim, ClaimResponse, Coverage and
  Consent. Hospital systems reuse such numbers across patients (an SS-MIX2 order number is unique per patient, day and
  data type only). Two patients' order "RX1" were one id: the lake kept one MedicationRequest, under the second
  patient. The first patient's was gone, with no error and no count. A tombstone for one deleted the other's, and a
  reference by number (a diagnosis's visit) named the other patient's record. TrialBox's own synthetic writers always
  emitted site-unique numbers, so no test or golden showed it.
- **Decision:**
  - **The rule (rule 2).** The id of every record that belongs to a patient is
    `HMAC(site key, "<type>|<pid>|<number>")[:32]` (`adapter.mapping.engine.patient_resource_id`). `pid` is the
    patient's pseudonym that `Mapper.pid` already derives: fixed-length hex with no `|`, so the three parts read back
    one way only. Each resource spec gets its patient column when the mapping loads. It is the column of its one
    `{ref: {type: Patient, pid: <col>}}`, or `id.patient` when the record names several.
  - **No opting out by forgetting.** An `hid` id whose record names no patient is refused at load. A record of no
    patient keeps the site-wide id `HMAC("<type>|<number>")` and must say so: `id: {hid: <col>, site_wide: true}`.
    Only Practitioner, PractitionerRole, Organization, Location, HealthcareService, Medication, Device, Substance and
    Group may say it, and never a record that names a patient. An `hid` id on one of those types must say it.
  - **A row without its patient** is rejected and counted, as D-812 rejects a row without its key ("no patient (mrn
    is empty)"). It never gets an id another patient's row could have too.
  - **References.**
    - A reference by number to a patient's record (`{ref: {type: Encounter, hid: enc_no}}`, the template token
      `{hid:T:col}`, the Encounter's own identifier) is built the same way, with the referencing row's patient. Every
      link that resolved before resolves now, and a link can never cross patients.
    - When the night's rows give that number only to other patients, the link is left out and counted
      (`references_to_another_patient`, per table and type).
    - The night's index of numbers sits in a scratch SQLite file under the spool, so memory stays flat with the
      patients (T-692).
    - A reference to a record of no patient keeps the site-wide id.
  - **Deletes.** A tombstone is built from the deleted row's own patient, so a delete removes that patient's record
    only. **A deleted row without its chart number removes nothing** and is counted (`deletes_without_patient`): the
    same number may be another patient's. This changes behaviour for a CSV site that sent bare-key deletes. It must
    now send the chart number with every delete (`docs/data/02-mapping-a-site.md`, `CANONICAL.md`).
  - **Collisions are visible.** Two records of one night with one id and different content are counted per record
    type (`id_collisions`): two different source rows of the same patient and number. The last row still wins
    (DATA-017). The same row sent twice is the same record, not a collision.
  - **Where a person reads the counts.** These four counts are kept:
    - `id_collisions`;
    - `references_to_another_patient`;
    - `deletes_without_patient`;
    - `rejected_no_patient`, the rows rejected because they have no chart number.

    They are in `completeness.json`, in the night's audit detail, in the data-ops batch row
    (`datacore.dataops.DETAIL_KEYS`) and in a log warning. The console's data-ops batch page shows them in a card,
    counts only, in en, ja and zh-TW. The card appears only when a count is above zero; otherwise the page is as
    before. `IngestReport` (a contract) is unchanged.
  - **SS-MIX2 version handling is unchanged** (cards #1095 and #1189 own it). The reader keeps the newest version per
    (patient, data type, order number[, day]) before the mapper sees a row. This rule sits after it: a version
    choice never meets another patient's order. With `per_day` keys the number the id is made from is
    `<order>@<day>`, with the patient added.
  - **fhir_bulk is not affected.** A FHIR server's id is unique per server and type. `pipeline.bulk_id` keeps
    `HMAC("<type>|<server id>")`, pinned by `test_fhir_bulk_ids_stay_the_servers_unique_ids`. Patient ids (pids) are
    unchanged everywhere.
- **Where a source number became an id or a reference (the checkpoint's list), and the patient in it after this:**
  1. `Mapper.row_id`: yes.
  2. `Mapper.hid` and the template token: yes.
  3. `Mapper.ref` (`hid`): yes.
  4. `Mapper.tombstones` and D-528's left-out records: yes, from the row's own patient.
  5. The F7 links by day: the mapping's keys, which hold the patient.
  6. The SS-MIX2 version choice: (patient, type, order, day).
  7. `tables[t].duplicate_keys`: still the source key alone. It is a count of the source, not an id.
  8. The snapshot merge and the back-fill merge by id: whatever the id is.
  9. `bulk_id`: the server's id, unchanged.
  10. The lake's columns `eid`, `aid`, `cid`, `oid` (and a panel component's `<oid>.<code>`), `mid`, `prid`, `rid`,
      `did`, `kid`, `consid`, and the SQL evidence `<id>|<day>`: copies of 1 to 3.
- **The one-time consequence.** Every id of a patient's record changes once. Stores outside the lake keep such ids:
  - the OMOP store of record: `tb_record.source_record_id` and the before-images
    (`services/omop/schema.py:230`, `services/omop/load.py:310`);
  - the derived store: `score_row.anchor_oid` and `inputs`, `input_link.source_id`
    (`libs/tb_common/derived_store.py:60`, 183, 203, 439);
  - the vector store: `note_chunk.did` (`services/vec/store.py:39`);
  - the patient twin's documents (`services/patient_profile/twin.py:50`);
  - the candidate pool's verdicts (`services/orchestrator/db.py:47`);
  - the EDC drafts' citations (`services/edc/prefill.py:179`, the signature over `final_citation`, the ODM
    `SourceID`);
  - fhir-store, through its ledger (it deletes ids that are not in the snapshot: it follows by itself);
  - published job outputs.

  No old-to-new map is built: it would have to be built from the very collisions that lost data. Instead:
  - **The id rule is recorded and never mixed.** Every snapshot carries `id_rule.json`. The OMOP, derived, vector,
    twin and pool stores each have a `tb_id_rule` table (their own migration) and check it in their own write
    transaction (`tb_common.id_rule`):
    - an empty store is stamped with rule 2;
    - a store that holds lake ids and does not say rule 2 refuses with the night's words, naming itself, the
      runbook step and its command, and nothing is written.

    The EDC drafts keep the rule per study (see below). No database role was changed.
  - **The night fails closed.** Before it reads or writes anything, a night (and a back-fill) is refused when the
    lake's snapshots or the OMOP or derived store hold ids of the earlier rule. A snapshot is never merged over an
    old-rule base, so a delta night refuses an old base. The refusal is audited (`ingest.failed`, `refused: id_rule`).
    The adapter's database role reads only its own schemas (D-378), so the vector store, the patient twin and the
    candidate pool are caught **at their own first write after the night, not before it**: a night can complete
    while those three still hold old ids, until their next write refuses. Nothing mixes. The operator runs the
    rebuild's plan (`python3 -m tools.trialbox id-rule-rebuild`, which reads all of them) right after the update.
    Nothing trips OMOP's 20 % guard, orphans a chunk, retires a derived row or marks an EDC value `source_changed`
    by accident.
  - **The rebuild is one explicit operator step** for a box that holds synthetic data only:
    `python3 -m tools.trialbox id-rule-rebuild` (a plan; it changes nothing), then with `--yes`. It runs
    `tools/id_rule_rebuild.py` in a one-off adapter container as the box's admin, and is written up in RUNBOOK §5,
    "Lake ids per patient". It clears:
    - the lake's snapshot entries;
    - the OMOP store's feed records of patients' clinical data (persons, site records, vocabulary, conflicts, loads
      and ruleset releases stay);
    - the derived scores;
    - the note chunks;
    - the twin's documents;
    - the pool;
    - the open EDC drafts that no trail row names, of a study of the earlier rule.

    Then it stamps every store. The first night after it is a full night.
  - **EDC keeps the rule per study, and is the one place old ids stay on a box, by design.** A value a person
    confirmed, edited, signed or sent is a record. Its trail is append-only by trigger (D-281): nothing of it is
    deleted, no trigger is disabled and no signed record is rewritten, whether the box's data is synthetic or not.
    - A study whose decided, signed or sent values cite lake rows of the earlier rule is **frozen for prefill**:
      - a draft run, an ODM import and a send are refused, with the reason;
      - its records stay, readable and exportable as before, and its signatures still verify;
      - its citations cannot be traced into the rebuilt lake;
      - its EDC page says why prefill is stopped (one line in en, ja and zh-TW, shown only for a frozen study).
    - The other studies go on under rule 2. A study with no trail stamps itself at its first draft run
      (`edc.tb_id_rule_study`).
    - A person closes a frozen study in EDC, or starts it again under a new study key. This is where a person
      chooses.
    - The rebuild names each frozen study with its count and its ODM export, and offers no removal.
  - **Not touched:** published job outputs (they cite the old ids and cannot be traced into the rebuilt lake), the
    audit chain, permissions (no database role) and the audit schema. The console changes only by the counts card and
    the frozen study's line, each shown only when it has something to say.
- **Goldens.** The goldens' next night (the `-deletes` set) chose its deleted and corrected records by their place
  in the id-sorted snapshot, so a re-id would have deleted other records. It now chooses them by their content with
  the ids blanked (`tools/golden_nights.py`), which moves the `-deletes` set once for that reason. They move by ids
  alone, and the proof is `tools/goldens_id_proof.py`, which builds both releases with the new next night. It builds the goldens' data sets
  with master's code and with this change, then compares every lake row, chunk, funnel, candidate list and full
  outcome. Every 32-hex token is treated as an id; one one-to-one map from old ids to new must make every old row
  equal to the new one exactly, and every pid must map to itself. A new golden set, `ssmix2-jp-per-patient`, holds
  the same 400 synthetic patients with every number a running number per patient
  (`tools.synth_hospital.per_patient_numbers`), so the goldens hold the repeated-number case from now on.
- **Held by:**
  - `tests/unit/test_lake_ids_per_patient.py`: two patients sharing every number through the CSV, SQL and SS-MIX2
    doors, full and delta night (records, content, tombstones, references), the mapper's rules, collisions, and the
    fhir_bulk pin;
  - `tests/unit/test_lake_id_rule.py`: snapshots, the night's refusal, each store's stamp and refusal, through the
    OMOP load, the derived recompute, the twin's put and the pool's upsert;
  - `tests/unit/test_id_rule_rebuild.py`: the plan, the rebuild, the frozen EDC study kept and named, the host
    command;
  - `tests/unit/test_edc_id_rule_freeze.py`: a study stamps itself; a frozen study's draft and send are refused,
    its signatures verify;
  - `tests/console/test_id_rule_pages.py`: the counts card (and the page without it when no count is above zero),
    the frozen study's line;
  - `tests/integration/test_vec_store.py::test_new_chunks_are_refused_beside_chunks_of_the_earlier_id_rule`;
  - `tools/goldens_id_proof.py`.
