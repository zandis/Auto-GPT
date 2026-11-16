# D-502 cost table v2: the product path only (lane G, 2026-11-15)

For the owner. Nothing was started; no VM, no paid call. This replaces `d502-cost-table.md` (VOID: it costed harness
runs that are not product evidence; none of its rows is reused here).

**D-502:** every data set, public or synthetic, is run end to end with the real models in en, ja and zh-TW. "Done"
means a paid run whose results are committed. **Product path only:** the box installed from a signed bundle on the
GPU VM by the real installer, driven by `deploy/gcp/box-run.sh` of PR #649 (`claude/lane-g-box-accuracy`).

**Where every figure comes from.** The driver's own `--estimate`, run today on #649 merged with master (train 17,
`8a7ad118`; #649 head `09c1896b3bb318a5f8f98921fb7866249c650138`); raw output in this folder: `t17-estimates.txt`, `t17-estimates-2.txt`. The demo VM:
`deploy/gcp/demo-vm.sh --estimate` (`t17-demo-estimate.txt`). Prices are the driver's constants: spot US$2.74 an hour,
on demand US$8.22 (`tools/complete_run.py`; the owner's figure, not checked against the billing page). All US$ below
are spot. "Known" = the steps that have a figure; "cap" = the cloud's hard stop for the launch (the VM is stopped
there). **"Not yet costed"** = nothing supports a figure; I do not guess one.

**What the rates are worth.** The accuracy rows use model-call rates lane G measured on 2026-11-13 on its own serving
setup, which the validation reset marked superseded. They are an order of magnitude, not a forecast. The installed
box's own rates are not known until its first run.

## 0. Headline

| | US$ |
| --- | --- |
| Limit | 150.00 |
| Spent so far by lane G (results folders, validation reset §0) | 58.92 (about 59) |
| **Left** | **91.08** |
| The approved launch list (section 3), known steps, **low** bounds | 35.35 |
| The approved launch list, known steps, **high** bounds | 77.14 |
| The approved launch list **at the caps** (the most it can cost) | **149.12** |
| Data paths, the synthetic hospital profiles, injection, MedTxt, G-8 on the box | **not yet costed** (no driver group) |

**Plainly: the approved list exceeds the limit.** At its caps it needs US$149.12 against US$91.08 left: **US$58.04
over**. At the known high bounds it fits (US$77.14, US$13.94 to spare), but those bounds leave out every step that
has never been measured (the install, the wizard, `qualify`, the update, the bundle export and upload), so they are
not a safe figure to plan on. The data paths and the rest of the D-502 matrix come on top and are not costed.

**What fits for sure (at the caps), in order:** the demo VM, the validation bundle build, the start with G-1 and the
canary, and the qualify launch: US$36.78, running total US$95.70 of US$150. Run A then fits only if it ends near its
high bound (US$49.87, total US$145.57) and not at its cap (US$65.76, total US$161.46). G-6/G-9/G-10 and R2 do not
fit after that. Section 4 gives two ways to make it fit; the owner chooses.

## 1. The D-502 matrix on the product path

"When": **today** / **after train 18** / **after train 19** / **lane G wiring** (what) / **another lane** (what).
Nothing that uses the GPU can run today: every paid launch needs a bundle, and the build stops at the release gates
until train 18 brings the dated vLLM entry (CVE-2026-128089). Every row that screens or compiles also needs train 19
(see section 2). Sizes are the driver's defaults (Run A of the public accuracy plan).

### 1.1 Public accuracy sets (#628), on a VALIDATION box: step group `acc`, `--only <set>`

The figures are the set alone; each `acc` launch also pays once for "tools, site settings, routes probe, fetch,
build, one ingest" (not measured, under the cap) and, if the box is installed in the same launch, the `start` group.

