"""Card 10C-5c (D-1256): the English and Japanese device-claims tables get the classes D-1247 gave zh-TW.

D-1247 measured the zh-TW table and added whole classes the first version lacked: treat / cure / efficacy; prevent /
reduce an outcome; decide or recommend for the clinician; a reminder that warns of a condition; a clinician as the
subject only when no product acts in the sentence; true denials and list denials; show-only verbs. This file holds
the same classes for English and Japanese, read through the one rule (``check_claims``) with a table per language.

The rule is a TRIPWIRE, NOT A PROOF: it catches common claim forms in the product's own texts, and every new public
text still needs a human reading. ``DEV_EN`` and ``DEV_JA`` are the card's DEVELOPMENT set (150 sentences per
language: 50 claims, 50 honest lines, 50 near-misses both ways), written from the meaning before any rule changed and
then used to fix the rule, so the figures on them are not an independent measurement. D-1256 records them before and
after; no independent figure exists yet.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest
import yaml
from tb_common.wording import (
    CLAIM_ALLOWED_EN,
    CLAIM_ALLOWED_MORE_JA,
    CLAIM_TABLES,
    NAMED_INSTRUMENTS_EN,
    NAMED_INSTRUMENTS_JA,
    STATEMENT,
    Hit,
    check,
    check_claims,
    check_claims_ja,
    check_page,
    deny_masked,
)

from tests.unit.test_wording import _source

ROOT = Path(__file__).resolve().parents[2]


def en(text: str) -> list[Hit]:
    """:func:`check` on text the caller names en, as an English catalogue's test does."""
    return check(text, lang="en")


def ja(text: str) -> list[Hit]:
    """:func:`check` on text the caller names ja."""
    return check(text, lang="ja")


def words(hits: list[Hit]) -> list[str]:
    return [h.word for h in hits]


