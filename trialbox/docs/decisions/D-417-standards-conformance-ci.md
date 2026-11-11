# D-417 Standards conformance in CI: TW Core slices, the JP Core 1.2.0 diff, the HL7 validator job, the CQL path

- **Task:** T-619a (`docs/plan/28-master-plan-v6.md` §6.2.5)
- **PR:** this branch (`agent/T-619a-standards-ci`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** STD-011, STD-017 (the diff; the version is the Japan site's choice), STD-070; T-STD-05, T-STD-11; the CQL
  half of the comparator gap (CR-001, CR-098 note, CR-115) for direct observation comparisons
- **Builds on:** D-137 (JP Core rules), D-142 (censored values in SQL), D-321 (local CQL engine), D-342 (no SNOMED CT),
  D-400 (T-616: inbound contract, therapy period from `boundsPeriod`)

## Context

The TW mapping claimed TW Core profiles but wrote TrialBox code system URIs, so no TW Core slice was ever filled (open
slicing let it pass). JP Core was one version behind and nobody had compared. CI never ran the HL7 validator, never
translated or evaluated the committed CQL, and the CQL ignored `Quantity.comparator`. An observation stamped
`23:30Z` fell on one day for CQL (its own offset) and on the next for SQL (the site zone).

## Decision

1. **TW Core slices** (`tw_core/demo_his.yaml`, `fhir_profiles: tw-core`). Beside the codings the lake reads (always
   first), the TW mapping writes TW Core's own code systems: ICD-10-CM TW 2014 edition for a diagnosis dated before
   2025-01-01 and the 2023 edition from then on (`when: date_before / date_from`, new in the mapping engine); NHI drug
   codes (`medication-nhi-tw`); NHI service codes (`medical-service-payment-tw`); the NHI department for ONC (`AF`).
   TW Core binds the other departments to SNOMED CT, which TrialBox does not ship (D-342), so they keep the local
   coding only. The patient identifier gets type v2-0203 `ANON` (it is TrialBox's pseudonym, not the record number).
   `when: {fhir_profiles: tw-core}` keeps all of this out of the JP mapping, which extends the TW one.
2. **`boundsPeriod`.** The TW mapping writes the therapy period in `dosageInstruction[0].timing.repeat.boundsPeriod`
   (T-616 reads it first) and still in `dispenseRequest.validityPeriod` (the CQL and the structural check read it).
3. **TW Core rule file.** `tools/jpcore_rules.py --ig tw` builds `services/adapter/validate/twcore_rules.json` from the
   pinned TW Core 1.0.0 package with the generator of the JP rules (profiles, slices, bound value sets). SNOMED CT
   codes are never copied into a rule file (their value sets keep only their systems). CI checks both files are what
   their packages give.
4. **JP Core 1.2.0.** Not on the FHIR registries; JAMI publishes `jp-core.r4-1.2.0.tgz` on jpfhir.jp (pinned sha256 and
   sha1 of the 2026-11-11 download). `--version 1.2.0 --diff` prints the change against the pinned 1.1.0 rules; CI
   prints it as information. The 2026-11-11 diff: 112 lines. `JP_MedicationRequestBase` is gone (JP_MedicationRequest
   and the injection profile derive from base MedicationRequest and gain identifier slices `requestIdentifier`,
   `rpNumber`, `prescriptionIdentifierCommon`, `authoredOn` and dispense extensions); JP_Coverage gains insurance
   identifier slices; the body-measurement and vital-signs category slices are split; the release package carries
   no terminology, so 1.1.0's value sets are listed as gone. The pin stays 1.1.0 until the Japan site names the
   version its FHIR plans use (the owner's question, STD-017).
5. **One offset at ingest (STD-070).** `adapter.instants.to_site_offset` writes every date-time that has a time and an
   offset as the same instant in the site zone, once, after the read step of every source (mapping and FHIR bulk).
   The instant never changes; only its written offset does. This replaces D-400 point 6's "keeps it" for what the
   snapshot holds: the engine still parses the stated offset (the instant is right), the snapshot writes it in the
   site's. The ingest audit counts the values rewritten (`instants_to_site_offset`).
6. **CQL reads the comparator.** The CQL generator compares a censored result as the SQL does (D-142's table): `<`
   and `<=` decide only below the bound, `>` and `>=` only above it, else null; no comparator (or `ad`) is the plain
   comparison. GZQO and GOUT-COH were recompiled (CQL and ELM); the other rulesets have no direct observation
   comparison and are unchanged. The recorded verdicts did not move (the fixtures have no censored result).
7. **CI job `standards`** (GitHub-hosted, no paid service): `make jvm-deps` (the unit job's cache), the local CQL
   engine (its own cache, Maven tried three times), the rule-file checks, the JP Core diff, `tools/twcore_check.py`
   (HL7 validator 6.10.4, TW Core 1.0.0, 200 mapped synthetic resources: 0 errors and each fillable slice matched)
   and `tools/cql_path_check.py` (the five rulesets with a test set translated with the pinned jars, ELM equal to the
   committed; evaluated by the local engine as `tests/expected.json` records, which is also the SQL's oracle; the
   edge fixture of `criteria_compiler.equivalence.edge` through both engines). Every package download is retried.

## Consequences

- The validator matches the ICD-10-CM 2014, NHI drug, NHI service and NHI department slices. The 2023 ICD-10-CM slice
  cannot be shown offline: its value set filters on `USE = 1`, and the package's extract of the code system has 11
  codes. The job reports it and does not fail on it.
- The HL7 validator 6.10.4 keeps state inside one run: after a body-height Observation it fails every later
  DocumentReference's `contentType`. The job validates notes in a run of their own. The ingest's nightly sample
  (`Hl7Validator` in the pipeline) runs everything in one call and can show the same false error.
- `tools/cql_local/pom.xml` had `--fetch` inside an XML comment, which Maven refuses: `cql_eval --fetch` could not
  run. Fixed, so the engine tests of `test_cql_eval.py` can run where the jars are fetched.
- Not done: an offline TW Core validator that reads `twcore_rules.json` as `jpcore.py` reads the JP rules; the
  comparator in derived scores (DAS28, CDAI) on the CQL side; SNOMED CT department codes (licence).
