"""Licence report from CycloneDX SBOMs (D-186): flags GPL, LGPL and AGPL.

Each component's licence (SPDX id, name or expression, as Syft recorded it) is put in one class:

* ``agpl`` / ``gpl`` / ``lgpl``: copyleft; flagged. A flagged package passes only with an allow-list entry for that
  package and that class, with a reason (how the obligations are met, e.g. "unmodified, listed in the notices").
* ``ok``: no copyleft term found.
* ``unknown``: the SBOM has no licence; listed for a human to check, does not fail.

``A OR B`` takes the most permissive branch (dulwich: ``Apache-2.0 OR GPL-2.0-or-later`` is ``ok``, noted as dual);
``A AND B`` and several licences on one component take the strictest. ``WITH`` exceptions keep the class (the JRE's
GPL-2.0 WITH Classpath-exception-2.0 is still flagged ``gpl`` and needs its entry). A long free text (some packages
put the whole licence in the field) is classed by its first 400 characters, where a licence names itself; its
warranty disclaimer's capital "OR" is not an expression.

Distro packages of a base image (deb, apk, rpm) are listed but do not fail unless ``--gate-os-packages``: they come
unmodified with the image and are covered by the distro's own notices.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from tools.supply_chain.allowlist import Allowlist, norm

RANK = {"ok": 0, "unknown": 1, "lgpl": 2, "gpl": 3, "agpl": 4}
FLAGGED = ("lgpl", "gpl", "agpl")

_AGPL = re.compile(r"\bAGPL|Affero", re.IGNORECASE)
_LGPL = re.compile(r"\bLGPL|Lesser General Public|Library General Public", re.IGNORECASE)
_GPL = re.compile(r"\bGPL|General Public License", re.IGNORECASE)
_MAX_EXPR = 200  # longer than any SPDX expression in practice: free text
_HEAD = 400


def classify_one(text: str) -> str:
    """Class of a single licence id or name (no OR/AND)."""
    t = text.strip().strip("()").strip()
    if not t:
        return "unknown"
    if _AGPL.search(t):
        return "agpl"
    if _LGPL.search(t):
        return "lgpl"
    if _GPL.search(t):
        return "gpl"
    return "ok"


def classify(expr: str) -> tuple[str, bool]:
    """(class, dual) of an SPDX-like expression: OR takes the most permissive branch, AND the strictest.

    ``dual`` is True when an OR chose a permissive branch over a copyleft one. Anything that does not parse as an
    expression (a licence name with spaces, unbalanced parentheses) is classed as one text.
    """
    if len(expr) > _MAX_EXPR or "\n" in expr:
        return classify_one(expr[:_HEAD]), False
    if not expr.strip():
        return "unknown", False
    tokens = _TOKEN.findall(expr)
    if " OR " in expr or " AND " in expr or "(" in expr:
        try:
            pos, result = _parse_or(tokens, 0)
            if pos == len(tokens):
                return result
        except _ParseError:
            pass
    return classify_one(expr.split(" WITH ", maxsplit=1)[0]), False


class _ParseError(ValueError):
    pass


_TOKEN = re.compile(r"\(|\)|[^\s()]+")


def _parse_or(toks: list[str], i: int) -> tuple[int, tuple[str, bool]]:
    i, first = _parse_and(toks, i)
    parts = [first]
    while i < len(toks) and toks[i] == "OR":
        i, nxt = _parse_and(toks, i + 1)
        parts.append(nxt)
    if len(parts) == 1:
        return i, first
    best = min((c for c, _ in parts), key=RANK.__getitem__)
    worst = max((c for c, _ in parts), key=RANK.__getitem__)
    return i, (best, any(d for _, d in parts) or (best not in FLAGGED and worst in FLAGGED))


def _parse_and(toks: list[str], i: int) -> tuple[int, tuple[str, bool]]:
    i, first = _parse_atom(toks, i)
    parts = [first]
    while i < len(toks) and toks[i] == "AND":
        i, nxt = _parse_atom(toks, i + 1)
        parts.append(nxt)
    return i, (max((c for c, _ in parts), key=RANK.__getitem__), any(d for _, d in parts))


def _parse_atom(toks: list[str], i: int) -> tuple[int, tuple[str, bool]]:
    if i >= len(toks) or toks[i] in ("AND", "OR", "WITH", ")"):
        raise _ParseError(f"licence expected at token {i}")
    if toks[i] == "(":
        i, inner = _parse_or(toks, i + 1)
        if i >= len(toks) or toks[i] != ")":
            raise _ParseError("unbalanced parentheses")
        return i + 1, inner
    cls = classify_one(toks[i])
    i += 1
    if i < len(toks) and toks[i] == "WITH":  # an exception keeps the class of the licence it modifies
        if i + 1 >= len(toks) or toks[i + 1] in ("AND", "OR", "WITH", "(", ")"):
            raise _ParseError("exception expected after WITH")
        i += 2
    return i, (cls, False)


def component_licences(comp: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for entry in comp.get("licenses") or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("expression"):
            out.append(str(entry["expression"]))
            continue
        lic = entry.get("license") or {}
        val = lic.get("id") or lic.get("name")
        if val:
            out.append(str(val))
    return out


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
    cls: str
    dual: bool
    sources: tuple[str, ...]
    accepted: str | None  # the allow-list reason when a flagged row is accepted
    gated: bool  # False for distro packages of a base image unless --gate-os-packages

    @property
    def licence(self) -> str:
        """The component's licences joined with " AND ", for the report."""
        return " AND ".join(self.licences)

    @property
    def failing(self) -> bool:
        return self.gated and self.cls in FLAGGED and self.accepted is None


