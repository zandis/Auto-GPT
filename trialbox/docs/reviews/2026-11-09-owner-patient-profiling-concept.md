# Patient Profiling — the keystone capability of Anamnesis
### A detailed report
**For:** Chang-Fu Kuo · Center for AI in Medicine, CGMH · Nov 2026

---

## 1. The idea, in one line

> **Patient profiling is the capability of constructing, for every patient, a complete, multidimensional, continuously-updated, machine-readable representation — one that a clinician can read as a dossier and a model can consume as a vector — from which finding, forecasting, matching, and recontact all follow.**

Everything else Anamnesis does is a *use* of a profile. The finder reads the part of a profile that the chart doesn't say out loud. A trial match reads the eligibility layer. An external-control arm reads the forecast layer. Recontact acts on the gap layer. Precision therapy reads the biological layer. Population health is the arithmetic over a population of profiles. So "patient profiling" is not one feature among many — it is the **substrate feature**: the twin, rendered one patient at a time.

A profile in Anamnesis has two faces that must coexist:

- **The symbolic profile** — a structured, auditable dossier grounded in OMOP/FHIR: who the patient is, what is documented, what is *conspicuously missing*, the exact facts and counts. This is what a regulator or a clinician trusts.
- **The learned profile** — the dense embedding(s) produced by the foundation model over the patient's full multimodal trajectory. This is what enables similarity, subtyping, and prediction.

Neither replaces the other. The symbolic face is truth; the learned face is inference. They are bound by the patient's `IDCODE`, so every learned claim is traceable back to an exact record — the symbolic↔learned ID-duality that is the spine of the whole platform.

---

## 2. Why profiling is the keystone (the capability map)

| Platform capability | …is this layer of the profile, used this way |
|---|---|
| **Find undiagnosed/undertreated patients** | the **gap layer** — what the trajectory implies but no code records (your `ipf_bi`, the RA biologic-gap finder) |
| **Trial feasibility & sizing** | the **eligibility layer** summed over a population (your `computable_eligibility`, `recruitment_feasibility`) |
| **Patient–trial matching** | the eligibility layer, per patient, with verbatim grounding (your `llm_trial_matcher`) |
| **AI external control arm** | the **forecast layer** — the twin's predicted standard-of-care trajectory (Unlearn/PROCOVA-style) |
| **Precision therapy / companion-Dx** | the **biological layer** (HLA/PGx/variant) × the **response layer** |
| **Risk stratification / care gaps (population)** | the **risk layer** over the population of profiles |
| **Pharmacovigilance / RWE** | the response + trajectory layers, as cohorts |
| **Synthetic data / simulation lab** | sampling the **distribution** of profiles (DP-synthetic) |
| **Cohort-by-example** | the **similarity layer** — a profile's neighborhood in embedding space |

Read the table top to bottom and the thesis is plain: build the profile well, and each product is a projection of it, not a separate system.

---

## 3. Anatomy of an Anamnesis patient profile

A profile is layered. Each layer answers a different question, is computed differently, and carries its own provenance and uncertainty.

| Layer | Question it answers | How it's computed | Grounded in your work |
|---|---|---|---|
| **Identity & context** | Who is this (de-identified)? | `歸戶主檔` → OMOP `person` / FHIR `Patient`; `IDCODE` only | the real linkage key |
| **Longitudinal trajectory** | What has happened, in order? | visit/era-structured event sequence (dx, drugs, labs) from OMOP | the 2001–2026 CGRD depth |
| **Personal baseline (setpoint)** | What is *normal for this person*? | per-analyte personal setpoints + reference-change values | **`hematologic_setpoints`** — individual labs distinguishable from ~98% of others |
| **Multimodal signals** | What do the images/waveforms/text/genome say? | encoder embeddings (MONAI CT, 42-model ECG, pathology-FM, genomic-FM, clinical-LM) as soft tokens | your 50+ MONAI + ECG platforms as encoders |
| **Phenotype** | What does this patient *have* (incl. latent subtype)? | computed phenotypes (ATLAS-expressible) + unsupervised subtypes from the learned profile | `das_nlp`, `ctd_ild_nlp`, `renal_egfr_trajectory` |
| **Risk & forecast** | What is likely next? | time-to-event / next-event heads on the FM | `renal_egfr_trajectory` (ESRD), `jaki_cv` (MACE) |
| **Gap** | What is true but unrecorded? | finder heads: predicted condition/eligibility with **no** supporting code | **`ipf_bi`** (UIP on CT, no IPF code), RA biologic-gap |
| **Eligibility** | Which trials/criteria does this patient computably meet? | criteria engine over structured + report-coded + NLP fields | `computable_eligibility`, `llm_trial_matcher` |
| **Biological** | What is the mechanistic substrate? | biobank → WGS → variant/HLA/PGx linked by `IDCODE` | Illumina WGS, HLA/PGx, AMR isolates |
| **Similarity** | Who looks like this patient? | nearest neighbors in pgvector embedding space | cohort-by-example |

