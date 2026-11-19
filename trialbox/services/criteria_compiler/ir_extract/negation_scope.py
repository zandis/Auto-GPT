"""Whether a criterion's line may negate the concept its coded logic asks the presence of (card 10A-1).

"No prior chemotherapy" (an inclusion) compiled to "any of chemotherapy" is met only by the patients it should
exclude. :func:`negated_presence` says whether such an inclusion must go to a person.

**The rule fails safe.** An inclusion whose logic asks the presence of a concept is held when its line carries ANY
negation cue that is not explained. A cue is explained only when it is shown to be about something else:

* a bound on a value ("no more than 2", "not greater than 1.5 mg/dL", "超えない", "以上でない", "無…大於") or another
  phrase that negates nothing ("no longer", "non-small cell", "無法", "未満"): these are blanked before reading;
* a cue followed, before the concept, by a word it negates instead ("not *responded* to chemotherapy", "no
  *restriction* on", "化学療法後に*増悪*が認められない", "未經治療*的*晚期肺癌");
* a cue that clearly governs another concept the line names, and not this one: not when that concept is listed with
  this one under the cue ("no prior surgery or chemotherapy", "手術及び化学療法の治療歴がない": both negated);
* (card 10A-1b) a cue that governs another extracted concept in another clause: the cue and every mention of this
  concept are in clauses split by a coordinating boundary (";", a sentence end, "but", "however", が、, て、, 但, 且),
  no mention's clause carries a cue, goes on with a list or is this concept alone, and the cue's clause names
  another of the line's extracted concepts as what it negates. An object the extractor did not name never releases
  a cue: "no prior cytotoxic treatment", "化療", "抗悪性腫瘍薬" may be this concept by another name. When the cue's
  clause comes first the boundary must be adversative ("but", が、, 但). Anything less clear stays held.

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
allowed / permitted / eligible", "ineligible", "prohibited", card 10A-1b's "forbidden", "disallowed", "barred",
"precluded", "contraindicated", "not to be given", "must be avoided", "other than", "except", "-naive", "naive to",
"ex-smoker", "abstinent from", "non-pregnant", "untreated", "unless", "whereas", "provided"), every bound and
blocking word, the word windows, and all Japanese and Chinese cues. The licence of the adapted words:

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

import bisect
import re
import unicodedata
from collections.abc import Callable, Iterable

from tb_contracts import Atom, BoolExpr

_SPAN = 300  # characters read round a mention or a cue: a long line costs linear time, never quadratic

# ---------------------------------------------------------------------------------------------------- English cues
_EN_FORWARD = (
    r"absence\s+of|clear\s+of|declin\w*|den(?:y|ies|ied|ying)|free\s+(?:of|from)|lack(?:ed|s|ing)?(?:\s+of)?|"
    r"negative\s+for|never|rather\s+than|ruled?\s+out|to\s+exclude|with\s+no|without|none(?:\s+of)?|neither|nor|"
    r"no|not|[a-z]+n['’]t|cannot|na[iï]ve\s+(?:to|for|with\s+respect\s+to)|abstinen\w*\s+from|exclud\w*|"
    # card 10A-1b: a prohibition or an exception before the concept ("forbidden: X", "other than X", "except X")
    r"other\s+than|except(?:\s+for)?|contraindicat\w*|forbid\w*|prohibit\w*|disallow\w*|preclud\w*"
)
_PARTICIPLE = r"[a-z]+(?:ed|en|wn|ne|ht)"  # administered, given, shown, done, brought
_EN_BACKWARD = (
    r"(?:is|are|was|were|has\s+been|have\s+been)?\s*(?:not\s+(?:been\s+)?(?:allowed|permitted|acceptable|"
    r"eligible|administered|given|received|used|performed|done|present|evident|reported)|ineligible|prohibited|"
    r"forbidden|disallowed|barred|precluded|contraindicated|excluded|negative|unlikely|resolved)"
    rf"|not\s+to\s+be\s+{_PARTICIPLE}|(?:must|should|is|are|to)\s+be\s+avoided"
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
    r"insulin|steroid\w*|melanoma|metastatic|st[- ](?:segment[- ])?elevation|seminoma\w*|clear[- ]cell|"
    r"tuberculous|valvular|ischemic|ischaemic|obstructive|functioning|secretory|hereditary)\b|"
    r"\bgram[- ]negative\b|\bnot\s+(?:otherwise\s+)?specified\b|\bnot\s+elsewhere\s+classified\b|"
    r"\bnot\s+applicable\b|"
    r"\bnone\s+other\b|\bnevertheless\b|"
    r"\bno\.\s*\d|"  # "hospital No. 17": a number, not a negation (card 10A-1b)
    r"\bnot\s+(?:contraindicated|prohibited|forbidden|precluded|barred|disallowed)\b"  # a negated prohibition
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
    r"未(?:施行|実施|投与|治療|経験|使用|受診)|ナイーブ|禁煙|禁酒|断酒|"
    # card 10A-1b: a prohibition or an exception after the concept ("化学療法は不可", "禁止", "を除き", "以外")
    r"不可(?!欠|避)|禁止|禁忌|許可しない|許容しない|認められない|除き|を除く|以外"
)
_JA_FORWARD = r"未|非|無"  # "未治療", "非妊娠", "無治療": a prefix right before the concept
_JA_TERMINATE = r"ただし|但し|除き|を除く|以外"
_JA_BLOCK = r"増悪|進行|奏効|効果|反応|改善|適応|耐容|忍容|コントロール|制御|再発"
_JA_PSEUDO = (
    r"(?:を)?超えない|超えず|以上でない|以下でない|未満でない|を上回らない|を下回らない|未満|少ない|問わない|"
    r"限らない|に関わらず|かかわらず|制限(?:は)?なし|制限(?:は)?ない|上限(?:は)?なし|上限(?:は)?ない|非常|未来|未知|"
    r"無作為|無料|不可欠|不可避|禁止されていない|禁止しない|禁忌(?:は)?(?:なし|ない)|"
    # diagnosis names that only look negated ("非ホジキンリンパ腫", "無症状の胆石症"): descriptors, not negations
    r"非ホジキン|非小細胞|非アルコール性|非ST上昇|非浸潤|非扁平上皮|非転移|非結核性|非弁膜症性|非虚血性|非定型|"
    r"非代償性|非機能性|非遺伝性|無症状|無症候性|無症候"
)
# ------------------------------------------------------------------------------------------------ Chinese cues (own)
_ZH_FORWARD = (
    r"從未|从未|未曾|不曾|尚未|並未|并未|須未|须未|必須未|必须未|沒有|没有|沒|没|無|无|不得|不可|不能|不應|不应|"
    r"否認|否认|排除|未|非|免於|免于|"
    # card 10A-1b: a prohibition, or an exception ("除X外"; not 切除, 摘除 …)
    r"不允許|不允许|不准|禁止|禁用|禁忌|除了|(?<![切摘排去清割根免解移刪删])除(?=[^,，。;；]{1,12}外)"
)
_ZH_BACKWARD = r"未曾|從未|从未|未|沒有|没有|不曾|陰性|阴性|不允許|不允许|不准|禁止|禁忌|不可"
_ZH_TERMINATE = r"但|但是|除了|除外|然而|惟|唯|以外"
_ZH_BLOCK = r"惡化|恶化|進展|进展|反應|反应|效果|改善|控制|耐受|復發|复发"
_ZH_PSEUDO = (
    r"(?:無|无|不|未|沒有|没有)[^，,。；;、]{0,12}?(?:大於|小於|高於|低於|超過|多於|少於|大于|小于|高于|低于|超过|"
    r"多于|少于|以上|以下)|無法|无法|無論|无论|無關|无关|未滿|未满|不限|無上限|无上限|無年齡上限|无年龄上限|"
    r"非小細胞|非小细胞|非何杰金|非霍奇金|非常|未來|未来|"
    r"非酒精性|非ST段上升|非ST段抬高|非浸潤|非浸润|非鱗狀|非鳞状|非轉移|非转移|非結核|非结核|非瓣膜性|非缺血性|"
    r"非典型|非功能性|無症狀|无症状|不可或缺|未禁止|不禁止"
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
        if _JA_BUT.search(gap):  # "手術歴はあるが、…ない": an adversative が ends the reading (card 10A-1b); the
            return False  # fail-safe still reads that cue
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
# Card 10A-1b. "Another named concept" explains a cue only when it is not listed with this concept under that cue:
# "no prior surgery or chemotherapy", "手術及び化学療法の治療歴がない", "未曾接受手術或化學治療" negate both. The words
# that join a list (or that say the other concept is done with this one: "with", "including", "による") are filler.
_EN_FILLER = re.compile(
    r"^(?:[\s,;:/&()\-]|\b(?:or|and|nor|either|neither|any|other|prior|previous|of|the|a|an|with|by|using|including|"
    r"such|as|like|e\.g|i\.e|containing|both|plus)\b)*$",
    _FLAGS,
)
_CJK_FILLER = re.compile(
    r"^(?:[\s,;:、/・()\-]|及び|および|並びに|ならびに|または|又は|もしくは|若しくは|を含む|含む|による|などの|等の|"
    r"或是|或者|以及|包括|包含|例如|や|と|の|も|か|及|或|和|與|与|並|并|暨|跟|等|如)*$"
)
# the reach of a list: a comma or 、 does not end it, a semicolon followed by "or" / "and" does not either
_EN_LIST_END = re.compile(r";(?!\s*(?:or|and|nor)\b)|\.(?=\s|$)|\n", _FLAGS)
_CJK_LIST_END = re.compile(r"[。;\n]")
_EN_SENTENCE = re.compile(r"\.(?=\s|$)|\n")
_CJK_SENTENCE = re.compile(r"[。\n]")


def _list_after(text: str, i: int, cjk: bool, ja: bool) -> str:
    s = (_CJK_LIST_END if cjk else _EN_LIST_END).split(text[i : i + _SPAN])[0]
    return _term_re(cjk, ja).split(s)[0]


def _list_before(text: str, i: int, cjk: bool, ja: bool) -> str:
    """A backward cue's list reaches back to the sentence's start: "化学療法；放射線療法：なし" negates both."""
    s = (_CJK_SENTENCE if cjk else _EN_SENTENCE).split(text[max(0, i - _SPAN) : i])[-1]
    return _term_re(cjk, ja).split(s)[-1]


def _filler(s: str, cjk: bool) -> bool:
    return bool((_CJK_FILLER if cjk else _EN_FILLER).match(s))


def _listed_after(reach: str, own: list[re.Pattern[str]], others: list[re.Pattern[str]], cjk: bool) -> bool:
    """A forward cue's reach names another concept, then this one with only list words between: the cue governs
    both ("no prior surgery or chemotherapy", "diabetes, hypertension, or stroke")."""
    stop = _first(own, reach)
    if stop is None:
        return False
    ends = [m.end() for p in others for m in p.finditer(reach[:stop])]
    return bool(ends) and _filler(reach[max(ends) : stop], cjk)


def _listed_before(reach: str, own: list[re.Pattern[str]], others: list[re.Pattern[str]], cjk: bool) -> bool:
    """A backward cue's reach names this concept, then another with only list words between ("手術及び化学療法の
    治療歴がない", "chemotherapy and radiotherapy are not permitted")."""
    for p in own:
        for m in p.finditer(reach):
            starts = [o.start() for q in others for o in q.finditer(reach, m.end())]
            if starts and _filler(reach[m.end() : min(starts)], cjk):
                return True
    return False


