# D-385 Workflow fixes on the PoC path: one consent state, a referral pauses Approach, no implied consent

- **Task:** T-516 (wave P of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2)
- **PR:** this branch (`agent/T-516-poc-workflow`), on top of T-512 and T-514
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** UX-011, UX-013, UX-014, UX-015, LIFE-019 (PoC part)

## Context

The 2026-11-10 deep review walked the PoC path and found five workflow faults. The screening log said "contacted"
while the participant page said "consented" after a consent form was saved (UX-011). A referral asked after Approach
left the Approach in force, so the coordinator already had the call task and the treating doctor was bypassed by
the order of clicks (UX-013). The demo had no IRB approval date and no consent-form version, so every Approach was an
override (UX-014). A sub-investigator without the "approach" tick saw no Approach button and no reason (UX-015). An
enrolment form or a visit without a consent form walked the participant to "consented", "implied by" the later form
(LIFE-019).

## Decision

1. **One consent state for the log and the participant.** The participant's state stays the source. A refresh of
   the participants brings the screening log up to that state whenever the log is behind it on the main line, not
   only when a step was just taken. The log is never pulled back from an end state or from a state ahead of the
   participant. Saving a lifecycle form on the console refreshes the participants at once, with the screening
   numbers the console issued, so a consent form saved before the participant page was ever opened reaches the log.
2. **A referral asked after Approach pauses the Approach.** It is not a new mark: Approach stays the mark, and while
   the patient's latest referral is not agreed (asked, discuss or declined) the Approach is paused. The referral
   form first shows a confirm sheet that says so. While paused, the coordinator has no call task, contact outcomes
   are refused (page and `/api/v1`, 409 `outcome.wait_referral`), and the patient page, the candidate page and the
   screening log say "paused". The doctor's agreement resumes it. The referral's audit record carries
   `paused: approach`. The other order is unchanged: a referral first refuses Approach until the doctor agrees.
3. **The reason where the button is absent.** An account that may mark but not Approach sees one line where the
   button would be: Approach is not delegated to it, and the logged PI (by name) marks it or ticks it for the
   account. No new permission check: the line reads the same standing (`permit` through the delegation log).
4. **Two seeded values.** The one-command demo seeds the trial GZQO's IRB approval date (60 days before the demo
   day) and the consent-form version ("1.0"), synthetic, after its own checks and only when the study has neither.
   A record a tester saved is never overwritten. The cohort study keeps none, so the warning can still be shown.
5. **No implied consent from a TrialBox form.** Derivation never takes "consented" from an enrolment or a visit form.
   It holds the participant before consent (`held`, `consent_missing`) and the participant page raises "consent
   record missing" with a link to the consent form. The step from the screening log (a sponsor study, whose CRF
   holds consent) still follows and is labelled "implied by screening_log". The date-order checks, the re-consent
   worklist and the CRC digest alert stay with T-302a.

## Consequences

- The PoC testers see the same consent state on both pages and do not reach the patient before the doctor agrees.
- An Approach in the demo trial is not an override unless the tester changes the IRB record.
- A study that records enrolment before consent now shows held participants until the consent form is entered.
