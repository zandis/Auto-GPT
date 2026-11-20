# D-1260 The owner's vocabulary rulings on the restored loader card: two named exceptions, ICD-O-3 names removed, the bridge notes reworded

- **Task:** lane J's vocabulary loader card, cards 22-2 and 22-4 of root review 22
  (`docs/reviews/2026-11-root/22-owner-vocabularies.md`), restored by the pull request that replaces PR #1093
- **Date:** 2026-11-19
- **Status:** accepted; the number was given by lane J's coordinator (lane J's block D-1220 to D-1319)
- **Builds on:** D-342 (no SNOMED CT ships in v1), STD-044 (the licence register), review 22 section 2 (the licence
  classes)

## Context

PR #1093 added the Athena loader's skip-and-report rule (22-2) and `tools/vocab_bundle_check.py` (22-4), which fails a
build when a vocabulary the register classes c (must not ship) reaches a shipped artefact. On master its check found
data that was already there:

- `catalogue/verification/evidence.json` holds OMOP concept ids tagged SNOMED (245) and CPT4 (6), with no code and
  no name. It also held 60 ICD-O-3 entries, each with its concept name.
- Its test fixture holds 3 SNOMED and 1 CPT4 ids.
- `catalogue/codes_checked.csv` has one ICD-O-3 topography code, `C50`, with no name.

Separately, the notes of the ICD-10 bridge file `libs/tb_common/refdata_src/icd10_who_cm_checked.csv` used wording
that matched WHO ICD-10 titles. Train 91 took #1093 off master (`a669b043`) while these were open.

## The owner's rulings

The owner's ruling of **2026-11-19** (integrator's comment on PR #639, issue comment 7001109992), verbatim:

> **Vocabulary (lane J, #1093):** the SNOMED and CPT4 concept ids stay as a named exception in the licence register;
> the 60 ICD-O-3 names are removed and their ids kept; the ICD-10 bridge file's notes are reworded so they carry no
> WHO wording. Restore the card in a new pull request with those changes, ready when `make vocab-bundle-check` exits
> 0 on its head merged with master.

### Applied by the same rule, confirmed by the owner 2026-11-19

`C50` in `catalogue/codes_checked.csv` (row `ph.breast_cancer`, system `ICD-O-3`) is an ICD-O-3 id with no name. It is
outside the 60 the ruling counted, so it was covered by the same principle: an ICD-O-3 id kept without a name. The owner
confirmed this to the coordinator on 2026-11-19, about 23:30 UTC. The coordinator recorded it on the replacing pull
request (comment 7025258538). The row and its system tag are unchanged.

## Decision

1. **The card is restored as it was**, by reverting `a669b043`, so no history is rewritten.
2. **Two named exceptions in the licence register.** They are register rows of kind `bundle-exception` with the new
   status `owner-approved` and the new column `excepts`. Neither is a scan allow-list or ignore entry.
   - `catalogue-evidence-concept-ids` (ruling 1): `excepts` is `SNOMED;CPT4`. Its files are
     `catalogue/verification/evidence.json` and `tests/fixtures/catalogue_verify/verification/evidence.json`.
   - `catalogue-icdo3-concept-ids` (ruling 2 and the confirmation above): `excepts` is `ICDO3:` followed by the 60
     concept ids and `C50`, named one by one. Its files are `catalogue/verification/evidence.json` and
     `catalogue/codes_checked.csv`, named without a wildcard.
3. **What an exception lets through.** `tools/vocab_bundle_check.py` lets through an entry of an excepted vocabulary
   only if all of these hold:
   - it carries no text (no key or column naming a name, display, description, definition, title, synonym,
     designation, term or text with a value);
   - where the row names ids, its id is one of them;
   - in a table, the row names ids.

   It fails any other vocabulary in those files, and any hit beyond the entries let through.
4. **Checking the register rows.** `tools/licence_register.py --check` accepts `excepts` only on an `owner-approved`
   row, and only for vocabularies some row names in `athena_never`. An `owner-approved` row must name its vocabularies.
5. **ICD-O-3 names removed, ids kept.** The 60 names are gone from the evidence file and from the six places
   `catalogue/phenotype_icd10cm.csv` quoted them. `ICDO3` joins `NAMELESS_VOCABULARIES` in
   `tools/catalogue_verify.py`, so a refresh keeps them out.
6. **The bridge notes are reworded.** All 36 notes are rewritten in TrialBox's own plain words. Each says only how the
   WHO category maps to the CM one: one to one, or inside a wider CM category, naming codes only.
7. **NOTICE** names both exceptions.

## Tests

`tests/unit/test_vocab_owner_rulings.py` holds one or more tests per ruling:
- the two register rows, their files and ids;
- SNOMED, CPT4 and ICD-O-3 entries carry ids only;
- the same 60 ICD-O-3 ids are kept, and `C50` with its tag;
- no ICD-O-3 name remains in the catalogue or its fixtures;
- a refresh keeps ICD-O-3 nameless;
- no former bridge note, title or bracketed part remains.

The removed names and notes are pinned by sha256 only, never as text.

`tests/unit/test_vocab_bundle_check_22_4.py` tests the exception mechanism.

`make vocab-bundle-check` exits 0.