def _explained_forward(
    after: str, own: list[re.Pattern[str]], others: list[re.Pattern[str]], cjk: bool, reach: str = ""
) -> bool:
    """A forward cue is explained when what it reaches, before this concept, is a word it negates instead or another
    named concept not listed with this one."""
    stop = _first(own, after)
    head = after if stop is None else after[:stop]
    if cjk:
        if re.search(r"[的之]", head[:6]):  # "未經治療的晚期肺癌": the cue negates the modifier 的 closes
            return True
        if _ZH_BLK.search(head) or _JA_BLK.search(head):
            return True
        return _first(others, head) is not None and not _listed_after(reach or after, own, others, cjk)
    near = " ".join(_WORD.findall(head)[: _EN_WINDOW + 1])
    if _EN_BLK.search(near):
        return True
    return _first(others, near) is not None and not _listed_after(reach or after, own, others, cjk)


def _explained_backward(
    before: str, cue: str, after: str, own: list[re.Pattern[str]], others: list[re.Pattern[str]], cjk: bool,
    reach: str = "",
) -> bool:  # fmt: skip
    """A backward cue is explained when, between this concept (or the clause's start) and the cue, the line names
    another concept not listed with this one, or a word the cue negates instead ("化学療法後に増悪が認められない"), or
    when the cue's own words say what it negates ("has not *responded*", "未見*惡化*", "未受*控制*")."""
    last = [m.end() for p in own for m in p.finditer(before)]
    tail = before[max(last) :] if last else before
    if cjk:
        said = cue + after[:4]
        if _JA_BLK.search(said) or _ZH_BLK.search(said):
            return True
        if _JA_BLK.search(tail) or _ZH_BLK.search(tail):
            return True
        return _first(others, tail) is not None and not _listed_before(reach or before, own, others, cjk)
    if _EN_BLK.search(cue):
        return True
    near = " ".join(_WORD.findall(tail)[-4:])
    if _EN_BLK.search(near):
        return True
    return _first(others, near) is not None and not _listed_before(reach or before, own, others, cjk)


