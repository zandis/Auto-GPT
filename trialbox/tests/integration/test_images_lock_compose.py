"""T-673 (D-348): the images compose itself renders, for the base stack and each overlay, are the digests of
deploy/images.lock. ``docker compose config --images`` resolves anchors, overrides and ``${VAR:-default}`` as a box
does; nothing is pulled or started. Skipped without the compose plugin."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tools import images_lock as il

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
# the required variables of the overlays, with dummy values: only the image lines matter here
DUMMY_ENV = """TB_TZ=Asia/Taipei
TB_TLS_HOSTNAME=box.hospa.test
TB_MIG_PROFILE=3g.48gb
TB_MIG_JUDGE_DEVICE=MIG-judge
TB_MIG_VERIFIER_DEVICE=MIG-verifier
JUDGE_GPU_MEM_UTIL=0.4
JUDGE_MAX_LEN=16384
JUDGE_MAX_SEQS=8
VERIFIER_GPU_MEM_UTIL=0.2
VERIFIER_MAX_LEN=16384
VERIFIER_MAX_SEQS=8
POSTGRES_PASSWORD=x
TB_ACCEPTANCE_MAIL_PASSWORD=x
TB_ACCEPTANCE_MAIL_KEYSTORE_PASSWORD=x
"""
PROFILES = ("stub", "test", "gpu", "oidc", "dev")  # every profile any overlay defines
OVERLAYS = [
    "",
    "gb10",
    "rtx5090",
    "rtxpro6000",
    "shared-quota",
    "identity",
    "poc",
    "testbench",
    "secrets",
    "monitoring",
    "identity,acceptance",  # T-213a (D-410): the acceptance overlay extends the identity overlay's Authelia
]


def _compose() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "compose", "version"], capture_output=True, check=False).returncode == 0


pytestmark = pytest.mark.skipif(not _compose(), reason="needs the docker compose plugin")


def _env() -> dict[str, str]:
    """The caller's environment without anything that would choose an image or a file set for compose."""
    return {k: v for k, v in os.environ.items() if not k.endswith("_IMAGE") and not k.startswith("COMPOSE_")}


def _images(project: Path, overlay: str) -> set[str]:
    files = ["-f", str(DEPLOY / "docker-compose.yml"), "-f", str(DEPLOY / "docker-compose.test.yml")]
    for name in filter(None, overlay.split(",")):
        files += ["-f", str(DEPLOY / f"docker-compose.{name}.yml")]
    r = subprocess.run(
        ["docker", "compose", "--project-directory", str(project), *files,
         *(x for p in PROFILES for x in ("--profile", p)), "config", "--images"],
        capture_output=True, text=True, timeout=120, check=False, env=_env(),
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return {line.strip() for line in r.stdout.splitlines() if line.strip()}


def test_compose_renders_only_locked_digests_for_every_overlay(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(DUMMY_ENV, encoding="utf-8")
    lock = il.load()
    pinned = {il.pinned(e) for e in lock["third_party"].values()}
    seen: set[str] = set()
    for overlay in OVERLAYS:
        if any(not (DEPLOY / f"docker-compose.{name}.yml").is_file() for name in filter(None, overlay.split(","))):
            continue
        third = {i for i in _images(tmp_path, overlay) if not i.startswith(il.OWN_PREFIX)}
        assert all("@sha256:" in i for i in third), (overlay, third)
        assert third <= pinned, (overlay, third - pinned)
        seen |= third
    assert seen == pinned  # every locked image is rendered by some overlay


def test_a_site_variable_still_overrides_the_default(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(DUMMY_ENV + "VLLM_IMAGE=registry.hospa.test/vllm:mirror\n", encoding="utf-8")
    images = _images(tmp_path, "rtxpro6000")
    assert "registry.hospa.test/vllm:mirror" in images
    assert not any(i.startswith("vllm/vllm-openai") for i in images)
