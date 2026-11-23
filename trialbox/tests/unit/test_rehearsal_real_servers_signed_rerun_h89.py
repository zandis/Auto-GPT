"""The walk's blocker (the integrator's red 7089921734, the bench's run 7089913978): the install with real servers
through the bundle load and the run from the signed release.

1. install.sh exported its own TB_COMPOSE_OVERRIDE for the real servers; the run from the signed tree (``exec``)
   inherited it and refused it as a caller's. Now the value is never handed on: the signed run writes it again, and a
   value it is given is a caller's and is refused, before and after the re-run.
2. The first run stopped after its load; run again, the update path's launcher stopped on the release's own link back
   to the site's deploy/.env (tools/host_tree.py STATE), which no settings step had written yet. Such a link, with no
   site file at all, is no setting (as on a fresh box); any other link or an untrusted file stops it as before.

The harness: H-89's bench (the real installer, stand-ins for docker and nvidia-smi, a passing engine probe), with
tools/apply_update.sh a stand-in loader that does what the load does to the folder (the release, ``current``, the
installer a link into the release, the release's back-links) and calls the update path's launcher check on the
release's deploy folder. The engine stand-in stops the signed run at its image check, after every rehearsal step.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.unit.test_rehearsal_real_servers_h89 import ROOT, Bench
from tools.trialbox import launch

STOP = "install: the bundle carried no trialbox-py:1.0.0 image"
REFUSED = "install: --rehearsal-real-servers writes the box's compose override itself: unset TB_COMPOSE_OVERRIDE"
SIGNED = "continuing from the signed release"

# the loader: what tools/apply_update.sh does to the folder (tools/host_tree.py install), then the update path's
# launcher check of the box file, as python3 -m tools.trialbox update runs it from inside the release
LOADER = r"""#!/bin/sh
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
[ "${2:-}" = --dry-run ] && exit 0
echo "load $*" >> "$TB_TEST_LOG"
rel="$ROOT/releases/r1"
mkdir -p "$rel/deploy"
cp "$ROOT/deploy/install.sh.signed" "$rel/deploy/install.sh"
for s in .env settings.yaml site keys; do ln -sfn "../../../deploy/$s" "$rel/deploy/$s"; done
ln -sfn releases/r1 "$ROOT/current"
ln -sfn ../current/deploy/install.sh "$ROOT/deploy/install.sh"
python3 -c 'import sys; from pathlib import Path; from tools.trialbox import launch; launch.box_file(Path(sys.argv[1]))' \
  "$rel/deploy"
echo "update r1 loaded"
"""
# the engine: no volumes, a version, the nvidia runtime; its image is there for the first run only (the stop)
DOCKER = r"""#!/bin/sh
echo "$*" >> "$TB_TEST_LOG"
case "$1 $2" in
  "volume ls") exit 0 ;;
  "version --format") echo 27.0; exit 0 ;;
  "image inspect") [ -z "${TB_INSTALL_SIGNED:-}" ]; exit $? ;;
