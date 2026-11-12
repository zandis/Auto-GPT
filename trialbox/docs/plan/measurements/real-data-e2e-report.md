# Real public data, end to end: report (8 Nov 2026)

Branch `realdata-local` (local only, not pushed; backup bundle at `trialbox-build/git-backup/realdata-local.bundle`), 11 commits on top of `step5-local`.

## 1. The data, and what is real

`tools/public_site.py` builds one public-data hospital of **268 patients** from the open sources already in the project:

| Source | Patients | Language | Real |
| --- | --- | --- | --- |
| SIGIR 2016 patient descriptions | 53 | EN | note text, verbatim |
| MedTxt-CR case reports | 123 | JA | note text, verbatim |
| MedTxt-RR radiology reports | 92 | JA | note text, verbatim |

- **Derived only where the note states it:** age and sex (regex; NFKC for Japanese), and diagnoses through a small dictionary to ICD-10, skipping negated, family, suspected and literature mentions.
- **Placed, not sourced:** visit dates, appointments (every third patient), staff. No names, labs or medicines are invented.
- Each run writes `derivation.json` and `PROVENANCE.md` (copy: [real-e2e-PROVENANCE.md](real-e2e-PROVENANCE.md)).
- Two study profiles run against it: **PUB-ONC** (a trial: age ≥ 18, malignancy, ECOG from notes; excludes pregnancy, active TB, ILD from notes, other trial by a person) and **PUB-CA** (a cohort).

## 2. Results

**Browser walk (stub model): 422 / 422 pass.** 5 roles × ja / zh-TW / en × desktop / phone. Every page is checked for status, `html lang`, raw catalogue keys, `None`/`undefined`, and no sideways scroll on the phone, plus the forbidden pages for the CRA role and the PI and CRC actions.
- Full table (function | screen | role | language | result | screenshot): [real-data-e2e-results.md](real-data-e2e-results.md)
- 428 screenshots: `real-e2e-shots/`. The walk ran after fixes 1 and 2; the screenshots predate fix 3.

**In-process functions (stub): 94 / 94 pass in en, ja and zh-TW.** Stages covered:
- data in; S2 paste → S20 approval → feasibility, with Refresh;
- screening of PUB-ONC and the PUB-CA cohort;
- list, S5, all marks (approach, need info, not now, replace, withdraw), outcome, screening log and XLSX;
- N1/N2 mail, and REDCap S36/S21 with read-back;
- other screens and admin, 404;
- exports, CASE on a real MedTxt report, consent ICF upload, Cancel/Retry;
- audit chain verify.

**Same run with the real pair on the GPU: 94 / 94 pass** in 996.6 s. Screening PUB-ONC took 393.2 s. 281 model calls, 28 retries, 2 schema violations (both recovered), 2 judge/verifier disagreements sent to a person, 1 failure handled. Raw: `gpu-run-2026-11-08/public_e2e_real_pair.json`.

**Suite:** `make lint` clean (mypy 486 files, MCP snapshot OK). Results by chunk:
- console: 131 pass
- testbench: 44 pass
- integration: 41 + 34 pass
- unit: 366 + 214 + 314 pass, plus a 17-test re-run of the changed areas after the last commit

## 3. Bugs fixed (one commit each, each with a test)

| Commit | Bug | Fix |
| --- | --- | --- |
| 4bdf31b | An unknown URL showed raw JSON | The console's own 404 page, in the user's language |
| 8e44dc6 | An old S20 approval link gave an English 409 refusal | It opens the job's page |
| 52ca430 | Exclusion rows said "met" / 該当, which reads as eligible | "present: excludes" / "not present" in all three languages |
| fb9d65f | On the card, guided JSON made both models stop after `confidence` or pad whitespace up to max_tokens | Judge schema puts `reason` before `confidence`; both models now stop in 54–106 tokens, about 2 s per check |

## 4. Real models on the card (tb-gpu-sim, vLLM v0.32.0)

The serving record with sha256 hashes is in `eval/parity/serving_config_2026-11-08_tb-gpu-sim.json`. Hashes: judge `2ba339fa…`, verifier `561c3b56…`. The pair is served at 35,810 MiB.

**SIGIR filter-first, N-11 (patient-trial pairs lost out of 79; the gate is the most each language may lose):**

