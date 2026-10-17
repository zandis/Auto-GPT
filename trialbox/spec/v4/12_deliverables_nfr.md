## 12. Pharma deliverables

This section defines the **TrialBox Deliverable Standard (TDS) 1.0**: six reports, with the analyses behind them and the renderer that produces them. The six reports are:
- four sponsor packs;
- the internal PI pre-screening report;
- an RWE cohort-characterisation report.

TDS closes R3-36 (no report standard), R3-37 (no deliverables during conduct) and R3-38 (no sponsor exchange formats).

No industry-standard feasibility report exists:
- TransCelerate SIP forms describe site capability only;
- ASCO 2021 asks for standardisation but publishes no template;
- CDISC has no feasibility-report standard *(uncertain: none found)*.

TDS is therefore TrialBox's own convention, borrowing from the standards in §12.2.8. It is versioned: data objects (§6) carry `tds_version`, and a TDS change is a change under §18.

### 12.1 Principles and catalogue

**Principles (normative).**

1. **One engine.** Every number comes from deterministic functions in `libs/tb_analytics` over the cascade, pipeline and snapshot result tables. No renderer computes a number.
2. **Disclose before render.** Renderers receive only data objects that have passed disclosure control and the privacy accountant (§7). Figures are drawn from suppressed tables, never from raw data.
3. **Honest uncertainty.** No estimate is shown without its interval. The computable count, the chart-review-adjusted estimate and the unknown share always appear together.
4. **Numbers by placeholder** (AI-07, carried over).
5. **Machine-readable twin.** Every table has a dictionary-backed machine form, and every figure has its data table.
6. **Provenance on every page.** Every page footer carries the lineage id.
7. **Site-owned release.** Every release passes G2 (G6 for regulated records, §11), goes through the outbox, and is recorded in the privacy ledger.

| ID | Deliverable | Audience | Class (§7) | Trigger | Gate | Cadence | First |
| --- | --- | --- | --- | --- | --- | --- | --- |
| DL-1 | **Feasibility pack** | Sponsor/CRO feasibility and site-selection teams | Aggregate | Ruleset frozen at G1; `FEAS` or a questionnaire (M3) | G2 | Per protocol or data cut | MS1 |
| DL-2 | **Accrual pack** | Sponsor study manager or CRA; research office | Aggregate | Study `recruiting`; 1st working day of the month | G2 | Monthly | MS4 |
| DL-3 | **Site performance pack** | Sponsor site-selection and clinical operations | Aggregate, confidential between sponsors | Sponsor request; study close (M9) | G2 | On request | MS4 |
| DL-4 | **Data deliverables** | Sponsor data management, CRA, hospital researchers | D2 or D4 | M8 workflows; dataset request | G6, or G2 + privacy officer | Per item | MS5 |
| DL-5 | **PI pre-screening report** (internal) | PI, sub-investigators, delegated CRCs | D4 | Pre-screen run or clinic-day portfolio (M4) | None (G3 for decisions) | Weekly or nightly | MS2 silent, MS3 live |
| DL-6 | **RWE cohort characterisation** | Medical affairs, protocol design, HEOR, research office | Aggregate | Frozen analysis protocol | G2 if external | Per protocol | MS5 |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| RPT-01 | Site-derived numbers MUST leave the hospital only as DL-1, DL-2, DL-3, DL-4 or an externally released DL-6. Ad-hoc exports MUST NOT be sent. | T | MS1 |
| RPT-02 | All quantities MUST be computed by `libs/tb_analytics`. A quantity that appears in two deliverables with the same snapshot, ruleset and disclosure profile MUST be identical in both (`tests/golden/reports/test_consistency.py`). | T | MS1 |
| RPT-03 | Each deliverable MUST exist first as a typed data object (§6; `schemas/deliverable_<type>.schema.json`). Renderers MUST accept only the frozen, hashed `DisclosedDeliverable` type. | T | MS1 |
| RPT-04 | DL-5 MUST be addressable only to recipients in the study's delegation log. The outbound DLP check (§14) MUST block any external send and log it as a security event. | T | MS2 |

### 12.2 Common elements

#### 12.2.1 Header and provenance blocks

**Header (first page, and repeated in `manifest.json`).** The header carries:
- deliverable type and TDS version;
- deliverable id (ULID) and version;
- protocol id, version and amendment;
- sponsor and recipient organisation (never a personal address);
- site, site code and PI;
- snapshot id and data-cut date;
- look-back window and index definition;
- the generated timestamp, taken from the manifest and never from the clock at render time;
- language;
- status (`draft`, `released`, or `superseded by <id>`).

**Provenance block.** Modelled on RECORD items 12–13 and the HARPER data-source section. It is a fixed section near the end of the deliverable; its lineage id also appears in every page footer.

| Element | Content |
| --- | --- |
| Lineage id | Resolves to the OpenLineage graph: source batches → L0–L4 → snapshot → ruleset → run → object → files (§5) |
| Data fitness | DQ scorecard grade per domain used, reconciliation status, completeness of the variables used |
| Ruleset | `<study>/v<semver>`, IR version, canonical hash, CQL≡SQL equivalence result, G1 id |
| Code lists | ValueSet canonical URLs and versions; terminology editions |
| Cascade metrics | n per stage S0–S5 (rounded); share of judgements involving a model; sample sizes |
| Recall certificate | Certificate id; elusion upper bound; known-positive lower bound **with its named population** (AI-13) |
| Models | Per model-assisted step: role, build id and SHA, prompt version, data class, route, model card reference (§8) |
| Analyses | `tb_analytics` function names, versions and method references |
| Disclosure | Profile and version, privacy-ledger entry, number of suppressed cells, differencing-check result |
| Approval | Gate id, approver's printed name and role, meaning, record SHA-256, UTC time |
| Reproduction | Manifest hash; `trialbox deliverable regenerate <id>` |
| AI disclosure | `disc.ai` (§12.2.2) |

#### 12.2.2 Standard disclosures

Disclosures are versioned templates (`libs/tb_reports/templates/disclosures/<id>@<ver>.<locale>.txt`), cited by id and version. Editing one is a G5-class change (§18), because it changes what the site asserts.

| Id | In | Text (en; zh-TW and ja kept in parallel) |
| --- | --- | --- |
| `disc.emr_counts` | DL-1, 2, 3, 6 | "Counts derive from routinely collected medical records at {site} and reflect documentation, not clinical eligibility. Criteria marked partially or not computable need chart review." |
| `disc.aggregate` | External | "Aggregate results only; no patient-level data left the hospital. {profile_sentence}" |
| `disc.profile.sponsor` | `dc.sponsor` | "Counts 1–10 are shown as '<11'; other counts are rounded to the nearest 5; percentages are computed before rounding; totals may not equal the sum of their parts." |
| `disc.ai` | All | "AI-assisted pre-screening is used at this site; software proposes and investigators decide eligibility. Model-assisted steps: {ai_steps}. Validation: {validation_ref}. {recall_statement}" |
| `disc.accuracy` | DL-1 | "Record-derived counts can differ from manual estimates in either direction; prefer the chart-review-adjusted estimate and its interval." (Basis, not printed: in the EHR4CR ten-trial comparison, record counts beat the manual process in 3 trials and were worse in 6; *BMC Med Res Methodol* 2015.) |
| `disc.forecast` | DL-1, 2 | "Forecasts are probabilistic: P10–P90 means a 10 % chance of fewer and a 10 % chance of more. Past forecasts are scored in the calibration record." |
| `disc.rwe_descriptive` | DL-6 | "Descriptive analysis of one site's records; no treatment effects are estimated; unadjusted unless stated." |

#### 12.2.3 Disclosure control for numbers and figures

§7 owns the disclosure engine, the accountant and the differencing check. This section fixes the **report-level rules**, grouped into profiles.
- The **recipient class** selects the profile; the author does not.
- Parameter changes, for example to meet a DUA or a jurisdiction's rule, go through §7's privacy change procedure.

| Profile | Used for | Suppress | Round | Other |
| --- | --- | --- | --- | --- |
| `dc.sponsor` (external default) | DL-1; DL-2 EMR-derived stages; DL-3; external DL-6 | 1–10 → `<11` (k = 11, as in the CMS cell-size policy); zero shown | Nearest 5 (v1 `round_count` generalised to base b, threshold k) | Month is the finest date. Ages ≥ 90 → `90+`. Regions > 20,000 residents only. |
| `dc.internal` | Research office, internal DL-6, Hermes T1 answers | 1–4 → `<5` (v3 behaviour) | Nearest 5 | Same date, age and geography rules |
| `dc.alliance` | Federated answers (M11) | As `dc.sponsor` | Plus geometric noise; ε accounted per PRIV-22 (§7) | — |
| `dc.trial_ops` | Counts the sponsor already receives through the EDC (screened, screen-failed, randomised) | None | None | Never crossed with demographics or reasons |
| `dc.identified` | DL-5, DL-4 SDV source | None | None | Role-restricted (§7, §14) |
| `dc.jur.<code>` | DUA or jurisdiction override, for example the UK 10-5 rule | Configured | Configured | Set by the privacy officer and recorded in the ledger |

**Order of operations (normative).** The data object's `disclosure_trace` records each step:

1. Compute exact aggregates.
2. Apply primary suppression.
3. Round every count independently. Difference counts, such as "excluded at step i", are computed from exact values and then rounded. They are never computed by subtracting rounded values.
4. Apply complementary suppression across linked structures:
   - funnels;
   - margins and strata;
   - month series;
   - Sankey links;
   - KM risk tables.

   Where any member of a structure is published exactly (`dc.trial_ops`), a linear-constraint check (§7) adds suppressions until no cell from 1 to k−1 is recoverable.
5. Derive percentages and rates from unrounded values. Publish them only if `rate_publishable(k)` holds: the numerator, its complement and the denominator are each 0 or ≥ k.
6. Never cross a reason or outcome category with a demographic category when either margin is below k.
7. Run the differencing check against prior releases to the same requester (§7). Relaxation variants count towards §7's per-snapshot variant limit.
8. Freeze the object, hash it, write the ledger entry, and render.

**Figure-specific rules.**

| Figure | Rule |
| --- | --- |
| Flow and waterfall | Boxes and bars are rounded independently. An excluded count of 1–10 is shown as `<11`, or merged with the next step (`merge_small_steps`) with a footnote. Suppressed bars are hatched `///` in #595959. |
| Histogram and ECDF | Start from a protocol-relevant grid. Merge adjacent bins until each is 0 or ≥ k. Pool the tails into `≤ x` and `≥ y`. Never print min or max. |
| Box and violin | Whiskers at P5–P95. No outliers drawn. Groups with n < k omitted. |
| Sankey and sunburst | Links below k are pooled into "Other / small groups". Nodes still below k are merged into the parent class (for example ATC level 4). This follows the OHDSI pathway precedent of a minimum of 11 (Hripcsak et al., PNAS 2016). |
| Kaplan–Meier | Risk-table cells 1 to k−1 → `<k`. Truncate the curve where at-risk < k. Do not plot strata with < 20 patients (TrialBox choice). Do not draw censor ticks for strata with < 50 patients. |
| Pyramid | Merge age bands until every cell is 0 or ≥ k. 90+ is one band. |
| Heat map | Cells with n < k are grey #BBBBBB with black `<11` text. |
| Map (optional, off by default) | Choropleth of regions with > 20,000 residents. In Taiwan: county or city, with Lienchiang (about 14,000 residents, *est.*) merged with Kinmen. No point maps. |
| Fan chart | Model output, so no suppression. Overlaid actuals follow their stage's profile. |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| RPT-05 | The profile MUST follow the recipient class: `external_sponsor` → `dc.sponsor`, `internal` → `dc.internal`, `alliance` → `dc.alliance`, `delegated_study_team` → `dc.identified`. The profile name and version are recorded and printed. | T | MS1 |
| RPT-06 | The order of operations MUST be applied. Renderers MUST refuse an object whose `disclosure_trace` is incomplete. | T | MS1 |
| RPT-07 | A Hypothesis property test (`tests/unit/test_disclosure_linked.py`) MUST show that no suppressed cell in a random funnel, stratum set or month series is recoverable as an exact value. | T | MS1 |
| RPT-08 | Figure rules MUST be implemented in `libs/tb_reports/disclosure_fig.py`. Each figure type MUST have a small-cell golden fixture. | T | MS1 |
| RPT-09 | External deliverables MUST NOT show dates finer than month (except the data-cut and generation dates), ages above `90+`, or geography below the region rule. | T | MS1 |

