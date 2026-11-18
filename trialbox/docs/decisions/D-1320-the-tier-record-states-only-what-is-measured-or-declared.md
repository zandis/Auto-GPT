# D-1320 The tier record states only what is measured or declared, and a stand-in is never one

- **Task:** lane H, plan 10 row 10E-1 (commitment C-4; review 13 card 13-2; review 19 section 5.1)
- **Date:** 2026-11-18
- **Status:** proposed
- **Builds on:** D-112 and D-124 (a profile installs only from a serving record of its own uncapped card), D-138
  (tiers from measured records only)
- **Amended 2026-11-18 (10E-1c):** the records, schema and page moved from `deploy/tiers/` to `models/tiers/`,
  which `deploy/docker/python.Dockerfile` copies into the trialbox-py image (`COPY models /app/models`), so the
  gateway and the orchestrator find them at the same path relative to the code as on the host. Readers take a value
  from the record only when its field is measured (D-1322).

## Context

Commitment C-4 of plan 10 says one tier record is read by the gateway, the scheduler and the console, and no tier
value lives anywhere else. Today the values live in four places: the compose override's flags and comments,
`deploy/install.sh`, the gateway's slot constant and the night budget's code default (review 13 section 5.3). The
first site runs the 32 GB card (the owner's third ruling of 2026-11-18), and nothing about that card has been measured
on the card itself: the only stored figures were taken on a larger card capped to 32 GB (review 19 section 1.3). Plan
10 row 10E-28 adds a ballast stand-in, whose records say "by ballast" and are never tier records.

## Decision

1. **One file per GPU profile.** `models/tiers/<profile>.json`, format `tb-tier-record/1`, schema
   `models/tiers/tier_record.schema.json`. The file's name is the profile `deploy/gpu_profile.sh` prints; `tier` is
   the name `tools/tiers.py` gives that profile.
2. **Every field states its basis.** `measured` (from `measured_on.serving_record`, which must pass
   `tools/serving_config.py`'s rule for the profile), `declared` (a repository file and line, which the checker opens),
   or `not_measured` (value null, and `measured_by` names the run or card that would measure it). A value is never
   filled in from another card, an estimate or a code default.
3. **Complete means every field.** The schema lists 28 fields (sequences, context, roles on the box, protocol route,
   night budget, interactive lane, console promises, and the card facts the host check and `doctor` read). A record
   that leaves one out is refused; "not measured" is a complete answer.
4. **A stand-in is never a tier record.** A record whose text says "by ballast", or whose serving record was taken on
   a capped card (ballast or utilisation), is refused by name.
5. **The 32 GB site box's record is the first.** `models/tiers/rtx5090.json`: 0 measured, 18 declared, 10 not
   measured. It changes only by a new measurement (R-1, row 10E-30) or a changed declaration.
6. **What reads it.** `models/tiers/README.md` lists, per waiting row (10E-33, 10E-11, 10E-17, 10G-11, 10K-3,
   10K-11), the fields it reads. Moving the existing readers onto the record (the gateway's slot constant, the night
   budget default, the console) is their owners' change and is not made by this record.

## Consequences

- `python3 tools/tier_record.py check` (standard library, as `tools/tiers.py`) gives exit 0 or 3 with the reasons;
  `summary` prints the counts by basis.
- The row's "every reader uses it" and "`SLOTS = 16` gone" stay open until the readers' owners move them.
