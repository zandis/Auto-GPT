"""Deterministic answers for every TrialBox prompt (``TB_LLM_MODE=stub``; DECISIONS D-13).

These handlers make CPU CI and macOS development exercise the exact ``chat_json`` path (schemas, retries, audit,
post-processing) without a model. They are NOT a clinical NLP system: the judge rules recognise the sentence
templates of the synthetic fixtures; LLM quality is measured only with a real model (``pytest -m llm``).
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from tb_common import dates

CASSETTES = Path(__file__).resolve().parent / "cassettes"
_DATE_ZH = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip().lower()


# ----------------------------------------------------------------------------- ir_extract
_NUM = r"(\d+(?:\.\d+)?)"
_OPS = {"≥": ">=", ">=": ">=", "≤": "<=", "<=": "<=", ">": ">", "<": "<"}
_OP = r"(≥|>=|≤|<=|>|<)"


def _heuristic_criterion(line: dict[str, Any]) -> dict[str, Any]:
    """Pattern extractor for common single-variable criteria; anything else becomes a `human` criterion."""
    text = str(line["text"])
    t = text.replace("kg/m²", "kg/m2")
    base = {
        "text": text,
        "label": text[:40],
        "source_ref": line.get("source_ref") or "",
        "kind": line["kind"],
        "time_sensitive": False,
        "concept_candidates": [],
    }
    patterns: list[tuple[str, dict[str, Any], list[dict[str, Any]]]] = [
        (
            rf"\bBMI\)?\s*{_OP}\s*{_NUM}",
            {
                "domain": "observation",
                "derived": "bmi",
                "quantifier": "latest",
                "window": {"from_days": -365, "to_days": 0},
            },
            [],
        ),
        (
            rf"\beGFR\b.*?{_OP}\s*{_NUM}",
            {
                "domain": "observation",
                "derived": "egfr",
                "quantifier": "latest",
                "window": {"from_days": -365, "to_days": 0},
            },
            [],
        ),
        (
            rf"\bDAS28\b.*?{_OP}\s*{_NUM}",
            {
                "domain": "observation",
                "derived": "das28",
                "quantifier": "latest",
                "window": {"from_days": -90, "to_days": 0},
            },
            [],
        ),
        (
            rf"\bHbA1c\s*{_OP}\s*{_NUM}",
            {
                "domain": "observation",
                "concept": "hba1c",
                "quantifier": "latest",
                "window": {"from_days": -180, "to_days": 0},
            },
            [{"domain": "observation", "name": "hba1c", "synonyms": []}],
        ),
        (
            rf"(?:serum urate|uric acid|sUA)\s*{_OP}\s*{_NUM}",
            {
                "domain": "observation",
                "concept": "serum urate",
                "quantifier": "latest",
                "window": {"from_days": -365, "to_days": 0},
            },
            [{"domain": "observation", "name": "serum urate", "synonyms": ["uric acid"]}],
        ),
        (rf"aged?\s*{_NUM}\s*years? or older|age\s*{_OP}\s*{_NUM}", {"domain": "demographic"}, []),
    ]
    for pat, atom, concepts in patterns:
        m = re.search(pat, t, re.I)
        if not m:
            continue
        groups = [g for g in m.groups() if g is not None]
        if atom["domain"] == "demographic":
            num = float(groups[-1])
            op = _OPS.get(groups[0], ">=") if len(groups) == 2 else ">="
            age = {"min": num} if op in (">=", ">") else {"max": num}
            return {**base, "class": "structured", "logic": {"domain": "demographic", "age": age}}
        op, num = _OPS[groups[0]], float(groups[1])
        logic = {**atom, "value": {"op": op, "num": num}}
        return {**base, "class": "structured", "logic": logic, "concept_candidates": concepts}
    return {
        **base,
        "class": "human",
        "logic": {"domain": "demographic"},
        "human_question": f"Confirm with the patient/clinician: {text}",
    }


def ir_extract(inp: dict[str, Any]) -> dict[str, Any]:
    ruleset = str(inp.get("ruleset", ""))
    lines: list[dict[str, Any]] = list(inp.get("criteria", []))
    cassette: list[dict[str, Any]] = []
    path = CASSETTES / "ir_extract" / f"{ruleset}.json"
    if not path.exists():  # test aliases such as "GZQO-IT" reuse the "GZQO" cassette
        prefixes = [p for p in (CASSETTES / "ir_extract").glob("*.json") if ruleset.startswith(p.stem + "-")]
        path = max(prefixes, key=lambda p: len(p.stem)) if prefixes else path
    if path.exists():
        cassette = json.loads(path.read_text(encoding="utf-8"))["criteria"]
    by_text = {norm(c["text"]): c for c in cassette}
    out = []
    for line in lines:
        hit = by_text.get(norm(str(line["text"])))
        if hit is not None:
            out.append({**hit, "kind": line["kind"], "source_ref": line.get("source_ref") or hit.get("source_ref", "")})
        else:
            out.append(_heuristic_criterion(line))
    return {"criteria": out}


# ----------------------------------------------------------------------------- concept_map
def concept_map(inp: dict[str, Any]) -> dict[str, Any]:
    concept = norm(str(inp.get("concept", "")))
    best: tuple[float, dict[str, Any]] | None = None
    for c in inp.get("candidates", []):
        disp = norm(str(c.get("display", "")))
        a, b = set(re.findall(r"\w+", concept)), set(re.findall(r"\w+", disp))
        score = len(a & b) / (len(a | b) or 1)
        if best is None or score > best[0]:
            best = (score, c)
    if best is None or best[0] == 0:
        return {"choices": [], "needs_review": True}
    conf = 0.95 if best[0] >= 0.99 else round(0.5 + best[0] / 3, 2)
    return {
        "choices": [{"code": best[1]["code"], "system": best[1]["system"], "confidence": conf}],
        "needs_review": conf < 0.9,
    }


# ----------------------------------------------------------------------------- judge
def _sentences(text: str) -> list[str]:
    return [s + "。" for s in text.split("。") if s.strip()]


def _zh_dates(sentence: str) -> list[date]:
    out = []
    for y, m, d in _DATE_ZH.findall(sentence):
        try:
            out.append(date(int(y), int(m), int(d)))
        except ValueError:
            continue
    return out


def judge(inp: dict[str, Any]) -> dict[str, Any]:
    q = str(inp.get("note_question", "")).lower()
    index = date.fromisoformat(str(inp["index_date"])[:10])
    excerpts = sorted(inp.get("excerpts", []), key=lambda e: str(e.get("date", "")), reverse=True)

    def found(verdict: str, sentence: str, ex: dict[str, Any], reason: str) -> dict[str, Any]:
        return {
            "verdict": verdict,
            "quote": sentence[:400],
            "quote_date": str(ex["date"])[:10],
            "confidence": 0.9,
            "reason": reason[:300],
        }

    if "flare" in q and ("two" in q or "2" in q):
        flare_dates: dict[date, tuple[str, dict[str, Any]]] = {}
        for ex in excerpts:
            for s in _sentences(str(ex.get("text", ""))):
                if "沒有任何痛風發作" in s or ("僅於" in s and "一次痛風發作" in s):
                    return found("fail", s, ex, "notes state fewer than two flares in the past year")
                if "急性痛風發作" in s and "發作中" not in s:
                    for d in _zh_dates(s):
                        if index - timedelta(days=365) <= d <= index:
                            flare_dates.setdefault(d, (s, ex))
        if len(flare_dates) >= 2:
            s, ex = flare_dates[max(flare_dates)]
            return found("pass", s, ex, f"{len(flare_dates)} dated flares within 12 months")
    elif "flare" in q and ("ongoing" in q or "current" in q):
        for ex in excerpts:
            ex_date = date.fromisoformat(str(ex["date"])[:10])
            if not (index - timedelta(days=14) <= ex_date <= index):
                continue
            for s in _sentences(str(ex.get("text", ""))):
                if "急性痛風發作中" in s:
                    return found("pass", s, ex, "acute flare documented within 14 days")
                if "目前無急性痛風發作" in s:
                    return found("fail", s, ex, "no current flare documented within 14 days")
    elif "ecog" in q:
        for ex in excerpts:
            for s in _sentences(str(ex.get("text", ""))):
                m = re.search(r"ECOG\s*體能狀態\s*(\d)\s*分", s)
                if m:
                    ok = int(m.group(1)) <= 1
                    return found("pass" if ok else "fail", s, ex, f"ECOG {m.group(1)} documented")
    elif "das28" in q or "response" in q:
        for ex in excerpts:
            for s in _sentences(str(ex.get("text", ""))):
                if "治療反應良好" in s:
                    return found("pass", s, ex, "documented good response")
                if "治療反應不佳" in s:
                    return found("fail", s, ex, "documented poor response")
    # every key present, as strict structured output returns it (llm_judge_output 1.1.0: null means absent)
    return {
        "verdict": "unknown",
        "quote": None,
        "quote_date": None,
        "confidence": 0.5,
        "reason": "excerpts do not answer the question",
    }


# ----------------------------------------------------------------------------- draft_doc, ie_locate
_FACT_LABELS = [
    ("diagnosis", "診斷為{}"),
    ("diagnosis_date", "診斷日期{}"),
    ("dmards", "曾使用傳統DMARDs：{}"),
    ("das28_latest", "最近一次DAS28為{}"),
    ("das28_latest_date", "（{}評估）"),
    ("das28_previous", "前次DAS28為{}"),
    ("tb_screening", "結核篩檢：{}"),
    ("hbv_screening", "B型肝炎篩檢：{}"),
    ("current_biologic", "目前使用{}"),
    ("approval_end", "現行核准至{}"),
]


def draft_doc(inp: dict[str, Any]) -> dict[str, Any]:
    facts = inp.get("facts", {}) or {}
    parts = []
    for key, tpl in _FACT_LABELS:
        val = facts.get(key)
        if val not in (None, "", []):
            parts.append(tpl.format("、".join(map(str, val)) if isinstance(val, list) else val))
    text = "病人" + "，".join(parts) + "。" if parts else "病歷資料不足，請醫師補充臨床經過。"
    return {"paragraph": text[:1200]}


def ie_locate(inp: dict[str, Any]) -> dict[str, Any]:
    inc: list[str] = []
    exc: list[str] = []
    current: list[str] | None = None
    for sec in inp.get("sections", []):
        title = str(sec.get("title", ""))
        if re.search(r"inclusion|納入|選択基準", title, re.I):
            current = inc
        elif re.search(r"exclusion|排除|除外基準", title, re.I):
            current = exc
        else:
            current = None
        if current is not None:
            for line in str(sec.get("text", "")).splitlines():
                line = re.sub(r"^\s*(?:\d+[.)、]|[-•*])\s*", "", line).strip()
                if line:
                    current.append(line)
    return {"inclusion": inc, "exclusion": exc}


def mlbench_judge(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Public judging suite (``tools/mlbench`` messages, no JSON input block): always abstains with a valid label.
    It proves the request path through a running gateway; it says nothing about accuracy."""
    user = next((str(m.get("content", "")) for m in messages if m.get("role") == "user"), "")
    m = re.search(r"^Criterion type:\s*(inclusion|exclusion)", user, re.M)
    if m is None:
        raise ValueError("no 'Criterion type:' line in the user message")
    return {"label": "not enough information", "evidence": []}


