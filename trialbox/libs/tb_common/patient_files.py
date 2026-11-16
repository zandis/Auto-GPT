"""Whether a job's patient-level files name a patient on the opt-out register (NEW-MAIL-1, D-863).

One judgment, used by the orchestrator's answer to the mail gateway (``GET /jobs/{job_id}/outputs-current``) and by
the opt-out worker's clear of a held mail (``held_mail``): a per-patient file (a TWPAS bundle, a draft) by its own
patient, named by the 12 to 32 hex characters that end its name; a text file by its content, in any case; a
compressed file (a PDF, a zip) by the job's text files, which list the same patients. A mail of counts (``tag``
``aggregate``) names no one. This module reads no register: the caller passes the pseudonyms opted out now."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import Any

#: the reason the mail gateway holds a mail whose job's outputs name a patient opted out since they were made; the
#: opt-out worker's ``held_mail`` clear finds the held mail by it
HELD = "opted out: a patient on this mail opted out since it was made; not sent"
TEXT = (".json", ".jsonl", ".html", ".htm", ".csv", ".txt", ".md")
_OWNER = re.compile(r"_([0-9a-f]{12,32})$")

Read = Callable[[str], bytes]


def _owner(filename: str) -> str | None:
    hit = _OWNER.search(filename.rsplit(".", 1)[0].lower())
    return hit.group(1) if hit else None


def _text_names(read: Read, key: str, low: set[str]) -> bool:
    text = bytes(read(key)).lower()
    return any(p.encode("ascii") in text for p in low)


def naming(read: Read, files: Iterable[Any], outputs: Iterable[Any], gone: frozenset[str]) -> list[str]:
    """The object keys of ``files`` (each with ``filename``, ``minio_key`` and maybe ``tag``) that name a patient in
    ``gone``. A compressed file is judged by the text files among ``outputs`` (the job's own outputs). ``read`` raises
    for a file it cannot read; the caller decides what that means (the answer to the mail fails closed)."""
    if not gone:
        return []
    low = {p.lower() for p in gone}
    outs = [f for f in outputs if getattr(f, "tag", "phi") != "aggregate"]
    lists: bool | None = None  # whether the job's text files name one (read once, when a compressed file asks)
    out: list[str] = []
    for f in files:
        if getattr(f, "tag", "phi") == "aggregate":
            continue
        owner = _owner(f.filename)
        if owner is not None:
            hit = any(p.startswith(owner) for p in low)
        elif f.filename.lower().endswith(TEXT):
            hit = _text_names(read, f.minio_key, low)
        else:
            if lists is None:
                lists = any(
                    _owner(t.filename) is None
                    and t.filename.lower().endswith(TEXT)
                    and _text_names(read, t.minio_key, low)
                    for t in outs
                )
            hit = lists
        if hit:
            out.append(f.minio_key)
    return out
