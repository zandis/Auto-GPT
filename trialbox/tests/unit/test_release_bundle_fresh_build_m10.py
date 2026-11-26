"""INT-M10 (min), item c: ``make release-bundle`` never ships an image built from a cache or from an unpulled base.

H-143 (``test_release_layers_uncached_h143.py``) already holds ``make release-images`` to "pull every pinned base by
digest, then build every image with --no-cache and without --pull", and the ``release-bundle`` rule to name
``release-images`` before ``release-gates``. What it does not hold, and this file does:

* the whole ``make release-bundle`` run (``make -n``), not only its ``release-images`` part: every image build of the
  run is uncached, every pull comes before the first build, the bundle is made after the last build, and the bases
  pulled are the bases of the Dockerfiles that run builds (read from the run's own ``-f`` arguments, not from a list
  kept beside the Makefile);
* every outside base of those Dockerfiles is pinned by digest, so it can be pulled at all (a base without a digest
  is never in the pull, and nothing else would say so);
* a pull that fails stops the release before any build: the pull loop's ``|| exit 1``. Run for real with a stand-in
  ``docker`` on ``PATH`` that refuses the first pull and logs every call; nothing is fetched or built.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PINNED = re.compile(r"[a-z0-9./_-]+:[^\s@\"]*@sha256:[0-9a-f]{64}")
DB_DOCKERFILE = "deploy/docker/db.Dockerfile"  # what deploy/build_db_image.sh builds (its -f)
OWN = "trialbox-"  # the box's own images, built by the same run: never pulled


def _dry_run(goal: str) -> list[str]:
    proc = subprocess.run(
        ["make", "--no-print-directory", "-n", goal, "FONTS=pyproject.toml", "TB_REVISION=x"],
        cwd=ROOT, capture_output=True, text=True, check=False, timeout=120,
    )  # fmt: skip
    assert proc.returncode == 0, proc.stderr[-2000:]
    return re.sub(r"\\\n\s*", " ", proc.stdout).splitlines()


def _is_build(line: str) -> bool:
    words = line.split()
    return bool(words) and (words[0] == "deploy/build_db_image.sh" or (words[0] == "docker" and "build" in words[1:3]))


def _dockerfile(build: str) -> str:
    words = build.split()
    if words[0] == "deploy/build_db_image.sh":
        return DB_DOCKERFILE
    return words[words.index("-f") + 1]


def _bases(dockerfile: str) -> list[str]:
    """Every image a FROM of ``dockerfile`` names, ARG defaults resolved; stage names left out."""
    text = (ROOT / dockerfile).read_text(encoding="utf-8")
    args = dict(re.findall(r"^ARG\s+([A-Za-z_][A-Za-z0-9_]*)=(\S+)", text, re.M))
    stages: set[str] = set()
    out: list[str] = []
    for ref, stage in re.findall(r"^FROM\s+(?:--platform=\S+\s+)?(\S+)(?:\s+AS\s+(\S+))?", text, re.M | re.I):
        ref = re.sub(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", lambda m: args.get(m.group(1), m.group(0)), ref)
        if ref not in stages:
            out.append(ref)
        if stage:
            stages.add(stage)
    return out


def test_the_whole_release_bundle_run_pulls_first_builds_uncached_and_bundles_last() -> None:
    run = _dry_run("release-bundle")
    builds = [i for i, ln in enumerate(run) if _is_build(ln)]
    pulls = [i for i, ln in enumerate(run) if "docker pull" in ln]
    bundle = [i for i, ln in enumerate(run) if ln.lstrip().startswith("tools/make_bundle.sh ")]
    assert builds and pulls and len(bundle) == 1, run
    assert max(pulls) < min(builds), run  # every pull before the first build
    assert bundle[0] > max(builds), run  # the bundle is made from this run's images
    for i in builds:
        words = run[i].split()
        assert "--no-cache" in words, run[i]
        assert "--pull" not in words and not any(w.startswith("--pull=") for w in words), run[i]
    pulled = {m for i in pulls for m in PINNED.findall(run[i])}
    outside = {b for i in builds for b in _bases(_dockerfile(run[i])) if not b.startswith(OWN)}
    assert outside and pulled == outside, (sorted(pulled), sorted(outside))


def test_every_outside_base_of_a_release_build_is_pinned_by_digest() -> None:
    run = _dry_run("release-bundle")
    files = sorted({_dockerfile(ln) for ln in run if _is_build(ln)})
    assert DB_DOCKERFILE in files and len(files) >= 2, files
    unpinned = [(f, b) for f in files for b in _bases(f) if not b.startswith(OWN) and not PINNED.fullmatch(b)]
    assert not unpinned, unpinned


def test_a_failed_base_pull_stops_the_release_before_any_build(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "docker.log"
    docker = bin_dir / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$*" >> "$TB_TEST_DOCKER_LOG"\n'
        'if [ "$1" = pull ]; then exit 1; fi\n'  # the registry refuses every pull
        "exit 1\n",  # and nothing else may run either: a build reached is logged, then stopped
        encoding="utf-8",
    )
    docker.chmod(docker.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}", TB_TEST_DOCKER_LOG=str(log))
    out = tmp_path / "make.out"
    with out.open("w", encoding="utf-8") as fh:
        proc = subprocess.run(
            ["make", "--no-print-directory", "release-images", "FONTS=pyproject.toml", "TB_REVISION=x"],
            cwd=ROOT, env=env, stdout=fh, stderr=subprocess.STDOUT, check=False, timeout=120,
        )  # fmt: skip
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    assert proc.returncode != 0, out.read_text(encoding="utf-8")[-2000:]
    assert [c.split()[0] for c in calls] == ["pull"], calls  # the first refused pull ends it: no other pull, no build
