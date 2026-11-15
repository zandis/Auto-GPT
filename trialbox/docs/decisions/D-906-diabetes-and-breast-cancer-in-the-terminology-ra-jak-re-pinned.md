# D-906 Diabetes and breast cancer in the terminology; RA-JAK re-pinned (the owner's D-518)

- **Task:** the owner's ruling D-518 (2026-11-15, by way of the integrator on #639): the terminology update is approved, by lane A2's option (a); **Date:** 2026-11-15; **Status:** reserved
- **Decision:** the synonyms gain "diabetes mellitus", "diabetes" and 糖尿病 as a grouper over E08, E09, E10, E11 and E13 (and WHO's E14 by D-314), and "breast cancer", "breast carcinoma", "invasive breast carcinoma", 乳癌 and 乳がん as C50. The terminology release moves from TR-42f2b2dc96cf to TR-7cedf1a45e79. RA-JAK's manifest field `terminology_release` is re-pinned to it; its value sets, SQL and CQL are unchanged (`tools.build_rulesets --check`: every shipped ruleset equals the compiler's output), and no other ruleset carries a pin.
- **What the owner re-approves:** RA-JAK, for the one field `terminology_release` (TR-42f2b2dc96cf to TR-7cedf1a45e79); nothing it compiles to changes.
- **Test:** `tests/unit/test_diabetes_grouper.py` (the groupers, and RA-JAK's pin equal to the release the shipped tables make).
