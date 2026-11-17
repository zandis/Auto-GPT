"""Study, site and subject names the administrator saves (contract version 1).

A TrialBox study ref maps to an EDC project id. A site maps to a data access group. A subject maps to the study
record id, which is not a chart number.
"""

from __future__ import annotations

import json
import os
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
    with _LOCK:
        path.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(path, 0o600)


def study_for_project(folder: str, project_id: str) -> str:
    want = project_id.strip()
    for study, pid in load(folder)["studies"].items():
        if pid == want:
            return str(study)
    return ""
