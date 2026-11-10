# D-332 The clinician PoC is product evaluation, not research

- **Task:** T-508 (wave P of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2.3)
- **PR:** this branch (`agent/T-508-poc-pack`)
- **Date:** 2026-11-10
- **Status:** accepted (the owner's answer to Q-07 of 2026-11-10, recorded in `docs/plan/27-poc-plan.md`)
- **Number:** D-307 was reserved for this text in `docs/decisions/REGISTRY.md` and never written; the card takes
  D-332, and the D-307 row is voided
- **Closes:** REG-013 (with the PoC pack in `docs/poc/`); go/no-go item 12 of `docs/plan/27-poc-plan.md` §8.1

## Context

Two site clinicians test TrialBox on a hosted demo with synthetic patients (`docs/plan/27-poc-plan.md`). The deep
review asked whether that test is research on the clinicians, which would bring a research protocol, a consent form
for them as subjects and a committee review (REG-013). The owner answered on 2026-11-10 (Q-07): the PoC is product
evaluation, not research, and the clinicians sign the acknowledgement only. D-311 then struck every committee and
ethics step for work on synthetic data.

## Decision

1. **What the PoC is.** Formative evaluation of a product under design: the clinicians use the console in their own
   language on synthetic patients and say what is wrong, confusing or missing. Their feedback is design input for the
   design freeze. The pack that runs it is `docs/poc/`.
2. **What it is not.** It is not research on the clinicians: no hypothesis about them is tested and nothing about
   them is the object of study. It is not a clinical investigation: no patient takes part, no real record is read,
   and no output is used for any patient or trial. It is not validation: no IQ, OQ or PQ evidence comes from it. It
   is not a test of model accuracy.
3. **What follows.** No research protocol (the PoC protocol, `docs/poc/protocol.md`, is the procedure for the
   sessions), no subject consent form, no committee or ethics review, no conflict-of-
   interest file. Each clinician accepts the acknowledgement on screen (D-328), once per account; nothing else is
   signed.
4. **The clinicians' own data** (account, logs, feedback) is handled as the data-handling statement says
   (`docs/poc/data-handling.en.md` and its Japanese and Traditional Chinese versions) and the notice on the testers'
   own data (`docs/poc/testers-data.md`): kept to run the test and improve the product, filed under a code, deleted
   90 days after the PoC ends except the feedback without names.
5. **If findings are ever published**, the clinicians are asked first, and a named quote needs their consent.

## Consequences

- The PoC needs no gate record and no signer (D-311 S1, S2, S4). Go/no-go item 12 is met by this file.
- If the PoC changes so that it studies the clinicians (for example a published usability study with measured
  outcomes), or reads any real patient record, this decision no longer covers it and the owner decides again.
- Step 2 of the PoC (real models on the owner's machine, same synthetic patients) stays inside this decision.
