"""H-106 (the owner's ruling, relayed as 7117794599 and 7117870645): the multi-box test mode.

THE INVARIANT: :func:`test_two_test_boxes_share_no_volume_network_port_or_key`. Two test boxes installed by the REAL
``deploy/install.sh`` (H-94's bench: stand-ins for the engine) side by side: every compose and docker command of each
install ran under its own project, and the volumes, networks, published ports and secrets volume the compose files
give each project never meet. The engine itself is inspected on the real path by the rehearsal's ``test-boxes`` step
(tools/rehearse_box/box.sh).

PRODUCTION: :func:`test_production_refuses_the_option_and_a_host_with_a_test_box` (and its twin with every variable a
caller could plant).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest
import yaml

from tests.unit.test_poc_stops_bench_h94 import Box, Run
from tools.trialbox import doctor, launch, testbox

pytestmark = [pytest.mark.nodb, pytest.mark.skipif(sys.platform != "linux", reason="bash and GNU tools")]
ROOT = Path(__file__).resolve().parents[2]

#: the engine as the boxes on a host show it, read by tools/trialbox/testbox.py; every compose call logged with the
#: project it ran under (COMPOSE_PROJECT_NAME), then handed to H-94's stand-in
WRAP = r"""#!/bin/sh
echo "project=${COMPOSE_PROJECT_NAME:-<none>} $*" >> "$TB_H106_LOG"
case "$*" in
  "volume ls --filter label=com.docker.compose.volume=tb-secrets --format "*)
    [ -f "$TB_H106_ENGINE" ] && sed -n 's/^volume //p' "$TB_H106_ENGINE"; exit 0 ;;
  "ps -a --filter label=com.docker.compose.project="*" --format "*)
    p="${4#label=com.docker.compose.project=}"
    [ -f "$TB_H106_ENGINE" ] && sed -n "s/^dir $p //p" "$TB_H106_ENGINE"; exit 0 ;;
