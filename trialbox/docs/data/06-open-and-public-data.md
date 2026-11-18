# 6. Open and public data in the tests

| Data | Use | Licence | Where |
| --- | --- | --- | --- |
| Synthetic hospital (`tools.synth_hospital`) | every gate: JP and TW sites, notes in ja, zh-TW and en, planted findings | ours, all fictional | generated |
| Synthetic sites A and B (`tools/make_fixtures.py`) | unit and integration tests, 600 + 520 patients | ours | `tests/fixtures/` |
| SIGIR 2016 patient descriptions (TrialGPT) | the public site's English notes | CC BY-SA 4.0 (Koopman and Zuccon, CSIRO); the criterion labels beside them: US government work, public domain | `eval/criterion_ml/NOTICE.md`, `eval/criterion_ml/LICENSE.NCBI` |
| NTCIR-16 MedTxt-CR and MedTxt-RR | the public site's Japanese notes | CC BY 4.0 (Sociocom, NAIST) | fetched to `.cache/medtxt`, never committed |
| MIMIC-IV Clinical Database Demo on FHIR v2.1.0 | the open-data test | ODbL 1.0 | fetched to `.cache/open_data/`, never committed |
| ClinicalTrials.gov NCT04157751, NCT02568722 | open-data test rulesets | public registry | `tests/fixtures/open_data/` |
| TREC Clinical Trials 2021/22 | N-12 | NIST qrels, NCBI corpus | fetched by `tools/trec_ct_eval.py` |

The public site (`tools/public_site.py`) keeps every note verbatim; age, sex and diagnoses are derived from the text
by fixed rules; chart numbers, visit dates and staff are placed. Its `PROVENANCE.md` says which is which.
ClinicalTrials.gov records in the cassettes are fictional (`NCT990000xx`, titled `[SYNTHETIC]`).

**MIMIC notice.** The open-data test uses the MIMIC-IV Clinical Database Demo on FHIR under the Open Data Commons
Open Database License v1.0. Cite: Bennett A, Ulrich H, Wiedekopf J, Szul P, Grimes J, Johnson A. MIMIC-IV Clinical
Database Demo on FHIR (version 2.1.0). PhysioNet (2025). DOI 10.13026/vphg-y548. Also Bennett AM et al., JAMIA
2023;30(4):718–25; Johnson AEW et al., Sci Data 2023;10:1; Pollard T et al., PhysioNet, Nature Health (2026). A
database derived from the demo falls under the ODbL share-alike terms; the derived lake stays in `.cache/`.

How the MIMIC data is normalised and what the test found: [Validation §5](../VALIDATION.md#5-the-open-data-test).
