"""F6 of the integrator's root-cause review of the P1b run (#639, 2026-11-16), D-985: a note exclusion decided by
INFERRING a diagnosis. On jmed both models agreed, four times, that a patient "has a history of hypertension" from
"降圧薬は服用しています" (takes an antihypertensive) or "has a history of diabetes" from metformin with an HbA1c, and
the judge's own reason said there was no stated history; sigir's NCT01784523 counted ACR criteria into SLE.
``both_agree`` does not protect against a shared inference.

An exclusion's "present" stands only on a quote that states the criterion's condition: its own words, an abbreviation
or synonym of it (HTN, T2DM, 妊娠 for pregnancy), and not negated, a family history, a risk or a drug for it ("denies
diabetes", "family history of hypertension", 高血圧リスク, 糖尿病薬). Any other quote (a drug, a dose, a lab value,
findings counted into a diagnosis) is an inference and goes to review. The quote is the verified span (CAS-16), never
the model's reason, which claimed a diagnosis on every one of these. A generic diagnosis word (症, 診断, "known") is
not the condition: 健康診断 or "diagnosed with atrial fibrillation" states no hypertension.

A criterion in one language is read against notes in another through the concepts below and the cascade's own
bilingual terms table (an English "gout flare" is stated by 急性痛風發作). The criterion is its text only, never the
note question, whose filler (があります) would count as the condition.
A criterion that is itself a value, a drug or a procedure (ALT > 3x ULN, eGFR < 30, corticosteroids, HBsAg positive)
is out of scope: there the value or the drug IS what the line asks about.
"""

from __future__ import annotations

import re
import unicodedata

from tb_common.quotes import quote_key

