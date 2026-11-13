# D-536 A drug code is ATC only when its coding's system is the ATC system

- **Task:** NEW-B-16 (a finding of lane E's review of #428, confirmed by running)
- **PR:** this branch (`agent/NEW-B-16-atc-is-the-atc-system`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** T-616 (the drug of an order: its codeable concept or its Medication), the OMOP loader's rule that
  its reading of a medication's codes and the lake flattener's must agree

## Context

The lake's flattener (`lake.flatten.Flattener.medication`) and the OMOP loader (`omop.load`) decided which coding
of a medication is its ATC code by asking whether the coding's `system` **contains the letters "atc"**. A house
code system whose address holds them is taken for ATC: `https://hospa.test/fhir/CodeSystem/batch-catalog`
("b-atc-h"), a path with `match`, `dispatch`, `patch`. Run on train 5: one order coded only in such a system gave
`atc = C10AA05, nhi_code = None`. The `atc` column is matched by prefix as ATC by the criteria that ask for a drug
class, so a house code that happens to begin like an ATC class would count as that class, and the order's real
code column was empty.

## Decision

1. **`lake.flatten.is_atc_system`**: a system is ATC when it is `http://www.whocc.no/atc` (whatever the scheme,
   the letter case or a trailing slash) or the system's OID (`urn:oid:2.16.840.1.113883.6.73`). Nothing else.
2. **Both readers use it**: the flattener and the OMOP loader (whose `atc_src` mark is what the OMOP-sourced lake
   reads its `atc` column from), so their two readings still agree.

## Consequences

- A code in a house system that holds the letters is the order's own code (`nhi_code`, the lake's "first code
  that is not ATC") and is no longer in `atc`. Every mapping the box ships names ATC as `http://www.whocc.no/atc`
  (checked: the only system in the repository's mappings, fixtures and reference data that contains "atc").
- A site that sent ATC under an address of its own (`https://hospital.example/atc`) loses its `atc` column until
  its mapping names the ATC system. That is the mapping saying what the code is, which is its job; the unmapped
  counter does not see it (the code is kept, in the other column).

## Not decided here

- The `nhi_code` column's name for "the first code that is not ATC", whatever its system.
- Other substring tests on a coding's system elsewhere in the flattener.
