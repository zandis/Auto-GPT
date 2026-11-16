# D-863 The mail outbox asks before it sends a job's files (NEW-MAIL-1; the integrator's ruling of 2026-11-16)

- **Task:** NEW-MAIL-1. The adversarial review of T-206b part 2b found that a mail held at publish (the SMTP server down) and sent later by the drain, or by `trialbox mail resolve KEY --resend`, read the job's patient-level files with no check of the opt-out register. The integrator ruled the design: one choke point, fail closed, and the erasure path for a held mail. · **Date:** 2026-11-16
- **The choke point:** every attempt to send goes through `Gateway._attempt`: publish, a queued try, and a person's resend. A mail is patient-level as the mail builder judges it: its own tag, or any file's tag. Before such a mail is built, `_still_current` asks the orchestrator `GET /jobs/{job_id}/outputs-current?file=...`, keyed on the job id the outbox row carries and naming the files the mail carries. The answer is a yes or no, never a patient or a count; the route is in `reads_without_patient`, and the mail gateway is its only caller. One judgment (`tb_common.patient_files.naming`) matches the console's D-860 rule: a per-patient file by its patient; a text file by its content, in any case; a compressed file by the job's text list of the same name, else by all of the job's text lists. With no text list to judge it by, a compressed file counts as naming one.
- **Fail closed:**
  - A no is held as `failed` with the typed reason `patient_files.HELD`.
  - A file outside `outputs/{job_id}/`, no job id, or a job the orchestrator no longer has is held as `failed` with the reason `NO_JOB`.
  - No answer is held as `queued` with the reason `NO_ANSWER`. It is counted and retried with back-off, and goes to `failed` for a person at `MAX_ATTEMPTS`.
  - Only a yes sends.
- **The erasure path, and the review:**
  - The first build deleted a held mail's attached files from the store. The adversarial review found that those are the job's working outputs, read by other patients' pages (the job card, the home page, the screening log), and that the workbook was judged by the excluded list too. Deleting them conflicts with D-513, so the delete was withdrawn.
  - The opt-out worker's new clear, `held_mail`, drops the held mail: its kept request (files by key, and a per-patient file's name carrying the pseudonym's prefix) and its recipients go, and nothing can send it again.
  - `mail.send_keys` gains that clear, and a queued or uncertain row stays owed. `objects:outputs` stays owed, kept until retention (D-513) and withheld on read by the console and now the mail. The owed list stays at 49.
  - The review's oracle note: the gateway can ask the route about any job id. It learns only yes or no; the route is not audited.
- **Held by:** `tests/unit/test_the_outbox_asks_before_it_sends.py`, synthetic data only. It covers:
  - SMTP down at publish, then an opt-out, then the drain;
  - the same with `--resend`;
  - an orchestrator that does not answer (counted to a person), and a gateway with no way to ask;
  - a job it no longer has, and a file of another job;
  - patient files under a counts label, and a mail of counts;
  - the orchestrator's judgment per file;
  - the worker's drop, with the job's file kept.

  The callers pin and the clear-name list move. Two mail tests' synthetic keys move under their job.
