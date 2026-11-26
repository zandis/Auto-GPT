"""Every value that is written in more than one place agrees, and every memory cap holds its measured peak.

1. Pin consistency, per machine profile (gb10, rtxpro6000): the context length, the served names, the model folders, the
   memory fractions, the memory caps, the platform, the image and the ports are read independently from the profile's
   compose file, the profile record, the registry rows, the site registry the installer writes, images.lock,
   gb10-profile.yaml and the link's compose file. Each pair of readings must be equal.
2. Cap from peak: a container's cap is at least 1.5 x its recorded 50,000-patient peak. A container with no recorded
   peak is listed in the output, not failed.
Synthetic weights and counts only.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from tests.model_pins import promote_pins, release_registry
from tools import pin_model
from tools import two_device as td
from tools.trialbox import doctor

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
PROFILES = ("gb10", "rtxpro6000")
PLATFORM = {"gb10": "linux/arm64", "rtxpro6000": "linux/amd64"}
IMAGE_VAR = {"gb10": "VLLM_GB10_IMAGE", "rtxpro6000": "VLLM_IMAGE"}
# the server a variable belongs to: (compose service, length, memory fraction, served name, folder)
SERVERS = {
    "serving": ("llm-service", "JUDGE_MAX_LEN", "JUDGE_GPU_MEM_UTIL", "JUDGE_MODEL", "JUDGE_MODEL_DIR"),
    "verifier": ("llm-verifier", "VERIFIER_MAX_LEN", "VERIFIER_GPU_MEM_UTIL", "VERIFIER_MODEL", "VERIFIER_MODEL_DIR"),
}
SERVED = {"serving": pin_model.JUDGE_SERVED, "verifier": pin_model.VERIFIER_SERVED}
GUARD_ROUTE = re.compile(r"(llm-[a-z]+)=(llm-[a-z]+-vllm):(\d+)")


def _overlay(profile: str) -> Path:
    return DEPLOY / f"docker-compose.{profile}.yml"


def _default(text: str, var: str) -> str:
    """The default compose gives ``var`` (``${VAR:-default}``); exactly one default, or the test names the variable."""
    found = set(re.findall(r"\$\{" + re.escape(var) + r":-([^}]*)\}", text))
    assert len(found) == 1, f"{var}: {len(found)} different defaults {sorted(found)}"
    return cast(str, found.pop())


def _services(profile: str) -> dict[str, dict[str, Any]]:
    return cast(dict[str, dict[str, Any]], yaml.safe_load(_overlay(profile).read_text(encoding="utf-8"))["services"])


def _record(profile: str) -> dict[str, Any]:
    return cast(
        dict[str, Any], json.loads((DEPLOY / "measured" / f"profile_record.{profile}.json").read_text(encoding="utf-8"))
    )


def _caps(profile: str, compose_profiles: str = "gpu") -> dict[str, float]:
    """Each service's effective cap in GiB: the base file with the profile's overlay over it, as compose merges them."""
    files = [DEPLOY / "docker-compose.yml", _overlay(profile)]
    caps, _, problems = doctor._service_caps(files, {"COMPOSE_PROFILES": compose_profiles})  # gpu: the model servers
    assert problems == []
    return caps


@pytest.fixture(scope="module")
def registry_rows() -> dict[str, dict[str, Any]]:
    doc = yaml.safe_load((ROOT / "models" / "registry.yaml").read_text(encoding="utf-8"))
    return {b["build_id"]: b for b in doc["builds"]}


def _site_pins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profile: str, stale_context: int) -> dict[str, Any]:
    """The registry the installer writes for a site (``pin_model.install_pins``) over synthetic weights, from a site pin
    that already names ``stale_context`` for the pair (a box pinned for another profile), as the registry's rows."""
    models = tmp_path / "models"
    folders = {}
    for build, _endpoint, _dvar, folder, *_ in pin_model.PROFILE_PAIRS[profile]:
        (models / folder).mkdir(parents=True)
        (models / folder / "model.safetensors").write_bytes(f"synthetic {folder}".encode())
        folders[build] = models / folder
    release_registry(tmp_path, folders, monkeypatch)
    out = tmp_path / "site" / "registry.site.yaml"
    ok, lines = pin_model.install_pins(profile, models, out, {})
    assert ok, lines
    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    for build in folders:
        doc["builds"][build]["context_length"] = stale_context
    out.write_text(yaml.safe_dump(doc), encoding="utf-8")
    ok, lines = pin_model.install_pins(profile, models, out, {})  # the install again over the stale pin
    assert ok, lines
    promote_pins(out)
    return cast(dict[str, Any], yaml.safe_load(out.read_text(encoding="utf-8"))["builds"])


