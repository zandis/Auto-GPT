"""Build step 4 (D-110) in the console: the header command field (mail grammar + ja/zh-TW/en phrases + search), its
test set and score, S22 My account, S29 Help panel, S37 Notices received, the S13 admin tabs with S26 Cancel and
Retry and S24 data sources, and every key in every language."""

from __future__ import annotations

import json
import re
import string
from datetime import UTC, datetime
from typing import Any

import pytest
from console import command, step4
from console.i18n import CATALOGUES, EN
from console.i18n_step4 import EN as S4_EN
from console.i18n_step4 import JA as S4_JA
from console.screening_log import _rc_note
from console.sitestore import StudySettings
from tb_common.audit import AuditLog
from tb_contracts import Job, JobError, JobFile

from tests.console.test_console_app import ADMIN_PW, VIEWER_PW, _ulid, box, login  # noqa: F401 - fixture by name
from tools import command_score

PW = "step-four-password-001"
AT = "2026-11-07T09:00:00+00:00"
_T = datetime(2026, 11, 7, 9, 0, tzinfo=UTC)


@pytest.fixture
def b4(box: dict[str, Any]) -> dict[str, Any]:  # noqa: F811
    for name, role in (("crc", "coordinator"), ("pi", "investigator"), ("cra", "cro")):
        box["users"].create(name, role, PW, f"{name}@hospa.test")
    box["users"].set_scope("cra", "cro", "GZQO", None)  # D-380 (ROLE-011): a CRO account names its studies
    return {**box, "h": box["app"].state.helpers}


