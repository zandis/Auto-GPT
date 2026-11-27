"""M9 machine-profile findings on the unified-memory (GB10) and 96 GB profiles.

1. The GB10 adapter cap is 6 GiB: a 50,000-patient ingest peaked at 3,842 MiB (1.5 x must fit); 3 GiB was killed.
2. The orchestrator's cap is at least 6 GiB on both profiles (a 48,000-patient SCREEN peaked near 4.0 GiB), the
   installer's memcaps never writes a value under the profile's default, and the GB10 limits still fit its memory.
3. The pinned context is the length each profile's servers run with: a stale site pin is put back to the registry's,
   and the install and doctor refuse a pin that is not the profile's length (the gateway's model_mismatch), a length
   that is set and is no length, and a length they cannot read (never a silent pass).
4. Preflight's gpu_tier accepts a unified-memory device, which reports no card memory.
5. A bundle's images are checked for its --platform when it is built, release.json records it, and an update refuses
   a bundle recorded for another architecture than the host (one that records none is not refused).
Synthetic weights, archives and counts only.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
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
    assert _limit(GB10, "adapter") == 6 == profile["memory"]["adapter"]["limit_gib"]
    assert _limit(GB10, "adapter") * 1024 >= 3842 * 1.5  # the 50,000-patient peak, with headroom


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
    assert memcaps.main(["--env-file", str(env), "--overlay", str(GB10), "--write"]) == 0
    peaks = memcaps.load_peaks(DEPLOY / "measured" / memcaps.PEAKS_NAME)  # the cap is derived from the measured peak
    pin = math.ceil(memcaps.HEADROOM * memcaps.peak_mib(peaks, "TB_MEM_ORCH", 100_000))
    assert memcaps._parse_env(env.read_text(encoding="utf-8"))["TB_MEM_ORCH"] == f"{pin}m"


def test_the_installer_gives_memcaps_the_profile_overlay() -> None:
    install = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    assert '${OVERLAY:+--overlay "$OVERLAY"}' in install and 'OVERLAY="deploy/docker-compose.$GPU.yml"' in install


def test_the_overlay_compose_runs_is_the_last_file_that_names_the_orchestrator_default(tmp_path: Path) -> None:
    base = DEPLOY / "docker-compose.yml"
    assert memcaps.profile_overlay([base, PRO]) == PRO
    assert memcaps.profile_overlay([PRO, base]) == base  # a later file overrides an earlier one
    assert memcaps.profile_overlay([base, DEPLOY / "docker-compose.monitoring.yml", tmp_path / "gone.yml"]) == base
    assert memcaps.profile_overlay([]) is None


def _caps_deploy(tmp: Path) -> Path:
    deploy = tmp / "deploy"
    (deploy / "measured").mkdir(parents=True)
    for f in ("measured/ingest_memory.json", "measured/orchestrator_memory.json", "docker-compose.yml", PRO.name):
        (deploy / f).write_text((DEPLOY / f).read_text(encoding="utf-8"), encoding="utf-8")
    return deploy


def test_doctor_judges_the_orchestrator_cap_by_the_profile_default(tmp_path: Path) -> None:
    """48,000 synthetic patients need about 4.3 GiB: above the base file's 4 GiB, under the profile's 6, which is
    what compose runs on that box. A lower cap this tool wrote before the profile's default rose is a FAIL, and the
    installer's memcaps (with the overlay) removes it."""
    deploy = _caps_deploy(tmp_path)
    env = {"TB_ENV": "PRODUCTION", "TB_SITE_PATIENTS": "48000"}
    base = doctor.check_memory_caps(doctor.DoctorInputs(env=env, deploy=deploy))
    assert base.status == "FAIL" and "TB_MEM_ORCH 4096 MB <" in base.detail, base  # the base file alone
    env["COMPOSE_FILE"] = f"docker-compose.yml:{PRO.name}"
    ok = doctor.check_memory_caps(doctor.DoctorInputs(env=env, deploy=deploy))
    assert ok.status == "PASS" and "TB_MEM_ORCH 6144 MB (needs 6144)" in ok.detail, ok
    stale = doctor.check_memory_caps(doctor.DoctorInputs(env={**env, "TB_MEM_ORCH": "4400m"}, deploy=deploy))
    assert stale.status == "FAIL" and "TB_MEM_ORCH 4400 MB < 6144 MB" in stale.detail, stale
    text = "TB_MEM_ORCH=4400m\n# memcaps: TB_MEM_ORCH=4400m n=48000 (TB_SITE_PATIENTS)\n"
    caps = memcaps.plan(text, 48000, memcaps.load_record(deploy / "measured" / "ingest_memory.json"),
                        deploy / "docker-compose.yml",
                        memcaps.load_orch_record(deploy / "measured" / "orchestrator_memory.json"),
                        overlay=deploy / PRO.name)  # fmt: skip
    assert caps["TB_MEM_ORCH"] is None  # the tool's own value under the profile's default: removed


