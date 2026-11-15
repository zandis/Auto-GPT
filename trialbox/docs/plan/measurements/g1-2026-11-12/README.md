> **SUPERSEDED on 2026-11-14: not evidence of the shipped product.** See `SUPERSEDED.md` and [the validation reset plan](../validation-reset-2026-11-14.md).

# G1, 2026-11-12: the calls-in-flight curve, the chat-template check and the first full report

One RTX PRO 6000 spot VM (`tb-gpu-sim`, asia-east1-a, g4-standard-48, US$2.74 an hour), synthetic data only.
Code: branch `g1/rehearsed-2026-11-12b`, commit `931a0f79` (rehearsed). Run id: `20261112T165042Z-931a0f79`.
Results came back through the bucket (`TB_BUCKET`, `gs://trialbox-demo-runs`). The figures were read by
`deploy/gcp/results_report.py`. The reader was changed for this run (see "Reader change"). This README and
`DEFECTS.md` are written by hand, because they add the lane findings the reader cannot know.

## Attempts

| Attempt | Run | Outcome | VM time | Cost |
| --- | --- | --- | --- | --- |
| 1 | `20261112T152258Z-9c09e3fd` | Nothing was produced: the TLS door could not be reached through a TLS-inspecting proxy (bug A6). | not kept | about US$3.50 |
| 2 | `20261112T165042Z-931a0f79` | All nine parts ran. 919 of 925 checks passed, 90 of 90 screenshots, 62.9 minutes of part time. | 16:50 to 18:10 UTC, 1.33 h | about US$3.70 |

Total spent today: **about US$7.20**. Both VMs were checked TERMINATED after the run. No key was left in the VM metadata.
The cost of attempt 2 is 1.33 h at US$2.74, US$3.64; the plan's estimate was 2.33 h and US$6.38, the cap 4 h and
US$10.96. The report's verdict is FAILED: 6 checks failed (2 in `chat-template`, and 1 in stage 12 of each of the
four hospital parts).

## What ran

| part | status | checks | in flight | seconds |
| --- | --- | --- | --- | --- |
| `install` | passed | 4/4 | 1 | 0.3 |
| `prepare` | passed | 2/2 | 1 | 2.9 |
| `chat-template` (G-1) | FAILED | 3/5 | 1 | 5.9 |
| `hospital-ja@c1` | FAILED | 224/225 | 1 | 1,744 |
| `hospital-ja@c4` | FAILED | 224/225 | 4 | 757 |
| `hospital-ja@c16` | FAILED | 224/225 | 16 | 512 |
| `hospital-ja@c48` | FAILED | 224/225 | 48 | 485 |
| `scenario-emr-fhir` | passed | 11/11 | 1 | 263 |
| `scenario-gateway` | passed | 3/3 | 1 | 5.1 |

The hospital part is the Japanese main screen on 5,000 synthetic patients, run four times with the same data.

## G-1: the chat template is not the weights folder's own (FAILED)

- The template passed to the judge has sha256 `ae53464bf3be25802b3a5b37def7fd89667067d7577049b3b2d74c4d8de4c6d4`.
  The weights folder's own has `94899c0f917d93f6fe81c95744d1e8ddab2d21d39228d2e4aec1fb2a25bff413`.
- The passed template file gives token ids identical to the folder's own template on all 20 prompts; only the text
  hash differs. The failing check is the server's ids against the folder tokenizer's: 5 of the 20 prompts are listed
  (1, 3, 5, 7, 9), the first difference is at position 22, the server's prompt is one token longer. The part compared
  2,268 tokens in all.
- The judge server was started without `--chat-template` (`served_with_it` is false). On prompts with a system turn
  the server renders one extra token at the end of the system turn. So: the server's rendering differs from the
  reference tokenizer on system turns. It is not shown that the passed template is wrong. The template texts were not
  collected.
- Owner: lanes D and A (HW-005). Evidence: `parts/chat-template.json`, block `chat_template`.

## G-3: calls in flight, hospital-ja main screen (5,000 patients)

| in flight | calls/s | tokens/s | part wall s | p50 s | p95 s | GPU util mean % | listed (S4) | breaker opened |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 0.40 | 378 | 1,744 | 2.18 | 3.90 | 33 | 54 | never |
| 4 | 1.04 | 976 | 757 | 2.29 | 4.07 | 49 | 54 | never |
| 16 | 1.77 | 1,671 | 512 | 2.46 | 4.46 | 33 | 55 | never |
| 48 | 1.95 | 1,847 | 485 | 2.60 | 4.68 | 32 | 55 | never |

- **Read the figures with the audit below.** The calls/s above are whole-part numbers, diluted by the canary and
  stages 15 and 17. SCREEN-only rates are higher.
