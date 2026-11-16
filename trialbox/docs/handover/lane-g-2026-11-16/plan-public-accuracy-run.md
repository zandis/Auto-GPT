# Public accuracy run: the first real-model run on the installed box (plan, 2026-11-14)

For the owner. Lane G. Branch `claude/lane-g-public-accuracy` (not pushed), head `347f3b27824920a8ce0eafb1e92f317c148bb064`.
Code: `trialbox/tools/public_accuracy/` (fetchers, item builder, scorer, plumbing proof, this estimate).
Every number below is derived from the data or from a named measurement. "Not known" means nothing supports a figure.

## 1. The run in one table

Recommended first run = rows marked **A**. Rows marked B are the larger versions the catalogue named; they cost
several times more, mostly because each TREC/SIGIR trial is a separate protocol to compile and approve.

| Run | Set | Sample | Lang | Patients | Protocols to compile | Answers scored | Model calls: compile (low-high) | Model calls: screening (high) | Hours (low-high) | Gold |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **A** | TREC CT 2021+2022 | 1,225 pairs, balanced | en | 125 | 803 | 1,225 pairs (645 eligible, 580 excluded) | 803 - 8,833 | 24,500 | 1.47 - 8.51 | NIST label per pair |
| B | TREC CT 2021+2022 | 3,000 pairs, balanced | en | 125 | 2,133 | 3,000 pairs (1,494 / 1,506) | 2,133 - 23,463 | 60,000 | 3.90 - 22.30 | same |
| **A** | TREC CT 2023 | 500 pairs, balanced | en | 37 | 297 | 500 pairs (240 / 260) | 297 - 3,267 | 10,000 | 0.54 - 3.21 | NIST label; questionnaire patients |
| **A** | SIGIR, physician criterion labels | all 1,015 criteria | en | 53 | 103 | 1,015 criteria (+105 pairs) | 103 - 1,133 | 2,100 | 0.19 - 1.03 | physician label + evidence sentence ids |
| B | SIGIR 2016, all labels | 3,835 pairs (421 / 681 / 2,733) | en | 58 | 3,593 | 3,835 pairs | 3,593 - 39,523 | 76,700 | 6.57 - 36.07 | assessor 0/1/2, "would consider" apart |
| **A** | Taiwan FDA + its CT.gov record | 100 trials x 2 languages | zh-Hant, en | 0 | 200 | 100 compile pairs | 200 - 3,800 | 0 | 0.37 - 2.85 | same trial twice: count, class, age agree |
| **A** | jRCT + its CT.gov record | 50 trials x 2 languages | ja, en | 0 | 100 | 50 compile pairs | 100 - 1,100 | 0 | 0.18 - 0.87 | as TFDA |
| **A** | Chia | 100 trials | en | 0 | 100 | ~1,240 lines | 100 - 1,200 | 0 | 0.18 - 0.94 | annotated entity kinds per line |
| **A** | TCGA-Reports | 500 reports x 10 cancer types | en | 500 | 10 | 5,000 criterion answers | 10 - 20 | 10,000 | 0.02 - 0.64 | TCGA project of the case (GDC) |
| **A** | JMED-Personas | 300 patients x 2 criteria | ja | 300 | 2 | 600 criterion answers | 2 - 6 | 2,400 | 0.00 - 0.15 | structured fields; family-history-only stratum |
| - | BioScope clinical (negation) | - | en | - | - | - | - | - | - | **blocked**: the public file masks every clinical word |
| | **Run A in all** | | | 1,015 | 1,615 | | 1,615 - 19,359 | 49,000 | **3.3 - 18.5 h** with VM start and canary | |
| | **Run A, US$** at US$2.74/h spot | | | | | | | | **US$9 - US$51** | |
| | Run A + B rows instead of their A rows | | | | | | | | 12.3 - 68.4 h, US$34 - US$187 | |

How the hours are derived (`python -m tools.public_accuracy estimate --box-s-per-protocol 4.1`):

- **Compile calls, low** = one `ir_extract` call per protocol: what the stand-in run served (19, 30, 16, 12, 6, 10, 2
  calls for 19, 30, 16, 12, 6, 10, 2 protocols). **High** = that plus one `concept_map` call per eligibility line (the
  G-8 estimator's rule in `tools/g_probes.py`). Lines per protocol are counted on the data: median 10 (SIGIR corpus,
  3,588 trials, used for all English trials), 26 (TFDA zh-Hant, 4,564 trials), 11 (Chia).
