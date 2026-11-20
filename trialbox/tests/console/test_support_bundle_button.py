# ruff: noqa: F811 - the ob fixture is imported from test_ops_pages and taken by name
"""10K-5 (D-1381): the support bundle as a button on the operations pages.

The button is the operations action ``support_bundle``; the runner (inline here, the host's on a box) calls the same
builder and scan as ``trialbox support-bundle``, without the service logs (the review of 83a0640a: they can carry
patient pseudonyms). Held here: the happy path (confirm, make, download, the audit events with size and sha256 and
never a line of the bundle; no log member and the MANIFEST saying why), every other role of the matrix refused the
tab, the making and the download, signed-out access, a bundle that fails the scan is not handed out and the page says
so, the make event written before the file gets its final name and no bundle without it, the folder's check (a link,
a folder others may write), a file changed on disk or a link at its place not handed out, HEAD, CSRF, the texts in
en, ja and zh-TW. Synthetic data only: the one log line planted is invented.

Not held here: the refusal while a support session is on (10K-15, #1170, not on master when this was built)."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import re
import tarfile
from pathlib import Path
from typing import Any

import pytest
from console.i18n import CATALOGUES
from console.i18n_support_bundle import EN, JA, ZH
from fastapi.testclient import TestClient
from tb_common.authz import MATRIX_ROLES, admin_allowed

from tests.console.test_console_app import login
from tests.console.test_ops_pages import PW, _events, ob  # noqa: F401 - the fixture is used by name
from tools import support_bundle
from tools.trialbox import ops as tb_ops
from tools.trialbox import ops_support

OTHER_ROLES = tuple(r for r in MATRIX_ROLES if r != "admin")  # every role of the matrix but the administrator


def _plant_log(ob: dict[str, Any]) -> None:
    """One collected day of the console's log, synthetic: what the bundle's log part reads."""
    day = ob["deploy"] / "logs" / "services" / "2026-11-18"
    day.mkdir(parents=True)
    with gzip.open(day / "console.log.gz", "wt", encoding="utf-8") as fh:
        fh.write("2026-11-18T05:00:00Z console started (synthetic test line)\n")


def _make(ob: dict[str, Any]) -> tuple[Any, str, str]:
    c, csrf = login(ob["app"])
    r = c.post("/admin/ops/support_bundle", data={"csrf": csrf, "confirm": "yes"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/admin/ops?tab=support&req="), r.text
    return c, csrf, r.headers["location"].rsplit("=", 1)[1]


def _bundles(ob: dict[str, Any]) -> list[Path]:
    d = ob["dir"] / "ops" / "support"
    return sorted(p for p in d.glob("*") if p.is_file()) if d.is_dir() else []


# ---------------------------------------------------------------------------------------------- who may
def test_the_right_is_the_one_that_opens_the_operations_pages_for_the_administrator_only() -> None:
    from console import ops_pages, support_bundle_page

    assert ops_pages.ACTIONS["support_bundle"] == ("ops.view", "support") and support_bundle_page.RIGHT == "ops.view"
    assert admin_allowed("admin", "ops.view")
    for role in (*OTHER_ROLES, "", "root"):
        assert not admin_allowed(role, "ops.view"), role


@pytest.mark.parametrize("role", OTHER_ROLES)
def test_every_other_role_is_refused_the_tab_the_making_and_the_download(ob: dict[str, Any], role: str) -> None:
    _plant_log(ob)
    _admin, _csrf, rid = _make(ob)  # a real bundle is there to be refused
    assert len(_bundles(ob)) == 1
    if ob["users"].get(role[:5]) is None:
        ob["users"].create(role[:5], role, PW, f"{role[:5]}@hospa.test")
    c, csrf = login(ob["app"], role[:5], PW)
    before = sorted(p.name for p in (ob["dir"] / "ops" / "requests").glob("*.json"))
    assert c.get("/admin/ops?tab=support").status_code == 403
    assert c.post("/admin/ops/support_bundle", data={"csrf": csrf, "confirm": "yes"}).status_code == 403
    r = c.get(f"/admin/ops/support/{rid}")
    assert r.status_code == 403 and not r.content.startswith(b"\x1f\x8b")
    assert sorted(p.name for p in (ob["dir"] / "ops" / "requests").glob("*.json")) == before  # nothing asked
    denied = [e["detail"]["action"] for e in _events(ob["audit"], "console.denied")]
    assert {"/admin/ops", "/admin/ops/support_bundle", f"/admin/ops/support/{rid}"} <= set(denied)
    downloads = [e for e in _events(ob["audit"], "console.ops") if e["detail"]["action"].startswith("support_bundle_d")]
    assert downloads == []


# ---------------------------------------------------------------------------------------------- the happy path
def test_the_button_asks_first_makes_the_bundle_with_the_same_builder_and_hands_it_out_audited(
    ob: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _plant_log(ob)
    calls: list[dict[str, Any]] = []
    real = support_bundle.build

    def spy(deploy: Path, out_dir: Path, **kw: Any) -> Path:
        calls.append({"deploy": deploy, "out": out_dir, **kw})
        return real(deploy, out_dir, **kw)

    monkeypatch.setattr(support_bundle, "build", spy)
    c, csrf = login(ob["app"])
    page = c.get("/admin/ops?tab=support").text
    assert 'data-testid="opstab-support"' in page and 'data-testid="ops-support_bundle"' in page
    assert 'data-testid="sbundle-none"' in page and 'data-testid="sbundle-never"' in page
    r = c.post("/admin/ops/support_bundle", data={"csrf": csrf})  # no confirmation yet: the sheet, nothing made
    assert 'data-testid="confirm-text"' in r.text and "never go in" in r.text
    assert 'href="/admin/ops?tab=support" data-testid="confirm-no"' in r.text
    assert not _bundles(ob) and not _events(ob["audit"], "console.ops")
    r = c.post("/admin/ops/support_bundle", data={"csrf": csrf, "confirm": "yes"}, follow_redirects=False)
    assert r.status_code == 303
    rid = r.headers["location"].rsplit("=", 1)[1]
    # the same builder, with nothing added (no --add file) and the service logs left out, into <ops>/support/.making
    support = ob["dir"] / "ops" / "support"
    assert len(calls) == 1 and calls[0]["deploy"] == ob["deploy"] and calls[0]["out"] == support / ".making"
    assert "add" not in calls[0] and "days" not in calls[0] and calls[0]["commands"] is False
    assert calls[0]["logs_left_out"] == ops_support.LOGS_LEFT_OUT
    assert list((support / ".making").iterdir()) == []  # moved out once audited
    [f] = _bundles(ob)
    assert ops_support.NAME.fullmatch(f.name)
    page = c.get(r.headers["location"]).text
    assert 'data-action="support_bundle"' in page and 'data-testid="ops-result">done' in page
    assert f'href="/admin/ops/support/{rid}"' in page and 'data-testid="sbundle-refused"' not in page
    d = c.get(f"/admin/ops/support/{rid}")
    assert d.status_code == 200 and d.headers["content-type"] == "application/gzip"
    assert f'filename="{f.name}"' in d.headers["content-disposition"] and d.headers["cache-control"] == "no-store"
    assert d.content == f.read_bytes()
    sha = hashlib.sha256(d.content).hexdigest()
    with tarfile.open(fileobj=io.BytesIO(d.content), mode="r:gz") as tar:
        names = tar.getnames()
        manifest = json.loads(tar.extractfile("support/MANIFEST.json").read())  # type: ignore[union-attr]
    assert "support/MANIFEST.json" in names and "support/env.redacted" in names
    assert not [n for n in names if n.startswith("support/logs")]  # the planted log day is NOT in it
    assert not [n for n in names if n.startswith("support/added/")]  # nothing added to what the bundle holds
    assert manifest["tool"].startswith("tools/support_bundle.py") and "the audit chain" in manifest["never"]
    assert manifest["log_days"] == [] and {"what": "logs/", "why": ops_support.LOGS_LEFT_OUT} in manifest["left_out"]
    assert "pseudonyms" in ops_support.LOGS_LEFT_OUT and "D-1381" in ops_support.LOGS_LEFT_OUT
    assert {"what": "cmd/", "why": "--no-commands"} in manifest["left_out"]  # the in-process box runs no command
    ev = [e["detail"] for e in _events(ob["audit"], "console.ops")]
    assert [e["action"] for e in ev] == ["support_bundle", "support_bundle.made", "support_bundle.done",
                                         "support_bundle_download.started"]  # fmt: skip
    assert ev[0] == {"action": "support_bundle", "request": rid} and ev[2]["ok"] is True
    assert ev[1] == {"action": "support_bundle.made", "request": rid, "file": f.name, "bytes": len(d.content),
                     "sha256": sha}  # fmt: skip
    assert ev[3] == {"action": "support_bundle_download.started", "request": rid, "file": f.name,
                     "bytes": len(d.content), "sha256": sha}  # fmt: skip
    actors = [e["actor"] for e in _events(ob["audit"], "console.ops")]
    assert actors == ["console:admin", "trialbox-ops", "console:admin", "console:admin"]
    chain = "".join(p.read_text(encoding="utf-8") for p in sorted(ob["audit"].glob("*.jsonl")))
    assert "synthetic test line" not in chain and "MANIFEST" not in chain  # never the contents


def test_the_texts_are_in_three_languages_and_the_tab_renders_in_each(ob: dict[str, Any]) -> None:
    assert set(EN) == set(JA) == set(ZH)
    for lang in ("en", "ja", "zh-TW"):
        assert all(k in CATALOGUES[lang] for k in EN), lang
    c, csrf = login(ob["app"])
    for lang, cat in (("ja", JA), ("zh-TW", ZH), ("en", EN)):
        c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/admin/ops?tab=support"})
        page = c.get("/admin/ops?tab=support").text
        assert cat["ops.tab.support"] in page and cat["sbundle.none"] in page, lang


# ---------------------------------------------------------------------------------------------- refusals
def test_a_bundle_that_fails_the_scan_is_not_handed_out_and_the_page_says_so(
    ob: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools import data_scan as ds

    _plant_log(ob)
    hit = ds.Hit("trialbox-support.tar.gz!gunzip!support/logs/2026-11-18/console.log", 1, "tw_id", "A1********")
    monkeypatch.setattr(support_bundle, "last_look", lambda archive: [hit])  # the builder's own last look
    c, _csrf, rid = _make(ob)
    assert _bundles(ob) == []  # the builder wrote nothing
    res = tb_ops.OpsDir(ob["dir"] / "ops").result(rid)
    assert res is not None and res["ok"] is False and res["summary"].startswith("BundleRefused")
    assert "A1" not in res["summary"]  # pattern ids and member names, never a value
    page = c.get(f"/admin/ops?tab=support&req={rid}").text
    assert 'data-testid="sbundle-refused"' in page and EN["sbundle.refused"] in page
    assert f'href="/admin/ops/support/{rid}"' not in page
    assert c.get(f"/admin/ops/support/{rid}").status_code == 404
    ev = [e["detail"] for e in _events(ob["audit"], "console.ops")]
    assert [e["action"] for e in ev] == ["support_bundle", "support_bundle.done"] and ev[1]["ok"] is False


def test_the_make_event_is_written_before_the_file_gets_its_final_name(
    ob: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    support = ob["dir"] / "ops" / "support"
    seen: list[tuple[list[str], list[str]]] = []
    real = ops_support._audit_made

    def spy(runner: Any, rec: Any, rid: str) -> None:
        seen.append(
            (sorted(p.name for p in support.iterdir()), sorted(p.name for p in (support / ".making").iterdir()))
        )
        real(runner, rec, rid)

    monkeypatch.setattr(ops_support, "_audit_made", spy)
    _make(ob)
    [f] = _bundles(ob)
    assert seen == [([".making"], [f.name])]  # at the event the file was still in .making, not in support/


def test_no_make_event_no_bundle_and_the_page_says_so(ob: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(runner: Any, rec: Any, rid: str) -> None:
        raise OSError("the audit chain cannot be written (synthetic)")

    _plant_log(ob)
    monkeypatch.setattr(ops_support, "_audit_made", broken)
    c, _csrf, rid = _make(ob)
    assert _bundles(ob) == [] and list((ob["dir"] / "ops" / "support" / ".making").iterdir()) == []  # removed
    res = tb_ops.OpsDir(ob["dir"] / "ops").result(rid)
    assert res is not None and res["ok"] is False and res["summary"].startswith("BundleNotAudited: not released")
    assert "synthetic" not in res["summary"] and ops_support.record(res) is None
    page = c.get(f"/admin/ops?tab=support&req={rid}").text
    assert 'data-testid="sbundle-unaudited"' in page and EN["sbundle.unaudited"].replace("'", "&#39;") in page
    assert f'href="/admin/ops/support/{rid}"' not in page
    assert c.get(f"/admin/ops/support/{rid}").status_code == 404
    ev = [e["detail"]["action"] for e in _events(ob["audit"], "console.ops")]
    assert ev == ["support_bundle", "support_bundle.done"]


def test_a_link_planted_at_the_support_folder_is_refused_and_nothing_is_written_through_it(
    ob: dict[str, Any], tmp_path: Path
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    ops_root = ob["dir"] / "ops"
    ops_root.mkdir(parents=True, exist_ok=True)
    (ops_root / "support").symlink_to(elsewhere)
    mode = elsewhere.stat().st_mode
    c, _csrf, rid = _make(ob)
    res = tb_ops.OpsDir(ops_root).result(rid)
    assert res is not None and res["ok"] is False and res["summary"].startswith("SupportFolderRefused")
    assert "a link" in res["summary"]
    assert list(elsewhere.iterdir()) == [] and elsewhere.stat().st_mode == mode  # nothing made, chmod-ed or chown-ed
    assert (ops_root / "support").is_symlink()
    page = c.get(f"/admin/ops?tab=support&req={rid}").text
    assert 'data-testid="sbundle-folder"' in page and EN["sbundle.folder"].replace("'", "&#39;") in page
    assert c.get(f"/admin/ops/support/{rid}").status_code == 404


def test_the_folder_check_refuses_a_linked_or_open_operations_folder_and_a_file_in_the_place(tmp_path: Path) -> None:
    real = tmp_path / "real-ops"
    real.mkdir(mode=0o755)
    (tmp_path / "linked-ops").symlink_to(real)
    with pytest.raises(ops_support.SupportFolderRefused, match="without a link"):
        ops_support._open_support(tmp_path / "linked-ops", 10001)
    assert not (real / "support").exists()
    real.chmod(0o775)
    with pytest.raises(ops_support.SupportFolderRefused, match="group or others"):
        ops_support._open_support(real, 10001)
    real.chmod(0o755)
    (real / "support").write_bytes(b"not a folder")
    with pytest.raises(ops_support.SupportFolderRefused, match="not a folder"):
        ops_support._open_support(real, 10001)
    (real / "support").unlink()
    sfd, mfd = ops_support._open_support(real, 10001)  # a plain folder: made, .making inside it, 0700
    os.close(sfd)
    os.close(mfd)
    assert (real / "support" / ".making").is_dir() and ((real / "support" / ".making").stat().st_mode & 0o777) == 0o700


def test_signed_out_gets_no_bytes(ob: dict[str, Any]) -> None:
    _admin, _csrf, rid = _make(ob)
    assert len(_bundles(ob)) == 1
    r = TestClient(ob["app"]).get(f"/admin/ops/support/{rid}", follow_redirects=False)
    assert r.status_code in (303, 401) and not r.content.startswith(b"\x1f\x8b")
    assert not [e for e in _events(ob["audit"], "console.ops") if e["detail"]["action"].startswith("support_bundle_d")]


def test_a_link_at_the_bundle_path_is_not_followed(ob: dict[str, Any], tmp_path: Path) -> None:
    c, _csrf, rid = _make(ob)
    [f] = _bundles(ob)
    copy = tmp_path / "copy.tar.gz"
    copy.write_bytes(f.read_bytes())  # the same bytes and hash: only the link makes it wrong
    f.unlink()
    f.symlink_to(copy)
    assert c.get(f"/admin/ops/support/{rid}").status_code == 404


def test_head_is_not_answered_and_a_range_gets_the_whole_file(ob: dict[str, Any]) -> None:
    c, _csrf, rid = _make(ob)
    [f] = _bundles(ob)
    assert c.head(f"/admin/ops/support/{rid}").status_code == 405
    r = c.get(f"/admin/ops/support/{rid}", headers={"Range": "bytes=0-9"})
    assert r.status_code == 200 and r.content == f.read_bytes()  # D-1381: the whole file, 200


def test_a_file_changed_on_disk_is_not_handed_out(ob: dict[str, Any]) -> None:
    _plant_log(ob)
    c, _csrf, rid = _make(ob)
    [f] = _bundles(ob)
    f.write_bytes(f.read_bytes() + b"x")
    assert c.get(f"/admin/ops/support/{rid}").status_code == 404
    ev = [e["detail"] for e in _events(ob["audit"], "console.ops")]
    assert ev[-1]["action"] == "support_bundle_download.refused" and "sha256" not in ev[-1]
    f.unlink()
    assert c.get(f"/admin/ops/support/{rid}").status_code == 404  # removed (older bundles are pruned)


def test_another_result_or_a_bad_id_names_no_bundle(ob: dict[str, Any]) -> None:
    c, csrf = login(ob["app"])
    r = c.post("/admin/ops/network_sheet", data={"csrf": csrf, "confirm": "yes"}, follow_redirects=False)
    other = r.headers["location"].rsplit("=", 1)[1]
    for rid in (other, "20990101T000000Z-abcdef", "..%2Fstatus.json", "x"):
        assert c.get(f"/admin/ops/support/{rid}").status_code == 404, rid


def test_the_making_needs_post_and_the_csrf_token(ob: dict[str, Any]) -> None:
    c, _csrf = login(ob["app"])
    assert c.post("/admin/ops/support_bundle", data={"csrf": "wrong", "confirm": "yes"}).status_code == 400
    assert c.get("/admin/ops/support_bundle").status_code in (404, 405)
    assert _bundles(ob) == [] and not list((ob["dir"] / "ops" / "requests").glob("*.json"))


# ---------------------------------------------------------------------------------------------- the host's half
def test_the_record_is_read_only_from_a_successful_result_in_its_exact_form() -> None:
    sha = "a" * 64
    good = {"action": "support_bundle", "ok": True,
            "lines": ["x", "file trialbox-support-20261119T010203Z.tar.gz", "bytes 12", f"sha256 {sha}"]}  # fmt: skip
    assert ops_support.record(good) == {"file": "trialbox-support-20261119T010203Z.tar.gz", "bytes": 12,
                                        "sha256": sha}  # fmt: skip
    for bad in (
        {**good, "ok": False},
        {**good, "action": "network_sheet"},
        {**good, "lines": ["file ../status.json", "bytes 12", f"sha256 {sha}"]},
        {**good, "lines": ["file trialbox-support-20261119T010203Z.tar.gz\n", "bytes 12", f"sha256 {sha}"]},
        {**good, "lines": ["file trialbox-support-20261119T010203Z.tar.gz", "bytes -1", f"sha256 {sha}"]},
        {**good, "lines": ["file trialbox-support-20261119T010203Z.tar.gz", "bytes 12", "sha256 xyz"]},
        None,
    ):
        assert ops_support.record(bad) is None, bad


def test_only_the_newest_bundles_are_kept(tmp_path: Path) -> None:
    names = [f"trialbox-support-2026111{i}T000000Z.tar.gz" for i in range(5)]
    for n in (*names, "keep-me.txt"):
        (tmp_path / n).write_bytes(b"x")
    assert ops_support._prune(tmp_path, ops_support.KEEP) == names[:2]
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([*names[2:], "keep-me.txt"])


def test_the_runner_knows_the_action_and_ignores_its_arguments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert "support_bundle" in tb_ops.ACTIONS
    seen: list[dict[str, Any]] = []

    def fake_build(deploy: Path, out_dir: Path, **kw: Any) -> Path:
        seen.append(kw)
        out_dir.mkdir(parents=True, exist_ok=True)
        f = out_dir / "trialbox-support-20261119T010203Z.tar.gz"
        f.write_bytes(b"synthetic")
        return f

    monkeypatch.setattr(support_bundle, "build", fake_build)
    ops = tb_ops.OpsDir(tmp_path / "ops")
    runner = tb_ops.OpsRunner(tb_ops.Box.local(tmp_path / "deploy", {"TB_AUDIT_DIR": str(tmp_path / "audit")}), ops)
    rid = ops.submit("support_bundle", "console:admin", {"add": "/data/lake.duckdb", "days": "999"})
    res = runner.run_one({"id": rid, "action": "support_bundle", "by": "console:admin",
                          "args": {"add": "/data/lake.duckdb", "days": "999"}})  # fmt: skip
    assert res["ok"] is True
    assert seen == [{"commands": False, "say": seen[0]["say"], "logs_left_out": ops_support.LOGS_LEFT_OUT}]
    rec = {"file": "trialbox-support-20261119T010203Z.tar.gz", "bytes": 9,
           "sha256": hashlib.sha256(b"synthetic").hexdigest()}  # fmt: skip
    assert ops_support.record(res) == rec
    # no console here: the in-process box's make event goes to the box's own writer (TB_AUDIT_DIR)
    assert [e["detail"] for e in _events(tmp_path / "audit", "console.ops")] == [
        {"action": "support_bundle.made", "request": rid, **rec}
    ]


def test_on_a_site_box_the_runner_audits_the_made_bundle_with_its_size_and_hash(tmp_path: Path) -> None:
    argvs: list[list[str]] = []

    def run(argv: Any, timeout: Any) -> str:
        argvs.append(list(argv))
        return ""

    class FakeRunner:
        box = tb_ops.Box("compose", tmp_path, {}, run=run)

    rec = {"file": "trialbox-support-20261119T010203Z.tar.gz", "bytes": 9, "sha256": "b" * 64}
    ops_support._audit_made(FakeRunner(), rec, "20261119T010203Z-abcdef")
    assert len(argvs) == 1 and argvs[0][-1].startswith("{")
    detail = json.loads(argvs[0][-1])
    assert detail == {"action": "support_bundle.made", "request": "20261119T010203Z-abcdef", **rec}
    assert re.search(r"open_audit\(\)\.append\('console\.ops'", argvs[0][-2])


def test_on_a_site_box_a_failed_make_event_removes_the_bundle_before_it_is_released(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(argv: Any, timeout: Any) -> str:  # the orchestrator's exec exits non-zero (run_cmd raises)
        raise tb_ops.OpsFailed("exit 1: synthetic")

    def fake_build(deploy: Path, out_dir: Path, **kw: Any) -> Path:
        f = out_dir / "trialbox-support-20261119T010203Z.tar.gz"
        f.write_bytes(b"synthetic")
        return f

    monkeypatch.setattr(support_bundle, "build", fake_build)
    ops = tb_ops.OpsDir(tmp_path / "ops")
    runner = tb_ops.OpsRunner(tb_ops.Box("compose", tmp_path / "deploy", {}, run=fail), ops)
    rid = ops.submit("support_bundle", "console:admin", {})
    res = runner.run_one({"id": rid, "action": "support_bundle", "by": "console:admin", "args": {}})
    assert res["ok"] is False and res["summary"].startswith("BundleNotAudited: not released")
    assert "synthetic" not in res["summary"] and ops_support.record(res) is None
    assert sorted(p.name for p in (tmp_path / "ops" / "support").iterdir()) == [".making"]
    assert list((tmp_path / "ops" / "support" / ".making").iterdir()) == []
