# JP Core mapping (Japan sites)

* `ssmix2_site.yaml` — template for a site that exposes SS-MIX2 standardized storage (`--source ssmix2`, D-122).
  The reader reads ADT-00 (patient), ADT-12/22 (visits), PPR-01 (標準病名 with ICD-10), OMP-01/02 (YJ with ATC)
  and OML-11 (JLAC10 results); everything else (vitals, notes, reports, claims, registry) comes from the extended
  storage CSVs under `<root>/extended/`.
* `jlac10_to_loinc.csv` — JLAC10 → LOINC for the lab results (same columns as `tw_core/lab_local_to_loinc.csv`).
* `byomei_to_icd10.csv`, `yj_to_atc.csv` — fallbacks when a vendor sends PRB-3 / RXE-2 without the alternate code.

Every sample code row says `verify`: the codes are synthetic and must be checked against the MEDIS 標準病名,
JLAC10 and YJ releases on site. Sites with a HIS export instead of SS-MIX2 use `csv` or `cgrd_sql` with
`../templates/csv_site.yaml` and these lookups. `tools/ssmix2_export.py` writes a synthetic hospital
(`tools/synth_hospital`) as SS-MIX2 storage for tests.
