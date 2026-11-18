"""Polarity of exclusion note questions (D-98).

The judge answers the ``note_question``; for an exclusion criterion ``pass`` (YES) means the excluded condition is
present, so the patient fails the criterion. A question phrased in the negative ("Does the patient have no history of
X?") inverts that: YES then means the condition is absent, and the box would exclude exactly the patients it should
keep. The 2026-11-05 public-data validation (TREC CT, MedTxt) found this the largest single source of wrong
exclusions after suspected findings. The extraction prompt forbids negated exclusions, but a model does not always
obey, so the compiler checks every exclusion question here, rewrites the common English forms to the positive, keeps
the original for the reviewer, and flags whatever it cannot rewrite.
"""

from __future__ import annotations

import re

# English negation markers that invert a yes/no question.
_EN_NEGATED = re.compile(
    r"\b(no|not|never|without|absence of|absent|free of|free from|neither|nor|lack of|lacks|lacking|"
    r"n't|denies|denied|negative for|ruled out|excluded)\b",
    re.I,
)
# Japanese / Chinese negation markers (surface forms; the reviewer rewrites these by hand).
_CJK_NEGATED = re.compile(r"(ない|なし|ません|否定|除外|未|無|沒有|没有|不曾|從未|从未|非)")

# Rewrites in order; the first that matches wins. Each maps a negated question to the positive one.
_REWRITES: tuple[tuple[re.Pattern[str], str], ...] = (
    # "Does the patient have no / not have ... ?"  ->  "Does the patient have ... ?"
    (re.compile(r"^(Does|Did) (the patient|the subject|he|she|they) (have|has) no (.+)$", re.I), r"\1 \2 \3 \4"),
    (re.compile(r"^(Does|Did) (the patient|the subject|he|she|they) not (have|has) (.+)$", re.I), r"\1 \2 \3 \4"),
    (re.compile(r"^(Does|Did) (the patient|the subject|he|she|they) not (.+)$", re.I), r"\1 \2 \3"),
    # "Is there no ... ?" -> "Is there ... ?";  "Is the patient free of/from X" -> "Does the patient have X"
    (re.compile(r"^(Is|Was|Are|Were) there no (.+)$", re.I), r"\1 there \2"),
    (re.compile(r"^(Is|Was) (the patient|the subject|he|she) free (?:of|from) (.+)$", re.I), r"Does \2 have \3"),
    (re.compile(r"^(Is|Was) (the patient|the subject|he|she) not (.+)$", re.I), r"\1 \2 \3"),
    (re.compile(r"^(Is|Was) (the patient|the subject|he|she) without (.+)$", re.I), r"Does \2 have \3"),
    # "Has the patient never ... ?" -> "Has the patient ever ... ?";  "Has the patient not ..." -> "Has the patient ..."
    (re.compile(r"^(Has|Had|Have) (the patient|the subject|he|she|they) never (.+)$", re.I), r"\1 \2 ever \3"),
    (re.compile(r"^(Has|Had|Have) (the patient|the subject|he|she|they) not (.+)$", re.I), r"\1 \2 \3"),
    # "Is there an absence of X" / "Is X absent" -> "Is X present"
    (re.compile(r"^(Is|Was) there (?:an )?absence of (.+)$", re.I), r"\1 there \2"),
    (re.compile(r"^(Is|Was|Are|Were) (.+?) absent(\??)$", re.I), r"\1 \2 present\3"),
    # "Is the patient negative for X" -> "Is the patient positive for X"
    (re.compile(r"^(Is|Was) (the patient|the subject|he|she) negative for (.+)$", re.I), r"\1 \2 positive for \3"),
)


def is_negated(question: str) -> bool:
    """True when the question carries a negation marker (English or Japanese/Chinese surface forms)."""
    q = question.strip()
    return bool(_EN_NEGATED.search(q)) or bool(_CJK_NEGATED.search(q))


