"""User-journey review of 2026-11-09, wave 1c (D-146): the orchestrator, sign-in and data rules behind J-01, J-02,
J-07, J-08 and J-26 (the console pages are in ``tests/console/test_journey_pages.py``)."""

from __future__ import annotations

import dataclasses
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from embed_service.embedder import HashEmbedder
from fastapi import FastAPI
from lake.client import LakeLocal
from lake.store import Lake
from orchestrator.clients import StepFailed
from orchestrator.core import Rejected
from orchestrator.scenarios import screen
from orchestrator.studystore import StudyStore
from sitesetup import charts
from tb_common import authz
from tb_common import service_auth as sa
from tb_contracts import JobCreate

from tests.actor3 import SignedClient
from tests.unit.test_orchestrator_unit import make  # noqa: F401 - the fixture is used by name
from tests.unit.test_site_setup import svc  # noqa: F401 - the fixture is used by name

SNAP = "2026-10-31"


# ---------------------------------------------------------------------------------------------- J-01: by role
def test_a_console_request_is_authorised_by_role_not_by_mailbox(make: Any) -> None:  # noqa: F811
    """A coordinator created on the console has a mailbox that is not on settings.yaml's list: the signed role
    decides. The mailbox rule still decides a mailed request (no role)."""
    orch, _ = make({})
    job = orch.create(JobCreate(type="FEAS", ruleset="GZQO", requested_by="new-crc@hospa.test"),
                      role="coordinator", by="console:crc7")  # fmt: skip
    assert job.state == "received"
    assert orch.create(JobCreate(type="SCREEN", ruleset="GZQO", requested_by="admin@hospa.test"), role="admin")
    with pytest.raises(Rejected, match="not permitted"):  # mailed: the mailbox rule, as before
        orch.create(JobCreate(type="FEAS", ruleset="GZQO", requested_by="new-crc@hospa.test"))
    with pytest.raises(Rejected, match="the investigator role may not run COHORT"):  # T-512: FEAS/SCREEN/CASE only
        orch.create(JobCreate(type="COHORT", ruleset="GZQO", requested_by="pi@hospa.test"), role="investigator")
    for role in ("viewer", "cro"):
        with pytest.raises(Rejected, match=f"the {role} role may not run FEAS"):
            orch.create(JobCreate(type="FEAS", ruleset="GZQO", requested_by="v@hospa.test"), role=role)
    with pytest.raises(Rejected, match="the coordinator role may not run APPROVE"):  # FR-AUTH-13: the PI approves
        orch.create(JobCreate(type="APPROVE", ruleset="GZQO", requested_by="crc1@hospa.test"), role="coordinator")
    assert authz.role_allowed("investigator", "APPROVE") and not authz.role_allowed("admin", "APPROVE")
    lines = [json.loads(x) for p in sorted(orch.audit.directory.glob("*.jsonl")) for x in p.read_text().splitlines()]
    rec = next(r for r in lines if r["event"] == "job.state" and r.get("job_id") == job.job_id)
    assert rec["detail"]["by"] == "console:crc7" and rec["detail"]["role"] == "coordinator"


def test_the_role_travels_signed_and_a_changed_role_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_SERVICE_TOKEN", "journey-test-token-0123456789")
    monkeypatch.delenv(sa.ACTOR_KEYS_ENV, raising=False)
    monkeypatch.delenv(sa.REGISTRY_ENV, raising=False)
    h = sa.actor_header("console:crc", session="s1", role="coordinator")
    assert h[sa.ROLE_HEADER] == "coordinator"
    who = sa.verify_actor(h[sa.ACTOR_HEADER], h[sa.ASSERTION_HEADER], role=h[sa.ROLE_HEADER])
    assert who.verified and who.role == "coordinator" and who.name == "console:crc"
    with pytest.raises(sa.ActorError, match="does not verify"):  # the role is under the signature
        sa.verify_actor(h[sa.ACTOR_HEADER], h[sa.ASSERTION_HEADER], role="admin")
    plain = sa.actor_header("console:crc", session="s1")  # an assertion without a role still verifies (S-09)
    assert sa.verify_actor(plain[sa.ACTOR_HEADER], plain[sa.ASSERTION_HEADER]).role == ""
    with pytest.raises(sa.ActorError, match="does not verify"):  # and cannot have a role added afterwards
        sa.verify_actor(plain[sa.ACTOR_HEADER], plain[sa.ASSERTION_HEADER], role="admin")