def _gb10_total_gib(profile: dict, peaks: list, n: int) -> float:
    """Every container's cap on the Spark for a hospital of ``n`` patients (the models' limits included), plus the OS
    reserve: each measured service holds the larger of its profile limit and 1.5 x its measured peak."""
    limits = td.memory_limits(profile)
    for svc, var in {**memcaps.CAPS, memcaps.ORCH: memcaps.ORCH_VAR}.items():
        derived = math.ceil(memcaps.HEADROOM * memcaps.peak_mib(peaks, var, n)) / 1024
        limits[svc] = max(limits[svc], derived)
    return sum(v for k, v in limits.items() if k != "link") + profile["device"]["os_reserve_gib"]


def test_the_gb10_caps_for_its_declared_site_size_fit_its_unified_memory() -> None:
    """E2E P-02: the caps follow the measured peaks, so the profile's declared size is what they fit, not a typed claim."""
    profile = td.load_profile()
    peaks = memcaps.load_peaks(DEPLOY / "measured" / memcaps.PEAKS_NAME)
    n, memory = profile["site"]["max_patients"], profile["device"]["unified_memory_gib"]
    assert _gb10_total_gib(profile, peaks, n) <= memory  # the container caps and the models fit
    assert all(_gb10_total_gib(profile, peaks, p) > memory for p, _ in peaks if p > n)  # lowered no further than needed


def test_the_gb10_limits_still_fit_its_unified_memory() -> None:
    profile = td.load_profile()
    limits = td.memory_limits(profile)
    one = sum(v for k, v in limits.items() if k != "link")
    assert one + profile["device"]["os_reserve_gib"] <= profile["device"]["unified_memory_gib"]
    assert td.profile_problems(profile) == []
    assert one + profile["device"]["os_reserve_gib"] == 127.25
    assert _limit(GB10, "db") == limits["db"] == 8
    # the verifier's 0.12 share (15.36 GiB) holds the model (7.8 GiB) and 8 x 16k of KV at 804k tokens per 26 GiB
    assert _limit(GB10, "llm-verifier") == limits["llm-verifier"] == 27
    assert "--gpu-memory-utilization=${VERIFIER_GPU_MEM_UTIL:-0.12}" in GB10.read_text(encoding="utf-8")
    assert 7.8 + 26 * 8 * 16384 / 804_000 < 0.12 * 128


# ------------------------------------------------------------------------------------------------ 3. the context
def test_each_profile_s_servers_run_at_its_own_length() -> None:
    assert pin_model.profile_context("gb10", "serving", {}) == 16384
    assert pin_model.profile_context("gb10", "verifier", {}) == 16384
    assert pin_model.profile_context("rtxpro6000", "serving", {}) == 32768
    assert pin_model.profile_context("gb10", "serving", {"JUDGE_MAX_LEN": "8192"}) == 8192  # deploy/.env moves it
    assert pin_model.profile_context("shared-quota", "serving", {}) is None  # measured on the partition: no default


@pytest.mark.parametrize(
    ("value", "length"), [("", 16384), ("  ", 16384), ('"8192"', 8192), ("'8192'", 8192), ("unmeasured", None)]
)
def test_an_empty_or_quoted_length_is_read_as_compose_reads_it(value: str, length: int | None) -> None:
    assert pin_model.profile_context("gb10", "serving", {"JUDGE_MAX_LEN": value}) == length
    assert pin_model.profile_context("rtx4090", "serving", {}) == 8192  # the rtx5090 file, as install.sh runs it


