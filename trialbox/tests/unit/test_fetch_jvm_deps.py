"""The validator jar fetch refuses a jar whose sha256 is not the pinned one (DEP-017, card T-671).

Offline: the cached-jar path never downloads, and the check runs before Maven or the FHIR package fetch, so a stub
``mvn`` and ``PY`` are enough. The pinned sum itself is checked against the real release asset only when the jar is
fetched for real (``make jvm-deps``, which CI runs).
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "fetch_jvm_deps.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("sha256sum") is None, reason="needs bash and sha256sum"
)


def _pinned(name: str) -> str:
    m = re.search(rf'^{name}="([^"]+)"$', SCRIPT.read_text(encoding="utf-8"), re.MULTILINE)
    assert m, f"{name} not found in {SCRIPT.name}"
    return m.group(1)


def _run(out: Path, tmp_path: Path, **env: str) -> subprocess.CompletedProcess[str]:
    stub = tmp_path / "stubbin"
    stub.mkdir(exist_ok=True)
    mvn = stub / "mvn"
    mvn.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    mvn.chmod(0o755)
    full_env = {
        "PATH": f"{stub}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": str(tmp_path),
        "PY": "true",  # the FHIR package fetch is not under test
        **env,
    }
    return subprocess.run(
        ["bash", str(SCRIPT), str(out)], capture_output=True, text=True, env=full_env, timeout=60, check=False
    )


def _lib_sums(tmp_path: Path, jars: dict[str, bytes]) -> Path:
    p = tmp_path / "jvm-deps.sha256"
    lines = ["# test list"] + [f"{hashlib.sha256(b).hexdigest()}  {n}" for n, b in sorted(jars.items())]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _cached(tmp_path: Path, jars: dict[str, bytes]) -> tuple[Path, dict[str, str]]:
    """A cache with the validator jar and these translator jars; env with the validator's sum."""
    out = tmp_path / "jvm"
    (out / "cql-translator" / "lib").mkdir(parents=True)
    (out / "validator_cli.jar").write_bytes(b"stand-in jar")
    for name, data in jars.items():
        (out / "cql-translator" / "lib" / name).write_bytes(data)
    return out, {"VALIDATOR_SHA256": hashlib.sha256(b"stand-in jar").hexdigest()}


def test_pin_is_a_sha256() -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", _pinned("PINNED_VALIDATOR_SHA256"))
    assert re.fullmatch(r"\d+\.\d+\.\d+", _pinned("PINNED_VALIDATOR_VERSION"))


def test_tampered_cached_jar_fails_the_fetch(tmp_path: Path) -> None:
    out = tmp_path / "jvm"
    out.mkdir()
    (out / "validator_cli.jar").write_bytes(b"PK\x03\x04 not the validator")
    res = _run(out, tmp_path)
    assert res.returncode != 0
    assert "is not the pinned" in res.stderr
    assert not (out / "validator_cli.jar.sha256").exists()


def test_jar_matching_the_sum_passes(tmp_path: Path) -> None:
    out = tmp_path / "jvm"
    out.mkdir()
    data = b"stand-in jar"
    (out / "validator_cli.jar").write_bytes(data)
    (out / "cql-translator" / "lib").mkdir(parents=True)
    (out / "cql-translator" / "lib" / "x.jar").write_bytes(b"x")  # Maven step skipped
    sums = _lib_sums(tmp_path, {"x.jar": b"x"})
    res = _run(out, tmp_path, VALIDATOR_SHA256=hashlib.sha256(data).hexdigest(), JVM_LIB_SUMS=str(sums))
    assert res.returncode == 0, res.stderr
    assert (out / "validator_cli.jar.sha256").read_text(encoding="utf-8").startswith(hashlib.sha256(data).hexdigest())


def test_one_tampered_byte_fails(tmp_path: Path) -> None:
    out = tmp_path / "jvm"
    out.mkdir()
    data = b"stand-in jar"
    (out / "validator_cli.jar").write_bytes(data + b"!")
    res = _run(out, tmp_path, VALIDATOR_SHA256=hashlib.sha256(data).hexdigest())
    assert res.returncode != 0
    assert "refusing it" in res.stderr


def test_unpinned_version_needs_a_sum(tmp_path: Path) -> None:
    out = tmp_path / "jvm"
    res = _run(out, tmp_path, VALIDATOR_VERSION="0.0.1")
    assert res.returncode != 0
    assert "no pinned sha256" in res.stderr
    assert not out.exists()


