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
        # the lake gives each row its code system (D-598); a row written here without one is of the box's own
        own = {"observation": "http://loinc.org", "condition": "http://hl7.org/fhir/sid/icd-10-cm"}.get(source)
        rows = self.data.get(source, []) if pid in self.patients else []
        return [r if own is None or "system" in r else {**r, "system": own} for r in rows]

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


SIGN_KEY = b"tests-edc-signature-key-0123456789"  # D-281: the kit's own key, whatever TB_ENV the test sets


def service(tmp_path: Path, facts: FakeFacts | None = None, llm: Any = None,
            records: list[dict[str, str]] | None = None) -> tuple[EdcService, Any, str]:  # fmt: skip
    """(service, simulator, token) on the test's own database schemas."""
    sim = create_app()
    token = sim_project(sim, records if records is not None else [{"record_id": "1", "tb_screening_no": RECORD}])
    the_llm = llm if llm is not None else StubLlm()
    svc = EdcService(EdcStore(sign_key=SIGN_KEY), DataCore(), AuditLog(tmp_path / "audit"), lambda: STAMP, lambda: TODAY,
                     lambda _ref: client_for(sim, token), lambda: facts or FakeFacts(),
                     lambda job: gateway_drafter(the_llm, job))  # fmt: skip
    return svc, sim, token


def ready(svc: EdcService, on: bool = True) -> None:
    """Dictionary read from REDCap, map saved, switch on (with a stored re-entry result where typed numbers do
    not count)."""
    svc.import_dictionary(STUDY, "edc", "crc", "record_id")
    svc.put_map(STUDY, MAP, TARGET, "crc")
    if on:
        if not svc.typed_reentry():  # VALIDATION or PRODUCTION (D-368, E-14): the switch reads a stored result
            svc.record_reentry(STUDY, pages=30, accuracy=0.985,
                               document="DOC-REENTRY-1", by="admin")  # fmt: skip
        svc.set_switch(STUDY, True, by="pi", role="investigator", **ACK)


def seen(svc: EdcService, record: str = RECORD, visit: str = "") -> dict[int, str]:
    """What a review page shows before signing: each decided, unsigned value of the visit and its hash."""
    from datacore.export import BASE_EVENT

    return {int(d["id"]): str(d["sha"]) for d in svc.store.drafts(STUDY, record, visit or BASE_EVENT)
            if d["fate"] in ("confirmed", "edited") and d["signature_id"] is None}  # fmt: skip


def old_unkeyed_sha(shas: dict[int, str]) -> str:
    """What a version-1 signature (before D-281) stored: an unkeyed hash over the value hashes, which anyone can
    re-make. Kept here only to show that such a row covers nothing (D-461)."""
    import hashlib
    import json as _json

    return hashlib.sha256(_json.dumps(sorted((int(k), str(v)) for k, v in shas.items())).encode()).hexdigest()


def store_with_old_signature(values: dict[int, str] | None = None) -> tuple[EdcStore, dict[str, Any]]:
    """D-461: an EDC store at schema version 3 holding one version-1 (unkeyed) signature row, as a box signed before
    D-281 would, then opened by today's code. Synthetic values."""
    import json as _json
    import os

    from edc.store import MIGRATIONS
    from tb_common.db import ENV, Database

    shas = values if values is not None else {1: "a" * 64, 2: "b" * 64}
    with Database.connect(os.environ[ENV], "edc") as db:
        db.migrate(list(MIGRATIONS[:3]))
        sid = int(db.fetchval(
            "INSERT INTO signature (study, record, visit, signer, printed_name, role, meaning, meaning_text, lang, "
            "method, at, content_sha, drafts, sig_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1) RETURNING id",
            (STUDY, RECORD, "", "crc", "Chen Mei", "coordinator", "transcribed", "I checked each value.", "en",
             "password", "2026-10-01T09:00:00+00:00", old_unkeyed_sha(shas),
             _json.dumps({str(k): v for k, v in sorted(shas.items())}))))  # fmt: skip
    store = EdcStore(sign_key=SIGN_KEY)
    row = store.signature(sid)
    assert row is not None
    return store, row


