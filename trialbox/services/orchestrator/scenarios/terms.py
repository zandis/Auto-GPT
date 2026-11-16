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
    "egfr": ("EGFR", "表皮生長因子受體"),  # the receptor; the kidney's eGFR is ``_KIDNEY_EGFR`` (D-986)
    "mutation": ("突變", "変異"),
}
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]+")

# D-986: "EGFR" is two things. The epidermal growth factor receptor (a lung cancer's mutation, its TKI) is written in
# capitals; the kidney's estimated glomerular filtration rate is "eGFR". The spelling decides unless the line says
# otherwise: a kidney word (mL/min, creatinine, renal, CKD) makes "EGFR" the kidney's, a receptor word (mutation,
# exon, TKI, NSCLC) makes "eGFR" the receptor's. A comparison with a number ("EGFR < 30") is the kidney's value.
_KIDNEY_EGFR = ("eGFR", "腎絲球過濾率", "腎小球濾過率", "糸球体濾過量")
_KIDNEY_SAID = re.compile(
    r"egfr\s*(?:[<>≤≥≦≧=]|of|below|above|under|over)\s*\d|ml\s*/\s*min|creatinine|renal|kidney|\bckd\b|"
    r"glomerular|dialysis|腎|クレアチニン",
    re.IGNORECASE,
)
_RECEPTOR_SAID = re.compile(
    r"mutat|exon|\btkis?\b|tyrosine\s+kinase|growth\s+factor|nsclc|lung\s+(?:cancer|adeno|carcinoma)|l858r|t790m|"
    r"del\s*19|amplif|變異|変異|突變|受體|受容体|肺癌|肺腺癌",
    re.IGNORECASE,
)


def egfr_sense(word: str, text: str) -> str:
    """``"kidney"`` or ``"receptor"``: what an "egfr" written as ``word`` in ``text`` means (D-986)."""
    kidney, receptor = bool(_KIDNEY_SAID.search(text)), bool(_RECEPTOR_SAID.search(text))
    if kidney != receptor:
        return "kidney" if kidney else "receptor"
    return "receptor" if word == "EGFR" else "kidney"


def _terms_of(word: str, text: str) -> tuple[str, ...]:
    k = word.lower()
    if k == "egfr" and egfr_sense(word, text) == "kidney":
        return _KIDNEY_EGFR
    return TERMS.get(k, ())


def source_words(text: str) -> list[str]:
    """The English keywords of ``text`` that the terms table knows (deduplicated, in order of appearance): the lexicon
    keys for notes written in English (the cascade's S2, D-103)."""
    out: list[str] = []
    for w in _WORD.findall(text):
        k = w.lower()
        if k in TERMS and k not in out:
            out.append(k)
    return out


def keywords(text: str, limit: int = 12) -> list[str]:
    """zh-TW / ja equivalents of the English keywords in ``text`` (deduplicated, in order of appearance)."""
    out: list[str] = []
    for w in _WORD.findall(text):
        for t in _terms_of(w, text):
            if t not in out:
                out.append(t)
    return out[:limit]
