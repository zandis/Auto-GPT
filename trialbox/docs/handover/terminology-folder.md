# The hospital's folder of licensed code systems (V-18)

**Reader:** the box owner and the hospital's IT. The page says how to lay out the folder of the hospital's own
licensed copies, so the box loads them at install and at each update.

SNOMED CT, the UMLS and the ATC/DDD index come from the hospital's own licensed copy, never from TrialBox: the
repository and the install bundle never carry them (D-1182, the owner's ruling on #639). LOINC and WHO ICD-10 may come
from the same folder. You put the files there, and the box reads them where they are. It builds its tables from them
and copies the files nowhere: not into a bundle, a log or a backup (a backup keeps each system's name, version and
hash, and a restore reloads the tables from this folder).

## Where the folder is

`deploy/site/terminology/` by default. A folder elsewhere on the box (outside the repository) is named by
`TB_LICENSED_DIR=/path/to/folder` in `deploy/.env`. The box reads it read-only.

## The layout

```
<the folder>/
  acceptance.json      who accepted the licences (one person, by name), and the day
  snomed/              SNOMED CT: the RF2 release, International or national
                         its zip as SNOMED International or the national release centre ships it,
                         or the unpacked release (the loader reads its Snapshot/Terminology files:
                         sct2_Concept_Snapshot_*, sct2_Description_Snapshot*, sct2_Relationship_Snapshot_*)
  umls/                the UMLS: a MetamorphoSys subset in RRF
                         its META folder's files, or a zip of them: MRCONSO.RRF, MRREL.RRF,
                         MRFILES.RRF and release.dat as MetamorphoSys writes them
  atc/                 the ATC/DDD index as the WHOCC sells it: one .xlsx (or .csv or .tsv)
                         and VERSION, the index's year (e.g. 2026), one line
  loinc/               LOINC: Regenstrief's download zip (or Loinc.csv); optional
  icd10-who/           WHO ICD-10: the ClaML XML; VERSION if the file does not say; optional
```

Each system's subfolder may also hold:

- `SHA256SUMS`: the publisher's or your own list of `sha256  file` lines. Every listed file must match, or that
  system is refused.
- `SHA256`: the sha256 of the one zip you downloaded, as the publisher's page shows it.

The UMLS subset is checked by its own `MRFILES.RRF`. A system with none of these is loaded on its own headers, and the
manifest line says so (`verified`).

`acceptance.json`:

```
{"accepted_by": "Full Name", "accepted_on": "YYYY-MM-DD",
 "statement": "academic, non-commercial use under the hospital's own licences"}
```

The name is a person's full name, never a role (`admin`, `IT`, `yes` are refused, D-1114). The install question
(lane U) writes this file once the hospital confirms the statement. Until it exists, no licensed system is loaded,
and each is listed on the "information still needed" page.

## What happens

- **At install:** after the services start, the install runs `deploy/terminology-update.sh`. It runs two steps:
  1. The folder's systems go into the terminology volume, with no network.
  2. The vocabulary and the FHIR store are loaded from that one manifest and the shipped tables.
- **Missing or refused:** a system that is missing, or whose check fails, never stops the install. It is a line of
  `deploy/site/needed.jsonl` (the "information still needed" page), with the reason. One whose files are there but
  whose check fails is also a line of `poc-stops.jsonl`.
- **Later:** add or replace files in the folder, then run `deploy/terminology-update.sh` again: no reinstall. Each
  system's earlier version stays in the FHIR store's history; `python -m tools.fhir_codesystems rollback <system>`
  puts it back.
- **An update bundle:** a bundle may also bring a new release of a code system the box may carry (ICD-10-CM,
  ICD-10-PCS, the NHI lists), never one of the licensed ones. `deploy/terminology-update.sh --rollback <bundle>` puts
  back what it replaced.
- **The doctor:** `trialbox doctor` shows each system's version and fails when the vocabulary and the FHIR store
  hold another release than the folder's tables.

## One system at a time

The same loaders, one system each (the file under `/stage`, the folder as the loader sees it):

```
deploy/terminology.sh snomed /stage/snomed --accepted-by "Full Name"
deploy/terminology.sh umls /stage/umls --accepted-by "Full Name"
deploy/terminology.sh atc /stage/atc/index.xlsx --accepted-by "Full Name" --version 2026
deploy/terminology.sh status
```