# ---------------------------------------------------------------------------------------------- J-02: heavy only
def test_the_daily_limit_counts_heavy_runs_only_each_on_its_own(make: Any) -> None:  # noqa: F811
    orch, _ = make({})
    s = orch.cfg.settings
    assert (
        authz.daily_limit(s, "SCREEN") == 20
        and authz.daily_limit(s, "CASE") is None
        and authz.daily_limit(s, "CONSENT") is None
    )
    for _ in range(25):  # case questions and status checks are never counted
        orch.create(JobCreate(type="CASE", ruleset="GZQO", requested_by="crc1@hospa.test"))
    for _ in range(20):
        orch.create(JobCreate(type="SCREEN", ruleset="GZQO", requested_by="crc1@hospa.test"))
    with pytest.raises(Rejected, match=r"rate limit reached \(20 SCREEN jobs per sender per day\)"):
        orch.create(JobCreate(type="SCREEN", ruleset="GZQO", requested_by="crc1@hospa.test"))
    assert orch.create(JobCreate(type="FEAS", ruleset="GZQO", requested_by="crc1@hospa.test"))  # its own count
    orch.cfg = dataclasses.replace(
        orch.cfg, settings=s.model_copy(update={"rate_limits_per_day": {"SCREEN": 0, "CASE": 25}})
    )
    assert orch.create(JobCreate(type="SCREEN", ruleset="GZQO", requested_by="crc1@hospa.test"))  # 0 = no limit
    with pytest.raises(Rejected, match=r"\(25 CASE jobs"):  # a site may limit any type
        orch.create(JobCreate(type="CASE", ruleset="GZQO", requested_by="crc1@hospa.test"))


# ---------------------------------------------------------------------------------------------- J-07: NUL bytes
def test_chart_text_drops_nul_and_control_characters() -> None:
    raw = "尿酸 8.8 mg/dL\x00 痛風発作\x01あり\tdate 2026-10-01\r\n\x7fend".encode()
    no_ocr: Any = SimpleNamespace(available=lambda: False)
    out = charts.chart_text("chart.txt", raw, ocr=no_ocr)
    assert "\x00" not in out.text and "\x01" not in out.text and "\x7f" not in out.text
    assert out.text == "尿酸 8.8 mg/dL 痛風発作あり\tdate 2026-10-01\r\nend"