# The development set, written from the meaning before the rule changed (card 10C-5c step 1). Kept as written.
# (expect, group, class, text): expect R must be refused, A must pass; group claim / allow / near (near-misses both
# ways). Before the rule changed (master f6c42230): en 9 / 75 claims refused, 71 / 75 honest lines passed; ja 30 / 75
# and 71 / 75. After: en 74 / 75 and 75 / 75; ja 73 / 75 and 75 / 75 (D-1256 gives the figures per class).
DEV_EN = [
    ("R", "claim", "find", "TrialBox detects early-stage lung cancer in patients' records."),
    ("R", "claim", "find", "The system can identify patients with undiagnosed diabetes."),
    ("R", "claim", "find", "Our AI diagnoses heart failure from discharge notes."),
    ("R", "claim", "find", "The software flags patients who may have sepsis."),
    ("R", "claim", "find", "Atrial fibrillation is detected automatically by the model."),
    ("R", "claim", "find", "TrialBox helps clinicians spot dementia earlier."),
    ("R", "claim", "find", "The tool screens the whole hospital population for chronic kidney disease."),
    ("R", "claim", "find", "Rare diseases that doctors missed are uncovered by the AI."),
    ("R", "claim", "find", "The model recognises signs of depression in clinic notes."),
    ("R", "claim", "find", "Using TrialBox, hospitals can find patients with hidden hepatitis C infection."),
    ("R", "claim", "find", "The box is designed to catch cases of pneumonia that would otherwise be overlooked."),
    ("R", "claim", "rate", "TrialBox predicts which patients will be readmitted within 30 days."),
    ("R", "claim", "rate", "The system calculates each patient's risk of stroke."),
    ("R", "claim", "rate", "Every patient receives an AI risk score."),
    ("R", "claim", "rate", "The model estimates the probability that a patient will develop cancer."),
    ("R", "claim", "rate", "Patients are ranked by their likelihood of disease progression."),
    ("R", "claim", "rate", "The software forecasts mortality for intensive care patients."),
    ("R", "claim", "rate", "Our algorithm stratifies patients into high- and low-risk groups."),
    ("R", "claim", "rate", "It gives a prognosis for each oncology patient."),
    ("R", "claim", "warn", "TrialBox sends an early warning when a patient's kidney function is deteriorating."),
    ("R", "claim", "warn", "The system alerts the physician to possible sepsis."),
    ("R", "claim", "warn", "Clinicians are notified when the AI suspects a heart attack."),
    ("R", "claim", "warn", "A reminder warns the doctor that the patient may be developing diabetes."),
    ("R", "claim", "warn", "The dashboard raises an alarm for patients at risk of falls."),
    ("R", "claim", "treat", "TrialBox helps treat patients with asthma more effectively."),
    ("R", "claim", "treat", "Our product cures chronic pain."),
    ("R", "claim", "treat", "The efficacy of TrialBox in improving diabetes control has been shown."),
    ("R", "claim", "treat", "The system manages hypertension by adjusting the care plan."),
    ("R", "claim", "treat", "With TrialBox, patients' depression is treated sooner."),
    ("R", "claim", "prevent", "TrialBox prevents hospital readmissions for heart failure."),
    ("R", "claim", "prevent", "The tool reduces mortality in sepsis patients."),
    ("R", "claim", "prevent", "Using the box lowers the risk of stroke."),
    ("R", "claim", "prevent", "Complications of diabetes can be avoided with TrialBox."),
    ("R", "claim", "prevent", "The AI helps prevent falls among elderly patients."),
    ("R", "claim", "decide", "TrialBox recommends the best treatment for each patient."),
    ("R", "claim", "decide", "The system decides which drug dose the patient should receive."),
    ("R", "claim", "decide", "The model replaces the doctor's clinical judgement."),
    ("R", "claim", "decide", "The software makes the diagnosis so the physician does not have to."),
    ("R", "claim", "decide", "AI suggests a therapy plan for every patient with cancer."),
    ("R", "claim", "decide", "The box tells the clinician which patients should start insulin."),
    ("R", "claim", "state", "The system tells you whether a patient has COVID-19."),
    ("R", "claim", "state", "TrialBox determines if the patient is suffering from a relapse."),
    ("R", "claim", "state", "The AI assesses the severity of each patient's illness."),
    ("R", "claim", "state", "It works out whether a patient is infected."),
    ("R", "claim", "judge", "The AI decides whether a patient is eligible for the study."),
    ("R", "claim", "judge", "Eligibility is determined by the system, not by staff."),
    ("R", "claim", "judge", "The doctor only confirms what the model has already diagnosed."),
    ("R", "claim", "outright", "TrialBox may help detect cancer earlier."),
    ("R", "claim", "outright", "Lists of suspected cases of tuberculosis are produced by the system."),
    ("R", "claim", "outright", "The tool supports earlier diagnosis of Parkinson's disease."),
    ("A", "allow", "does", "TrialBox helps research staff find patients who may match a study's criteria."),
    ("A", "allow", "does", "A qualified person decides on every list before it is used."),
    ("A", "allow", "denial", "TrialBox does not diagnose, treat or prevent disease."),
    ("A", "allow", "denial", "The software does not predict a patient's risk and gives no score."),
    ("A", "allow", "denial", "It does not recommend treatment and gives no clinical alerts."),
    ("A", "allow", "denial", "TrialBox is not a medical device."),
    ("A", "allow", "does", "The investigator decides whether a patient takes part."),
    ("A", "allow", "criterion", "Criterion: patients with a record of type 2 diabetes treated with metformin."),
    ("A", "allow", "criterion", "Inclusion: prior treatment with at least one biologic."),
    ("A", "allow", "criterion", "Exclusion: history of stroke within six months."),
    ("A", "allow", "label", "Treatment arm"),
    ("A", "allow", "label", "Date of first treatment"),
    ("A", "allow", "label", "Condition"),
    ("A", "allow", "notice", "Prevention of data loss: the backup runs every night."),
    ("A", "allow", "notice", "The box detected that the backup file is incomplete."),
    ("A", "allow", "notice", "The import could not identify the file's character encoding."),
    ("A", "allow", "label", "Estimated enrolment for the next six months"),
    ("A", "allow", "does", "The forecast counts candidates per month; it says nothing about any patient."),
    ("A", "allow", "does", "Each candidate is shown with the record passages the match rests on."),
    ("A", "allow", "notice", "Risk of bias was assessed by the review team."),
    ("A", "allow", "notice", "The study's main risks are described in the consent form."),
    ("A", "allow", "notice", "The ECOG score is entered by the research nurse."),
    ("A", "allow", "notice", "eGFR is computed from creatinine by the published formula."),
    ("A", "allow", "show", "The system shows the lab values as recorded; the physician reads them."),
    ("A", "allow", "notice", "Reminder: the visit for this participant is due on Monday."),
    ("A", "allow", "notice", "Visit reminders are printed for staff to hand out."),
    ("A", "allow", "does", "Staff review the list and decide whom to contact."),
    ("A", "allow", "does", "This page lists records that did not match a criterion, for the investigator's review."),
    ("A", "allow", "does", "The tool reduces the time staff spend reading charts."),
    ("A", "allow", "does", "It lowers the number of manual look-ups per study."),
    ("A", "allow", "does", "The model reads the records; a person checks every result."),
    ("A", "allow", "notice", "Notice: the data source has been offline since 03:00."),
    ("A", "allow", "notice", "Alert: the disk is nearly full."),
    ("A", "allow", "criterion", "Treatment history is taken from the pharmacy records."),
    ("A", "allow", "criterion", "A patient with a diagnosis code of E11 meets criterion 2."),
    ("A", "allow", "criterion", "Patients diagnosed with rheumatoid arthritis by a rheumatologist."),
    ("A", "allow", "criterion", "Previously treated with a TNF inhibitor."),
    ("A", "allow", "denial", "The physician makes the diagnosis; TrialBox only lists records."),
    ("A", "allow", "denial", "TrialBox neither diagnoses disease nor predicts outcomes."),
    ("A", "allow", "denial", "No patient is scored, ranked or flagged by the software."),
    ("A", "allow", "denial", "The box makes no prediction about any patient."),
    ("A", "allow", "denial", "Whether a patient is eligible is decided by the investigator, never by the software."),
    ("A", "allow", "denial", "The clinician chooses the treatment; the box plays no part in it."),
    ("A", "allow", "label", "Data steward: confirms the mapping of local codes."),
    ("A", "allow", "label", "Screening log"),
    ("A", "allow", "label", "Screening visit date"),
    ("A", "allow", "does", "Prescreening: candidates who may match the written criteria."),
    ("A", "allow", "label", "Detection limit of the assay"),
    ("A", "allow", "does", "The program flags records with missing consent."),
    ("A", "allow", "does", "The rate of patients found among those eligible (recall) was measured on synthetic data."),
    ("R", "near", "find", "TrialBox does not only list candidates; it also detects heart disease."),
    ("R", "near", "find", "Not a single case of cancer is missed by our AI."),
    ("R", "near", "find", "The system never fails to spot early sepsis."),
    ("R", "near", "find", "Although it is not a medical device, TrialBox diagnoses diabetes."),
    ("R", "near", "judge", "The physician signs off, but the AI makes the diagnosis."),
    ("R", "near", "judge", "Doctors no longer need to diagnose: the software does it for them."),
    ("R", "near", "decide", "Let the AI decide which patients need treatment."),
    ("R", "near", "rate", "Patients at high risk of heart attack are listed for the physician."),
    ("R", "near", "rate", "The box does not just find candidates, it predicts who will get sick."),
    ("R", "near", "judge", "Staff can rely on the system's judgement of whether a patient has cancer."),
    ("R", "near", "find", "Without TrialBox, many cases of dementia would go undetected."),
    ("R", "near", "warn", "Clinicians are reminded when a patient shows signs of kidney failure."),
    ("R", "near", "find", "It is not unusual for the AI to catch tumours that radiologists overlooked."),
    ("R", "near", "rate", "The software may possibly be able to predict relapse in some patients."),
    (
        "R",
        "near",
        "find",
        "TrialBox, which is not a diagnostic tool, nevertheless identifies patients with likely COPD.",
    ),
    ("R", "near", "judge", "There is no need for a doctor: the model determines the diagnosis."),
    ("R", "near", "decide", "The model's recommendations on dosage are shown to the physician."),
    ("R", "near", "find", "Patients flagged by the AI as probable Alzheimer's cases are listed first."),
    ("R", "near", "decide", "Physicians choose the therapy that TrialBox recommends."),
    ("R", "near", "prevent", "The system can help reduce deaths from sepsis."),
    ("R", "near", "find", "Use TrialBox to catch the disease before symptoms start."),
    ("R", "near", "judge", "No physician review is needed before the tool's diagnosis is used."),
    ("R", "near", "judge", "The research nurse checks the patients the system has diagnosed."),
    ("R", "near", "treat", "Better treatment outcomes thanks to TrialBox."),
    ("R", "near", "warn", "The box warns staff about patients likely to deteriorate."),
    ("A", "near", "denial", "The software does not detect, diagnose or treat any disease."),
    ("A", "near", "denial", "TrialBox does not tell the physician whether a patient has a disease."),
    ("A", "near", "denial", "No clinical alerts are given; staff decide whom to contact."),
    ("A", "near", "criterion", "Patients diagnosed with heart failure by their cardiologist may match criterion 3."),
    ("A", "near", "criterion", "The study tests whether the drug reduces mortality in sepsis."),
    ("A", "near", "criterion", "Trial objective: to prevent relapse in multiple sclerosis."),
    ("A", "near", "show", "The investigator decides on treatment; TrialBox shows the records only."),
    ("A", "near", "criterion", "Received treatment for hepatitis C before 2020."),
    ("A", "near", "denial", "The model predicts nothing; it reads the text of each record."),
    ("A", "near", "notice", "Risk of data loss is low because backups run nightly."),
    ("A", "near", "notice", "The box detects duplicate patient records during import."),
    ("A", "near", "does", "TrialBox reduces the paperwork of a feasibility check."),
    ("A", "near", "does", "It prevents the same candidate from being contacted twice."),
    ("A", "near", "notice", "The coordinator is reminded to confirm the consent form."),
    ("A", "near", "notice", "Warning: three criteria could not be read for this record."),
    ("A", "near", "does", "The estimated number of candidates is a count, not a prediction about any patient."),
    ("A", "near", "show", "Disease names are shown as they are written in the record."),
    ("A", "near", "criterion", "The physician's diagnosis is quoted from the chart, with its date."),
    ("A", "near", "denial", "TrialBox is not intended to replace the clinician's judgement."),
    ("A", "near", "label", "Score definitions for DAS28 are taken from the protocol."),
    ("A", "near", "does", "The software identifies which criteria a record does not meet."),
    ("A", "near", "does", "Candidates who may meet the criteria are found earlier in the month."),
    ("A", "near", "does", "Find candidates for the asthma study by its written criteria."),
    ("A", "near", "criterion", "The drug under study is intended to treat moderate asthma."),
    ("A", "near", "denial", "No patient's risk is calculated or shown."),
]
DEV_JA = [
    ("R", "claim", "find", "本システムは電子カルテから肺がんを早期に発見します。"),
    ("R", "claim", "find", "AIが未受診の糖尿病患者を見つけ出します。"),
    ("R", "claim", "find", "TrialBoxは心不全を診断します。"),
    ("R", "claim", "find", "敗血症の可能性がある患者をAIがフラグ付けします。"),
    ("R", "claim", "find", "心房細動はモデルによって自動的に検出されます。"),
    ("R", "claim", "find", "認知症の早期発見を支援します。"),
    ("R", "claim", "find", "院内の全患者を対象に慢性腎臓病のスクリーニングを行います。"),
    ("R", "claim", "find", "医師が見落とした希少疾患をAIが見つけます。"),
    ("R", "claim", "find", "本システムは外来記録からうつ病の兆候を読み取ります。"),
    ("R", "claim", "find", "隠れたC型肝炎の患者を掘り起こします。"),
    ("R", "claim", "find", "見逃されがちな肺炎を本機が拾い上げます。"),
    ("R", "claim", "rate", "本製品は30日以内の再入院を予測します。"),
    ("R", "claim", "rate", "患者ごとの脳卒中リスクを算出します。"),
    ("R", "claim", "rate", "すべての患者にAIリスクスコアを付与します。"),
    ("R", "claim", "rate", "がんを発症する確率をモデルが推定します。"),
    ("R", "claim", "rate", "病状が進行する可能性の高い順に患者を並べます。"),
    ("R", "claim", "rate", "集中治療室の患者の死亡率を予測します。"),
    ("R", "claim", "rate", "患者を高リスク群と低リスク群に層別化します。"),
    ("R", "claim", "rate", "がん患者ごとの予後を示します。"),
    ("R", "claim", "warn", "腎機能が悪化している患者について早期警告を出します。"),
    ("R", "claim", "warn", "敗血症の疑いがあるとき本システムが医師にアラートを出します。"),
    ("R", "claim", "warn", "AIが心筋梗塞を疑うと担当医に通知されます。"),
    ("R", "claim", "warn", "糖尿病を発症しつつある患者について本機が医師にリマインドします。"),
    ("R", "claim", "warn", "転倒リスクの高い患者に警報を出します。"),
    ("R", "claim", "treat", "本システムは喘息の治療を支援します。"),
    ("R", "claim", "treat", "本製品は慢性疼痛を治します。"),
    ("R", "claim", "treat", "TrialBoxの糖尿病改善効果が確認されています。"),
    ("R", "claim", "treat", "本ツールは高血圧を管理し、治療計画を調整します。"),
    ("R", "claim", "treat", "TrialBoxにより、うつ病の治療が早まります。"),
    ("R", "claim", "prevent", "本システムは心不全による再入院を予防します。"),
    ("R", "claim", "prevent", "本ツールは敗血症患者の死亡率を低減します。"),
    ("R", "claim", "prevent", "TrialBoxを使うと脳卒中のリスクが下がります。"),
    ("R", "claim", "prevent", "本製品で糖尿病の合併症を防ぐことができます。"),
    ("R", "claim", "prevent", "AIが高齢者の転倒を防止します。"),
    ("R", "claim", "decide", "TrialBoxは患者ごとに最適な治療法を推奨します。"),
    ("R", "claim", "decide", "システムが投与量を決定します。"),
    ("R", "claim", "decide", "本製品は医師に代わって臨床判断を行います。"),
    ("R", "claim", "decide", "医師の代わりにAIが診断を下します。"),
    ("R", "claim", "decide", "AIががん患者の治療方針を提案します。"),
    ("R", "claim", "decide", "どの患者にインスリンを開始すべきかをシステムが医師に提示します。"),
    ("R", "claim", "state", "本システムは患者が新型コロナに感染しているかどうかを教えてくれます。"),
    ("R", "claim", "state", "TrialBoxは患者が再発しているかを判定します。"),
    ("R", "claim", "state", "AIが各患者の病気の重症度を評価します。"),
    ("R", "claim", "state", "患者が感染症にかかっているかをシステムが判別します。"),
    ("R", "claim", "judge", "AIが患者の試験参加の可否を決めます。"),
    ("R", "claim", "judge", "適格性はスタッフではなくシステムによって判断されます。"),
    ("R", "claim", "judge", "医師はモデルがすでに下した診断を確認するだけです。"),
    ("R", "claim", "outright", "TrialBoxはがんの早期発見に役立つ可能性があります。"),
    ("R", "claim", "outright", "結核の疑い例の一覧をシステムが作成します。"),
    ("R", "claim", "outright", "パーキンソン病の早期診断を支援します。"),
    ("A", "allow", "does", "TrialBoxは、研究の参加条件に合う可能性のある患者を担当者が探すのを支援します。"),
    ("A", "allow", "does", "すべての出力は、資格のある担当者が判断してから用いられます。"),
    ("A", "allow", "denial", "本製品は疾病の診断・治療・予防を行いません。"),
    ("A", "allow", "denial", "患者のリスクを予測せず、スコアも付けません。"),
    ("A", "allow", "denial", "治療を推奨せず、臨床上の警告を出しません。"),
    ("A", "allow", "denial", "本ソフトウェアは医療機器ではありません。"),
    ("A", "allow", "does", "参加するかどうかは研究責任医師が決めます。"),
    ("A", "allow", "criterion", "基準：メトホルミンで治療中の2型糖尿病の記録がある患者。"),
    ("A", "allow", "criterion", "選択基準：生物学的製剤による治療歴が1剤以上。"),
    ("A", "allow", "criterion", "除外基準：6か月以内の脳卒中の既往。"),
    ("A", "allow", "label", "治療群"),
    ("A", "allow", "label", "初回治療日"),
    ("A", "allow", "label", "病名"),
    ("A", "allow", "notice", "データ消失の防止のため、毎晩バックアップを取ります。"),
    ("A", "allow", "notice", "バックアップファイルが不完全であることを検出しました。"),
    ("A", "allow", "notice", "ファイルの文字コードを特定できませんでした。"),
    ("A", "allow", "label", "今後6か月の登録予測"),
    ("A", "allow", "does", "見込み数は月ごとの候補者数であり、患者個人については何も述べません。"),
    ("A", "allow", "does", "各候補者には、一致の根拠となる記録の該当箇所が表示されます。"),
    ("A", "allow", "notice", "バイアスのリスクはレビューチームが評価しました。"),
    ("A", "allow", "notice", "研究の主なリスクは同意説明文書に記載されています。"),
    ("A", "allow", "notice", "ECOGスコアは研究看護師が入力します。"),
    ("A", "allow", "notice", "eGFRは公表された式でクレアチニンから計算します。"),
    ("A", "allow", "show", "システムは検査値を記録どおりに表示し、医師が読みます。"),
    ("A", "allow", "notice", "お知らせ：この参加者の来院予定日は月曜日です。"),
    ("A", "allow", "notice", "来院案内は担当者が印刷して手渡します。"),
    ("A", "allow", "does", "担当者が一覧を確認し、連絡する相手を決めます。"),
    ("A", "allow", "does", "このページには、条件に合致しなかった記録を研究責任者の確認のために一覧にしています。"),
    ("A", "allow", "does", "カルテを読む時間を減らします。"),
    ("A", "allow", "does", "試験ごとの手作業による照会の回数を減らします。"),
    ("A", "allow", "does", "モデルが記録を読み、人がすべての結果を確認します。"),
    ("A", "allow", "notice", "お知らせ：データソースは3時から停止しています。"),
    ("A", "allow", "notice", "警告：ディスクの空き容量が少なくなっています。"),
    ("A", "allow", "criterion", "治療歴は薬剤部の記録から取得します。"),
    ("A", "allow", "criterion", "傷病名コードE11の患者は基準2に合致します。"),
    ("A", "allow", "criterion", "リウマチ専門医によって関節リウマチと診断された患者。"),
    ("A", "allow", "criterion", "TNF阻害薬による治療歴がある。"),
    ("A", "allow", "denial", "診断は医師が行い、TrialBoxは記録を一覧にするだけです。"),
    ("A", "allow", "denial", "TrialBoxは疾患を診断せず、転帰も予測しません。"),
    ("A", "allow", "denial", "ソフトウェアが患者を点数化したり、順位付けしたりすることはありません。"),
    ("A", "allow", "denial", "本機はどの患者についても予測を行いません。"),
    ("A", "allow", "denial", "患者が適格かどうかは研究責任医師が決め、ソフトウェアが決めることはありません。"),
    ("A", "allow", "denial", "治療は医師が選び、本機は一切関与しません。"),
    ("A", "allow", "label", "データスチュワード：院内コードの対応付けを確認します。"),
    ("A", "allow", "label", "スクリーニング名簿"),
    ("A", "allow", "label", "スクリーニング来院日"),
    ("A", "allow", "does", "事前スクリーニング：記載された基準に合う可能性のある候補者。"),
    ("A", "allow", "label", "測定の検出限界"),
    ("A", "allow", "does", "同意書が未取得の記録に印を付けます。"),
    ("A", "allow", "does", "適格患者のうち見つかった割合（再現率）は合成データで測定しました。"),
    ("R", "near", "find", "TrialBoxは候補者を一覧にするだけでなく、心疾患も検出します。"),
    ("R", "near", "find", "AIはがんを一例も見逃しません。"),
    ("R", "near", "find", "本システムは早期の敗血症を見落とすことはありません。"),
    ("R", "near", "find", "医療機器ではありませんが、TrialBoxは糖尿病を診断します。"),
    ("R", "near", "judge", "医師が承認しますが、診断を下すのはAIです。"),
    ("R", "near", "judge", "医師が診断する必要はなく、ソフトウェアが代わりに行います。"),
    ("R", "near", "decide", "どの患者に治療が必要かはAIに決めさせましょう。"),
    ("R", "near", "rate", "心筋梗塞のリスクが高い患者を医師向けに一覧にします。"),
    ("R", "near", "rate", "本機は候補者を探すだけでなく、誰が病気になるかを予測します。"),
    ("R", "near", "judge", "がんかどうかはシステムの判断に任せられます。"),
    ("R", "near", "find", "TrialBoxがなければ、多くの認知症が見過ごされていたでしょう。"),
    ("R", "near", "warn", "腎不全の兆候がある患者について本システムが医師に知らせます。"),
    ("R", "near", "find", "放射線科医が見落とした腫瘍をAIが見つけることも珍しくありません。"),
    ("R", "near", "rate", "一部の患者では再発を予測できるかもしれません。"),
    ("R", "near", "find", "診断ツールではないものの、TrialBoxはCOPDの可能性が高い患者を特定します。"),
    ("R", "near", "judge", "医師は不要で、モデルが診断を確定します。"),
    ("R", "near", "decide", "投与量に関するモデルの推奨が医師に表示されます。"),
    ("R", "near", "find", "AIがアルツハイマー病の可能性が高いと判定した患者を先頭に表示します。"),
    ("R", "near", "decide", "医師はTrialBoxが推奨する治療法を選びます。"),
    ("R", "near", "prevent", "本システムは敗血症による死亡を減らすのに役立ちます。"),
    ("R", "near", "find", "TrialBoxなら症状が出る前に病気を捉えられます。"),
    ("R", "near", "judge", "ツールの診断結果は医師の確認なしに使えます。"),
    ("R", "near", "judge", "研究看護師は、システムが診断した患者を確認します。"),
    ("R", "near", "treat", "TrialBoxのおかげで治療成績が向上します。"),
    ("R", "near", "warn", "本システムは悪化しそうな患者についてスタッフに警告します。"),
    ("A", "near", "denial", "本ソフトウェアは疾患の検出・診断・治療を一切行いません。"),
    ("A", "near", "denial", "本システムは患者が病気かどうかを医師に伝えることはありません。"),
    ("A", "near", "denial", "臨床上の警告は出さず、連絡する相手は担当者が決めます。"),
    ("A", "near", "criterion", "循環器医により心不全と診断された患者は基準3に合う可能性があります。"),
    ("A", "near", "criterion", "本研究は、その薬が敗血症の死亡率を下げるかを検証します。"),
    ("A", "near", "criterion", "試験の目的：多発性硬化症の再発予防。"),
    ("A", "near", "show", "治療は研究責任医師が決め、TrialBoxは記録を表示するだけです。"),
    ("A", "near", "criterion", "2020年より前にC型肝炎の治療を受けた。"),
    ("A", "near", "denial", "モデルは何も予測せず、各記録の本文を読むだけです。"),
    ("A", "near", "notice", "毎晩バックアップを取るため、データ消失のリスクは低いです。"),
    ("A", "near", "notice", "取り込み時に重複した患者記録を検出します。"),
    ("A", "near", "does", "TrialBoxは実施可能性調査の書類作業を減らします。"),
    ("A", "near", "does", "同じ候補者に二度連絡することを防ぎます。"),
    ("A", "near", "notice", "同意書の確認をコーディネーターにリマインドします。"),
    ("A", "near", "notice", "警告：この記録では3つの基準を読み取れませんでした。"),
    ("A", "near", "does", "候補者の見込み数は件数であり、どの患者についての予測でもありません。"),
    ("A", "near", "show", "病名は記録に書かれたとおりに表示されます。"),
    ("A", "near", "criterion", "医師の診断はカルテから日付とともに引用します。"),
    ("A", "near", "denial", "TrialBoxは医師の判断に代わるものではありません。"),
    ("A", "near", "label", "DAS28のスコア定義は計画書から取っています。"),
    ("A", "near", "does", "記録が満たしていない基準を特定します。"),
    ("A", "near", "does", "条件に合う可能性のある候補者を月の早い時期に見つけます。"),
    ("A", "near", "does", "喘息研究の候補者を記載された基準で探します。"),
    ("A", "near", "criterion", "治験薬は中等症の喘息を治療することを目的としています。"),
    ("A", "near", "denial", "患者のリスクを計算したり表示したりすることはありません。"),
]
# Development claims the rule does not see, recorded (D-1256, known limits): a doctor's act denied with the product
# doing it in another clause; the model "reading" a sign of a disease (読み取り is the product's own word for a model
# reading a record, as 判讀 is in zh-TW).
KNOWN_MISSES = {
    "Doctors no longer need to diagnose: the software does it for them.",
    "本システムは外来記録からうつ病の兆候を読み取ります。",
    "医師が診断する必要はなく、ソフトウェアが代わりに行います。",
}


