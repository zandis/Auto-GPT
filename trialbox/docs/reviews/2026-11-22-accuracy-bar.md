# The accuracy bar: what comparable systems measured, and the standard proposed for TrialBox (2026-11-22)

**Reader:** the owner first (section 1). Then the integrator and the lanes.

**What this is.** A review of published systems that match patients to clinical trials or pre-screen them for
eligibility, and from it a proposed accuracy standard: what is measured, on what, and what number is good enough
for rc1 (a supervised demonstration), for the first hospital pilot, and for release. It follows the owner's rulings
of 2026-11-22 (inbox #639) and the plan 10 review (`docs/reviews/2026-11-22-plan-10-review.md`, pull request #1327,
sections 2.1 and 4.2). It changes no code, test or decision record. It is a proposal until the owner rules.

**How a claim is marked.** The literature was read by five workers, each with its own brief; I read their reports,
not the papers again. **[FT]** a worker read the number in the paper's full text. **[AB]** in the abstract only.
**[SN]** in a search snippet or a secondary report only. **[calc]** computed here (exact binomial, Clopper–Pearson).
**[repo]** read in this repository. **[bench]** measured on the bench host and reported on #639, not re-measured.
**[opinion]** this page's judgement. Legal points are "what the text says", not advice. Section 7 lists what was
not found, not opened and not verified. No model was run for this page and nothing was paid for.

---

## 1. For the owner: the proposed standard and the three numbers

**The finding in four lines.**

1. **People are the reference line, and people miss about one eligible patient in ten.** Where manual pre-screening
   was measured against an expert, it found 88 % to 90 % of eligible patients. Two qualified readers judging the
   same criterion agree with a kappa of about 0.5 to 0.8.
2. **No comparable system is trusted to remove patients on what it reads in notes.** Published tools exclude by
   themselves on coded fields only (age, sex, a lab value). On notes they rank or flag, and a person decides. The
   owner's ruling of 2026-11-22 is the same position.
3. **No regulator and no professional body sets a number.** The texts ask for "fit for purpose", validation in
   proportion to risk, figures with confidence intervals, and a person able to check the basis of each answer.
4. **A patient-level limit cannot be proved on the public sets.** Their labels are too noisy (one assessor per
   pair, no agreement figure published). A patient-level number needs labels made by clinicians on the site's own
   patients. Before that, the honest measure is per criterion.

**The standard, in one sentence.** Measure how often a note answer wrongly removes a patient (per criterion, on
physician labels), how much the box decides at all, and, where real labels exist, how many eligible patients are
missing from the list; count "sent to review" as not missed, and print the review load beside every figure.

**The three numbers.**

