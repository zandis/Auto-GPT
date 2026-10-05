"""zh-TW clinical note templates for the synthetic hospital (fictional content)."""

from __future__ import annotations

import random
from datetime import date

SURNAMES = list("陳林黃張李王吳劉蔡楊許鄭謝郭洪曾邱廖賴周徐蘇葉莊呂江何蕭羅高潘簡朱鍾游彭詹胡施沈余趙盧梁顏柯翁魏孫戴")
GIVEN = list("家俊志明怡君淑芬美玲建宏雅婷宗翰承恩冠宇心怡佳穎柏翰品妤子豪欣怡俊傑淑惠秀英文雄")

FILLER = [
    "生命徵象穩定，意識清楚。",
    "病人主訴近期睡眠品質尚可，食慾正常。",
    "身體診察：心音規則，無雜音，雙側呼吸音清晰。",
    "衛教病人規律服藥並定期回診追蹤。",
    "已向病人及家屬說明檢驗結果。",
    "腹部柔軟，無壓痛，腸音正常。",
    "四肢無水腫，周邊脈搏可觸及。",
    "建議低普林飲食並減少含糖飲料攝取。",
    "持續原處方藥物，三個月後回診。",
    "病人無發燒、畏寒或體重明顯減輕。",
    "建議規律運動，每週至少一百五十分鐘。",
    "血壓自我監測紀錄已檢視，大致穩定。",
    "回顧近三個月門診紀錄，病人大致依醫囑服藥，偶有漏服情形，已再次衛教服藥時間與注意事項。",
    "病人主訴偶有胃部不適，進食後較明顯，無黑便或吐血，建議飯後服藥並觀察症狀變化。",
    "理學檢查：頭頸部無淋巴結腫大，甲狀腺未觸及腫塊，胸部聽診無囉音，心跳規則無雜音。",
    "檢驗結果與上次比較變化不大，將持續追蹤相關數值，必要時調整藥物劑量。",
    "與病人討論飲食控制，建議減少紅肉、內臟及海鮮攝取，多喝水，每日至少兩千毫升。",
    "病人詢問運動相關注意事項，已說明避免劇烈運動造成關節受傷，建議以快走或游泳為主。",
    "社會史：已婚，與配偶同住，不抽菸，偶爾社交性飲酒，近期已減量。",
    "家族史：母親有高血壓及糖尿病，父親有高血脂，兄弟姊妹健康狀況良好。",
]


def fake_name(rng: random.Random) -> str:
    return rng.choice(SURNAMES) + rng.choice(GIVEN) + rng.choice(GIVEN)


def roc(d: date) -> str:
    return f"{d.year}年{d.month}月{d.day}日"


def filler(rng: random.Random, n: int) -> str:
    return "".join(rng.sample(FILLER, k=min(n, len(FILLER))))


def flare_sentence(d: date, joint: str) -> str:
    return f"病人於{roc(d)}{joint}紅腫熱痛，臨床診斷為急性痛風發作，給予秋水仙素治療後緩解。"


def no_flare_sentence() -> str:
    return "病人表示過去一年內沒有任何痛風發作，關節無紅腫熱痛。"


def single_flare_sentence(d: date) -> str:
    return f"過去一年僅於{roc(d)}有一次痛風發作，其後無再發作。"


def current_flare_sentence() -> str:
    return "目前右側第一蹠趾關節急性紅腫熱痛，診斷為急性痛風發作中。"


def no_current_flare_sentence() -> str:
    return "目前無急性痛風發作，關節檢查無紅腫或壓痛。"


def ra_assessment_sentence(tjc: int, sjc: int, ptga: int) -> str:
    return f"雙手近端指間關節腫痛，壓痛關節數{tjc}處，腫脹關節數{sjc}處，病人整體評估{ptga}/100。"


def response_sentence(delta: float, good: bool) -> str:
    if good:
        return f"與基準期相比DAS28下降{delta:.1f}，治療反應良好，建議續用生物製劑。"
    return f"與基準期相比DAS28僅下降{delta:.1f}，治療反應不佳，需評估是否更換藥物。"


def injection_willing_sentence(willing: bool) -> str:
    if willing:
        return "病人表示願意接受每週一次自行皮下注射。"
    return "病人表示害怕打針，不願意自行注射藥物。"


JOINTS = ["右側第一蹠趾關節", "左側第一蹠趾關節", "右側踝關節", "左膝關節", "右手腕關節"]

# Distinctive "needle" facts for the 20 seeded retrieval queries (phase 1 DoD).
NEEDLES: list[tuple[str, str]] = [
    ("病人於花蓮旅遊時首次出現足踝劇痛", "花蓮旅遊 足踝劇痛"),
    ("家族史：父親曾因痛風石接受手術切除", "父親 痛風石 手術"),
    ("病人自述每日飲用三瓶含糖手搖飲", "含糖手搖飲 每日"),
    ("職業為夜班計程車司機，作息不規律", "夜班計程車司機"),
    ("曾於馬拉松比賽後出現橫紋肌溶解", "馬拉松 橫紋肌溶解"),
    ("病人對磺胺類藥物過敏，曾出現皮疹", "磺胺類藥物過敏"),
    ("近期接受牙齒植體手術，術後恢復良好", "牙齒植體手術"),
    ("病人計畫明年移居澳洲與子女同住", "移居澳洲"),
    ("曾參與社區健走活動並獲得獎牌", "社區健走 獎牌"),
    ("飼養兩隻貓，否認其他動物接觸史", "飼養兩隻貓"),
    ("過去曾在海產餐廳擔任廚師十年", "海產餐廳 廚師"),
    ("病人表示服用中藥補品後症狀加劇", "中藥補品 症狀加劇"),
    ("左手第三指曾因車禍骨折開刀", "車禍骨折 左手第三指"),
    ("病人為素食者，蛋奶素已二十年", "蛋奶素 二十年"),
    ("最近一次出國為日本北海道滑雪", "北海道滑雪"),
    ("夜間睡眠時有打鼾及呼吸中止情形", "打鼾 呼吸中止"),
    ("病人擔任國小教師，需長時間站立", "國小教師 站立"),
    ("曾接受白內障手術，視力已改善", "白內障手術"),
    ("家中有高齡母親需照顧，壓力大", "照顧高齡母親 壓力"),
    ("病人喜好釣魚，每週末至基隆海邊", "釣魚 基隆"),
]
