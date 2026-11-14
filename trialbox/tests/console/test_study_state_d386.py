"""D-386 (T-622, LIFE-008, LIFE-013): the study's state and identifiers.

* The state machine: start-up -> open -> paused -> open -> closed; closed is final; every change is kept with who,
  when and why, and audited in the same transaction.
* A paused study gives no list (the timer holds MICROBATCH and COHORT and audits the hold; a SCREEN, MICROBATCH or
  COHORT asked for by hand fails at its first step) and no mail (N1 and N2 leave it out).
* jRCT and Taiwan registry ids validate (with NCT and UMIN-CTR) and print on the screening log, page and XLSX.

Synthetic data only: the registry ids below follow the registries' public formats and name no real study."""

from __future__ import annotations

import io
import json
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from console import notify
from console.auth import User
from console.i18n import CATALOGUES
from console.sitestore import (
    STATE_MOVES,
    STUDY_STATES,
    NotifyPerson,
    SiteStore,
    StudyIdentity,
    registry_id_ok,
)

from tests.console.test_console_app import _done_screen, _ulid, box, login  # noqa: F401 - box is a fixture
from tests.console.test_role_pages import _csrf, _user
from tests.console.test_step2 import _row
from tests.console.test_team_pages import _log_pi_and_sub

AT = "2026-11-02T00:00:00+00:00"
MONDAY = date(2026, 11, 2)
# synthetic ids in each registry's public format
NCT = "NCT09990001"
JRCT = "jRCT2039990001"
JRCT_S = "jRCTs039990001"
UMIN = "UMIN000999001"
TW = "TW-SYN-2026-001"


# ---------------------------------------------------------------------------------------------- identifiers
@pytest.mark.parametrize(
    ("registry", "value", "ok"),
    [
        ("nct", NCT, True),
        ("nct", "NCT1234", False),
        ("nct", "nct09990001", False),
        ("jrct", JRCT, True),
        ("jrct", JRCT_S, True),
        ("jrct", "jrct2039990001", False),  # the prefix is case-sensitive
        ("jrct", "jRCT12", False),
        ("jrct", "jRCTss039990001", False),
        ("umin", UMIN, True),
        ("umin", "UMIN99", False),
        ("tw", TW, True),
        ("tw", "TFDA/2026.0001", True),
        ("tw", "ab", False),
        ("tw", "has space 01", False),
        ("tw", JRCT, False),  # another registry's id in the Taiwan field
        ("tw", NCT, False),
        ("xx", "anything", False),
    ],
)
def test_registry_ids_validate(registry: str, value: str, ok: bool) -> None:
    assert registry_id_ok(registry, value) is ok


def test_identity_problems_name_the_wrong_fields() -> None:
    good = StudyIdentity("Synthetic Pharma", "SYN-001", "2026-10-01", {"jrct": JRCT, "tw": TW, "nct": NCT})
    assert good.problems() == []
    bad = StudyIdentity("x\x00", "-bad", "2026-02-30", {"jrct": "jRCT1", "tw": NCT, "who": "1"})
    assert bad.problems() == ["sponsor", "protocol_no", "siv_date", "registry.jrct", "registry.tw", "registry.who"]
    assert good.lines() == [("sponsor", "Synthetic Pharma"), ("protocol_no", "SYN-001"), ("siv_date", "2026-10-01"),
                            ("registry.nct", NCT), ("registry.jrct", JRCT), ("registry.tw", TW)]  # fmt: skip


def test_identity_store_round_trip_and_refusal() -> None:
    s = SiteStore()
    assert s.study_identity("GZQO").lines() == []
    s.save_study_identity("gzqo", StudyIdentity("Synthetic Pharma", "SYN-001", "", {"jrct": JRCT, "tw": TW}), "crc",
                          AT)  # fmt: skip
    got = s.study_identity("GZQO")
    assert got.registry_ids == {"jrct": JRCT, "tw": TW} and got.by == "crc" and got.siv_date == ""
    with pytest.raises(ValueError, match=r"registry\.jrct"):
        s.save_study_identity("GZQO", StudyIdentity(registry_ids={"jrct": "JRCT2039990001"}), "crc", AT)
    assert s.study_identity("GZQO").registry_ids["jrct"] == JRCT  # unchanged