| Stage | The number | Measured on | What it means in plain words |
| --- | --- | --- | --- |
| **rc1** (supervised demonstration; synthetic and public data) | **False-block rate per criterion at most 1.0 %** (at most 10 wrong removals in the 982 cells physicians left open; 95 % upper bound 1.7 %) | The physician-labelled public criterion set (`eval/criterion_ml`), English first | As good as the published reference system on the same set (1.4 %). **No patient-level claim.** |
| **Pilot** (the site's past studies, then shadow) | **At least 95 % of known eligible patients are on the list, shown to be at least 90 %** (for example at most 4 missed of 100) | Patients the site enrolled or an investigator judged eligible; then the shadow run beside the coordinator | Shown to be no worse than a trained human screener (88 to 90 %), aiming at the 95 % that other fields accept from a machine that screens for a person |
| **Release** | **At most 5 % of eligible patients missing, as the 95 % upper bound, per language** (at most 2 missed of 124, from at least 12 protocols) | Real patients, labels by two clinicians and an adjudicator | Better than any human baseline found in the literature. This is the limit already ruled (decisions 17 and 91); this page keeps it and moves it to where it can be proved |

**Three choices are yours** (section 5.6 has the reasoning):

1. **The reference line for the pilot.** "No worse than a trained human screener" (shown at least 90 %, aim 95 %),
   or the 5 % upper bound already at the pilot. *Recommended: the first.* The 5 % bound needs about 124 eligible
   patients with real labels; one site's past studies may not hold that many.
2. **Who labels.** Every set that gates is labelled by two clinically trained readers and a third who settles
   disagreements, with their agreement printed. *Recommended: yes.* It costs reading time: about 326 sentences per
   language now (you could read the Traditional Chinese set yourself; the Japanese set needs a Japanese reader),
   and about 1,000 criterion cells at the site.
3. **Run-to-run variation.** A note answer may remove a patient only when a second, separate run gives the same
   answer; otherwise the patient goes to review. Every gated figure is the worst of three runs.
   *Recommended: yes.* The second run is needed only for the few answers that would remove.

**What is not verified** is in section 7. The two that matter most: the product's own figure on its real path has
never been run (decision D-918), so nobody knows yet whether rc1's number is met; and the Japanese and Traditional
Chinese notes of the criterion set are machine translations that no clinician has checked.

---

## 2. The comparable systems

"Level" is what one measured unit is: **C** one criterion for one patient; **P-T** one patient against one trial;
**Pt** one patient for one trial's list; **R** a ranked list. "Excludes?" says whether the system removes a patient
by itself. Sens = sensitivity (recall of eligible), Spec = specificity, PPV = precision. Full references are in
section 8.

### 2.1 Rule-based and classic language processing (2005 to 2022)

| System, year | Kind | Level | Data and labels | Setting | Results | Excludes? | Source |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Clinical trial alert, 2005 | Rule in the record system, prompt to the physician | Referrals, enrolment | 114 physicians, 12 months before, 4 after | In use | Referrals 5.7 to 59.5 a month; enrolment 2.9 to 6.0 a month (rate ratio 2.06, 1.22 to 3.46). No accuracy figure | No, prompts | Embi 2005 [AB] |
| ACCORD e-screening, 2009 | Database query on coded data | Pt | 193 screened; investigator review | Prospective | Sens 100 % (45 to 100), Spec 84 %, PPV 13 %, negative predictive value 100 % (98 to 100) | Yes, on coded data | Thadani 2009 [AB] |
| Cancer-centre matching software, 2010 | Rules on billing, pathology, lab | Pt | 5 studies, 282 to 2,112 patients each | In use | Share of flagged patients truly eligible 17 % to 74 %. Sensitivity not measured. Thresholds set "for highest sensitivity" by staff and investigators | No, flags | Penberthy 2010 [FT] |
| Routine-data report beside manual recruitment, 2013 | Database query | Pt | 510 patients in one week | Prospective, parallel | Found 14 % more patients; showed 7 % of manual inclusions wrong. **Manual recruitment: Sens 88 %, Spec 87 %** | No, report | Köpcke 2013 [AB] |
| Automated pre-screening, children's emergency department, 2015 | Coded filter, then language processing and ranking | P-T, R | 13 trials; 3,061 pairs (75 eligible) labelled by 2 physicians, agreement 96.8 % | Retrospective | Workload down 92 %; **90 % recall when the top 22 % is read** ("missing only 10 %") | Coded fields only; rest ranked | Ni 2015 JAMIA [FT] |
| Same, children's oncology, 2015 | Same | P-T | 55 trials, 215 patients; 169 past enrolments | Retrospective | Workload down 85 %; PPV 12.6 %; recall 100 % by construction (the cut-off was set to catch all past enrolments) | Coded fields only | Ni 2015 BMC [FT] |
| Same, real time, 2019 | Same, live | Workflow | 46,612 visits, 7 coordinators, 12 months | **In routine use** | Screening time down 34 %; enrolled up 11.1 %. No sensitivity measured in use | Coded fields only | Ni 2019 [FT] |
| Criteria parser to cohort query (Criteria2Query), 2019 | Criteria text to database query | Criterion text | 177 criteria; 2 experts | Retrospective | Entity recognition F1 0.80; concept mapping accuracy 0.51. No patient-level accuracy against chart review found | Not applicable | Yuan 2019 [FT] |
| n2c2 cohort selection shared task, 2018 | 47 teams; best was rule-based | C | 288 patients, 13 criteria; 2 annotators, **mean kappa 0.54** (−0.1 to 0.73) | Benchmark | Best micro-F1 0.91 | Not applicable | Stubbs 2019 [FT] |
| IBM Watson for Clinical Trial Matching, community cancer centre, 2020 | Vendor language processing | Attribute, P-T | 239 patients, 4 breast trials; vendor co-authors | Retrospective | Eligibility agreement 81 % to 96 %; **Sens 91 % to 95 % on three trials and 46.7 % on the fourth**; manual 110 minutes against 24 with the system | "Reliably excluded ineligible patients" | Beck 2020 [AB] |
| Same, lung, Australia, 2020 | Same | P-T | 102 patients, 10 trials; 2 clinicians, kappa 0.70 to 1.00; labels built from hand-entered attributes, not the chart; vendor-funded | Retrospective | Accuracy 91.6 %, Sens 83.3 %, PPV 76.5 %. **34 of 799 "Exclude" calls were wrong (4.3 %)** | **Yes** | Alexander 2020 [FT] |
| Same, breast, 2021 | Same | P-T, four coarse filters only | 318 patients, 4 trials; nurse abstractors | Retrospective | Accuracy 87.6 %, Sens 81.1 %, Spec 89 %. Two coordinators re-screening 38 cases: kappa 0.60 and 0.77 against the reference | Yes | Haddad 2021 [FT] |
| Vendor language processing, 3 oncology trials, 2020 | Vendor (Mendel) | Pt | One community centre; vendor authors | Retrospective | 24 % to 50 % more eligible patients than standard practice; none found by standard practice was missed | Not found | Calaprice-Whitty 2020 [AB] |
| Pooled review of AI for cancer trial enrolment, 2023 | 10 articles, 19 datasets | Mixed | Over 50,000 patients | Review | Pooled Sens 90.5 % (70.9 to 97.4), Spec 99.3 % (81.8 to 99.9); PPV over 80 % in only 5 of 17 datasets | Mixed | Chow 2023 [AB] |

Two systems often named beside these do **not** measure matching accuracy. **Trial Pathfinder** (Nature 2021)
emulates trials on record data to show how each criterion changes the eligible pool and the survival result:
loosening criteria about doubled the pool [FT]. **TrialTranslator** (Nature Medicine 2025) emulates landmark trials
to test whether their results hold for real-world patients [AB]. Both are about the design of criteria.

### 2.2 The shared sets and their labels

| Set, year | Unit | Size | Who labelled | Agreement between labellers | Best published result | Source |
| --- | --- | --- | --- | --- | --- | --- |
| SIGIR 2016 patient-trial collection | P-T | 60 patients, 4,000 judged pairs | 4 medical assessors, **one per pair** | 70 % on the one patient all four judged | Ranking baselines only | Koopman and Zuccon 2016 [FT] |
| n2c2 2018 track 1 | C | 288 patients, 13 criteria | 2 annotators, adjudicated | Mean kappa 0.54 | Micro-F1 0.91 (2018); 0.93 with a language model, macro-F1 0.81 (2024) | Stubbs 2019; Wornow 2025 [FT] |
| TREC Clinical Trials 2021, 2022, 2023 | P-T | 75, 50 and 40 patients; about 35,000 judged pairs a year | Physician graduate students, indexers, other experts; one per pair as far as stated | **None published** | NDCG@10 0.61, P@10 0.51 (2022) | Roberts 2022 [FT]; 2021 and 2023 overviews not found |
| TrialGPT criterion-level annotations, 2024 | C | 1,015 cells, 53 patients of the SIGIR set, 105 pairs | **3 physicians**, two-of-three | No kappa; each physician against the consensus 88.7 % to 90.0 % | The reference system 87.3 % | Jin 2024 [FT] |
| PRISM set (one US cancer centre), 2024 | C, R | 720 questions, 50 patients, real records; not public | 5 doctors | **64 %** across five; 70 % for the best two | A commercial model 68 %; doctors 70 % | Gupta 2024 [FT] |

The 1,015-cell set is the one in `eval/criterion_ml`. It comes from the SIGIR patients, not from TREC [FT]. The
1,700-pair set of the plan 10 review is TREC 2021 and 2022: one assessor per pair and no agreement figure. The
repository's own check of 30 dropped "eligible" pairs found 12 wrong labels (`eval/trec_ct/AUDIT.md`) [repo].

### 2.3 Language-model systems (2023 to November 2026)

| System, year | Kind | Level | Data and labels | Setting | Results | Excludes? | Source |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **TrialGPT**, 2024 (US National Library of Medicine) | Commercial model; criterion answers, then ranking | C, R | 183 public synthetic patients; 1,015 cells by 3 physicians | Retrospective | **Criterion accuracy 87.3 %** (inclusion 89.9 %, exclusion 85.9 %) against the physicians' own 88.7 % to 90.0 %; NDCG@10 0.73. "42.6 % less screening time" came from 2 physicians, 6 trials and 6 vignettes | No, ranks | Jin 2024 [FT] |
| TrialGPT adapted on a local open model, 2026 | Local model, one trial | Pt | 149 patients; 2 of 3 reviewers and the investigator | Retrospective | Sens 81.8 % (52 to 95), Spec 97.8 %. **Manual screener on 55 patients: Sens 36.4 %** (about 11 eligible) | No | Syed 2026 [FT] |
| TrialGPT 2.0, 2026 (preprint) | Commercial model | P-T, R | 900 pairs, 5 sites; 27 prospective tumour-board cases | Retrospective and prospective | Tool alone 89.0 % against clinicians 94.2 % (labels include the clinicians' own); time per patient down 55 % | No | Fang 2026 [FT] |
| **RECTIFIER**, 2024 (Mass General Brigham) | Commercial model with retrieval | C, Pt | 1,894 test patients, 13 criteria; **one** blinded expert clinician | Retrospective | Patient level **Sens 92.3 %, Spec 93.9 %; study staff 90.1 % and 83.6 %**. Per criterion 97.9 % to 100 % (staff 91.7 % to 100 %). Five repeated runs agreed 99.2 % to 100 %. Intervals not found | No, final review by staff | Unlu 2024 [AB; repeat runs FT of the preprint] |
| Same, **randomised trial**, 2025 | Same | Workflow | 4,476 patients, one heart-failure trial | **Prospective, randomised** | Eligibility determined 20.4 % against 12.7 %; enrolled 35 against 19 (P = .04). Among completed screens the eligible share was the same (20.8 % against 21.1 %): the gain is throughput | Staff review after the screen | Unlu 2025 [FT] |
| Coordinators with and without an AI system, 2026 (vendor-funded) | Vendor system | Chart items | 355 patients; two abstractions and an adjudicator | Randomised, on past charts | **Coordinators alone 71.5 % of chart items right**; with AI 76.1 %; AI alone 59.9 %. No time saved. Over-reliance seen on one item | No | Parikh 2026 [FT] |
| MSK-MATCH, 2025 (preprint) | Commercial model, several agents | Pt | 731 patients, 6 breast trials | Retrospective | With human review: Sens 98.4 %, Spec 98.7 %. AI alone: Sens 62.8 %, Spec 98.3 % | **Yes**: "ineligible" with 3 or more failing criteria is not reviewed (62 % of cases); the developers chose the cut-off | Rosenthal 2025 [FT] |
| PRISM / OncoLLM, 2024 (vendor) | Fine-tuned and commercial models | C, R | 720 questions, real records | Retrospective | 63 % to 68 % against doctors' 70 % | No | Gupta 2024 [FT] |
| Zero-shot on n2c2, 2025 | Commercial model | C | 86 test patients | Benchmark | Micro-F1 0.93, macro-F1 0.81 | Not applicable | Wornow 2025 [FT] |
| Real-world sites, 2025 (vendor) | Commercial models | C | 485 patients, 36 trials, 30 sites; labels are the sites' confirmations | Retrospective | 87 % per criterion (inclusion 93 %, exclusion 86 %) | Unclear | Callies 2025 [AB, FT] |
| Tumour-board registrations, Germany, 2025 | Commercial model | Pt | 124 registrations, 6 protocols; 4 clinicians | Retrospective | Sens 0 % to 100 % by trial; Spec 83 % to 96 %. Consultants near 100 %; junior doctors 0 % to 100 % | No; "not suitable alone" | Krückel 2025 [FT] |
| Intensive care, France, 2026 | Local open models | C, Pt | 1,342 stays; 6 clinicians | Retrospective | Criterion Sens 0.89, Spec 0.81; 72 % of flagged patients right. Unflagged patients were not reviewed, so misses are unknown | Flags | Korvin 2026 [AB, FT] |
| Liver cancer, China, 2024 | Vendor system, "Consider" or "Exclude" | Pt | 1,053 patients, 2 trials; oncologists, kappa 0.65 to 0.88 | Retrospective | **Sens 51.9 % and 83.5 %**, Spec 99 % | **Yes**, "reliability of exclusion was prioritized" | Wang 2024 [FT] |
| University hospital, Japan, 2025 and 2026 (conference papers) | Local open model after an extraction step | C, Pt | Real records, one endometrial cancer trial; 348 patients, 6 eligible | Retrospective | Criterion recall 0.21 on raw notes, 0.48 after extraction. At a threshold that keeps **all 6**, 68 of 348 go to review: 174 hours to 34 | No, ranks | Shibata 2025, 2026 [FT; the Japanese text did not render for the worker] |

**The names starting with "Trial".** Covered: TrialGPT, its local adaptation and TrialGPT 2.0 (above); Trial-LLAMA
(fine-tuned open models reach "parity" with a commercial one; no numbers in the abstract [AB]); TrialMatchAI
(Nat Commun 2026; a relevant trial in the top 20 for 48 of 52 real patients [AB]); Trial Pathfinder and
TrialTranslator (not matching accuracy, section 2.1); Trial2Vec (similarity between trials) and TrialMind (literature
screening), neither a patient screener; TrialTriage (a rules proof of concept on 90 synthetic cases [AB]). For
TrialX and Trialjectory no published evaluation was found. The one the owner most likely meant is **TrialGPT**: its
physician labels are already this repository's criterion set.

---

## 3. The human reference line

**How many eligible patients does manual pre-screening find?**

| Figure | Where | Source |
| --- | --- | --- |
| Sens 88 %, Spec 87 % | Manual recruitment, one trial, against a routine-data report | Köpcke 2013 [AB] |
| Sens 90.1 %, Spec 83.6 % | Trained study staff, heart failure, against one expert clinician | Unlu 2024 [AB] |
| Sens 36.4 % | One coordinator, about 11 eligible patients; "tended to exclude borderline cases" | Syed 2026 [FT] |
| 67 % to 81 % | Standard practice against standard practice plus a vendor's system (derived by the worker from "+24 % to +50 %") | Calaprice-Whitty 2020 [AB] |
| 71.5 % of chart items right | Coordinators abstracting eligibility items alone | Parikh 2026 [FT] |
| 86.6 % (80.6 to 91.2); two screeners 97.5 % | The nearest other field: one person screening abstracts for a systematic review | Gartlehner 2020 [SN] |
| "The truth is, we must miss some" | Interviews, 25 cancer-trial professionals, France; no rate measured | La Rosa 2024 [FT] |

**How well do two people agree on eligibility?**

| Figure | Where | Source |
| --- | --- | --- |
| Mean kappa 0.54 (−0.1 to 0.73 by criterion) | 2 annotators, 13 criteria, 288 patients | Stubbs 2019 [FT] |
| 64 % across five doctors; 70 % for the best two | Criterion questions on real cancer records | Gupta 2024 [FT] |
| Kappa 0.60 and 0.77; Fleiss 0.64 | Breast coordinators against a nurse reference | Haddad 2021 [FT] |
| Kappa 0.70 to 1.00 | Two clinicians, lung trials, from entered attributes | Alexander 2020 [FT] |
| Kappa 0.65 to 0.88 | Oncologists, liver cancer, China | Wang 2024 [FT] |
| 88.7 % to 90.0 % against the consensus | Three physicians on the 1,015 cells of this repository's criterion set | Jin 2024 [FT] |
| 96.8 % | Two emergency physicians, where only 2.45 % of pairs were eligible | Ni 2015 [FT] |

**Reading** [opinion]. (a) A trained person screening alone finds roughly **nine in ten** eligible patients; the
range is wide and the studies are few. No large audit of manual misses in a clinic was found. (b) Raw agreement
looks high when almost everyone is ineligible; on the cases that need judgement, kappa of 0.5 to 0.8 is the honest
figure. (c) So a label made by one person is wrong or arguable on something like 10 % of criterion cells. **A
measured error rate under a few per cent is below what single-label sets can resolve**; this is why the plan 10
review's "14 to 17 % against 5 %" could not be settled on the public set, and why every gate below asks for two
labellers and an adjudicator. (d) Manual screening takes 0.7 to 0.9 hours per evaluation and 6 to 9 hours per
enrolled patient (Penberthy 2012 [FT]); measured savings with tools run from 34 % (in use) to 80 % (retrospective).

---

## 4. The operating point others chose, and why

**Exclude, or rank and flag?**

- **Coded fields: systems exclude.** Age, sex, language, a lab threshold. The emergency-department system, the
  ACCORD query and the cancer-centre software all removed patients on structured data alone [FT, AB].
- **Notes: systems rank or flag, and a person decides.** TrialGPT ranks. RECTIFIER's authors recommend final review
  by a clinician, and in the randomised trial staff reviewed after the screen. The German and the US head-and-neck
  studies say the model is not suitable alone [FT, AB].
- **The exceptions show the cost.** The cognitive-computing matcher issued "Exclude": 4.3 % of those calls were
  wrong, and sensitivity was 83 %, or 47 % on one trial [FT, AB]. The Chinese liver system "prioritized the
  reliability of exclusion" and found 52 % of the eligible on one trial [FT]. MSK-MATCH finalises "ineligible"
  without review at three failing criteria; alone it finds 63 %, with human review 98 % [FT].
- Language models lean toward **false negatives** in several studies (sensitivity 22 % to 63 % alone at about 98 %
  specificity) [FT]. A design that protects recall recurs: review of the predicted negatives, or of near matches.

**What miss rate was accepted, and by whom?**

- The only stated figures were set by the **study authors**: 90 % recall at the top 22 % of the list (Ni 2015
  [FT]); a cut-off with sensitivity at least 0.98 "where the eligible population is small" (Cai 2021 [SN]); a
  threshold that keeps recall at 1.0 (Shibata 2026 [FT]); "highest sensitivity at the sacrifice of specificity",
  set by staff and investigators (Penberthy 2010 [FT]).
- **No paper was found in which a regulator, an ethics committee or a sponsor set a number**, and none says who
  formally accepted a miss rate.
- **Two neighbouring fields.** Screening papers for systematic reviews by machine uses **95 % recall** by
  convention ("work saved at 95 % recall", Cohen 2006 [SN]); ranking is called safe, automatic removal "promising,
  but not yet fully proven" (O'Mara-Eves 2015 [SN]). In US legal discovery the judges' guide says the rules give
  no required recall, that 80 % "is not a benchmark", and that such review "is not designed to identify all"
  documents (Federal Judicial Center 2017 [FT]). In both, exhaustive human review does not reach 100 % either.

**What the regulators' texts say** (each read in the issuer's text unless marked; none is advice).

- **No text found, in the US, the EU, Japan or Taiwan, names recruitment or eligibility pre-screening software and
  says whether it is a medical device.** Every reading is by analogy.
- **US.** The device definition leaves out software "for administrative support of a health care facility",
  naming "information about patient populations" and "population health management"; research and recruitment are
  not named (FD&C Act s.520(o)(1)(A)). The Clinical Decision Support guidance (version of 29 January 2026) has no
  trial example and no accuracy threshold. It expects the professional to be able to "independently review the
  basis", names automation bias as a risk, and asks the labelling to describe validation results and missing
  inputs. The January 2025 draft on AI for drug decisions asks for performance "with confidence intervals"; its
  scope neither includes nor leaves out recruitment.
- **EU.** MDCG 2019-11 rev.1 (June 2025): hospital information systems and "simple search" are not devices; a
  search by language processing that "contributes to achieving a medical purpose" is not simple search; a device
  acts "for the benefit of individual patients". The AI Act's list of high-risk uses does not name clinical
  research [secondary copy]. GDPR Article 22 bites only on decisions "based solely on automated processing"
  [secondary copy].
- **Japan.** The health ministry's guideline on programs as devices (2021, revised 2023-03-31) lists programs for
  in-hospital administrative support (院内業務支援) among those that are not devices; its case database (September
  2026) has no entry on trial candidates. The GCP ordinance, Article 44, puts the selection of subjects on the
  investigator (治験責任医師等): a person.
- **Taiwan.** The regulator's software guide (2022): hospital administrative software is not a device "unless it
  can replace clinicians' diagnosis or treatment decisions" (除非這類軟體可取代醫事人員的診斷治療決定).
- **Good clinical practice.** ICH E6(R3) (January 2025): computerised systems "should be fit for purpose (e.g.,
  through risk-based validation)"; validation shows "completeness, accuracy and reliability"; the protocol names
  the "mechanism for pre-screening"; the monitor verifies that only eligible participants are enrolled. No number.

