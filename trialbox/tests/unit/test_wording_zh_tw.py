"""Card 10C-5b (D-1247): the Traditional Chinese (zh-TW) device-claims guard, through D-1228's one rule.

The Japanese tests of D-1228 (``tests/unit/test_wording.py``) run unchanged; this file mirrors them for zh-TW. For
every refused class there are near-misses that must pass, and for every allowed context the closest real claim that
must still be refused. ``FRESH_1`` (60 sentences) was written before the zh-TW rule was final, ``FRESH_2`` (40) after;
both are kept as written, and the PR reports how many each way the rule got right at each point.
"""

from __future__ import annotations

import pytest
from tb_common.wording import check, check_page

# Written before the zh-TW rule was final (card 10C-5b step 4): 30 claims, then 30 legitimate lines. Kept as written.
FRESH_1_CLAIMS = [
    "本系統可偵測早期肺癌病人。",
    "AI 能從病歷中找出尚未確診的糖尿病患者。",
    "TrialBox 會預測每位病人的住院風險。",
    "系統自動計算病人的死亡機率。",
    "本軟體提供疾病風險評分。",
    "協助醫師及早發現潛在病人。",
    "透過 AI 篩檢罕見疾病。",
    "模型判斷病人是否罹患心衰竭。",
    "列出疑似肺炎的病人清單。",
    "本產品可辨識有中風徵兆的病人。",
    "系統會針對每位受試者給出風險分數。",
    "AI 預後分析協助醫師。",
    "自動偵測病人病情惡化。",
    "本工具能早期檢出癌症。",
    "本軟體提供高危險群病人名單。",
    "TrialBox 找出可能有未診斷疾病的人。",
    "依 AI 評分排序病人。",
    "系統判別病人是否有腫瘤。",
    "演算法估算病人復發的機率。",
    "本系統能偵測敗血症前兆。",
    "我們的 AI 會發現醫師遺漏的疾病。",
    "為每位病患計算風險。",
    "AI 分數高的病人優先聯絡。",
    "篩檢出慢性腎病的高風險族群。",
    "本軟體可以早期篩檢失智症。",
    "系統會識別出病情可能加重的個案。",
    "本產品提供疾病預測服務。",
    "模型能判斷受試者的疾病嚴重度。",
    "利用人工智慧找出隱藏的病人。",
    "AI 會告訴您哪位病人最可能發病。",
]
FRESH_1_LEGITIMATE = [
    "本軟體不用於疾病之篩檢或診斷。",
    "系統找出近期回診的候選者。",
    "預測本月收案人數。",
    "依過去趨勢預測未來六個月的收案數。",
    "本研究的主要風險與好處請見同意書。",
    "試驗可能的風險已寫在受試者同意書中。",
    "無法辨識此檔案的文字編碼。",
    "低於偵測極限的數值維持不明。",
    "系統偵測到備份檔案不完整。",
    "請為此頁面評分。",
    "本軟體不預測病人的風險，也不給予任何分數。",
    "本工具並非用於發現疾病。",
    "是否符合研究資格由試驗主持人判斷。",
    "模型只讀取紀錄，參加與否由醫師判斷。",
    "計畫書中的 eGFR 分數由系統依公式計算。",
    "這份文獻的偏差風險為低。",
    "資料外洩的風險由資訊室管理。",
    "監測訪視的發現事項以新紀錄保存。",
    "識別編號已儲存。",
    "標記為識別資料的欄位會被捨棄。",
    "篩選結果顯示 12 位候選者符合條件。",
    "檢出率是合格病人中被找到的比例。",
    "系統沒有疾病預測功能。",
    "本軟體未提供任何風險評分。",
    "疾病代碼系統無法辨識時，條件列為未知。",
    "預測隨機分派人數需要篩選失敗率。",
    "分數定義變更後需重新核准。",
    "以 DAS28 分數核對病人的條件。",
    "試驗主持人判斷病人是否參加；TrialBox 僅列出紀錄。",
    "本軟體不做診斷、預測或風險分層。",
]


@pytest.mark.parametrize("text", FRESH_1_CLAIMS)
def test_every_fresh_claim_of_the_first_set_fails(text: str) -> None:
    """A real claim that passes is a blocker (card 10C-5b)."""
    assert check(text) != []
    assert check_page(f"<p>{text}</p>") != []