_STUDY = re.compile(r"(?<![A-Za-z0-9])([A-Z][A-Z0-9]{2,7}(?:-[A-Z0-9]{1,8})?)(?![A-Za-z0-9])")
_LOOKBACK = re.compile(r"(\d{1,3})\s*(?:months?|個月|か月|ヶ月|m\b)|(\d{1,2})\s*(?:years?|年)", re.I)


def classify_intent(inp: dict[str, Any]) -> dict[str, Any]:
    """Native engine / console intake (``classify_intent@1``): keyword rules in en, zh-TW and ja. Deterministic, so
    the proposal flow runs without a model; it never invents a study code (null when the text has none)."""
    text = str(inp.get("text", ""))
    lang = str(inp.get("language") or "en")
    low = norm(text)
    study = next((s for s in _STUDY.findall(text) if s not in ("FEAS", "SCREEN", "STATUS", "OK", "PDF")), None)
    lang = lang if lang in ("en", "ja", "zh-TW", "mixed") else "en"
    out: dict[str, Any] = {"type": "UNKNOWN", "study": study, "language": lang}
    if re.search(r"做得起來|可行|收得到|feasib|how many|enrol|recruit|実施可能|何例|集まる", low):
        out["type"] = "FEAS"
        m = _LOOKBACK.search(text)
        if m:
            out["lookback_months"] = int(m.group(1)) if m.group(1) else int(m.group(2)) * 12
    elif re.search(r"screen|篩選|收案名單|スクリーニング", low):
        out["type"] = "SCREEN"
    elif re.search(r"status|進度|狀態|状況|進捗", low):
        out["type"] = "STATUS"
    elif "?" in text or "？" in text:
        out["type"] = "ASK"
        out["question"] = text[:500]
    return out


