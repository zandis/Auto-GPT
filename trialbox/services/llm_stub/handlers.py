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
    elif "das28" in q or "response" in q:
        for ex in excerpts:
            for s in _sentences(str(ex.get("text", ""))):
                if "治療反應良好" in s:
                    return found("pass", s, ex, "documented good response")
                if "治療反應不佳" in s:
                    return found("fail", s, ex, "documented poor response")
    return {"verdict": "unknown", "confidence": 0.5, "reason": "excerpts do not answer the question"}


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


HANDLERS = {
    "ir_extract": ir_extract,
    "concept_map": concept_map,
    "judge": judge,
    "draft_doc": draft_doc,
    "ie_locate": ie_locate,
}
