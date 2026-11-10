# Qualification records

`python -m tools.trialbox eval qualify --profile <profile>` (`tools/qualify.py`, D-313) writes one record here per
run: `<profile>-<judge build>-<UTC time>.json`. It follows `schemas/qualification_record.schema.json`. A record is
`passed` only when every step of `tools.qualify.STEPS` is in it and `passed`; a missing step is a failed step.

Check a record before you rely on it:

    python -m tools.qualify --check eval/qualification/<record>.json --profile rtxpro6000 --environment PRODUCTION

`--check` recomputes the status and the body's sha256. It refuses an edited record, a record of another profile and,
for PRODUCTION, synthetic weights or a stub run.

`schema_probes.yaml` holds one adversarial probe per prompt id for the `schema` step (all data synthetic). Add a
probe in the same pull request as a new prompt id: a prompt with no probe fails the step.

Stub runs (`--stub`, profile `ci`) write to `.cache/qualification/`, not here. They prove the wiring only.
