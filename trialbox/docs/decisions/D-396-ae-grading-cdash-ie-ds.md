# D-396 AE grading by CTCAE and the CDASH IE and DS rows

- **Task:** T-619b (wave 2 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2; T-STD-09 of the deep review)
- **PR:** this branch (`agent/T-619b-ae-grading`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Builds on:** D-129 (built-in forms and exports), D-160 (CDASH tags), D-387 (the criterion not met on a screen
  failure), T-115 (ODM 1.3.2 schema check), D-311 (no development gates)
- **Closes:** STD-050, STD-051, STD-063

## Context

The built-in AE form records severity as mild, moderate or severe. Oncology studies grade AEs by CTCAE, and v5.0
(2017) and v6.0 (2025) are both in use, so a study must name its version (STD-051). The AE term is free text and
nothing says who codes it to MedDRA (STD-050). CDASH coverage was 13 variables of DM, VS, LB, MH, CM and SV, with no
AE, IE or DS, although the screening log already knows the criterion a screen failure did not meet (STD-063).

## Decision

1. **CTCAE per study.** The built-in AE form gains `ae_ctcae_grade` (1 to 5, with CTCAE's general meaning of each
   grade in three languages) and `ae_ctcae_version` (5.0 or 6.0). A study names its version when it adds the built-in
   forms (forms page, `POST /studies/{rs}/forms/builtin` with `ctcae`); the AE form then offers that one version and
   both items are required, so every AE carries its grade and the version it was graded by. Severity stays on the form
   but is not required in such a study (CDASH: `AETOXGR` or `AESEV`). A study that names no version does not get the
   two items. Another value (4.03, 7) is refused (`FORM-CTCAE`). Nothing is graded automatically.
2. **MedDRA: not coded here.** AE terms stay verbatim (CDASH `AETERM`); MedDRA coding is the sponsor's or the data
   centre's. No MedDRA fields are added: the optional LLT code pair waits until a site holds its own subscription.
3. **CDASH tags.** `edc.cdash` knows AE (`AETERM`, `AESTDAT`, `AEENDAT`, `AESER`, `AESEV`, `AETOXGR`, `AEOUT`,
   `AEREL`), IE (`IECAT`, `IETESTCD`, `IETEST`, `IEORRES`, `IEDAT`) and DS (`DSCAT`, `DSDECOD`, `DSTERM`, `DSSTDAT`).
   The built-in items carry their tag (`cdash.BUILTIN`); the CTCAE version item is aliased to the SDTM trial summary
   parameter `TOXGRV`. The item map suggests `AE.AETOXGR` for a grade item and refuses it on an item that is not a
   choice of grades 1 to 5 (`cdash_grade`).
4. **IE and DS from the screening log.** A new export format, `cdisc` (`export.cdisc.odm.xml`), is the data-core ODM
   plus a form `Form.cdash` on the first event with two repeating groups. `IG.IE`: one row for the criterion a screen
   failure did not meet (D-387): `IECAT` from the criterion id (`INC` / `EXC`, `I3` / `E1`), `IETESTCD` as `INCL02` /
   `EXCL06` (8 characters at most), `IETEST` the id with its criteria version, `IEORRES` `N` for an inclusion not met
   and `Y` for an exclusion met, `IEDAT` the day. `IG.DS`: informed consent obtained (protocol milestone), and screen
   failure, completed or the withdrawal reason (withdrawal by subject, physician decision, adverse event, lost to
   follow-up, death, other) as the disposition event, from the standing lifecycle steps. The plain `odm` export is
   unchanged, so the REDCap round trip still holds; both pass the ODM 1.3.2 schema.
5. **CDISC scope stated** in `docs/data/03-trial-data-the-data-core.md`: CDASH for DM, VS, LB, MH, CM, SV, AE, IE
   and DS; EX, SDTM datasets, Define-XML and CDISC Controlled Terminology files are out of scope.

## Consequences

- Tests: `tests/unit/test_ae_grading_d396.py` (grade 1 to 5 with the version; IE rows for a screen failure in a
  schema-valid ODM; DS per CDASH; the CDASH short names; the item map's grade check) and
  `tests/console/test_ae_grading_pages.py` (the forms page and API take the version; the CDISC export downloads).
- A study that changes its CTCAE version adds the built-in forms again with the new one; AEs already saved keep the
  version they were graded by.
- Later: CTCAE grade as a catalogue item type and eligibility text such as "no grade 2 or higher neuropathy" on
  structured grades; EX; ODM metadata import.
