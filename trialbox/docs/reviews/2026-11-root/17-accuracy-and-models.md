# Root review 17: a realistic accuracy target from the public studies, and the open model generations per tier (lane J, B-19, 2026-11-18)

**Reader:** the owner (a clinician) first, then the builders and whoever revises plan 10.

**The owner's words (2026-11-18).** On restating "no eligible patient excluded" as a measurable bound and on how
Japanese gold data is made: "See Lind, TrialGPT, and all public studies, but I want it to be realistic; Qwen4 is out,
need to assess?" On the first site's card: "5090?"

**What this review did.** It goes under reviews 05, 06, 07, 08, 13 and 15, plan 9 revision 2 and plan 10 (on master or
on the branches `agent/B12` to `B18`, read with `git show`) and does not repeat them: 07 owns the validation programme
and the first bound table, 13 owns the tier arithmetic and the run list, 15 owns the engine and the criterion
taxonomy. This review adds (1) every public study of trial matching and cohort selection it could open, with what each
measured and what does not carry over to an offline Japanese box; (2) a target the literature supports, with the
binomial arithmetic for cells and patients; (3) what is released in open models as of today, from the makers' pages,
with licences; (4) the fit per tier; (5) a straight answer on the 5090; (6) a bake-off design inside the cap. No model
was downloaded, nothing paid was run, no hospital data was read.

**Marks.** **[M n]** measured here (section 15 gives the command); **[R file:line]** read in the repository (paths from
`trialbox/`, at master `273b1e149`); **[R nn]** read in root review nn (or "plan 10"); **[S n]** a public source opened
2026-11-18 (section 16); **[S2 n]** a secondary source (press, blog, aggregator), weaker than a maker's or a
publisher's page; **[O]** opinion, with the reasoning. "Not verified" where a source could not be opened.

**Model names.** Inside this document a model family or build is named where the analysis needs it (licence, size,
measured score). The judge today is the 26B mixture-of-experts build of Gemma 4 (about 4B parameters active a token,
NVFP4) and the verifier the 9B dense Qwen3.5 build (AWQ 4-bit) [R `deploy/docker-compose.rtxpro6000.yml:6-8`;
`models/registry.yaml:139-171`].

---

## 0. One page for the owner

**"Lind".** It is a company, not a study: a US start-up whose trial-matching platform was tested at a US cancer centre
(over 1,700 criteria, "more than 94 % agreement with clinical reviewers", a prospective trial started May 2026) [S2 1,
S2 2]. The paper itself (announced for JCO Oncology Practice) could not be opened: not verified. Its model and whether
it runs on premises are not stated.

**What accuracy is realistic.** [S, O; section 1 and 2]
- The headline numbers in the literature (87 to 94 % per criterion) are **agreement on the lines a system answers, on
  English text, mostly with large closed models in a cloud**. TrialBox's comparable figure is as good: when the box
  answers a SIGIR line it agrees with the physicians 42 of 43 times (95 % CI 88 to 100 %) [R 15; M 4].
- What the literature rarely prints is **how many lines a system leaves open**. TrialBox prints it, and it is low: 15 %
  of cells decided on SIGIR, 53 % on the Japanese coded set, 85 % on the cancer set [R 15]. That, not the error rate, is
  today's gap.
- **People are not a perfect ceiling.** Trained screeners agree with each other at kappa 0.60 to 0.77 [S 9];
  in one hospital study manual screening found 36 % of the truly eligible patients against 82 % for a local model
  [S 5]; study staff had 90 % sensitivity and 84 % specificity against an expert [S 7].
- **Real Japanese charts are much harder than the public English sets.** The one Japanese study on real charts (a
  university hospital and a vendor, an open 70B Japanese model) found the model reading notes directly at precision
  0.07 and recall 0.21 per criterion, and 0.28 and 0.48 after a structured extraction step [S 15]. No Japanese or
  Chinese study reports a patient-level bound.

**The target I propose** (section 2): stated per language as an upper bound, not as "none":
- **First site (Japanese, pre-screening):** "a patient who meets the criteria is wrongly excluded by the box in at
  most 5 % of eligible patients (95 % upper bound), on at least 124 eligible patients from at least 12 protocols,
  with the decided share printed beside it." Realistic now that "unknown never excludes".
- **Release 1.0:** at most 2 % per language (313 eligible patients each, two misses allowed), 07's target, reached by
  growing the same set.