- **Wall time.** 16 in flight is 3.4 times faster than 1 (1,744 s to 512 s). 48 adds about 10 % over 16 (1.95 against
  1.77 calls/s). The servers' `max_num_seqs` is 16, so beyond 16 the gateway queues the calls. The estimate assumed a
  speedup of 2 for 4, 16 and 48. That was low (bug M3).
- **GPU memory.** Peak 62,592 MiB of 97,887 MiB, the same at every setting. That is 61.1 GiB of 95.6 GiB. (The handover
  note gave 62.6 GiB; the files say 62,592 MiB, which is 61.1 GiB.)
- **Canary.** 54 cases at every setting: 53 pair-correct, 0 decided wrong.
- **Breaker.** It never opened at any setting.
- **Model calls.** 628, 623, 626, 633 over the four settings. The report says no patient was excluded by one model
  alone (see audit item 8: that count is from the one-patient microbatch). Judge/verifier disagreements: 0, 0, 1 (at 16), 0.
- **Night window (whole-part figures).** For 50,000 patients, 5 studies and 8 hours at 70 % usable, with 0.125 calls per patient and study
  as measured, the window needs 1.55 calls/s. 16 and 48 in flight meet it (1.77 and 1.95). 4 does not (1.04). The
  reader picks the fastest setting whose candidate list matches the others; as the list differs (F1), it picked 4 and
  printed "below the window". Read this row with F1 in mind. It is an extrapolation: 50,000 patients were not run.

### F1: the listed candidates differ with the calls in flight (lane A)

Main screen, S4 and listed: 54, 54, 55, 55 at 1, 4, 16 and 48 in flight. The tiers differ too (high 3, 3, 4, 3;
review 51, 51, 51, 52). One judge/verifier disagreement was seen, at 16. The
canary was the same at every setting. But the list is not reproducible across settings. The report's line "Candidate
lists of hospital-ja at every setting: identical" is wrong (lane G bug M1: the report hashed a one-patient list of
another stage, not the screen's list). Evidence: `parts/hospital-ja@c*.json`, block `screen`.

### F2: stage 12 fails one check in all four hospital parts (lane E)

Stage "12 site set-up and data harmonization" is 22/23 at every setting. The failed check is:

> confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready

It returned 7 outcomes (ready, needs, not_eligible for six pseudonymous patient ids) where it expected another set.
The same check failed in the run of 2026-11-11. Evidence: `parts/hospital-ja@c1.json`, stage 12.

## Audit of these numbers (2026-11-12)

An independent audit recomputed the run from the raw files. It corrects the text above as follows.

1. **Throughput.** The reported calls/s (0.40, 1.04, 1.77, 1.95) is arithmetically right but diluted: each part's count
   includes the canary (108 calls, one at a time, about 205 s) and stages 15 and 17. SCREEN-only is roughly
   0.38 / 1.3 / 3.5 / 4.4 calls/s at 1 / 4 / 16 / 48 in flight (estimate from the same files; the sample count gives
   0.39 / 1.36 / 3.7 / 4.0). "Calls" are judge and verifier calls counted separately, not pairs. They match vLLM's
   request counters exactly (335+293, 336+287, 336+290, 336+297), and the tokens match too. About 98 % of the tokens/s
   at 4, 16 and 48 are cached prompt tokens; generation tokens/s is 47 / 122 / 207 / 230.
2. **GPU.** "Mean about 33 %" covers idle time and the canary. Busy samples after the canary: mean 36.9 / 80.8 / 68.5 /
   67.4 %, max 74 / 93 / 93 / 94 %; in bursts (2 or more calls running) about 81 to 86 %. No GPU headroom is shown (and
   nvidia-smi utilisation is not a headroom measure). Memory of 62,590 MiB is the weights plus the pre-allocated KV
   cache (62,576 MiB idle). KV cache use peaked at 7.1 % (judge) and 11.5 % (verifier).
3. **48 in flight.** Per server, running peaked at 16 and 13, 29 in all. vLLM's waiting was 0 at every setting. The cap
   is the gateway's 16 slots per endpoint (`services/gateway/load.py`, `SLOTS = 16`). The wait in the gateway is not
   measured, and p50 and p95 start after a slot is taken, so they exclude it. vLLM e2e means: judge 2.72 / 2.78 / 3.00 /
   3.16 s, verifier 2.24 / 2.37 / 2.55 / 2.71 s.
4. **Order.** The settings ran in the order 1, 4, 16, 48 (timestamps). The prefix-cache bias on calls/s is likely 3 % or
   less (judge cache hits 62.9 % at 1, then about 97.5 %).
5. **F1.** The per-patient main-screen list was not recorded, so which patient differs cannot be told. At 16 the extra
   one is high/ready and is the one disagreement; at 48 it is review/needs with no disagreement (they may be different
   patients). It is not a timeout: failures are 0. The gateway fixes the sampling (temperature 0, top_p 1, a fixed seed),
   yet outputs vary from run to run (the stage-12 chart reading returned different codes in each repeat).
