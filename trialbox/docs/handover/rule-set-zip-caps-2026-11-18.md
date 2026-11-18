# Rule-set zip caps, and where a rule set's signature is checked (2026-11-18)

**Reader:** the people who build TrialBox: lane B2 (the rule-set install), lane A2 (feasibility), lane H and the
integrator. Findings for builders, so in one language.

Plan 10 row 10G-6 (review 16-23 and 9g-12, ASVS 12.1.2), decision D-1102. Findings in the register's `--add-from`
form: `rule-set-zip-caps-2026-11-18/findings.json`.

## What changed

Every place a rule-set zip is opened now goes through one checker, `libs/tb_common/zipcap.py`
(`check_ruleset_zip`), before any member is read or written:

| Place | Opens | Refusal |
| --- | --- | --- |
| `services/criteria_compiler/import_ruleset.py` `read_zip` (the offline install; `tools/trialbox/update.py` `rulesets` runs it in the compiler container) | the staged update's rule-set zip | `ImportRefused`, before the repository is touched |
| `services/orchestrator/scenarios/cohort.py` `load_draft` (the trial simulation, `trials.py`) | the compiler's draft zip from the object store | `StepFailed`, before the temporary folder is made |

No console route uploads or imports a rule-set zip (the console writes zips only: the sponsor pack, the review
pack). The caps (D-1102): at most 2,000 members; 100,000,000 bytes a member and 200,000,000 bytes in all,
uncompressed; at most 200 times expansion for a member over 1 MB; no absolute path, `..` part, backslash, NUL,
symbolic link or repeated name. They are stated rows L36 to L39 of `tools/limits_edge.py`, driven on the function,
and tested at the limit, one over and far over in `tests/unit/test_ruleset_zip_caps.py`.

## Is the offline rule set's signature checked before the zip is opened?

**Yes, on the update path.** The order:

1. `tools/apply_update.sh:111` (or `:120` in a container) runs `tools/verify_update.py` before anything is staged:
   the Ed25519 signature of the bundle's manifest with a trusted vendor key (`tools/verify_update.py:243`), then each
   payload's size and sha256 against the signed manifest while it is copied to the stage (`:352`, `:491`). The
   rule-set zip is such a payload (kind `ruleset`). A mismatch stages nothing.
2. `tools/apply_update.sh:148` runs the update path only after that; `tools/trialbox/update.py:2036` refuses a
   summary that does not name the staged manifest's sha256.
3. The zip is first opened at `tools/trialbox/update.py:1615` -> `services/criteria_compiler/import_ruleset.py:32`,
   after the restart; its stored SQL reaches feasibility through `repo.materialize` and
   `criteria_compiler/compile_sql/overlay.py:56` (`safe_sql`) into `services/orchestrator/scenarios/feas_compute.py:274`.

So for H10G42-21 and -22, an offline rule set's SQL text is covered by the vendor signature. Two routes are not:

- `python -m criteria_compiler.import_ruleset FILE` installs any zip it is given, approved by its own manifest; it
  checks no signature itself (H10G6-01, Low: it needs a shell in the compiler container).
- The trial simulation reads the compiler's **draft** zip from the object store (`trials.py:63` and `:97` ->
  `cohort.load_draft`) and runs its SQL through `feas_compute` (`trials.py:118`). A draft is never signed (it is the
  box's own compiler output, not approved); nothing binds the stored zip to the compile result that named it
  (H10G6-02, Low: it needs write access to the object store).

Neither is fixed here (the card's word).
