# docs/validation: the validation and quality records

*Card T-215 (deep review REG-027 (f)). Decision D-344. Status: living.*

The frame is the validation master plan, `docs/plan/25-vmp.md` (TB-VMP-01 v1.1). This folder holds the records it
names. Every record is written by the pull request or the tool that does the work; none is signed (D-311).

| File | What it is | Card |
| --- | --- | --- |
| [`qms-lite.md`](qms-lite.md) | the quality system: document control, records, training, evidence rules, the vendor pack | T-215 |
| [`standards-position.md`](standards-position.md) | IEC 62304 (light), IEC 82304-1 (guidance), ISO 13485 (trigger) | T-215 |
| [`change-control.md`](change-control.md) | change classes CC1 to CC6, release, the staged roll-out, emergency change | T-215 |
| [`functional-spec.md`](functional-spec.md) | the functional specification index, FS-01 to FS-17 | T-215 |
| [`supplier-assessments.md`](supplier-assessments.md) | suppliers by GAMP category, including the CGMH platform | T-215 |
| [`release-records/`](release-records/README.md) | one record per release | T-215 (layout); the release step |
| [`software-safety-classification.md`](software-safety-classification.md) | internal 62304-style class per path | T-654 |
| [`development-plan.md`](development-plan.md) | how a change is made, checked and recorded | T-654 |
| [`soup.csv`](soup.csv) | the SOUP list, model weights included | T-654 |
| [`problems.csv`](problems.csv) | the problem log; deviations and CAPA (VMP §6) | T-654 |
| [`ai-governance.md`](ai-governance.md) | the AI governance note: who answers for the models, what they may and may not do | T-649b |
| [`model-change-protocol.md`](model-change-protocol.md) | the model change protocol: the qualify steps and their thresholds | T-649b |
| [`record-inventory.md`](record-inventory.md) | every record the box makes or holds: class, system of record, keeper, retention, export, audit events; the store map | T-643 |
| [`erasure-registry.md`](erasure-registry.md) | generated from `libs/tb_common/erasure.py`: what an opt-out erases, keeps (with the decision) and still owes, per table, lake folder and store | T-727 |
| [`soa.csv`](soa.csv) | the statement of applicability: ISO/IEC 27001:2022 Annex A, 93 controls, who each applies to (product, Aimedics, hospital), evidence or a reason | T-649c |
| `protocols/` | IQ, OQ, PQ protocols, only under TB-PLAN-06 §0.3 item 2 (planned) | T-315b |

Not here, by D-311: `gates/` (gate records, B1), `risk-register.md` (one risk file, B18; the risk file stays TB-PLAN-05
§6 and TB-DS-11), `part11-ers.md` and `source-and-copies.md` (B27), `e6r3-section4.md` (B27).

`tests/unit/test_validation_records.py` checks this folder: the files above exist (the four of T-654 once that card
merges), every FS id of the traceability matrix has a row in `functional-spec.md`, each change class is defined once,
and the paths the records name exist.
