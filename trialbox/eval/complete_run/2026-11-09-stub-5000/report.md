# TrialBox complete-platform run

Head `a69b51bbd3ec` (TB-PLAN-04 step 9: the walk is its own part, after the GPU stops). Model: stub. Hospital: 5,000 synthetic patients. Languages: ja, zh-TW. Host: x86_64, 4 CPUs.
Started 2026-11-09T05:32:45+00:00, finished 2026-11-09T05:52:21+00:00.

**PASSED**: 581 of 581 checks; 60 of 60 screenshots; 19.6 min in all.

Screenshots are in the run's `report/shots/` folder (not committed).

| part | stage | checks | result | seconds | screenshot |
| --- | --- | --- | --- | --- | --- |
| prepare | synthetic hospital | 2/2 | pass | 0.0 | `prepare.png` |
| install | install: tier and serving record | 3/3 | pass | 0.0 | `install.png` |
| hospital-ja | 0 data in | 4/4 | pass | 0.6 | `hospital-ja-00.png` |
| hospital-ja | 1 feasibility report | 8/8 | pass | 0.0 | `hospital-ja-01.png` |
| hospital-ja | 2 investigator approval | 2/2 | pass | 0.1 | `hospital-ja-02.png` |
| hospital-ja | 3 screening | 6/6 | pass | 0.0 | `hospital-ja-03.png` |
| hospital-ja | 4 list, marks and mail | 7/7 | pass | 0.9 | `hospital-ja-04.png` |
| hospital-ja | 5 ready and needs-information lists | 8/8 | pass | 0.8 | `hospital-ja-05.png` |
| hospital-ja | 7 REDCap read-back and screening log | 5/5 | pass | 0.1 | `hospital-ja-06.png` |
| hospital-ja | audit | 13/13 | pass | 0.9 | `hospital-ja-07.png` |
| hospital-ja | 8 REDCap write-back | 12/12 | pass | 0.7 | `hospital-ja-08.png` |
| hospital-ja | 9 data core: REDCap off then on, conflicts, a PI's sheet | 13/13 | pass | 0.2 | `hospital-ja-09.png` |
| hospital-ja | 10 built-in data capture | 15/15 | pass | 1.4 | `hospital-ja-10.png` |
| hospital-ja | 11 trial lifecycle | 25/25 | pass | 4.6 | `hospital-ja-11.png` |
| hospital-ja | 12 site set-up and data harmonization | 23/23 | pass | 21.0 | `hospital-ja-12.png` |
| hospital-ja | 13 Japan: SS-MIX2, JP Core and the licensed code lists | 16/16 | pass | 10.1 | `hospital-ja-13.png` |
| hospital-ja | re-run (FR-REP-02) | 3/3 | pass | 11.4 | `hospital-ja-14.png` |
| hospital-ja | runtime | 1/1 | pass | 0.0 | `hospital-ja-15.png` |
| hospital-zh-TW | 0 data in | 4/4 | pass | 0.6 | `hospital-zh-TW-00.png` |
| hospital-zh-TW | 1 feasibility report | 8/8 | pass | 0.0 | `hospital-zh-TW-01.png` |
| hospital-zh-TW | 2 investigator approval | 2/2 | pass | 0.1 | `hospital-zh-TW-02.png` |
| hospital-zh-TW | 3 screening | 6/6 | pass | 0.0 | `hospital-zh-TW-03.png` |
| hospital-zh-TW | 4 list, marks and mail | 7/7 | pass | 0.8 | `hospital-zh-TW-04.png` |
| hospital-zh-TW | 5 ready and needs-information lists | 8/8 | pass | 0.9 | `hospital-zh-TW-05.png` |
| hospital-zh-TW | 7 REDCap read-back and screening log | 5/5 | pass | 0.1 | `hospital-zh-TW-06.png` |
| hospital-zh-TW | audit | 13/13 | pass | 0.6 | `hospital-zh-TW-07.png` |
| hospital-zh-TW | 8 REDCap write-back | 12/12 | pass | 0.8 | `hospital-zh-TW-08.png` |
| hospital-zh-TW | 9 data core: REDCap off then on, conflicts, a PI's sheet | 13/13 | pass | 0.3 | `hospital-zh-TW-09.png` |
| hospital-zh-TW | 10 built-in data capture | 15/15 | pass | 1.5 | `hospital-zh-TW-10.png` |
| hospital-zh-TW | 11 trial lifecycle | 25/25 | pass | 4.6 | `hospital-zh-TW-11.png` |
| hospital-zh-TW | 12 site set-up and data harmonization | 23/23 | pass | 20.5 | `hospital-zh-TW-12.png` |
| hospital-zh-TW | 13 Japan: SS-MIX2, JP Core and the licensed code lists | 16/16 | pass | 10.1 | `hospital-zh-TW-13.png` |
| hospital-zh-TW | re-run (FR-REP-02) | 3/3 | pass | 11.1 | `hospital-zh-TW-14.png` |
| hospital-zh-TW | runtime | 1/1 | pass | 0.0 | `hospital-zh-TW-15.png` |
| public-ja | 0 public data in | 7/7 | pass | 0.4 | `public-ja-00.png` |
| public-ja | 1 criteria, approval and feasibility | 16/16 | pass | 7.1 | `public-ja-01.png` |
| public-ja | 2 screening (patient list) on real notes | 6/6 | pass | 4.3 | `public-ja-02.png` |
| public-ja | 3 list, S5 and marks | 13/13 | pass | 3.2 | `public-ja-03.png` |
| public-ja | 4 N1 / N2 mail | 3/3 | pass | 0.3 | `public-ja-04.png` |
| public-ja | 5 REDCap simulator read-back | 4/4 | pass | 0.8 | `public-ja-05.png` |
| public-ja | 5b trial lifecycle (D-134) | 7/7 | pass | 1.9 | `public-ja-06.png` |
| public-ja | 5c site set-up and data harmonization (D-135) | 6/6 | pass | 4.6 | `public-ja-07.png` |
| public-ja | 6 other screens | 38/38 | pass | 4.6 | `public-ja-08.png` |
| public-ja | 7 exports, CASE, consent explainer, Cancel / Retry | 11/11 | pass | 5.0 | `public-ja-09.png` |
| public-ja | 8 audit chain | 1/1 | pass | 0.0 | `public-ja-10.png` |
| public-zh-TW | 0 public data in | 7/7 | pass | 0.3 | `public-zh-TW-00.png` |
| public-zh-TW | 1 criteria, approval and feasibility | 16/16 | pass | 7.3 | `public-zh-TW-01.png` |
| public-zh-TW | 2 screening (patient list) on real notes | 6/6 | pass | 4.4 | `public-zh-TW-02.png` |
| public-zh-TW | 3 list, S5 and marks | 13/13 | pass | 3.0 | `public-zh-TW-03.png` |
| public-zh-TW | 4 N1 / N2 mail | 3/3 | pass | 0.4 | `public-zh-TW-04.png` |
| public-zh-TW | 5 REDCap simulator read-back | 4/4 | pass | 0.9 | `public-zh-TW-05.png` |
| public-zh-TW | 5b trial lifecycle (D-134) | 7/7 | pass | 2.0 | `public-zh-TW-06.png` |
| public-zh-TW | 5c site set-up and data harmonization (D-135) | 6/6 | pass | 4.4 | `public-zh-TW-07.png` |
| public-zh-TW | 6 other screens | 38/38 | pass | 4.3 | `public-zh-TW-08.png` |
| public-zh-TW | 7 exports, CASE, consent explainer, Cancel / Retry | 11/11 | pass | 5.3 | `public-zh-TW-09.png` |
| public-zh-TW | 8 audit chain | 1/1 | pass | 0.0 | `public-zh-TW-10.png` |
| walk | public console for the walk (public_e2e, stub) | 1/1 | pass | 35.9 |  |
| walk | walk (5 roles x 3 languages x desktop and phone) | 4/4 | pass | 384.3 | `walk/` |
| backup | backup, wipe and restore (tools.backup_drill) | 11/11 | pass | 111.9 | `backup.png` |
| update | signed update, two rollbacks (tools.update_drill) | 12/12 | pass | 246.7 | `update.png` |
| scale | cascade at 5000 patients (hospital_sim scale) | 2/2 | pass | 77.1 | `scale.png` |

