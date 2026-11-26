"""termfix: an update stopped by SIGTERM must end as one stopped by ``kill -9`` does: back on the release before,
with no marker left at "rollback failed" that ``tools/apply_update.sh rollback`` cannot finish.

On the bench box a SIGTERM during the apply started the updater's own rollback; its database restore failed with
"cannot drop inherited constraint" (the pre-H-151 ``pg_restore --clean`` over a partitioned lake), and every
``rollback <bundle>`` after it failed within seconds. Two things in the compose box's rollback made a failed
in-process rollback final: it put the host tree (the code the next ``rollback`` runs) back to the release before
*before* the database restore, so a retry ran that older release's restore; and it removed the images the update
had added with ``docker image rm -f``, which fails on a second run because the first one removed them already.

Each case runs the real :class:`tools.trialbox.update.Updater` and the real ``ComposeBox.rollback``; the update is
stopped by a real SIGTERM sent to this process inside the apply step. The ``db`` container is the session's local
test cluster (``tools/pglocal.py``) with H-151's partitioned lake: the runner stand-in runs the restore script given
to ``docker compose exec db`` under dash against it, as ``test_rollback_restore_h151.py`` does; every other docker
command is a stand-in that keeps the engine's tags as docker does."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_rollback_restore_h151 import ADMIN, AFTER_SQL, LAKE_SQL, Box
from tools import pglocal
from tools import update_status as us
from tools.trialbox import update as up

RELEASE_RESTORE_SH = up.RESTORE_SH  # this release's restore (H-151: a fresh database, the names swapped)
# the restore script before #1535 (git show 21b3c8d29^:trialbox/tools/trialbox/update.py), the one the bench box's
# installed release ran: pg_restore --clean over the database in place
OLD_RESTORE_SH = (
    f'umask 077; d="{up.RESTORE_DIR}"; rm -rf -- "$d"; mkdir -m 0700 "$d" || exit 1; '
    "trap 'rm -rf -- \"$d\"' EXIT; trap 'exit 1' HUP INT TERM; "
    't=$(mktemp -p "$d") || exit 1; '
    'pg_restore --clean --if-exists --no-owner -f "$t" || exit 1; '
    '{ printf "%s\\n" "$3"; cat "$t"; } | psql -X -q -v ON_ERROR_STOP=1 --single-transaction -U "$1" -d "$2"'
)
NEW_TAG = "trialbox/added-by-the-update:1"  # an image the bundle brought that the box did not have (rollback tag "")


class Engine:
    """The runner stand-in: the db exec runs the restore against the test cluster; image tags are kept as docker
    keeps them (``image inspect`` and ``image rm`` of a tag that is not there fail, as docker's do)."""

    def __init__(self, lake: Box) -> None:
        self.lake = lake
        self.images = {NEW_TAG}
        self.calls: list[str] = []

    def __call__(self, argv: list[str], stdin_file: Path | None = None, **_kw: Any) -> str:
        argv = list(argv)
        if "tb-restore" in argv:  # docker compose exec -T db sh -c SCRIPT tb-restore ROLE DB RESET_SQL
            i = argv.index("tb-restore")
            script, (role, db, reset) = argv[i - 1], argv[i + 1 : i + 4]
            assert (role, db) == ("trialbox", "trialbox_wf")
            self.calls.append("restore trialbox_wf")
            shell = shutil.which("dash") or "/bin/sh"
            with (stdin_file or Path(os.devnull)).open("rb") as fh:
                r = subprocess.run([shell, "-c", script, "tb-restore", self.lake.owner, self.lake.db, reset],
                                   stdin=fh, env=self.lake.env, capture_output=True, check=False)  # fmt: skip
            if r.returncode != 0:
                raise up.UpdateFailed(f"restore exit {r.returncode}: {r.stderr.decode(errors='replace')[-600:]}")
            return ""
        if argv[:3] == ["docker", "image", "inspect"]:
            if argv[-1] not in self.images:
                raise up.UpdateFailed(f"docker image inspect ... exit 1: No such image: {argv[-1]}")
            return "sha256:" + "a" * 64
        if argv[:3] == ["docker", "image", "rm"]:
            if argv[-1] not in self.images:
                raise up.UpdateFailed(f"docker image rm ... exit 1: No such image: {argv[-1]}")
            self.images.discard(argv[-1])
            self.calls.append(f"rm {argv[-1]}")
            return ""
        self.calls.append(" ".join(argv[-3:]))
        return ""


class TermBox(up.ComposeBox):
    """The compose box with its real rollback; the steps before it are stand-ins. The apply does what a new release
    does to the lake (rows, a partition, a table) and is then stopped by a real SIGTERM."""

    def __init__(self, deploy: Path, lake: Box, dump: Path) -> None:
        self.engine = Engine(lake)
        super().__init__(deploy, run=self.engine)
        self.lake = lake
        self.dump = dump
        self.host_restored = 0

    def snapshot(self, plan: up.Plan, rb: Path, point: up.Point) -> None:
        self.lake.dump(self.dump)
        point.dumps["trialbox_wf"] = str(self.dump)
        point.images[NEW_TAG] = ""
        point.extra["host"] = {"previous": "R0", "release": plan.bundle_id, "fresh": True}

    def apply(self, plan: up.Plan, rb: Path, point: up.Point) -> list[str]:
        self.lake.psql(AFTER_SQL, user=self.lake.owner)
        os.kill(os.getpid(), signal.SIGTERM)
        for _ in range(500):  # the updater's handler raises UpdateInterrupted between two bytecodes
            time.sleep(0.01)
        raise AssertionError("SIGTERM did not stop the apply")

    def restart(self, plan: up.Plan) -> None:
        return None

    def check(self, plan: up.Plan) -> str:
        return "healthy"

    def check_weights(self) -> str:
        return ""

    def audit(self, event: str, plan: up.Plan, detail: dict[str, Any]) -> None:
        return None


@pytest.fixture
def lake(pg_cluster_url: str, tmp_path: Path) -> Iterator[Box]:
    """H-151's partitioned lake on the session's cluster, with its own roles and database (the same set-up)."""
    from psycopg.conninfo import conninfo_to_dict
    from tb_common.db import split_url

    host = str(conninfo_to_dict(split_url(pg_cluster_url)[0])["host"])
    work = tmp_path / "pgdata"  # PGDATA: the restore's script folder is under it, as on the db volume
    work.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    env.update(PGHOST=host, PGDATA=str(work), POSTGRES_USER=ADMIN,
               PATH=f"{pglocal.bindir()}:{env.get('PATH', '')}")  # fmt: skip
    tag = f"{os.getpid()}_{tmp_path.name[-6:]}".replace("-", "_").lower()
    b = Box(db=f"term_{tag}", owner=f"termo_{tag}", group=f"termg_{tag}", env=env, work=work)
    b.psql(f"CREATE ROLE {b.owner} LOGIN; CREATE ROLE {b.group} NOLOGIN; GRANT {b.group} TO {b.owner}", db="postgres")
    b.psql(f"CREATE DATABASE {b.db} OWNER {b.owner}", db="postgres")
    b.psql(f"REVOKE ALL ON DATABASE {b.db} FROM PUBLIC; GRANT CONNECT ON DATABASE {b.db} TO {b.group}", db="postgres")
    b.psql(LAKE_SQL.format(owner=b.owner, group=b.group))
    try:
        yield b
    finally:
        for name in b.databases():
            b.psql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)', db="postgres")
        b.psql(f"DROP ROLE IF EXISTS {b.owner}; DROP ROLE IF EXISTS {b.group}", db="postgres")


