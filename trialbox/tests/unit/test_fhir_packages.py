"""The FHIR package set is fetched by the version in settings (T-676, DEP-016, D-372).

Offline: the registry is a stand-in that serves tiny synthetic tarballs, pinned in the test; nothing is downloaded.
The real pins are checked against packages.fhir.org when the fetch runs for real (``make jvm-deps``, which CI runs).
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import tarfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tools import fetch_fhir_packages as fhir

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = ROOT / "deploy" / "settings.example.yaml"
REGISTRY = "https://registry.invalid"


def _base(spec: str) -> str:
    """``name#version`` of a package or subset spec (no alias, no file list)."""
    return spec.partition(":")[0].partition("=")[0]


def _all_specs(version: str) -> list[str]:
    packages, subsets = fhir.twpas_set(version)
    return [*fhir.DEFAULT_PACKAGES, *packages, *subsets]


def test_settings_name_the_twpas_version_the_build_fetches() -> None:
    version = fhir.settings_twpas_version(SETTINGS)
    assert version == fhir.TWPAS_VERSION
    assert version in fhir.TWPAS_SETS
    # the platform copy, the wizard's default and the scenario's fallback name the same version
    assert fhir.settings_twpas_version(ROOT / "deploy" / "platform" / "base" / "settings.example.yaml") == version
    assert f'"twpas_version": "{version}"' in (ROOT / "tools" / "settings_wizard.py").read_text(encoding="utf-8")
    from orchestrator.scenarios import twpas

    assert f"tw.gov.mohw.nhi.pas#{version}" == twpas.DEFAULT_IG


def test_every_package_of_the_set_is_pinned() -> None:
    pins = fhir.pins()
    for spec in _all_specs(fhir.TWPAS_VERSION):
        assert _base(spec) in pins, spec
    assert f"tw.gov.mohw.nhi.pas#{fhir.TWPAS_VERSION}" in pins
    for digest in pins.values():
        assert re.fullmatch(r"[0-9a-f]{64}", digest)


def test_one_terminology_and_one_extensions_version() -> None:
    """DEP-016: the released extensions (no ballot) and one terminology release across the cache."""
    versions: dict[str, set[str]] = {}
    for spec in fhir.DEFAULT_PACKAGES:
        name, _, version = _base(spec).partition("#")
        versions.setdefault(name, set()).add(version)
    for name in ("hl7.terminology.r4", "hl7.terminology"):
        assert versions[name] == {fhir.TERMINOLOGY_VERSION}, name
    for name in ("hl7.fhir.uv.extensions.r4", "hl7.fhir.uv.extensions"):
        assert versions[name] == {fhir.EXTENSIONS_VERSION}, name
    assert "ballot" not in fhir.EXTENSIONS_VERSION and "ballot" not in fhir.TERMINOLOGY_VERSION


def test_fetch_script_reads_the_version_from_settings() -> None:
    script = (ROOT / "tools" / "fetch_jvm_deps.sh").read_text(encoding="utf-8")
    assert "--twpas-settings" in script and "deploy/settings.example.yaml" in script
    assert "tw.gov.mohw.nhi.pas#" not in script  # no second place that names the version
    assert fhir.DEFAULT_REGISTRY == "https://packages.fhir.org"


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ('profiles: {tw_core: "1.0.0", twpas_version: "1.2.5"}  # note\n', "1.2.5"),
        ("profiles:\n  tw_core: 1.0.0\n  twpas_version: 1.3.0\n", "1.3.0"),
        ("profiles: {twpas_version: '1.2.7'}\n", "1.2.7"),
    ],
)
def test_settings_twpas_version_reads_both_yaml_styles(tmp_path: Path, text: str, want: str) -> None:
    p = tmp_path / "settings.yaml"
    p.write_text(text, encoding="utf-8")
    assert fhir.settings_twpas_version(p) == want


