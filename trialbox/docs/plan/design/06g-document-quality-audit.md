# TB-REV-006g Document quality audit of the TrialBox design set

| Field | Value |
| --- | --- |
| Document ID | TB-REV-006g |
| Title | Document quality audit: structure and quality of each design document against its standard |
| Version | 1.3 (v1.0, §R and §F text unchanged; §C confirmation appended) |
| Date | 2026-11-07 |
| Author | Claude (independent technical-documentation auditor, Fable) |
| Owner | Product owner (Changfu Kuo) |
| Status | Final (review record); §R re-audit after the fix pass, set 4.1 / 5; §F final audit after pass 2, set 4.4 / 5, 16 of 18 documents at 4.5; §C confirmation after the §F fix pass, set 4.5 / 5, 18 of 18 documents at 4.5 |
| Scope | Document quality only: ID scheme, control tables, scope, definitions, normative references, traceability, requirement characteristics (ISO/IEC/IEEE 29148 §5.2), viewpoints and ADRs (ISO/IEC/IEEE 42010, arc42, C4), interface specifications, test documentation (ISO/IEC/IEEE 29119-3), security documentation (ISO/IEC 27001, OWASP ASVS), risk file structure (ISO 14971 structure, as the file itself adopts), configuration management (ISO 10007), change history, cross-document consistency. **Not** product scope, and **not** process: the owner's direction (SIMPLE-PLAN.md, TB-DS-20) is a development build with no gates, and nothing here recommends a gate, an approval or a review step. |
| Documents audited | 00, 00R, 01, 02, 03, 04, 05, 07, 08, 09, 10, 11, 12, 17, 19, 19a, 20, 21, SIMPLE-PLAN. Earlier reviews 06..06f read as context only. 13, 14, 15, 16, 18 are hospital-stage documents outside this brief and are not scored. |
| Method | Full read of every document (large documents section by section); automated checks over the whole set (table structure, requirement-ID cross-references, matrix coverage, stale phrases, control blocks); seeded random sample of 40 SRS requirement rows judged against the 29148 characteristics. Scripts and seeds are stated in §4 so the result can be reproduced. |
| Nothing else edited | This file is the only change made to the folder. |

---

## 1. Summary

**Set overall: 3.4 / 5** (unweighted mean of the 17 scored documents; the three largest, 01/02/04, average 3.5).

The set is far above an ordinary start-up design set in **structure**: every TB-DS document has a control table and a change history, one ID scheme, one canonical-numbers document, an SRS with 412 identified rows, an arc42 architecture with 16 ADRs and a 42010 annex, an ICD with JSON Schemas and an error register, and a requirements-to-test matrix. What keeps it at 3.4 instead of 4.5 is **drift and finish**, not missing chapters:

1. The traceability chain is broken at the SRS → V&V step: TB-DS-04's matrix was regenerated from TB-DS-01 v0.2 (346 rows) and now covers 396 of 412 rows; the 39 untraced rows are exactly the build-stage additions (FR-SYN-01..04, FR-PLAT-01..30, FR-OPS-11/12, FR-MOD-10, FR-RC-17, FR-FEAS-13), including FR-OPS-11, the one build gate.
2. Two tagging regimes (M1/M2/C and S0–S5/H/L) coexist in different proportions in every document, and the BD-13 simplification ("one page, one Approve") is still contradicted by text in 02, 04, 09, 11, 17 and 19a.
3. Markdown table structure is broken in 14 places, including all nine control tables of TB-DS-03 (header 8 columns, separator 7), which means the "SRS IDs" column does not render.
4. In the 40-row sample, 8 rows (20 %) fail at least one 29148 characteristic (singular, unambiguous, verifiable, implementation-free); 58 of 412 rows (14 %) contain two or more "shall".
5. Small control-record defects: register version 0.10 against its own row 0.9; TB-DS-10 is at 0.1b with no 0.1b history entry; TB-DS-12 at 0.1a with no 0.1a entry; TB-DS-20 (1.0) and TB-DS-21 (1.1) carry approved-level versions while TB-DS-12 §6 says 1.0 means approved.

All of these are paper fixes. What cannot be fixed on paper is listed in §7.

---

## 2. Per-document scores

Scores are out of 5 and are not rounded up. "Standard" is the yardstick the document itself claims or the one that fits it best.

| Doc | ID | Ver. | Standard measured against | Score | One-line verdict |
| --- | --- | --- | --- | --- | --- |
| 00-baseline-decisions | TB-DS-00 | 0.8 | ISO/IEC/IEEE 29148 (decision baseline), ISO 10007 (baseline record) | **3.5** | Clear single source for numbers and decisions; no approvals row; superseded wording kept inline inside BD-07/BD-13/BD-15 instead of a status field; §2.H still the longest part of a "build-stage" document. |
| 00-document-register | TB-DS-00R | 0.10 | ISO 10007 §(status accounting), IEEE 828 register practice | **3.5** | Complete row set and planned-document list; self-version mismatch (0.10 vs 0.9 row); no distribution column although TB-DS-12 §6 says the register states distribution; file numbers ≠ IDs (13 = TB-PLAN-01, 14 = TB-TMPL-01, 18 = TB-TMPL-07, 19a unregistered ID). |
| 01-SRS | TB-DS-01 | 0.9 | ISO/IEC/IEEE 29148:2018 §9.5 (SRS) and §5.2 (requirement characteristics) | **3.5** | Full 29148 skeleton, stable IDs, source and verification columns, glossary, crosswalk. Loses on characteristics: 20 % sample defect rate, 14 % non-singular rows, build-status prose inside requirement text, FR-MOD-10 misfiled in the FR-SEC table with a missing column, §3 column legend still "M1/M2/C", §4 release rule still written for the pilot. |
| 02-architecture | TB-DS-02 | 0.7 | ISO/IEC/IEEE 42010:2022, arc42, C4 | **4.0** | All 12 arc42 sections, 20 Mermaid diagrams, ADRs with alternatives and consequences, concern/viewpoint table and correspondence rules. Loses on ADR status discipline (13 of 16 "Proposed", no decider/date), stale text (§5.2 "two sign-offs", §1.1 pilot wording), two malformed tables, trace at area level only, four quality scenarios whose measure is "target set later". |
| 03-security-privacy | TB-DS-03 | 0.4 | ISO/IEC 27001:2022 Annex A / 27002, OWASP ASVS 5.0, STRIDE, DPIA practice | **3.5** | Assets, zones, STRIDE per container and flow, LLM threats, 100-odd controls with regulation mapping, DPIA, de-identification spec. Loses on form: all nine SC tables malformed; no Statement-of-Applicability view (control → applicable / excluded with reason); ASVS L2 mapped by three controls; H1 title lacks the ID; §1.2 points to a §7.4 that does not exist; "Pilot gate" column not re-expressed in the S/H/L regime. |
| 04-verification-operations | TB-DS-04 | 0.7 | ISO/IEC/IEEE 29119-3:2021 (test plan, design, case, procedure, completion report), GAMP 5 light | **3.0** | Good test plan content (risk basis, levels, environments, entry/exit, suspension, release record). Loses on the matrix: regenerated from SRS v0.2, 396/412 rows, build-gate row FR-OPS-11 untraced, header text and counts stale; test cases are "representative" only, no case or procedure specification structure; §3.4a precedes §3.4; change-history row with four cells in a three-column table. |
| 05-open-source-reuse | TB-DS-05 | 0.3 | Survey / licence-register good practice (ISO/IEC 5230 register fields) | **3.5** | Per-layer candidates with licence, version, activity, verdict; licence notes; "unverified" marked 44 times (honest, but a third of the facts). No evaluation criteria stated up front; H1 title lacks the ID; per-row check date absent. |
| 07-data-dictionary | TB-DS-07 | 0.4 | ISO/IEC 11179-style dictionary; data-model specification practice | **3.5** | Store inventory, field-level class/PII/retention, FHIR profile table, lake DDL, erasure handling. Column sets differ between tables (only `jobs` has Null/Source/Retention); keys and relationships ad hoc; §4.6.1 heading says S-28 but sits under S-06; change-history table split by a blank line; one malformed row (§4.10). |
| 08-interface-control | TB-DS-08 | 0.5 | ICD practice (IEEE 1016/42010 interface view); JSON Schema 2020-12; RFC 9457 | **4.0** | Best-finished document: versioning rules, RFC 9457 error model, error register, auth summary, schemas, conformance tests per interface. Uneven depth (ICD-03, ICD-12 one paragraph; ICD-13/14 schemas in prose); errors `RC-LINK-DUP`, `RC-LINK-FIELD`, `UP-META`, `UP-LAYOUT`, `UP-IDMATCH`, `UP-SIZE` missing from §2.3; §1 table tags still [M1]/[M2]; one malformed row. |
| 09-ui-ux-spec | TB-DS-09 | 0.8 | UI specification practice (ISO 9241-210 artefacts), WCAG 2.2 | **3.5** | Role × screen matrix, 37 screens, card component with state machine, copy rules, accessibility, states. §3 promises "goal, layout, primary action, data, states, latency" per screen but S10–S15 and S22–S37 are one paragraph each; stale "entry page" (P5, §7 "Back to entry page"), S20 row half in the two-sign-off model; no wireframes or layout references. |
| 10-terminology-mapping | TB-DS-10 | 0.1b | Terminology-binding specification practice (FHIR terminology, UCUM) | **3.0** | Correct skeleton (code systems, mapping rules, normalisers, rule-book format, build, licences, open items). Six "verify" flags on codes and URIs the build depends on; no normative-references section; 0.1b with no 0.1b history entry and a split change-history table; §3 rule 2 cites an unverified modifier code. |
| 11-risk-management | TB-DS-11 | 0.4 | ISO 14971:2019 structure (as adopted), ISO/IEC 27001 §6.1 link | **3.5** | Criteria, acceptability matrix, 17 hazards each with causes/controls/verification/residual, misuse list, benefit-risk, post-production. H-01 control (g) still describes two sign-offs; controls trace to FR areas, not IDs; verification cites documents, not test cases; "marked H" without re-evaluating which hazards exist on synthetic data (none, but the file should say so). |
| 12-configuration-management | TB-DS-12 | 0.1a | ISO 10007:2017, IEEE 828 | **3.0** | All four CM functions present in nine pages. Stale: CI-DOC lists TB-DS-00..16 (set now reaches 21); baselines keyed to "M1 build freeze"; the build-stage rule of the register (git, PRs, `docs/DECISIONS.md` D-nnn) is not in the plan; 0.1a with no 0.1a history entry; no status-accounting report format. |
| 17-clinical-operations | TB-DS-17 | 0.6 | ISO/IEC/IEEE 29148 §9.3 (operational concept) as the nearest fit | **3.5** | Personas, workload budget with replaced-task rule, role homes, full study cycle, alert budget, data sources, measurement plan. Mixed tags in every table; §4.1 step 2 still "S20 part 1 / part 2"; §3.2 numbering (1, 1a, 2…) differs from TB-DS-09 S8 (1–7, F6-21); no definitions or references section beyond §0.1 sources. |
| 19-platform-functions | TB-DS-19 | 0.2 | Functional specification practice | **3.0** | Useful one-place list with status words and code locations. Body tags are "M1" while the control table carries the build tags; FR-PLAT-12 text lacks Retry (SRS v0.8 has it); no approvals block. |
| 19a-completeness-table | — | — | Record | **2.5** | Good content, but no document ID, control table or change history; "add the two sign-offs" stale; not registered under an ID (register row says "—"). |
| 20-build-map | TB-DS-20 | 1.0 | Plan / work-map practice | **3.5** | Clear done-when lines and decision table. Tag-count table says "TB-DS-01 v0.8" and does not match v0.9 (S0 32 vs 45, S2 29 vs 30, S3 11 vs 12, L 104 vs 110); version 1.0 while unapproved (TB-DS-12 §6 rule). |
| 21-synthetic-hospital-spec | TB-DS-21 | 1.1 | Test-data specification practice (29119-3 test data requirements) | **3.0** | Testable checks, gold-file schema with offset convention. Missing: prevalence/distribution parameters, finding-slot catalogue per ruleset criterion, name-list sources and licences, truth-file schema for structured criteria, approvals; version 1.1 while unapproved. |
| SIMPLE-PLAN | — | — | Owner's direction page | not scored | Not a controlled document; carries no ID. Its lifecycle table and "why it can be simple" are clear. Register it as the owner's record so the set's rule (TB-DS-00 §1: every document has an ID) is not contradicted by its own plan. |

---

## 3. Findings

Severity: **Major** = breaks a chain the set relies on (traceability, identity, control record) or misleads a reader about a decision; **Moderate** = a standard clause missing or weak; **Minor** = form, rendering, wording. Every fix is a document edit; none adds a process step.

### 3.1 Document-level findings