6. **G-1.** Corrected above: the passed file is not shown to be wrong; the server's rendering of system turns differs.
7. **F2** is G1's bug B1, now seen at 5,000 patients, so it is not an effect of the 50,000-patient snapshot. After the
   confirmations, patient 10000005 should be not_eligible and 10000004 ready. Both stayed needs, because the model's
   chart reading returned the wrong LOINC for urate (2160-x or 2823-3, not 3084-1) and an undated malignancy at 16 and
   48 in flight. It is a model-output or expectation issue for lanes A and E. The check's detail is cut at 300
   characters.
8. **Report errors (lane G, fix in batch 1).** "Listed", "identical" and "Model exclusions: 0" come from the last
   captured SCREEN, the one-patient stage-17 microbatch. "Started" and "finished" both show the report rebuild time.
   "62.9 min" is the sum of the part times. "Languages: ja, zh-TW" is printed though no zh-TW part ran. All four stage-12
   FAILED bullets print under the c48 block. The gateway audit (`gw-audit`) was not collected, so there is no per-call
   recomputation and no PHI-refusal count. The "No patient was excluded by one model" statement above rests on the
   report's count and is therefore not shown by this run.
9. **What a reader may conclude.**
   - Calls and tokens agree exactly between the gateway and vLLM; nothing was lost; no breaker opened.
   - Throughput rises to roughly 4 calls/s in SCREEN; 16 to 48 gains about 1.2 times, because of the gateway's 16 slots.
   - vLLM never queued, the KV cache stayed at 12 % or less, the GPU was busy 81 to 94 % in bursts: no headroom is shown.
   - The candidate list is not proven independent of the calls in flight.
   - G-1: the server's rendering of system turns differs from the reference tokenizer; the passed file is not shown wrong.
10. **The next run must**
   - measure SCREEN-only windows (start and end per stage, canary excluded);
   - randomise the order, repeat 3 or more times, and restart the servers or reset the cache between settings;
   - record the gateway's slot wait;
   - persist the main-screen per-patient list and the per-call answers;
   - collect `gw-audit` and the template texts;
   - raise the 300-character detail limit;
   - give 48 a meaning beyond 16 gateway slots, or drop it.

`capacity_inputs.json` and the reader's window verdict use the whole-part figures. They are diluted in the same way
(the need per patient counts the canary calls too). Use them as a lower bound of the rate and an upper bound of the need.

## Reader change

The reader took the candidate list from the part's `candidates` block. In this run that block holds one patient
(`high`), the same at every setting, so the reader said "identical". It now reads the screen's `funnel`, `tiers` and
`listed` when the part has them, and compares those (`screen_candidates()` in `deploy/gcp/results_report.py`, test
`test_the_screen_decides_the_candidate_comparison_not_the_candidates_block`). The screen has counts, not patient ids, so
"listed only here" and "missing here" are not known. The reader's `README.md` and `DEFECTS.md` were not used as they
stand: the reader writes a generic list, and this folder adds the lane findings by hand.

## Lane G bugs (all: fix in lane G batch 1)

- **A6.** The TLS door cannot be reached through a TLS-inspecting proxy. Use `TB_BUCKET`. Attempt 1 lost US$3.50 to it.
- **A7.** There is no free GCP pre-flight. What it missed: firewall for ports 80 and 443, the Secret Manager API was
  off, the secret was missing, the deployer lacked `secretmanager.viewer` (`setup-gcp.sh` omits it), and the bucket and
  its grants.
- **A8.** An enabled door-secret version is left after the run.
- **M1.** The report's "candidate lists identical" line hashed a one-patient list of another stage.
- **M2.** The count of PHI-tripwire refusals is not reported. Not counted in this run: the collected files hold no
  gateway audit and no refusal counter.
- **M3.** The estimate assumed a speedup of 2 for 4, 16 and 48 in flight. Measured by part wall time against 1 in flight: 2.3 at 4, 3.4 at 16, 3.6 at 48.

## Sent to lane D

The embedder `e-embed-1` manifest: `manifest_sha256 = e131f3203849cd7ba89144fdefce52c950bd748c285c2235c1f5628ddcc6e895`.
It has 18 files and 2,295,165,682 bytes. It is BAAI/bge-m3 at `7b44caba5c06fd6f1ef1d2786261e636c38e4295` without the
three pickle files; the safetensors file equals `pytorch_model.bin`, tensor for tensor.

## Not measured in this run

50,000 patients; zh-TW; 8 and 32 in flight (plan G-3 in full); G-2; G-4 to G-11.

## Files

`DEFECTS.md` (defects for other lanes), `capacity_inputs.json` (the figures T-667, T-637 and T-734 read; made by the
reader), `report.md`, `report.json`, `plan.json`, `TB_HEAD.json`, `parts/*.json` and each part's `gpu.csv` and
`vllm.csv`. Not committed: screenshots, `src.tgz`, the raw `.prom` scrapes.
