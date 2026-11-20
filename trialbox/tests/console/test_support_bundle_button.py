# ruff: noqa: F811 - the ob fixture is imported from test_ops_pages and taken by name
"""10K-5 (D-1381): the support bundle as a button on the operations pages.

The button is the operations action ``support_bundle``; the runner (inline here, the host's on a box) makes every
member from an allow-list of fields of closed kinds (``tools/trialbox/support_fields.py``) and has the same builder as
``trialbox support-bundle`` scan and write them. Held here: who may (the administrator only; every other role refused
the tab, the making and the download), the happy path (confirm, make, download as a POST with the CSRF token, the
audit events with size and sha256 and never a line of the bundle), the allow-list (every source the button reads
seeded with planted markers: none reaches any member, raw or JSON-escaped; every value of every member of its declared
kind), each finding of the reviews of 31935cc4 and 48b3210c, a bundle that fails the scan not handed out, the make
event before the final name and no bundle without it, the folder's check, a file changed on disk or a link at its
place not handed out, the age limit, the texts in en, ja and zh-TW. Synthetic data only: every marker is invented.

Not held here: the refusal while a support session is on (10K-15, #1170, not on master when this was built)."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import tarfile
import time
from pathlib import Path
from typing import Any

import pytest
from console.i18n import CATALOGUES
from console.i18n_support_bundle import EN, JA, ZH
from fastapi.testclient import TestClient
from tb_common.audit import AuditLog
from tb_common.authz import MATRIX_ROLES, admin_allowed

from tests.console.test_console_app import login
from tests.console.test_ops_pages import PW, _events, ob  # noqa: F401 - the fixture is used by name
from tools import support_bundle
from tools.trialbox import ops as tb_ops
from tools.trialbox import ops_support
from tools.trialbox import support_fields as sf

OTHER_ROLES = tuple(r for r in MATRIX_ROLES if r != "admin")  # every role of the matrix but the administrator
#: invented markers, one of each kind a support bundle must never carry (the review of 48b3210c)
MARKERS = {
    "pseudonym": "PSN-7F3A9C21",
    "chart number": "0012345678",
    "name": "Hanako Testperson",
    "login name": "hanakot",
    "mail address": "hanako.testperson@hospa.test",
    "study id": "STUDY-ONC-042",
    "password-shaped value": "SYNTH-pw-31935-Qz",
    "type-like name": "Hanako_Testperson_Timeout",
}
MEMBERS_LOCAL = ["support/MANIFEST.json", "support/audit-verify.json", "support/health.json", "support/history.jsonl",
                 "support/ops-snapshot.json", "support/release.json"]  # fmt: skip
MEMBERS_SITE = sorted([*MEMBERS_LOCAL, "support/disks.json", "support/gpu.json", "support/services.json"])


def _members(blob: bytes) -> dict[str, str]:
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        return {m.name: tar.extractfile(m).read().decode("utf-8") for m in tar.getmembers()}  # type: ignore[union-attr]


def _forms(text: str) -> set[str]:
    """A text as it can stand in a member: raw, JSON-escaped, and with the ASCII escapes of non-ASCII."""
    return {text, json.dumps(text)[1:-1], json.dumps(text, ensure_ascii=False)[1:-1]}


def _absent(members: dict[str, str]) -> None:
    for name, body in members.items():
        for what, marker in MARKERS.items():
            for form in _forms(marker):
                assert form not in body, (name, what)


def _kinds(members: dict[str, str]) -> None:
    for name, body in members.items():
        short = name.removeprefix("support/")
        if short == "MANIFEST.json":
            continue
        assert short in sf.SCHEMAS, name
        assert sf.check_member(short, body) == [], name


def _make(ob: dict[str, Any]) -> tuple[Any, str, str]:
    c, csrf = login(ob["app"])
    r = c.post("/admin/ops/support_bundle", data={"csrf": csrf, "confirm": "yes"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/admin/ops?tab=support&req="), r.text
    return c, csrf, r.headers["location"].rsplit("=", 1)[1]


def _download(c: Any, csrf: str, rid: str, **kw: Any) -> Any:
    return c.post(f"/admin/ops/support/{rid}", data={"csrf": csrf}, follow_redirects=False, **kw)


def _bundles(ob: dict[str, Any]) -> list[Path]:
    d = ob["dir"] / "ops" / "support"
    return sorted(p for p in d.glob("*") if p.is_file()) if d.is_dir() else []


# ---------------------------------------------------------------------------------------------- seeds
def _seed(deploy: Path, audit_dir: Path, targets: list[Path]) -> None:
    """Every source the button reads, each with every marker where a writer (or a person) could put one."""
    m = MARKERS
    blob = " ".join(m.values())
    updates = deploy / "updates"
    updates.mkdir(parents=True, exist_ok=True)
    rows = [
        {"at": "2026-11-19T01:00:00+00:00", "bundle": m["study id"], "box": "compose", "step": "apply", "ok": True,
         "detail": "3 payloads"},
        {"at": "2026-11-19T01:01:00+00:00", "bundle": m["study id"], "box": "compose", "step": "update", "ok": False,
         "detail": f"UpdateFailed: psql exit 1: DETAIL: Key (pseudonym)=({m['pseudonym']}) {blob}"},
        {"at": "2026-11-19T01:02:00+00:00", "bundle": m["pseudonym"], "box": m["name"], "step": f"x {blob}",
         "ok": True, "detail": f"{m['type-like name']}: {blob}", "note": blob},
    ]  # fmt: skip
    (updates / "history.jsonl").write_text("\n".join([*(json.dumps(r) for r in rows), f"not json {blob}"]) + "\n",
                                           encoding="utf-8")  # fmt: skip
    (updates / "installed.json").write_text(json.dumps({
        "format": "trialbox-installed/1", "release_seq": 7, "bundle_id": m["pseudonym"], "key_id": m["mail address"],
        "manifest_sha256": "a" * 64, "applied_at": "2026-11-19T01:00:00+00:00", "state": {"model_pin": blob},
        "operator": m["name"], "url": f"https://x.test/?token={m['password-shaped value']}"}), encoding="utf-8")  # fmt: skip
    (deploy / "release.json").write_text(json.dumps({"release_seq": 7, "created_at": "2026-11-18T00:00:00+00:00",
                                                     "source": {"commit": "b" * 40, "dirty": False, "by": blob},
                                                     "notes": blob}), encoding="utf-8")  # fmt: skip
    (deploy / "site").mkdir(parents=True, exist_ok=True)
    (deploy / "site" / "backup-verified.json").write_text(json.dumps({
        "at": "2026-11-01T00:00:00+00:00", "file": f"/media/{m['login name']}/{m['name']}/trialbox-x.tbbak",
        "sha256": "c" * 64, "site": m["study id"], "drill_failed_at": "2026-11-18T00:00:00+00:00",
        "drill_file": f"/media/usb/{m['pseudonym']}.tbbak", "drill_error": f"IntegrityError: {blob}"}),
        encoding="utf-8")  # fmt: skip
    for t in targets:
        t.mkdir(parents=True, exist_ok=True)
        (t / f"trialbox-{m['study id']}-20261119T010000Z.tbbak").write_bytes(b"x")
    (deploy / ".env").write_text(f"TB_ENV=TEST\nLLM_VERIFIER_BASE_URL=http://v.test/v1?password="
                                 f"{m['password-shaped value']}\nTB_SMTP_LOGIN={m['login name']}\n"
                                 f"TB_BACKUP_ALERT_WATCHER={m['name']}\n", encoding="utf-8")  # fmt: skip
    log = AuditLog(audit_dir, "UTC")
    log.append("console.ops", actor="console:admin", detail={"note": blob})
    log.reanchor("admin", f"gap after the restore of {m['pseudonym']} ({m['name']}, {m['mail address']}), chart "
                          f"{m['chart number']}, {m['study id']}, MRN:\n{m['chart number']}")  # fmt: skip


def _site_commands(seen: list[list[str]], backup_mount: Path) -> Any:
    """What docker, df and nvidia-smi could print on a site box, each with every marker in it (synthetic)."""
    m = MARKERS
    blob = " ".join(m.values())

    def run(argv: Any, timeout: int) -> tuple[int, str]:
        argv = [str(a) for a in argv]
        seen.append(argv)
        if argv[-1] == "-q":
            return 0, "abc123\ndef456\nfed789\n"
        if argv[:2] == ["docker", "inspect"]:
            return 0, ("console|2|running|healthy|2026-11-20T09:00:00.123456789Z\n"
                       f"{m['pseudonym']}|0|exited||2026-11-19T00:00:00Z\n"
                       f"orchestrator|x|{m['name']}|{blob}|{m['study id']}\n")  # fmt: skip
        if argv[0] == "df":
            return 0, ("Filesystem 1-blocks Used Available Capacity Mounted on\n"
                       "/dev/sda1 1000 400 600 40% /\n"
                       f"/dev/sdb1 2000 100 1900 5% {backup_mount}\n"
                       f"//nas/{m['login name']} 3000 300 2700 10% /mnt/{m['pseudonym']} {m['mail address']}\n"
                       "tmpfs 10 0 10 0% /run\n")  # fmt: skip
        if argv[0] == "nvidia-smi":
            return 0, f"1024, 49152, 7, 41, 550.54.15\n1, 2, 3, 4, {m['type-like name']}\n"
        return 0, blob

    return run


# ---------------------------------------------------------------------------------------------- who may
def test_the_right_is_the_one_that_opens_the_operations_pages_for_the_administrator_only() -> None:
    from console import ops_pages, support_bundle_page

    assert ops_pages.ACTIONS["support_bundle"] == ("ops.view", "support") and support_bundle_page.RIGHT == "ops.view"
    assert admin_allowed("admin", "ops.view")
    for role in (*OTHER_ROLES, "", "root"):
        assert not admin_allowed(role, "ops.view"), role


@pytest.mark.parametrize("role", OTHER_ROLES)
def test_every_other_role_is_refused_the_tab_the_making_and_the_download(ob: dict[str, Any], role: str) -> None:
    _admin, _csrf, rid = _make(ob)  # a real bundle is there to be refused
    assert len(_bundles(ob)) == 1
    if ob["users"].get(role[:5]) is None:
        ob["users"].create(role[:5], role, PW, f"{role[:5]}@hospa.test")
    c, csrf = login(ob["app"], role[:5], PW)
    before = sorted(p.name for p in (ob["dir"] / "ops" / "requests").glob("*.json"))
    assert c.get("/admin/ops?tab=support").status_code == 403
    assert c.post("/admin/ops/support_bundle", data={"csrf": csrf, "confirm": "yes"}).status_code == 403
    r = _download(c, csrf, rid)
    assert r.status_code == 403 and not r.content.startswith(b"\x1f\x8b")
    assert sorted(p.name for p in (ob["dir"] / "ops" / "requests").glob("*.json")) == before  # nothing asked
    denied = [e["detail"]["action"] for e in _events(ob["audit"], "console.denied")]
    assert {"/admin/ops", "/admin/ops/support_bundle", f"/admin/ops/support/{rid}"} <= set(denied)
    downloads = [e for e in _events(ob["audit"], "console.ops") if e["detail"]["action"].startswith("support_bundle_d")]
    assert downloads == []


# ---------------------------------------------------------------------------------------------- the happy path
def test_the_button_asks_first_makes_the_bundle_from_its_allow_lists_and_hands_it_out_audited(
    ob: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
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
    assert 'data-testid="confirm-text"' in r.text and "No text, path, file name" in r.text
    assert 'href="/admin/ops?tab=support" data-testid="confirm-no"' in r.text
    assert not _bundles(ob) and not _events(ob["audit"], "console.ops")
    r = c.post("/admin/ops/support_bundle", data={"csrf": csrf, "confirm": "yes"}, follow_redirects=False)
    assert r.status_code == 303
    rid = r.headers["location"].rsplit("=", 1)[1]
    support = ob["dir"] / "ops" / "support"
    assert len(calls) == 1 and calls[0]["deploy"] == ob["deploy"] and calls[0]["out"] == support / ".making"
    assert "add" not in calls[0] and "days" not in calls[0] and calls[0]["commands"] is False
    want = {n.removeprefix("support/") for n in MEMBERS_LOCAL} - {"MANIFEST.json", "history.jsonl"}
    assert set(calls[0]["given"]) == want and callable(calls[0]["scanned"])
    assert list((support / ".making").iterdir()) == []  # moved out once audited
    [f] = _bundles(ob)
    assert ops_support.NAME.fullmatch(f.name)
    page = c.get(r.headers["location"]).text
    assert 'data-action="support_bundle"' in page and 'data-testid="ops-result">done' in page
    assert f'action="/admin/ops/support/{rid}"' in page and 'data-testid="sbundle-refused"' not in page
    assert f'href="/admin/ops/support/{rid}"' not in page  # a form, never a link
    d = _download(c, csrf, rid)
    assert d.status_code == 200 and d.headers["content-type"] == "application/gzip"
    assert f'filename="{f.name}"' in d.headers["content-disposition"] and d.headers["cache-control"] == "no-store"
    assert d.content == f.read_bytes()
    sha = hashlib.sha256(d.content).hexdigest()
    members = _members(d.content)
    assert sorted(members) == [n for n in MEMBERS_LOCAL if n != "support/history.jsonl"]  # no update ran here
    manifest = json.loads(members["support/MANIFEST.json"])
    assert manifest["tool"].startswith("tools/support_bundle.py") and manifest["log_days"] == []
    whats = [r["what"] for r in manifest["left_out"]]
    assert "logs/" in whats and "services.json, disks.json, gpu.json" in whats
    _kinds(members)
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


def test_the_texts_are_in_three_languages_and_the_tab_renders_in_each(ob: dict[str, Any]) -> None:
    assert set(EN) == set(JA) == set(ZH)
    for lang in ("en", "ja", "zh-TW"):
        assert all(k in CATALOGUES[lang] for k in EN), lang
    c, csrf = login(ob["app"])
    for lang, cat in (("ja", JA), ("zh-TW", ZH), ("en", EN)):
        c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/admin/ops?tab=support"})
        page = c.get("/admin/ops?tab=support").text
        assert cat["ops.tab.support"] in page and cat["sbundle.none"] in page, lang
    assert f"at most {ops_support.MAX_AGE_DAYS} days" in c.get("/admin/ops?tab=support").text  # the age limit


def test_the_texts_name_every_member_and_claim_no_scan_as_the_protection() -> None:
    for member in ("MANIFEST.json", "ops-snapshot.json", "health.json", "release.json", "history.jsonl",
                   "audit-verify.json", "services.json", "disks.json", "gpu.json"):  # fmt: skip
        for cat in (EN, JA, ZH):
            assert member in cat["sbundle.in"], member
    for words in ("no patient data", "every secret value replaced", "counts, no event", "as these print them"):
        assert words not in " ".join(EN.values()), words
    assert "it is not what keeps them out" in EN["ops.confirm.support_bundle"]


# ---------------------------------------------------------------------------------------------- the allow-list
def test_no_planted_marker_reaches_any_member_and_every_value_is_of_its_declared_kind(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The review of 48b3210c: every source the button reads seeded with markers (a pseudonym, a chart number, a
    name, a login name, a mail address, a study id, a password-shaped value, a type-like name), on a site box."""
    m = MARKERS
    deploy = tmp_path / "deploy"
    targets = [tmp_path / "media" / m["login name"] / m["study id"], tmp_path / "mnt" / m["pseudonym"]]
    audit_dir = tmp_path / "audit-chain"
    _seed(deploy, audit_dir, targets)
    monkeypatch.setenv("TB_AUDIT_HOST_DIR", str(audit_dir))
    seen: list[list[str]] = []
    monkeypatch.setattr(support_bundle, "run_cmd", _site_commands(seen, targets[0]))
    ops = tb_ops.OpsDir(tmp_path / "ops")
    env = {"TB_BACKUP_TARGETS": " ".join(str(t) for t in targets)}
    runner = tb_ops.OpsRunner(tb_ops.Box("compose", deploy, env, run=lambda argv, timeout: ""), ops)
    rid = ops.submit("support_bundle", "console:admin", {})
    res = runner.run_one({"id": rid, "action": "support_bundle", "by": "console:admin", "args": {}})
    assert res["ok"] is True, res
    rec = ops_support.record(res)
    assert rec is not None
    members = _members((tmp_path / "ops" / "support" / rec["file"]).read_bytes())
    assert sorted(members) == MEMBERS_SITE
    _absent(members)
    _kinds(members)
    for line in res["lines"]:  # the result the page shows: nothing of the seeds either
        for marker in m.values():
            assert marker not in line
    # what the seeds left: structure, never their text
    hist = [json.loads(x) for x in members["support/history.jsonl"].splitlines()]
    assert [(h["step"], h["ok"], h["detail_type"], h["detail_length"], h["box"]) for h in hist] == [
        ("apply", True, "other", "1-99", "compose"), ("update", False, "UpdateFailed", "100-999", "compose"),
        ("other", True, "other", "100-999", "other")]  # fmt: skip
    assert [h["bundle"] for h in hist] == ["bundle-1", "bundle-1", "installed"]
    snap = json.loads(members["support/ops-snapshot.json"])
    assert [t["label"] for t in snap["backups"]["targets"]] == ["backup", "backup-2"]
    assert [t["files"] for t in snap["backups"]["targets"]] == [1, 1]
    assert snap["health"]["verified"]["drill_error_type"] == "IntegrityError"
    assert "file" not in snap["health"]["verified"] and "drill_file" not in snap["health"]["verified"]
    audit_v = json.loads(members["support/audit-verify.json"])
    assert audit_v["state"] == "verified" and audit_v["notes"] >= 1
    assert set(audit_v) <= set(sf.SCHEMAS["audit-verify.json"])
    services = json.loads(members["support/services.json"])
    assert [s["service"] for s in services] == ["console", "other", "orchestrator"]
    assert services[0] == {"service": "console", "state": "running", "health": "healthy", "restarts": 2,
                           "since": "2026-11-20T09:00:00Z"}  # fmt: skip
    disks = json.loads(members["support/disks.json"])
    assert [d["label"] for d in disks] == ["system", "backup", "other-1"]
    gpu = json.loads(members["support/gpu.json"])
    assert gpu[0]["driver"] == "550.54.15" and "driver" not in gpu[1]
    manifest = json.loads(members["support/MANIFEST.json"])
    dropped = [r["what"] for r in manifest["left_out"] if "allow-list" in r["what"]]
    assert any(w.startswith("history.jsonl:") for w in dropped) and any(w.startswith("release.json:") for w in dropped)
    # the commands: a query of numbers for the GPU (no process list), ids and a fixed format for docker
    assert ["df", "-P", "-B1"] in seen and list(sf.GPU) in seen
    assert next(a for a in seen if a[:2] == ["docker", "inspect"])[3] == sf.INSPECT_FORMAT
    assert not [a for a in seen if "config" in a or "doctor" in " ".join(a) or "check_host.sh" in " ".join(a)]