- **Screening calls, high** = judge and verifier on every line of every scored pair (2 x lines x pairs). The real
  number is lower (the structured filters exclude first; the judge stops at the first verified block; the verifier
  is asked only on would-be blocks and strong candidates), but how much lower is **not known** (section 3).
- **Rates**: compile calls one at a time at 0.403 calls/s; screening at 4.502 calls/s (16 in flight). Both are lane
  G's measurements of 2026-11-13 (run `20261113T044219Z-2b9eec74`, 5,000-patient hospital, `tools/complete_run.py`
  `HOSPITAL_MEASURED`). They are **superseded** and **predate the shipped serving setup** (lane G's own vLLM start,
  without the shipped chat template, in-process box). Use them as an order of magnitude only.
- **Box time per protocol outside the models**: 4.1 s, measured on the in-process box of the stand-in dry run on this
  machine (SIGIR: 124.1 s for 30 protocols; TREC 69.0 s / 19; TCGA 48.5 s / 10). The installed box's figure is
  **not known**.
- **Fixed**: VM start 0.25 h and the pair canary 300 s (`tools/complete_run.py` constants); US$2.74 an hour spot.

## 2. What the run proves, and what it does not

It proves, on the shipped box with the shipped pair: wrong exclusions and eligible patients lost on real
(English) patient notes against assessor and physician labels (TREC, SIGIR); the criterion-level answer with the
deciding sentence (SIGIR evidence ids); real pathology text (TCGA, OCR noise); the family-history trap in Japanese
(JMED, synthetic text); and whether the compiler reads the same trial the same way in zh-Hant, Japanese and
English (TFDA, jRCT) and agrees with annotators on structurable lines (Chia).

It does not prove: anything on real Taiwanese chart text (none is public); negation on clinical text (BioScope is
blocked); calibration of the 0.5/0.75 floors beyond what these answers allow; the S2b semantic stage before #589.

## 3. Known, and not known

Known (measured or counted today):

- The whole path runs end to end on the stand-in models through the product: hospital CSV ingest, protocol mailed
  as `FEAS <ruleset>`, compiled by the criteria compiler through a PRODUCTION gateway (as `criteria-compiler`),
  behind model-guard, review mail, approval by replying with the review workbook, `SCREEN` scoped by the study's own
  site profile, answers joined to the gold by ids only afterwards. Dry runs (stand-in, **not accuracy**): TREC 40
  pairs / 19 protocols, SIGIR 30 pairs / 30 protocols / 167 criterion labels, TFDA 8 trials x 2 languages, jRCT 6 x 2,
  Chia 6, TCGA 20 reports x 10, JMED 18 patients x 2.
- The cost driver is compiling protocols, not screening: TREC 2021/2022 trials are judged for one patient each in
  89 % of cases (14,809 of 16,574), so 3,000 pairs need 2,133 protocols; full SIGIR needs 3,593.
- The stand-in compiler makes 85-100 % of lines `human` criteria, so the stand-in run sent **0** calls to the judge.
  The stand-in run therefore cannot measure how many criteria reach the judge after the structured filters.

Not known (and why):

- **The share of criteria that reach the judge.** The only real-model compile on record (G-8, NCT02629159,
  2026-11-14, superseded, before B14) made 8 of 10 criteria note or mixed. One protocol is not a measurement. The
  first hour of the real run measures it; the estimate's high bound assumes every line.
- **The installed box's rates and per-protocol time**: no run on the installed box exists yet.
- **Whether compile jobs run in parallel on the installed box**: the estimate takes one at a time (upper bound).

## 4. Blockers (stated, not worked around)

1. **#589 not merged.** Until it is, a note criterion with no lexicon term is "not evaluated" and never reaches the
   judge (`services/matching/cascade/engine.py`, NEW-LLM-2). Running before #589 measures a screening path that asks
   the models less than it will. Owner ruling 2 says #589 merges first. Owner: lane A2.
