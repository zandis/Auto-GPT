# D-759 The email shape is looked for around each "@" only

- **Task:** NEW-B-51 (lane B2's own finding while measuring D-756), lane B2 · **PR:** `agent/NEW-B-51-email-shape-linear` · **Date:** 2026-11-16 · **Status:** accepted

1. `phi_guard.EMAIL` tried every position of a long run of letters or digits (0.65 s for 30,000 digits, in the masker and the guard alike); the masker and the guard now look for it only in a window around each "@": the longest local part (64 characters) before it and the longest domain (255) after (`find_emails`).
2. The addresses found are the same (a test compares them with the whole-text search on generated text); a longer local part than an address may have is masked from its last 64 characters.
3. The masking version is unchanged: what is masked is the same.
4. A note of 30,000 characters in one run is read in milliseconds.
5. Tests: `tests/unit/test_email_shape_linear.py` (the same spans as before on 3,000 generated strings; long runs; the guard reading the masker's search).
