# Gate 1 held expectations

Across the four shipped synthetic protocols, **2 of 25 previously executable presence criteria released (8%) and 23 held (92%)** on first extraction with successful audit receipts. The releases were GZQO’s type 1 diabetes and pancreatitis history. The holds include alternatives, conditional thresholds, clinical standards, clinic settings, exceptions, note questions and calendar intervals that a fixed number of days cannot represent.

| Protocol | Released | Held |
| --- | ---: | ---: |
| GZQO | 2 | 9 |
| AD-MAB | 0 | 3 |
| NEUR-COH | 0 | 2 |
| RA-JAK | 0 | 9 |

## Existing tests still failing

Fourteen failures expect compound or qualified protocol predicates to run. Five expect active-status logic, five expect a mapping or qualifier the gate cannot confirm, and four lack source text that supports the proposed logic.

| Test ID relative to `trialbox/` | Passage | Why the assertion fails |
| --- | --- | --- |
| `tests/unit/test_admit_presence.py::test_a_timed_alternative_needs_both_diagnoses_and_the_same_window_per_branch` | `Myocardial infarction or stroke within 90 days before screening.` | The assertion expects one executable predicate covering two distinct diagnoses. |
| `tests/unit/test_admit_presence.py::test_qualifying_text_and_the_mixed_fallback_must_agree` | `History of venous thromboembolism (deep vein thrombosis or pulmonary embolism).` | The assertion expects the gate to approve both an enumerated clinical definition and a separate notes question. |
| `tests/unit/test_any_of_groups.py::test_a_set_of_structured_alternatives_compiles_as_one_or_criterion` | `Hyperuricaemic gout:`<br>`Serum urate ≥6.8 mg/dL at screening, or ≥6.0 mg/dL if receiving urate-lowering therapy.` | The group includes a therapy-dependent threshold and the fixture’s replacement list disagrees with the source sections. |
| `tests/unit/test_any_of_groups.py::test_a_structured_lead_ins_own_requirement_stays_in_its_group` | `Hyperuricaemic gout:`<br>`Serum urate ≥6.8 mg/dL at screening, or ≥6.0 mg/dL if receiving urate-lowering therapy.` | The group includes a therapy-dependent threshold and the fixture’s replacement list disagrees with the source sections. |
| `tests/unit/test_clinical_status.py::test_the_compiler_reads_active_from_the_line[Active malignancy-True]` | `Active malignancy` | The active-status predicate also counts records with no clinical status. |
| `tests/unit/test_clinical_status.py::test_the_compiler_reads_active_from_the_line[Current or ongoing cancer-True]` | `Current or ongoing cancer` | The active-status predicate also counts records with no clinical status. |
| `tests/unit/test_clinical_status.py::test_the_compiler_reads_active_from_the_line[\u4e00\u5e74\u5167\u6709\u6d3b\u52d5\u6027\u7d50\u6838\u75c5\u3002-True]` | `一年內有活動性結核病。` | The predicate counts missing status and proposes malignancy for a passage about active tuberculosis. |
| `tests/unit/test_clinical_status.py::test_the_compiler_reads_active_from_the_line[\u6d3b\u52d5\u6027\u306e\u60aa\u6027\u816b\u760d-True]` | `活動性の悪性腫瘍` | The active-status predicate also counts records with no clinical status. |
| `tests/unit/test_clinical_status.py::test_the_compiler_reads_active_from_the_line[\u76ee\u524d\u6709\u60e1\u6027\u816b\u760d-True]` | `目前有惡性腫瘍` | The active-status predicate also counts records with no clinical status. |
| `tests/unit/test_compiler_service.py::test_compile_produces_draft_and_review` | [GZQO passages](#gzqo-passages) | The expected structured total includes nine qualified or compound GZQO passages. |
| `tests/unit/test_compiler_service.py::test_one_uncompilable_criterion_goes_to_review_instead_of_failing_the_protocol` | [GZQO passages](#gzqo-passages) | The expected structured total includes nine qualified or compound GZQO passages. |
| `tests/unit/test_compiler_service.py::test_reject_removes_criterion_from_compiled_artifacts` | `Myocardial infarction or stroke within 90 days before screening.` | The assertion expects the myocardial infarction or stroke column to remain in SQL after rejecting another criterion. |
| `tests/unit/test_diagnosis_filed_as_procedure.py::test_a_diagnosis_filed_as_a_procedure_is_refiled_and_flagged` | `invasive breast carcinoma`<br>`mastectomy`<br>`乳癌`<br>`gout` | The fixture expects mastectomy to run even though the terminology lookup returns no procedure code. |
| `tests/unit/test_encounter_atoms_need_a_code.py::test_a_diagnosis_filed_as_an_encounter_is_read_as_a_condition[Other acute abdominal diseases-acute abdominal disease]` | `Other acute abdominal diseases` | The open-ended abdominal disease category has no mapped code. |
| `tests/unit/test_encounter_atoms_need_a_code.py::test_a_diagnosis_filed_as_an_encounter_is_read_as_a_condition[The diagnosis of MDD consistent with DSM-IV (M.I.N.I)-major depressive disorder]` | `The diagnosis of MDD consistent with DSM-IV (M.I.N.I)` | The depression code cannot establish that the diagnosis met DSM-IV criteria on the specified interview. |
| `tests/unit/test_mixed_and_polarity.py::test_postprocess_flags_and_rewrites_negated_exclusions_and_accepts_mixed` | `x` | The placeholder “x” supplies no evidence for tuberculosis or for the rewritten dialysis question. |
| `tests/unit/test_mixed_keeps_its_note_question.py::test_a_mixed_criterion_that_runs_is_unchanged` | `line` | The placeholder “line” supplies no evidence for pneumonia. |
| `tests/unit/test_negated_exclusion_and_empty_lists.py::test_a_negated_exclusion_is_rewritten_positive_and_flagged` | `History of diabetes`<br>`Diabetes, and no other`<br>`No history of diabetes` | The gate holds the diabetes predicate because the compiler flagged its reversal from absence to presence for review. |
| `tests/unit/test_negated_inclusion_never_compiles_as_presence.py::test_the_counts_the_pull_request_reports` | [85 affected fixture lines](#negation-scorecard-passages) | The scorer passes each batch as extraction output alone, so additional presence rows move into the held totals. |
| `tests/unit/test_parser_terminology_review.py::test_concepts_never_share_a_valueset` | `痛風 病史`<br>`慢性腎臟病 病史`<br>`Type 2 diabetes 病史`<br>`type-2 diabetes 病史` | All four proposals lack a source and therefore refer to NONE in the emitted criteria, reducing the distinct reference count from four to one. |
| `tests/unit/test_presence_gate_invariants.py::test_numbered_protocol_items_released_from_the_original_passage[AD-MAB-released1]` | [AD-MAB passages](#ad-mab-passages) | The old release list includes specified drug types and a calendar-month stroke or TIA history. |
| `tests/unit/test_presence_gate_invariants.py::test_numbered_protocol_items_released_from_the_original_passage[GZQO-released0]` | [GZQO passages](#gzqo-passages) | The old release list includes separate cardiovascular and drug alternatives. |
| `tests/unit/test_presence_gate_invariants.py::test_numbered_protocol_items_released_from_the_original_passage[NEUR-COH-released2]` | [NEUR-COH passages](#neur-coh-passages) | The expected release combines multiple diagnoses, subtypes and code families. |
| `tests/unit/test_presence_gate_invariants.py::test_numbered_protocol_items_released_from_the_original_passage[RA-JAK-released3]` | [RA-JAK passages](#ra-jak-passages) | The old release list includes calendar intervals, alternative medications and a qualified mixed predicate. |
| `tests/unit/test_stray_atom_fields.py::test_a_held_mixed_line_keeps_its_note_question` | `Children aged 1 to 12 years with CAP` | The pneumonia question omits the passage’s restriction to children aged 1 to 12. |
| `tests/unit/test_synth_ad.py::test_committed_ruleset_is_the_current_compilers_output[AD-MAB-AD-MAB_\u6cbb\u9a13\u5b9f\u65bd\u8a08\u753b\u66f8_v1.docx-trial]` | [AD-MAB passages](#ad-mab-passages) | The committed snapshot executes qualified or compound criteria that the whole-passage gate sends to review. |
| `tests/unit/test_synth_ad.py::test_committed_ruleset_is_the_current_compilers_output[NEUR-COH-NEUR-COH_\u767b\u9332\u8a08\u753b\u66f8_v1.docx-cohort]` | [NEUR-COH passages](#neur-coh-passages) | The committed snapshot executes qualified or compound criteria that the whole-passage gate sends to review. |
| `tests/unit/test_synth_rajak.py::test_committed_ruleset_is_the_current_compilers_output` | [RA-JAK passages](#ra-jak-passages) | The committed snapshot executes qualified or compound criteria that the whole-passage gate sends to review. |

## AD-MAB passages

| Criterion | Original passage | Qualification |
| --- | --- | --- |
| AD-MAB-INC-02 | アルツハイマー病による軽度認知障害（MCI）または軽度のアルツハイマー型認知症と診断されている者（ICD-10-CM G31.84 または G30）。 | The diagnosis requires Alzheimer etiology and a mild stage. |
| AD-MAB-EXC-01 | スクリーニング前90日以内に抗凝固薬（ワルファリン、直接経口抗凝固薬）を使用した者。 | The passage specifies which anticoagulants count. |
| AD-MAB-EXC-03 | スクリーニング前12か月以内に脳卒中または一過性脳虚血発作（TIA）の既往がある者。 | The passage lists two diagnoses and the predicate treats 12 calendar months as 365 days. |

## GZQO passages

| Criterion | Original passage | Qualification |
| --- | --- | --- |
| GZQO-INC-02 | Diagnosis of gout according to the 2015 ACR/EULAR gout classification criteria. | A diagnosis code cannot establish the 2015 classification standard. |
| GZQO-INC-04 | Serum urate ≥6.8 mg/dL at screening, or ≥6.0 mg/dL if receiving urate-lowering therapy. | The urate threshold changes with treatment. |
| GZQO-INC-09 | Followed at the rheumatology or metabolism clinic with at least one visit in the past 12 months. | The patient must receive follow-up at the specified clinic. |
| GZQO-EXC-03 | Personal history of medullary thyroid carcinoma or multiple endocrine neoplasia type 2. | The exclusion names two diagnoses. |
| GZQO-EXC-04 | Use of a GLP-1 receptor agonist or GIP/GLP-1 receptor agonist within 90 days before screening. | The passage names two drug classes. |
| GZQO-EXC-05 | Prior or planned bariatric surgery. | Planned surgery also qualifies. |
| GZQO-EXC-07 | Malignancy within the past 5 years, except non-melanoma skin cancer. | The criterion excepts a cancer subtype. |
| GZQO-EXC-08 | Pregnant or breastfeeding, or positive pregnancy test. | The alternatives include breastfeeding and a test result. |
| GZQO-EXC-10 | Myocardial infarction or stroke within 90 days before screening. | Either of two distinct diagnoses qualifies. |

## NEUR-COH passages

| Criterion | Original passage | Qualification |
| --- | --- | --- |
| NEUR-COH-INC-01 | 軽度認知障害（MCI）または認知症（アルツハイマー型、血管性、その他）と診断されている者（ICD-10-CM G31.84、G30、F01〜F03）。 | The passage lists alternative diagnoses, subtypes and code families. |
| NEUR-COH-INC-02 | 過去12か月以内にもの忘れ外来（脳神経内科または精神科）を1回以上受診した者。 | A specialty visit alone cannot establish that the patient attended the specified memory clinic. |

## RA-JAK passages

| Criterion | Original passage | Qualification |
| --- | --- | --- |
| RA-JAK-INC-02 | Rheumatoid arthritis diagnosed at least 6 months before screening. | The predicate uses 180 days for six calendar months. |
| RA-JAK-EXC-01 | Any prior biologic DMARD or JAK inhibitor. | The exclusion names two medication classes. |
| RA-JAK-EXC-04 | Positive interferon-gamma release assay (IGRA) within 1 year without tuberculosis preventive therapy. | The test result qualifies only without preventive therapy. |
| RA-JAK-EXC-05 | Serious infection (sepsis or pneumonia) within 30 days before screening. | The infection must be serious. |
| RA-JAK-EXC-06 | Herpes zoster within 12 months before screening. | The predicate uses 365 days for 12 calendar months. |
| RA-JAK-EXC-07 | History of venous thromboembolism (deep vein thrombosis or pulmonary embolism). | The passage specifies two forms of thromboembolism and supplies a separate notes question. |
| RA-JAK-EXC-08 | Malignancy within the past 5 years. | The predicate uses 1,825 days for five calendar years. |
| RA-JAK-EXC-09 | Heart failure (NYHA class III or IV). | Heart failure must meet a specified NYHA class. |
| RA-JAK-EXC-10 | Pregnancy (a pregnancy diagnosis within 280 days). | The pregnancy predicate also reaches diagnoses recorded after pregnancy. |

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
