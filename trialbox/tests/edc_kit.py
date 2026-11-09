"""Shared synthetic material for the EDC prefill tests (D-160): a small gout CRF, a REDCap simulator project for it,
a fixed hospital record (no real patient), and a service wired to both. Nothing here is real data."""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from datacore.store import DataCore
from edc.prefill import gateway_drafter
from edc.service import EdcService
from edc.store import EdcStore
from fastapi.testclient import TestClient
from rc_bridge.client import RedcapClient
from rc_sim.app import create_app
from tb_common.audit import AuditLog

STUDY = "GZQO"
STAMP = datetime(2026, 11, 9, 10, 0, tzinfo=UTC)
TODAY = date(2026, 11, 9)
VISIT_DATE = "2026-11-05"
PID = "p-0001"
RECORD = "S-001"

CRF: list[dict[str, str]] = [
    {"field_name": "record_id", "form_name": "demographics", "field_type": "text", "field_label": "Record ID"},
    {"field_name": "tb_screening_no", "form_name": "demographics", "field_type": "text",
     "field_label": "Screening number"},
    {"field_name": "brthdat", "form_name": "demographics", "field_type": "text", "field_label": "Birth date",
     "text_validation_type_or_show_slider_number": "date_ymd", "field_label:ja": "生年月日"},
    {"field_name": "sex", "form_name": "demographics", "field_type": "radio", "field_label": "Sex",
     "select_choices_or_calculations": "1, Male | 2, Female"},
    {"field_name": "pt_initials", "form_name": "demographics", "field_type": "text", "field_label": "Initials",
     "identifier": "y"},
    {"field_name": "weight", "form_name": "baseline", "field_type": "text", "field_label": "Body weight (kg)",
     "text_validation_type_or_show_slider_number": "number", "text_validation_min": "20",
     "text_validation_max": "300"},
    {"field_name": "urate", "form_name": "baseline", "field_type": "text", "field_label": "Serum uric acid (mg/dL)",
     "text_validation_type_or_show_slider_number": "number"},
    {"field_name": "mh_gout", "form_name": "baseline", "field_type": "yesno", "field_label": "History of gout"},
    {"field_name": "cm_allo", "form_name": "baseline", "field_type": "yesno", "field_label": "Allopurinol (medication)"},
    {"field_name": "tophus", "form_name": "baseline", "field_type": "yesno", "field_label": "Tophus present"},
    {"field_name": "comments", "form_name": "baseline", "field_type": "notes", "field_label": "Comments"},
]  # fmt: skip

MAP: list[dict[str, Any]] = [
    {"item": "brthdat", "cdash": "DM.BRTHDAT", "source": "patient", "what": "birth_date"},
    {"item": "sex", "cdash": "DM.SEX", "source": "patient", "what": "sex", "sex_codes": {"male": "1", "female": "2"}},
    {"item": "weight", "cdash": "VS.VSORRES", "test": "WEIGHT", "source": "observation", "what": "value",
     "codes": ["29463-7"], "system": "http://loinc.org", "unit": "kg", "window_days": 30},
    {"item": "urate", "cdash": "LB.LBORRES", "test": "URATE", "source": "observation", "what": "value",
     "codes": ["3084-1"], "system": "http://loinc.org", "unit": "mg/dL", "window_days": 90},
    {"item": "mh_gout", "cdash": "MH.MHOCCUR", "source": "condition", "what": "presence", "codes": ["M10"],
     "window_days": 0},
    {"item": "cm_allo", "cdash": "CM.CMOCCUR", "source": "medication", "what": "presence", "codes": ["M04AA01"],
     "window_days": 0},
    {"item": "tophus", "cdash": "MH.MHOCCUR", "source": "note", "what": "value", "question": "tophus|痛風結節",
     "window_days": 365},
    {"item": "comments"},
]  # fmt: skip
TARGET = {"token_ref": "edc", "key_field": "tb_screening_no", "id_field": "record_id"}
ACK = {"kind": "sponsor_letter", "reference": "SPN-2026-041", "ack_date": "2026-11-01", "reentry_pages": 30,
       "reentry_accuracy": 0.985}  # fmt: skip


def dictionary_csv() -> str:
    cols = sorted({k for r in CRF for k in r}, key=lambda k: (k != "field_name", k != "form_name", k))
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    for r in CRF:
        w.writerow(r)
    return buf.getvalue()


