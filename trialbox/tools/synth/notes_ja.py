"""Japanese clinical note templates for the synthetic hospital (fictional content, TB-DS-21 §5.1).

The sentence sets mirror ``notes.py`` (zh-TW) slot by slot: positive, negative and negated sentences per note
criterion. Dates are passed in already written (西暦 or 和暦, see ``tools.synth.lang``).
"""

from __future__ import annotations

FILLER = [
    "バイタルサイン安定、意識清明。",
    "睡眠は良好、食欲も保たれている。",
    "身体所見：心音整、雑音なし、両側呼吸音清。",
    "内服を継続し、定期受診するよう説明した。",
    "検査結果を本人および家族に説明した。",
    "腹部平坦・軟、圧痛なし、腸蠕動音正常。",
    "両下肢浮腫なし、末梢動脈触知良好。",
    "低プリン食とし、清涼飲料水を控えるよう指導した。",
    "現処方を継続し、三か月後に再診とする。",
    "発熱、悪寒、体重減少はない。",
    "週150分以上の運動を勧めた。",
    "家庭血圧の記録を確認、おおむね安定している。",
    "直近三か月の外来記録を確認、服薬はおおむね良好だが時に飲み忘れあり、服薬時間を再度指導した。",
    "時に食後の胃部不快感あり、黒色便や吐血はない。食後内服とし経過観察とする。",
    "頸部リンパ節腫脹なし、甲状腺触知せず、胸部聴診でラ音なし。",
    "前回と比較し検査値に大きな変化はない。必要に応じて用量を調整する。",
    "食事療法について相談し、肉類・内臓・魚介類を控え、一日二リットル以上の飲水を勧めた。",
    "運動時の注意点を説明し、ウォーキングや水泳を勧めた。",
    "社会歴：既婚、配偶者と同居、喫煙歴なし、機会飲酒（最近は減量）。",
    "家族歴：母に高血圧と糖尿病、父に脂質異常症あり。",
]

JOINTS = ["右第一中足趾節関節", "左第一中足趾節関節", "右足関節", "左膝関節", "右手関節"]


def flare_sentence(date_text: str, joint: str) -> str:
    return f"{date_text}に{joint}の発赤・腫脹・熱感・疼痛あり、急性痛風発作と診断しコルヒチンで改善した。"


def no_flare_sentence() -> str:
    return "過去一年間に痛風発作はなく、関節の発赤・腫脹もない。"


def single_flare_sentence(date_text: str) -> str:
    return f"過去一年間の痛風発作は{date_text}の一回のみで、その後の再発はない。"


def current_flare_sentence() -> str:
    return "現在、右第一中足趾節関節に急性の発赤・腫脹・疼痛あり、急性痛風発作中である。"


def no_current_flare_sentence() -> str:
    return "現在、急性痛風発作はなく、関節の発赤・圧痛は認めない。"


def ra_assessment_sentence(tjc: int, sjc: int, ptga: int) -> str:
    return f"両手PIP関節に腫脹・疼痛あり、圧痛関節数{tjc}、腫脹関節数{sjc}、患者全般評価{ptga}/100。"


def response_sentence(delta: float, good: bool) -> str:
    if good:
        return f"ベースラインと比べDAS28は{delta:.1f}低下し、治療反応は良好。生物学的製剤を継続する。"
    return f"ベースラインと比べDAS28の低下は{delta:.1f}にとどまり、治療反応不十分。薬剤変更を検討する。"


def injection_willing_sentence(willing: bool) -> str:
    if willing:
        return "週一回の自己皮下注射を受け入れる意向あり。"
    return "注射が怖く、自己注射は希望しないとのこと。"


ECOG_SENTENCE = "ECOG PSは1で、日常生活は自立している。"
CXR_CLEAR = "両肺野清明、活動性結核を示唆する所見なし。"
LUNG_MASS = "右上葉に約3.2cmの腫瘤影あり、原発性肺癌を疑う。遠隔転移の所見なし。"

NEEDLES: list[tuple[str, str]] = [
    ("北海道旅行中に初めて足関節の激痛が出現した", "北海道旅行 足関節 激痛"),
    ("家族歴として父が痛風結節の切除術を受けている", "父 痛風結節 切除"),
    ("毎日加糖の缶コーヒーを三本飲んでいる", "加糖 缶コーヒー 三本"),
    ("職業は夜勤のタクシー運転手で生活が不規則", "夜勤 タクシー運転手"),
    ("マラソン大会の後に横紋筋融解症を起こしたことがある", "マラソン 横紋筋融解症"),
    ("サルファ剤で皮疹が出たことがある", "サルファ剤 皮疹"),
]
