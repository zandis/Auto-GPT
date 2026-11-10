# D-314 Japan's ICD-10 is WHO ICD-10: the WHO URI on every JP Condition, the ICD-10-CM twin only for the same code, WHO-only categories in the groupers

**D-314 A Japanese diagnosis keeps its WHO ICD-10 code under `http://hl7.org/fhir/sid/icd-10`; it is also given as
ICD-10-CM only where ICD-10-CM has the very same code; the compiler's groupers stand for the WHO-only categories
(E14, I64, F00, B24, C97), so such a record makes the criterion unknown, never false.**
Task T-614 (wave 2 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2.5; T-STD-01 of the 2026-11-10 deep review).
Closes STD-010. Branch `agent/T-614-japan-icd10`. Date 2026-11-10. Builds on D-113, D-130, D-137 and D-301.

## The problem

Japan codes diagnoses in WHO ICD-10 (2013, through MEDIS 標準病名), not ICD-10-CM. The JP mapping extended the TW
one and wrote every Japanese code under the ICD-10-CM URI; the SS-MIX2 reader dropped a licensed MEDIS target that
ICD-10-CM does not have. A WHO-only code (`E14.9` unspecified diabetes, `I64` stroke not specified, `F00.1` dementia
in Alzheimer's disease) then sat in the lake as an ICD-10-CM code outside every grouper's family, so "type 2 diabetes"
or "stroke" was a silent false for that patient.

## Decision

* **The reader** (`adapter/sources/ssmix2/source.py`) keeps the WHO code: PRB-3's I10 alternate, else the licensed
  MEDIS target (kept even when ICD-10-CM has no such code), else `byomei_to_icd10.csv`. The code is written one way
  (`who_icd10`: upper case, no blanks, the dagger or asterisk mark dropped, the dot after the category: `e149` is
  `E14.9`). It fills two columns: `icd10`, the WHO code, always; `icd10cm`, the same code only when the full
  ICD-10-CM list (D-122) has it (D-137's rule, already used for the MEDIS master's links). A code not shaped like a
  WHO code is counted (`diagnosis:not a WHO ICD-10 shape`), never changed.
* **The JP mapping** (`mapping/jp_core/ssmix2_site.yaml`) writes the ICD-10-CM coding first when there is one, then
  the WHO coding (always), then the 標準病名 code. The lake reads the first coding, so a code that is the same in both
  systems matches the ICD-10-CM groupers as before, and a WHO-only code reaches the lake under the WHO URI.
* **JP Core `$validate`** (`adapter/validate/jpcore.py`) accepts the WHO URI. A code under it not written as a WHO code
  (`C50.911`, `M1A.9XX0`: ICD-10-CM shapes) is a warning, not an error, so the synthetic SS-MIX2 hospital, whose codes
  come from the shared ICD-10-CM catalogue, still has 0 errors.
* **The grouper table** (`criteria_compiler/terminology/mapper.py`, `WHO_ONLY_CATEGORIES`): each WHO-only category
  names the ICD-10-CM categories whose groupers it belongs with (E14 with E08 to E13; I64 with I60 to I63; F00 with
  F01 to F03 and G30; B24 with B20; C97 with C80 and with any family that is its prefix, such as malignancy's C9). A
  grouper's ICD-10-CM families gain the matching `(WHO URI, category)` families. Both engines already read families
  with their system (D-113), so a record coded `E14.9` under the WHO URI is inside the family and outside the list:
  the criterion is unknown, for an inclusion and for an exclusion. No generator is edited.
* Only WHO-only categories are added, never a WHO twin of an ICD-10-CM family: the twin changes the D-130 oracle
  (D-301, "Not done here"), and these categories have no ICD-10-CM code, so no ICD-10-CM record and no oracle row
  moves. Families do not enter `known_systems`, so D-130 still holds a WHO-coded row outside every family for review.

## Not done here, and why

* A WHO code that ICD-10-CM lacks but whose category ICD-10-CM has (`C34.1`, `K85.9`, `E11.7`) reaches the lake under
  the WHO URI and is outside the ICD-10-CM family by system: the SQL says false and D-130 turns an inclusion unknown;
  an exclusion stays false. Closing that needs the WHO family clause in the SQL and CQL generators (D-301's engine
  half, the strict xfail tests in `tests/unit/test_valueset_family.py`), which belong to the critical-issues fix
  groups.
* The WHO-only list is the categories the review named and their neighbours; the rest of the MEDIS file's WHO-only
  categories are not derived from a loaded release yet.
* The synthetic SS-MIX2 export (`tools/ssmix2_export.py`, T-615a's file) still writes ICD-10-CM codes from the shared
  catalogue as the I10 alternate; JP Core lists the ICD-10-CM-shaped ones as warnings.
