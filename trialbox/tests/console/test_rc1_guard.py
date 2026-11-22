"""rc1's refusals of live patient lists and of patient mail and downloads (the owner's ruling of 2026-11-20; review
R22-34; ``tb_common.rc1_refusals``).

* ``live_patient_lists``: the orchestrator's first step of every scenario that lists patients refuses
  (``orchestrator.scheduler.require_released``), and the console serves no stored list (``console.rc1_guard``);
* ``patient_mail_and_downloads``: the mail gateway holds a mail with a job's patient-level files
  (``mail_gateway.gateway.Gateway._still_current``), and the console gives no patient-level file to download.

On a box with ``TB_ENV`` unset, PRODUCTION or unknown: nothing is listed, shown, sent or downloaded; the person reads the
table's message (the problem page, JSON on ``/api/``, the job's error, the held mail's reason) and the refusal is an
audited event. On DEV, TEST and VALIDATION (D-1072) the guards let it through. Synthetic data only."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from console import i18n_rc1
from console import rc1_guard as rg
from console.app import create_app
from console.auth import UserStore
from console.i18n import CATALOGUES
from fastapi.testclient import TestClient
from tb_common import rc1_refusals
from tb_common.audit import AuditLog
from tb_common.crypto import sha256_bytes
from tb_contracts import Job, JobOutput

from tests.console.test_console_app import ADMIN_PW, PILOT_ENV, FakeBackend

ENVS = ("", "PRODUCTION", "PILOT", "DEV", "TEST", "VALIDATION")
LIST_KEY = "rc1.live_patient_lists"
FILE_KEY = "rc1.patient_mail_and_downloads"
PATIENT = "a1b2c3d4e5f6c001" * 2  # a synthetic pseudonym
NOW = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)


def _job(b: FakeBackend, n: int, type_: str, files: tuple[tuple[str, bytes, str], ...]) -> Job:
    jid = f"01JB{n:022d}"
    outs = []
    for name, data, tag in files:
        key = f"outputs/{jid}/{name}"
        b.objects[key] = data
        out = {"filename": name, "sha256": sha256_bytes(data), "minio_key": key, "recipients": ["crc@hospa.test"],
               "tag": tag}  # fmt: skip
        outs.append(JobOutput.model_validate(out))
    job = {"job_id": jid, "type": type_, "ruleset": "GZQO", "ruleset_version": "1.0.0", "requested_by": "crc@hospa.test",
           "received_at": NOW, "updated_at": NOW, "state": "done", "options": {}, "inputs": [], "outputs": outs}  # fmt: skip
    return b.add_job(Job.model_validate(job))


def _console(tmp_path: Path, env: str) -> dict[str, Any]:
    backend = FakeBackend()
    backend.audit_dir = tmp_path / "audit"
    users = UserStore()
    if users.get("admin") is None:  # one trial database per test: a second console of the test shares it
        users.create("admin", "admin", ADMIN_PW, "admin@hospa.test")
    rows = json.dumps({"rows": [{"pid": PATIENT, "tier": "high"}]}).encode()
    screen = _job(
        backend, 1, "SCREEN", (("candidate_list_GZQO.json", rows, "phi"), ("counts_GZQO.json", b"{}", "aggregate"))
    )
    feas = _job(backend, 2, "FEAS", (("feasibility_GZQO.json", b'{"start_n": 600}', "aggregate"),))
    base = {k: v for k, v in PILOT_ENV.items() if k != "TB_ENV"}
    app = create_app({**base, **({"TB_ENV": env} if env else {}), "TB_CONSOLE_DIR": str(tmp_path / "console")},
                     backend=backend, audit=AuditLog(backend.audit_dir), users=users)  # fmt: skip
    return {"app": app, "dir": tmp_path, "screen": screen, "feas": feas}


def _events(b: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for f in sorted((b["dir"] / "audit").glob("*.jsonl")):
        out += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x]
    return [e for e in out if e["event"] == rg.EVENT and (e.get("detail") or {}).get("refusal")]


def _refused(env: str) -> bool:
    return env not in rc1_refusals.ALLOWED


def _ask(b: dict[str, Any], paths: list[str], key: str, env: str) -> None:
    """Each path is refused before its route (refused), or reaches its route (allowed)."""
    c = TestClient(b["app"], base_url="https://testserver", follow_redirects=False)
    shown = rc1_refusals.text(key, "en", environment=env or "PRODUCTION")
    for path in paths:
        r = c.get(path)
        if _refused(env):
            assert r.status_code == 403, (path, r.status_code)
            if path.startswith("/api/"):
                assert r.json() == {"error": key, "detail": {"environment": env or "PRODUCTION"}}, path
            else:
                assert shown in r.text and 'data-testid="problem-page"' in r.text, path
            assert PATIENT not in r.text, path  # nothing listed or downloaded
        else:
            assert r.status_code != 403 and shown not in r.text, (path, r.status_code)
    seen = _events(b)
    if _refused(env):
        assert [e["detail"] for e in seen] == [{"refusal": rc1_refusals.row(key.removeprefix("rc1.")).name,
                                                "environment": env or "PRODUCTION", "action": p} for p in paths]  # fmt: skip
        assert all(e["actor"] == "console:-" for e in seen)
    else:
        assert seen == []


@pytest.mark.parametrize("env", ENVS)
def test_no_live_patient_list_on_a_production_box(
    env: str, db_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orchestrator.clients import StepFailed
    from orchestrator.scheduler import require_open, require_released

    if env:
        monkeypatch.setenv("TB_ENV", env)
    else:
        monkeypatch.delenv("TB_ENV", raising=False)
    monkeypatch.delenv("TB_DB_URL", raising=False)  # a bare stack: the restore hold and the study state are open
    if _refused(env):
        for first_step in (require_released, lambda: require_open("GZQO")):
            with pytest.raises(StepFailed) as got:
                first_step()
            assert got.value.step == "rc1" and got.value.detail == LIST_KEY
            assert got.value.message == rc1_refusals.text(LIST_KEY, environment=env or "PRODUCTION")
    else:
        require_released()
        require_open("GZQO")
    monkeypatch.setenv("TB_DB_URL", db_url)  # the console's own stores
    b = _console(tmp_path, env)
    paths = ["/studies/GZQO/week", "/studies/GZQO/cohort", f"/pilot/jobs/{b['screen'].job_id}"]
    _ask(b, paths, LIST_KEY, env)
    c = TestClient(b["app"], base_url="https://testserver", follow_redirects=False)
    assert c.get(f"/pilot/jobs/{b['feas'].job_id}").status_code != 403  # a card of counts stays open
    assert c.get("/week").status_code != 403  # the list of studies; one study's list is the guarded page


@pytest.mark.parametrize("env", ENVS)
def test_no_patient_mail_or_download_on_a_production_box(
    env: str, db_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.test_mail_resolve import MTA
    from tests.unit.test_the_outbox_asks_before_it_sends import JOB, Register, _gw, _phi, _state

    if env:
        monkeypatch.setenv("TB_ENV", env)
    else:
        monkeypatch.delenv("TB_ENV", raising=False)
    mta, reg = MTA(), Register()
    mta.cause = None  # the server is up
    gw = _gw(tmp_path / "mail", mta, reg)
    gw.send(_phi("rc1"))
    state, why = _state(gw, "rc1")
    if _refused(env):
        assert mta.sent == [] and reg.asked == []  # held before anything is read or sent
        assert state == "failed" and FILE_KEY in why and (env or "PRODUCTION") in why  # held at once, for a person
        assert gw.drain(force=True) == {} and mta.sent == []  # never tried again by itself
        held = [json.loads(x) for f in sorted((tmp_path / "mail" / "audit").glob("*.jsonl"))
                for x in f.read_text(encoding="utf-8").splitlines() if x]  # fmt: skip
        assert [e["event"] for e in held] == ["mail.failed"] and FILE_KEY in held[0]["detail"]["error"]
    else:
        assert state == "sent" and mta.sent and reg.asked == [JOB]  # asked, then sent
    b = _console(tmp_path / "console", env)
    s = b["screen"].job_id
    paths = [f"/pilot/jobs/{s}/files/candidate_list_GZQO.json", f"/pilot/jobs/{s}/view/candidate_list_GZQO.json",
             "/studies/GZQO/screening-log.xlsx", "/pilot/registry/GZQO/export.xlsx", "/studies/GZQO/enrolment.csv",
             "/api/v1/studies/GZQO/enrolment/csv", "/studies/GZQO/export.csv", "/api/v1/studies/GZQO/export/csv",
             "/studies/GZQO/edc/export.odm.xml", "/api/v1/studies/GZQO/edc/export/odm", "/studies/GZQO/edc/copy.csv",
             "/api/v1/studies/GZQO/edc/copy"]  # fmt: skip
    _ask(b, paths, FILE_KEY, env)
    c = TestClient(b["app"], base_url="https://testserver", follow_redirects=False)
    assert c.get(f"/pilot/jobs/{s}/files/counts_GZQO.json").status_code != 403  # an aggregate file stays open


def test_the_guard_reads_the_consoles_environment_and_the_table(db_url: str, tmp_path: Path) -> None:
    """One rule: the console's own ``TB_ENV`` (unset is PRODUCTION), an unknown name refused, the table's sets."""
    for env, refused in (("", True), ("PRODUCTION", True), ("PILOT", True), ("VALIDATION", False), ("dev", False),
                         ("TEST", False)):  # fmt: skip
        g = _console(tmp_path / (env or "unset"), env)["app"].state.rc1_guard
        assert g.lists_refused() is refused and g.downloads_refused() is refused, env


def test_the_consoles_words_are_the_tables_words() -> None:
    cats = {"en": i18n_rc1.EN, "ja": i18n_rc1.JA, "zh-TW": i18n_rc1.ZH}
    for r in rc1_refusals.REFUSALS:
        for lang in rc1_refusals.LANGS:
            assert cats[lang][r.key] == rc1_refusals.TEXTS[r.key][lang] == CATALOGUES[lang][r.key], (r.key, lang)
            assert CATALOGUES[lang][f"problem.h.{r.key}"] == cats[lang][f"problem.h.{r.key}"]
