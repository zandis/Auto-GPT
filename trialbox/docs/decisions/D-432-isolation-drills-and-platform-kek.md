# D-432 Shared-host isolation drills, the platform KEK in a hospital KMS, and the noisy-neighbour measurement

- **Task:** T-319 (`docs/plan/28-master-plan-v6.md` §6.2.5; the contract of TB-ASSESS-01's T-319)
- **PR:** this branch (`agent/T-319-isolation-drills`)
- **Date:** 2026-11-11
- **Status:** accepted (the code and the offline tests); the drill itself is not run: no shared GPU host exists yet
- **Closes:** CR-094 (isolation part: the probes and the drill are built), OPS-069 (drill half)
- **Builds on:** D-211 (the platform form), PR #85's `tests/platform/`, T-633 / D-416 (day 2), T-210b / D-347 (the KEK)

## Context

PR #85 shipped a probe from a second namespace (ports and volumes). The card asks for more: TrialBox reaches only the
IT pack's §A.3 hosts, a job over the GPU partition is refused, the running images are `release.json`'s digests, a
KEK held by the platform without a plain Secret, and a measurement of what another tenant's load does to serving. No
shared GPU host and no hospital KMS exist yet; the work has to be runnable later and tested now without them.

## Decision

1. **Three more live probes** in `tests/platform/test_isolation_probe.py` (integration, run against a cluster): a
   TrialBox-labelled pod reaches neither a host on the internet (`TB_PROBE_OUTSIDE`) nor the API server; a pod asking
   for one GPU device more than the quota is refused at admission; every running container of a pinned image runs
   the pinned digest.
2. **The negative test runs offline in CI** (`tests/platform/test_isolation_drill.py`): one extra egress host in a
   rendered policy, as an address only or also named in the annotation, makes `doctor --platform` FAIL
   `network_policy`.
3. **The platform KEK variant is a `kms` back end of `tb_common.kek`**: a random KEK sealed by the hospital's KMS
   through the Vault / OpenBao transit protocol; `kek.json` keeps only the KMS ciphertext; services open it with
   `TB_KMS_TOKEN` (an environment variable; on a platform the Secret `trialbox-kms`, a revocable token, never the
   KEK); https only (plain http to the loopback for a test KMS); no proxy; the token never in an error. The returned
   key must match `kek.json`'s id. Tested against a mock transit server on the loopback.
4. **Noisy neighbour** is `python -m tools.trialbox.noisy_neighbour`: the same short request idle and under the
   platform team's load, PASS when nothing fails and the loaded 95th percentile is at most 1.5 times the idle one.
5. **The drill** (RUNBOOK §17): probes, noisy neighbour, `doctor --platform`, on the acceptance cluster, at IQ and
   after every platform patch; its record table says "not run" until a shared GPU host exists.

## Open

- The drill on a real shared GPU host, and again after a simulated driver change, with the serving record re-measured.
- "D3 never leaves the namespace" as a live probe; `doctor --platform` reading the drill files as IQ evidence.
- Which KMS CGMH has (if any); without one the steward's unseal stays.
