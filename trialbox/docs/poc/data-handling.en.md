# TrialBox proof of concept: how data is handled

PoC data-handling statement v1, 2026-11-10. One page, given to each tester before the first sign-in, in the tester's
language ([Japanese](data-handling.ja.md), [Traditional Chinese](data-handling.zh-TW.md)). The acknowledgement at the
end is the one the console shows at the first sign-in (D-328); it is stored with the account, the time and this
version. Nothing else is signed (D-332).

## The statement

1. **What this is.** A demonstration copy of TrialBox, a research-support tool that screens records against study
   eligibility criteria. It runs on a hosted server in Taiwan (Google Cloud, region `asia-east1`), outside any
   hospital. It is pre-release software. It is not validated and is **not a medical device**.
2. **The data in it is not real.** Every patient, chart, name, number and date in the demonstration is synthetic (made
   by a generator) or comes from public research data sets. No hospital's data is in it. Any likeness to a real person
   is chance.
3. **Do not enter patient information.** Do not type, paste, upload or photograph anything from a real patient's
   record, in any field, file, comment or feedback form. This includes names, chart numbers, dates of birth, note
   text, images and rare details that could identify a person. The demonstration refuses chart paste and uploads; the
   rule also covers free-text boxes and your feedback.
4. **Not for clinical use, not for trial conduct.** Do not use any output to decide on a patient's care, eligibility,
   approach or consent. Nothing here is a trial record, a screening log, a source document or an essential record
   under GCP. Results may be wrong; the demonstration uses a test model.
5. **Your own data.** We keep your name, role, institution, mail address, account name, sign-in and action logs
   (time, page, action), and the feedback you give (written, spoken in calls, and screen recordings only if you agree
   each time). Purpose: to run the test, to keep the service secure, and to improve the product. Controller: Aimedics
   (legal name and address are given with your accounts). Contact: the project owner. We do not sell or share it.
   Feedback is filed under a code, not your name; a named quote is used only with your consent. The details are in
   the notice on your own data ([testers-data.md](testers-data.md)).
6. **Where and how long.** The data is held in Taiwan on Google Cloud. For a tester in Japan this is a transfer
   outside Japan: the country is Taiwan, and its data-protection law is the Personal Data Protection Act. Accounts
   and logs are deleted 90 days after the test ends; feedback is kept without names.
7. **Your rights.** You may ask to see, correct or delete your data, or stop taking part, at any time, without giving
   a reason.
8. **If something goes wrong.** If patient information is entered by mistake, tell the project owner the same day. We
   delete it, purge the snapshots and logs that hold it, record the event without the content, and tell you what was
   done. You follow your hospital's own reporting rule.
9. **What your feedback is.** Design input for the product. It is not qualification evidence and not research on you
   (D-332). If we later wish to publish findings from the test, we ask you first.
10. **Confidentiality.** The software and its screens are confidential until release.

This is a draft by the plan's authors, not legal advice.

## The acknowledgement

As the console shows it (`services/console/i18n_demo.py`, key `demo.ack.*`):

> I have read the TrialBox proof-of-concept data-handling statement (PoC data-handling statement v1, 2026-11-10).
>
> - [ ] I understand that all patient data in the demonstration is synthetic or public.
> - [ ] I will not enter, paste, upload or describe any real patient's information.
> - [ ] I will not use any output for patient care, eligibility decisions, consent or trial records.
> - [ ] I understand the software is pre-release, not validated and not a medical device, and that its outputs may
>   be wrong.
> - [ ] I agree that my account data, activity logs and feedback are used to run the test and improve the product, as
>   the statement says.
> - [ ] (optional) I agree to screen recording in feedback sessions.
> - [ ] (optional) I agree that my feedback may be quoted with my name.
>
> **I accept.** Accepted as (account) (role). The time and the statement's version are kept with your account.

The five statements are required; the two optional ones may stay empty. Accepting writes the audit event `demo.ack`
once per account.

## Contact

The project owner, by the mail address given with your accounts.