The crucial, non-obvious layers are **setpoint**, **gap**, and **eligibility**. Most "patient representation" work stops at trajectory + risk. Those three are where Anamnesis's data advantage (longitudinal, multimodal, recontactable) turns into something no one else can compute.

---

## 4. How a profile is produced (the pipeline → a concrete object)

Profiling is the *output* of the pipeline already specified in the master plan, assembled per patient:

```
OMOP/FHIR record  ──►  concept_id tokenizer  ──►  foundation model  ──►  heads (gap/risk/phenotype)
      │                 (+ encoder soft tokens:        │                         │
      │                  CT, ECG, path, genome, text)  ▼                         ▼
      └──────────────────────────────────────►  pgvector embedding         derived layers
                                                        │                         │
                                                        └────────► PROFILE ASSEMBLER ◄────── setpoint stats,
                                                                        │                    biobank/WGS joins,
                                                                        ▼                    eligibility engine
                                                                 profile object (keyed by IDCODE)
```

The deliverable artifact — the thing the rest of the system reads — is a versioned **profile object**:

```json
{
  "idcode": "<40-char hash>",              // the only identifier; real identity stays in the vault
  "as_of": "2026-11-09",                    // profiles are time-stamped; recomputed as data arrives
  "model_version": "fm-0.3 / vocab-2026.1", // every layer carries the version that produced it
  "symbolic": { "omop_cohorts": [...], "documented_dx": [...], "exact_facts": {...} },
  "embedding": { "vector": "<pgvector ref>", "neighbors": ["<idcode>", ...] },
  "setpoint":  { "CRP": {"personal_mean":..,"RCV":..}, "eGFR_slope": .. },
  "phenotype": { "computed": ["RA-seropos-erosive"], "latent_subtype": "cluster-7" },
  "forecast":  { "ESRD_2yr": {"p":0.18,"calib":"..."}, "MACE_1yr": {...} },
  "gap":       [ {"suspected":"IPF","evidence":"CT:UIP-pattern","no_code":true,"confidence":..} ],
  "eligibility": [ {"trial":"NCT...","status":"likely","unmet":["DAS28≥5.1 @screen"]} ],
  "biological": { "HLA": [...], "pgx": [...], "variants_fhir": "<ref>" },
  "provenance": { "sources":[...], "gates_passed":[...], "audit":"<ref>" }
}
```

Two properties make this trustworthy rather than a black box. First, **every layer is traceable**: a `gap` entry points to the CT report that triggered it; a `forecast` to the model version and its calibration. Second, **the profile is a projection, never a replacement** for the record — the symbolic plane remains the source of exact truth, so a wrong embedding can never silently become "fact."

---

## 5. The state of the art — and where Anamnesis departs from it

Patient representation has become one of the most active areas in clinical ML, and the 2025–2026 work validates the architecture while leaving the hard, valuable parts open.

**Representation learning is converging on exactly your design.** The newest EHR foundation models unify, in one model, the three capabilities a profile needs — feature representation, zero-shot prediction, and synthetic generation — and do it with explicit temporal tokenization of the patient timeline. <cite index="3-1,8-1">CEHR-GPT/XGPT presents a unified EHR foundation model supporting feature representation, zero-shot prediction, and synthetic data generation within a single architecture.</cite> <cite index="10-1">It encodes patients' dynamic timelines with a time-token framework and reports state-of-the-art performance across risk prediction, patient representation, and synthetic generation, enabling cohort discovery and outcome forecasting without task-specific retraining.</cite> Most consequentially for Anamnesis, the field is moving to make the vocabulary OMOP-native so a model is portable across institutions: <cite index="5-1,9-1">MedRep learns medical-concept representations on the OMOP common data model — vocabulary-agnostic and able to operate at any institution with an OMOP CDM database — by enriching each concept with an LLM-generated definition and the graph ontology of the OMOP vocabulary.</cite> This is precisely the `concept_id`-native tokenizer decision already in your spec; the literature has independently arrived at it.

