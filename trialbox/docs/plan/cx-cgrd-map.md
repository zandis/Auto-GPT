# Taiwan SQL-view door mapping metadata

Card: cx-cgrd-map. Decision: none yet (the integrator allocates the number).

The template retains its read-only view contract. Its source metadata catalogue records table domains,
priorities, schema column counts and guarded identifier columns. It is not an instruction to read raw tables.
Views must drop or tokenize those columns; existing identity handling is unchanged. No patient rows were imported.

## Reference scope

The diagnosis table contains 1,972 code pairs selected by exact codes in rule value sets and synthetic generator
literals, plus the test's I10 code. It keeps all targets for a selected code. The mapper requires the declared
ICD edition and exactly one target in the requested vocabulary. Unknown and ambiguous codes retain their source
coding and are reported as unmapped. Dotless and dotted lookup inputs are equivalent within that edition.

The generic lab table contains 48 source-to-LOINC pairs. The configured table has 58 entries, combining these
with the door's existing aliases. Units come from the existing lookup or the repository's catalogue/items.csv;
13 analytes lack unit evidence and carry UNKNOWN, yielding no numeric value even with a missing source unit.
Existing unit spelling normalization and explicit conversion factors remain in use. No automatic molar conversion
was added. Existing ESR behavior is retained; the source's different pair is visible in tw_lab_standard.csv.

The drug reference parser uses columns 1 and 16, drops names, requires a full ATC code, and rejects conflicting
answers. The SQL export joins valid ATC-to-standard-RxNorm relationships and writes code pairs only. The shipped
drug table is empty because no drug export exists in the permitted mapping folder. The end-to-end test supplies
explicit synthetic pairs. Multiple targets remain unmapped; an ATC class is never guessed to be an ingredient.

## Provenance and omissions

Sources were two read-only folders of the owner's earlier mapping project (its table-control files and its
concept-mapping folder). Ported sources, relative to those folders:

- control: cgrd_tables.yaml and cgrd_tables.seed.yaml: schema metadata and identifier guards.
- concept-mapping: maps/cgrd_dssid_mapped.csv and sql/10_dx_crosswalk.sql: diagnosis pairs and lookup logic.
- concept-mapping: maps/lab_loinc.csv and build_lab_loinc.py: generic analyte pairs; no heuristic suffix stripping.
- concept-mapping: load_nhi_drug.py: reference column positions and relationship join logic.
- concept-mapping: maps/VOCAB_VERSIONS.txt: vocabulary IDs and versions in the template.
- concept-mapping: extract_cgrd_dx.py: diagnosis column metadata only; never executed.
- concept-mapping: MAPPING_STATUS.md: target vocabulary and lab-column evidence only; no coverage counts retained.

Dropped all usage counts, concept names, source descriptions, departments, system names, operational load status,
unneeded diagnosis rows and local identifying values. No distinct-code frequency export or patient file was read.
No external scripts, database connections or network calls were run. No vocabulary dump was copied.

## Checks and limitations

The 16 unit cases pass under the repository's test runner. The night test needs the test database and is run by
the gate; it was not run on the machine that wrote it. No test was skipped, weakened or gated.
The new night test checks diagnosis, drug and lab codings in the lake snapshot. Full Linux gates remain required.

No existing assertion changes are requested. No rule value sets or date windows changed. The mapping-file writer
uses flush, fsync and rename. No new script is called by path; commands use python -m. Files outside the mapping
template are its engine builder, reference parser, stand-in mapping copier, tests and this card's records.

## Findings

The source export contains no ICD-9 rows; only synthetic ICD-9 tests and the ported SQL logic can be supplied.
The source ESR pair is 30341-2 while the existing door alias uses 4537-7; resolving that clinical distinction needs
review. The source provides no units for its generic analytes and no drug crosswalk export. These gaps are explicit,
not filled with inferred mappings. Findings are recorded in cx-cgrd-map/findings.json.

Final checks: doclint, limits and decisions checks pass; the changed files pass the data scan.

The diagnosis export omits target vocabulary. MAPPING_STATUS.md identifies SNOMED as its intended target.
Pairs with nonnumeric extension codes were withheld together with every other target for the same source code,
so filtering cannot turn an ambiguous answer into a unique one. Those codes need a vocabulary-qualified export.
