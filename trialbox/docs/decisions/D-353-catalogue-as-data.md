# D-353 The clinical item catalogue loaded as data: concepts, the storable gate, the items page

- **Task:** T-107 (wave 2 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2.5; scope in
  `docs/reviews/2026-11-09-assessment-and-tasks.md`, "T-107 The catalogue loaded as data")
- **PR:** this branch (`agent/T-107-catalogue-data`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Builds on:** D-144 (local concepts at 2e9 and up; unknown never excludes), D-180 (the catalogue's verification
  columns and `may_exclude`), D-301 (a custom concept is never standard), T-105b (the Athena bundle)
- **Closes:** CR-067 (catalogue half), FIT-017 (catalogue half)
- **Replaces:** the reservation D-221 (voided; this card took D-353)

## Context

`catalogue/items.csv` (469 items) was data that no code read. Its local items carry proposed concept ids in the
TB-SHARED band, its LOINC items carry codes whose concept ids come from the vocabulary, and its `storable` column
says per instrument whether a site may keep the score only, the item answers too, or also the text. Nothing
enforced any of it, and a steward could not see it.

## Decision

1. **One reader.** `tb_common.catalogue` reads `items.csv` (folder `TB_CATALOGUE_DIR`, else `trialbox/catalogue`,
   which the python image now ships) and refuses a file that breaks an id rule, whole: a local id is in
   2,000,001,001 to 2,099,999,999, unique, in file order (rows are appended, never renumbered), and never an id
   that `verification/loinc_decisions.csv` retired; a LOINC item has no local id; `storable` is one of three values.
2. **Concepts.** `omop.catalogue_load.load` gives each item one concept and one domain. A LOINC item is the
   standard LOINC concept the vocabulary holds for its code; a code the vocabulary lacks is listed as unmapped in
   the report, never invented. A local item is a TB-SHARED concept (class `TB Catalogue Item`, the item id as code,
   the Japanese and Chinese names as synonyms, never standard) at the catalogue's id, the same on every box. A
   second load changes nothing; a load that would move an item to another id, or put a new item on an id that holds
   another code, is refused before anything is written (`CAT-RENUMBER`). A load is a `tb_vocab_release` row named
   `CATALOGUE`. The report lists unmapped items per specialty (the box's coverage report).
3. **Storable gate.** Chart extraction drops a proposed fact that names an item answer of an instrument whose
   `storable` is `score` (`MMSE orientation 3/5`, `PANSS positive`), by the instrument's names or English acronym,
   or a listed component by name or LOINC code. The instrument's own total (`MMSE 24/30`) and items that are scores
   of their own (`MDS-UPDRS Part III`) are kept. The rule is in one function, `catalogue.refused_fact`.
4. **Hints.** `catalogue.hints_block` generates the extraction hints (one line per item; a score-only instrument
   says "never list its item answers"). The block is optional.
5. **Items page.** `/data/items`: the administrator (the box's data steward) sees the items by specialty in English,
   Japanese or Traditional Chinese, with code, what may be stored, the code check and `may_exclude`. Anyone else gets
   403 and a `console.denied` event; an unreadable catalogue is a 503 page.

## Not done here

The chart-facts prompt version that carries the hints block (a new registry entry with its qualification record,
T-101's process), the criteria parser's phrasing table, and running the load at box start (the OMOP load path is
T-106's). Until the prompt version lands the model is not asked for scores, and the gate holds for anything it
lists.