def _csrf(page: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', page)
    assert m
    return m.group(1)


def _ja(c: Any, csrf: str, lang: str = "ja") -> None:
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/home"})


# ---------------------------------------------------------------------------------------------- the command set
def test_command_set_scores_95_right_0_wrong() -> None:
    res = command_score.score()
    assert res["n"] >= 60
    for lang in ("en", "ja", "zh-TW"):
        assert res["by_lang"][lang]["n"] >= 20, lang
    assert res["right_pct"] >= 95 and res["wrong"] == 0, res["misses"]
    committed = json.loads(command_score.SCORE.read_text(encoding="utf-8"))
    assert committed == json.loads(json.dumps(res)), "run python -m tools.command_score --write"


@pytest.mark.parametrize(
    ("text", "role", "intent", "study"),
    [
        ("FEAS GZQO", "coordinator", "feasibility", "GZQO"),
        ("SCREEN GZQO", "coordinator", "request", "GZQO"),
        ("APPROVE GZQO", "investigator", "refused", "GZQO"),
        ("今週のリスト", "investigator", "week", None),
        ("GZQO 篩選紀錄", "coordinator", "log", "GZQO"),
        ("users", "investigator", "forbidden", None),
        ("feasibility", "coordinator", "pick_study", None),
        ("blah blah", "coordinator", "unknown", None),
    ],
)
def test_interpret(text: str, role: str, intent: str, study: str | None) -> None:
    act = command.interpret(text, ["GZQO", "RA-BIO"], role)
    assert (act.intent, act.study) == (intent, study)


def test_the_field_never_runs_anything() -> None:
    """Every action the field can take is a page to open or a message; a job always waits on its own page."""
    act = command.interpret("SCREEN GZQO", ["GZQO"], "coordinator")
    assert command.url_of(act, "coordinator") == "/pilot/request?ruleset=GZQO&kind=SCREEN"
    for text in ("APPROVE GZQO", "REJECTGATE GZQO", "CONFIRM GZQO a1b2c3d4", "MATCH GZQO"):
        assert not command.interpret(text, ["GZQO"], "investigator").opens_page, text
    act = command.interpret("feasibility", ["GZQO"], "coordinator")  # only one study: no need to ask
    assert (act.intent, act.study) == ("feasibility", "GZQO")


# ---------------------------------------------------------------------------------------------- the field in the app
def test_field_on_every_page_and_redirects(b4: dict[str, Any]) -> None:
    c, _ = login(b4["app"], "crc", PW)
    for path in ("/home", "/reports", "/account", "/help", "/notices/received", "/studies/GZQO/screening-log"):
        page = c.get(path).text
        assert 'data-testid="cmd-q"' in page and 'data-testid="help"' in page, path
    r = c.get("/cmd", params={"q": "FEAS GZQO"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/studies/GZQO/feasibility"
    r = c.get("/cmd", params={"q": "GZQO のスクリーニングログ"}, follow_redirects=False)
    assert r.headers["location"] == "/studies/GZQO/screening-log"
    r = c.get("/cmd", params={"q": "SCREEN GZQO"}, follow_redirects=False)
    assert r.headers["location"].startswith("/pilot/request?ruleset=GZQO")
    assert b4["backend"].created == []  # nothing ran
    page = c.get("/cmd", params={"q": "zzz qqq"}).text
    assert 'data-testid="cmd-unknown"' in page and 'data-testid="cmd-examples"' in page
    recs = [r for r in b4["backend"].audit(None, 50) if r.event == "console.command"]
    assert recs and recs[0].detail["intent"] == "unknown"
    raw = "".join(p.read_text(encoding="utf-8") for p in b4["backend"].audit_dir.glob("*.jsonl"))
    assert "zzz qqq" not in raw and "スクリーニングログ" not in raw  # the typed text is never kept


def test_field_refuses_approval_and_respects_roles(b4: dict[str, Any]) -> None:
    pi, _ = login(b4["app"], "pi", PW)
    page = pi.get("/cmd", params={"q": "APPROVE GZQO"}).text
    assert 'data-testid="cmd-refused"' in page
    cro, _ = login(b4["app"], "cra", PW)
    page = cro.get("/cmd", params={"q": "jobs"}).text
    assert 'data-testid="cmd-forbidden"' in page
    r = cro.get("/cmd", params={"q": "GZQO feasibility"}, follow_redirects=False)
    assert r.headers["location"] == "/studies/GZQO/feasibility"
    assert cro.get("/account").status_code == 200 and cro.get("/help").status_code == 200


def test_field_searches_screening_numbers_and_pseudonyms(b4: dict[str, Any]) -> None:
    pid = "ab" * 16
    no = b4["h"].store.assign_screening_no("GZQO", pid, StudySettings(), AT)
    c, _ = login(b4["app"], "crc", PW)
    r = c.get("/cmd", params={"q": no.lower()}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/studies/GZQO/patients/{pid}"
    r = c.get("/cmd", params={"q": pid[:12]}, follow_redirects=False)
    assert r.headers["location"] == f"/studies/GZQO/patients/{pid}"
    v, _ = login(b4["app"], "viewer", VIEWER_PW)  # aggregate-only: never patients
    assert "cmd-forbidden" in v.get("/cmd", params={"q": no}).text
    assert pid not in v.get("/cmd", params={"q": pid[:12]}).text


# ---------------------------------------------------------------------------------------------- S22, S29, S37
def test_account_page_and_password(b4: dict[str, Any]) -> None:
    c, csrf = login(b4["app"], "crc", PW)
    page = c.get("/account").text
    assert 'data-testid="account-facts"' in page and "crc@hospa.test" in page
    r = c.post("/account/password", data={"csrf": csrf, "current": PW, "new": "x" * 12, "again": "y" * 12})
    assert r.status_code == 400 and "account-error" in r.text
    r = c.post(
        "/account/password", data={"csrf": csrf, "current": "wrong-password-0", "new": "n" * 14, "again": "n" * 14}
    )
    assert r.status_code == 400
    new = "a-new-password-0042"
    r = c.post(
        "/account/password", data={"csrf": csrf, "current": PW, "new": new, "again": new}, follow_redirects=False
    )
    assert r.status_code == 303 and r.headers["location"] == "/login"  # signed out everywhere, signs in again
    assert c.get("/account", follow_redirects=False).status_code in (302, 303, 401)
    login(b4["app"], "crc", new)
    assert any(r.event == "console.user" and r.detail.get("action") == "password" for r in b4["backend"].audit())


def test_help_panel_follows_the_page(b4: dict[str, Any]) -> None:
    c, _ = login(b4["app"], "pi", PW)
    assert 'data-page="log"' in c.get("/help", params={"back": "/studies/GZQO/screening-log"}).text
    assert 'data-page="week"' in c.get("/help", params={"back": "/week"}).text
    assert 'data-page="home"' in c.get("/help", params={"back": "//evil.example"}).text
    for slug in step4.HELP_SLUGS:
        assert f"help.page.{slug}" in EN, slug


def test_notices_received(b4: dict[str, Any]) -> None:
    b4["h"].store.log_notice("N1", "pi", "2026-11-02", "2026-11-02T07:00:00+09:00", "GZQO: 3 patients before clinic")
    b4["h"].store.log_notice("N1", "pi", "2026-11-05", "2026-11-05T07:00:00+09:00", "GZQO: 1 patient before clinic")
    b4["h"].store.log_notice("N2", "crc", "2026-11-05", "2026-11-05T08:00:00+09:00", "not for the PI")
    c, _ = login(b4["app"], "pi", PW)
    page = c.get("/notices/received").text
    assert page.index("1 patient before clinic") < page.index("3 patients before clinic")
    assert "not for the PI" not in page


def test_notices_received_in_site_time(b4: dict[str, Any]) -> None:
    """T-513 (UX-020): the list showed the stored UTC time ("2026-11-01 22:00" for a 07:00 mail in Tokyo) while its
    footer says times are site time."""
    from console.timefmt import local_time, site_zone

    b4["h"].store.log_notice("N1", "pi", "2026-11-02", "2026-11-01T22:00:00+00:00", "GZQO: 2 patients before clinic")
    c, _ = login(b4["app"], "pi", PW)
    page = c.get("/notices/received").text
    shown = local_time("2026-11-01T22:00:00+00:00", site_zone(b4["h"].bk))
    assert f'data-testid="received-at">{shown}<' in page
    assert shown != "2026-11-01 22:00" and "2026-11-01 22:00" not in page


# ---------------------------------------------------------------------------------------------- S13 / S26 / S24
def _failed_job(bk: Any) -> Job:
    f = JobFile(
        filename="criteria.txt", sha256="0" * 64, minio_key="attachments/x/criteria.txt", content_type="text/plain"
    )
    job: Job = bk.add_job(
        Job(
            job_id=_ulid(701),
            type="FEAS",
            ruleset="GZQO",
            requested_by="crc@hospa.test",
            received_at=_T,
            updated_at=_T,
            state="failed",
            options={"lookback": "36"},
            inputs=[f],
            error=JobError(step="compiling", message="x"),
        )
    )
    return job


def test_admin_tabs_cancel_and_retry(b4: dict[str, Any]) -> None:
    bk = b4["backend"]
    cancelled: list[tuple[str, str]] = []

    def cancel_job(job_id: str, by: str, headers: dict[str, str] | None = None) -> Job | None:
        cancelled.append((job_id, by))
        return bk.get_job(job_id)  # type: ignore[no-any-return]

    bk.cancel_job = cancel_job
    running = bk.add_job(
        Job(
            job_id=_ulid(702),
            type="SCREEN",
            ruleset="GZQO",
            requested_by="crc@hospa.test",
            received_at=_T,
            updated_at=_T,
            state="running",
            options={},
        )
    )
    failed = _failed_job(bk)
    c, csrf = login(b4["app"])
    home = c.get("/home").text
    assert 'data-testid="admin-tabs"' in home and 'data-testid="tile-accounts"' in home
    page = c.get("/admin", params={"tab": "jobs"}).text
    assert f'data-testid="cancel-{running.job_id}"' in page and f'data-testid="retry-{failed.job_id}"' in page
    assert f'data-testid="cancel-{failed.job_id}"' not in page
    r = c.post(f"/admin/jobs/{running.job_id}/cancel", data={"csrf": csrf})
    assert 'data-testid="admin-confirm"' in r.text and not cancelled  # asks first
    r = c.post(f"/admin/jobs/{running.job_id}/cancel", data={"csrf": csrf, "confirm": "yes"}, follow_redirects=False)
    assert r.status_code == 303 and cancelled == [(running.job_id, "console:admin")]
    r = c.post(f"/admin/jobs/{failed.job_id}/retry", data={"csrf": csrf, "confirm": "yes"}, follow_redirects=False)
    assert r.status_code == 303
    req = bk.created[-1]
    assert (req.type, req.ruleset, req.options, req.requested_by) == (
        "FEAS",
        "GZQO",
        {"lookback": "36"},
        "crc@hospa.test",
    )
    assert [i.filename for i in req.inputs or []] == ["criteria.txt"]
    assert c.post(f"/admin/jobs/{running.job_id}/retry", data={"csrf": csrf, "confirm": "yes"}).status_code == 409
    acts = [r.detail.get("action") for r in bk.audit() if r.event == "console.operate"]
    assert "cancel" in acts and "retry" in acts
    filtered = c.get("/admin", params={"tab": "jobs", "state": "failed"}).text
    assert failed.job_id in filtered and running.job_id not in filtered
    crc, crc_csrf = login(b4["app"], "crc", PW)
    assert crc.get("/admin").status_code == 403
    assert crc.post(f"/admin/jobs/{failed.job_id}/retry", data={"csrf": crc_csrf, "confirm": "yes"}).status_code == 403


def _scheduler_types() -> list[str]:
    from types import SimpleNamespace

    from orchestrator.scheduler import plan

    return [t for t, _ in plan(SimpleNamespace(schedule=None))]  # type: ignore[arg-type]


@pytest.mark.parametrize("jtype", _scheduler_types())
def test_admin_retry_of_a_scheduler_job(b4: dict[str, Any], jtype: str) -> None:
    """T-746 (D-474; replaces T-713's "three types run again on schedule"): the administrator retries a failed job of
    the box's scheduler of every type. The console asks the orchestrator's retry route with the job's id and the
    administrator's mailbox only (the orchestrator copies the type and parameters); it never sends a JobCreate."""
    bk = b4["backend"]
    nightly = bk.add_job(
        Job(
            job_id=_ulid(703),
            type=jtype,  # type: ignore[arg-type]
            ruleset="GZQO",
            requested_by="scheduler",
            received_at=_T,
            updated_at=_T,
            state="failed",
            options={"window": "1"},
            error=JobError(step="running", message="x"),
        )
    )
    c, csrf = login(b4["app"])
    page = c.get("/admin", params={"tab": "jobs"}).text
    assert f'data-testid="retry-{nightly.job_id}"' in page and "on-schedule-" not in page
    n = len(bk.created)
    r = c.post(f"/admin/jobs/{nightly.job_id}/retry", data={"csrf": csrf})
    assert 'data-testid="admin-confirm"' in r.text and not getattr(bk, "retried", [])  # asks first
    r = c.post(f"/admin/jobs/{nightly.job_id}/retry", data={"csrf": csrf, "confirm": "yes", "type": "SCREEN",
                                                          "options": "window=99"}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303 and len(bk.created) == n  # no POST /jobs: the orchestrator copies the failed job
    job_id, reply_to, by, role = bk.retried[-1]
    assert (job_id, by, role) == (nightly.job_id, "console:admin", "admin") and "@" in reply_to
    new = [j for j in bk.jobs.values() if j.parent_job_id == nightly.job_id][-1]
    assert (new.type, new.ruleset, new.options) == (jtype, "GZQO", {"window": "1"})
    ops = [r for r in bk.audit() if r.event == "console.operate" and r.detail.get("action") == "retry"]
    assert ops and ops[-1].detail["from"] == nightly.job_id and ops[-1].job_id == new.job_id


def test_a_scheduler_job_retry_needs_the_matrix_row_and_a_failed_job(
    b4: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from console import step4
    from tb_common import authz

    bk = b4["backend"]
    base: dict[str, Any] = {"type": "INGEST", "ruleset": None, "requested_by": "scheduler", "received_at": _T,
                            "updated_at": _T, "options": {}}  # fmt: skip
    failed = bk.add_job(Job(job_id=_ulid(704), state="failed", error=JobError(step="running", message="x"), **base))
    running = bk.add_job(Job(job_id=_ulid(705), state="running", **base))
    c, csrf = login(b4["app"])
    assert c.post(f"/admin/jobs/{running.job_id}/retry", data={"csrf": csrf, "confirm": "yes"}).status_code == 409
    real = authz.permit
    monkeypatch.setattr(step4, "permit", lambda role, action, *a: authz.Decision(False, role, action, "role")
                        if action == "job.retry_scheduled" else real(role, action, *a))  # fmt: skip
    assert f'data-testid="retry-{failed.job_id}"' not in c.get("/admin", params={"tab": "jobs"}).text
    assert c.post(f"/admin/jobs/{failed.job_id}/retry", data={"csrf": csrf, "confirm": "yes"}).status_code == 403
    assert not getattr(bk, "retried", [])


def test_only_the_administrator_holds_the_retry_of_scheduled_jobs() -> None:
    from tb_common.authz import MATRIX_ROLES, permit, role_allowed

    assert [r for r in MATRIX_ROLES if permit(r, "job.retry_scheduled").allowed] == ["admin"]
    # the retry right is not a right to start them: the administrator still may not start these three
    assert {t for t in _scheduler_types() if not role_allowed("admin", t)} == {"INGEST", "RETENTION", "CALIBRATION"}


def test_admin_data_sources_from_ingest_records(b4: dict[str, Any]) -> None:
    au = AuditLog(b4["backend"].audit_dir)
    au.append(
        "ingest.done",
        actor="adapter",
        detail={"source": "csv", "counts": {"Patient": 500, "Condition": 1500}, "validation_error_pct": 0.12},
    )
    c, _ = login(b4["app"])
    page = c.get("/admin", params={"tab": "sources"}).text
    assert ('data-source="csv"' in page and "500" in page and "2,000" in page) or "2000" in page
    assert "0.12 %" in page


# ---------------------------------------------------------------------------------------------- languages
def _fields(text: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(text) if f}


def test_every_key_in_every_language_with_the_same_placeholders() -> None:
    for lang, cat in CATALOGUES.items():
        assert set(cat) == set(EN), (lang, sorted(set(EN) ^ set(cat))[:10])
        for key, text in EN.items():
            assert _fields(cat[key]) == _fields(text), (lang, key)


def test_step4_strings_are_translated() -> None:
    same = [k for k, v in S4_EN.items() if S4_JA[k] == v and not re.fullmatch(r"[A-Z0-9 \-]+|GZQO-0001", v)]
    assert same == []


def test_proposed_mark_labels() -> None:
    ja, zh = CATALOGUES["ja"], CATALOGUES["zh-TW"]
    assert (ja["mark.approach"], ja["mark.need_info"], ja["mark.not_suitable"], ja["mark.ask_doctor"]) == (
        "声をかける",
        "情報が必要",
        "今回は見合わせる",
        "主治医に確認",
    )
    assert (zh["mark.approach"], zh["mark.need_info"], zh["mark.not_suitable"], zh["mark.ask_doctor"]) == (
        "邀請",
        "需要更多資訊",
        "暫不邀請",
        "詢問主治醫師",
    )


def test_redcap_caption_in_the_readers_language() -> None:
    assert _rc_note("REDCap record 17 (consent withdrawn)") == ("17", "consent withdrawn")
    assert _rc_note("REDCap record 9") == ("9", "")
    assert _rc_note("comorbidity") is None


@pytest.mark.parametrize("lang", ["ja", "zh-TW"])
def test_step4_pages_have_no_english(b4: dict[str, Any], lang: str) -> None:
    english = {
        v.split("{")[0].strip()
        for k, v in S4_EN.items()
        if CATALOGUES[lang][k] != v and " " in v and not k.startswith("cmd.ex.")
    } - {""}
    for user, pw, paths in (
        ("admin", ADMIN_PW, ("/admin", "/admin?tab=jobs", "/admin?tab=sources", "/account", "/help")),
        ("crc", PW, ("/account", "/help", "/notices/received", "/cmd?q=zzz")),
        ("cra", PW, ("/account", "/help")),
    ):
        c, csrf = login(b4["app"], user, pw)
        _ja(c, csrf, lang)
        for path in paths:
            page = c.get(path).text
            leaked = [e for e in english if e in page]
            assert leaked == [], (user, path, leaked[:3])


# ---------------------------------------------------------------------------------------------- canary on the Models tile
def test_models_tile_shows_the_canary_date_and_result_and_runs_it(b4: dict[str, Any]) -> None:
    """TB-PLAN-03 step 2 (D-117): the admin Models tile shows when the pair canary last ran and how it went."""
    from tests.console.test_console_app import MODELS_INFO

    bk = b4["backend"]
    pair = {
        **MODELS_INFO,
        "mode": "agreement",
        "verifier_model": "v-verifier",
        "note_block": "both_agree",
        "may_block": True,
    }
    bk.models_info = {
        **pair,
        "canary": {
            "gate": "on",
            "code": "ok",
            "running": False,
            "at": "2026-11-08T03:10:00",
            "cases": 54,
            "pair_correct": 52,
        },
    }
    c, csrf = login(b4["app"])
    page = c.get("/admin").text
    tile = page[page.index('data-testid="tile-models"') :]
    assert 'data-testid="models-canary"' in tile and "passed 2026-11-08 03:10, the pair 52 of 54 correct" in tile
    assert 'data-testid="canary-run"' in tile
    _ja(c, csrf)
    assert "2026-11-08 03:10 に合格" in c.get("/admin").text
    _ja(c, csrf, "zh-TW")
    assert "2026-11-08 03:10 通過" in c.get("/admin").text
    _ja(c, csrf, "en")
    bk.models_info = {
        **pair,
        "may_block": False,
        "canary": {"gate": "on", "code": "failed", "running": False, "at": "2026-11-08T03:10:00"},
    }
    page = c.get("/admin").text
    assert "failed 2026-11-08 03:10: note answers are not final until it passes" in page
    r = c.post("/admin/models/canary", data={"csrf": csrf}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin?notice=canary" and bk.canary_runs == 1
    assert "The model self-test is running" in c.get(r.headers["location"]).text
    assert c.post("/admin/models/canary", data={"csrf": "x"}).status_code == 400
    bk.models_info = {**pair, "canary": {"gate": "off", "code": "off", "running": False, "at": None}}
    page = c.get("/admin").text
    assert "off on this box" in page and 'data-testid="canary-run"' not in page