def test_the_audit_verification_carries_counts_only_never_a_reanchor_reason(tmp_path: Path) -> None:
    """The review of 48b3210c, H1: ``audit.verify`` puts re-anchor events' detail, a reason a person typed, into its
    notes; the button's audit-verify.json holds whether it verified, and counts."""
    from tb_common import audit

    audit_dir = tmp_path / "chain"
    _seed(tmp_path / "deploy", audit_dir, [])
    res = audit.verify(audit_dir)
    assert any(MARKERS["pseudonym"] in n for n in res.notes)  # the source does carry it
    got, dropped = sf.keep(sf.SCHEMAS["audit-verify.json"], sf.audit_verify(res, state="verified"))
    assert dropped == 0 and set(got) == {"state", "error", "ok", "files", "lines", "errors", "notes"}
    assert all(isinstance(v, (bool, int)) or v in ("verified", None) for v in got.values())


def test_paths_typed_or_mounted_never_travel_only_fixed_labels(tmp_path: Path) -> None:
    """The review of 48b3210c, M1: the verified backup's file, the drill's file, the backup targets and the mounts."""
    login_name = MARKERS["login name"]
    disks = sf.Disks(tmp_path, "/var/lib/docker", [f"/media/{login_name}/stick", "/mnt/nas"])
    paths = (
        "/",
        "/data",
        "/var/lib/docker",
        str(tmp_path),
        "/mnt/nas",
        f"/media/{login_name}/stick",
        "/srv/x",
        "/srv/x",
    )
    assert [disks.of_path(p) for p in paths] == ["system", "data", "docker", "deploy", "backup-2", "backup", "other-1",
                                                 "other-1"]  # fmt: skip
    assert disks.of_mount("/media") == "backup" and disks.of_mount("/opt/y") == "other-2"
    snap = {"health": {"verified": {"file": "/media/a/PSN.tbbak", "drill_file": "/x/y", "site": "S", "at": "2026-11-01"}},
            "backups": {"targets": [{"path": "/mnt/nas", "files": [], "reachable": True}]}}  # fmt: skip
    got, _ = sf.keep(sf.SCHEMAS["ops-snapshot.json"], sf.snapshot(snap, sf.Labels(), disks))
    assert got["health"]["verified"] == {"at": "2026-11-01", "sha256": None, "created_at": None, "drill_failed_at": None,
                                         "drill_error_type": None, "drill_error_length": None,
                                         "drill_databases": None}  # fmt: skip
    assert got["backups"]["targets"][0]["label"] == "backup-2"


