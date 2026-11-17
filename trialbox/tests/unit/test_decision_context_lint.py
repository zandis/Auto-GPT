"""T-708 (D-477; review 2026-11-12 ``decision.md`` AD-1): the decision context, enumerated.

A path that decides or counts patients reads the opt-out register, consent and the note-block decision through
``services/orchestrator/decision_context.py`` and nowhere else. A new direct read fails here: route it through
``ctx.decision`` (or, for code outside a job, :func:`orchestrator.decision_context.register_now`). A read that
stays outside is on a list below with its reason; the lists only shrink (a stale line fails too).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.guard, pytest.mark.nodb]  # D-1119: the guard step of `checks`; no database

ROOT = Path(__file__).resolve().parents[2]
MODULE = "services/orchestrator/decision_context.py"

#: a call of the register's reader (``opted_out(...)``, ``optout.opted_out(...)``); not ``drop_opted_out(`` etc.
OPTED_OUT = re.compile(r"(?<![A-Za-z0-9_])opted_out\(")
#: an import of the register module: whatever name the read then goes by (``register_now``, ``registry_state``,
#: ``OptOutRegister().effective()``, ``REGISTRY_SQL``: review of T-708, a rename no longer passes)
REGISTER_MODULE = re.compile(
    r"^\s*(?:from tb_common\.optout import|from tb_common import .*\boptout\b|import tb_common\.optout)"
)
#: a query of the lake's consent table, in either case and with a schema name (``FROM main.consent``)
FROM_CONSENT = re.compile(r"(?i)\b(?:FROM|JOIN)\s+(?:[A-Za-z_]+\.)?consent\b")
#: a read of the note-block decision or of the configured policy
NOTE_BLOCK = re.compile(r"(?<![A-Za-z0-9_])(?:effective_note_block|note_block_policy|note_block_why)\(")
PATTERNS = {
    "opted_out(": OPTED_OUT,
    "register module": REGISTER_MODULE,
    "FROM consent": FROM_CONSENT,
    "note-block read": NOTE_BLOCK,
}

#: Where each read is implemented: the library the module calls. Nothing else may be added here.
IMPLEMENTATION: dict[tuple[str, str], str] = {
    ("libs/tb_common/optout.py", "opted_out("): "the register's one reader (its definition and its docstring)",
    ("libs/tb_common/optout.py", "FROM consent"): "REGISTRY_SQL: the one consent rule, read by registry_state",
    ("services/orchestrator/scenarios/evaluate.py", "note-block read"): "the rule's definition (effective_note_block "
    "calls note_block_policy); every caller goes through the decision context",
}
#: Reads outside a job path, each with its reason. The list only shrinks.
OUTSIDE: dict[tuple[str, str], str] = {
    ("services/console/reveal.py", "opted_out("): "the console's reveal guard reads the register as it stands now; "
    "the console has no job context (T-719 moves identifiers behind one module)",
    ("services/console/reveal.py", "register module"): "the same read (its import)",
    ("services/patient_profile/twin.py", "opted_out("): "the twin builder runs after an ingest, outside a job; it "
    "reads the same one function (with merged charts)",
    ("services/patient_profile/twin.py", "register module"): "the same read (its import)",
    ("services/omop/export.py", "register module"): "the as-of export (T-728) tombstones the patients opted out "
    "now; another service, no job: tb_common.optout.register_now, the door for code outside the orchestrator",
    ("services/orchestrator/app.py", "register module"): "wires the reader into the EDC service as its check at "
    "send time (a reference handed over, called per send)",
    ("services/matching/cascade/engine.py", "register module"): "the cascade's fallback for a caller with no "
    "context (a tool, a test): registry_state, the one rule; a job passes the context's own read (cfg.registry)",
    ("services/datacore/optout_worker.py", "register module"): "the opt-out worker: it applies the register to "
    "the stores and syncs it with the hospital registry (the register's own writer)",
    ("services/console/team.py", "register module"): "the research office's page: it writes the register and "
    "lists it (effective(), merged charts)",
    ("tools/trialbox/backup.py", "register module"): "backup and restore of the register's own table and actor "
    "name; it decides nothing about a patient",
}
#: Lines the patterns match that read nothing (prose).
NOT_A_READ: dict[tuple[str, str], str] = {
    ("services/console/i18n_life.py", "FROM consent"): 'a sentence of the page ("from consent")',
    ("services/console/migrate_stores.py", "register module"): "db-up's migration step (D-921) opens the register's "
    "store to apply its schema versions and closes it; it reads no row and decides nothing about a patient",
}


def _rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def _code() -> list[Path]:
    out: list[Path] = []
    for d in ("services", "libs", "tools"):
        out += [p for p in (ROOT / d).rglob("*.py")
                if "/tests/" not in _rel(p) and not p.name.startswith("test_") and "/.venv/" not in _rel(p)]  # fmt: skip
    return sorted(out)


def _hits() -> dict[tuple[str, str], list[int]]:
    found: dict[tuple[str, str], list[int]] = {}
    for p in _code():
        rel = _rel(p)
        if rel == MODULE:
            continue
        for no, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            for name, pat in PATTERNS.items():
                if pat.search(line):
                    found.setdefault((rel, name), []).append(no)
    return found


def test_the_register_consent_and_the_note_block_are_read_through_the_decision_context() -> None:
    hits = _hits()
    allowed = {**IMPLEMENTATION, **OUTSIDE, **NOT_A_READ}
    stray = {f"{rel}:{nos[0]} ({name})" for (rel, name), nos in hits.items() if (rel, name) not in allowed}
    assert not stray, (
        "read outside the decision context (use ctx.decision, or orchestrator.decision_context.register_now "
        f"outside a job): {sorted(stray)}"
    )


def test_the_lists_hold_no_stale_line() -> None:
    hits = _hits()
    stale = sorted(
        f"{rel} ({name})" for (rel, name) in {**IMPLEMENTATION, **OUTSIDE, **NOT_A_READ} if (rel, name) not in hits
    )
    assert not stale, f"no longer read there: remove the line(s) {stale}"
    assert not set(IMPLEMENTATION) & set(OUTSIDE)
    assert len(OUTSIDE) <= 10, "the list of reads outside the decision context only shrinks"


def test_the_module_is_the_reader() -> None:
    """Not vacuous: the module itself reads all three, and a job context hands it out."""
    text = (ROOT / MODULE).read_text(encoding="utf-8")
    assert "opted_out(" in text and "registry_state(" in text and "note_block_why(" in text
    core = (ROOT / "services/orchestrator/core.py").read_text(encoding="utf-8")
    assert "def decision(self) -> DecisionContext" in core


def test_the_patterns_catch_what_they_name() -> None:
    assert OPTED_OUT.search("gone = opted_out(as_of=x)") and OPTED_OUT.search("x = optout.opted_out()")
    assert not OPTED_OUT.search("kept = drop_opted_out(ctx, scoped)")
    assert not OPTED_OUT.search("self._not_opted_out(rs, by)")
    assert FROM_CONSENT.search('"SELECT pid FROM consent WHERE 1=1"') and not FROM_CONSENT.search("FROM consents")
    assert FROM_CONSENT.search("LEFT JOIN consent c ON")
    # review of T-708: a lower-case query and a schema name are caught (prose that matches is on NOT_A_READ)
    assert FROM_CONSENT.search('"select pid from consent"') and FROM_CONSENT.search("FROM main.consent c")
    for line in (
        "from tb_common.optout import register_now",
        "    from tb_common.optout import OptOutRegister, registry_state",
        "from tb_common import audit, optout",
        "import tb_common.optout as oo",
    ):
        assert REGISTER_MODULE.search(line), line
    assert not REGISTER_MODULE.search("from orchestrator.decision_context import register_now")
    assert NOTE_BLOCK.search("may = effective_note_block(judge)[0]") and NOTE_BLOCK.search("p = note_block_policy()")
    assert not NOTE_BLOCK.search("nb = decision.note_block(judge)")
