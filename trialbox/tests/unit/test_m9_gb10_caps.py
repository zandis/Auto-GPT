"""M9 machine-profile findings on the unified-memory (GB10) and 96 GB profiles.

1. The GB10 adapter cap is 5 GiB: a 50,000-patient ingest peaked at 3,842 MiB and 3 GiB was killed.
2. The orchestrator's cap is at least 6 GiB on both profiles (a 48,000-patient SCREEN peaked near 4.0 GiB), the
   installer's memcaps never writes a value under the profile's default, and the GB10 limits still fit its memory.
3. The pinned context is the length each profile's servers run with: a stale site pin is put back to the registry's,
   and the install and doctor refuse a pin that is not the profile's length (the gateway's model_mismatch).
4. Preflight's gpu_tier accepts a unified-memory device, which reports no card memory.
5. A bundle's images are checked for its --platform when it is built, and an update refuses images of another
   architecture than the host.
Synthetic weights, archives and counts only.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import subprocess
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from tests.model_pins import promote_pins, release_registry
from tools import pin_model, release
from tools import two_device as td
from tools.trialbox import doctor, memcaps, profile_m9
from tools.trialbox import preflight as pf

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
GB10, PRO = DEPLOY / "docker-compose.gb10.yml", DEPLOY / "docker-compose.rtxpro6000.yml"
JUDGE, VERIFIER = "gemma-4-26b-a4b-it-spark", "qwen3.5-9b-spark"


def _limit(compose: Path, service: str) -> float:
    gib = td._gib(yaml.safe_load(compose.read_text(encoding="utf-8"))["services"][service]["mem_limit"])
    assert gib is not None, (compose.name, service)
    return gib


# ------------------------------------------------------------------------------------------------ 1. the adapter
def test_the_gb10_adapter_cap_holds_the_measured_ingest_peak() -> None:
    profile = td.load_profile()
    assert _limit(GB10, "adapter") == 5 == profile["memory"]["adapter"]["limit_gib"]
    assert _limit(GB10, "adapter") * 1024 > 3842 * 1.2  # the 50,000-patient peak, with headroom


# ------------------------------------------------------------------------------------------------ 2. the orchestrator
@pytest.mark.parametrize("overlay", [GB10, PRO], ids=["gb10", "rtxpro6000"])
def test_the_orchestrator_cap_is_at_least_6_gib_on_both_profiles(overlay: Path) -> None:
    assert _limit(overlay, "orchestrator") >= 6
    assert memcaps.size_mb(memcaps.orch_default(overlay=overlay)) >= 6 * 1024
    assert memcaps.orch_default() == memcaps.compose_default("TB_MEM_ORCH")  # no overlay: the base file's


def _orch(tmp: Path) -> Path:
    p = tmp / "orchestrator_memory.json"
    doc = {"format": memcaps.ORCH_FORMAT, "services": {"orchestrator": {"fixed_mb": 500.0, "per_patient_kb": 80.0}}}
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def test_memcaps_never_writes_an_orchestrator_cap_under_the_profile_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """50,000 synthetic patients need about 4.3 GiB: above the base file's 4 GiB, under the profile's 6. Written
    without the overlay, that value would lower the profile's cap."""
    monkeypatch.setattr(memcaps, "ORCH_RECORD", _orch(tmp_path))
    env = tmp_path / ".env"
    env.write_text("TB_ENV=PRODUCTION\nTB_SITE_PATIENTS=50000\n", encoding="utf-8")
    assert memcaps.main(["--env-file", str(env), "--overlay", str(PRO), "--write"]) == 0
    assert "TB_MEM_ORCH" not in memcaps._parse_env(env.read_text(encoding="utf-8"))
    env.write_text("TB_ENV=PRODUCTION\nTB_SITE_PATIENTS=100000\n", encoding="utf-8")
    memcaps.main(["--env-file", str(env), "--overlay", str(GB10), "--write"])
    assert (
        memcaps._parse_env(env.read_text(encoding="utf-8"))["TB_MEM_ORCH"] == f"{math.ceil(500 + 80 * 100_000 / 1024)}m"
    )


def test_the_installer_gives_memcaps_the_profile_overlay() -> None:
    install = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    assert '${OVERLAY:+--overlay "$OVERLAY"}' in install and 'OVERLAY="deploy/docker-compose.$GPU.yml"' in install


def test_the_gb10_limits_still_fit_its_unified_memory() -> None:
    profile = td.load_profile()
    limits = td.memory_limits(profile)
    one = sum(v for k, v in limits.items() if k != "link")
    assert one + profile["device"]["os_reserve_gib"] <= profile["device"]["unified_memory_gib"]
    assert td.profile_problems(profile) == []
    assert one + profile["device"]["os_reserve_gib"] == 127.25
    assert _limit(GB10, "db") == limits["db"] == 8
    # the verifier's 0.12 share (15.36 GiB) holds the model (7.8 GiB) and 8 x 16k of KV at 804k tokens per 26 GiB
    assert _limit(GB10, "llm-verifier") == limits["llm-verifier"] == 28
    assert "--gpu-memory-utilization=${VERIFIER_GPU_MEM_UTIL:-0.12}" in GB10.read_text(encoding="utf-8")
    assert 7.8 + 26 * 8 * 16384 / 804_000 < 0.12 * 128