**Phenotyping is the "what does this patient have" layer, and its two jobs are well defined.** <cite index="11-1">Computational phenotyping has two primary applications — discovering and stratifying new subtypes (largely unsupervised), and discovering phenotypes to improve classification under existing disease definitions (supervised) — both seeking data-driven phenotypes rather than manual clinical descriptions.</cite> The practical bottleneck is labels: <cite index="20-1">phenotyping typically depends on gold-standard labels from manual chart review, with silver-standard proxies used to avoid time-consuming review.</cite> Your **benefit-gated recontact loop is, in effect, a gold-label factory** — physician-adjudicated confirmations feeding back — which is the scarce input the whole field is short of. <cite index="17-1">NLP-based phenotyping already spans diagnosis categorization, novel phenotype discovery, clinical-trial screening, pharmacogenomics, and adverse-drug-event detection</cite>, which is the exact span of your `das_nlp`/`ctd_ild_nlp`/matcher units.

**Stratification and similarity at scale are proven — on single modalities.** <cite index="30-1">Landi et al. transformed the trajectories of 1,608,741 patients across 57,464 clinical concepts into low-dimensional vectors (ConvAE) and used them to stratify multi-disease and disease-specific cohorts at scale.</cite> <cite index="27-1">Transformer-based patient embeddings have since been shown to enable both stratification and progression analysis.</cite> Patient-similarity networks are attractive for precision medicine precisely because they mirror clinical reasoning and stay interpretable: <cite index="24-1">in patient-similarity networks, patients are clustered or classified by similarity across features including genomic profiles — analogous to standard medical diagnosis, performant, interpretable, and privacy-preserving.</cite> But these are mostly structured-data or notes-only; the multimodal, biologically-grounded profile is still open.

**The clinical "digital twin" framing is maturing, and the field now distinguishes the profile from the simulation built on it.** <cite index="34-1">A patient medical digital twin is defined as a high-resolution, data-driven computational replica of an individual, continuously updated from multimodal data to simulate progression and forecast therapy response.</cite> The practical point of a twin is counterfactual testing: <cite index="40-1">rather than relying solely on population guidelines, a physician could test treatment options on a patient's digital twin before a real-world decision — which requires the model to expose its limitations and calibration for adoption.</cite> And foundation models are now the engine of the trial-facing version of this: <cite index="39-1">a 2026 IQVIA brief describes how foundation models advance digital patient simulation and distinguishes external comparators, synthetic controls, digital twins, synthetic twins, and synthetic data in clinical development.</cite> Regulators are moving in parallel: <cite index="33-1">digital twins are being used as virtual control arms, supported by the FDA's AI credibility framework (Jan 2025) and the FDA/EMA "Guiding Principles of Good AI Practice" (Jan 2026), with examples including Johns Hopkins' FDA-approved virtual-heart pilot and Phesi's cGvHD digital twin built from >2,000 virtual patients.</cite>

**Where Anamnesis departs.** Every strand above is single-threaded — representation *or* phenotyping *or* similarity *or* twin, and almost always one modality on a Western cohort. Anamnesis's profile is differentiated on six axes simultaneously, and the combination is the moat:

1. **Multimodal** — imaging, ECG, pathology, genomics, and text in one profile, via your existing encoders, not codes alone.
2. **Recontactable** — the profile links back to a real patient under governance, so a profile can *act* (the gap layer → benefit-gated recall). No public dataset can do this.
3. **Biologically grounded** — biobank + WGS + HLA/PGx attach a mechanistic layer to the statistical one.
4. **Sovereign & Han-Chinese** — a population and ancestry under-represented in every model above; the profile's baselines differ, and that difference is itself the insight.
5. **Standards-native** — OMOP `concept_id` profiles are portable and federatable, exactly the direction MedRep/CEHR-GPT are taking the field.
6. **Longitudinal** — 25 years of depth, so trajectory and setpoint layers are real, not snapshots.

---

## 6. Your own work already builds the profile — Anamnesis unifies it

The strongest evidence that this is the right keystone is that your thirteen umbrella-IRB analyses are *already* each constructing one layer of the profile. They have simply never been assembled into one object per patient.

