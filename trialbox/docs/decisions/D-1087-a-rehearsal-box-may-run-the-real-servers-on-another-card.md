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

## Amendment (H-89b, 2026-11-23; the owner's ruling 7087828219, the integrator's 7088891993)

- Under the same mark only, every shipped profile: `dgpu48` (the 48 GB draft; outside the mark the refusal of cards
  24-5 and 24-6 stands byte for byte), `gb10` on an x86_64 host as an "x86 stand-in: memory budget only" (the box's
  compose override sets the overlay's arm64-pinned services to linux/amd64; the host check FAILs gb10 on x86_64
  outside the mark), and `rtx5090` on one slice of a split card (`--gpu-index N:M`, for the probe and the install,
  pinned by the slice's UUID; every check of the probe holds for the slice). Each is held to its own class's memory on
  the bench's card.
- deploy/box-install.sh hands the real-servers options on to install.sh under the mark only (the Windows host path,
  inside WSL2); not verified on a WSL2 host.
- Unchanged: never on PRODUCTION, never by an environment variable alone, the completion mark, the boot guard and the
  caller's-override refusal.
- Page: `docs/handover/rehearsal-real-servers-h89b-2026-11-23.md`.
