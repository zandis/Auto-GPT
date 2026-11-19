# JP Core mapping (Japan sites)

* `ssmix2_site.yaml` — template for a site that exposes SS-MIX2 standardized storage (`--source ssmix2`, D-122,
  D-137). The reader reads ADT-00 (patient), ADT-12/22 (visits), ADT-52 (discharge or patient class change, by the
  trigger event), PPR-01 (one snapshot per patient: deletions, ICD-10 from PRB-10, dates, 転帰, 主診断, 修飾語),
  OMP-01/02 (prescription and injection orders: one dose, the doses a day from the 用法 through an optional
  `usage.csv` here, `code,doses_per_day`, else "1日N回" in its text; YJ from RXE-31) and OMP-11/12 (their 実施, folded
  into the order or on their own), with YJ, HOT and ATC kept, OML-11 (JLAC10 results) and the documents of the
  extended storage (`<root>/extended_storage/`, the guideline's content folders and the older layout: text, HTML,
  Word and PDF). What of the specification is read and what is not: `docs/data/01-what-the-box-reads.md`.
* `prb14_outcome.csv` (PRB-14 転帰 code to the diagnosis status) and `document_loinc.csv` (an extended-storage
  LOINC document code to the note type): only codes a document in this repository records (review 12), every
  row `verify`. A PRB-14 row is applied only once its `verified` column says `yes` and it names its public source:
  `document` a well-formed https URL or a DOI, `version` a date or a version number, `title`, `publisher` and
  `section` filled, the publisher not this project (else the reader stops at start). A person reviews each such row
  in the pull request that adds it. Until then its `status` is a proposal and the code reads as unknown, never
  active.
  Vitals, reports, claims and the
  registry come from the extended CSVs under `<root>/extended/`.
* The mapping puts JP Core 1.1.0 profiles on the shared resource set (`profiles`) and adds what JP Core asks for
  (`overlay`: the lab specimen and code text, the Rp identifiers of a MedicationRequest, the 標準病名 coding, the
  class history of a visit). Every ingest checks 50 resources of each type against JP Core
  (`adapter.validate.jpcore`, rules in `validate/jp_core_rules.json` built by `tools/jpcore_rules.py`) and writes
  the result to `jp_core_validation.json` beside the snapshot. `adapter validate` and `POST /$validate` do the same
  on demand.
* `jlac10_to_loinc.csv` — JLAC10 → LOINC for the lab results (same columns as `tw_core/lab_local_to_loinc.csv`).
* `byomei_to_icd10.csv`, `yj_to_atc.csv` — fallbacks when a vendor sends PRB-3 / RXE-2 without the alternate code.

Every sample code row says `verify`: the codes are synthetic and must be checked against the MEDIS 標準病名,
JLAC10 and YJ releases on site. A site loads its own licensed releases (TrialBox never ships them):

    python -m adapter.licensed load --kind medis  --file <病名基本テーブル> --version <release>
    python -m adapter.licensed load --kind jlac10 --file <JLAC10 file>   --version <release>
    python -m adapter.licensed load --kind yj     --file <HOT master>    --version <release>
    python -m adapter.licensed status

Files are CSV or tab-separated, Shift_JIS or UTF-8 (detected); columns are found by the vendors' header names, and a
release without a header row takes `--columns` in file order. Until a list is loaded its codes stay unknown (D-130);
the hospital-codes page says which lists are loaded. Sites with a HIS export instead of SS-MIX2 use `csv` or
`cgrd_sql` with `../templates/csv_site.yaml` and these lookups. `tools/ssmix2_export.py` writes a synthetic
hospital (`tools/synth_hospital`) as SS-MIX2 storage for tests.
