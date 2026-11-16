# D-957 An encounter atom needs a code; a diagnosis filed as one is a condition

- **Task:** G2 of the integrator's second review of the P1b run (#639, 2026-11-16). Four protocols (NCT00439478, NCT00674726, NCT01829659, NCT01855594) failed equivalence on the FHIR server's refusal (HTTP 422) of a compiled `encounter` atom.
  - The run's traces show the model filing diagnoses as encounters: "acute appendicitis", "atrial fibrillation", "major depressive disorder", "hemorrhagic stroke", 37 atoms in all.
  - The CQL asked whether `X.serviceType` was in a ValueSet with no code.

  **Date:** 2026-11-16. **Status:** reserved.
- **Decision** (`postprocess`):
  - **A diagnosis filed as an encounter is read as a condition**, as one filed as a procedure already is (`is_diagnosis_name`, flag `domain_refiled`).
  - **An encounter type with no code on the box is not compiled** (`logic_invalid`). A person reads it, or the notes do when the criterion is mixed and they can settle it (D-954).
- **Not in this card:** the terminology. 1,076 of the run's 1,220 extracted concepts have no code on the box; that is lane E's card.
- **Test:** `tests/unit/test_encounter_atoms_need_a_code.py`, using the run's own lines.
