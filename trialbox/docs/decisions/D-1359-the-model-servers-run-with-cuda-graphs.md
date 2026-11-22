# D-1359 The model servers run with CUDA graphs: `--enforce-eager` off in every profile (H80)

- **Task:** lane H, card H-80 (the integrator, 2026-11-22 10:09 UTC: "the flag off, the pinned arguments updated, and
  the qualification record re-measured once on the new setting by the bench before the line") · **Date:** 2026-11-22
- **Status:** proposed (row reserved; the integrator flips it when merged)
- **Builds on:** D-111 (the serving record), D-112 and D-124 (a profile installs from a measured record of its own
  card), D-1320 (the tier record). Answers review findings R-89 / A-17, MR-088, LLM-013 and root review B1-M1 / 08-10.

## Decision

1. No serving profile starts its model servers with `--enforce-eager`: the five compose profiles
   (`deploy/docker-compose.{rtxpro6000,rtx5090,dgpu48,shared-quota,gb10}.yml`, judge and verifier), the platform
   manifest `deploy/platform/components/gpu-pair/llm.yaml` and the two runs that take a profile's records
   (`deploy/gcp/gpu-pro6000-run.sh`, `deploy/gcp/complete-run-vm.sh`). The engine's default then applies: CUDA graphs
   are captured at start. Nothing else of the command lines changes.
2. Why the flag was there: no record says. It first appears in the GPU simulation script of 2026-11-06
   (`deploy/gcp/gpu-sim-startup.sh`, kept as the record of that run) and was copied into every profile; three
   reviews found it never measured ("It was set for the first measured runs and kept").
3. The bench's comparison (its comment on #639, 2026-11-22 10:08 UTC), the shipped judge, the same weights and
   settings otherwise: on 20,096 TREC CT criteria the same label on 91.5 % eager against graphs, and two eager runs
   agree on 91.5 % too (decoding at temperature 0 is not bit-stable on that server), so the difference is run-to-run
   noise; lost 36.5 % eager, 35.9 % graphs; block flips about 1.2 to 1.3 % both ways, on the 1,015-criterion sets of
   each language as well. First token of a 3,000-token prompt alone: median 0.123 s eager, 0.020 s graphs.
   Throughput 4 to 9 times at 8 to 64 calls in flight. The bench ran at a memory fraction of 0.9, not the profiles'.
4. The vendor's measured record `deploy/measured/serving_config.rtxpro6000.json` was taken with the flag and keeps
   `enforce_eager: true`: it is what was measured. It still passes `tools/serving_config.py measured` (card, context,
   fractions and sequences are unchanged), so the install is not refused; `measured` says on stderr, for any record
   that ran eager, that start time, memory and rate of the new setting are to be re-measured. The tier record's
   values from that record are not changed: no figure is filled in without a measurement.
5. Re-measured once by the bench on the new setting, before the line, per profile it holds: time from start to
   healthy of each server; card memory at start and at peak at the profile's own fractions; throughput; label
   agreement. The records: a new serving record (`deploy/gcp/capture-serving-config.sh`, i.e.
   `tools/serving_config.py capture`), the peak file of the same run, and the qualification record
   (`python3 -m tools.trialbox eval qualify --box --profile <gpu> ...`). The card's page lists every start-time and
   memory assumption to read again (`docs/handover/serving-without-enforce-eager-2026-11-22.md`).

## Putting it back

The flag is not an environment switch, and none is added. A site or a profile whose servers misbehave with graphs
(a failed capture at start, memory short at the profile's fractions, a wrong answer) puts it back by a compose
override beside the site's files, named in `COMPOSE_FILE` after the profile, holding each server's `command` with
`--enforce-eager` added (`deploy/gcp/box-install-run.sh` writes such an override for its tuned mode). A profile that
needs it for good gets the line back in its compose file by a card with the measurement that shows why.