def _cases(rows: list[tuple[str, str, str, str]], expect: str) -> list[str]:
    return [t for e, _, _, t in rows if e == expect and t not in KNOWN_MISSES]


@pytest.mark.parametrize("text", _cases(DEV_EN, "R"))
def test_every_english_development_claim_fails(text: str) -> None:
    assert en(text) != []
    assert check_page(f'<html lang="en"><body><p>{text}</p></body></html>') != []  # the page walk names it en


@pytest.mark.parametrize("text", _cases(DEV_EN, "A"))
def test_every_english_development_honest_line_passes(text: str) -> None:
    assert en(text) == []
    assert check_page(f'<html lang="en"><body><p>{text}</p></body></html>') == []


@pytest.mark.parametrize("text", _cases(DEV_JA, "R"))
def test_every_japanese_development_claim_fails(text: str) -> None:
    assert ja(text) != []
    assert check_claims_ja(text) != [] or check(text) != []  # check_claims_ja names it ja too


@pytest.mark.parametrize("text", _cases(DEV_JA, "A"))
def test_every_japanese_development_honest_line_passes(text: str) -> None:
    assert ja(text) == []
    assert check_page(f'<html lang="ja"><body><p>{text}</p></body></html>') == []


def test_the_development_sets_are_what_d1256_counts() -> None:
    for rows in (DEV_EN, DEV_JA):
        assert len(rows) == 150 and len({t for *_, t in rows}) == 150
        assert sum(1 for e, g, _, _ in rows if g == "claim" and e == "R") == 50
        assert sum(1 for e, g, _, _ in rows if g == "allow" and e == "A") == 50
        assert sum(1 for _, g, _, _ in rows if g == "near") == 50
    for text in KNOWN_MISSES:  # recorded: still not seen
        assert check(text, lang="en" if text.isascii() else "ja") == [], text


