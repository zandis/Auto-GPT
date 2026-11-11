# Release records

*Card T-215 (VMP §4; `change-control.md` §3). Status: living.*

One file per release, `<version>.md`, written by the release step when the tag is made. None exists yet: the first is
written for the first tagged release (the PoC tag `poc-1` has no record, D-311 S1).

Each record holds, in this order:

1. **Identity.** Version, commit, date, `release.json` digest, image digests, the qualified model pair with the
   qualification record ids.
2. **Changes.** Every pull request since the last release, with its card, change class (CC1 to CC6) and decision.
3. **Verification.** The CI run of the tagged commit (link and result per job); the qualification records of any CC1
   change; the goldens state.
4. **Problems.** Rows of `../problems.csv` closed in this release; open rows of the blocking kinds (wrong answer,
   data loss, security; D-311 S5), which must be none.
5. **SOUP and suppliers.** Changes to `../soup.csv` and `../supplier-assessments.md`; the advisory scan result.
6. **Roll-out.** One line per stage of `../change-control.md` §4: where, date, the tool output filed (doctor, canary,
   update log), result.
7. **Periodic review.** When one falls due (VMP §8): its findings and the problem-log rows it opened.
8. **Steps to repeat at a site.** Only where TB-PLAN-06 §0.3 item 2 applies; otherwise "none".

No signature (D-311).