# ENG-013 (T-110b): the translator jars Maven copies are pinned by tools/jvm-deps.sha256


def test_jar_list_is_well_formed_and_names_the_translator() -> None:
    rows = [ln for ln in (ROOT / "tools" / "jvm-deps.sha256").read_text(encoding="utf-8").splitlines()]
    rows = [ln for ln in rows if ln and not ln.startswith("#")]
    assert len(rows) > 50
    names = []
    for ln in rows:
        m = re.fullmatch(r"([0-9a-f]{64})  (\S+\.jar)", ln)
        assert m, ln
        names.append(m.group(2))
    assert len(names) == len(set(names))
    assert any(n.startswith("cql-to-elm") for n in names)
    assert "-C" in SCRIPT.read_text(encoding="utf-8").split("dependency:copy-dependencies")[0].rsplit("mvn", 1)[1]


def test_one_tampered_byte_in_a_cached_translator_jar_fails(tmp_path: Path) -> None:
    jars = {"a.jar": b"jar a", "b.jar": b"jar b"}
    out, env = _cached(tmp_path, jars)
    sums = _lib_sums(tmp_path, jars)
    assert _run(out, tmp_path, JVM_LIB_SUMS=str(sums), **env).returncode == 0
    (out / "cql-translator" / "lib" / "b.jar").write_bytes(b"jar c")
    res = _run(out, tmp_path, JVM_LIB_SUMS=str(sums), **env)
    assert res.returncode != 0
    assert "not the ones jvm-deps.sha256 pins" in res.stderr
    assert "b.jar" in res.stderr


@pytest.mark.parametrize("change", ["extra", "missing"])
def test_an_extra_or_missing_translator_jar_fails(tmp_path: Path, change: str) -> None:
    jars = {"a.jar": b"jar a", "b.jar": b"jar b"}
    out, env = _cached(tmp_path, jars)
    sums = _lib_sums(tmp_path, jars)
    if change == "extra":
        (out / "cql-translator" / "lib" / "evil.jar").write_bytes(b"added")
    else:
        (out / "cql-translator" / "lib" / "a.jar").unlink()
    res = _run(out, tmp_path, JVM_LIB_SUMS=str(sums), **env)
    assert res.returncode != 0
    assert "refusing them" in res.stderr


def _bare_path(tmp_path: Path) -> str:
    """A PATH with the shell tools the script uses and no Maven (CI's runners have one on their own PATH)."""
    d = tmp_path / "bare"
    d.mkdir(exist_ok=True)
    for tool in ("bash", "sh", "sha256sum", "sort", "sed", "grep", "cut", "ls", "mkdir", "cat", "head", "diff",
                 "dirname", "mv", "rm", "tr", "true"):  # fmt: skip
        found = shutil.which(tool)
        if found and not (d / tool).exists():
            (d / tool).symlink_to(found)
    return str(d)


def test_no_maven_says_what_the_build_host_needs(tmp_path: Path) -> None:
    """I-7 (D-885): lane G's VM stopped at `mvn: command not found`; the fetch now names Maven and the JDK first."""
    out, env = _cached(tmp_path, {})
    res = subprocess.run(["bash", str(SCRIPT), str(out)], capture_output=True, text=True, timeout=60, check=False,
                         env={"PATH": _bare_path(tmp_path), "HOME": str(tmp_path), "PY": "true", **env})  # fmt: skip
    assert res.returncode == 1
    major = (ROOT / ".java-version").read_text(encoding="utf-8").strip()
    assert "Maven" in res.stderr and f"JDK {major}" in res.stderr and "openjdk-" in res.stderr
    assert "command not found" not in res.stderr


def test_maven_without_a_jdk_says_so(tmp_path: Path) -> None:
    out, env = _cached(tmp_path, {})
    stub = tmp_path / "nojdk"
    stub.mkdir()
    (stub / "mvn").write_text(
        "#!/bin/sh\necho 'The JAVA_HOME environment variable is not defined correctly' >&2\nexit 1\n"
    )
    (stub / "mvn").chmod(0o755)
    res = subprocess.run(["bash", str(SCRIPT), str(out)], capture_output=True, text=True, timeout=60, check=False,
                         env={"PATH": f"{stub}{os.pathsep}{_bare_path(tmp_path)}", "HOME": str(tmp_path), "PY": "true",
                              **env})  # fmt: skip
    assert res.returncode == 1 and "mvn -v failed" in res.stderr and "JDK" in res.stderr
