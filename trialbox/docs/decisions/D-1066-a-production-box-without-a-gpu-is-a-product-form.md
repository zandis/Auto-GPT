# D-1066 A PRODUCTION box without a GPU is a product form

- **Task:** an owner's ruling, numbered by the integrator; built by lane D (the second card after H-22's finding 5)
- **Date:** 2026-11-17
- **Status:** accepted (the owner's ruling; recorded here on 2026-11-17)

## Ruling

1. A hospital may install a PRODUCTION TrialBox on a machine with no GPU. Such a box does feasibility and the
   structured criteria; criteria that need the notes read wait for a GPU, which the site may add later.
2. The installer therefore pins the embedder (e-embed-1) in stub mode as it pins the model pair in GPU mode, every
   site bundle carries the embedder's weights (about 2.3 GB), and the bundle check refuses a site bundle without them.
3. The box plan's no-GPU path and `deploy/install.sh` agree, and the install runbook says what a no-GPU box does and
   what it does not.
4. Whether embedding on a CPU is fast enough at a hospital's size is not measured yet. It is measured on a clean
   machine with the pinned weights before release 1.0 says so.

## Where the wording comes from

Lane H's install by the runbook alone (H-22, D-1136, finding 5): `--mode stub` on a PRODUCTION box left
embed-service unhealthy, "no pin for e-embed-1". The integrator put two options to the owner on 2026-11-17: make it
a product form, or refuse it. The owner's answer in the integrator's session: "Option a".

## Used by

Lane D's card for finding 5 (the installer, the bundle check, the box plan, `docs/runbook/`).