# ---------------------------------------------------------------------------------------------------- by class
# For each class: the claim, and the closest honest line that must pass. The new classes need their object and,
# for act / state / decide / judge, the product as the subject.
CLASS_EN = [
    # finding a disease
    ("find", "The software flags patients who may have sepsis.", "The program flags records with missing consent."),
    (
        "find",
        "Atrial fibrillation is detected automatically by the model.",
        "The box detected that the backup file is incomplete.",
    ),
    ("find", "Find patients with asthma.", "Find candidates for the asthma study by its written criteria."),
    ("find", "The AI found earlier cases.", "Candidates who may meet the criteria are found earlier in the month."),
    ("find", "Patients the AI diagnosed with gout are listed.", "Patients diagnosed with gout by a rheumatologist."),
    # rating a patient or a disease; possible only about a disease
    ("rate", "TrialBox predicts which patients will be readmitted.", "The forecast counts candidates per month."),
    ("rate", "The AI score is shown next to each name.", "The ECOG score is entered by the research nurse."),
    ("possible", "Lists patients with possible sepsis.", "Lists possible candidates for the study."),
    # warning, reminding
    ("warn", "The dashboard raises an alarm for patients at risk of falls.", "Alert: the disk is nearly full."),
    (
        "remind",
        "Clinicians are reminded when a patient shows signs of kidney failure.",
        "The coordinator is reminded to confirm the consent form.",
    ),
    # acting on a disease
    (
        "act",
        "TrialBox prevents hospital readmissions for heart failure.",
        "It prevents the same candidate from being contacted twice.",
    ),
    (
        "act",
        "With TrialBox, patients' depression is treated sooner.",
        "Received treatment for hepatitis C before 2020.",
    ),
    (
        "act",
        "Complications of diabetes can be avoided with TrialBox.",
        "The study tests whether the drug reduces mortality in sepsis.",
    ),
    (
        "act",
        "The efficacy of TrialBox in improving diabetes control has been shown.",
        "Trial objective: to prevent relapse in multiple sclerosis.",
    ),
    (
        "act",
        "TrialBox lists patients and treats their diabetes.",
        "TrialBox lists patients treated with metformin for diabetes.",
    ),
    ("act", "Better treatment outcomes thanks to TrialBox.", "Treatment arm"),
    ("act", "The system manages hypertension.", "The data steward manages the code mapping."),
    # telling a patient's state
    (
        "state",
        "The system tells you whether a patient has COVID-19.",
        "The system tells you whether the import has finished.",
    ),
    (
        "state",
        "Eligibility is determined by the system, not by staff.",
        "Whether a patient is eligible is decided by the investigator, never by the software.",
    ),
    # deciding for the clinician
    (
        "decide",
        "TrialBox recommends the best treatment for each patient.",
        "The investigator decides on treatment; TrialBox shows the records only.",
    ),
    (
        "decide",
        "Physicians choose the therapy that TrialBox recommends.",
        "The clinician chooses the treatment; the box plays no part in it.",
    ),
    ("decide", "Let the AI decide which patients need treatment.", "Staff review the list and decide whom to contact."),
    (
        "decide",
        "The model's recommendations on dosage are shown to the physician.",
        "The physician's recommendations on dosage are quoted from the chart.",
    ),
    # judging with the product as the subject; a person yields to a product that does the judgement
    (
        "judge",
        "The doctor only confirms what the model has already diagnosed.",
        "The physician makes the diagnosis; TrialBox only lists records.",
    ),
    (
        "judge",
        "The model replaces the doctor's clinical judgement.",
        "TrialBox is not intended to replace the clinician's judgement.",
    ),
    (
        "judge",
        "Staff can rely on the system's judgement of whether a patient has cancer.",
        "Staff rely on the investigator's judgement of whether a patient takes part.",
    ),
]
CLASS_JA = [
    ("find", "敗血症の可能性がある患者をAIがフラグ付けします。", "同意書が未取得の記録に印を付けます。"),
    ("find", "本システムは早期の敗血症を見落とすことはありません。", "本システムは記録を見落とすことがあります。"),
    ("find", "AIが未受診の糖尿病患者を見つけ出します。", "条件に合う可能性のある候補者を月の早い時期に見つけます。"),
    ("rate", "病状が進行する可能性の高い順に患者を並べます。", "参加条件に合う可能性のある患者を一覧にします。"),
    ("rate", "一部の患者では再発を予測できるかもしれません。", "患者の再発を予測することはありません。"),
    ("warn", "転倒リスクの高い患者に警報を出します。", "警告：ディスクの空き容量が少なくなっています。"),
    (
        "remind",
        "糖尿病を発症しつつある患者について本機が医師にリマインドします。",
        "同意書の確認をコーディネーターにリマインドします。",
    ),
    ("remind", "AIが心筋梗塞を疑うと担当医に通知されます。", "来院予定の患者を担当者に通知します。"),
    ("act", "本システムは喘息の治療を支援します。", "TNF阻害薬による治療歴がある。"),
    ("act", "TrialBoxの糖尿病改善効果が確認されています。", "TrialBoxの画面改善が確認されています。"),
    ("act", "TrialBoxを使うと脳卒中のリスクが下がります。", "本研究は、その薬が敗血症の死亡率を下げるかを検証します。"),
    ("act", "本システムは心不全による再入院を予防します。", "データ消失の防止のため、毎晩バックアップを取ります。"),
    ("act", "TrialBoxにより、うつ病の治療が早まります。", "2020年より前にC型肝炎の治療を受けた。"),
    ("state", "AIが各患者の病気の重症度を評価します。", "バイアスのリスクはレビューチームが評価しました。"),
    (
        "state",
        "患者が感染症にかかっているかをシステムが判別します。",
        "患者が感染症にかかっているかは医師が判断します。",
    ),
    (
        "decide",
        "どの患者にインスリンを開始すべきかをシステムが医師に提示します。",
        "どの患者にインスリンを開始するかは医師が決めます。",
    ),
    ("decide", "AIが患者の試験参加の可否を決めます。", "参加するかどうかは研究責任医師が決めます。"),
    ("decide", "どの患者に治療が必要かはAIに決めさせましょう。", "治療は医師が選び、本機は一切関与しません。"),
    ("decide", "医師はTrialBoxが推奨する治療法を選びます。", "医師は計画書が定める治療法を選びます。"),
    ("judge", "がんかどうかはシステムの判断に任せられます。", "がんかどうかは医師の判断に任せられます。"),
    (
        "judge",
        "適格性はスタッフではなくシステムによって判断されます。",
        "適格性はシステムではなく研究責任医師によって判断されます。",
    ),
    ("judge", "医師が承認しますが、診断を下すのはAIです。", "診断は医師が行い、TrialBoxは記録を一覧にするだけです。"),
]


