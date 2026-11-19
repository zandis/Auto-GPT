"""Card 24-7 (root review 24): `TB_POC_EMBED=model deploy/poc.sh` is "stub judge, real embedder".

The one-command start serves the pinned embedder ``e-embed-1`` on the CPU from ``deploy/models/embedder`` in place of
the hash embedder the PoC overlay gives a synthetic stack: it checks the folder before anything is written, builds
the embedder's image on the builder path, pins the folder with the embedder-only pin (``--install-embedder``) and
checks it again, and passes the image and the mode to compose. It refuses a missing folder, a folder that is not the
pinned build (no weights, pickle files), the GPU mode, and a lake embedded by the other embedder. The choice is kept
in deploy/.env. No weights are downloaded: the folder here is a fake one, and docker is a stand-in that records its
calls (the pin's manifest check itself is pin_model's, tested in test_embed_review.py)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.nodb

# docker stand-in: `volume inspect` fails unless TB_TEST_LAKE=1 (no lake volume yet); `image inspect` of the embed
# image fails when TB_TEST_NO_EMBED_IMAGE=1; everything else succeeds and is recorded with the environment compose sees
DOCKER = r"""#!/bin/sh
echo "$* | TB_EMBED_IMAGE=${TB_EMBED_IMAGE:-} TB_EMBED_MODE=${TB_EMBED_MODE:-} TB_MODELS_DIR=${TB_MODELS_DIR:-}" >> "$TB_TEST_LOG"
case "$1 $2" in
  "volume inspect") [ "${TB_TEST_LAKE:-0}" = 1 ] && exit 0 || exit 1 ;;
  "image inspect") case "$*" in *trialbox-embed*) [ "${TB_TEST_NO_EMBED_IMAGE:-0}" = 1 ] && exit 1 ;; esac; exit 0 ;;