| ID | Sev. | Doc | Section | Finding | Fix |
| --- | --- | --- | --- | --- | --- |
| Q-01 | Major | 04 | §6.1–6.3 | Matrix regenerated from TB-DS-01 v0.2 ("Every one of the 346 SRS rows", "394 active of 396"). SRS v0.9 has 412 rows; 39 are absent: FR-FEAS-13, FR-MOD-10, FR-OPS-11, FR-OPS-12, FR-PLAT-01..30, FR-RC-17, FR-SYN-01..04. FR-OPS-11 is the only build gate and is itself untraced. AM-01 has no row. | Regenerate §6.2 from v0.9; add rows for the 39 IDs and an AM-01 row (levels U, I, B; suite TS-AUTH); rewrite §6.1 header text and §6.3 counts; change the "Release gate" column legend to S0–S5 / H / L. |
| Q-02 | Major | 01 | §3.1.18 | FR-MOD-10 is placed inside the FR-SEC table (7 columns) with 6 cells, so the row renders misaligned and the requirement is filed under security controls. | Move FR-MOD-10 to §3.1.21 MOD with the 6-column layout. |
| Q-03 | Major | 03 | §4.1–4.9 | All nine SC tables have an 8-column header and a 7-column separator; the "SRS IDs" column (added 0.2a to close OI-10) does not render in any Markdown viewer. | Add the eighth `---` cell to each separator row. |
| Q-04 | Major | 02, 04, 09, 11, 17, 19a, 15 | 02 §5.2 console row; 04 §3.5; 09 §2 S20 row; 11 H-01 (g); 17 §4.1 step 2; 19a row 3; 15 | Text still describes ruleset approval as two sign-offs / "S20 part 1 and part 2" after BD-13 was simplified to one page, one Approve (F6-07) and TB-DS-01 FR-FEAS-12 was rewritten. | One pass replacing each occurrence with the one-page wording and a "(was two sign-offs, superseded F6-07)" note where history matters. |
| Q-05 | Major | 00R | Control table vs row | Register header says 0.10; its own row says 0.9. | Set the row to 0.10. Add a rule that the register's row is updated in the same edit as its header. |
| Q-06 | Moderate | 01 | §3 intro, §1.6, §4 | §3 legend says "Pri (M1/M2/C)" while §1.6 defines S0–S5/H/L; §4 "Release rule" and the pilot-dates note describe M1 shipping conditions. | Rewrite the §3 legend; mark §4's release rule "hospital stage (H)" or move it to TB-PLAN-01, and add a two-line build-stage verification statement (e2e_simple, N-11, N-12). |
| Q-07 | Moderate | 01 | §3 (sample) | 29148 characteristics: 8 of 40 sampled rows fail (details §4): no fit criterion (FR-ING-04a "notably", FR-ING-13 OCR without accuracy), compound (FR-ING-19, FR-MOD-06), not a sentence (FR-ING-22), vague example (FR-MOD-07 "e.g."), implementation named (FR-MOD-01 vLLM), project activity written as a system requirement (NFR-COMP-02). Set-wide, 58 rows (14 %) contain two or more "shall". | Split compound rows with letter suffixes (the set already does this: FR-FEAS-04a..i); give every FR without a number a fit criterion in the text or a "Fit" column; move vLLM/AES-GCM/scrypt names into CON-nn constraints and cite them; move project-activity rows (NFR-COMP-02, -08) to TB-DS-04/TB-DS-03 obligations with a pointer row. |
| Q-08 | Moderate | 01 | FR-UI-17, FR-SCR-07b, FR-SCR-07c, FR-ING-19, FR-STUDY-03, FR-AUTH-13 | Requirement text carries build status and schedule ("removing them is M1 work, TB-PLAN-01 WP-17", "release before pilot week 7", "the CCB may pull it into the M1 line"). The St column exists for this. | Strip status/schedule prose from the Requirement cell into St or a Note column. |
| Q-09 | Moderate | 01 | Appendix B | Open-issue table has no Status or Date-raised column; OI-14 and OI-15 "Needed by: Now" cannot be read as open or closed. | Add Status (open / closed / superseded by build-stage rule) and Raised columns; close OI-14/15 against TB-DS-00 v0.8. |
| Q-10 | Moderate | 02 | §9.2 | 13 of 16 ADRs are "Proposed"; no decided-by or decided-on field; ADR-06 row is blank except "Superseded". 42010 §5.8 asks for the rationale **and** the decision record. | Add "Decided by / on" and "Decision drivers" columns; set status Accepted where BD-nn in TB-DS-00 v0.8 fixes the decision (ADR-03, -05, -13, -14, -15, -16); fill ADR-06 with the superseding reference. |
| Q-11 | Moderate | 02 | §1.1, §1.2, §3.1, §5.2, §12 | Build-stage header, but body text still "Release M1", "Pilot start January 2027", "[target, M1]" in 142 places, glossary "M1 / M2 / C … pilot January 2027", "Shadow mode". The header's rule ("a [target, M1] tag means its step is in TB-DS-20") is a workaround for an unfinished re-tag. | Either finish the re-tag in the tables that readers use (§3.2, §5.2, §8.13.2, §10.3 are done; §5.2 status column, §6 headings, §7.2 are not) or state the rule once per section. Update §12 glossary rows. |
| Q-12 | Moderate | 02 | §10.2 | QS-13, QS-15, QS-16, QS-17 have measures "unmeasured / target set after the first site". A quality scenario without a response measure is not verifiable. | Give provisional measures with "(provisional until measured)" or move them to §11 risks. |
| Q-13 | Moderate | 02 | §10.3, A.3 | Trace is at FR-area level ("FR-ING, FR-JP"), by design, so it cannot show which requirement has no building block. A.3 claims "every [target] block is traced to a work package in TB-PLAN-01", a superseded plan. | Keep the area table and add a generated ID-level table (SRS ID → container → ADR → QS) as Annex B; change the A.3 rule to point at TB-DS-20 steps. |
| Q-14 | Minor | 02 | §8.13.4, §8.16 | Tables at lines 1247 and 1355 have rows with a different cell count from the header. | Repair the rows. |
| Q-15 | Moderate | 03 | §1.2 | "The interface requirements on them are listed in section 7.4"; §7 has 7.1–7.3 (interface requirements are §7.3). | Fix the reference. |
| Q-16 | Moderate | 03 | §4, §12.2 | No Statement-of-Applicability view: ISO 27001 Annex A is covered by "whole catalogue; gap analysis in year 1" and ASVS L2 by three controls. The catalogue has the material; the mapping table is the thin part. | Add Annex: ASVS 5.0 chapter → SC-nn (or "not applicable, reason") and ISO 27002 theme → SC-nn. A table, not a programme. |
| Q-17 | Moderate | 03 | §4 column "Pilot gate" | Column values Yes / Y1 / Ph predate the S/H/L regime; §0 explains the mapping in prose only. | Add a "Build tag" value per control (S0 built / H / L) or rename the column and restate its legend. |
| Q-18 | Minor | 03, 05 | H1 | Titles read "TrialBox design set, document 3/5" instead of "TB-DS-03 …" like every other document. | Rename the H1. |
| Q-19 | Moderate | 04 | §4 | Test design gives conditions and "representative cases" (TC-ING-012 …) but no test-case specification structure (objective, preconditions, inputs, expected result, traceability per case) and no test-procedure specification. 29119-3 test design and case content is deferred to "full case lists live in the repository", which do not yet exist under TB-DS-01 IDs (Appendix D marker migration not started). | Add one worked case per high-risk suite in full 29119-3 form (TC id, SRS id, precondition, steps, expected, level, env) as the template, and state the file layout the repository will use. |
| Q-20 | Minor | 04 | §3.4a / §3.4, Change history | §3.4a precedes §3.4; change-history row 0.7 has four cells in a three-column table. | Renumber §3.4a → §3.4 and §3.4 → §3.5 (and cascade), or label them §3.4.1/§3.4.2; repair the row. |
| Q-21 | Moderate | 04 | §1.3, §1.5, §12 | Scope and conventions are written for the pilot release ("every TB-DS-01 requirement verified for the release its tag names (M1, M2, C)"); only §3.4a and §6.2 cells speak the build-stage language. | Add a build-stage paragraph to §1.3 and §1.5 and tag §12 "H" in the heading (done) and in the contents list. |
| Q-22 | Minor | 05 | How to read | No stated evaluation criteria or weights before the verdicts; 44 facts "unverified" with no check date per row. | Add a criteria line (licence class, activity, arm64, JP/TW fit, maintenance load) and a "checked on" column. |
| Q-23 | Moderate | 07 | §4 | Column sets differ between tables (`jobs`: Field/Type/Null/Class/PII/Source/Retention/Notes; most others: Field/Type/Class/PII/Notes); primary and foreign keys are noted ad hoc in Notes; no relationship list or diagram. | Adopt one column set for every table; add a "Key" column (PK/FK → table) and a one-table relationship list per store. |
| Q-24 | Minor | 07 | §3, §4.6.1, Change history, §4.10 | S-28 is listed between S-06 and S-07; §4.6.1 "in S-28" is nested under §4.6 S-06; change-history table split by a blank line between 0.2 and 0.3; one row in §4.10 has a different cell count. | Promote §4.6.1 to §4.6a "S-28 orchestrator study store"; order the inventory; remove the blank line; repair the row. |
| Q-25 | Moderate | 08 | §2.3 vs §4.1a, §10b | Error codes `RC-LINK-DUP`, `RC-LINK-FIELD`, `UP-META`, `UP-LAYOUT`, `UP-IDMATCH`, `UP-SIZE` are defined in interface sections but absent from the error-code register. | Add them to §2.3 with HTTP status and caller action. |
| Q-26 | Minor | 08 | §1 table, §3.3, §10, §10a/10b | §1 release column still [M1]/[M2]; ICD-03 and ICD-12 are one paragraph with no schema or conformance test; ICD-13 and ICD-14 payload schemas are prose, unlike ICD-09/ICD-10; sections numbered 10a/10b; one malformed row (§5). | Retag; give ICD-03/-12 the same headings as the others (parties, transport, schema, errors, conformance); write ICD-13/-14 schemas as JSON Schema blocks; renumber §10a/10b → §11/§12. |
| Q-27 | Moderate | 09 | §3 | §3 promises six attributes per screen; S10–S15, S22–S37 give one paragraph with no states or latency target; S28 is an empty heading with two blank lines before its text. | Add the missing attributes as a four-line block per screen (goal, primary action, states, latency), or delete the promise. |
| Q-28 | Minor | 09 | P5, §7, §2 S20 row | "The entry page is one input box and tiles" and "Back to entry page" survive F6-06; §2 S20 row still splits "sign off clinical criteria / confirm code mapping". | Rewrite the three spots to the header-field and one-Approve model. |
| Q-29 | Moderate | 10 | §2, §3, §5, §11 | Six "verify" flags sit on values the step-2 build depends on (MEDIS/YJ/HOT/JLAC10 system URIs, the 「疑い」 modifier code, licence terms). The document is a reference for build step 2 but has no normative-references section listing the masters, their versions and where they were read. | Add §1a Normative references (MEDIS master release, JSLM JLAC10 edition, JP Core 1.2.0 CodeSystem pages, LOINC release, ATC release, UCUM) with the version read; keep the verify flags until TM-02 closes. |
| Q-30 | Minor | 10, 12 | Change history | TB-DS-10 is 0.1b, history ends at 0.1a and is split by a blank line; TB-DS-12 is 0.1a, history ends at 0.1. | Add the missing rows; remove the blank line. |
| Q-31 | Moderate | 11 | §4, §5 | Controls trace to FR areas ("FR-SCR-*") and to document sections, not to requirement IDs or test cases; H-01 (g) describes two sign-offs; §1 scope "M1 pilot release … M2" with no statement that no hazard applies on synthetic data. | Add an SRS-ID column to each hazard's controls; rewrite H-01 (g) to FR-FEAS-12 v0.9; add one sentence to §1: "No hazard in this file is live while the system runs only on synthetic data (TB-DS-20 §1); the file applies from the first real-data install." |
| Q-32 | Moderate | 12 | §3, §4, §5 | CI-DOC lists TB-DS-00..16; baselines are "before M1 build freeze"; the build-stage CM rule used by the set (git master, one PR per step, `docs/DECISIONS.md` D-nnn, register TB-DS-20 living) is in TB-DS-00R §1 and TB-DS-20 but not in the CM plan. | Extend CI-DOC to TB-DS-21, TB-TMPL-07, TB-REV-006a..g; add §4 row "Build-stage baseline: master at each merged step PR"; add §5.0 "Build stage: a merged PR with its D-nnn entry is the change record"; add a one-line status-accounting format (what the register and `docs/DECISIONS.md` show). |
| Q-33 | Minor | 17 | §3.2, §4.1, tags | S8 section numbering (1, 1a, 2 …) differs from TB-DS-09 S8 (1–7, F6-21); §4.1 step 2 "S20 part 1 / part 2"; release cells mix "M1 (…WP-17…)" with "S2 (was M1)". | Renumber to match TB-DS-09; rewrite step 2; finish the re-tag in §2.2 and §4. |
| Q-34 | Minor | 19 | §3, control table | Body release tags "M1" for every function; FR-PLAT-12 text omits Retry (SRS v0.8 added it, F6-27); no approvals block. | Replace body tags with the control-table build tags; add Retry; add the approvals block TB-DS-00 §1 requires. |
| Q-35 | Moderate | 19a | whole | No ID, control table or change history; register row "—"; stale "two sign-offs". | Give it TB-REC-01 (record) or fold it into TB-DS-19 as an annex; add the control block. |
| Q-36 | Moderate | 20 | §1 | Tag-count table cites TB-DS-01 v0.8 and does not match v0.9 (S0 32→45, S2 29→30, S3 11→12, H 169→170, L 104→110). As the living page, its counts are what readers trust. | Regenerate the counts from v0.9 and name the script; add the SRS version to the table caption. |
| Q-37 | Minor | 20, 21 | Control table | Versions 1.0 and 1.1 while unapproved; TB-DS-12 §6 says 1.0 is the first approved version. | Either renumber to 0.x or add to TB-DS-12 §6 the rule the set actually uses ("living and build documents start at 1.0; approval is the owner's merge"). |
| Q-38 | Moderate | 21 | §3–§6 | No prevalence or distribution parameters (how many patients carry each planted state), no finding-slot catalogue per ruleset criterion, no truth-file schema for structured criteria (`states.json`), no source or licence for name frequency lists, no approvals block. | Add §3a "Rates" (table per study: eligible, each exclusion, each note finding, PHI spans per 1,000 notes), §5a schema for `states.json` and `human_truth.json`, §4a sources for name lists. |
| Q-39 | Minor | 00 | Control table, §3 | No approvals row (TB-DS-00 §1 says every document has one); BD-07/BD-13/BD-15 keep superseded text inline with "Simplified" / "superseded" prose. | Add the approvals row; add a Status column (Fixed / Proposed / Superseded by …) to the BD table and move superseded wording to a footnote. |
| Q-40 | Minor | 00R | §2 | No "Distribution" column although TB-DS-12 §6 says the register states who receives which document; TB-DS-10 row says 0.1b, consistent with the document header but not with its history (Q-30). | Add the column; after Q-30, nothing else. |

### 3.2 Set-level findings

| ID | Sev. | Finding | Fix |
| --- | --- | --- | --- |
| S-01 | Major | **Traceability chain.** SRS → architecture (area level, Q-13) → ICD (good: every ICD cites FR IDs, all resolve) → tests (broken for 39 rows, Q-01) → risk (area level, Q-31). No single generated table shows SRS ID → design element → interface → test → hazard. | One generated file `trace.md` (or Annex B of TB-DS-04) with the five columns, built from the IDs already in the documents; mark gaps instead of hiding them. |
| S-02 | Major | **Two tag regimes.** M1/M2/C survives in 01 (370 "M1"), 02 (142), 07 (39), 08 (27), 09 (32), 17 (50), 19 (30) while headers declare S0–S5/H/L. Each document explains the mapping differently (01 §1.6, 02 header, 04 §1.5, 07 §1, 08 header, 09 header, 17 §0). | Put the one legend in TB-DS-00 §2 (it is already close) and have every other document cite it in one line; finish the re-tag in tables that readers use, leave prose history where it is. |
| S-03 | Major | **Superseded decision text.** BD-13 (one Approve) is contradicted in six documents (Q-04); BD-15 (no RELEASE) and F6-06 (no entry page: 01 ×5, 02 ×4, 04 ×2, 09 ×6, 15, 17) are contradicted in prose that was not revised. | A set-wide search-and-replace pass keyed to each F6 decision, recorded as one version step per document. |
| S-04 | Moderate | **Table structure.** 14 malformed tables across 01, 02, 03, 04, 07, 08 (script in §4). | Repair; add the 10-line table-lint to the repository so a future edit cannot break one silently. |
| S-05 | Moderate | **Definitions.** One glossary (TB-DS-01 App C, 47 terms) is the declared single glossary, but 02 §12 keeps 27 terms (some overlapping, "Shadow mode" defined differently), 03 §0 defines area codes and rating scales, 04 §1.5 defines levels. Terms used across the set and absent from App C: DET, DAG (present), CCB, IQ/OQ/PQ, SAT, PV, SBOM, SDC, ALCOA+, CRA, STRIDE, ADR, QS, TC/TS. | Add the missing terms to App C; reduce 02 §12 to terms used only in 02; have 03/04 keep their legends but cite App C for shared terms. |
| S-06 | Moderate | **Normative references.** Only 01 §1.5 and 04 §1.4 have a references section; 02 has a "Sources" row; 03 §12.1 is a regulation register; 07, 08, 09, 10, 11, 12, 17, 19, 21 cite standards inline only (JSON Schema 2020-12, RFC 9457, RFC 6238, RFC 8291, WCAG 2.2, ISO 14971, ISO 10007, UCUM, LOINC …). | Add a short "References" section to each (five to ten lines), pointing to TB-DS-01 §1.5 where the entry exists there. |
| S-07 | Moderate | **Numbering and IDs.** File numbers 13, 14, 18 carry IDs TB-PLAN-01, TB-TMPL-01, TB-TMPL-07; 19a has no ID; TB-DS-06 and TB-DS-13/14/18 are unused; SIMPLE-PLAN has no ID; sub-sections §2.H, §3.4a, §10a/10b, §4.6.1-under-S-06 show insertions never renumbered. | Record the file-number ≠ ID convention in TB-DS-00R §1 (one sentence) and renumber the inserted sections at the next edit of each document. |
| S-08 | Moderate | **Change-history discipline.** All versions of all documents are dated 2026-11-07, so dates do not order versions; three histories miss their latest version (00R row, 10, 12); two are split by blank lines (07, 10); one has a malformed row (04); histories reach 400-word cells (01 v0.2) that read as review logs rather than change summaries. | Add time of day or a sequence number to the Date cell; add the missing rows; cap a history cell at three lines and put the detail in the review record it already cites. |
| S-09 | Moderate | **Approvals.** Every approvals block is blank or "pending" (correct for 0.x), but the two 1.x documents (20, 21) have none at all and the two record documents (19a, SIMPLE-PLAN) have no control block. | Q-35, Q-37, Q-39, and the SIMPLE-PLAN row in §2. |
| S-10 | Minor | **Cross-references to superseded artefacts.** 50-odd citations of TB-PLAN-01 WP-nn / MS-nn and TB-DS-15 OQ-nn in 01, 02, 04, 09, 10, 17 still serve as the "when" of a requirement although TB-PLAN-01 is "superseded for the build" (register). | Keep the citations (they are the hospital-stage plan) but prefix "(hospital stage)" where they appear as a date. |
| S-11 | Minor | **Consistency checks that pass.** For the record: every FR/NFR/DR/IR ID cited in 02, 07, 08, 09, 11, 15, 17, 19, 20, 21 resolves to a row in TB-DS-01 v0.9 (0 dangling IDs); every N-nn and BD-nn cited resolves to TB-DS-00; the port table is one (N-19); SC-nn numbering is unique; no TBD/TODO markers anywhere. | None. |

---

## 4. Requirement sample (ISO/IEC/IEEE 29148 §5.2 characteristics)

**Population:** the 412 requirement rows of TB-DS-01 v0.9 §3 (FR, NFR, DR, IR; AM-01 excluded as a matrix). **Sample:** 40 rows drawn with `shuf --random-source=<(yes 29148) -n 40` over the ID rows (one draw fell in Appendix D and was replaced by the first draw of seed 42 not already in the sample, FR-JP-01). **Judgement:** a row is defective if it fails any of singular, unambiguous, verifiable (fit criterion present or implied by a cited N-nn), implementation-free (unless the implementation is a cited CON-nn), or is not a system requirement.