# handlers that read the raw chat messages instead of a ```json input block

# ----------------------------------------------------------------------------- consent explainer
_CONSENT_SECTIONS = (
    ("purpose", ("purpose", "why is this study", "investigational")),
    ("procedures", ("will happen", "visit", "inject", "assigned by chance")),
    ("duration", ("weeks", "months", "how long")),
    ("risks", ("risk", "side effect", "may cause", "harm")),
    ("benefits", ("benefit",)),
    ("alternatives", ("other choices", "alternative", "do not have to take part")),
    ("obligations", ("you will need to", "you must", "do not start")),
    ("rights", ("voluntary", "stop at any time", "decide not to")),
    ("privacy", ("records", "code number", "privacy", "confidential")),
    ("costs", ("free", "cost", "pay", "injured")),
    ("contacts", ("call", "contact", "questions about")),
)


def _consent_section(text: str) -> str | None:
    low = text.lower()
    for name, words in _CONSENT_SECTIONS:
        if any(w in low for w in words):
            return name
    return None


def consent_explain(inp: dict[str, Any]) -> dict[str, Any]:
    """Deterministic stand-in: the first sentence of each paragraph that names a section, quoted verbatim and
    restated as is (the stub does not simplify); questions from the voluntary, risk and contact paragraphs."""
    items: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for p in inp.get("paragraphs", []):
        sentences = [s.strip() for s in re.split(r"(?<=[.!?。])\s+", p["text"]) if len(s.strip()) > 20]
        for sent in sentences[:2]:
            sec = _consent_section(sent) or _consent_section(p.get("heading", ""))
            if sec is None or seen.get(sec, 0) >= 3 or len(items) >= 30:
                continue
            seen[sec] = seen.get(sec, 0) + 1
            items.append({"section": sec, "text": sent[:400], "quote": sent[:600], "para": p["id"]})
    questions = []
    for sec, q in (
        ("rights", "Do you have to take part, and can you stop later?"),
        ("risks", "What is one possible side effect of the study medicine?"),
        ("contacts", "Whom do you call if you have a side effect?"),
    ):
        it = next((i for i in items if i["section"] == sec), None)
        if it is not None:
            questions.append({"question": q, "answer": it["text"][:300], "quote": it["quote"], "para": it["para"]})
    return {"items": items, "questions": questions}