# Card 10A-1b: a cue whose negated thing the line does not name as a concept ("Prior surgery is required; no prior
# radiotherapy", radiotherapy not a candidate) is about something else only when the structure says so without
# doubt: the cue and every mention of this concept are in different clauses split by a coordinating boundary, no
# mention's clause carries a cue, and the cue's clause has an object of its own. When this concept's clause comes
# first any such boundary will do (a cue never reaches back over one); when the cue's clause comes first the boundary
# must be adversative ("No chemotherapy, but prior surgery is required"), since a semicolon or 且 may go on with the
# cue's list. Anything less clear is "cannot tell", and the line stays held.
_EN_ADVERSATIVE = r"\b(?:but|however|whereas|although|though|yet)\b"
_JA_ADVERSATIVE = r"(?<=[るただいす])が(?![ぁ-ん])、?|けれども、?|けれど、?|ものの、?"
_ZH_ADVERSATIVE = r"但是|但|然而|惟|不過|不过|可是|卻|却"
_JA_BUT = re.compile(_JA_ADVERSATIVE)
_PLAIN = {
    "en": r";|\.(?=\s|$)|\n",
    "ja": r"[。;\n]|(?:[てで]|され|あり|おり)、",
    "zh": r"[。;\n]|並且|并且|而且|且",
}
_BOUNDS = {
    lang: re.compile(rf"(?P<adv>{adv})|(?:{_PLAIN[lang]})", _FLAGS)
    for lang, adv in (("en", _EN_ADVERSATIVE), ("ja", _JA_ADVERSATIVE), ("zh", _ZH_ADVERSATIVE))
}
_LIST_GOES_ON = {
    "en": re.compile(r"^[\s,]*(?:or|and|nor|and/or|plus|as\s+well\s+as)\b", _FLAGS),
    "ja": re.compile(r"^[\s,、]*(?:及び|および|並びに|ならびに|または|又は|もしくは|若しくは|や|と)"),
    "zh": re.compile(r"^[\s,、]*(?:及|或|和|與|与|以及|並|并|暨|或是|或者|跟)"),
}
_ANY_CUE = [_EN_FWD, _EN_BWD_ANY, _EN_PRE, _JA_BWD, _JA_FWD, _ZH_FWD, _ZH_BWD]
# an object of its own: a word that is not a function word, a time, a verb form, or a word that may take in this
# concept ("any treatment", "it", "such therapy", "任何形式之治療", "いずれも")
_EN_ANAPHOR = re.compile(
    r"\b(?:it|its|them|they|this|these|those|that|such|same|either|both|which|one|ones|above|aforementioned|said)\b",
    _FLAGS,
)
_EN_GENERIC = re.compile(
    r"^(?:treatments?|therap(?:y|ies)|drugs?|medications?|medicines?|agents?|regimens?|interventions?)$", _FLAGS
)
_EN_EMPTY = re.compile(
    r"^(?:a|an|the|any|other|prior|previous|of|to|for|with|in|on|at|by|from|within|before|after|during|since|until|"
    r"is|are|was|were|be|been|being|has|have|had|do|does|did|must|should|may|can|will|would|shall|could|might|not|no|"
    r"never|none|nor|or|and|history|evidence|use|time|times|day|days|week|weeks|month|months|year|years|hour|hours|"
    r"last|past|ago|enrolment|enrollment|entry|study|screening|randomisation|randomization|registration|consent|"
    r"baseline|start|dose|first|at|all|ever|again|more|less|longer|than|there|patient|patients|subject|subjects|"
    r"participant|participants|some|alone|line|lines|receive|receives|take|takes|took|use|uses|undergo|undergoes|"
    r"underwent|get|gets|got|start|starts|begin|began|give|gives|gave|need|needs|require|requires|allow|allows|"
    r"permit|permits|accept|accepts|complete|completes|continue|continues|stop|stops|discontinue|discontinues|"
    r"show|shows|experience|experiences|develop|develops|meet|meets|perform|administer|prescribe|try|tried|"
    r"initiate|initiates|qualify|qualifies|exist|exists|occur|occurs|[a-z]+ly|[a-z]+(?:ed|en|wn|ne|ht)|"
    r"\d+(?:[.,]\d+)?)$",
    _FLAGS,
)
_EN_ADVERBIAL = re.compile(
    r"^\s*(?:within|before|after|during|since|until|till|at|in|for|from|by|as|beyond|while|when|if|unless|except|earlier|"
    r"later|again|previously|ever|yet|more|less|longer|than|\d)\b",
    _FLAGS,
)
_CJK_ANAPHOR = re.compile(
    r"それ|これ|その|この|当該|上記|前記|いずれ|どちら|双方|両方|其|此|該|该|上述|前述|兩者|两者|皆|均|都|同"
)
_CJK_EMPTY = re.compile(
    r"[぀-ゟ]|[0-9０-９]|接受|使用|服用|投与|施行|実施|経験|認め|伴わ|伴う|有する|發生|发生|發現|发现|出現|出现|患有|罹患|"
    r"任何|形式|方式|種類|种类|治療|治疗|藥物|药物|薬剤|病史|既往|過去|过去|最終|最近|期間|期间|以内|以內|以前|以後|以后|"
    r"か月|ヶ月|カ月|時間|[曾過过有之的於于經经歴史週月年日天前後后内內患薬]"
)
_CJK_WORD = re.compile(r"[㐀-鿿ァ-ヿA-Za-z]{2,}")