@pytest.fixture
def term(lake: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TermBox, up.Updater]:
    deploy = tmp_path / "deploy"
    (deploy / "updates").mkdir(parents=True)
    monkeypatch.delenv("TB_COMPOSE", raising=False)
    monkeypatch.setattr(up.Updater, "preflight", lambda self, plan, backup=True: [])  # not what these cases test
    tb = TermBox(deploy, lake, tmp_path / "trialbox_wf.dump")

    def host_back(base: Path, point: up.Point) -> None:  # the host tree's own put-back is host_tree's tests'
        if point.extra.get("host"):
            tb.host_restored += 1
            tb.engine.calls.append("host tree back")

    monkeypatch.setattr(up, "restore_host", host_back)
    return tb, up.Updater(tb, deploy / "updates", say=lambda _m: None)


def _plan(tmp_path: Path) -> up.Plan:
    stage = tmp_path / "stage"
    stage.mkdir(exist_ok=True)
    return up.Plan("B1", "f" * 64, "vendor", [], stage)


def _history(updates: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in (updates / "history.jsonl").read_text(encoding="utf-8").splitlines() if x]


def test_sigterm_during_the_apply_rolls_a_partitioned_lake_back(term: tuple[TermBox, up.Updater],
                                                                 tmp_path: Path) -> None:  # fmt: skip
    """The bench's case with this release's restore: SIGTERM in the apply, the in-process rollback puts the lake
    back (rows in their partitions, keys, the partition the release added gone), the database first and the host tree
    after it, and the marker is removed."""
    tb, updater = term
    at_dump = tb.lake.state()
    with pytest.raises(up.UpdateFailed) as exc:
        updater.run(_plan(tmp_path), backup=False)
    assert "stopped by SIGTERM" in str(exc.value) and "rolled back" in str(exc.value), str(exc.value)
    assert "ROLLBACK FAILED" not in str(exc.value)
    assert us.marker(updater.dir) is None
    assert tb.lake.state() == at_dump
    assert tb.lake.databases() == [tb.lake.db]
    assert NEW_TAG not in tb.engine.images and tb.host_restored == 1
    assert tb.engine.calls.index("restore trialbox_wf") < tb.engine.calls.index("host tree back")


