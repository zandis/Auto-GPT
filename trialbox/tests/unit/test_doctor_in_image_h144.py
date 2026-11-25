"""H-144 (High, ring 0; the integrator's 7159322336 and ruling 7159506328): ``trialbox doctor`` on a host's own Python.

The walk's box, updated to c3a5b2b2: the installed doctor ran 41 checks and 17 FAILed. 16 were import errors on the
host's Python (no pydantic, no httpx, ``services/`` not on the path), four of them also for want of
``models/routing.yaml`` and ``models/registry.yaml``, which the signed host tree does not carry. And the install folder
still held a ``services/`` from before the signed host tree, which no update replaces or checks.

The ruling: those checks run in the box image (``doctor.IMAGE_CHECKS``, ``tools/trialbox/doctor_image.py``); an import
error or a container that does not run is a FAIL with its reason, never a PASS or a skip; a loose ``services/`` or
``models/`` is named (``release_tree``; the update names it too), never removed and never imported.

Each case runs the real installed wrapper of a box made from this repository's own host tree
(``tools/host_tree.py`` pack and install, as an update leaves it) on an interpreter where pydantic, httpx and every
package of ``services/`` cannot be imported: the host's own Python. The container engine is a stand-in that runs
``python -m tools.trialbox`` from this checkout as the box image would (``/app``: the code, ``models/`` and the
libraries), with the mounts it was given. Settings and records are synthetic.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tools import host_tree as ht
from tools.trialbox import doctor, doctor_image, launch
from tools.trialbox import update as up

ROOT = Path(__file__).resolve().parents[2]
SERVICES = sorted(p.name for p in (ROOT / "services").iterdir() if p.is_dir() and not p.name.startswith((".", "_")))
NOT_ON_THE_HOST = ("pydantic", "httpx")
IMPORT_ERROR = re.compile(r"No module named|ModuleNotFoundError|ImportError")

# the host's own Python: these cannot be imported in this process (a finder ahead of every other one)
BARE = r"""
import importlib.abc, runpy, sys
BLOCKED = set(sys.argv[1].split(","))
class Bare(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCKED:
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)
        return None
sys.meta_path.insert(0, Bare())
form, target = sys.argv[2], sys.argv[3]
sys.argv = [target, *sys.argv[4:]]
if form == "file":
    runpy.run_path(target, run_name="__main__")
else:
    runpy.run_module(target, run_name="__main__", alter_sys=True)
"""

# the engine: `run` plays the box image (this checkout at /app); the rest answers as a box with nothing running does
ENGINE = r"""#!PYTHON
import json, os, subprocess, sys
LOG, REPO, MODE, NONET, LEAK = "@LOG@", "@REPO@", "@MODE@", "@MODE@.nonet", "@MODE@.leak"
a = sys.argv[1:]
with open(LOG, "a") as fh:
    fh.write(json.dumps(a) + "\n")
if a[:1] != ["run"]:
    sys.exit(1)  # ps, inspect, volume inspect, compose: nothing of the project runs here
if os.path.exists(MODE):
    print("Error: Unable to find image locally (pull never)", file=sys.stderr)
    sys.exit(125)
VALUED = {"-v", "-e", "--env-file", "--network", "--user", "--security-opt", "--cap-drop", "--pull", "-w", "--tmpfs", "--name"}
net = a[a.index("--network") + 1]
if os.path.exists(NONET) and net != "none":
    print(f"Error response from daemon: network {net} not found", file=sys.stderr)
    sys.exit(125)
mounts, env, i = [], {}, 1
while i < len(a) and a[i].startswith("-"):
    if a[i] in VALUED:
        v = a[i + 1]
        if a[i] == "-v":
            src, dst = v.split(":")[:2]
            mounts.append((dst, src))
        elif a[i] == "-e":
            k, _, val = v.partition("=")
            env[k] = val
        elif a[i] == "--env-file":
            for line in open(v):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, val = line.partition("=")
                    env.setdefault(k, val)
        i += 2
    else:
        i += 1