esac
case "$*" in *--install-embedder*) [ "${TB_TEST_PIN_FAILS:-0}" = 1 ] && exit 1 ;; esac
exit 0
"""


def _root(tmp: Path, weights: str = "good") -> Path:
    root = tmp / "root"
    (root / "deploy").mkdir(parents=True)
    for rel in ("deploy/poc.sh", "deploy/gpu_profile.sh", "deploy/docker-compose.poc.yml", ".env.example"):
        shutil.copy2(ROOT / rel, root / rel)
    emb = root / "deploy/models/embedder"
    if weights != "none":
        emb.mkdir(parents=True)
        (emb / "config.json").write_text("{}", encoding="utf-8")
        if weights != "no-safetensors":
            (emb / "model.safetensors").write_bytes(b"synthetic, not weights")
        if weights == "pickle":
            (emb / "pytorch_model.bin").write_bytes(b"synthetic pickle")
    return root


def _run(tmp: Path, root: Path, *args: str, **env: str) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bindir = tmp / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "docker").write_text(DOCKER, encoding="utf-8")
    (bindir / "docker").chmod(0o755)
    log = tmp / "docker.log"
    full = {k: v for k, v in os.environ.items() if not k.startswith("TB_")}
    # no mvn on this PATH: the builder-container path, as on the owner's machine
    full.update(PATH=f"{bindir}:/usr/bin:/bin", TB_TEST_LOG=str(log), TB_POC_SKIP_INGEST="1", TB_POC_ALIVE_S="600",
                **env)  # fmt: skip
    res = subprocess.run(["bash", str(root / "deploy/poc.sh"), *args], capture_output=True, text=True, env=full,
                         timeout=120, check=False)  # fmt: skip
    return res, (log.read_text(encoding="utf-8").splitlines() if log.exists() else [])


def _first(log: list[str], *words: str) -> int:
    return next(i for i, line in enumerate(log) if all(w in line for w in words))


def test_the_switch_builds_pins_and_starts_the_real_embedder(tmp_path: Path) -> None:
    root = _root(tmp_path)
    res, log = _run(tmp_path, root, TB_POC_EMBED="model", TB_POC_BUILD="1")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "ok    embedder folder" in res.stdout
    # the builder path builds the embedder's image after the service image it is built on
    py = _first(log, "build", "python.Dockerfile")
    emb = _first(log, "build", "embed.Dockerfile", "trialbox-embed:1.0.0")
    assert py < emb
    # the embedder-only pin into the PoC's site folder, then the check of the folder against it, before compose up
    pin = _first(log, "pin_model --install-embedder", "--out /d/poc/site/registry.site.yaml")
    ver = _first(log, "pin_model --verify --build e-embed-1", "--model-dir /m/embedder")
    up = _first(log, "compose", " up -d ")
    assert pin < ver < up
    assert f"{root}/deploy/models:/m:ro" in log[pin]
    # compose sees the embed image, the mode and the models folder that holds the pinned weights
    assert f"TB_EMBED_IMAGE=trialbox-embed:1.0.0 TB_EMBED_MODE=model TB_MODELS_DIR={root}/deploy/models" in log[up]
    assert "docker-compose.poc.yml" in log[up] and "--profile stub" in log[up]
    # kept for every later start
    assert "TB_POC_EMBED=model" in (root / "deploy/.env").read_text(encoding="utf-8").splitlines()
    assert "model embedder" in res.stdout


def test_existing_images_still_get_the_embedder_image_built(tmp_path: Path) -> None:
    root = _root(tmp_path)
    res, log = _run(tmp_path, root, TB_POC_EMBED="model", TB_TEST_NO_EMBED_IMAGE="1")
    assert res.returncode == 0, res.stdout + res.stderr
    assert not any("python.Dockerfile" in line for line in log)  # the other images are there: not rebuilt
    assert any("build -f deploy/docker/embed.Dockerfile -t trialbox-embed:1.0.0" in line for line in log)


@pytest.mark.parametrize(
    ("weights", "said"),
    [
        ("none", "no embedder weights in"),
        ("no-safetensors", "is not the pinned build e-embed-1 (no config.json or no model.safetensors)"),
        ("pickle", "holds pickle or code files"),
    ],
)
def test_a_missing_or_wrong_folder_is_refused_before_anything_is_written(
    tmp_path: Path, weights: str, said: str
) -> None:
    root = _root(tmp_path, weights)
    res, log = _run(tmp_path, root, TB_POC_EMBED="model")
    assert res.returncode == 1
    assert said in res.stderr
    assert not (root / "deploy/.env").exists()
    assert not any("build -f" in line or " up -d " in f" {line} " or "pin_model" in line for line in log)


def test_a_folder_the_pin_refuses_stops_the_start(tmp_path: Path) -> None:
    """The fake folder passes the shape check; the pin refuses it (as pin_model does on another manifest), and the
    start stops before compose."""
    root = _root(tmp_path)
    res, log = _run(tmp_path, root, TB_POC_EMBED="model", TB_TEST_PIN_FAILS="1")
    assert res.returncode == 1, res.stdout
    assert "the embedder could not be pinned" in res.stderr and "not the pinned build e-embed-1" in res.stderr
    assert not any(" up -d " in f" {line} " for line in log)
    # review of #1100, item 10: a failed pin leaves no kept choice behind (a later plain start stays on the hash one)
    assert "TB_POC_EMBED" not in (root / "deploy/.env").read_text(encoding="utf-8")


def test_gpu_mode_and_a_bad_word_are_refused(tmp_path: Path) -> None:
    root = _root(tmp_path)
    res, _ = _run(tmp_path, root, TB_POC_EMBED="maybe")
    assert res.returncode == 1 and "TB_POC_EMBED must be hash or model" in res.stderr
    res, _ = _run(tmp_path, root, TB_POC_EMBED="model", TB_LLM_MODE="gpu", TB_GPU_PROFILE="rtxpro6000",
                  TB_POC_MIN_FREE_GB="0")  # fmt: skip
    assert res.returncode == 1  # the GPU checks or the embedder's refusal: either way nothing starts


def test_a_lake_embedded_by_the_other_embedder_is_refused(tmp_path: Path) -> None:
    root = _root(tmp_path)
    # the stub start of runbook 28 ran first: a lake volume and no kept choice (the hash embedder)
    res, log = _run(tmp_path, root, TB_POC_EMBED="model", TB_TEST_LAKE="1")
    assert res.returncode == 1 and "deploy/poc.sh reset" in res.stderr and "hash embedder" in res.stderr
    assert not any(" up -d " in f" {line} " for line in log)
    # after a reset (no lake volume) the switch is accepted and kept; a later plain start keeps the real embedder
    res, _ = _run(tmp_path, root, TB_POC_EMBED="model")
    assert res.returncode == 0, res.stderr
    res, log = _run(tmp_path, root, TB_TEST_LAKE="1")
    assert res.returncode == 0, res.stderr
    assert "TB_EMBED_MODE=model" in log[_first(log, "compose", " up -d ")]
    # going back to the hash embedder over that lake is refused the same way
    res, _ = _run(tmp_path, root, TB_POC_EMBED="hash", TB_TEST_LAKE="1")
    assert res.returncode == 1 and "embedded with the model embedder" in res.stderr


def test_without_the_switch_nothing_changes(tmp_path: Path) -> None:
    root = _root(tmp_path, "none")
    res, log = _run(tmp_path, root, TB_TEST_LAKE="1")
    assert res.returncode == 0, res.stderr
    assert "TB_POC_EMBED" not in (root / "deploy/.env").read_text(encoding="utf-8")
    assert not any("embed.Dockerfile" in line or "pin_model" in line for line in log)
    assert "TB_EMBED_IMAGE= TB_EMBED_MODE= " in log[_first(log, "compose", " up -d ")]


def test_the_overlay_passes_the_mode_and_keeps_the_hash_default() -> None:
    svc = yaml.safe_load((ROOT / "deploy/docker-compose.poc.yml").read_text(encoding="utf-8"))["services"]
    emb = svc["embed-service"]
    assert emb["environment"]["TB_EMBED_MODE"] == "${TB_EMBED_MODE:-hash}"
    assert emb["image"] == "${TB_EMBED_IMAGE:-trialbox-py:1.0.0}"
    assert "TB_EMBED_MODE=hash" in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()


def test_the_start_refuses_what_the_embed_service_refuses() -> None:
    """The start's folder check names every suffix the service itself refuses (it would refuse them at start)."""
    from embed_service.embedder import REFUSED_SUFFIXES

    text = (ROOT / "deploy/poc.sh").read_text(encoding="utf-8")
    for suffix in REFUSED_SUFFIXES:
        assert f"-iname '*{suffix}'" in text, suffix


