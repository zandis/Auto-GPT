"""F-19 and its review (#1305): a re-run of ``deploy/install.sh`` cleans up a failed run's containers, and nothing else.

The installer's PROJECT-CLEANUP block runs here in bash, as written in the script, with a stand-in Docker engine
(no daemon): the engine answers the compose project's name, the containers that carry its label and their state, and
records a ``down``. The invariant: ``down --remove-orphans`` runs only on a project proven to be this install's (its
name, and every container started from this ``deploy`` folder) whose stack is not running healthy. Each planted case
breaks one part of that proof and must remove nothing."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.nodb
ROOT = Path(__file__).resolve().parents[2]
INSTALL = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
START, END = "# PROJECT-CLEANUP", "# ---- end of PROJECT-CLEANUP"

ENGINE = r"""
import json, sys
from pathlib import Path
here = Path(__file__).resolve().parent
state = json.loads((here / "state.json").read_text())
args = sys.argv[1:]
with (here / "docker.log").open("a") as log:
    log.write(json.dumps(args) + "\n")
if args[:1] == ["compose"] and "config" in args:
    print(json.dumps({"name": state["resolves"]}))
elif args[:1] == ["compose"] and "down" in args:
    pass
elif args[:2] == ["ps", "-a"]:
    want = args[-1].rpartition("=")[2]
    print("\n".join(c["Id"] for c in state["containers"] if c["Config"]["Labels"]["com.docker.compose.project"] == want))
elif args[:1] == ["inspect"]:
    print(json.dumps([c for c in state["containers"] if c["Id"] in args[1:]]))
else:
    sys.exit(f"stand-in docker: unexpected {args}")
