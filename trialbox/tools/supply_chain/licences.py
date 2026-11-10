"""Licence report from CycloneDX SBOMs (D-186): flags GPL, LGPL, AGPL, unknown licences and dual-licence choices.

Each component gets a set of *flags*; a flagged component fails unless the allow-list accepts every flag:

* ``agpl`` / ``gpl`` / ``lgpl``: a copyleft licence anywhere in the component's licence data (SPDX id, name,
  expression, URL or full text; ``Licence`` and ``License`` spellings; ``LicenseRef_GPL3`` too). A full licence text
  is searched end to end.
* ``unknown``: no licence data, or a licence that is not on the known list below (``LicenseRef-*``, ``NOASSERTION``,
  ``Proprietary``, a hash, "BSD, Public Domain"...). The allow-list entry records the licence a person verified.
* ``dual``: an ``OR`` with a permissive branch and a non-permissive one (dulwich: ``Apache-2.0 OR GPL-2.0-or-later``).
  The allow-list entry names the branch chosen, which must be one of the permissive branches.

``OR`` counts only branches that are entirely on the permissive list; with none, the most permissive copyleft branch
applies, and a branch with an unknown part can never be chosen. ``AND`` and several licences on one component add
their flags. ``WITH`` keeps the class of the licence it modifies.

Nothing is guessed: a licence that is neither copyleft nor on ``PERMISSIVE``/``OTHER_OK`` is ``unknown``.

Distro packages of a base image (deb, apk, rpm) are listed but do not fail unless ``--gate-os-packages``: they come
unmodified with the image and are covered by the distro's own notices.
"""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from tools.supply_chain.allowlist import Allowlist, norm

RANK = {"ok": 0, "dual": 1, "unknown": 2, "lgpl": 3, "gpl": 4, "agpl": 5}
FLAGS = ("dual", "unknown", "lgpl", "gpl", "agpl")
COPYLEFT = ("lgpl", "gpl", "agpl")

# SPDX ids (lower case) that may be chosen as an OR branch and need no review
PERMISSIVE = frozenset(
    {
        "0bsd", "apache-2.0", "bsd-1-clause", "bsd-2-clause", "bsd-3-clause", "bsd-3-clause-clear", "cc0-1.0",
        "hpnd", "isc", "mit", "mit-0", "mit-cmu", "psf-2.0", "python-2.0", "unlicense", "zlib", "bsl-1.0", "x11",
        "ncsa", "upl-1.0", "zpl-2.1", "blessing", "curl",
    }
)  # fmt: skip
# accepted, not copyleft in the sense of this gate, but not offered as an OR choice (file-level copyleft: notices)
OTHER_OK = frozenset({"mpl-2.0"})
# the trove-classifier and common names of permissive licences (lower case, whitespace collapsed)
PERMISSIVE_NAMES = frozenset(
    {
        "mit license", "the mit license", "mit licence", "bsd license", "bsd licence", "new bsd license",
        "bsd 3-clause license", "bsd 2-clause license", "apache software license", "apache license 2.0",
        "apache license, version 2.0", "apache license version 2.0", "apache 2.0", "apache-2", "apache 2",
        "python software foundation license", "isc license (iscl)", "isc license", "the unlicense (unlicense)",
        "zlib/libpng license", "boost software license 1.0 (bsl-1.0)",
        "historical permission notice and disclaimer (hpnd)",
    }
)  # fmt: skip
OTHER_OK_NAMES = frozenset({"mozilla public license 2.0 (mpl 2.0)"})
# a full licence text: its own words name it
_TEXT_SIGNATURES = (
    ("Permission is hereby granted, free of charge, to any person obtaining a copy", "mit"),
    ("Redistribution and use in source and binary forms, with or without modification, are permitted", "bsd"),
    ("Apache License Version 2.0, January 2004", "apache-2.0"),
)
_PERMISSIVE_URLS = re.compile(
    r"^https?://(www\.)?(opensource\.org/licenses?/(MIT|BSD-[23]-Clause|Apache-2\.0|ISC)|apache\.org/licenses/LICENSE-2\.0)"
    r"(\.html|\.txt|/)?$",
    re.IGNORECASE,
)