def positive(question: str) -> str | None:
    """The positive form of a negated English yes/no question, or None when no safe rewrite applies.

    Only whole-question patterns are rewritten; a negation buried mid-sentence ("... in patients not on dialysis")
    may be a legitimate qualifier, so it is flagged for the reviewer instead."""
    q = " ".join(question.strip().split())
    q2 = re.sub(r"\bhave no (history|evidence|record|diagnosis|documentation) of\b", r"have a \1 of", q, flags=re.I)
    if q2 != q and not _EN_NEGATED.search(q2):
        return q2
    for pat, repl in _REWRITES:
        m = pat.match(q)
        if m:
            out = pat.sub(repl, q)
            out = re.sub(r"\s+([?？])", r"\1", out)
            out = out[0].upper() + out[1:]
            if not out.endswith(("?", "？")):
                out += "?"
            return out if not _EN_NEGATED.search(out) else None  # a second negation remains: leave it to a person
    return None


# A criterion LINE that is a negation as a whole (card 10A-1): "No prior chemotherapy", "化学療法歴なし",
# "未曾接受化學治療".
# Narrower than ``is_negated``, which also fires on a negation that only qualifies a line ("adenocarcinoma, not
# amenable to surgery", "MDD without psychotic features"): only the line's lead (English, Chinese) or its end
# (Japanese, where the predicate is last) is read. A section heading ("PRIOR CONCURRENT THERAPY:") and a bullet or a
# number are skipped first.
_BULLET = re.compile(r"^\s*(?:[-*•・●○◦▪]|\(?\d{1,3}[.)、]|\(?[a-z][.)])\s*", re.I)
_HEADING = re.compile(r"^[^:：]{1,60}[:：]\s*")
_EN_LEAD = re.compile(
    r"^(?:(?:patients?|subjects?|participants?|individuals?|adults?|children|women|men|people|those)\s+"
    r"(?:(?:who|that)\s+(?:have|has|had|did|do|does|are|is|were|was)\s+(?:not|never)\b|with\s+no\b|without\b|"
    r"having\s+no\b|not\b)"
    r"|(?:no|not|never|without|none|neither|absence\s+of|absent|free\s+(?:of|from)|lack\s+of|lacking|cannot|"
    r"(?:must|should|may|has|have|had|did|does|do|is|are|was|were)\s+(?:not|never)|(?:has|have|had|did|does|do|is|are|"
    r"was|were)n['’]t|can['’]t)\b)",
    re.I,
)
# "<treatment>-naive" ends the line, with at most a subject after it: "Treatment-naive HIV infection" asks the HIV
_EN_NAIVE = re.compile(
    r"^\S+(?:\s\S+)?[- ]na[iï]ve(?:\s+(?:patients?|subjects?|participants?|adults?|women|men|children))?$", re.I
)
_ZH_LEAD = re.compile(
    r"^(?:(?:病人|患者|受試者|受试者|個案|个案)\s*)?"
    r"(?:無|无|沒有|没有|未曾|從未|从未|不曾|未(?:接受|使用|服用|罹患|患有|有|做過|做过|經|经|行|施行))"
)
_JA_END = re.compile(
    r"(?:な[しい]|無し|(?<!少)ない(?:こと|もの|者|患者|症例|方)?|認めず|ません|未(?:施行|実施|投与|治療|経験|使用))$"
)
_END_PUNCT = re.compile(r"[\s。．.、,;；!！]+$")


def line_is_negated(text: str) -> bool:
    """True when a criterion's line as a whole says the patient has NOT something: its lead (English, Chinese) or its
    end (Japanese) is a negation, after a heading, a bullet or a number. A negation inside a positive line is not."""
    t = _BULLET.sub("", " ".join(text.split()))
    bodies = {t, _BULLET.sub("", _HEADING.sub("", t))}
    for b in bodies:
        b = _END_PUNCT.sub("", b)
        if _EN_LEAD.match(b) or _EN_NAIVE.match(b) or _ZH_LEAD.match(b) or _JA_END.search(b):
            return True
    return False