**What follows for TrialBox** [opinion]. The eligibility decision that matters in law and in safety is made later,
by the investigator, at formal screening. A pre-screening error has one harm that nobody downstream can repair: an
eligible patient who never appears on any list. So the standard below bounds **silent removal** tightly, treats
"sent to review" as safe but counted, and keeps the basis of every answer checkable (the quoted sentence).

---

## 5. The proposed TrialBox standard

### 5.1 Words

- A **cell** is one criterion for one patient, answered from notes.
- The **reference label** of a cell is a clinician's: it either **blocks** ("not included", "excluded") or **does
  not block** ("included", "not excluded", "not enough information", "not applicable").
- The **product's answer** to a cell is one of: **remove** (the patient leaves that trial's list), **review** (a
  person is asked), **pass**. After the ruling of 2026-11-22 a note answer removes only on an exclusion whose quote
  states the condition (D-985); an inclusion "not met" from notes is a review.
- A **pair** is one patient against one trial. A pair is **listed** when the patient is a candidate or is under
  review for that trial, and **missing** otherwise.
- The **product path** is D-918's: the set screened as a site, through the installed box, scored by ids.

### 5.2 The metrics

Each is reported per language, with its counts, a 95 % one-sided exact (Clopper–Pearson) bound, the gold kind
(D-1326) and the number of labellers. Nothing is pooled across languages or gold kinds.