# ------------------------------------------------------------------------------------------------ 3. the context
def test_each_profile_s_servers_run_at_its_own_length() -> None:
    assert pin_model.profile_context("gb10", "serving", {}) == 16384
    assert pin_model.profile_context("gb10", "verifier", {}) == 16384
    assert pin_model.profile_context("rtxpro6000", "serving", {}) == 32768
    assert pin_model.profile_context("gb10", "serving", {"JUDGE_MAX_LEN": "8192"}) == 8192  # deploy/.env moves it
    assert pin_model.profile_context("shared-quota", "serving", {}) is None  # measured on the partition: no default


def _gb10_box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    models = tmp_path / "models"
    for name in ("gemma-4-26b-a4b-it-4bit", "qwen3.5-9b-4bit"):
        (models / name).mkdir(parents=True)
        (models / name / "model.safetensors").write_bytes(f"synthetic {name}".encode())
    release_registry(
        tmp_path, {JUDGE: models / "gemma-4-26b-a4b-it-4bit", VERIFIER: models / "qwen3.5-9b-4bit"}, monkeypatch
    )
    out = tmp_path / "site" / "registry.site.yaml"
    ok, lines = pin_model.install_pins("gb10", models, out, {})
    assert ok, lines
    promote_pins(out)
    return models, out


def _stale(out: Path, context: int) -> None:
    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    for build in (JUDGE, VERIFIER):
        doc["builds"][build]["context_length"] = context
    out.write_text(yaml.safe_dump(doc), encoding="utf-8")


def test_a_stale_site_pin_is_refused_by_doctor_and_put_back_by_the_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    models, out = _gb10_box(tmp_path, monkeypatch)
    inp = doctor.DoctorInputs(env={"TB_REGISTRY_OVERRIDE": str(out)})
    assert profile_m9.context_row("gb10", inp)[0][1] == "PASS"
    _stale(out, 32768)  # the site pin of the finding: 32768 for both builds, the servers at 16384
    bad = pin_model.context_problems("gb10", out, {})
    assert len(bad) == 2 and all("context_length is 32768" in b and "serves 16384" in b for b in bad), bad
    (row,) = profile_m9.context_row("gb10", inp)
    assert row[:2] == ("profile_context", "FAIL") and JUDGE in row[2] and VERIFIER in row[2]
    ok, lines = pin_model.install_pins("gb10", models, out, {})
    assert ok, lines
    assert all("context 16384 (the registry's for this build; the pin had 32768)" in ln for ln in lines[:2]), lines
    assert pin_model.context_problems("gb10", out, {}) == []
    assert profile_m9.context_row("gb10", inp)[0][1] == "PASS"


def test_the_install_refuses_servers_set_to_another_length_than_the_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    models, out = _gb10_box(tmp_path, monkeypatch)
    ok, lines = pin_model.install_pins("gb10", models, out, {"JUDGE_MAX_LEN": "32768"})
    assert not ok
    assert any(ln.startswith(JUDGE) and "serves 32768 (JUDGE_MAX_LEN)" in ln for ln in lines), lines
    install = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    assert "-e JUDGE_MAX_LEN -e VERIFIER_MAX_LEN" in install  # the length the servers run with reaches the pin step


def test_no_context_row_for_a_profile_without_a_pair() -> None:
    assert profile_m9.context_row("stub", doctor.DoctorInputs()) == []


def test_pins_that_do_not_load_are_a_warning_not_the_loss_of_the_profile_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_a: object, **_k: object) -> list[str]:
        raise ValueError("registry: build x context_length '16k' is not a whole number above 0")

    monkeypatch.setattr(pin_model, "context_problems", broken)
    (row,) = profile_m9.context_row("gb10", doctor.DoctorInputs())
    assert row[:2] == ("profile_context", "WARN") and "cannot look" in row[2]


# ------------------------------------------------------------------------------------------------ 4. preflight
def test_a_unified_memory_device_is_read_as_a_card(monkeypatch: pytest.MonkeyPatch) -> None:
    from tools.box import plan

    out = "NVIDIA GB10, [N/A]\nNVIDIA RTX PRO 6000 Blackwell Server Edition, 97887\nNVIDIA-SMI has failed\n"
    monkeypatch.setattr(plan, "_run", lambda cmd: out)
    assert pf._gpus() == [("NVIDIA GB10", None), ("NVIDIA RTX PRO 6000 Blackwell Server Edition", 97887.0)]


