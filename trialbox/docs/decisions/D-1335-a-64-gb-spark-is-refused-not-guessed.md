# D-1335 A DGX Spark with under 96 GiB of memory is refused, not guessed

- **Task:** lane H, plan 10 row 10E-5 (tier C split by memory). The integrator's ruling of 2026-11-19, 16:03 UTC,
  sent the card to lane H. The lane H lead's rulings bind it: a tier value is read only when measured (D-1322);
  nothing is measured here, so no tier record is written; if a 64 GB profile cannot be shown to fit from numbers
  already in the repository, the installer refuses with a clear message.
- **Date:** 2026-11-19
- **Status:** proposed
- **Builds on:** D-1322, D-373 (the GB10 profile), D-124 (the pair profiles), D-1005, D-890

## Context

`deploy/gpu_profile.sh` called every GB10 `gb10`. That profile is the 128 GB Spark: `docker-compose.gb10.yml` caps
the two model servers alone at 42 + 32 GiB. A 64 GB Spark has at most 64 GiB of memory (59.6 GiB if the 64 is 10^9
bytes). The draft pull request #1201 gave it its own caps (23 and 13 GiB for the model servers, 1 GiB for the
orchestrator and for the database). Its review found that these caps cut below numbers the repository records, and
that they cap the containers, not the models.

What the repository records, and what it does not:

| Part | GiB | Source |
| --- | --- | --- |
| The judge's weights | 17.5 | the RTX PRO 6000 record's `model_files` (18,825,679,760 bytes); the Spark builds' sizes are not recorded |
| The verifier's weights | 8.5 | the same (9,091,720,350 bytes) |
| The judge's memory outside its budget | about 3.1 | plan 10 decision 32 (review 19) |
| The orchestrator at 20,000 patients | 2.1 | `deploy/measured/orchestrator_memory.json` (2,133.9 MiB, D-1005) |
| The embedder, one load | about 3.3 | D-890 (about 3.5 GB) |
| The adapter's validator heap | 3 | `TB_VALIDATOR_XMX` in the compose file |
| The FHIR store's heap | 3 | `HAPI_XMX` default in the compose file |
| The OS reserve | 8 | `deploy/gb10-profile.yaml` (a planning value) |

These rows add up to about 48.5 GiB. That leaves about 11 GiB on 59.6 for the KV caches of both models at 16k, the
database, the lake, the gateway, the console, the document parser, the mail gateway, the identity services and each
JVM's own memory. None of these is measured on a GB10. The 128 GB profile's planning caps for the services alone come
to 23.25 GiB. So a 64 GB profile cannot be shown to fit from recorded numbers.

## Decision

1. **Detected by memory.** `deploy/gpu_profile.sh` prints `gb10-64` for a GB10 host (or an Arm host whose card name
   cannot be read) whose `MemTotal` is under 96 GiB (100,663,296 kB). The memory is compared in kB, never rounded.
   Unknown memory stays `gb10`, as before. `sh deploy/gpu_profile.sh memory-class` gives the class of this host alone.
2. **Refused.** `deploy/install.sh` refuses GPU mode on that host however gb10 was chosen: detected, `--gpu gb10`,
   `TB_GPU_PROFILE`, `--tier medium` or a rehearsal. `deploy/poc.sh`, `tools/tiers.py` and `make spark-e2e`
   (`tools/spark_e2e.sh`) refuse it too. The message says why and what to do: install with `--mode stub`, or use a
   128 GB Spark. The box plan (`tools/box/plan.py`) makes it a stub box with a warning that says the same.
3. **Nothing guessed.** There is no `gb10-64` overlay, profile YAML, tier record, serving record or pinned pair.
4. **When this changes.** A run on a 64 GB Spark (card 10E-6, borrowed hardware, decision 77) that measures the
   pair's peaks and the services' peaks can propose a profile, with its caps taken from that record.

## Consequences

- A 128 GB Spark is unchanged: `gb10`, the same caps, the same record rule.
- A 64 GB Spark gets a refusal with a reason, not a box that runs out of memory at night. Its stub mode works.
- A 64 GB box that an earlier installer accepted as `gb10` (by an explicit `--gpu gb10`) is refused on its next GPU
  install. Before, it ran with model caps of 74 GiB on a 64 GB machine.
