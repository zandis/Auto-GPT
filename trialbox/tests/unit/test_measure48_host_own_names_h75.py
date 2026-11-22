"""H-75: the 48 GB host run takes its own compose project and image tag, beside an installed box.

`tools/measure48-host.sh --project NAME --image-tag TAG` (defaults from the run id; trialbox and the box's tags refused)
runs the stub, the servers and the screen under the run's own names, through variables that six files of other lanes
now read with today's value as the default: deploy/docker-compose.yml, deploy/docker-compose.test.yml, deploy/poc.sh,
deploy/build_db_image.sh, tools/dgpu48.py, tools/measure48-vm.sh. With nothing set every name is master's: the compose
files render byte-identical to their literal form, and the scripts' commands are master's. Under an own tag no build,
tag or removal names a box tag, and the run removes only its own objects and images. No Docker daemon: compose renders
without one; docker is a stand-in elsewhere."""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_compose_limits import DUMMY_ENV
from tests.unit.test_measure48_host_h67 import ROOT, SCRIPT, Rig
from tests.unit.test_poc_db_image import DOCKER as POC_DOCKER

pytestmark = [pytest.mark.nodb, pytest.mark.skipif(sys.platform != "linux", reason="bash and GNU tools")]

DEPLOY = ROOT / "deploy"
VAR = "${TB_COMPOSE_PROJECT:-trialbox}"
BOX_TAG = re.compile(r"trialbox-[a-z]+:(1\.0\.0|16-1)\b")
OWN = {"TB_COMPOSE_PROJECT": "r1", "TB_IMAGE": "trialbox-py:r1", "TB_JVM_IMAGE": "trialbox-jvm:r1",
       "TB_DB_IMAGE": "trialbox-postgres:r1", "POSTGRES_IMAGE": "trialbox-postgres:r1"}  # fmt: skip
BOX_IMAGES = ["trialbox-py:1.0.0", "trialbox-jvm:1.0.0", "trialbox-embed:1.0.0", "trialbox-postgres:16-1"]
NAMED = ("TB_COMPOSE_PROJECT", "TB_IMAGE", "TB_JVM_IMAGE", "TB_EMBED_IMAGE", "TB_DOCPARSER_IMAGE", "TB_DB_IMAGE",
         "POSTGRES_IMAGE", "COMPOSE_PROJECT_NAME")  # fmt: skip


def _clean_env(**more: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in NAMED and not k.startswith(("COMPOSE_", "TB_MEM_"))}
    env.update(more)
    return env


# ------------------------------------------------------------------------------ the compose files, rendered
def _render(project: Path, files: list[Path], **env: str) -> str:
    (project / ".env").write_text(DUMMY_ENV, encoding="utf-8")
    args = [x for f in files for x in ("-f", str(f))]
    r = subprocess.run(["docker", "compose", "--project-directory", str(project), *args, "--profile", "stub",
                        "--profile", "test", "config", "--format", "json"],
                       capture_output=True, text=True, timeout=120, check=False, env=_clean_env(**env))  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout


def _literal(tmp: Path, name: str) -> Path:
    """The file as master wrote it: the project's variable replaced by its default, trialbox."""
    text = (DEPLOY / name).read_text(encoding="utf-8")
    assert VAR in text
    out = tmp / "literal" / name
    out.parent.mkdir(exist_ok=True)
    out.write_text(text.replace(VAR, "trialbox"), encoding="utf-8")
    return out


@pytest.mark.parametrize("stack", [("docker-compose.yml",), ("docker-compose.yml", "docker-compose.test.yml")])
def test_with_nothing_set_compose_renders_byte_identical_to_the_literal_names(tmp_path: Path,
                                                                              stack: tuple[str, ...]) -> None:  # fmt: skip
    project = tmp_path / "proj"
    project.mkdir()
    now = _render(project, [DEPLOY / f for f in stack])
    literal = _render(project, [_literal(tmp_path, f) for f in stack])
    assert now == literal
    doc = json.loads(now)
    assert doc["name"] == "trialbox"
    names = {n["name"] for n in doc["networks"].values()}
    assert "trialbox-net" in names  # the stub profile's networks: the ones its services use
    assert names <= {"trialbox-net", "trialbox-model-net", "trialbox-model-backend", "trialbox-egress",
                     "trialbox-console", "trialbox-hostnet"}  # fmt: skip
    if "docker-compose.test.yml" in stack:
        assert "trialbox-hostnet" in names


