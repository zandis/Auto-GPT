"""ENG-003 / HW-002 (D-563): a PRODUCTION box starts its embed service.

The box's own compose file starts ``embed-service`` from the ``trialbox-embed`` image with ``TB_ENV=PRODUCTION``, a
weights folder pinned by the installer's own call (``pin_model --install``) and no stub. The folder is a tiny model
in the publisher's format, made on the spot inside the image (``tools.tiny_embedder``): no model is downloaded.
The service must come up healthy, name the pinned weights, embed one sentence, and refuse to start on other weights.

Marker ``integration`` (``TB_INTEGRATION=1``; needs Docker and the images of ``make images``): the nightly compose
job (``make test-compose``, no skip allowed) and ``make embed-start``. Synthetic text only.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
IMAGE = os.environ.get("TB_EMBED_IMAGE") or "trialbox-embed:1.0.0"
BUILD = "e-embed-1"
TOKEN = "embed-start-test-token-not-a-secret"  # a test stack's token, made here, used nowhere else

pytestmark = [pytest.mark.integration, pytest.mark.nodb]  # Docker only: no test database


def _run(argv: list[str], check: bool = True, **kw: object) -> subprocess.CompletedProcess[str]:
    r = subprocess.run(argv, capture_output=True, text=True, check=False, **kw)  # type: ignore[call-overload]
    if check and r.returncode != 0:
        raise AssertionError(f"{' '.join(argv[:6])} ... exit {r.returncode}\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}")
    return r  # type: ignore[no-any-return]


def _in_image(
    work: Path, *cmd: str, registry: Path | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """One command in the embed image, with this checkout's code over the image's and the work folder at /work."""
    mounts = [x for name in ("tools", "services", "libs", "models") for x in ("-v", f"{ROOT / name}:/app/{name}:ro")]
    if registry is not None:
        mounts += ["-v", f"{registry}:/app/models/registry.yaml:ro"]
    return _run(["docker", "run", "--rm", "--network", "none", *mounts, "-v", f"{work}:/work", IMAGE, *cmd], check)


@pytest.fixture(scope="module")
def box(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, object]]:
    if os.environ.get("TB_INTEGRATION") != "1":
        pytest.skip("needs Docker and the images of `make images` (TB_INTEGRATION=1; `make embed-start`)")
    if shutil.which("docker") is None or _run(["docker", "image", "inspect", IMAGE], check=False).returncode != 0:
        pytest.skip(f"the image {IMAGE} is not built here (`make images`)")
    work = tmp_path_factory.mktemp("embed-start")
    work.chmod(0o777)  # the image's user (uid 10001) writes the folders below
    deploy = work / "deploy"
    for d in (deploy, deploy / "models", deploy / "site"):
        d.mkdir()
        d.chmod(0o777)
    _in_image(work, "python", "-m", "tools.tiny_embedder", "--out", "/work/deploy/models/embedder")
    out = _in_image(work, "python", "-c", "from pathlib import Path; from embed_service.embedder import "
                    "manifest_sha256; print(manifest_sha256(Path('/work/deploy/models/embedder')))")  # fmt: skip
    manifest = out.stdout.strip().splitlines()[-1]
    # the registry as it will read once the real folder's manifest is written: here the tiny folder's
    committed = (ROOT / "models" / "registry.yaml").read_text(encoding="utf-8")
    row = committed.index(f"build_id: {BUILD}")
    head, tail = (
        committed[:row],
        re.sub(r"manifest_sha256: (?:[0-9a-f]{64}|null)", f"manifest_sha256: {manifest}", committed[row:], count=1),
    )
    registry = work / "registry.yaml"
    registry.write_text(head + tail, encoding="utf-8")
    shutil.copy(ROOT / "deploy" / "settings.example.yaml", deploy / "settings.example.yaml")
    (deploy / ".env").write_text(
        f"TB_ENV=PRODUCTION\nTB_TZ=Asia/Taipei\nPOSTGRES_PASSWORD=unused-here\nTB_SERVICE_TOKEN={TOKEN}\n",
        encoding="utf-8",
    )
    project = f"tbembed{uuid.uuid4().hex[:8]}"
    compose = ["docker", "compose", "-p", project, "--project-directory", str(deploy),
               "-f", str(ROOT / "deploy" / "docker-compose.yml")]  # fmt: skip
    try:
        yield {"work": work, "deploy": deploy, "registry": registry, "manifest": manifest, "compose": compose}
    finally:
        _run([*compose, "down", "-v", "--remove-orphans"], check=False)


def _pin(box: dict[str, object]) -> subprocess.CompletedProcess[str]:
    """The installer's own call (deploy/install.sh): the pair's folders are not here, the embedder's is."""
    return _in_image(box["work"], "python", "-m", "tools.pin_model", "--install", "rtxpro6000", "--models-root",  # type: ignore[arg-type]
                     "/work/deploy/models", "--out", "/work/deploy/site/registry.site.yaml",
                     registry=box["registry"], check=False)  # type: ignore[arg-type]  # fmt: skip


