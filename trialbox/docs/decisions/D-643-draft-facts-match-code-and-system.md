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
`medication.atc` is matched by code as before: the column holds the code of any coding whose system names ATC
(`lake/flatten.py`, `omop/load.py`), and the compiled SQL reads it the same way, so the draft and the criteria
agree.

The TWPAS bundle's own three lookups (`twpas._latest`: body weight, height, the EGFR mutation result) name their
system too: LOINC for the two, the clinical-score system for `EGFR-MUT`, as ONC-OSI's `VS_EGFR_MUTATION` does. The
review of this card found them still matched by code alone: a newer house row gave 6.1 kg for 61 kg, a house
`EGFR-MUT` alone gave "mutation present". A ValueSet include that names no system gives no pair.

## What this does not do

- **The EDC pre-fill** (`services/edc/prefill.py:65-69, 136-144`, lane E) still selects observation, condition and
  medication rows without their system and matches by code (a condition and an ATC code by a prefix). It drafts
  eCRF values with a citation for a coordinator. Found by reading in the review of this card; not changed here.
- Neither the draft nor the compiled SQL folds two spellings of one system (an OID, `https`, a trailing slash,
  another case): a site that sends one loses the fact in both alike. The review ran eleven variants; the two agree.
- The pair is written `system|code`: a system or a code that itself holds `|` could be read two ways. No committed
  ValueSet has one.

- It does not read the ValueSet's family rule (`vsf`: a code inside a grouper's family but outside its list): the
  draft shows a coded diagnosis only for a listed code, as before.
- The draft's wording and layout are unchanged.

## Test

`tests/unit/test_facts_code_system.py` (a DuckDB stand-in for the lake, RA-BIO): the diagnosis is the ICD-10-CM
one; a house code alone is no diagnosis; a screening result and a report under another system are not shown; a
DAS28 component under another system is not counted; the TWPAS bundle's weight and EGFR result; an include with no
system. The review also compared the facts of 45 patients before and after on a real synthetic lake, from both lake
sources (RA-BIO), and legacy for ONC-OSI: no fact disappeared or changed.
