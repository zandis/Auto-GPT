"""Whether a criterion's line may negate the concept its coded logic asks the presence of (card 10A-1).

"No prior chemotherapy" (an inclusion) compiled to "any of chemotherapy" is met only by the patients it should
exclude. :func:`negated_presence` says whether such an inclusion must go to a person.

**The rule fails safe.** An inclusion whose logic asks the presence of a concept is held when its line carries ANY
negation cue that is not explained. A cue is explained only when it is shown to be about something else:

* a bound on a value ("no more than 2", "not greater than 1.5 mg/dL", "超えない", "以上でない", "無…大於") or another
  phrase that negates nothing ("no longer", "non-small cell", "無法", "未満"): these are blanked before reading;
* a cue followed, before the concept, by a word it negates instead ("not *responded* to chemotherapy", "no
  *restriction* on", "化学療法後に*増悪*が認められない", "未經治療*的*晚期肺癌");
* a cue that clearly governs another concept the line names, and not this one.

The scope reading (ConText's: a cue before the concept, or after it for "not allowed", "なし", "未曾…", in the same
clause and within a few words; Harkema H, Dowling JN, Thornblade T, Chapman WW. ConText: an algorithm for determining
negation, experiencer, and temporal status from clinical reports. J Biomed Inform 2009;42(5):839-51) serves only to
let a line RUN, by showing its cue is about something else; it never decides that a negated line is safe. A line
that cannot be read either way is held: holding costs a person's look, running can exclude the patients the line
should keep. An atom that compares a value, counts, takes the latest result, or carries a derived value, a change or
an aggregate asks a measure, not a presence, and is never held.

**Sources of the cue words.** Adapted from medspaCy 1.3.1's ConText rules (``resources/en/context_rules.json``;
https://pypi.org/project/medspacy/1.3.1/, sdist sha256
976599d9446e98018b311951cfa926be5a59d0c140967b828fe98bc4bada40fe), all of category NEGATED_EXISTENCE in that file:

* direction FORWARD: absence of, clear of, decline (declined, declines, declining), deny (denied, denies, denying),
  free of, lack of, lacked (lacking), negative for, never (from "never had" / "never developed"), no, not (n't),
  rather than, ruled out, to exclude, with no, without;
* direction BACKWARD: free, has been negative, was negative (is, are), ": none", ": no", are not evident, negative,
  unlikely, now resolved;
* direction TERMINATE: apart from, aside from, secondary (to), and the rule whose literal is "but", whose pattern
  lists but, however, nevertheless, still, except, though, although, yet.

This project's own: the criterion-line forms ("must not", "has not been <done>", "has never been <done>", "not
allowed / permitted / eligible", "ineligible", "prohibited", "-naive", "naive to", "ex-smoker", "abstinent from",
"non-pregnant", "untreated", "other than", "unless", "whereas", "provided"), every bound and blocking word, the word
windows, and all Japanese and Chinese cues. The licence of the adapted words:

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

(Register row ``context-negation-cues``; NOTICE section 3.)
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable

from tb_contracts import Atom, BoolExpr

_SPAN = 300  # characters read round a mention or a cue: a long line costs linear time, never quadratic

# ---------------------------------------------------------------------------------------------------- English cues
_EN_FORWARD = (
    r"absence\s+of|clear\s+of|declin\w*|den(?:y|ies|ied|ying)|free\s+(?:of|from)|lack(?:ed|s|ing)?(?:\s+of)?|"
    r"negative\s+for|never|rather\s+than|ruled?\s+out|to\s+exclude|with\s+no|without|none(?:\s+of)?|neither|nor|"
    r"no|not|[a-z]+n['’]t|cannot|na[iï]ve\s+(?:to|for|with\s+respect\s+to)|abstinen\w*\s+from|exclud\w*"
)
_PARTICIPLE = r"[a-z]+(?:ed|en|wn|ne|ht)"  # administered, given, shown, done, brought
_EN_BACKWARD = (
    r"(?:is|are|was|were|has\s+been|have\s+been)?\s*(?:not\s+(?:been\s+)?(?:allowed|permitted|acceptable|"
    r"eligible|administered|given|received|used|performed|done|present|evident|reported)|ineligible|prohibited|"
    r"excluded|negative|unlikely|resolved)"
    rf"|(?:has|have|had|must|should|may|is|are|was|were)\s+(?:not|never)\s+(?:have\s+)?(?:been\s+)?{_PARTICIPLE}"
    r"|[-–:]\s*(?:none|no|absent|negative)\b|[- ]na[iï]ve|[- ]free\b"
)
_EN_TERMINATE = (
    r"\b(?:but|however|nevertheless|still|except|though|although|yet|apart\s+from|aside\s+from|other\s+than|"
    r"secondary\s+to|unless|whereas|provided)\b"
)
# a word the cue negates instead of the concept after it ("not responded to chemotherapy")
_EN_BLOCK = (
    r"\b(?:respon\w*|tolera\w*|candidate|amenable|suitable|restrict\w*|limit\w*|requir\w*|able|progress\w*|"
    r"benefit\w*|controlled|adequate\w*|fit|willing|plan\w*|longer|change|increase|decrease|heal\w*|conceiv\w*|"
    r"improv\w*|recover\w*)\b"
)
_EN_PSEUDO = (
    r"\b(?:no|not|never)\s+(?:more|greater|less|fewer|higher|lower|longer|older|younger|earlier|later|above|below|"
    r"over|under|exceed\w*|in\s+excess|beyond|until|before|after|only|change|increase|decrease|restriction\w*|"
    r"upper|lower|minimum|maximum)\b|\bnon[- ]?(?:small|hodgkin\w*|invasive|muscle|squamous|alcoholic|"
    r"insulin|steroid\w*|melanoma)\b|\bgram[- ]negative\b|\bnot\s+specified\b|\bnot\s+applicable\b|"
    r"\bnone\s+other\b|\bnevertheless\b"
)
# a cue inside the concept word itself ("non-pregnant", "nonsmoker", "untreated", "ex-smoker")
_EN_PREFIX = r"(?:non-?|un|ex-)"
_EN_PREFIXED = (
    r"\b(?:non-?(?:pregnan|lactat|breast-?feed|smok|drink|user|respond)|un(?:treated|exposed|vaccinated|diagnosed)|"
    r"ex-?(?:smok|drink|user))\w*"
)
_EN_WINDOW = 6  # words between a cue and its concept (NegEx's window is five)

# ----------------------------------------------------------------------------------------------- Japanese cues (own)
_JA_BACKWARD = (
    r"な[しいく]|無[しいく]|ません|おらず|せず|認めず|認めない|否定|除外|ではない|でない|ゼロ|"
    r"未(?:施行|実施|投与|治療|経験|使用|受診)|ナイーブ|禁煙|禁酒|断酒"
)
_JA_FORWARD = r"未|非|無"  # "未治療", "非妊娠", "無治療": a prefix right before the concept
_JA_TERMINATE = r"ただし|但し|除き|を除く|以外"
_JA_BLOCK = r"増悪|進行|奏効|効果|反応|改善|適応|耐容|忍容|コントロール|制御|再発"
_JA_PSEUDO = (
    r"(?:を)?超えない|超えず|以上でない|以下でない|未満でない|を上回らない|を下回らない|未満|少ない|問わない|"
    r"限らない|に関わらず|かかわらず|制限(?:は)?なし|制限(?:は)?ない|上限(?:は)?なし|上限(?:は)?ない|非常|未来|未知|"
    r"無作為|無料"
)
# ------------------------------------------------------------------------------------------------ Chinese cues (own)
_ZH_FORWARD = (
    r"從未|从未|未曾|不曾|尚未|並未|并未|須未|须未|必須未|必须未|沒有|没有|沒|没|無|无|不得|不可|不能|不應|不应|"
    r"否認|否认|排除|未|非|免於|免于"
)
_ZH_BACKWARD = r"未曾|從未|从未|未|沒有|没有|不曾|陰性|阴性"
_ZH_TERMINATE = r"但|但是|除了|除外|然而|惟|唯|以外"
_ZH_BLOCK = r"惡化|恶化|進展|进展|反應|反应|效果|改善|控制|耐受|復發|复发"
_ZH_PSEUDO = (
    r"(?:無|无|不|未|沒有|没有)[^，,。；;、]{0,12}?(?:大於|小於|高於|低於|超過|多於|少於|大于|小于|高于|低于|超过|"
    r"多于|少于|以上|以下)|無法|无法|無論|无论|無關|无关|未滿|未满|不限|無上限|无上限|無年齡上限|无年龄上限|"
    r"非小細胞|非小细胞|非何杰金|非霍奇金|非常|未來|未来"
)
_CJK_WINDOW = 8  # characters between a cue and its concept
_CJK_BOUNDARY = r"[、。，,；;（）()「」\[\]【】\n]"  # a colon is not a boundary here ("化學治療:未曾接受")
_EN_BOUNDARY = r"[,;.()\[\]{}\n]"

_FLAGS = re.I
_EN_FWD = re.compile(rf"\b(?:{_EN_FORWARD})\b", _FLAGS)
_EN_BWD_ANY = re.compile(rf"(?:{_EN_BACKWARD})", _FLAGS)
_EN_PRE = re.compile(_EN_PREFIXED, _FLAGS)
_EN_TERM = re.compile(_EN_TERMINATE, _FLAGS)
_EN_BLK = re.compile(_EN_BLOCK, _FLAGS)
_EN_PS = re.compile(_EN_PSEUDO, _FLAGS)
_JA_BWD = re.compile(_JA_BACKWARD)
_JA_FWD_END = re.compile(rf"(?:{_JA_FORWARD})$")
_JA_FWD = re.compile(_JA_FORWARD)
_JA_TERM = re.compile(_JA_TERMINATE)
_JA_BLK = re.compile(_JA_BLOCK)
_JA_PS = re.compile(_JA_PSEUDO)
_ZH_FWD = re.compile(_ZH_FORWARD)
_ZH_BWD_AT = re.compile(rf"^[\s:：]*(?:{_ZH_BACKWARD})")
_ZH_BWD = re.compile(_ZH_BACKWARD)
_ZH_TERM = re.compile(_ZH_TERMINATE)
_ZH_BLK = re.compile(_ZH_BLOCK)
_ZH_PS = re.compile(_ZH_PSEUDO)
_CJK_B = re.compile(_CJK_BOUNDARY)
_EN_B = re.compile(_EN_BOUNDARY)
_KANA = re.compile(r"[぀-ヿ]")
_CJK = re.compile(r"[぀-ヿ㐀-鿿]")
_WORD = re.compile(r"[A-Za-z0-9]+(?:['’][a-z]+)?")
_ABBREV = re.compile(r"^\s*[（(][^（）()]{1,20}[）)]")  # "結核(TB)の既往がない": an abbreviation after the concept
_SUFFIX = re.compile(r"(?:ations?|atory|ancies|ancy|ants?|ments?|ions?|ies|ing|ers|er|ed|es|s|y)$")

Mention = tuple[int, int, bool]


def _blank(text: str, pattern: re.Pattern[str]) -> str:
    """``text`` with every match of ``pattern`` replaced by spaces of its length (offsets stay put)."""
    return pattern.sub(lambda m: " " * len(m.group(0)), text)


def _prepare(text: str) -> str:
    t = unicodedata.normalize("NFKC", text)
    return _blank(_blank(_blank(t, _EN_PS), _JA_PS), _ZH_PS)


def _stem(word: str) -> str:
    w = word.lower()
    s = _SUFFIX.sub("", w)
    return s if len(s) >= 4 else w


def _term_pattern(term: str) -> re.Pattern[str] | None:
    """A concept name or synonym as a pattern over a line: CJK as written; Latin words by their stems, each word
    allowed a suffix, with an optional "non-", "un" or "ex-" before the first (captured as group ``neg``)."""
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


def _patterns(terms: Iterable[str]) -> list[re.Pattern[str]]:
    seen: dict[str, re.Pattern[str]] = {}
    for x in terms:
        key = unicodedata.normalize("NFKC", x).strip().lower()
        if key and key not in seen and (p := _term_pattern(x)) is not None:
            seen[key] = p
    return list(seen.values())


def _mentions(text: str, pats: list[re.Pattern[str]]) -> list[Mention]:
    """Where the concept is named in the line: ``(start, end, carries "non-"/"un"/"ex-")``."""
    out: list[Mention] = []
    for pat in pats:
        for m in pat.finditer(text):
            out.append((m.start(), m.end(), bool(m.groupdict().get("neg"))))
    return sorted(out)


def _first(pats: list[re.Pattern[str]], s: str) -> int | None:
    """The offset of the first mention in ``s`` of one of ``pats``, or None."""
    hits = [m.start() for p in pats if (m := p.search(s))]
    return min(hits) if hits else None


def _term_re(cjk: bool, ja: bool) -> re.Pattern[str]:
    return (_JA_TERM if ja else _ZH_TERM) if cjk else _EN_TERM


def _clause_after(text: str, i: int, cjk: bool, ja: bool = False) -> str:
    s = (_CJK_B if cjk else _EN_B).split(text[i : i + _SPAN])[0]
    return _term_re(cjk, ja).split(s)[0]


def _clause_before(text: str, i: int, cjk: bool, ja: bool = False) -> str:
    s = (_CJK_B if cjk else _EN_B).split(text[max(0, i - _SPAN) : i])[-1]
    return _term_re(cjk, ja).split(s)[-1]


def _abbrev_len(text: str, e: int) -> int:
    m = _ABBREV.match(text[e : e + 30])
    return m.end() if m else 0


# ------------------------------------------------------------------------- the scope reading (a cue on the concept)
def _en_governed(text: str, s: int, e: int, others: list[re.Pattern[str]]) -> bool:
    before = _clause_before(text, s, cjk=False)
    for cue in _EN_FWD.finditer(before):
        gap = before[cue.end() :]
        if len(_WORD.findall(gap)) <= _EN_WINDOW and not _EN_BLK.search(gap) and _first(others, gap) is None:
            return True
    after = _clause_after(text, e + _abbrev_len(text, e), cjk=False)
    for m in _EN_BWD_ANY.finditer(after):
        gap = after[: m.start()]
        said = gap + m.group(0)  # "has not responded": the cue's own words say what it negates
        if len(_WORD.findall(gap)) <= 3 and not _EN_BLK.search(said) and _first(others, gap) is None:
            return True
    return False


def _cjk_governed(text: str, s: int, e: int, others: list[re.Pattern[str]], ja: bool) -> bool:
    before = _clause_before(text, s, cjk=True, ja=ja)
    after = _clause_after(text, e + _abbrev_len(text, e), cjk=True, ja=ja)
    if ja:
        if _JA_FWD_END.search(before):  # "未治療": a prefix right before the concept
            return True
        m = _JA_BWD.search(after)  # "化学療法の治療歴がない": a few characters later, nothing else negated between
        if m is None:
            return False
        gap = after[: m.start()]
        return not _JA_BLK.search(gap) and _first(others, gap) is None
    for cue in _ZH_FWD.finditer(before):
        gap = before[cue.end() :]
        if len(gap) <= _CJK_WINDOW and not re.search(r"[的之]", gap) and _first(others, gap) is None:
            return True
    return _ZH_BWD_AT.match(after) is not None


def _others(terms: Iterable[str], other_terms: Iterable[str]) -> list[re.Pattern[str]]:
    mine = {unicodedata.normalize("NFKC", x).strip().lower() for x in terms}
    return _patterns(x for x in other_terms if unicodedata.normalize("NFKC", x).strip().lower() not in mine)


def governed(text: str, terms: Iterable[str], other_terms: Iterable[str] = ()) -> bool | None:
    """True when a negation cue in ``text`` reads as governing a mention of one of ``terms``; False when the line
    names the concept and no cue reads that way; None when the line never names it. ``other_terms`` name the line's
    other concepts: a cue with one of them between it and this concept governs that one."""
    terms = list(terms)
    own = _patterns(terms)
    others = _others(terms, other_terms)
    t = _prepare(text)
    found = _mentions(t, own)
    if not found:
        return None
    ja = bool(_KANA.search(t))
    for s, e, neg in found:
        if neg:
            return True
        if _CJK.search(t[max(0, s - 1) : e + 1]):
            if _cjk_governed(t, s, e, others, ja):
                return True
        elif _en_governed(t, s, e, others):
            return True
    return False


# ----------------------------------------------------------------------------- the fail-safe (an unexplained cue)
def _explained_forward(after: str, own: list[re.Pattern[str]], others: list[re.Pattern[str]], cjk: bool) -> bool:
    """A forward cue is explained when what it reaches, before this concept, is a word it negates instead or another
    named concept."""
    stop = _first(own, after)
    head = after if stop is None else after[:stop]
    if cjk:
        if re.search(r"[的之]", head[:6]):  # "未經治療的晚期肺癌": the cue negates the modifier 的 closes
            return True
        return bool(_ZH_BLK.search(head) or _JA_BLK.search(head)) or _first(others, head) is not None
    near = " ".join(_WORD.findall(head)[: _EN_WINDOW + 1])
    return bool(_EN_BLK.search(near)) or _first(others, near) is not None


def _explained_backward(
    before: str, cue: str, after: str, own: list[re.Pattern[str]], others: list[re.Pattern[str]], cjk: bool
) -> bool:
    """A backward cue is explained when, between this concept (or the clause's start) and the cue, the line names
    another concept or a word the cue negates instead ("化学療法後に増悪が認められない"), or when the cue's own words
    say what it negates ("has not *responded*", "未見*惡化*", "未受*控制*")."""
    last = [m.end() for p in own for m in p.finditer(before)]
    tail = before[max(last) :] if last else before
    if cjk:
        said = cue + after[:4]
        if _JA_BLK.search(said) or _ZH_BLK.search(said):
            return True
        return bool(_JA_BLK.search(tail) or _ZH_BLK.search(tail)) or _first(others, tail) is not None
    if _EN_BLK.search(cue):
        return True
    near = " ".join(_WORD.findall(tail)[-4:])
    return bool(_EN_BLK.search(near)) or _first(others, near) is not None


def unexplained_cue(text: str, terms: Iterable[str], other_terms: Iterable[str] = ()) -> bool:
    """Whether the line carries a negation cue that is not shown to be about something other than this concept."""
    terms = list(terms)
    own = _patterns(terms)
    others = _others(terms, other_terms)
    t = _prepare(text)
    for m in _EN_FWD.finditer(t):
        if not _explained_forward(_clause_after(t, m.end(), cjk=False), own, others, cjk=False):
            return True
    for m in _EN_BWD_ANY.finditer(t):
        before = _clause_before(t, m.start(), cjk=False)
        if not _explained_backward(before, m.group(0), "", own, others, cjk=False):
            return True
    found = _mentions(t, own)
    for m in _EN_PRE.finditer(t):
        # "Nonsmokers with asthma": the prefixed word negates itself; it is about something else only when this
        # concept is named elsewhere in the line, outside that word
        inside = any(s < m.end() and m.start() < e for s, e, _ in found)
        if inside or not found:
            return True
    japanese = bool(_KANA.search(t))
    if japanese:
        for m in _JA_BWD.finditer(t):
            before, after = _clause_before(t, m.start(), True, True), _clause_after(t, m.end(), True, True)
            if not _explained_backward(before, m.group(0), after, own, others, cjk=True):
                return True
        for m in _JA_FWD.finditer(t):
            if not _explained_forward(_clause_after(t, m.end(), True, True), own, others, cjk=True):
                return True
        return False
    for m in _ZH_FWD.finditer(t):
        if not _explained_forward(_clause_after(t, m.end(), cjk=True), own, others, cjk=True):
            return True
    for m in _ZH_BWD.finditer(t):
        before, after = _clause_before(t, m.start(), cjk=True), _clause_after(t, m.end(), cjk=True)
        if not before.strip():  # at the clause's start it is a forward cue, read above
            continue
        if not _explained_backward(before, m.group(0), after, own, others, cjk=True):
            return True
    return False


# ----------------------------------------------------------------------------------------------------- the logic
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


def negated_presence(
    text: str, logic: object, terms_for: Callable[[str], list[str]], other_terms: Iterable[str] = ()
) -> bool:
    """Whether an inclusion's ``logic`` asks the presence of a concept its ``text`` may negate (card 10A-1): a cue
    reads as governing the concept, or any cue in the line is left unexplained (the fail-safe above).
    ``terms_for(valueset)`` gives a concept's names and synonyms (its ValueSet slug is added); ``other_terms`` are the
    line's other named concepts (its concept candidates)."""
    every = [x for a in atoms_of(logic) for x in (*terms_for(a.valueset or ""), *_slug_words(a.valueset))]
    every += list(other_terms)
    for atom in presence_atoms(logic):
        terms = [*terms_for(atom.valueset or ""), *_slug_words(atom.valueset)]
        if governed(text, terms, every) or unexplained_cue(text, terms, every):
            return True
    return False