def test_the_projects_variable_names_the_project_and_every_network(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    doc = json.loads(_render(project, [DEPLOY / "docker-compose.yml", DEPLOY / "docker-compose.test.yml"],
                             TB_COMPOSE_PROJECT="m48h-r1"))  # fmt: skip
    assert doc["name"] == "m48h-r1"
    names = sorted(n["name"] for n in doc["networks"].values())
    assert names and all(n.startswith("m48h-r1-") for n in names), names
    assert sorted(v["name"] for v in doc["volumes"].values()) == sorted(f"m48h-r1_{k}" for k in doc["volumes"])


# ------------------------------------------------------------------------------ deploy/poc.sh and the database build
def _poc(tmp: Path, *, build_tools: bool = False, **env: str) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    root = tmp / "root"
    (root / "deploy").mkdir(parents=True)
    (root / "tools").mkdir()
    for rel in ("deploy/poc.sh", "deploy/build_db_image.sh", ".env.example"):
        shutil.copy2(ROOT / rel, root / rel)
    log = tmp / "docker.log"
    (root / "tools" / "fetch_jvm_deps.sh").write_text(f'echo "fetch_jvm_deps" >> "{log}"\n', encoding="utf-8")
    bindir = tmp / "bin"
    bindir.mkdir()
    tools = {"docker": POC_DOCKER, "uname": '#!/bin/sh\n[ "$1" = -m ] && echo x86_64 || /bin/uname "$@"\n'}
    if build_tools:
        tools.update(make=f'#!/bin/sh\necho "make $*" >> "{log}"\n', mvn="#!/bin/sh\nexit 0\n")
        py = root / ".venv/bin/python"
        py.parent.mkdir(parents=True)
        py.write_text(f'#!/bin/sh\necho "python $*" >> "{log}"\n', encoding="utf-8")
        py.chmod(0o755)
    for name, body in tools.items():
        (bindir / name).write_text(body, encoding="utf-8")
        (bindir / name).chmod(0o755)
    full = {k: v for k, v in _clean_env().items() if not k.startswith("TB_") and k != "HTTPS_PROXY"}
    full.update(PATH=f"{bindir}:/usr/bin:/bin", TB_LLM_MODE="stub", TB_TEST_LOG=str(log), TB_POC_SKIP_INGEST="1",
                TB_TEST_ARCH="x86_64", TB_TEST_PRESENT=" ".join(BOX_IMAGES))  # fmt: skip
    full.update(env)
    res = subprocess.run(["bash", str(root / "deploy/poc.sh")], capture_output=True, text=True, env=full, timeout=120,
                         check=False)  # fmt: skip
    return res, log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def _changing(log: list[str]) -> list[str]:
    return [s for s in log if s.startswith(("build ", "tag ", "rmi ", "image rm", "image tag", "make ", "rm "))]


@pytest.mark.parametrize("build_tools", [False, True])
def test_poc_under_an_own_tag_builds_its_own_images_and_never_names_a_box_tag(tmp_path: Path,
                                                                              build_tools: bool) -> None:  # fmt: skip
    res, log = _poc(tmp_path, build_tools=build_tools, **OWN)
    assert res.returncode == 0, res.stdout + res.stderr
    assert _changing(log) == [
        "build -f deploy/docker/python.Dockerfile -t trialbox-py:r1 .",
        "build -f deploy/docker/jvm.Dockerfile --build-arg BASE_IMAGE=trialbox-py:r1 -t trialbox-jvm:r1 .",
        "build -f deploy/docker/db.Dockerfile -t trialbox-postgres:r1 deploy/docker",
    ]
    assert not any(BOX_TAG.search(s) for s in _changing(log))
    assert not any(s.startswith("make ") for s in log)  # `make images` tags the box's names
    assert ("fetch_jvm_deps" in log) is build_tools  # the build inputs on the host when it has the tools
    assert "volume inspect r1_lake-data" in log and "volume inspect trialbox_lake-data" not in log


def test_poc_with_nothing_set_keeps_masters_commands_and_names(tmp_path: Path) -> None:
    res, log = _poc(tmp_path, TB_TEST_PRESENT="")
    assert res.returncode == 0, res.stdout + res.stderr
    assert _changing(log) == [
        "build -f deploy/docker/python.Dockerfile -t trialbox-py:1.0.0 .",
        "build -f deploy/docker/jvm.Dockerfile -t trialbox-jvm:1.0.0 .",
        "build -f deploy/docker/db.Dockerfile -t trialbox-postgres:16-1 deploy/docker",
    ]
    assert "volume inspect trialbox_lake-data" in log


def test_poc_with_nothing_set_and_build_tools_still_runs_make_images(tmp_path: Path) -> None:
    res, log = _poc(tmp_path, build_tools=True, TB_TEST_PRESENT="")
    assert res.returncode == 0, res.stdout + res.stderr
    assert [s for s in _changing(log)] == [f"make images PY={tmp_path}/root/.venv/bin/python"]


# ------------------------------------------------------------------------------ tools/dgpu48.py, tools/measure48-vm.sh
DGPU = ("import json, tools.dgpu48 as d; o = {'serves': ['judge', 'verifier']}; "
        "e = {'env': {}, 'pinned_engine': True, 'image': 'vllm'}; "
        "c = d.plan_commands(o, e, ['deploy/docker-compose.yml'], d.ROOT / 'm'); "
        "print(json.dumps([d.PROJECT, d.BACKEND_NET, d.PY_IMAGE, c['canary']]))")  # fmt: skip


@pytest.mark.parametrize(("env", "names"), [
    ({}, ["trialbox", "trialbox-model-backend", "trialbox-py:1.0.0"]),
    ({"TB_COMPOSE_PROJECT": "r1", "TB_IMAGE": "trialbox-py:r1"}, ["r1", "r1-model-backend", "trialbox-py:r1"]),
])  # fmt: skip
def test_dgpu48_names_follow_the_variables_and_default_to_masters(env: dict[str, str], names: list[str]) -> None:
    r = subprocess.run([sys.executable, "-c", DGPU], capture_output=True, text=True, cwd=ROOT, timeout=60, check=False,
                       env=_clean_env(PYTHONPATH=str(ROOT), **env))  # fmt: skip
    assert r.returncode == 0, r.stderr
    project, net, image, canary = json.loads(r.stdout)
    assert [project, net, image] == names
    assert canary[canary.index("--network") + 1] == names[1] and names[2] in canary


VM_CALLS = r"""
TB_M48_FUNCTIONS_ONLY=1; . "$1/tools/measure48-vm.sh"
SI=""; CK=/ck; STEP_LOG=/dev/null; RUN=/nowhere
tool canary --judge-url x; servers_up; bridge connect; step_screen > /dev/null 2>&1 || true
"""


@pytest.mark.parametrize(("env", "project", "image"), [({}, "trialbox", "trialbox-py:1.0.0"),
                                                      ({"TB_COMPOSE_PROJECT": "r1", "TB_IMAGE": "trialbox-py:r1"},
                                                       "r1", "trialbox-py:r1")])  # fmt: skip
def test_the_vm_scripts_container_network_and_image_names(tmp_path: Path, env: dict[str, str], project: str,
                                                         image: str) -> None:  # fmt: skip
    log = tmp_path / "docker.log"
    (tmp_path / "docker").write_text(f'#!/bin/sh\necho "$*" >> "{log}"\n', encoding="utf-8")
    (tmp_path / "docker").chmod(0o755)
    subprocess.run(["bash", "-c", VM_CALLS, "x", str(ROOT)], capture_output=True, text=True, timeout=60, check=False,
                   env=_clean_env(PATH=f"{tmp_path}:{os.environ['PATH']}", **env))  # fmt: skip
    calls = log.read_text(encoding="utf-8").splitlines()
    assert f"run --rm --network {project}-model-backend -e TB_GPU_KEY -v /ck/tools/canary.py:/app/tools/canary.py:ro " \
           f"{image} python -m tools.canary --judge-url x" in calls  # fmt: skip
    assert f"inspect -f {{{{.State.Running}}}} {project}-llm-service-1" in calls
    assert f"network connect bridge {project}-llm-service-1" in calls
    assert f"network connect bridge {project}-llm-verifier-1" in calls


# ------------------------------------------------------------------------------ tools/measure48-host.sh beside a box
BOX: dict[str, Any] = {"containers": {"trialbox-db-1": {"com.docker.compose.project": "trialbox"},
                      "trialbox-console-1": {"com.docker.compose.project": "trialbox"}},
       "networks": ["trialbox-net", "trialbox-model-backend"], "volumes": ["trialbox_db-pg", "trialbox_lake-data"],
       "images": BOX_IMAGES}  # fmt: skip


class OwnRig(Rig):
    """H-67's rig, its stub and servers following the run's project and tag (as the real stub and dgpu48 now do),
    with an installed box's objects and images on the host."""

    def __init__(self, tmp: Path) -> None:
        super().__init__(tmp)
        si = (self.bin / "standin").read_text()
        si = si.replace("a = sys.argv[1:]\n", 'a = sys.argv[1:]\nP = os.environ["TB_COMPOSE_PROJECT"]\n', 1)
        si = si.replace('"com.docker.compose.project": "trialbox"', '"com.docker.compose.project": P')
        si = si.replace(
            's["images"] += ["trialbox-py:1.0.0"]',
            's["images"] += [os.environ[v] for v in ("TB_IMAGE", "TB_JVM_IMAGE", "TB_DB_IMAGE")]',
        )
        si = re.sub(r'"trialbox([-_])', r'P + "\1', si)
        assert "trialbox-" not in si and "trialbox_" not in si
        (self.bin / "standin").write_text(si)
        dk = (self.bin / "docker").read_text()
        dk = dk.replace(
            'elif a[0] == "pull":',
            'elif a[:2] == ["image", "rm"]:\n'
            '    [s["images"].remove(n) for n in a[2:] if n in s["images"]]\n    save()\nelif a[0] == "pull":',
        )
        (self.bin / "docker").write_text(dk)
        d = self.docker
        self.dock(containers={**d["containers"], **BOX["containers"]}, networks=d["networks"] + BOX["networks"],
                  volumes=d["volumes"] + BOX["volumes"], images=d["images"] + BOX["images"])  # fmt: skip
        (self.co / "deploy").mkdir()
        for f in ("docker-compose.yml", "docker-compose.test.yml", "docker-compose.poc.yml"):
            shutil.copy2(DEPLOY / f, self.co / "deploy" / f)  # untracked: the checkout stays clean

    def calls_of_docker(self) -> list[str]:
        p = self.tmp / "docker.json.calls"
        return p.read_text().splitlines() if p.exists() else []

    def box_intact(self) -> None:
        d = self.docker
        for c, lab in BOX["containers"].items():
            assert d["containers"].get(c) == lab
        assert set(BOX["networks"]) <= set(d["networks"]) and set(BOX["volumes"]) <= set(d["volumes"])
        assert set(BOX_IMAGES) <= set(d["images"])


@pytest.fixture
def own(tmp_path: Path) -> OwnRig:
    return OwnRig(tmp_path)


def test_a_full_run_beside_an_installed_box_uses_and_removes_only_its_own_names(own: OwnRig) -> None:
    r = own.go("run", "--project", "m48h-t1", "--image-tag", "t1tag")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "an installed box's" in r.stdout and "never builds over, tags, stops or removes them" in r.stdout
    own.box_intact()
    d = own.docker
    assert not [c for c in d["containers"] if c.startswith("m48h-t1")] and not any("t1tag" in i for i in d["images"])
    assert not [n for n in d["networks"] + d["volumes"] if n.startswith("m48h-t1")]
    changing = [c for c in own.calls_of_docker() if c.startswith(("rm ", "network rm", "volume rm", "image rm",
                                                                    "tag ", "build ", "rmi "))]  # fmt: skip
    assert changing and not any(BOX_TAG.search(c) for c in changing), changing
    assert not any(re.search(r"\btrialbox[-_]", c) for c in changing if not c.startswith("image rm")), changing
    assert {"image rm trialbox-py:t1tag", "image rm trialbox-jvm:t1tag", "image rm trialbox-postgres:t1tag"} <= set(
        changing
    )
    objs = json.loads((own.out / "records" / "docker-objects.json").read_text())
    assert objs["project"] == "m48h-t1" and objs["image_tag"] == "t1tag" and objs["left"] == []
    made = {o["name"] for o in objs["objects"]}
    assert {"m48h-t1-net", "m48h-t1_db", "m48h-t1-llm-service-1", "trialbox-py:t1tag", "tb-ballast-t1"} <= made
    assert not any(n.startswith(("trialbox-net", "trialbox_", "trialbox-db")) or BOX_TAG.search(n) for n in made)
    head = json.loads((own.out / "records" / "head.json").read_text())
    assert head["project"] == "m48h-t1" and head["image_tag"] == "t1tag"
    own.assert_nothing_forbidden_and_others_untouched()


def test_the_default_project_and_tag_come_from_the_run_id_never_trialbox(own: OwnRig) -> None:
    r = own.go("preflight")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "compose project t1, t1-* networks, t1_* volumes" in r.stdout
    assert "trialbox-py:t1 trialbox-jvm:t1 trialbox-postgres:t1" in r.stdout
    args = [a for a in own.args("preflight") if a not in ("--run-id", "t1")]
    r = subprocess.run([*args, "--run-id", "Trialbox.X"], env=own.env(), capture_output=True, text=True, timeout=240,
                       check=False)  # fmt: skip
    assert r.returncode == 0, r.stdout + r.stderr
    assert "compose project m48h-trialbox-x," in r.stdout


@pytest.mark.parametrize(("more", "words"), [
    (("--project", "trialbox"), "--project trialbox is refused: trialbox is the installed box's project"),
    (("--project", "trialbox-x"), "--project trialbox-x is refused"),
    (("--project", "Bad.Name"), "--project Bad.Name: lower-case letters"),
    (("--image-tag", "1.0.0"), "--image-tag 1.0.0 is refused: it is a tag of the installed box's images"),
    (("--image-tag", "16-1"), "--image-tag 16-1 is refused"),
])  # fmt: skip
def test_the_boxs_project_or_tag_is_refused_in_one_line(own: OwnRig, more: tuple[str, str], words: str) -> None:
    r = own.go("run", *more)
    assert r.returncode == 2 and words in r.stderr
    assert [x for x in r.stderr.splitlines() if x.startswith("measure48-host:")] == [f"measure48-host: {words}"
                                                                                       + r.stderr.split(words, 1)[1]
                                                                                       .splitlines()[0]]  # fmt: skip
    assert not own.run_dir.exists() and own.calls_of_docker() == []
    own.box_intact()


@pytest.mark.parametrize(("setup", "words"), [
    ({"volumes": ["t1_db-pg"]}, "1 Docker object(s) of the run's names already (1 volume)"),
    ({"networks": ["t1-net"]}, "1 Docker object(s) of the run's names already (1 network)"),
    ({"containers": {"t1-db-1": {"com.docker.compose.project": "t1"}}}, "of the run's names already (1 container)"),
    ({"images": ["trialbox-jvm:t1"]}, "1 image(s) of the run's tag already (trialbox-jvm:t1)"),
])  # fmt: skip
def test_the_runs_own_project_or_tag_present_already_refuses(own: OwnRig, setup: dict[str, object],
                                                            words: str) -> None:  # fmt: skip
    d = own.docker
    merged = {k: (d[k] | v if isinstance(v, dict) else d[k] + v) for k, v in setup.items()}
    own.dock(**merged)
    before = own.docker
    r = own.go("run")
    assert r.returncode == 2 and words in r.stdout, r.stdout
    assert own.docker == before and not own.run_dir.exists()


def test_a_stub_port_in_use_refuses_and_names_its_variable(own: OwnRig) -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        r = own.go("preflight", TB_HOST_CONSOLE_PORT=str(port))
    assert r.returncode == 2
    assert f"publishes host ports that answer already: TB_HOST_CONSOLE_PORT {port} (on 127.0.0.1" in r.stdout


def test_the_usage_names_the_options() -> None:
    r = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, timeout=60, check=False)
    assert r.returncode == 2 and "[--run-id ID] [--project NAME] [--image-tag TAG]" in r.stderr