def test_a_pdf_whose_text_carries_nul_is_stored(svc: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """The review's PDF crashed the fact store (psycopg: text fields cannot contain NUL). The PDF reader's text, with
    NUL between the CJK glyphs, now reaches the store clean."""
    monkeypatch.setattr(
        charts, "_pdf", lambda data, ocr: charts.ChartText("2026-10-01 尿酸\x00 8.8 mg/dL\x00 痛風\x00", "pdf", 1)
    )
    out = svc.add_chart("main", "00012345", "chart.pdf", b"%PDF-1.4 fake", "crc", "ja")
    assert out["method"] == "pdf"
    text = (svc.root / "main" / "inputs" / f"{out['input']}.txt").read_text(encoding="utf-8")
    assert "\x00" not in text and "尿酸 8.8" in text
    assert all("\x00" not in json.dumps(f, ensure_ascii=False) for f in svc.store.facts("main", "proposed"))


# ---------------------------------------------------------------------------------------------- J-26: who to screen
def _lake(tmp: Path) -> LakeLocal:
    feed = tmp / "feed"
    feed.mkdir(parents=True)
    pts = [{"resourceType": "Patient", "id": f"P{i}", "birthDate": "1960-01-01", "gender": "male"} for i in range(3)]
    enc = [
        {
            "resourceType": "Encounter",
            "id": f"E{i}",
            "status": "finished",
            "subject": {"reference": f"Patient/P{i}"},
            "participant": [{"individual": {"reference": f"Practitioner/D{i}"}}],
            "period": {"start": "2026-09-01T09:00:00+09:00"},
            "class": {"code": "AMB"},
        }
        for i in range(3)
    ]
    docs: dict[str, list[dict[str, Any]]] = {"Patient": pts, "Encounter": enc, "Condition": []}
    for rtype, items in docs.items():
        (feed / f"{rtype}.ndjson").write_text("".join(json.dumps(r) + "\n" for r in items), "utf-8")
    Lake(tmp / "lake", tz="Asia/Tokyo").rebuild(SNAP, HashEmbedder(), ndjson_dir=feed)
    return LakeLocal(tmp / "lake", HashEmbedder())


def test_whole_hospital_scope_reads_every_doctors_patients(tmp_path: Path) -> None:
    ctx: Any = SimpleNamespace(
        services=SimpleNamespace(lake=_lake(tmp_path)), cfg=SimpleNamespace(env=SimpleNamespace(tz="Asia/Tokyo"))
    )
    run = date(2026, 10, 31)
    some = screen.scope_patients(ctx, ["D1"], run, 180, 12, [], SNAP)
    everyone = screen.scope_patients(ctx, None, run, 180, 12, [], SNAP)
    assert len(some) == 1 and some[0].practitioner_id == "D1"
    assert len(everyone) == 3 and {s.practitioner_id for s in everyone} == {"D0", "D1", "D2"}


def test_the_study_set_up_decides_who_a_screening_run_looks_at(db_url: str, tmp_path: Path) -> None:
    from orchestrator.study_api import router

    store = StudyStore(tmp_path, db_url)
    fake = SimpleNamespace(store=store, audit=SimpleNamespace(append=lambda *a, **k: None), stamp=lambda: "2026-11-09")
    api = FastAPI()
    api.include_router(router(lambda: fake))  # type: ignore[arg-type,return-value]
    c = SignedClient(api)  # T-715d (D-554): the scope's route takes the signed person; a `by` here is who signs
    assert c.get("/studies/NEW1/screen-scope").json()["mode"] is None
    rs = SimpleNamespace(id="NEW1", manifest=SimpleNamespace(scopes=None))

    def ctx(options: dict[str, str]) -> Any:
        return SimpleNamespace(
            orch=SimpleNamespace(db=SimpleNamespace(url=db_url)), job=SimpleNamespace(options=options)
        )

    with pytest.raises(StepFailed, match="Who to screen"):  # nothing set: the run says where to set it
        screen.practitioners_of(ctx({}), rs)  # type: ignore[arg-type]
    r = c.put("/studies/NEW1/screen-scope", json={"mode": "hospital", "by": "console:crc"})
    assert r.status_code == 200 and r.json()["mode"] == "hospital"
    assert screen.practitioners_of(ctx({}), rs) is None  # type: ignore[arg-type]
    assert screen.practitioners_of(ctx({"pract": "P1,P2"}), rs) == ["P1", "P2"]  # type: ignore[arg-type]
    bad = c.put("/studies/NEW1/screen-scope", json={"mode": "practitioners", "practitioners": [], "by": "x"})
    assert bad.status_code == 400
    r = c.put("/studies/NEW1/screen-scope", json={"mode": "practitioners", "practitioners": ["P9"], "by": "x"})
    assert r.json()["practitioners"] == ["P9"]
    assert screen.practitioners_of(ctx({}), rs) == ["P9"]  # type: ignore[arg-type]
    assert screen.practitioners_of(ctx({"scope": "hospital"}), rs) is None  # type: ignore[arg-type]
    store.close()