- **What is claimable today: no bound on Japanese charts at all.** On public English sets the box is rarely wrong when
  it answers and answers little; on public Japanese reports the shipped pair still treats about **1 stated-absent
  finding in 9 as present** (10.9 %, CI 8.0 to 14.6 %) [M 1]: rules before the model (review 11's JP-11) must fix that
  before any number is promised.

**The models.** [S, section 4]
- **Qwen4 is not out as open weights.** On 2026-11-18 the maker's model hub lists no Qwen4 model [S 20]; a hosted
  "Qwen4-Max" preview exists behind Alibaba's own service [S2 21, S2 22], which a hospital box cannot use. The open
  generation is **Qwen3.8** (August 2026): a 27B dense model under Apache-2.0 worth testing, a 125B/6B-active model under
  a **new "Qwen Community License" that asks a separate licence of "Model as a Service" businesses** (a finding), and a
  2.4T model no box can hold [S 23, S 24, S 25].
- Gemma 4 has two new sizes (12B dense, 31B dense; Apache-2.0); there is no Gemma 5 [S 26, S 27]. No gpt-oss successor
  is published [S2 28]. Japanese medical and Japanese-first open models exist under Apache-2.0 (a medical continued
  training of gpt-oss-120b; LLM-jp-4.1) [S 29, S 30].
- **None of these changes the plan by itself.** Measured on Japanese public reports, the strongest single engine in the
  repository's runs is already one we serve as the guard's base family [M 1]. A switch needs the bake-off of section 7.

**"5090?" — no, not for the first site** (section 6). A 32 GB card holds one model of today's class awake at a time,
cannot hold the pair side by side (measured on the stand-in [R `deploy/docker-compose.rtx5090.yml:24-25`]), costs
**¥1,239,000** in Japan today against **¥2,798,000** for the RTX PRO 6000 Max-Q [S2 31, S2 32], and needs 3 to 10
nights for a 600-bed first load [R 13]. It is a fair box for a small partner hospital that already owns one.

**The five changes that matter most.**
1. Restate release criterion 1 as the staged bound above, and plan the set size for **two misses allowed**, so a good
   box passes (card 17-1).
2. Print the **decided share** beside every bound, per criterion kind and per language (17-2).
3. Make Japanese gold: **130 synthetic charts written by Japanese clinicians** (about 120 clinician hours) plus the
   site's own de-identified sample under its rules, and a **shadow mode** beside the coordinator for 8 to 12 weeks
   (17-4, 17-5).
4. Run the **two-stage bake-off** (hosted public data first, then the finalist on the box) before any model switch; at
   most about US$45 spot (17-6 to 17-8).
5. Put the **licence terms of every candidate** in the register before a run (17-9); refuse "community" and
   "research" terms for the shipped box.

**What it costs.** Code cards are free. The bake-off: about US$25 hosted plus about US$16 to US$20 GPU spot (US$75 on
demand) [O, section 7]. The Japanese gold: about 120 clinician hours for the synthetic set plus about 40 for the site
sample [O, section 3.4]. The 5090 question costs nothing more if the answer is no.

---

## 1. Every public study of matching patients to trials and selecting cohorts

### 1.1 Benchmarks and shared tasks (public data)

| Study (date) | Task | Data, language | Model class | Number | Human ceiling | Data licence | Mark |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SIGIR 2016 test collection (Koopman, Zuccon; SIGIR 2016) | ranking: patient case → trials | 60 TREC CDS case reports (written, not charts), 204,855 trials, 4,000 judged pairs, labels 0/1/2 | baseline retrieval (BM25 etc.) | retrieval only (P@5 about 0.1 to 0.17 for baselines) | four medical assessors; **70 %** agreement on the control query | CSIRO data portal (doi 10.4225/08/5714557510C17); licence not opened | [S 3] |
| n2c2 2018 track 1 (Stubbs et al., JAMIA 2019) | patient level: 13 criteria met / not met | 288 diabetic patients, 2 to 5 longitudinal **real** notes each, English | 47 teams; best **rule-based** | best micro-F1 **0.91**; the top 10 rule-based or hybrid | annotators "use domain knowledge and intuition"; kappa not in the abstract (not verified) | n2c2 data use agreement | [S 4] |
| n2c2 2018, later LLM systems | same | same | GPT-4 class zero-shot with retrieval (Wornow, NEJM AI 2024); multimodal reasoning model (Callies 2025); GPT-3.5 with ontology summaries (2025) | "state of the art" (Wornow); **93 %** criterion accuracy (Callies); micro-F1 **0.906** (2025) | as above | as above | [S 10, S 11, S 12] |
| TREC Clinical Trials 2021, 2022 (NIST) | ranking: synthetic patient description → trials | 75 and 50 synthetic topics, about 26,000 trials each | many | TrialGPT NDCG@10 0.73 against 0.48 for the best baseline [S 1] | NIST assessors; agreement not opened | NIST terms; not opened | [S 1]; overviews not verified |
| TREC Clinical Trials 2023 | ranking from **structured questionnaires** | 40 synthetic patients, 8 diseases | many | best official NDCG@10 found **0.64** (a participant's table) | not opened | not opened | [S2 13]; overview not verified |
| TrialGPT (Jin et al., Nat Commun 2024, CC BY 4.0) | criterion level; ranking; retrieval | SIGIR + TREC 2021/22: 183 synthetic patients, 1,015 physician-labelled patient-criterion pairs | GPT-4 (cloud) | **87.3 %** criterion accuracy (inclusion 89.9 %, exclusion 85.9 %); retrieval recall > 90 % from < 6 % of trials; **42.6 %** less screening time in a two-annotator, six-vignette study (accuracy 97.2 % vs 91.7 %, not significant) | experts 88.7 to 90.0 % against the consensus | code on GitHub (licence not stated in the paper); labels on Hugging Face | [S 1] |
| TrialBox on the same 1,015 pairs (2026-10-25) | criterion level, 4-way label | same, plus TrialBox ja / zh-TW / mixed renderings | open models, hosted | 4-way accuracy 0.47 to 0.64 with TrialBox's "absent is not negative" prompt; 0.67 to 0.78 with TrialGPT's wording; "screen" (block vs open) 0.95 to 0.97; false block 1.7 to 3.6 % single, **0.9 to 1.3 %** for the both-must-block pair | as TrialGPT | as above | [R `eval/bakeoff/results/2026-10-25/summary.md:9-39`] |
| Criteria2Query (Yuan, JAMIA 2019; 2.0 2022; 3.0 2024) | criteria text → OMOP SQL | 125 + 52 criteria (2019); 1,010 COVID-19 trials (2.0); 20 trials, 518 concepts (3.0) | hybrid NLP; GPT-4 (3.0) | entity F1 0.795, relation 0.805 (2019); negation scope 0.924 (2.0); concept extraction F1 **0.891**, 29 SQL errors in 5 trials, a third of them logic errors (3.0) | two evaluators | ClinicalTrials.gov text | [S 14] |
| Chia (Kury, 2020) | criteria annotation | 12,409 criteria of 1,000 trials | – | 12.9 % "not useful for patient-focused database queries" | – | CC BY | [R 15] |

### 1.2 Real charts, hospital deployments and commercial tools

| Study (date) | Task | Data | Model, where it runs | Number (CI where given) | Human comparison | Mark |
| --- | --- | --- | --- | --- | --- | --- |
| Ni et al. (JAMIA 2015), paediatric emergency department | patient level, workload | 202,795 ED visits, 13 trials, structured + notes, English | classic NLP + ML, on site | workload **−92 %**, MAP 62.9 % | physician gold and historical enrolment | [S 16] |
| Beck et al. (JCO CCI 2020), a commercial matching system, community cancer centre | patient level, 4 trials | 997 breast cancer patients (239 compared) | vendor NLP + ML | agreement 81 to 96 %; sensitivity 91 to 95 % for three trials, **46.7 %** for the fourth; specificity 76 to 99 %; **110 → 24 min** for 90 patients x 3 trials | manual screening | [S 9] |
| Haddad et al. (JMIR Med Inform 2021), same vendor, academic centre | patient level, 4 trials | 318 breast cancer patients | vendor | accuracy 87.6 %, sensitivity **81.1 %**, specificity 89 % | **manual screeners' kappa 0.60 to 0.77** | [S 9] |
| Calaprice-Whitty et al. (TIRS 2020), a commercial AI tool | potentially eligible patients found | 3 oncology trials, retrospective | vendor | **+24 to +50 %** patients found; none found by standard practice missed | standard practice | [S 17] |
| RECTIFIER (Unlu et al., NEJM AI 2024) | criterion and patient level, 13 note questions | heart failure trial; 1,894 test patients, real notes | GPT-4 with retrieval (cloud) | per question 97.9 to 100 %; patient sensitivity **92.3 %**, specificity **93.9 %**; 2 to 11 cents a patient | study staff 90.1 % / 83.6 %; one expert as gold | [S 7] |
| RECTIFIER randomised (Unlu et al., JAMA 2025) | prospective, randomised workflow | 4,476 patients 1:1 | same | faster time to eligibility (HR 1.78); eligible 20.4 % vs 12.7 %; enrolled **35 vs 19** (1.6 % vs 0.9 %) | manual arm | [S2 8]; the paper itself not opened |
| PRISM / OncoLLM (Gupta et al., npj Digit Med 2024; arXiv CC BY-NC-ND) | criterion and trial level | real oncology records, one US centre | fine-tuned model "significantly smaller" than GPT-4 | "outperforms GPT-3.5 and matches qualified medical doctors"; numbers not in the abstract | doctors | [S 6]; full text not opened |
| Wong et al. (Microsoft, 2023), oncology | criterion structuring | a US health network in test deployment | GPT-4 | not opened | – | [S2 search only]; not verified |
| UT Health San Antonio local TrialGPT (JAMIA 2026) | patient level | 149 expert-adjudicated, 55 vs manual | **locally hosted** open model | sensitivity **81.8 %**, specificity 97.8 %, PPV 75.0 % | **manual screening found 36.4 %** of truly eligible | [S 5] |
| Gong et al. (JCO CCI 2026), OMOP-based rules + NLP | patient level; deployed | 1 trial validated, then 29 trials; **98,348 patients screened since 2022** | hybrid, on OMOP | 94 % retrospective, **88 % prospective** accuracy, 100 % sensitivity on the validation trial; review workload **10x lower**, 3.1 → 1.8 min a chart; 117 enrolments | chart review | [S 18] |
| Parikh et al. (Nat Commun 2026), randomised | chart level, human + AI vs human | 355 lung and colorectal cancer charts | "neurosymbolic" language model | accuracy **76.5 % vs 71.1 %** (non-inferior and superior); time **37.4 vs 37.8 min** (no saving); automation bias in some domains | trained research staff | [S 19] |
| TrialMatchAI (Nat Commun 2026) | retrieval + criterion level | synthetic and real oncology | fine-tuned **open** models, local | 92 % had a relevant trial in the top 20; > 90 % criterion accuracy by expert review | experts | [S 33] |
| Hepatopathy pipeline (BioData Min 2025), China | criterion level, question decomposition | liver disease trials, real records | LLM, "secure" | precision 0.921, recall about 0.82 (criterion level) | – | [S 34] |
| Callies et al. (Commun Med 2025) | criterion level | 485 real patients from 30 sites, 36 trials | multimodal reasoning model on page images | **87 %** (93 % on n2c2) | – | [S 11] |
| Lind (press, 2026-05-27) | criterion and trial level | over 1,700 criteria, breast, lung, pancreatic cancer | not stated | "more than 94 % agreement"; prospective trial started | clinical reviewers | [S2 1, S2 2]; paper not opened |
| Systematic review (Morrison et al. 2025) | 31 of 126 articles | – | GPT-4 mostly | hallucination, data leakage and cost as the challenges | – | [S2 search]; not opened |

### 1.3 Japanese and Chinese

| Study | Task | Data | Model | Number | Mark |
| --- | --- | --- | --- | --- | --- |
| A university hospital and a Japanese IT vendor (言語処理学会 2025, P3-19, CC BY 4.0) | criterion level, endometrial cancer, criteria of a JCOG trial | **real Japanese charts** of 851 patients (2,741 documents); ethics approval stated | BERT-CRF extraction into a database, then an open 70B Japanese-tuned model (Llama-3.1-Swallow-70B) one-shot | LLM on raw charts: precision **0.067**, recall **0.207** (mean of five criteria); on the extracted database: **0.284 / 0.477** (the "up to 4.2x"); extraction NER micro-F1 0.884, relations 0.768 | [S 15] |
| Same group with the vendor, 2024-10 to 12 demonstration | candidate extraction | not stated | medical-tuned LLM | "accuracy improved" (no figure) | [S2 search]; not verified |
| A university hospital, a pharma company and a telecom group (2026-06 start) | rules vs a Japanese LLM for candidate extraction | – | domestic LLM | planned; no result | [S2 search]; not verified |
| MedTxt (NTCIR-16 Real-MedNLP), TrialBox's runs | finding present / absent / suspected as an exclusion | 215 Japanese case and radiology reports, clinician English translations | open models, hosted | shipped pair, ja: present blocked **69.0 %**, stated absent blocked **10.9 %**, not mentioned 3.7 % | [M 1; R 11] |
| Chinese: an SQL route on a Shanghai hospital's real hepatocellular carcinoma cohort (PLoS One 2026) | criteria → SQL | ClinicalTrials.gov criteria; a real EHR cohort | BART parser + LLM agent | not opened beyond the abstract | [S 35] |
| Chinese, criterion-level on real Chinese notes | – | – | – | **none found** in PubMed or a Chinese-language web search | [S2 search] |

**What is missing everywhere** [O]: a patient-level upper bound on wrongly excluded eligible patients; any number on
Japanese or Traditional Chinese notes at patient level; any study where the system may say "unknown" and is scored for
both its errors and its abstentions.

### 1.4 What does not carry over to TrialBox

| Literature condition | TrialBox's condition | Effect on the number [O] |
| --- | --- | --- |
| Closed frontier models in a cloud (most rows) | open models of 9B to 26B on one card, offline | lower ceiling per call; the pair rule and quoting compensate on errors, not on coverage |
| A forced label ("try to use as little 'not enough information' as possible", TrialGPT's prompt [R `tools/bakeoff_live.py:52-58`]) | "unknown never excludes"; absent is not negative | lower agreement on 4-way labels (0.47 to 0.64 vs 0.67 to 0.78 for the same models [R summary.md]); far fewer false exclusions |
| Case reports and synthetic topics (SIGIR, TREC) | longitudinal charts, SS-MIX2 coded data, 疑い and 保険病名 [R 15 §6.4] | public-set accuracy overstates real-chart accuracy; the one Japanese real-chart study is 5 to 10 times lower [S 15] |
| English | Japanese, Traditional Chinese | measured loss small on clean reports (ja vs en, same engine: 91.8 vs 96.5 % present blocked [M 1]), large on real charts (not measured) |
| One expert's labels as gold | two blind labellers + adjudication (spec 16.8 [R 07]) | our gold is stricter, so our numbers will look lower |
| Accuracy over all criteria | accuracy on decided cells + decided share | must report both, never one |

---

## 2. What a realistic target is

### 2.1 Ranges the literature supports, per use and criterion kind

| Use, criterion kind | Literature range | Human ceiling | TrialBox today | Realistic target at the first site [O] |
| --- | --- | --- | --- | --- |
| Pre-screening, coded criteria (age, sex, coded diagnosis, lab with window) | n2c2 rule systems F1 0.90 to 0.91 [S 4]; C2Q concept F1 0.89 [S 14]; OMOP rules 88 % prospective [S 18] | data quality, not reading | coded cells right except the compile faults of 15 §2.3 [R 15] | ≥ 98 % right on decided coded cells; the two inclusion compile faults fixed first |
| Pre-screening, note criteria (diagnosis attributes, history, scales) | 82 to 94 % criterion accuracy [S 1, S 5, S 7, S 11]; real Japanese charts 0.07 to 0.28 precision [S 15] | kappa 0.60 to 0.77 [S 9]; 70 % assessor agreement [S 3] | 42 of 43 right when answered; 15 % decided [R 15] | wrong exclusions ≤ 5 % of eligible patients (95 % UB); decided share **30 to 50 %** of note cells on Japanese charts |
| Pre-screening, patient level | sensitivity 81 to 95 % [S 5, S 7, S 9] | staff sensitivity 90 % [S 7]; manual found 36 % [S 5] | not measured on real charts | recall of coordinator-found patients ≥ 95 % (lower bound ≥ 90 %) in shadow mode |
| Investigator judgement, consent, logistics | not automatable (all papers route to a person) | – | human by design [R 15] | 0 % machine-decided; counted as "asked at visit" |
| Reimbursement, precision first | no public study found | – | switched off for 1.0 [R 15] | "documents complete" precision ≥ 95 % (95 % lower bound) per rule; a missing item named, never "eligible" |
| Feasibility counts | Gong: 825 candidates of 98,348 [S 18] | – | definite + unknown interval [R 15] | count interval covers the manual count in ≥ 9 of 10 sampled studies |

### 2.2 The binomial arithmetic [M 3]

Exact one-sided 95 % Clopper-Pearson bounds; "eligible patients" are patients a gold standard says are eligible for the
trial, each scored "excluded by the box or not". 07's table gives the 0-miss sizes; this one adds the misses allowed
and the chance a good box passes, which is what makes a target realistic.

| Bound on wrongly excluded eligible patients | 0 misses | 1 miss | 2 misses | 3 misses | Clustered, 1 miss (10 per protocol, ICC 0.05) |
| --- | ---: | ---: | ---: | ---: | ---: |
| 5 % | 59 | 93 | 124 | 153 | 135 |
| 2 % | 149 | 236 | 313 | 386 | 342 |
| 1 % | 299 | 473 | 628 | 773 | 686 |

**Chance a box passes, when its true rate is a quarter or a half of the bound** [M 3]:

| Bound | Misses allowed | n | true rate = bound/4 | true rate = bound/2 |
| --- | ---: | ---: | ---: | ---: |
| 5 % | 0 | 59 | 0.48 | 0.22 |
| 5 % | 2 | 124 | 0.80 | 0.40 |
| 2 % | 0 | 149 | 0.47 | 0.22 |
| 2 % | 2 | 313 | 0.79 | 0.39 |
| 1 % | 2 | 628 | 0.79 | 0.39 |

**Reading** [O]: a zero-miss plan at the minimum n fails a box that is four times better than the bound half the time.
Plan for **two misses allowed**; that is the realistic form of the owner's wish.

**Cells versus patients.** A patient is wrongly excluded if any one decided exclusion-capable cell is wrong. If each
eligible patient carries c such decided cells, a patient bound of p needs a per-cell bound near p/c [O]:

| Patient bound | c = 5 cells: cells needed, 0 / 1 miss | c = 10 cells: 0 / 1 miss |
| --- | --- | --- |
| 5 % | 299 / 473 | 598 / 947 |
| 2 % | 748 / 1,185 | 1,497 / 2,371 |
| 1 % | 1,497 / 2,371 | 2,995 / 4,742 |

So **state the release bound at the patient level** (124 to 313 eligible patients) and report cells for diagnosis
only; a cell-level bound is 5 to 10 times more labelling for the same promise.

**How many candidates to review to reach N eligible** [M 3]: at an eligible share of 5 / 13 / 20 % among candidates (13
to 20 % is RECTIFIER's range [S2 8]), 124 eligible patients need about 2,480 / 954 / 620 candidates; 313 need 6,260 /
2,408 / 1,565. Gold sets must therefore be **enriched** (synthetic charts written to be eligible, section 3.4), or the
labelling cost is unrealistic.

### 2.3 Proposed wording for release criterion 1

> **First site (pre-screening, Japanese):** "On a frozen set of at least 124 gold-eligible patient-trial pairs drawn
> from at least 12 protocols, declared before the run, the box excludes at most 2 of them, so that the one-sided 95 %
> upper bound of the rate of wrongly excluded eligible patients is at most 5 %; the decided share of note-criterion
> cells and the count per criterion kind are printed beside it; no key is changed after its run."
>
> **Release 1.0, per language (ja, zh-TW, en):** the same with 313 pairs and a 2 % bound; pooled 1 % (628 pairs) is a
> 1.x goal.

This keeps 07's frame (frozen, pre-registered, per language [R 07 §5.3]) and changes two things: the staged bound and
the misses allowed (owner decision 1).

### 2.4 What TrialBox has measured, and what is claimable today

| Figure | Value | What it supports | Mark |
| --- | --- | --- | --- |
| SIGIR cells decided | 138 of 895, 15.4 % (Wilson 13.2 to 17.9 %) | coverage is the gap | [R 15; M 4] |
| SIGIR lines the physicians could answer, answered by the box | 43 of 284, 15.1 % (11.4 to 19.8 %) | same | [R 15; M 4] |
| Agreement when answered | 42 of 43 (87.9 to 99.6 %) | high precision on decided cells | [R 15; M 4] |
| Wrong exclusions on answered "eligible on this line" | 1 of 41 (95 % UB 11.1 %) | too few to bound | [M 3] |
| P2b pooled eligible exclusions | 4 of 420, UB 2.17 % | the best bound on record; English, development data | [R 07] |
| TCGA, 0 of 50 lost | UB 5.8 % | English, one protocol | [R 07; M 3] |
| MedTxt ja, the shipped pair, stated-absent finding blocked | 38 of 349, **10.9 %** (8.0 to 14.6 %) | negation is the Japanese weak point | [M 1] |
| MedTxt ja, the shipped pair, present finding blocked | 69.0 % (gemma 26B NVFP4 + qwen 9B) | the pair rule costs exclusion recall | [M 1] |
| Hosted bake-off, both-must-block false block on SIGIR pairs | 0.9 to 1.3 % per language (UB 1.6 to 2.1 %) | criterion level, development set, another judge | [R summary.md:36-39] |

**Claimable today, plainly** [O]: "On public English test data, when the box decides a criterion it agrees with
physicians about 98 % of the time (95 % CI 88 to 100 %), and it decides about one criterion in six. On public Japanese
reports it wrongly reads about one stated-absent finding in nine as present when both models agree. No figure exists
for real Japanese charts. No bound on wrongly excluded eligible patients exists for Japanese." The MedTxt figure uses
the bake-off prompt, not the box's quoting judge with its mapping rules [R `tools/medtxt_eval.py:1-20`], so the box may
do better; that is to be measured on the box (stage G, section 7).

---

## 3. How to get there

### 3.1 Which gains the literature shows are real

| Method | Evidence | Size of gain | In TrialBox | Verdict [O] |
| --- | --- | --- | --- | --- |
| Structured data first, notes second | NEC/Tohoku 4.2x precision from extraction first [S 15]; RECTIFIER: codes decide 5 of 6 inclusions [S 7]; Gong OMOP rules [S 18]; n2c2 rules best [S 4] | the largest, especially in Japanese | the ladder's first rung [R 15] | **real; the main lever** |
| Retrieval before judging | TrialGPT retrieval > 90 % recall [S 1]; Wornow two-stage retrieval cuts tokens a third at the same score [S 10]; RECTIFIER uses retrieval [S 7] | cost and long-chart context, not accuracy per se | S2/S2b removed **no pair** in SIGIR or TCGA [R 15; R 08] | real for long charts; needs real-chart lengths to tune |
| Criterion decomposition | hepatopathy composite questions [S 34]; C2Q [S 14]; Parikh gains on biomarker, stage, response [S 19] | moderate | IR v3 on paper, not run [R 15] | real; 15's B16-1 to B16-4 |
| Rules for negation and suspicion | n2c2 rule systems [S 4]; MedTxt strict slice [R 11] | large for Japanese negation | scattered cue lists [R 11] | **real; JP-11 first** |
| A second model / verification | TrialBox's both-must-block halves false block (2.4 → 0.9 to 1.3 %) [R summary.md] | halves false exclusions; costs exclusion recall (90 → 69 % present blocked, ja) | shipped | real; keep; choose the verifier for independent errors |
| Abstention ("unknown") | no paper scores it; TrialBox's design | trades coverage for safety | shipped | real; must be reported (decided share) |
| A bigger or newer model | GPT-4 vs 3.5 in TrialGPT, RECTIFIER; in TrialBox's runs larger models block more of both kinds [M 1] | a few points; does not fix missing representations | – | **small**; never the first lever |
| Fine-tuning on the task | OncoLLM [S 6]; TrialMatchAI [S 33] | matches a larger model | none | possible later; needs gold we do not have |
| Reasoning ("thinking") | Callies [S 11]; earlier run used low effort for reasoning builds [R summary.md:3] | unclear on screening; 3 to 10x tokens | thinking off on the verifier [R registry:110] | **not shown** to be worth its time on a box |
| Human + AI per chart time | Parikh: no time saved, 76.5 vs 71.1 % [S 19]; TrialGPT −42.6 % (two annotators) [S 1]; Beck 110 → 24 min [S 9] | workload (fewer charts) large; time per chart small | – | promise fewer charts, not faster charts |

### 3.2 Coverage alongside accuracy

[O] On real charts the literature's systems decide every criterion; TrialBox leaves doubt to a person. A realistic
decided share at the first site, by kind: coded criteria 80 to 95 % (once 06's code lists load); note criteria 30 to
50 % in Japanese (anchored by the NEC/Tohoku recall of 0.48 with structured extraction [S 15] and JMED's 53 % [R 15]);
human criteria 0 %. **Pair every bound with the decided share** so the box cannot pass the bound by abstaining (07 §3.10
says the same); a release fails if note coverage on the frozen ja set is under 25 % [O; owner decision 2].

### 3.3 Measurement plan at the first site: shadow mode beside the coordinator

| Item | Design [O] |
| --- | --- |
| Studies | the first 1 to 3 studies the coordinator pre-screens by hand anyway |
| Duration | 8 to 12 weeks, the box's weekly list kept from the coordinator until the week's manual list is fixed (blind) |
| Known positives | every patient the coordinator lists as a candidate; the box must not have excluded any. Recall lower bound ≥ 0.90 needs 29 known positives with 0 misses, 46 with 1 [M 3b] |
| Elusion sample | 40 box-excluded patients a month, read by the coordinator (07's recall ledger design [R 07 §3.6]) |
| Extra finds | patients the box lists and the coordinator missed, adjudicated by the investigator (the UT Health study's "twice as many" [S 5] is the effect to look for) |
| Time | coordinator minutes per candidate with and without the sheet (expect fewer charts, not faster charts [S 19]) |
| Output | a counts-only site acceptance record; no chart text leaves the hospital |
| Size check | a 600-bed hospital's coordinator lists perhaps 10 to 40 candidates a month across 3 studies [O]; 8 to 12 weeks gives 30 to 120 known positives |

### 3.4 How Japanese gold is made, and what it costs in clinician hours

| Source | What it gives | Size | Clinician hours [O] | Licence or rule |
| --- | --- | --- | --- | --- |
| MedTxt (review 11) | negation, suspicion, present findings in real Japanese text; development only | 215 reports, 1,677 items | 0 (already labelled) | CC BY 4.0 (RR and test collection) [R 11] |
| Synthetic charts written by Japanese clinicians | patient-trial gold with 疑い, 保険病名, SOAP abbreviations, 読影 and 病理 reports, older-record gaps (11 §5) | **130 charts x 2 trials = 260 pairs, about 130 eligible** (enriched: each chart written eligible for one trial, ineligible or open for the other), 12+ public jRCT protocols | writing 130 x 40 min = 87 h; double labelling 260 x 2 x 4 min = 35 h; adjudication 20 % x 5 min = 4 h; **about 125 h** | written for TrialBox, assigned to it by contract |
| The site's own de-identified sample | real-chart truth; the only source of real prevalence and real error kinds | 60 to 100 patients pre-screened by the coordinator for 2 studies | double labelling about 25 h; adjudication 5 h; plus the site's privacy officer's time | the site's ethics and APPI route (review 11 §2.1); counts only leave the hospital |
| Shadow mode (3.3) | recall at the site, not a frozen test set | 30 to 120 known positives | coordinator time already spent; 40 elusion reads a month at 5 min = 3.3 h a month | as above |

Cost [O]: at ¥12,000 to ¥20,000 an hour for a Japanese physician or research nurse (rate not verified), the synthetic
set is about ¥1.5 to 2.5 million. It reaches the 5 % bound (124 eligible, 2 misses) once; the 2 % bound needs about
2.5 times more (313 eligible), which the site sample and later sites grow toward.

---

## 4. The open model generations as of 2026-11-18

### 4.1 Qwen: is "Qwen4 out"?

| What | Exists? | Licence | Date | Size | Mark |
| --- | --- | --- | --- | --- | --- |
| Qwen4 open weights (any size) | **No.** The maker's hub lists none; the 27B is "named, no date, no licence" | – | – | – | [S 20; S2 21] |
| Qwen4-Max-Preview | yes, hosted only (a two-week preview on the maker's service, from 2026-11-11 per secondary pages) | service terms | 2026-11 | not published | [S2 21, S2 22]; maker's blog not opened |
| Qwen3.8-27B (+ FP8) | yes | **Apache-2.0** | August 2026 | 27B dense with a vision encoder; Gated DeltaNet + Gated Attention hybrid; 262k context | [S 23] |
| Qwen3.8-Flash-Next (+ FP8) | yes | **"qwen-community-1.0"**: a separate licence before use by a "Model as a Service or AI Work Assistant business"; a name display duty above 100 million MAU or US$20 million monthly revenue | August 2026 | 125B total, 6B active, plus 51B n-gram embeddings (180B listed) | [S 24, S 25] |
| Qwen3.8-2.4T-A95B (+ FP8) | yes | not opened | 2026 | 2.4T | [S 20] |
| Qwen3.6-35B-A3B, 27B (+ FP8) | yes | Apache-2.0 | April 2026 | 35B / 3B active; 27B dense; 262k | [S 36] |
| Qwen3.5-9B (today's verifier) | yes | Apache-2.0 | – | 9B | [R `docs/licences/register.csv:31`] |
| Small Qwen3.8 (under 27B) | **none** in the collection | – | – | – | [S 20] |

Japanese claims: none of the Qwen cards states a language count or a Japanese score; Qwen3.6 lists C-Eval 90.0 for
Chinese [S 36]. Thinking is on by default and is turned off with `enable_thinking: false` [S 23, S 36].

**Finding** [O]: whether a hospital box that a vendor sells is "Model as a Service" under the Qwen Community License is
not answered by its text (the definition is "giving a third party access to language model inference ... in a manner
that allows such third parties to exercise meaningful control over the inputs" [S 25]); the console lets staff type
free questions. Treat that licence as excluded for the shipped box unless the maker answers in writing.

### 4.2 The other families a hospital box could run

| Family, build | Released | Licence | Size, context | Japanese / medical evidence | Mark |
| --- | --- | --- | --- | --- | --- |
| Gemma 4 26B-A4B (today's judge) | April 2026 | Apache-2.0 | 25.2B / 3.8B active; 256k | MMMLU 86.3; MedXPertQA MM 58.1 [S 27]; MedTxt ja present blocked 82.7 % at NVFP4, **90.3 % at full precision** [M 1] | [S 27] |
| Gemma 4 31B | July 2026 (report) | Apache-2.0 | 30.7B dense; 256k | MMMLU 88.4; MedXPertQA MM 61.3 | [S 27] |
| Gemma 4 12B | hub entry updated about 2026-10-31; release date not stated | Apache-2.0 | 11.95B dense; 256k | MMMLU 83.4; MedXPertQA MM 48.7 | [S 26] |
| Gemma 4 E4B, E2B | updated 2026-11 | Apache-2.0 (not opened per card) | 8B / 5B listed | – | [S 37] |
| Gemma 5, Gemma 4.x | **not released** | – | – | – | [S 37; S2 38] |
| MedGemma 1.5 (4B), 1.0 (27B) | 2026-01 | **Health AI Developer Foundations terms**, not Apache | 4B; 27B | medical imaging focus | [S2 39]; terms not opened |
| gpt-oss-120b, -20b | 2025-08 | Apache-2.0 + a usage policy | 117B (active share not opened; about 5B [O]); 21B | MedTxt ja present blocked **91.8 %**, stated absent 21.5 % (strongest single engine) [M 1] | [S2 28]; no successor found |
| Weblab-MedLLM-gpt-oss-120b (a Japanese university's medical continued training) | 2026-06 | **Apache-2.0** | 117B; published at full precision (about 240 GB BF16) | Japanese physician licensing exam 93.6 % (+3.8 over base); "not recommended" for diagnosis or clinical decision support; may be a 医療機器プログラム | [S 29, S 40] |
| Weblab-MedLLM on GLM-4.7 / Qwen3-235B | 2026-06 | MIT / Apache-2.0 | too large for any tier | – | [S 40] |
| LLM-jp-4.1 32B-A3B thinking, 33B thinking | 2026-09/10 | **Apache-2.0** | 32.1B / 3.8B active; **65,536** context; English and Japanese | Japanese MT-Bench 7.69; thinking variants only (no instruct listed) | [S 30, S 41] |
| NVIDIA Nemotron Nano 9B v2 Japanese | 2026-02-17 | **NVIDIA Nemotron Open Model License** (terms not opened) | 9B Mamba2-Transformer hybrid; 128k | Nejumi LB4 0.711 (first under 10B) | [S 42] |
| Nemotron 3.5 lightning (in TrialBox's MedTxt run) | – | not verified | – | MedTxt ja present blocked 19.7 % (unusable recall) [M 1] | [R scores.json] |
| Ministral 14B (2512) | 2025-12 | not verified here | 14B | MedTxt ja present 86.5 %, absent 21.5 % [M 1] | – |
| LFM 2.5 24B-A2B | – | not verified here | 24B / 2B active | MedTxt ja present 68.0 %, absent 10.6 % [M 1] | – |

**What the repository's own Japanese runs say** [M 1]: no single open engine is below 10 % on stated-absent findings
without losing most true findings; the best both-must-block pairs sit at 8 to 16 % negated-blocked. **Quantisation
costs Japanese:** the judge at NVFP4 blocks 82.7 % of present findings against 90.3 % at full precision on the same
reports. Google's 4-bit QAT build was already tried and rejected (worse alone in Japanese, broken JSON on 3 of 54
canary cases) [R `deploy/docker-compose.rtx5090.yml:26-28`].

### 4.3 Licence verdicts for a signed, offline box sold to hospitals

| Terms | Builds | Verdict [O] |
| --- | --- | --- |
| Apache-2.0, MIT | Gemma 4 (all sizes), Qwen3.8-27B, Qwen3.6, Qwen3.5, gpt-oss (+ usage policy), Weblab-MedLLM-gpt-oss-120b, LLM-jp-4.1 | shippable; register row with licence text sha256 [R `models/registry.yaml:9-13`] |
| Qwen Community License 1.0 | Qwen3.8-Flash-Next | **exclude** until the maker answers in writing (owner decision 5) |
| NVIDIA Nemotron Open Model License | Nemotron Nano 9B v2 Japanese | read the terms before any run; not verified |
| Health AI Developer Foundations terms | MedGemma | exclude for the box (not Apache; terms not opened) |
| Hosted only | Qwen4-Max | out of scope (no PHI leaves the box) |

---

## 5. Fit per tier

Inputs: tier memory, bandwidth and today's measured layout from 13 [R 13 §2-§3]. Weight sizes at 4-bit ≈ 0.56 bytes a
parameter including scales [O]; decode for one stream ≈ bandwidth x 0.6 ÷ bytes read a token [O, as 13]. "Measured"
only where marked.

### 5.1 Memory of candidate builds

| Build | 4-bit weights | 8-bit | Bytes read a token (4-bit) | Notes |
| --- | ---: | ---: | ---: | --- |
| Gemma 4 26B-A4B (judge today) | 17.1 GiB [R] | ~26 GB | ~2.1 GB | KV ~110 KiB a token [R 13] |
| Qwen3.5-9B (verifier today) | 7.5 GiB [R] | ~10 GB | ~5 GB | KV ~45 KiB a token [R 13] |
| Gemma 4 31B | ~17 GB | ~31 GB | ~17 GB | dense: slow on C and A |
| Gemma 4 12B | ~7 GB | ~12 GB | ~7 GB | same family as the judge: not an independent verifier |
| Qwen3.8-27B | ~16 GB (no official 4-bit: a TrialBox quantisation) | ~28 GB official FP8 | ~15 GB | hybrid attention: small KV (not verified) |
| Qwen3.6-35B-A3B | ~20 GB | ~36 GB official FP8 | ~1.7 GB | MoE: fast on C and A |
| LLM-jp-4.1 32B-A3B | ~18 GB | ~32 GB | ~2.1 GB | thinking only; 65k context |
| gpt-oss-120b (or its Japanese medical variant) | ~61 GB MXFP4 (variant: a TrialBox quantisation from F32) | – | ~3 GB | fits D or C only |
| gpt-oss-20b | ~13 GB MXFP4 | – | ~2 GB | the guard's base family already registered [R register.csv:32] |
| Nemotron Nano 9B v2 Japanese | ~5 GB | ~9 GB | ~5 GB | Mamba state, small cache; vLLM ≥ 0.11.2 with a cache flag [S 42] |

### 5.2 Judge and verifier per tier

| Tier | Today | Best candidate layout to test [O] | Memory with cache at the needed concurrency | Speed (opinion — to be measured unless marked) | Japanese evidence | Structured output |
| --- | --- | --- | --- | --- | --- | --- |
| A, no GPU (64 to 128 GB RAM) | none in PRODUCTION [R 13] | judge: a small-active MoE (today's judge as GGUF, or Qwen3.6-35B-A3B); verifier: gpt-oss-20b or the 9B on vLLM CPU | 17 + 13 GB weights + < 8 GB cache at 4 slots: fits 64 GB | server: ~0.2 pair calls a second; desktop ~0.05 [R 13]; dense 27 to 31B: about 6x slower, **not for A** | MedTxt for today's pair only | llama.cpp JSON schema [R 13] |
| B, 32 GB card | one awake, swap; 8k; 4 sequences [R rtx5090.yml] | judge alone awake on the card (17.1 GiB + ~7 GiB cache), verifier on the host CPU (vLLM CPU, AWQ); or a 5 GB verifier (Nemotron JP) beside the judge at 8k | judge + 9B side by side "does not fit" [R rtx5090.yml:24-25]; judge + 5 GB verifier ≈ 22 GiB + 2 contexts ≈ 25 GiB, leaving ~5 GiB cache: **untested** | judge ~1 to 3.5 calls a second [R 13]; protocol reading with the judge alone at 16 to 32k, 2 sequences (3.4 GiB a 32k sequence [R 13]): plausible at night | as today | vLLM `json_schema` [R `libs/tb_llm/client.py:152-153`] |
| C, Spark (128 GB unified) | pair resident, 16k, unmeasured [R 13] | as today; or a stronger judge: gpt-oss-120b class (~61 GB) + today's verifier | 61 + 7.5 GB + cache ~30 GB: fits 117 GiB of limits [R 13] | 120B MoE MXFP4 on a Spark: 45.9 to 60.6 tok/s one stream **(source, llama.cpp)** [R 13]; the dense 9B verifier is the slow member (~30 tok/s ceiling [R 13]) | gpt-oss-120b is the strongest single ja engine in the runs [M 1] | vLLM; gpt-oss's harmony format with JSON schema on this vLLM: not verified |
| D, RTX PRO 6000 (96 GB) | pair resident, 32k, 16 sequences, 3.06 calls a second (measured) [R 13] | (1) today's pair with the **judge at FP8** (~26 GB) to recover the Japanese quantisation loss; (2) gpt-oss-120b class judge (~61 GB) + 9B verifier; (3) Qwen3.8-27B as a different-family verifier | (1) 26 + 7.5 GB: cache room ample; (2) 61 + 7.5 = 69 GB + contexts: ~20 GB cache, enough for 16 to 32 sequences at p95 calls [O] | (1) about today's rate; (2) fewer calls a second (more active parameters) | (1) +7.6 pp present findings at full precision [M 1]; (2) best ja single engine [M 1] | as today |

**Reading** [O]: no candidate changes tier B's basic shape (32 GB holds one model of this class with cache). On C and
A, keep mixture-of-experts models for both roles; a dense verifier is the slow member there. On D the most promising
single test is **the same judge at 8-bit**: no new model, no new licence, the measured Japanese loss recovered.

---

## 6. "5090?" for the first site, answered straight

**Answer: no.** Buy the RTX PRO 6000 Max-Q workstation, as 13 recommends [R 13 §9]. Reasons, each with its source:

| Question | With today's profile | With the best candidate (section 5) | Mark |
| --- | --- | --- | --- |
| Both models side by side | no: "verifier short of KV cache" on the 32 GB stand-in | only with a ~5 GB verifier, untested; or the verifier on the CPU | [R rtx5090.yml:24-25; O] |
| Protocol compile on the box | no at 8k today; the judge alone at 16 to 32k with 2 sequences is memory-possible at night | same | [R rtx5090.yml:33-34; R 13; O] |
| Nightly delta, 600 beds, 15 studies, typical | 1.6 h today, 0.5 h tuned: fits | same | [R 13 §4] |
| First load, 600 beds typical | 55 h today (10 nights), 15.7 h tuned (3 nights) | same | [R 13 §4] |
| Chat or a note check during the verifier pass | "busy, try again" | resolved only with a CPU verifier | [R rtx5090.yml:20] |
| ECC memory, power | no ECC (consumer card; not on the maker's page); 575 W card, 1,000 W PSU | – | [R 13 §2] |
| Price in Japan, 2026-11-18 | **¥1,239,000** lowest in stock | – | [S2 31] |
| RTX PRO 6000 Max-Q | **¥2,798,000** lowest new, 2026-11-13 (13 had ¥2,499,980; the price rose) | – | [S2 32] |
| DGX Spark | ¥1,045,000 (13; not rechecked) | – | [R 13] |
| Measured on a real 5090 | never; only a capped RTX PRO 6000 | – | [R 13] |

**What must be measured before a 5090 is ever promised** (13's B-1, B-2, B-3 plus one): B-4, the judge alone at 16k
and 32k reading the 104 SIGIR protocols with 2 sequences, `ir_extract` parts completed without a split, on the 32 GB
stand-in, 1 h, about US$2.7 spot (card 17-12).

**Recommendation** [O]: the first site is the head hospital of a multicentre group; it must read protocols on the box,
run the pair side by side and finish a first load in days. The ¥1.56 million difference buys exactly those. A 5090 is a
fair box for a small partner hospital that already owns one, with protocols compiled at the head hospital (13's card
13-3). A Spark is the better new small box once measured (¥1.05 million, quiet, 128 GB).

---

## 7. The evaluation to run before any model switch

### 7.1 What the harness already allows

| Need | Command (from `trialbox/`) | Mark |
| --- | --- | --- |
| Pin a hosted build to a dated provider version | `python -m tools.pin_provider --build or-<name> --model <hub id> --provider <name>` | [R `tools/pin_provider.py:1-22`] |
| Criterion pairs, SIGIR 1,015, en / ja / zh-TW / mixed, through a DEV gateway | `python -m tools.bakeoff --live --build or-<name> --langs en ja --n 0 --budget-usd 5 --out eval/bakeoff/results/<date>` then `--report` | [R `tools/bakeoff_live.py:1-25`; `tools/bakeoff.py:310-331`] |
| Japanese real text (MedTxt), base and "suspected" prompts; pairs scored | `python -m tools.medtxt_eval run --models <ids> [--variant suspected] [--base-url <OpenAI-compatible URL>]`, then `score` | [R `tools/medtxt_eval.py:20-23,296-299`] |
| SIGIR full cohort and TREC CT 2023, with Wilson and patient-cluster intervals | `python -m tools.open_cohorts_eval run --cohort sigir\|trec2023 --models <ids>`, then `score` | [R `tools/open_cohorts_eval.py:17-20,290-294`] |
| On the box: synthetic ja / zh-TW / en accuracy set | `python -m tools.accuracy_set run cases.jsonl answers.json`, then `score` | [R `eval/accuracy/README.md:6-10`] |
| On the box: qualification, throughput, tcga:500 | `deploy/gcp/box-run.sh --mode validation --steps start,acc --only tcga:500` and `qualify --profile` | [R 13 §8] |
| **A candidate model on the box without a release** | **not possible**: `box-run.sh` takes a bundle and `--serving shipped\|tuned`, no weights override [R `deploy/gcp/box-run.sh:100-135`]; a candidate needs a registry row, a licence row, a pinned weight folder and a bundle (card 17-6) | [R] |

### 7.2 The design

**Stage H — hosted, public data only (DEV, class D0), the integrator's key.**

| Role | Candidates | Why |
| --- | --- | --- |
| Judge | today's judge at full precision (control); Gemma 4 31B; Qwen3.8-27B (thinking off); Qwen3.6-35B-A3B (thinking off); gpt-oss-120b (have); LLM-jp-4.1-32B-A3B and the Japanese medical gpt-oss-120b **only if a provider serves them** (pin_provider says) | the 2026 Apache-2.0 generation, two Japanese-first |
| Verifier | today's 9B (control); Gemma 4 12B; Nemotron Nano 9B JP (only after its licence is read); gpt-oss-20b | small, ideally another family than the judge |

Sets: SIGIR 1,015 pairs in en and ja (bakeoff); MedTxt 215 reports, ja and en, base and suspected (medtxt_eval); SIGIR
full cohort and TREC 2023 (open_cohorts_eval). Pairs are scored from the recorded single answers (both must block),
so a pair costs nothing extra [R `eval/medtxt/README.md:8-9`].

Cost [O]: the whole 2026-10-25 bake-off (five builds, four languages, 1,015 pairs each, plus the cascade) cost
US$7.68, of which US$1.9 was the closed reference [R summary.md:81, :16-20]. Ten builds x (2 languages x 1,015 + 4 x
1,677 MedTxt items + 2 cohorts) is about 5 times that: **about US$25, cap the runs at US$35 with `--budget-usd`**.
Hours: about 1 day of the integrator, 8 workers.

**Stage G — the finalist on the box (one RTX PRO 6000 spot VM, in the same session as G-4 / V1).**

1. The control: today's pair, and today's judge at FP8 (no new model; a serving change: MC class per
   `docs/validation/model-change-protocol.md`).
2. At most two finalist layouts from stage H, in the box's own quantisation.
3. On each: `qualify --profile rtxpro6000` (canary, pair gate, determinism, injection), the synthetic accuracy set in
   three languages, MedTxt ja through the box's endpoint (`--base-url`), tcga:500 for calls a second.

Hours and cost: 6 h, **about US$16 spot (US$49 on demand)** at US$2.74 / 8.22 an hour [R 13 §8]. Add B-2 / B-4 on the
32 GB stand-in for any finalist meant for tier B: 1 h, US$2.7.

**Total**: about US$45 spot, US$85 on demand. Plan 10's paid rows reach US$99 to US$131 spot (US$266 to US$354 on
demand) beside US$117.7 already spent [R plan 10 §7]: spot fits easily; **on demand, the worst reading of the cap leaves
about US$28** [O, 500 − 354 − 117.7], so stage G must run on spot or replace plan 10's 9c-8 small-model experiment
(US$8 to 14 spot), which asks a related question.

### 7.3 The decision rule (written before the run)

Switch a role's build only if **all** hold on the stage G box, against the control, on the same items:

1. Japanese safety: MedTxt ja **pair** stated-absent blocked rate not higher than the control's by more than 1 point,
   and its 95 % upper bound under 15 % [M 1 baseline 10.9 %, UB 14.6 %]; SIGIR pair false block not higher (UB).
2. Coverage: present findings blocked by the pair (ja) at least the control's 69.0 % [M 1], and on the synthetic set the
   decided share at least the control's.
3. No language worse: en, ja, zh-TW each non-inferior by 2 points on the screen (block vs open) agreement.
4. Operations: invalid JSON ≤ 1 % on the canary; calls a second at least 80 % of the control's on the same tier; fits
   the tier's memory with the profile's sequences.
5. Licence: a register row with the licence text's sha256, Apache-2.0 or MIT [R `models/registry.yaml:9-13`].
6. A gain worth a requalification: either rule 1 or rule 2 improves by at least 5 points; otherwise keep the control.

If none passes: **keep the pair**, move only to the FP8 judge on tier D if it passes rules 1 to 5, and spend the effort
on rules first (JP-11) and IR v3 (15).

---

## 8. Gap table

| What the product does today | What is needed | Evidence |
| --- | --- | --- |
| Release criterion 1: "no eligible patient excluded" (07 proposes 2 % / 1 %) | a staged patient-level bound, 2 misses allowed, decided share beside it | [R 07 §3.1; M 3] |
| Bounds counted in cells or pairs | patient-level eligible pairs for the bound; cells for diagnosis | [M 3] |
| Decided share reported in reviews only | in every accuracy report, per kind and language | [R 15 §2.2] |
| No Japanese patient-trial gold | 130 synthetic charts + site sample + shadow mode | [R 07 §3.2; R 11] |
| MedTxt run with the bake-off prompt | the same items through the box's judge with quoting | [R `tools/medtxt_eval.py:1-20`] |
| Japanese negated findings blocked 10.9 % by the pair | rules first (JP-11), then measure | [M 1; R 11] |
| A candidate model cannot be run on the box without a release | a candidate-weights path for VALIDATION boxes | [R `deploy/gcp/box-run.sh:100-135`] |
| Licence register holds the three shipped builds | rows for every candidate, with the Qwen Community and NVIDIA terms marked | [R `docs/licences/register.csv:30-32`] |
| Thinking control per build is a comment | a registry field, refused for thinking-only builds in the judge role unless measured | [R `models/registry.yaml:110`] |
| Judge at NVFP4 everywhere | FP8 judge on tier D if stage G passes | [M 1] |
| 5090 profile: protocols "on the cloud route" | judge-alone protocol reading measured (B-4) or "compiled at the head hospital" | [R rtx5090.yml:33-34] |
| Reimbursement precision: no measure | a per-rule precision set (Japan's 保険 rules) | [R 15 §6.1] |

---

## 9. Cards (to paste into plan 10)

| Card | What | Size | Lane (guess) | Waits for | Proof |
| --- | --- | --- | --- | --- | --- |
| 17-1 | Restate criterion 1 (section 2.3); qualify's thresholds a smaller version of it (with 07's B7-5) | S | Int, H | decision 1 | plan text, `model-change-protocol.md` and a test of the arithmetic agree (59 / 93 / 124 / 149 / 236 / 313 / 299 / 473 / 628) |
| 17-2 | Accuracy report: decided share per criterion kind and rung beside every bound (with 15's B16-16) | S | G, A2 | – | the report on the stored P2b traces prints 138 of 895 for SIGIR |
| 17-3 | MedTxt ja pair score as a standing gate for any model, prompt or quantisation change | S | G | – | a planted worse build fails the gate in CI on recorded answers |
| 17-4 | Shadow-mode protocol for the first site (section 3.3): blind weekly lists, known positives, 40 elusion reads a month, counts-only record | M | G, owner | site agreement | a dry run on the synthetic hospital produces the record |
| 17-5 | Japanese gold kit: writer's guide (11 §5 features), 12+ public jRCT protocols, labelling guide in Japanese, 130 charts, double labels, kappa | L | H, owner, clinicians | decision 3, 07's B7-8 annotation mode | kappa ≥ 0.80 on a 30-chart pilot; manifest sealed by hash |
| 17-6 | Candidate-weights path for VALIDATION boxes: registry row + licence row + pinned folder, refused in PRODUCTION | M | D, G | 17-9 | box-run serves a candidate on a VALIDATION VM; PRODUCTION refuses it |
| 17-7 | Stage H hosted bake-off (section 7.2) and its report | S | Int | 17-9 | `summary.md` and `scores.json` with every candidate and pair |
| 17-8 | Stage G on the box, with the decision rule printed | S | Int, G | 17-6, 17-7, G-4 session | the decision line in the run record |
| 17-9 | Licence register rows for every candidate; Qwen Community License and NVIDIA Open Model License texts read and summarised | S | Int | – | `tools.licence_register --check` green with the new rows |
| 17-10 | Thinking control as a registry field; thinking-only builds refused for judge and verifier unless measured | S | A2 | – | a registry test |
| 17-11 | FP8 judge on tier D: a profile variant and its fit (26 GB) | S | D | stage G | the serving record; MedTxt ja present ≥ 85 % |
| 17-12 | B-4: judge alone protocol reading at 16k / 32k on the 32 GB stand-in | S | D | 13's B-1 | 104 SIGIR protocols compiled with no part split |
| 17-13 | Retrieval for long charts: note-section retrieval sized from real chart lengths (synthetic Japanese charts first) | M | A2 | 17-5 | judge tokens a patient down; decided share not lower |
| 17-14 | Reimbursement precision set: 5 Japanese 保険 rules x 40 synthetic patients, "items met / missing" | M | A2, H | 15's B16-2 | precision lower bound ≥ 95 % per rule |
| 17-15 | Site sample route: the de-identified sample's protocol for the site's ethics review (counts only out) | M | owner, G | decision 3 | the site's approval letter on file |
| 17-16 | Coordinator time and workload in shadow mode: charts read per candidate found, minutes per chart | S | G | 17-4 | the shadow record shows both |

Counts: S 10 (17-1, 17-2, 17-3, 17-7, 17-8, 17-9, 17-10, 17-11, 17-12, 17-16), M 5 (17-4, 17-6, 17-13, 17-14,
17-15), L 1 (17-5).

---

## 10. Decisions only the owner can make

| # | Decision | Recommendation |
| --- | --- | --- |
| 1 | **Criterion 1 as a staged bound**: first site ≤ 5 % (124 eligible, 2 misses), 1.0 ≤ 2 % per language (313, 2 misses), pooled 1 % later | **Yes.** 07's 2 % per language stays the 1.0 target; the first site cannot reach 313 Japanese eligible pairs before go-live |
| 2 | **A coverage floor**: release fails if fewer than 25 % of note cells are decided on the frozen ja set | Yes; without it the bound can be met by saying "unknown" to everything |
| 3 | **Japanese gold**: paid clinician writers on synthetic persons (about 125 h, ¥1.5 to 2.5 million) **and** the site's de-identified sample under its ethics review | Both; writers first (no ethics review needed), the site sample after the site agrees |
| 4 | **Qwen4**: wait, or plan for it? | **Wait.** No open weights, no licence, no date. Test Qwen3.8-27B now; re-check when a Qwen4 model card with a licence appears |
| 5 | **Builds under "community" licences** (Qwen3.8-Flash-Next) | Exclude from the shipped box unless the maker answers in writing; may be used in DEV bake-offs only |
| 6 | **MedGemma** (Health AI Developer Foundations terms) | Exclude for the box |
| 7 | **The Japanese medical gpt-oss-120b** (Apache-2.0, full precision weights) on tiers C and D | Test it if a provider serves it (stage H); on the box only after our own quantisation passes stage G; its card says "not for clinical decision support" — our use (finding candidates for a person) must be stated in the intended use |
| 8 | **5090 for the first site** | **No**: RTX PRO 6000 Max-Q (¥2.80 million card today) |
| 9 | **Spend**: stage H about US$25, stage G about US$16 spot, inside the US$500 cap | Yes, on spot; if the cap counts on-demand rates and the US$117.7 already spent, drop 9c-8 in its favour |

---

## 11. What the owner or the first hospital must supply

1. **Japanese clinician time**: two writers (about 87 h together) and two labellers plus one adjudicator (about 40 h),
   with contracts that assign the synthetic charts to TrialBox.
2. **The list of 12 or more public protocols** (jRCT or ClinicalTrials.gov numbers) the site runs or would run, so the
   gold uses the site's own criterion mix.
3. **The site's ethics route** for a de-identified sample: whom to ask, the form, the expected time (07 and 11 hold the
   legal basis).
4. **The coordinator's agreement** to keep a weekly manual pre-screening list for 1 to 3 studies for 8 to 12 weeks, and
   to read 40 box-excluded charts a month.
5. **The coordinator's current figures** (counts only): candidates a month per study, minutes per chart.
6. **The bed count** (500 to 600 assumed; 13 asks the same) and the yes for the workstation order (decision 8).
7. **The integrator's provider key policy** for stage H (the key stays in the gateway [R `tools/bakeoff_live.py:6-9`]).

---

## 12. What this document did not verify

- **Lind's paper** (JCO Oncology Practice): not opened; only press releases. Its model and deployment are unknown.
- **TREC Clinical Trials 2021 to 2023 overviews**: not opened; the 2023 figure is one participant's table.
- **PRISM/OncoLLM numbers**, **Wong et al.**, the **Morrison review**: abstracts or search pages only.
- **The RECTIFIER randomised trial** (JAMA 2025): from secondary pages; the paper itself not opened.
- **n2c2 2018 inter-annotator agreement** and the SIGIR collection's licence.
- **Japanese studies**: the vendor demonstration and the 2026 joint study are press items without numbers; the
  ANLP paper's Japanese text did not render, so its figures are read from its tables (numbers legible, labels partly).
- **Chinese real-note criterion studies**: none found; CNKI and Wanfang not searched.
- **Qwen4-Max-Preview**: the maker's own announcement page did not render; secondary pages only. That no Qwen4 open
  weights exist is from the maker's hub page as fetched today.
- **Licence texts** of the NVIDIA Nemotron Open Model License, the Health AI Developer Foundations terms, gpt-oss's
  usage policy, Ministral and LFM: not opened.
- **All memory and speed figures for candidates** in section 5 are arithmetic or third-party measurements of other
  models; whether vLLM v0.32.0 serves Qwen3.8 and runs gpt-oss with a JSON schema here is not verified.
- **The MedTxt numbers** use the bake-off prompt through a hosted provider (FP8 or provider quantisation), not the box's
  quoting judge.
- **Clinician hourly rates** in Japan and the shadow-mode volumes are estimates.
- **The 5090 price** is one shop's lowest in stock on one day; the Max-Q price is from an aggregator.

---

## 13. Where this review differs from earlier ones

| Earlier | This review | Why |
| --- | --- | --- |
| 07: 2 % per language, 1 % pooled; "one miss at n = 473" | staged: 5 % first site, 2 % at 1.0; **two misses** allowed | a zero-miss plan fails a good box half the time [M 3]; Japanese eligible pairs cannot reach 313 before go-live |
| 13: Max-Q ¥2,499,980 | ¥2,798,000 (2026-11-13) | price rose [S2 32] |
| 13: the 5090 "cannot read protocols" (8k) | memory allows the judge alone at 16 to 32k with 2 sequences | to be measured (B-4) |
| 11: "SIP-jmed-llm ... not verified" | the university's medical models: Apache-2.0 / MIT, with the 120B variant's card read | [S 29, S 40] |

---

## 14. Change history

- 2026-11-18: first version (B-19).

---

## 15. Measurement log

Scripts kept outside the repository (`b19binom.py` in the agent's scratch folder); outputs in
`/var/tmp/trialbox-0/b19/`. Run with `python3 -I` on the shared 4-core machine.

| # | Command | Result |
| --- | --- | --- |
| 1 | `python3 -I -c` over `eval/medtxt/results/scores.json`: `single[...]` and `both_must_block[...]`, `rate` of positive, negative, suspicious, absent | shipped pair (judge NVFP4 + 9B) ja: present 0.690, negated 0.109 (38 of 349), absent 0.037; judge full precision ja present 0.903, NVFP4 0.827; gpt-oss-120b ja present 0.918, negated 0.215; Ministral 14B 0.865 / 0.215; LFM 0.680 / 0.106; Nemotron 3.5 lightning 0.197 / 0.034; 9B 0.756 / 0.166 |
| 2 | read `eval/bakeoff/results/2026-10-25/summary.md` | as quoted in sections 1.1 and 2.4 |
| 3 | `b19binom.py` (exact Clopper-Pearson by bisection; design effect 1.45; cells as p/c) | the tables of section 2.2; 1 of 41 → UB 11.1 %; 0 of 50 → 5.8 % |
| 3b | the same tail function at p = 0.10 (`python3 -I -c`) | recall lower bound ≥ 0.90: 29 known positives with 0 misses, 46 with 1 |
| 4 | same script, Wilson intervals | 42/43: 0.879 to 0.996; 43/284: 0.114 to 0.198; 138/895: 0.132 to 0.179; 38/349: 0.080 to 0.146 |

---

## 16. Sources (opened 2026-11-18 unless marked)

| n | Source | Link | Terms |
| --- | --- | --- | --- |
| S 1 | Jin et al., Matching patients to clinical trials with large language models, Nat Commun 2024;15:9074 | https://pmc.ncbi.nlm.nih.gov/articles/PMC11574183/ | CC BY 4.0 |
| S2 1 | Healthcare Innovation, "Advocate Health partners with startup Lind", 2026-05-28 | https://www.hcinnovationgroup.com/analytics-ai/artifical-intelligence-machine-learning/news/55380471/advocate-health-partners-with-startup-lind-on-clinical-trial-matching | publisher terms |
| S2 2 | Advocate Health news release, 2026-05-27 | https://www.advocatehealth.org/news/advocate-health-partners-with-ai-startup-to-connect-more-cancer-patients-to-clinical-trials | publisher terms |
| S 3 | Koopman, Zuccon, A test collection for matching patients to clinical trials, SIGIR 2016, doi 10.1145/2911451.2914672 | https://bevankoopman.github.io/papers/sigir2016_clinicaltrials_collection.pdf | ACM; authors' copy |
| S 4 | Stubbs et al., n2c2 2018 track 1, JAMIA 2019, doi 10.1093/jamia/ocz163; Oleynik (0.9100), Vydiswaran (0.9111), Chen (0.9028), Dai (0.8765) in the same issue | PubMed 31562516, 31512729, 31197354, 31300825, 32360937 | abstracts; data under the n2c2 DUA |
| S 5 | Adapting TrialGPT for real-world eligibility screening, JAMIA 2026, doi 10.1093/jamia/ocag006 | PubMed abstract | publisher terms |
| S 6 | Gupta et al., PRISM, npj Digit Med 2024, doi 10.1038/s41746-024-01274-7; arXiv 2404.15549 | https://arxiv.org/abs/2404.15549 | CC BY-NC-ND 4.0 (arXiv) |
| S 7 | Unlu et al., RAG-enabled GPT-4 for clinical trial screening (RECTIFIER), NEJM AI 2024, doi 10.1056/AIoa2400181 | PubMed 42932487 | publisher terms |
| S2 8 | RECTIFIER randomised trial, JAMA 2025, doi 10.1001/jama.2024.28047 (search summaries of the paper and press) | https://jamanetwork.com/journals/jama/fullarticle/2830514 (not opened) | – |
| S 9 | Beck et al., JCO CCI 2020, doi 10.1200/CCI.19.00079; Haddad et al., JMIR Med Inform 2021, doi 10.2196/27767 | PubMed 31977254, 33769304 | publisher terms |
| S 10 | Wornow et al., Zero-shot clinical trial patient matching with LLMs, NEJM AI 2024, doi 10.1056/AIcs2400360 | PubMed 42932459 | publisher terms |
| S 11 | Callies et al., Commun Med 2025, doi 10.1038/s43856-025-01256-0 | PubMed 41275042 | publisher terms |
| S 12 | Prompt-based learning for patient recruitment, Healthc Inform Res 2025, doi 10.4258/hir.2025.31.4.367 | PubMed abstract | publisher terms |
| S2 13 | TREC 2023 CT participant papers (DoSSIER table) | https://trec.nist.gov/pubs/trec32/papers/DoSSIER.C.pdf (search summary) | NIST |
| S 14 | Yuan et al., Criteria2Query, JAMIA 2019 (doi 10.1093/jamia/ocy178); Fang et al. 2022 (ocac051); Park et al., C2Q 3.0, J Biomed Inform 2024 (10.1016/j.jbi.2024.104649) | PubMed 30753493, 35426943, 38697494 | publisher terms |
| S 15 | 診療記録からの構造化と大規模言語モデルによる臨床試験適格性判定 (a university hospital and a Japanese IT vendor), 言語処理学会 第31回年次大会 P3-19, 2025 | https://www.anlp.jp/proceedings/annual_meeting/2025/pdf_dir/P3-19.pdf | CC BY 4.0 (stated on the page) |
| S 16 | Ni et al., JAMIA 2015, doi 10.1136/amiajnl-2014-002887 | PubMed 25030032 | publisher terms |
| S 17 | Calaprice-Whitty et al., Ther Innov Regul Sci 2020, doi 10.1007/s43441-019-00030-4 | PubMed 32008227 | publisher terms |
| S 18 | Gong et al., JCO CCI 2026, doi 10.1200/CCI-25-00262 | PubMed 41512229 | publisher terms |
| S 19 | Parikh et al., Human-AI teaming ..., Nat Commun 2026, doi 10.1038/s41467-026-68873-8 (NCT06561217) | PubMed 41634037 | publisher terms |
| S 20 | Qwen organisation page and Qwen3.8 collection, Hugging Face | https://huggingface.co/Qwen ; https://huggingface.co/collections/Qwen/qwen38 | hub terms |
| S2 21 | Qwen4 status pages (newszest 2026-11; yottalabs; alphasignal 2026-11-11) | https://www.newszest.in/2026/11/qwen4-4-models-named-0-open-weights.html ; https://alphasignal.ai/news/alibaba-launches-qwen4-max-with-agent-first-coding-and-1m-token-support | – |
| S2 22 | Qwen4-Max-Preview summaries | https://ai-tldr.dev/releases/qwen-qwen4-max-preview/ | – |
| S 23 | Qwen3.8-27B model card | https://huggingface.co/Qwen/Qwen3.8-27B | Apache-2.0 |
| S 24 | Qwen3.8-Flash-Next model card | https://huggingface.co/Qwen/Qwen3.8-Flash-Next | qwen-community-1.0 |
| S 25 | Qwen3.8-Flash-Next LICENSE | https://huggingface.co/Qwen/Qwen3.8-Flash-Next/blob/main/LICENSE | the licence itself |
| S 26 | Gemma 4 12B model card | https://huggingface.co/google/gemma-4-12B-it | Apache-2.0 |
| S 27 | Gemma 4 26B-A4B model card (with the 31B table) | https://huggingface.co/google/gemma-4-26B-A4B-it | Apache-2.0 |
| S2 28 | gpt-oss: no successor (secondary, 2026-10) | search summary | – |
| S 29 | Weblab-MedLLM-gpt-oss-120b model card | https://huggingface.co/weblab-LLM-M/Weblab-MedLLM-gpt-oss-120b | Apache-2.0 |
| S 30 | LLM-jp-4.1 32B-A3B thinking model card | https://huggingface.co/llm-jp/llm-jp-4.1-32b-a3b-thinking | Apache-2.0 |
| S2 31 | gazlog GPU daily chart, data to 2026-11-18 | https://gazlog.jp/entry/gpu-daily-charts/ | – |
| S2 32 | price-rank.com, RTX PRO 6000 Blackwell Max-Q, 2026-11-13 (search summary); kakaku.com item page did not render | https://kakaku.com/item/K0001715624/ | – |
| S 33 | TrialMatchAI, Nat Commun 2026, doi 10.1038/s41467-026-70509-w | PubMed abstract | publisher terms |
| S 34 | Hepatopathy pre-screening pipeline, BioData Min 2025, doi 10.1186/s13040-025-00458-5 | PubMed abstract | CC BY (BMC; not opened) |
| S 35 | EC2Seq2Sql, PLoS One 2026 | PubMed abstract | CC BY (PLoS; not opened) |
| S 36 | Qwen3.6-35B-A3B model card; Qwen3.6 collection | https://huggingface.co/Qwen/Qwen3.6-35B-A3B | Apache-2.0 |
| S 37 | Google organisation page, Hugging Face | https://huggingface.co/google | hub terms |
| S2 38 | Gemma 4 launch coverage (no Gemma 5) | search summary | – |
| S2 39 | MedGemma 1.5 coverage and model-card summary | search summary | – |
| S 40 | University of Tokyo press release, 2026-07-08, medical LLMs and safety tools | https://www.t.u-tokyo.ac.jp/hubfs/press-release/2026/0708/001/text.pdf | press release |
| S 41 | LLM-jp organisation page | https://huggingface.co/llm-jp | hub terms |
| S 42 | NVIDIA Nemotron Nano 9B v2 Japanese model card | https://huggingface.co/nvidia/NVIDIA-Nemotron-Nano-9B-v2-Japanese | NVIDIA Nemotron Open Model License (not opened) |
