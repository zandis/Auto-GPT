"""Candidate registry: where the study team is with each patient for one ruleset (D-92).

The registry is the pseudonymous screening and enrolment log a CRA asks for (ICH E6(R3) 3.16, the site's
"screening log"), kept per approved ruleset. A row is a pseudonym plus a status; every change is an event with who,
when and why, and an audit record. Rows arrive three ways: added by hand with a chart number (the box resolves it to
the pseudonym and discards it), promoted from a SCREEN job's candidate pool, or from a CASE check. The export resolves
the chart numbers from the in-box pid map for the site's own log; the registry itself never stores one.

What it is not: not an EDC, no visit data, and the consent status in it is the coordinator's note, not the consent
record (D-88: TrialBox stays outside the regulated e-record).
"""

from __future__ import annotations

import io
import re
from datetime import datetime
from pathlib import Path

from tb_common.audit import AuditLog
from tb_common.crypto import pid_for_mrn
from tb_common.deterministic import normalize_ooxml
from tb_contracts import RegistryEntry, RegistryEvent, RegistryPromote, RegistrySummary, RegistryUpdate

from orchestrator.db import JobDB

STATUSES: tuple[str, ...] = ("candidate", "contacted", "consented", "enrolled", "screen_fail", "declined", "withdrawn")
# any status may go back to an earlier one (a coordinator corrects a mistake), except that enrolled is final unless
# withdrawn: the registry never decides, it records; the list keeps clerical errors fixable and the log honest
FORWARD: dict[str, tuple[str, ...]] = {
    "candidate": ("contacted", "consented", "screen_fail", "declined", "withdrawn"),
    "contacted": ("candidate", "consented", "screen_fail", "declined", "withdrawn"),
    "consented": ("candidate", "contacted", "enrolled", "screen_fail", "declined", "withdrawn"),
    "enrolled": ("withdrawn", "consented"),
    "screen_fail": ("candidate", "contacted", "consented"),
    "declined": ("candidate", "contacted"),
    "withdrawn": ("candidate", "consented", "enrolled"),
}
_RULESET = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,15}$")


class RegistryError(ValueError):
    pass