class _Structure:
    """The clauses of a line and where this concept is named in them, read once per line (card 10A-1b)."""

    def __init__(self, t: str, found: list[Mention], lang: str, others: list[re.Pattern[str]]) -> None:
        self.lang, self.cjk, self.others = lang, lang != "en", others
        self.starts, self.ends, self.adv = [0], [], []
        for m in _BOUNDS[lang].finditer(t):
            self.ends.append(m.start())
            self.adv.append(m.group("adv") is not None)
            self.starts.append(m.end())
        self.ends.append(len(t))
        self.adv.append(False)
        self.own: set[int] = set()
        self.ok = bool(found)  # the line must name this concept, in clauses that carry no cue
        for s, e, neg in found:
            k = self.at(s)
            self.own.add(k)
            if neg or self.at(e - 1) != k:
                self.ok = False
        for k in self.own:
            clause = t[self.starts[k] : self.ends[k]]
            if any(p.search(clause) for p in _ANY_CUE) or _LIST_GOES_ON[lang].match(clause):
                self.ok = False
            bare = list(
                clause
            )  # a clause that is this concept alone is an item of a list ("化学療法；放射線療法：なし")
            for s, e, _ in found:
                if self.starts[k] <= s and e <= self.ends[k]:
                    bare[s - self.starts[k] : e - self.starts[k]] = " " * (e - s)
            if _filler("".join(bare).strip(" .。"), self.cjk):
                self.ok = False
        self.last = max(self.own, default=-1)

    def at(self, i: int) -> int:
        return max(0, bisect.bisect_right(self.starts, i) - 1)


