"""Cue tables for ``note_prep``: ConText-style cues over a sentence of a note, in English, Japanese and Traditional or
Simplified Chinese (MATCH-ARCH layer (a)).

A cue is a *tag*, never a verdict. ``tag(text)`` says which negation, experiencer, temporality and uncertainty words a
sentence carries and where; it does not say what they reach. Scope belongs to the reader of the tags (the lexicon
stage, the extractor, a person), which also sees the raw sentence. Nothing here excludes, includes or drops a note.

Four kinds:

* ``negation``: ``absent`` (denies, no, 認めず, なし, 否認, 未曾 ...);
* ``experiencer``: ``family`` or ``other`` (mother, 家族歴, 母親 ...); no cue means the patient;
* ``temporality``: ``historical``, ``planned`` or ``hypothetical``; no cue means current;
* ``uncertainty``: ``uncertain`` (suspected, 疑い, 疑似, r/o ...).

Each cue also has a direction (``forward``: before what it reaches, ``backward``: after it, as in "HIV negative",
"アレルギーなし"), the reading of Harkema H, Dowling JN, Thornblade T, Chapman WW. ConText: an algorithm for
determining negation, experiencer, and temporal status from clinical reports. J Biomed Inform 2009;42(5):839-51. The
English words are the common clinical negation and context words of that line of work; the Japanese endings (〜なし,
〜を認めず ...) and the zh-TW words (無, 未, 否認, 排除 ...) are this project's own, written from ordinary clinical
usage. The criterion-line tables of ``criteria_compiler.ir_extract.negation_scope`` answer a different question (may a
criterion line run) and are not reused.

**Pseudo cues** are phrases that look like a cue and are not (``no longer``, ``non-small cell``, ``未満``, ``無法``,
``排除標準``). A cue wholly inside one is dropped. **Overlaps** keep the longer cue (``family history of`` over
``history of``; ``否定できない``, "cannot be excluded" as uncertainty over the negation they contain).

**Known ceilings** (reading, not decision): the bare Japanese ``ない`` is not a cue (too many other uses); a cue is
not scoped; a sentence that negates a list is tagged once.
"""

from __future__ import annotations

import re
from typing import NamedTuple


class Cue(NamedTuple):
    kind: str  # negation | experiencer | temporality | uncertainty
    value: str  # absent | family | other | historical | planned | hypothetical | uncertain
    direction: str  # forward | backward
    start: int  # character offsets in the NFKC sentence text
    end: int
    text: str


