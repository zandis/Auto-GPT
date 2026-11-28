"""The S2 miss rate on MedTxt (H3-NLP §3.5 (2); HOLISTIC-3 lane N): a finding the lexicon never hits is one the models
never read.

For every finding MedTxt tags ``positive`` (real Japanese case and radiology reports with aligned English
translations, CC BY 4.0, Sociocom NAIST; fetched by ``python -m tools.medtxt_eval fetch``, never committed) the
criterion is "Patients with <the English wording of the tag>.", as :mod:`tools.medtxt_eval` builds it. Its keys are
S2's own (``engine.lexicon_terms`` with no site table: the shipped bilingual terms), folded as S2 folds them, and the
question is whether any key is in the sentence that holds the finding, in the Japanese original and in the English
translation. A miss is either ``no_key`` (no key written in that language's script, so S2 has nothing to look for) or
``missed`` (keys, none in the sentence). No model, no GPU.

The fix list is every missed Japanese finding with its English wording and count, most frequent first: the terms a
site table or the shipped table lacks.

    python -m tools.medtxt_s2            # -> eval/medtxt/results/s2_miss.json
"""

from __future__ import annotations

import html
import json
import re
from collections import Counter
from types import SimpleNamespace
from typing import Any

from matching.cascade.engine import has_term_for, lexicon_terms
from matching.cascade.judge import norm

from tools.medtxt_eval import DTAG, FILES, RESULTS, TAG, articles

SPLIT = {"ja": re.compile(r"(?<=[。．])|\n"), "en": re.compile(r"(?<=[.!?])\s+|\n")}


def _tagged(raw: str, lang: str) -> list[tuple[str, str, str]]:
    """(certainty, finding, its sentence) for each tag of a report, in order; tags never hold a sentence end."""
    out = []
    for part in SPLIT[lang].split(raw):
        plain = " ".join(html.unescape(TAG.sub("", part)).split())
        out += [(c, " ".join(html.unescape(TAG.sub("", t)).split()), plain) for c, t in DTAG.findall(part)]
    return out


def misses(ja: dict[str, str], en: dict[str, str]) -> dict[str, Any]:
    """The S2 hit count per language over the positive findings of the reports whose JA and EN tags align."""
    res: dict[str, Counter[str]] = {lang: Counter() for lang in ("ja", "en")}
    fix: Counter[tuple[str, str]] = Counter()
    for rid in sorted(ja):
        tj, te = _tagged(ja[rid], "ja"), _tagged(en.get(rid, ""), "en")
        if [c for c, _, _ in tj] != [c for c, _, _ in te]:
            continue  # as medtxt_eval: no trustworthy English wording for the Japanese label
        seen: set[str] = set()
        for (c, fja, sja), (_, fen, sen) in zip(tj, te, strict=True):
            if c != "positive" or fen.lower() in seen:
                continue
            seen.add(fen.lower())
            crit = SimpleNamespace(id=fen, text=f"Patients with {fen}.", note_question=None)
            keys = [norm(x).lower() for x in lexicon_terms(crit, {})]  # type: ignore[arg-type]
            for lang, sent in (("ja", sja), ("en", sen)):
                low = norm(sent).lower()
                kind = "hit" if any(k in low for k in keys) else "missed" if has_term_for(keys, lang) else "no_key"
                res[lang][kind] += 1
                if lang == "ja" and kind != "hit":
                    fix[(fja, fen.lower())] += 1
    out: dict[str, Any] = {}
    for lang, cnt in res.items():
        n = sum(cnt.values())
        out[lang] = {"findings": n, **{k: cnt[k] for k in ("hit", "missed", "no_key")}}
        out[lang]["miss_rate"] = round(1 - cnt["hit"] / n, 4) if n else 0.0
    out["fix_list_ja"] = [{"ja": j, "en": e, "n": k} for (j, e), k in sorted(fix.items(), key=lambda x: (-x[1], x[0]))]
    return out


def main() -> None:
    ja: dict[str, str] = {}
    en: dict[str, str] = {}
    for corpus in FILES:
        ja |= articles(corpus, "ja")
        en |= articles(corpus, "en")
    res = misses(ja, en)
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "s2_miss.json").write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "fix_list_ja"}), len(res["fix_list_ja"]), "fix rows")


if __name__ == "__main__":
    main()