# Concepts named by abbreviation or synonym. English entries are word prefixes (case-insensitive) unless all capitals,
# which match as whole words, case as written; CJK entries match anywhere.
_CONCEPTS: tuple[tuple[str, ...], ...] = (
    ("hypertens", "HTN", "高血圧", "高血壓"),
    ("diabet", "DM", "T1DM", "T2DM", "DM1", "DM2", "IDDM", "NIDDM", "糖尿病"),
    (
        "chronic kidney",
        "renal insufficiency",
        "renal failure",
        "CKD",
        "ESRD",
        "慢性腎臓病",
        "慢性腎臟病",
        "腎不全",
        "腎衰竭",
        "腎功能不全",
        "腎機能障害",
    ),
    ("myocardial infarct", "heart attack", "MI", "AMI", "STEMI", "NSTEMI", "心筋梗塞", "心肌梗塞", "心肌梗死"),
    ("atrial fibrillation", "AF", "AFib", "A-fib", "心房細動", "心房顫動"),
    ("chronic obstructive", "COPD", "emphysema", "慢性閉塞性肺疾患", "慢性阻塞性肺病"),
    ("HIV", "human immunodeficiency", "愛滋", "エイズ"),
    ("hepatitis B", "HBV", "HBsAg", "B型肝炎"),
    ("hepatitis C", "HCV", "C型肝炎"),
    ("heart failure", "HF", "HFrEF", "HFpEF", "CHF", "心不全", "心衰竭"),
    ("lupus", "SLE", "エリテマトーデス", "紅斑性狼瘡"),
    ("pregnan", "妊娠", "懷孕", "怀孕"),
    ("breastfeed", "breast-feed", "lactat", "nursing", "授乳", "哺乳"),
    ("stem cell transplant", "SCT", "HSCT", "BMT", "幹細胞移植", "造血幹細胞"),
    (
        "cancer",
        "carcinoma",
        "adenocarcinoma",
        "malignan",
        "metasta",
        "tumor",
        "tumour",
        "neoplasm",
        "lymphoma",
        "leukemia",
        "leukaemia",
        "myeloma",
        "melanoma",
        "sarcoma",
        "NSCLC",
        "SCLC",
        "癌",
        "がん",
        "腫瘍",
    ),
    ("stroke", "CVA", "cerebrovascular", "脳卒中", "腦中風", "中風", "脳梗塞", "腦梗塞"),
    ("alcohol", "drinks", "beer", "ethanol", "飲酒", "アルコール"),
    ("smok", "tobacco", "cigarette", "喫煙", "吸菸", "抽菸"),
    ("epilep", "seizure", "てんかん", "癲癇"),
)
# The words around a condition that say what a line asks, not what it asks about.
_GENERIC = re.compile(
    r"既往|患者|がありますか|ありますか|あります|がある|のある|あり|ます|です|ください|ません|"
    r"の|歴|病史|有|曾|者|ある|いる|患|史|か|中(?=$|[^㐀-䶿一-鿿])"
)
_CJK_RUN = re.compile(r"[㐀-䶿一-鿿぀-ヿ]+")
_STOP = {
    "patient", "patients", "history", "with", "have", "has", "had", "known", "current", "currently", "prior",
    "previous", "does", "the", "any", "who", "that", "this", "subject", "subjects", "diagnosis", "diagnosed", "based",
    "criteria", "within", "months", "years", "weeks", "other", "clinically", "significant", "severe", "active",
    "chronic", "acute", "uncontrolled", "condition", "conditions", "illness", "medical", "disease", "disorder",
    "syndrome", "comply", "compliance", "protocol", "investigator", "ability", "judgment", "judgement", "opinion",
    "consent", "informed", "study", "trial", "interfere", "participate", "participation", "would", "which", "their",
}  # fmt: skip
# A criterion that is itself a value, a drug or a procedure, and names none of the conditions above: the rule does
# not apply. "SLE ... ACR criteria > 4/11" names SLE, so it does.
_NOT_A_CONDITION = re.compile(
    r"[<>≤≥≦≧]|\bULN\b|\d\s*(?:mg|g/dl|ml|%|u/l|mmol|µmol|umol)|\b(?:eGFR|CrCl|ALT|AST|HbA1c|INR)\b|creatinine|"
    r"bilirubin|platelet|haemoglobin|hemoglobin|neutrophil|\bcount\b|\blevel|positive|negative|therap|treatment|"
    r"medication|\bdrugs?\b|steroid|chemotherap|insulin|anticoagul|inhibitor|vaccin|surgery|surgical|operation|"
    r"\breceiv|\btaking\b|\buse of\b|\busing\b|服用|内服|投与|治療|薬(?!疹|物性)|手術|陽性|陰性|値|值|使用",
    re.IGNORECASE,
)
# A mention that does not state the condition: negated or stated absent, a relative's, suspected, a risk, a screen
# (R22-16 round 2). Read in the whole part of the sentence that holds the mention (``_part``), before or after it:
# Japanese and Chinese put the negation or the doubt at the end (嘔吐はない, 心外膜炎疑い, 腫瘍が増悪する可能性も考慮
# された), English often before or after ("Epicarditis was suspected", "no enlargement or fibrosis").
_NOT_STATED = re.compile(
    r"\b(?:no|not|never|none|nor|neither|without|absent|absence|negative|neg|deny|denies|denied|unlikely|excluded?|"
    r"free of|no longer|ruled? out|rules out|r/o|resolved|resected|removed|dropped off|disappeared|healed|subsided|"
    r"cleared|suspect\w*|possib\w*|probab\w*|likely|suggest\w*|consider\w*|may|might|could|quer\w*|questionabl\w*|"
    r"concern for|differential|versus|vs|either|characteristic\w*|consistent with|compatible with|pending|await\w*|"
    r"presum\w*|evaluat\w* for|work-?up|screen\w*|risk|"
    r"(?:grand|step|half-?)?(?:mother|father|parents?|sisters?|brothers?|siblings?|sons?|daughters?)|grandparents?|"
    r"aunts?|uncles?|cousins?|wife|husband|spouse|relatives?|family|familial|maternal|paternal)\b|n't\b|\?|"
    r"\(\s*[-−]\s*\)|"
    r"なし|無し|なく|ない|無い|ません|否定|否認|陰性|認めず|認めな|認められず|認められな|未|疑|可能|考え|推定|推測|示唆|"
    r"考慮|鑑別|除外|排除|リスク|家族|母|父|兄|姉|弟|妹|祖|叔|伯|息子|娘|妻|夫|親|どちら|性格|沒有|没有|無|不明|待查|消失",
    re.IGNORECASE,
)
# A drug or diet for it, said right after the mention (糖尿病薬, "diabetic diet").
_AFTER = re.compile(
    r"^\W{0,2}(?:薬|治療薬|diet|medication|meds|drug)",
    re.IGNORECASE,
)
# A sentence; and within it, the parts a contrast divides ("HTN, but no family history"; 高血圧症がありますが、家族歴は
# ありません): a negation in the other part says nothing about this mention.
_SENTENCE = re.compile(r"[;。；！？!?\n]|\.(?=\s|$)")
_CONTRAST = re.compile(
    r"が[、,]|けれど|けど|しかし|ただし|但し|但是|不過|\b(?:but|however|although|though|whereas|while)\b", re.IGNORECASE
)


def _is_caps(term: str) -> bool:
    return term.isascii() and term.upper() == term and any(ch.isalpha() for ch in term)


def _pattern(term: str) -> re.Pattern[str]:
    if not term.isascii():
        return re.compile(re.escape(term))
    if _is_caps(term) or term in {"AFib", "HFrEF", "HFpEF"}:  # an abbreviation: the whole word, as written
        return re.compile(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z])")
    return re.compile(rf"\b{re.escape(term)}", re.IGNORECASE)  # a word start: "hyper" is not in "prehypertension"


