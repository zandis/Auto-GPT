"""Study, site and subject names the administrator saves (contract version 1).

A TrialBox study ref maps to an EDC project id. A site maps to a data access group. A subject maps to the study
record id, which is not a chart number.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()


def map_path(folder: str) -> Path:
    return Path(folder) / "edc-map.json"


def empty() -> dict[str, Any]:
    return {"studies": {}, "sites": {}, "subjects": {}}


def load(folder: str) -> dict[str, Any]:
    path = map_path(folder)
    if not folder or not path.exists():
        return empty()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty()
    if not isinstance(doc, dict):
        return empty()
    out = empty()
    for key in ("studies", "sites", "subjects"):
        raw = doc.get(key)
        if isinstance(raw, dict):
            out[key] = {str(k): (dict(v) if isinstance(v, dict) else str(v)) for k, v in raw.items()}
    return out


def save(folder: str, doc: dict[str, Any]) -> None:
    if not folder:
        raise ValueError("TB_EDC_EVENT_DIR is not set")
    path = map_path(folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    kept = empty()
    kept["studies"] = {
        str(k).strip().upper(): str(v).strip() for k, v in (doc.get("studies") or {}).items() if str(v).strip()
    }
    kept["sites"] = {str(k).strip(): str(v).strip() for k, v in (doc.get("sites") or {}).items() if str(v).strip()}
    subjects: dict[str, dict[str, str]] = {}
    for study, rows in (doc.get("subjects") or {}).items():
        if not isinstance(rows, dict):
            continue
        subjects[str(study).strip().upper()] = {
            str(k).strip(): str(v).strip() for k, v in rows.items() if str(k).strip() and str(v).strip()
        }
    kept["subjects"] = subjects
    data = json.dumps(kept, ensure_ascii=False, indent=2).encode("utf-8")
    with _LOCK:
        # H-137: written whole to a 0600 temp file beside the map and renamed over it: no reader sees a torn or
        # group-readable map, and a failed write leaves the saved one as it was
        fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
        folder_fd = os.open(path.parent, os.O_RDONLY)  # the rename itself survives a power cut
        try:
            os.fsync(folder_fd)
        finally:
            os.close(folder_fd)


def study_for_project(folder: str, project_id: str) -> str:
    want = project_id.strip()
    for study, pid in load(folder)["studies"].items():
        if pid == want:
            return str(study)
    return ""
