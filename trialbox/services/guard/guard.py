"""PHI guard (spec v4 §7.14, §8.6; S1-08): detect, redact, tripwire.

* :meth:`Guard.detect` runs every recogniser and merges overlapping spans (longest wins).
* :meth:`Guard.redact` replaces each span with a type tag (``[TW_NATIONAL_ID]``); the trace store calls it at write.
* :meth:`Guard.tripwire` is the independent check the gateway runs (LLM-15, PRIV-29): a hit from these recognisers
  or from the v1 :func:`tb_common.phi_guard.scan` blocks, whatever the class label says.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tb_common import phi_guard

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

    def detect(self, text: str) -> list[Finding]:
        found: list[Finding] = []
        for _name, rec in self._recognisers:
            found.extend(f for f in rec(text) if f.end > f.start)
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

    def tripwire(self, text: str) -> Verdict:
        spans = self.detect(text)
        v1 = phi_guard.scan(text, self.mrn_regex)
        kinds = sorted({f.kind for f in spans} | {k.upper() for k, _ in v1.findings})
        hit = bool(spans) or v1.hit
        return Verdict(hit, tuple(kinds), len(spans) + len(v1.findings), spans)