esac
echo "Runtimes: nvidia runc"
"""


def rerun_bench(tmp: Path, **bench: str) -> Bench:
    b = Bench(tmp, **bench)  # type: ignore[arg-type]
    (b.deploy / "keys").mkdir()
    (b.deploy / "keys" / "vendor_ed25519.pub").write_text("stand-in key\n", encoding="utf-8")
    signed = (b.deploy / "install.sh").read_bytes()
    (b.deploy / "install.sh.signed").write_bytes(signed)  # the signed release's installer: the same bytes
    (tmp / "tools").unlink()
    (tmp / "tools").mkdir()
    for entry in (ROOT / "tools").iterdir():
        if entry.name not in ("apply_update.sh", "__pycache__"):
            (tmp / "tools" / entry.name).symlink_to(entry)
    for name, text in (("tools/apply_update.sh", LOADER), ("bin/docker", DOCKER)):
        (tmp / name).write_text(text, encoding="utf-8")
        (tmp / name).chmod(0o755)
    for name in ("libs", "services"):
        (tmp / name).symlink_to(ROOT / name)
    return b


def run(b: Bench, *given: str, **extra: str) -> subprocess.CompletedProcess[str]:
    env = {**b.env(**extra), "PYTHONPATH": f"{b.tmp / 'libs'}:{b.tmp}"}
    args = list(given) or ["--rehearsal", "--rehearsal-real-servers", "--gpu", "rtxpro6000", "--gpu-index", "1",
                           "--engine-probe", str(b.probe), "--yes"]  # fmt: skip
    return subprocess.run(["bash", str(b.deploy / "install.sh"), str(b.tmp / "b.tar"), *args], cwd=b.tmp,
                          capture_output=True, text=True, env=env, timeout=180, check=False)  # fmt: skip


def test_the_real_servers_install_goes_through_the_load_and_the_signed_rerun(tmp_path: Path) -> None:
    b = rerun_bench(tmp_path)
    r = run(b)
    out = r.stdout + r.stderr
    assert SIGNED in out and REFUSED not in out, out
    assert r.stderr.splitlines()[-1] == STOP, out  # the signed run's every rehearsal step passed: the stand-in stops it
    assert out.count("WARN  NVIDIA driver 575.57.08") == 2  # the card, driver and probe judged again by the signed run
    assert out.count("card 1: NVIDIA B200, 180000 MiB free") == 2
    override = (b.deploy / "site" / "rehearsal-real-servers.yml").read_text(encoding="utf-8")
    assert "x-trialbox-rehearsal-real-servers: true" in override.splitlines()


@pytest.mark.parametrize("signed", [False, True])
def test_a_callers_own_override_is_refused_before_and_after_the_rerun(tmp_path: Path, signed: bool) -> None:
    """Before: the first run. After: a caller who names the release ``current`` names as TB_INSTALL_SIGNED (the
    signed run's own marker) still gets the refusal for an override of their own."""
    b = rerun_bench(tmp_path)
    extra = {"TB_COMPOSE_OVERRIDE": str(tmp_path / "mine.yml")}
    if signed:
        assert run(b).stderr.splitlines()[-1] == STOP  # the box now has its release
        extra["TB_INSTALL_SIGNED"] = os.readlink(b.tmp / "current")
    r = run(b, **extra)
    assert r.returncode == 1 and r.stderr.splitlines()[-1] == REFUSED, r.stdout + r.stderr
    assert SIGNED not in r.stdout


def test_without_the_mark_a_callers_override_reaches_the_signed_run_as_before(tmp_path: Path) -> None:
    """A plain rehearsal with an override of the caller's (D-176): both runs use it, as on master."""
    b = rerun_bench(tmp_path, driver="580.95.05")
    mine = tmp_path / "mine.yml"
    r = run(b, "--rehearsal", "--mode", "gpu", "--gpu", "rtxpro6000", "--yes", TB_COMPOSE_OVERRIDE=str(mine))
    note = f"install: note: a rehearsal box (TB_ENV VALIDATION, {mine}, an unmeasured card accepted)"
    assert SIGNED in r.stdout and r.stderr.splitlines().count(note) == 2, r.stdout + r.stderr
    assert r.stderr.splitlines()[-1] == STOP


def test_a_first_install_stopped_after_its_load_runs_again(tmp_path: Path) -> None:
    """The bench's second fault: the first run stopped in the signed run (here: the engine stand-in), before the
    settings step wrote deploy/.env; run again, it loads, and goes on to the signed run."""
    b = rerun_bench(tmp_path)
    first = run(b)
    assert first.stderr.splitlines()[-1] == STOP and not os.path.lexists(b.deploy / ".env")
    assert os.path.islink(b.tmp / "releases" / "r1" / "deploy" / ".env")  # the release's back-link, dangling
    again = run(b)
    out = again.stdout + again.stderr
    assert "cannot be read" not in out and "loading the bundle failed" not in out, out
    assert "update r1 loaded" in out and SIGNED in out and again.stderr.splitlines()[-1] == STOP, out


# ------------------------------------------------------------------------------------- the launcher's rule kept
def _release(tmp: Path) -> tuple[Path, Path]:
    """BASE/deploy (the site's) and BASE/releases/r1/deploy with its back-link to the site's deploy/.env."""
    site = tmp / "deploy"
    site.mkdir()
    rel = tmp / "releases" / "r1" / "deploy"
    rel.mkdir(parents=True)
    (rel / ".env").symlink_to("../../../deploy/.env")
    return site, rel


def test_a_release_back_link_with_no_site_file_is_no_setting(tmp_path: Path) -> None:
    _, rel = _release(tmp_path)
    assert launch.box_file(rel) == {}


def test_a_release_back_link_to_a_site_file_reads_it(tmp_path: Path) -> None:
    site, rel = _release(tmp_path)
    (site / ".env").write_text("TB_ENV=VALIDATION\n", encoding="utf-8")
    (site / ".env").chmod(0o600)
    assert launch.box_file(rel) == {"TB_ENV": "VALIDATION"}


@pytest.mark.parametrize("case", ["writable", "dangling site link", "another link", "not a release"])
def test_any_other_box_file_that_cannot_be_trusted_still_stops(tmp_path: Path, case: str) -> None:
    site, rel = _release(tmp_path)
    if case == "writable":
        (site / ".env").write_text("TB_ENV=TEST\n", encoding="utf-8")
        (site / ".env").chmod(0o666)
        why = "can be written by group or others"
    elif case == "dangling site link":  # the site's own file is there, as a dangling link: judged as before
        (site / ".env").symlink_to(tmp_path / "nowhere")
        why = "cannot be read"
    elif case == "another link":
        (rel / ".env").unlink()
        (rel / ".env").symlink_to(tmp_path / "nowhere")
        why = "cannot be read"
    else:
        other = tmp_path / "kept" / "r1" / "deploy"  # the same shape outside releases/
        other.mkdir(parents=True)
        (other / ".env").symlink_to("../../../deploy/.env")
        rel = other
        why = "cannot be read"
    with pytest.raises(launch.BoxFileError, match=why):
        launch.box_file(rel)
