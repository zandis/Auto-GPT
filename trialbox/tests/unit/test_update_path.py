"""TB-PLAN-04 step 8 (D-138): the update path. Backup first (nothing changes when it fails), a rollback point, apply,
migrate and restart, check; any failure after the rollback point puts images, models and database back.

The order of the steps is tested on a recording box; the docker and compose commands of the site box and the demo
box are tested against a fake runner (no Docker here); the in-process box runs for real on the test's own schemas
(``pg_dump``, ``tb_common.db`` migrations, ``pg_restore``). ``tools/update_drill.py`` runs the whole path on the
``e2e_simple`` box."""

from __future__ import annotations

import hashlib
import json
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Any

import pytest

from tools.trialbox import update as up

ROOT = Path(__file__).resolve().parents[2]


def _plan(tmp: Path, kinds: dict[str, dict[str, bytes]] | None = None, bundle_id: str = "B1") -> up.Plan:
    stage = tmp / f"stage-{bundle_id}"
    for kind, files in (kinds or {}).items():
        for rel, data in files.items():
            p = stage / kind / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
    stage.mkdir(parents=True, exist_ok=True)
    return up.Plan(bundle_id, "f" * 64, "TrialBox vendor", [{"path": "x", "kind": "other"}], stage)


class Recorder:
    name = "recorder"

    def __init__(self, fail: str | None = None, fail_rollback: bool = False) -> None:
        self.calls: list[str] = []
        self.fail = fail
        self.fail_rollback = fail_rollback
        self.audits: list[tuple[str, dict[str, Any]]] = []

    def _step(self, name: str) -> None:
        self.calls.append(name)
        if self.fail == name:
            raise RuntimeError(f"{name} broke")

    def running(self) -> bool:
        return True

    def backup(self, plan: up.Plan, rb: Path) -> str:
        self._step("backup")
        return "nas"

    def snapshot(self, plan: up.Plan, rb: Path, point: up.Point) -> None:
        self._step("snapshot")
        f = rb / "trialbox_wf.dump"
        f.write_text("dump")
        point.dumps["trialbox_wf"] = str(f)

    def apply(self, plan: up.Plan, rb: Path, point: up.Point) -> list[str]:
        self._step("apply")
        return ["image x"]

    def restart(self, plan: up.Plan) -> None:
        self._step("restart")

    def post_apply(self, plan: up.Plan) -> list[str]:
        self._step("post_apply")
        return []

    def check(self, plan: up.Plan) -> str:
        self._step("check" if "rollback" not in self.calls else "check_after")
        return "healthy"

    def rollback(self, plan: up.Plan, rb: Path, point: up.Point) -> None:
        self.calls.append("rollback")
        if self.fail_rollback:
            raise RuntimeError("rollback broke")

    def audit(self, event: str, plan: up.Plan, detail: dict[str, Any]) -> None:
        self.audits.append((event, detail))


def test_a_good_update_backs_up_first_then_applies_migrates_checks_and_audits(tmp_path: Path) -> None:
    box = Recorder()
    out = up.Updater(box, tmp_path / "updates", say=lambda _m: None).run(_plan(tmp_path))
    assert out["ok"]
    assert box.calls == ["backup", "snapshot", "apply", "restart", "post_apply", "check"]
    assert [e for e, _ in box.audits] == ["update.applied"]
    assert not (tmp_path / "updates/B1/rollback/trialbox_wf.dump").exists()  # the local dump goes after success
    hist = [json.loads(x) for x in (tmp_path / "updates/history.jsonl").read_text().splitlines()]
    assert hist[0]["step"] == "backup (D-126)" and all(h["ok"] for h in hist)


def test_a_failed_backup_changes_nothing(tmp_path: Path) -> None:
    box = Recorder(fail="backup")
    with pytest.raises(up.UpdateFailed, match="backup failed, nothing was changed"):
        up.Updater(box, tmp_path / "updates", say=lambda _m: None).run(_plan(tmp_path))
    assert box.calls == ["backup"] and box.audits == []


@pytest.mark.parametrize("where", ["apply", "restart", "post_apply", "check"])
def test_any_failure_after_the_rollback_point_rolls_back_and_is_audited(tmp_path: Path, where: str) -> None:
    box = Recorder(fail=where)
    with pytest.raises(up.UpdateFailed, match="rolled back"):
        up.Updater(box, tmp_path / "updates", say=lambda _m: None).run(_plan(tmp_path))
    assert box.calls[-2:] == ["rollback", "check_after"]
    ((event, detail),) = box.audits
    assert event == "update.rolled_back" and detail["rolled_back"] and f"{where} broke" in detail["error"]


def test_a_failed_rollback_says_so(tmp_path: Path) -> None:
    box = Recorder(fail="restart", fail_rollback=True)
    with pytest.raises(up.UpdateFailed, match="ROLLBACK FAILED"):
        up.Updater(box, tmp_path / "updates", say=lambda _m: None).run(_plan(tmp_path))
    assert box.audits[0][1]["rolled_back"] is False