def test_the_installer_reads_a_quoted_length_as_compose_does(tmp_path: Path) -> None:
    install = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    read = next(ln.strip() for ln in install.splitlines() if "compose drops quotes" in ln)
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy" / ".env").write_text("JUDGE_MAX_LEN=\"8192\"\nVERIFIER_MAX_LEN='4096'\n", encoding="utf-8")
    script = f'for v in JUDGE_MAX_LEN VERIFIER_MAX_LEN; do {read}\nprintf "%s=%s\\n" "$v" "$val"; done'
    r = subprocess.run(["bash", "-c", script], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert r.stdout == "JUDGE_MAX_LEN=8192\nVERIFIER_MAX_LEN=4096\n", r.stdout + r.stderr


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


@pytest.mark.parametrize("value", ["bogus", "0", "16k", "8192.5"])
def test_a_length_that_is_set_and_is_no_length_is_refused_not_defaulted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """Compose passes the value to the server, which does not start: never read as the default length."""
    with pytest.raises(pin_model.PinError, match=re.escape(f"JUDGE_MAX_LEN is {value!r}")):
        pin_model.profile_context("gb10", "serving", {"JUDGE_MAX_LEN": value})
    models, out = _gb10_box(tmp_path, monkeypatch)
    ok, lines = pin_model.install_pins("gb10", models, out, {"JUDGE_MAX_LEN": value})
    assert not ok and any(ln.startswith(JUDGE) and "not a length" in ln for ln in lines), lines
    inp = doctor.DoctorInputs(env={"TB_REGISTRY_OVERRIDE": str(out), "JUDGE_MAX_LEN": value})
    (row,) = profile_m9.context_row("gb10", inp)
    assert row[:2] == ("profile_context", "FAIL") and "not a length" in row[2], row


def test_the_length_is_read_from_the_box_s_deploy_folder_never_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The image carries no profile compose file: the install reads the mounted site folder, and a folder without
    the file, or a file that names no length, is a refusal, not a silent pass."""
    models, out = _gb10_box(tmp_path, monkeypatch)
    site = tmp_path / "site-deploy"
    site.mkdir()
    ok, lines = pin_model.install_pins("gb10", models, out, {}, deploy=site)
    assert not ok and sum("cannot be read" in ln for ln in lines) == 2, lines
    inp = doctor.DoctorInputs(env={"TB_REGISTRY_OVERRIDE": str(out)}, deploy=site)
    (row,) = profile_m9.context_row("gb10", inp)
    assert row[:2] == ("profile_context", "FAIL") and "cannot be read" in row[2], row
    (site / GB10.name).write_text("services: {}\n", encoding="utf-8")
    ok, lines = pin_model.install_pins("gb10", models, out, {}, deploy=site)
    assert not ok and any("gives JUDGE_MAX_LEN no length" in ln for ln in lines), lines
    (site / GB10.name).write_text(GB10.read_text(encoding="utf-8"), encoding="utf-8")
    ok, lines = pin_model.install_pins("gb10", models, out, {}, deploy=site)
    assert ok, lines
    assert profile_m9.context_row("gb10", inp)[0][1] == "PASS"
    install = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    assert "--models-root /d/models --deploy /d" in install


def test_the_pin_command_reads_the_folder_above_its_models_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    models, out = _gb10_box(tmp_path, monkeypatch)
    args = ["--install", "gb10", "--models-root", str(models), "--out", str(out)]
    assert pin_model.main(args) == 1  # the folder above the models holds no docker-compose.gb10.yml
    (tmp_path / GB10.name).write_text(GB10.read_text(encoding="utf-8"), encoding="utf-8")
    assert pin_model.main(args) == 0


def test_no_context_row_for_a_profile_without_a_pair() -> None:
    assert profile_m9.context_row("stub", doctor.DoctorInputs()) == []


def test_pins_that_do_not_load_are_a_failure_not_the_loss_of_the_profile_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_a: object, **_k: object) -> list[str]:
        raise ValueError("registry: build x context_length '16k' is not a whole number above 0")

    monkeypatch.setattr(pin_model, "context_problems", broken)
    (row,) = profile_m9.context_row("gb10", doctor.DoctorInputs())
    assert row[:2] == ("profile_context", "FAIL") and "cannot look" in row[2]


def test_a_site_pin_that_does_not_validate_fails_the_context_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _models, out = _gb10_box(tmp_path, monkeypatch)
    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    doc["builds"][JUDGE]["context_length"] = "16k"
    out.write_text(yaml.safe_dump(doc), encoding="utf-8")
    (row,) = profile_m9.context_row("gb10", doctor.DoctorInputs(env={"TB_REGISTRY_OVERRIDE": str(out)}))
    assert row[:2] == ("profile_context", "FAIL") and "cannot look" in row[2] and "context_length" in row[2], row


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
def _archive(tmp: Path, arch: str, **more: object) -> Path:
    cfg = json.dumps({"architecture": arch, "os": "linux", **more}, sort_keys=True).encode()
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

    monkeypatch.setattr(os, "uname", lambda: SimpleNamespace(machine=machine), raising=False)
    assert update.host_architecture() == arch


def test_an_update_refuses_a_bundle_built_for_another_architecture(monkeypatch: pytest.MonkeyPatch) -> None:
    from tools.trialbox import update  # a POSIX host's module (its signals)

    # every bundle shipped before the record: its images' platforms come from images.lock and may be mixed
    mixed = {"images": {"py": {"platform": "linux/amd64"}, "vllm": {"platform": "linux/arm64/v8"}, "x": {}}}
    assert update.architecture_mismatch(mixed, "arm64") == "" and update.architecture_mismatch(mixed, "amd64") == ""
    amd = {**mixed, "platform": "linux/amd64"}  # built with --platform linux/amd64
    assert update.architecture_mismatch(amd, "arm64") == "linux/amd64"
    assert update.architecture_mismatch(amd, "amd64") == ""
    assert update.architecture_mismatch(amd, "") == ""  # a host that cannot say is not compared
    assert update.architecture_mismatch(None, "arm64") == ""
    monkeypatch.setattr(update, "host_architecture", lambda: "arm64")
    updater = update.Updater.__new__(update.Updater)
    with pytest.raises(update.UpdateRefused, match=r"another architecture than this host \(arm64\): linux/amd64"):
        updater._same_architecture(SimpleNamespace(release=amd, bundle_id="2026.11-9"))  # type: ignore[arg-type]
    for ok in (mixed, {**mixed, "platform": "linux/arm64"}):  # an old release (a rollback) and this host's
        plan = SimpleNamespace(release=ok, bundle_id="2026.11-9")
        assert updater._same_architecture(plan) == []  # type: ignore[arg-type]


def test_a_bundle_built_for_a_platform_records_it(tmp_path: Path) -> None:
    from tests.unit.test_release_bundle import _gate_record, _iid

    ref = "trialbox-py:1.0.0"
    gates, sbom = _gate_record(tmp_path, [ref])
    repo = release.repository(ref)
    layer = "sha256:" + hashlib.sha256(repo.encode()).hexdigest()
    rootfs = {"type": "layers", "diff_ids": [layer]}
    arch = _archive(tmp_path, "amd64", config={"Labels": {"repo": repo}}, rootfs=rootfs)
    assert release.archive_identities(arch) == (_iid(ref),)  # the image the gate record passed
    kw = {"release_id": "2026.11-9", "release_seq": 9, "gates": gates, "sbom_dir": sbom,
          "images": [(ref, arch)], "items": [("image", arch, arch.name)]}  # fmt: skip
    rel = release.build(out_dir=tmp_path / "o", platform="linux/amd64", **kw)  # type: ignore[arg-type]
    assert rel["platform"] == "linux/amd64" and rel["images"]["py"]["platform"] == "linux/amd64"
    assert "platform" not in release.build(out_dir=tmp_path / "p", **kw)  # type: ignore[arg-type]
    schema = json.loads((ROOT / "schemas" / "release.schema.json").read_text(encoding="utf-8"))
    assert "platform" not in schema["required"]  # a bundle from before it still validates
