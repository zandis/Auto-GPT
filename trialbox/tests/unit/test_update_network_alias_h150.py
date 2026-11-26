"""H-150: on the bench the update's database step said "made again", then the final ``up`` failed: the orchestrator
could not resolve ``db``. ``docker inspect`` of the database container showed no alias on trialbox-net (a fresh
install of the same bundle: ``[trialbox-db-1, db]``).

The cause, reproduced on a local engine: the release changed trialbox-net's settings (its address range, H-137). For
compose a network whose settings changed is made again, but only when every container on it is in the command's
selection: db-up's ``up db`` leaves it (a warning), and the release's final ``up`` of the whole project removes it,
makes it again and reconnects every container that was there WITHOUT its service's name (``[]``). No raw engine call
makes the container; compose's own reconnect drops the aliases.

The database step (db-up, run by the release now in force before anything is started) now converges the networks
first, with compose for the box's own project and files (``up --no-start --no-recreate``: nothing is started or
recreated), reads every container's aliases, and recreates through compose (``up --no-start --no-deps
--force-recreate``) each service whose container lacks its name on one of its networks; the final ``up`` then finds
the networks as the files say and every name in place. A service still without its name stops the update.

The inspect lines below are recorded from a local engine (compose 5.7.1, engine 29.9.3), with this module's own
format, for a project ``trialbox`` whose trialbox-net took an address range: before, after the network was made
again, and after the recreate."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from tools.trialbox import update as up

RECORDED_FRESH = "db trialbox-net=trialbox-db-1,db\norchestrator trialbox-net=trialbox-orchestrator-1,orchestrator\n"
RECORDED_NETWORK_MADE_AGAIN = "db trialbox-net=\norchestrator trialbox-net=\n"
RECORDED_RECREATED = RECORDED_FRESH

DB_ENV = "TB_DB_URL=postgresql://trialbox@db:5432/trialbox_wf\nCOMPOSE_FILE=docker-compose.yml\n"


class Engine:
    """A recorded engine: ``compose ps -a -q`` names two containers; ``docker inspect`` answers with the recorded
    lines in turn (the last one again after that); every command is kept."""

    def __init__(self, inspects: Sequence[str]) -> None:
        self.inspects = list(inspects)
        self.calls: list[list[str]] = []
        self.kwargs: list[dict[str, Any]] = []

    def __call__(self, argv: Sequence[str], **kw: Any) -> str:
        self.calls.append(list(argv))
        self.kwargs.append(dict(kw))
        if argv[-2:] == ["-a", "-q"]:
            return "c0ffee01\nc0ffee02\n"
        if argv[-2:] == ["-q", "db"]:
            return ""  # the database step's own question (its scripts): no container running, nothing to make again
        if "inspect" in argv:
            return self.inspects.pop(0) if len(self.inspects) > 1 else self.inspects[0]
        return ""

    def composed(self, *words: str) -> list[list[str]]:
        return [c for c in self.calls if c[: len(BASE)] == BASE and all(w in c for w in words)]


def _deploy(tmp_path: Path) -> Path:
    deploy = tmp_path / "deploy"
    (deploy / "docker").mkdir(parents=True)
    (deploy / ".env").write_text(DB_ENV, encoding="utf-8")
    return deploy


BASE: list[str] = []


@pytest.fixture(autouse=True)
def _box_compose(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The box's own compose command, as the updater makes it when TB_COMPOSE names none: the deploy folder is the
    project directory, so compose reads the project's name and files from deploy/.env."""
    monkeypatch.delenv("TB_COMPOSE", raising=False)
    monkeypatch.delenv("TB_DOCKER", raising=False)
    monkeypatch.setenv("TB_INSTALL_UP_TIMEOUT", "60")
    BASE[:] = ["docker", "compose", "--project-directory", str(tmp_path / "deploy")]


