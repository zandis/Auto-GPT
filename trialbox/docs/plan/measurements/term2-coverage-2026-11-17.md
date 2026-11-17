# Drafted concepts the terminology resolves, before and after TERM-2 (measured 2026-11-17, D-1116)

**What was measured.** Of the concepts that the compiler drafted from launch P1b's public ClinicalTrials.gov
protocols, how many `Terminology.map` resolves without the model and without the synonym dictionary. This is lane E's
measure of TERM-1 (D-858, #639 of 2026-11-16, 11:58 and 12:49 UTC).

**How.** The code is commit `8b1f527f` (branch `claude/lane-h-5-term2` on master `fa639b61`). The input is
`work/raw-traces.json` of launch P1b's `sigir.tgz`. The archive is not committed: sha256 `667d92f5...`, and the file
`12cd4580...`. It was unpacked into an empty scratch folder and read as data only.

```
python -m tools.terminology_coverage <raw-traces.json>                      # the shipped tables only
python -m tools.terminology_coverage <raw-traces.json> --installed <DIR>    # plus what the loader put in DIR
```

There are 132 `extract_criteria` calls and 1,533 candidates. The 1,273 that are not demographic are counted. The
4 call outputs that are not JSON give no candidates.

| Domain | Concepts | Before TERM-1 (commit `828cb3d3`) | TERM-1, master `fa639b61` ("before" for TERM-2) | After TERM-2, committed data only | After TERM-2, plus the committed NHI sample rows loaded |
| --- | --- | --- | --- | --- | --- |
| condition | 588 | 47 | 255 | 255 | 255 |
| observation | 308 | 5 | 5 | 5 | 5 |
| medication | 177 | 6 | 6 | 6 | 6 |
| procedure | 145 | 0 | 0 | 0 | 3 |
| encounter | 51 | 0 | 0 | 0 | 0 |
| claim | 4 | 0 | 0 | 0 | 0 |
| **all** | **1,273** | **58 (4.6 %)** | **266 (20.9 %)** | **266 (20.9 %)** | **269 (21.1 %)** |

**Reading it.**

- **The "before" is 266, not 270.** The tool reproduces lane E's 58 exactly, on the tree before TERM-1. 270 (235
  conditions, 29 observations) was lane E's first draft (#639, 11:58). Lane E's own figure for TERM-1 as built is
  266, with 255 conditions (#639, 12:49), and that is what master gives. TERM-1's step 2d is for conditions only,
  so the 24 diagnoses drafted as observations that the draft counted are not resolved.
- **The "after" does not move with committed data alone.** TERM-2 adds loaders, not data. With nothing loaded, the
  mapper answers exactly as before (a test holds it). No full NHI list, ICD-10-PCS release, LOINC table, WHO ICD-10
  copy, ATC index or site list was available offline, and none was fabricated.
- **The last column only shows the path working.** It loads the public NHI rows committed as test samples
  (`tests/fixtures/refdata`: 1 drug, 7 service codes) through `nhi-drugs` and `nhi-services`. The +3 is "hemodialysis"
  three times, resolved to NHI 58001C. It is not a coverage figure, and the match is weaker than it looks. 58001C is
  one inpatient haemodialysis session (血液透析（一次）- 住院). It answers without review only because the 7-row sample
  holds no other item of that name. With the full list, every item named "Hemodialysis" answers together, for review
  (D-1114 point 3, after the class B review). Whether other items share the name was not checked. The sample's drug
  (flupentixol) left the list in 2014, so an ended code answers nothing. The figures were measured again after that
  review, on commit `f6a90903`; they are unchanged.

**What remains, and which install-time system would answer it. NOT MEASURED.** These are counts of the names that
remain, read by eye from the tool's `--json` output. No licensed table was loaded, so no "after" figure for them
exists.

| Domain | Unresolved | What they are (examples from the output) | Install-time system that would answer most of them |
| --- | --- | --- | --- |
| condition | 333 (300 distinct) | qualified or compound names: "acute coronary syndrome", "active pulmonary tuberculosis", "allergy to oxytocin", "advanced cancer" | the site's ICD-to-local list (site-list), and WHO ICD-10 titles where ICD-10-CM lacks a name; many need the model's step, which is lane A2's |
| observation | 303 (264 distinct) | labs ("absolute neutrophil count", "alkaline phosphatase", "alanine amino transferase") and many non-lab states ("ability to sign consent") | LOINC (named person's licence); a site lab list; non-lab states are not terminology |
| medication | 171 (148 distinct) | ingredients ("acetazolamide", "amoxicillin") and classes ("antibiotics", "anticoagulants", "arb") | ATC index (classes and substances) and the full NHI drug list (ingredient to ATC) |
| procedure | 145 (142 with the NHI samples; 123 distinct) | "bronchoscopy", "cabg", "carotid endarterectomy", "acupuncture", also CPT numbers ("45380") | NHI service and order codes (full list) and ICD-10-PCS; their names seldom equal a trial's word, so a synonym layer would also be needed |
| encounter, claim | 55 | mostly diagnoses or events drafted under the wrong domain ("atrial fibrillation", "hospitalization") | none: a domain question for the compiler (lane A2), plus the site's department list |

**Limits.** Every match here is an exact name. A licensed table would add only the names that equal its own words
(a LOINC long or short name, an ATC level name, a PCS description). LOINC components and NHI ingredients are matched
too, and those matches go for review. The model's `concept_map` candidates still come from the curated rows only.
That call site is lane A2's and is not changed here.
