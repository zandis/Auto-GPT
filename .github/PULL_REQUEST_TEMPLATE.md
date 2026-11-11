<!-- TrialBox pull request (T-654; trialbox/docs/validation/development-plan.md). Plain English, short sentences.
Synthetic or public data only. No secret, key or real identifier in the body. Delete the hints you do not need. -->

## Card

<!-- The card id and its row in trialbox/docs/plan/28-master-plan-v6.md §6.2, or "none" with a reason. -->

## Summary

<!-- What changes and why, in a few lines. -->

## Class B paths touched

<!-- yes or no. If yes, list them (trialbox/docs/validation/software-safety-classification.md §2) and the tests that
check their rules: property, mutation-killing or engine-agreement tests. A class B change also gets one automated
adversarial review (D-311). -->

## Decision

<!-- D-nnn and its file under trialbox/docs/decisions/, or "none". -->

## Acceptance

<!-- Each acceptance test of the card: done, partial or not done, with the test that shows it. -->

## Tests added

## Checks run

<!-- From trialbox/: ruff check, ruff format --check, doclint, data_scan, decisions_index --check, the security scans
if you touched dependencies or code they read (python -m tools.security_scan secrets|sast), and the tests you ran. -->

## Problems closed or opened

<!-- Finding ids and rows of trialbox/docs/validation/problems.csv this change fixes (state fixed, this PR, the
verifying test) or opens. A new ignore in trialbox/tools/security_scan_ignores.yaml is listed here with its reason. -->

## Files outside the card

## Remains

## Dropped (D-311)
