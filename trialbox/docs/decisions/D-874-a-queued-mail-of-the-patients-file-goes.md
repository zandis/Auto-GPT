# D-874 A queued mail carrying an opted-out patient's own file is dropped (ERASE-D, part 2)

- **Task:** ERASE-D, lane C2's backlog. D-863 dropped a mail the gateway held for an opt-out when it carried the patient's own file. A mail still queued (the SMTP server down, not yet asked again) kept its request in `mail.send_keys`, and its attachment names carry the pseudonym's prefix. · **Date:** 2026-11-16
- **Decision:** the opt-out worker's `held_mail` clear drops a queued mail carrying an opted-out patient's own file, as it drops a held one: its request and recipients go, and its state becomes `dropped`. The gateway would hold it anyway, since it asks before each send (D-863). A mail the gateway has taken to send since is left: the update asks the state again. A queued or held mail of lists stays, since it names no one in the outbox.
- **Left:** an uncertain mail stays owed. It may have left, and a person checks the mailbox and resolves it; its request stays until then.
- **Held by:** `tests/unit/test_a_queued_mail_of_the_patients_file_goes.py`, synthetic data only (failing output on the previous code kept: `erased2-fail.txt`).
