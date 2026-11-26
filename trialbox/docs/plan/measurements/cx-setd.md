# cx-setd: constructed coded and note evidence

The generator is `tools/set_d.py`; tests are `tests/unit/test_set_d.py`.
All records are synthetic. No external card text is stored here.

## Scope and use

Run from the project directory with the library and service directories on the import path:

```text
python -m tools.set_d --out eval/set-d --seed 42 --anchor 2026-11-01
```

The anchor is required; no wall clock supplies evidence dates. `--counts` accepts a JSON object of cell counts.
The total must be positive and divisible by four. Defaults are 600 agreeing, 400 note-adds, 500 conflicting,
300 missing, 300 stale and 300 note-only pairs. These yield 600 patients and 2,400 pairs.
Each patient has four criteria and one note language, cycling English, Japanese and Traditional Chinese.

The four synthetic criterion configurations are gout diagnosis, serum urate at least 7 mg/dL within 365 days,
rheumatoid-arthritis diagnosis and methotrexate exposure at the anchor. The last is an exposure component,
not the full background-therapy card. Classification, disease duration, dose and stable-dose requirements are
outside this generator's scope. The read-only cards informed these configurations; no card parser or copied
card fixture is shipped. Decision number needed for this choice of four component criteria.

## Construction and formats

One seeded sequence chooses hidden facts and allocates cells. The hidden event is retained alongside the damage
description, coded evidence, note evidence and expected answer. Missing means neither source supplies an answer;
note-only removes coded evidence; note-adds keeps an uncertain coded record. Conflicts reverse the note's
assertion in both directions. Stale cases include old no-history followed by a new diagnosis, resolved diagnoses,
old, undated, pending and unconvertible labs, and exposure stops and supply boundaries.

The generator reuses `imperfect_feed` table schemas, row identifiers and CSV encoding, and `synth_hospital` note
round-trip checks. It follows the CSV landing-table approach also used by `hospital_sim`; it does not import that
simulation's platform-dependent measurement harness or run the full nightly pipeline.

The CSV files load through the existing `CsvSource` reader. `gold.json` contains the complete record, including
LOINC codes, reference ranges, order/dispense/claim/administration provenance, days of supply, explicit stops,
allergies and visits. The legacy CSV columns cannot retain all those distinctions. Consumers evaluating set D
must use the rich evidence in this sidecar, not infer gold labels from the lossy CSV projection alone.
Evidence lists retain both sides newest first. Each file is flushed, fsynced and replaced; on supported systems
the directory is fsynced too. The folder as a whole is not a transactional snapshot.

## Rules and verification

Coded evidence decides first. A usable note can fill an unknown answer; opposing usable evidence produces
unknown. Earlier no-history does not contradict a later confirmed diagnosis. Suspected, rule-out, resolved,
pending, PRN and refill evidence cannot establish an answer. Labs require a dated convertible value within
365 days, inclusive. Exposure ranks administration above dispense or claim, above order, above statement.
A dated stop ends exposure that day; only supply exhaustion receives the inclusive 30-day grace.
Both methotrexate codes in the inspected card are exercised. No broader drug-class value set is claimed.

Seven tests pass with shared setup disabled using `--noconftest`: exact counts and an independent oracle over all
2,400 pairs; three byte comparisons and the CSV reader; configurable counts; source ranks and supply boundaries;
hidden facts and patient context; old no-history with a newer diagnosis; and note assertion polarity.
Before implementation, collection failed because the module was absent. Additional coverage tests failed for
missing competing sources, missing patient context and missing old-no-history cases before those were implemented.
A further failing test caught affirmative wording on negative note-only facts; the template now preserves polarity.

The normal run cannot load the database wrapper on this machine. Isolating only the parent setup still reaches
a unit setup dependency on a platform-specific file-lock module. The seven test bodies run without those shared
fixtures; this is not evidence that the normal suite passes. The configured timeout plugin and lint formatter
are also unavailable. Full standard gates remain for the integration environment.

Document lint passed with 88 warnings; limits lint passed with 106 literals; the decisions index passed with
1,030 decisions. The data scan reported 129 hits across the existing tree, including unreadable archived outputs;
no scan exception was added. These counts are local command results, not a clean full-gate claim.
Text-key validation is blocked by the file-lock import. Static security scanning lacks its tool; secret scanning
failed with the platform's command-length error (206).
The scan-ignore inventory ran; no inventory entries were changed.

The local isolated command was:

```text
python -m pytest tests/unit/test_set_d.py --noconftest -o "markers=nodb: pure test" -p no:cacheprovider --basetemp=eval/set-d-test
```

Added test names:

- `test_gold_counts_and_independent_oracle`
- `test_seed_bytes_and_feed_reader`
- `test_configurable_counts`
- `test_exposure_ranks_stops_and_supply_boundaries`
- `test_hidden_history_and_patient_context`
- `test_newer_diagnosis_supersedes_old_no_history`
- `test_note_words_preserve_assertion_polarity`

No existing assertions were changed. No product services, scan exceptions, findings register or history changed.
No new script is invoked by path; the command uses module execution. No unrelated product defect was established.
