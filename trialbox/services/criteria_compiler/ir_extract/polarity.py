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