def _up(box: dict[str, object]) -> subprocess.CompletedProcess[str]:
    return _run([*box["compose"], "up", "-d", "--wait", "--no-deps", "embed-service"], check=False)  # type: ignore[misc]


def _logs(box: dict[str, object]) -> str:
    r = _run([*box["compose"], "logs", "--tail", "60", "embed-service"], check=False)  # type: ignore[misc]
    return r.stdout + r.stderr


def test_without_a_pin_the_production_embed_service_refuses_to_start(box: dict[str, object]) -> None:
    """D-429 holds with the real image: weights in place and no pin is not a start."""
    r = _up(box)
    logs = _logs(box)
    _run([*box["compose"], "down", "-v"], check=False)  # type: ignore[misc]
    assert r.returncode != 0 and f"no pin for {BUILD}" in logs, logs[-1500:]


def test_the_installers_pin_call_pins_the_embedder_with_the_pair(box: dict[str, object]) -> None:
    r = _pin(box)
    line = next(ln for ln in r.stdout.splitlines() if ln.startswith(f"{BUILD}:"))
    assert f"pinned {str(box['manifest'])[:12]}" in line and "on embed" in line, r.stdout


def test_a_production_box_starts_the_embed_service_and_embeds_one_sentence(box: dict[str, object]) -> None:
    _pin(box)
    r = _up(box)
    assert r.returncode == 0, r.stderr[-1500:] + _logs(box)[-1500:]
    code = (
        "import json, sys, urllib.request\n"
        "base = 'http://127.0.0.1:8014'\n"
        "print(urllib.request.urlopen(base + '/healthz', timeout=10).read().decode())\n"
        "req = urllib.request.Request(base + '/embed', data=json.dumps({'texts': ['patient with gout and fever']})"
        ".encode(), headers={'content-type': 'application/json', 'X-TB-Service-Token': sys.argv[1]})\n"
        "print(urllib.request.urlopen(req, timeout=60).read().decode())\n"
    )
    out = _run([*box["compose"], "exec", "-T", "embed-service", "python", "-c", code, TOKEN])  # type: ignore[misc]
    health, answer = (json.loads(ln) for ln in out.stdout.strip().splitlines()[-2:])
    assert health["status"] == "ok"
    assert health["checks"] == {"model": BUILD, "weights": str(box["manifest"])[:12]}
    assert answer["model"] == BUILD and answer["dim"] == len(answer["vectors"][0]) == 32
    env = _run([*box["compose"], "exec", "-T", "embed-service", "env"]).stdout  # type: ignore[misc]
    assert "TB_ENV=PRODUCTION" in env and "TB_EMBED_MODE=" not in env  # the product's setting, no stub override


def test_other_weights_than_the_pinned_ones_are_refused_at_the_next_start(box: dict[str, object]) -> None:
    _pin(box)
    _run([*box["compose"], "down", "-v"], check=False)  # type: ignore[misc]
    extra = Path(str(box["deploy"])) / "models" / "embedder" / "added.json"
    _in_image(box["work"], "python", "-c",  # type: ignore[arg-type]
              "from pathlib import Path; Path('/work/deploy/models/embedder/added.json').write_text('{}')")  # fmt: skip
    try:
        r = _up(box)
        logs = _logs(box)
        assert r.returncode != 0 and "not the pinned weights" in logs, logs[-1500:]
    finally:
        _run([*box["compose"], "down", "-v"], check=False)  # type: ignore[misc]
        _in_image(box["work"], "python", "-c",  # type: ignore[arg-type]
                  "from pathlib import Path; Path('/work/deploy/models/embedder/added.json').unlink()")  # fmt: skip
        assert not extra.exists()