def report(sboms: dict[str, dict[str, Any]], allow: Allowlist, *, gate_os_packages: bool = False) -> list[Row]:
    """One row per (package, version, licences) across the SBOMs, sorted strictest first.

    Distro packages (deb, apk, rpm) come unmodified with a base image and are covered by the distro's own notices:
    they are listed but do not fail unless ``gate_os_packages``.
    """
    seen: dict[tuple[str, str, str, tuple[str, ...]], set[str]] = {}
    for source, doc in sboms.items():
        for comp in doc.get("components") or []:
            if comp.get("type") not in (None, "library", "application", "framework"):
                continue
            name = str(comp.get("name", "")).strip()
            if not name:
                continue
            key = (norm(name), str(comp.get("version", "")), ecosystem(comp), tuple(component_licences(comp)))
            seen.setdefault(key, set()).add(source)
    rows = []
    for (pkg, version, eco, lics), sources in seen.items():
        if lics:
            per = [classify(x) for x in lics]
            cls = max((c for c, _ in per), key=RANK.__getitem__)  # several licence entries: the strictest
            dual = any(d for _, d in per)
        else:
            cls, dual = "unknown", False
        entry = allow.licence(pkg, cls) if cls in FLAGGED else None
        gated = gate_os_packages or eco not in OS_ECOSYSTEMS
        rows.append(
            Row(pkg, version, eco, lics, cls, dual, tuple(sorted(sources)), entry.reason if entry else None, gated)
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
        f"{len(rows)} components: " + ", ".join(f"{counts[c]} {c}" for c in ("agpl", "gpl", "lgpl", "unknown", "ok")),
        f"Result: {'FAIL' if failing else 'PASS'} ({len(failing)} flagged without an allow-list entry)",
        "",
        "| Package | Version | Type | Licence | Class | Accepted because |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    body = []
    for r in rows:
        if r.cls == "ok" and not r.dual:
            continue
        cls = r.cls.upper() + (" (dual)" if r.dual else "")
        why = r.accepted or ("**not allow-listed**" if r.failing else "")
        if not r.gated and r.cls in FLAGGED and not r.accepted:
            why = f"base-image {r.ecosystem} package (distro notices)"
        lic = (r.licence[:80] + "...") if len(r.licence) > 80 else r.licence  # some packages put the full text
        body.append(
            f"| {r.package} | {r.version} | {r.ecosystem} | {lic.replace('|', '/') or '(none)'} | {cls} | {why} |"
        )
    tail = ["", f"{counts['ok']} components with a permissive licence are not listed."]
    return "\n".join(head + body + tail) + "\n"
