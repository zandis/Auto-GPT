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


# ------------------------------------------------------------------------------------------------ Alzheimer's (T-503)
# Memory-clinic notes and reports of the ``ad`` archetype (scenario J1, trial AD-MAB). Each function returns one
# sentence (or one report) that answers one AD-MAB criterion; the date is passed in already written. To be read by a
# native clinician before the PoC (T-503 PR).
AD_FILLER = [
    "本人は物忘れの自覚に乏しく、家族が日付や約束を忘れることを心配して受診。",
    "神経学的所見：脳神経に異常なし、明らかな運動麻痺や感覚障害なし、歩行は安定。",
    "日常生活動作は自立しているが、金銭管理と服薬管理は家族が一部援助している。",
    "抑うつ気分や幻視の訴えはなく、睡眠は保たれている。",
    "前回受診時と比べ、会話の内容や応答に大きな変化はない。",
    "家族より、同じ話を繰り返すことが増えたとの情報あり。",
    "血液検査でビタミンB12、葉酸、甲状腺機能に異常なし。",
    "運動と社会参加を続けるよう本人と家族に説明した。",
    "車の運転は家族と相談のうえ控えているとのこと。",
    "次回、認知機能検査の再評価を予定する。",
]


def mmse_sentence(date_text: str, mmse: int, hdsr: int | None) -> str:
    if hdsr is None:
        return f"{date_text}の認知機能検査でMMSE {mmse}点（30点満点）であった。"
    return f"{date_text}の認知機能検査でMMSE {mmse}点（30点満点）、HDS-R {hdsr}点であった。"


def hdsr_only_sentence(date_text: str, hdsr: int) -> str:
    return f"{date_text}にHDS-R {hdsr}点（30点満点）。MMSEは本日未施行。"


def cdr_sentence(cdr: str) -> str:
    return f"CDR（Clinical Dementia Rating）の全般スコアは{cdr}と評価した。"


def amyloid_pet_report(date_text: str, positive: bool) -> str:
    if positive:
        return f"【アミロイドPET】{date_text}施行。大脳皮質にびまん性のアミロイド集積を認め、視覚読影で陽性と判定する。"
    return f"【アミロイドPET】{date_text}施行。大脳皮質へのアミロイド集積は認めず、視覚読影で陰性と判定する。"


def csf_report(date_text: str) -> str:
    return (
        f"【脳脊髄液検査】{date_text}採取。Aβ42/40比は低下、リン酸化タウ（p-tau181）は高値であり、"
        "アミロイド病理を示唆する所見（陽性）。"
    )


def amyloid_not_done_sentence() -> str:
    return "アミロイドPETおよび脳脊髄液検査は未実施である。"


def mri_report(date_text: str, microbleeds: int, siderosis: bool) -> str:
    head = f"【頭部MRI】{date_text}施行。両側海馬に軽度の萎縮を認める。"
    mb = f"T2*強調像で脳微小出血を{microbleeds}か所に認める。" if microbleeds else "T2*強調像で脳微小出血は認めない。"
    ss = "左頭頂葉の脳表にヘモジデリン沈着を認める。" if siderosis else "脳表ヘモジデリン沈着は認めない。"
    return head + mb + ss


def partner_sentence(has_partner: bool) -> str:
    if has_partner:
        return "長女と同居しており、受診には毎回長女が付き添っている。"
    return "独居で近隣に親族はおらず、受診はいつも一人で来院している。"