#### 12.2.4 Figure standard

**Typography and layout.**
- Fonts: Noto Sans TC, JP and Latin, embedded as subsets (v1 `tools/fetch_fonts.py`).
- Minimum sizes in PDF: 9 pt for text, 11 pt for titles.
- Data lines ≥ 1.5 pt. Markers ≥ 4 pt. Reference lines 1 pt, dashed, #767676.
- Widths: 170 mm (full) or 82 mm (half), on A4. White background.

**Palette `tb-cvd-1`.** Okabe–Ito, adjusted so that every mark reaches ≥ 3:1 against white (WCAG 2.2 SC 1.4.11).
- Okabe–Ito orange (#E69F00, 2.25:1), sky blue (#56B4E9, 2.31:1) and yellow (#F0E442, 1.32:1) fail on white. They are replaced by darker variants of the same hue.
- Ratios below are computed with the WCAG relative-luminance formula.

| # | Colour | Hex | vs #FFFFFF | Default meaning |
| --- | --- | --- | --- | --- |
| 1 | Blue | #0072B2 | 5.19:1 | Primary series, cohort, actuals |
| 2 | Vermillion | #D55E00 | 3.87:1 | Fail, excluded |
| 3 | Bluish green | #009E73 | 3.42:1 | Pass |
| 4 | Reddish purple | #CC79A7 | 3.06:1 | 4th series |
| 5 | Dark orange | #B07800 | 3.80:1 | 5th series |
| 6 | Dark sky blue | #2B8CC4 | 3.72:1 | 6th series |
| 7 | Olive | #8A7F00 | 4.10:1 | 7th series |
| 8 | Black | #000000 | 21:1 | Totals, text |
| — | Grey | #767676 | 4.54:1 | Targets, references, unknown |
| — | Dark grey | #595959 | 7.00:1 | Suppressed hatch |
| — | Light grey (fill only) | #BBBBBB | 1.92:1 | Backgrounds and suppressed cells. Never the sole carrier of meaning. |

**Colour scales and contrast.**
- Sequential: *cividis* (Nuñez et al., PLoS ONE 2018).
- Diverging: ColorBrewer PuOr, 11 classes, midpoint #F7F7F7.
- Text on fills is black or white, whichever reaches ≥ 4.5:1 (SC 1.4.3).
- Palette colours can fall below 3:1 against each other (blue against vermillion is 1.34:1). Adjacent areas are therefore separated by 0.75 pt white gaps and carry direct labels.

**Encoding.**
- Colour is never the only channel (SC 1.4.1). Every series also has a direct label, a dash pattern or a marker shape.
- Bars start at 0. Log axes are labelled.
- No dual axes, no 3-D, no pies.
- Monthly time axes. Criteria in protocol order.
- Intervals are always drawn.
- n is shown in the title. The data cut goes in the caption, and the profile in a footnote.

**Alternative text.** Generated per figure type from the disclosed object (`libs/tb_reports/alttext.py`), with numbers by placeholder. Example: "Bar chart of patients remaining after each of {k} criteria, from {n_first} to {n_last}; largest drop at {crit_max} (−{drop_max})." The alt text is embedded in the PDF `/Figure` element. The data table is sheet `fig_<id>` and a JSON entry.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| RPT-10 | Figures MUST use `tb-cvd-1`, cividis and PuOr. `libs/tb_reports/palette.py` MUST compute WCAG contrast for every mark and text-on-fill pair from the figure specification. CI fails a figure on a mark below 3:1 or text below 4.5:1, unless the mark is declared decorative. | T | MS1 |
| RPT-11 | Each series MUST carry at least one non-colour channel. The figure linter checks this. | T | MS1 |
| RPT-12 | Each figure MUST have generated alt text and a data table (XLSX and JSON). Otherwise the build fails. | T | MS1 |
| RPT-13 | The figure linter MUST enforce the typography minimums at the size at which the figure is placed. | T | MS1 |

#### 12.2.5 Narrative rules

- **Who drafts.** Narratives (executive summary, risks, limitations) are drafted by the `draft_narrative` role (§8) in night pass 3, with placeholders such as `{eligible_adj.p50}`, and stored as recorded outputs.
- **Number check.** The renderer substitutes values from the disclosed object. `numbers_match` then rejects any digit the template engine did not insert, after normalising CJK numerals (一, 十, 百, …; ML-3).
- **No model at render.** The renderer never calls a model. If no recorded narrative exists, it uses deterministic sentence templates and records `narrative: template_fallback`.
- **Claims lint** (`libs/tb_reports/claims.py`), in all languages:

  | Do not write | Write instead |
  | --- | --- |
  | "eligible patients" | "meeting computable criteria" or "estimated eligible after chart review" |
  | "will enrol" | "projected (P50)" |
  | Causal verbs in DL-6 | Descriptive verbs |
  | "guarantee", "all patients", superlatives about the site | — |
  | Any recall claim without the certificate's lower bound and population (AI-13) | The certificate wording |

- **Site-written comments** are allowed in labelled boxes ("Site comment, written by {role}"). They are exempt from `numbers_match` but are PHI-guarded (§7).
- **Terminology.** Terms come from the bilingual glossary (§10, ML-) and render as `term (譯名)` when bilingual rendering is on.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| RPT-14 | Narrative MUST come only from recorded `draft_narrative` outputs with placeholders. Renderers MUST NOT call a model. A failed `numbers_match` blocks the narrative and falls back to templates. | T | MS1 |
| RPT-15 | The claims lint MUST pass on all rendered text in every language before a gate is requested. | T | MS1 |
| RPT-16 | Every estimate MUST print its interval and the interval's definition. Computable counts MUST be labelled as such, and the unknown share shown with them. | T | MS1 |

#### 12.2.6 Languages

- **External language** is `languages.sponsor` on the Study Card. en and zh-TW from MS1; ja from MS6. Bilingual en + zh-TW is available for the cover and summary, with terms elsewhere.
- **Internal deliverables** default to zh-TW.
- **Evidence quotes** in DL-5 stay in their original, possibly code-mixed, language. Glosses are marked as translations.
- **Untranslated items.** Criterion codes are never translated. Machine outputs use ISO 8601 dates, UCUM units and dot decimals.

#### 12.2.7 Formats and packaging

| Format | Standard | Content | For |
| --- | --- | --- | --- |
| PDF | **PDF/A-3b** (ISO 19005-3:2012) **and PDF/UA-1** (ISO 14289-1:2014). PDF/A-4f + PDF/UA-2 (ISO 14289-2:2024) as an MS6 option *(tooling uncertain)* | Tagged headings, tables with `TH` scope, figures with `Alt`, `Lang` per span, bookmarks, embedded fonts. Embedded XLSX (`AFRelationship=Data`) and manifest (`Supplement`). | All |
| XLSX | ISO/IEC 29500, normalised by v1 `normalize_ooxml` | Sheets: `README`, `dictionary`, `provenance`, `T_<id>`, `fig_<id>`. Row 1 holds machine keys. No merged cells, no formulas. One Excel Table per sheet. Each value column has a sibling `<col>__flag` ∈ {exact, rounded, suppressed, estimate, not_computable}. Suppressed cells hold `<11`. | All |
| JSON | JSON Schema 2020-12: `deliverable_manifest` and `deliverable_<type>` | Manifest: header, files (`path`, `media_type`, `bytes`, `sha256`, `role`), object hash, lineage, ruleset, snapshot, certificate, profile and ledger entry, approval, renderer and template versions, model builds, signature. Data object: `suppressed: true`, never a blank. | All |
| CSV | RFC 4180, UTF-8 | One file per table, on request | DL-1–4, 6 |
| FHIR | R4 4.0.1, with R5 elements as needed (§12.10) | `Group`, `EvidenceVariable`, `MeasureReport`, `ResearchStudy`, `Provenance` | DL-1, DL-2 (MS4) |
| USDM | CDISC USDM v4.0 *(class names to be confirmed at implementation)* | Eligibility criteria and the planned population | DL-1 (MS4) |
| Dataset-JSON | CDISC Dataset-JSON v1.1 *(confirm at MS4)* | Tables as datasets | DL-1, 2, 6 (MS4); DL-4 (MS5) |
| ODM | CDISC ODM v2.0, CDASH names | eCRF pre-fill | DL-4 (MS5) |
| PPTX *(optional)* | ISO/IEC 29500 | One summary slide | DL-1 (MS4) |

**Package.** `TB_<site>_<protocol>_<DL>_<YYYYMMDD>_v<n>.zip`, containing the PDF, XLSX, JSON, the exchange files, `manifest.json` and `SHA256SUMS`. It is encrypted where §14 requires. The PDF alone is self-contained, because it embeds the XLSX and manifest.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| RPT-17 | PDFs MUST pass veraPDF (pinned) for PDF/A-3b and PDF/UA-1, both in CI and in `trialbox validate`. A failure blocks release. | T | MS1 |
| RPT-18 | `tools/xlsx_lint.py` MUST enforce the XLSX rules. | T | MS1 |
| RPT-19 | Each release MUST include a schema-valid `manifest.json` whose hashes match the shipped bytes. The approval MUST bind the manifest hash. | T | MS1 |
| RPT-20 | Released PDFs SHOULD carry a PAdES baseline B-T signature (ETSI EN 319 142-1) made with the site's document-signing key (§14). | T | MS4 |

#### 12.2.8 Reporting standards borrowed

TDS borrows structure from these standards. It claims conformance to none of them, except that DL-6 includes a completed RECORD checklist.

| Standard | Borrowed for |
| --- | --- |
| CONSORT 2025 flow diagram | Attrition flow layout (F-F1, R-F2) |
| RECORD (Benchimol et al., PLoS Med 2015;12:e1001885) | Code lists, algorithm validation, linkage and cleaning disclosure; the checklist annex in DL-6 |
| STaRT-RWE (Wang et al., BMJ 2021;372:m4856) | Design diagram and implementation tables (DL-6 §4–§6) |
| HARPER (ISPE/ISPOR, 2022) | DL-6 skeleton; pre-specified, versioned protocol |
| FDA, *Real-World Data: Assessing EHR and Medical Claims Data…* (final, July 2024) | Relevance and reliability; phenotype validation (PPV); data-fitness tables |
| FDA, *Considerations for the Use of RWD and RWE…* (final, August 2023) | Access, audit trail, transparency (provenance block) |
| FDA, *RWE: Considerations Regarding Non-Interventional Studies…* (draft, March 2024) | Protocol freeze before analysis (DL-6) |
| ICH M14 (Step 4, 4 September 2025) | Fitness-for-use assessment (F-T3, DL-6 §3) |
| ICH E6(R3) (Step 4, 6 January 2025) | Computerised-system and data-governance expectations behind provenance |
| KMunicate (Morris et al., BMJ Open 2019;9:e030215) | KM plots with bands and an extended risk table |
| DARWIN EU outputs (EMA) | Incidence by year, age and sex; characterisation tables |
| FDORA §3601–3602; FDA draft guidance on Diversity Action Plans (June 2024). **Status uncertain**: removed in January 2025, reportedly restored, final version not confirmed as of October 2026. | Representativeness headings only (§12.3.6) |
| FDA, *Enhancing the Diversity of Clinical Trial Populations* (final, November 2020) | Rationale for relaxation and representativeness |

### 12.3 Analyses and methods

All analyses are pure functions in the new package `libs/tb_analytics/`:
- no I/O and no clock;
- seeded randomness;
- numpy and scipy only;
- `mypy --strict`.

Modules: `attrition`, `epi`, `survival`, `forecast`, `relax`, `represent`, `lot`, `labs`, `pathway`, `competing`, `sitemetrics`.

Each function is validated on committed fixtures (`tests/unit/analytics/`) against a reference: R `survival` for KM and Aalen–Johansen, R `accrual` for Bayesian accrual, and closed forms for Poisson–Gamma. Tolerance is 1e-6, or a stated Monte Carlo tolerance. Reference outputs are stored as JSON, so CI needs no R.

#### 12.3.1 Criterion state matrix and attrition

For each patient in scope and each criterion, the cascade (S0–S5, §4, §10) yields one of five states:
- `pass`;
- `fail`;
- `unknown:data_gap`: data absent in the window; feeds the `potential:data_gap` tier;
- `unknown:uncertain`: data present but the judgement abstained or disagreed; feeds `potential:uncertain`;
- `not_evaluated`.

`attrition.state_matrix` stores the states as a 2-bit-per-criterion mask per patient (OHDSI inclusion-rule style). The four views below are derived from it.

| View | Definition |
| --- | --- |
| Sequential | Criteria applied in protocol order. n_i = patients passing criteria 1…i. Excluded_i is computed exactly, then rounded. Unknowns are carried forward and counted in their own column. The order is printed. |
| Marginal | Patients in the base population failing each criterion on its own, and their share of the base |
| Leave-one-out (LOO) | eligible without c − eligible with all criteria. Safety-critical criteria are computed but flagged "locked". |
| Unknown share | Share of the base whose state is `unknown:*`, split into data gap and uncertain. This shows how much of the attrition is undocumented rather than ineligible. |

**Chart-review-adjusted estimate.** The computable count (no `fail` after S0–S2) overstates eligibility. `adjusted_estimate` combines three sources:
- the tier counts from the full run;
- the stratified-sample judgements (S3–S5) of the feasibility design (§10, M3);
- the PPV observed for the same canonical criteria in five-minute reviews and G3 decisions (§10, SAFE), where available.

It returns Σ n_tier × p̂_tier with a 95 % interval from §10's stratified estimator.

#### 12.3.2 Incidence and prevalence (site-based)

**New index-condition patients per month.**
- Definition: the first qualifying index event at the site after a clean look-back (default 12 months).
- Shown with a 12-month trailing moving average.
- A month-of-year profile is added once 36 months of data exist.
- Garwood exact Poisson intervals are available on request.

**New patients meeting computable criteria per month.** The same incident cohort passed through the frozen ruleset, with the adjusted estimate.

**Site period prevalence.** Patients with a qualifying record in the period, per 1,000 patients with any encounter in the period. Always labelled "per 1,000 active site patients".

**DL-6 incidence rates.**
- Expressed per 1,000 person-years, with a Garwood CI, by year, sex and age band.
- Age standardisation is used only against a standard population named in the protocol.

**No population rates.** A single hospital's catchment denominator is unknown, so site counts are never presented as population rates. The exception is an external denominator supplied by the sponsor, which is then labelled as an external assumption.

#### 12.3.3 Time to event

**Kaplan–Meier (`survival.km`).**
- Greenwood variance with log(−log) intervals.
- Brookmeyer–Crowley interval for the median (Biometrics 1982).
- Landmark estimates, by default at 6, 12, 18 and 24 months.
- A KMunicate risk table: numbers at risk, censored and with events.

**Competing events.** When a competing event precludes the event of interest (for example, death before second line), `aalen_johansen` reports the cumulative incidence. 1 − KM is never used in that situation.

**Typical uses.**
- Time from 1L to 2L, which gives the inflow to a 2L trial.
- Time from diagnosis to biomarker result.
- Descriptive overall survival from index (DL-6).

#### 12.3.4 Enrolment forecasting

One method, stated once and cited by FR-M3-16 and RPT-25: `libs/tb_analytics/forecast.py`: stage probabilities per
§10.3; monthly rate λ moment-matched to Gamma and propagated as the Poisson–Gamma predictive (below); 10,000 seeded paths.

**Before activation (DL-1).**

`forecast.site_rate_prior` builds the distribution of the monthly rate:

```
λ = [depletion(P0) + μ_new] × v × r × c × s × (1 − a)
```

| Term | Meaning | Source |
| --- | --- | --- |
| P0 | Adjusted prevalent pool | §12.3.1 |
| μ_new | Incident inflow of patients meeting criteria | §12.3.2 |
| v | Monthly visit probability | Appointment history |
| r, c, s | Reach, consent and screen-pass probabilities | Hierarchical Beta-Binomial model of FR-M3-13/14 (§10.3): therapeutic area within site, shrunk to site priors; labelled defaults when the site has fewer than 3 closed studies in the area |
| a | Allocation share lost to competing trials | §12.3.8 |

The calculation then proceeds in four steps:
1. Propagate λ by simulation and moment-match it to a Gamma(α, β).
2. The monthly predictive count is then **Poisson–Gamma**, i.e. negative binomial (Anisimov & Fedorov, *Stat Med* 2007;26:4958–75).
3. Model activation delay from site history (M7) and ramp-up as linear over 2 months by default.
4. `simulate_paths` draws 10,000 seeded paths and reports cumulative P5/P10/P50/P90/P95 by month and the time-to-target distribution.

**During recruitment (DL-2).**
- `bayes_accrual_update` follows Gajewski, Simon & Carlson (*Stat Med* 2008;27:2328–40). The prior is weighted by a declared confidence w (default: 50 % of the planned period), giving the posterior Gamma(α·w + n, β·w + t).
- The update is re-run monthly.
- Interim re-prediction with time-varying rates (Anisimov et al., arXiv 1910.07965) is used after a step change flagged by the CRC, for example an amendment.
- The JSON carries the site posterior (α, β), so that sponsors can plug the site into their own multi-centre Poisson–Gamma models.

**Forecast ledger.** Every released forecast is stored in the one `forecast_ledger` table, written only by `services/tracking/ledger.py` (FR-M6-12), with its quantiles, input hash and horizon.

`score_forecast` computes the following at each month end:
- PIT;
- P10–P90 coverage (target 80 %);
- CRPS;
- at close, also the PI's recorded estimate.

DL-1 and DL-3 print the **calibration record**: scored studies, coverage x/y, calibration slope, and CRPS against PI estimates. The target slope (0.8–1.2 after 10 studies, innovation 7) is reported against, never assumed.

#### 12.3.5 Criterion impact and relaxation

Liu et al. (*Nature* 2021;592:629–33) relaxed lab-based exclusions in 61,094 patients from about 280 clinics. This more than doubled the eligible pool on average, with little change in the overall-survival hazard ratio. A single site cannot emulate effects, but it can supply the inputs sponsors combine across sites:
- **LOO gain.**
- **Threshold sweeps** over grids declared in the ruleset, for example eGFR ≥ 60/45/30 mL/min/1.73 m² or ANC ≥ 1.5/1.0 × 10⁹/L.
- **Composition shift** of the added patients: Δ % female, Δ % aged ≥ 75, Δ Charlson band.
- **Safety proxy**: the share of added patients with CTCAE v5.0 grade ≥ 2 laboratory values in the organ system that the criterion protects.

Criteria flagged `safety_critical` at G1 are **locked**: shown, never swept. No hazard ratio or outcome comparison is produced. Every variant counts against §7's variant limit and is disclosed under the same profile.

#### 12.3.6 Representativeness

`represent.compare_shares` compares four populations:
- (a) the site condition population;
- (b) patients meeting criteria;
- (c) enrolled participants (DL-2);
- (d) a reference supplied by the sponsor, or the site's general population.

It reports, per category:
- shares with Wilson intervals;
- differences with Newcombe hybrid-score intervals (*Stat Med* 1998;17:873–90);
- the standardised mean difference;
- the participation-to-prevalence ratio PPR = share in (b) or (c) ÷ share in (a). A PPR of 0.8–1.2 is printed as "comparable" *(convention, uncertain)*.

Default categories:
- age: <18, 18–44, 45–64, 65–74, 75–84, 85+;
- sex;
- Charlson band: 0, 1–2, ≥ 3 (Quan ICD-10 coding, *Med Care* 2005);
- preferred language;
- residence region (under the region rule);
- NHI insurance category;
- indigenous status *(recording consistency uncertain)*;
- race and ethnicity under US OMB SPD 15 (2024), only where the site records it and the sponsor asks. It is rarely recorded in Taiwan.

A category is reported only if its completeness in (a) is ≥ 80 %. Otherwise the table states "not reliably recorded (completeness x %)".

Section headings mirror the FDA diversity-action-plan elements:
- goals disaggregated by race, ethnicity, sex and age group;
- rationale;
- measures.

A fixed box states that the guidance's US status is uncertain (§12.2.8) and that the site supplies inputs, not a plan.

#### 12.3.7 Lines of therapy

`lot.derive_lines` applies the IR v3 line-of-therapy macro (§6) with parameters versioned per disease in the criterion library:
- eligible agents;
- combination window (default 28 days);
- line-ending gap (default 90 days, `new_line_gap_days` in `lot_rules@tw-onc-1.0.0`, §6.2.2);
- maintenance and switch rules;
- setting (neoadjuvant, adjuvant, metastatic) where it can be determined.

These follow published rule sets, such as Flatiron's line-of-therapy conventions and the NSCLC rules paper (PMC11588435).

Outputs:
- the current-line distribution;
- line durations (KM of time on line);
- class-level transitions (ATC level 4, or sponsor classes);
- **pathway uniqueness**: the share of patients whose pathway is shared by fewer than k patients. This is reported only as a share.

#### 12.3.8 Labs, care pathways and competing trials

**Labs.** `labs.latest_in_window` takes the latest value in the protocol window after UCUM normalisation (§5). Derived values (eGFR by the protocol's equation, × ULN) come from the IR v3 calculators. It reports:
- safe-binned distribution and ECDF;
- % passing;
- % with **no** value in the window;
- median (IQR).

**Care pathways.** `pathway.milestone_intervals` gives median (IQR) days, and the share within the protocol window, between declared milestones. Examples: diagnosis → biomarker order → result → 1L start → 2L start. This shows whether a pre-screening window exists.

**Competing trials.**
- `competing.registry_competitors` reads:
  - the local index of ClinicalTrials.gov API v2 (`/api/v2/studies`, refreshed nightly);
  - the Taiwan registry index where available;
  - the site CTMS.
- Overlap is computed at aggregate level as the Jaccard index of eligible sets, when the competitor's criteria match a library ruleset (M1). Otherwise it is marked "not computed" with a qualitative match (condition, phase, line, biomarker).
- The default allocation share is a = 1/(m+1), for m open competitors with overlap ≥ 0.3. It is printed as an assumption the sponsor may change.

#### 12.3.9 Requirements

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| RPT-21 | Sequential, marginal and LOO views and the unknown share (data gap and uncertain, separately) MUST derive from one state matrix per run. | T | MS1 |
| RPT-22 | The adjusted estimate MUST carry a 95 % interval and be printed with the computable count and the unknown share. | T | MS1 |
| RPT-23 | Site counts MUST NOT be labelled as population rates. Every rate names its denominator, and every standardised rate its standard population. | T, I | MS1 |
| RPT-24 | KM MUST use Greenwood log(−log) intervals, Brookmeyer–Crowley medians and KMunicate tables. Competing events use Aalen–Johansen. Results MUST agree with R `survival` on fixtures to within 1e-6. | T | MS4 |
| RPT-25 | The pre-activation forecast MUST be computed by `libs/tb_analytics/forecast.py`: stage probabilities per §10.3; monthly rate λ moment-matched to Gamma and propagated as the Poisson–Gamma predictive (§12.3.4); 10,000 seeded paths (FR-M3-16), from the EMR-derived prior, with P5–P95 by month and time to target. | T | MS1 |
| RPT-26 | The in-recruitment forecast MUST apply the Bayesian accrual update with a declared prior weight, run monthly, be stored in the ledger with its input hash, and export the posterior (α, β). | T | MS4 |
| RPT-27 | DL-1 and DL-3 MUST print the calibration record. With fewer than 3 scored studies they print "insufficient history" and no slope. | T | MS4 |
| RPT-28 | Relaxation MUST lock `safety_critical` criteria, MUST NOT produce effect estimates, and every variant MUST count against §7's limit. | T | MS1 |
| RPT-29 | Representativeness MUST report only categories with ≥ 80 % completeness, use Newcombe intervals, and print the FDA-status box whenever the DAP headings are used. | T | MS1 |
| RPT-30 | Lines of therapy MUST come only from the IR v3 macro, with its parameters printed in the methods section. | T | MS4 |
| RPT-31 | Every analysis printed MUST cite its method reference and its `tb_analytics` function and version in the methods section. | I | MS1 |

### 12.4 Feasibility pack (DL-1)

**Purpose.** Answer a sponsor's feasibility request with defensible EMR-derived numbers:
- the eligible-pool band;
- the recruitable rate;
- the limiting criteria;
- the population mix;
- competition;
- capability and track record.

M3 questionnaire autofill (§10) answers every question with a path into this pack's data object, so the questionnaire and the pack cannot disagree.

**Audience.** Sponsor or CRO feasibility and site-selection teams. Protocol-design teams for §12, on request.

**Trigger and timing.**
- After G1, ready for G2 by 08:00 on the next working day (NFR-3), for ≤ 40 criteria and ≤ 3M patients.
- A re-issue on a new data cut carries "what changed since v{n}" (M3).
- Target: ≤ 2 working days from request to release.

**Sections, in order.**

| § | Section | Tables | Figures |
| --- | --- | --- | --- |
| 1 | Cover and executive summary: computable count; adjusted estimate (interval); new patients meeting criteria per month; 12-month P10/P50/P90; start-up timeline; top three limiting criteria; competing load; recall sentence | F-T1 | — |
| 2 | Study, scope and data fitness | F-T2, F-T3 | — |
| 3 | Criteria mapping and computability | F-T4 | F-F3 |
| 4 | Attrition and the estimate by tier | F-T5–F-T8 | F-F1, F-F2 |
| 5 | Incidence (24 months) and the prevalent pool | F-T9 | F-F4 |
| 6 | Population characteristics and representativeness | F-T10 | F-F5, F-F6 |
| 7 | Clinical profile: labs against cut-offs; stage; biomarker testing rate and turnaround | F-T11 | F-F7 |
| 8 | Treatment patterns and standard of care, including NHI reimbursement context (comparator coverage, biomarker reimbursement; M10) | F-T12, F-T13 | F-F8 |
| 9 | Pool by department and investigator (bands only) | F-T14 | F-F9 |
| 10 | Competing trials and allocation | F-T15 | — |
| 11 | Recruitability and projection, with the calibration record | F-T16, F-T17 | F-F10, F-F11 |
| 12 | Criterion impact and relaxation *(on request)* | F-T18 | F-F12, F-F13 |
| 13 | Site profile and start-up: SIP-style facility and department fields, PI experience, staffing, equipment, IRB and contract timelines, DL-3 summary | F-T19 | — |
| 14 | Data, methods and limitations: RECORD data description; documentation bias; single-site and referral-centre effects | F-T20 | — |
| 15 | Provenance, disclosures and approval (§12.2.1–§12.2.2) | — | — |
| A–E | Annexes: A ValueSets; B criterion logic hashes and IR summaries; C questionnaire answer map; D glossary; E data dictionary | — | — |

**Tables.** Columns are the XLSX machine keys.

| ID | Columns |
| --- | --- |
| F-T1 Summary | `metric`, `value`, `interval_low`, `interval_high`, `interval_def`, `source_path`, `flag` |
| F-T2 Scope | `item`, `value` |
| F-T3 Data fitness | `domain`, `source`, `coverage_pct`, `completeness_pct_key_vars`, `freshness_days`, `dq_grade`, `reconciliation_status` |
| F-T4 Criteria mapping | `criterion_id`, `kind`, `protocol_text`, `text_lang`, `computability` (full/partial/none), `stages`, `logic_summary`, `valueset_refs`, `window`, `completeness_pct`, `llm_involved`, `lexicon_recall`, `library_match`, `safety_critical` |
| F-T5 Sequential attrition | `step`, `criterion_id`, `label`, `n_remaining`, `n_excluded`, `pct_excluded_of_prev`, `n_unknown_data_gap`, `n_unknown_uncertain`, `stage` |
| F-T6 Marginal | `criterion_id`, `n_fail_alone`, `pct_of_base`, `n_unknown`, `pct_unknown` |
| F-T7 LOO | `criterion_id`, `n_eligible_without`, `delta_n`, `delta_pct`, `locked` |
| F-T8 By tier | `tier` (strong, potential:data_gap, potential:uncertain, watchlist), `n_computable`, `est`, `ci95_low`, `ci95_high`, `n_sampled`, `method` |
| F-T9 Incidence | `month`, `n_new_index`, `ma12`, `n_new_meeting_est`, `ci95_low`, `ci95_high` |
| F-T10 Representativeness | `characteristic`, `category`, `n_condition`, `pct_condition`, `n_cohort`, `pct_cohort`, `pct_reference`, `diff_pp`, `diff_ci_low`, `diff_ci_high`, `smd`, `ppr`, `completeness_pct` |
| F-T11 Labs | `criterion_id`, `loinc`, `cutoff`, `unit`, `n_with_value`, `pct_missing`, `pct_passing`, `median`, `q1`, `q3` |
| F-T12 Lines | `line`, `n_patients_12m`, `top_classes`, `median_duration_days`, `q1`, `q3` |
| F-T13 Pathway intervals | `from_milestone`, `to_milestone`, `n`, `median_days`, `q1`, `q3`, `pct_within_window` |
| F-T14 Departments | `department`, `investigator_code`, `cohort_band`, `upcoming_visits_14d_band`, `active_competing_studies` |
| F-T15 Competing trials | `registry_id`, `short_title`, `phase`, `sponsor`, `status`, `local_pi_code`, `overlap`, `overlap_method`, `allocation_assumption` |
| F-T16 Assumptions | `parameter`, `value`, `low`, `high`, `distribution`, `source` (EMR / site history / sponsor / default), `n_behind` |
| F-T17 Projection | `month`, `p10`, `p50`, `p90`, `cum_p5`, `cum_p10`, `cum_p50`, `cum_p90`, `cum_p95`, `p_target_by_month` |
| F-T18 Relaxation | `criterion_id`, `variant`, `delta_n`, `delta_pct_female`, `delta_pct_75plus`, `delta_charlson_ge3`, `safety_proxy_pct`, `locked` |
| F-T19 Site profile | `field`, `value`, `source`, `as_of`, `answer_memory_ref` |
| F-T20 Methods | `analysis`, `function`, `version`, `reference`, `parameters` |

**Figures.**

| ID | Type | X | Y and encodings | Annotations; disclosure |
| --- | --- | --- | --- | --- |
| F-F1 | CONSORT-style flow | — | Boxes: n remaining. Side boxes: "Excluded: {criterion} (n)". Final box: computable count and adjusted estimate. | Stage tag per box; unknowns in grey italics; flow rules |
| F-F2 | Waterfall bar | Criteria in protocol order | Remaining (linear from 0). Drops as vermillion floating bars; start and end bars blue. | Value labels; top three drops annotated; hatched `<11` |
| F-F3 | 100 % stacked bar | Criteria | Pass (green) / fail (vermillion) / unknown data gap (grey, dotted hatch) / unknown uncertain (grey, cross hatch) | Computability badge ●/◐/○; segments below k unlabelled |
| F-F4 | Line | Month (24) | Monthly new index-condition patients (thin, markers) and 12-month MA (thick). Panel 2: patients meeting criteria with band. | Seasonality note at ≥ 36 months; hollow `<11` markers |
| F-F5 | Population pyramid | Count (female left, male right) | Age bands. Condition population as an outline, cohort filled. | Band merging |
| F-F6 | Dumbbell | Share % | Rows = categories. Condition (hollow circle), cohort (filled square), reference (diamond). | PPR at the right; suppressed dots omitted |
| F-F7 | ECDF small multiples | Lab value (UCUM) | Cumulative % (binned step) | Cut-off line "{op} {value}"; % passing and % missing; safe bins |
| F-F8 | Sankey | Dx → 1L → 2L → 3L+ | Link width = patients; nodes = regimen class | Node n; pooling into "Other" |
| F-F9 | Heat map | Month (12) | Rows = departments; cividis = new patients meeting criteria; value in each cell | Row totals; `<11` cells grey |
| F-F10 | Fan chart | Months from projected activation | Cumulative P50 line; P10–P90 band dark, P5–P95 band light; grey dashed target | "P(target by {month}) = {p}" |
| F-F11 | Calibration plot | Predicted P50 at close | Actual at close, one point per past study; identity line; P10–P90 whiskers | Coverage x/y, slope; no study identities; shown only from 3 studies |
| F-F12 | Tornado | Δ eligible (LOO) | Rows = criteria sorted; locked rows hatched and labelled | Δ % printed; `<11` |
| F-F13 | Diverging heat map *(optional)* | Metrics: fail %, LOO Δn, unknown %, Δ % female, Δ % ≥ 75, safety proxy | Rows = criteria or variants; PuOr centred on 0; values printed | Locked rows outlined; `<k` cells grey |

**Formats.** PDF, XLSX and JSON at MS1. FHIR, USDM, Dataset-JSON and the optional PPTX slide at MS4.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| RPT-32 | DL-1 MUST contain §1–§11 and §13–§15 in order, with §12 on request. Every listed table and figure MUST be present, or replaced by a fixed "not available: {reason}" panel. | T | MS1 |
| RPT-33 | The executive summary MUST show exactly these headline numbers: computable count, adjusted estimate with interval, monthly new patients meeting criteria, and 12-month P10/P50/P90. | T | MS1 |
| RPT-34 | Every autofilled questionnaire answer MUST reference a DL-1 object path, a site-profile field or an answer-memory entry. All are listed in Annex C. Unmapped questions stay blank (AI-08). | T | MS1 |
| RPT-35 | CQL/SQL logic text MUST NOT be released by default; only hashes and IR summaries are. Releasing logic text needs an explicit research-office approval recorded in the gate. | T | MS1 |

### 12.5 Accrual pack (DL-2)

**Purpose.** DL-2 replaces ad-hoc enrolment emails and CTMS re-keying with one monthly report. It also explains *why* enrolment is above or below plan, using pre-screening data that sponsors do not otherwise see: the pipeline, the reasons, blind spots and the forecast.

**Audience.** The sponsor's study manager or CRA, with a copy to the research office.

**Trigger.**
- The scheduler produces it on the 1st working day for the previous month.
- It is ready for G2 by the 3rd working day (NFR-24).
- It is also produced on request.
- A flag raised mid-month produces a one-page interim **flag notice**.

**Sections, in order.**

| § | Section | Tables | Figures |
| --- | --- | --- | --- |
| 1 | Header and period: month, data cut, status, activation date | — | — |
| 2 | KPI tiles: randomised this month and cumulative against target; screened; cumulative screen-fail rate; approached → consented conversion; days since last randomisation; P50 date to target | A-T1 | — |
| 3 | Enrolment against plan, with the updated forecast and P(target by planned end) | A-T5 | A-F1 |
| 4 | Recruitment funnel, month and cumulative: EMR-identified → PI-reviewed → approached → consented → screened → randomised; exits | A-T2 | A-F2, A-F4 |
| 5 | Screen-failure reasons, mapped to criteria (Pareto); decline and non-approach reasons | A-T3, A-T4 | A-F3 |
| 6 | Time in pipeline | A-T8 | A-F6 |
| 7 | Pre-screening quality: blind spots (criteria marked `pass` that caused ≥ 3 screen failures, M4), recall statement, review depth | A-T9 | — |
| 8 | Early-warning flags | A-T6 | — |
| 9 | Diversity: enrolled compared with eligible *(on request)* | A-T7 | A-F5 |
| 10 | Site issues and actions (site-written box, §12.2.5) | — | — |
| 11 | Provenance, disclosures, approval | — | — |

**Early-warning rules.** The defaults below are site-configurable, and each flag prints its rule.

| Flag | Default rule |
| --- | --- |
| Behind plan | P50 < 80 % of plan in two consecutive weekly evaluations (kept from v3) |
| Zero enroller | No randomisation 60 days after activation |
| High screen-fail | > 50 % with ≥ 10 screened. Vendor practice, not a consortium standard. |
| Stalled pipeline | No new approach for 30 days while the cohort estimate is > 0 |
| Blind spot | The M4 blind-spot condition is met |

**Tables.**

| ID | Columns |
| --- | --- |
| A-T1 KPIs | `kpi`, `month_value`, `cumulative_value`, `target`, `flag` |
| A-T2 Funnel | `stage`, `n_month`, `n_cumulative`, `conversion_from_prev_pct`, `disclosure_profile` |
| A-T3 Screen failures | `criterion_id`, `reason_category`, `n_cumulative`, `pct_of_screen_fails`, `cascade_state_at_prescreen` |
| A-T4 Non-approach and decline | `reason_category` (patient declined, physician declined, logistics, competing trial, not contactable, other), `n_month`, `n_cumulative` |
| A-T5 Forecast | `month`, `actual_cum`, `plan_cum`, `cum_p10`, `cum_p50`, `cum_p90`, `p_target_by_end`, `posterior_alpha`, `posterior_beta`, `prior_weight` |
| A-T6 Flags | `flag`, `rule`, `first_raised`, `status` |
| A-T7 Diversity | `characteristic`, `category`, `pct_cohort`, `pct_enrolled`, `pct_goal`, `ppr` |
| A-T8 Intervals | `from_state`, `to_state`, `n`, `median_days`, `q1`, `q3` |
| A-T9 Quality | `item` (blind-spot criteria, recall lower bound, population, review depth k), `value` |

**Figures.**

| ID | Type | X | Y and encodings | Disclosure |
| --- | --- | --- | --- | --- |
| A-F1 | Step line with fan | Months since activation | Actual (blue solid step), plan (grey dashed), P50 (black, from the current month) with P10–P90 band; target line; "P(target by {date})" | `dc.trial_ops` for randomised counts |
| A-F2 | Grouped bars | Month (last 12) | Count per stage; direct labels on the last month | EMR-derived stages under `dc.sponsor` |
| A-F3 | Pareto (horizontal) | Cumulative count | Reasons sorted descending; cumulative % as labels (no second axis) | Below k pooled into "Other". Never crossed with demographics. |
| A-F4 | Run chart | Month | % approached → consented and % screened → randomised (markers + dash); median line; run of 6 on one side of the median flagged | Denominator < k → withheld |
| A-F5 | Dot plot | % | Rows = categories. Cohort (hollow circle), enrolled (square), goal (diamond). | Enrolled 1–10 → `<11`, dot omitted |
| A-F6 | Cumulative incidence | Days since identification | % consented (Aalen–Johansen; decline is the competing event) | Truncated at at-risk < k |

**Formats.** PDF, XLSX and JSON. FHIR `ResearchStudy` recruitment plus a `MeasureReport` with funnel populations stratified by month. Dataset-JSON of A-T2, A-T3 and A-T5.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| RPT-36 | DL-2 MUST be produced monthly for every `recruiting` study with the sections above, ready for G2 by the 3rd working day. | T | MS4 |
| RPT-37 | Every screen-failure reason MUST map to a criterion id or a fixed category, shown with the cascade state at pre-screen. | T | MS4 |
| RPT-38 | Flags MUST be evaluated weekly. A new flag MUST produce the interim notice to the research office within one working day. | T | MS4 |
| RPT-39 | Conduct counts MAY use `dc.trial_ops`. EMR-derived stages MUST use `dc.sponsor`. The two together MUST pass the linear-constraint check (§12.2.3, step 4). | T | MS4 |

### 12.6 Site performance pack (DL-3)

**Purpose.** Evidence of the site's operational track record, in a fixed vocabulary, without disclosing other sponsors' studies.

**Audience.** Sponsor site-selection and clinical-operations teams. Also the research office, for internal benchmarking.

**Trigger.** A sponsor request, usually attached to a DL-1 reply. Each study close (M9) adds the study to the site history.

**Metric vocabulary.** The definitions are TrialBox's own. They are aligned in intent with Metrics Champion Consortium and TransCelerate practice *(alignment uncertain; no certification claimed)*. Sources:
- the M6 pipeline;
- M7 start-up and RBQM KRIs;
- M8 queries;
- CTMS and IRB imports;
- sponsor EDC metrics, flagged `sponsor_provided`.

| Metric | Definition | Unit |
| --- | --- | --- |
| IRB cycle time | Submission → approval | days, median (IQR) |
| Contract cycle time | First draft received → executed | days |
| Activation cycle time | Final protocol received → site activated | days |
| Time to first participant | Activation → first consent | days |
| Enrolment against target | Randomised ÷ site target | % |
| Enrolment rate | Randomised per active site-month | per month |
| Screen-failure rate | Screen failed ÷ screened | % (Wilson CI) |
| Pre-screen conversion | Consented ÷ approached | % |
| Retention | (Completed + ongoing) ÷ randomised | % |
| Query rate | Queries per 100 data pages *(sponsor-provided)* | per 100 |
| Query resolution time | Opened → closed | days, median |
| Important deviation rate | Important deviations per 100 participant-months | per 100 |
| Visit-window adherence | Visits in window ÷ visits due | % |
| SAE timeliness | SAEs reported to the sponsor ≤ 24 h after awareness ÷ SAEs | % |
| Consent version lag | New version effective → re-consent complete | days, median |
| Zero-enroller share | Activated studies with no randomised participant ÷ activated studies | % |
| Forecast calibration | §12.3.4 | coverage, slope, CRPS |

**Confidentiality between sponsors.**
- Sponsor X sees its own studies by protocol id.
- Every other study appears only inside therapeutic area × phase-group aggregates (I/II, III/IV), and a group is shown only if it contains ≥ 3 studies (k_study = 3).
- Dots for other sponsors' studies carry no labels.

**Sections.**
1. Header and scope.
2. Summary tiles (S-T1).
3. Start-up (S-T2, S-F2).
4. Enrolment (S-T3, S-F1, S-F3).
5. Conduct quality (S-T4, S-F4).
6. Retention (S-T3).
7. Calibration record (S-T5, F-F11).
8. Data, methods and limitations.
9. Provenance, disclosures and approval.

**Tables.**

| ID | Columns |
| --- | --- |
| S-T1 Summary | `metric`, `value`, `interval`, `n_studies`, `period` |
| S-T2 Start-up | `group`, `n_studies`, `irb_days_median`, `contract_days_median`, `activation_days_median`, `fpi_days_median` |
| S-T3 Enrolment and retention | `group`, `n_studies`, `enrol_vs_target_median_pct`, `rate_per_month_median`, `screen_fail_pct`, `screen_fail_ci_low`, `screen_fail_ci_high`, `retention_pct`, `zero_enroller_pct` |
| S-T4 Conduct quality | `group`, `query_rate`, `query_days_median`, `deviation_rate`, `visit_window_pct`, `sae_timely_pct`, `consent_lag_days`, `source` |
| S-T5 Calibration | `n_scored_studies`, `coverage_p10_p90`, `slope`, `crps_box`, `crps_pi` |

**Figures.**

| ID | Type | X | Y and encodings | Disclosure |
| --- | --- | --- | --- | --- |
| S-F1 | Strip and dot plot | Enrolment against target (%) | Rows = groups; one dot per study (own studies labelled); median bar; 100 % reference line | k_study = 3 |
| S-F2 | Box plot | Activation days | Rows = groups; P5–P95 whiskers | k_study = 3 |
| S-F3 | Forest-style plot | Screen-fail % with Wilson CI | Rows = groups with n; overall diamond | Screened < k omitted |
| S-F4 | ECDF | Query resolution days | One line per year | Groups with ≥ k queries only |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| RPT-40 | DL-3 metrics MUST be implemented once, in `tb_analytics.sitemetrics`, with each definition printed in the methods section and sponsor-provided inputs flagged. | T | MS4 |
| RPT-41 | A test MUST show that no other sponsor's protocol id, title or registry number appears in any file of a DL-3 for sponsor X. Other studies MUST appear only in groups of ≥ 3. | T | MS4 |

### 12.7 Data deliverables (DL-4)

These are trial-support products of M8 (§10). Every item carries the provenance block.

| Item | Content | Standard and format | Class | Gate | Channel | R |
| --- | --- | --- | --- | --- | --- | --- |
| eCRF pre-fill | Structured domains (demographics, vitals, labs, concomitant medication, history) mapped to the sponsor's eCRF, each with a source reference | ODM v2.0 `ClinicalData` with CDASH names, or the EDC vendor's import CSV | D4, under the participant's consent | G6 (the CRC certifies each form) | The CRC uploads it. TrialBox never writes to the EDC. | MS5 |
| SDV source packet | Per visit: source excerpts with lineage, verified quotes, labs with reference ranges | PDF/A-3b + UA-1, with a JSON source map embedded | D4 | G6 | Under the site's monitor-access policy (§14); never by email | MS5 |
| Query answer drafts | Draft answers to EDC queries, with source citations | DOCX/PDF; plain text | D4 | CRC review; G6 if a regulated record changes | Internal | MS5 |
| De-identified dataset | Retrospective dataset for an approved request | Dataset-JSON v1.1 + CSV, XLSX dictionary, optional OMOP CDM 5.4 extract | D2 | G2 + privacy officer + de-identification certificate (§7) | Outbox, encrypted | MS5 |
| DQ report | DQD categories and Kahn conformance, completeness and plausibility for the dataset's variables | PDF + XLSX | D1 | With the dataset | With the dataset | MS5 |
| De-identification certificate | Method (Safe Harbor checklist or expert determination); k-anonymity and l-diversity results; residual-risk statement; signatory | PDF/A + JSON | D1 | Privacy officer, Level B | With the dataset | MS5 |

**Dictionary columns.** `variable`, `label_en`, `label_zh_TW`, `type`, `unit_ucum`, `codelist`, `derivation`, `source_domain`, `missing_pct`, `deid_transform`.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| RPT-42 | eCRF pre-fill MUST validate against ODM v2.0 or the declared EDC template. Every item MUST carry a source reference. Items without a source stay empty and are never inferred. | T | MS5 |
| RPT-43 | A de-identified dataset MUST ship with its dictionary, DQ report and certificate, all bound by one manifest. | T | MS5 |

### 12.8 PI pre-screening report (DL-5, internal)

**Purpose.** A ranked worklist of candidates, with per-criterion evidence, so that the PI and the delegated team can confirm or reject each candidate for follow-up (G3).
- The report never states eligibility (§15).
- It never leaves the hospital.
- The site's lawful basis (IRB approval, waiver or the national equivalent) is checked before the first run (§15).

**Audience.** Delegated study team members only.

**Trigger.** A weekly per-study run, or the nightly clinic-day portfolio (M4). Delivered by 07:00.

**Forms.** One encrypted XLSX decision sheet, and **one consolidated evidence PDF per run** with a bookmark per candidate. This replaces v3's one PDF per strong candidate (R3-27). An optional review page (§3) renders the same object.

**Sections.**

| § | Section | Content |
| --- | --- | --- |
| 1 | Header | Protocol, PI, run date, snapshot, ruleset, model builds, recall sentence |
| 2 | Summary | Candidates by tier (strong, potential:data_gap, potential:uncertain, watchlist) and by status (new, under review, approached, declined, screened, ineligible on review); review depth k (M4) |
| 3 | Worklist | P-T1 |
| 4 | Visit timeline | P-F4 |
| 5 | Evidence cards | P-T2, P-F2, P-F3 per candidate |
| 6 | Time-window alerts | Watchlist flips; expiring data for `potential:data_gap` (missing item and its deadline) |
| 7 | Decisions | Reply lines and plain-language options (Hermes proposes, §9); the decision sheet |
| 8 | Audit footer | Distribution, print and export policy |

**Tables.**

| ID | Columns |
| --- | --- |
| P-T1 Worklist | `rank`, `pid_short`, `mrn_masked` (last 4 in print; full only in the encrypted XLSX), `name` (XLSX only), `age`, `sex`, `treating_physician`, `next_visit_at`, `clinic`, `tier`, `n_met`, `n_not_met`, `n_unknown`, `reason_to_review`, `flip_date`, `decision`, `reason_code`, `comment` |
| P-T2 Evidence | `criterion_id`, `label`, `status` (met / not met / unknown: data gap / unknown: uncertain / verify at screening / pending human), `stage`, `evidence_quote` (original language, ≤ 400 chars, verified offsets), `gloss` (marked as a translation), `source_type`, `source_date`, `department`, `value`, `cutoff`, `second_opinion_agrees` |

No predicted screen-fail risk column is printed: no FR defines its calibration, and ranking by predicted outcome is a §15.3 drift trigger. The worklist ranks by tier and evidence only.

**Figures.**

| ID | Type | Encoding | Controls |
| --- | --- | --- | --- |
| P-F1 | Funnel (horizontal bars) | EMR-flagged → PI-reviewed → confirmed for follow-up → approached → consented → screened → randomised | `dc.identified`. Never copied into external packs; DL-2 re-derives it. |
| P-F2 | Criterion matrix | Rows = candidates, columns = criteria. Symbol plus colour: ✓ met (green), ✗ not met (vermillion), ? unknown (grey), ◇ verify at screening (blue). | Initials and masked MRN |
| P-F3 | Lab sparkline | Last 12 months, with the cut-off band shaded | Evidence card only; not exportable |
| P-F4 | Visit timeline | Next 14 days; swim lanes by clinic; marker shape by tier | Internal |

**Controls.**
- Minimum necessary fields.
- No free-text export beyond verified quotes.
- Print watermark with user and time, and an "Internal: pre-screening only" banner.
- A 30-day expiry notice on printed lists.
- Status changes count towards sponsor numbers only after G3 or G4.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| RPT-44 | DL-5 MUST use `dc.identified`, go only to delegated recipients (RPT-04), and carry the watermark and expiry text. "Eligible" and "qualified" (and their zh-TW and ja equivalents) MUST NOT appear outside verbatim protocol text. | T | MS2 |
| RPT-45 | Each evidence card MUST show every criterion with its status, and a verified original-language quote for note-based statuses. A candidate with an unverified quote is listed as `potential:uncertain` and gets no card claim. | T | MS2 |
| RPT-46 | DL-5 MUST be one consolidated PDF with candidate bookmarks plus one decision sheet per study, or per practitioner in portfolio mode. | T | MS3 |

### 12.9 RWE cohort-characterisation report (DL-6)

**Purpose.** A descriptive, non-interventional characterisation of a disease or treatment cohort, for:
- medical affairs;
- protocol design;
- external-control scoping;
- HEOR.

Comparative-effectiveness estimation needs a full HARPER protocol and SAP, and is outside DL-6.

**Trigger.** An approved analysis specification (`rwe_protocol.yaml`: cohorts, windows, variables, analyses), frozen with a hash before any result is computed. Deviations are logged. DL-6 runs on the OMOP CDM 5.4 serving layer (§5) or the curated lake.

**Sections (HARPER skeleton), in order.**

| § | Section | Tables and figures |
| --- | --- | --- |
| 1 | Title, registration (HMA-EMA RWD catalogue or another register where applicable), protocol hash, version history and deviations | — |
| 2 | Rationale and pre-specified objectives | — |
| 3 | Data source and fitness for use (ICH M14; FDA July 2024): coverage, completeness, known biases, DQ scorecard | R-T6 |
| 4 | Design diagram (STaRT-RWE) | R-F1 |
| 5 | Cohort definitions: entry, inclusion and exclusion, code lists, phenotype PPV and sensitivity if available (RECORD 6.1–7.1) | R-T1 |
| 6 | Variables with operational definitions | R-T7 |
| 7 | Methods: descriptive statistics, Garwood rates, KM and Aalen–Johansen, missing data (complete case unless stated), disclosure profile | — |
| 8 | Results: 8.1 attrition; 8.2 baseline "Table 1"; 8.3 incidence and prevalence by year, age and sex; 8.4 treatment patterns; 8.5 time to event; 8.6 subgroups; 8.7 sensitivity; 8.8 labs | R-F2, R-T2, R-T3/R-F3, R-T4/R-F4, R-T5/R-F5, R-F6, R-F7 |
| 9 | Discussion and limitations (single site, documentation bias) | — |
| 10 | Data protection, governance, ethics | — |
| A–D | Code lists; completed RECORD checklist with page references; lineage and query log; dictionary and missingness | R-F8 |

**Tables.**

| ID | Columns |
| --- | --- |
| R-T1 Attrition | `step`, `criterion`, `n_remaining`, `n_excluded` |
| R-T2 Baseline | `variable`, `level`, `stat_type`, `overall`, `subgroup_1…k`, `smd`, `missing_pct` |
| R-T3 Incidence | `year`, `sex`, `age_band`, `events`, `person_years`, `rate_per_1000py`, `ci95_low`, `ci95_high` |
| R-T4 Lines | `line`, `n`, `top_classes`, `median_duration_days`, `ci95` |
| R-T5 Landmarks | `stratum`, `t_months`, `n_at_risk`, `estimate`, `ci95_low`, `ci95_high`, `method` |
| R-T6 Fitness | `variable`, `domain`, `missing_pct`, `plausibility_fail_pct`, `dq_grade` |
| R-T7 Variables | `variable`, `role`, `definition`, `window`, `codelist`, `validation` |

**Figures.**

| ID | Type | X | Y and encodings | Disclosure |
| --- | --- | --- | --- | --- |
| R-F1 | Design diagram | Days relative to index | Bands for washout, covariates, exposure, follow-up | No data |
| R-F2 | Attrition flow | — | As F-F1 | As F-F1 |
| R-F3 | Rate plot | Calendar year | Rate per 1,000 PY with CI bars; facets by sex or age band | Events 1–10: no point; "<11 events" label |
| R-F4 | Sankey or sunburst | Line stage | Patients per transition | Pooling |
| R-F5 | KM or CIF (KMunicate) | Months since index | Probability with CI band; extended risk table | Truncation and stratum rules |
| R-F6 | Forest plot | Estimate with 95 % CI | Rows = subgroups with n; overall reference | n < k merged or omitted; "descriptive, unadjusted" footnote |
| R-F7 | Box plot | Subgroup | Lab value; reference range shaded; P5–P95 whiskers | n < k omitted |
| R-F8 | Heat map | Variables | Year; cividis = % missing | Denominator < k grey |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| RPT-47 | DL-6 MUST NOT compute any result before its specification is frozen with a hash. Deviations are printed in §1. | T | MS5 |
| RPT-48 | DL-6 MUST include a completed RECORD checklist with page references generated from section anchors. Unaddressed items are listed as such. | T, I | MS5 |
| RPT-49 | DL-6 MUST pass the causal-language lint. Adjusted or comparative estimates MUST be refused within DL-6. | T | MS5 |

### 12.10 Machine-readable exchange

**FHIR.** FHIR R4 4.0.1 is normative at the site (§5). R4 lacks `ResearchStudy.recruitment` and the R5 `Group` combination semantics used by the EBM IG *StudyEligibilityCriteria* profile. The bundle is therefore R4, with these elements carried as FHIR cross-version extensions; a native R5 5.0.0 bundle is an option (`exchange.fhir_version`). The extension URLs are fixed at MS4 against the published extension pack *(uncertain)*.

| TDS object | Resource | Mapping |
| --- | --- | --- |
| Eligibility | `Group` (EBM IG pattern) plus one `EvidenceVariable` per criterion | `characteristic.definitionExpression` → a `Library` reference (hash only unless logic release is approved, RPT-35); `definitionCodeableConcept` for single-code criteria; `exclude` for exclusions; windows via `timeFromEvent` (R5) or an extension |
| Attrition and funnel | `MeasureReport` (`type = summary`) referencing a TrialBox `Measure` per ruleset version | One `group` per view; one `population` per step, coded by criterion id; `count` = rounded value. Suppressed counts omit `count` and carry `data-absent-reason = masked`. Extension `tb-disclosure` holds the profile, base and k. |
| Strata | `MeasureReport.group.stratifier` | Age band, sex, month, department; same suppression rules |
| Recruitment | `ResearchStudy` | `recruitment.targetNumber`, `actualNumber`, `actualGroup` |
| Lineage | `Provenance` | Targets the resources above; entities = snapshot, ruleset, manifest; agents = software build and approver role |
| Package | `Bundle` (`collection`) | `identifier` = deliverable id; `meta.tag` = TDS version |

**USDM.** One USDM v4.0 eligibility-criterion object per IR criterion:
- category;
- identifier = criterion id;
- protocol text;
- dictionary links to the ValueSets.

The planned enrolment comes from the Study Card. This export is read back from the frozen ruleset, so it round-trips with M1's USDM import.

**Dataset-JSON.** One dataset per table, with `itemOID` = column key, metadata from the dictionary, and null plus a `__flag` item for suppressed values.

**ODM v2.0.** Used for eCRF pre-fill, structured as `ClinicalData` → `SubjectData` → `StudyEventData` → `ItemGroupData`, with CDASH names and an `AuditRecord` carrying the source reference.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| RPT-50 | FHIR bundles MUST validate with the pinned HL7 validator against `deploy/fhir/ig/trialbox-exchange/`. Suppressed counts MUST use `data-absent-reason = masked`, never 0. | T | MS4 |
| RPT-51 | The USDM export MUST round-trip with M1's import on the fixture protocols, with no loss of id, category or text. | T | MS4 |
| RPT-52 | Dataset-JSON MUST validate against the v1.1 schema and equal the XLSX values cell for cell. | T | MS4 |

### 12.11 Renderer architecture

**Pipeline.** Each step's output is recorded.

```
analysis     tb_analytics (batch pass)        → DeliverableData       (§6 schema, hashed)
disclosure   §7 engine + accountant           → DisclosedDeliverable  (frozen; disclosure_trace; ledger entry)
narrative    draft_narrative (night pass 3)   → NarrativeDraft        (placeholders)
assemble     deterministic                    → RenderInput           (object + narrative + template@ver + locale)
render       tb.files.render (T3, post-gate)  → PDF, XLSX, JSON, FHIR, USDM, CDISC, SVG/PNG
package      deterministic                    → ZIP + manifest.json   (hashes, approval binding, PAdES)
```

**New package `libs/tb_reports/`.** It absorbs v1's `services/orchestrator/reports/common.py` plumbing.

| Module | Content |
| --- | --- |
| `model.py` | `DisclosedDeliverable`, `RenderInput` and `FigureSpec` (pydantic, exported to `schemas/`) |
| `figspec.py` | Builders from disclosed tables to `FigureSpec` |
| `backends/mpl.py` | Matplotlib on Agg: fixed rcParams, `svg.hashsalt`, metadata stripped (v1 `figure()`/`png()`). Produces SVG and PNG. |
| `backends/vegalite.py` | Vega-Lite v5 specifications with inline data, from the same `FigureSpec`. Used by the review page and the JSON package. |
| `palette.py`, `disclosure_fig.py`, `alttext.py`, `narrative.py`, `claims.py` | §12.2 |
| `pdf.py` | Jinja2 HTML → PDF/A-3b + PDF/UA-1 with embedded files via WeasyPrint (pinned) *(the combined variant must be proven in an MS1 spike; fallback: v1's reportlab plus a tagging post-processor; veraPDF decides)* |
| `xlsx.py` | openpyxl + `normalize_ooxml` |
| `exchange/fhir.py`, `exchange/usdm.py`, `exchange/cdisc.py` | §12.10 |
| `manifest.py`, `package.py` | Manifest, ZIP, `SHA256SUMS`, PAdES hook (§14 key service) |
| `packs/{feasibility,accrual,siteperf,data,prescreen,rwe}.py` | The TDS contract in code: section order and table and figure lists |
| `templates/<pack>/<locale>/` | Templates and ICU string catalogues |

**Purity.**
- Renderers are pure functions of `RenderInput`, pinned fonts and pinned libraries.
- No database, network, model or clock. Timestamps come from the manifest. No randomness.
- The PDF document id derives from the manifest hash.
- An import-linter contract forbids `tb_reports` from importing database, gateway or HTTP clients.

**One specification, two backends.** `FigureSpec` is canonical. A parity test renders the Vega-Lite output with a pinned offline renderer (`vl-convert`) and compares it with the matplotlib output on mark counts, labels, domains and annotations. Pixels are not compared.

**Golden tests.**
- **Location.** `tests/golden/reports/<pack>/<fixture>/` holds fixture objects built from Synthea, the MIMIC-IV demo and synthetic data (§16).
- **Fixture coverage.** Each pack has fixtures for:
  - a typical case;
  - small cells everywhere;
  - empty sections;
  - long CJK labels;
  - code-mixed quotes;
  - 40 criteria;
  - every tier.

The fixtures must pass these checks:

| Check | Pass condition |
| --- | --- |
| Data object | Hash equal to the golden |
| SVG | Canonical text equal to the golden (same architecture) |
| PNG | Byte-equal on the reference architecture; SSIM ≥ 0.99 between x86_64 and arm64 |
| PDF | veraPDF PDF/A-3b and UA-1 pass; extracted text and structure tree equal to the golden; embedded-file hashes equal to the shipped files |
| XLSX | Normalised bytes equal; `xlsx_lint` passes |
| JSON, FHIR, USDM, Dataset-JSON | Validators pass; content equal to the golden |
| Accessibility and language | Palette validator, alt text and typography lint pass; every shipped locale renders with no missing string |

**Updating goldens.** `tools/golden.py --update` writes goldens only on a branch. The pull request shows SVG diffs side by side and needs a reviewer other than the author. A template change that affects released deliverables is a G5 change (§18).

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| RPT-53 | Renderers MUST be pure. The import-linter contract MUST pass, and so MUST a test run with the network disabled and the clock frozen to a wrong date. | T | MS1 |
| RPT-54 | A released deliverable MUST regenerate byte-identically from its manifest on the same architecture (`trialbox deliverable regenerate`), and semantically identically across architectures (NFR-9, NFR-85). | T | MS1 |
| RPT-55 | Golden tests MUST cover every pack and fixture class on both architectures in CI. Goldens change only through a reviewed pull request. | T | MS1 |
| RPT-56 | `FigureSpec` MUST be the single source for both backends. Parity MUST pass for every figure type. | T | MS1 |
| RPT-57 | Template and catalogue versions MUST be recorded in the manifest. Template changes are G5 changes and MUST re-run the golden suite. | T, I | MS1 |
| RPT-58 | The research office's monthly report MUST track: days from request to release; share of questionnaire items auto-answered; sponsor rework requests per deliverable; G2 rejection reasons. | T | MS4 |

## 13. Non-functional requirements

### 13.1 Quality model and conventions

§13 is organised by the nine characteristics of ISO/IEC 25010:2023. Security is specified in §14 and safety in §10 (SAFE); §13 cross-references both.

| ISO/IEC 25010:2023 characteristic | Requirements | Owner |
| --- | --- | --- |
| Functional suitability | NFR-17–19 (bench gate); RPT-02, RPT-21–31 | §4, §12 |
| Performance efficiency (time, resources, capacity) | NFR-1–4, NFR-6, NFR-20, NFR-21–39, NFR-80–83 | §13 |
| Compatibility (co-existence, interoperability) | NFR-56; RPT-50–52; §5 standards | §13, §5, §12 |
| Interaction capability (usability, accessibility) | NFR-10, NFR-65–69; FR-UX | §13, §3 |
| Reliability (availability, fault tolerance, recoverability) | NFR-40–46 | §13, §18 |
| Security | NFR-14; SEC- | §14 |
| Maintainability | NFR-12, NFR-75–79 | §13, §17 |
| Flexibility (adaptability, scalability, installability) | NFR-55, NFR-57–59 | §13 |
| Safety (fail-safe, hazard warning) | SAFE-; NFR-85–86 | §10, §13 |

Localisation (NFR-60–64), observability (NFR-70–74) and cost (NFR-50–54) are cross-cutting requirements.

**Conventions.**
- Percentiles are measured over a rolling 30 days.
- "Day window" is the J-resident day pass, 07:00–19:00 by default (§4).
- Every numeric target has an SLI and an alert (NFR-71).
- Targets marked *(est.)* are confirmed per site at MS0.

**Disposition of v3 NFRs.**

| Disposition | v3 NFRs |
| --- | --- |
| Kept unchanged | NFR-1–4, 6, 9, 10, 12, 14, 20 |
| Kept, specified in §4 | NFR-17–19; NFR-B1–B5 (pass scheduler) |
| Superseded | **NFR-5** by NFR-21–23 (the ingest-window defect). **NFR-7** by NFR-40/41. **NFR-8** by NFR-42. **NFR-11** by NFR-60. **NFR-13** by NFR-55. **NFR-15** by NFR-70 (R3-24). **NFR-16** by NFR-50–53. |

### 13.2 Batch service levels (kept and corrected)

**Defect.** v3 published snapshot T in a fixed 19:00–21:00 window, but NFR-5 allowed 4 h for a 3M-patient ingest. Starting ingest earlier collides with the J-resident day pass and the memory budget (NFR-B5).

**Correction.**
- *Intra-day landing.* HL7 v2, CDC and FHIR `_since` deltas land in L0 and are validated in L1 through the day (§5).
- *Nightly publish.* The 19:00–21:00 window processes only the day's deltas through L2–L4. It reconciles full control totals, which are cheap count, max-delta and distinct-patient queries, then publishes T.
- *Full rebuilds* (initial load, G0 mapping change, terminology edition, recovery) run outside the nightly window.
- *Night pass 1* starts on publish (≤ 5 min after, NFR-25), 21:15 at the latest, rather than at a fixed 21:00. The pass tables in §4.6 and §18.2 state this.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| NFR-1 | Deterministic receipt acknowledgement within one intake poll (≤ 15 min), with no model involved. *(kept)* | T | MS0 |
| NFR-2 | Understanding email by 08:00 on the next working day after the confirmed command (or after receipt, for a grammar command), if it arrives by 17:00, with ≤ 40 criteria and ≤ 150 pages (FR-M1-26). *(revised)* | T | MS1 |
| NFR-3 | DL-1 ready for G2 by 08:00 on the working day after G1. *(kept)* | T | MS1 |
| NFR-4 | Nightly portfolio pre-screen of 30 recruiting studies and 20k scheduled patients finishes within the night passes on P-GB10 with ≥ 2× headroom (NFR-18). *(kept)* | T | MS2 |
| NFR-21 | **Nightly incremental publish.** With intra-day landing active, T (data to 19:00) MUST be published by 21:00 on ≥ 95 % of nights and by 21:15 on ≥ 99 %, for 3M patients and a daily change volume ≤ 2 % of rows *(est.; re-sized at MS0)*. No model is resident during publish. Shown by `pipeline_scale` (Synthea 3M, 2 % delta) on the reference profile. | T | MS1 |
| NFR-22 | **Full rebuild.** 3M patients through L0–L4 in ≤ 4 h (streaming, within NFR-B5). It MUST NOT run between 19:00 and 07:00 on working days. Default slot: Saturday 07:00–13:00 maintenance window with J unloaded, or on demand with passes suspended and the research office notified. | T | MS1 |
| NFR-23 | **Late-publish fallback.** If T is not published by 21:15, T−1 stays current (publish gate, §5), the night pass uses T−1's dirty set, morning outputs state "data as of {T−1}", and the steward receives the reason by 21:20. | T | MS1 |
| NFR-24 | **Deliverable timeliness.** DL-2 ready for G2 by the 3rd working day. DL-3 ≤ 5 working days after request. DL-6 ≤ 10 working days after freeze, for ≤ 20 analyses *(est.)*. DL-5 by 07:00 on clinic days. | T | MS4 |
| NFR-25 | Night pass 1 MUST start ≤ 5 min after publish, or at 21:15 under NFR-23. Minutes gained are recorded in the run manifest. | T | MS1 |

### 13.3 Ingestion service levels per stream

**Freshness** runs from the source event (message time, commit time or file drop) to availability. "Same day" means usable by the clinic-day and hospital-flagged-event logic in L5 serving (§5) within the same day pass.

| ID | Stream | Freshness | Throughput and completeness | On failure | V | R |
| --- | --- | --- | --- | --- | --- | --- |
| NFR-26 | HL7 v2 over MLLP (ADT A01/A04/A08/A40, SIU S12–S15, ORU R01, MDM T02) | ACK p95 ≤ 1 s; in L5 p95 ≤ 15 min (same day) | 50 msg/s sustained, 500 msg/s bursts for 60 s *(est.)*; dedupe on MSH-10; persist before ACK, zero loss | Sender retries on NAK; alarm after 30 min of silence in clinic hours | T | MS2 |
| NFR-27 | CDC (appointments, encounters, labs) | Micro-batch to L1 p95 ≤ 15 min | Lag alarm at 30 min | Fall back to the nightly view delta; steward alerted | T | MS2 |
| NFR-28 | HIS views (nightly delta) | Extract complete by 19:45 | Control totals reconciled: exact for same-transaction totals; ≤ 0.5 % only where the contract documents non-transactional totals (§5.9.1) (publish gate) | Gate blocks; NFR-23 applies | T | MS1 |
| NFR-29 | FHIR Bulk `$export` (`_since`), SMART Backend Services | Complete by 20:15 | All contracted types; NDJSON counts reconciled | As NFR-28 | T | MS1 |
| NFR-30 | CGRD-type research DB / TRE; CSV and registry drops; cohort tables | Research DB ≤ 2 working days after refresh; drops ≤ 1 working day; cohort quarterly | Contract-validated; SHA-256 sidecar verified | Quarantine with reason code | T | MS1 |
| NFR-31 | NHI MediCloud query (optional) | p95 ≤ 30 s *(uncertain; NHIA-dependent)* | Care events only, behind the legal-basis gate | Becomes `unknown:data_gap`; never blocks a run | T | MS4 |
| NFR-56 | **HIS co-existence** | — | ≤ 2 concurrent extract sessions; statement timeout agreed with the DBA (default 15 min); agreed window only; CDC reads log or change tables only; declared read account only | One retry, then quarantine | T, I | MS1 |

### 13.4 Interactive targets

Interactive work is cheap only over T0 tools (no patient data) and T1 tools (aggregates via the accountant) (C-4). Anything that needs judgement at S3 or beyond becomes a batch job with an acknowledgement.

Latency runs from server receipt (mail server receipt time, Teams activity time) to the reply being handed to the channel. The Hermes mailbox therefore uses push delivery (IMAP IDLE or Microsoft Graph change notifications), or polls at least every 15 s.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| NFR-32 | **Hermes over T0** (status, help, protocol Q&A, registry search, Atlas describe): p95 ≤ 60 s and p50 ≤ 20 s in the day window, with ≤ 20 concurrent conversations, on the reference profile. | T | MS1 |
| NFR-33 | **Hermes over T1** (deterministic S0–S2 aggregates on the current snapshot, `dc.internal`): p95 ≤ 60 s at 3M patients. If the planner predicts > 45 s, or the question needs S3+, the reply within 60 s MUST be an acknowledgement with an ETA, and the work becomes a batch job. | T | MS1 |
| NFR-34 | Outside the day window: a deterministic acknowledgement ≤ 60 s, and model answers by 08:00. Exceptions: an always-resident small model (P-Scale), or a topology C route permitted for the data class; NFR-32 then applies at all hours. | T | MS1 |
| NFR-35 | Teams and LINE nudges (no PHI): ≤ 5 min after the triggering event. | T | MS4 |
| NFR-36 | Signing and review pages: p95 server response ≤ 1 s and full render ≤ 3 s on the hospital LAN. Admin console: p95 ≤ 2 s. | T | MS2 |
| NFR-37 | CDS Hooks `patient-view` card (optional): p95 ≤ 500 ms, served from a table precomputed nightly. On timeout or error, return no card; never block the EHR. | T | MS5 |
| NFR-38 | Interactive model calls MUST use ≤ 15 % of day-pass GPU time (gateway budget, §8). When the budget is exhausted, replies are deterministic with an ETA. Interactive work never delays a gate reply or a deadline-bound batch item. | T | MS1 |
| NFR-39 | Grammar commands on Teams: deterministic acknowledgement ≤ 10 s. | T | MS4 |

### 13.5 Availability, recoverability and degraded modes

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| NFR-40 | **Durability.** No accepted request, gate reply or approval is lost in an outage of any length. Workflows resume from durable steps, and the outbox sends exactly once (§11). *(substance of v3 NFR-7)* | T | MS0 |
| NFR-41 | Availability per topology as tabled below (monthly; maintenance windows excluded; *(est.)*, confirmed in the site's service agreement). | T, A | MS3 |
| NFR-42 | RPO and RTO per topology and store as tabled below. CI-designated hospitals MUST hold a cold-standby unit; without one the 36 h target (SEC-97) is not claimed. | T | MS2 |
| NFR-43 | Full restore to a spare unit (A) or a clean tenant (B) MUST be tested quarterly, with a site-loss DR drill annually. Measured RPO and RTO go into the QA pack. A missed target opens a CAPA. | T | MS3 |
| NFR-44 | Degraded modes MUST behave as tabled below, each tested by fault injection (`tests/chaos/`). | T | MS2 |
| NFR-45 | DL-5 lists and scheduled deliverables on time on ≥ 98 % of working days per quarter (A), ≥ 99 % (A-HA, B). Every miss is explained in the QA pack. | T | MS3 |
| NFR-46 | No deliverable, gate or deadline may depend on a topology C cloud route. On loss of the route, the gateway falls back to on-prem within 5 min where the data class permits (§8). Otherwise the work carries over (NFR-B3). | T | MS4 |

**Availability targets.**

| Service | A (single appliance) | A-HA (warm standby, streaming replication) | B (tenant, zone-redundant) | C (hybrid) |
| --- | --- | --- | --- | --- |
| Front door, signing page, review page | 99.0 % (day window, working days) | 99.5 % (day window) | 99.5 % (24×7) | As base |
| Admin control plane | 99.0 % | 99.5 % | 99.5 % | As base |
| Cloud model route | — | — | — | Not counted (NFR-46) |

**RPO / RTO.**

| Store | A | A-HA | B |
| --- | --- | --- | --- |
| Workflows, gates, approvals, audit ledger (PostgreSQL) | RPO ≤ 15 min (continuous WAL archive to the backup disk and the immutable copy, §14). RTO ≤ 1 working day with a spare unit, ≤ 5 without *(est.)* | RPO ≤ 1 min; RTO ≤ 2 h | RPO ≤ 5 min (point-in-time recovery); RTO ≤ 4 h |
| Key material | RPO 0 (escrow, §14) | RPO 0 | RPO 0 (KMS/HSM) |
| Curated lake snapshots (L4) | RPO 24 h. RTO ≤ 1 working day: restore, or rebuild per NFR-22 | Same | RPO 24 h; RTO ≤ 8 h |
| Landing zone (L0, 90 days) | RPO 24 h; sources re-send | Same | Versioned object storage, RPO ≈ 0 |
| Released deliverables and manifests | RPO 0: written to the immutable copy before the outbox sends | Same | Same (object lock) |

Topology C inherits its base (A or B). v4 tightens v3's 24 h database RPO for A to 15 min. WAL archiving costs nothing on the appliance, and approvals and the audit ledger are the only records that cannot be regenerated.

**Degraded modes.**

| Failure | Behaviour |
| --- | --- |
| Hermes down | `channels.engine: native` serves email and the grammar. Kill switch and automatic health-check fallback: engine switched ≤ 60 s (FR-UX-23); full channel rollback incl. verification ≤ 15 min (§18.5.5). No loss (NFR-40). |
| Gateway down | No model calls. Deterministic intake, acknowledgements and rendering of approved objects continue. Model work carries over. |
| On-prem model down | Next permitted route. D3/D4 have none, so the work carries over and the research office is told if a deadline is at risk. |
| Source late or invalid | Publish gate; T−1 current (NFR-23); outputs state their data date. |
| Disclosure engine or accountant down | No external release (fail closed). Internal drafts continue. |
| Mail server down | Outbox retries with back-off. Gate deadlines are extended and recorded. |
| Signing page down | Level B gates wait. Level A replies are accepted. No alternative signing path is allowed. |

### 13.6 Capacity

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| NFR-6 | 300 active studies, 50 recruiting, 200 users. *(kept)* | A, T | MS4 |
| NFR-80 | On P-GB10 (4 TB NVMe), at ≤ 70 % planned use: 3M patients with 10 years of history, *(est.)* 600M structured facts and 150M notes (about 300 GB of canonical text), two L4 snapshots, 90 days of L0, OMOP, full-text and embedding indexes. Re-sized at MS0 from the Atlas; on exceedance, use an external tier or P-Scale. | T, A | MS1 |
| NFR-81 | Rendering after analysis and disclosure: ≤ 60 s per DL-1, DL-2 or DL-3; ≤ 5 min per DL-6. 50 DL-2s in ≤ 30 min. A 20k-patient DL-5 portfolio within the 06:30–07:00 assembly window. | T | MS4 |
| NFR-82 | Concurrency: 50 Hermes conversations (NFR-32 holds to 20; beyond that p95 ≤ 120 s), 20 page users, 10 T1 queries. | T | MS4 |
| NFR-83 | Sites with more than 50 recruiting studies or more than 3M patients MUST use P-Scale or topology B sizing, chosen by the bench gate (NFR-18). | A | MS6 |
| NFR-20 | Power and space: one desktop-class unit ≤ 300 W typical (P-GB10), or one workstation ≤ 1 kW (P-5090); fits a standard server-room shelf. *(kept)* | I | MS0 |

### 13.7 Cost ceilings and budgets

`tb-gateway` (§8) meters every call. Costs are aggregated per study, module, role, deliverable and month.
- On-prem cost = GPU-seconds × the site's amortised rate (hardware over 4 years plus measured energy, NFR-20).
- Cloud cost = provider price × recorded tokens.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| NFR-50 | Every model call MUST record tokens, GPU-seconds or provider cost, route and purpose. A monthly cost report goes to the research office: per study, module, role and deliverable; cost per pre-screened candidate; cost per DL-1. | T | MS1 |
| NFR-51 | **Topology C ceilings.** The site sets the monthly cloud-model ceiling at install; there is no vendor default. Optional sub-budgets per study and role. Alert at 80 %. At 100 %, cloud calls are refused and fall back on-prem where the class permits. Raising a ceiling is a G5 fast-track change (§11). | T | MS4 |
| NFR-52 | **On-prem budget.** Planned weekly LLM items ≤ 50 % of measured night capacity (NFR-18), under the global `night_tokens` budget (§4). Reported targets *(est.)*: ≤ 2 GPU-hours per DL-1 on P-GB10; a warm-cache portfolio fits in night pass 1. | T, A | MS1 |
| NFR-53 | **Topology B.** The install record includes a monthly infrastructure cost forecast (compute, GPU, storage, egress, KMS). Alert at 80 % of the approved budget. GPU nodes SHOULD stop outside passes where the provider supports it *(uncertain per provider)*. | T, A | MS4 |
| NFR-54 | OpenRouter bake-off use (D0 only, §8) runs under its own budget key with a hard cap per run, recorded in the bake-off report. | T | MS1 |

### 13.8 Flexibility

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| NFR-55 | One signed multi-arch image set (x86_64 and arm64) runs topologies A, B and C. The topology is configuration. Runtime egress is limited to the topology allowlist (§14). Only the gateway reaches model endpoints. | T | MS0 |
| NFR-57 | Topology B runs on any IaaS with GPU VMs, block storage, S3-compatible storage with object lock, and a KMS reached by PKCS#11, KMIP or an adapter. No provider-proprietary AI or data service sits in a D3/D4 path. Rootless Podman with `podman-compose` is the default (§17.2); a Helm chart is available by MS4. | T, I | MS4 |
| NFR-58 | Topology A installs to `trialbox doctor` green in ≤ 1 working day (excluding source approvals). A second site produces its first DL-1 ≤ 30 days after install. A new source is onboarded in ≤ 10 working days. | D | MS6 |
| NFR-59 | On exit, all hospital data and records can be exported in open formats within 10 working days: Parquet, FHIR NDJSON, OMOP CSV, the JSON audit ledger with its verifier, and PDF/A deliverables. | T | MS5 |

### 13.9 Interaction capability and accessibility

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| NFR-10 | A CRC completes stages 1–2 for a new protocol using only the 1-page guide; every message passes FR-UX-1. *(kept)* | T + D | MS1 |
| NFR-65 | Signing page, review page, admin control plane and CDS card content conform to WCAG 2.2 AA. Checked by axe-core in CI, plus a manual NVDA and VoiceOver pass on each release that changes a page. | T | MS2 |
| NFR-66 | Emails ≤ 600 px wide, with a plain-text part. Teams cards use Adaptive Cards schema ≤ 1.5. | T | MS1 |
| NFR-67 | PDF deliverables pass PDF/UA-1 (RPT-17), and figures meet RPT-10–13. | T | MS1 |
| NFR-68 | Pilot task times *(targets, est.)*, medians: a PI handles a 20-candidate clinic-day list in ≤ 15 min; a five-minute review item takes ≤ 5 min; the research office approves a DL-2 in ≤ 10 min. | D | MS3 |
| NFR-69 | Every admin-plane action is also available in the `trialbox` CLI. Destructive actions need confirmation and are reversible or gated. | T | MS1 |

### 13.10 Localisation

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| NFR-60 | zh-TW and en at MS1; ja at MS6. Code-mixed input accepted wherever input is accepted (C-8). | T | MS1 |
| NFR-61 | All user-visible strings live in ICU MessageFormat catalogues. CI fails on a missing key in a shipped locale, or on an unused key. | T | MS1 |
| NFR-62 | Machine outputs use ISO 8601, UCUM and dot decimals. Human outputs follow the locale. zh-TW internal documents MAY add ROC-era dates (ML-3); sponsor documents MUST NOT. | T | MS1 |
| NFR-63 | Embedded Noto Sans TC, JP and Latin fonts. Line breaking per UAX #14. `Lang` tags on mixed-script runs in PDFs. | T | MS1 |
| NFR-64 | Deliverable terms come from the glossary. Missing terms render in their source language and are listed on the release checklist. | T | MS1 |

### 13.11 Maintainability

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| NFR-12 | Coverage ≥ 85 % for deterministic code; `mypy --strict`; ruff. *(kept)* | T | MS0 |
| NFR-75 | New packages (`tb_analytics`, `tb_reports`, gateway, data-platform stages) meet NFR-12 from their first merge, with 100 % branch coverage on disclosure paths. | T | MS1 |
| NFR-76 | Import-linter contracts: renderers are pure (RPT-53); analytics are I/O-free; only the gateway imports model clients; Hermes-side code imports only the front-door MCP client. | T | MS0 |
| NFR-77 | Lead-time targets: model swap ≤ 1 working day of effort after the evaluation report (including G5); a new deliverable locale ≤ 5 working days; a new source ≤ 10 working days. | A | MS4 |
| NFR-78 | Dependencies are pinned with hashes and updated monthly. CVE SLA per NFR-14. | T | MS0 |
| NFR-14 | Security per §14; no critical or high CVEs open for more than 30 days in shipped images. *(kept)* | T | MS0 |
| NFR-79 | Every §12–§13 requirement is traced by `@req` to a test or inspection record (§17). | I | MS1 |

### 13.12 Observability

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| NFR-70 | All services, Hermes and the gateway included, emit OpenTelemetry traces, metrics and logs. W3C trace context propagates across workflow steps and gateway calls, and the trace id is stored in audit events. Traces go to the self-hosted, PHI-redacted trace store (§8), retained 90 days. | T | MS0 |
| NFR-71 | Every numeric NFR has an SLI recording rule, a dashboard panel and an alert (`deploy/observability/slo/*.yaml`). Monthly error budgets cover NFR-21, 26, 32, 33, 41 and 45. Burn above 2× alerts the administrator. | T | MS1 |
| NFR-72 | Logs are structured JSON and PHI-free. The PHI guard (§7) is tested on log sinks with planted identifiers. Operational logs are retained 1 year; the audit ledger follows §15. | T | MS0 |
| NFR-73 | Security events are exported to the hospital SIEM (syslog or CEF, §14). | T | MS2 |
| NFR-74 | An hourly synthetic probe runs a synthetic request through the active channel engine. Its study and patients are excluded from all reports. | T | MS2 |

### 13.13 Reproducibility and safety

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| NFR-9 | Any released output regenerates byte-identically from its manifest and recorded step outputs. *(kept)* | T | MS1 |
| NFR-85 | Across architectures, regenerated deliverables are semantically identical: data objects, JSON, XLSX and FHIR equal; SVG text equal; PNG SSIM ≥ 0.99. The manifest records the original architecture. | T | MS1 |
| NFR-86 | Fail-safe (with SAFE-, §10). If disclosure, number checking, quote verification or the recall certificate fails, the affected output is withheld, never sent degraded. Withholding is reported to the responsible role within one working day. | T | MS1 |
