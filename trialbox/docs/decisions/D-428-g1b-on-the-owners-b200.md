# D-428 G1b on the owner's B200: an offline bundle, one script, a host fingerprint, two MIG layouts

- **Task:** T-114 (`docs/plan/28-master-plan-v6.md` §6.2.4, wave 1)
- **PR:** this branch (`agent/T-114-b200-bundle`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** PLAN-017 (how G1b reaches the owner's B200), OPS-071 (driver, CUDA and vLLM digest compared);
  supports LLM-011 (measured half), LLM-025 (the B200 number), CR-089. Risk RSK-52.
- **Builds on:** D-409 (shared-quota: two MIG instances, the rule keyed on the MIG profile), D-313 (`eval qualify`),
  D-311 (no development gates)

## Context

G1b was written as a cloud B200 that agents drive with `gcloud`. The owner qualifies on the owner's own B200
instead. No agent can reach that machine, so the run must be one script a person runs, offline. CGMH's MIG profile is
unknown until survey question 51, so one layout cannot be claimed to match it. And a qualification on one host
predicts another only where the hosts match (driver, CUDA, MIG layout, vLLM build).

## Decision

1. **An offline bundle.** `python -m tools.b200_qualify build` writes one `.tar.gz`: the code by `git archive` at a
   commit, the image tarballs, the weight folders, the layouts and `MANIFEST.json` (sha256 and size of every file),
   plus `<bundle>.sha256`, sent by another channel. Nothing on the host needs the network or `gcloud`.
2. **One script.** `tools/b200_qualify.sh`, run as root by the owner or the named operator: check the bundle,
   load the images, fingerprint the host, then for each layout partition, serve, capture, stamp, qualify, stop;
   then write the G1b record. It asks before it partitions. It replaces the planned `deploy/gcp/b200-qualify.sh`,
   which was never written.
3. **The host fingerprint** (`tb-host-fingerprint/1`): GPU name, count and memory, driver, CUDA, VBIOS, MIG mode and
   layout, kernel, OS, container toolkit, docker, vLLM image digests; `host_id` is a hash of the GPU UUIDs, never a
   hostname. Each layout's serving record carries its fingerprint (`host_fingerprint`).
4. **Two layouts** (`eval/qualification/b200-layouts.json`): the smallest that fits the pair (judge 2g.45gb, verifier
   1g.23gb) and one larger (two 3g.90gb). Exactly two; each profile must have a context rule.
5. **The G1b record** (`tb-b200-qualification/1`, `schemas/b200_qualification_record.schema.json`) states the host is
   not CGMH's. It is `passed` only when both layouts are measured and qualified from a bundle built at a commit. A
   stand-in run is `standin`, never `passed`.
6. **`doctor --platform` warns, not fails** (`host_match`): it compares the serving record's fingerprint with this
   host (`TB_PLATFORM_HOST_FINGERPRINT`, else the GPU node's labels and the running vLLM images) and names each field
   that differs. A difference means "re-measure here", which IQ does anyway (WS-11.8); a FAIL would block an install
   for a fact the site cannot change.

## Consequences

- The owner (or the operator) spends one session at the B200; the agents prepare the bundle and read the results.
- `serving_config.capture` now finds a weight folder named by its container path (`/models/...`), as the shared-quota
  compose file names it.

## Open

- The real run on the B200 (GPU ledger B2); the layouts' `max_seqs` and memory fractions are starting values.
- The two throughput numbers of LLM-025 are fields of the record, filled only when the run writes `throughput.json`
  per layout; no tool writes it yet (T-004's G1 report).
