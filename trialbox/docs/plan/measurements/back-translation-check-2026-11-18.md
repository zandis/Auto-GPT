# Back-translation check of `criterion_ml` ja and zh-TW: card 10G-35, 2026-11-18

**Reader: a machine reader, not a clinician and not a native medical translator.** The verdicts below are a machine
reader's reading of meaning. They do not verify the translations clinically. The README's "not clinician-verified" stays
until a human reader has checked the lists below; this card does not remove it.

Lane H, plan 10 row 10G-35 (`docs/plan/47-plan-10-2026-11-18.md`, Track G; source card 20-11 in
`docs/reviews/2026-11-root/20-gold-data-open-sources.md`). Prerequisite 10H-1 (card H-37,
`docs/plan/measurements/eval-licence-labels-2026-11-18.md`): the notes and their translations are CC BY-SA 4.0.

## How it was done

- Data: `eval/criterion_ml/notes_en.json` (source), `notes_ja.json`, `notes_zh-TW.json`; 53 notes, 326 sentences per
  language, sentence for sentence. Sentence id `<patient_id>#<index>`, 0-based, the numbering of the evidence ids in
  `annotations.jsonl`.
- Every sentence of both translations was read (326 of 326 per language; no sampling, so no seed). The 53 copies of
  the closing consent sentence are one template per language, read once and recorded 53 times (`repeated_template`).
- For each sentence the reader wrote its own English back-translation of the translation, reading only (no external
  service, no model call, no script that translates), and compared it with the English source for meaning. Kinds of
  difference: `number_or_unit`, `negation`, `time_window`, `dropped_condition`, `wrong_term`, `added_detail`,
  `certainty`, `register` (register only: meaning kept). Severity: `medium` if a criterion could be judged
  differently, else `low`.
- Records: [`back-translation-check-2026-11-18/ja.json`](back-translation-check-2026-11-18/ja.json) and
  [`zh-TW.json`](back-translation-check-2026-11-18/zh-TW.json), one per sentence: id, source, translation,
  back-translation, verdict, kinds, severity, what differs, proposed correction.
- The translations were not changed (H-37 left open whether they stay); corrections are proposals only.
- Test: `tests/unit/test_criterion_ml_back_translation_check.py` (files well formed; ids, sources and translations
  equal the eval files; the counts below equal the files).

## Counts

| Language | Sentences in the file | Read | Equal | Differs | Register only |
| --- | --- | --- | --- | --- | --- |
| ja | 326 | 326 | 262 | 64 | 1 |
| zh-TW | 326 | 326 | 319 | 7 | 1 |

Differing sentences by kind (a sentence may carry more than one kind):

| Kind | ja | zh-TW |
| --- | --- | --- |
| `number_or_unit` | 0 | 0 |
| `negation` | 0 | 0 |
| `time_window` | 3 | 1 |
| `dropped_condition` | 1 | 1 |
| `wrong_term` | 5 | 2 |
| `added_detail` | 1 | 2 |
| `certainty` | 53 | 0 |
| `register` | 1 | 1 |

Severity: ja 2 medium, 62 low; zh-TW 2 medium, 5 low. No number, unit or negation differs in either language. The ja
count is dominated by one template: the consent sentence, 53 times, hedged in Japanese (one finding, not 53).

## Lists for the human reader

