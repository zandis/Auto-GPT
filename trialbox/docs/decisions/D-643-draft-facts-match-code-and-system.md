# D-643 The facts of an NHI draft match a record by its code and its code system

- **Task:** a finding recorded for lane A in the integrator's brief of 2026-11-12 ("`services/orchestrator/facts.py:72`
  matches a diagnosis by code without its code system"; the file is `services/orchestrator/scenarios/facts.py`)
- **PR:** this branch (`agent/FACT-code-system`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on a green train)

## Context

`facts.collect` gathers what an NHI application draft and a TWPAS bundle show about a patient: the diagnosis and
its date, the hepatitis B and tuberculosis screening results, the chest X-ray, the DAS28 components. Its own text
says it reads "exactly the data the criteria were evaluated on". It matched records by the ValueSet's code strings
alone. The ruleset's compiled SQL matches the code system too (`vs.system = x.system AND vs.code = x.code`).

Run here on RA-BIO with a synthetic patient: a condition coded `M05.9` under a house code system in 2011 and under
ICD-10-CM in 2020 gave the draft "diagnosed 2011-03-01"; a house lab code `5196-1` newer than the LOINC HBsAg result
gave "HBsAg positive" where the LOINC result was negative; a house `TJC28` gave a tender joint count of 28.

## Decision

Every lookup in `facts.py` of a table that carries a code system (`condition`, `observation`, `report`) compares
the record's `system|code` with the ValueSet's `system|code` pairs (`_pairs`), and the DAS28 components with the
pairs of `tb_common.derived.CODES`. A record with no system matches nothing, as in the compiled SQL.
`medication.atc` holds one system by construction and is matched by code as before.

## What this does not do

- It does not read the ValueSet's family rule (`vsf`: a code inside a grouper's family but outside its list): the
  draft shows a coded diagnosis only for a listed code, as before.
- The draft's wording and layout are unchanged.

## Test

`tests/unit/test_facts_code_system.py` (a DuckDB stand-in for the lake, RA-BIO): the diagnosis is the ICD-10-CM
one; a house code alone is no diagnosis; a screening result and a report under another system are not shown; a
DAS28 component under another system is not counted.
