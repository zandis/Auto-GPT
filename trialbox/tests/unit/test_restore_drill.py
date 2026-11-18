"""H-33 (D-1122): the restore follower, the comparison rules and the findings file, on stand-ins (no Docker).

The compose run itself is ``make restore-drill`` (tools/restore_drill.py); this test holds what can be held without a
box: the restore page's commands are found by H-22's rule, the follower lifts only by ``LIFTS`` and records each, the
comparison calls a store equal only by D-1122's rules, and the committed findings quote the page and fit the
register's ``--add-from`` form.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from tools import restore_drill as rd
from tools import runbook_install as ri

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
FINDINGS = ROOT / rd.RECORD_DIR / "findings.json"
RECORD = ROOT / rd.RECORD_DIR / "run.json"


def test_the_restore_pages_commands_by_h22s_rule_plus_trialbox() -> None:
    cmds = rd.restore_commands()
    texts = [c.text for c in cmds]
    first, last = rd.section_lines()
    assert all(first <= c.line <= last and c.file == rd.PAGE for c in cmds)
    # the path's commands are all there, in the page's order
    order = [rd.find(cmds, s.starts).line for s in rd.PATH if s.starts]
    assert order == sorted(order)
    assert any(t.startswith("TB_DB_ROLES_CMD=") for t in texts)
    # H-22's rule alone does not see `trialbox restore`: the card's one added head does
    assert not ri.is_command("trialbox restore <file>")
    with rd._heads(rd.HEADS):
        assert ri.is_command("trialbox restore <file>")
    assert rd.HEADS[:-1] == ri.HEADS  # the module's heads are put back


class Box:
    """A stand-in host: what a host installed as §1 says answers, until a lift supplies what the page did not."""

    def __init__(self, page_right: bool = False) -> None:
        self.page_right = page_right
        self.ran: list[tuple[str, dict[str, str]]] = []

    def __call__(self, cmd: str, env: Mapping[str, str], timeout: float | None) -> tuple[int, str]:
        self.ran.append((cmd, dict(env)))
        if self.page_right:
            return 0, "{}"
        if cmd.startswith("trialbox "):
            return 127, "bash: line 1: trialbox: command not found"
        if cmd.startswith("python3 -m tools.trialbox") and "venv" not in env.get("PATH", ""):
            return 1, "ModuleNotFoundError: No module named 'zstandard'"
        if cmd.startswith("docker compose ") and "--project-directory deploy" not in cmd:
            return 1, "no configuration file provided: not found"
        if " restore " in cmd and "TB_DB_URL" not in env:
            return 1, "restore: TB_DB_URL is not set: nothing to back up from the database"
        if " restore " in cmd:
            return 0, '{"complete": true, "password": "postgresql://trialbox:s3cret@127.0.0.1:5433/trialbox_wf"}'
        return 0, "ok"


def _follow(box: Box, tmp_path: Path) -> tuple[rd.Follower, dict[str, object]]:
    clock = iter(range(1000))
    fol = rd.Follower(box, hide=["s3cret"], clock=lambda: float(next(clock)))
    fol.machine = {"TB_BACKUP_DIRS": "objects=/x"}

    def reinstall() -> rd.Ran:
        return rd.Ran("reinstall", "Reinstall (§1)", "make up-test", 0, 1.0, "", list(fol.lifted))

    db = {"TB_DB_URL": "postgresql://trialbox:s3cret@127.0.0.1:5433/trialbox_wf"}
    res = fol.follow(tmp_path / "b.tbbak", tmp_path / "k.key", tmp_path / "packs", lambda: db, reinstall,
                     venv_bin="/release/.venv/bin")  # fmt: skip
    return fol, res


def test_the_follower_lifts_only_by_name_and_records_each(tmp_path: Path) -> None:
    box = Box()
    fol, res = _follow(box, tmp_path)
    assert res["page_alone"] is False
    assert str(res["stopped_at"]).startswith("trialbox-command")
    assert res["lifts"] == ["trialbox-command", "host-python", "reinstall-test-stack", "compose-project",
                            "objects-bind", "restore-db-url"]  # fmt: skip
    assert set(res["lifts"]) <= set(rd.LIFTS)
    keys = [r.key for r in fol.steps]
    assert keys[:3] == ["verify", "verify", "verify"] and keys[-3:] == ["restore", "migrate", "start"]
    restore = [r for r in fol.steps if r.key == "restore"]
    assert restore[-1].rc == 0 and "TB_DB_ROLES_CMD" in box.ran[-3][1]
    # what the page names is supplied; nothing secret is kept in the record
    assert all("s3cret" not in r.run + r.out for r in fol.steps)
    assert "--refdata" in restore[-1].run and "[" not in restore[-1].run
    # every lift is ``page`` (a finding) or ``machine`` (this machine), never another kind
    assert {rd.LIFTS[k].kind for k in res["lifts"]} <= {"page", "machine"}


def test_a_page_that_is_right_needs_no_page_lift(tmp_path: Path) -> None:
    fol, res = _follow(Box(page_right=True), tmp_path)
    assert res["page_alone"] is True and res["stopped_at"] is None
    assert all(rd.LIFTS[k].kind == "machine" for k in fol.lifted)


def test_every_lift_names_words_the_restore_page_holds() -> None:
    text = ri._fold((ROOT / rd.PAGE).read_text(encoding="utf-8"))
    for lift in rd.LIFTS.values():
        assert ri._fold(lift.needle) in text, lift.key


def test_equal_means_d1122() -> None:
    before = {"a.t": [2, "h1"], "audit.journal": [3, "x"], "orch.pool": [3, "p"]}
    after = {"a.t": [2, "h1"], "audit.journal": [5, "y"], "edc.draft": [0, ""], "orch.pool": [2, "q"]}
    allowed = rd.EXPECTED_CHANGES["db:trialbox_wf"]
    c = rd.compare_tables(before, after, allowed)
    assert c["ok"] and c["unequal"] == [] and set(c["expected"]) == {"audit.journal", "edc.draft", "orch.pool"}
    # a table the restore lost is never "expected", and a new edc table only when it was not there before
    assert not rd.compare_tables({**before, "x.y": [1, "z"]}, after, allowed)["ok"]
    assert not rd.compare_tables({**before, "edc.draft": [4, "d"]}, after, allowed)["ok"]
    files = rd.compare_files({"a": "1", "tmp/s": "2", "db/gen/g1.duckdb": "3"}, {"a": "1"},
                             rd.EXPECTED_CHANGES["volume:lake-data"])  # fmt: skip
    assert files["ok"] and files["missing"] == ["db/gen/g1.duckdb", "tmp/s"]
    assert not rd.compare_files({"a": "1"}, {"a": "2"}, {})["ok"]
    assert not rd.compare_files({"a": "1"}, {}, {})["ok"]


def test_the_comparison_table_has_a_row_per_store() -> None:
    fp = {"db": {"trialbox_wf": {"a.t": [1, "h"]}}, "volumes": {"console-data": {"f": "1"}},
          "audit_head": {"lines": 3, "hash": "abc"}, "optouts": ["p|opt_out"], "rulesets": {"GZQO": {"version": "1"}},
          "accounts": ["u|admin|h"]}  # fmt: skip
    after = json.loads(json.dumps(fp))
    after["audit_head"] = {"lines": 4, "hash": "abd", "verified": True, "prefix_of_after": True}
    rows = rd.compare(fp, after)
    assert [r["store"] for r in rows] == ["database trialbox_wf", "volume console-data", "the audit chain's head",
                                          "the opt-out list", "the approved rule sets", "the accounts"]  # fmt: skip
    assert all(r["equal"] for r in rows)
    after["optouts"] = []
    assert not next(r for r in rd.compare(fp, after) if r["store"] == "the opt-out list")["equal"]
    after["audit_head"]["prefix_of_after"] = False
    assert not next(r for r in rd.compare(fp, after) if r["store"] == "the audit chain's head")["equal"]


def test_scrub_keeps_no_password() -> None:
    assert "pw" not in rd.scrub("postgresql://trialbox:pw@127.0.0.1:5433/x")
    assert "TOKEN" not in rd.scrub("a TOKEN b", ["TOKEN"])


def test_the_committed_findings_fit_the_register_and_quote_the_page() -> None:
    doc = json.loads(FINDINGS.read_text(encoding="utf-8"))
    assert rd.check_findings(doc) == []
    assert doc["card"] == rd.CARD and doc["source"] == rd.PAGE_OUT and doc["decision"] == rd.DECISION
    for f in doc["findings"]:
        place, _, line = str(f["place"]).rpartition(":")
        text = (ROOT / place).read_text(encoding="utf-8").split("\n")
        near = ri._fold(" ".join(text[max(0, int(line) - 3) : int(line) + 3]))
        assert ri._fold(str(f["page_says"])) in near, f["id"]
    # the register would take them as they are: each row passes the register's own row rules (nothing is written:
    # only lane V writes the register)
    from tools import findings_register as fr

    card, _title, cells = fr.rows_from(doc, fr.REGISTER, ROOT)
    for i, c in enumerate(cells):
        assert c["Id"].startswith(f"{card}-"), c["Id"]
        assert fr.row_problems(fr.Row(i + 1, card, c), fr.REGISTER.parent, ROOT) == [], c["Id"]


@pytest.mark.skipif(not RECORD.is_file(), reason="no committed run record yet")
def test_the_committed_record_holds_no_secret_and_backs_the_findings() -> None:
    text = RECORD.read_text(encoding="utf-8")
    assert "_cookie" not in text and "postgresql://trialbox:" + "change-me" not in text
    rec = json.loads(text)
    doc = json.loads(FINDINGS.read_text(encoding="utf-8"))
    lifted = set(rec["follow"]["lifts"])
    for f in doc["findings"]:
        if f.get("lift"):
            assert f["lift"] in lifted, f["id"]