# ---------------------------------------------------------------------------------------------- the state machine
def test_the_state_machine() -> None:
    assert STUDY_STATES == ("startup", "open", "paused", "closed")
    assert STATE_MOVES["closed"] == ()
    s = SiteStore()
    cur = s.study_state("GZQO")
    assert cur.state == "open" and cur.runs and cur.by == ""  # no recorded state: open, as before D-386
    with pytest.raises(ValueError, match="from open to startup"):
        s.set_study_state("GZQO", "startup", "", "crc", AT)
    s.set_study_state("GZQO", "paused", "sponsor letter", "crc", "2026-11-02T01:00:00+00:00")
    assert not s.study_state("GZQO").runs
    s.set_study_state("GZQO", "open", "", "crc", "2026-11-03T01:00:00+00:00")
    s.set_study_state("GZQO", "closed", "last patient out", "pi", "2026-11-04T01:00:00+00:00")
    for to in STUDY_STATES:
        with pytest.raises(ValueError):
            s.set_study_state("GZQO", to, "", "crc", "2026-11-05T01:00:00+00:00")
    hist = s.state_history("GZQO")
    assert [(e.prev, e.state) for e in hist] == [("open", "paused"), ("paused", "open"), ("open", "closed")]
    assert hist[0].reason == "sponsor letter" and hist[2].by == "pi"
    with pytest.raises(ValueError):
        s.set_study_state("GZQO", "frozen", "", "crc", AT)


def test_a_failed_audit_keeps_the_old_state() -> None:
    s = SiteStore()

    def boom(_new: Any) -> None:
        raise RuntimeError("audit down")

    with pytest.raises(RuntimeError):
        s.set_study_state("GZQO", "paused", "x", "crc", AT, before_commit=boom)
    assert s.study_state("GZQO").state == "open" and s.state_history("GZQO") == []


# ---------------------------------------------------------------------------------------------- no mail when paused
def _helpers(store: SiteStore, life: dict[str, Any] | None = None) -> Any:
    users = [User("pi", "investigator", "pi@hospa.test"), User("crc", "coordinator", "crc@hospa.test")]
    rows = [_row("1" * 16, "2026-11-02T09:00:00+08:00"), _row("2" * 16, "2026-11-04T10:00:00+08:00")]
    return SimpleNamespace(
        store=store,
        users=SimpleNamespace(users=lambda: users),
        trials=lambda _sess: [SimpleNamespace(id="GZQO")],
        week_bundle=lambda _sess, _rs: {"rows": [dict(r) for r in rows], "cl": None},
        life_mail=(lambda _rs, _day: life) if life else None,
        bk=SimpleNamespace(registry_rows=lambda _rs: []),
        delegated_ok=lambda _u, _rs, *_: True,  # T-102c: the log's answer (the pi is delegated); no fallback in notify
    )


def test_a_paused_study_gives_no_mail() -> None:
    """LIFE-008 acceptance: open, N1 and N2 go out on Monday; paused, neither does; open again, they come back."""
    store = SiteStore()
    store.save_notify_person(NotifyPerson("pi", None, lang="en"))
    store.save_notify_person(NotifyPerson("crc", None, lang="en"))
    h = _helpers(store)
    assert {n.kind for n in notify.collect(h, MONDAY)} == {"N1", "N2"}
    store.set_study_state("GZQO", "paused", "sponsor letter", "crc", AT)
    assert notify.collect(h, MONDAY) == []
    store.set_study_state("GZQO", "open", "", "crc", "2026-11-02T00:10:00+00:00")
    assert {n.kind for n in notify.collect(h, MONDAY)} == {"N1", "N2"}


def test_a_paused_study_still_mails_its_participants_care() -> None:
    """A pause stops recruitment, not the care of the enrolled: an unacknowledged serious AE is still mailed, without
    any list row. Start-up and closed mail nothing."""
    store = SiteStore()
    store.save_notify_person(NotifyPerson("pi", None, lang="en"))
    h = _helpers(store, life={"today": [], "week": [], "overdue": [], "reports": [], "sae": 1})
    store.set_study_state("GZQO", "paused", "sponsor letter", "crc", AT)
    n1 = notify.collect(h, MONDAY, ("N1",))
    assert len(n1) == 1 and n1[0].counts == {"today": 0, "week": 0, "sae": 1}
    assert "11111111" not in n1[0].body
    store.set_study_state("GZQO", "closed", "ended", "crc", "2026-11-02T00:10:00+00:00")
    assert notify.collect(h, MONDAY, ("N1",)) == []


