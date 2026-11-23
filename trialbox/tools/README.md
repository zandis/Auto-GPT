# Tools

The commands under `tools/` are run from `trialbox/` with the product's environment (`make venv`); each says what it
does in its own first lines (`python -m tools.<name> --help`). This page holds the sections that need more than that.

## The owner's code dictionaries

`tools/owner_code_dictionaries.py` runs the mapping check of `tools/mapping_coverage.py` on a hospital's own code
dictionaries and writes only a summary. The design and the figures it is compared with are in
`docs/plan/design/site-data-requirements.md`.

**Where it runs.** Only on the machine that holds the dictionaries (the owner's own machine). Copy nothing of the
hospital's into this repository, a pull request, an issue or a cloud session: not the dictionaries, not the
configuration file that names them, not a refused file's message. Only the summary file may leave, after the owner
has read it.

**What it reads.** Code dictionaries: one row per code (the lab-item table, the order or procedure table, the
department table, the diagnosis table, the drug master). Never a table of patients, visits, results or orders.

**What it refuses** (exit 2, nothing written):

- a file with a column whose header names a patient identifier or a person's details (chart number, patient id,
  national id, a person's name, birth date, telephone, address; in English, Japanese and Traditional Chinese);
- a file with a cell shaped like a Taiwanese national identity number;
- a file in which more than a fifth of the rows repeat a code (a table of events, not a dictionary);
- a system that does not belong to the table's kind (a lab system for the drug table).

The message names the table's position, the column header or the line number, never a value of a cell.

**How to run it.** Name each table as `kind:system:file:code_column,name_column[,target_column]`, or list them in a
JSON file:

    .venv/bin/python tools/owner_code_dictionaries.py --config tables.json --out summary.json

    {
      "tables": [
        {"kind": "diagnosis", "system": "icd-10-cm", "file": "dx.csv", "code": "ICD_CODE", "name": "DX_NAME"},
        {"kind": "lab", "system": "local-lab", "file": "lab_items.tsv", "code": "ITEM", "name": "ITEM_NAME"},
        {"kind": "drug", "system": "nhi-drug", "file": "drugs.csv", "code": "NHI_CODE", "name": "NAME", "target": "ATC"},
        {"kind": "order", "system": "nhi-order", "file": "orders.csv", "code": "CODE", "name": "NAME"},
        {"kind": "department", "system": "local-department", "file": "dept.csv", "code": "DEPT", "name": "NAME"}
      ],
      "lab_lookup": "lab_local_to_loinc.csv",
      "department_table": "department_to_trialbox.csv"
    }

`kind` is `diagnosis`, `lab`, `drug`, `order` or `department`. `system` is one of the systems listed in
`tools/mapping_coverage.py` (`SYSTEMS`): `icd-10-cm`, `icd-10`, `medis`, `local-lab`, `jlac10`, `jlac11`, `atc`,
`nhi-drug`, `yj`, `hot`, `nhi-order`, `jp-procedure`, `department` and the `local-*` ones. `target` is the column
in which the hospital's own table already gives the standard code (the ATC column of a drug master), if it has one.
The optional cross-walks (`lab_lookup`, `jlac10`, `byomei`, `yj`, `ingredient_atc`, `nhi_drug`, `who_icd10cm`,
`department_table`) are the site's own
tables, in the columns of the samples under `services/adapter/mapping/`; without them the shipped samples are used,
and a real hospital's codes will mostly not be in them. Files are CSV or tab-separated, in UTF-8, Big5 (cp950) or
Shift_JIS (cp932).

**What it writes.** `--out` only: the tables' kinds, systems and row counts, the codes mapped and not mapped by domain
and route, each unmapped code with its dictionary name and the reason, and for each ruleset value set how many of the
hospital's codes fall in it. No file path, no other column. The terminal shows the same.

**Before the summary leaves.** Read it. A dictionary name can still name a person (a clinic named after a doctor) or
the hospital; remove such a line before sending.