@pytest.mark.parametrize(("cls", "claim", "honest"), CLASS_EN)
def test_an_english_class_refuses_its_claim_and_passes_its_closest_honest_line(
    cls: str, claim: str, honest: str
) -> None:
    assert en(claim) != [], (cls, claim)
    assert en(honest) == [], (cls, honest)


@pytest.mark.parametrize(("cls", "claim", "honest"), CLASS_JA)
def test_a_japanese_class_refuses_its_claim_and_passes_its_closest_honest_line(
    cls: str, claim: str, honest: str
) -> None:
    assert ja(claim) != [], (cls, claim)
    assert ja(honest) == [], (cls, honest)


# Each part of the rule that no development sentence needed on its own, pinned by the sentence it decides (the
# mutation run of card 10C-5c: removing the part fails this test).
PARTS_EN = [
    # (part, text, refused?)
    ("a record's treatment, before the word", "TrialBox lists patients who received treatment for asthma.", False),
    ("the product straight before an act", "TrialBox's efficacy has been shown.", True),
    ("a sentence ends at a full stop", "The box finds candidates. Sepsis is one of the criteria.", False),
    ("nor denies alone", "The software does not store names, nor does it predict a patient's risk.", False),
    ("a denial after the verb", "The model predicts nothing about any patient.", False),
    (
        "a denied clause's disease",
        "TrialBox does not screen for cancer; it lists candidates found by the staff.",
        False,
    ),
    (
        "a product that only shows does nothing",
        "TrialBox only shows the record and the physician makes the diagnosis.",
        False,
    ),
    ("a product replacing a person", "The doctor's judgement is no longer needed; the model replaces it.", True),
]
PARTS_JA = [
    ("a record's treatment, before the word", "本システムは初回治療の喘息患者を一覧にします。", False),
    ("a record's treatment, after the word", "本システムは喘息の治療歴を表示します。", False),
    ("an early finding of candidates", "本システムは条件に合う候補者を早期に見つけます。", False),
    ("a passive with no product as agent", "関節リウマチと診断された患者。", False),
    ("a person named by a 医 compound", "診断は主治医が行います。", False),
    ("a product replacing a person", "医師の判断は不要で、AIが代わりに行います。", True),
    ("an outright claim noun", "誤診を減らします。", True),
    ("an outright claim noun", "疑い例を一覧にします。", True),
    ("an outright claim noun", "臨床判断支援のためのツールです。", True),
]