| # | Name | Formula | Gate or report |
| --- | --- | --- | --- |
| M1 | **False-block rate per criterion** | cells the product removes whose reference does not block ÷ all cells whose reference does not block | **Gate** at every stage. Also split into inclusion and exclusion criteria |
| M2 | **Decided share** | cells answered pass or remove ÷ all cells | Reported at rc1; a floor from the pilot on (the ruled 25 % of note cells on the frozen Japanese set stays) |
| M3 | **Wrong-pass rate** | cells the product passes whose reference blocks ÷ all cells whose reference blocks | Reported. It costs the coordinator time; it loses no patient |
| M4 | **Missing eligible** (1 − recall) | eligible pairs that are missing ÷ all eligible pairs, on the product path | **Gate** at the pilot and at release, on real labels only. Reported, never gated, on public sets |
| M5 | **Review load** | listed pairs ÷ all pairs screened; and listed pairs per eligible pair found | Reported beside M4 always. A figure for M4 without M5 is not quoted |
| M6 | **Evidence** | removals whose quote is word for word in the record ÷ removals (must be 1 by construction); and, in a clinician's sample, removals whose quote states the condition ÷ removals sampled | The first is a test. The second is reported |
| M7 | **Run-to-run flips** | cells (and pairs) whose side, remove or not (missing or not), differs between two complete runs ÷ all cells (pairs) | Section 6 |