def _has_object(
    clause: str, cue_start: int, cue_end: int, forward: bool, cjk: bool, others: list[re.Pattern[str]]
) -> bool:
    """The cue's clause names, as what it negates (after a forward cue, before a backward one), another concept the
    extractor emitted for the line. An object it does not name may be this concept under another name ("no prior
    cytotoxic treatment", "化療", "抗悪性腫瘍薬"): never enough. Nor is a clause that may take this concept in ("it",
    "any treatment", "任何形式之治療")."""
    side = clause[cue_end:] if forward else clause[:cue_start]
    if cjk:
        if _CJK_ANAPHOR.search(clause):
            return False
        return _CJK_WORD.search(_CJK_EMPTY.sub(" ", side)) is not None and _first(others, side) is not None
    if _EN_ANAPHOR.search(clause) or (forward and _EN_ADVERBIAL.match(side)):
        return False
    words = _WORD.findall(side)
    for i, w in enumerate(words):  # "any other treatment" may take in this concept; "biologic therapy" does not
        if _EN_GENERIC.match(w) and (i == 0 or _EN_EMPTY.match(words[i - 1])):
            return False
    return _first(others, side) is not None


def _elsewhere(t: str, start: int, end: int, forward: bool, st: _Structure) -> bool:
    """Whether the cue at ``t[start:end]`` is, by structure alone, about something in another clause than this
    concept (card 10A-1b). False whenever it cannot tell."""
    if not st.ok:
        return False
    c = st.at(start)
    if c in st.own or st.at(end - 1) != c:
        return False
    if st.last > c and not st.adv[c]:  # the cue's clause first: only an adversative boundary right after it will do
        return False
    cs, ce = max(st.starts[c], start - _SPAN), min(st.ends[c], end + _SPAN)
    if st.cjk and not forward and not t[cs:start].strip(" ,、"):
        forward = True  # "…,且未發現胎兒異常": at its clause's start a backward cue reads forward
    return _has_object(t[cs:ce], start - cs, end - cs, forward, st.cjk, st.others)