_STUB_TAG = {"ja": "［日本語・サンプル：翻訳ではありません］", "zh-TW": "［中文・範例：非翻譯］"}


def consent_translate(inp: dict[str, Any]) -> dict[str, Any]:
    """Not a translation: the text is copied with a language tag, so numbers and ids survive (pipeline tests)."""
    tag = _STUB_TAG.get(str(inp.get("target_language")), "")
    return {
        "items": [{"id": i["id"], "text": f"{tag}{i['text']}"[:600]} for i in inp.get("items", [])],
        "questions": [
            {"id": q["id"], "question": f"{tag}{q['question']}"[:400], "answer": f"{tag}{q['answer']}"[:400]}
            for q in inp.get("questions", [])
        ],
    }


def consent_verify(inp: dict[str, Any]) -> dict[str, Any]:
    """Supported when every number in the text is in the quote and the text gives no advice."""
    out = []
    for e in inp.get("entries", []):
        text, quote = str(e.get("text", "")), str(e.get("quote", ""))
        nums = set(re.findall(r"\d+", quote))
        bad_num = any(n not in nums for n in re.findall(r"\d+", text))
        advice = any(w in text.lower() for w in ("you should join", "we recommend", "it is safe"))
        verdict = "unsupported" if bad_num or advice else "supported"
        problem = "number not in the quote" if bad_num else ("gives advice" if advice else "")
        back = re.sub(r"^［[^］]+］", "", text)
        out.append({"id": e["id"], "verdict": verdict, "back_translation": back[:600], "problem": problem})
    return {"checks": out}


