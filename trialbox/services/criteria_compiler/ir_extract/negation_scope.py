"""Whether a negation in a criterion's line governs the concept its coded logic asks for (card 10A-1).

"No prior chemotherapy" (an inclusion) compiled to "any of chemotherapy" is met only by the patients it should
exclude. :func:`negated_presence` says whether a negation cue in the line governs one of the concepts the logic asks
the presence of: the concept's own name or a synonym is found in the line and a cue stands before it (or after it, for
the backward cues) inside its scope, the way ConText reads a clinical sentence (Harkema H, Dowling JN, Thornblade T,
Chapman WW. ConText: an algorithm for determining negation, experiencer, and temporal status from clinical reports.
J Biomed Inform 2009;42(5):839-51). When the line never names the concept, the rule cannot tell and says yes when the
line holds any cue: holding a line costs a person's look, running it can exclude the patients it should keep.

* A cue's scope ends at a clause boundary (a comma, a semicolon, a full stop, a bracket; 、。，；), at a terminating
  word ("but", "except", "however"; ただし; 但, 除了) and after a few words (six in English, eight characters in
  Japanese and Chinese). A word that the cue really negates ("not responded to chemotherapy", "no restriction on
  prior chemotherapy") ends the scope too.
* A bound is not a negation: "no more than 2 prior lines", "not greater than 1.5 mg/dL", "超えない", "以上でない",
  "無…大於". These phrases are blanked before the cues are read, as are "no longer", "無法" (unable), "未満" (under).
* A morphological negation ("non-pregnant", "nonsmoker", "untreated") governs the concept it is part of.

The English cues are adapted from medspaCy 1.3.1's ConText rules (``resources/en/context_rules.json``, categories
NEGATED_EXISTENCE and TERMINATE; https://pypi.org/project/medspacy/1.3.1/, sdist sha256
976599d9446e98018b311951cfa926be5a59d0c140967b828fe98bc4bada40fe), themselves from pyConText and NegEx. Copied as
plain words, cut to the cues a criterion line uses, and grouped into regular expressions here. Their licence:

    MIT License. Copyright (c) 2020 medspacy. Permission is hereby granted, free of charge, to any person obtaining
    a copy of this software and associated documentation files (the "Software"), to deal in the Software without
    restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute,
    sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do
    so, subject to the following conditions: The above copyright notice and this permission notice shall be included
    in all copies or substantial portions of the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY
    KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
    PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
    CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR
    IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

The criterion-line cues added to them ("must not", "has not been", "not allowed", "prohibited", "-naive"), the bounds
and the Japanese and Chinese cues are this project's own (register row ``context-negation-cues``).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable

from tb_contracts import Atom, BoolExpr

# ---------------------------------------------------------------------------------------------------- English cues
# forward: the cue stands before the concept. ConText's NEGATED_EXISTENCE forward rules a criterion line can carry
# (absence of, clear of, decline, deny, free of, lack of, lacked, negative for, never had, no, no evidence, not,
# rather than, ruled out, to exclude, with no, without, without any evidence of, was not, patient was not), then the
# criterion forms ("must not", "has not been", "have never", "none of", "neither", "cannot have")
_EN_FORWARD = (
    r"absence\s+of|clear\s+of|declin\w*|den(?:y|ies|ied|ying)|free\s+(?:of|from)|lack(?:ed|s|ing)?(?:\s+of)?|"
    r"negative\s+for|never|rather\s+than|ruled?\s+out|to\s+exclude|with\s+no|without|none(?:\s+of)?|neither|nor|"
    r"no|not|[a-z]+n['’]t|cannot"
)
# backward: the cue follows the concept. ConText's backward rules (free, has been negative, was negative, : none,
# : no, are not evident, negative on, no longer present, now resolved, unlikely) and the criterion forms
_EN_BACKWARD = (
    r"(?:is|are|was|were|has\s+been|have\s+been)?\s*(?:not\s+(?:been\s+)?(?:allowed|permitted|acceptable|"
    r"administered|given|received|used|performed|done|present|evident|reported)|prohibited|excluded|negative|"
    r"unlikely|resolved)|[-–:]\s*(?:none|no|absent|negative)\b|[- ]na[iï]ve|[- ]free\b"
)
# TERMINATE in ConText (but, however, nevertheless, still, except, though, although, yet, apart from, aside from,
# as well as any, other possibilities of, secondary, cause for, source for, origin for, trigger event for)
_EN_TERMINATE = (
    r"\b(?:but|however|nevertheless|still|except|though|although|yet|apart\s+from|aside\s+from|other\s+than|"
    r"secondary\s+to|unless|whereas|provided)\b"
)
# a word the cue negates instead of the concept after it ("not responded to chemotherapy")
_EN_BLOCK = (
    r"\b(?:respon\w*|tolera\w*|candidate|amenable|eligible|suitable|restrict\w*|limit\w*|requir\w*|able|"
    r"progress\w*|benefit\w*|controlled|adequate\w*|fit|willing|plan\w*|longer|change|increase|decrease)\b"
)
# bounds and other negation words that negate nothing ("no more than 2", "not greater than 1.5", "no longer")
_EN_PSEUDO = (
    r"\b(?:no|not|never)\s+(?:more|greater|less|fewer|higher|lower|longer|older|younger|earlier|later|above|below|"
    r"over|under|exceed\w*|in\s+excess|beyond|until|before|after|only|change|increase|decrease|restriction\w*|"
    r"upper|lower|minimum|maximum)\b|\bnon[- ]?(?:small|hodgkin\w*|invasive|muscle|squamous|alcoholic|"
    r"insulin|steroid\w*|melanoma)\b|\bgram[- ]negative\b|\bnot\s+specified\b|\bnot\s+applicable\b"
)
_EN_PREFIX = r"(?:non-?|un)"  # "non-pregnant", "nonsmoker", "untreated": the concept word carries the negation
_EN_WINDOW = 6  # words between a cue and its concept (NegEx's window is five)

# ----------------------------------------------------------------------------------------------- Japanese cues (own)
# backward: the predicate follows the concept ("化学療法歴なし", "化学療法を受けていない", "化学療法を受けておらず")
_JA_BACKWARD = (
    r"な[しいく]|無[しいく]|ません|おらず|せず|認めず|認めない|否定|除外|ではない|でない|"
    r"未(?:施行|実施|投与|治療|経験|使用|受診)|ナイーブ"
)
_JA_FORWARD = r"未|非|無"  # "未治療", "非妊娠", "無治療": a prefix before the concept
_JA_TERMINATE = r"ただし|但し|除き|を除く|以外"
# bounds: "超えない", "以上でない", "以下でない", "未満" (under), "少ない" (few), "問わない" (regardless), "限らない"
_JA_PSEUDO = (
    r"(?:を)?超えない|超えず|以上でない|以下でない|未満でない|を上回らない|を下回らない|未満|少ない|問わない|"
    r"限らない|に関わらず|かかわらず|制限(?:は)?なし|制限(?:は)?ない|上限(?:は)?なし|上限(?:は)?ない"
)
# ------------------------------------------------------------------------------------------------ Chinese cues (own)
_ZH_FORWARD = (
    r"從未|从未|未曾|不曾|尚未|並未|并未|須未|须未|必須未|必须未|沒有|没有|沒|没|無|无|不得|不可|不能|不應|不应|"
    r"否認|否认|排除|未|非|免於|免于"
)
_ZH_BACKWARD = r"未曾|從未|从未|未|沒有|没有|不曾|陰性|阴性"
_ZH_TERMINATE = r"但|但是|除了|除外|然而|惟|唯|以外"
_ZH_PSEUDO = (
    r"(?:無|无|不|未|沒有|没有)[^，,。；;、]{0,12}?(?:大於|小於|高於|低於|超過|多於|少於|大于|小于|高于|低于|超过|"
    r"多于|少于|以上|以下)|無法|无法|無論|无论|無關|无关|未滿|未满|不限|無上限|无上限|無年齡上限|无年龄上限|"
    r"非小細胞|非小细胞|非何杰金|非霍奇金"
)
_CJK_WINDOW = 8  # characters between a cue and its concept
_CJK_BOUNDARY = r"[、。，,；;：:（）()「」\[\]【】\n]"
_EN_BOUNDARY = r"[,;.()\[\]{}\n]"

_FLAGS = re.I
_EN_FWD = re.compile(rf"\b(?:{_EN_FORWARD})\b", _FLAGS)
_EN_BWD = re.compile(rf"^\s*(?:{_EN_BACKWARD})", _FLAGS)
_EN_TERM = re.compile(_EN_TERMINATE, _FLAGS)
_EN_BLK = re.compile(_EN_BLOCK, _FLAGS)
_EN_PS = re.compile(_EN_PSEUDO, _FLAGS)
_JA_BWD = re.compile(rf"(?:{_JA_BACKWARD})")
_JA_FWD = re.compile(rf"(?:{_JA_FORWARD})$")
_JA_TERM = re.compile(_JA_TERMINATE)
_JA_PS = re.compile(_JA_PSEUDO)
_ZH_FWD = re.compile(rf"(?:{_ZH_FORWARD})")
_ZH_BWD = re.compile(rf"^(?:{_ZH_BACKWARD})")
_ZH_TERM = re.compile(_ZH_TERMINATE)
_ZH_PS = re.compile(_ZH_PSEUDO)
_CJK_B = re.compile(_CJK_BOUNDARY)
_EN_B = re.compile(_EN_BOUNDARY)
_KANA = re.compile(r"[぀-ヿ]")
_CJK = re.compile(r"[぀-ヿ㐀-鿿]")
_WORD = re.compile(r"[A-Za-z0-9]+(?:['’][a-z]+)?")
# any cue at all, for a line that never names its concept
_EN_PREFIXED = r"\b(?:non-?(?:pregnan|lactat|breast-?feed|smok|drink|user)|un(?:treated|exposed|vaccinated))"
_ANY_CUE = (_EN_FWD, re.compile(rf"(?:{_EN_BACKWARD})", _FLAGS), re.compile(_EN_PREFIXED, _FLAGS),
            re.compile(_JA_BACKWARD), re.compile(_ZH_FORWARD))  # fmt: skip
_SUFFIX = re.compile(r"(?:ations?|atory|ancies|ancy|ants?|ments?|ions?|ies|ing|ers|er|ed|es|s|y)$")


def _blank(text: str, pattern: re.Pattern[str]) -> str:
    """``text`` with every match of ``pattern`` replaced by spaces of its length (offsets stay put)."""
    return pattern.sub(lambda m: " " * len(m.group(0)), text)


def _stem(word: str) -> str:
    w = word.lower()
    s = _SUFFIX.sub("", w)
    return s if len(s) >= 4 else w


def _term_pattern(term: str) -> re.Pattern[str] | None:
    """A concept name or synonym as a pattern over a line: CJK as written; Latin words by their stems, each word
    allowed a suffix, with an optional "non-" or "un" before the first (captured as group ``neg``)."""
    t = unicodedata.normalize("NFKC", term).strip()
    if not t:
        return None
    if _CJK.search(t):
        return re.compile(re.escape(t))
    words = _WORD.findall(t)
    if not words:
        return None
    body = r"[\s\-/]+".join(re.escape(_stem(w)) + r"[a-z]*" for w in words)
    return re.compile(rf"(?<![A-Za-z])(?P<neg>{_EN_PREFIX})?{body}(?![A-Za-z])", _FLAGS)


def _mentions(text: str, terms: Iterable[str]) -> list[tuple[int, int, bool]]:
    """Where the concept is named in the line: ``(start, end, carries "non-"/"un")``."""
    out: list[tuple[int, int, bool]] = []
    for term in terms:
        pat = _term_pattern(term)
        if pat is None:
            continue
        for m in pat.finditer(text):
            out.append((m.start(), m.end(), bool(m.groupdict().get("neg"))))
    return out


def _en_governed(text: str, s: int, e: int, others: list[re.Pattern[str]]) -> bool:
    before = _EN_B.split(text[:s])[-1]
    before = _EN_TERM.split(before)[-1]
    for cue in _EN_FWD.finditer(before):
        gap = before[cue.end() :]
        if len(_WORD.findall(gap)) <= _EN_WINDOW and not _EN_BLK.search(gap) and not _other(gap, others):
            return True
    after = _EN_B.split(text[e:])[0]
    after = _EN_TERM.split(after)[0]
    # a backward cue right after the concept, or after a few words ("Chemotherapy has not been administered")
    for i in range(0, min(len(after), 40) + 1):
        if (i == 0 or not after[i - 1].isalpha()) and _EN_BWD.match(after[i:]):
            return len(_WORD.findall(after[:i])) <= 3
    return False


def _other(gap: str, others: list[re.Pattern[str]]) -> bool:
    """Whether another concept of the line is named between a cue and this one: the cue governs that one."""
    return any(p.search(gap) for p in others)


def _cjk_governed(text: str, s: int, e: int, others: list[re.Pattern[str]]) -> bool:
    before = _CJK_B.split(text[:s])[-1]
    after = _CJK_B.split(text[e:])[0]
    japanese = bool(_KANA.search(text))
    if japanese:
        before = _JA_TERM.split(before)[-1]
        after = _JA_TERM.split(after)[0]
        if _JA_FWD.search(before):  # "未治療": a prefix right before the concept
            return True
        m = _JA_BWD.search(after)  # "化学療法の治療歴がない": a few characters later, no other concept between
        return m is not None and m.start() <= _CJK_WINDOW + 4 and not _other(after[: m.start()], others)
    before = _ZH_TERM.split(before)[-1]
    after = _ZH_TERM.split(after)[0]
    for cue in _ZH_FWD.finditer(before):
        gap = before[cue.end() :]
        # "未經治療的晚期肺癌": the cue negates a modifier that 的 / 之 closes, not the concept after it
        if len(gap) <= _CJK_WINDOW and not re.search(r"[的之]", gap) and not _other(gap, others):
            return True
    return bool(_ZH_BWD.match(after.lstrip()))


def governed(text: str, terms: Iterable[str], other_terms: Iterable[str] = ()) -> bool | None:
    """True when a negation cue in ``text`` governs a mention of one of ``terms``; False when the line names the
    concept and no cue governs it; None when the line never names it. ``other_terms`` name the line's other concepts:
    a cue with one of them between it and this concept governs that one."""
    own = {unicodedata.normalize("NFKC", x).strip().lower() for x in terms}
    others = [p for x in other_terms if x.strip().lower() not in own and (p := _term_pattern(x)) is not None]
    t = unicodedata.normalize("NFKC", text)
    t = _blank(_blank(_blank(t, _EN_PS), _JA_PS), _ZH_PS)
    found = _mentions(t, terms)
    if not found:
        return None
    for s, e, neg in found:
        if neg:
            return True
        if _CJK.search(t[max(0, s - 1) : e + 1]):
            if _cjk_governed(t, s, e, others):
                return True
        elif _en_governed(t, s, e, others):
            return True
    return False


def any_cue(text: str) -> bool:
    """Whether the line carries any negation cue at all, bounds and the like left out."""
    t = unicodedata.normalize("NFKC", text)
    t = _blank(_blank(_blank(t, _EN_PS), _JA_PS), _ZH_PS)
    return any(p.search(t) for p in _ANY_CUE)


def presence_atoms(logic: object, negated: bool = False) -> list[Atom]:
    """The atoms a logic asks the presence of: an atom other than an age or a sex whose quantifier is ``any``,
    ``all`` or unset, under an even number of ``not`` (an atom ``none of`` under a ``not`` too). An atom that compares
    a value, counts, takes the latest result, or carries a derived value, a change or an aggregate asks a measure, not
    a presence ("No ALT above 2 x ULN" as ``latest ALT <= 2 x ULN`` is right as it is)."""
    if isinstance(logic, BoolExpr):
        flip = negated != (logic.op == "not")
        return [a for arg in logic.args for a in presence_atoms(arg, flip)]
    if not isinstance(logic, Atom) or logic.domain == "demographic":
        return []
    measured = logic.quantifier in ("latest", "count>=") or any(
        getattr(logic, f, None) is not None for f in ("value", "value_if", "derived", "change", "aggregate", "count")
    )  # read by name: the IR's later atom (tb_contracts.criterion_ir) adds value_if, change and aggregate
    if measured:
        return []
    return [logic] if (logic.quantifier == "none") == negated else []


def atoms_of(logic: object) -> list[Atom]:
    if isinstance(logic, BoolExpr):
        return [a for arg in logic.args for a in atoms_of(arg)]
    return [logic] if isinstance(logic, Atom) and logic.domain != "demographic" else []


def _slug_words(valueset: str | None) -> list[str]:
    """``VS_CARDIOPULMONARY_DISEASE`` -> ``cardiopulmonary disease`` (a hashed CJK slug gives nothing)."""
    if not valueset or valueset == "NONE":
        return []
    body = re.sub(r"^VS_", "", valueset)
    body = re.sub(r"_[0-9A-F]{8}$", "", body)
    words = [w for w in body.split("_") if w and not w.isdigit()]
    return [" ".join(words).lower()] if words else []


def negated_presence(text: str, logic: object, terms_for: Callable[[str], list[str]]) -> bool:
    """Whether an inclusion's ``logic`` asks the presence of a concept its ``text`` negates (card 10A-1).
    ``terms_for(valueset)`` gives the concept's names and synonyms; the ValueSet's slug is added to them. A concept
    the line never names holds the line when the line carries any cue."""
    every = [x for a in atoms_of(logic) for x in (*terms_for(a.valueset or ""), *_slug_words(a.valueset))]
    for atom in presence_atoms(logic):
        terms = [*terms_for(atom.valueset or ""), *_slug_words(atom.valueset)]
        hit = governed(text, terms, every)
        if hit or (hit is None and any_cue(text)):
            return True
    return False