# ------------------------------------------------------------------------------------------------------------------
# NEW-EDC-0 (D-584): the conformance project of our own REDCap test instance. The CRF above, the longitudinal and
# repeating set of tests/unit/test_edc_t302b.py (two arms, four events, the repeating ``ae`` instrument, a
# calculated field, branching logic), and the three fields the deep review asked for: one checkbox, one
# ``date_dmy`` and one number kept to one decimal place by TrialBox (D-840). Synthetic data only. ``tools/redcap_instance.py`` builds it on the instance
# (or on the simulator, as a stand-in) and runs R1 to R9 against it.
CONF_SCREEN1, CONF_WEEK4_1 = "screening_arm_1", "week4_arm_1"
CONF_SCREEN2, CONF_WEEK4_2 = "screening_arm_2", "week4_arm_2"
CONF_BMI = "round([weight]/(([height]/100)*([height]/100)),1)"  # D-840: a real REDCap refuses ^ in a calculation
CONF_CRF: list[dict[str, str]] = [
    *CRF,
    {"field_name": "height", "form_name": "baseline", "field_type": "text", "field_label": "Height (cm)",
     "text_validation_type_or_show_slider_number": "number"},
    {"field_name": "bmi", "form_name": "baseline", "field_type": "calc", "field_label": "BMI",
     "select_choices_or_calculations": CONF_BMI},
    {"field_name": "tophus_site", "form_name": "baseline", "field_type": "text", "field_label": "Tophus site",
     "branching_logic": "[tophus] = '1'"},
    {"field_name": "joints", "form_name": "baseline", "field_type": "checkbox", "field_label": "Joints involved",
     "select_choices_or_calculations": "1, Toe | 2, Ankle | 3, Knee | -99, Unknown"},  # -99: R2 reads REDCap's name
    {"field_name": "visit_dmy", "form_name": "baseline", "field_type": "text", "field_label": "Visit date (D-M-Y)",
     "text_validation_type_or_show_slider_number": "date_dmy"},
    {"field_name": "temp", "form_name": "baseline", "field_type": "text", "field_label": "Body temperature (°C)",
     "text_validation_type_or_show_slider_number": "number", "text_validation_min": "30.0",
     "text_validation_max": "45.0", "field_annotation": "@TB-DECIMALS=1"},  # D-840: number_1dp is not offered there
    {"field_name": "ae_term", "form_name": "ae", "field_type": "text", "field_label": "AE term"},
    {"field_name": "ae_serious", "form_name": "ae", "field_type": "yesno", "field_label": "Serious"},
    {"field_name": "ae_sae_reason", "form_name": "ae", "field_type": "text", "field_label": "Why serious",
     "branching_logic": "[ae_serious] = '1'"},
]  # fmt: skip
CONF_ARMS = [{"arm_num": 1, "name": "Drug"}, {"arm_num": 2, "name": "Placebo"}]
CONF_EVENTS = [{"event_name": "Screening", "arm_num": 1, "unique_event_name": CONF_SCREEN1},
               {"event_name": "Week4", "arm_num": 1, "unique_event_name": CONF_WEEK4_1},
               {"event_name": "Screening", "arm_num": 2, "unique_event_name": CONF_SCREEN2},
               {"event_name": "Week4", "arm_num": 2, "unique_event_name": CONF_WEEK4_2}]  # fmt: skip
CONF_DESIGNATED = [{"arm_num": a, "unique_event_name": ev, "form": f}
                   for a, ev in ((1, CONF_SCREEN1), (2, CONF_SCREEN2)) for f in ("demographics", "baseline")]  # fmt: skip
CONF_DESIGNATED += [{"arm_num": a, "unique_event_name": ev, "form": "ae"}
                    for a, ev in ((1, CONF_WEEK4_1), (2, CONF_WEEK4_2))]  # fmt: skip
CONF_REPEATING = [{"event_name": CONF_WEEK4_1, "form_name": "ae"}, {"event_name": CONF_WEEK4_2, "form_name": "ae"}]
CONF_DAGS = [{"data_access_group_name": "Site A", "unique_group_name": "site_a"},
             {"data_access_group_name": "Site B", "unique_group_name": "site_b"}]  # fmt: skip
