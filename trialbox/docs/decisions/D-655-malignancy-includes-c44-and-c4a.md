# D-655 "Malignancy" includes skin carcinoma (C44) and Merkel cell carcinoma (C4A); its exception is the criterion's

- **Task:** SCR-01 (lane G's deep review of 2026-11-13, Critical), routed by the owner through the integrator
- **PR:** this branch (`agent/SCR-01-malignancy-c44-c4a`), cut from master (`2c76e9da`)
- **Date:** 2026-11-14
- **Status:** proposed (merges on a green train). **RA-JAK, RA-BIO and GZQO need the owner's re-approval**: their
  value sets, SQL and CQL change; no lane approves a ruleset.
- **Builds on:** D-113 (a code in a grouper's family but not listed is unknown), D-122 (a grouper expands over the
  full ICD-10-CM list), T-613a / D-322 (the offline recompile and drift check)

## Context

The terminology grouper "malignancy" (`terminology/src/synonyms.csv`) listed ICD-10-CM families C0 to C9 but not
C44 (other malignant neoplasm of skin: basal and squamous cell carcinoma) and not C4A (Merkel cell carcinoma). A
code outside list and families is a plain non-match: the compiled SQL answered FALSE. So "Malignancy within the
past 5 years" (RA-JAK-EXC-08, RA-BIO-EXC-04) did **not** exclude a patient with such a carcinoma: a silent wrong
inclusion. C44 had been left out for one criterion's sake, GZQO's "except non-melanoma skin cancer"; C4A was never
there. A personal history code (Z85) and the neoplasms malignant by behaviour (D45 polycythaemia vera, D46
myelodysplastic syndromes, D47) were a silent FALSE too.

Confirmed by running before the change (`tests/unit/test_malignancy_c44_c4a.py`): the shipped value sets of the
three rulesets lack C4A and (for RA-JAK and RA-BIO) C44; the compiled SQL answers FALSE for C44.91, C4A.0, Z85.3,
D45 and D46.9.

## Decision

1. **The grouper "malignancy"** gains the families C44 and C4A, and four codes that are malignancies only sometimes
   or in the past (Z85, D45, D46, D47) as family members that are **not listed**: a new match kind `family` in the
   grouper table (the mapper adds the family, expands no code). By D-113 a record with such a code makes the answer
   unknown, and a person looks; never a silent "no malignancy".
2. **The exception is the criterion's.** A second grouper concept, "malignancy except non-melanoma skin cancer",
   is the same without C44. GZQO-EXC-07 ("Malignancy within the past 5 years, except non-melanoma skin cancer")
   uses it: its extraction cassette names that concept, its approved IR names the value set
   `VS_MALIGNANCY_EXCEPT_NON_MELANOMA_SKIN_CANCER`, and its old `VS_MALIGNANCY` is gone from GZQO.
3. **Recompiled offline** (`tools.build_rulesets --recompile RA-JAK RA-BIO GZQO`); `--check` passes for every
   shipped ruleset. The IR's logic, the manifests and the recorded tests are kept, but for the one change below.

## Which decisions change

| Criterion | A record in the window coded | Before | After |
| --- | --- | --- | --- |
| RA-JAK-EXC-08, RA-BIO-EXC-04 ("Malignancy within the past 5 years") | C44.x (basal or squamous cell carcinoma of skin) | not met: the patient stays eligible | **met: excluded** |
| same | C4A.x (Merkel cell carcinoma) | not met | **met: excluded** |
| same | Z85.x, D45, D46.x, D47.x | not met | **unknown: kept for review** |
| GZQO-EXC-07 ("… except non-melanoma skin cancer") | C44.x | not met | not met (as the criterion says) |
| same | C4A.x | not met | **met: excluded** |
| same | Z85.x, D45, D46.x, D47.x | not met | **unknown: kept for review** |

An undated record with these codes follows the same list (the undated check reads the same value set).

On the recorded test sets: two RA-BIO patients of synthetic site A (MRN 10000156 and 10000396, each with C44.91)
change on RA-BIO-EXC-04 from not met to met; `rulesets/RA-BIO/tests/expected.json` records it (the CQL of the
recompiled ruleset reads the same value set; it was not re-run on HAPI here). GZQO's two C44.91 patients do not
change. RA-JAK's test set is of another synthetic site and holds none of these codes.

Any study compiled after this on a box (a site's own protocol) gets the new grouper: "malignancy" includes C44
and C4A unless the criterion says otherwise and the compile names the exception.

## Also changed, because they held the old list as a fact

- `tests/unit/test_valueset_family.py` and the off-list fixture (`tests/fixtures/equivalence/offlist`): their
  patient "outside every malignancy family" had C44.91; it now has D22.5 (a benign naevus), so the tests keep
  their meaning.
- `tools/scenarios.py`: the hand-written oracle of the site study ("any history of malignancy") counted C44 out
  and did not know C4A; it now counts both, and Z85 / D45 to D47 as unknown.

## Test

`tests/unit/test_malignancy_c44_c4a.py`: the three shipped value sets (C4A listed and in the families; C44 in
RA-JAK and RA-BIO, not in GZQO; Z85 and D45 to D47 in the families, not listed); the compiled SQL for both concepts
(C44, C4A, C43, Z85, D46, D45, a gout code); the shipped lists equal what the grouper gives today.