_NOT_LETTER = r"(?<![A-Za-z])"
_AGPL = re.compile(_NOT_LETTER + r"AGPL|Affero\s+General\s+Public\s+Licen[cs]e", re.IGNORECASE)
_LGPL = re.compile(_NOT_LETTER + r"LGPL|(Lesser|Library)\s+General\s+Public\s+Licen[cs]e", re.IGNORECASE)
_GPL = re.compile(
    _NOT_LETTER + r"GPL|(?<!Lesser )(?<!Library )(?<!Affero )General\s+Public\s+Licen[cs]e", re.IGNORECASE
)
_MAX_EXPR = 200  # longer than any SPDX expression in practice: free text
_TOKEN = re.compile(r"\(|\)|[^\s()]+")


def _ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def copyleft(text: str) -> str | None:
    """The strictest copyleft class named anywhere in ``text``, or None."""
    t = _ws(text)
    if _AGPL.search(t):
        return "agpl"
    if _GPL.search(t):
        return "gpl"
    if _LGPL.search(t):
        return "lgpl"
    return None


def classify_one(text: str) -> str:
    """Class of a single licence id, name, URL or full text: ok, unknown, lgpl, gpl or agpl."""
    t = _ws(text)
    if not t:
        return "unknown"
    found = copyleft(t)
    if found:
        return found
    low = t.lower()
    if low in PERMISSIVE or low in OTHER_OK or low in PERMISSIVE_NAMES or low in OTHER_OK_NAMES:
        return "ok"
    if _PERMISSIVE_URLS.match(t):
        return "ok"
    if any(sig.lower() in low for sig, _ in _TEXT_SIGNATURES):
        return "ok"
    return "unknown"


@dataclass(frozen=True)
class Verdict:
    flags: frozenset[str]
    choices: frozenset[str] = frozenset()  # the permissive OR branches a ``dual`` entry may name

    @property
    def cls(self) -> str:
        return max(self.flags, key=RANK.__getitem__) if self.flags else "ok"


def _flags(cls: str) -> frozenset[str]:
    return frozenset() if cls == "ok" else frozenset({cls})


class _ParseError(ValueError):
    pass


def classify(expr: str) -> Verdict:
    """Verdict for one licence string (an SPDX expression, a name, a URL or a full text)."""
    t = _ws(expr)
    if not t:
        return Verdict(frozenset({"unknown"}))
    if len(expr) > _MAX_EXPR or "\n" in expr or not re.search(r" (OR|AND|WITH) |\(", t):
        return Verdict(_flags(classify_one(expr)))
    tokens = _TOKEN.findall(t)
    try:
        pos, verdict = _parse_or(tokens, 0)
        if pos == len(tokens):
            return verdict
    except _ParseError:
        pass
    # not an expression after all (a licence name with words and brackets): one text, and copyleft words still count
    return Verdict(_flags(classify_one(expr)))


def _parse_or(toks: list[str], i: int) -> tuple[int, Verdict]:
    i, first = _parse_and(toks, i)
    parts = [first]
    while i < len(toks) and toks[i] == "OR":
        i, nxt = _parse_and(toks, i + 1)
        parts.append(nxt)
    if len(parts) == 1:
        return i, first
    permissive = [p for p in parts if not p.flags]
    others = [p for p in parts if p.flags]
    if permissive and others:
        choices = frozenset().union(*(p.choices for p in permissive))
        return i, Verdict(frozenset({"dual"}), choices)
    if permissive:  # every branch permissive
        return i, Verdict(frozenset(), frozenset().union(*(p.choices for p in permissive)))
    selectable = [p for p in others if "unknown" not in p.flags and "dual" not in p.flags]
    if not selectable:
        return i, Verdict(frozenset({"unknown"}))
    best = min(selectable, key=lambda p: RANK[p.cls])
    return i, best