def test_a_container_that_lost_its_name_is_recreated_through_the_boxs_compose(tmp_path: Path) -> None:
    """The bench's case: after the networks converge, db and orchestrator have no name on trialbox-net; both are
    recreated by the box's own compose command (project directory: the box's deploy folder, so its project and
    files), never by a raw engine call; the recorded inspect after it shows ``[trialbox-db-1, db]`` again."""
    eng = Engine([RECORDED_NETWORK_MADE_AGAIN, RECORDED_RECREATED])
    line = up.ComposeBox(_deploy(tmp_path), run=eng).db_on_new_settings()
    converge = eng.composed("up", "--no-start", "--no-recreate")
    assert len(converge) == 1 and converge[0][len(BASE) :][:1] == ["up"]
    assert "--force-recreate" not in converge[0] and "-d" not in converge[0]
    again = eng.composed("up", "--no-start", "--no-deps", "--force-recreate")
    assert len(again) == 1 and again[0][-2:] == ["db", "orchestrator"], eng.calls
    assert eng.calls.index(converge[0]) < eng.calls.index(again[0])
    db_up = eng.composed("up", "-d", "--wait")
    assert db_up and eng.calls.index(again[0]) < eng.calls.index(db_up[-1])  # the database starts after its recreate
    raw = [c for c in eng.calls if c[:1] == ["docker"] and c[1:2] in (["run"], ["create"], ["network"], ["container"])]
    assert raw == []  # no container and no network is made outside compose
    assert "db, orchestrator" in line and "recreated" in line
    assert "trialbox-db-1,db" in RECORDED_RECREATED  # what the recorded inspect of the recreated db shows


def test_containers_that_keep_their_names_are_left_as_they_are(tmp_path: Path) -> None:
    """A box whose networks did not change (every update before H-137's, every install): the converge step runs,
    nothing is recreated, and the step's line is the one it was."""
    eng = Engine([RECORDED_FRESH])
    line = up.ComposeBox(_deploy(tmp_path), run=eng).db_on_new_settings()
    assert len(eng.composed("up", "--no-start", "--no-recreate")) == 1
    assert eng.composed("--force-recreate") == []
    assert line == "on this release's settings"


def test_a_service_still_without_its_name_stops_the_update(tmp_path: Path) -> None:
    """Never a box started with a database nobody can find: when the recreate did not give the name back, the step
    fails, naming the service and the network, and the database is not started."""
    eng = Engine([RECORDED_NETWORK_MADE_AGAIN, "db trialbox-net=\norchestrator trialbox-net=trialbox-orchestrator-1,"
                                                "orchestrator\n"])  # fmt: skip
    with pytest.raises(up.UpdateFailed, match=r"db: no name on trialbox-net"):
        up.ComposeBox(_deploy(tmp_path), run=eng).db_on_new_settings()
    assert eng.composed("up", "-d", "--wait") == []


def test_the_engine_its_own_networks_are_not_compose_networks() -> None:
    """The engine's own networks (host, none, the default bridge) carry no service names: never read as lost."""
    assert (
        up.ComposeBox.lacking_names("db host=\nweb bridge=\njob none=\ncache trialbox-net=trialbox-cache-1,cache\n")
        == {}
    )
    assert up.ComposeBox.lacking_names("db trialbox-net= trialbox-model-net=trialbox-db-1,db\n") == {
        "db": ["trialbox-net"]
    }


def test_a_test_box_beside_a_box_keeps_its_own_range(tmp_path: Path) -> None:
    """H-137's test boxes: each has its own range (``testbox.nets``, written into its deploy/.env). The converge of
    a test box is that box's own compose (its deploy folder as the project directory, so its .env and its range),
    with no setting of the updater's own passed to it: never the box's range, never the box's project. Shown on a
    local engine too: a test box's converge left its network on its own range and the box's network (same id)
    untouched."""
    from tools.trialbox import testbox

    root = Path(__file__).resolve().parents[2]
    tdeploy = tmp_path / "tbox" / "deploy"
    (tdeploy / "docker").mkdir(parents=True)
    (tdeploy / "docker-compose.identity.yml").write_text(
        (root / "deploy" / "docker-compose.identity.yml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    own = testbox.nets(tdeploy, 1)
    box_range = testbox.nets(tdeploy, 0)["TB_NET_SUBNET"]
    assert own and own["TB_NET_SUBNET"] != box_range  # a range of its own, beside the box's
    lines = [f"{k}={v}" for k, v in sorted(own.items())]
    (tdeploy / ".env").write_text(DB_ENV + "COMPOSE_PROJECT_NAME=tbtest1\n" + "\n".join(lines) + "\n", encoding="utf-8")
    eng = Engine([RECORDED_NETWORK_MADE_AGAIN, RECORDED_RECREATED])
    up.ComposeBox(tdeploy, run=eng).db_on_new_settings()
    composed = [c for c in eng.calls if c[:2] == ["docker", "compose"]]
    assert composed and all(c[2:4] == ["--project-directory", str(tdeploy)] for c in composed)
    assert not any("TB_NET_SUBNET" in " ".join(c) for c in eng.calls)
    named = [kw.get("env") or {} for kw in eng.kwargs]
    assert not any("TB_NET_SUBNET" in e or "COMPOSE_PROJECT_NAME" in e for e in named)