class CandidateRegistry:
    def __init__(self, db: JobDB, audit: AuditLog, secrets_dir: Path, mrn_regex: str | None = None) -> None:
        self.db = db
        self.audit = audit
        self.secrets_dir = secrets_dir
        self.mrn_regex = mrn_regex

    # ------------------------------------------------------------------ identity
    def pid_for(self, upd: RegistryUpdate) -> str:
        if upd.pid and upd.mrn:
            raise RegistryError("give the pseudonym or the chart number, not both")
        if upd.pid:
            if not re.match(r"^[0-9a-f]{8,64}$", upd.pid):
                raise RegistryError("pseudonyms are 8 to 64 hex characters")
            return upd.pid
        if not upd.mrn:
            raise RegistryError("a chart number (mrn) or a pseudonym (pid) is needed")
        if self.mrn_regex and not re.match(self.mrn_regex, upd.mrn):
            raise RegistryError("that does not look like a chart number of this site")
        key = self.secrets_dir / "site_hmac.key"
        if not key.exists():
            raise RegistryError("the box has no site key yet (no ingest has run), so chart numbers cannot be resolved")
        return pid_for_mrn(key.read_bytes(), upd.mrn)

    def mrns(self, pids: list[str]) -> dict[str, str]:
        db, key = self.secrets_dir / "pid_map.sqlite", self.secrets_dir / "pid_map.key"
        if not db.exists() or not key.exists() or not pids:
            return {}
        from adapter.pidmap import PidMap

        pm = PidMap(db, key)
        try:
            return pm.resolve_many(pids)
        finally:
            pm.close()

    # ------------------------------------------------------------------ reads
    def summaries(self) -> list[RegistrySummary]:
        return [RegistrySummary.model_validate(s) for s in self.db.candidate_summaries()]

    def rows(self, ruleset: str) -> list[RegistryEntry]:
        return [RegistryEntry.model_validate(r) for r in self.db.candidates(check_ruleset(ruleset))]

    def events(self, ruleset: str, pid: str | None = None) -> list[RegistryEvent]:
        return [RegistryEvent.model_validate(e) for e in self.db.candidate_events(check_ruleset(ruleset), pid)]

    # ------------------------------------------------------------------ writes
    def update(self, ruleset: str, upd: RegistryUpdate, now: datetime) -> RegistryEntry:
        ruleset = check_ruleset(ruleset)
        pid = self.pid_for(upd)
        prev = self.db.candidate_get(ruleset, pid)
        if prev is not None and prev["status"] != upd.status and upd.status not in FORWARD[str(prev["status"])]:
            raise RegistryError(f"{prev['status']} -> {upd.status} is not a recorded transition")
        if prev is not None and prev["status"] == upd.status and not upd.reason:
            raise RegistryError(f"already {upd.status}; add a reason to record a note")
        row = self.db.candidate_set(
            ruleset,
            pid,
            upd.status,
            (upd.reason or "").strip()[:500] or None,
            upd.by,
            now.isoformat(timespec="seconds"),
            upd.source or "manual",
            upd.source_job,
        )
        self.audit.append(
            "registry.update",
            ruleset=ruleset,
            actor=upd.by,
            job_id=upd.source_job,
            detail={"pid": pid, "status": upd.status, "previous": prev["status"] if prev else None},
        )
        return RegistryEntry.model_validate(row)

    def promote(self, ruleset: str, req: RegistryPromote, now: datetime) -> int:
        """Add the ruleset's current SCREEN pool rows (D-92: tiers high and review) that the registry lacks."""
        ruleset = check_ruleset(ruleset)
        tiers = set(req.tiers or ["high", "review"])
        have = {r["pid"] for r in self.db.candidates(ruleset)}
        added = 0
        for p in self.db.pool(ruleset):
            if p["tier"] not in tiers or p["pid"] in have:
                continue
            self.db.candidate_set(
                ruleset,
                str(p["pid"]),
                "candidate",
                None,
                req.by,
                now.isoformat(timespec="seconds"),
                "screen",
                str(p["job_id"]),
                tier=str(p["tier"]),
            )
            added += 1
        self.audit.append(
            "registry.promote", ruleset=ruleset, actor=req.by, detail={"added": added, "tiers": sorted(tiers)}
        )
        return added

    # ------------------------------------------------------------------ export
    def export_xlsx(self, ruleset: str, site_id: str) -> bytes:
        """The site's screening log: pseudonym, chart number (resolved in-box), status, dates, reasons; deterministic
        OOXML (D-82) so a re-export of an unchanged registry is byte-identical. PHI (chart numbers)."""
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill

        ruleset = check_ruleset(ruleset)
        rows = self.db.candidates(ruleset)
        events = self.db.candidate_events(ruleset)
        mrns = self.mrns([str(r["pid"]) for r in rows])
        wb = Workbook()
        wb.properties.creator = f"TrialBox {site_id}"
        wb.properties.title = f"screening log {ruleset}"
        ws = wb.active
        assert ws is not None
        ws.title = "screening_log"
        head = ["MRN", "pid", "status", "reason", "updated_at", "updated_by", "source", "source_job", "tier", "changes"]
        ws.append(head)
        for c in ws[1]:
            c.font = Font(bold=True)
            c.fill = PatternFill("solid", fgColor="DCE6F1")
        for r in sorted(rows, key=lambda x: (str(x["updated_at"]), str(x["pid"]))):
            ws.append(
                [
                    mrns.get(str(r["pid"]), ""),
                    r["pid"],
                    r["status"],
                    r["reason"] or "",
                    r["updated_at"],
                    r["updated_by"],
                    r["source"],
                    r["source_job"] or "",
                    r["tier"] or "",
                    r["events"],
                ]
            )
        ev = wb.create_sheet("events")
        ev.append(["at", "MRN", "pid", "status", "previous", "reason", "by", "source_job"])
        for e in events:
            ev.append(
                [
                    e["at"],
                    mrns.get(str(e["pid"]), ""),
                    e["pid"],
                    e["status"],
                    e["previous"] or "",
                    e["reason"] or "",
                    e["by"],
                    e["source_job"] or "",
                ]
            )
        legend = wb.create_sheet("about")
        legend.append(["TrialBox candidate registry export"])
        legend.append(["ruleset", ruleset])
        legend.append(["statuses", ", ".join(STATUSES)])
        legend.append(["note", "Pseudonymous log kept on the box; chart numbers resolved from the site's pid map."])
        legend.append(["note", "Consent status is the coordinator's note, not the consent record."])
        from openpyxl.utils import get_column_letter

        for sheet in (ws, ev):
            for col in range(1, sheet.max_column + 1):
                sheet.column_dimensions[get_column_letter(col)].width = 18
        buf = io.BytesIO()
        wb.save(buf)
        return normalize_ooxml(buf.getvalue())


def check_ruleset(ruleset: str) -> str:
    r = (ruleset or "").upper()
    if not _RULESET.match(r):
        raise RegistryError(f"invalid ruleset id {ruleset!r}")
    return r


def counts(rows: list[RegistryEntry]) -> dict[str, int]:
    out = dict.fromkeys(STATUSES, 0)
    for r in rows:
        out[r.status] = out.get(r.status, 0) + 1
    return out


__all__ = ["FORWARD", "STATUSES", "CandidateRegistry", "RegistryError", "check_ruleset", "counts"]
