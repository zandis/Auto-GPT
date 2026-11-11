# Qualification records

`python -m tools.trialbox eval qualify --profile <profile>` (`tools/qualify.py`, D-313) writes one record here per
run: `<profile>-<judge build>-<UTC time>.json`. It follows `schemas/qualification_record.schema.json`. Each record
cites the model change protocol (`docs/validation/model-change-protocol.md`, D-343) by path, sha256 and change id:
give the change with `--change MC-n` (default `MC-0`, a first qualification). The `n12` evidence must say `"basis":
"unadjusted"`. A record is `passed` only when every step of `tools.qualify.STEPS` is in it and `passed`; a missing
step is a failed step.

Check a record before you rely on it:

    python -m tools.qualify --check eval/qualification/<record>.json --profile rtxpro6000 --environment PRODUCTION

`--check` recomputes the status and the body's sha256. It refuses an edited record, a record of another profile and,
for PRODUCTION, synthetic weights or a stub run.

`schema_probes.yaml` holds one adversarial probe per prompt id for the `schema` step (all data synthetic). Add a
probe in the same pull request as a new prompt id: a prompt with no probe fails the step.

Stub runs (`--stub`, profile `ci`) write to `.cache/qualification/`, not here. They prove the wiring only.

`b200-layouts.json` names the two MIG layouts G1b qualifies on the owner's B200 (T-114, D-428; RUNBOOK §11 "G1b on
the owner's B200"). `tools/b200_qualify.sh` reads it from the bundle; G1b's record lives in
`docs/plan/measurements/b200-g1b/`.
