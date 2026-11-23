# D-1183 ATC reaches the readers only from the site's own copy; the FHIR store restarts after a terminology change (V-18b)

- **Task:** lane V, card V-18b (the integrator's comments 7114273376 and the answer to 7114639597 on #639) ·
  **Date:** 2026-11-23
- **Status:** reserved for V-18b (the integrator flips the row when merged)
- **Builds on:** D-1182 (one manifest, three readers), D-1114 (the site's ATC index under a named acceptance), D-536
  (ATC is named by its system URI), D-1127 (the NHI open data the image may ship), D-342 (the licence register)
- **Closes:** V18-07 (the shipped ATC fed the compiler and the vocabulary but not the FHIR store) and V18-01 (the
  store answered from an earlier version for minutes after an update)

## Decision

1. **No ATC table ships.** `services/criteria_compiler/terminology/src/atc.csv` and `atc.parquet` are removed, and
   `tools/build_terminology.py` no longer builds them. The licence register's `atc` row (permission-to-ask) no longer
   names them. So the compiler's mapper, `omop.concept` and the FHIR store read ATC from the same place.
2. **Where ATC comes from.** In this order:
   - the site's own ATC index (`atc_index`, loaded at install under a named acceptance, D-1114): its names and codes,
     in every step the shipped table answered (its substances answer the exact-name step);
   - else, codes only, as identifiers (D-536): the ATC column of the NHI drug lists (open data, D-1127) and the codes
     TrialBox's own groupers (`src/synonyms.csv`) name. Such a code's name is the NHI ingredient when there is one, else
     the code itself. A WHOCC name never reaches a reader without the site's copy;
   - else nothing: a drug named only in the WHOCC index is unmapped, and the FHIR store's ATC is a line of the
     "information still needed" page (D-1182 point 3).
3. **A group is a family, never a member.** A grouper expands to the level-5 substances of the site's index; its
   prefix stays a family of the ValueSet. A grouper family that the NHI lists hold no code of names its members
   itself: the anticoagulant rows (B01AA03, B01AE07, B01AF01 to B01AF03) and the JAK inhibitor rows (L04AF01 to
   L04AF03) are exact rows of `src/synonyms.csv`, so the shipped rule sets keep every code they had.
4. **The shipped rule sets.** Recompiled (`python -m tools.build_rulesets --recompile`): only medication ValueSets
   move, 15 of them in 7 rule sets, each with the same codes and the code as its display; their CQL and ELM follow.
   No SQL changes. RA-JAK's `terminology_release` is re-pinned to the new parquet release.
5. **The FHIR store restarts after a terminology change.** The pinned store keeps its `$lookup` and `$validate-code`
   answers for minutes, and none of its operations clears them (`$reindex-terminology` fails with its full-text
   search off). After a load that changed a system (a row `loaded` in the report), `deploy/terminology-update.sh`
   and an update's code-system step restart `fhir-store` and wait until it is healthy. The report records it
   (`store_restart`), and the doctor warns when a changed system was not followed by a restart, or the store did
   not answer again. The store's cache setting is kept.

## Consequences

- A site without its own ATC copy sees ATC codes without names, and a drug the NHI lists do not hold is matched only
  through TrialBox's groupers. A box that loaded an ATC index keeps it; its groupers now expand from it.
- A box that loaded the vocabulary from the shipped table before this keeps those ATC concepts, with their WHOCC
  names, in `omop.concept`: a load never removes a concept. The attribute rows `term:atc` are emptied on the next
  load, so the compiler no longer reads them (finding V18b-01).
- A terminology change costs the store's restart (38 s on the test machine) during which the store does not answer.
