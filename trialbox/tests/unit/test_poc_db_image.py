"""Card 24-2 (root review 24): the one-command start builds the database image too.

`deploy/poc.sh` builds its own images on a machine without them; its builder path (no Maven on the host) built only
trialbox-py and trialbox-jvm, while compose's `db` service runs trialbox-postgres:16-1, which has no `build:` entry and
is on no registry, so on a fresh machine the start stopped at compose up and runbook 28 had a manual build step. The
start now builds it with the one command `make images` also runs (deploy/build_db_image.sh), only when it is missing or
TB_POC_BUILD=1, and stops with a plain message, starting nothing, when the build fails. Run here with a stand-in docker
(no daemon) on a root of its own, as tests/unit/test_poc_gpu.py does."""

from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DB = "trialbox-postgres:16-1"
DB_BUILD = "build -f deploy/docker/db.Dockerfile -t trialbox-postgres:16-1 deploy/docker"

pytestmark = pytest.mark.nodb

# `image inspect` answers from TB_TEST_PRESENT (space-separated references); a build whose argv holds
# TB_TEST_FAIL_BUILD fails; `info` names the stand-in machine's architecture
DOCKER = r"""#!/bin/sh
echo "$*" >> "$TB_TEST_LOG"
case "$1" in
  info) echo "Architecture: $TB_TEST_ARCH" ;;
  image)
    shift 2
    for ref in "$@"; do
      case " $TB_TEST_PRESENT " in *" $ref "*) ;; *) echo "Error: No such image: $ref" >&2; exit 1 ;; esac
    done ;;
  build) case "$*" in *"${TB_TEST_FAIL_BUILD:-@none@}"*) echo "E: Unable to fetch some archives" >&2; exit 100 ;; esac ;;
esac
exit 0
"""
UNAME = '#!/bin/sh\n[ "$1" = -m ] && echo "$TB_TEST_ARCH" || /bin/uname "$@"\n'
MAKE = '#!/bin/sh\necho "make $*" >> "$TB_TEST_LOG"\n'
OK = "#!/bin/sh\nexit 0\n"
ALL = f"trialbox-py:1.0.0 trialbox-jvm:1.0.0 {DB}"
ARCHES = ("aarch64", "x86_64")


def _root(tmp: Path) -> Path:
    root = tmp / "root"
    (root / "deploy").mkdir(parents=True)
    for rel in ("deploy/poc.sh", "deploy/build_db_image.sh", ".env.example"):
        shutil.copy2(ROOT / rel, root / rel)
    return root


