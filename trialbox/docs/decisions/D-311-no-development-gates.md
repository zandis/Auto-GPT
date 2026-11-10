**D-311 No development gates: IRB, ethics, conflict-of-interest and review steps apply only when real patient data
is read.** Owner rule of 2026-11-10 (Changfu Kuo), on the gates review `gates-review-2026-11-10.md` (Group B, DROP,
and the SIMPLIFY items) and the owner's answers to its eight questions. Branch `agent/no-dev-gates`. Date: 2026-11-10.

*The rule.* Building, testing, deploying and sharing TrialBox (including with Dr Makoto) use synthetic or public data
only. They need no IRB or ethics step, no conflict-of-interest step, no hospital sign-off, no gate record with a
signer and no named human reviewer. A gate exists only where real patient data is read.

*CGMH.* The owner's approved IRB covers the whole CGRD (CGMH research database). It covers TrialBox reading that data
on a machine inside CGMH for its users. No new CGMH IRB step, amendment, supplement, cover note, steward or second
reviewer question, or conflict-of-interest item is part of the plan. The amendment filed on 2026-11-10 is withdrawn
by the owner himself; the plan does not track it.

*Japan.* Real Japanese patient data waits for Dr Makoto's own committee, which he handles himself. There is no Japan
date and no Japan step on this plan. Dr Makoto holds the Japan amendment filed on 2026-11-10.

*What stays (the code checks and the owner's own rules).* CI jobs `lint`, `types`, `contracts`, `unit`, `e2e-simple`,
`goldens`, `data-scan`, `shell`, `images`, `demo-boot`; the safety property, mutation and engine-agreement tests
(T-650, T-652), which replace the human safety-core reviewer; the data scan and the rule "synthetic and public data
only"; the demo's refusal of uploads and pasted chart text, its banner and the scan of stored feedback (T-502); the
second factor on every sign-in route (T-505a); the G1 50k run and the G1b B200 qualification as test runs that block
nothing else; the owner's approval of each cost; the access design before a session reaches the owner's B200 (T-630).
One decision number has one text (`tools/decisions_index.py --check`).

*Merging.* A safety-core change merges on green CI plus one automated adversarial review. Branch protection: required
CI checks, no required human approval (the owner sets it; agent sessions do not change repository settings).
`.github/CODEOWNERS` stays as information only.

*Lighter forms (SIMPLIFY).* GP-0 is the tag `poc-1` with CI green and the demo booted from it, no record or signer
(S1). GP-1 is an automated walk of the scripts plus 30 minutes by the owner (S2). The PoC keeps the on-screen
acknowledgement and the one-page notice; no signed paper copy (S3). GP exit is one triaged findings list (S4). A
release is blocked only by an open wrong-answer, data-loss or security bug (S5). `decisions_index --check` fails only
on a number used twice; registry rows are notes (S6). `gen_traceability --check` and doclint's link and path checks
are warnings (S7). A goldens rewrite takes any reason text (S8). "One card, one PR" and the card's file list are
guidance to avoid conflicts, not a stop (S9).

*Before real patient data (not a development gate).* Only these, and only from the first read of real data:

1. Security measures and a breach-notice plan on the live box (Japan APPI Art. 23 and 26; Taiwan PDPA Art. 27 and
   12).
2. Sponsor acknowledgement, signature rules and validation records, only if EDC prefill writes into a sponsor's
   regulated trial record (GCP).
3. Medical-device registration, only if the product is ever claimed to diagnose or decide eligibility.
4. Japan: Dr Makoto's committee approval and the lawful basis for using records (review items A1 to A5) are his own
   matter, outside this plan.

*Removed.* The gate records and the doclint gate check; the commitments register and its CI check; the owner-chain
tracker and its test; the G0 and G2b paperwork gates; the conflict-of-interest, steward and second-reviewer items;
the Q-14 cover note; the CGMH IRB amendment and supplement; the signed native-read notes; counsel's read of the PoC
statement; signed lifecycle records; the traceability status ritual; the planned IT-pack and regulatory-watch lint
checks; the calendar, card-path lint, backlog and single-risk-file cards; the dated owner chores; the decision-number
"row before the branch" rule; the second independent review of docs-or-tools PRs; Study A card T-010; the CGMH half
of the legal-basis memo; the regulatory consultants this month; the G4 to G6 formal validation ritual at CGMH; the
licence as a gate (the owner shares a completed system later; no `LICENSE` now). The full list with files is in the
pull request and in TB-PLAN-06 §0.