# ---------------------------------------------------------------------------------------------- no list when paused
class _Orch:
    def __init__(self) -> None:
        self.scenarios = {"MICROBATCH": None, "COHORT": None, "CALIBRATION": None, "INGEST": None}
        self.created: list[tuple[str, str | None]] = []
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.audit = SimpleNamespace(append=lambda ev, **kw: self.events.append((ev, kw)))

    def create(self, req: Any) -> None:
        self.created.append((req.type, req.ruleset))


def test_a_paused_study_gives_no_list() -> None:
    """LIFE-008 acceptance: the timer holds the list jobs of a paused study and audits the hold; a list job asked for
    by hand (SCREEN, MICROBATCH, COHORT) fails at its first step with the reason; other jobs are not held."""
    from orchestrator import scheduler
    from orchestrator.clients import StepFailed
    from orchestrator.scenarios import cohort, microbatch, screen

    store = SiteStore()
    orch = _Orch()
    scheduler._submit(orch, "MICROBATCH", "GZQO")  # type: ignore[arg-type]
    assert orch.created == [("MICROBATCH", "GZQO")]
    scheduler.require_open("GZQO")  # open: no refusal
    store.set_study_state("GZQO", "paused", "sponsor letter", "crc", AT)
    assert scheduler.study_state("gzqo") == "paused"
    for jtype in ("MICROBATCH", "COHORT"):
        scheduler._submit(orch, jtype, "GZQO")  # type: ignore[arg-type]
    scheduler._submit(orch, "CALIBRATION", "GZQO")  # type: ignore[arg-type]  # learning from feedback, not a list
    assert orch.created == [("MICROBATCH", "GZQO"), ("CALIBRATION", "GZQO")]
    assert [(e, kw["detail"]["job"], kw["detail"]["state"]) for e, kw in orch.events] == [
        ("scheduler.held", "MICROBATCH", "paused"),
        ("scheduler.held", "COHORT", "paused"),
    ]
    ctx: Any = SimpleNamespace(job=SimpleNamespace(ruleset="GZQO", options={}))
    for run in (screen.run, microbatch.run, cohort.run):
        with pytest.raises(StepFailed, match="GZQO is paused: lists run only for an open study"):
            run(ctx)


