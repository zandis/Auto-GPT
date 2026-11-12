"""T-719 (D-487; trust review TR-8): one door between a chart number and a pseudonym.

An import lint. In the orchestrator and the console, only ``orchestrator/identifiers.py`` may import the hash
(``pid_for_mrn``), open the map (``PidMap``) or name the two key files. A new use anywhere else fails here; the
exceptions are listed with their reason and the list may only shrink.
"""

from __future__ import annotations

import ast
from pathlib import Path

SERVICES = Path(__file__).resolve().parents[2] / "services"
DOOR = "orchestrator/identifiers.py"
NAMES = frozenset({"pid_for_mrn", "PidMap", "pseudonymise_bulk"})
KEY_FILES = ("site_hmac.key", "pid_map.key")
#: file -> why it is not behind the door yet. Shrinks only. (``services/sitesetup`` is another package: it hashes with
#: the key the orchestrator's door hands it, and its one caller with a chart number is ``POST /setup/pseudonym``.)
EXCEPTIONS: dict[str, str] = {}


def uses(path: Path) -> list[str]:
    """What ``path`` imports or names that only the door may: ``"<line>: <what>"``."""
    out: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            if (node.module or "").endswith("pidmap"):
                out.append(f"{node.lineno}: from {node.module} import ...")
            out += [f"{node.lineno}: import {a.name}" for a in node.names if a.name in NAMES]
        elif isinstance(node, ast.Import):
            out += [f"{node.lineno}: import {a.name}" for a in node.names if a.name.endswith("pidmap")]
        elif isinstance(node, (ast.Name, ast.Attribute)):
            name = node.id if isinstance(node, ast.Name) else node.attr
            if name in NAMES:
                out.append(f"{node.lineno}: {name}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and "\n" not in node.value:
            out += [f"{node.lineno}: {k!r}" for k in KEY_FILES if k in node.value]
    return sorted(set(out))


def test_only_the_door_touches_the_hash_the_map_and_their_keys() -> None:
    found: dict[str, list[str]] = {}
    for folder in ("orchestrator", "console"):
        for path in sorted((SERVICES / folder).rglob("*.py")):
            rel = path.relative_to(SERVICES).as_posix()
            if rel != DOOR and (hits := uses(path)):
                found[rel] = hits
    extra = {f: h for f, h in found.items() if f not in EXCEPTIONS}
    assert not extra, "identifier work outside orchestrator/identifiers.py:\n" + "\n".join(
        f"  {f}: {', '.join(h)}" for f, h in extra.items()
    )
    assert not set(EXCEPTIONS) - set(found), "an exception that is no longer needed: remove it"


def test_the_door_itself_is_seen_by_the_lint() -> None:
    """The lint finds what it looks for (it is not passing because it sees nothing)."""
    hits = " ".join(uses(SERVICES / DOOR))
    assert "pid_for_mrn" in hits and "pidmap" in hits and "'site_hmac.key'" in hits and "'pid_map.key'" in hits
