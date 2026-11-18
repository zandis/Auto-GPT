# Tier records

`<profile>.json`: the tier record of one GPU profile (plan 10 row 10E-1, commitment C-4, D-TIERREC), format
`tb-tier-record/1`, schema `tier_record.schema.json`, checked by `python3 tools/tier_record.py check`. One record per
profile holds what the rest of the product reads about the box. Every field says its basis:

- **measured**: from this profile's serving record taken on its own uncapped card (`measured_on.serving_record`,
  which must pass `tools/serving_config.py measured <profile>`);
- **declared**: a repository file and line declare it (`source`); the checker opens the file and the line;
- **not measured**: the value is null and `measured_by` names the run or card that would measure it. A figure not
  measured is never filled in.

A record made under the ballast stand-in (plan 10 row 10E-28, text "by ballast") is refused, and so is a record whose
serving record was taken on a capped card.

| file | box | measured | declared | not measured |
| --- | --- | ---: | ---: | ---: |
| `rtx5090.json` | the 32 GB site box (tier `small`) | 0 | 18 | 10 |

No other profile has a record yet. The owner's own workstation (Ubuntu on Arm, IGX Orin, RTX A6000 48 GB) is not a
measured tier and has no record; release candidate 1 installs only on an x86 box with the measured RTX PRO 6000 card,
whose tier record is not written by this card.

## What each waiting row reads

| Row | Reads | What it does with it |
| --- | --- | --- |
| 10E-33 site box wording | `box_role`, `protocol_route`, `interactive_lane`, `busy_wait_seconds`, `first_load_nights`, `console_promises` | "sent to the coordinating box" for a protocol; "night 1 of N" from `first_load_nights` (shown as not measured until R-1); busy times while a run holds the card |
| 10E-11 night plan per tier | `night_budget_patients`, `judge_calls_per_second`, `models_on_card`, `screen_concurrency` | the night's budget and order; both figures are not measured on the 32 GB box, so its plan says so instead of using a default |
| 10E-17 tier-aware console wording | `console_promises`, `interactive_lane`, `role_groups_on_box`, `protocol_route` | a capability the box lacks is a status line, never an error; a not-measured value is shown as "not measured" |
| 10G-11 host check per tier | `profile`, `tier`, `desk_side`, `arch` | `desk_side: true` fails a TPM-only disk unlock in VALIDATION and PRODUCTION |
| 10K-3 live preflight (wizard, `doctor`) | `card_names`, `arch`, `card_memory_mib`, `driver`, `host_memory_gib_min`, `measured_on` | the GPU line checks the card against the record; `driver` not measured gives a line that says so, not a pass |
| 10K-11 capability registry and page | `tier`, `console_promises`, `role_groups_on_box`, `protocol_route`, `ecc`, `measured_on` | rows such as "Protocol reading: not on this box, arrives as a signed package"; "not available: tier" |
| the gateway's slots (C-4) | `judge_sequences`, `verifier_sequences` | the slots per endpoint, in place of the constant in `services/gateway/load.py` (not done by 10E-1: see D-TIERREC) |