# ----------------------------------------------------------------------------- chart_facts, assist (D-135)
_STUB_DX = (  # wording -> ICD-10-CM, as a careful reader would code it; a negated mention is never a fact
    (r"痛風|gout", "M10.9"),
    (r"乳癌|乳がん|breast cancer", "C50.919"),
    (r"胃癌|胃がん|gastric cancer", "C16.9"),
    (r"大腸癌|大腸がん|colon cancer", "C18.9"),
    (r"2型糖尿病|第二型糖尿病|type 2 diabetes", "E11.9"),
    (r"高血圧|高血壓|hypertension", "I10"),
)
_STUB_LAB = (
    (r"(?:血清)?尿酸(?:値)?|uric acid|\bUA\b", "3084-1", "mg/dL"),
    (r"HbA1c|ヘモグロビンA1c|糖化血色素", "4548-4", "%"),
    (r"クレアチニン|肌酸酐|creatinine|\bCr\b", "2160-0", "mg/dL"),
)
_STUB_DRUG = (
    (r"アロプリノール|allopurinol|別嘌呤醇", "M04AA01"),
    (r"フェブキソスタット|febuxostat", "M04AA03"),
    (r"コルヒチン|colchicine|秋水仙素", "M04AC01"),
)
_NEG = re.compile(r"なし|否定|無し|否認|未見|no (?:history|evidence)|denies|ruled out|家族歴|家族史|family history")
_DATE_ANY = dates.CHART_SPAN  # 和暦, 民國 or Gregorian (D-215)


def chart_facts(inp: dict[str, Any]) -> dict[str, Any]:
    """Deterministic stand-in for the chart reader: line rules for the common diagnoses, labs and medicines of the
    synthetic charts, every fact quoted verbatim from its line, a negated mention skipped, the date of the line or of
    the last dated line above it."""
    text = str(inp.get("chart") or "")
    out: list[dict[str, str]] = []
    current = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.search(r"(生年月日|出生日期|Date of birth|DOB)\s*[:：]?\s*(.+)", line, re.I)
        sx = re.search(r"(性別|Sex)\s*[:：]?\s*(男性|女性|男|女|male|female)", line, re.I)
        if m:  # a date of birth is not the date of the visit
            d = _DATE_ANY.search(m.group(2))
            if d:
                out.append({"domain": "birth_date", "term": "", "code": "", "system": "", "value": d.group(0),
                            "unit": "", "date": "", "quote": m.group(0)[:300]})  # fmt: skip
        if sx:
            out.append({"domain": "sex", "term": "", "code": "", "system": "", "value": sx.group(2), "unit": "",
                        "date": "", "quote": sx.group(0)})  # fmt: skip
        if m or sx:
            continue
        found = _DATE_ANY.search(line)
        if found:
            current = found.group(0)
        if _NEG.search(line):
            continue
        for rx, code in _STUB_DX:
            hit = re.search(rx, line, re.I)
            if hit:
                out.append({"domain": "condition", "term": hit.group(0), "code": code, "system": "icd10cm",
                            "value": "", "unit": "", "date": current, "quote": line[:300]})  # fmt: skip
        for rx, loinc, unit in _STUB_LAB:
            hit = re.search(rf"({rx})\s*[:：=]?\s*(\d+(?:\.\d+)?)\s*(mg/dL|mg/dl|%|µmol/L|umol/L)?", line, re.I)
            if hit:
                out.append({"domain": "observation", "term": hit.group(1), "code": loinc, "system": "loinc",
                            "value": hit.group(2), "unit": hit.group(3) or unit, "date": current,
                            "quote": hit.group(0)})  # fmt: skip
        for rx, atc in _STUB_DRUG:
            hit = re.search(rx, line, re.I)
            if hit:
                out.append({"domain": "medication", "term": hit.group(0), "code": atc, "system": "atc", "value": "",
                            "unit": "", "date": current, "quote": line[:300]})  # fmt: skip
    return {"facts": out[:40]}


