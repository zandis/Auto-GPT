"""Keyword expansion for note retrieval (SPEC §7.5: "criterion keywords translated to zh-TW/ja terms table").

Clinical notes in Taiwan mix Chinese narrative with English terms; Japanese sites write Japanese. The retrieval query
adds the zh-TW and ja equivalents of the English keywords found in the criterion text.
"""

from __future__ import annotations

import re

TERMS: dict[str, tuple[str, ...]] = {
    "gout": ("痛風", "痛風"),
    "flare": ("發作", "急性發作", "発作"),
    "flares": ("發作", "発作"),
    "attack": ("發作", "発作"),
    "tophus": ("痛風石", "痛風結節"),
    "urate": ("尿酸", "尿酸値"),
    "uric": ("尿酸",),
    "colchicine": ("秋水仙素", "コルヒチン"),
    "rheumatoid": ("類風濕", "関節リウマチ"),
    "arthritis": ("關節炎", "関節炎"),
    "das28": ("DAS28", "疾病活動度"),
    "response": ("治療反應", "反応"),
    "remission": ("緩解", "寛解"),
    "biologic": ("生物製劑", "生物学的製剤"),
    "dmard": ("DMARD", "抗風濕藥"),
    "methotrexate": ("MTX", "滅殺除癌", "メトトレキサート"),
    "tuberculosis": ("結核", "肺結核", "TB"),
    "hepatitis": ("肝炎", "B型肝炎"),
    "pregnancy": ("懷孕", "妊娠"),
    "pregnant": ("懷孕", "妊娠"),
    "surgery": ("手術",),
    "injection": ("注射", "自行注射", "自己注射"),
    "pain": ("疼痛", "痛"),
    "swelling": ("腫脹", "腫れ"),
    "joint": ("關節", "関節"),
    "infection": ("感染",),
    "cancer": ("癌", "惡性腫瘤", "悪性腫瘍"),
    "tumor": ("腫瘤", "腫瘍"),
    "stage": ("分期", "病期"),
    "ecog": ("ECOG", "體能狀態"),
    "egfr": ("EGFR", "表皮生長因子受體"),
    "mutation": ("突變", "変異"),
}
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]+")


def keywords(text: str, limit: int = 12) -> list[str]:
    """zh-TW / ja equivalents of the English keywords in ``text`` (deduplicated, in order of appearance)."""
    out: list[str] = []
    for w in _WORD.findall(text):
        for t in TERMS.get(w.lower(), ()):
            if t not in out:
                out.append(t)
    return out[:limit]