class FakeFacts:
    """One synthetic patient's record, shaped as ``edc.prefill.LakeFacts`` returns it."""

    def __init__(self) -> None:
        self.patients = {PID: {"pid": PID, "birth_date": date(1960, 5, 1), "sex": "M"}}
        self.data: dict[str, list[dict[str, Any]]] = {
            "observation": [
                {"row": "o1", "code": "29463-7", "d": date(2026, 11, 1), "value_num": 72.5, "unit": "kg", "cmp": ""},
                {"row": "o2", "code": "3084-1", "d": date(2026, 10, 20), "value_num": 8.4, "unit": "mg/dL",
                 "cmp": ""},
                {"row": "o3", "code": "3084-1", "d": date(2026, 6, 1), "value_num": 9.1, "unit": "mg/dL", "cmp": ""},
            ],
            "condition": [{"row": "c1", "code": "M10.9", "d": date(2024, 1, 10), "status": "active"}],
            "medication": [],
        }  # fmt: skip
        self.facts: list[dict[str, Any]] = [
            {"fid": "f1", "domain": "medication", "code": "M04AA01", "d": date(2026, 10, 1), "basis": "proposed"},
        ]
        self.note_rows: list[dict[str, Any]] = [
            {
                "row": "n1",
                "d": date(2026, 10, 20),
                "type": "progress",
                "text": "Gout clinic.\nTophus on the right ear.",
            },
        ]

    def snapshot(self) -> str:
        return "snap-1"

    def patient(self, pid: str) -> dict[str, Any] | None:
        return self.patients.get(pid)

    def rows(self, pid: str, source: str) -> list[dict[str, Any]]:
        return list(self.data.get(source, [])) if pid in self.patients else []

    def site_facts(self, pid: str) -> list[dict[str, Any]]:
        return list(self.facts) if pid in self.patients else []

    def notes(self, pid: str, until: date) -> list[dict[str, Any]]:
        return [n for n in self.note_rows if n["d"] <= until] if pid in self.patients else []


class StubLlm:
    """The gateway stand-in: the stub's own handler, as the box's ``llm_stub`` answers."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def chat_json(self, prompt_id: str, variables: dict[str, Any], schema: str | None = None, **_: Any) -> Any:
        from llm_stub.handlers import HANDLERS

        self.calls.append(variables)

        class R:
            data = HANDLERS[prompt_id](variables)
            prompt_version = "1"

        return R()


def sim_project(sim: Any, records: list[dict[str, str]] | None = None, events: list[str] | None = None) -> str:
    """A REDCap project for the CRF in the simulator; answers its token."""
    c = TestClient(sim)
    r = c.post("/sim/projects", json={"title": "GZQO CRF", "metadata": CRF, "events": events or []})
    assert r.status_code == 200, r.text
    token = str(r.json()["token"])
    if records:
        rc = client_for(sim, token)
        rc.import_records(records)
    return token


def client_for(sim: Any, token: str) -> RedcapClient:
    rc = RedcapClient("https://rc.example/", token, http=TestClient(sim, base_url="http://rc"))
    rc.url = "/api/"
    return rc


def service(tmp_path: Path, facts: FakeFacts | None = None, llm: Any = None,
            records: list[dict[str, str]] | None = None) -> tuple[EdcService, Any, str]:  # fmt: skip
    """(service, simulator, token) on the test's own database schemas."""
    sim = create_app()
    token = sim_project(sim, records if records is not None else [{"record_id": "1", "tb_screening_no": RECORD}])
    the_llm = llm if llm is not None else StubLlm()
    svc = EdcService(EdcStore(), DataCore(), AuditLog(tmp_path / "audit"), lambda: STAMP, lambda: TODAY,
                     lambda _ref: client_for(sim, token), lambda: facts or FakeFacts(),
                     lambda job: gateway_drafter(the_llm, job))  # fmt: skip
    return svc, sim, token


def ready(svc: EdcService, on: bool = True) -> None:
    """Dictionary read from REDCap, map saved, switch on."""
    svc.import_dictionary(STUDY, "edc", "crc", "record_id")
    svc.put_map(STUDY, MAP, TARGET, "crc")
    if on:
        svc.set_switch(STUDY, True, by="pi", role="investigator", **ACK)


def seen(svc: EdcService, record: str = RECORD, visit: str = "") -> dict[int, str]:
    """What a review page shows before signing: each decided, unsigned value of the visit and its hash."""
    from datacore.export import BASE_EVENT

    return {int(d["id"]): str(d["sha"]) for d in svc.store.drafts(STUDY, record, visit or BASE_EVENT)
            if d["fate"] in ("confirmed", "edited") and d["signature_id"] is None}  # fmt: skip