_I = re.I
# (kind, value, direction, pattern, flags); the order is the tie-break of two cues of one length
_RAW: tuple[tuple[str, str, str, str, int], ...] = (
    # ---- English
    (
        "negation",
        "absent",
        "forward",
        r"\b(?:no|not|denies|denied|denying|denial of|negative for|without|absence of|absent|free of|lack of|never"
        r"|ruled out)\b|\b\w+n['’]t\b",
        _I,
    ),
    (
        "negation",
        "absent",
        "backward",
        r"\b(?:was|is|are|were|been)\s+negative\b|\bnegative\b(?!\s+for\b)|\bnone\b|\bnkd?a\b",
        _I,
    ),
    (
        "experiencer",
        "family",
        "forward",
        r"\b(?:family history|fhx|mother|father|mom|dad|sister|brother|sibling"
        r"s?|grandmother|grandfather|grandparents?|aunt|uncle|cousin|son|daughter|parents?|maternal|paternal)\b",
        _I,
    ),
    ("experiencer", "other", "forward", r"\b(?:husband|wife|spouse|friend|neighbou?r|coworker|roommate)\b", _I),
    (
        "temporality",
        "historical",
        "forward",
        r"\b(?:history of|h/o|hx(?: of)?|previous(?:ly)?|prior|formerly|in the past|used to|status post|s/p)\b",
        _I,
    ),
    ("temporality", "historical", "backward", r"\b(?:resolved|resolving)\b", _I),
    (
        "temporality",
        "planned",
        "forward",
        r"\b(?:plan(?:s|ned)?(?: to| for)?|will|scheduled(?: for| to)?|to be (?:started|given|scheduled)"
        r"|to (?:start|begin|undergo)|going to|next visit)\b",
        _I,
    ),
    ("temporality", "hypothetical", "forward", r"\b(?:if|in case of|in the event of|should the)\b", _I),
    (
        "uncertainty",
        "uncertain",
        "forward",
        r"\b(?:possible|possibly|probable|probably|suspect(?:ed|s)?|suspicious for|questionable|likely|unlikely"
        r"|r/o|rule out|concern for|cannot be (?:excluded|ruled out)|can(?:not|['’]t) rule out)\b|\?",
        _I,
    ),
    ("uncertainty", "uncertain", "forward", r"\b(?:may|might|could)\b", 0),  # lower case only: "May 2026" is a month
    # ---- Japanese
    (
        "negation",
        "absent",
        "backward",
        r"なし|無し|認めず|認めない|認められず|認められない|認めなかった|認めません|見られず|みられず|見られない"
        r"|みられない|否定|陰性|伴わず|示さず|ありません",
        0,
    ),
    ("negation", "absent", "forward", r"未(?!満)|非(?!常|特異)|無(?![いり理料限数論]|関係)", 0),
    (
        "experiencer",
        "family",
        "forward",
        r"家族歴|祖母|祖父|母親|父親|兄弟|姉妹|両親|息子|娘|叔母|叔父|伯母|伯父|実母|実父"
        r"|[母父姉兄妹弟](?=[がはもの、 ])",
        0,
    ),
    ("experiencer", "other", "forward", r"配偶者|友人|知人|同居人|[夫妻](?=[がはもの、 ])", 0),
    ("temporality", "historical", "forward", r"既往歴|既往|以前|過去|かつて|前医", 0),
    ("temporality", "historical", "backward", r"消失|治癒|寛解", 0),
    ("temporality", "planned", "forward", r"予定|予約|次回|今後|検討", 0),
    ("temporality", "hypothetical", "forward", r"場合|もし|際は|ときは", 0),
    (
        "uncertainty",
        "uncertain",
        "backward",
        r"疑い|疑われ|疑う|可能性|示唆|思われ|考えられ|かもしれ|と推測|と推定|否定できない|除外できない|否定はできない",
        0,
    ),
    # ---- Chinese (zh-TW first, simplified spellings beside them)
    (
        "negation",
        "absent",
        "forward",
        r"沒有|没有|並無|并无|未曾|從未|从未|未見|未见|否認|否认|不曾|排除|無|无|未",
        0,
    ),
    ("negation", "absent", "backward", r"陰性|阴性", 0),
    (
        "experiencer",
        "family",
        "forward",
        r"家族史|家人|家屬|家属|母親|母亲|父親|父亲|媽媽|妈妈|爸爸|姊姊|姐姐|哥哥|弟弟|妹妹|祖母|祖父|外婆|外公|奶奶|爺爺"
        r"|兒子|儿子|女兒|女儿|父母|兄弟|姊妹|姐妹|阿姨|叔叔|舅舅",
        0,
    ),
    ("experiencer", "other", "forward", r"配偶|太太|丈夫|妻子|朋友|同事", 0),
    ("temporality", "historical", "forward", r"病史|既往|曾經|曾患|曾有|曾接受|曾(?!孫)|過去|过去|以前|先前", 0),
    ("temporality", "historical", "backward", r"痊癒|痊愈|緩解|缓解|消退|消失", 0),
    ("temporality", "planned", "forward", r"預計|预计|計畫|计划|擬|預約|预约|安排|將|将|下次|後續|后续", 0),
    ("temporality", "hypothetical", "forward", r"如果|如有|若(?!干)|倘若|必要時|必要时", 0),
    (
        "uncertainty",
        "uncertain",
        "forward",
        r"疑似|懷疑|怀疑|可能(?=[是有為为會会已在])|可疑|待排除|待排|不排除|不能排除|無法排除|无法排除|考慮|考虑|推測|推测",
        0,
    ),
)

_PSEUDO = (
    re.compile(
        r"\b(?:no longer|not only|no change|no further|no increase|no decrease|not necessarily|gram[- ]negative"
        r"|non-?small|not certain|not limited to|no more than|no less than|no greater than|not more than"
        r"|not less than|not (?:to )?exceed(?:ing)?|no\.\s*\d)\b",
        _I,
    ),
    re.compile(r"未満|ないし|無理|無料|無限|無数|無論|無関係|非常|母集団|母乳|父母会"),
    re.compile(r"無法|无法|無論|无论|未滿|未满|排除標準|排除标准|排除條件|排除条件|若干|曾孫"),
)

CUES: tuple[tuple[str, str, str, re.Pattern[str]], ...] = tuple(
    (kind, value, direction, re.compile(pat, flags)) for kind, value, direction, pat, flags in _RAW
)


def tag(text: str) -> list[Cue]:
    """The cues of one NFKC sentence, in text order: pseudo cues removed, the longer of two overlapping cues kept."""
    blocked = [m.span() for pat in _PSEUDO for m in pat.finditer(text)]
    found: list[tuple[int, int, int, str, str, str]] = []
    for order, (kind, value, direction, pat) in enumerate(CUES):
        for m in pat.finditer(text):
            s, e = m.span()
            if e > s and not any(bs <= s and e <= be for bs, be in blocked):
                found.append((s, e, order, kind, value, direction))
    found.sort(key=lambda c: (c[0] - c[1], c[2], c[0]))
    kept: list[tuple[int, int, int, str, str, str]] = []
    for c in found:
        if all(c[1] <= k[0] or k[1] <= c[0] for k in kept):
            kept.append(c)
    kept.sort(key=lambda c: (c[0], c[1]))
    return [Cue(kind, value, direction, s, e, text[s:e]) for s, e, _o, kind, value, direction in kept]