| Setup | EN (gate ≤ 5) | JA (gate ≤ 4) | zh-TW (gate ≤ 2) |
| --- | --- | --- | --- |
| **Gemma NVFP4 + Qwen AWQ pair** | **4 PASS** | **2 PASS** | **1 PASS** |
| Gemma QAT-AWQ + Qwen AWQ pair | 4 PASS | 2 PASS | not run |
| Qwen AWQ alone | 4 | 4 | 2 |
| Gemma NVFP4 alone | 11 | 7 | 10 |
| Gemma QAT-AWQ alone | 10 | 12 | not run |

The previous run, on 6 Nov, lost EN 4 and JA 3. TREC (N-12) was started and then stopped early to save cost, so N-12 is not measured.

**Pair optimisation: keep Gemma NVFP4 as the judge.** The QAT build gives the same pair numbers, is worse alone in Japanese (12 vs 7), and its block recall is slightly lower in the pair (EN 0.48 vs 0.52; JA 0.45 vs 0.48).

**Canary (54 cases, the box's judge prompt):**

| Model | Correct | Flips | Other |
| --- | --- | --- | --- |
| Gemma NVFP4 | 53 / 54 | 1 (ja pregnancy yes, pass → fail) | 2 truncation retries, 124 s |
| Gemma QAT-AWQ | 51 / 51 answered | 0 | 3 cases failed schema twice (ja t2dm no, ja ad no, zh-TW ad no: broken JSON); 1 retry, 464 s, about 4× slower |
| Qwen AWQ | 47 / 54 | 0 | 0 retries, 110 s |

Qwen's misses are mostly "silent" cases answered fail instead of unknown, plus ja chemo yes. That is safe in the pair, because the verifier only blocks, but it would matter if Qwen ran alone.

**32 GB fit and sleep mode** (`eval/parity/fit_2026-11-08_tb-gpu-sim.json`; total card memory in use):

| Case | Result |
| --- | --- |
| Judge alone, 0.30, 8k, 4 seqs | starts in 117 s, 32,519 MiB |
| Verifier alone, 0.30, 8k, 4 seqs | starts in 82 s, 30,035 MiB |
| Both at once, tight (0.20 / 0.093, 4k, 2 seqs) | **does not fit.** The judge starts (22,793 MiB); the verifier fails with 0.20 GiB KV cache against 0.23 needed (vLLM's maximum would be 3,168 tokens) |
| Sleep swap at 0.27 each | **works.** Judge awake 29,623 MiB, asleep 1,289. Second server starts at 0.27 while the first sleeps (28,402 awake). Both asleep 2,086. Sleep 0.4–3.7 s, wake 0.3–0.5 s |
| QAT judge + verifier (0.22 / 0.105, 8k) | QAT alone 22,239 MiB; pair 33,310 MiB, over 32 GB |

So on a 32 GB card the pair runs as a **sleep-mode swap** (one awake at a time, under 1 s to switch), not side by side. One caveat: the on-box smoke prompts in the fit script came back empty (the script's own request, not the servers). The SIGIR and canary runs show the QAT and pair servers answer correctly, but answers after a wake were not separately checked.

## 5. Cost and VM

- tb-gpu-sim (Spot, about US$2.74/h): running from **02:33:16Z** after two quick preemptions, stopped at **04:21:26Z**. That is 1 h 48 m, **about US$4.9** plus a few cents for the preempted starts. This is well under the US$18 cap.
- Startup-script metadata restored to `deploy/gcp/gpu-sim-startup.sh`.
- **Final state: TERMINATED**, verified with gcloud (lastStopTimestamp 2026-11-07T20:21:26-08:00).

## 6. Still open or untested

**Language and display problems the walk surfaced (not fixed):**
- About 23 hard-coded English refusal reasons appear on Japanese and Chinese pages.
- English evidence strings appear on Japanese pages ("no value in the window", "abstained", "human criterion").
- The banner says "synthetic data only (D0)" even on public data.
- S5 shows the practitioner as "Dr. A (synthetic)" instead of the CSV name.

**Data and logic limits:**
- The demo terminology has only 59 ICD codes, so "malignancy" misses C80.1 and C50.9. A site would load the full ICD-10-CM.
- Feasibility counts 23 while screening lists 65, because unknown age is kept for review. That is by design, but the screen should explain it.

**Not built or not measured:**
- Backup and restore are not built.
- TREC N-12 is not measured on the deployed files.
- zh-TW was not run with the QAT judge.
- The sleep-swap path is measured on the VM but not wired into the box: there is no orchestrator code yet to sleep and wake around a batch.
- `services/orchestrator/canary/judge_canary.jsonl` came from the other branch and is not committed here.