Why M1 leads [calc, repo]. A trial in the public set has about 11 criteria. If each note answer wrongly removes
with probability p, a pair with k such criteria is lost with probability 1 − (1 − p)^k:

| p per criterion | k = 4 | k = 7 | k = 11 | k = 20 |
| ---: | ---: | ---: | ---: | ---: |
| 0.2 % | 0.8 % | 1.4 % | 2.2 % | 3.9 % |
| 0.5 % | 2.0 % | 3.4 % | 5.4 % | 9.5 % |
| 1.0 % | 3.9 % | 6.8 % | 10.5 % | 18.2 % |
| 2.0 % | 7.8 % | 13.2 % | 19.9 % | 33.2 % |

The plan 10 review measured 1.97 % and 17.4 %, as this arithmetic predicts. Under the ruling only exclusions can
remove from notes: about two thirds of criteria in the criterion set (659 of 1,015), so k is near 7 for an
average trial. **A 5 % patient-level limit therefore needs about 0.5 % per criterion; 1 % gives about 7 %.**

### 5.3 The evaluation sets

**What exists** [repo].

| Set | What it is | Labels | Good for | Not good for |
| --- | --- | --- | --- | --- |
| `eval/criterion_ml` | 1,015 cells, 53 public patients; notes in English, with Japanese, Traditional Chinese and code-mixed translations | 3 physicians, two-of-three (English). **The translations are machine-made and not clinician-checked** | **M1**: 982 cells do not block | M3: only 33 cells block (10 excluded, 23 not included), so even zero errors leaves an upper bound of 8.7 % [calc]. No patient-level figure: 79 eligible pairs |
| `eval/trec_ct` | 1,700 public pairs (1,200 eligible) | One assessor per pair; no agreement published; the repository's audit found 12 wrong labels in 30 | Trend between versions; M5; the product-path run of D-918 with a label check | **Any gate.** No rule should be chosen on it either |
| `eval/medtxt` | 215 real Japanese case and radiology reports with clinician-made English | Annotators' certainty tags | M1 in real Japanese, on single findings | Whole criteria; patients |
| `eval/accuracy` | Synthetic notes in three languages, from a seed | Generated truth | Regression between versions; planted cases | Any claim about real notes |

**What must be built**, in order of need.