| Your research unit | The profile layer it builds |
|---|---|
| `hematologic_setpoints` | the **personal-baseline / setpoint** layer (the per-person biometric) |
| `renal_egfr_trajectory` | the **trajectory + forecast** layer (eGFR slope → ESRD) |
| `trajectory_phewas` | a **trajectory feature** (within-person variability as signal) |
| `das_nlp`, `ctd_ild_nlp` | the **phenotype** layer, from free-text SOAP |
| `gout_ult`, `jaki_cv` | the **treatment-response + risk** layers |
| `ipf_bi` | the **gap** layer (the undiagnosed-finder template) |
| `foundation_model` | the **learned-embedding** layer (and its no-GPU floor) |
| `computable_eligibility`, `recruitment_feasibility`, `llm_trial_matcher` | the **eligibility** layer |
| `amr_antibiogram` | a **biological** layer (organism/resistance, for the sepsis/AMR line) |

Anamnesis's claim, concretely, is: *stop building these as thirteen separate studies and assemble them as one profile per patient, recomputed as data arrives, and every study becomes a live service.*

---

## 7. The actionable twist no one else has: the gap profile + benefit-gated recontact

Most profiling tells you about the patient as recorded. The distinctive Anamnesis move is to profile **what the data implies but the record never states** — the gap layer — and then, uniquely, to be able to *act* on it.

The gap layer is the finder: a UIP pattern described in a CT report with no IPF code (your ~3,638); seropositive erosive RA with no biologic exposure; an eGFR trajectory heading to ESRD with no nephrology contact. Computed across the population, the gap layer is a ranked list of patients the system has, in effect, under-served.

What makes it more than analytics is the bridge back to the person, under hard constraints: a gap entry becomes a candidate for recontact **only** inside the benefit-eligible set, only on an active IRB protocol, only with treating-physician co-sign, only if not opted out — and never to improve the model for its own sake. That governance is what separates "profiling for benefit" from "profiling" in the pejorative sense, and it is the ethical line the platform must hold visibly. The payoff is a loop: the gap layer finds the patient, the recall confirms the label, the label sharpens the next profile.

---

## 8. What profiling lets the system do (in depth)

**For the twin (per-patient care).** A clinician opens a patient and sees the assembled dossier: documented problems, computed phenotypes and likely subtype, personal lab setpoints (so an "in-range" value that is abnormal *for this person* is flagged), forecasts with calibration, suspected gaps with evidence, and look-alike patients. This is decision support — and therefore SaMD the moment it drives a decision, which sets the regulatory bar (§9).

**For trials.** The eligibility layer summed over the population *is* feasibility and sizing; per patient it *is* matching, with verbatim grounding so every determination is auditable. The forecast layer is the substrate for an AI external-control arm — the twin's predicted standard-of-care course as a virtual comparator — which is exactly the use regulators are now entertaining. Together these are your "smaller + full" trial bundle, expressed as profile operations.

**For precision therapy.** The biological layer crossed with the response layer is companion-diagnostic territory: who carries the HLA/PGx marker *and* has the trajectory that predicts benefit or harm. The Han-Chinese grounding matters here specifically (e.g., HLA risk alleles with APAC-specific frequencies).

**For RWE & pharmacovigilance.** Cohorts of profiles, defined by the eligibility/phenotype layers and followed through the trajectory/response layers, are reproducible OMOP cohorts — portable into the Sentinel/DARWIN-style ecosystem.

**For population health.** The risk and gap layers, aggregated, are a care-gap and risk-stratification map for the health system — the sovereign/public-good use.

**For partners (the simulation lab).** A profile, de-identified and DP-protected, is what an external researcher queries, stratifies, or simulates against — bring-compute-to-data, results out. The synthetic tier is sampled from the profile distribution.

---

## 9. Honest caveats and risks

**A rich profile is re-identifying — that is the point and the danger.** The more complete the profile, the more it is PHI, and embeddings can be inverted or membership-attacked. Profiling does not provide privacy; the governance plane does (de-identification, differential privacy on outputs/synthetic, federated/confidential compute, the gate). This must be stated plainly, not assumed.

**A profile is a projection, not the patient.** Each learned layer is inference with uncertainty; the symbolic plane remains truth. Exact facts, counts, and regulatory cohorts are computed symbolically, never read off the embedding.

