# AI governance note

*Card T-649b, decision D-343. Closes REG-006 and REG-030. The change control it refers to is
`docs/validation/model-change-protocol.md` (REG-032).*

This note is for a hospital AI committee, a sponsor or an auditor who asks how TrialBox governs its AI. It maps
TrialBox to four texts: the GMLP guiding principles, Taiwan's AI Basic Act, Japan's AI Guidelines for Business and,
as a model for change control, the FDA PCCP guidance. Every control named below is in the code or in CI. D-311
applies: no gate waits for a person's signature, and the controls are automated checks.

TrialBox is not a medical device and makes no diagnosis or treatment decision. It helps a research team find patients
who might fit a trial. A clinician decides. We use GMLP and the PCCP guidance as good practice, not as a claim that
they apply.

## 1. What the AI does and does not do

| Part | AI? | What it decides | What it never decides |
| --- | --- | --- | --- |
| FEAS (counts per trial) | no | nothing: coded filters only, no model | |
| SCREEN, coded criteria | no | coded filters exclude on structured data | |
| SCREEN, note criteria | two models: the judge and the verifier of `models/registry.yaml` | no note answer excludes a patient (D-1072); when **both** say "fail" and each quotes the note, the notes may speak against the criterion and the patient goes to review, as with one "fail" or an "unknown" | that a patient is eligible: the list goes to the study team |
| Drafts (consent explanation, translation, CRF prefill, documents) | the judge model | a draft a person reads, edits and sends | nothing is sent or saved as final without a person |
| Criteria import and messages (criteria to IR, concept mapping, intent of a message) | the judge model | a proposal: the investigator approves the ruleset, and a person handles each message | nothing runs on a patient before the investigator approves the ruleset |

The deployed pair runs on the site's own GPU. No patient text leaves the site. The gateway (`services/gateway/`) is
the only way to a model. It checks each call's data class, records the build of each answer and keeps no note text
in its audit.

**Human oversight.** People stay in charge of every outcome. The study team reviews the candidate list, and the
investigator approves the criteria and the ruleset before SCREEN runs (D-318). These are product functions, not
development gates.

## 2. GMLP (FDA, Health Canada, MHRA 2021; IMDRF N88)