Source sentences: SIGIR 2016 patient descriptions (Koopman B., Zuccon G., CSIRO,
https://researchdata.edu.au/a-test-collection-clinical-trials/664508; "All Rights (including copyright) CSIRO, U.S.
National Institute of Standards, U.S. National Institutes of Health 2016"), CC BY-SA 4.0
(https://creativecommons.org/licenses/by-sa/4.0/). Translations: TrialBox machine translations (October 2026),
CC BY-SA 4.0. The back-translations and notes on this page and in the two files are adapted from them and offered under
CC BY-SA 4.0. Attribution in full: `eval/criterion_ml/NOTICE.md`.

### ja (12 findings, 64 sentences)

| Id | Source | Translation | Back-translation | What differs | Sev. |
| --- | --- | --- | --- | --- | --- |
| sigir-20147#2 | She also states that she has had thoughts of suicide. | 希死念慮もあったと述べている。 | She states that she also had a wish to die (passive death wish). | `wrong_term`: 希死念慮 is a passive wish to die; the source says suicidal thoughts (自殺念慮) | medium |
| sigir-20158#0 | A 10 yo boy with nighttime snoring, pauses in breathing, and restlessness with nighttime awakenings. | 10歳男児。夜間のいびき、呼吸停止、夜間覚醒を伴う落ち着きのなさを認める。 | 10-year-old boy. Night-time snoring, respiratory arrest, and restlessness with night-time awakening. | `wrong_term`: 呼吸停止 reads as respiratory arrest, not pauses (呼吸休止 / 無呼吸) | medium |
| sigir-20159#4 | Physical exam findings include cyanosis, slight stiffness of the neck, and marked periorbital edema. | 身体所見としてチアノーゼ、軽度の項部硬直、著明な眼窩周囲浮腫を認める。 | Physical findings: cyanosis, mild nuchal rigidity, marked periorbital oedema. | `wrong_term`: neck stiffness becomes the meningeal sign 項部硬直 | low |
| sigir-20148#0 | A 62-year-old man sees a neurologist for progressive memory loss and jerking movements of the lower extremities. | 62歳男性。進行性の記憶障害と下肢のミオクローヌス様不随意運動を主訴に神経内科を受診。 | 62-year-old man. Came to neurology with progressive memory impairment and myoclonus-like involuntary movements of the lower limbs. | `wrong_term`: "jerking" interpreted as myoclonus-like | low |
| sigir-201424#4 | The patient is pale, the physical examination of the abdomen revealed muscle contraction and resistance. | 顔面蒼白であり、腹部診察では筋性防御と抵抗を認めた。 | Pale face; abdominal examination showed muscular guarding and resistance. | `wrong_term`: "muscle contraction" interpreted as guarding (筋性防御) | low |
| sigir-201418#0 | A 6-month-old male infant has a urine output of less than 0.2 mL/kg/hr shortly after undergoing major surgery. | 生後6か月の男児。大手術施行直後より尿量0.2 mL/kg/hr未満。 | 6-month-old boy. Urine output below 0.2 mL/kg/hr from immediately after major surgery. | `time_window`: "shortly after" becomes "from immediately after" | low |
| sigir-201411#0 | … excruciating pain in her right arm that had started 1 hour prior to her admission. | 既往歴のない40歳女性。来院1時間前に発症した右上肢の激痛を主訴に救急外来を受診。 | … severe pain in the right upper limb that began 1 hour before arrival at hospital. | `time_window`: anchor admission becomes arrival (来院) | low |
| sigir-201413#0 | … shortness of breath that had started 2 hours before admission. | 普段は健康な30歳女性。来院2時間前に発症した息切れを主訴に受診。 | … shortness of breath that began 2 hours before arrival at hospital. | `time_window`: anchor admission becomes arrival (来院) | low |
| sigir-20152#1 | He is on immunosuppressive medications, including prednisone. | プレドニゾンを含む免疫抑制薬を内服中。 | Taking oral immunosuppressants including prednisone. | `added_detail`: oral route added | low |
| sigir-20154#5 | An EKG showed sinus regular tachycardia of 119 bpm, with ST-segment elevations up to 3 mm in V1, V2, and V3. | 心電図で心拍数119 bpmの洞性頻脈を認め、V1、V2、V3で最大3 mmのST上昇を認めた。 | ECG showed sinus tachycardia with heart rate 119 bpm, and ST elevation of up to 3 mm in V1, V2 and V3. | `dropped_condition`: "regular" dropped | low |
| sigir-201422#0 | A 15-year-old girl presents to the ER with abdominal pain. | 15歳女性。腹痛を主訴に救急外来を受診。 | 15-year-old female. Came to the emergency outpatient department with abdominal pain. | `register`: girl becomes 女性 | low |
| 53 sentences: the last of every note | The patient will provide informed consent, and will comply with the trial protocol without any practical issues. | 本人よりインフォームド・コンセントが得られる見込みであり、治験実施計画書を実務上の問題なく遵守可能である。 | It is expected that informed consent will be obtained from the patient, and the patient is able to comply with the trial protocol without practical problems. | `certainty`: "will provide" becomes "expected to be obtained" (見込み); a consent criterion may read it as not yet given | low |

### zh-TW (7 findings, 7 sentences)

| Id | Source | Translation | Back-translation | What differs | Sev. |
| --- | --- | --- | --- | --- | --- |
| sigir-20159#2 | Three weeks ago the family returned home after a stay with relatives on a farm that raises domestic pigs for consumption. | 三週前全家人到飼養食用家豬的親戚農場住了一段時間後返家。 | Three weeks ago the whole family went to stay for a while on a relatives' farm raising domestic pigs for food, and then came home. | `time_window`: "three weeks ago" moves from the return to the departure, so the exposure window shifts | medium |
| sigir-201416#1 | Her physical exam was unremarkable except for slight tremors and almost imperceptible spasticity. | 她的理學檢查除了輕微顫抖及幾乎難以察覺的痙攣外，其餘並無異常。 | … apart from slight trembling and almost imperceptible convulsion/spasm … | `wrong_term`: spasticity becomes 痙攣 (spasm, convulsion); spasticity is 痙直 / 痙縮 | medium |
| sigir-20152#3 | BAL fluid examination reveals owl's eye inclusion bodies in the nuclei of infection cells. | BAL液體檢查發現受感染細胞的細胞核內有鷹眼狀包涵體。 | … hawk's-eye-shaped inclusion bodies … | `wrong_term`: 鷹眼 is hawk's eye (owl is 貓頭鷹); the short form may be in local use, a reader decides | low |
| sigir-201522#0 | A 65-year-old male with a history of tuberculosis has started to complain of productive cough with tinges of blood. | 一名65歲男性，有肺結核病史，開始主訴有帶血絲的濕咳。 | … with a history of pulmonary tuberculosis … | `added_detail`: site "pulmonary" added | low |
| sigir-201513#3 | The parents deny the possibility of foreign body ingestion or trauma, and they report that they are delaying some of his vaccines. | 父母否認有誤食異物或外傷的可能，並表示他有部分疫苗延遲接種。 | … and say that some of his vaccines are delayed. | `dropped_condition`: that the parents chose the delay is lost | low |
| sigir-201430#3 | Over the past month, his blood pressure has worsened despite previous control with diltiazem, hydrochlorothiazide, and propranolol. | 過去一個月，他的血壓惡化，先前以diltiazem、hydrochlorothiazide及propranolol控制良好。 | … it was previously well controlled with … | `added_detail`: "well" (良好) added | low |
| sigir-201521#0 | A 32-year-old male presents to your office complaining of diarrhea, abdominal cramping and flatulence. | 一名32歲男性至您的診所就醫，主訴腹瀉、腹部絞痛及脹氣。 | … came to your clinic … | `register`: textbook second person kept | low |

Proposed corrections for every row are in the JSON files (`proposed_correction`); none was applied.

## Ten most serious per language

ja has 12 findings and zh-TW 7, so the tables above, ordered by severity, are the whole lists. The two medium rows of
each language come first.

## What waits for the human reader

1. A clinician fluent in Japanese, and one fluent in Traditional Chinese (Taiwan usage), checks every flagged row
   above (ja 12 findings, zh-TW 7) and gives a verdict: agree, disagree, or a different correction.
2. The same readers check a random sample of the sentences marked `equal` (proposal: 30 per language, drawn with
   `random.Random(1035).sample` over the sorted ids of the `equal` records), because a machine reader's "equal" is not
   evidence that a native medical reader would agree.
3. Only after both: the owner decides whether to apply the corrections (the translations' keep-or-remove question from
   H-37 is still open), and the README's "not clinician-verified" changes for the language that was checked, naming
   the reader and the date. This card did not change the README.

## What was not done

- No clinician and no native medical translator read anything. The `notes_mixed.json` code-mixed set was not in scope.
- No criterion was re-scored with corrected translations, so the effect of the findings on `mlbench` results is not known.