"""


def _container(n: int, deploy: Path | str, status: str = "running", health: str | None = "healthy",
               exit_code: int = 0, restart: str = "unless-stopped", project: str = "trialbox") -> dict[str, Any]:  # fmt: skip
    state: dict[str, Any] = {"Status": status, "ExitCode": exit_code}
    if health is not None:
        state["Health"] = {"Status": health}
    labels = {"com.docker.compose.project": project, "com.docker.compose.project.working_dir": str(deploy)}
    return {"Id": f"c{n:063d}", "Name": f"/{project}-svc-{n}", "State": state, "Config": {"Labels": labels},
            "HostConfig": {"RestartPolicy": {"Name": restart}}}  # fmt: skip


def _box(tmp: Path) -> Path:
    box = tmp / "box"
    (box / "deploy").mkdir(parents=True)
    (box / "deploy" / "docker-compose.yml").write_text("name: trialbox\nservices: {}\n", encoding="utf-8")
    (box / "tools").symlink_to(ROOT / "tools")
    b = tmp / "bin"
    b.mkdir()
    (b / "python3").symlink_to(sys.executable)
    engine = b / "docker"
    engine.write_text(f"#!{sys.executable}\n{ENGINE}", encoding="utf-8")
    engine.chmod(0o755)
    return box


def _cleanup(tmp: Path, box: Path, resolves: str, containers: list[dict[str, Any]],
             **env: str) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:  # fmt: skip
    """The installer's block, whole, after the compose command install.sh builds; then the engine's calls."""
    (tmp / "bin" / "state.json").write_text(json.dumps({"resolves": resolves, "containers": containers}))
    block = INSTALL[INSTALL.index(START) : INSTALL.index(END)]
    script = ("set -euo pipefail\ndie() { echo \"install: $*\" >&2; exit 1; }\n"
              f"ROOT={box}\ncd \"$ROOT\"\nCOMPOSE=(docker compose --project-directory deploy "
              "-f deploy/docker-compose.yml --profile stub)\n" + block + "echo cleanup-passed\n")  # fmt: skip
    base = {"PATH": f"{tmp / 'bin'}{os.pathsep}/usr/bin:/bin", "HOME": str(tmp)}
    res = subprocess.run(["bash", "-c", script], env={**base, **env}, capture_output=True, text=True, check=False,
                         timeout=120)  # fmt: skip
    log = tmp / "bin" / "docker.log"
    calls = [json.loads(x) for x in log.read_text().splitlines()] if log.is_file() else []
    return res, calls


def _downs(calls: list[list[str]]) -> list[list[str]]:
    return [c for c in calls if "down" in c]


PLANTED = {
    # a shell that exported another project's name: compose would have taken that project down as "this" one
    "inherited-project-name": ({"COMPOSE_PROJECT_NAME": "radiology"}, "radiology", "radiology", "other"),
    # compose resolves a name other than this install's (any route): never acted on
    "compose-resolves-another-name": ({}, "radiology", "trialbox", "this"),
    # a container of the project started from another folder: the name is shared with another install
    "container-from-another-folder": ({}, "trialbox", "trialbox", "other"),
}


@pytest.mark.parametrize("case", sorted(PLANTED))
def test_install_cleanup_removes_only_this_installs_unhealthy_project(tmp_path: Path, case: str) -> None:
    """THE INVARIANT of the card: the cleanup removes containers only of a project it proves is this install's, and
    only when that stack is not running healthy. Each planted case breaks one part of the proof: refused, nothing
    removed, the reason said. The positive control (this install's failed run) is taken down."""
    box = _box(tmp_path)
    mine = box / "deploy"
    env, resolves, project, where = PLANTED[case]
    elsewhere = tmp_path / "radiology" / "deploy"
    failed = [_container(1, mine, project=project), _container(2, elsewhere if where == "other" else mine,
              status="exited", health=None, exit_code=1, project=project)]  # fmt: skip
    res, calls = _cleanup(tmp_path, box, resolves, failed, **env)
    assert res.returncode != 0 and "cleanup-passed" not in res.stdout, res.stderr
    assert _downs(calls) == [], calls
    assert "nothing was removed" in res.stderr, res.stderr
    # positive control: the same failed run, proven to be this install's, is cleaned up with every profile
    ok, ok_calls = _cleanup(tmp_path, box, "trialbox", [_container(1, mine), _container(2, mine, status="exited",
                            health=None, exit_code=1)])  # fmt: skip
    assert ok.returncode == 0 and "cleanup-passed" in ok.stdout, ok.stderr
    (down,) = _downs(ok_calls)
    assert down[-2:] == ["down", "--remove-orphans"], down
    assert any(down[i : i + 2] == ["--profile", "*"] for i in range(len(down))), down


def test_a_healthy_stack_is_kept_with_its_logs(tmp_path: Path) -> None:
    """Review of #1305 (5, 10): a same-release re-run on a healthy box removes no container (their logs stay). A
    one-shot job that ended with exit 0 is part of a healthy stack."""
    box = _box(tmp_path)
    mine = box / "deploy"
    healthy = [_container(1, mine), _container(2, mine, health=None),
               _container(3, mine, status="exited", health=None, exit_code=0, restart="no")]  # fmt: skip
    res, calls = _cleanup(tmp_path, box, "trialbox", healthy)
    assert res.returncode == 0 and "cleanup-passed" in res.stdout and "kept" in res.stderr, res.stderr
    assert _downs(calls) == []
    for planted in (_container(4, mine, health="unhealthy"), _container(4, mine, status="exited", health=None,
                    exit_code=0, restart="unless-stopped")):  # fmt: skip
        (tmp_path / "bin" / "docker.log").unlink()
        res, calls = _cleanup(tmp_path, box, "trialbox", [*healthy, planted])
        assert res.returncode == 0 and len(_downs(calls)) == 1, (planted, res.stderr)


def test_no_container_means_nothing_to_remove_and_the_same_name_inherited_is_allowed(tmp_path: Path) -> None:
    box = _box(tmp_path)
    res, calls = _cleanup(tmp_path, box, "trialbox", [])
    assert res.returncode == 0 and _downs(calls) == [], res.stderr
    failed = [_container(1, box / "deploy", status="exited", health=None, exit_code=137)]
    res, calls = _cleanup(tmp_path, box, "trialbox", failed, COMPOSE_PROJECT_NAME="trialbox")
    assert res.returncode == 0 and len(_downs(calls)) == 1, res.stderr


def test_the_cleanup_waits_for_the_releases_checks() -> None:
    """Review of #1305 (5): nothing is taken down before the release's own checks (pre-start, which refuses a bad
    directory CA) have passed, and the cleanup still comes before the network is used."""
    block = INSTALL.index(START)
    assert INSTALL.index('python3 -m tools.trialbox pre-start --deploy "$ROOT/deploy"') < block
    assert INSTALL.index('finish_check "not finished') < block
    assert block < INSTALL.index('"${COMPOSE[@]}" run --rm --no-deps -T adapter')
    assert block < INSTALL.index('"${COMPOSE[@]}" up -d --pull "$PULL" --wait db')
    assert INSTALL.count("down --remove-orphans") == 2  # the help's plan and the one guarded call
