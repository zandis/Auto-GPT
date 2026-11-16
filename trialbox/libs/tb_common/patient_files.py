"""Whether a job's patient-level files name a patient on the opt-out register (NEW-MAIL-1, D-863).

One judgment, used by the orchestrator's answer to the mail gateway (``GET /jobs/{job_id}/outputs-current``) and by
the opt-out worker's clear of a held mail (``held_mail``): a per-patient file (a TWPAS bundle, a draft) by its own
patient, named by the 12 to 32 hex characters that end its name; a text file by its content, in any case; a
compressed file (a PDF, a workbook, a zip) by the text list mailed with it, else by the job's text list of the
same name, else by all of the job's text lists, and with no text list to judge it by it counts as
naming one (fail closed, as the console's D-860 rule). A file of counts (``tag`` ``aggregate``) names no one. This
module reads no register: the caller passes the pseudonyms opted out now."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import Any

#: the reason the mail gateway holds a mail whose job's outputs name a patient opted out since they were made; the
#: opt-out worker's ``held_mail`` clear finds the held mail by it
HELD = "opted out: a patient on this mail opted out since it was made; not sent"
TEXT = (".json", ".jsonl", ".html", ".htm", ".csv", ".txt", ".yaml", ".md")  # as the console (D-860)
_OWNER = re.compile(r"_([0-9a-f]{12,32})$")

Read = Callable[[str], bytes]


def _owner(filename: str) -> str | None:
    hit = _OWNER.search(filename.rsplit(".", 1)[0].lower())
    return hit.group(1) if hit else None


def _text_names(read: Read, key: str, low: set[str]) -> bool:
    text = bytes(read(key)).lower()
    return any(p.encode("ascii") in text for p in low)


def owner_of(filename: str) -> str | None:
    """The pseudonym prefix a per-patient file's name ends in, or None (a list, a sheet of counts)."""
    return _owner(filename)


def _stem(filename: str) -> str:
    return filename.rsplit(".", 1)[0].lower()


def naming(read: Read, files: Iterable[Any], outputs: Iterable[Any], gone: frozenset[str]) -> list[str]:
    """The object keys of ``files`` (each with ``filename``, ``minio_key`` and maybe ``tag``) that name a patient in
    ``gone``. A compressed file is judged by the text lists among ``outputs`` (the job's own outputs), the one
    mailed with it first. ``read`` raises for a file it cannot read; the caller decides what that means (the mail
    fails closed)."""
    if not gone:
        return []
    low = {p.lower() for p in gone}
    lists = [
        t
        for t in outputs
        if getattr(t, "tag", "phi") != "aggregate" and _owner(t.filename) is None and t.filename.lower().endswith(TEXT)
    ]
    files = list(files)
    carried = {f.minio_key for f in files}
    said: dict[str, bool] = {}

    def names(key: str) -> bool:
        if key not in said:
            said[key] = _text_names(read, key, low)
        return said[key]

    out: list[str] = []
    for f in files:
        if getattr(f, "tag", "phi") == "aggregate":
            continue
        owner = _owner(f.filename)
        if owner is not None:
            hit = any(p.startswith(owner) for p in low)
        elif f.filename.lower().endswith(TEXT):
            hit = names(f.minio_key)
        else:
            # the list mailed with it, else the list of its own name, else every list of the job
            mine = (
                [t for t in lists if t.minio_key in carried]
                or [t for t in lists if _stem(t.filename) == _stem(f.filename)]
                or lists
            )
            hit = not mine or any(names(t.minio_key) for t in mine)  # nothing to judge it by: names one
        if hit:
            out.append(f.minio_key)
    return out