esac
exec "$(dirname "$0")/docker.h94" "$@"
"""


class H106Box(Box):
    """H-94's bench with the engine of a host that may hold other boxes (``engine``: lines ``volume PROJECT`` and
    ``dir PROJECT FOLDER``)."""

    def __post_init__(self) -> None:
        super().__post_init__()
        b = self.tmp / "bin"
        (b / "docker").rename(b / "docker.h94")
        (b / "docker").write_text(WRAP, encoding="utf-8")
        (b / "docker").chmod(0o755)

    def run(self, *args: str, engine: str = "", env: dict[str, str] | None = None) -> Run:
        e = self.tmp / "engine.txt"
        e.write_text(engine, encoding="utf-8")
        return self.install(*args, env={"TB_H106_LOG": str(self.tmp / "h106.log"), "TB_H106_ENGINE": str(e),
                                        **(env or {})})  # fmt: skip

    def calls(self) -> list[str]:
        return (self.tmp / "h106.log").read_text(encoding="utf-8").splitlines()

    def dotenv(self) -> dict[str, str]:
        return testbox.read_env(self.deploy / ".env")


TEST_ARGS = ("--mode", "stub", "--yes")
PLANTED = {"TB_ENV": "TEST", "TB_TEST_BOX": "x", "COMPOSE_PROJECT_NAME": "tbt-x-000000", "TB_STOP_ARG_ENV": "TEST",
           "TEST_BOX": "x", "TB_STOP_REHEARSAL": "1", "TB_REHEARSAL": "1"}  # fmt: skip


def _compose_names(project: str) -> tuple[set[str], set[str]]:
    """The volumes and networks deploy/docker-compose.yml gives a project (compose's own naming)."""
    doc = yaml.safe_load((ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8"))
    vols = {f"{project}_{v}" for v in doc["volumes"]}
    nets = {str(n["name"]).replace("${COMPOSE_PROJECT_NAME:-trialbox}", project) for n in doc["networks"].values()}
    return vols, nets


def _published(env: dict[str, str]) -> set[int]:
    """The host ports a box publishes: each published port's variable in the compose files an install runs (the base,
    the TLS proxy, the monitoring and the PoC overlays; not the developers' test stacks), as the box's .env sets it."""
    out = set()
    for name in ("docker-compose.yml", "docker-compose.identity.yml", "docker-compose.monitoring.yml",
                 "docker-compose.poc.yml"):  # fmt: skip
        f = ROOT / "deploy" / name
        for var, default in re.findall(r"\$\{(TB_[A-Z_]*PORT):-(\d+)\}:\d+", f.read_text(encoding="utf-8")):
            out.add(int(env.get(var) or default))
    return out


# ------------------------------------------------------------------------------------------------ the invariant
def test_two_test_boxes_share_no_volume_network_port_or_key(tmp_path: Path) -> None:
    """Two test boxes, each by the real installer: each install's every compose and docker command ran under its own
    project (none under the other's or the ordinary box's), and the projects' volumes (the site keys' tb-secrets
    among them), networks and published ports never meet. Each says what it is in its last lines."""
    a, b = H106Box(tmp_path / "a"), H106Box(tmp_path / "b")
    ra = a.run("--test-box", "a", "--port-offset", "1", *TEST_ARGS)
    assert ra.rc == 0 and "TrialBox is running." in ra.out, ra.text[-4000:]
    pa = a.dotenv()["COMPOSE_PROJECT_NAME"]
    rb = b.run("--test-box", "b", "--port-offset", "2", *TEST_ARGS,
               engine=f"volume {pa}\ndir {pa} {a.deploy}\n")  # fmt: skip
    assert rb.rc == 0 and "TrialBox is running." in rb.out, rb.text[-4000:]
    pb = b.dotenv()["COMPOSE_PROJECT_NAME"]
    assert re.fullmatch(r"tbt-a-[0-9a-f]{6}", pa) and re.fullmatch(r"tbt-b-[0-9a-f]{6}", pb)
    for box, own, other in ((a, pa, pb), (b, pb, pa)):
        engine = [
            c
            for c in box.calls()
            if (" compose " in f" {c} " or c.split(" ", 2)[1] in ("run", "volume"))
            and not c.endswith(" compose version")
        ]  # the engine's version: asked before the box is known
        assert engine and all(c.startswith(f"project={own} ") for c in engine), [c for c in engine if own not in c]
        listing = f"label=com.docker.compose.project={other} "  # asking the engine which boxes are there
        assert not any(
            (other in c and listing not in c) or "trialbox_" in c or "trialbox-net" in c for c in box.calls()
        )
        assert (
            f"TEST BOX {box.dotenv()['TB_TEST_BOX']}: one of several boxes on this host" in (ra if box is a else rb).out
        )
    (va, na), (vb, nb) = _compose_names(pa), _compose_names(pb)
    assert not va & vb and not na & nb and f"{pa}_tb-secrets" in va and f"{pb}_tb-secrets" in vb
    assert not va & _compose_names("trialbox")[0] and not na & _compose_names("trialbox")[1]
    ports_a, ports_b, first = _published(a.dotenv()), _published(b.dotenv()), _published({})
    assert not ports_a & ports_b and not ports_a & first and not ports_b & first, (ports_a, ports_b)
    # the keys: each box's deploy/secrets is its own folder, and no secret of a test box goes to the host's KEK folder
    assert (a.deploy / "secrets").resolve() != (b.deploy / "secrets").resolve()
    for box in (a, b):
        assert "seal_keys" not in (box.tmp / "calls.log").read_text(encoding="utf-8")


def test_the_project_follows_the_folder_never_a_variable(tmp_path: Path) -> None:
    """Two folders with the same box name get two projects; a caller's COMPOSE_PROJECT_NAME, TB_TEST_BOX or TB_ENV
    changes nothing; a re-run without the option is the same box, from its record."""
    a1, a2 = H106Box(tmp_path / "one"), H106Box(tmp_path / "two")
    assert a1.run("--test-box", "same", "--port-offset", "1", *TEST_ARGS).rc == 0
    r = a2.run("--test-box", "same", "--port-offset", "2", *TEST_ARGS, env=PLANTED)
    assert r.rc == 0, r.text[-3000:]
    assert a1.dotenv()["COMPOSE_PROJECT_NAME"] != a2.dotenv()["COMPOSE_PROJECT_NAME"]
    assert a2.dotenv()["COMPOSE_PROJECT_NAME"] == testbox.project_for("same", a2.tmp)
    again = a2.run(*TEST_ARGS)  # no option: the folder's own record speaks
    assert again.rc == 0 and a2.dotenv()["TB_TEST_BOX"] == "same", again.text[-3000:]
    assert all(c.startswith(f"project={testbox.project_for('same', a2.tmp)} ") for c in a2.calls()
               if " compose " in c and not c.endswith(" compose version"))  # fmt: skip


# ------------------------------------------------------------------------------------------------ PRODUCTION
@pytest.mark.parametrize("planted", [False, True], ids=["clean", "planted"])
def test_production_refuses_the_option_and_a_host_with_a_test_box(tmp_path: Path, planted: bool) -> None:
    """A PRODUCTION install refuses --test-box, and refuses a host where a test box runs, before anything is loaded,
    whatever a caller plants; with no test box on the host it goes on as before (its words unchanged)."""
    env = PLANTED if planted else {}
    p = H106Box(tmp_path / "prod", env="TB_ENV=PRODUCTION\n")
    r = p.run("--environment", "PRODUCTION", "--test-box", "x", "--port-offset", "1", *TEST_ARGS, env=env)
    assert r.rc == 1 and r.err.splitlines()[-1] == ("install: --test-box makes a TEST box, not PRODUCTION: a test box "
                                                    "never holds a site's data and never becomes PRODUCTION (nothing "
                                                    "was changed)"), r.text[-2000:]  # fmt: skip
    assert not (p.deploy / "site" / "test-box.env").exists() and not (p.tmp / "current").exists()
    t = tmp_path / "t" / "deploy"
    (t / "site").mkdir(parents=True)
    testbox.record(t, "walk", "1")
    proj = testbox.project_for("walk", t.parent)
    r = p.run("--environment", "PRODUCTION", *TEST_ARGS, engine=f"volume trialbox\nvolume {proj}\ndir {proj} {t}\n",
              env=env)  # fmt: skip
    assert r.rc == 1 and r.err.splitlines()[-1] == (
        f"install: this host runs test boxes ({proj}): a PRODUCTION box is installed on a host of its own; remove "
        "them first (tools/testboxes.sh remove NAME); nothing was changed"), r.text[-2000:]  # fmt: skip
    assert not (p.tmp / "current").exists() and "load " not in (p.tmp / "calls.log").read_text(encoding="utf-8")


def test_a_test_box_never_goes_beside_a_production_box_nor_becomes_one(tmp_path: Path) -> None:
    """A test box refuses a host with a PRODUCTION box (or one whose folder cannot be found: it cannot be told), and
    a folder installed as no test box is never made one; --environment VALIDATION or PRODUCTION is refused."""
    prod = tmp_path / "site-box" / "deploy"
    prod.mkdir(parents=True)
    (prod / ".env").write_text("TB_ENV=PRODUCTION\n", encoding="utf-8")
    t = H106Box(tmp_path / "t")
    for engine in (f"volume trialbox\ndir trialbox {prod}\n", "volume trialbox\n"):
        r = t.run("--test-box", "t", "--port-offset", "1", *TEST_ARGS, engine=engine)
        assert r.rc == 1 and "this host holds a PRODUCTION box (project trialbox)" in r.err, r.text[-2000:]
        assert not (t.tmp / "current").exists()
    walk = tmp_path / "walk" / "deploy"
    walk.mkdir(parents=True)
    (walk / ".env").write_text("TB_ENV=TEST\n", encoding="utf-8")
    r = t.run("--test-box", "t", "--port-offset", "1", *TEST_ARGS, engine=f"volume trialbox\ndir trialbox {walk}\n")
    assert r.rc == 0, r.text[-3000:]  # beside a PoC box (the walk box): allowed
    for environment in ("VALIDATION", "PRODUCTION"):
        r = H106Box(tmp_path / environment).run("--test-box", "v", "--port-offset", "1", "--environment", environment,
                                               *TEST_ARGS)  # fmt: skip
        assert r.rc == 1 and f"--test-box makes a TEST box, not {environment}" in r.err
    old = H106Box(tmp_path / "old", prewritten_env="TB_ENV=TEST\n")
    r = old.run("--test-box", "o", "--port-offset", "1", *TEST_ARGS)
    assert r.rc == 1 and "this folder holds a box installed as no test box" in r.err


@pytest.mark.parametrize("case", ["secrets-dir", "kek-backend", "hardening"])
def test_a_test_box_s_secret_never_goes_where_another_box_s_could(tmp_path: Path, case: str) -> None:
    """H-94 (5) on a PoC box too: a secrets folder a caller names, or the host's KEK folder, is refused."""
    t = H106Box(tmp_path / case)
    env = {
        "secrets-dir": {"TB_SECRETS_HOST_DIR": str(tmp_path / "shared")},
        "kek-backend": {"TB_KEK_BACKEND": "passphrase"},
    }
    if case == "hardening":
        (t.deploy / "site" / "hardening.conf").write_text("KEK_BACKEND=tpm\n", encoding="utf-8")
    r = t.run("--test-box", "k", "--port-offset", "1", *TEST_ARGS, env=env.get(case, {}))
    assert r.rc == 1 and "PoC box, H-94" not in r.err.splitlines()[-1], r.text[-2000:]
    assert (
        "TB_SECRETS_HOST_DIR is set" if case == "secrets-dir" else "a test box's site keys are never sealed"
    ) in r.err
    assert not (t.tmp / "current").exists()


def test_the_option_s_values_without_the_option_are_refused_by_name(tmp_path: Path) -> None:
    r = H106Box(tmp_path / "u").run("--environment", "TEST", "--port-offset", "1", *TEST_ARGS)
    assert (
        r.rc == 1
        and r.err.splitlines()[-1] == "install: --port-offset, --gpus and --gpu-mem-gb go with --test-box NAME"
    )
    r = H106Box(tmp_path / "r").run("--test-box", "r", "--port-offset", "1", "--rehearsal", *TEST_ARGS)
    assert r.rc == 1 and "a test box is no rehearsal box" in r.err


def test_no_host_level_file_of_the_ordinary_box_is_a_test_box_s(tmp_path: Path) -> None:
    """The host's trialbox command, units, cron files, logrotate, egress table and the first sign-in file: a test
    box writes none of them (H-106's list on the card page); its first sign-in file is its own name's."""
    text = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    assert 'if [ "$(id -u)" = 0 ] && [ -z "${TEST_BOX:-}" ]; then\n  install -d /usr/local/bin' in text
    assert 'CAN_CRON=0; [ -z "${TEST_BOX:-}" ] && {' in text and "TB_SYSTEMD=0; export TB_SYSTEMD" in text
    assert '[ -d /etc/logrotate.d ] && [ -z "${TEST_BOX:-}" ]' in text
    assert "trialbox-admin-first-sign-in${TEST_BOX:+-$TEST_BOX}" in text
    t = H106Box(tmp_path / "h")
    r = t.run("--test-box", "h", "--port-offset", "1", *TEST_ARGS)
    assert r.rc == 0 and not list((t.tmp / "cron").iterdir()), r.text[-2000:]
    assert "test box: no backup schedule, no log retention cron" in r.out


# ------------------------------------------------------------------------------------------------ the helper
def test_record_ports_and_cards(tmp_path: Path) -> None:
    d = tmp_path / "x" / "deploy"
    (d / "site").mkdir(parents=True)
    box = testbox.record(d, "p32", "2", "1", "32")
    assert box.project == testbox.project_for("p32", d.parent) and testbox.load(d) == box
    assert testbox.ports(2) == {"TB_HOST_CONSOLE_PORT": 8110, "TB_TLS_PORT": 8463, "TB_PROMETHEUS_PORT": 9110}
    with pytest.raises(testbox.Refused, match="a box keeps its name"):
        testbox.record(d, "other", "2")
    for bad in (("0", "", ""), ("50", "", ""), ("1", "1,1", ""), ("1", "", "32"), ("1", "a", ""), ("1", "1", "0")):
        with pytest.raises(testbox.Refused):
            testbox.check_values(*bad)
    # a record copied to another folder is not that folder's
    other = tmp_path / "y" / "deploy"
    (other / "site").mkdir(parents=True)
    (other / testbox.RECORD).write_text((d / testbox.RECORD).read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(testbox.Refused, match="never copied between folders"):
        testbox.load(other)


def test_the_cards_override_names_every_server_that_reserves_a_card(tmp_path: Path) -> None:
    d = tmp_path / "x" / "deploy"
    (d / "site").mkdir(parents=True)
    testbox.record(d, "g", "1", "2,3")
    files = [ROOT / "deploy" / "docker-compose.yml", ROOT / "deploy" / "docker-compose.rtxpro6000.yml"]
    path = testbox.override(d, files)
    assert path is not None
    doc = yaml.safe_load(path.read_text(encoding="utf-8").replace("!override ", ""))
    want = set(testbox.gpu_services(files))
    assert want and set(doc["services"]) == want
    for spec in doc["services"].values():
        assert spec["deploy"]["resources"]["reservations"]["devices"][0]["device_ids"] == ["2", "3"]
    # the TLS proxy publishes the box's own port (the identity file's 443 is the ordinary box's)
    tls = testbox.override(d, [*files, ROOT / "deploy" / "docker-compose.identity.yml"])
    assert tls is not None and '  caddy:\n    ports: !override ["${TB_TLS_BIND:-0.0.0.0}:8453:443"]' in tls.read_text()
    testbox.record(d, "g", "1")  # no cards, no TLS: no file
    assert testbox.override(d, files) is None and not path.exists()


def test_the_cap_scales_each_utilisation_to_the_cap_s_share(tmp_path: Path) -> None:
    """What enforces the cap is the serving engine's utilisation (not the container engine): a 32 GB cap on a card of
    183,359 MiB gives each server the share of 32,768 MiB its profile asks for."""
    d = tmp_path / "x" / "deploy"
    (d / "site").mkdir(parents=True)
    for f in ("docker-compose.yml", "docker-compose.rtx5090.yml"):
        (d / f).write_text((ROOT / "deploy" / f).read_text(encoding="utf-8"), encoding="utf-8")
    box = testbox.record(d, "p", "1", "4", "32")

    def smi(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        assert argv[:3] == ["nvidia-smi", "-i", "4"]
        return subprocess.CompletedProcess(argv, 0, "183359\n", "")

    caps = testbox.capped(d, box, "rtx5090", smi)
    base = testbox.utils(d, "rtx5090")
    assert caps and set(caps) == set(base)
    for k, u in base.items():
        assert caps[k] <= u * 32768 / 183359 and caps[k] > u * 32768 / 183359 - 0.002

    def small(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, "30000\n", "")

    with pytest.raises(testbox.Refused, match="has 30000 MiB"):
        testbox.capped(d, box, "rtx5090", small)
    lines = testbox.env_lines(d, "rtx5090", smi)
    assert "TB_HOST_CONSOLE_PORT=8100" in lines and f"COMPOSE_PROJECT_NAME={box.project}" in lines


class Engine:
    """A container engine with boxes in it: projects, their folders, their objects; it records what is removed."""

    def __init__(self, boxes: dict[str, str]) -> None:
        self.boxes = boxes  # project -> folder ("" when no container says)
        self.objects = {
            p: {"container": [f"{p}-c"], "network": [f"{p}-n"], "volume": [f"{p}_tb-secrets"]} for p in boxes
        }
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        a = list(argv[1:])
        out = ""
        if a[:2] == ["volume", "ls"] and "label=com.docker.compose.volume=tb-secrets" in a:
            out = "\n".join(self.boxes)
        elif a[:2] == ["ps", "-a"] and "--format" in a:
            p = a[a.index("--filter") + 1].split("=", 2)[2]
            out = f"{self.boxes[p]}/deploy" if self.boxes.get(p) else ""
        elif "-q" in a or "-aq" in a:
            p = a[a.index("--filter") + 1].split("=", 2)[2]
            kind = {"ps": "container", "network": "network", "volume": "volume"}[a[0]]
            out = "\n".join(self.objects.get(p, {}).get(kind, []))
        elif a[:1] == ["rm"] or a[1:2] == ["rm"]:
            kind = "container" if a[0] == "rm" else a[0]
            for objs in self.objects.values():
                objs[kind] = [x for x in objs[kind] if x not in a]
        return subprocess.CompletedProcess(argv, 0, out + "\n", "")


def test_remove_takes_one_test_box_whole_and_never_another(tmp_path: Path) -> None:
    roots = {}
    for name in ("a", "b"):
        d = tmp_path / name / "deploy"
        (d / "site").mkdir(parents=True)
        roots[testbox.record(d, name, "1" if name == "a" else "2").project] = str(d.parent)
    prod = tmp_path / "prod" / "deploy"
    prod.mkdir(parents=True)
    (prod / ".env").write_text("TB_ENV=PRODUCTION\n", encoding="utf-8")
    eng = Engine({**roots, "trialbox": str(prod.parent)})
    kinds = {s.project: s.kind for s in testbox.boxes(eng)}
    assert kinds == {**dict.fromkeys(roots, "test"), "trialbox": "production"}
    with pytest.raises(testbox.Refused):
        testbox.remove("trialbox", eng, yes=True)
    pa = next(p for p, r in roots.items() if r.endswith("/a"))
    assert testbox.remove("a", eng, yes=False, say=lambda s: None) == 0 and (tmp_path / "a").exists()
    assert testbox.remove("a", eng, yes=True, say=lambda s: None) == 0
    assert not (tmp_path / "a").exists() and (tmp_path / "b").exists() and prod.exists()
    removed = [c for c in eng.calls if "rm" in c[1:3] or "down" in c]
    assert removed and all(pa in " ".join(c) for c in removed), removed
    others = {p: o for p, o in eng.objects.items() if p != pa}
    assert all(all(v for v in o.values()) for o in others.values())  # every other box's objects are there
    assert all(not v for v in eng.objects[pa].values())


# ------------------------------------------------------------------------------------------------ the commands
def test_trialbox_names_its_box_when_there_are_several(tmp_path: Path) -> None:
    def two() -> list[tuple[str, str]]:
        return [("walk", str(tmp_path / "w")), ("trialbox", "/opt/trialbox")]

    root, _, refused = launch.pick_box(["doctor"], True, two)
    assert root is None and "this host has 2 boxes (trialbox, walk): name one" in refused
    assert launch.pick_box(["doctor"], False, two) == (None, ["doctor"], "")  # the folder's own module form
    assert launch.pick_box(["--box", "walk", "doctor"], True, two) == (tmp_path / "w", ["doctor"], "")
    assert "no single box" in launch.pick_box(["--box", "nope", "doctor"], True, two)[2]

    def one() -> list[tuple[str, str]]:
        return [("trialbox", "/opt/trialbox")]

    assert launch.pick_box(["doctor"], True, one) == (None, ["doctor"], "")

    def down() -> list[tuple[str, str]]:
        raise testbox.NoEngine("no engine")

    assert launch.pick_box(["doctor"], True, down) == (None, ["doctor"], "")
    assert "cannot be listed" in launch.pick_box(["--box", "walk", "doctor"], True, down)[2]


def test_a_test_box_s_commands_use_its_own_network_and_never_the_ordinary_box_s_backup(tmp_path: Path) -> None:
    need = launch.COMMANDS["backup"]
    argv = launch.container_argv(["backup", "--to", str(tmp_path)], need, {"COMPOSE_PROJECT_NAME": "tbt-a-abcdef"},
                                 tmp_path, 1, 1)  # fmt: skip
    assert argv[argv.index("--network") + 1] == "tbt-a-abcdef-net"
    argv = launch.container_argv(["backup", "--to", str(tmp_path)], need, {}, tmp_path, 1, 1)
    assert argv[argv.index("--network") + 1] == "trialbox-net"  # the ordinary box: as before
    assert {"backup", "restore", "logs", "backup-install"} <= launch.TEST_BOX_REFUSED
    script = f"""
import sys
from pathlib import Path
from tools.trialbox import launch
launch.DEPLOY = Path({str(tmp_path / "deploy")!r})
launch.pick_box = lambda a, i: (None, list(a), "")
sys.exit(launch.enter(["backup", "--to", "/x"], {{}}) or 0)
"""
    d = tmp_path / "deploy"
    d.mkdir()
    (d / ".env").write_text("TB_ENV=TEST\nTB_TEST_BOX=a\n", encoding="utf-8")
    (d / ".env").chmod(0o600)
    r = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, check=False,
                       env={**os.environ, "PYTHONPATH": f"{ROOT}:{ROOT / 'libs'}"})  # fmt: skip
    assert r.returncode == 2 and "refused: backup on test box a (H-106)" in r.stderr, r.stderr


def test_doctor_and_the_console_say_test_box(tmp_path: Path) -> None:
    d = tmp_path / "x" / "deploy"
    (d / "site").mkdir(parents=True)
    box = testbox.record(d, "p48", "3", "2", "48")
    env = {"TB_ENV": "TEST", "TB_TEST_BOX": "p48", "COMPOSE_PROJECT_NAME": box.project}
    c = doctor.check_test_box(doctor.DoctorInputs(deploy=d, env=env))
    assert c.status == "WARN" and c.detail.startswith("TEST BOX p48: one of several boxes on this host")
    assert "cards 2, capped to 48 GB a card" in c.detail and "console port 8120" in c.detail
    for bad in (
        {**env, "COMPOSE_PROJECT_NAME": "trialbox"},
        {**env, "TB_ENV": "PRODUCTION"},
        {**env, "TB_TEST_BOX": ""},
    ):
        assert doctor.check_test_box(doctor.DoctorInputs(deploy=d, env=bad)).status == "FAIL"
    plain = tmp_path / "plain" / "deploy"
    plain.mkdir(parents=True)
    assert doctor.check_test_box(doctor.DoctorInputs(deploy=plain, env={})).status == "PASS"
    assert doctor.check_test_box(doctor.DoctorInputs(deploy=plain, env={"TB_TEST_BOX": "x"})).status == "FAIL"
    sys.path.insert(0, str(ROOT / "services"))
    from console.app import environment_banner

    assert environment_banner({"TB_ENV": "TEST", "TB_TEST_BOX": "p48"}).startswith("TEST TEST BOX p48: one of several")
    assert environment_banner({"TB_ENV": "PRODUCTION", "TB_TEST_BOX": "p48"}) == "PRODUCTION"
    base = (ROOT / "services" / "console" / "templates" / "base.html").read_text(encoding="utf-8")
    assert "'TEST BOX' in settings.environment_label" in base


def test_the_findings_file_is_in_the_register_s_form() -> None:
    page = ROOT / "docs" / "handover" / "test-boxes-h106-2026-11-24.md"
    data = json.loads((page.with_suffix("") / "findings.json").read_text(encoding="utf-8"))
    assert data["card"] == "H106" and data["source"] == f"docs/handover/{page.name}"
    assert all(r["id"].startswith("H106-") and r["basis"] in ("shown", "hypothesis", "not_run", "not stated")
               for r in data["findings"])  # fmt: skip


def test_an_update_of_a_test_box_never_takes_a_secrets_folder_a_caller_names(tmp_path: Path) -> None:
    """tools/apply_update.sh on a test box: TB_SECRETS_HOST_DIR is refused (H-94 (5)); its keys are its own
    project's volume (the record's, never the ordinary box's)."""
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "apply_update.sh").write_bytes((ROOT / "tools" / "apply_update.sh").read_bytes())
    d = tmp_path / "deploy"
    (d / "site").mkdir(parents=True)
    testbox.record(d, "u", "1")
    (tmp_path / "b.tar").write_bytes(b"stand-in\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TB_", "COMPOSE_"))}
    r = subprocess.run(["sh", str(tmp_path / "tools" / "apply_update.sh"), str(tmp_path / "b.tar")], cwd=tmp_path,
                       env={**env, "TB_SECRETS_HOST_DIR": str(tmp_path / "shared")}, capture_output=True, text=True,
                       timeout=60, check=False)  # fmt: skip
    assert r.returncode == 1 and r.stderr.startswith("update REFUSED: TB_SECRETS_HOST_DIR is set on a test box"), (
        r.stderr
    )
    text = (ROOT / "tools" / "apply_update.sh").read_text(encoding="utf-8")
    assert "SECRETS=${TB_SECRETS_HOST_DIR:-/var/lib/docker/volumes/${OWN_PROJECT:-trialbox}_tb-secrets/_data}" in text


def test_the_key_tool_s_folders_are_the_test_box_s_own(tmp_path: Path) -> None:
    """The KEK rotation's journal and lock live in the secrets folder: tools/keys.py's default is the box's own."""
    from tools import keys

    root = tmp_path / "box"
    (root / "tools").mkdir(parents=True)
    (root / "tools" / "keys.py").write_bytes((ROOT / "tools" / "keys.py").read_bytes())
    d = root / "deploy"
    (d / "site").mkdir(parents=True)
    box = testbox.record(d, "k", "1")
    script = "import sys; sys.path[:0] = [sys.argv[1], sys.argv[2]]; import keys; print(keys.secrets_dir(None, {}))"
    r = subprocess.run([sys.executable, "-c", script, str(root / "tools"), str(ROOT / "libs")], capture_output=True,
                       text=True, check=False)  # fmt: skip
    assert r.stdout.strip() == f"/var/lib/docker/volumes/{box.project}_tb-secrets/_data", r.stderr
    assert keys.secrets_dir(None, {}) == Path(keys.HOST_SECRETS)  # the ordinary box: as before


def test_the_first_load_of_a_test_box_reads_it_as_test_before_deploy_env_says(tmp_path: Path) -> None:
    """Found by the rehearsal's test-boxes step: the bundle loads before deploy/.env exists, and the update path read
    a fresh test box as PRODUCTION (and refused the rehearsal bundle). Its record says TEST, as the rehearsal mark
    does; deploy/.env wins once written, and a folder with neither is PRODUCTION as before."""
    from tools.trialbox import update

    d = tmp_path / "deploy"
    (d / "site").mkdir(parents=True)
    box = update.ComposeBox(d)
    assert box.environment() == "PRODUCTION"
    testbox.record(d, "f", "1")
    assert box.environment() == "TEST"
    (d / ".env").write_text("TB_ENV=PRODUCTION\n", encoding="utf-8")
    assert box.environment() == "PRODUCTION"