def _terms(criterion: str) -> list[str]:
    """What names the criterion's condition: its own Han / kana runs (generic words removed), the prefix of each of
    its content words, its abbreviations, and every abbreviation or synonym of a concept it names."""
    terms: list[str] = []
    for run in _CJK_RUN.findall(_GENERIC.sub(" ", criterion)):
        if len(run) == 2:
            terms.append(run)  # 喘息, 痛風, 妊娠: the run itself
        terms += [run[i : i + 3] for i in range(len(run) - 2)]
    for word in re.findall(r"[A-Za-z][A-Za-z-]{4,}", criterion):
        if word.lower() not in _STOP:
            terms.append(word[: max(5, len(word) - 3)].lower())  # "diabetes" finds "diabetic"
    terms += [a for a in re.findall(r"\b[A-Z][A-Za-z0-9]*[A-Z][A-Za-z0-9]*\b", criterion) if len(a) <= 6]
    for concept in _CONCEPTS:
        if any(_pattern(t).search(criterion) for t in concept):
            terms += concept
    return terms + _translated(criterion)


def _translated(criterion: str) -> list[str]:
    """The site's bilingual terms table, both ways: an English criterion's words in zh-TW / ja (gout: 痛風), and a
    zh-TW / ja criterion's terms in English. A criterion in English is often read against notes in Chinese; one Han
    character alone (痛) names nothing."""
    from orchestrator.scenarios.terms import TERMS, keywords  # D-985; the cascade's own S2 table (D-103)

    out = [t for t in keywords(criterion, limit=len(criterion)) if len(t) > 1]
    out += [k for k, ts in TERMS.items() if any(len(t) > 1 and t in criterion for t in ts)]
    return out


def _part(text: str, start: int, end: int) -> str:
    """The part of ``text``'s sentence that holds ``text[start:end]``, between two contrasts, the mention blanked."""
    s0 = max((m.end() for m in _SENTENCE.finditer(text, 0, start)), default=0)
    s1 = next((m.start() for m in _SENTENCE.finditer(text, end)), len(text))
    p0 = max((s0, *(m.end() for m in _CONTRAST.finditer(text, s0, start))))
    p1 = next((m.start() for m in _CONTRAST.finditer(text, end, s1)), s1)
    return f"{text[p0:start]} _ {text[end:p1]}"


def _stated_at(quote: str, start: int, end: int) -> bool:
    if quote[end - 1 : end].isascii():  # to the end of the word: "diabe" is "diabetic diet"
        end += len(quote[end:]) - len(quote[end:].lstrip("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"))
    return not _NOT_STATED.search(_part(quote, start, end)) and not _AFTER.search(quote[end : end + 12])


def names_condition(quote: str, criterion: str) -> bool:
    """The quote states the criterion's condition: one of its terms (``_terms``), in a mention that is not negated
    or stated absent, a relative's, suspected, a risk, or a drug or diet for it. Both are read in NFKC (a record's
    full-width ＩＣＩｓ, （－）)."""
    q = unicodedata.normalize("NFKC", quote or "")
    for term in dict.fromkeys(_terms(unicodedata.normalize("NFKC", criterion or ""))):
        for m in _pattern(term).finditer(q):
            if _stated_at(q, m.start(), m.end()):
                return True
    return False


def inferred(quote: str, criterion: str, sentence: str = "") -> bool:
    """The criterion names a condition and the quote does not state it: a "present" on it is an inference (a
    treatment, a dose, a value, findings the model counted into a diagnosis, a negated, a relative's or a suspected
    condition). Never for a criterion that is itself a value, a drug or a procedure.

    ``sentence``: the record's sentence the quote was verified in (:func:`sentence_of`), when the caller has it. A
    quote may be a fragment of it ("HIV" of "Mother has HIV."): then the sentence must state the condition too
    (R22-16 round 2: the guard read only the quoted fragment)."""
    c = unicodedata.normalize("NFKC", criterion or "")
    if _NOT_A_CONDITION.search(c) and not any(_pattern(t).search(c) for concept in _CONCEPTS for t in concept):
        return False
    return not names_condition(quote or "", c) or bool(sentence and not names_condition(sentence, c))


def sentence_of(quote: str, text: str) -> str:
    """The sentence(s) of ``text`` (an excerpt) the ``quote`` lies in, read as :func:`tb_common.quotes.quote_key`
    reads both (NFKC, stray spaces by CJK dropped); "" when the quote is not in it."""
    q, t = quote_key(quote or ""), quote_key(text or "")
    at = t.find(q) if q else -1
    if at < 0:
        return ""
    s0 = max((m.end() for m in _SENTENCE.finditer(t, 0, at)), default=0)
    s1 = next((m.end() for m in _SENTENCE.finditer(t, at + len(q))), len(t))
    return t[s0:s1].strip()