@pytest.mark.parametrize(("part", "text", "refused"), PARTS_EN)
def test_each_english_rule_part_decides_its_sentence(part: str, text: str, refused: bool) -> None:
    assert (en(text) != []) is refused, part


@pytest.mark.parametrize(("part", "text", "refused"), PARTS_JA)
def test_each_japanese_rule_part_decides_its_sentence(part: str, text: str, refused: bool) -> None:
    assert (ja(text) != []) is refused, part


def test_text_not_named_ja_keeps_d1228s_denial() -> None:
    """D-1228 read a comma before a claim word as continuing a list, so AIが患者のリスクを示し、予測は行いません denied
    リスク too. Text named ja is read with D-1256's rule (a comma after a verb ends the clause); text with no
    language keeps D-1228's reading, as before."""
    text = "AIが患者のリスクを示し、予測は行いません。"
    assert check(text) == []
    assert words(ja(text)) == ["リスク"]


# ---------------------------------------------------------------------------------------------------- denials
@pytest.mark.parametrize(
    "text",
    [
        "TrialBox does not diagnose, treat or prevent disease.",  # a list denial
        "TrialBox neither diagnoses disease nor predicts outcomes.",  # neither ... nor
        "The software does not predict a patient's risk and gives no score.",  # two denials, one per verb
        "The model predicts nothing; it reads the text of each record.",  # a denial after the verb
        "No patient is scored, ranked or flagged by the software.",
        "TrialBox does not tell the physician whether a patient has a disease.",  # the denied clause's disease
        "It does not recommend treatment and gives no clinical alerts.",
    ],
)
def test_an_english_denial_in_its_common_forms_passes(text: str) -> None:
    assert en(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "The system never fails to spot early sepsis.",  # two negatives deny nothing
        "Not a single case of cancer is missed by our AI.",  # a negated miss claims completeness
        "TrialBox does not only list candidates; it also detects heart disease.",  # "not only" denies nothing
        "It is not unusual for the AI to catch tumours that radiologists overlooked.",
        "Although it is not a medical device, TrialBox diagnoses diabetes.",  # the denial is in another clause
        "TrialBox does not store names and detects heart disease.",  # "and" before another verb ends the denial
    ],
)
def test_english_false_negatives_are_not_a_denial(text: str) -> None:
    assert en(text) != []