def test_a_failed_in_process_rollback_is_finished_by_rollback_bundle(term: tuple[TermBox, up.Updater],
                                                                     tmp_path: Path,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    """The bench's sequence. The in-process rollback after the SIGTERM runs the pre-#1535 restore and fails with
    "cannot drop inherited constraint": the marker stays at "rollback failed", the lake is as the release left it,
    and the host tree is still the release that wrote the marker (its rollback is the one that runs next). Then
    ``tools/apply_update.sh rollback B1`` (``Updater.recover``) finishes it: the image the first run removed already
    is no error, the lake is back, the host tree is put back once, the marker is gone."""
    tb, updater = term
    at_dump = tb.lake.state()
    monkeypatch.setattr(up, "RESTORE_SH", OLD_RESTORE_SH)
    with pytest.raises(up.UpdateFailed) as exc:
        updater.run(_plan(tmp_path), backup=False)
    assert "stopped by SIGTERM" in str(exc.value) and "ROLLBACK FAILED" in str(exc.value), str(exc.value)
    assert (us.marker(updater.dir) or {}).get("step") == "rollback failed"
    failed = [h for h in _history(updater.dir) if h["step"] == "rollback" and not h["ok"]]
    assert failed and "cannot drop inherited constraint" in failed[-1]["detail"], failed
    assert tb.lake.state() != at_dump  # the release's rows and partition are still there
    assert NEW_TAG not in tb.engine.images  # the first run removed the update's image before its restore failed
    assert tb.host_restored == 0  # the code that finishes the rollback is still this release's

    monkeypatch.setattr(up, "RESTORE_SH", RELEASE_RESTORE_SH)
    out = up.Updater(tb, updater.dir, say=lambda _m: None).recover("B1")
    assert out["ok"] is True and out["from_step"] == "rollback failed"
    assert us.marker(updater.dir) is None
    assert tb.lake.state() == at_dump
    assert tb.lake.databases() == [tb.lake.db]
    assert tb.host_restored == 1
