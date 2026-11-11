# D-419 The consortium code-map registry: layout, TB-SHARED ranges, signed releases as a refdata pack part

- **Task:** T-316b (wave 3 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2; the owner kept it for go-live, Q-06;
  scope in `docs/reviews/2026-11-09-assessment-and-tasks.md`, "T-316 Consortium", code-map part)
- **PR:** this branch (`agent/T-316b-codemap-registry`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Builds on:** D-140 and D-170 (the refdata pack and its `map` kind), D-144 (TB-SHARED below the site blocks),
  D-301 (a custom concept is never standard; releases in `tb_vocab_release`), D-342 (no SNOMED CT ships), T-105b
- **Closes:** CR-031 (code-map part; the signed counts are T-316a, the de-identified export T-316c)

## Context

The owner decided that the consortium shares its code maps through a registry hosted by the lead hospital, which
Aimedics ships (MR-142, WS-09.1). Nothing on master held such maps: each box minted reference concept ids from its
own sequence, so the same code had different ids on two boxes, and no release named what map set a box ran.

## Decision

1. **Layout.** The registry is a git repository (`trialbox-codemap/1`): `registry.json` (name, url, ranges, the
   registry's own code systems, the maps), `concepts.csv` (shared concepts at fixed ids), `maps/<id>.csv` (FHIR R4
   ConceptMap rows) and `releases/<version>.json` (the record of every release). A map change is a reviewed pull
   request there; `tools/codemap_release.py check` lists every broken rule.
2. **TB-SHARED ranges.** The registry's concepts take ids in 2,005,000,000 to 2,009,999,999 (`omop.vocab.CODEMAP_MIN`
   and `CODEMAP_MAX`): inside TB-SHARED, below the reference concepts (2,010,000,000) and far above the catalogue's
   ids. `registry.json` gives each owner (the consortium, each member hospital) its own range; a concept sits in its
   owner's range. An id once released is never renumbered nor reused (held against `releases/`, and again at load
   against the box). These concepts are never standard.
3. **Licences.** A release carries a code system only when it is the registry's own, or its row in
   `docs/licences/register.csv` is `cleared`, `own-work` or `synthetic`. SNOMED CT (removed), ATC (permission to ask),
   WHO ICD-10, RxNorm and the JP masters (site-loaded) are refused, and so is a system the register does not know.
4. **A release** is a refdata pack part `trialbox-refdata-<date>-codemap-<version>`: one `map` source per map at the
   release's version, so the signed update bundle carries it and the refdata store reads it like any pack. Beside it,
   the record `codemap.json` (version, author, approver, ranges, licences, every file's sha256, the concept ids, a
   content sha256) and `codemap/concepts.jsonl.gz`. The author and the approver are two people. With the registry's
   Ed25519 key the record is signed (`codemap.sig`, `tb_common.crypto`).
5. **Loading.** `tools/codemap_release.py load` refuses a file whose sha256 differs from the manifest or the record,
   and, with `--public-key`, a release without a valid signature. It loads in one transaction: the shared concepts at
   their ids (`omop.vocab.seed_registry_concepts`), each map as map release `map:codemap-<id>`
   (`omop.vocab_load.load_concept_map`), a map the release dropped taken out, and the active `CODEMAP` row in
   `tb_vocab_release`. A code-map release is not a compile release: it changes data, never a compiled ruleset.
   Loading the same release again changes nothing.
6. **Naming.** `omop.vocab.release(db)` returns the terminology release (`TR-...`) and the active code-map release:
   registry, version, sha256, who loaded it and when, and its maps. `python -m omop vocab status` prints it.

## Consequences

- Two boxes that load one release hold its shared concepts at the same ids and map their codes to the same targets
  (the two-box test in `tests/unit/test_codemap_release.py`, synthetic TW and JP sites).
- The vocabulary-committee page (steward) and loading a release automatically when the update bundle applies its
  refdata pack are not built here; `codemap_release load` is the step until then.
- The catalogue's nominal band (2,000,001,001 to 2,099,999,999, D-353) still covers the registry band on paper; the
  catalogue uses ids from 2,000,001,001 in file order, and a load refuses any id that already holds another code.
