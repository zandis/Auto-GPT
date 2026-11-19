"""H-54: the box rehearsal's step `host-image` is fast and bounded. Train 98's legs failed it at 500 s (archive.ubuntu.com
refused, apt's own retries running out) and at 112 s (indexes not read, "Unable to locate package"); a leg that morning
took 46 minutes. The base is pinned by digest, every apt fetch is bounded and retried, a build attempt has a named cap
whose failure says what was being fetched, and CI keeps the built image in the Actions cache on the Dockerfile's hash."""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT.parent / ".github" / "workflows" / "trialbox-rehearse-box.yml"
DOCKERFILE = (ROOT / "tools" / "rehearse_box" / "host.Dockerfile").read_text(encoding="utf-8")
REHEARSE = (ROOT / "tools" / "rehearse_box" / "rehearse.sh").read_text(encoding="utf-8")
CACHE_ACTION = "@55cc8345863c7cc4c66a329aec7e433d2d1c52a9"
KEY = "tb-rehearsal-host-${{ hashFiles('trialbox/tools/rehearse_box/host.Dockerfile') }}"

pytestmark = pytest.mark.nodb


def _steps() -> list[dict[str, Any]]:
    doc = yaml.safe_load(WF.read_text(encoding="utf-8"))
    steps = doc["jobs"]["rehearse"]["steps"]
    assert isinstance(steps, list)
    return steps


def test_the_base_image_is_pinned_by_digest() -> None:
    froms = re.findall(r"^FROM\s+(\S+)", DOCKERFILE, re.M)
    assert froms == [froms[0]] and re.fullmatch(r"ubuntu:24\.04@sha256:[0-9a-f]{64}", froms[0]), froms


def test_every_apt_fetch_is_retried_and_bounded() -> None:
    for line in ('Acquire::Retries "5";', 'Acquire::Retries::Delay "true";', 'Acquire::http::Timeout "20";',
                 'Acquire::https::Timeout "20";'):  # fmt: skip
        assert line in DOCKERFILE, line
    run = DOCKERFILE[DOCKERFILE.index("\nRUN ") :]
    assert run.index("99-tb-bounded-fetch") < run.index("apt-get update") < run.index("apt-get install"), (
        "the bound is set before the first fetch"
    )
    # an index that was not read fails here, not as "Unable to locate package" in the install
    assert re.search(r"apt-get update [^;]*--error-on=any", DOCKERFILE)
    # nothing else in the image fetches: no curl, wget, pip or pull at build time
    assert not re.search(r"\b(curl|wget|pip3?|docker pull)\b[^\n]*(http|install|-o)", DOCKERFILE.split("FROM", 1)[1])


def test_the_cap_is_a_named_constant_and_bounds_every_attempt() -> None:
    assert re.search(r'^HOST_IMAGE_CAP_S="\$\{TB_REHEARSE_HOST_IMAGE_CAP_S:-600\}"$', REHEARSE, re.M)
    assert re.search(r"^HOST_IMAGE_ATTEMPTS=2$", REHEARSE, re.M)
    body = REHEARSE[REHEARSE.index("host_image() {") : REHEARSE.index("clear_images() {")]
    builds = [ln for ln in body.splitlines() if re.search(r"docker build \"", ln)]
    assert len(builds) == 1 and 'timeout --kill-after=30 "$HOST_IMAGE_CAP_S" docker build' in builds[0], builds
    assert "stopped at its cap of $HOST_IMAGE_CAP_S s (HOST_IMAGE_CAP_S) while fetching:" in body
    # the step stays fatal: a host image that could not be built blocks the rest of the run
    assert re.search(r"^step host-image 1 host_image$", REHEARSE, re.M)


def test_the_workflow_restores_and_saves_the_cache_on_the_dockerfiles_hash() -> None:
    steps = _steps()
    uses = [s.get("uses", "") for s in steps]
    restore = next(i for i, u in enumerate(uses) if u.startswith("actions/cache/restore@"))
    save = next(i for i, u in enumerate(uses) if u.startswith("actions/cache/save@"))
    run = next(i for i, s in enumerate(steps) if "make rehearse-box" in str(s.get("run", "")))
    assert restore < run < save
    for i in (restore, save):
        assert uses[i].endswith(CACHE_ACTION), uses[i]
        assert steps[i]["with"]["key"] == KEY
        assert steps[i]["with"]["path"] == "trialbox/.cache/rehearsal-host"
    assert steps[run]["env"]["TB_REHEARSE_HOST_CACHE"] == "${{ github.workspace }}/trialbox/.cache/rehearsal-host"
    cond = steps[save]["if"]
    assert "always()" in cond and "steps.hostcache.outputs.cache-hit != 'true'" in cond
    assert steps[restore]["id"] == "hostcache"
    # never continue-on-error, on the rehearsal or on the cache
    assert not any(s.get("continue-on-error") for s in steps)