def test_gpu_tier_accepts_a_unified_memory_device(tmp_path: Path) -> None:
    tiers = tmp_path / "tiers"
    tiers.mkdir()
    fields = {"card_names": {"value": ["GB10"]}, "card_memory_mib": {"value": 97887},
              "host_memory_gib_min": {"value": 96}}  # fmt: skip
    (tiers / "rtxpro6000.json").write_text(json.dumps({"fields": fields}), encoding="utf-8")
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "meminfo").write_text(f"MemTotal: {120 * 1024**2} kB\n", encoding="utf-8")
    inp = doctor.DoctorInputs(env={"TB_PROFILE": "P-PRO6000", "TB_LLM_MODE": "vllm"}, deploy=tmp_path, proc=proc)
    probes = pf.Probes(gpus=lambda: [("NVIDIA GB10", None)], tiers_dir=tiers)
    got = pf.check_gpu_tier(inp, probes)
    assert got.status == "PASS" and "unified memory (no card memory reported)" in got.detail, got
    (proc / "meminfo").write_text(f"MemTotal: {64 * 1024**2} kB\n", encoding="utf-8")
    low = pf.check_gpu_tier(inp, probes)  # the host's memory is the device's: still compared
    assert low.status == "FAIL" and "the host has 64 GiB" in low.detail, low


# ------------------------------------------------------------------------------------------------ 5. the bundle
def _archive(tmp: Path, arch: str) -> Path:
    cfg = json.dumps({"architecture": arch, "os": "linux"}).encode()
    name = hashlib.sha256(cfg).hexdigest()
    manifest = json.dumps([{"Config": f"{name}.json", "RepoTags": ["trialbox-py:1.0.0"], "Layers": []}]).encode()
    path = tmp / f"img-{arch}.tar"
    with tarfile.open(path, "w") as tf:
        for member, data in (("manifest.json", manifest), (f"{name}.json", cfg)):
            info = tarfile.TarInfo(member)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return path


def test_an_archive_says_its_platform_and_the_build_refuses_another(tmp_path: Path) -> None:
    arm = _archive(tmp_path, "arm64")
    assert release.archive_platform(arm) == "linux/arm64"
    gates = tmp_path / "gates.json"
    gates.write_text("{}", encoding="utf-8")
    with pytest.raises(release.ReleaseError, match="for linux/arm64, the bundle is for linux/amd64"):
        release.build(release_id="2026.11-9", release_seq=9, gates=gates, sbom_dir=tmp_path, out_dir=tmp_path / "o",
                      images=[("trialbox-py:1.0.0", arm)], items=[("image", arm, arm.name)],
                      platform="linux/amd64")  # fmt: skip


def test_make_bundle_takes_the_box_s_platform(tmp_path: Path) -> None:
    text = (ROOT / "tools" / "make_bundle.sh").read_text(encoding="utf-8")
    assert text.count('--platform "$PLATFORM"') == 2  # the model pack's release record and the software pack's
    assert 'DOCKER_DEFAULT_PLATFORM="$PLATFORM" docker pull' in text
    (tmp_path / "gates.json").write_text("{}", encoding="utf-8")
    (tmp_path / "sbom").mkdir()
    (tmp_path / "vendor.key").write_text("not a key\n", encoding="utf-8")
    r = subprocess.run(
        ["bash", str(ROOT / "tools/make_bundle.sh"), "--key", str(tmp_path / "vendor.key"), "--id", "2026.11-9",
         "--release-seq", "9", "--out", str(tmp_path / "b.tar"), "--gates", str(tmp_path / "gates.json"),
         "--sbom-dir", str(tmp_path / "sbom"), "--platform", "linux/s390x"],
        capture_output=True, text=True, check=False, env={**os.environ, "PY": "python3"},
    )  # fmt: skip
    assert r.returncode == 2 and "--platform is linux/amd64 or linux/arm64" in r.stderr, r.stderr


@pytest.mark.parametrize(
    ("machine", "arch"), [("x86_64", "amd64"), ("aarch64", "arm64"), ("arm64", "arm64"), ("riscv64", "riscv64")]
)
def test_the_host_architecture_is_named_as_an_image_platform_names_it(
    monkeypatch: pytest.MonkeyPatch, machine: str, arch: str
) -> None:
    from tools.trialbox import update  # a POSIX host's module (its signals)

    monkeypatch.setattr(update.os, "uname", lambda: SimpleNamespace(machine=machine), raising=False)
    assert update.host_architecture() == arch


def test_an_update_refuses_images_of_another_architecture(monkeypatch: pytest.MonkeyPatch) -> None:
    from tools.trialbox import update  # a POSIX host's module (its signals)

    rel = {"images": {"py": {"platform": "linux/amd64"}, "vllm": {"platform": "linux/arm64/v8"}, "x": {}}}
    assert update.architecture_mismatch(rel, "arm64") == ["py (linux/amd64)"]
    assert update.architecture_mismatch(rel, "") == []  # a host that cannot say is not compared
    assert update.architecture_mismatch(None, "arm64") == []
    monkeypatch.setattr(update, "host_architecture", lambda: "arm64")
    updater = update.Updater.__new__(update.Updater)
    with pytest.raises(update.UpdateRefused, match=r"another architecture than this host \(arm64\): py"):
        updater._same_architecture(SimpleNamespace(release=rel, bundle_id="2026.11-9"))
    same = {"images": {"py": {"platform": "linux/arm64"}}}
    assert updater._same_architecture(SimpleNamespace(release=same, bundle_id="2026.11-9")) == []