| ID | Pri | Verdict | Characteristic failed | Note |
| --- | --- | --- | --- | --- |
| FR-ING-03 | H | pass | — | Enumerated message types; rationale sentence about appointments could move to a note. |
| FR-ING-04a | H | **defect** | verifiable | "covering data not in standard storage, notably clinical notes": no completeness criterion. |
| FR-ING-07a | H | pass | — | |
| FR-ING-08b | S1 | pass | — | |
| FR-ING-09 | H | pass | — | |
| FR-ING-10 | S0 | pass | — | Numbers stated. |
| FR-ING-11 | S0 | pass | — | |
| FR-ING-12 | S1 | pass | — | |
| FR-ING-13 | L | **defect** | verifiable | No OCR accuracy criterion in the SRS (TB-DS-04 §4.1 adds CER ≤ 5 %; it belongs here). |
| FR-ING-16 | S0 | pass | — | |
| FR-ING-17 | H | pass | — | |
| FR-ING-19 | L | **defect** | singular; status prose | Four behaviours and a schedule note ("follow in M2 (WP-19b)") in one row. |
| FR-ING-20 | L | pass | — | "Wizard" is a UI noun, acceptable. |
| FR-ING-22 | L | **defect** | unambiguous (form) | Noun phrase, no "shall". |
| FR-DEID-02 | S0 | pass | — | AES-256-GCM is a security requirement, acceptable. |
| FR-DEID-03 | S0 | pass | — | |
| FR-DEID-04 | H | pass | — | |
| FR-DEID-05b | H | pass | — | |
| FR-DEID-05c | H | pass | — | |
| FR-DEID-08 | H | pass | — | |
| FR-DEID-09 | H | pass | — | |
| FR-DEID-10 | H | pass | — | Verification "D" for a computed metric could be "T". |
| FR-DEID-11a | H | pass | — | |
| FR-FEAS-03 | S1 | pass | — | |
| FR-FEAS-04c | S1 | pass | — | |
| FR-FEAS-04d | S1 | pass | — | |
| FR-FEAS-04g | S1 | pass | — | |
| FR-RC-05 | L | pass | — | |
| FR-MOD-01 | S0 | **defect** | implementation-free | Names vLLM in the requirement; CON-12 names builds, not the server. |
| FR-MOD-06 | H | **defect** | singular | Two requirements (gate before release; ruleset names prompt version). |
| FR-MOD-07 | H | **defect** | unambiguous | "see the effect on policy (e.g. …)" leaves the set of effects open. |
| FR-STUDY-04 | L | pass | — | |
| FR-PLAT-04 | S4 | pass | — | |
| FR-PLAT-22 | H | pass | — | |
| FR-PLAT-24 | H | pass | — | Borderline compound (close; stop; keep; delete), kept as one lifecycle action. |
| NFR-PERF-01 | H | pass | — | |
| NFR-PERF-03 | H | pass | — | |
| NFR-USAB-04 | H | pass | — | |
| NFR-COMP-02 | H | **defect** | not a system requirement | A penetration test is a project activity; belongs in TB-DS-04/TB-DS-03 with a pointer. |
| FR-JP-01 | S4 | pass | — | |

**Result: 8 defective of 40 = 20 % (Wilson 95 % interval 10.5 – 34.8 %).** Whole-population indicators that agree with the sample: 58 of 412 rows (14 %) contain two or more "shall"; 22 rows use "should"/"may" as the main modal (acceptable where permission is meant, not where a requirement is); 11 rows contain a vagueness marker (e.g., "notably", "appropriate", "e.g."); Ver column holds 343 T, 38 I, 13 D, 3 A, 24 combined. The B/P/N status column and the Source column are filled on every row, which is better than most SRSs of this size.

**What a 29148-clean SRS of this set would look like:** the same rows, with (a) compound rows split by letter suffix, (b) a short fit criterion in every FR that has none, (c) implementation names moved to CON-nn, (d) status prose moved out of the Requirement cell, (e) project activities moved out of §3. That is an editing pass, not a rewrite; estimated 60–80 rows touched.

---

## 5. Reproduction (scripts used)

All checks ran over `/mnt/project-files/trialbox-design/*.md` excluding `06*.md`, with Python 3 standard library only.

- **Table lint:** for each line starting with `|` whose next line matches `^\|\s*:?-{2,}`, compare cell counts of header, separator and every following `|` row. Output: 01:614 (1 row), 02:1247 (1), 02:1355 (2), 03:273/283/297/308/321/331/346/359/371 (header 8 vs separator 7, 70 rows), 04:1515 (1), 07:407 (1), 08:352 (1).
- **ID resolution:** regex `(FR|NFR)-<AREA>-\d+[a-z]?` and `(DR|IR)-\d+[a-z]?` over each document; compare with the ID set of TB-DS-01 §3. Dangling: none. Root-ID citations without suffix (FR-AUD-01, FR-AUTH-05, FR-DEID-05, FR-FEAS-04 in TB-DS-04 prose) are family references, not errors.
- **Matrix coverage:** ID rows of TB-DS-04 §6.2 (396) vs TB-DS-01 §3 (412): 39 missing as listed in Q-01; AM-01 absent.
- **Stale phrases:** counts of "two sign-off", "entry page", "shadow mode", "MinIO", "MailHog", "TB-SRS-001", "SEC-NN" per document (Q-04, Q-11, Q-28, S-03).
- **Tag regime:** counts of `\bM1\b`, `\bM2\b` per document (S-02).
- **Control blocks:** presence of a control table, a change-history heading and an approvals block per document (§2 and S-09).
- **Sample:** `grep -nE '^\| (FR|NFR|DR|IR)-' 01-SRS.md | shuf --random-source=<(yes 29148) -n 40`.

---

## 6. Path to 4.5 per document

What each document needs to reach 4.5 on paper. Effort is an editing estimate for one person, in hours.

| Doc | Current | Needs (all editing) | Est. h |
| --- | --- | --- | --- |
| 00 | 3.5 | Approvals row; Status column on BD table; superseded text to footnotes; §2.H shortened to a pointer at TB-PLAN-01 (keep the content there). | 2 |
| 00R | 3.5 | Q-05, Q-40; file-number ≠ ID sentence; one row per record document (19a, SIMPLE-PLAN) with IDs. | 1 |
| 01 | 3.5 | Q-02, Q-06, Q-07, Q-08, Q-09; App C additions (S-05); 60–80 row edits; regenerated §2.2 and §1.3 built-inventory lines re-checked against the current master commit (the document cites `a1e55fa` while TB-DS-19 cites `38d93ce` on a branch). | 12 |
| 02 | 4.0 | Q-10, Q-11 (tables only), Q-12, Q-13 (generated Annex B), Q-14; §12 glossary trimmed. | 6 |
| 03 | 3.5 | Q-03, Q-15, Q-16 (two mapping tables), Q-17, Q-18; a residual-risk statement in §3.5 for the build stage (nothing live on synthetic data). | 6 |
| 04 | 3.0 | Q-01 (regenerate), Q-19 (one full case per high-risk suite, procedure template), Q-20, Q-21; completion-report template as Annex (29119-3 §8 fields); §6.3 counts recomputed. | 10 |
| 05 | 3.5 | Q-18, Q-22; re-check the 44 unverified rows or mark each with a check date. | 3 (paper) |
| 07 | 3.5 | Q-23 (one column set, Key column, relationship list), Q-24. | 5 |
| 08 | 4.0 | Q-25, Q-26 (schemas for ICD-13/-14, headings for ICD-03/-12). | 4 |
| 09 | 3.5 | Q-27 (four-line block × 22 screens), Q-28; one layout sketch per home (S16, S8, S13) as ASCII or Mermaid. | 6 |
| 10 | 3.0 | Q-29, Q-30; TM-02 closed on paper by citing JP Core 1.2.0 CodeSystem pages; licence table with the source URL per row. | 4 |
| 11 | 3.5 | Q-31; verification column pointing to TC/OQ IDs instead of sections. | 3 |
| 12 | 3.0 | Q-32, Q-30; a status-accounting paragraph; CI-DOC extended. | 2 |
| 17 | 3.5 | Q-33; References and Definitions sections (S-05, S-06). | 3 |
| 19 | 3.0 | Q-34; fold 19a in as Annex A (Q-35). | 2 |
| 19a | 2.5 | Q-35 (or fold into 19). | 1 |
| 20 | 3.5 | Q-36, Q-37; name the script that produces the count table. | 1 |
| 21 | 3.0 | Q-38, Q-37. | 3 |

Total about 75 hours of editing for the whole set to reach 4.5 on paper. Set-level items S-01 (generated trace) and S-04 (table lint in the repository) are the two that pay back on every later edit.

---

## 7. What 4.5 cannot reach on paper, and what 5.0 needs

These items are written correctly as targets or open items in the documents; they cannot be closed by editing. They cap the set at about 4.5 until the work happens, and 5.0 needs all of them.

| Area | Item | Where it is stated | Closed by |
| --- | --- | --- | --- |
| Measured results | 32 GB fit of judge + verifier on a real RTX 5090; swap time | 02 ADR-03, TD-5; 01 FR-MOD-10; 00 BD-10 | Build step 5 measurement |
| Measured results | 500,000-patient dry run, storage model (bytes per patient per snapshot), lake rebuild time and RAM | 01 NFR-CAP-01/05; 02 §7.5, QS-13; 04 P2–P7 | Step 1 generation and a full run |
| Measured results | Generator time: 5,000 patients in CI < 5 min; 500,000 in one night | 21 §3; 01 FR-SYN-04 | Step 1 PR |
| Measured results | SIGIR / TREC baselines on a real 5090 (current numbers are from a capped RTX PRO 6000) | 01 NFR-PERF-08; 04 G1 | Step 5 gate run |
| Measured results | PHI leak rate (N-07) on synthetic planted spans (build) and on 200 real notes per site (hospital) | 03 §13.6; 04 G5; 01 NFR-PERF-14 | Step 1 check; hospital stage |
| Measured results | Interactive latency p95, night-window fit, 10-user load | 01 NFR-PERF-01..07; 04 P1 | Step 5 or later |
| Real-site validation | SAT (IQ/OQ), PQ, SUS, NASA-TLX, time-motion baseline, recall by chart review | 04 §7.3, §8; 15; 17 §9; 18 | Hospital stage only |
| Real-site facts | SS-MIX2 layout at the head hospital, appointment source, CGMH warehouse views, REDCap field names, mail-server acceptance | 08 IC-01..IC-07; 01 OI-08, OI-09, OI-17 | Site IT and REDCap admins |
| Terminology facts | JLAC10 codes against the site master, MEDIS 「疑い」 modifier code, JP Core system URIs, YJ/HOT→ATC source, licences of MEDIS/JSLM/ATC/WHO ICD-10, SNOMED status | 10 TM-01..06, §11; 05 surprise 3 | Masters in hand, written licence answers |
| Legal | APPI category of the head hospital; Bloom-filter encodings as personal data; CGMH CSMA status; PDPA amendment rules; opt-out wording | 03 OI-1..OI-7 [LEGAL]; 01 OI-12, OI-13 | Counsel and the hospitals (hospital stage) |
| Language | Native review of JA / zh-TW mark labels (OQ-14) | 09 §6, UX-08 | Native speakers |
| Security evidence | Penetration test, ASVS L2 self-assessment results, injection-suite results | 03 §15.1 items 8, 13; 04 G6, S | Executed tests (hospital stage for the pentest) |
| Test evidence | Test cases carrying TB-DS-01 IDs in the repository (Appendix D marker migration), executed results, 29119-3 completion report | 01 App D note 1; 04 §6.4, §9.5 | Code work in steps 1–5 |
| Decisions | OI-14/OI-15 owner confirmations recorded as BD status; ADR statuses Accepted | 01 App B; 02 §9.2 | Owner's word, then one edit |
| Approvals | Every approvals block is blank | all | Signatures, if and when the owner wants them (none needed for the build) |

---

## 8. Top 15 fixes, in order of value

1. Regenerate the TB-DS-04 §6.2 matrix from TB-DS-01 v0.9; add the 39 missing rows and AM-01; fix §6.1/§6.3 text (Q-01).
2. Move FR-MOD-10 out of the FR-SEC table and repair the row (Q-02).
3. Repair the nine TB-DS-03 SC table separators so the SRS-IDs column renders (Q-03).
4. One set-wide pass replacing the "two sign-offs / S20 part 1–2" wording in 02, 04, 09, 11, 17, 19a, 15 (Q-04, S-03).
5. Register: row 0.9 → 0.10; add Distribution column; register 19a and SIMPLE-PLAN under IDs (Q-05, Q-40, S-07).
6. SRS §3 legend and §4 release rule to the build-stage regime; strip status prose from Requirement cells (Q-06, Q-08).
7. SRS characteristics pass on the ~70 rows flagged by the sample pattern: split compounds, add fit criteria, move implementation names to CON-nn, move project activities out of §3 (Q-07).
8. TB-DS-02 ADR table: Decided by/on and Decision drivers; set Accepted where TB-DS-00 fixes the decision; finish table re-tags (Q-10, Q-11).
9. TB-DS-03: fix §1.2 → §7.3; add ASVS-chapter and ISO 27002-theme mapping tables; add a build-tag value per control (Q-15, Q-16, Q-17).
10. TB-DS-04: one full 29119-3 test case and one procedure per high-risk suite as templates; completion-report field list as an annex; renumber §3.4a (Q-19, Q-20).
11. TB-DS-08: add the six missing error codes to §2.3; JSON Schema blocks for ICD-13 and ICD-14 (Q-25, Q-26).
12. TB-DS-07: one column set for every table, a Key column, relationship list; S-28 as its own section; unsplit the change history (Q-23, Q-24).
13. Change histories: add the missing 0.1b (10), 0.1a (12) rows; add time or sequence to all Date cells; cap cell length (S-08, Q-30).
14. Glossary and references: add DET, CCB, IQ/OQ/PQ, SAT, PV, SBOM, SDC, ALCOA+, CRA, STRIDE, ADR to TB-DS-01 App C; add a five-line References section to 07, 08, 09, 10, 11, 12, 17, 21 (S-05, S-06).
15. Put the table-lint and ID-resolution scripts of §5 into the repository (`tools/doclint.py`) so the next edit cannot reintroduce S-04 or S-01 silently. This is a file, not a gate; it runs when someone wants it to.

## §R Re-audit after the TB-REV-006g fix pass (v1.1)

Same yardsticks, same strictness, same auditor as v1.0. Read: every document at the versions in TB-DS-00R v0.11 (00 0.9, 00R 0.11, 01 0.10, 02 0.8, 03 0.5, 04 0.8, 05 0.4, 07 0.5, 08 0.6, 09 0.9, 10 0.2, 11 0.5, 12 0.2, 17 0.7, 19 0.3, TB-REC-01 1.0, 20 1.1, 21 1.2, SIMPLE-PLAN). Checks re-run: `tools/doclint.py` (from `/tmp`), an independent script over the same set (table lint, ID resolution, matrix coverage, Annex B coverage, stale phrases, control blocks), and a fresh 40-row SRS sample with a different seed (§R.4). Nothing here recommends a gate, an approval or a review step; every fix below is an edit.

**Correction to v1.0.** §1 and §2 said "17 scored documents"; the §2 table scores 18 (00, 00R, 01, 02, 03, 04, 05, 07, 08, 09, 10, 11, 12, 17, 19, 19a, 20, 21). The v1.0 mean 3.4 is the mean over those 18 (60.5 / 18 = 3.36). This section uses 18 throughout.

### R.1 Summary

**Set overall: 4.1 / 5** (unweighted mean of 18; 75.0 / 18 = 4.17, not rounded up). Up from 3.4.

**Documents at or above 4.5 (industrial standard for their type): 6 of 18:** TB-DS-00R, TB-DS-08, TB-DS-09, TB-DS-11, TB-DS-12, TB-DS-21. **Twelve are at 4.0.** None is below 4.0. What separates the twelve from 4.5 is no longer structure: it is **stale cross-references and surviving M1/M2/C text** that a reader of the current build regime would act on wrongly, plus, in the SRS, a sample defect rate that did not move. The whole remaining paper work is about 22 hours (§R.5), against 75 in v1.0.

What closed (set level): the traceability chain SRS → V&V is whole (480 of 480 v0.10 rows in TB-DS-04 §6.2 plus AM-01; 0 missing, 0 extra); SRS → architecture is at ID level (TB-DS-02 Annex B, 480 rows); every FR/NFR/DR/IR ID cited anywhere resolves; no malformed table remains (14 → 0); every controlled document has a control table, approvals (except the two living build documents, which carry the owner-merge rule instead), a References section and a change history with a sequence column; one tag legend (TB-DS-00 §2) is cited by every document; the register matches every header.

What did not close: (a) the 29148 sample rate is 8 / 40 again (different defects, §R.4); (b) a residue of pilot-era text survives in prose and in a few tables that builders read (TB-DS-02 §5.2 status cell, TB-DS-04 control table and §3.7, TB-DS-17 §1–§7, TB-DS-05 §5 and §20); (c) a cluster of section renumberings was done in one document and not followed in the documents that cite it (§3.4a → §3.4.1, §2 → §2.H, §5a → §5.2, TB-DS-10 §8 → §3).

### R.2 Per-document re-scores and status of every v1.0 finding

Status values: **closed** (fixed as described or better), **partly** (fixed in part; the open part is stated), **open**. Citations are to the current files. New defects carry R-nn IDs (§R.3).