def _harness(tmp_path: Path, docker: str, cache: Path) -> subprocess.CompletedProcess[str]:
    """host_image() from rehearse.sh alone, with a fake `docker` on PATH (no daemon here) and a 2 s cap."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "docker"
    fake.write_text("#!/usr/bin/env bash\n" + docker, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    body = REHEARSE[REHEARSE.index("host_image() {") : REHEARSE.index("clear_images() {")]
    logs = tmp_path / "logs"
    logs.mkdir()
    script = "\n".join([
        "set -uo pipefail", f"cd '{ROOT}'", 'HOST_IMG="trialbox-rehearsal-host:24.04"', f"LOGS='{logs}'",
        "HOST_IMAGE_CAP_S=2", "HOST_IMAGE_ATTEMPTS=2", 'HOST_IMAGE_LABEL="org.trialbox.rehearsal.host-dockerfile-sha256"',
        f"HOST_CACHE='{cache}'", "sleep() { :; }", body, "host_image",
    ])  # fmt: skip
    env = {k: v for k, v in os.environ.items() if k not in ("HTTPS_PROXY", "TB_EXTRA_CA")}
    env["PATH"] = f"{bindir}:{env['PATH']}"
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, timeout=60, check=False)


def test_a_build_at_its_cap_says_what_it_was_fetching(tmp_path: Path) -> None:
    calls = tmp_path / "calls"
    docker = (f'echo "$1" >> "{calls}"\n'
              'if [ "$1" = build ]; then echo "#5 3.1 Get:7 http://archive.ubuntu.com/ubuntu noble/main amd64 libssh-4"; '
              "exec sleep 30; fi\n")  # fmt: skip
    r = _harness(tmp_path, docker, tmp_path / "cache")
    assert r.returncode == 1, r.stdout + r.stderr
    assert r.stdout.count("stopped at its cap of 2 s (HOST_IMAGE_CAP_S) while fetching: ") == 2, r.stdout
    assert "Get:7 http://archive.ubuntu.com/ubuntu noble/main amd64 libssh-4" in r.stdout.splitlines()[-2]
    assert r.stdout.rstrip().endswith("did not serve the build (see above)")
    assert calls.read_text(encoding="utf-8").split() == ["build", "build"]
    assert not (tmp_path / "cache").exists(), "nothing is saved from a failed build"


def test_a_cached_image_with_this_dockerfiles_hash_is_loaded_not_built(tmp_path: Path) -> None:
    key = subprocess.run(["sha256sum", str(ROOT / "tools/rehearse_box/host.Dockerfile")], capture_output=True,
                         text=True, check=True).stdout[:64]  # fmt: skip
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / f"host-{key}.tar").write_text("synthetic image tar", encoding="utf-8")
    calls = tmp_path / "calls"
    docker = f'echo "$1" >> "{calls}"\nif [ "$1" = image ]; then echo {key}; fi\n'
    r = _harness(tmp_path, docker, cache)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "from the cache" in r.stdout and "nothing fetched" in r.stdout
    assert calls.read_text(encoding="utf-8").split() == ["load", "image"]


def test_a_cached_image_of_another_dockerfile_is_not_used(tmp_path: Path) -> None:
    key = subprocess.run(["sha256sum", str(ROOT / "tools/rehearse_box/host.Dockerfile")], capture_output=True,
                         text=True, check=True).stdout[:64]  # fmt: skip
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / f"host-{key}.tar").write_text("synthetic image tar", encoding="utf-8")
    calls = tmp_path / "calls"
    # the tar's image carries another hash: the build runs, then the new image is saved over the old tar
    docker = (f'echo "$1" >> "{calls}"\n'
              'case "$1" in image) echo 0000;; save) : > "$3";; build) echo built;; esac\n')  # fmt: skip
    r = _harness(tmp_path, docker, cache)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "did not load as" in r.stdout and "saved to" in r.stdout
    assert calls.read_text(encoding="utf-8").split() == ["load", "image", "build", "save"]
    assert sorted(p.name for p in cache.iterdir()) == [f"host-{key}.tar"]
