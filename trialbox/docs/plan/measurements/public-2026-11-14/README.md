<!-- written by deploy/gcp/results_report.py: do not edit by hand, run the reader again -->

# Cloud run results: 20261114T061459Z-02858674

Synthetic and public data only. Public data read by this run: MedTxt-CR Japanese case reports (CC BY 4.0, Sociocom, NAIST; NTCIR-16 Real-MedNLP); TREC Clinical Trials 2021/2022 topics and qrels (NIST) and trial texts from ClinicalTrials.gov (the NCBI TrialGPT corpus); the public-data site's notes (tools/public_site.py): MedTxt-CR and MedTxt-RR (CC BY 4.0, Sociocom, NAIST) and the SIGIR 2016 patient descriptions (NCBI, public domain). Written from the collected results folder by `deploy/gcp/results_report.py`.

- **Run id**: `20261114T061459Z-02858674`
- **Commit**: `02858674236585c0b0a227e409ae7a34e3c5524c`
- **Card**: not in the folder
- **Hours**: 2.0 h (VM hours given with --vm-hours); estimate 1.92 h; cap 3 h
- **Cost**: US$5.48 at US$2.74 an hour; estimate US$5.26; cap US$8.22
- **Parts**: 2 passed, 2 failed, 0 pending, 0 missing, of 4 planned
- **Verdict**: **FAILED**

## Parts

| part | status | checks passed | in flight | seconds | note |
| --- | --- | --- | --- | --- | --- |
| `scenario-public-medtxt` | FAILED | 2/3 | 16 | 2806.7 | 1 failed check(s) |
| `public-ja` | PASSED | 130/130 | 16 | 600.1 | - |
| `public-zh-TW` | PASSED | 130/130 | 16 | 664.4 | - |
| `scenario-public-trec` | FAILED | 0/2 | 16 | 2709.7 | 2 failed check(s) |

A part with no result is PENDING (its VM still runs, or a half-written result is there) or MISSING. Neither counts as passed.

## G-1: chat template identity

- **Verdict: NOT PLANNED** (the plan has no chat-template part)

## G-3: throughput at each number of calls in flight

The plan has no hospital part: no curve.

## Defects

3 entry(ies) in `DEFECTS.md`.

Files: `capacity_inputs.json` (the figures T-667, T-637 and T-734 read), `DEFECTS.md`.
