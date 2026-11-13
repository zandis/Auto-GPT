"""PHI guard (spec v4 §7.14, §8.6; S1-08): detect, redact, tripwire.

* :meth:`Guard.detect` runs every recogniser and merges overlapping spans (longest wins).
* :meth:`Guard.redact` replaces each span with a type tag (``[TW_NATIONAL_ID]``); the trace store calls it at write.
* :meth:`Guard.tripwire` is the independent check the gateway runs (LLM-15, PRIV-29): a hit from these recognisers
  or from the v1 :func:`tb_common.phi_guard.scan` blocks, whatever the class label says. A NAME finding on a
  Japanese line gets a second look first (:mod:`guard.names`, D-647): the patterns alone refused ordinary text.
* :meth:`Guard.screen` is the planted-instruction screen (T-606, D-359; :mod:`guard.injection`): it flags text written
  as an instruction to a model. It never blocks a call; the caller decides what a flag does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from tb_common import phi_guard

from guard import names
from guard.injection import Screen, screen
from guard.recognisers import Finding, recognisers


@dataclass(frozen=True)
class Verdict:
    hit: bool
    kinds: tuple[str, ...] = ()
    count: int = 0
    findings: list[Finding] = field(default_factory=list)


def merge(findings: list[Finding]) -> list[Finding]:
    """Overlapping or touching spans become one span labelled with the kind of the longest member."""
    out: list[Finding] = []
    for f in sorted(findings, key=lambda x: (x.start, -(x.end - x.start))):
        if out and f.start <= out[-1].end:
            last = out[-1]
            kind = last.kind if (last.end - last.start) >= (f.end - f.start) else f.kind
            out[-1] = Finding(kind, last.start, max(last.end, f.end), last.valid and f.valid)
        else:
            out.append(f)
    return out


_CJK = re.compile(r"[぀-ヿ㐀-鿿]")


def _unconfirmed(text: str, f: Finding, look: names.Look) -> bool:
    """A NAME finding in Japanese or Chinese characters that the second look takes away (only on a line with
    kana, D-647). A name in Latin letters (``Mr. Chen``) is not looked at again: it stands."""
    return f.kind == "NAME" and bool(_CJK.search(text[f.start : f.end])) and not look.stands(text, f.start, f.end)


def _standing_names(text: str) -> list[str]:
    """The v1 guard's Chinese and Japanese names (:func:`tb_common.phi_guard._cjk_names`) that stand at one of the
    places they are written."""
    out = []
    look = names.Look()
    for name in phi_guard._cjk_names(text):
        at = text.find(name)
        while at >= 0:
            if look.stands(text, at, at + len(name)):
                out.append(name)
                break
            at = text.find(name, at + 1)
    return out


class Guard:
    def __init__(self, mrn_regex: str | None = None) -> None:
        self.mrn_regex = mrn_regex
        self._recognisers = recognisers(mrn_regex)

    @classmethod
    def from_settings(cls) -> Guard:
        """The site MRN pattern comes from ``settings.mrn_regex``; without readable settings none is used."""
        try:
            from tb_common.config import get_config

            return cls(get_config().settings.mrn_regex)
        except Exception:
            return cls(None)

    def detect(self, text: str, second_look: bool = False) -> list[Finding]:
        """``second_look`` (the tripwire, D-647): a NAME finding stands unless :mod:`guard.names` takes it away
        (ordinary Japanese text on a line with kana). Redaction does not take it: masking too much costs
        readability only."""
        found: list[Finding] = []
        for _name, rec in self._recognisers:
            found.extend(f for f in rec(text) if f.end > f.start)
        if second_look:
            look = names.Look()
            found = [f for f in found if not _unconfirmed(text, f, look)]
        return merge(found)

    def redact(self, text: str) -> str:
        spans = self.detect(text)
        if not spans:
            return text
        parts: list[str] = []
        pos = 0
        for f in spans:
            parts.append(text[pos : f.start])
            parts.append(f"[{f.kind}]")
            pos = f.end
        parts.append(text[pos:])
        return "".join(parts)

    def redact_obj(self, obj: Any) -> Any:
        """Redact every string inside a JSON-like value (keys are kept; they are field names, not content)."""
        if isinstance(obj, str):
            return self.redact(obj)
        if isinstance(obj, dict):
            return {k: self.redact_obj(v) for k, v in obj.items()}
        if isinstance(obj, list | tuple):
            return [self.redact_obj(v) for v in obj]
        return obj

    def tripwire(self, text: str, second_look: bool = True) -> Verdict:
        """``second_look=False``: every pattern match counts, as before D-647 (the document parser's mask of a
        protocol's contact and subject lines keeps the stricter look, as the trace store's redaction does)."""
        spans = self.detect(text, second_look=second_look)
        v1 = phi_guard.scan(text, self.mrn_regex, cjk_names=_standing_names if second_look else None)
        kinds = sorted({f.kind for f in spans} | {k.upper() for k, _ in v1.findings})
        hit = bool(spans) or v1.hit
        return Verdict(hit, tuple(kinds), len(spans) + len(v1.findings), spans)

    def screen(self, text: str) -> Screen:
        """The planted-instruction screen (:func:`guard.injection.screen`)."""
        return screen(text)