def test_the_manual_download_excludes_each_pickle_file_with_its_own_flag() -> None:
    """Review of #1100, item 2: `--exclude a b c` is read by the download tool as "download b and c" (it ignores the
    exclude once file names are given); one `--exclude` per pattern, the tool at a pinned version."""
    import re

    page = (ROOT / "docs/runbook/28-igx-orin-a6000-without-a-model.md").read_text(encoding="utf-8")
    downloads = [ln for ln in page.splitlines() if "hf download" in ln]
    assert downloads
    for ln in downloads:
        for name in ("pytorch_model.bin", "colbert_linear.pt", "sparse_linear.pt"):
            assert f"--exclude {name}" in ln, name
        assert not re.search(r"--exclude [^ -][^ ]* [^ -]", ln.replace("`", " ")), ln
    assert 'pip install "huggingface_hub==2.4.0"' in page
    assert "--dry-run" in page and "18" in page


def test_the_report_to_send_back_holds_no_address_password_or_folder(tmp_path: Path) -> None:
    """Review of #1100, item 4: the start's own output shows the admin password and the folder names; the page asks
    for `deploy/poc.sh report` instead: the services' states and memory, the embedder's mode and its pin."""
    root = _root(tmp_path)
    res, _ = _run(tmp_path, root, TB_POC_EMBED="model")
    assert res.returncode == 0, res.stderr
    site = root / "deploy/poc/site"
    site.mkdir(parents=True, exist_ok=True)
    (site / "registry.site.yaml").write_text(
        "builds:\n  e-embed-1:\n    sha256: " + "e131f320" * 8 + "\n", encoding="utf-8"
    )
    res, log = _run(tmp_path, root, "report")
    assert res.returncode == 0, res.stderr
    assert "model embedder choice" in res.stdout and "e-embed-1 pin: e131f320e131" in res.stdout
    assert any("exec -T embed-service printenv TB_EMBED_MODE" in line for line in log)
    for leak in (str(root), "127.0.0.1", "admin@", "password", "http://"):
        assert leak not in res.stdout, leak
