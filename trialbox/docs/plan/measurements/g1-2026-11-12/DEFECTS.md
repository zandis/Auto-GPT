# Defects found by run 20261112T165042Z-931a0f79, for other lanes

Lane G changes no product code. Each entry gives the lane, the finding and the evidence file. Cause, Fix and Card are
for the lane that owns the entry. The full text of F1 and F2 is in `README.md`.

## For other lanes

| # | Lane | Finding | Evidence |
| --- | --- | --- | --- |
| 1 | D and A (HW-005) | G-1 failed. The text hash of the passed template (`ae53464b...`) differs from the weights folder's own (`94899c0f...`). The passed file gives the folder's token ids on all 20 prompts; the server's ids differ on 5 of 20 (first difference at position 22, one token longer, on prompts with a system turn). The judge server was started without `--chat-template`. Not shown: that the passed template is wrong. Template texts not collected. | `parts/chat-template.json`, block `chat_template` |
| 2 | A (F1) | The listed candidates of the main screen differ with the calls in flight: S4 and listed 54, 54, 55, 55 at 1, 4, 16, 48; tiers differ too; one judge/verifier disagreement at 16. Which patient differs was not recorded (no per-patient list); failures 0. The list is not proven independent of concurrency. | `parts/hospital-ja@c1.json`, `@c4`, `@c16`, `@c48`, block `screen` |
| 3 | E (F2) | Stage "12 site set-up and data harmonization" fails one check in all four hospital parts: "confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready". It failed in the 2026-11-11 run too (G1 bug B1, seen at 5,000 patients: the chart reading returned the wrong LOINC for urate and an undated malignancy at 16 and 48; patients 10000004 and 10000005 stayed needs). Model-output or expectation issue; the detail is cut at 300 characters. | `parts/hospital-ja@c1.json`, stage 12 (same in `@c4`, `@c16`, `@c48`) |

## Lane G (fix in lane G batch 1)

| # | Bug | Evidence |
| --- | --- | --- |
| A6 | The TLS door is unreachable through a TLS-inspecting proxy. Use `TB_BUCKET`. Attempt 1 (`20261112T152258Z-9c09e3fd`) cost about US$3.50 and produced nothing. | `README.md`, Attempts |
| A7 | No free GCP pre-flight. Missed: firewall for 80 and 443, Secret Manager API off, secret missing, deployer without `secretmanager.viewer` (`setup-gcp.sh` omits it), bucket and its grants. | `deploy/gcp/setup-gcp.sh` |
| A8 | An enabled door-secret version is left after the run. | `shard-1/door-version` in the collected folder (not committed) |
| M1 | The report's line "Candidate lists ... identical" is wrong: it hashed a one-patient list from another stage. The reader now reads the screen (changed in this branch, with a test). | `report.md` line 185; `parts/hospital-ja@c16.json`, blocks `candidates` and `screen` |
| M2 | The count of PHI-tripwire refusals is not reported. Not counted in this run: the collected files hold no gateway audit and no refusal counter. | none |
| R1 | Report errors: "listed", "identical" and "Model exclusions: 0" come from the one-patient stage-17 microbatch; started and finished both show the rebuild time; "62.9 min" is the sum of part times; "Languages: ja, zh-TW" though no zh-TW part ran; the four stage-12 FAILED bullets all print under c48. | `report.md` |
| R2 | `gw-audit` and the template texts were not collected: no per-call recomputation, no PHI-refusal count. | collected folder |
| R3 | The calls/s are whole-part figures, diluted by the canary and stages 15 and 17. No SCREEN-only window is recorded. | `README.md`, audit item 1 |
| M3 | The estimate assumed a speedup of 2 for 4, 16 and 48 in flight. Part wall time against 1 in flight: 2.3, 3.4, 3.6. | `plan.json` (`llm_speedup`), `README.md` G-3 table |

The next run's requirements are in `README.md`, "Audit of these numbers", item 10.

## Not defects, but open

- Not measured: 50,000 patients, zh-TW, 8 and 32 in flight, G-2, G-4 to G-11.
- The night-window verdict is an extrapolation from 5,000 patients, and depends on the setting chosen while F1 is open.