# record 1 belongs to site A, record 2 to site B (R4: a token bound to site A may not write record 2)
CONF_SEED = [{"record_id": "1", "redcap_event_name": CONF_SCREEN1, "tb_screening_no": "S-001", "height": "175",
              "redcap_data_access_group": "site_a"},
             {"record_id": "2", "redcap_event_name": CONF_SCREEN2, "tb_screening_no": "S-002", "height": "160",
              "redcap_data_access_group": "site_b"}]  # fmt: skip
# the users of the instance: who holds which of the four tokens, and the person who may lock a form (R3)
CONF_USERS = {
    "full": {"username": "tb_full", "api_export": 1, "api_import": 1},
    "export_only": {"username": "tb_export", "api_export": 1, "api_import": 0},
    "dag": {"username": "tb_dag", "api_export": 1, "api_import": 1, "data_access_group": "site_a"},
    "expired": {"username": "tb_expired", "api_export": 1, "api_import": 1, "expiration": "2020-01-01"},
    "locker": {"username": "tb_locker", "lock_records": 1, "lock_records_all_forms": 1},
}
# R6: the expressions of test_the_evaluator_computes_as_redcap and test_branching_logic_shows_as_redcap, with the
# row each is computed on. On the instance each becomes a calculated field of a second, classic project (a
# branching expression as ``if(<expression>, 1, 0)``: REDCap has no API that says whether a field is shown), one
# record per case. The case that reads another event is run by the evaluator only.
CONF_CALC: list[tuple[str, dict[str, str]]] = [
    (CONF_BMI, {"weight": "72.5", "height": "175"}),
    (CONF_BMI, {"weight": "72.5", "height": ""}),
    ("sum([a],[b],[c])", {"a": "1", "b": "", "c": "2.5"}),
    ("mean([a],[b])", {"a": "1", "b": "2"}),
    ("[a]/[b]", {"a": "1", "b": "0"}),
    ("round(2.5) + rounddown(1.99,1) + roundup(1.01,1)", {}),
    ("if([a] > 70, 1, 0)", {"a": "72"}),
    ("datediff([d1],[d2],'d')", {"d1": "2026-01-01", "d2": "2026-03-01"}),
    ("datediff([d2],[d1],'d',true)", {"d1": "2026-01-01", "d2": "2026-03-01"}),
    ("rounddown(datediff([dob],'today','y'))", {"dob": "1960-05-01"}),
    ("[cb(2)] + [cb(3)]", {"cb": "1,3"}),
    ("2*2*2*2*2*2*2*2*2*2 - 1", {}),  # D-840: no ^, no two minus signs (the original forms are evaluator tests)
    ("sqrt(-1)", {}),
]
CONF_BRANCH: list[tuple[str, dict[str, str]]] = [
    ("[s] = '1'", {"s": "1"}),
    ("[s] = '1'", {"s": ""}),
    ("[s] = ''", {"s": ""}),
    ("[s] = 0", {"s": ""}),
    ("[a] > 5", {"a": ""}),
    ("[a] <> '2' and ([b] = 'x' or [c] >= 3)", {"a": "1", "b": "y", "c": "3"}),
    ("[a] != 1 || [b] = 1", {"a": "1", "b": "1"}),
    ("[d] > '2026-01-01'", {"d": "2026-02-01"}),
    ("contains([t], 'gout') and not_contain([t], 'rash')", {"t": "Gout flare"}),
    ("isnumber([a]) and isinteger([b])", {"a": "1.5", "b": "2.0"}),
]
# the input fields of the logic project (name, REDCap validation); ``cb`` is a checkbox with the codes 1 to 3
CONF_LOGIC_INPUTS = {"weight": "number", "height": "number", "a": "", "b": "", "c": "", "d1": "date_ymd",
                     "d2": "date_ymd", "dob": "date_ymd", "d": "date_ymd", "s": "", "t": ""}  # fmt: skip
