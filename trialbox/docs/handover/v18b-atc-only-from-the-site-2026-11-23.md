# V-18b: ATC only from the site's own copy, and the FHIR store restarted after a terminology change (2026-11-23)

Lane V, card V-18b, on the integrator's rulings 7114273376 and the answer to 7114639597 on #639. Decision: D-1183.
It closes V18-07 and V18-01 of V-18 (`docs/handover/v18-code-systems-in-the-fhir-store-2026-11-23.md`). Findings:
`docs/handover/v18b-atc-only-from-the-site-2026-11-23/findings.json`.

## ATC (V18-07)

Before: the shipped `src/atc.csv` and `atc.parquet` (33 codes with WHOCC's English names; licence register row `atc`,
permission to ask) fed the compiler's mapper and `omop.concept`, while the FHIR store left them out.

Now:

- Both files are removed, and `tools/build_terminology.py` no longer builds them. The register row no longer names
  them; NOTICE says no ATC name is shipped.
- `atc` is no longer one of the mapper's shipped tables (`TABLE_FILES`): no file in a tables folder can feed it.
  When the site's `atc_index` is loaded, its substances take the shipped table's place in every step (the exact-name
  step and the candidates included), so a box with its own copy answers as the shipped table did.
- `Terminology.atc_source()` is the one source of ATC rows for the groupers:
  - the site's `atc_index` (its level-5 substances);
  - else codes only: the ATC column of the NHI drug lists and the exact codes of TrialBox's own groupers, named
    with the NHI ingredient when there is one, else with the code.
- The vocabulary loader and the resolver read their table names from a list and skip a missing file, so they needed
  no change: `omop.concept` gets ATC only from the tables loaded at install (`terminology_load`'s code lists).
- The FHIR store already took ATC only from `atc_index` (D-1182 point 2); without it, ATC is a line of
  `needed.jsonl`, never a fault.
- A grouper family the NHI lists hold no code of names its members itself: 16 exact rows in `src/synonyms.csv`
  (anticoagulant and 抗凝固薬: B01AA03, B01AE07, B01AF01 to B01AF03; biologic DMARD or JAK inhibitor and JAK
  inhibitor: L04AF01 to L04AF03). Without them those ValueSets lost these codes, and a patient on one of them would
  read "unknown" (a family member not listed, SCR-01) rather than a match.
- The grouper step now answers with a family alone (`if hits or fams`), so a family the site's copy and the NHI lists
  both lack still reaches the ValueSet.

## The shipped rule sets

`python -m tools.build_rulesets --check` before the change of `synonyms.csv`: 7 rule sets drifted, every medication
ValueSet empty. After: the same 15 ValueSets in 7 rule sets, each with the same codes; only the displays (the code
instead of WHOCC's name) and the content-hash version move. Their CQL and ELM follow; no SQL file, IR or test file
changes. `--recompile` wrote them. RA-JAK's `terminology_release` moves from `TR-7cedf1a45e79` to `TR-c5fac887e001`.

## The FHIR store's validation cache (V18-01)

Shown on the pinned image (`hapiproject/hapi:v8.12.0-2` on Postgres): a CodeSystem put as `v1` with code A, then as
`v2` with only B. Twenty seconds later `$lookup` of A still answered `v1` and `$validate-code` of A answered true.
`POST /$reindex-terminology` failed (HAPI-2072: Hibernate Search was not initialized). After `docker restart` the
store answered in 38 s: A not found, B found as `v2`.

So:

- `python -m tools.terminology_load changed --report R` names the systems a load stored anew (state `loaded`).
- `deploy/terminology-update.sh` then restarts `fhir-store` and waits, 15 s apart and up to 60 times, until compose
  reports it healthy; `restarted --report R --answered yes|no --seconds N` records it in the report
  (`store_restart`).
- An update's code-system step (`tools/trialbox/update.py`) does the same through its own runner; a failed restart is
  in the report, never a stop.
- The doctor's terminology line warns when a changed system was not followed by a restart, or the store did not
  answer again, and otherwise says when it restarted.

## Test assertions changed (the integrator's ruling (c))

- `test_licence_register.py::test_the_detector_sees_the_known_data_files`: the known data file `src/atc.csv` is
  replaced by `src/nhi_drug.csv`.
- `test_fhir_codesystems.py::test_a_system_its_licence_does_not_let_the_box_carry_is_skipped_with_the_reason`: the
  licence gate is shown on a file of the `atc` row (`drug_to_atc.csv`) instead of the shipped ATC; same assertion.
- `test_terminology_load.py::test_the_doctor_fails_when_the_terminology_changed_after_the_load`: its report records
  the store's restart, as the update step now writes it; same assertions.
- `test_parser_terminology_review.py::test_terminology_steps`: `allopurinol` was an exact match (WHOCC's name); it is
  now unmapped, and the exact step is shown on `rheumatology`.
- `test_h17_nhi_import_and_site_list.py`, three figures: with committed data only, 261 of 1,273 (was 266), medication
  1 (was 6), methods exact 3 and synonym 50 (were 9 and 49); with the extract medication 8 (was 13); with the
  50-line site list 391 (was 396), medication 23 (was 28). Six drug names matched WHOCC's names; methotrexate now
  resolves through TrialBox's own grouper.
- `test_refdata_jp.py`, two tests: the dictionary's drug names answer from a synthetic site ATC copy the test writes
  (made-up Z99 codes); PSL's code is that copy's prednisolone code (was H02AB06), and must be one code.
- `test_study_manifest.py::test_the_criteria_hash_of_a_shipped_study_is_its_golden`: RA-JAK's criteria hash is
  regenerated (`e1e9eed8...`; D-1366 still quotes the earlier one).

## Not in this card

- The ATC concepts an existing box loaded from the shipped table stay in `omop.concept` (V18b-01).
- Real ATC/DDD index releases: only the synthetic index the tests write was loaded.

## Run, and not run

- `tests/unit/test_v18b_atc_from_the_site.py` (6) and `tests/unit/test_v18b_store_restart.py` (6).
- The restart was shown by hand on the pinned store image (above); the script's restart was run with a stub docker,
  not on a box.
- `python -m tools.build_rulesets --check` after `--recompile`: equal.
