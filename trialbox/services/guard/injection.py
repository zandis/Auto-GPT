"""The planted-instruction screen (T-606, D-359; review LLM-034 (b)).

A cheap, deterministic check that runs before text from a record or a document reaches a model: it flags sentences
written as an instruction **to the model** (en, ja, zh-TW). It does not flag clinical orders written to a patient or a
colleague ("stop alcohol", "ignore the old diet sheet", "investigators must ignore values older than 90 days"): each
pattern needs a cue that the reader addressed is a model (instructions, prompt, system, AI, assistant, a verdict or
JSON to output), not only an imperative verb.

Kinds (stable codes; results carry codes, counts and offsets, never the matched text):

* ``override``: "ignore all previous instructions", 以前の指示を無視, 忽略以上指示;
* ``addressed``: text addressed to a model ("note to the AI", AIアシスタントへの指示, 給AI的指示, "you are now");
* ``role``: a line that claims to be a system or administrator turn (``SYSTEM:``, ``## system``, chat-template tags);
* ``output``: an order about the model's answer (answer fail, return an empty list, 判定は pass, 回傳空白清單);
* ``fence``: a Markdown code fence, which would close a prompt's data block;
* ``json``: an answer object written into the text (``{"verdict": …``).

The screen is measured by the injection suite (``eval/injection/cases.yaml``): it must flag every attack plant and no
control plant, base text or synthetic note (``tests/unit/test_injection_hardening.py``). What a flag does is the
caller's: the document parser warns and the approval page marks the row (D-359); the note judge never takes a quote
from a flagged span as evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_EN_PREV = r"(?:previous|prior|earlier|above|preceding|foregoing|original|initial|system|your|all|any|the|these|those)"
_EN_OBJ = r"(?:instructions?|prompts?|rules?|directions?|guidelines?|commands?|directives?|system\s+prompt)"
_MODEL = r"(?:ai|a\.i\.|assistant|chatbot|llm|language\s+model|ai\s+model|the\s+model|model)"


def _p(kind: str, *parts: str, flags: int = 0) -> tuple[str, re.Pattern[str]]:
    return kind, re.compile("".join(parts), flags)


_I = re.I
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # ------------------------------------------------------------------ override
    _p(
        "override",
        r"\b(?:ignore|disregard|forget|override|bypass)\s+",
        rf"(?:{_EN_PREV}\s+){{0,3}}{_EN_OBJ}\b",
        flags=_I,
    ),
    _p("override", r"\b(?:ignore|disregard|forget)\s+(?:all\s+|everything\s+|the\s+)?(?:above|foregoing)\b", flags=_I),
    _p("override", r"(?:指示|指令|命令|プロンプト|ルール|設定)(?:を|は|も)?(?:全て|すべて|一切)?(?:無視|忘れ)"),
    _p(
        "override",
        r"(?:忽略|無視|无视|忽視|不要理會)(?:之前|以上|先前|前面|上述|上面|以前|所有|全部|前述)",
        r"[^。！？\n]{0,6}(?:指示|指令|規則|规则|提示|說明|命令)",
    ),
    # ------------------------------------------------------------------ addressed to a model
    _p(
        "addressed",
        r"\b(?:note|message|instructions?|memo|reminder)\s+(?:to|for)\s+(?:the\s+|any\s+)?",
        _MODEL,
        r"\b",
        flags=_I,
    ),
    _p("addressed", r"\bnew\s+(?:instructions?|system\s+prompt|directives?)\b|\bnew\s+rules\s*[:：]", flags=_I),
    _p("addressed", r"\b(?:you\s+are\s+now|from\s+now\s+on\s+you|as\s+an?\s+(?:ai|language\s+model))\b", flags=_I),
    _p(
        "addressed",
        r"(?:AI|ＡＩ|アシスタント|モデル|チャットボット)(?:への|に対する|に対して)[^。\n]{0,8}(?:指示|命令)",
    ),
    _p("addressed", r"新しい(?:指示|命令|ルール)|新たな指示"),
    _p(
        "addressed", r"(?:給|對|致)\s*(?:AI|ＡＩ|人工智慧|人工智能|模型|助理|機器人)[^。\n]{0,6}(?:指示|指令|說明|訊息)"
    ),
    _p("addressed", r"新的?(?:指示|指令|規則)(?:如下|[:：])"),
    # ------------------------------------------------------------------ a system or assistant turn
    _p("role", r"(?:^|(?<=[\n。.!?]))\s*(?:\[\s*)?(?:system|assistant|developer)(?:\s*\])?\s*[:：]", flags=_I),
    _p("role", r"^\s*#{1,6}\s*(?:system|assistant|user)\s*$", flags=_I | re.M),
    _p("role", r"<\|?(?:im_start|im_end|system|endoftext)\|?>|\[/?INST\]|<<\s*/?SYS\s*>>", flags=_I),
    _p("role", r"システム(?:管理者|指示|プロンプト|メッセージ)|系統(?:指令|指示|提示|訊息|管理員)|系统(?:指令|提示)"),
    # ------------------------------------------------------------------ an order about the answer
    _p(
        "output",
        r"\b(?:answer|respond|reply|output|return|mark|set|report|classify)\b[^.\n]{0,30}",
        r"(?:\bverdict\b|\bconfidence\b|\bjson\b|\b(?:pass|fail)\b(?=[\s.,;)]|$)|\bempty\s+(?:list|array)\b|",
        r"\b(?:no|zero)\s+(?:facts|criteria|diagnoses)\b)",
        flags=_I,
    ),
    _p("output", r"\bthe\s+verdict\s+(?:for\s+this\s+patient\s+)?(?:is|must\s+be|should\s+be)\b", flags=_I),
    _p(
        "output",
        r"判定は[^。\n]{0,6}(?:pass|fail|適格|不適格|該当|非該当)|",
        r"と(?:回答|答え|出力|報告|返)(?:して|しなさい|せよ|すること|ろ)|出力しないで|(?:空の|空白の)(?:リスト|配列)|確信度は",
    ),
    _p(
        "output",
        r"(?:回答|輸出|输出|回傳|回传|答案)\s*(?:一律|都|皆)?\s*(?:為|为|是)?\s*(?:pass|fail|空白|空的|空|JSON)|",
        r"不要輸出|不要输出|一律為|答案一律",
        flags=_I,
    ),
    # ------------------------------------------------------------------ prompt syntax
    _p("fence", r"```|~~~"),
    _p("json", r"\{\s*\"(?:verdict|confidence|facts|inclusion|exclusion|items|quote|answer)\"\s*:", flags=_I),
)


@dataclass(frozen=True)
class Flag:
    kind: str
    start: int
    end: int


@dataclass(frozen=True)
class Screen:
    """The screen's verdict on one text: ``hit`` when any pattern matched; kinds, count and spans, never the text."""

    hit: bool
    kinds: tuple[str, ...] = ()
    count: int = 0
    spans: list[Flag] = field(default_factory=list)

    def covers(self, start: int, end: int) -> bool:
        """True when ``[start, end)`` overlaps a flagged span."""
        return any(f.start < end and start < f.end for f in self.spans)