def test_without_a_trial_database_every_study_is_open(monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator import scheduler

    monkeypatch.delenv("TB_DB_URL")
    assert scheduler.study_state("GZQO") == "open"


# ---------------------------------------------------------------------------------------------- the console page
def _events(b: dict[str, Any], name: str) -> list[dict[str, Any]]:
    out = []
    for f in sorted((b["dir"] / "audit").glob("*")):
        for line in f.read_text().splitlines():
            if line and json.loads(line).get("event") == name:
                out.append(json.loads(line))
    return out


def test_the_coordinator_pauses_the_study_and_the_ids_print_on_the_log(box: dict[str, Any]) -> None:  # noqa: F811
    """The page: the coordinator pauses with a reason (audited), saves the identifiers (a malformed jRCT id is shown
    back, nothing saved), and the screening log page and its XLSX "about" sheet print the ids and the state."""
    from openpyxl import load_workbook

    _done_screen(box["backend"], _ulid(9801))
    crc = _user(box, "crc1", "coordinator")
    page = crc.get("/studies/GZQO/state")
    assert page.status_code == 200 and 'data-state="open"' in page.text and 'data-testid="state-default"' in page.text
    csrf = _csrf(page.text)
    assert crc.post("/studies/GZQO/state", data={"csrf": csrf, "state": "paused"}).status_code == 400  # no reason
    assert crc.post("/studies/GZQO/state", data={"csrf": csrf, "state": "startup", "reason": "x"}).status_code == 400
    r = crc.post("/studies/GZQO/state", data={"csrf": csrf, "state": "paused", "reason": "sponsor letter"},
                 follow_redirects=False)  # fmt: skip
    assert r.status_code == 303
    page = crc.get("/studies/GZQO/state").text
    assert 'data-state="paused"' in page and "sponsor letter" in page and 'data-testid="state-history"' in page
    ev = _events(box, "console.study_state")
    assert len(ev) == 1 and ev[0]["detail"] == {"state": "paused", "prev": "open", "reason": "sponsor letter"}
    # identifiers: a malformed jRCT id is refused and shown back
    form = {"csrf": csrf, "sponsor": "Synthetic Pharma", "protocol_no": "SYN-001", "siv_date": "2026-10-01",
            "registry_jrct": "JRCT-1", "registry_tw": TW}  # fmt: skip
    bad = crc.post("/studies/GZQO/identity", data=form)
    assert bad.status_code == 400 and 'data-testid="state-error"' in bad.text and "jRCT id" in bad.text
    assert 'value="JRCT-1"' in bad.text and SiteStore().study_identity("GZQO").lines() == []
    form["registry_jrct"] = JRCT
    assert crc.post("/studies/GZQO/identity", data=form, follow_redirects=False).status_code == 303
    assert _events(box, "console.study_identity")[0]["detail"]["jrct"] == JRCT
    log = crc.get("/studies/GZQO/screening-log").text
    assert f'data-testid="log-id-jrct">{JRCT}<' in log and f'data-testid="log-id-tw">{TW}<' in log
    assert "Closed to recruitment / paused" in log  # D-763 (LIFE-006): the label says what the state means
    x = crc.get("/studies/GZQO/screening-log.xlsx")
    assert x.status_code == 200
    about = {row[0]: row[1:] for row in load_workbook(io.BytesIO(x.content))["about"].iter_rows(values_only=True)}
    assert about["registry.jrct"][0] == JRCT and about["registry.tw"][0] == TW
    assert about["sponsor"][0] == "Synthetic Pharma" and about["state"][0] == "paused"
    assert about["state.paused"][1] == "console:crc1" and about["state.paused"][2] == "sponsor letter"
    assert str(about["state.paused"][0]).startswith("20")  # the date of the change


def test_who_may_change_the_state(box: dict[str, Any]) -> None:  # noqa: F811
    """``permit(role, "study.state")``: the coordinator and the study's PI change it; the administrator, a viewer and
    a CRO account do not; a refusal is audited."""
    _done_screen(box["backend"], _ulid(9802))
    pi = _user(box, "drsato", "investigator")
    sub = _user(box, "drkato", "investigator")
    _log_pi_and_sub(box, pi, ("screen",))  # the log names drsato PI; drkato is a sub-investigator
    page = pi.get("/studies/GZQO/state")  # D-380 (ROLE-008): the PI the log names
    assert page.status_code == 200 and 'data-testid="state-form"' in page.text
    page = sub.get("/studies/GZQO/state")
    assert page.status_code == 200 and 'data-testid="state-readonly"' in page.text
    assert 'data-testid="state-form"' not in page.text
    r = sub.post("/studies/GZQO/state", data={"csrf": _csrf(page.text), "state": "paused", "reason": "x"})
    assert r.status_code == 403 and SiteStore().study_state("GZQO").state == "open"
    assert any(e["actor"] == "console:drkato" for e in _events(box, "console.denied"))
    r = pi.post("/studies/GZQO/state", data={"csrf": _csrf(pi.get("/studies/GZQO/state").text), "state": "paused",
                                             "reason": "IRB decision"}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303 and SiteStore().study_state("GZQO").by == "console:drsato"
    cro = _user(box, "cra1", "cro")
    assert cro.get("/studies/GZQO/state").status_code in (403, 404)
    viewer = _user(box, "viewer2", "viewer")
    assert viewer.get("/studies/GZQO/state").status_code in (403, 404)
    from tb_common.authz import permit

    assert permit("coordinator", "study.state").allowed and not permit("admin", "study.state").allowed
    assert not permit("investigator", "study.state").allowed  # only as the study's PI


def test_the_strings_exist_in_every_language() -> None:
    from console.i18n_state import EN, JA, ZH

    assert set(EN) == set(JA) == set(ZH)
    for lang, cat in CATALOGUES.items():
        for st in STUDY_STATES:
            assert cat[f"sstate.{st}"] and cat[f"sstate.effect.{st}"], (lang, st)
    assert CATALOGUES["ja"]["sstate.paused"] == "募集終了／一時停止" and CATALOGUES["zh-TW"]["sstate.open"] == "收案中"