def _parse_and(toks: list[str], i: int) -> tuple[int, Verdict]:
    i, first = _parse_atom(toks, i)
    parts = [first]
    while i < len(toks) and toks[i] == "AND":
        i, nxt = _parse_atom(toks, i + 1)
        parts.append(nxt)
    if len(parts) == 1:
        return i, first
    flags = frozenset().union(*(p.flags for p in parts))
    # an AND of permissive parts is chosen as a whole; its text is the choice
    whole = [sorted(p.choices) for p in parts]
    if not flags:
        choices = frozenset({" AND ".join(sorted(" OR ".join(c) for c in whole))})
    else:  # the choices of a dual part stay nameable
        choices = frozenset().union(*(p.choices for p in parts if "dual" in p.flags))
    return i, Verdict(flags, choices)


def _parse_atom(toks: list[str], i: int) -> tuple[int, Verdict]:
    if i >= len(toks) or toks[i] in ("AND", "OR", "WITH", ")"):
        raise _ParseError(f"licence expected at token {i}")
    if toks[i] == "(":
        i, inner = _parse_or(toks, i + 1)
        if i >= len(toks) or toks[i] != ")":
            raise _ParseError("unbalanced parentheses")
        return i + 1, inner
    lic = toks[i]
    i += 1
    if i < len(toks) and toks[i] == "WITH":  # an exception keeps the class of the licence it modifies
        if i + 1 >= len(toks) or toks[i + 1] in ("AND", "OR", "WITH", "(", ")"):
            raise _ParseError("exception expected after WITH")
        i += 2
        cls = classify_one(lic)
        return i, Verdict(_flags(cls))  # an exception is not offered as a plain permissive choice
    cls = classify_one(lic)
    return i, Verdict(_flags(cls), frozenset({lic}) if cls == "ok" else frozenset())


def _text_content(text: Any) -> str:
    if not isinstance(text, dict):
        return str(text or "")
    content = str(text.get("content", ""))
    if str(text.get("encoding", "")).lower() == "base64":
        try:
            return base64.b64decode(content).decode("utf-8", "replace")
        except (binascii.Error, ValueError):
            return content
    return content


def component_licences(comp: dict[str, Any]) -> list[tuple[str, str]]:
    """Every licence string of a component as (kind, value): kind "named" (expression, id, name) or "ref" (URL,
    text). A URL or text only adds copyleft flags when the licence is also named; alone, it is classed in full."""
    out: list[tuple[str, str]] = []
    for entry in comp.get("licenses") or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("expression"):
            out.append(("named", str(entry["expression"])))
        lic = entry.get("license") or {}
        if not isinstance(lic, dict):
            continue
        for key in ("id", "name"):
            if lic.get(key):
                out.append(("named", str(lic[key])))
        if lic.get("url"):
            out.append(("ref", str(lic["url"])))
        if lic.get("text"):
            out.append(("ref", _text_content(lic["text"])))
    return out


def walk(components: Any) -> Iterator[dict[str, Any]]:
    """Every component, nested ``components`` included."""
    for comp in components or []:
        if isinstance(comp, dict):
            yield comp
            yield from walk(comp.get("components"))


def verdict_of(lics: list[tuple[str, str]]) -> Verdict:
    """Flags of a component from all its licence strings; no licence data at all is ``unknown``."""
    named = [classify(v) for kind, v in lics if kind == "named"]
    refs = [v for kind, v in lics if kind == "ref"]
    if not named:
        named = [Verdict(_flags(classify_one(v))) for v in refs] or [Verdict(frozenset({"unknown"}))]
    flags = frozenset().union(*(v.flags for v in named))
    flags |= {c for c in (copyleft(v) for v in refs) if c}  # a URL or text naming a copyleft licence always counts
    return Verdict(flags, frozenset().union(*(v.choices for v in named)))


OS_ECOSYSTEMS = frozenset({"deb", "apk", "rpm", "alpm"})


def ecosystem(comp: dict[str, Any]) -> str:
    """The purl type (``pypi``, ``deb``, ``maven``...), or ``other``."""
    purl = str(comp.get("purl", ""))
    return purl[4:].split("/", 1)[0].lower() if purl.startswith("pkg:") and "/" in purl else "other"