cmd = a[i + 1:]  # after the image name
assert cmd[:3] == ["python", "-m", "tools.trialbox"], cmd
if os.path.exists(LEAK):  # a check that printed a setting's value: what comes back must not show it
    names = cmd[cmd.index("--only") + 1].split(",")
    print(json.dumps([{"name": n, "status": "PASS", "detail": "saw " + open(LEAK).read()} for n in names]))
    sys.exit(0)
def host(p):
    for dst, src in sorted(mounts, key=lambda m: -len(m[0])):
        if p == dst or p.startswith(dst + "/"):
            return src + p[len(dst):]
    return p
args = [host(x) for x in cmd[3:]]
boot = ("import runpy, sys; from tools.trialbox import launch; launch.in_box_image = lambda: True; "
        "sys.argv = ['tools.trialbox', *sys.argv[1:]]; runpy.run_module('tools.trialbox', run_name='__main__')")
child = {"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8", "HOME": os.environ.get("HOME", "/tmp"),
         "PYTHONPATH": "libs:services:.", **env}
sys.exit(subprocess.run([sys.executable, "-c", boot, *args], cwd=REPO, env=child, stdin=sys.stdin).returncode)
"""


@pytest.fixture(scope="module")
def host_tar(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tar = tmp_path_factory.mktemp("h144-tree") / ht.HOST_TAR
    ht.pack(ROOT, tar)
    return tar


def _box(tmp_path: Path, tar: Path, settings: str = "") -> dict[str, Path]:
    """A box as an update leaves it: R1 installed, then R2 (the host tree's install and switch), the box's own
    deploy/.env (0600, its runtime the stand-in engine)."""
    base = tmp_path / "opt-trialbox"
    (base / "deploy").mkdir(parents=True)
    engine = tmp_path / "engine"
    log = tmp_path / "engine.log"
    mode = tmp_path / "image-refused"
    engine.write_text(ENGINE.replace("#!PYTHON", f"#!{sys.executable}").replace("@LOG@", str(log))
                      .replace("@REPO@", str(ROOT)).replace("@MODE@", str(mode)), encoding="utf-8")  # fmt: skip
    engine.chmod(0o755)
    env = base / "deploy" / ".env"
    env.write_text(f"TB_ENV=DEV\nTB_TOPOLOGY=A\nCOMPOSE_PROJECT_NAME=h144test\nTB_IMAGE=trialbox-py:h144\n"
                   f"TB_DOCKER={engine}\nPOSTGRES_PASSWORD=synthetic-pw-h144\n{settings}", encoding="utf-8")  # fmt: skip
    env.chmod(0o600)
    ht.install(tar, base, "R1")
    ht.install(tar, base, "R2")  # the update's host part: a new release, current switched
    for part in ("secrets", "updates"):  # what no image check reads: covered in the container
        (base / "deploy" / part).mkdir(exist_ok=True)
        (base / "deploy" / part / "planted").write_text("synthetic\n", encoding="utf-8")
    return {
        "base": base,
        "env": env,
        "log": log,
        "refused": mode,
        "tmp": tmp_path,
        "nonet": Path(f"{mode}.nonet"),
        "leak": Path(f"{mode}.leak"),
    }


def _doctor(b: dict[str, Path], *, form: str = "file", blocked: tuple[str, ...] = (*NOT_ON_THE_HOST, *SERVICES),
            pythonpath: str | None = None) -> tuple[int, list[dict[str, str]], str]:  # fmt: skip
    """The installed wrapper (``form="file"``, ``base/tools/trialbox/__main__.py`` as on PATH) or the runbook's module
    run from the install folder (``form="module"``), on a host's own Python."""
    target = str(b["base"] / "tools/trialbox/__main__.py") if form == "file" else "tools.trialbox"
    env = {"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8", "HOME": str(b["tmp"])}
    if pythonpath is not None:
        env["PYTHONPATH"] = pythonpath
    argv = [sys.executable, *(["-I"] if form == "file" else []), "-c", BARE, ",".join(blocked), form, target,
            "doctor", "--env-file", str(b["env"]), "--json"]  # fmt: skip
    got = subprocess.run(argv, cwd=b["base"] if form == "module" else b["tmp"], env=env, capture_output=True,
                         text=True, check=False, timeout=600)  # fmt: skip
    try:
        checks = json.loads(got.stdout)
    except ValueError:
        pytest.fail(f"doctor gave no JSON (exit {got.returncode}): {got.stdout[-2000:]} {got.stderr[-3000:]}")
    return got.returncode, checks, got.stderr


def _runs(b: dict[str, Path]) -> list[list[str]]:
    lines = b["log"].read_text(encoding="utf-8").splitlines() if b["log"].exists() else []
    return [a for a in map(json.loads, lines) if a[:1] == ["run"]]


def test_h144_the_installed_doctor_on_a_hosts_own_python_reports_every_checks_own_verdict(
    tmp_path: Path, host_tar: Path
) -> None:
    """The invariant (the ruling's test): no check of the installed doctor is an import error on a host Python that
    has none of pydantic, httpx and the services' code; the image's checks are answered by the box image, once."""
    b = _box(tmp_path, host_tar)
    _rc, checks, err = _doctor(b)
    by = {c["name"]: c for c in checks}
    missing = [n for n in doctor.IMAGE_CHECKS if n not in by]
    assert not missing, (missing, err[-2000:])
    broken = [f"{c['name']}: {c['detail'][:160]}" for c in checks if IMPORT_ERROR.search(c["detail"])]
    assert not broken, broken
    not_run = [n for n in doctor.IMAGE_CHECKS if by[n]["detail"].startswith("not run:")]
    assert not not_run, [by[n] for n in not_run]
    assert by["topology"]["status"] == "PASS" and by["channel_engine"]["status"] == "PASS", (by["topology"],
                                                                                             by["channel_engine"])  # fmt: skip
    assert [c["name"] for c in checks if c["name"] in doctor.IMAGE_CHECKS] == list(doctor.IMAGE_CHECKS)
    runs = {r[r.index("--network") + 1]: r for r in _runs(b)}
    assert set(runs) == {"none", "h144test-model-net"}, list(runs)  # a network only for the check that needs one
    assert runs["h144test-model-net"][runs["h144test-model-net"].index("--only") + 1] == "perimeter_addresses"
    files_only = [n for n in doctor.IMAGE_CHECKS if n != "perimeter_addresses"]
    assert runs["none"][runs["none"].index("--only") + 1] == ",".join(files_only)
    for run in runs.values():
        for want in (["--pull", "never"], ["--cap-drop", "ALL"], ["--security-opt", "no-new-privileges:true"],
                     ["--tmpfs", "/app/deploy/secrets:ro,size=4k,mode=0555"],
                     ["--tmpfs", "/app/deploy/updates:ro,size=4k,mode=0555"]):  # fmt: skip
            assert any(run[i : i + 2] == want for i in range(len(run))), (want, run)
        assert ["-v", f"{(b['base'] / 'deploy').resolve()}:/app/deploy:ro"] == run[
            run.index("-v") : run.index("-v") + 2
        ]
        assert "trialbox-py:h144" in run and "--env-file" in run  # the box file's image; the settings by file only
        assert not any("synthetic-pw-h144" in x or "TB_DB_URL=" in x for x in run)  # no secret on a command line
    assert "synthetic-pw-h144" not in json.dumps(checks) + err


def test_h144_when_the_box_image_cannot_run_each_of_its_checks_is_a_fail_with_the_reason(
    tmp_path: Path, host_tar: Path
) -> None:
    """Never a PASS, never a skip: an image the engine refuses leaves each image check a FAIL naming why."""
    b = _box(tmp_path, host_tar)
    b["refused"].write_text("1", encoding="utf-8")
    rc, checks, _err = _doctor(b)
    by = {c["name"]: c for c in checks}
    assert rc == 1
    for n in doctor.IMAGE_CHECKS:
        assert by[n]["status"] == "FAIL", by[n]
        assert re.match(r"not run: the box image trialbox-py:h144 gave no verdicts( on network \S+)? \(exit 125",
                        by[n]["detail"]), by[n]  # fmt: skip
        assert "Unable to find image" in by[n]["detail"], by[n]
    assert not [c for c in checks if c["status"] == "SKIP"]


def test_h144_a_check_whose_network_is_not_there_says_so_and_the_others_still_run(
    tmp_path: Path, host_tar: Path
) -> None:
    """The integrator's 7159790789 (1): a check that needs the box's network gets it, or says why not."""
    b = _box(tmp_path, host_tar)
    b["nonet"].write_text("1", encoding="utf-8")
    _rc, checks, _err = _doctor(b)
    by = {c["name"]: c for c in checks}
    pa = by["perimeter_addresses"]
    assert pa["status"] == "FAIL" and "gave no verdicts on network h144test-model-net (exit 125" in pa["detail"], pa
    assert "network h144test-model-net not found" in pa["detail"], pa
    assert all(not by[n]["detail"].startswith("not run:") for n in doctor.IMAGE_CHECKS if n != "perimeter_addresses")


def test_h144_no_setting_of_the_box_comes_back_in_what_the_image_says(tmp_path: Path, host_tar: Path) -> None:
    """The integrator's 7159790789 (2): a check in the image that printed a secret setting's value is shown with the
    value replaced; nothing the run prints holds it."""
    b = _box(tmp_path, host_tar)
    b["leak"].write_text("synthetic-pw-h144", encoding="utf-8")
    _rc, checks, err = _doctor(b)
    by = {c["name"]: c for c in checks}
    assert by["topology"]["detail"] == "saw [redacted]", by["topology"]
    assert "synthetic-pw-h144" not in json.dumps(checks) + err


def test_h144_a_stale_services_folder_after_an_update_is_seen_and_never_imported(
    tmp_path: Path, host_tar: Path
) -> None:
    """The integrator's test: an installed box after an update, with a stale ``services/`` (and ``models/``) planted,
    is seen: ``release_tree`` names each and the command that removes it. The runbook's module run from the install
    folder, with ``services/`` on its PYTHONPATH and every library there, never imports it, and FAILs (that path holds
    it); the installed wrapper, whose path does not, WARNs (7159790789 (3))."""
    b = _box(tmp_path, host_tar)
    stale = b["base"] / "services" / "gateway"
    stale.mkdir(parents=True)
    (stale / "__init__.py").write_text('raise RuntimeError("the stale services/ was imported")\n', encoding="utf-8")
    (b["base"] / "models").mkdir()
    (b["base"] / "models" / "routing.yaml").write_text("routes: {}\n", encoding="utf-8")
    _rc, checks, err = _doctor(b, form="module", blocked=("no-such-module",), pythonpath="libs:services:.")
    by = {c["name"]: c for c in checks}
    assert by["release_tree"]["status"] == "FAIL", by["release_tree"]
    said = by["release_tree"]["detail"]
    for p in (b["base"] / "services", b["base"] / "models"):
        assert str(p) in said, said
    assert f"sudo rm -rf -- {b['base'] / 'services'} {b['base'] / 'models'}" in said, said
    assert f"This command's import path holds {b['base'] / 'services'}" in said, said  # FAIL: its PYTHONPATH has it
    assert "the stale services/ was imported" not in json.dumps(checks) + err
    assert len(_runs(b)) == 2  # the image's checks went to the image, not to the loose folder
    assert (b["base"] / "services" / "gateway" / "__init__.py").is_file()  # named, never removed
    # the installed wrapper (its own path only): the same folders are a WARN, nothing imports them
    _rc, checks, err = _doctor(b)
    tree = {c["name"]: c for c in checks}["release_tree"]
    assert tree["status"] == "WARN" and str(b["base"] / "services") in tree["detail"], tree
    assert "No host command imports it" in tree["detail"], tree
    assert "the stale services/ was imported" not in json.dumps(checks) + err


def test_h144_the_update_names_a_loose_folder_and_leaves_it(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = tmp_path / "opt-trialbox"
    (base / "deploy").mkdir(parents=True)
    (base / "releases" / "r1").mkdir(parents=True)
    (base / "releases" / "r1" / ht.SUMS).write_text("", encoding="utf-8")
    (base / "current").symlink_to("releases/r1")
    up._name_loose(base / "deploy")
    assert capsys.readouterr().out == ""
    (base / "services").mkdir()
    up._name_loose(base / "deploy")
    out = capsys.readouterr().out
    assert out.startswith(f"update: note (H-144): {base / 'services'}: not the release's"), out
    assert f"sudo rm -rf -- {base / 'services'}" in out and (base / "services").is_dir()
    src = ast.parse((ROOT / "tools/trialbox/update.py").read_text(encoding="utf-8"))
    main = next(n for n in src.body if isinstance(n, ast.FunctionDef) and n.name == "main_apply")
    calls = [n for n in ast.walk(main) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_name_loose"]
    assert len(calls) == 2  # after "applied, checked and audited" and after "loaded" (install.sh's first load)


def test_ocr_1512_1_the_update_names_nothing_in_a_source_checkout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """OCR 1512-1: a source checkout's services/ and models/ are its own code: no note, and no rm -rf line for them."""
    checkout = tmp_path / "checkout"
    for n in ("deploy", "services", "models", "rulesets"):
        (checkout / n).mkdir(parents=True)
    up._name_loose(checkout / "deploy")
    assert capsys.readouterr().out == ""


def test_ocr_1512_2_a_deploy_folder_the_caller_cannot_search_is_each_image_checks_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OCR 1512-2 (escape check i): the install's deploy folder present but not searchable by this user: each image
    check is a FAIL that names why, never a traceback that ends the doctor. The refusal is a stand-in (os.stat below
    the folder answers PermissionError), so the case runs as root and as an ordinary user alike."""
    box = tmp_path / "box"
    (box / "deploy").mkdir(parents=True)
    (box / "deploy" / ".env").write_text("TB_ENV=DEV\n", encoding="utf-8")
    monkeypatch.setattr(launch, "DEPLOY", box / "deploy")
    real_stat = os.stat
    below = str(box) + os.sep

    def stat(p: Any, *a: Any, **k: Any) -> os.stat_result:
        if os.fspath(p).startswith(below):
            raise PermissionError(13, "Permission denied", os.fspath(p))
        return real_stat(p, *a, **k)

    monkeypatch.setattr(os, "stat", stat)
    out = doctor.run(doctor.DoctorInputs(env={"TB_ENV": "DEV"}), (doctor.check_topology,),
                     image=doctor.image_part(None, None, None), extras=False)  # fmt: skip
    (topology,) = [c for c in out if c.name == "topology"]
    assert topology.status == "FAIL" and "PermissionError" in topology.detail, topology


def test_ocr_1512_3_a_container_past_its_time_is_removed_and_the_check_fails() -> None:
    calls: list[list[str]] = []

    def run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if cmd[1] == "run":
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout") or 0)
        return subprocess.CompletedProcess(cmd, 0 if cmd[1] == "rm" else 1, "", "")

    req = doctor_image.Request(("topology",), None, None, box={"TB_DOCKER": "eng"})
    (v,) = doctor_image.verdicts(req, run=run)
    started = next(c for c in calls if c[1] == "run")
    name = started[started.index("--name") + 1]
    assert ["eng", "rm", "-f", name] in calls, calls
    assert v["status"] == "FAIL" and f"container {name} removed" in v["detail"], v


def test_h144_the_merge_keeps_the_order_and_never_passes_a_check_the_image_did_not_answer() -> None:
    inp = doctor.DoctorInputs(env={"TB_ENV": "DEV"})

    def image(names: tuple[str, ...]) -> list[doctor.Check]:
        assert names == ("topology", "channel_engine")
        return [doctor.Check("inputs", "FAIL", "settings file /x not found"), doctor.Check("topology", "PASS", "ok"),
                doctor.Check("no_such", "PASS", "ignored")]  # fmt: skip

    def check_site_tz(_inp: doctor.DoctorInputs) -> doctor.Check:
        return doctor.Check("site_tz", "PASS", "here")

    out = doctor.run(
        inp, (doctor.check_topology, check_site_tz, doctor.check_channel_engine), image=image, extras=False
    )
    assert [(c.name, c.status) for c in out] == [("inputs (box image)", "FAIL"), ("topology", "PASS"),
                                                 ("site_tz", "PASS"), ("channel_engine", "FAIL")]  # fmt: skip
    assert out[3].detail == "the box image gave no verdict for this check"


def test_h144_the_image_part_fails_each_unanswered_check_with_the_reason(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def run(cmd: list[str], **_kw: Any) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if cmd[1] == "run":
            return subprocess.CompletedProcess(cmd, 1, json.dumps([{"name": "topology", "status": "PASS",
                                                                    "detail": "TB_TOPOLOGY=A"}]), "")  # fmt: skip
        return subprocess.CompletedProcess(cmd, 1, "", "")

    req = doctor_image.Request(("topology", "terminology"), None, None, box={"TB_DOCKER": "eng"})
    got = {v["name"]: v for v in doctor_image.verdicts(req, run=run)}
    assert got["topology"] == {"name": "topology", "status": "PASS", "detail": "TB_TOPOLOGY=A"}
    assert got["terminology"]["status"] == "FAIL"
    assert got["terminology"]["detail"].startswith("not run: the box image trialbox-py:1.0.0 answered, but not for")

    def boom(cmd: list[str], **_kw: Any) -> subprocess.CompletedProcess[str]:
        if cmd[1] == "run":
            raise FileNotFoundError(2, "No such file or directory", "eng")
        return subprocess.CompletedProcess(cmd, 1, "", "")

    got = {v["name"]: v for v in doctor_image.verdicts(req, run=boom)}
    assert all(v["status"] == "FAIL" and "could not be started here" in v["detail"] for v in got.values()), got


def test_h144_the_image_only_folders_are_what_the_box_image_carries_and_the_host_tree_does_not() -> None:
    copied = set(re.findall(r"^COPY --chown=tb:tb ([a-z]+) /app/\1$", (ROOT / "deploy/docker/python.Dockerfile")
                            .read_text(encoding="utf-8"), re.M))  # fmt: skip
    assert {"services", "models"} <= set(ht.IMAGE_ONLY)
    # eval/: the image carries its qualification and injection sets (copied in part), which the eval commands read
    assert set(ht.IMAGE_ONLY) == (copied - set(ht.TOP_DIRS)) | {"eval"}, (ht.IMAGE_ONLY, copied)
    assert all(n not in ht.TOP_DIRS for n in ht.IMAGE_ONLY)
    assert set(doctor.IMAGE_CHECKS) <= {fn.__name__.removeprefix("check_") for fn in doctor.CHECKS}


# ---------------------------------------------------------------------------------------- each host command's imports
#: each command ``launch.COMMANDS`` runs on the host, and the modules ``tools/trialbox/__main__.py`` loads for it
HOST_ENTRY = {
    "doctor": ("tools.trialbox.doctor", "tools.trialbox.doctor_image"),
    "platform-images": ("tools.trialbox.platform",),
    "platform-egress": ("tools.trialbox.platform",),
    "restore": ("tools.trialbox.box_restore",),
    "restore-drill": ("tools.trialbox.restore_drill", "tools.trialbox.box_drill"),
    "backup-nightly": ("tools.trialbox.backup_schedule",),
    "backup-status": ("tools.trialbox.backup_schedule",),
    "backup-install": ("tools.trialbox.backup_schedule",),
    "migrate": ("tools.trialbox.update",),
    "secrets": ("tools.trialbox.svc_secrets",),
    "audit-sign": ("tools.trialbox.audit_heads",),
    "anchors-compose": ("tools.trialbox.anchors",),
    "finish-check": ("tools.trialbox.finish_check",),
    "logs": ("tools.trialbox.logs",),
    "update": ("tools.trialbox.update",),
    "pre-start": ("tools.trialbox.prestart",),
    "db-up": ("tools.trialbox.prestart",),
    "ops": ("tools.trialbox.ops",),
    "watchdog": ("tools.trialbox.watchdog",),
    "support-bundle": ("tools.support_bundle",),
    "selftest": ("tools.trialbox.selftest",),
    "decommission-plan": ("tools.trialbox.decommission",),
    "platform-day2": ("tools.trialbox.platform_day2",),
    "provenance": ("tools.trialbox.provenance",),
}
HOST_LIBS = {"yaml"}  # install.sh HOST-PYTHON: the standard library and PyYAML
REPO_TOPS = {"tools", "tb_common", "tb_contracts", "tb_llm", "deploy"} | {
    p.name for p in (ROOT / "libs").iterdir() if p.is_dir()
}


def _path(mod: str) -> Path | None:
    for base in (ROOT, ROOT / "libs"):
        p = base / Path(*mod.split("."))
        if (p / "__init__.py").is_file():
            return p / "__init__.py"
        if p.with_suffix(".py").is_file():
            return p.with_suffix(".py")
    return None


def _loaded_imports(mod: str) -> set[str]:
    """What loading ``mod`` imports: its module-level statements (in ``if``/``try`` blocks too, never under
    ``TYPE_CHECKING``); a function's own import runs only when the function does."""
    p = _path(mod)
    if p is None:
        return set()
    pkg = mod if p.name == "__init__.py" else mod.rpartition(".")[0]
    out: set[str] = set()

    def visit(stmts: list[ast.stmt]) -> None:
        for n in stmts:
            if isinstance(n, ast.Import):
                out.update(a.name for a in n.names)
            elif isinstance(n, ast.ImportFrom):
                base = n.module or ""
                if n.level:
                    parts = pkg.split(".")[: len(pkg.split(".")) - n.level + 1]
                    base = ".".join([*parts, base] if base else parts)
                out.add(base)
                out.update(f"{base}.{a.name}" for a in n.names)
            elif isinstance(n, ast.If):
                if "TYPE_CHECKING" not in ast.unparse(n.test):
                    visit(n.body)
                    visit(n.orelse)
            elif isinstance(n, ast.Try):
                visit(n.body)
                visit(n.orelse)
                visit(n.finalbody)
                for h in n.handlers:
                    visit(h.body)

    visit(ast.parse(p.read_text(encoding="utf-8")).body)
    return out


def _reach(start: str) -> set[str]:
    seen: set[str] = set()
    todo, bad = [start], set()
    while todo:
        m = todo.pop()
        if m in seen:
            continue
        seen.add(m)
        top = m.split(".")[0]
        if top in SERVICES:
            bad.add(f"services/{top}")
        elif _path(m) is not None:
            todo.extend(_loaded_imports(m))
        elif top not in sys.stdlib_module_names and top not in HOST_LIBS and top not in REPO_TOPS and top:
            bad.add(top)
    return bad


def test_h144_every_host_command_is_listed_with_the_modules_it_loads() -> None:
    assert set(HOST_ENTRY) == {c for c, n in launch.COMMANDS.items() if n.where == launch.HOST}
    assert all(_path(m) is not None for ms in HOST_ENTRY.values() for m in ms)


@pytest.mark.parametrize("command", sorted(HOST_ENTRY))
def test_h144_a_host_command_loads_nothing_the_hosts_own_python_lacks(command: str) -> None:
    """Per command (the lead's go): loading what it runs on the host reaches no package of ``services/`` and no
    library beyond the standard library and PyYAML. What a function imports when it runs is the command's own
    check's business (doctor's: the image's part, above)."""
    bad = sorted(set().union(*(_reach(m) for m in HOST_ENTRY[command])))
    assert not bad, bad
