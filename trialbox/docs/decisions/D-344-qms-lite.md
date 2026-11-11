# D-344 QMS-lite records, change classes and the standards position under D-311

- **Task:** T-215 (wave 2 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2.5)
- **PR:** this branch (`agent/T-215-qms-lite`)
- **Date:** 2026-11-10
- **Status:** accepted
- **Closes:** REG-027, REG-029, OPS-026, CR-096 (QMS-lite part), PLAN-027 (FS part); REG-030 in part (the evidence rules)

## Context

TB-ASSESS-01 card T-215 asked for QMS-lite records, change classes on every pull request, a functional specification
per workstream, a risk file and a VMP ready for nine signatures before IQ. The deep review of 2026-11-10 added the VMP
sections of REG-027, the standards position of REG-029 and a staged roll-out procedure (OPS-026). D-311 then removed
every development gate, signer and named reviewer, struck the single risk file (B18) and the formal validation at
CGMH (B28). Card T-654 added the safety classification, the SOUP list, the development plan and the problem log.

## Decision

1. **`docs/validation/` is the home of the quality records**, laid out in its `README.md`. Records are written by the
   pull request or tool that does the work. None is signed.
2. **The VMP is v1.1 without signatures.** It names the regulated user (the site), assesses GxP impact per function,
   gives the model sub-system its own life cycle (category 5 in effect, through `trialbox eval qualify`), a deviation
   and CAPA procedure on the problem log, and a retirement and migration section. GAMP 5 is the Second Edition (2022)
   with risk-based assurance. Formal IQ, OQ and PQ return only under TB-PLAN-06 §0.3 item 2.
3. **Change classes CC1 to CC6** (TB-DS-04 §9.3) are kept and written on every pull request. Significance A, B, C
   (TB-DS-12 §5.1) only chooses which tests run. No board, no peer review, no approver.
4. **Staged roll-out:** acceptance box, then the first site, then the second, three working days apart for MINOR and
   MAJOR releases; the site's administrator applies the signed bundle; evidence is tool output, not a sign-off.
5. **Standards:** IEC 62304 followed as good practice in a light form, with the records mapped to their paths;
   IEC 82304-1 adopted as guidance; ISO 13485 not adopted, with a written trigger.

## Consequences

- The PR template field for the change class waits for card T-654's template to merge (it replaces the template);
  until then the pull request body states it.
- `tests/unit/test_validation_records.py` holds the folder to its layout and the FS index to the matrix.
- Reviewer hours per pull request are no longer recorded (there is no human review to count).