def test_command_outputs_never_travel_only_parsed_numbers_states_and_fixed_names() -> None:
    """The review of 48b3210c, M2: compose ps, docker inspect and nvidia-smi."""
    assert sf.services(["console|1|running|healthy|2026-11-20T09:00:00Z", "a|b|c", "PSN-1|0|exited||x"]) == [
        {"service": "console", "state": "running", "health": "healthy", "restarts": 1, "since": "2026-11-20T09:00:00Z"},
        {"service": "other", "state": "exited", "health": "none", "restarts": 0, "since": None}]  # fmt: skip
    got, dropped = sf.keep(sf.SCHEMAS["gpu.json"], sf.gpu(["1, 2, 3, 4, 550.54.15", "1, 2, 3, 4, /usr/bin/python x"]))
    assert got[0]["driver"] == "550.54.15" and "driver" not in got[1] and dropped == 1
    assert sf.PS_IDS == ("ps", "--all", "-q") and sf.GPU[1].startswith("--query-gpu=")


def test_the_error_mark_carries_only_a_known_type_and_a_length_range() -> None:
    """The review of 48b3210c, L1: any identifier-shaped text was taken for a type."""
    for text, want in (("UpdateFailed: x", "UpdateFailed"), ("psycopg.errors.UniqueViolation: x", "UniqueViolation"),
                       ("PSN7F3A9C21Failed: x", "other"), ("Hanako_Testperson_Timeout", "other"),
                       ("patient_0012345678_Refused", "other"), ("", "none"), ("3 payloads", "other")):  # fmt: skip
        assert sf.error_type(text) == want, text
    assert [sf.length("x" * n) for n in (0, 1, 99, 100, 999, 1000)] == ["0", "1-99", "1-99", "100-999", "100-999",
                                                                         "1000+"]  # fmt: skip


