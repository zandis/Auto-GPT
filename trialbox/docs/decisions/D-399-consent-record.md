# D-399 Consent record: approved ICF versions with history, the version check, date order, re-consent list

- **Task:** T-302a (first part of T-302; `docs/plan/28-master-plan-v6.md` §6.2.4)
- **PR:** this branch (`agent/T-302a-consent-record`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Builds on:** D-134 (the lifecycle), D-147 (IRB record and the Approach warning), D-311 (no development gates),
  D-385 (T-516: no consent implied by a TrialBox form)
- **Closes:** FIT-009, LIFE-018, LIFE-019, UX-012 (the consent half; see "Not in this decision")

## Context

The consent form had six fields and a free-text version that nothing checked. The IRB record kept one consent-form
(ICF) version per study and overwrote it on save, so there was no list of approved versions and no history. There
was one re-consent slot and no list of who must consent again after a new version (FIT-009, LIFE-018). T-516
stopped TrialBox forms implying consent, but nothing compared the dates: an enrolment or a visit before the consent
date went unseen (LIFE-019). Consent could be recorded three ways: the registry's status select, the consent form
and a lifecycle step (UX-012).

## Decision

1. **Approved ICF versions are a list with history.** Table `icf_versions` in schema `team` (team store version 2).
   Each row: version, the date printed on the form, the IRB approval date, the first day it is used (empty: the IRB
   approval date; never before it), whether subjects on study must consent again on it, a note, who and when. A
   change is a new row for the same version; a withdrawal (entered by mistake) is a new row with a note. The list is
   the newest row of each version not withdrawn. The IRB record's consent-form version is read from the newest
   version on the list; a version typed on the IRB record joins the list. Edited on `/studies/{rs}/irb` (and
   `/api/v1/studies/{rs}/icf`) by who may edit the IRB record; audited as `console.icf`.
2. **The consent form's version is checked on save, as a warning.** `datacore.lifecycle.icf_check` compares the
   version with the list on the consent date: not on the list, no IRB approval date, not yet approved or in use on
   that day, or replaced by a newer version in use that day. The form is saved as entered (PI-15: warn, never
   block), the page says why, and each warned version is logged as `console.consent_version_override`. A study with
   no list yet gets no per-save warning: the IRB page and Approach already warn that the consent form is missing.
   Versions are compared without spaces and case.
3. **The consent record is richer.** The consent form gains (additive, all optional): the re-consent slot's version,
   the form's language, the day the form was given to think it over, explained by and assisted by, consent by a legal
   representative and the relation, an impartial witness and who, and whether the participant signed on or before
   the day of the person taking consent.
4. **Re-consent is repeating.** A re-consent is the consent form again on its own numbered event `rc1`, `rc2` ... (a
   visit cannot be named so). The old single slot still counts.
5. **Date order is flagged, never forced.** An enrolment or a visit done dated before the first consent, and a
   subject past consent with no consent form in a study that records consent in TrialBox, are alerts on the
   participant page with a link to a deviation entry. No date is changed. An enrolment without a consent form keeps
   holding the subject before "consented" (D-385).
6. **The re-consent list.** The newest version in use that asks for re-consent is the target; every subject on study
   (consented, enrolled, on study) whose last recorded consent is on an older version, or one not on the list, is
   listed on `/studies/{rs}/reconsent` and `/api/v1/studies/{rs}/reconsent`, with the action that opens the consent
   form on the next `rcN` event. Record level: who reads the participants reads it. A subject with no consent form is
   not on it (the participant page raises that); a sponsor study whose CRF holds consent has no consent forms here.
7. **One way to record consent.** In a study with the built-in consent form, the participant page's step bar offers
   "Record consent", which opens the consent form, instead of a bare "Consented" step. The registry's status select
   no longer offers "consented", and the registry refuses it with the way to do it. The manual step and the REDCap
   read-back stay for sponsor studies.

## Not in this decision

- The call task's own "record consent" action and the two pages named "Screening log" (rest of UX-012).
- The IRB-text record of T-310b (D-395) is about the cross-department candidate view, not the ICF version; the
  approved ICF version lives on this list. If a later card moves IRB records together, this list is one of them.
- Consent shown in the CRC digest mail.