@dataclass(frozen=True)
class Row:
    package: str
    version: str
    ecosystem: str
    licences: tuple[str, ...]
    flags: frozenset[str]
    choices: frozenset[str]
    sources: tuple[str, ...]
    accepted: dict[str, str] = field(default_factory=dict, hash=False, compare=False)  # flag -> allow-list reason
    gated: bool = True  # False for distro packages of a base image unless --gate-os-packages

    @property
    def cls(self) -> str:
        return max(self.flags, key=RANK.__getitem__) if self.flags else "ok"

    @property
    def licence(self) -> str:
        """The component's licences joined with " AND ", for the report."""
        return " AND ".join(self.licences)

    @property
    def open_flags(self) -> frozenset[str]:
        return frozenset(f for f in self.flags if f not in self.accepted)

    @property
    def failing(self) -> bool:
        return self.gated and bool(self.open_flags)


def _accept(allow: Allowlist, pkg: str, verdict: Verdict) -> dict[str, str]:
    accepted: dict[str, str] = {}
    for flag in verdict.flags:
        entry = allow.licence(pkg, flag)
        if entry is None:
            continue
        if flag == "dual" and (entry.chosen or "").lower() not in {c.lower() for c in verdict.choices}:
            continue  # the entry chose a branch this component does not offer
        accepted[flag] = entry.reason
    return accepted


def report(sboms: dict[str, dict[str, Any]], allow: Allowlist, *, gate_os_packages: bool = False) -> list[Row]:
    """One row per (package, version, licences) across the SBOMs, strictest first. Nested components are read."""
    seen: dict[tuple[str, str, str, tuple[tuple[str, str], ...]], set[str]] = {}
    for source, doc in sboms.items():
        for comp in walk(doc.get("components")):
            if comp.get("type") not in (None, "library", "application", "framework"):
                continue
            name = str(comp.get("name", "")).strip()
            if not name:
                continue
            key = (norm(name), str(comp.get("version", "")), ecosystem(comp), tuple(component_licences(comp)))
            seen.setdefault(key, set()).add(source)
    rows = []
    for (pkg, version, eco, lics), sources in seen.items():
        verdict = verdict_of(list(lics))
        rows.append(
            Row(
                package=pkg,
                version=version,
                ecosystem=eco,
                licences=tuple(v for _, v in lics),
                flags=verdict.flags,
                choices=verdict.choices,
                sources=tuple(sorted(sources)),
                accepted=_accept(allow, pkg, verdict),
                gated=gate_os_packages or eco not in OS_ECOSYSTEMS,
            )
        )
    rows.sort(key=lambda r: (-RANK[r.cls], r.package, r.version))
    return rows


def render(rows: list[Row]) -> str:
    """Markdown table for the release record."""
    counts = {c: sum(1 for r in rows if r.cls == c) for c in RANK}
    failing = [r for r in rows if r.failing]
    head = [
        "# Licence report",
        "",
        f"{len(rows)} components: "
        + ", ".join(f"{counts[c]} {c}" for c in ("agpl", "gpl", "lgpl", "unknown", "dual", "ok")),
        f"Result: {'FAIL' if failing else 'PASS'} ({len(failing)} flagged without an allow-list entry)",
        "",
        "| Package | Version | Type | Licence | Flags | Accepted because |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    body = []
    for r in rows:
        if not r.flags:
            continue
        flags = ", ".join(sorted(r.flags, key=RANK.__getitem__, reverse=True))
        if r.failing:
            why = "**not allow-listed: " + ", ".join(sorted(r.open_flags)) + "**"
        elif not r.gated and r.open_flags:
            why = f"base-image {r.ecosystem} package (distro notices)"
        else:
            why = "; ".join(f"{f}: {reason}" for f, reason in sorted(r.accepted.items()))
        lic = _ws(r.licence)
        lic = (lic[:80] + "...") if len(lic) > 80 else lic  # some packages put the full text
        body.append(
            f"| {r.package} | {r.version} | {r.ecosystem} | {lic.replace('|', '/') or '(none)'} | {flags} | {why} |"
        )
    tail = ["", f"{counts['ok']} components with a permissive licence are not listed."]
    return "\n".join(head + body + tail) + "\n"
