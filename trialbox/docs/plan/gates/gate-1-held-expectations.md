# Gate 1 held expectations

Across the four shipped synthetic protocols, of the **25 presence criteria** that ran before the gate, **2 are released by the plain rule** (GZQO's type 1 diabetes and pancreatitis history), **21 by the labelled approvals shipped with the protocol** (owner's ruling, 2026-11-22; see [gate-1.md](gate-1.md)) and **2 are still held**: GZQO-EXC-05 "Prior or planned bariatric surgery." (a planned, hypothetical clause) and RA-JAK-EXC-04 "Positive interferon-gamma release assay (IGRA) within 1 year without tuberculosis preventive therapy." (negated in part). The owner's rule gives a negated, other-person or hypothetical line no shipped approval.

| Protocol | Plain rule | Shipped approval | Held |
| --- | ---: | ---: | ---: |
| GZQO | 2 | 8 | 1 |
| AD-MAB | 0 | 3 | 0 |
| NEUR-COH | 0 | 2 | 0 |
| RA-JAK | 0 | 8 | 1 |

## Existing tests still failing

Thirteen of the 28 failures listed in round 1 remain. Fifteen now pass with no change to their assertions: seven through the shipped approvals (the gate's four protocol release tests, the AD-MAB and NEUR-COH snapshot tests, the GZQO reject test), and eight through a person's recorded approval of the test's own exact text in its set-up (the gate's alternative and qualified-line tests, five active-status lines, the DSM-IV line). Every row below is category (c): neither a shipped approval nor an approval of the test's own text can apply, so it waits for an assertion ruling.

| Test ID relative to `trialbox/` | Passage | Why it still fails |
| --- | --- | --- |
| `tests/unit/test_compiler_service.py::test_compile_produces_draft_and_review` | GZQO-EXC-05 `Prior or planned bariatric surgery.` | The count of 18 structured lines includes the planned-surgery exclusion, which gets no shipped approval (hypothetical). |
| `tests/unit/test_compiler_service.py::test_one_uncompilable_criterion_goes_to_review_instead_of_failing_the_protocol` | GZQO-EXC-05 `Prior or planned bariatric surgery.` | The same count, less the one uncompilable line, still includes the planned-surgery exclusion. |
| `tests/unit/test_synth_rajak.py::test_committed_ruleset_is_the_current_compilers_output` | RA-JAK-EXC-04 `Positive interferon-gamma release assay (IGRA) within 1 year without tuberculosis preventive therapy.` | The committed snapshot runs the IGRA exclusion, which gets no shipped approval (negated in part). |
| `tests/unit/test_any_of_groups.py::test_a_set_of_structured_alternatives_compiles_as_one_or_criterion` | `Hyperuricaemic gout:`<br>`Serum urate ≥6.8 mg/dL at screening, or ≥6.0 mg/dL if receiving urate-lowering therapy.` | Each member sits under a lead-in, so the passage the gate reads (lead-in and line) is not the proposal's own text, and an approval, which needs both to be one exact text, cannot bind it; the therapy-dependent threshold also stays. |
| `tests/unit/test_any_of_groups.py::test_a_structured_lead_ins_own_requirement_stays_in_its_group` | `Hyperuricaemic gout:`<br>`Serum urate ≥6.8 mg/dL at screening, or ≥6.0 mg/dL if receiving urate-lowering therapy.` | The same: the members sit under lead-ins, so no approval of one exact text can bind them. |
| `tests/unit/test_diagnosis_filed_as_procedure.py::test_a_diagnosis_filed_as_a_procedure_is_refiled_and_flagged` | `invasive breast carcinoma`<br>`mastectomy`<br>`乳癌`<br>`gout` | The terminology lookup returns no procedure code for mastectomy, and a line with no code cannot be approved. |
| `tests/unit/test_encounter_atoms_need_a_code.py::test_a_diagnosis_filed_as_an_encounter_is_read_as_a_condition[Other acute abdominal diseases-acute abdominal disease]` | `Other acute abdominal diseases` | The open-ended category has no mapped code, so it cannot be approved. |
| `tests/unit/test_mixed_and_polarity.py::test_postprocess_flags_and_rewrites_negated_exclusions_and_accepts_mixed` | `x` | The placeholder "x" is no text a person could approve for tuberculosis or for the rewritten dialysis question. |
| `tests/unit/test_mixed_keeps_its_note_question.py::test_a_mixed_criterion_that_runs_is_unchanged` | `line` | The placeholder "line" is no text a person could approve for pneumonia. |
| `tests/unit/test_negated_exclusion_and_empty_lists.py::test_a_negated_exclusion_is_rewritten_positive_and_flagged` | `History of diabetes`<br>`Diabetes, and no other`<br>`No history of diabetes` | The compiler flags the reversal from absence to presence, and no approval releases a negated proposal. |
| `tests/unit/test_negated_inclusion_never_compiles_as_presence.py::test_the_counts_the_pull_request_reports` | [85 affected fixture lines](#negation-scorecard-passages) | The scorer's lines are mostly negated or qualified; approving all of them would defeat the scorecard, so none is approved. |
| `tests/unit/test_parser_terminology_review.py::test_concepts_never_share_a_valueset` | `痛風 病史`<br>`慢性腎臟病 病史`<br>`Type 2 diabetes 病史`<br>`type-2 diabetes 病史` | `慢性腎臟病` has no code on this box (`concept_unmapped`), so that line cannot be approved and the four distinct ValueSets cannot all appear. |
| `tests/unit/test_stray_atom_fields.py::test_a_held_mixed_line_keeps_its_note_question` | `Children aged 1 to 12 years with CAP` | The age on a condition makes the proposal a note already marked held (`presence_requires_review`); no approval releases a held proposal. |

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