def screen(text: str) -> Screen:
    """Flag the sentences of ``text`` written as an instruction to a model (module rules)."""
    text = str(text or "")
    if not text:
        return Screen(False)
    found: list[Flag] = []
    for kind, rx in PATTERNS:
        found.extend(Flag(kind, m.start(), max(m.end(), m.start() + 1)) for m in rx.finditer(text))
    if not found:
        return Screen(False)
    found.sort(key=lambda f: (f.start, f.end))
    return Screen(True, tuple(sorted({f.kind for f in found})), len(found), found)


_SENTENCE_END = re.compile(r"[.!?。！？]\s*|\n")


def sentence_spans(text: str, s: Screen) -> list[tuple[int, int]]:
    """Each flagged span widened to its whole sentence (or line): the part of the text that is the instruction."""
    out: list[tuple[int, int]] = []
    for f in s.spans:
        start = 0
        for m in _SENTENCE_END.finditer(text, 0, f.start):
            start = m.end()
        stop = _SENTENCE_END.search(text, f.end)
        end = stop.end() if stop else len(text)
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def planted_in(text: str, quote: str) -> bool:
    """True when ``quote`` (whitespace-normalised) lies inside a flagged sentence of ``text``: an instruction found in
    a record is never the evidence for an answer."""
    q = " ".join(str(quote or "").split())
    if not q:
        return False
    s = screen(text)
    if not s.hit:
        return False
    for a, b in sentence_spans(text, s):
        part = " ".join(text[a:b].split())
        if q in part or (part and part in q):
            return True
    return False
