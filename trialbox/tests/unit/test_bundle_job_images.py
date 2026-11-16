"""A bundle's job images (PERF-010 R1, D-968): an image the box runs as a one-off job, not as a compose service.

The nightly backup's image (``trialbox-backup``) is in the bundle but no box container runs it between nights. The
bundle's own signed ``release.json`` says so (``runs: job``; every other image ``runs: service``), and the box
rehearsal's offline step reads that: a service image must be run by a box container as before; a job image must be
loaded on the box with exactly the bundle's image id (loaded from the media, since the images were removed by id and
nothing was pulled). No list of images in the rehearsal script or in this test decides which image is a job.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_release_bundle import (  # noqa: F401
    BACKUP,
    HAPI,
    OWN,
    VLLM,
    _archive,
    _gate_record,
    _make,
    kit,
)
from tools import release

ROOT = Path(__file__).resolve().parents[2]
BOX_SH = ROOT / "tools" / "rehearse_box" / "box.sh"
REHEARSE_SH = ROOT / "tools" / "rehearse_box" / "rehearse.sh"


def _release_json(bundle: Path) -> dict[str, Any]:
    with tarfile.open(bundle) as tf:
        rel: dict[str, Any] = json.loads(tf.extractfile("release.json").read())  # type: ignore[union-attr]
    return rel


def test_the_backup_image_is_a_job_image_of_the_bundle(kit: dict[str, Any]) -> None:  # noqa: F811
    """make_bundle names the backup image itself (no compose service runs it) and marks it a job in release.json."""
    gates, sbom = _gate_record(kit["tmp"], [*OWN, BACKUP, HAPI, VLLM])
    res = _make(kit, "--release-seq", "1", "--gates", str(gates), "--sbom-dir", str(sbom))
    assert res.returncode == 0, res.stdout + res.stderr
    rel = _release_json(kit["tmp"] / "out.tar")
    assert {n: i["runs"] for n, i in rel["images"].items()} == {
        "py": "service", "backup": "job", "jvm": "service", "db": "service", "hapi": "service",
        "vllm-openai": "service",
    }  # fmt: skip
    assert release.check_bundle(kit["tmp"] / "out.tar") == []


def test_a_job_image_named_on_the_command_line_is_a_job(kit: dict[str, Any]) -> None:  # noqa: F811
    """--job-image, as the box rehearsal passes its images by name: in the bundle, and a job in release.json."""
    gates, sbom = _gate_record(kit["tmp"], [*OWN, BACKUP, HAPI])
    args = [a for ref in (*OWN, HAPI) for a in ("--image", ref)]
    res = _make(kit, "--release-seq", "1", "--gates", str(gates), "--sbom-dir", str(sbom), *args,
                "--job-image", BACKUP)  # fmt: skip
    assert res.returncode == 0, res.stdout + res.stderr
    rel = _release_json(kit["tmp"] / "out.tar")
    assert rel["images"]["backup"]["runs"] == "job"
    assert {i["runs"] for n, i in rel["images"].items() if n != "backup"} == {"service"}


def test_release_build_refuses_a_job_that_is_not_an_image_of_the_bundle(tmp_path: Path) -> None:
    gates, sbom = _gate_record(tmp_path, ["trialbox-py:1.0.0"])
    archive = _archive(tmp_path / "py.tar", "trialbox-py:1.0.0", config=_cfg("trialbox-py"))
    with pytest.raises(release.ReleaseError, match="trialbox-backup:1.0.0.*not an image of the bundle"):
        release.build(release_id="r1", release_seq=1, gates=gates, sbom_dir=sbom, out_dir=tmp_path / "meta",
                      images=[("trialbox-py:1.0.0", archive)], items=[("image", archive, "py.tar")],
                      jobs=["trialbox-backup:1.0.0"])  # fmt: skip
    assert not (tmp_path / "meta" / "release.json").exists()


def _cfg(repo: str) -> str:
    import hashlib

    return hashlib.sha256(repo.encode()).hexdigest()


# ---------------------------------------------------------------------------------------------- the offline step


def _offline_check() -> str:
    """The python the rehearsal's offline step runs over the bundle's images (box.sh, step 12)."""
    text = BOX_SH.read_text(encoding="utf-8")
    block = text[text.index("\noffline)") :]
    m = re.search(r"<<'EOF' \|\| fail \"an image is not the bundle's\"\n(.*?)\nEOF\n", block, re.S)
    assert m, "the offline step's image check is not where this test looks"
    return m.group(1)


FAKE_DOCKER = r"""#!PYTHON
import json, os, sys
state = json.load(open(os.environ["FAKE_STATE"]))
a = sys.argv[1:]
if a[:1] == ["ps"]:
    print("\n".join(c["Id"] for c in state["containers"]))
elif a[:2] == ["inspect"] or a[:1] == ["inspect"]:
    ids = a[1:]
    print(json.dumps([c for c in state["containers"] if c["Id"] in ids]))
elif a[:2] == ["image", "inspect"]:
    ref = a[-1]
    if ref not in state["loaded"]:
        sys.exit(f"Error: No such image: {ref}")
    print(state["loaded"][ref])
else:
    sys.exit(f"fake docker: {a}")