def test_settings_without_one_version_stop_the_fetch(tmp_path: Path) -> None:
    p = tmp_path / "settings.yaml"
    p.write_text("profiles: {tw_core: 1.0.0}\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="found 0"):
        fhir.settings_twpas_version(p)


def test_a_version_without_a_package_set_stops_the_fetch(tmp_path: Path) -> None:
    p = tmp_path / "settings.yaml"
    p.write_text('profiles: {twpas_version: "9.9.9"}\n', encoding="utf-8")
    with pytest.raises(SystemExit, match="no package set"):
        fhir.main(["--cache", str(tmp_path / "cache"), "--registry", REGISTRY, "--twpas-settings", str(p)])
    assert not (tmp_path / "cache").exists() or not any((tmp_path / "cache").iterdir())


def _tarball(name: str, version: str, files: dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        members = {"package/package.json": {"name": name, "version": version, "dependencies": {}}, **files}
        for path, content in members.items():
            data = json.dumps(content).encode()
            info = tarfile.TarInfo(path)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """A stand-in registry with a tiny tarball for every package of the set, and pins for them."""
    blobs: dict[str, bytes] = {}
    for spec in _all_specs(fhir.TWPAS_VERSION):
        name, _, version = _base(spec).partition("#")
        files = {
            f"package/{f}": {"resourceType": "StructureDefinition"} for f in spec.partition(":")[2].split(",") if f
        }
        blobs[f"{name}#{version}"] = _tarball(name, version, files)
    pinned = {k: hashlib.sha256(v).hexdigest() for k, v in blobs.items()}
    monkeypatch.setattr(fhir, "pins", lambda path=fhir.PINS: pinned)

    def get(url: str) -> bytes:
        rest = url.removeprefix(f"{REGISTRY}/")
        if rest.startswith("tarballs/"):
            return blobs[rest.removeprefix("tarballs/")]
        versions = {
            k.partition("#")[2]: {"dist": {"tarball": f"{REGISTRY}/tarballs/{k}"}}
            for k in blobs
            if k.startswith(f"{rest}#")
        }
        return json.dumps({"versions": versions}).encode()

    monkeypatch.setattr(fhir, "_get", get)
    return blobs


def test_cached_twpas_is_the_settings_version(
    registry: dict[str, bytes], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The acceptance of T-676: the vendor fetch, run as fetch_jvm_deps.sh runs it, caches exactly the settings
    version, and the TWPAS scenario then validates against that version (not a fallback)."""
    cache = tmp_path / "fhir-home" / ".fhir" / "packages"
    assert fhir.main(["--cache", str(cache), "--registry", REGISTRY]) == 0
    assert fhir.main(["--cache", str(cache), "--registry", REGISTRY, "--twpas-settings", str(SETTINGS)]) == 0
    version = fhir.settings_twpas_version(SETTINGS)
    cached = sorted(p.name.partition("#")[2] for p in cache.glob("tw.gov.mohw.nhi.pas#*"))
    assert cached == [version]
    meta = json.loads((cache / f"tw.gov.mohw.nhi.pas#{version}" / "package" / "package.json").read_text("utf-8"))
    assert meta["version"] == version
    # the aliases the TWPAS IG declares, and the one Da Vinci PAS extension definition
    assert (
        json.loads((cache / "tw.gov.mohw.twcore#0.3.2" / "package" / "package.json").read_text("utf-8"))["version"]
        == "0.3.2"
    )
    davinci = next(cache.glob("hl7.fhir.us.davinci-pas#*")) / "package"
    assert sorted(p.name for p in davinci.iterdir()) == [
        "StructureDefinition-extension-diagnosisRecordedDate.json",
        "package.json",
    ]
    for name in ("hl7.terminology.r4", "hl7.fhir.uv.extensions.r4"):
        assert (
            cache / f"{name}#{fhir.TERMINOLOGY_VERSION if 'terminology' in name else fhir.EXTENSIONS_VERSION}"
        ).is_dir()

    from orchestrator.scenarios import twpas

    monkeypatch.delenv("TB_TWPAS_IG", raising=False)
    monkeypatch.setenv("TB_FHIR_PACKAGE_HOME", str(tmp_path / "fhir-home"))
    ctx: Any = SimpleNamespace(
        cfg=SimpleNamespace(settings=SimpleNamespace(profiles=SimpleNamespace(twpas_version=version)))
    )
    assert twpas.ig_spec(ctx) == f"tw.gov.mohw.nhi.pas#{version}"


def test_a_tampered_tarball_is_refused(registry: dict[str, bytes], tmp_path: Path) -> None:
    spec = f"tw.gov.mohw.nhi.pas#{fhir.TWPAS_VERSION}"
    registry[spec] = registry[spec] + b"tampered"
    cache = tmp_path / "cache"
    with pytest.raises(SystemExit, match="not the pinned"):
        fhir.main(["--cache", str(cache), "--registry", REGISTRY, "--twpas-settings", str(SETTINGS)])
    assert not (cache / spec).exists()