| Doc | Ver. | v1.0 | v1.1 | v1.0 findings: status with citation | What remains for 4.5 (paper unless marked) |
| --- | --- | --- | --- | --- | --- |
| 00 | 0.9 | 3.5 | **4.0** | Q-39 closed: approvals block present; BD table has a Status column; superseded wording moved to footnotes (113 footnotes, doclint P1 is one long footnote). S-02 closed: §2 is the one legend and every other document cites it. | R-01 (§2 line 29 cites "TB-DS-04 §3.4a", renumbered to §3.4.1 by Q-20); control row reads "Document" where 03/11/12 use "Document ID"; one double blank line (lines 34–35); doclint G3 on the legacy §2.H table (lines 40–42, known historical). 0.3 h. |
| 00R | 0.11 | 3.5 | **4.5** | Q-05 closed (row 0.11 = header; same-edit rule §1 line 25). Q-40 closed (Distribution column). S-07 closed (TB-PLAN-02, TB-REC-01, file-number ≠ ID rule). S-09 closed (status values, living-document 1.0 rule). "All version cells match" confirmed by doclint. | Nothing structural. Line 96 "Appendix D of TB-DS-01 v0.2" is history and reads as such. By the register's own same-edit rule its TB-REV-006g row (1.0) falls behind this v1.1 the moment this file is saved; this audit edits no other file, so that row is the owner's next one-cell edit. |
| 01 | 0.10 | 3.5 | **4.0** | Q-02 closed (FR-MOD-10 in §3.1.21). Q-06 closed (§3 legend S0–S5/H/L; §4 split into build-stage verification and hospital-stage release rule). Q-07 **partly**: 45 split rows with letter suffixes, fit criteria added, NFR-COMP-02/-08 withdrawn to PO-01/-02, CON-17/18 added; the fresh sample still fails 8 / 40 (§R.4). Q-08 **partly**: Notes column added and used (FR-SCR-07, FR-STUDY-09), but status prose remains inside the Requirement or Pri cell of FR-ING-01 (line 282), FR-DEID-04 (323), FR-STUDY-03 (788), NFR-PERF-05 (871), NFR-USAB-08 (931: "the TOTP sentence is H" refers to a sentence no longer in the row). Q-09 closed (App B Status and Raised columns). S-05 closed (App C 61 terms). | R-05 (FR-SEC-11 line 666 points at NFR-COMP-02, itself withdrawn; should point at PO-01); R-06 (three different withdrawn-row layouts: FR-SCR-09 "—/W", FR-SEC-11 "H/—", NFR-COMP-02 "H/W"); R-07 (§1.1 line 34 and AS-08 line 240 still frame the document around the pilot and cite "TB-DS-00 §2 'Pilot dates'", which is now §2.H); R-08 (raw retired tag "C" in prose at lines 47, 250, 379, 756, 942, 1074; §1.3 figure line 76 "M1: API read / M2: External Module"; OI-01/OI-06 "M2"; App D note 3 "add rows in v0.3 … M1"); R-09 (FR-EDC-02 cites HbA1c 3D045 for NGSP while 02/04/10 use 3D046, recorded as TM-07 in TB-DS-10 but not corrected here); the eight sampled rows and their pattern (§R.4). 6 h, then a fresh sample to confirm ≤ 3 / 40. |
| 02 | 0.8 | 4.0 | **4.0** | Q-10 closed (§9.2 Decided by / on, Decision drivers, Build tag; Accepted for ADR-03/-05/-13/-14/-15/-16; ADR-06 filled). Q-11 **partly**: §3.2, §5.2 rows, §8.13.2, §10.3, §12 re-tagged; but the §5.2 console **Status** cell (line 335) still lumps the feasibility input page (S1), the chat command box (S4), role homes (S4) and S20 (S2) under one "[target, H]", and the chat command box row (line 420) says "[target, H] grammar" though FR-CHAT is S4; OC-2 (147) "EDC-lite (C, …)", OC-4 (149) "(BD-01, M1)", §3.1 "hardening for further vendors M2", ADR-07 "(C)". Q-12 closed (QS-13/15/16/17 carry provisional measures). Q-13 closed (Annex B at ID level, 480 rows; A.3 points at TB-DS-20). Q-14 closed (both tables repaired). S-05 closed (§12 trimmed). S-06 closed (Annex C). | R-10 (**Annex B provenance**: header line 1604 "Generated … from TB-DS-01 v0.9 §3" and "the script is in the change history"; the content is in fact complete against v0.10 (all 125 split IDs present, 0 missing), but no generator exists: `tools/gen_trace.py` regenerates TB-DS-04 §6.2 only, and the change history holds no script); R-11 (§5.2 status cell and line 420, above); R-12 (§1.1 line 78 "In the pilot (TB-DS-00 §2 'Pilot dates')" → §2.H); R-13 (ADR-03 F6-12 note placed in the "Affects" column instead of Consequences). Seven ADRs remain Proposed with decider "—", which is honest and not a defect. 3 h. |
| 03 | 0.5 | 3.5 | **4.0** | Q-03 closed (nine tables lint clean; SRS IDs column renders). Q-15 closed (§1.2 → "section 7.3"). Q-16 closed (Annex A.1 ASVS V1–V17 → SC-nn, A.2 ISO 27002 themes → SC-nn). Q-17 **partly**: §4.1 header renamed "Build tag (hospital timing)" (line 275); §4.2–§4.9 headers still "Gate" (285, 299, 310, 323, 333, 348, 361, 373). Q-18 closed (H1 "TB-DS-03"). S-06 closed (Annex B references). §3.5 build-stage residual-risk statement present (line 259). | R-14 (§4.2–4.9 headers); R-15 (§12.2 lines 711–713 still "Whole catalogue; gap analysis" and "ASVS L2 \| SC-90, SC-14, SC-47" instead of pointing at Annex A); R-16 (§16 open-item table has no Status column; OI-10 line 873 says "Still to do: an SRS-ID column" after it was done; OI-12 "Before M1 build of WP-08"); R-17 (§0 line 41 EDCL "(C, TB-DS-00 §2; ADR-14)"; §15.1 heading line 807 cites "§2 'Pilot dates'"); R-18 (control table has no Title row; "Change log" table has no Author column, lines 944–947). 1.5 h. |
| 04 | 0.8 | 3.0 | **4.0** | Q-01 closed (§6.2 regenerated by `tools/gen_trace.py` from v0.10: 481 rows = 480 + AM-01; §6.3 counts S0 45, S1 32, S2 40, S3 12, S4 27, S5 9, H 184, L 127). Q-19 closed (§4.9 six full 29119-3 cases TC-SCR-101, TC-DEID-101, TC-AUTH-101, TC-FEAS-101, TC-RC-101, TC-EDC-101 and procedures TP-01..05; Annex A completion-report template). Q-20 closed (§3.4.1; history row repaired). Q-21 closed (build-stage paragraphs in §1.3 and §1.5). Q-04 **partly**: §3.7 line 253 still counts "S20 clinical-criteria sign-off on phone; S20 code-mapping confirmation on desktop" as two tasks and counts TOTP in the taps (NFR-USAB-08a says it is not counted). | R-19 (**control table**: line 14 "Requirement baseline \| TB-DS-01 v0.6" while §6 is generated from v0.10; line 12 Status "Draft for owner approval" while the register says "Reference, frozen"; line 8 "replaces v0.9, which used a different numbering" for a document at 0.8); R-20 (§1.3 line 39 and §1.5 line 62 cite "§2 'Pilot dates'"); R-21 (retired tags: §3.6 pentest row line 245 "M1: …", §6.4 line 1218 "each M1 requirement … WBS B2 … W1", ENV-REDCAP-DEV "M1 read; M2 module", §6.3 "FR-EDC-01..10, M2"); R-22 (TC-FEAS-101 line 464 cites "TB-DS-21 §5a"; the truth-file schema is TB-DS-21 §5.2); R-23 (history table has no Author column, line 1730). 2 h. |
| 05 | 0.4 | 3.5 | **4.0** | Q-18 closed (H1). Q-22 closed (evaluation criteria stated before the verdicts; Checked column on every candidate table). S-06 closed (References). S-08 closed (sequence numbers). | R-24 (picks and the recommended stack still speak M1/M2/C: §1 line 43 "ADR-14 M2 spike", §5 line 129 "pilot (M1) … After the pilot (M2)", §10 line 206 and §20 line 371 "(C, TB-DS-00 §2)", §17 line 321 "(M2)", §18 line 335, §20 lines 361 and 366 "HAPI in M1; Medplum in M2"); the 40-odd "unverified" cells remain honest markers (closable only by reading each primary source; desk work, about 3 h, not counted below). 1 h for the tags. |
| 07 | 0.5 | 3.5 | **4.0** | Q-23 closed (§2.5 one column set with Key, Null, Retention; §4.12 keys and relationships). Q-24 closed (S-28 promoted to §4.11; inventory ordered; history rejoined; row repaired). S-06 closed. | R-25 (§4.12 lines 503–513 list `study_team`, `study_physicians`, `ethics_record`, `rc_project_link`, `notify_settings`, `notify_log`, `recon_decision` under **S-06** although they moved to S-28 in v0.4; the "generated" table was generated from a stale source); R-26 (§6 lines 583–584 cite "TB-DS-10 §8.3" and "§8.4" for the 「疑い」 and 保険病名 rules; in TB-DS-10 v0.2 those are §3 rules 2 and 5, and §8.3 is "Case and space"); R-27 (DD-04 "Medplum (M2)"; §4.1 `jobs` repeats a 50-character Retention string on 13 rows where a one-line note under the table would do). 1 h. |
| 08 | 0.6 | 4.0 | **4.5** | Q-25 closed (§2.3 has RC-LINK-FIELD, RC-LINK-DUP, UP-META, UP-LAYOUT, UP-IDMATCH, UP-SIZE, NOTIFY-UNDELIVERED). Q-26 closed (§1 tags S0/S2/S3/S4/H/L; ICD-03 and ICD-12 with the common headings; ICD-13 and ICD-14 as JSON Schema 2020-12; §11/§12 renumbered; row repaired). S-06 closed (§14). | At standard. Minor residue, 0.5 h: §4.3 line 317 "M1 = log …; M2 = PREFILL"; §7 line 498 "[target, C]"; N2 row line 595 "M2: tasks and unverified fields"; §11 states the notice payload twice (prose line 601 and the schema block at 603). |
| 09 | 0.9 | 3.5 | **4.5** | Q-27 closed (§3.1 six attributes for all 37 screens; §3.2 layout sketches of S16, S8, S13). Q-28 closed (header field and role work list wording in P5, §2 S1 row, §5, §7, §10; S20 row one Approve). S-06 closed (§13; §9 WCAG 2.2 criteria table). S-08 closed. | At standard. UX-06 line 513 "M2 PWA" (0.1 h). "(was …)" cells in §2 are history and read as such. |
| 10 | 0.2 | 3.0 | **4.0** | Q-29 closed (§1a normative references with edition, what each confirms, status, and what closes each verify flag). Q-30 closed (history unsplit, sequence numbers). S-06 closed. TM-07 records the HbA1c conflict and this file follows 02/04. | R-28 (§11 line 199 "C release only"); S-10 applies to TM-01..06 due dates keyed to TB-PLAN-01 milestones without a "(hospital stage)" prefix; TM-02 (JP Core 1.2.0 CodeSystem URIs) is closable on paper by reading the published pages (about 1 h) and would remove four verify flags; TM-01, TM-03, TM-05, TM-06 need masters or licensors (§R.6). 1.5 h. |
| 11 | 0.5 | 3.5 | **4.5** | Q-04 closed (H-01 (g) one page, one Approve, FR-FEAS-12, BD-13, with the supersession noted). Q-31 closed (§1 build-stage statement, lines 30–32; §4.0 trace table hazard → SRS IDs → SC-nn → suites, gates, OQ steps). S-06 closed (§9). S-08 closed. | At standard for a 14971-structured file at this stage. §4.0 line 97 says "(TB-DS-01 v0.9)" for IDs that resolve against v0.10 (0.1 h). Verification still names suites and gates rather than TC IDs because only six TC IDs exist (TB-DS-04 §4.9); that follows the state of TB-DS-04, not a defect here. |
| 12 | 0.2 | 3.0 | **4.5** | Q-32 closed (§0 build stage; §3 CI-DOC through TB-DS-21, TB-PLAN-02, TB-TMPL-07, TB-REV-006a..g; §5.0 build-stage change record; §5.4 status accounting). Q-30 closed. Q-37 closed by the §6 rule (living build documents start at 1.0; approval is the owner's merge). S-06 closed (References). | At standard. Nothing open. |
| 17 | 0.7 | 3.5 | **4.0** | Q-33 **partly**: §3.2 renumbered 1–7 to match TB-DS-09 S8; §4.1 step 2 is one page, one Approve; §2.2, §4, §5.5, §6, §8 release cells re-tagged; §11 definitions and references added. Open part: prose and inline tags still M1/M2/C at lines 70 ("cross-site query (M2)"), 101, 116, 150 ("M2 / C"), 207 ("before M2"), 285 ("(C)"), 321 ("OMOP optional (C)"), 341 ("e-mail (M1); PWA push (M2)"), 348 ("Yes (M2)"), 366 ("(C)"), 442–450 (§7 "Nothing in M1", "M2 candidate", "C, not M2"), 506 (CO-08 "are C"). | R-29 (control table line 11 "Depends on … TB-DS-00 v0.8, TB-DS-01 v0.8, TB-DS-09 v0.7, TB-DS-07 v0.4": all four stale); R-30 (§1.1 line 53 "the Monday list" where §5.1 makes the clinic-day list the default); the 14 tag spots above. 1.5 h. |
| 19 | 0.3 | 3.0 | **4.0** | Q-34 closed (body tags are build tags; FR-PLAT-12 has Retry; approvals row). S-06 closed (§5 References). | R-31 (control table line 9 "matching TB-DS-01 v0.8" and history row 2 the same, against v0.10); R-32 (FR-PLAT-14 line 90 "· S28" although S28 was merged into the S1 header field, F6-06). 0.3 h. |
| 19a | 1.0 | 2.5 | **4.0** | Q-35 closed (TB-REC-01; control table with ID, Title, Version, Owner, Author, Status, Approvals "None needed (record)", Basis; change history; "two sign-offs" and M1 wording replaced per its history row 2). S-03 closed for this file. | A record issued once; 4.5 would need its gap rows cross-checked against TB-DS-19 v0.3 (row line 97 still cites "S28 (FR-PLAT-14)" as the page; the page is the S1 header field). 0.3 h. |
| 20 | 1.1 | 3.5 | **4.0** | Q-36 closed (tag counts from TB-DS-01 v0.10: 45 / 32 / 40 / 12 / 27 / 9 / 186 / 127 / 2 = 480, caption names the SRS version). Q-37 closed by the TB-DS-12 §6 rule; approvals row carries the owner-merge rule. | R-33 (step 5 line 52 cites "TB-DS-04 §3.4a", renumbered §3.4.1); the count table names no script (`tools/gen_trace.py` produces the matrix, not these counts), so the counts cannot be regenerated by the stated method. 0.3 h. |
| 21 | 1.2 | 3.0 | **4.5** | Q-38 closed (§3.1 rates with source of truth per criterion, taken from `generator.py`; §4.1 name-list sources and licence notes; §5.1 finding-slot catalogue; §5.2 truth-file schema; two new §6 checks; §8 References; approval row with the owner-merge rule; Seq column). Q-37 closed by rule. | At standard for a test-data specification. PHI span rates are marked "Proposed (none are planted today)" and the CI time is a target: both become facts only when step 1 code lands (§R.6). The wrong citation of this document ("§5a") is in TB-DS-04 (R-22), not here. |
| SIMPLE-PLAN | — | not scored | not scored | Registered as TB-PLAN-02 (00R). The file itself still carries no ID or version line, so doclint reports V1 (no Version row) for it. | One control line at the top (ID TB-PLAN-02, version, date) would clear the lint and the set's own rule (TB-DS-00 §1). 0.1 h. Not scored, as in v1.0. |

### R.3 New defects found in the re-audit

Severity as in §3. All are paper fixes.

| ID | Sev. | Doc | Where | Defect |
| --- | --- | --- | --- | --- |
| R-01 | Minor | 00, 20 | 00 §2 line 29; 20 step 5 line 52 | Cite "TB-DS-04 §3.4a" after Q-20 renumbered it §3.4.1. |
| R-02 | Minor | 01, 02, 03, 04 | 01:34, 01:240, 02:78, 03:807, 04:39, 04:62 (also 15:29, hospital stage) | Cite "TB-DS-00 §2 'Pilot dates'"; the pilot dates are now TB-DS-00 §2.H. |
| R-03 | Moderate | 02, 04, 11, 17, 19 | 02:1604 (v0.9), 04:14 (v0.6), 11:97 (v0.9), 17:11 (v0.8), 19:9 (v0.8) | Stale TB-DS-01 version cites in control tables or generated-table headers while the content was produced from or checked against v0.10. In 04 and 02 the header contradicts the generated table beneath it. |
| R-04 | Minor | folder | `tmp-forkA-new-ids.txt` | A working file (the list of 45 split IDs) sits in the controlled folder beside the documents; it is not in CI-DOC and has no control block. Move it under `tools/` or delete it. |
| R-05 | Moderate | 01 | FR-SEC-11 line 666 | Withdrawn row points at NFR-COMP-02, which is itself withdrawn; the live item is PO-01 (§2.7). |
| R-06 | Minor | 01 | FR-SCR-09, FR-SEC-11, NFR-COMP-02 | Three layouts for a withdrawn row (Pri/St "—/W", "H/—", "H/W"). One pattern, stated in the §3 legend. |
| R-07 | Moderate | 01 | §1.1 line 34, AS-08 line 240 | The SRS still introduces itself as the specification "for the pilot (asked for January 2027 …)" while §1.6, §3 and §4 are in the build-stage regime. |
| R-08 | Minor | 01 | lines 47, 76, 250, 379, 756, 942, 1074; OI-01, OI-06; App D note 3 | Retired tags as bare letters in prose ("(C)", "M1: API read", "M2") without the "(was …)" form the legend prescribes. |
| R-09 | Moderate | 01 | FR-EDC-02 | HbA1c 3D045 for NGSP; TB-DS-02 §6, TB-DS-04 TC-ING-031 and TB-DS-10 §5 use 3D046 (TM-07). The frozen SRS is the one place still different. |
| R-10 | Moderate | 02 | Annex B header line 1604 | Says generated from v0.9 by a script "in the change history". Content matches v0.10 (480 / 480, 125 split IDs present); no script exists for Annex B (`tools/gen_trace.py` covers TB-DS-04 §6.2 only). Provenance is wrong twice; coverage is right. |
| R-11 | Major | 02 | §5.2 console row line 335; chat command box row line 420 | One "[target, H]" covers S1, S2 and S4 deliverables (feasibility input page, S20 one Approve, role homes, chat command box). A builder reading §5.2 would defer step-1, -2 and -4 work to the hospital stage. |
| R-12 | Minor | 02 | §1.1 line 78 | Pilot framing and §2 citation (see R-02). |
| R-13 | Minor | 02 | ADR-03 row | F6-12 note placed in "Affects" rather than Consequences. |
| R-14 | Minor | 03 | §4.2–§4.9 headers | Eight of nine SC tables still head the column "Gate"; §4.1 was renamed "Build tag (hospital timing)". |
| R-15 | Moderate | 03 | §12.2 lines 711–713 | Mapping summary still says "Whole catalogue; gap analysis in year 1" and "ASVS L2 \| SC-90, SC-14, SC-47"; Annex A now holds the full views and §12.2 should point there. |
| R-16 | Minor | 03 | §16 | No Status column; OI-10 text "Still to do: an SRS-ID column" after it was done; OI-12 "Before M1 build of WP-08". |
| R-17 | Minor | 03 | §0 line 41; §15.1 heading | EDCL "(C, …)"; "§2 'Pilot dates'". |
| R-18 | Minor | 03 | control table; change log | No Title row; change-log table has Seq, Version, Date, Change and no Author column (every other history has one). |
| R-19 | Major | 04 | control table lines 8, 12, 14 | "Requirement baseline TB-DS-01 v0.6" above a matrix generated from v0.10; Status "Draft for owner approval" against the register's "Reference, frozen"; "0.8 … replaces v0.9". The control record of the V&V plan contradicts its own body. |
| R-20 | Minor | 04 | §1.3 line 39, §1.5 line 62 | See R-02. |
| R-21 | Moderate | 04 | §3.6 line 245; §3.7 line 253; §6.3; §6.4 line 1218; ENV table | "M1:" pentest schedule; two-task S20 wording and TOTP counted in taps (contradicts NFR-USAB-08a and TB-DS-09 §11); "FR-EDC-01..10, M2"; "each M1 requirement … WBS B2 … W1"; "M1 read; M2 module". |
| R-22 | Minor | 04 | TC-FEAS-101 line 464 | Cites "TB-DS-21 §5a"; the schema is TB-DS-21 §5.2. |
| R-23 | Minor | 04 | change history line 1730 | No Author column. |
| R-24 | Moderate | 05 | §1:43, §5:129, §10:206, §17:321, §18:335, §20:361, 366, 371 | Picks and the recommended stack keyed to M1/M2/C; the control table claims alignment to TB-DS-00 v0.8. |
| R-25 | Moderate | 07 | §4.12 lines 503–513 | Eleven relationship rows filed under S-06 for tables that live in S-28 (§4.11). The "generated" list was not regenerated after F6-14. |
| R-26 | Moderate | 07 | §6 lines 583–584 | Cites TB-DS-10 §8.3 / §8.4 for 「疑い」 and 保険病名; those rules are TB-DS-10 §3 items 2 and 5. |
| R-27 | Minor | 07 | DD-04; §4.1 `jobs` | "Medplum (M2)"; repeated long Retention cell. |
| R-28 | Minor | 10 | §11 line 199 | "C release only". |
| R-29 | Moderate | 17 | control table line 11 | Four stale dependency versions (TB-DS-00 v0.8, 01 v0.8, 09 v0.7, 07 v0.4). |
| R-30 | Minor | 17 | §1.1 line 53; 14 tag spots listed in §R.2 | "the Monday list" where the clinic-day list is the default; M1/M2/C in prose. |
| R-31 | Minor | 19 | control table line 9; history row 2 | "matching TB-DS-01 v0.8". |
| R-32 | Minor | 19, 19a | 19 line 90; 19a line 97 | "S28" named as the search page after its merge into S1 (F6-06). |
| R-33 | Minor | 20 | §1 count table | No script named for the counts, so "regenerate from the SRS" has no stated method. |
| R-34 | Minor | SIMPLE-PLAN | top of file | No ID or version line (doclint V1); registered as TB-PLAN-02 in 00R only. |

Lint state for the record (`tools/doclint.py`, run from `/tmp`): 00 G3 (§2.H legacy table, lines 40–42) and P1 (footnote 113); 01 P1 (line 1050, App A P-ENTRY "entry page", historical row); 02 P2 (lines 78 and 1538 "shadow mode", one of them the defined term); 13 P2 (hospital stage); SIMPLE-PLAN V1. All other documents clean. The independent script agrees: 0 malformed tables, 0 split tables, 0 dangling requirement IDs, 0 TBD/TODO.

### R.4 Fresh 29148 sample (seed `006gR`)

Draw: `grep -nE '^\| (FR|NFR|DR|IR)-' 01-SRS.md | shuf --random-source=<(yes 006gR) -n 40`. One draw fell in Appendix D (line 1204, FR-M5-9, a crosswalk row, not a §3 requirement) and was replaced by the first seed-42 draw not already in the sample (FR-DEID-13a), as the v1.0 method states. Judged against ISO/IEC/IEEE 29148 §5.2.5–5.2.6: necessary, implementation-free, unambiguous, singular, complete (fit criterion where a number or behaviour needs one), verifiable, a system requirement (not a project activity).

| Row | Verdict | Note |
| --- | --- | --- |
| FR-ING-04a | pass | Fit criterion present (99 %, unmapped fields reported). |
| FR-ING-07a | pass | |
| FR-ING-12 | pass (note) | Two clauses; the second (flag changed patients) is the purpose of the first. |
| FR-ING-17 | pass | |
| FR-ING-18 | pass (note) | Delete + audit record of the deletion: one behaviour with its evidence. |
| FR-ING-19a | pass | |
| FR-ING-19b | pass | |
| FR-ING-21 | pass | |
| FR-ING-21a | pass | |
| FR-ING-21b | pass | |
| FR-DEID-01 | pass | HMAC is a baseline decision (SC-30), cited. |
| FR-DEID-04 | **fail** | Pri cell carries status prose ("rules + NER pass on synthetic notes, used by `e2e_simple` stage 0"); requirement text mixes production and DEV/TEST timing in one sentence. Attribute misuse (Q-08 pattern). |
| FR-DEID-05c | pass | Precise, verifiable. |
| FR-DEID-13a | **fail** | "Where the IRB allows, the Taiwan national ID **may** be added …": a permission, not a requirement (no shall, no actor, no fit criterion). |
| FR-FEAS-01b | pass | |
| FR-FEAS-06 | pass | |
| FR-FEAS-07 | **fail** | Three statements (status on page; notice on page and e-mail; "jobs may complete overnight" is a fact, not a requirement). Not singular. |
| FR-SCR-02b | pass | |
| FR-SCR-05 | pass (note) | Second sentence is the degenerate case of the first (no verifier). |
| FR-SCR-07 | **fail** | Two independent requirements in one row: the mark vocabulary, and "each mark shall be an audited registry event and shall not change a screening result". |
| FR-SCR-13 | **fail** | Process prose (who imports, how often, which upload, mapping by whom) written as a system requirement; the system part is one sentence. |
| FR-SEC-01b | pass | |
| FR-SEC-07 | pass | |
| FR-SEC-08 | **fail** | Two requirements: prompts fixed and versioned; patient text only inside a delimited field. |
| FR-LOG-01a | pass | |
| FR-LOG-01b | **fail** | Two requirements: storage in UTC; display in site time zone. (The parent FR-LOG-01 was split, but this half still holds two.) |
| FR-LOG-02 | pass | Fit criterion present. |
| FR-MOD-06a | pass | |
| FR-JP-08 | **fail** | "shall support Taiwan conventions: …" — "support" has no fit criterion; filed under the Japan area (FR-JP) while it is the Taiwan counterpart. |
| FR-I18N-04 | pass (note) | Second clause restates FR-CON-06 (duplication, not a defect of this row). |
| FR-STUDY-05a | pass | |
| FR-STUDY-09 | pass | Long but singular and verifiable. |
| FR-NOTIF-07 | pass | |
| NFR-PERF-14a | pass | |
| NFR-CAP-02 | pass (note) | Load condition is in N-18, cited. |
| NFR-USAB-05 | pass (note) | "a task" is bounded by TB-DS-17 §9.2's task list; verification D. |
| NFR-USAB-08a | pass | Numbers per task; TOTP exclusion in Notes. |
| NFR-COMP-06a | pass | |
| DR-03 | pass (note) | "(sqlglot guard)" names an implementation in parentheses; CON-nn would be the place. |
| IR-06 | pass | |

**Result: 8 / 40 fail (20 %; Wilson 95 % interval 10.5–34.8 %)**, the same count as v1.0 (seed 29148). The character changed: v1.0 defects were missing fit criteria, "TBD"-like vagueness, implementation names and a project activity written as a requirement; none of those recur here. The v1.1 defects are five "not singular" rows that are two-line splits (FR-SCR-07, FR-SEC-08, FR-LOG-01b, FR-FEAS-07, FR-SCR-13), one permissive "may" (FR-DEID-13a), one vague verb without a fit criterion (FR-JP-08) and one attribute-cell misuse (FR-DEID-04). The set-wide count of rows with two or more "shall" is the pattern to chase: the eight above are instances of it, and the 45 splits of v0.10 removed the compounds the v1.0 sample happened to hit, not the pattern. The SRS stays at 4.0 until a fresh draw after the next pass comes in at 3 / 40 or fewer.

### R.5 Remaining paper fixes, ranked by value, with effort

Effort is editing time for one person. Total about 22 h. Items 1–4 move five documents (01, 02, 03, 04, 07) to 4.5 and the set to about 4.4.

| # | Fix | Docs | Est. h |
| --- | --- | --- | --- |
| 1 | **Cross-reference pass**, grep-driven: "§3.4a" → §3.4.1 (R-01); "§2 'Pilot dates'" → §2.H (R-02); TB-DS-01 version cites → v0.10 (R-03); "TB-DS-21 §5a" → §5.2 (R-22); "TB-DS-10 §8.3/§8.4" → §3 rules 2 and 5 (R-26); TB-DS-17 dependency versions (R-29); TB-DS-19 v0.8 (R-31). | 00, 02, 03, 04, 07, 11, 17, 19, 20 | 2 |
| 2 | **TB-DS-04 control record and residue** (R-19, R-20, R-21, R-23): baseline v0.10, status per register, drop "replaces v0.9"; §3.7 one-task S20 and TOTP not counted; §3.6, §6.3, §6.4, ENV table re-tagged; Author column. | 04 | 2 |
| 3 | **TB-DS-02 §5.2 status cell by step and Annex B provenance** (R-10, R-11, R-12, R-13): split the console status cell into S1 / S2 / S4 / H items; line 420 to S4; OC-2, OC-4, §3.1, ADR-07 tags; Annex B header to v0.10 and either add an Annex B mode to `tools/gen_trace.py` or state that the annex is maintained by hand and checked by the coverage script. | 02 | 3 |
| 4 | **SRS characteristics pass 2** (R-05..R-09 and §R.4 pattern): split every row with two or more "shall" that are independently testable (letter suffixes, as v0.10 did); replace "may" rows with a shall or move them to §2 assumptions; give "support" rows a fit criterion; move FR-SCR-13's process sentences to TB-DS-04 §8.9 and keep the system sentence; strip status prose from the five cells named in §R.2; FR-SEC-11 → PO-01; one withdrawn-row layout; §1.1 and AS-08 in build-stage terms; bare C/M1/M2 to "(was …)" or removed; FR-EDC-02 → 3D046. Then re-draw 40 rows with a new seed. | 01 | 6 |
| 5 | **TB-DS-07 §4.12 regeneration and cross-refs** (R-25, R-26, R-27). | 07 | 1 |
| 6 | **TB-DS-03 finish** (R-14..R-18): eight headers; §12.2 pointing at Annex A; OI Status column and OI-10/OI-12 text; EDCL and §15.1 wording; Title row; Author column. | 03 | 1.5 |
| 7 | **TB-DS-17 prose re-tag** (R-30 and the 14 spots in §R.2); "Monday list" → clinic-day list. | 17 | 1.5 |
| 8 | **TB-DS-05 picks** (R-24): §5, §20, §1, §10, §17, §18 in S/H/L terms; control table alignment line to TB-DS-00 v0.9. | 05 | 1 |
| 9 | **TB-DS-10** (R-28; S-10 prefix on TM due dates; TM-02 closed on paper by reading the JP Core 1.2.0 CodeSystem pages and recording the URIs read). | 10 | 1.5 |
| 10 | **TB-DS-19 / TB-REC-01 / TB-DS-20 / TB-DS-00 one-liners** (R-01, R-31, R-32, R-33; "Document ID" label; double blank line); name the method for the TB-DS-20 counts (a 10-line count mode in `tools/gen_trace.py`, or the grep). | 00, 19, 19a, 20 | 1 |
| 11 | **Housekeeping** (R-04, R-34): move or delete `tmp-forkA-new-ids.txt`; one control line at the top of SIMPLE-PLAN (TB-PLAN-02); the register's TB-REV-006g row to 1.1 (same-edit rule). | folder, SIMPLE-PLAN, 00R | 0.5 |
| 12 | **TB-DS-08 and TB-DS-09 minor residue** (DET M1/M2 line 317, "[target, C]" line 498, N2 "M2" line 595, duplicate payload prose; UX-06 "M2"). Already at 4.5; this is finish. | 08, 09 | 0.6 |

Not in the total: re-reading the primary sources behind the ~40 "unverified" cells in TB-DS-05 (desk work with internet, about 3 h) — honest markers until then.

### R.6 Unreachable on paper (unchanged from §7, with three additions)

Every row of §7 stands: none of them was, or could have been, closed by the fix pass, because each needs a measurement, a site, a master, a licensor, counsel, a native speaker, executed tests or a signature. Three items surfaced or sharpened in this pass belong on the same list:

| Area | Item | Where stated | Closed by |
| --- | --- | --- | --- |
| Test data | PHI span rates in the synthetic notes are "Proposed (none are planted today)"; CI generation time "target under 5 minutes, not yet measured" | 21 §3.1, §3 | Step 1 code and the first `--profile ci` run, which then write the numbers back into TB-DS-21 (living document) |
| Terminology | JLAC10 analyte codes, MEDIS 「疑い」 modifier code, YJ/HOT → ATC source, site LOINC for amyloid and p-tau; the HbA1c 3D045 / 3D046 question against the MHLW table and the site master | 10 TM-01, TM-03, TM-05, TM-06, TM-07 | Site masters and licensors; the paper part (SRS FR-EDC-02 → 3D046, TM-02 URIs) is in §R.5 |
| Requirements quality | Whether the SRS pass 2 brings the 29148 sample rate to ≤ 3 / 40 | §R.4 | A fresh seeded draw after the edit; paper to do, measurement to confirm |

What 5.0 needs is as §7 says: measured results on the real card and at full scale, real-site validation, the legal answers, native review, executed security tests, test cases carrying TB-DS-01 IDs in the repository with results, ADR and BD statuses settled by the owner's word, and signatures if the owner ever wants them. None of these is a document edit, and none is a gate: the documents already state each one correctly as a target or an open item.

### R.7 Reproduction (this pass)

- `cd /tmp && python3 /mnt/project-files/trialbox-design/tools/doclint.py` — output as listed at the end of §R.3.
- Independent checks (Python 3 standard library, run with `-I`): §3 ID rows of 01 (480, all unique) against §6.2 of 04 (481 incl. AM-01; 0 missing, 0 extra) and Annex B of 02 (480; 0 missing, 125 split IDs present); table lint as §5 (0 defects); blank-line-split tables (0); dangling FR/NFR/DR/IR IDs in 00, 02, 03, 04, 05, 07, 08, 09, 10, 11, 12, 17, 19, 19a, 20, 21 (0); `\bM1\b`, `\bM2\b`, "two sign-off", "entry page", "shadow mode" counts per file; presence of control table, approvals, references, change-history heading and last-row version per file.
- Stale cross-references: `grep -n '§3\.4a' *.md`; `grep -n "§2 'Pilot dates'" *.md`; `grep -nE 'TB-DS-01 v0\.[0-9]+' *.md` compared with the register (0.10).
- Sample: §R.4, seed `006gR`, replacement rule as §4.

---

## §F Final audit after pass 2 (v1.2)

Same yardsticks, same strictness, same auditor as v1.0 and §R. Read: every document at the versions in TB-DS-00R v0.12 (00 0.10, 00R 0.12, 01 0.11, 02 0.9, 03 0.6, 04 0.9, 05 0.5, 07 0.6, 08 0.7, 09 0.10, 10 0.3, 11 0.6, 12 0.3, 17 0.8, 19 0.4, TB-REC-01 1.1, 20 1.2, 21 1.2, TB-PLAN-02 1.0). Checks re-run: `tools/doclint.py` (from `/tmp`), an independent script over the same set (table lint, blank-line splits, SRS §3 population, TB-DS-04 §6.2 coverage, TB-DS-02 Annex B coverage and tag agreement, control blocks, retired-tag counts, stale cross-references), `tools/gen_trace.py --counts`, and a fresh 40-row SRS sample with a third seed (§F.4). Every claim of the pass-2 change-history rows was checked in the text it points at, not taken from the row. Nothing here recommends a gate, an approval or a review step; every fix is an edit.

### F.1 Summary

**Set overall: 4.4 / 5** (unweighted mean of 18; 80.0 / 18 = 4.44, not rounded up). Up from 4.1 (§R) and 3.4 (v1.0).

**Documents at or above 4.5 (industrial standard for their type): 16 of 18:** TB-DS-00, TB-DS-00R, TB-DS-01, TB-DS-04, TB-DS-05, TB-DS-07, TB-DS-08, TB-DS-09, TB-DS-10, TB-DS-11, TB-DS-12, TB-DS-17, TB-DS-19, TB-REC-01, TB-DS-20, TB-DS-21. **Two are at 4.0:** TB-DS-02 (Annex B one SRS version behind, with a false provenance claim and one wrong tag, §F.3 F-01) and TB-DS-03 (17 retired-tag spots in tables with no reading rule, F-05). Both are paper fixes of about one hour each; with them the set would be 4.5 (81.0 / 18).

What closed since §R: 30 of the 34 R-findings closed outright and 4 partly (none open); 10 of the 12 L8 document items closed in the design set, L8-02 and L8-07 partly (the rest is a measurement), L8-09 is outside this folder. The SRS passed its own exit condition: the fresh sample fails **2 / 40 (5 %)** against 8 / 40 in both earlier draws, and set-wide not one of the 600 rows carries two or more "shall", none carries a vagueness marker, and every row but the five withdrawn ones is a "shall" sentence. The SRS → V&V chain is whole at 600 / 600 plus AM-01, with every Pri tag in the matrix equal to the SRS; the TB-DS-20 counts are reproduced to the row by `gen_trace.py --counts`; the register matches every header; 0 malformed tables, 0 dangling IDs, 0 TBD/TODO; the only doclint hits are two definitional "shadow mode" lines in 02 and the superseded plan 13.

What did not close: the one recurring pattern is **version cites that lag the SRS by one step** because the SRS moved to 0.11 in the same pass that fixed them to 0.10 (02 Annex B header, 11 §4.0, 17 Depends-on, 21 Status; F-01, F-02). Annex B of TB-DS-02 is the only place where this changes content: it holds 480 of the 600 rows (§F.5).

### F.2 Per-document scores and status of every §R finding

Status values as in §R: **closed**, **partly** (open part stated), **open**.

| Doc | Ver. | v1.0 | §R | §F | §R findings: status with citation | What remains for 4.5 / 5.0 (paper unless marked) |
| --- | --- | --- | --- | --- | --- | --- |
| 00 | 0.10 | 3.5 | 4.0 | **4.5** | R-01 closed (§2 line 30 cites TB-DS-04 §3.4.1). "Document ID" and "Title" rows present; the double blank line is gone (no consecutive blank lines). doclint clean (the §2.H G3 hits and the footnote P1 of §R are gone). | F-07: six BD-table cells use bare M1 / M2 (BD-01 line 64, BD-03 66, BD-05 68, BD-09 72, BD-18 81, N-01 89) while the only reading rule (line 34, "'M1' below means what a hospital pilot needs") covers §2.H. 0.3 h. |
| 00R | 0.12 | 3.5 | 4.5 | **4.5** | All rows match headers (doclint V clean; independent check agrees). TB-PLAN-02 and TB-REC-01 rows present; Distribution column; same-edit rule. | By the same-edit rule its TB-REV-006g row (1.1) falls behind this v1.2 when this file is saved; this audit edits no other file, so that cell is the owner's next edit (F-08). Line 96 is history. |
| 01 | 0.11 | 3.5 | 4.0 | **4.5** | Q-07 closed: 600 rows, **0 rows with two or more "shall"** (58 in v0.9, pattern chased in §R.4), 0 vagueness markers, 165 "(split from …)" rows; fresh sample 2 / 40 (§F.4), below the ≤ 3 / 40 exit set in §R.4. Q-08 closed (FR-DEID-04 line 328 Pri cell is "S1 (was M1)", status prose in Notes; FR-STUDY-03, NFR-PERF-05, NFR-USAB-08 clean). R-05 closed (FR-SEC-11 line 735 → PO-01). R-06 **partly** (FR-SEC-11 "— (was H)", NFR-COMP-02/-08 "— (was M1)"; FR-SCR-09 line 416 and NFR-USAB-02 line 1034 still bare "—"). R-07 closed (§1.1 line 34 build-stage purpose, §2.H; AS-08 line 240). R-08 closed (line 47 "(L)", line 76 figure "S3 / L", OI-01, OI-06 "(L)"; OI-14 names the superseded split as history). R-09 closed (FR-EDC-02 line 443 no longer carries a code; "codes per TB-DS-10"). | F-03 (NFR-COMP-01 line 1059 "pilot-gate controls of TB-DS-03": the column was renamed, R-14); F-04 (FR-SEC-05 compound, two bare "—" rows, §1.6 line 139 "split in v0.10" while v0.11 split 120 more). 0.5 h. 5.0 needs the repository test markers in TB-DS-01 IDs (§7). |
| 02 | 0.9 | 4.0 | 4.0 | **4.0** | R-10 **partly**: header line 1604 now says hand-maintained and "against TB-DS-01 v0.10 §3 (480 rows)", which is true; but it also says coverage "is checked with `tools/doclint.py`", and doclint has no Annex B check (nor has `gen_trace.py` an Annex B mode), and the annex was not extended when the SRS went to 0.11 in the same pass: **480 of 600 rows** (F-01, §F.5). R-11 closed (line 335 console status split into S1 / S2 / S3 / S4 / H / L items; line 420 chat command box S4). R-12 closed (line 78 §2.H). R-13 closed (ADR-03 Consequences carry the 6 Nov configuration and four fit options). Tables and headings carry no M1/M2/C (lines 22–23 state the prose rule). | F-01: regenerate Annex B from v0.11 (add an `--annex-b` mode to `gen_trace.py` using the §10.3 area rule, or extend by hand), header to v0.11, drop or make true the doclint claim, FR-DEID-04 tag H → S1 (line 1644; SRS and TB-DS-04 say S1). 1 h. Seven ADRs "Proposed" with decider "—" remain honest, not a defect. |
| 03 | 0.6 | 3.5 | 4.0 | **4.0** | R-14 closed (all nine SC headers "Build tag (hospital timing)", lines 276–374). R-15 closed (§12.2 lines 19–21 of the section point at Annex A.1 / A.2). R-16 closed (§16 Status column; OI-10 "Closed"; OI-12 H). R-17 closed (EDCL "(L, …)" line 41; §15.1 heading cites §2.H). R-18 closed (Title row; change log Seq, Version, Date, Author, Change). Annex A.1 (ASVS V1–V17) and A.2 (27002 themes) present. | F-05: 17 spots of bare M1 / M2 in tables and prose with no "(was …)" form and no reading rule in §0 (lines 67, 96, 133, 181, 304 SC-22 "KEK wrapping M1", 339 SC-48 "Pilot (M1) is read-only", 367 SC-73, 397 "Pilot (M1)", 405 and 414 auditor "New (M1)", 411, 428, 450 "Yearly (M1)", 451, 510, 573, 632). §R did not list them; the omission is this auditor's. 1 h. |
| 04 | 0.9 | 3.0 | 4.0 | **4.5** | R-19 closed (control table: baseline TB-DS-01 v0.11, Status "Reference, frozen", version note explains the 0.9 numbering). R-20 closed (lines 39, 62 §2.H). R-21 **partly**: §3.6 pentest row re-tagged (PO-01, H / L); §3.7 S20 is one task and "a TOTP code entry is not counted"; ENV table re-tagged; §6.4 "each M1 requirement" gone; §6.3 line 1328 still "FR-EDC-01..10, M2". R-22 closed (TC-FEAS-101 cites TB-DS-21 §5.2). R-23 closed (Author column). Matrix: **601 ID rows = 600 + AM-01, 0 missing, 0 extra**, every Pri tag equals the SRS; §6.3 counts (57 / 36 / 58 / 17 / 35 / 9 / 228 / 155) equal `gen_trace.py --counts`. §4.9: 7 full 29119-3 cases and 5 procedures; Annex A completion report. L8-04 (G2 "Projected, not measured", reader named), L8-05 (G1 zh-TW provisional), L8-10 (ENV-GPU "does not exist yet") closed. | F-06: §6.3 one cell; §12 is the hospital-stage schedule in M1 / M2 / WP / MS terms under an H-tagged heading with its date pointer (S-10 satisfied; leave it). 0.1 h. 5.0 needs executed tests and a completion report (§7). |
| 05 | 0.5 | 3.5 | 4.0 | **4.5** | R-24 closed (no M1 / M2 / C outside the change history; §5 pick "build stage S0 / hospital stage H / later L"; §10, §17, §18, §20 in S / H / L terms). L8-06(b) closed (§20 line 391: Gemma 4 licence read as Apache-2.0 on 2026-11-07, earlier generations noted). Evaluation criteria and Checked column present. | At standard for a reuse survey. 37 candidate cells remain "unverified" (44 in v1.0): honest markers, closable only by reading each primary source (about 3 h desk work, not counted). |
| 07 | 0.6 | 3.5 | 4.0 | **4.5** | R-25 closed (§4.12 lines 505–515 file `study_team`, `rc_project_link`, `notify_log`, `recon_decision` under S-28). R-26 closed (§6 lines 585–586 cite TB-DS-10 §3 rules 2 and 5). R-27 closed (DD-04 "(L, ADR-14 spike)"; `jobs` retention as one footnote). One column set: all 17 field tables carry Table / Field / Type / Key / Null / Class / PII / Retention / Notes. | At standard. Nothing open. |
| 08 | 0.7 | 4.0 | 4.5 | **4.5** | §R residue closed: §4.3 "H: log + optional CASE … L: PREFILL"; §7 "[target, L]"; N2 row "later (L)"; §11 payload stated once (heading then schema block). §1 tags S0 / S1 / S2 / S3 / S4 / H / L. | At standard. Nothing open. (Line 185 "TB-DS-10 §8.2" resolves to row 8.2 of the normaliser table, NFKC: correct.) |
| 09 | 0.10 | 3.5 | 4.5 | **4.5** | UX-06 "(L; TB-DS-17 CO-02)". §3.1 six-attribute table covers every screen incl. S4 (line 313); S28 marked merged into the header field; no M1 / M2 outside "(was …)" cells and history. | At standard. Nothing open. 5.0 needs native review of the JA / zh-TW labels (§7). |
| 10 | 0.3 | 3.0 | 4.0 | **4.5** | R-28 closed ("(L)" in §11). S-10 closed (TM-01, TM-05, TM-06 due "Hospital stage (H) …"). TM-02 attempted on paper and honestly left open (line 206: the JP Core 1.2.0 artifacts page lists no CodeSystem for MEDIS, YJ, HOT or JLAC10). §1a normative references present. | F-09: TM-07 (line 211) still says "TB-DS-01 FR-EDC-02 still cites 3D045 for NGSP"; the SRS row no longer carries a code (R-09 closed). 0.1 h. 5.0 needs the masters and licences (§7). |
| 11 | 0.6 | 3.5 | 4.5 | **4.5** | §4.0 trace table present (hazard → SRS IDs → SC-nn → suites and gates); §1 build-stage statement. | F-02: §4.0 line 97 "(TB-DS-01 v0.10)" (was v0.9 at §R; the SRS moved again). IDs resolve against v0.11. 0.1 h. |
| 12 | 0.3 | 3.0 | 4.5 | **4.5** | L8-08 closed (CI-MOD line 58 names the CON-12 builds and adds the serving configuration to what is pinned; notes the 6 Nov run has no file hashes). CI-DOC lists TB-DS-00..21, TB-PLAN-01/02, TB-TMPL-01/07, TB-REC-01, TB-REV-006..006g. | At standard. Nothing open. |
| 17 | 0.8 | 3.5 | 4.0 | **4.5** | R-29 **partly** (Depends-on line 11 updated to TB-DS-01 v0.10, TB-DS-09 v0.10, TB-DS-07 v0.6; the SRS is now 0.11). R-30 closed (line 53 "the PI list before each clinic day … with Monday as the fallback"). The 14 tag spots of §R closed (no M1 / M2 outside line 21's legend sentence and the history). §11 definitions and references. | F-02: one Depends-on cell. 0.1 h. 5.0 needs the pilot baseline that replaces every (E) figure (§7). |
| 19 | 0.4 | 3.0 | 4.0 | **4.5** | R-31 closed (line 9 "TB-DS-01 v0.11"). R-32 closed (FR-PLAT-14 line 90 "header command field (FR-UI-01); no separate screen"). Approvals row; body tags S3 / S4 / H / L (30 functions). | At standard. Nothing open. |
| 19a | 1.1 | 2.5 | 4.0 | **4.5** | R-32 closed (history row 3; search is the header command field). Control table complete for a record. | At standard for a record issued once. |
| 20 | 1.2 | 3.5 | 4.0 | **4.5** | R-33 closed: the count table names `python3 tools/gen_trace.py --counts` and the command reproduces it exactly (57 / 36 / 58 / 17 / 35 / 9 / 228 / 155 / 5 = 600). R-01 closed (step 5 "TB-DS-04 §3.4.1"). L8-05 closed (step 5 done-when: N-11 in EN, JA and zh-TW, serving configuration recorded, fit result written into TB-DS-02). | At standard for the living page. Nothing open. |
| 21 | 1.2 | 3.0 | 4.5 | **4.5** | Unchanged since §R; PHI span rates "Proposed (none are planted today)" and CI time "target … not yet measured" remain honest targets. | F-02: Status row line 9 "FR-SYN-01..04 in TB-DS-01 v0.10" (true as origin; cite the current version or none). 0.1 h. 5.0 needs the step-1 code (§R.6). |
| SIMPLE-PLAN | 1.0 | — | — | not scored | R-34 closed (control table: TB-PLAN-02, 1.0, date, owner, status). doclint V1 gone. | Not scored, as before. |

Hospital-stage documents (not scored, read for cross-references only): 13 line 90 "two sign-offs" (superseded plan; doclint P2) and lines 86, 151; 15 line 29 "TB-DS-00 §2 'Pilot dates'" (→ §2.H). 0.2 h if the owner wants the superseded plan tidy (F-10).

### F.3 New defects found in this pass

| ID | Sev. | Doc | Where | Defect | Fix |
| --- | --- | --- | --- | --- | --- |
| F-01 | Moderate | 02 | Annex B, line 1604 and table | 480 of 600 SRS rows. The 120 absent rows are exactly the v0.11 split rows: 116 whose root row is in the annex, 4 (FR-AUTH-01c, FR-ING-04c, FR-SCR-04c, NFR-COMP-03c) whose root was already split, with sibling "a" present. The header claims coverage "is checked with `tools/doclint.py`": doclint has no Annex B check and `gen_trace.py` has no Annex B mode, so the stated rule ("after every SRS version … missing rows are added") was not applied on the very version that wrote it. One tag disagrees with the SRS: FR-DEID-04 "H" (line 1644) against "S1" in TB-DS-01 line 328 and TB-DS-04 line 584; a builder reading the annex would defer step-1 work. | `gen_trace.py --annex-b` (same area rule as §10.3) or a hand extension; header to v0.11; drop the doclint claim or add the check (10 lines); FR-DEID-04 → S1. 1 h. |
| F-02 | Minor | 11, 17, 21 | 11:97, 17:11, 21:9 | "TB-DS-01 v0.10" one pass after R-03 / R-29 fixed the same cells to v0.10: the SRS moved to 0.11 in the same edit. | Cite "TB-DS-01 (version per TB-DS-00R)" in Depends-on rows, or move these three cells in the same edit as the SRS. 0.2 h. |
| F-03 | Moderate | 01 | NFR-COMP-01, line 1059 | "the pilot-gate controls of TB-DS-03 (SC-nn)" names a set by a column heading that TB-DS-03 renamed to "Build tag (hospital timing)" (R-14). The set the requirement binds is no longer identifiable by that name: fails *unambiguous*. | "the controls of TB-DS-03 §4 tagged H (hospital timing) or S0". 0.1 h. |
| F-04 | Minor | 01 | FR-SEC-05 (726); FR-SCR-09 (416), NFR-USAB-02 (1034); §1.6 (139) | FR-SEC-05 holds three statements, the third a process step (shown to hospital IT before release). Two withdrawn rows carry Pri "—" without the "(was …)" the §1.6 rule prescribes (R-06 residue). §1.6 says split rows are "a row split in v0.10"; v0.11 split 120 more. | Split FR-SEC-05 (a: allowlist; b: PHI scan zero hits) and move the review step to TB-DS-04 §9.5 with a pointer; "— (was M1)" on the two rows; "split in v0.10 or v0.11". 0.4 h. |
| F-05 | Minor | 03 | 17 lines listed in §F.2 | Bare M1 / M2 in SC Status cells, the §5 identity tables, the §10 backup set and §13, with no "(was …)" and no reading rule in §0. | "(was M1)" → H or S0 per TB-DS-00 §2; one legend sentence in §0 as 02 has. 1 h. |
| F-06 | Minor | 04 | §6.3 line 1328 | "FR-EDC-01..10, M2" in the high-risk list. | "L". 0.1 h. |
| F-07 | Minor | 00 | BD-01, BD-03, BD-05, BD-09, BD-18, N-01 | Retired tags in the baseline's own decision table; the §2.H note (line 34) covers §2.H only. | "(was M1)" form or "hospital pilot". 0.3 h. |
| F-08 | Minor | 00R | TB-REV-006g row | 1.1 → 1.2 once this file is saved (same-edit rule, as in §R). | One cell. |
| F-09 | Minor | 10 | TM-07, line 211 | "TB-DS-01 FR-EDC-02 still cites 3D045 for NGSP": the SRS row no longer carries a code. | "TB-DS-01 FR-EDC-02 defers to this file". 0.1 h. |
| F-10 | Minor | 13, 15 (hospital stage) | 13:86, 90, 151; 15:29 | Superseded-plan residue: "two sign-offs", "§2 'Pilot dates'". Not scored. | 0.2 h, optional. |

Checks that pass, for the record: 0 malformed tables and 0 blank-line splits in the scored set (the five "splits" a naive script reports in 04 §4.9 and one in 15 are consecutive two-column case tables, each with its own header); 0 dangling FR / NFR / DR / IR / BD / N / SC IDs; 0 TBD / TODO; every scored document has a control table, approvals (or the owner-merge rule), a References section where the type calls for one, and a change history whose last row equals the header version; `tools/doclint.py`: 02 P2 (lines 78 and 1538, both definitional), 13 P2 (superseded plan), all else clean; TB-DS-04 matrix Pri = SRS Pri on every row; TB-DS-20 counts = `gen_trace.py --counts`.

### F.4 Fresh 29148 sample (seed `006gF`)

Draw: `grep -nE '^\| (FR|NFR|DR|IR)-' 01-SRS.md | shuf --random-source=<(yes 006gF) -n 40`. Three draws fell in Appendix D (lines 1317, 1324, 1330: crosswalk rows FR-CONV-3, FR-M5-9, FR-UX-32) and were replaced by the first seed-42 draws not already in the sample and not in Appendix D (FR-MAIL-02, IR-03a, FR-ING-09), as the v1.0 method states. Judged against ISO/IEC/IEEE 29148 §5.2.5–5.2.6 exactly as in §4 and §R.4.

| Row | Verdict | Note |
| --- | --- | --- |
| FR-ING-03a | pass (note) | A list-display rule filed under ING; filing, not a characteristic. |
| FR-ING-09 | pass | |
| FR-ING-15a | pass | One report, its content enumerated. |
| FR-ING-17 | pass (note) | Refuse + keep the previous snapshot current: the second clause is the effect of the refusal. |
| FR-ING-18 | pass (note) | As §R.4: delete + audit record of the deletion. |
| FR-ING-19a | pass | |
| FR-ING-19b | pass | |
| FR-ING-21 | pass | |
| FR-DEID-01 | pass (note) | HMAC named; SC-30 cited (as §R.4). |
| FR-DEID-03 | pass | |
| FR-DEID-05d | pass (note) | Categories to detect; the fit is NFR-PERF-14 / N-07 by the set's structure. |
| FR-DEID-11a | pass | N-01 cited. |
| FR-FEAS-04b | pass | |
| FR-FEAS-05a | pass | |
| FR-FEAS-10 | pass (note) | Answer from the D2 source and label it: the label is the evidence. |
| FR-SCR-04c | pass | |
| FR-CHAT-02 | pass | |
| FR-CHAT-06 | pass | |
| FR-CHAT-07 | pass (note) | A modifiability requirement in an FR table; verifiable by inspection of the job interface. |
| FR-AUTH-04 | pass (note) | Keycloak named; BD-01 cited. |
| FR-AUTH-04a | pass | |
| FR-AUTH-05a | pass | |
| FR-AUTH-11a | pass | |
| FR-AUTH-12 | pass | "use needs two people" is the fit. |
| FR-AUD-01e | pass | |
| FR-AUD-01j | pass | |
| FR-SEC-05 | **fail** | Three statements (allowlisted content; PHI scan with zero hits; shown to hospital IT before release), the third a process step. Not singular. |
| FR-ERR-06 | pass | |
| FR-ERR-06b | pass | |
| FR-LOG-03b | pass | |
| FR-MAIL-02 | pass | |
| FR-STUDY-07a | pass | |
| FR-STUDY-10a | pass (note) | One prohibition over three actions: one access rule. |
| FR-NOTIF-08 | pass | |
| FR-PLAT-11 | pass | |
| NFR-PERF-12 | pass | Fit present (one working day). |
| NFR-MAINT-02 | pass | Components named through CON-15/16/17; fit stated. |
| NFR-COMP-01 | **fail** | "pilot-gate controls of TB-DS-03" no longer names an identifiable set (F-03): not unambiguous, hence not verifiable as written. |
| IR-03a | pass | |
| IR-07 | pass (note) | Ed25519 named; SC-53 cited. |

**Result: 2 / 40 fail (5 %; Wilson 95 % interval 1.4–16.5 %)**, against 8 / 40 (20 %; 10.5–34.8 %) in v1.0 and §R. Below the ≤ 3 / 40 exit condition set in §R.4. Whole-population indicators agree: 0 of 600 rows contain two or more "shall" (58 of 412 in v1.0); 0 rows carry a vagueness marker (11 in v1.0); 3 rows use "may" (all permissions); 0 use "should"; the only rows without "shall" are the five withdrawn ones; 165 rows carry "(split from …)" and 424 carry "(was …)". The two failures are of different kinds from each other and from both earlier draws: one compound row the split pass did not reach (its third clause is a process step rather than a second "shall", which is why the two-"shall" count missed it), and one cross-document reference broken by a rename made in the same pass. Neither is the pattern of the earlier samples; nothing systematic is left to chase.

### F.5 TB-DS-02 Annex B against the 120 new SRS rows

Asked directly: does Annex B cover the 120 v0.11 rows, and is the state acceptable?

- **Coverage:** no. Annex B holds 480 rows (every v0.10 row); all 120 v0.11 rows are absent. The absent rows are all letter-suffix splits: for 116 the root row is in the annex; for the other 4 the sibling "a" row is. Since the annex traces by area rule (requirement → the containers, ADRs and quality scenarios of its area, §10.3), every absent row's trace is the same as its root's or sibling's. **No design gap is hidden**: the information content of the 120 rows is fully determined by rows already present.
- **Acceptable as information:** yes, for the reason above, and TB-DS-04 §6.2 carries all 600 at ID level, so the chain SRS → test is whole.
- **Acceptable as a controlled record:** no. The header states a version (v0.10) one step behind the baseline the same pass froze (v0.11); it states a check (doclint) that does not exist; its own rule ("after every SRS version … missing rows are added") was not followed; and one present row (FR-DEID-04) carries the wrong tag. For a frozen reference whose purpose is traceability at ID level, that is a Moderate nonconformity (F-01) and the reason TB-DS-02 stays at 4.0.
- **Fix:** mechanical. `gen_trace.py` already reads the SRS and knows the tags; an `--annex-b` mode that applies the §10.3 area table is about 40 lines, and `doclint.py` can test Annex B coverage in 10. Then the header is true and the annex follows every SRS version for free. 1 h.

### F.6 Updated design-review overall (TB-REV-006f)

Two of the eight areas scored in TB-REV-006f §R.3 / §8.6 changed on the document evidence of this pass; the rest are unchanged (their open parts are measurements, sites or code, not documents).

| # | Area | §R.3 / §8.6 | Now | Why |
| --- | --- | --- | --- | --- |
| 7 | Consistency across documents | 3.5 | **4.0** | The in-set contradictions §R.3 row 7 named are gone: one legend cited everywhere, tables and headings free of M1 / M2 / C in 15 of 17 documents, 600 / 600 matrix with tags equal to the SRS, register equal to every header, 0 dangling IDs, 0 stale decision phrases in the build documents. Held at 4.0, not higher, for F-01 (Annex B), F-02 (version cites), F-05 (03 tags) and the deck differences, which are recorded with decisions in TB-DS-20 §4 but not yet applied to the decks. |
| 8 | LLM choice | 3.5 | **4.0** | Every document item of §8.4 is closed in the set: AS-04 says time-sharing is unmeasured (L8-01); the 6 Nov configuration is recorded in NFR-PERF-08, ADR-03, G1 and CI-MOD (L8-02, except file hashes, which are stated as not recorded); ADR-03 carries the four fit options in order (L8-03); G2 and NFR-PERF-09 say "projected" and name the reader (L8-04); zh-TW has a provisional gate value in N-11, G1, NFR-PERF-08 and TB-DS-20 step 5 (L8-05); one unit (GiB) and the Gemma licence verified with a date (L8-06); the overlay's caveat is stated (L8-07); CON-12 names everywhere (L8-08); ENV-GPU "does not exist yet" (L8-10); Gemma 4 as lead PHI-tagger candidate (L8-11); OI-10 points at the fine-tune run (L8-12). Held at 4.0 because the baseline is still one proxy-card run without hashes, zh-TW has an API number only, and the fit is unmeasured: those are step-5 measurements, not edits. |

**Updated overall: 4.0 / 5** — (4.0 + 4.3 + 4.0 + 4.0 + 4.3 + 3.8 + 4.0 + 4.0) / 8 = 32.4 / 8 = 4.05, not rounded up (from 3.9). This section records the re-score; TB-REV-006f itself is not edited.

L8 items by status: L8-01, -03, -04, -05 (paper part), -06, -08, -10, -11, -12 **closed**; L8-02 **partly** (configuration recorded, sha256 hashes absent until step 5); L8-07 **partly** (caveat documented; the overlay rename is code, step 5); L8-09 **not in this folder** (dated records under `trialbox-consumer-gpu/` and `trialbox-role-redesign/`, not read for this audit).

### F.7 Remaining paper fixes, ranked by value, with effort

Total about 4 h (22 h at §R, 75 h at v1.0). Items 1 and 2 bring the last two documents to 4.5 and the set to 4.5.

| # | Fix | Docs | Est. h |
| --- | --- | --- | --- |
| 1 | **Annex B regeneration** (F-01): `gen_trace.py --annex-b` by the §10.3 area rule, or a hand extension of the 120 rows; header to v0.11; a 10-line Annex B coverage check in `doclint.py` so the header's claim is true; FR-DEID-04 → S1. | 02, tools | 1 |
| 2 | **TB-DS-03 tag finish** (F-05): 17 spots to "(was M1)" → H or S0; one legend sentence in §0. | 03 | 1 |
| 3 | **SRS one-liners** (F-03, F-04): NFR-COMP-01 wording; FR-SEC-05 split with the review step moved to TB-DS-04 §9.5; "— (was M1)" on FR-SCR-09 and NFR-USAB-02; §1.6 "v0.10 or v0.11". Then a fourth seeded draw is optional: the exit condition is met. | 01 | 0.5 |
| 4 | **Version cites that lag the SRS** (F-02, F-09): 11 §4.0, 17 Depends-on, 21 Status, 10 TM-07; or cite "version per TB-DS-00R" so the cells never lag again. | 10, 11, 17, 21 | 0.3 |
| 5 | **TB-DS-00 BD cells** (F-07) and **TB-DS-04 §6.3 cell** (F-06). | 00, 04 | 0.4 |
| 6 | **Register row** (F-08): TB-REV-006g 1.1 → 1.2. | 00R | 0.1 |
| 7 | **Hospital-stage residue** (F-10), optional. | 13, 15 | 0.2 |
| 8 | Re-read the 37 "unverified" primary sources in TB-DS-05 (desk work, not a defect). | 05 | 3 (not counted) |

### F.8 Unreachable on paper

Unchanged from §7 and §R.6; nothing in this pass moved any row, because none can be moved by editing. In plain words, what the set cannot get from its authors:

- **Numbers from a real card at full scale:** the 32 GB fit in the time-shared mode, swap time, night-window throughput, SIGIR / TREC / zh-TW baselines on the deployed files with their hashes, the PHI leak rate on real notes, interactive latency and the 500,000-patient run (storage, rebuild time, RAM). Step 1 and step 5 produce these; TB-DS-21 and ADR-03 are written to receive them.
- **Facts only a hospital has:** SS-MIX2 layout, appointment source, CGMH warehouse views, REDCap field names, mail-server acceptance, lab masters (JLAC10, amyloid and p-tau codes), the MEDIS 「疑い」 code, the HbA1c code against the site table.
- **Answers only a licensor or counsel can give:** MEDIS / JSLM / ATC / WHO licences, SNOMED status, the Gemma licence as it applies to a hospital, APPI and PDPA classifications, CGMH's CSMA status, opt-out wording.
- **People:** native review of JA / zh-TW labels; site-adjudicated TREC pairs; SAT, PQ, SUS, NASA-TLX, time-motion baseline and chart-review recall at the pilot; signatures, if the owner ever wants them.
- **Code:** test markers in TB-DS-01 IDs with executed results and a 29119-3 completion report; the overlay rename; the step-1 generator that turns TB-DS-21's "Proposed" rates and "target" times into measurements.

Every one of these is stated correctly in the documents as a target, an open item or a provisional value; the set at 4.4 is as good as a design set can be before the build produces its first measurement, and the remaining 4 h of edits take it to 4.5. 5.0 is the list above, and it is build work, not document work.

### F.9 Reproduction (this pass)

- `cd /tmp && python3 /mnt/project-files/trialbox-design/tools/doclint.py` — 02 P2, 13 P2, all else clean.
- `python3 /mnt/project-files/trialbox-design/tools/gen_trace.py --counts` — 57 / 36 / 58 / 17 / 35 / 9 / 228 / 155 / withdrawn 5 / total 600, equal to TB-DS-20 §1 and TB-DS-04 §6.3.
- Independent script (Python 3 standard library, run with `-I`): SRS §3 ID rows between the `## 3` and `## 4` headings (600, unique); TB-DS-04 §6.2 ID rows allowing the " †" marker (601 = 600 + AM-01; 0 missing, 0 extra; Pri cell equal to the SRS on every row); TB-DS-02 Annex B rows (480; 120 missing, listed in §F.5; tag equal to the SRS on 479, FR-DEID-04 differs); "shall" count per Requirement cell (0 rows ≥ 2); vagueness markers (0); modal counts; table lint and blank-line splits (0 real); control table, Version row, approvals, References heading, change-history heading and last-row version per file; `\bM1\b` / `\bM2\b` per file outside "(was …)" and change histories; `grep -n '§3\.4a'`, `grep -n "§2 'Pilot dates'"`, `grep -noE 'TB-DS-01 v0\.[0-9]+'` against the register (0.11).
- Sample: §F.4, seed `006gF`, replacement rule as §4. Wilson interval: 2 / 40 → 1.4–16.5 %.

---

## §C Confirmation after the §F fix pass (v1.3)

Short, strict confirmation by the same auditor. Read: the fourteen documents the §F fix pass touched, at the versions in TB-DS-00R v0.13 (00 0.11, 00R 0.13, 01 0.12, 02 0.10, 03 0.7, 04 0.10, 10 0.4, 11 0.7, 13 0.7, 15 0.6, 17 0.9, 19 0.5, 20 1.3, 21 1.3). Every status below was checked in the text the citation points at, not taken from the change-history row. Checks re-run from `/tmp`: `tools/doclint.py` (now with check B), `tools/gen_trace.py --counts`, `tools/gen_trace.py --annex-b --write` on a scratch copy of the set, and an independent script (standard library, `-I`) for the matrix, the tags and the table structure. No gate, approval or review step is recommended anywhere below; every item is an edit.

### C.1 Status of F-01..F-10

| ID | Status | Evidence (file:line, text as it now stands) |
| --- | --- | --- |
| F-01 | **closed** | TB-DS-02 Annex B header (line 1604): "Generated by `tools/gen_trace.py --annex-b` from TB-DS-01 v0.12 §3 (601 rows, all split IDs included) … `tools/doclint.py` check B reports any SRS ID missing here or carrying a different tag." Both claims are now true: `gen_trace.py` has the `--annex-b` mode (docstring lines 7–12) and `doclint.py` has check B (lines 119–152). Annex B holds **601 rows = every §3 row of TB-DS-01 v0.12**; doclint B clean; the independent script finds 0 missing, 0 extra, 0 tag disagreements. FR-DEID-04 line 1649 "S1" (SRS line 328, TB-DS-04 line 584 agree). "**Gaps:** none" (line 2210). Reproducibility: `gen_trace.py --annex-b --write` on a scratch copy produced an Annex B byte-identical to the published one (`diff` empty; "601 rows from SRS v0.12; added 0; dropped 0; gaps 0"). |
| F-02 | **closed** | 11:97 "(TB-DS-01, version per TB-DS-00R)"; 17:11 "TB-DS-01, TB-DS-09 and TB-DS-07 (versions per TB-DS-00R)"; 21:9 "TB-DS-01 (version per TB-DS-00R; added in v0.10)". The same form is used in 19:9 (history row 5). `grep -oE 'TB-DS-01 v0\.[0-9]+'` outside change histories: only 04:526 (history prose, see C-03) and 13:86 (superseded plan, history of its own). |
| F-03 | **closed** | 01:1060 NFR-COMP-01: "the controls of TB-DS-03 §4 (SC-nn) whose build tag is S0 or H". Names the set by the column TB-DS-03 now has (line 273 legend). |
| F-04 | **closed** | 01:726 FR-SEC-05 one statement (allowlisted content), Notes cell moves the hospital-IT review to "TB-DS-04 §9.5, not a system requirement"; 01:727 FR-SEC-05a "shall pass the PHI scan … with zero hits … (split from FR-SEC-05)"; 04:1556 §9.5 records that review with date and reviewer; 04:945–946 both rows in the matrix. 01:416 FR-SCR-09 and 01:1035 NFR-USAB-02 "— (was M1)". 01:139 "a row split in v0.10 or later". |
| F-05 | **partly** (15 of 17) | 03:24 reading rule: "Tags (TB-DS-00 §2) … Where older text named a release, it now reads 'H (was M1)' or 'L (was M2)'; 'pilot' … always means the hospital stage." Spots re-expressed: 305 control text "(H; was M1)", 340 "(L; was M2)", 368 "(H, was M1)", 398 "Pilot (H; was M1)", 451 "Yearly (H; was M1)" and the rest of the §F list. **Still bare:** 03:305 Status cell "Partial (AES-GCM built; KEK wrapping M1)" (the control text of the same row was fixed, the Status cell was not) and 03:633 "raised to M1 … New for M1 are purge on the next snapshot rebuild" (two words). The change-history row 9 says "17 bare M1/M2 spots re-expressed"; the count is 15. See C-01. |
| F-06 | **closed** | 04:1329 "eCRF pre-fill (FR-EDC-01..10, L: U, C, I, E, B, X …)". |
| F-07 | **closed** | 00:64 BD-01, 66 BD-03, 68 BD-05 "(was M1)", 72 BD-09, 81 BD-18 "hospital pilot (was M1)", 89 N-01 carry build tags or the "(was …)" form; history row 11 names the six. The remaining bare M1/M2 in TB-DS-00 are the legend sentences (30, 34, 58), §2.H under its reading rule (42–56) and footnote `[^bd13]` (113), which is marked superseded history. |
| F-08 | **closed** (and recurs) | 00R:67 TB-REV-006g row "1.2 (2026-11-07)", equal to the header this file carried when the register was edited. By the same-edit rule the cell falls behind again when this v1.3 is saved; this audit edits no other file (C-05). |
| F-09 | **closed** | 10:211 TM-07 "TB-DS-01 FR-EDC-02 carries no code and defers to this file." |
| F-10 | **partly** (optional, not scored) | 15:29 "TB-DS-00 §2.H 'Pilot dates'" fixed. 13:90 WP-17 wording follows BD-13 (no "two sign-offs" left in 13: `grep` finds none); 13:86 cites "§2.H 'M1 content by date'". **Still open:** 13:151 `TB-DS-00 §2 "Pilot dates"` (the §2.H form was applied to line 86 but not here). |

### C.2 Re-scores and regression check

| Doc | Ver. | §F | §C | Basis |
| --- | --- | --- | --- | --- |
| 02 | 0.10 | 4.0 | **4.5** | F-01 closed in full: the annex is complete (601 / 601), every tag equals the SRS, the header's provenance and check claims are true, the generator reproduces it byte for byte, and check B catches a deleted row and a changed tag (C.3). Tables and headings carry no retired tag; the only doclint hits are the two definitional "shadow mode" lines (78, 1538). Seven ADRs "Proposed" with decider "—" remain honest, as in §F. Nothing open. |
| 03 | 0.7 | 4.0 | **4.5** (at the margin) | §F held 03 at 4.0 for 17 bare tags with no reading rule. The rule is present (line 24), the Annex A mapping tables and the nine repaired SC tables stand, and 15 of the 17 spots are fixed. The two residual spots (305 Status cell, 633) are the same kind and weight as the six BD cells §F accepted at 4.5 for TB-DS-00 (F-07) and the one cell for TB-DS-04 (F-06); scoring 03 differently for three words would be inconsistent. They are listed as open (C-01, 0.1 h). |
| 00, 00R, 01, 04, 10, 11, 13 (not scored), 15 (not scored), 17, 19, 20, 21 | per 00R 0.13 | 4.5 | **4.5** (no regression) | For each touched document: control-table Version equals its TB-DS-00R row (doclint V clean on all 25 files) and equals the last change-history row (checked on all 14: 00 row 11 = 0.11, 00R row 14 = 0.13, 01 row 13 = 0.12, 02 row 11 = 0.10, 03 row 9 = 0.7, 04 row 11 = 0.10, 10 "0.4 (seq 6)", 11 row 8 = 0.7, 13 = 0.7, 15 = 0.6, 17 row 9 = 0.9, 19 row 5 = 0.5, 20 row 4 = 1.3, 21 row 4 = 1.3). Chain: TB-DS-01 §3 = **601 rows** (FR-SEC-05a added, 5 withdrawn); TB-DS-04 §6.2 = **602 = 601 + AM-01**, 0 missing, 0 extra, Pri equal to the SRS on every row; §6.3 counts 57 / 36 / 58 / 17 / 35 / 9 / 229 / 155 (line 1328) = TB-DS-20 §1 (lines 27–36, total 601) = `gen_trace.py --counts`. Structure: 0 malformed tables (the one line an all-pipe split reports, 20:102, has four escaped `\|` in a history cell and renders correctly; doclint agrees), 0 dangling FR / NFR / DR / IR / BD / N / SC IDs, 0 TBD / TODO, doclint P only on 02:78 and 02:1538 (definitional; 13 is now clean). |
| 05, 07, 08, 09, 12, TB-REC-01 | unchanged | 4.5 | **4.5** | Not touched by the pass; versions equal the register; not re-read beyond the automated checks. |

**Set overall: 4.5 / 5** (18 × 4.5 = 81.0 / 18 = 4.50, not rounded up; §F 4.4, §R 4.1, v1.0 3.4). **Documents at or above 4.5: 18 of 18.** This is the ceiling stated in §7 and §F.8: 5.0 needs measurements, site facts, licences, people and code, none of which an edit can supply.

### C.3 Check B tested

On a scratch copy of the whole folder (doclint takes `DESIGN_DIR` as its first argument): (a) deleting the FR-DEID-04 row of Annex B gave `02-architecture.md Annex B: B 1 — FR-DEID-04 missing from Annex B`; (b) with the row restored and its tag changed S1 → H it gave `B 1 — FR-DEID-04 tag H in Annex B vs S1 in TB-DS-01`; (c) on the published file, `clean (601 rows)`. The check reads the tag from the SRS Pri cell and treats a W row as "W", so a withdrawn requirement cannot be hidden behind a stale tag either. The check reports and does not block, as the whole tool does (docstring line 2).

### C.4 Residue found in this pass (none changes a score)

| ID | Sev. | Doc | Where | Residue | Fix |
| --- | --- | --- | --- | --- | --- |
| C-01 | Minor | 03 | 305 Status cell, 633 | F-05 residue: "KEK wrapping M1"; "raised to M1 … New for M1". History row 9 says 17, the count is 15. | "(H; was M1)" twice, "H (was M1)" once; history row "15 of the 17, two in v0.8". 0.1 h. |
| C-02 | Minor | 13 (not scored) | 151 | F-10 residue: `TB-DS-00 §2 "Pilot dates"` → §2.H. | One cell. Optional. |
| C-03 | Minor | 04 | §6.1 line 526 | The matrix history sentence ends at "then regenerated from TB-DS-01 v0.10"; the v0.11 and v0.12 regenerations are recorded only in change-history rows 10–11, while §6.3 (line 1328) says v0.12. The column legend (line 522) correctly defers to "the version named in §6.2". | Append "…, v0.11 and v0.12 (FR-SEC-05a)". 0.1 h. |
| C-04 | Minor | 04, 12, 00R | 04:145, 245, 324, 368, 375–376 ("not built (M2)", "not built (M1)" in the §3.4.1 gate table's Current value column); 12:55 "REDCap External Module (M2)"; 00R:84, 92 (planned-documents table) | Bare M1 / M2 in Status, Notes and Content cells outside the Pri / Release columns doclint G watches. All predate §F and were not in its F-list; §F scored these documents 4.5 with them present, so they are this auditor's omission, not a regression, and are treated as F-07 was. TB-DS-04 §1.5 (line 64) gives the legend but, unlike TB-DS-02 "How to read" (lines 22–23), has no sentence telling the reader how to read a bare "M1" in prose. | "(was …)" form on the nine cells, or one reading-rule sentence in 04 §1.5 and 12 §1. 0.5 h. |
| C-05 | Minor | 00R | TB-REV-006g row | 1.2 → 1.3 once this file is saved (same-edit rule; recurs with every audit version because the audit edits no other file). | One cell, owner's next edit. |

Total residue about 0.8 h, none of it affecting a chain, an identity or a control record.

### C.5 TB-REV-006f overall, areas 7 and 8

| # | Area | §F | Now | Why |
| --- | --- | --- | --- | --- |
| 7 | Consistency across documents | 4.0 | **4.3** | §F held area 7 at 4.0 for F-01, F-02, F-05 and the deck differences. F-01 and F-02 are closed and F-05 is closed but for three words; the Annex B chain is now generated and checked, so SRS → architecture is at ID level like SRS → test. Not 4.5: the deck differences recorded in TB-DS-20 §4 are still not applied to the decks (outside this folder, not verified here), and C-01 / C-04 leave bare retired tags in cells of three documents. |
| 8 | LLM choice | 4.0 | **4.0** (unchanged) | No document item of §8.4 moved: the pass changed TB-DS-02 only in Annex B (history row 11), and ADR-03, NFR-PERF-08, G1, CI-MOD and TB-DS-20 step 5 are as §F read them. The open parts (file hashes, zh-TW baseline, the 32 GB fit) are step-5 measurements, not edits. |

**Updated overall: 4.0 / 5** — (4.0 + 4.3 + 4.0 + 4.0 + 4.3 + 3.8 + 4.3 + 4.0) / 8 = 32.7 / 8 = 4.09, not rounded up (§F 4.05). TB-REV-006f itself is not edited.

### C.6 Reproduction (this pass)

- `cd /tmp && python3 /mnt/project-files/trialbox-design/tools/doclint.py` — `02-architecture.md: P 2` (lines 78, 1538), `02-architecture.md Annex B: clean (601 rows)`, every other file clean, `TOTAL: P 2`.
- `python3 /mnt/project-files/trialbox-design/tools/gen_trace.py --counts` — S0 57, S1 36, S2 58, S3 17, S4 35, S5 9, H 229, L 155, withdrawn 5, total 601.
- `cp` the folder to a scratch directory; `python3 tools/gen_trace.py <scratch> --annex-b --write`; `diff` of the Annex B block against the published TB-DS-02: empty. Then `sed` one row out / one tag changed; `python3 tools/doclint.py <scratch> --only 02`: B 1 each time (C.3).
- Independent script (`python3 -I`): SRS §3 rows with Pri (601); TB-DS-04 §6.2 rows between `### 6.2` and `### 6.3` with the " †" marker stripped (602; set difference both ways empty; Pri equal on all); `\bM1\b` / `\bM2\b` per file outside code blocks, change histories and a 25-character "(was …)" / legend context (the C-04 and C-01 lines, the legend and §2.H lines of 00, the nested "(was M1 (…))" cells of 09 and 01, which are compliant); all-pipe table lint (one hit, 20:102, escaped pipes).
- `grep -noE 'TB-DS-01 v0\.[0-9]+' *.md`, `grep -n 'version per TB-DS-00R'`, `grep -n 'two sign-off\|S20 part\|Pilot dates' 13-*.md 15-*.md`, control-table Version vs last change-history row on the fourteen touched files.
- No fresh 29148 sample: the SRS edit touched five rows (NFR-COMP-01, FR-SEC-05, FR-SEC-05a, FR-SCR-09, NFR-USAB-02) and §1.6; each was read; the §F exit condition (≤ 3 / 40) stands.

---

## Change history

| Version | Date | Author | Change |
| --- | --- | --- | --- |
| 1.0 | 2026-11-07 | Claude (Fable), independent documentation audit | First issue: per-document scores (17 scored, set 3.4), findings Q-01..Q-40 and S-01..S-11, 40-row 29148 sample (20 % defect), reproduction scripts, path to 4.5 per document, unreachable-on-paper list, top-15 fixes. No other file edited. |
| 1.1 | 2026-11-07 | Claude (Fable), independent documentation audit | §R Re-audit after the TB-REV-006g fix pass: every Q-/S- finding re-checked with citations (closed / partly / open), 34 new defects R-01..R-34, fresh 40-row sample (seed 006gR, 8 / 40), re-scores (set 4.1; six documents at 4.5: 00R, 08, 09, 11, 12, 21), remaining paper fixes (about 22 h) and the unreachable-on-paper list; correction: 18 documents are scored, not 17. Annex B of TB-DS-02 checked: coverage complete against v0.10, header provenance stale (R-10). No other file edited. |
| 1.2 | 2026-11-07 | Claude (Fable), independent documentation audit | §F Final audit after pass 2: every R-finding re-checked with citations (30 closed, 4 partly, 0 open) and the 12 L8 document items (9 closed, 2 partly, 1 outside the folder); 10 new defects F-01..F-10; fresh 40-row sample (seed 006gF, 2 / 40, Wilson 1.4–16.5 %); re-scores (set 4.4; 16 of 18 at 4.5; 02 and 03 at 4.0); TB-DS-02 Annex B judged against the 120 v0.11 rows (480 / 600, acceptable as information, not as a record, §F.5); TB-REV-006f areas 7 and 8 re-scored to 4.0, overall 4.0 (§F.6); remaining paper fixes about 4 h; unreachable-on-paper list in plain words. No other file edited. |
| 1.3 | 2026-11-07 | Claude (Fable), independent documentation audit | §C Confirmation after the §F fix pass: F-01..F-10 re-checked with citations (8 closed, F-05 15 of 17 spots, F-10 optional and partly); doclint check B tested by mutation (deleted row and changed tag both reported) and Annex B reproduced byte for byte by `gen_trace.py --annex-b`; re-scores 02 and 03 to 4.5, no regression in the twelve other touched documents (set 4.5 = 81.0 / 18, 18 of 18 at 4.5); residue C-01..C-05 about 0.8 h; TB-REV-006f area 7 to 4.3, area 8 unchanged, overall 4.09 → 4.0 (§C.5). No other file edited. |