**Selection and informed-presence bias are baked into CGRD.** Coverage is ~10% of Taiwan and skews to sicker, multi-hospital patients; a "gap" may reflect care elsewhere, not a true miss. Profiles must carry this caveat, and gap findings need negative controls and (where possible) external checks before they drive recall.

**Measurement heterogeneity corrupts the baseline layer.** The lab unit problem you identified (mixed mg/dL and mmol/L in one field) directly poisons the setpoint and trajectory layers if unhandled; per-analyte normalization is a prerequisite, not a nicety — your `calibrate_pharm` positive control is the guardrail.

**Validation and calibration gate clinical use.** A forecast layer without calibration, or a finder without a leakage check and negative controls, is not deployable. The model registry, drift monitoring, and the FDA AI-credibility mapping are part of profiling, not an afterthought.

**Profiling for decisions is regulated, and profiling for harm is prohibited.** Any layer that informs a clinical decision is SaMD (TFDA first). And the benefit-gate is not optional ethics gloss — the whole apparatus must be demonstrably incapable of surfacing a patient for exclusion or harm. Profiling earns trust only if it visibly serves the patient.

---

## 10. Build path (it rides the plan you already have)

Profiling is not a new workstream; it is the assembly point of the existing phases.

- **P0–P1 (now):** the `concept_id` tokenizer + the small structured FM already produce the **embedding, trajectory, phenotype, risk, and gap** layers for the RA/IPF verticals. Add a thin **profile assembler** that writes the profile object (above) per `IDCODE`, plus the **setpoint** layer (your `hematologic_setpoints` method) and the **eligibility** layer (your criteria engine). That alone is a demonstrable, differentiated per-patient profile.
- **P2:** attaching the MONAI/ECG/pathology/genomic encoders adds the **multimodal** layer; the biobank/WGS work adds the **biological** layer; recontact makes the gap layer *actionable* and starts the gold-label flywheel.
- **P3:** the simulation lab exposes profiles (de-identified/synthetic) to partners; the forecast layer becomes the external-control product; federation lets profiles be queried across hospitals via shared `concept_id`.

The single new artifact to introduce is the **versioned profile object** and the assembler that writes it — register it as a subsystem (`int.profile`) in the control system, with the profile object's completeness tracked per layer.

---

## 11. Recommendation

Make **"one profile per patient"** the organizing deliverable of the intelligence plane, and treat the thirteen research units as the layers of that profile rather than as separate papers. It reframes the platform's story from "a model" to *a living profile of every patient that you can read, question, forecast, and act on* — which is both the clearest articulation of the North Star and the thing none of the 2025–2026 field has, because none of them is simultaneously multimodal, biologically grounded, recontactable, and sovereign.

The concrete next step is small and high-leverage: specify the **profile object schema** (§4) as the contract, add the **profile assembler** as subsystem `int.profile` in the registries, and stand up the **setpoint + gap + eligibility** layers on the RA/IPF cohort you are already building. That turns profiling from a concept into the running core of Anamnesis.

---

### Sources
- CEHR-GPT/XGPT — unified EHR foundation model (representation + zero-shot prediction + synthetic generation; temporal tokenization; OMOP): arXiv:2509.03643
- MedRep — OMOP concept representation for general EHR foundation models (vocabulary-agnostic; graph ontology of OMOP vocabulary): arXiv:2504.08329
- SerialBEHRT — temporal serialization for richer patient representations: arXiv:2510.13843
- Deep EHR survey — computational phenotyping's two applications: arXiv:1706.03446
- Yang et al. — ML for EHR phenotyping (gold/silver labels): PMC9846699
- Zeng & Luo — NLP for EHR-based computational phenotyping (application span)
- Landi et al. — deep representation learning for patient stratification at scale (1.6M patients): arXiv:2003.06516 / npj Digit Med 2020
- Transformer patient embedding for stratification + progression: npj Digit Med 2025 (s41746-025-01872-z)
- Patient similarity networks for precision medicine (SNF/netDx): J Mol Biol 2018
- Patient Medical Digital Twin (PMDT) — definition: emergentmind topic (2026)
- Stanford Medicine — medical digital twins (five components; test-before-decide): Jun 2025
- IQVIA — foundation models for digital patient simulation; comparator/twin/synthetic distinctions: Jul 2026
- Digital twins in clinical trials — virtual control arms; FDA AI credibility (Jan 2025), FDA/EMA Good AI Practice (Jan 2026): intuitionlabs 2026