def _image_tar(path: Path, tag: str) -> bytes:
    import io

    buf = json.dumps([{"RepoTags": [tag]}]).encode()
    with tarfile.open(path, "w") as tf:
        info = tarfile.TarInfo("manifest.json")
        info.size = len(buf)
        tf.addfile(info, io.BytesIO(buf))
    return path.read_bytes()


class FakeRun:
    def __init__(self, fail_on: str | None = None, images: dict[str, str] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.stdin: list[str] = []
        self.envs: list[dict[str, str]] = []
        self.fail_on = fail_on
        self.images = images or {}
        # OCR 1469-7: the engine's data root is a folder of the test's own, never the host's /var/lib/docker (an
        # empty answer to `docker info` falls back to it: CI's runner has it, 0710 root, train 167)
        self.docker_root = Path(tempfile.mkdtemp(prefix="docker-root-"))

    def __call__(self, argv: list[str], stdin_file: Path | None = None, stdout_file: Path | None = None,
                 env: dict[str, str] | None = None, timeout: float | None = None) -> str:  # fmt: skip
        self.calls.append(list(argv))
        self.envs.append(dict(env or {}))
        if stdin_file:
            self.stdin.append(str(stdin_file))
        if stdout_file:
            stdout_file.write_text("dump")
        line = " ".join(argv)
        if self.fail_on and self.fail_on in line:
            raise up.UpdateFailed(f"{self.fail_on} failed")
        if argv[:3] == ["docker", "image", "inspect"]:
            if argv[-1] not in self.images:
                raise up.UpdateFailed("no such image")
            return self.images[argv[-1]] + "\n"
        if "ps" in argv and "--services" in argv:
            return "db\norchestrator\nconsole\n"
        if argv[:3] == ["docker", "inspect", "-f"]:
            return "true\n"
        if "FROM orch.jobs" in line:  # T-695: no job running, so the update may stop the services
            return "0\n"
        if argv[:2] == ["docker", "info"]:
            return f"{self.docker_root}\n"
        if "pg_database_size" in line:  # H-121: the size check reads a size (an empty answer stops the update)
            return "1000\n"
        return ""


@pytest.fixture(autouse=True)
def _no_real_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    """`docker volume ls` through TB_DOCKER: `true` answers "no volumes" without the host's Docker."""
    monkeypatch.setenv("TB_DOCKER", "true")


@pytest.fixture()
def deploy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "deploy"
    (d / "secrets").mkdir(parents=True)
    (d / "secrets/backup.pub").write_text("pub")
    (d / ".env").write_text(f"TB_BACKUP_TARGETS={tmp_path / 'nas'}\nPOSTGRES_PASSWORD=pg-secret\n"
                            "TB_DB_URL=postgresql://trialbox:wf-secret@db:5432/trialbox_wf\n")  # fmt: skip
    monkeypatch.setenv("TB_COMPOSE", "dc")
    monkeypatch.setenv("TB_MODELS_DIR", str(tmp_path / "models"))
    (tmp_path / "models/judge").mkdir(parents=True)
    (tmp_path / "models/judge/config.json").write_text("old")
    return d


def test_compose_box_commands_in_order(tmp_path: Path, deploy: Path) -> None:
    plan = _plan(tmp_path, {"image": {"py.tar": b""}, "model": {"judge/config.json": b"new"}})
    _image_tar(plan.stage / "image/py.tar", "trialbox-py:1.0.0")
    run = FakeRun(images={"trialbox-py:1.0.0": "sha256:old"})
    box = up.ComposeBox(deploy, run=run)
    out = up.Updater(box, deploy / "updates", say=lambda _m: None).run(plan)
    lines = [" ".join(c) for c in run.calls]
    i = {k: next(n for n, ln in enumerate(lines) if k in ln) for k in
         ("dc stop", "pg_dump -Fc --no-owner -U trialbox -d trialbox_wf", "docker run --rm --network trialbox-net",
          "docker tag sha256:old trialbox-py:rollback-B1", "docker load", "dc up -d --wait")}  # fmt: skip
    assert list(i.values()) == sorted(i.values())  # quiet box, dump, backup, rollback tag, load, start
    assert out["ok"] and (tmp_path / "models/judge/config.json").read_text() == "new"
    backup = run.calls[i["docker run --rm --network trialbox-net"]]
    assert not any("pg-secret" in a or "wf-secret" in a for a in backup)  # passwords: in the environment only
    env = run.envs[i["docker run --rm --network trialbox-net"]]
    assert env["TB_HAPI_DB_URL"].endswith("@db:5432/hapi") and "wf-secret" in env["TB_DB_URL"]
    assert any("update.applied" in Path(f).read_text() for f in run.stdin)


def test_compose_box_rolls_back_images_models_and_database(tmp_path: Path, deploy: Path) -> None:
    plan = _plan(tmp_path, {"image": {"py.tar": b""}, "model": {"judge/config.json": b"new", "judge/new.bin": b"x"}})
    _image_tar(plan.stage / "image/py.tar", "trialbox-py:1.0.0")
    run = FakeRun(fail_on="--wait-timeout 900", images={"trialbox-py:1.0.0": "sha256:old"})
    box = up.ComposeBox(deploy, run=run)
    with pytest.raises(up.UpdateFailed):
        up.Updater(box, deploy / "updates", say=lambda _m: None).run(plan)
    lines = [" ".join(c) for c in run.calls]
    assert "docker tag trialbox-py:rollback-B1 trialbox-py:1.0.0" in lines
    restores = [ln for ln in lines if "pg_restore" in ln]
    assert len(restores) == 2 and all("--clean" in ln for ln in restores)
    assert (tmp_path / "models/judge/config.json").read_text() == "old"
    assert not (tmp_path / "models/judge/new.bin").exists()


def test_compose_box_refuses_without_a_backup_key_or_target(tmp_path: Path, deploy: Path) -> None:
    (deploy / "secrets/backup.pub").unlink()
    run = FakeRun()
    with pytest.raises(up.UpdateRefused, match="backup not possible, nothing was changed"):
        up.Updater(up.ComposeBox(deploy, run=run), deploy / "updates", say=lambda _m: None).run(_plan(tmp_path))
    assert run.calls == []  # D-210: refused in the preflight, before any command


def test_demo_box_swaps_the_container_and_runs_e2e_simple(tmp_path: Path, deploy: Path,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    plan = _plan(tmp_path, {"image": {"demo.tar": b""}})
    _image_tar(plan.stage / "image/demo.tar", "trialbox-demo:step5")
    run = FakeRun(images={"trialbox-demo:step5": "sha256:demo-a"})
    box = up.DemoBox(deploy, run=run)
    monkeypatch.setattr(box, "_recreate", lambda: run(["recreate"]))
    out = up.Updater(box, deploy / "updates", say=lambda _m: None).run(plan)
    lines = [" ".join(c) for c in run.calls]
    order = [next(n for n, ln in enumerate(lines) if k in ln) for k in
             ("tools.update_drill backup-work", "docker tag sha256:demo-a trialbox-demo:rollback-B1", "docker load",
              "recreate", "tools.e2e_simple")]  # fmt: skip
    assert out["ok"] and order == sorted(order)
    assert (deploy / "updates/audit").is_dir()


def test_first_install_only_loads_and_defers_the_audit(
    tmp_path: Path, deploy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stage = tmp_path / "stage"
    (stage / "model/judge").mkdir(parents=True)
    (stage / "model/judge/config.json").write_text("new")
    (stage / "manifest.json").write_bytes(b"{}")
    summary = stage / "summary.json"  # D-210: in the stage folder, bound to the staged manifest
    compat = {"format": "trialbox-update-compat/1", "bundle_id": "B0", "rows": [{}]}
    summary.write_text(json.dumps({"bundle_id": "B0", "manifest_sha256": hashlib.sha256(b"{}").hexdigest(),
                                   "signer": "v", "files": [], "release_seq": 1, "compat": compat,
                                   "trust_sha256": None}))  # fmt: skip
    (deploy / ".env").unlink()  # a first install: install.sh writes the settings after the load
    shutil.rmtree(deploy / "secrets")
    monkeypatch.setenv("TB_SKIP_AUDIT", "1")
    assert up.main_apply(stage, summary, "compose", deploy) == 0
    assert (deploy / "updates/pending_audit/B0.json").is_file()
    assert (tmp_path / "models/judge/config.json").read_text() == "new"
    assert json.loads((deploy / "updates/installed.json").read_text())["release_seq"] == 1  # D-210


def test_in_process_box_migrates_and_rolls_back_the_database(tmp_path: Path, db_url: str) -> None:
    work = tmp_path / "box-run"
    (work / "box").mkdir(parents=True)
    (work / "box/file.txt").write_text("data")
    box = up.InProcessBox(work, db_url, tmp_path / "backups")
    upd = up.Updater(box, tmp_path / "updates", say=lambda _m: None)
    good = _plan(tmp_path, {"image": {"py.tar": b"x"}, "other": {"migrations/001_note.sql": b"CREATE TABLE note (id INT)"}},
                 bundle_id="G")  # fmt: skip
    assert upd.run(good)["ok"] and box.schema_version() == 1
    assert len(list((tmp_path / "backups/nas").glob("*.tbbak"))) == 1
    bad = _plan(tmp_path, {"image": {"py.tar": b"y"}, "other": {
        "migrations/001_note.sql": b"CREATE TABLE note (id INT)", "migrations/002_extra.sql": b"CREATE TABLE extra (id INT)",
        "FAIL_CHECK": b"x"}}, bundle_id="H")  # fmt: skip
    with pytest.raises(up.UpdateFailed, match="rolled back"):
        upd.run(bad)
    assert box.schema_version() == 1  # version 2 ran, then the database came back from the dump
    assert (work / "RELEASE").read_text().startswith("G ")
    events = [
        json.loads(x)["event"] for f in sorted((work / "box/audit").glob("*.jsonl")) for x in f.read_text().splitlines()
    ]
    assert events == ["update.applied", "update.rolled_back"]