"""


def _ct(cid: str, svc: str, ref: str, iid: str) -> dict[str, Any]:
    return {"Id": cid, "Image": iid, "Config": {"Image": ref, "Labels": {"com.docker.compose.service": svc}}}


def _bundle(path: Path, runs: dict[str, str]) -> Path:
    rel = {"images": {ref.split(":")[0]: {"source": ref, "image": ref, "runs": r} for ref, r in runs.items()}}
    data = json.dumps(rel).encode()
    with tarfile.open(path, "w") as tf:
        info = tarfile.TarInfo("release.json")
        info.size = len(data)
        import io

        tf.addfile(info, io.BytesIO(data))
    return path


def _run_offline(tmp: Path, *, runs: dict[str, str], loaded: dict[str, str], containers: list[dict[str, Any]],
                 pulls: str = "") -> subprocess.CompletedProcess[str]:  # fmt: skip
    ids = {"trialbox-py:1.0.0": "sha256:" + "1" * 64, "trialbox-backup:1.0.0": "sha256:" + "2" * 64}
    (tmp / "bundle-images.txt").write_text("".join(f"{r} {ids[r]}\n" for r in runs), encoding="utf-8")
    (tmp / "image-events.log").write_text(pulls, encoding="utf-8")
    (tmp / "state.json").write_text(json.dumps({"containers": containers, "loaded": loaded}), encoding="utf-8")
    bindir = tmp / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "docker").write_text(FAKE_DOCKER.replace("PYTHON", sys.executable), encoding="utf-8")
    (bindir / "docker").chmod(0o755)
    bundle = _bundle(tmp / "bundle.tar", runs)
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}", "FAKE_STATE": str(tmp / "state.json")}
    return subprocess.run(
        [sys.executable, "-", str(tmp / "bundle-images.txt"), str(tmp / "image-events.log"), str(bundle)],
        input=_offline_check(),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


PY_ID, BK_ID = "sha256:" + "1" * 64, "sha256:" + "2" * 64
RUNS = {"trialbox-py:1.0.0": "service", "trialbox-backup:1.0.0": "job"}


def test_a_job_image_loaded_from_the_media_passes_without_a_container(tmp_path: Path) -> None:
    res = _run_offline(tmp_path, runs=RUNS, loaded={"trialbox-backup:1.0.0": BK_ID},
                       containers=[_ct("c1", "console", "trialbox-py:1.0.0", PY_ID)])  # fmt: skip
    assert res.returncode == 0, res.stdout + res.stderr
    assert "job image" in res.stdout and "trialbox-backup:1.0.0" in res.stdout


def test_a_job_image_with_another_id_on_the_box_fails(tmp_path: Path) -> None:
    res = _run_offline(tmp_path, runs=RUNS, loaded={"trialbox-backup:1.0.0": "sha256:" + "9" * 64},
                       containers=[_ct("c1", "console", "trialbox-py:1.0.0", PY_ID)])  # fmt: skip
    assert res.returncode != 0
    assert "trialbox-backup:1.0.0" in res.stderr and "not the bundle's" in res.stderr


def test_a_job_image_missing_on_the_box_fails(tmp_path: Path) -> None:
    res = _run_offline(tmp_path, runs=RUNS, loaded={},
                       containers=[_ct("c1", "console", "trialbox-py:1.0.0", PY_ID)])  # fmt: skip
    assert res.returncode != 0
    assert "trialbox-backup:1.0.0" in res.stderr


def test_a_service_image_no_container_runs_still_fails(tmp_path: Path) -> None:
    """The step is as strict as before for every image the bundle does not mark a job."""
    res = _run_offline(tmp_path, runs={**RUNS, "trialbox-backup:1.0.0": "service"},
                       loaded={"trialbox-backup:1.0.0": BK_ID},
                       containers=[_ct("c1", "console", "trialbox-py:1.0.0", PY_ID)])  # fmt: skip
    assert res.returncode != 0
    assert "trialbox-backup:1.0.0: in the bundle, but no box container runs it" in res.stderr


def test_an_image_the_release_does_not_mark_is_a_service(tmp_path: Path) -> None:
    """A bundle built before runs existed: no exemption for anything."""
    rel_runs = {"trialbox-py:1.0.0": "service", "trialbox-backup:1.0.0": ""}
    res = _run_offline(tmp_path, runs=rel_runs, loaded={"trialbox-backup:1.0.0": BK_ID},
                       containers=[_ct("c1", "console", "trialbox-py:1.0.0", PY_ID)])  # fmt: skip
    assert res.returncode != 0
    assert "no box container runs it" in res.stderr


def test_a_pull_still_fails(tmp_path: Path) -> None:
    res = _run_offline(
        tmp_path,
        runs=RUNS,
        loaded={"trialbox-backup:1.0.0": BK_ID},
        containers=[_ct("c1", "console", "trialbox-py:1.0.0", PY_ID)],
        pulls="pull x trialbox-py\n",
    )
    assert res.returncode != 0 and "pulled" in res.stderr


def test_no_list_of_job_images_in_the_rehearsal_scripts() -> None:
    """Which image is a job comes from the bundle's release.json, never from a name in the step itself."""
    check = _offline_check()
    assert "trialbox-backup" not in check and '"runs"' in check and "release.json" in check
    # the rehearsal passes the backup image to make_bundle as a job, as make_bundle's own default does
    assert "--job-image" in REHEARSE_SH.read_text(encoding="utf-8")