# ------------------------------------------------------------------------------------------------ 1. the pins
@pytest.mark.parametrize("profile", PROFILES)
def test_context_length_is_one_number_in_every_place(
    profile: str, registry_rows: dict[str, dict[str, Any]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = _overlay(profile).read_text(encoding="utf-8")
    record = _record(profile)["concurrency"]["context_tokens"]
    # a site pinned before for the other profile: the install puts the pair's pin back to the registry's
    site = _site_pins(tmp_path, monkeypatch, profile, stale_context=32768 if profile == "gb10" else 16384)
    for build, endpoint, *_ in pin_model.PROFILE_PAIRS[profile]:
        length_var = SERVERS[endpoint][1]
        served_with = int(_default(text, length_var))
        assert registry_rows[build]["context_length"] == served_with == record, (build, length_var)
        assert site[build]["context_length"] == served_with, (build, "the site registry")
        assert pin_model.profile_context(profile, endpoint, {}) == served_with


@pytest.mark.parametrize("profile", PROFILES)
def test_served_names_and_model_folders_agree(profile: str, registry_rows: dict[str, dict[str, Any]]) -> None:
    text = _overlay(profile).read_text(encoding="utf-8")
    for build, endpoint, folder_var, folder, name_var, name in pin_model.PROFILE_PAIRS[profile]:
        _svc, _len, _frac, compose_name_var, compose_folder_var = SERVERS[endpoint]
        assert (name_var, folder_var) == (compose_name_var, compose_folder_var)
        assert _default(text, name_var) == name == SERVED[endpoint]
        assert _default(text, folder_var) == folder
        assert name.count("/") == 1 and name.startswith("local/")  # one namespace separator, as the gateway splits it
        assert registry_rows[build]["served"] == {endpoint: None}


@pytest.mark.parametrize("profile", PROFILES)
def test_the_registry_rows_name_one_release_per_build(profile: str, registry_rows: dict[str, dict[str, Any]]) -> None:
    for build, *_ in pin_model.PROFILE_PAIRS[profile]:
        row = registry_rows[build]
        prov = row["provenance"]
        assert row["expected"]["revision"] == prov["revision"], build  # the release is named once, read twice
        assert prov["source"] == row["repository"], build
    # the pair's builds on both profiles are the same two releases (the same weights folders, one revision each)
    other = {p: [registry_rows[b]["expected"]["revision"] for b, *_ in pin_model.PROFILE_PAIRS[p]] for p in PROFILES}
    assert other["gb10"] == other["rtxpro6000"]


@pytest.mark.parametrize("profile", PROFILES)
def test_memory_fractions_and_caps_agree_with_the_profile_record(profile: str) -> None:
    text = _overlay(profile).read_text(encoding="utf-8")
    record = _record(profile)
    for _endpoint, (_svc, _len, frac_var, *_) in SERVERS.items():
        assert record["caps"][frac_var] == _default(text, frac_var), frac_var
    seqs = {"JUDGE_MAX_SEQS": "judge_max_seqs", "VERIFIER_MAX_SEQS": "verifier_max_seqs"}
    for var, key in seqs.items():
        assert record["caps"][var] == _default(text, var) == str(record["concurrency"][key])
    caps = _caps(profile)
    for var, svc in (("TB_MEM_LLM", "llm-service"), ("TB_MEM_VERIFIER", "llm-verifier")):
        if var in record["caps"]:  # the gb10 record names only the verifier's: the other is fixed in the overlay
            assert doctor._mem_gib(record["caps"][var]) == caps[svc], (profile, var)


def test_the_gb10_caps_in_the_profile_data_are_the_compose_caps() -> None:
    profile = td.load_profile()
    caps = _caps("gb10", "gpu,stub")  # `llm-stub` is behind the stub profile, never beside the model servers
    for svc, row in profile["memory"].items():
        if svc != "link":  # `link` is the two-device form's, in its own file
            assert svc in caps, svc
            assert row["limit_gib"] == caps[svc], svc
    record = _record("gb10")
    assert record["fixed_in_overlay"]["llm_service_mem_limit"].startswith(f"{caps['llm-service']:g}g")
    assert profile["device"]["platform"] == PLATFORM["gb10"]


@pytest.mark.parametrize("profile", PROFILES)
def test_platform_and_image_agree_with_the_lock(profile: str) -> None:
    lock = json.loads((DEPLOY / "images.lock").read_text(encoding="utf-8"))["third_party"]["vllm"]
    text = _overlay(profile).read_text(encoding="utf-8")
    image = _default(text, IMAGE_VAR[profile])
    assert image == f"{lock['image']}@{lock['digest']}"
    assert IMAGE_VAR[profile] in lock["variables"]
    assert PLATFORM[profile] in lock["platforms"]
    declared = {s.get("platform") for s in _services(profile).values()} - {None}
    assert declared <= {PLATFORM[profile]}  # a service that names a platform names the profile's
    if profile == "gb10":
        assert declared == {PLATFORM[profile]} and re.search(r"^\s+platform: linux/arm64$", text, re.M)


@pytest.mark.parametrize("profile", PROFILES)
def test_model_server_ports_agree(profile: str) -> None:
    base = yaml.safe_load((DEPLOY / "docker-compose.yml").read_text(encoding="utf-8"))["services"]
    guard = base["model-guard"]["environment"]["TB_GUARD_ROUTES"]
    routes = {s: (alias, int(port)) for s, alias, port in GUARD_ROUTE.findall(guard)}
    text = _overlay(profile).read_text(encoding="utf-8")
    ports = set(re.findall(r"http://127\.0\.0\.1:(\d+)/health", text))
    assert len(ports) == 1, ports  # both servers listen on one port, and their healthcheck asks it
    for _endpoint, (svc, *_rest) in SERVERS.items():
        merged = {**base.get(svc, {}), **_services(profile)[svc]}  # the overlay's keys over the base file's
        aliases = merged["networks"]["model-backend-net"]["aliases"]
        guard_alias, guard_port = routes[svc]
        assert aliases == [guard_alias] and {str(guard_port)} == ports, (profile, svc)


def test_the_link_port_is_the_same_in_the_relay_and_its_compose_file() -> None:
    spark = (DEPLOY / "two-device" / "docker-compose.spark.yml").read_text(encoding="utf-8")
    assert f'TB_LINK_PORT: "{td.LINK_PORT}"' in spark
    assert f"${{TB_LINK_PORT:-{td.LINK_PORT}}}" in spark


# ------------------------------------------------------------------------------------------------ 2. cap from peak
# The 50,000-patient peaks, MiB: the profile record's measurements of the machine-profile finding. A container is
# listed here only with a peak that was measured; the others are named in the output of the last test.
#   adapter: ingest of 50,000 synthetic patients, with the validator (3,842 MiB; a 3 GiB cap was killed)
#   orchestrator: the SCREEN of 50,000 synthetic patients, before the result-memory fix (3,973 MiB)
PEAK_MIB = {"adapter": 3842, "orchestrator": 3973}
# the host stack (every container but the two model servers) at the same size: 18 to 20 GiB together
STACK_PEAK_GIB = 20
MODEL_SERVERS = ("llm-service", "llm-verifier")
HEADROOM = 1.5


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("service", sorted(PEAK_MIB))
def test_a_cap_is_at_least_1_5_times_the_recorded_peak(profile: str, service: str) -> None:
    cap_mib = _caps(profile)[service] * 1024
    assert cap_mib >= HEADROOM * PEAK_MIB[service], (
        f"{profile} {service}: cap {cap_mib:.0f} MiB, recorded peak {PEAK_MIB[service]} MiB, "
        f"needs {HEADROOM * PEAK_MIB[service]:.0f} MiB"
    )


@pytest.mark.parametrize("profile", PROFILES)
def test_the_stack_caps_hold_the_recorded_stack_peak(profile: str) -> None:
    stack = sum(v for k, v in _caps(profile).items() if k not in MODEL_SERVERS)
    assert stack >= HEADROOM * STACK_PEAK_GIB, (profile, stack)


@pytest.mark.parametrize("profile", PROFILES)
def test_the_caps_without_a_recorded_peak_are_listed(profile: str, capsys: pytest.CaptureFixture[str]) -> None:
    caps = _caps(profile)
    assert set(PEAK_MIB) <= set(caps)
    unmeasured = sorted(set(caps) - set(PEAK_MIB))
    print(f"{profile}: {len(unmeasured)} containers have no recorded 50,000-patient peak: {', '.join(unmeasured)}")
    assert unmeasured  # the list is not the whole box: a measured container is not in it


def test_every_recorded_peak_is_written_beside_its_cap() -> None:
    """The figure the test holds is the one a reader sees on the cap's own line."""
    needs = {"adapter": "3,842 MiB", "orchestrator": "3,973 MiB"}
    for profile in PROFILES:
        files = [DEPLOY / "docker-compose.yml", _overlay(profile)]
        text = "\n".join(f.read_text(encoding="utf-8") for f in files)
        for service, figure in needs.items():
            assert figure in text, (profile, service, figure)