## Part times

| part | wall seconds |
| --- | --- |
| prepare | 0.7 |
| install | 0.6 |
| hospital-ja | 112.8 |
| hospital-zh-TW | 111.6 |
| public-ja | 44.2 |
| public-zh-TW | 44.2 |
| walk | 421.5 |
| backup | 113.2 |
| update | 248.3 |
| scale | 78.3 |

## hospital-ja: screen

```json
{"funnel": [["S0", 3022], ["S1", 92], ["S3", 92], ["S4", 81]], "tiers": {"excluded": 2941, "high": 2, "review": 79}, "listed": 81, "judging": {"configured_note_block": "both_agree", "disagreements": 0, "failures": 0, "judge_model": "stub", "may_block": false, "mode": "single", "note_block": "never", "note_block_reason": "no verifier configured: a single model may not exclude", "verifier_model": null}}
```

## hospital-zh-TW: screen

```json
{"funnel": [["S0", 3022], ["S1", 92], ["S3", 92], ["S4", 81]], "tiers": {"excluded": 2941, "high": 2, "review": 79}, "listed": 81, "judging": {"configured_note_block": "both_agree", "disagreements": 0, "failures": 0, "judge_model": "stub", "may_block": false, "mode": "single", "note_block": "never", "note_block_reason": "no verifier configured: a single model may not exclude", "verifier_model": null}}
```

