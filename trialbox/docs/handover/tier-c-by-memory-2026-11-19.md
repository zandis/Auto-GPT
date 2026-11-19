# H-10E-5: tier C split by memory, a 64 GB Spark refused

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders, so in one
language.

- **Card:** 10E-5 (plan 10, track E; lane H since the integrator's ruling of 2026-11-19, 16:03 UTC)
- **Date:** 2026-11-19
- **Decision:** [D-1335](../decisions/D-1335-a-64-gb-spark-is-refused-not-guessed.md)
- **Findings:** [`tier-c-by-memory-2026-11-19/findings.json`](tier-c-by-memory-2026-11-19/findings.json)
  (H10E5-01 to H10E5-03)
- **Tests:** `tests/unit/test_small_spark_refused.py`

Nothing here was run on a Spark. No GPU, no Docker daemon and no cloud call were used. The scripts were run with
stand-ins for `docker` and `nvidia-smi`, and the memory was given to them.

## 1. Why the builders' branch was not kept

Draft pull request #1201 (`agent/10E-5-tier-c-split-by-memory`, head `b5c82768`) gave a 64 GB Spark its own
profile: fixed container caps scaled down from the 128 GB profile. The lead's rulings bind this card: a tier value is
read only when measured (D-1322); nothing is measured here; if a 64 GB profile cannot be shown to fit from numbers
already in the repository, the installer refuses. D-1335 shows that it cannot be shown to fit. So the branch's caps
were not kept, and this branch starts from master.

## 2. What changed

| File | Change |
| --- | --- |
| `deploy/gpu_profile.sh` | A GB10 host (or an Arm host with an unreadable card name) whose `MemTotal` is under 96 GiB prints `gb10-64`. The memory is compared in kB. A fourth argument gives it for a named machine; without it the memory is unknown and the answer is `gb10`, as before. `memory-class [<kB>]` gives the class alone. |
| `deploy/install.sh` | GPU mode with gb10 on a host under 96 GiB becomes `gb10-64` and is refused, however gb10 was chosen. The message says why and names `--mode stub`. `TB_TEST_MEM_KIB` stands in for `MemTotal` in tests and is passed to the tier check. |
| `deploy/poc.sh` | The same refusal in the one-command PoC's GPU mode. |
| `tools/tiers.py` | A live check reads `MemTotal`; `--mem-kib` gives it. A small Spark is refused with its own sentence, not "not one of the three measured boxes". |
| `tools/box/plan.py` | `Hardware.mem_total_kib` keeps `MemTotal` as read. The plan passes it to the detector (the rounded `ram_gib` only when it is missing) and makes a small Spark a stub box with a warning. |
| `tools/spark_e2e.sh` | Its GPU run stops on a small Spark before anything is written. |
| `docs/runbook/08-dgx-spark-end-to-end.md` | One paragraph: a 64 GB Spark is refused, and what to do. |

## 3. The review's findings and how each is closed

| Finding (integrator, 16:03 UTC) | Closed by |
| --- | --- |
| High: a fixed 1 GiB orchestrator cap below the recorded 2,133.9 MiB peak | No 64 GB caps exist. The host is refused. |
| High: a 1 GiB database cap against the installer's `shared_buffers` sizing | The same. |
| Medium: the box planner passes its detected profile as `--gpu` and bypasses the existing-install check | A small Spark is planned as a stub box. A 128 GB Spark is unchanged. |
| Medium: a second serving record reclassifies an installed box | No record is consulted. The class comes from `MemTotal` alone. |
| Medium: the tier check rejects an existing medium install on a 64 GB host | Refusing that host is now the ruling. Before, it ran with model caps of 74 GiB on 64 GB. |
| Medium: validation applies the cutoff to nvidia-smi's memory, detection to `MemTotal` | No validation cutoff was added. H10E5-02 records what is left. |
| Medium: the mail gateway's 256 MiB cap | No 64 GB caps exist. |
| Medium: the budget test omits the identity services | No 64 GB budget exists. |
| Medium: the PoC rejects the new detector output | The PoC now refuses with a reason (tested). |
| Low: the compose skip decorator moved off the site-cap test | `tests/unit/test_compose_limits.py` is not changed. |
| First round, Low: rounding to one decimal moves a host across the line | The memory is compared in kB; the plan uses `MemTotal` as read (tested one kB under the line). |
| Lane H's comment: the caps cap the container, not the model; the stack sums to more than the host | No 64 GB caps exist. D-1335 gives the arithmetic. |

Lane H's comment also named an 80 GiB boundary in `tools/serving_config.py`. It was not found on master `a7d6562b`.

## 4. What was not done

- No 64 GB profile, overlay, tier record or serving record was written (D-1335).
- `deploy/check_host.sh` and `tools/serving_config.py` are unchanged (H10E5-02, H10E5-03).