| # | Principle | TrialBox control |
| --- | --- | --- |
| 1 | Expertise across the whole life cycle | Clinical, data and software work are reviewed by automated adversarial review and CI (D-311). The PoC gets feedback from clinicians (`docs/poc/`) |
| 2 | Good software engineering and security | Typed contracts, CI on every pull request, signed updates, the gateway's policy, secret scanning |
| 3 | Data sets represent the intended population | Tests in ja, zh-TW and en: the SIGIR, TREC CT, MedTxt and synthetic sets. Real-data accuracy waits for the dry run and Study A |
| 4 | Training data independent of test data | We train no model. The prompts were not tuned on the gate sets, and Study A removes the patients used for tuning (`docs/plan/study-a-protocol.md`) |
| 5 | Reference standards from the best available methods | N-12 uses the NIST TREC labels as given. The sample check of the labels was done by an AI assistant, not a clinician, so **N-12 is reported unadjusted** and the adjusted figure is a note only (§6) |
| 6 | Model design fits the data and the intended use | A note answer never excludes a patient; two models must agree before it is final (D-1072). "Unknown" never excludes. The context fits the longest prompt (`qualify`'s `longest_prompt` step) |
| 7 | Performance of the human-AI team | The model never excludes; the team reviews disagreements and every note that may speak against a criterion. Study A measures the team |
| 8 | Testing under clinically relevant conditions | the pair canary, N-11, N-12, `public_e2e` on public notes, the 5,000-patient synthetic hospital (`docs/VALIDATION.md`) |
| 9 | Users get clear, essential information | The user guide, the reason and quote shown for every model answer, and the models page with the champion's record |
| 10 | Deployed models are monitored; re-training risks are managed | The canary runs before every night's jobs (`orchestrator.selftest`). We do no re-training. Every change follows the model change protocol |

## 3. Taiwan AI Basic Act (人工智慧基本法, in force 2026-01-14)

The Act sets seven principles and asks the ministries to set a risk framework (MODA's framework is dated 2026-07-07).
TrialBox is used at CGMH under the owner's approved CGRD IRB (D-311). D-311 removed any further committee step.
This note is what we give an AI governance body if it asks.

| Principle | TrialBox control |
| --- | --- |
| 永續發展與福祉 sustainable development and well-being | Runs on one site GPU, with no cloud. The aim is fewer missed trial patients |
| 人類自主 human autonomy | The model never excludes and never enrols anyone. Investigators and the study team decide (§1) |
| 隱私保護與資料治理 privacy and data governance | Patient data stays at the site. Pseudonymous keys. Data classes are enforced by the gateway. The PHI tripwire. No note text in logs (`qualify`'s `log_marker` step) |
| 資安與安全 security and safety | Signed updates, the gateway's policy, injection screening (T-606, T-208), the canary before each run |
| 透明與可解釋 transparency and explainability | Every model answer shows its reason and a quote from the note. The prompt and build of each answer are recorded |
| 公平與不歧視 fairness and non-discrimination | Gates per language (en, ja, zh-TW). Coded filters handle age and sex, and the model does not |
| 問責 accountability | The audit chain, a qualification record per model change and decisions in `docs/decisions/` |

## 4. Japan: AI Guidelines for Business (AI事業者ガイドライン v1.2, 2026-03-31)

TrialBox's developer is an AI developer and AI provider under the guideline. The hospital is the AI user. The ten
common principles (共通の指針):

| Principle | TrialBox control |
| --- | --- |
| 人間中心 human-centric | People decide; the model narrows a list (§1) |
| 安全性 safety | No note answer excludes a patient (D-1072). The canary and the planted-defect check in every qualification |
| 公平性 fairness | Gates per language; Japanese notes in N-11 and MedTxt |
| プライバシー保護 privacy | Data stays at the site; the SS-MIX2 input is pseudonymised at ingest |
| セキュリティ確保 security | The gateway's policy, signed updates and injection screening |
| 透明性 transparency | The reason and quote for every answer; the prompt and build recorded; this note |
| アカウンタビリティ accountability | The audit chain, qualification records and decision files |
| 教育・リテラシー education and literacy | The Japanese user guide, and the PoC with site clinicians |
| 公正競争確保 fair competition | Open models with verified licences (`qualify`'s `licence` step) |
| イノベーション innovation | Open data and tests; the system can run on any site's GPU |

The guideline's v1.2 adds AI agents. No part of TrialBox acts as an agent: the models judge, extract, classify and
draft, and none of them changes a record or sends a message by itself.

## 5. Change control (PCCP as a model)

The model change protocol lists each foreseen change (new prompt version, new weights or quantisation, chat template,
judge or verifier replaced, serving engine, hardware profile, routing). It gives each one its automated test and
threshold, the impact check, rollback and who is told. The evidence for every change is a qualification record from
`trialbox eval qualify`. Each record cites the protocol by path and sha256.

## 6. N-12 is reported unadjusted

N-12 is the share of TREC CT pairs that NIST labels eligible but the pair drops. The deployed pair dropped **9.4 %
(95 % 7.9–11.2 %)** against a gate of 5 %. This figure is the gate result, and **it fails**. The audit-adjusted 3.1 %
(1.8–5.0 %) assumes that about two-thirds of those drops are label noise. A sample of 30 drops supports that, but an
AI assistant read the sample and no clinician did (`eval/trec_ct/AUDIT.md`). The adjusted figure is a note until a
clinician repeats the sample. `docs/VALIDATION.md` §3 shows both. `qualify`'s `n12` step accepts only evidence marked
unadjusted.

## 7. Summaries

**日本語.** TrialBox は治験候補者の絞り込みを支援するもので、診断や治療の判断はしない。ノートを根拠に患者を除外する
ことはない。ノートが基準に反する可能性を示す場合は、引用を付けて確認に回す。最終判断は研究チームが行う。モデルの変更は
すべて変更手順書(model change protocol)の自動テストと閾値で確認し、その記録が手順書を引用する。N-12 は補正前の値
(9.4 %、基準 5 % に不合格)を正式な結果とする。

**繁體中文.** TrialBox 協助研究團隊篩選可能符合試驗的病人，不做診斷或治療決定。系統不會依病歷文字排除病人；
病歷文字可能不利於某條件時，附上引文送交確認；最後由研究團隊決定。每一次模型變更都依模型變更規程的自動測試與門檻驗證，驗證紀錄會引用該
規程。N-12 以未經校正的數值(9.4 %，門檻 5 %，未通過)為正式結果。