## public-ja: screen

```json
{"funnel": {"S0": 268, "S1": 90, "S3": 90, "S4": 90}, "tiers": {"excluded": 178, "high": 0, "review": 90}, "listed": 90, "judging": {"configured_note_block": "both_agree", "disagreements": 0, "failures": 0, "judge_model": "stub", "may_block": false, "mode": "single", "note_block": "never", "note_block_reason": "no verifier configured: a single model may not exclude", "verifier_model": null}, "request_seconds": {"PUB-ONC": 3.1, "PUB-CA": 1.0}, "stage_seconds": 4.2}
```

## public-zh-TW: screen

```json
{"funnel": {"S0": 268, "S1": 90, "S3": 90, "S4": 90}, "tiers": {"excluded": 178, "high": 0, "review": 90}, "listed": 90, "judging": {"configured_note_block": "both_agree", "disagreements": 0, "failures": 0, "judge_model": "stub", "may_block": false, "mode": "single", "note_block": "never", "note_block_reason": "no verifier configured: a single model may not exclude", "verifier_model": null}, "request_seconds": {"PUB-ONC": 3.2, "PUB-CA": 1.1}, "stage_seconds": 4.3}
```

## walk: walk

```json
{"checks": 780, "failed": 0, "summary": {"pages": 768, "axe_by_impact": {"minor": 84}, "targets": 21600, "targets_under_44": 0, "taps": {"T1": 2, "T2": 2, "T3": 2, "T4": 5, "T5": 5, "T6": 3, "T7": 2, "T8": 2, "T9": 3}, "taps_max": {"T1": 2, "T2": 2, "T3": 2, "T4": 10, "T5": 5, "T6": 3, "T7": 3, "T8": 2, "T9": 3}}}
```

## scale: scale

```json
{"patients": 5000, "generate_s": 2.0, "pipeline_s": 75.1, "ms_per_patient": 15.02, "peak_rss_mb": 1828, "model_calls": 127, "final_list": 5}
```