def unexplained_cue(text: str, terms: Iterable[str], other_terms: Iterable[str] = ()) -> bool:
    """Whether the line carries a negation cue that is not shown to be about something other than this concept."""
    terms = list(terms)
    own = _patterns(terms)
    others = _others(terms, other_terms)
    t = _prepare(text)
    found = _mentions(t, own)
    lang = "ja" if _KANA.search(t) else "zh" if _CJK.search(t) else "en"
    built: list[_Structure] = []

    def elsewhere(m: re.Match[str], forward: bool) -> bool:
        if not built:
            built.append(_Structure(t, found, lang, others))
        return _elsewhere(t, m.start(), m.end(), forward, built[0])

    for m in _EN_FWD.finditer(t):
        reach = _list_after(t, m.end(), cjk=False, ja=False)
        if not _explained_forward(_clause_after(t, m.end(), cjk=False), own, others, False, reach) and not elsewhere(
            m, True
        ):
            return True
    for m in _EN_BWD_ANY.finditer(t):
        before = _clause_before(t, m.start(), cjk=False)
        reach = _list_before(t, m.start(), cjk=False, ja=False)
        if not _explained_backward(before, m.group(0), "", own, others, False, reach) and not elsewhere(m, False):
            return True
    for m in _EN_PRE.finditer(t):
        # "Nonsmokers with asthma": the prefixed word negates itself; it is about something else only when this
        # concept is named elsewhere in the line, outside that word
        inside = any(s < m.end() and m.start() < e for s, e, _ in found)
        if inside or not found:
            return True
    if lang == "ja":
        for m in _JA_BWD.finditer(t):
            before, after = _clause_before(t, m.start(), True, True), _clause_after(t, m.end(), True, True)
            reach = _list_before(t, m.start(), True, True)
            if not _explained_backward(before, m.group(0), after, own, others, True, reach) and not elsewhere(m, False):
                return True
        for m in _JA_FWD.finditer(t):
            reach = _list_after(t, m.end(), True, True)
            if not _explained_forward(_clause_after(t, m.end(), True, True), own, others, True, reach) and not (
                elsewhere(m, True)
            ):
                return True
        return False
    for m in _ZH_FWD.finditer(t):
        reach = _list_after(t, m.end(), True, False)
        if not _explained_forward(_clause_after(t, m.end(), cjk=True), own, others, True, reach) and not elsewhere(
            m, True
        ):
            return True
    for m in _ZH_BWD.finditer(t):
        before, after = _clause_before(t, m.start(), cjk=True), _clause_after(t, m.end(), cjk=True)
        if not before.strip():  # at the clause's start it is a forward cue, read above
            continue
        reach = _list_before(t, m.start(), True, False)
        if not _explained_backward(before, m.group(0), after, own, others, True, reach) and not elsewhere(m, False):
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