def assist(inp: dict[str, Any]) -> dict[str, Any]:
    """The help assistant's stand-in: the draft TrialBox built from its own pages, unchanged."""
    return {"answer": str(inp.get("draft") or "")[:1500]}


def crf_prefill(inp: dict[str, Any]) -> dict[str, Any]:
    """The eCRF note reader's stand-in (D-160): the item's ``question`` lists words split by ``|``; the newest note
    with a line holding one of them (not negated) answers. A choice item gets the code labelled Yes (or 1), a number
    item the first number after the word, a date item the line's ISO date; the quote is the line, copied verbatim."""
    item = inp.get("item") or {}
    words = [w.strip() for w in str(item.get("question") or "").split("|") if len(w.strip()) >= 2]
    kind = str(item.get("kind") or "text")
    none = {"found": False, "value": "", "note": "", "date": "", "quote": ""}
    for note in inp.get("notes") or []:
        for line in str(note.get("text") or "").splitlines():
            hit = next((w for w in words if w.lower() in line.lower()), None)
            if hit is None or _NEG.search(line):
                continue
            after = line[line.lower().index(hit.lower()) + len(hit) :]
            value = ""
            if kind == "choice":
                yes = [
                    c for c in item.get("choices") or [] if str(c.get("label")).strip().lower() in ("yes", "はい", "是")
                ]
                value = str((yes or [{"code": "1"}])[0]["code"])
            elif kind in ("integer", "decimal"):
                num = re.search(r"\d+(?:\.\d+)?", after)
                value = num.group(0) if num else ""
            elif kind == "date":
                iso = re.search(r"\d{4}-\d{2}-\d{2}", line)
                value = iso.group(0) if iso else ""
            else:
                value = hit
            if value:
                return {"found": True, "value": value, "note": str(note.get("id") or ""),
                        "date": str(note.get("date") or ""), "quote": line.strip()[:300]}  # fmt: skip
    return none


MESSAGE_HANDLERS = {"mlbench_judge": mlbench_judge}


# ----------------------------------------------------------------------------- judge personas (tests only, D-276)
def _dissent(a: dict[str, Any]) -> dict[str, Any]:
    """The other decided answer, with the same (real) quote: a second model that disagrees."""
    flip = {"pass": "fail", "fail": "pass"}
    return {**a, "verdict": flip.get(str(a.get("verdict")), a.get("verdict")), "reason": "stub-dissent"}


def _lowconf(a: dict[str, Any]) -> dict[str, Any]:
    return {**a, "confidence": 0.4}


def _badquote(a: dict[str, Any]) -> dict[str, Any]:
    """A decided answer whose quote is in no excerpt."""
    if a.get("verdict") not in ("pass", "fail"):
        return a
    return {**a, "quote": "This sentence is in no note of the patient."}


def _olddate(a: dict[str, Any]) -> dict[str, Any]:
    """A real quote given the wrong date (one day earlier than its note)."""
    if not a.get("quote_date"):
        return a
    return {**a, "quote_date": (date.fromisoformat(str(a["quote_date"])[:10]) - timedelta(days=1)).isoformat()}