def test_release_json_holds_its_listed_fields_only() -> None:
    """The review of 48b3210c, L3."""
    inst = {"format": "trialbox-installed/1", "release_seq": 3, "bundle_id": "B1", "manifest_sha256": "a" * 64,
            "key_id": "ed25519:0123456789abcdef", "applied_at": "2026-11-19T00:00:00+00:00", "dirty": False,
            "state": {"schema": 12}, "extra": MARKERS["mail address"]}  # fmt: skip
    rel = {"release_seq": 3, "created_at": "2026-11-18T00:00:00+00:00", "source": {"commit": "c" * 40, "x": 1}, "y": 2}
    got, dropped = sf.keep(sf.SCHEMAS["release.json"], sf.release("1.2.3", inst, rel, sf.Labels("B1")))
    assert got["installed"]["bundle"] == "installed" and got["installed"]["key_id"] == "ed25519:0123456789abcdef"
    assert got["release"] == {"release_seq": 3, "created_at": "2026-11-18T00:00:00+00:00", "commit": "c" * 40,
                              "dirty": None}  # fmt: skip
    assert MARKERS["mail address"] not in json.dumps(got) and dropped == 0  # the extra keys are never even read


def test_a_value_off_its_list_or_of_another_kind_is_dropped_and_counted() -> None:
    kind = {"a": sf.NUM, "b": [sf.TS], "c": {"d": sf.BOOL}}
    got, dropped = sf.keep(kind, {"a": "1", "b": ["2026-11-01", "Hanako"], "c": {"d": True, "e": 1}, "f": 2})
    assert got == {"b": ["2026-11-01"], "c": {"d": True}} and dropped == 4
    assert sf.check(kind, {"a": "x", "z": 1}) == [".a: not of its kind", ".z: not on the list"]


