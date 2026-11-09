"""Export ledger v1 (dataflow review P0-8, WS-08.3, D-149): one row for every file or record set that leaves the box.

Each row says what left (file name, bytes, sha256), how identifiable it is (``identifier_level``), under which
approval it left (``approval``: the approved ruleset version, the job and its requester, the console role check or
the study's REDCap link that allowed it), to whom (recipients), by which channel and who did it. The rows are
``flow.export`` events in the audit chain, so they are hash-chained, backed up with the audit folder and never
rewritten; :func:`exports` reads them back as a table ("what left this box in the last 30 days, to whom"). The
P1 ``dataops.flow`` table (WS-08.1) is filled from these same events.

Identifier levels, from least to most identifying:

* ``aggregate``: counts and tables, no row per patient (feasibility, D1 cascade numbers, sponsor packs).
* ``pseudonymised``: a row per patient keyed by a pseudonym or a screening number, no chart number or name
  (data-core ODM/CSV/XLSX, REDCap pushes).
* ``identified``: chart numbers or names (candidate workbooks, the screening log with chart numbers).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from tb_common.crypto import sha256_bytes

EVENT = "flow.export"
LEVELS = ("aggregate", "pseudonymised", "identified")
CHANNELS = ("job_output", "console_download", "console_export", "registry_export", "datacore_export", "redcap_push")


class _Audit(Protocol):
    def append(self, event: str, **fields: Any) -> dict[str, Any]: ...


@dataclass(frozen=True)
class FlowRow:
    ts: str
    channel: str
    filename: str
    sha256: str
    bytes: int
    identifier_level: str
    approval: str
    recipients: list[str] = field(default_factory=list)
    actor: str = ""
    ruleset: str | None = None
    job_id: str | None = None


def level_of_tag(tag: str) -> str:
    """A job output's tag (``aggregate`` or ``phi``) as an identifier level: a ``phi`` file is a patient list with
    chart numbers, so it is counted as identified."""
    return "aggregate" if tag == "aggregate" else "identified"


def record_export(
    audit: _Audit,
    *,
    channel: str,
    filename: str,
    data: bytes | None = None,
    sha256: str | None = None,
    nbytes: int | None = None,
    identifier_level: str,
    approval: str,
    recipients: Iterable[str] = (),
    actor: str = "",
    ruleset: str | None = None,
    ruleset_version: str | None = None,
    job_id: str | None = None,
    snapshot: str | None = None,
) -> dict[str, Any]:
    """Append one ``flow.export`` row. ``data`` or ``sha256`` names the content; an export with no approval
    reference or an unknown level is refused (ValueError) before anything leaves."""
    if identifier_level not in LEVELS:
        raise ValueError(f"identifier_level {identifier_level!r}: one of {', '.join(LEVELS)}")
    if channel not in CHANNELS:
        raise ValueError(f"channel {channel!r}: one of {', '.join(CHANNELS)}")
    if not approval.strip():
        raise ValueError("an export needs the approval it left under")
    if data is None and not sha256:
        raise ValueError("an export needs its content or its sha256")
    digest = sha256 or sha256_bytes(data or b"")
    size = nbytes if nbytes is not None else (len(data) if data is not None else 0)
    return audit.append(
        EVENT,
        job_id=job_id,
        ruleset=ruleset,
        ruleset_version=ruleset_version,
        snapshot=snapshot,
        actor=actor or None,
        output_sha=digest,
        recipients=sorted(set(recipients)),
        detail={
            "channel": channel,
            "filename": filename,
            "bytes": size,
            "identifier_level": identifier_level,
            "approval": approval,
        },
    )


def exports(audit_dir: Path, since: datetime | None = None, until: datetime | None = None) -> list[FlowRow]:
    """Every ``flow.export`` row of the audit chain in ``audit_dir``, oldest first, optionally between two times
    (timezone-aware; compared with each event's own timestamp)."""
    out: list[FlowRow] = []
    for path in sorted(audit_dir.glob("*.jsonl")):
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if f'"{EVENT}"' not in line:
                    continue
                rec = json.loads(line)
                if rec.get("event") != EVENT:
                    continue
                ts = datetime.fromisoformat(rec["ts"])
                if (since is not None and ts < since) or (until is not None and ts > until):
                    continue
                d = rec.get("detail") or {}
                out.append(
                    FlowRow(
                        ts=rec["ts"],
                        channel=str(d.get("channel") or ""),
                        filename=str(d.get("filename") or ""),
                        sha256=str(rec.get("output_sha") or ""),
                        bytes=int(d.get("bytes") or 0),
                        identifier_level=str(d.get("identifier_level") or ""),
                        approval=str(d.get("approval") or ""),
                        recipients=list(rec.get("recipients") or []),
                        actor=str(rec.get("actor") or ""),
                        ruleset=rec.get("ruleset"),
                        job_id=rec.get("job_id"),
                    )
                )
    return out
