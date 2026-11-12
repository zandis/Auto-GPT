# Starter prompt: build TrialBox plan v4

Copy everything below the line into a new Claude Code session on the repository `zandis/Auto-GPT`.

---

You are continuing the TrialBox build for Changfu Kuo (Aimedics). TrialBox is an on-prem clinical-trial appliance for hospitals in Japan and Taiwan. It covers pre-screening, the patient list and the PI mail, and the trial lifecycle. The code lives under `trialbox/` in `zandis/Auto-GPT`.

## Read first, in this order

1. `/mnt/project-files/trialbox-design/24-plan-v4.md` (TB-PLAN-04 v1.0, approved 2026-11-08). This is the plan. Build its steps 1–9 in order: 1 → 2 → 3 → 4 → 5 strictly; 6 and 7 may run in parallel with 3–5; 8 and 9 come last.
2. `/mnt/project-files/trialbox-build/fable-review-2026-11-08.md`, the independent review that the plan answers.
3. `trialbox/docs/DECISIONS.md` (D-106 to D-123) and `trialbox/README.md` on master.
4. Draft PR #31 (branch `claude/project-thread-mqobov`, commit 8a6df59): the step-3 work in progress, the data core and REDCap write-back. Keep its design, but move its tables into Postgres `trialbox_wf` after step 2. Its PR body lists what is left.
5. `/mnt/project-files/trialbox-design/23-fhir-platform-comparison.md`: keep HAPI, not Medplum.

## The owner's standing rules

- **No development gates.** Do not plan ethics submissions, hospital rules, external reviews or extra staff during development. Build end to end on synthetic and public data. Gates apply only when real patient data is used.
- **Keep plans and messages short and plain.** Ask him before big changes of direction.
- **Build the full platform before any formal trial.** Sites are not test beds.
- **TrialBox is fully standalone.** It imports every source and works on its own data. Hospital systems (EMR, SS-MIX2, FHIR) are one-way in only. Two-way sync is only for REDCap and spreadsheets, with per-field ownership and listed conflicts that are never forced.
- **Approved decisions (2026-11-08):**
  - CRF answers go in TrialBox's own Postgres tables, with FHIR export on request.
  - SQL is the only runtime screening engine. CQL is kept for the compile-time equivalence gate.
  - The v1 lifecycle leaves out randomisation, drug accountability, SDV, eConsent and the patient portal.
  - The Spark is measured only when a site orders one.
- **Hardware:** an RTX PRO 6000 (96 GB) at the Japan head hospital and at CGMH. One RTX 5090 for small sites, using the measured sleep swap. DGX Spark is the medium tier.
- **Models:** the judge is Gemma 4 26B-A4B NVFP4 and the verifier is Qwen3.5-9B AWQ. Both must agree before a patient is excluded. Hermes has been removed.
- **Languages:** every user-facing word must be in ja, zh-TW or en. The Playwright walk fails on English-only cells on ja and zh-TW pages.

## How to work

- **One pull request per plan step.**
  - Open it as a draft, then subscribe to it.
  - Merge only when Changfu says "merge".
  - No model IDs in commits, PR titles or PR bodies.
- **Before each push:**
  - `make lint` is clean.
  - The suite passes, run in chunks: unit, console, testbench, integration.
  - `python tools/e2e_simple.py` passes. It is the only build gate.
  - Also run `public_e2e` and the walk where the step touches screens.
- **Back up local commits** with a git bundle in `/mnt/project-files/trialbox-build/git-backup/`. Container restarts have killed long agents before.
- **GCP** (project trialbox-demo):
  - Use the service-account key file in place, from `/mnt/project-files/uploads/hearth/`. Never print, copy or commit it.
  - Use a private `CLOUDSDK_CONFIG` and unset `CLOUDSDK_AUTH_ACCESS_TOKEN`.
  - The GPU VM is `tb-gpu-sim`: g4-standard-48 spot in asia-east1-a, about US$2.74/h. The CPU demo VM is `trialbox-demo` in asia-east1-b, about US$0.15/h.
  - Tell Changfu the cost before each GPU run. The plan's runs, under US$15 in total, are approved.
  - Stop every VM after use and verify it shows TERMINATED. Both are stopped as of 2026-11-08.
- **Secrets:**
  - Never copy OpenRouter keys he has posted in chat.
  - The demo password lives only in `/mnt/project-files/trialbox-demo/password.txt`. Never post it.

Start with plan step 1, the hardware profiles. Post a short checklist of steps 1–9, and report when each step's PR is up.
