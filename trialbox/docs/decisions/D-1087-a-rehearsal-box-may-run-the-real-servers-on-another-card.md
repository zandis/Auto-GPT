# D-1087 A rehearsal box may run the real model servers on another card and a low driver (H-89)

- **Task:** lane H, card H-89 (the integrator's rulings of 2026-11-22 13:55 UTC and of the review round on #1370).
  · **Date:** 2026-11-22
- **Decision:**
  - Under the rehearsal mark only (`deploy/install.sh --rehearsal --rehearsal-real-servers --gpu rtxpro6000
    --gpu-index N --engine-probe FILE`, on a box that may be a rehearsal box: deploy/.env TB_ENV none, DEV or TEST, or
    VALIDATION with deploy/site/rehearsal.json and TB_REHEARSAL=1), the install may run the rtxpro6000 profile's real
    model servers on one whole card of another model and on a driver below deploy/images.lock `gpu.driver_min`.
  - The driver is a WARN only with an engine probe (`tools/engine_probe.py run --gpu-index N`) that passed H-74's
    check (`tools/measure48_vm.py bench_exception`) and this card's: the card's and this host's one-way ids, the
    pinned digest matched, at most 7 days old, a file root or the installer owns and no one else may write. Only the
    passing form's named variables reach the model servers.
  - Both servers are pinned to that card by its UUID; MIG and too little free memory are refused.
  - The box records it (deploy/site/rehearsal-real-servers.json, `valid_for_a_site: false`; TB_REHEARSAL_REAL_SERVERS=1)
    and says "rehearsal: driver below the minimum, not this profile's card, not valid for a site" (the installer's
    summary, doctor, the host check, the console's banner). It never starts as PRODUCTION: the install, the update's
    pre-start and db-up, and the boot (deploy/settings_guard.sh) refuse it.
  - Without the mark nothing changes: each refusal is byte-identical to before (the invariant test).
- **Page:** `docs/handover/rehearsal-real-servers-h89-2026-11-22.md`.

## Amendment (H-89b, 2026-11-23; the integrator's ruling 7088891993)

- Under the same mark, the rtx5090 profile may run on one slice of a split card (`--gpu-index N:M`, for the engine
  probe and the install), held to its 32 GB cap on the slice's own memory and pinned by the slice's UUID; every check
  of the probe holds for the slice. Any other profile on a slice is refused.
- deploy/box-install.sh hands the real-servers options on to install.sh with `--rehearsal` only (the Windows host
  path, inside WSL2); not verified on a WSL2 host.
- dgpu48 and gb10 stay closed until a ruling on the test that holds them closed.
- Page: `docs/handover/rehearsal-real-servers-h89b-2026-11-23.md`.