@pytest.mark.parametrize(
    "text",
    [
        "本製品は疾病の診断・治療・予防を行いません。",
        "治療を推奨せず、臨床上の警告を出しません。",
        "本システムは患者が病気かどうかを医師に伝えることはありません。",
        "患者が適格かどうかは研究責任医師が決め、ソフトウェアが決めることはありません。",
    ],
)
def test_a_japanese_denial_of_a_new_class_passes(text: str) -> None:
    assert ja(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "本システムは早期の敗血症を見落とすことはありません。",  # a negated miss claims completeness
        "一部の患者では再発を予測できるかもしれません。",  # a hedge is no denial
        "AIが患者のリスクを示し、治療は推奨しません。",  # a comma after a verb ends the clause (D-1228's test)
        "本システムは記録を表示せず、糖尿病を治療します。",  # a denial in an earlier clause
    ],
)
def test_japanese_false_negatives_are_not_a_denial(text: str) -> None:
    assert ja(text) != []


# ------------------------------------------------------------------------------ FORBIDDEN's verdict words, named
def test_a_diagnosis_is_the_products_only_with_the_product_as_subject() -> None:
    """FORBIDDEN's "diagnosis" / 診断 in text named en / ja: a record field, a passive with no product as its agent and
    a person's own act pass; the product as the subject is refused. Text with no language reads them as before
    (refused), as D-1247 does for zh-TW."""
    for text in (
        "A patient with a diagnosis code of E11.",
        "Date of diagnosis.",
        "The physician's diagnosis is quoted.",
    ):
        assert en(text) == [], text
        assert check(text) != [], text
    for text in (
        "The tool's diagnosis is used.",
        "TrialBox makes the diagnosis.",
        "Diagnosis of gout according to ACR.",
    ):
        assert en(text) != [], text
    for text in (
        "診断名と診断日。",
        "専門医によって関節リウマチと診断された患者。",
        "医師の診断を引用します。",
        "診断は医師が行います。",
    ):
        assert ja(text) == [], text
        assert check(text) != [], text
    for text in ("AIによって糖尿病と診断された患者。", "ツールの診断結果を使います。", "痛風の診断"):
        assert ja(text) != [], text


