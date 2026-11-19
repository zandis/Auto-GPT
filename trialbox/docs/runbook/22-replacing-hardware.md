# RUNBOOK §22 part: replacing hardware

**Reader:** Aimedics, with the box owner.

*T-635 (OPS-074, OPS-045). The box is dead, lost, or a part must be replaced and the disk cannot stay.*

**Drill (T-213b):** none. This procedure is not rehearsed by a test: a restore onto a second machine from the
backup and the KEK shares alone needs that second machine, and no such drill runs yet.

*Default until the owner answers (TB-DR-09 Q5):* Aimedics keeps one loaner box and ships it within five working days.

1. **A lost or stolen box** is first an incident: follow the hospital's procedure (§7; the incident plan is T-318)
   and the lost-box list (§23) the same day. The steps below then rebuild the service.
2. **A part that can be swapped with the disk staying** (power supply, fan, a GPU of the same model): the supplier
   swaps it on site; the disk never leaves. After the swap: `nvidia-smi`, `trialbox doctor`, the pair canary
   (`trialbox selftest` on the box). A GPU of another model is a new hardware form: the model pair must be qualified for
   it first (§11, "qualify a model pair"), so it is a release step, not a repair.
3. **A new box:** install it from the release media (§1). The KEK of the old box was sealed to its TPM, so the new
   box unseals it from the stewards' shares or the passphrase (§23); then restore (§22, "The restore, with the
   clock"). A new TPM is sealed at install.
4. **The old disk** is purged with a certificate, or kept locked by hospital IT until it is (§20, T-628). It never
   leaves the hospital.
5. Tell the trial offices when the service is back, and what to redo (the audit lists it).