| # | Set | Size and why [calc] | Who labels | Needed for |
| --- | --- | --- | --- | --- |
| B1 | The Japanese and Traditional Chinese notes of the criterion set, read by a clinician | 326 sentences per language, each checked against the English | One clinician per language who reads both; a second reads a sample of 60 | rc1 in those languages. Until then their figures are printed as "translated, not checked" and gate nothing |
| B2 | The label check of the product-path run | 100 pairs: every missing "eligible" pair, up to 100 at random | A person who reads clinical English, **not a model** (the existing audit was not a clinician's) | rc1: the D-918 figure with its labels checked |
| B3 | A blocking-rich criterion set | At least 300 cells whose reference blocks, per language: a wrong-pass rate near 50 % is then known to ±6 points | Two readers and an adjudicator; kappa printed | M3 and the decided share from the pilot on. Can be drawn from public notes |
| B4 | The site's retrospective set | Eligible pairs from past studies: **100 gives "at least 90 %" with up to 4 missed; 124 gives the 5 % bound with up to 2 missed.** Plus 1,000 cells that do not block, for M1 | The enrolment record or an investigator for pairs; two site readers and an adjudicator for cells | The pilot. Counts only leave the site |
| B5 | The shadow record | Every patient the coordinator found and every patient the box listed, for 1 to 3 studies over 8 to 12 weeks (F11) | The coordinator's own screening; the investigator on disagreements | The pilot's second step |
| B6 | The release set | At least 124 eligible pairs from at least 12 protocols per language; 1,500 cells that do not block | Two clinicians and an adjudicator | Release |

Counts for the bounds [calc]: of 982 cells, 10 wrong gives an upper bound of 1.72 % and 12 gives 1.97 %; of 1,000,
4 wrong gives 0.91 %; of 1,500, 2 wrong gives 0.42 %. For recall, 96 of 100 has a lower bound of 91.1 %, 95 of 100
has 89.8 % (just short), 118 of 124 has 90.7 %, 59 of 60 has 92.3 %, 57 of 60 has 87.6 %; 2 missed of 124 has an
upper bound of 4.99 %.

**Rules for every set that gates** [opinion, from section 3].

- Two labellers work apart; a third settles disagreements; kappa and raw agreement are printed with the result.
- The figure is given twice: on all adjudicated cells, and on the cells where the two labellers agreed at first.
- The set, the rule and the thresholds are fixed before the run. A rule tuned on a set is not scored on it.
- An answer the product failed to give counts as a review, and the share of such answers is printed. (Today's
  benchmark scorer lets silence count as "nobody lost": finding R22-04 of the plan 10 review.)
- Enrolled patients are the easy eligible ones (plan 10, F11). A retrospective figure says so.

### 5.4 The thresholds

**rc1: a supervised demonstration on synthetic and public data.**

| Metric | Threshold | Reasoning |
| --- | --- | --- |
| M1, English, `eval/criterion_ml`, product path | **At most 10 wrong removals of 982 (1.0 %; upper bound 1.7 %)**, worst of three runs | The published reference system scores 1.4 % (upper bound 2.2 %) on these cells [repo]; the three physicians differ from their own consensus on 10 % to 11 % of labels [FT]. Finer than about 1 % is below what the labels resolve |
| M1, Japanese and Traditional Chinese | The same count, **once B1 is done**; before that, printed and not a gate | The translations are unchecked [repo] |
| M1, real Japanese (`eval/medtxt`) | No worse than the stored control (the standing gate, D-1325) | Already ruled |
| M4 and M5 on the product path, `eval/trec_ct` | **Run once and printed, with B2's label check. No threshold** | D-918 has never been run; the labels cannot carry a limit (section 2.2) |
| M2, M3, M6, M7 | Printed | First measurement |
| The rule itself | A note answer never removes silently: a test, not a rate | The ruling of 2026-11-22; the operating point of every comparable system (section 4) |

*What rc1 may claim:* "On notes the box removes a patient only on an exclusion both models state with a quoted
sentence, and sends every other doubt to a person; on a public set labelled by three physicians its wrong-removal
rate per criterion is X % (at most Y %); it has no measured figure for missed patients yet."

**The pilot: retrospective first, then shadow, at the site.**

| Step | Metric | Threshold | Reasoning |
| --- | --- | --- | --- |
| Retrospective (B4) | M4 | **Recall at least 95 %, lower bound at least 90 %** (at most 4 missing of 100; at most 6 of 124) | The lower bound is the human line: manual screening found 88 % to 90 % (Köpcke, RECTIFIER's staff). 95 % is the convention where a machine screens for a person, and about what two human screeners reach together (97.5 %). It is F11's figure, kept |
| Retrospective (B4) | M1 | **At most 4 wrong removals in 1,000 cells (0.4 %; upper bound 0.9 %)**, Japanese | Section 5.2: about 0.5 % per criterion is what a 5 % patient-level limit needs |
| Retrospective | M2, M5 | Decided share at least 25 % of note cells; review load printed and accepted in writing by the site's coordinator | The ruled floor. No source gives a number for review load; over-flagging is the norm (precision above 80 % in 5 of 17 datasets) and overload makes people stop using a list (La Rosa 2024) |
| Shadow (B5) | M4 against the coordinator | **At least 95 % of the patients the coordinator found are listed, lower bound 90 %**; every miss traced to its cause | F11, kept |
| Shadow (B5) | Patients only the box found | Counted and confirmed by the investigator | The gain that others measured: +14 % (Köpcke 2013), eligibility determined for 20.4 % against 12.7 % (Unlu 2025) |
| Shadow | M7 | Section 6 | |

*What the pilot may claim:* "At this hospital, on N patients from its own past studies, the box listed X % of the
patients known to be eligible (at least Y % with 95 % confidence), which is no worse than manual pre-screening in
the published studies; a person still decides."

**Release.**

| Metric | Threshold | Reasoning |
| --- | --- | --- |
| M4, per language | **Upper bound at most 5 %**: at most 2 missing of at least 124 eligible pairs from at least 12 protocols (B6) | The ruled limit (decisions 17 and 91), unchanged. It is stricter than any human figure found and equal to the 95 % convention, shown with confidence |
| M1, per language | **At most 2 wrong removals in 1,500 cells (0.13 %; upper bound 0.42 %)** | With the bound under 0.5 %, a trial with 11 note-decided exclusions still stays near 5 % (section 5.2) |
| M2, M3, M5 | Printed per language and per criterion kind; the floors of the pilot hold | |
| M7 | Section 6 | |
| A language with no B6 | States no figure for missed patients | Already ruled (criterion 1) |

*What release may claim:* "In language L, on N eligible patients with labels by two clinicians, at most 5 % are
missing from the list (95 % confidence), with Z patients to review per eligible patient found."

**What no stage may claim** [opinion]: a criterion accuracy as the headline (87 % sounds good and still loses one
pair in ten, section 5.2); a figure from a set with one labeller as an error rate; "better than doctors" (the
studies that say so rest on one expert, or on labels that include the doctors scored); a time saving nobody
measured at the site.

### 5.5 What this changes in the plan, and what it does not

- **Unchanged:** the 5 % upper bound on at least 124 pairs (criterion 1), F11's 95 % and 90 %, the 25 % decided
  floor, the gold-kind rule (D-1326), D-918's definition of the product path, D-985.
- **New:** M1 as the gate at every stage, with a number; two labellers and an adjudicator for any gating set; the
  worst of three runs; the review load beside every missed-patient figure; the public pair set named as never a
  gate; sets B1 to B3.
- **For the integrator to place:** the two "5 %" definitions the plan 10 review found (R22-03) become one: the
  upper bound on real labels. D-918's "at most 5 %" on the public pair set becomes "reported with its label check".
  Both need the owner's ruling and a decision record; this page writes neither.

### 5.6 The owner's choices, with the reasoning

1. **The pilot's reference line.** Option A: recall shown at least 90 %, aim 95 % (about 100 eligible patients
   needed). Option B: the 5 % upper bound at the pilot (124, with at most 2 missing). *Recommended: A.* It is the
   level a trained human reaches in the published studies, it is what F11 already says, and a single site's past
   studies may not hold 124 eligible patients with usable labels. B stays the release limit.
2. **Two labellers and an adjudicator for every gating set.** *Recommended: yes.* One-labeller sets are why the
   current figures cannot be settled (kappa 0.5 to 0.8 between qualified readers). The cost is reading time: B1
   now, about 1,000 cells at the site, 1,500 for release.
3. **Run-to-run variation: confirm a removal by a second run, and gate on the worst of three.** *Recommended:
   yes*, with the stable serving setting where it is exact (section 6).

---

## 6. Run-to-run variation in the standard

**What is known.**

- Here [bench]: the same setting twice gives the same label on about 94 % of criteria; about 1.2 % of criteria
  change between "block" and "not block"; between two complete runs of the shipped rule 6.3 % of eligible pairs
  and 11.2 % of excluded pairs changed side (an upper figure: the two runs also differed in serving layout). A
  batch-invariant serving mode gave identical labels one at a time and 96 % to 97 % when concurrent. The measured
  "lost" figure moved by about 3 points between runs.
- Elsewhere: at temperature 0, repeated runs are not identical; accuracy moved by up to 15 % between runs in one
  study (Atil 2024 [AB]); batch size is a cause, and batch-invariant kernels made 1,000 of 1,000 outputs identical
  at about 1.6 times the run time (He 2025 [FT of the blog]). Most trial-matching papers report one run. RECTIFIER
  reports five: 99.2 % to 100 % agreement [FT of the preprint].
- **No regulator or standard found asks for bit-identical output.** The nearest texts: validation shows performance
  "consistent with its intended purpose" (ICH E6(R3) 4.3.4); "repeatability and/or reproducibility studies may
  help quantify the uncertainty" (the US draft on AI, 2025); report "inference settings (e.g., seed, temperature)"
  and the "consistency of outputs" (TRIPOD-LLM item 6c).

**The proposal** [opinion]. All three of: a stable setting, repeat runs, and disagreement sent to review.

1. **In the product: a removal is confirmed.** A note answer that would remove is asked again in a separate call.
   If the second answer does not remove, the cell goes to review. A patient then never leaves a list on one draw.
   Only the answers that would remove are asked twice (about 2 % of cells today), so the cost is small. With the
   two-model rule this is "both models, twice".
2. **In serving: the stable setting where it is exact.** The batch-invariant mode is used where it gives identical
   answers (one at a time). Where the night must run concurrently, rule 1 carries the difference. The settings and
   the seed are part of the pinned profile and are printed with every figure.
3. **In measurement: three complete runs.** Every gated figure is computed on three runs and **the worst run must
   pass**. The spread is printed. A difference between two versions smaller than the spread is not called a gain.
4. **M7 thresholds.** rc1: printed, for cells and for pairs. Pilot and release: **no pair is missing in one run
   and a candidate in another** without having passed through review (a test of rule 1); pairs that move between
   "candidate" and "review" at most 2 % between two runs [opinion: a first figure, to be reset from rc1's table].
5. **A stored answer is a record.** The list a coordinator saw is kept with its version and settings; a re-run
   that differs does not rewrite it (the answer store of plan 10 already holds this).

---

## 7. What was not found, not opened or not verified

**About this page.**

- I did not open the papers myself. Five workers did, and marked each number; I read their five reports in full.
  A worker's reading through a summarising fetch tool is weaker than a line-by-line reading; where that was the
  case the reports say so, and this page keeps the weaker mark.
- No model was run. Whether the product meets rc1's number is **unknown**: the product-path figure of D-918 has
  never been run, and the ruling of 2026-11-22 is not code yet.
- The interval arithmetic is mine [calc]; a second person has not checked it.
- The thresholds for review load and for run-to-run movement of pairs have no source; they are marked [opinion].

**Not opened or not found, by item.**

- **RECTIFIER** (NEJM AI 2024): full text refused; figures from the abstract and the preprint. Its 95 % intervals
  were not found. The classifiable test count is given as 1,894 and as 1,509 in different places.
- **The randomised trial** (JAMA 2025): whether the AI arm could exclude without staff review, and the AI's
  accuracy inside the trial, were not found.
- **Watson for Clinical Trial Matching:** the 2018 Mayo abstract (the "80 % more enrolment") was not opened; press
  only, and the sources disagree on the period. Beck 2020 from the abstract only. No retraction of these papers
  was found; the public criticism found concerns the vendor's treatment-advice product.
- **TREC Clinical Trials:** the 2021 and 2023 overview papers were not found; no assessor-agreement figure exists
  for any year as far as could be found.
- **Reviews:** Idnay 2021 and Chow 2023 from abstracts; the manual comparator behind "comparable, if not superior,
  to manual screening" was not read.
- **Vendors:** no peer-reviewed screening accuracy was found for Deep 6 AI, Tempus, ConcertAI, Paradigm, Antidote,
  TrialX or Trialjectory. That is a search result, not proof of absence.
- **Human baseline:** no large audit of how many eligible patients manual screening misses in a clinic. The 36 %
  figure rests on about 11 patients. The systematic-review and legal-discovery figures are from snippets, except
  the judges' guide.
- **Japan:** only one group's conference papers (not peer-reviewed) and a ministry grant report with no
  sensitivity figure. No public corpus of real Japanese clinical notes was found. The share of English and
  abbreviations in Japanese notes: not found. The Japanese text of the conference papers did not render for the
  worker; one table's column meaning is inferred.
- **Taiwan:** no published evaluation of trial screening at a Taiwanese hospital. Notes there are "frequently
  written in a mixture of Chinese and English" (Lee 2024 [FT]); about 25 % of emergency chief complaints contain
  Chinese (Lu 2009 [FT]). No public Taiwanese clinical-note benchmark was found.
- **Japanese against English accuracy of local models on clinical text:** no direct figure found.
- **Regulation:** no text classifies recruitment pre-screening software, in any of the four jurisdictions.
  Whether a candidate list is a record under 21 CFR Part 11, or a decision under GDPR Article 22: not established.
  Not opened: IMDRF N12 and N88, the WHO guidance on large multi-modal models, the EU Clinical Trials Regulation's
  annex on recruitment, ISO 5725, CLSI EP05, ISO/IEC TS 4213, the DECIDE-AI and STARD-AI item lists. Not verified:
  the article text of Japan's personal-information and clinical-research laws and of Taiwan's human-research law.
- **n2c2 2018** is not in this repository; its use needs a data agreement with its distributor (from memory, not
  checked).

---

## 8. Sources

Regulators' and bodies' texts are named in section 4 with their dates. Papers, in the order used:

- Embi PJ et al. Arch Intern Med 2005;165:2272. doi:10.1001/archinte.165.19.2272
- Thadani SR et al. JAMIA 2009;16:869. doi:10.1197/jamia.M3119
- Penberthy L et al. Contemp Clin Trials 2010;31:207. doi:10.1016/j.cct.2010.03.005
- Penberthy LT et al. J Oncol Pract 2012;8:365 (effort in eligibility screening). PMC3500483
- Köpcke F et al. Int J Med Inform 2013;82:185. doi:10.1016/j.ijmedinf.2012.11.008
- Köpcke F, Prokosch HU. J Med Internet Res 2014;16:e161. doi:10.2196/jmir.3446
- Ni Y et al. JAMIA 2015;22:166. doi:10.1136/amiajnl-2014-002887
- Ni Y et al. BMC Med Inform Decis Mak 2015;15:28. doi:10.1186/s12911-015-0149-3
- Ni Y et al. JMIR Med Inform 2019;7:e14185. doi:10.2196/14185
- Yuan C et al. JAMIA 2019;26:294. doi:10.1093/jamia/ocy178
- Stubbs A et al. JAMIA 2019;26:1163. doi:10.1093/jamia/ocz163
- Beck JT et al. JCO Clin Cancer Inform 2020;4:50. doi:10.1200/CCI.19.00079
- Alexander M et al. JAMIA Open 2020;3:209. doi:10.1093/jamiaopen/ooaa002
- Haddad T et al. JMIR Med Inform 2021;9:e27767. doi:10.2196/27767
- Calaprice-Whitty D et al. Ther Innov Regul Sci 2020;54:69. doi:10.1007/s43441-019-00030-4
- Chow R et al. J Natl Cancer Inst 2023;115:365. doi:10.1093/jnci/djad013
- Liu R et al. Nature 2021;592:629 (Trial Pathfinder). doi:10.1038/s41586-021-03430-5
- Orcutt X et al. Nat Med 2025;31:457 (TrialTranslator). doi:10.1038/s41591-024-03352-5
- Koopman B, Zuccon G. SIGIR 2016. doi:10.1145/2911451.2914672
- Roberts K et al. Overview of the TREC 2022 Clinical Trials Track. NIST, TREC 2022
- Jin Q et al. Nat Commun 2024;15:9074 (TrialGPT). doi:10.1038/s41467-024-53081-z
- Syed M et al. JAMIA 2026;33:909. doi:10.1093/jamia/ocag006
- Fang Y et al. arXiv:2609.01202, 2026 (TrialGPT 2.0; preprint)
- Unlu O et al. NEJM AI 2024;1(7) (RECTIFIER). doi:10.1056/AIoa2400181; preprint doi:10.1101/2024.02.08.24302376
- Unlu O et al. JAMA 2025 (manual against AI-assisted pre-screening, randomised). doi:10.1001/jama.2024.28047
- Parikh RB et al. Nat Commun 2026. doi:10.1038/s41467-026-68873-8
- Rosenthal JT et al. arXiv:2511.05696, 2025 (MSK-MATCH; preprint)
- Gupta SK et al. npj Digit Med 2024;7:305 (PRISM). doi:10.1038/s41746-024-01274-7
- Wornow M et al. NEJM AI 2025;2(1). doi:10.1056/AIcs2400360; arXiv:2402.05125
- Callies A et al. Commun Med 2025;5:536. doi:10.1038/s43856-025-01256-0
- Krückel A et al. Digit Health 2025;11. doi:10.1177/20552076251389325
- Korvin K et al. Crit Care 2026;30:304. doi:10.1186/s13054-026-06127-1
- Wang K et al. BMC Cancer 2024;24:246. doi:10.1186/s12885-024-11959-7
- Shibata D et al. Annual meetings of the Association for Natural Language Processing (Japan), 2025 P3-19 and 2026
  P4-10
- Nievas M et al. JAMIA 2024;31:1953 (Trial-LLAMA). doi:10.1093/jamia/ocae073
- Abdallah M et al. Nat Commun 2026;17:4472 (TrialMatchAI). doi:10.1038/s41467-026-70509-w
- Gartlehner G et al. J Clin Epidemiol 2020 (single-reviewer abstract screening; journal from memory)
- La Rosa A et al. Cancer Med 2024;13:e70466. doi:10.1002/cam4.70466
- Cai T et al. ACR Open Rheumatol 2021. doi:10.1002/acr2.11289
- Cohen AM et al. JAMIA 2006;13:206. O'Mara-Eves A et al. Syst Rev 2015;4:5. doi:10.1186/2046-4053-4-5
- Lau TT, Lee EG. Technology-Assisted Review for Discovery Requests: A Pocket Guide for Judges. Federal Judicial
  Center, 2017
- Atil B et al. arXiv:2408.04667, 2024. He H. Defeating Nondeterminism in LLM Inference, 2025 (web article)
- Gallifant J et al. Nat Med 2025;31:60 (TRIPOD-LLM)
- Lee YQ et al. J Med Internet Res 2024;26:e48443. doi:10.2196/48443
- Lu HM et al. Int J Med Inform 2009;78:308. doi:10.1016/j.ijmedinf.2008.08.004
