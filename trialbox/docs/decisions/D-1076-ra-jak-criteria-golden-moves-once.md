# D-1076 RA-JAK's criteria golden moves once, to the recompile of three ruled changes

- **Card:** the integrator's ruling F17-B (2026-11-27), applied in the Track 2 merge (#1508 then #1506).
- **Decision:** `RA_JAK_CRITERIA_SHA256` in `tests/unit/test_study_manifest.py` moves from
  `e1e9eed8…` to `4cf904d54627a8cbce15f12f8e567c6a11a6c1c68e83777b9f5b4c7b49a756c0`: the hash of one recompile of the
  merged tree. Every rule change between the two values is ruled: V-18b (D-1183), INT-R1 (D-1073), INT-R2 = integrator
  ruling F17-B for #1506 (D-1074), with V-18b review F1 (D-1183) as written: a grouper's lost ATC families are its
  prefix rows only (`Terminology.atc_losses`), so INT-R2's `family` rows, which list no code by design, send no
  ValueSet for review. The intermediate values of the separate merges (and `180b8b6a…`, the first value of this
  pull request, which still carried that review tag) never ship.
- **Evidence (the ruling's rule, all in the one commit and its pull request):** the ruling ids in the test comment and
  this row; `python -m tools.build_rulesets --recompile` then `--check` equal on the merged tree with RA-JAK pinned to
  terminology release TR-e2f7eee5053f; a criterion-level diff of the compiled output, old against new, each changed
  criterion mapped to one ruling; a second, independent run of the hash from a clean checkout of the commit, byte for
  byte.
- **Open (named):** the owner re-approves the recompiled rule sets (D-906 pattern) before RA-JAK goes live with this
  output. The golden moves in the repository now; the rule set does not go live until that approval is recorded.