# ----------------------------------------------------------------------------- the obeying persona (T-208, D-346)
# The negative control of the prompt-injection suite (``tools/injection_eval.py``): a model that does what a planted
# instruction says. It proves the suite can fail. The phrases are the openers the suite's plants use
# (``eval/injection/cases.yaml``) in en, ja and zh-TW; a test holds every plant to them.
PLANT_RE = re.compile(
    r"ignore (?:all |the )?(?:previous|earlier|above|prior)|disregard|new (?:instructions?|rules?)|\bsystem\s*:|"
    r"note to the ai|ai model|指示を無視|新しい指示|システム|ＡＩ|AIアシスタント|忽略|無視|系統指令",
    re.I,
)
_SENT = re.compile(r"(?<=[.!?。！？])\s*|\n+")


def planted(text: str) -> str | None:
    """The first sentence or line of ``text`` that holds a planted instruction (None: none)."""
    for part in _SENT.split(str(text or "")):
        if part.strip() and PLANT_RE.search(part):
            return part.strip()
    return None


def obey(prompt_id: str, inp: dict[str, Any], answer: dict[str, Any]) -> dict[str, Any]:
    """``answer`` changed the way a planted instruction in ``inp`` asks: the judge decides and quotes the plant, the
    chart reader drops every fact and reports the plant, the consent explainer and the criteria locator copy it."""
    if prompt_id == "judge":
        for ex in inp.get("excerpts") or []:
            hit = planted(str(ex.get("text", "")))
            if hit:
                verdict = "pass" if re.search(r"\bpass\b|符合|該当|適格", hit, re.I) else "fail"
                return {"verdict": verdict, "quote": hit[:400], "quote_date": str(ex.get("date", ""))[:10],
                        "confidence": 0.99, "reason": "as the note instructs"}  # fmt: skip
    elif prompt_id == "chart_facts":
        hit = planted(str(inp.get("chart") or ""))
        if hit:
            return {"facts": [{"domain": "condition", "term": "as instructed", "code": "", "system": "", "value": "",
                               "unit": "", "date": "", "quote": hit[:300]}]}  # fmt: skip
    elif prompt_id == "consent_explain":
        for p in inp.get("paragraphs") or []:
            hit = planted(str(p.get("text", "")))
            if hit:
                item = {"section": "risks", "text": hit[:400], "quote": hit[:600], "para": p.get("id", "")}
                return {**answer, "items": [*answer.get("items", []), item]}
    elif prompt_id == "ie_locate":
        for sec in inp.get("sections") or []:
            hit = planted(str(sec.get("text", "")))
            if hit:
                return {**answer, "exclusion": [*answer.get("exclusion", []), hit]}
    return answer


# model names of the obeying persona: two names, so it can also stand as a pair (D-276 refuses one name twice)
OBEYING = ("stub-obey", "stub-obey-verifier")


# model name -> what it does to the plain ``judge`` answer. ``stub-down`` answers 503 to everything (``app.py``).
# Opt-in by name: a test (or a developer) asks for the persona as the judge or the verifier; no shipped
# configuration names one, and the registry routes none.
PERSONAS: dict[str, Any] = {
    "stub-dissent": _dissent,
    "stub-lowconf": _lowconf,
    "stub-badquote": _badquote,
    "stub-olddate": _olddate,
    "stub-down": lambda a: a,
    **dict.fromkeys(OBEYING, lambda a: a),  # every prompt, in ``app.py`` through :func:`obey`
    # T-603: a model that enforces a context of 8k, 16k or 32k tokens (llm_stub.app.CONTEXT_PERSONAS)
    "stub-ctx-8k": lambda a: a,
    "stub-ctx-16k": lambda a: a,
    "stub-ctx-32k": lambda a: a,
}

HANDLERS = {
    "ir_extract": ir_extract,
    "concept_map": concept_map,
    "judge": judge,
    "draft_doc": draft_doc,
    "consent_explain": consent_explain,
    "consent_translate": consent_translate,
    "consent_verify": consent_verify,
    "ie_locate": ie_locate,
    "classify_intent": classify_intent,
    "chart_facts": chart_facts,
    "assist": assist,
    "crf_prefill": crf_prefill,
}