2. **`qualify` cannot run on an installed box yet.** Until a qualification record exists, PRODUCTION serves the
   baseline prompts (`judge@4`, `ir_extract@2`; the dry run's gateway audit shows `ir_extract@2` served), not the v5
   set the owner ruled ships. Owner: lane D (the job API and the box-install driver), then Stage 0.
3. **An approved study cannot be put on a PRODUCTION box unattended (D-640).** The run approves 1,615 protocols
   (Run A) by a scripted reviewer reply; on PRODUCTION every approval must name the site's delegated investigator.
   The accuracy run therefore needs a box that is **not PRODUCTION**: `TB_ENV=VALIDATION` (serves the newest
   registered prompts, i.e. v5, before qualification; approvals still name an approver, here the run's synthetic
   reviewer) or `TB_ENV=TEST` (examples allowed). Every result must print the mode. **The owner decides** which mode
   counts as evidence; lane D says whether the installer can install that mode and lane A2 whether D-640 allows a
   named synthetic approver on a VALIDATION box.
4. **Site settings for the run**: the box's daily limits stop the run otherwise (found in the dry run): FEAS 20 a
   sender a day (`rate_limit_per_sender_per_day`) and 200 mails a recipient a day (`TB_MAIL_PER_RECIPIENT_PER_DAY`).
   The run sets both off in the box's settings (`rate_limits_per_day: {FEAS: 0, SCREEN: 0}`, the env value 0).
5. **The driver.** `deploy/gcp/box-run.sh` (PR #614, `claude/lane-g-batch8`) has step groups build, start, g6, g9,
   g10 and no accuracy group. One must be added (lane G): ship `site/` and `protocols/` (built here, never the gold)
   to the VM, mail each protocol, approve, screen, collect `answers.json`; score on the operator's machine. Its cap
   would be set from the high bound above (x 1.3, as the complete run's cap rule).
6. **jRCT 50 records**: PDL 1.0 allows single records; "comprehensive collection" needs the helpdesk's written
   permission. 50 fetched one by one is the catalogue's suggestion; the owner may prefer to ask first.

## 5. Defects found by the dry run (for other lanes)

| What | Where | Effect | Lane |
| --- | --- | --- | --- |
| The FEAS report PDF crashes when reportlab splits a long paragraph across pages (`with_fallback(None)`: `'NoneType' object has no attribute 'isascii'`) | `services/orchestrator/reports/common.py:124,154` | FEAS ends "failed in reporting" for long protocols (5 of 49 in the TREC and SIGIR dry runs) | B or E (reports) |
| The gateway's PHI tripwire refuses `ir_extract` on public protocols: a sponsor compound code (`RO7507062`) hits PASSPORT; a zh-Hant protocol hits NAME | `services/gateway/core.py:513-518`, `services/guard` | the protocol cannot be compiled (2 of 16 TFDA/CT.gov texts; 3 of 12 in an earlier run) | A (guard), D (gateway) |
| An English UTF-8 `note.csv` with few non-ASCII characters is quarantined ("character set cannot be told for certain") and every note is lost | adapter CSV source, `libs/tb_common/encoding.py` | a whole site's notes silently missing from the lake; ingest "failed" | E |
| SCREEN refuses a ruleset with no structured criterion | `services/orchestrator/scenarios/screen.py` | a note-only protocol cannot be screened at all; worth a deliberate rule | A |
| The public site's MedTxt count: the downloaded MedTxt-CR training file holds **148** reports (unique ids), not the 100 the download page states; "JP1553" is an id prefix inside MedTxt-CR (51 reports), not a separate set | `.cache/medtxt` | the repo's 148 is right for the file it reads | A2 (doc) |
| `eval/DATASETS.yaml` gives Chia two licences (`criteria_extract_public`: "licence unconfirmed, loader disabled"; `chia`: CC BY 4.0). figshare's API says CC BY 4.0. Not changed here: `eval/` is lane A's | `eval/DATASETS.yaml` | contradiction stays | A2 |

## 6. Sizes fetched for this build (all in `.cache/public_accuracy`, gitignored)

About 95 MB kept; the two NCBI TREC corpora (137 MB and 138 MB) are streamed and checked against their pins, never
kept. Per file sha256 pins are in `tools/public_accuracy/sources.py`.
