# D-373 The GB10 profile as data, Spark memory limits, the driver hold, the two-device link

- **Task:** T-214, arm64 builds, the `gb10` profile, the two-device link (`docs/plan/28-master-plan-v6.md` §6.2.5;
  TB-ASSESS-01 T-214)
- **PR:** this branch (`agent/T-214-arm64`)
- **Date:** 2026-11-11
- **Status:** accepted for the parts built here; every number is unmeasured until a Spark run
- **Closes:** OPS-063 (the parts that need no Spark), OPS-019 (the image owner); supports CR-089
- **Builds on:** D-79 (the driver pin), D-124 (the GB10 tier), D-177 (model-guard), D-348 (the vLLM image by digest)

## Context

The deep review of 2026-11-10 (`docs/reviews/2026-11-10-deep-review/09-operations.md`) found: the Spark profile is
not measured; the driver is held at exactly 580.142 with no date and no re-test, so driver security fixes are
blocked without end; unified memory (128 GB) is shared by the models, Postgres, HAPI and DuckDB with no container
limit; the two-device form of the plan (a Spark and a CPU workstation, encrypted link) has no compose split
(OPS-063); and nobody owns the Spark's vLLM image (OPS-019). There is no Spark and no arm64 GPU here, and nothing may
cost money, so the measurement waits for a Spark. What CI can check is built now.

## Decision

1. **The profile is data.** `deploy/gb10-profile.yaml` (schema `tb-gb10-profile/1`) holds the device, the driver
   hold, a memory limit per service, the split of the two-device form and the seven rows of the owner's decision gate
   (TB-PLAN-05 §1.6). Its status is `unmeasured`: every measured field is null, and `python -m tools.two_device
   profile` refuses a value in one until the status is `measured` and `record:` names the benchmark record of a real
   Spark run. Then every measured field must have one.
2. **Memory limits on the Spark.** Every service of `docker-compose.gb10.yml` gets `mem_limit` equal to the profile
   (vLLM: its `--gpu-memory-utilization` fraction of 128 GiB plus the host process; HAPI: its heap plus JVM). The
   limits plus an 8 GiB OS reserve fit 128 GiB in both forms (one device: 124; the Spark of two devices: 77). Whether
   the GB10 charges a vLLM process's GPU allocations to its memory cgroup is itself unmeasured; the first Spark run
   reads it.
3. **The driver hold is dated.** 580.142 is held from 2026-11-11. The operations engineer of lane 2E re-tests each
   newer driver build on the bench Spark with `make spark-e2e` (canary 54) at least every 28 days; the next re-test is
   due 2026-12-09. The hold moves only on a pass. `doctor --two-device` warns on the Spark once the date has passed.
4. **The two-device link is mutual TLS 1.3, not WireGuard.** The workstation of form A runs Windows with WSL2, where a
   WireGuard interface needs host administration outside Docker, and a kernel tunnel cannot be tested in CI. The link
   is a small relay (`tools/two_device.py`, one `link` container per device, from `deploy/two-device/`). Both ends hold
   a certificate of a link CA made at the install ceremony (`python -m tools.two_device certs`); the CA key is never
   written, so adding a device is a new ceremony. Each end also checks that the peer's certificate names the other
   device (`trialbox-link-spark`, `trialbox-link-workstation`). The Spark exports `gateway` and imports `db` (the
   gateway's trace store); the workstation the reverse. Each link answers on the box network under the imported name,
   so no caller changes its address. Nothing else crosses.
5. **The gateway is not a listener.** On the Spark the link is the only published port, bound to the link address
   (`TB_LINK_ADDR`). `doctor --two-device` FAILs any other published port on the Spark (a gateway on 0.0.0.0 among
   them), host networking, the database on the Spark, the models on the workstation, a link without its peer,
   certificates or route alias, and a Spark memory limit other than the profile's.
6. **The image owner (OPS-019).** The Spark runs the official vLLM release by digest (D-348), its arm64 manifest. The
   image gates of `trialbox-images.yml` scan it and write its SBOM on the arm64 runner. The operations engineer of
   lane 2E owns moving the lock entry (a model change: requalify first). No mirror is built while the official image
   carries an arm64 build.
7. **arm64 in CI.** The image job builds every image natively on `ubuntu-24.04-arm` and now runs `make
   two-device-check` there: both devices' rendered compose against the profile, and the link selftest inside the
   arm64 image. `make images PLATFORM=linux/arm64` builds one platform off an arm64 host.

## Consequences

- A GB10 box gets memory limits from the first install. They are planning values; an out-of-memory kill on the first
  Spark run is a measurement to record, not a defect to hide by removing the limit.
- `doctor --two-device` is the configuration check of the two-device IQ. The IQ protocol itself waits for the bench.
- Not in this decision, and listed in the PR under Remains: every measurement on a Spark (the pair with canary 54, the
  5,000- and 50,000-patient nights, 200 profiles, the 14 nights, the cgroup accounting); the link on two real devices;
  the host firewall rule that admits only the peer to the link port; the backup and the update path across both
  devices; the Spark's local audit and trace folders in the workstation's backup.
