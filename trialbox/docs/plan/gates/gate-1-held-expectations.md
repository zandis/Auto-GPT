# Gate 1 held expectations

Of the 26 previously failing reader tests, two now pass. The rejection test retains the supported 90-day myocardial infarction or stroke criterion in SQL. The incremental-diff test recognizes unchanged items under numbered eligibility headings. The gate's released examples cover 12 protocol passages across the four compiled protocols.

## Tests awaiting a ruling

B marks a direct expectation about a criterion that needs review. C marks a downstream snapshot or count affected by those holds. The direct postprocessor fixtures supply only `LlmExtractOutput`. The production compiler obtains the original passage separately from `ParsedDoc.sections`. Test IDs are relative to `trialbox/`.

| Test ID | Criterion text | A/B/C | Why it still fails |
| --- | --- | :---: | --- |
| `tests/unit/test_any_of_groups.py::test_a_set_of_structured_alternatives_compiles_as_one_or_criterion` | `Hyperuricaemic gout:`<br>`Serum urate ≥6.8 mg/dL at screening, or ≥6.0 mg/dL if receiving urate-lowering therapy.` | B | The fixture replaces the list without replacing the source sections, and the urate threshold depends on whether the participant takes therapy. |
| `tests/unit/test_any_of_groups.py::test_a_structured_lead_ins_own_requirement_stays_in_its_group` | `Hyperuricaemic gout:`<br>`Serum urate ≥6.8 mg/dL at screening, or ≥6.0 mg/dL if receiving urate-lowering therapy.` | B | The fixture replaces the list without replacing the source sections, and the urate threshold depends on whether the participant takes therapy. |
| `tests/unit/test_clinical_status.py::test_the_compiler_reads_active_from_the_line[Active malignancy-True]` | `Active malignancy` | B | The direct postprocessor call supplies no source for the proposed active-malignancy exclusion. |
| `tests/unit/test_clinical_status.py::test_the_compiler_reads_active_from_the_line[Current or ongoing cancer-True]` | `Current or ongoing cancer` | B | Only the extraction asserts current disease, so there is no passage against which to verify that qualifier. |
| `tests/unit/test_clinical_status.py::test_the_compiler_reads_active_from_the_line[\u4e00\u5e74\u5167\u6709\u6d3b\u52d5\u6027\u7d50\u6838\u75c5\u3002-True]` | `一年內有活動性結核病。` | B | The proposal pairs a tuberculosis passage with malignancy codes and supplies no independent source. |
| `tests/unit/test_clinical_status.py::test_the_compiler_reads_active_from_the_line[\u6d3b\u52d5\u6027\u306e\u60aa\u6027\u816b\u760d-True]` | `活動性の悪性腫瘍` | B | The Japanese phrase occurs only in the proposed extraction, so the active-status predicate lacks an independent passage. |
| `tests/unit/test_clinical_status.py::test_the_compiler_reads_active_from_the_line[\u76ee\u524d\u6709\u60e1\u6027\u816b\u760d-True]` | `目前有惡性腫瘍` | B | The fixture supplies the current-malignancy phrase only as model output. |
| `tests/unit/test_compiler_answers_every_failure.py::test_a_criterion_that_cannot_run_is_a_persons_check_and_the_rest_compiles` | `History of stroke` | B | The fixture supplies only model output for the stroke history that it expects to compile. |
| `tests/unit/test_compiler_answers_every_failure.py::test_the_comparison_refused_by_the_fhir_server_is_a_422` | `History of stroke` | B | The fixture supplies only model output for the stroke history, so the gate holds the criterion before the FHIR comparison. |
| `tests/unit/test_compiler_service.py::test_compile_produces_draft_and_review` | [Seven GZQO passages](#gzqo-passages) | C | Seven patient predicates need review, which reduces the expected structured count from 18 to 11. |
| `tests/unit/test_compiler_service.py::test_one_uncompilable_criterion_goes_to_review_instead_of_failing_the_protocol` | [Seven GZQO passages](#gzqo-passages) | C | The deliberately broken criterion still goes to review, and the seven additional holds reduce the expected structured count from 17 to 10. |
| `tests/unit/test_diagnosis_filed_as_procedure.py::test_a_diagnosis_filed_as_a_procedure_is_refiled_and_flagged` | `invasive breast carcinoma`<br>`mastectomy`<br>`乳癌`<br>`gout` | B | Refiling the extracted concepts supplies no independent source for any of the four proposed coded predicates. |
| `tests/unit/test_encounter_atoms_need_a_code.py::test_a_diagnosis_filed_as_an_encounter_is_read_as_a_condition[Other acute abdominal diseases-acute abdominal disease]` | `Other acute abdominal diseases` | B | The fixture supplies an open-ended disease category only as model output. |
| `tests/unit/test_encounter_atoms_need_a_code.py::test_a_diagnosis_filed_as_an_encounter_is_read_as_a_condition[Patients with acute appendicitis-acute appendicitis]` | `Patients with acute appendicitis` | B | The fixture supplies the patient wording only in model output, even though the proposed diagnosis reads clearly. |
| `tests/unit/test_encounter_atoms_need_a_code.py::test_a_diagnosis_filed_as_an_encounter_is_read_as_a_condition[The diagnosis of MDD consistent with DSM-IV (M.I.N.I)-major depressive disorder]` | `The diagnosis of MDD consistent with DSM-IV (M.I.N.I)` | B | The fixture gives no source for the DSM-IV and interview qualifications in the extracted line. |
| `tests/unit/test_mixed_and_polarity.py::test_postprocess_flags_and_rewrites_negated_exclusions_and_accepts_mixed` | `x` | B | The source-less placeholder supports neither the tuberculosis code nor the rewritten dialysis question. |
| `tests/unit/test_mixed_keeps_its_note_question.py::test_a_mixed_criterion_that_runs_is_unchanged` | `line` | B | The fixture puts pneumonia in a question and a proposed code while its criterion text is a placeholder. |
| `tests/unit/test_negated_exclusion_and_empty_lists.py::test_a_negated_exclusion_is_rewritten_positive_and_flagged` | `History of diabetes`<br>`Diabetes, and no other`<br>`No history of diabetes` | B | Rewriting the proposed negation on “History of diabetes” gives no independent evidence for executing the diabetes predicate. |
| `tests/unit/test_negated_inclusion_never_compiles_as_presence.py::test_the_counts_the_pull_request_reports` | [85 affected fixture lines](#negation-scorecard-passages) | C | The scorer passes each batch as extraction output alone, so additional presence rows move into the held totals. |
| `tests/unit/test_parser_terminology_review.py::test_concepts_never_share_a_valueset` | `痛風 病史`<br>`慢性腎臟病 病史`<br>`Type 2 diabetes 病史`<br>`type-2 diabetes 病史` | C | All four proposals lack a source and therefore refer to NONE in the emitted criteria, reducing the distinct reference count from four to one. |
| `tests/unit/test_stray_atom_fields.py::test_a_held_mixed_line_keeps_its_note_question` | `Children aged 1 to 12 years with CAP` | B | There is no independent passage and the proposed pneumonia question omits the age restriction. |
| `tests/unit/test_synth_ad.py::test_committed_ruleset_is_the_current_compilers_output[AD-MAB-AD-MAB_\u6cbb\u9a13\u5b9f\u65bd\u8a08\u753b\u66f8_v1.docx-trial]` | `アルツハイマー病による軽度認知障害（MCI）または軽度のアルツハイマー型認知症と診断されている者（ICD-10-CM G31.84 または G30）。` | C | The snapshot expects G31.84 or G30 alone to establish the required Alzheimer etiology and mild stage. |
| `tests/unit/test_synth_ad.py::test_committed_ruleset_is_the_current_compilers_output[NEUR-COH-NEUR-COH_\u767b\u9332\u8a08\u753b\u66f8_v1.docx-cohort]` | `過去12か月以内にもの忘れ外来（脳神経内科または精神科）を1回以上受診した者。` | C | The snapshot counts any neurology or psychiatry encounter as a visit to the specified memory clinic. |
| `tests/unit/test_synth_rajak.py::test_committed_ruleset_is_the_current_compilers_output` | [Four RA-JAK passages](#ra-jak-passages) | C | The snapshot expects four qualified exclusions to execute even though their coded predicates leave the qualifications unresolved. |

## GZQO passages

| Criterion | Original text | Why the coded predicate is held |
| --- | --- | --- |
| GZQO-INC-02 | Diagnosis of gout according to the 2015 ACR/EULAR gout classification criteria. | A gout diagnosis code alone cannot establish classification under the 2015 ACR/EULAR criteria. |
| GZQO-INC-04 | Serum urate ≥6.8 mg/dL at screening, or ≥6.0 mg/dL if receiving urate-lowering therapy. | The lower threshold depends on receiving therapy, so therapy is a conditional branch of the criterion. |
| GZQO-INC-09 | Followed at the rheumatology or metabolism clinic with at least one visit in the past 12 months. | A single specialty visit in the past year leaves ongoing follow-up at that clinic unresolved. |
| GZQO-EXC-03 | Personal history of medullary thyroid carcinoma or multiple endocrine neoplasia type 2. | The thyroid branch uses C73, which includes thyroid cancers of other histologies. |
| GZQO-EXC-05 | Prior or planned bariatric surgery. | The passage includes planned surgery, which a completed procedure code cannot establish. |
| GZQO-EXC-07 | Malignancy within the past 5 years, except non-melanoma skin cancer. | The mapped list includes Merkel cell carcinoma (C4A), a non-melanoma skin cancer the passage excepts. |
| GZQO-EXC-08 | Pregnant or breastfeeding, or positive pregnancy test. | The pregnancy and laboratory branches omit breastfeeding. |

## RA-JAK passages

| Criterion | Original text | Why the coded predicate is held |
| --- | --- | --- |
| RA-JAK-EXC-04 | Positive interferon-gamma release assay (IGRA) within 1 year without tuberculosis preventive therapy. | The positive test qualifies only in the absence of preventive therapy. |
| RA-JAK-EXC-05 | Serious infection (sepsis or pneumonia) within 30 days before screening. | A pneumonia code alone leaves the required seriousness of the infection unresolved. |
| RA-JAK-EXC-09 | Heart failure (NYHA class III or IV). | A heart failure code alone leaves the required NYHA class unresolved. |
| RA-JAK-EXC-10 | Pregnancy (a pregnancy diagnosis within 280 days). | The proposed pregnancy list includes puerperal complications such as O85, which can be recorded after pregnancy. |

## Negation scorecard passages

All four fixtures pass source-less extractions to `postprocess`. Every row previously expected to hold still holds. The table counts additional holds among rows labelled `runs`, followed by their original texts in fixture order.

| Fixture | Previously held / labelled runs | Now held / labelled runs | Additional holds |
| --- | ---: | ---: | ---: |
| [lines.json](../../../tests/fixtures/negated_inclusion/lines.json) | 8/69 | 59/69 | 51 |
| [unseen_at_design.json](../../../tests/fixtures/negated_inclusion/unseen_at_design.json) | 20/23 | 23/23 | 3 |
| [card_10a1b.json](../../../tests/fixtures/negated_inclusion/card_10a1b.json) | 17/40 | 40/40 | 23 |
| [review_10a1b.json](../../../tests/fixtures/negated_inclusion/review_10a1b.json) | 0/8 | 8/8 | 8 |

<details>
<summary>lines.json (51 additional holds)</summary>

- `No more than 2 prior lines of chemotherapy`
- `Not more than 12 weeks since prior chemotherapy`
- `No longer responding to chemotherapy`
- `Patients who have not responded to chemotherapy`
- `No restriction on prior chemotherapy`
- `No upper age limit; prior chemotherapy`
- `無年齡上限，曾接受化學治療`
- `無法切除之肝癌，曾接受化學治療`
- `化学療法歴があり、手術適応がない`
- `無法手術切除的肝癌`
- `未經治療的晚期肺癌`
- `無症狀之腦轉移`
- `Histologically confirmed adenocarcinoma, not amenable to surgery`
- `Anovulatory patients who did not conceive after a minimum of three ovulatory cycles`
- `Patients with cutaneous leg ulcers due to diabetes mellitus, not healing after 4 weeks`
- `Non-small cell lung cancer`
- `Noninvasive breast cancer`
- `Nonsmokers with asthma`
- `Notable history of chemotherapy`
- `非小細胞肺癌`
- `未満18歳の化学療法歴のある患者`
- `未滿75歲且曾接受化學治療`
- `非小細胞肺癌の患者で化学療法を受けたもの`
- `Hypertension not controlled by two agents`
- `Asthma that has not responded to inhaled steroids`
- `Received at least one prior line of chemotherapy`
- `高血圧の既往がある`
- `化学療法の前治療歴を有する`
- `曾接受至少一線化學治療`
- `確診類風濕性關節炎`
- `高血壓且未受控制`
- `Non-alcoholic fatty liver disease`
- `Non-Hodgkin lymphoma`
- `Peripheral T-cell lymphoma, not otherwise specified, confirmed by central pathology.`
- `Non-alcoholic steatohepatitis`
- `Non-ST-elevation myocardial infarction`
- `Non-invasive bladder cancer`
- `Non-metastatic prostate cancer`
- `Nonsquamous non-small cell lung cancer`
- `非ホジキンリンパ腫と診断されている。`
- `びまん性大細胞型B細胞リンパ腫（非ホジキンリンパ腫）と診断されている。`
- `無症状の胆石症を有する患者。`
- `非アルコール性脂肪肝炎と診断された患者`
- `非ST上昇型心筋梗塞の既往がある`
- `非浸潤性乳管癌`
- `非扁平上皮非小細胞肺癌`
- `非酒精性脂肪肝炎`
- `非ST段上升心肌梗塞病史`
- `無症狀膽結石`
- `非小細胞肺癌，非鱗狀細胞型`
- `非何杰金氏淋巴瘤`

</details>

<details>
<summary>unseen_at_design.json (3 additional holds)</summary>

- `化学療法後に増悪が認められない患者。`
- `No progression after chemotherapy.`
- `化學治療後未見惡化。`

</details>

<details>
<summary>card_10a1b.json (23 additional holds)</summary>

- `Must have had prior surgery; no prior hormonal therapy.`
- `Prior chemotherapy is required; no prior radiotherapy.`
- `Chemotherapy but not surgery.`
- `Diagnosis of rheumatoid arthritis; no prior biologic therapy.`
- `Type 2 diabetes without ketoacidosis.`
- `Receiving metformin; no history of lactic acidosis.`
- `Atrial fibrillation; not on anticoagulant therapy.`
- `Documented penicillin allergy, without anaphylaxis.`
- `Prior surgery, but no radiotherapy.`
- `Pregnant women with no fetal anomalies.`
- `Chronic hepatitis B, with no cirrhosis.`
- `Prior surgery is required.`
- `Has had prior chemotherapy.`
- `手術歴はあるが、放射線治療歴はない。`
- `2型糖尿病と診断され、ケトアシドーシスを伴わない患者。`
- `心房細動を有するが、抗凝固療法は受けていない。`
- `化学療法を受けたことがある患者。`
- `妊娠中の女性で、胎児異常を認めない。`
- `曾接受手術,但未曾接受放射線治療。`
- `診斷為第二型糖尿病,且無酮酸中毒。`
- `第二型糖尿病,未使用胰島素。`
- `曾接受化學治療之患者。`
- `懷孕之婦女,且未發現胎兒異常。`

</details>

<details>
<summary>review_10a1b.json (8 additional holds)</summary>

- `Type 2 diabetes; metformin is not contraindicated.`
- `Type 2 diabetes with no restriction on diet.`
- `Prior chemotherapy is not prohibited.`
- `化学療法が不可欠な患者。`
- `2型糖尿病で、メトホルミンの禁忌なし。`
- `化学療法の前治療は禁止されていない。`
- `需要化學治療，且化學治療不可或缺。`
- `手術切除後之第二型糖尿病患者。`

</details>