| Set (`--only`) | Data language | Console | What it measures | When | Known h (low-high) | US$ known (low-high) | Cap h / US$ |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `trec` TREC CT 2021+2022, 1,225 pairs | en (real notes) | en | eligible lost, wrong exclusions vs NIST | after train 19; #589 (train 18) for S2b | 1.47-8.51 | 4.03-23.32 | 12 / 32.88 |
| `trec2023` TREC CT 2023, 500 pairs | en (questionnaire patients) | en | same | same | 0.54-3.21 | 1.48-8.80 | 5 / 13.70 |
| `sigir` SIGIR physician labels, 1,015 criteria | en | en | criterion answer and deciding sentence | same | 0.19-1.03 | 0.52-2.82 | 2 / 5.48 |
| `tfda` Taiwan FDA zh-Hant vs CT.gov en, 100 x 2 | **zh-Hant** + en (protocols) | en | the compiler reads the same trial the same way | after train 19 (compile needs the pair routed) | 0.37-2.85 | 1.01-7.81 | 4 / 10.96 |
| `jrct` jRCT ja vs CT.gov en, 50 x 2 | **ja** + en (protocols) | en | same | same; owner's choice on jRCT bulk (PDL 1.0) | 0.18-0.87 | 0.49-2.38 | 2 / 5.48 |
| `chia` Chia, 100 trials | en (protocols) | en | compiler vs annotated entity kinds | same; A2 settles Chia's licence (`eval/DATASETS.yaml` states two) | 0.18-0.94 | 0.49-2.58 | 2 / 5.48 |
| `tcga` TCGA-Reports, 500 x 10 | en (real pathology, OCR noise) | en | criterion answers on real reports | after train 19 | 0.02-0.64 | 0.05-1.75 | 1 / 2.74 |
| `jmed` JMED-Personas, 300 x 2 | **ja** (synthetic text) | en | the family-history trap | after train 19 | 0.00-0.15 | 0.00-0.41 | 1 / 2.74 |
| **Run A, all eight** (`--steps acc`) | | | | | **2.95-18.20** | **8.08-49.87** | **24 / 65.76** |
| Run A with the install (`--steps start,acc`) | | | | | 3.29-18.54 | 9.01-50.80 | 28 / 76.72 |
| B size: `trec:3000` | en | en | same, larger | as `trec` | driver 3.60-20.84; plan 3.90-22.30 | driver 9.86-57.10 | 28 / 76.72 |
| B size: SIGIR all labels, 3,835 pairs | en | en | assessor 0/1/2 | **lane G wiring**: no `acc` set; the plan's figure only (6.57-36.07 h) | - | not costed by the driver | - |
| MedTxt-CR/RR as a site (148 CR reports + RR) | **ja** (real clinician text) | ja | chart facts, negation | **lane G wiring** (an `acc` set from `tools/public_site.py`'s MedTxt part); **lane A2**: criterion-level gold (only certainty tags exist) | - | not yet costed | - |
| BioScope clinical (negation) | en | - | - | **blocked**: the public file masks every clinical word | - | - | - |

Note on `trec:3000`: the driver scales a set's hours linearly by size; the plan counts the protocols a sample needs
(3,000 pairs need 2,133 protocols, not 3,000 x 803 / 1,225 = 1,967), so the plan's 3.90-22.30 h is the better figure.
A lane G fix (small), not done here.

### 1.2 Synthetic hospital profiles and their rulesets, on the installed box

The driver has **no** group that generates a profile, feeds it, ingests it and screens its studies, except `g6`
(one generated site, 50,000 patients, thin or dense, one study). The in-process runs of `tools/complete_run.py` are
not the product path and are not counted. Audit B: these notes are templates (about 20 filler sentences per language
and one fixed sentence per finding); they prove plumbing and capacity, **never accuracy**.

| Profile | Data language (notes) | Studies (rulesets) | What runs it | When | Estimate |
| --- | --- | --- | --- | --- | --- |
| `ci` (JP 2,500 + TW 2,500) | ja + 10 % en; zh-TW + 10 % en | GZQO, GOUT-COH (default list adds ONC-OSI, RA-BIO, RA-COH) | **lane G wiring**: a `hospital` group (`tools.synth_hospital --profile`, feed, ingest, SCREEN each study through the box's job API) | after train 19; studies on the box (1.4) | not yet costed |
| `ci-en` (2 x 2,500, D-743) | en (TW table layout, English identities) | as `ci` | same | same | not yet costed |
| `ci-ja`, `ci-zh-TW` | ja / zh-TW | as `ci` | same | demo only; low priority | not yet costed |
| `jp-ad` (2,500) | ja + en | AD-MAB, NEUR-COH, GZQO, RA-BIO | same | + #589 (train 18): AD-MAB's 4 note criteria have no lexicon term and are "not evaluated" without the embed service | not yet costed |
| `tw-ra` (1,500) | zh-TW + en | RA-JAK, GZQO, RA-COH, RA-BIO | same | + #589 (RA-JAK-EXC-06/07) | not yet costed |
| `full` (500,000) | ja, zh-TW | defaults | same | **another lane**: only once the incremental night exists (T-694, T-702, T-703) | not yet costed |
| dense (50,000, `tb_testkit.scale.densify`) | the generator's one site (`DEMO-A`) | `--study <RULESET>` | `g6` (`--steps g6`, `tb-g6-profile dense`) | after train 19 and a study on the box (1.4) | 5.0 h, US$13.70 (plan 32 G-20 "est."); cap 7 h, US$19.18 |
| The 8 committed rulesets compiled by the real model and diffed (AD-MAB, GOUT-COH, GZQO, NEUR-COH, ONC-OSI, RA-BIO, RA-COH, RA-JAK) | protocols: en, ja titles | - | **lane G wiring** (an `acc` compile-only set over `tests/fixtures/protocols`) | after train 19 | not yet costed |

All eight committed rulesets pin `judge_v4`; lane A2 repins them to v5 after the qualification record exists.

### 1.3 Site formats, the two public protocols, injection

`tools/scenarios.py` runs these on the in-process harness: not the product path. On the installed box each needs a
lane G step that drives the box's own adapter, and lane B2/E samples that are not TrialBox's own output read back
(audit B, rank 3).

| Item | Data language | Model reads it? | What runs it | When | Estimate |
| --- | --- | --- | --- | --- | --- |
| SS-MIX2 | ja + 10 % en | yes (notes) | **lane G wiring** | after train 19; **B2/E**: a real-shaped sample | not yet costed |
| FHIR TW Core | zh-TW + en | yes | same | same | not yet costed |
| FHIR JP Core | ja | yes | same | same | not yet costed |
| Excel (Shift_JIS JP, Big5 TW) | ja, zh-TW | yes (SCREEN) | same | same | not yet costed |
| REDCap (`rc_sim`) | - | no | same (plumbing) | same | not yet costed |
| Chart paste | ja, zh-TW (no en charts exist) | yes (`chart_facts`) | same | same | not yet costed |
| Chart files with OCR (Tesseract) | ja, zh-TW | yes | same | same; **B2**: real scan noise | not yet costed |
| IT dump (Shift_JIS, local codes) | ja | no | same (plumbing) | same | not yet costed |
| G-8: the two public protocols (NCT02629159, NCT03887455) | en | yes (compile) | **lane G wiring**: a compile-only `acc` set like `chia` | after train 19 | not costed by the driver. By the plan's own rule (one call a protocol low, + one a line high, 0.403 calls/s, 4.1 s a protocol): 13 s low; about 1 min high if each has about 10 lines (one was counted at 10 criteria) |
| Injection (`eval/injection/cases.yaml`: 23 bases, 34 plants, 70 cases) | en, ja, zh-TW | yes | **lane G wiring** (plant the cases in a synthetic site's notes and a protocol, screen and compile); **A2**: ~30 paraphrased plants per language | after train 19 | not yet costed |

### 1.4 Studies on the box, and the box itself

| Item | What runs it | When | Estimate |
| --- | --- | --- | --- |
| A study on a PRODUCTION box (for G-6, G-9, any hospital profile) | the approved **signed-update route**: a ruleset in a signed update bundle, approver "G-run approver (synthetic)" (r2-bundle-plan.md section 3) | **another lane (D)** builds the gaps; then lane G wiring (a study-pack step in the driver) | the bundle: part of a build launch (export time not measured) |
| A study on a VALIDATION box | `acc` already does FEAS + APPROVE by mail per protocol; `g6`/`g9` only check that the study is there | **lane G wiring**: let `g6`/`g9` use the same FEAS/APPROVE path, or the update route | - |
| Qualification (v5) | `start` step 08 `trialbox eval qualify` | after train 18 (#642 qualify without git) **and** train 19 (box inputs #648/D-737; a D0 route; record -> promote; n12 evidence from SCREEN) | inside the start's cap (never run on real weights: not measured) |

## 2. What "three languages" can honestly mean (audit B)

There are two languages in every run: the **console** (what the coordinator reads) and the **data** (what the model
reads). Paying to run the same notes under a second console language buys a screenshot, not a new data language.
The console languages are covered by the stub walk (6 roles x 3 languages) at US$0.

| Language | Real clinical text the model reads | Protocol text | Synthetic only | Gold |
| --- | --- | --- | --- | --- |
| **en** | yes: TREC notes, SIGIR, TCGA pathology | CT.gov, Chia | `ci-en` | NIST, physician labels, Chia annotations, TCGA project |
| **ja** | MedTxt-CR/RR (real clinician text, CC BY 4.0), not yet a box set | jRCT (50) | JMED-Personas (synthetic text), `ci`/`jp-ad` templates | JMED structured fields; MedTxt certainty tags only (criterion gold: A2) |
| **zh-TW** | **none.** No public zh-Hant clinical notes exist | Taiwan FDA (100, zh-Hant) | `ci`/`tw-ra` templates | TFDA compile agreement only |

So today D-502's "zh-TW end to end" can mean only: the compiler on real zh-Hant protocols (TFDA), and the screen on
templated synthetic notes (plumbing). An accuracy figure on zh-TW notes needs the clinician-rewritten hospital cases
the owner approved on 2026-11-15 (the integrator's route; lane G never touches source records). Until they arrive,
every zh-TW accuracy row is "not possible", whatever is paid.

## 3. The launches in order, with a running total

Order as the integrator gave it. "Posted estimate" is what lane G posts before the run (D-505), and the run stops if it
goes more than half over it: for a launch whose time is mostly unmeasured, the posted estimate is its cap (the cloud
stops the VM there, so it cannot go half over); for `acc` and `g6`, the known high bound (their caps are 1.3x and 1.4x
it, under 1.5x). Running totals start at US$58.92 spent.

| # | Launch (command) | When | Known US$ (low-high) | Cap h / US$ | Posted estimate | Running total at the cap |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Demo VM, 2026-11-17 (`deploy/gcp/demo-vm.sh up`, stub model, no GPU) | today (owner's IPv4 addresses, #613) | US$0.16 an hour up; at most 1.95 per `up` (12 h hard stop); disk 0.11 a day stopped | 2 `up`s = 3.90 | 3.90 | 62.82 |
| 2 | Validation bundle build (`box-run.sh --mode validation --steps build --release-id val-<commit12> --release-seq 1 --commit <sha> --no-wait`) | after train 18 | 1.79 | 2 / 5.48 | 5.48 | 68.30 |
| 3 | Start + G-1 + canary on a VALIDATION box (`--mode validation --steps start --release-id val-<commit12>`) | after train 18 | 0.93 | 4 / 10.96 | 10.96 | 79.26 |
| 4 | Qualify: a new validation build from the train-19 head, then `--steps start` again (08 qualify, promote) | after train 19 | 1.79 + 0.93 = 2.72 | 6 / 16.44 | 16.44 | 95.70 |
| 5 | Run A accuracy (`--mode validation --steps acc` on that box) | after train 19 + `validation-check` passes | 8.08-49.87 | 24 / 65.76 | 49.87 | 161.46 |
| 6 | Data paths (site formats, profiles, injection, MedTxt, G-8) | lane G wiring + B2/E samples | not yet costed | - | - | - |
| 7 | G-6, G-9, G-10 (`--steps g6,g9,g10 --study <RULESET> --g10-image <ref>`) | after a study is on the box (1.4) | 15.21 | 11 / 30.14 | 30.14 | 191.60 |
| 8 | R2: production bundle build + production start (`--steps build ...`, then `--steps start ...`) | after train 18 + the vendor key, release id and seq, the v5 record in the release (Q-3) | 1.79 + 0.93 = 2.72 | 6 / 16.44 | 16.44 | 208.04 |
| | **All approved launches** | | **35.35-77.14** | **149.12** | | **208.04 (US$58.04 over US$150)** |

Notes per launch:

- **3.** In VALIDATION (as in PRODUCTION) the pair routes only as champion, and it is still "candidate", so the start
  stops at 08 `qualify` (no D0 route). Whether 07 (the pair canary, `trialbox selftest`, through the gateway) is
  refused the same way is **not verified**; if it is, this launch yields the install, pinning, the serving record and
  G-1, and stops at 07. Either way it costs far less than its cap.
- **4.** It needs a bundle from the train-19 head (a box takes only a release built from a commit, D-633), so it pays
  a second build. Its record must reach the production release (lane Q, Q-3) before launch 8.
- **5.** Can share launch 4's VM start (`--steps start,acc`: cap 28 h / US$76.72) if the owner prefers one launch; it
  then saves one VM start (0.25 h, US$0.69) but a failed qualify ends the launch before any accuracy set.
- **7.** G-10 in validation mode needs a second bundle signed with the same throwaway key: not wired (lane G).
  In production mode it needs a second vendor-signed bundle (release seq N+1).
- **8.** Build 0.65 h known (b05-b07 not measured: `docker save` of about 12 GB, sign, upload); start 0.34 h known.

## 4. Two ways to stay inside US$150 (the owner chooses)

| Option | Drops or changes | Total at the caps | Inside? |
| --- | --- | --- | --- |
| A. Skip launch 3; its steps run in launch 4 anyway | launch 3 (US$10.96 cap) | 58.92 + 138.16 = 197.08 | no |
| B. A + Run A in two halves: `--only jmed,tcga,sigir,tfda,jrct,chia` now (driver: known 0.94-6.48 h, US$2.58-17.76; cap 9 h, US$24.66), TREC later | TREC 2021-23 moved to a later budget | 58.92 + 3.90 + 5.48 + 16.44 + 24.66 = **109.40**; then G-6/9/10 (30.14) = **139.54** | **yes**, with R2 left out (it would make 155.98) |
| C. B, but R2 instead of G-6/9/10 | G-6/G-9/G-10 to a later budget | 109.40 + 16.44 = **125.84** | **yes** |
| D. C plus TREC 2023 alone (`--only trec2023`, cap 5 h, US$13.70) | G-6/G-9/G-10 and TREC 2021+2022 later | 125.84 + 13.70 = **139.54** | **yes** |

The accuracy set that matters most for a wrong answer on real notes is TREC (en, real notes, NIST labels); B and C
move it later, D keeps its smaller half. Every option keeps the US$150 at the caps, so no run can push the total
over even if each launch runs to its cap.

## 5. Not known (and why)

- The installed box's model-call rates, install time, wizard time, `qualify` time, bundle export and upload time:
  never measured on the product path.
- The share of criteria that reach the judge after the structured filters (the screening high bound assumes all).
- Whether the canary routes before promotion (launch 3 note).
- How `qualify`'s n12 evidence is made from SCREEN before the pair is promoted: train 19's card; not verified here.
- The real spend so far beyond lane G's folders (the 2026-11-08 runs before lane G existed are not counted).