def _run(
    tmp: Path, root: Path, *, build_tools: bool = False, **env: str
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bindir = tmp / "bin"
    bindir.mkdir(exist_ok=True)
    tools = {"docker": DOCKER, "uname": UNAME}
    if build_tools:  # a host with Maven, curl and a python with fontTools: the start runs `make images`
        tools.update(make=MAKE, mvn=OK)
        venv = root / ".venv/bin/python"
        venv.parent.mkdir(parents=True, exist_ok=True)
        venv.write_text(OK, encoding="utf-8")
        venv.chmod(0o755)
    for name, body in tools.items():
        (bindir / name).write_text(body, encoding="utf-8")
        (bindir / name).chmod(0o755)
    log = tmp / "docker.log"
    log.unlink(missing_ok=True)
    full = {
        k: v for k, v in os.environ.items() if not k.startswith("TB_") and k not in ("HTTPS_PROXY", "POSTGRES_IMAGE")
    }
    full.update(PATH=f"{bindir}:/usr/bin:/bin", TB_LLM_MODE="stub", TB_TEST_LOG=str(log), TB_POC_SKIP_INGEST="1",
                TB_TEST_ARCH="x86_64", TB_TEST_PRESENT="")  # fmt: skip
    full.update(env)
    res = subprocess.run(["bash", str(root / "deploy/poc.sh")], capture_output=True, text=True, env=full,
                         timeout=120, check=False)  # fmt: skip
    return res, (log.read_text(encoding="utf-8").splitlines() if log.exists() else [])


def _builds(log: list[str]) -> list[str]:
    return [s for s in log if s.startswith("build ") or s.startswith("make ")]


def _started(log: list[str]) -> bool:
    return any(" up -d " in f" {s} " for s in log)


@pytest.mark.parametrize("arch", ARCHES)
def test_a_machine_without_images_builds_the_database_image_with_the_one_command(tmp_path: Path, arch: str) -> None:
    root = _root(tmp_path)
    res, log = _run(tmp_path, root, TB_TEST_ARCH=arch)
    assert res.returncode == 0, res.stdout + res.stderr
    assert _builds(log) == [
        "build -f deploy/docker/python.Dockerfile -t trialbox-py:1.0.0 .",
        "build -f deploy/docker/jvm.Dockerfile -t trialbox-jvm:1.0.0 .",
        DB_BUILD,
    ]
    assert f"building the database image {DB}" in res.stdout
    assert log.index(DB_BUILD) < next(i for i, s in enumerate(log) if " up -d " in f" {s} ")


@pytest.mark.parametrize("arch", ARCHES)
def test_only_the_missing_database_image_is_built(tmp_path: Path, arch: str) -> None:
    """The two product images present, the database's not (the case of runbook 28 before card 24-2): only it."""
    root = _root(tmp_path)
    res, log = _run(tmp_path, root, TB_TEST_ARCH=arch, TB_TEST_PRESENT="trialbox-py:1.0.0 trialbox-jvm:1.0.0")
    assert res.returncode == 0, res.stdout + res.stderr
    assert _builds(log) == [DB_BUILD] and _started(log)


@pytest.mark.parametrize("arch", ARCHES)
def test_present_images_are_not_built_and_the_calls_are_masters_plus_one_inspect(tmp_path: Path, arch: str) -> None:
    """With every image present nothing is built; the docker calls are master's, with one added read-only
    `image inspect` of the database image right after master's inspect of the other two."""
    root = _root(tmp_path)
    res, log = _run(tmp_path, root, TB_TEST_ARCH=arch, TB_TEST_PRESENT=ALL)
    assert res.returncode == 0, res.stdout + res.stderr
    assert _builds(log) == [] and _started(log)
    inspects = [i for i, s in enumerate(log) if s.startswith("image inspect")]
    assert [log[i] for i in inspects] == ["image inspect trialbox-py:1.0.0 trialbox-jvm:1.0.0", f"image inspect {DB}"]
    assert inspects[1] == inspects[0] + 1
    assert "building" not in res.stdout


@pytest.mark.parametrize("arch", ARCHES)
def test_tb_poc_build_rebuilds_the_database_image_too(tmp_path: Path, arch: str) -> None:
    root = _root(tmp_path)
    res, log = _run(tmp_path, root, TB_TEST_ARCH=arch, TB_TEST_PRESENT=ALL, TB_POC_BUILD="1")
    assert res.returncode == 0, res.stdout + res.stderr
    assert _builds(log)[-1] == DB_BUILD and len(_builds(log)) == 3
    assert not any(s.startswith("image inspect") for s in log)  # as on master: TB_POC_BUILD=1 asks nothing


@pytest.mark.parametrize("arch", ARCHES)
def test_a_failed_database_build_stops_the_start_with_one_plain_message(tmp_path: Path, arch: str) -> None:
    root = _root(tmp_path)
    res, log = _run(tmp_path, root, TB_TEST_ARCH=arch, TB_TEST_PRESENT="trialbox-py:1.0.0 trialbox-jvm:1.0.0",
                    TB_TEST_FAIL_BUILD="db.Dockerfile")  # fmt: skip
    assert res.returncode == 1
    assert f"poc: the database image {DB} did not build" in res.stderr
    assert "run deploy/poc.sh again" in res.stderr
    assert not _started(log) and not any(s.startswith(("run ", "compose")) for s in log[log.index(DB_BUILD) :])


def test_the_build_is_idempotent_a_second_start_builds_nothing(tmp_path: Path) -> None:
    root = _root(tmp_path)
    res, log = _run(tmp_path, root, TB_TEST_PRESENT="trialbox-py:1.0.0 trialbox-jvm:1.0.0")
    assert res.returncode == 0 and _builds(log) == [DB_BUILD]
    res, log = _run(tmp_path, root, TB_TEST_PRESENT=ALL)  # the image is there now
    assert res.returncode == 0 and _builds(log) == []


def test_a_host_with_build_tools_builds_it_once_through_make_images(tmp_path: Path) -> None:
    """`make images` already ends with the database image: the start does not build it a second time."""
    root = _root(tmp_path)
    res, log = _run(tmp_path, root, build_tools=True)
    assert res.returncode == 0, res.stdout + res.stderr
    assert _builds(log) == [f"make images PY={root}/.venv/bin/python"]


def test_a_site_database_image_is_left_alone(tmp_path: Path) -> None:
    root = _root(tmp_path)
    res, log = _run(tmp_path, root, TB_TEST_PRESENT="trialbox-py:1.0.0 trialbox-jvm:1.0.0",
                    POSTGRES_IMAGE="registry.invalid/trialbox-postgres@sha256:" + "0" * 64)  # fmt: skip
    assert res.returncode == 0, res.stdout + res.stderr
    assert _builds(log) == [] and not any(DB in s for s in log)


# ---------------------------------------------------------------------------------------- one command, two callers
def _makefile_images() -> str:
    mk = re.sub(r"\\\n\s*", "", (ROOT / "Makefile").read_text(encoding="utf-8"))  # one line per command
    return mk[mk.index("\nimages:") :].split("\n\n", 1)[0]


def test_make_images_and_the_start_call_the_same_script() -> None:
    images = _makefile_images()
    assert "\tdeploy/build_db_image.sh $(PLATFORM_ARG) $(OCI_LABELS)" in images
    assert "db.Dockerfile" not in images  # no second copy of the command
    poc = (ROOT / "deploy/poc.sh").read_text(encoding="utf-8")
    assert "deploy/build_db_image.sh ||" in poc and "db.Dockerfile -t" not in poc


def test_the_script_runs_the_command_the_makefile_ran(tmp_path: Path) -> None:
    """The Makefile's earlier line: docker build $(PLATFORM_ARG) $(BUILD_ARGS) $(CA_SECRET) $(OCI_LABELS) -f
    deploy/docker/db.Dockerfile -t trialbox-postgres:16-1 deploy/docker. The same arguments, behind a proxy too."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "docker").write_text(DOCKER, encoding="utf-8")
    (bindir / "docker").chmod(0o755)
    log = tmp_path / "docker.log"
    labels = ["--label", "org.opencontainers.image.version=1.0.0", "--label", "org.opencontainers.image.title=trialbox"]
    env = {k: v for k, v in os.environ.items() if k not in ("HTTPS_PROXY", "TB_EXTRA_CA")}
    env.update(PATH=f"{bindir}:/usr/bin:/bin", TB_TEST_LOG=str(log), HTTPS_PROXY="http://proxy.invalid:3128",
               TB_EXTRA_CA="/etc/ca.pem")  # fmt: skip
    res = subprocess.run(["bash", str(ROOT / "deploy/build_db_image.sh"), "--platform", "linux/arm64", *labels],
                         capture_output=True, text=True, env=env, timeout=30, check=False)  # fmt: skip
    assert res.returncode == 0, res.stderr
    proxy = ["--network", "host", "--build-arg", "HTTPS_PROXY=http://proxy.invalid:3128",
             "--build-arg", "https_proxy=http://proxy.invalid:3128"]  # fmt: skip
    ca = ["--secret", "id=extra_ca,src=/etc/ca.pem"]
    tail = ["-f", "deploy/docker/db.Dockerfile", "-t", DB, "deploy/docker"]
    assert log.read_text(encoding="utf-8").split() == [
        "build",
        "--platform",
        "linux/arm64",
        *labels,
        *proxy,
        *ca,
        *tail,
    ]


def test_the_script_fetches_nothing_itself_and_names_no_host() -> None:
    text = (ROOT / "deploy/build_db_image.sh").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    for absent in ("curl", "wget", "http://", "https://", "docker pull", "@sha256"):
        assert absent not in code, absent


# ------------------------------------------------------------------------- the host's python3 3.10 (Ubuntu 22.04)
#: what Python 3.11 and later added that a 3.10 interpreter cannot import
NEWER_MODULES = {"tomllib", "wsgiref.types"}
NEWER_NAMES = {
    "typing": {"Self", "LiteralString", "Never", "assert_never", "reveal_type", "Required", "NotRequired",
               "TypeVarTuple", "Unpack", "dataclass_transform", "override", "TypeAliasType", "get_overloads"},
    "enum": {"StrEnum", "ReprEnum", "verify", "EnumCheck", "FlagBoundary", "member", "nonmember", "global_enum"},
    "datetime": {"UTC"},
    "asyncio": {"TaskGroup", "Runner", "timeout"},
}  # fmt: skip
#: the Python the start's builder path can run on the host: `make images PY=<host python3>` runs these two (the
#: builder container runs them with its own python3); the database build itself runs none
HOST_HELPERS = ("tools/fetch_fonts.py", "tools/fetch_fhir_packages.py")


@pytest.mark.parametrize("rel", HOST_HELPERS)
def test_every_helper_of_the_path_runs_on_python_3_10(rel: str) -> None:
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"), filename=rel, feature_version=(3, 10))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not {a.name for a in node.names} & NEWER_MODULES, rel
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module not in NEWER_MODULES, rel
            assert not {a.name for a in node.names} & NEWER_NAMES.get(node.module, set()), rel
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            assert (node.value.id, node.attr) not in {("hashlib", "file_digest"), ("datetime", "UTC")}, rel
    shell = (ROOT / "tools/fetch_jvm_deps.sh").read_text(encoding="utf-8")
    assert set(re.findall(r'"\$PY" "\$ROOT/(tools/[a-z_]+\.py)"', shell)) <= set(HOST_HELPERS)


def test_the_script_builds_from_the_checkout_wherever_it_is_called_from(tmp_path: Path) -> None:
    """The context and Dockerfile paths are relative to the checkout: the script moves there first, whatever the
    caller's working directory, and a checkout under a path with a space works too."""
    root = tmp_path / "a folder with space" / "trialbox"
    (root / "deploy/docker").mkdir(parents=True)
    shutil.copy2(ROOT / "deploy/build_db_image.sh", root / "deploy/build_db_image.sh")
    (root / "deploy/docker/db.Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    seen = tmp_path / "seen.txt"
    (bindir / "docker").write_text(
        '#!/bin/sh\n{ pwd; for a in "$@"; do echo "$a"; done; } > "$TB_TEST_SEEN"\n'
        "[ -f deploy/docker/db.Dockerfile ] && [ -d deploy/docker ] || exit 9\n",
        encoding="utf-8",
    )
    (bindir / "docker").chmod(0o755)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    env = {k: v for k, v in os.environ.items() if k not in ("HTTPS_PROXY", "TB_EXTRA_CA")}
    env.update(PATH=f"{bindir}:/usr/bin:/bin", TB_TEST_SEEN=str(seen))
    res = subprocess.run(["bash", str(root / "deploy/build_db_image.sh")], cwd=elsewhere, capture_output=True,
                         text=True, env=env, timeout=30, check=False)  # fmt: skip
    assert res.returncode == 0, res.stderr
    cwd, *argv = seen.read_text(encoding="utf-8").splitlines()
    assert Path(cwd).resolve() == root.resolve()
    assert argv == ["build", "-f", "deploy/docker/db.Dockerfile", "-t", DB, "deploy/docker"]
