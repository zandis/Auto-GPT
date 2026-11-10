# D-331 In-product feedback: a flag, a rating and a comment on every page

- **Task:** T-510 (wave P of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2.3)
- **PR:** this branch (`agent/T-510-feedback`)
- **Date:** 2026-11-10
- **Status:** accepted
- **Closes:** UX-006 (Blocker); `docs/plan/27-poc-plan.md` §6.1 (the feedback button) and §6.4 step 1 (the export)

## Context

The two PoC clinicians had no way to leave feedback in the product (UX-006). Anything written elsewhere loses the
page, the language and the role. The PoC rule is synthetic data only, so a free-text box must not invite a patient
example, and what it stores must be reachable by the scan of stored input of D-328.

## Decision

1. **One control on every page.** `templates/_feedback.html`, included once by `base.html` after the two banner
   includes of D-328, shows on every page a signed-in account sees, in the page's language (en, ja, zh-TW): a flag
   (wrong result, confusing, wording, missing, slow, other), a rating from 1 to 5 and a comment of at most 1000
   characters. Each is optional; at least one is needed. A public page drawn without the account (`/about`, the
   sign-in) has no control: there is no session to send it with.
2. **No patient field.** The form has the fields `flag`, `rating`, `comment` and the hidden `path` and `csrf`.
   Nothing asks for a patient, a pseudonym or an example. A bold line beside the comment box says no patient
   details go there, and the box is described by it for screen readers.
3. **What is stored.** One row per post in schema `feedback` of the trial database (table `entry`): the page's
   path (no query), the language, the account's role, the account and the time (UTC). The audit event
   `feedback.add` names the entry and the page, never the comment. The tester goes back to the same page with a
   thank-you; nothing else changes. Any signed-in account may send feedback, a CRO account too (its role scope of
   D-104 opens the reports pages only, and those pages carry the control as well). The sign-in, the role scopes
   and the reveal handlers are not changed.
4. **The scan of D-328 covers the comment.** `python -m console.demo_guard scan --db` reads every text column of
   the trial database, so `feedback.entry.comment` is read. It is also named in `demo_guard.MUST_SCAN`: the scan
   exits 1 and says "not scanned" when a named column is missing, so a renamed field cannot drop out unnoticed.
5. **The export to issues.** `/feedback/export.csv` (an admin account; audit event `feedback.export`) and
   `python -m console.feedback export --out FILE` write one CSV row per entry, ready to become one issue: `title`,
   `body`, `labels` (`poc`, `feedback`, `lang:<lang>`, `flag:<flag>`) and the raw fields. A tester is a code (T1,
   T2, in the order of their first entry), never the account name, because the repository is treated as public.
   Each comment passes `tools/data_scan` first: a comment with a hit is left out of the file and its row names the
   pattern in `scan`.

## Consequences

- A new store `feedback`, pinned in `tests/unit/test_migrations.py` as a version added after the D-204 baseline.
- The control sits in the page footer as a `<details>` block with the console's existing styles. A fixed-position
  button (27-poc-plan §6.1) needs a stylesheet change and is left to the card that next touches `console.css`.
- 27-poc-plan §6.1 also lists "how much it matters", the study, the screen size and the release, a per-criterion
  "this answer is wrong" flag and an ease question per task. They are not in this card's row and are not built here.
- The ja and zh-TW strings are drafts. Their native read is dropped as a gate (D-311).