# ---------------------------------------------------------------------------------------------- the review of 31935cc4
def test_the_env_file_and_settings_are_not_in_the_buttons_bundle(ob: dict[str, Any]) -> None:
    (ob["deploy"] / ".env").write_text(f"TB_SMTP_LOGIN={MARKERS['login name']}\nX_URL=http://v.test/?password="
                                       f"{MARKERS['password-shaped value']}\n", encoding="utf-8")  # fmt: skip
    c, csrf, rid = _make(ob)
    members = _members(_download(c, csrf, rid).content)
    assert "support/env.redacted" not in members and not [n for n in members if n.startswith("support/cmd/")]
    _absent(members)


def test_a_download_whose_start_cannot_be_audited_closes_the_file_and_is_refused(
    ob: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    c, csrf, rid = _make(ob)
    opened: list[Any] = []
    real_fdopen = os.fdopen

    def spy(fd: int, *a: Any, **kw: Any) -> Any:
        fh = real_fdopen(fd, *a, **kw)
        if os.readlink(f"/proc/self/fd/{fd}").endswith(".tar.gz"):  # the bundle, not another file of the request
            opened.append(fh)
        return fh

    real_append = AuditLog.append

    def append(self: Any, event: str, *a: Any, **kw: Any) -> Any:
        if (kw.get("detail") or {}).get("action") == "support_bundle_download.started":
            raise OSError("the audit chain cannot be written (synthetic)")
        return real_append(self, event, *a, **kw)

    monkeypatch.setattr(os, "fdopen", spy)  # what the page opens the bundle with
    monkeypatch.setattr(AuditLog, "append", append)
    r = _download(c, csrf, rid)
    assert len(opened) == 1 and opened[0].closed
    assert r.status_code == 503 and not r.content.startswith(b"\x1f\x8b")
    assert EN["sbundle.err.audit"].replace("'", "&#39;") in r.text


def test_the_file_released_is_the_file_the_last_look_scanned(
    ob: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    real = support_bundle.build
    scanned: list[str] = []
    real_look = support_bundle.last_look

    def look(archive: Path) -> list[Any]:
        scanned.append(hashlib.sha256(archive.read_bytes()).hexdigest())
        return real_look(archive)

    def swapped(d: Path, out: Path, **kw: Any) -> Path:
        made = real(d, out, **kw)
        made.write_bytes(made.read_bytes() + b"changed after the scan")
        return made

    monkeypatch.setattr(support_bundle, "last_look", look)
    monkeypatch.setattr(support_bundle, "build", swapped)
    c, csrf, rid = _make(ob)
    res = tb_ops.OpsDir(ob["dir"] / "ops").result(rid)
    assert res is not None and res["ok"] is False and res["summary"].startswith("BundleChanged"), res
    assert _bundles(ob) == [] and list((ob["dir"] / "ops" / "support" / ".making").iterdir()) == []
    assert _download(c, csrf, rid).status_code == 303
    monkeypatch.setattr(support_bundle, "build", real)  # unchanged: released, and its hash is the scanned copy's
    scanned.clear()
    _c, _csrf, rid = _make(ob)
    rec = ops_support.record(tb_ops.OpsDir(ob["dir"] / "ops").result(rid))
    assert rec is not None and scanned == [rec["sha256"]]


# ---------------------------------------------------------------------------------------------- refusals
def test_a_bundle_that_fails_the_scan_is_not_handed_out_and_the_page_says_so(
    ob: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools import data_scan as ds

    hit = ds.Hit("trialbox-support.tar.gz!gunzip!support/ops-snapshot.json", 1, "tw_id", "A1********")
    monkeypatch.setattr(support_bundle, "last_look", lambda archive: [hit])  # the builder's own last look
    c, csrf, rid = _make(ob)
    assert _bundles(ob) == []  # the builder wrote nothing
    res = tb_ops.OpsDir(ob["dir"] / "ops").result(rid)
    assert res is not None and res["ok"] is False and res["summary"].startswith("BundleRefused")
    assert "A1" not in res["summary"]  # pattern ids and member names, never a value
    page = c.get(f"/admin/ops?tab=support&req={rid}").text
    assert 'data-testid="sbundle-refused"' in page and EN["sbundle.refused"] in page
    assert f'action="/admin/ops/support/{rid}"' not in page
    r = _download(c, csrf, rid)
    assert r.status_code == 303 and r.headers["location"] == f"/admin/ops?tab=support&req={rid}&gone=1"
    assert 'data-testid="sbundle-gone"' in c.get(r.headers["location"]).text
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

    monkeypatch.setattr(ops_support, "_audit_made", broken)
    c, csrf, rid = _make(ob)
    assert _bundles(ob) == [] and list((ob["dir"] / "ops" / "support" / ".making").iterdir()) == []  # removed
    res = tb_ops.OpsDir(ob["dir"] / "ops").result(rid)
    assert res is not None and res["ok"] is False and res["summary"].startswith("BundleNotAudited: not released")
    assert "synthetic" not in res["summary"] and ops_support.record(res) is None
    page = c.get(f"/admin/ops?tab=support&req={rid}").text
    assert 'data-testid="sbundle-unaudited"' in page and EN["sbundle.unaudited"].replace("'", "&#39;") in page
    assert f'action="/admin/ops/support/{rid}"' not in page
    assert _download(c, csrf, rid).status_code == 303
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
    c, csrf, rid = _make(ob)
    res = tb_ops.OpsDir(ops_root).result(rid)
    assert res is not None and res["ok"] is False and res["summary"].startswith("SupportFolderRefused")
    assert "a link" in res["summary"]
    assert list(elsewhere.iterdir()) == [] and elsewhere.stat().st_mode == mode  # nothing made, chmod-ed or chown-ed
    assert (ops_root / "support").is_symlink()
    page = c.get(f"/admin/ops?tab=support&req={rid}").text
    assert 'data-testid="sbundle-folder"' in page and EN["sbundle.folder"].replace("'", "&#39;") in page
    assert _download(c, csrf, rid).status_code == 303


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
    _admin, csrf, rid = _make(ob)
    assert len(_bundles(ob)) == 1
    r = TestClient(ob["app"]).post(f"/admin/ops/support/{rid}", data={"csrf": csrf}, follow_redirects=False)
    assert r.status_code in (303, 401) and not r.content.startswith(b"\x1f\x8b")
    assert not [e for e in _events(ob["audit"], "console.ops") if e["detail"]["action"].startswith("support_bundle_d")]


def test_a_link_at_the_bundle_path_is_not_followed(ob: dict[str, Any], tmp_path: Path) -> None:
    c, csrf, rid = _make(ob)
    [f] = _bundles(ob)
    copy = tmp_path / "copy.tar.gz"
    copy.write_bytes(f.read_bytes())  # the same bytes and hash: only the link makes it wrong
    f.unlink()
    f.symlink_to(copy)
    r = _download(c, csrf, rid)
    assert r.status_code == 303 and not r.content.startswith(b"\x1f\x8b")


def test_the_download_is_a_post_with_the_csrf_token_get_and_head_answer_405(ob: dict[str, Any]) -> None:
    """The review of 48b3210c, L8: a link another site could make a signed-in browser follow is gone."""
    c, csrf, rid = _make(ob)
    [f] = _bundles(ob)
    assert c.get(f"/admin/ops/support/{rid}").status_code == 405
    assert c.head(f"/admin/ops/support/{rid}").status_code == 405
    r = c.post(f"/admin/ops/support/{rid}", data={"csrf": "wrong"}, follow_redirects=False)
    assert r.status_code == 400 and not r.content.startswith(b"\x1f\x8b")
    r = _download(c, csrf, rid, headers={"Range": "bytes=0-9"})
    assert r.status_code == 200 and r.content == f.read_bytes()  # D-1381: the whole file, 200
    started = [e for e in _events(ob["audit"], "console.ops") if e["detail"]["action"].endswith("download.started")]
    assert len(started) == 1  # the refused ones wrote none


def test_the_download_form_takes_nothing_typed() -> None:
    page = (Path(sf.ROOT) / "services" / "console" / "templates" / "_ops_support_bundle.html").read_text("utf-8")
    forms = re.findall(r"<form\b.*?</form>", page, re.S)
    assert len(forms) == 2
    for form in forms:
        assert re.findall(r"<input\b[^>]*>", form) == ['<input type="hidden" name="csrf" value="{{ csrf }}">']


def test_a_file_changed_on_disk_is_not_handed_out(ob: dict[str, Any]) -> None:
    c, csrf, rid = _make(ob)
    [f] = _bundles(ob)
    f.write_bytes(f.read_bytes() + b"x")
    r = _download(c, csrf, rid)
    assert r.status_code == 303 and r.headers["location"].endswith("&gone=1")
    ev = [e["detail"] for e in _events(ob["audit"], "console.ops")]
    assert ev[-1]["action"] == "support_bundle_download.refused" and "sha256" not in ev[-1]
    f.unlink()
    assert _download(c, csrf, rid).status_code == 303  # removed (older bundles are pruned)


def test_another_result_or_a_bad_id_names_no_bundle(ob: dict[str, Any]) -> None:
    c, csrf = login(ob["app"])
    r = c.post("/admin/ops/network_sheet", data={"csrf": csrf, "confirm": "yes"}, follow_redirects=False)
    other = r.headers["location"].rsplit("=", 1)[1]
    for rid in (other, "20990101T000000Z-abcdef", "x"):
        r = _download(c, csrf, rid)
        assert r.status_code == 303 and r.headers["location"].endswith("gone=1"), rid
    assert _download(c, csrf, "x").headers["location"] == "/admin/ops?tab=support&gone=1"  # a bad id is not echoed


def test_the_making_needs_post_and_the_csrf_token_and_waits_for_a_pending_one(ob: dict[str, Any]) -> None:
    """The review of 48b3210c, L9: a second request while one is pending answers 409."""
    c, csrf = login(ob["app"])
    assert c.post("/admin/ops/support_bundle", data={"csrf": "wrong", "confirm": "yes"}).status_code == 400
    assert c.get("/admin/ops/support_bundle").status_code in (404, 405)
    assert _bundles(ob) == [] and not list((ob["dir"] / "ops" / "requests").glob("*.json"))
    tb_ops.OpsDir(ob["dir"] / "ops").submit("support_bundle", "console:admin", {})  # one waits for the runner
    r = c.post("/admin/ops/support_bundle", data={"csrf": csrf, "confirm": "yes"}, follow_redirects=False)
    assert r.status_code == 409 and len(list((ob["dir"] / "ops" / "requests").glob("*.json"))) == 1


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


def _local_runner(tmp_path: Path) -> tuple[Any, Any]:
    ops = tb_ops.OpsDir(tmp_path / "ops")
    return tb_ops.OpsRunner(tb_ops.Box.local(tmp_path / "deploy", {"TB_AUDIT_DIR": str(tmp_path / "audit")}), ops), ops


def test_only_the_newest_bundles_are_kept_none_past_its_age_and_each_removal_is_audited(tmp_path: Path) -> None:
    """The review of 48b3210c, L6: a kept bundle older than the age limit is removed by the runner's next pass."""
    runner, ops = _local_runner(tmp_path)
    d = ops_support.support_dir(ops.root)
    d.mkdir(parents=True)
    names = [f"trialbox-support-2026111{i}T000000Z.tar.gz" for i in range(5)]
    for n in (*names, "keep-me.txt"):
        (d / n).write_bytes(b"x")
    old = time.time() - (ops_support.MAX_AGE_DAYS + 1) * 86400
    os.utime(d / names[2], (old, old))
    runner.run_pending()  # the pass: the sweep first
    assert sorted(p.name for p in d.iterdir()) == sorted([*names[3:], "keep-me.txt"])
    ev = [e["detail"] for e in _events(tmp_path / "audit", "console.ops")]
    assert sorted((e["file"], e["why"]) for e in ev) == [(names[0], "count"), (names[1], "count"), (names[2], "age")]
    assert all(e["action"] == "support_bundle.removed" for e in ev)


def test_the_make_event_names_the_request_itself_not_a_stale_marker(tmp_path: Path) -> None:
    """The review of 48b3210c, L5: a marker left by an earlier request cut off is not taken for this one."""
    runner, ops = _local_runner(tmp_path)
    stale = ops.submit("support_bundle", "console:admin", {})
    ops.marker(stale).parent.mkdir(parents=True, exist_ok=True)
    ops.marker(stale).write_text(json.dumps({"id": stale, "action": "support_bundle", "started": "2026-01-01"}))
    rid = ops.submit("support_bundle", "console:admin", {})
    res = runner.run_one({"id": rid, "action": "support_bundle", "by": "console:admin", "args": {}})
    assert res["ok"] is True, res
    [made] = [e["detail"] for e in _events(tmp_path / "audit", "console.ops") if e["detail"]["action"].endswith("made")]
    assert made["request"] == rid != stale


def test_the_runner_knows_the_action_and_ignores_its_arguments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert "support_bundle" in tb_ops.ACTIONS
    seen: list[dict[str, Any]] = []

    def fake_build(deploy: Path, out_dir: Path, **kw: Any) -> Path:
        seen.append(kw)
        out_dir.mkdir(parents=True, exist_ok=True)
        f = out_dir / "trialbox-support-20261119T010203Z.tar.gz"
        f.write_bytes(b"synthetic")
        kw["scanned"](hashlib.sha256(b"synthetic").hexdigest(), 9)  # what the builder's last look read
        return f

    monkeypatch.setattr(support_bundle, "build", fake_build)
    runner, ops = _local_runner(tmp_path)
    rid = ops.submit("support_bundle", "console:admin", {"add": "/data/lake.duckdb", "days": "999"})
    res = runner.run_one({"id": rid, "action": "support_bundle", "by": "console:admin",
                          "args": {"add": "/data/lake.duckdb", "days": "999"}})  # fmt: skip
    assert res["ok"] is True
    assert sorted(seen[0]) == ["commands", "given", "given_left_out", "say", "scanned"] and not seen[0]["commands"]
    rec = {"file": "trialbox-support-20261119T010203Z.tar.gz", "bytes": 9,
           "sha256": hashlib.sha256(b"synthetic").hexdigest()}  # fmt: skip
    assert ops_support.record(res) == rec
    # no console here: the in-process box's make event goes to the box's own writer (TB_AUDIT_DIR)
    assert [e["detail"] for e in _events(tmp_path / "audit", "console.ops")] == [
        {"action": "support_bundle.made", "request": rid, **rec}
    ]


def test_the_builder_takes_given_members_and_reads_nothing_of_the_box_for_them(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    (deploy / "updates").mkdir(parents=True)
    (deploy / "updates" / "history.jsonl").write_text(json.dumps({"detail": MARKERS["pseudonym"]}) + "\n")
    out = support_bundle.build(deploy, tmp_path / "out", commands=True, say=lambda _: None,
                               given={"a.json": "{}\n"}, given_left_out=[{"what": "x", "why": "y"}])  # fmt: skip
    members = _members(out.read_bytes())
    assert sorted(members) == ["support/MANIFEST.json", "support/a.json"]
    assert {"what": "x", "why": "y"} in json.loads(members["support/MANIFEST.json"])["left_out"]
    with pytest.raises(support_bundle.BundleRefused):
        support_bundle.build(deploy, tmp_path / "out2", add=[deploy / "updates" / "history.jsonl"], given={},
                             say=lambda _: None)  # fmt: skip


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
        kw["scanned"](hashlib.sha256(b"synthetic").hexdigest(), 9)
        return f

    monkeypatch.setattr(support_bundle, "build", fake_build)
    monkeypatch.setattr(support_bundle, "run_cmd", lambda argv, timeout: (1, ""))
    ops = tb_ops.OpsDir(tmp_path / "ops")
    runner = tb_ops.OpsRunner(tb_ops.Box("compose", tmp_path / "deploy", {}, run=fail), ops)
    rid = ops.submit("support_bundle", "console:admin", {})
    res = runner.run_one({"id": rid, "action": "support_bundle", "by": "console:admin", "args": {}})
    assert res["ok"] is False and res["summary"].startswith("BundleNotAudited: not released")
    assert "synthetic" not in res["summary"] and ops_support.record(res) is None
    assert sorted(p.name for p in (tmp_path / "ops" / "support").iterdir()) == [".making"]
    assert list((tmp_path / "ops" / "support" / ".making").iterdir()) == []