# -------------------------------------------------------------------------------- the product's own texts
@pytest.mark.parametrize("source", ["console", "orchestrator", "opportunity_hub"])
@pytest.mark.parametrize("lang", ["en", "ja"])
def test_no_en_or_ja_catalogue_string_makes_a_device_claim(source: str, lang: str) -> None:
    """Every English and Japanese string of the console, orchestrator and opportunity-hub catalogues, read with its
    language named (D-1228's own test reads every catalogue with no language, so as before)."""
    hits = []
    for key, text in _source(source)[lang].items():
        hits += [f"{key}: {h.word} in {h.context}" for h in check(re.sub(r"{\w+}", " ", text), lang=lang)]
    assert hits == []


def test_no_shipped_criterion_label_makes_an_en_or_ja_device_claim() -> None:
    """Every criterion label and text in rulesets/*/labels.yaml, read with its language named: a trial's own criteria
    mention diagnosis and treatment as data (treated with, diagnosed with, before screening), and none is a claim."""
    hits = []
    for path in sorted((ROOT / "rulesets").glob("*/labels.yaml")):
        for cid, entry in (yaml.safe_load(path.read_text(encoding="utf-8")).get("criteria") or {}).items():
            for lang in ("en", "ja"):
                for field, text in (entry.get(lang) or {}).items():
                    hits += [f"{cid} {lang} {field}: {h.word} in {h.context}" for h in check_claims(str(text), lang)]
    assert hits == []


def test_a_catalogue_instrument_is_named_by_its_own_name() -> None:
    """An instrument's catalogue name (International Prognostic Index, FRAX … 確率) is a record value's name, not the
    product scoring a patient (D-351). Every name in the catalogue passes in its language, each listed name is in the
    catalogue, and the closest real claims fail."""
    rows = list(csv.DictReader((ROOT / "catalogue/items.csv").open(encoding="utf-8")))
    instruments = [r["name"] for r in csv.DictReader((ROOT / "catalogue/instruments.csv").open(encoding="utf-8"))]
    assert [n for n in instruments if check_claims(n, "en")] == []  # the /data/instruments page names them
    rows += [{"name_en": n, "name_ja": ""} for n in instruments]
    assert [r["name_en"] for r in rows if check_claims(r["name_en"], "en")] == []
    assert [r["name_ja"] for r in rows if check_claims(r["name_ja"], "ja")] == []
    assert [n for n in NAMED_INSTRUMENTS_EN if not any(n in r["name_en"] for r in rows)] == []
    assert [n for n in NAMED_INSTRUMENTS_JA if not any(n in r["name_ja"] for r in rows)] == []
    for claim in (
        "The AI computes each patient's fracture probability.",
        "TrialBox gives a prognosis for each patient.",
    ):
        assert en(claim) != [], claim
    assert ja("AIが患者ごとの骨折確率を計算します。") != []


# Each allowed context is pinned: the sentence passes only because of its context, and fails without it.
PINNED_EN = [
    ("score", "The patient's ECOG score is entered by staff."),
    ("risk", "Patients are told the study's main risks."),
    ("risk", "The risk of bias in patient studies is low."),
    ("predict", "Patients and enrolment forecast per month."),
    ("detect", "Tumour markers below the detection limit."),
    ("screening", "Stroke within 90 days before screening."),
    ("possible", "Possible candidates for the asthma study with diabetes."),
    ("instrument", "International Prognostic Index"),
]
PINNED_JA = [
    ("可能性", "糖尿病研究の参加条件に合う可能性のある患者。"),
    ("instrument", "冠動脈 zスコア（川崎病）"),
    ("スクリーニング", "スクリーニング前90日以内の心筋梗塞。"),
]


@pytest.mark.parametrize(("term", "text"), PINNED_EN)
def test_each_english_allowed_context_is_what_lets_its_sentence_pass(
    term: str, text: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert en(text) == []
    monkeypatch.setitem(CLAIM_ALLOWED_EN, term, ())
    assert en(text) != []


@pytest.mark.parametrize(("term", "text"), PINNED_JA)
def test_each_japanese_allowed_context_is_what_lets_its_sentence_pass(
    term: str, text: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert ja(text) == []
    monkeypatch.setitem(CLAIM_ALLOWED_MORE_JA, term, ())
    assert ja(text) != []


# ------------------------------------------------------------------------------------------ one rule, by language
def test_one_rule_three_tables_and_the_caller_names_the_language() -> None:
    """D-1256: the English table reads only text named en, and D-1256's Japanese classes only text named ja. Text
    with no language, or named zh-TW, is read by D-1228's Japanese table exactly as before; the script is never used
    to guess."""
    assert [t.lang for t in CLAIM_TABLES] == ["ja", "zh-TW", "en"]
    claim_en, claim_ja = "TrialBox prevents strokes.", "本システムは脳卒中を予防します。"
    assert en(claim_en) != [] and check(claim_en) == [] and check(claim_en, lang="ja") == []
    assert ja(claim_ja) != [] and check(claim_ja) == [] and check(claim_ja, lang="zh-TW") == []
    assert check_page(f'<html lang="en"><p>{claim_en}</p></html>') != []
    assert check_page(f'<html lang="ja"><p>{claim_ja}</p></html>') != []
    assert deny_masked("TrialBox does not predict risk.", "en") != "TrialBox does not predict risk."
    assert deny_masked("TrialBox does not predict risk.") == "TrialBox does not predict risk."


def test_the_statement_passes_in_every_language_without_its_allowed_mask() -> None:
    """The intended-use statement denies the claims it names (does not diagnose, treat or prevent disease; 診断・治療・
    予防は行わず): it passes the claim rule on its own, read in its own language."""
    assert check_claims(STATEMENT["en"], "en") == []
    assert check_claims(STATEMENT["ja"], "ja") == []
    assert check(STATEMENT["en"], allowed=(), lang="en") == []


def test_the_known_limits_are_what_d1256_says() -> None:
    """D-1256's known limits, recorded so that a change to them is seen."""
    assert en("Is the patient sick? The system will tell you.") == []  # a claim split across two sentences
    assert en("TrialBox shines a light on patients hiding in the records.") == []  # a metaphor with no claim word
    assert en("Can treat depression.") == []  # an act on a disease with no subject
    assert check("TrialBox prevents strokes.") == []  # English text the caller does not name en: not read
    assert ja("本システムは外来記録からうつ病の兆候を読み取ります。") == []  # 読み取り is the product's word
    assert en("A pregnancy diagnosis within 280 days.") != []  # a criterion's diagnosis with no subject: refused
