"""NEW-LIFE-9 / LIFE-011 (D-778): a reason for every change, and append-only trails.

Where the built-in forms are the trial record, a consent date or the day the site learned of an SAE could be changed
with no "why", and the before and after lived only in tables the same service can rewrite. Now:

* changing a saved value in a form needs a reason; the reason is kept in the value's history, and the chain's
  ``data.entry`` event names each changed field with the sha256 of its old and new value, and the reason (a first
  entry needs none);
* an undo of a lifecycle step needs a reason, kept on the step and in the chain's ``life.step`` event;
* the investigator's SAE acknowledgements and the decisions on possible deviations are append-only like the value
  history and the steps (EDC-009, D-582): the service's own connection cannot update or delete them.

Synthetic data only."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import pytest

from tests.console.test_console_app import box, login, name_pi  # noqa: F401 - the fixture is used by name
from tests.console.test_lifecycle_pages import PW, _save, lb  # noqa: F401 - the fixture is used by name


def _sha(v: str) -> str:
    return hashlib.sha256(v.encode("utf-8")).hexdigest()


def _events(lb: dict[str, Any], name: str) -> list[dict[str, Any]]:  # noqa: F811
    """The data core's own chain (the orchestrator's audit log)."""
    out = []
    for f in sorted(lb["audit"].directory.glob("*.jsonl")):
        out += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x]
    return [e for e in out if e.get("event") == name]


def _consent(lb: dict[str, Any], c: Any, csrf: str, no: str, day: str, reason: str = "") -> Any:  # noqa: F811
    data = {"ic_date": day, "ic_version": "v1", "ic_copy": "1"}
    if reason:
        data["reason"] = reason
    extra = {"reason": reason} if reason else {}
    return c.post("/studies/GZQO/entry", data={"csrf": csrf, "record": no, "event": "", "form": "tb_consent",
                                               **{f"f_{k}": v for k, v in data.items() if k != "reason"}, **extra})  # fmt: skip


def test_a_changed_value_needs_a_reason_and_the_chain_names_old_and_new(lb: dict[str, Any]) -> None:  # noqa: F811
    no, _other = lb["nos"]
    c, csrf = login(lb["app"], "crc", PW)
    c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})
    c.get("/studies/GZQO/subjects")  # the list takes the candidates in as subjects
    first = _consent(lb, c, csrf, no, "2026-11-03")
    assert first.status_code == 200 and 'data-testid="entry-refused"' not in first.text  # a first entry: no reason
    r = _consent(lb, c, csrf, no, "2026-11-02")
    assert 'data-testid="entry-refused"' in r.text and 'data-testid="why-ic_date"' in r.text  # refused without a reason
    assert lb["dc"].record("GZQO", no)["ic_date"] == "2026-11-03"
    r = _consent(lb, c, csrf, no, "2026-11-02", reason="the signed form is dated the 2nd")
    assert lb["dc"].record("GZQO", no)["ic_date"] == "2026-11-02"
    hist = [x for x in lb["dc"].history("GZQO", no) if x["field"] == "ic_date"]
    assert [x["reason"] for x in hist] == ["", "the signed form is dated the 2nd"]
    entries = [e for e in _events(lb, "data.entry") if e["detail"].get("record") == no]
    last = entries[-1]["detail"]
    assert last["reason"] == "the signed form is dated the 2nd"
    assert last["changes"]["ic_date"] == {"old": _sha("2026-11-03"), "new": _sha("2026-11-02")}
    assert "2026-11-0" not in json.dumps(last)  # the values themselves are not in the chain


def test_an_undo_needs_a_reason_kept_on_the_step_and_in_the_chain(lb: dict[str, Any]) -> None:  # noqa: F811
    no, _other = lb["nos"]
    c, csrf = login(lb["app"], "crc", PW)
    c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})
    c.get("/studies/GZQO/subjects")  # the list takes the candidates in as subjects
    r = c.post(f"/studies/GZQO/subjects/{no}/step", data={"csrf": csrf, "to": "approached", "on_day": "2026-11-02"})
    assert 'data-testid="life-saved"' in r.text, r.text[-800:]
    r = lb["oc"].post(f"/studies/GZQO/subjects/{no}/undo", json={})
    assert r.status_code == 409 and "reason" in r.text.lower(), r.text
    r = lb["oc"].post(f"/studies/GZQO/subjects/{no}/undo", json={"note": "marked on the wrong patient"})
    assert r.status_code == 200, r.text
    step = lb["dc"].db.fetchdicts("SELECT * FROM subject_step WHERE study = ? AND record = ? ORDER BY id DESC",
                                  ("GZQO", no))[0]  # fmt: skip
    assert step["note"] == "marked on the wrong patient"
    ev = [e for e in _events(lb, "life.step") if e["detail"].get("source") == "undo"]
    assert ev and ev[-1]["detail"]["reason"] == "marked on the wrong patient"


def test_the_undo_button_asks_for_the_reason(lb: dict[str, Any]) -> None:  # noqa: F811
    no, _other = lb["nos"]
    c, csrf = login(lb["app"], "crc", PW)
    c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})
    c.get("/studies/GZQO/subjects")  # the list takes the candidates in as subjects
    c.post(f"/studies/GZQO/subjects/{no}/step", data={"csrf": csrf, "to": "approached", "on_day": "2026-11-02"})
    page = c.get(f"/studies/GZQO/subjects/{no}").text
    form = page[page.index("/undo") :][:800]
    assert re.search(r'name="note"[^>]*required', form), form


ROWS = {  # a synthetic row of each trail (inserting is allowed; changing or removing it is not)
    "ae_ack": ("INSERT INTO ae_ack (study, record, event, who, at) VALUES ('ZZ', 'ZZ-1', 'ae1', 'pi', 'now')"),
    "deviation_call": ("INSERT INTO deviation_call (study, record, key, decision, who, at) "
                       "VALUES ('ZZ', 'ZZ-1', 'k1', 'confirm', 'crc', 'now')"),
    "history": ("INSERT INTO history (study, record, event, field, old, new, \"by\", at, source) "
                "VALUES ('ZZ', 'ZZ-1', '', 'ic_date', NULL, '2026-11-01', 'crc', 'now', 'trialbox')"),
    "subject_step": ("INSERT INTO subject_step (study, record, old, new, on_day, who, at, source) "
                     "VALUES ('ZZ', 'ZZ-1', NULL, 'candidate', '2026-11-01', 'crc', 'now', 'page')"),
}  # fmt: skip


@pytest.mark.parametrize("table", sorted(ROWS))
def test_the_trails_are_append_only_for_the_service(lb: dict[str, Any], table: str) -> None:  # noqa: F811
    db = lb["dc"].db
    db.execute(ROWS[table])
    with pytest.raises(Exception, match="append-only"):
        db.execute(f"UPDATE {table} SET study = study WHERE study = 'ZZ'")
    with pytest.raises(Exception, match="append-only"):
        db.execute(f"DELETE FROM {table} WHERE study = 'ZZ'")


# ---------------------------------------------------------------------------------------------- never dropped
def test_a_change_without_a_reason_is_never_dropped(lb: dict[str, Any]) -> None:  # noqa: F811
    """The integrator's rule for D-778 (train 23): a change without a reason is refused with a plain message (the
    console's form) or saved with the reason marked missing (the API's direct write), never dropped; a change made by
    the system (a read-back, a resolved conflict) carries a system reason."""
    from datacore.store import NO_REASON

    no, _other = lb["nos"]
    lb["oc"].post("/studies/GZQO/forms/builtin", json={"by": "crc"})
    r = lb["oc"].put(f"/studies/GZQO/data/{no}", json={"event": "", "values": {"ic_date": "2026-11-03"}, "by": "crc"})
    assert r.status_code == 200, r.text
    r = lb["oc"].put(f"/studies/GZQO/data/{no}", json={"event": "", "values": {"ic_date": "2026-11-02"}, "by": "crc"})
    assert r.status_code == 200, r.text
    hist = [x for x in lb["dc"].history("GZQO", no) if x["field"] == "ic_date"]
    assert [(x["new"], x["reason"]) for x in hist] == [("2026-11-03", ""), ("2026-11-02", NO_REASON)]
    last = [e for e in _events(lb, "data.entry") if e["detail"].get("record") == no][-1]["detail"]
    assert last["reason"] == NO_REASON and set(last["changes"]) == {"ic_date"}
    # a value read back from a source: the system's reason, never blank
    lb["dc"].write("GZQO", no, "", "ic_copy", "1", "rc:read", "2026-11-08T01:00:00+00:00", "redcap")
    lb["dc"].write("GZQO", no, "", "ic_copy", "0", "rc:read", "2026-11-09T01:00:00+00:00", "redcap")
    rows = [x["reason"] for x in lb["dc"].history("GZQO", no) if x["field"] == "ic_copy"]
    assert rows == ["read back from redcap", "read back from redcap"]


def test_the_history_page_shows_the_reason(lb: dict[str, Any]) -> None:  # noqa: F811
    no, _other = lb["nos"]
    c, csrf = login(lb["app"], "crc", PW)
    c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})
    _consent(lb, c, csrf, no, "2026-11-03")
    _consent(lb, c, csrf, no, "2026-11-02", reason="the signed form is dated the 2nd")
    page = c.get(f"/studies/GZQO/history?record={no}").text
    assert "Reason for the change" in page and "the signed form is dated the 2nd" in page
