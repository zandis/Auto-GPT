"""OPS-004b (D-574), the owner's ruling of 2026-11-12: an image may have an OS package list the scanner cannot
read only with its own dated allow-list entry that names the image. No blanket rule: without the entry the report
is refused as before; with the entry the report must still show packages of some kind; and an entry for an image
whose OS packages are readable is refused as stale."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from tools.supply_chain import allowlist, vulns

pytestmark = pytest.mark.nodb

IMAGE = "authelia/authelia"
REF = f"{IMAGE}:4.39.28@sha256:" + "b" * 64
REASON = "The image ships no package database; its Go binary is scanned and the SBOM lists its packages"
ON = dt.date(2026, 11, 12)


def _report(*, os_packages: bool, binary: bool = True, artifact: str = REF) -> dict[str, Any]:
    results: list[dict[str, Any]] = [
        {"Target": f"{artifact} (ubuntu 26.04)", "Class": "os-pkgs", "Type": "ubuntu",
         **({"Packages": [{"Name": "zlib1g", "Version": "1"}]} if os_packages else {})},
    ]  # fmt: skip
    if binary:
        results.append({
            "Target": "app/authelia", "Class": "lang-pkgs", "Type": "gobinary",
            "Packages": [{"Name": "stdlib", "Version": "v1.27.1"}],
            "Vulnerabilities": [{"VulnerabilityID": "CVE-1", "PkgName": "stdlib", "InstalledVersion": "v1.27.1",
                                 "Severity": "HIGH", "FixedVersion": "1.27.2"}],
        })  # fmt: skip
    return {"ArtifactName": artifact, "Results": results, "Metadata": {"ImageConfig": {"os": "linux"}}}


def _entry(**over: Any) -> dict[str, Any]:
    return {"image": IMAGE, "reason": REASON, "review_by": "2026-12-10", **over}


def _allow(*entries: dict[str, Any]) -> allowlist.Allowlist:
    allow, errors = allowlist.parse({"os_packages_unreadable": list(entries)}, today=ON)
    assert errors == [], errors
    return allow


# ------------------------------------------------------------------------------------------------ the report
def test_without_an_entry_a_report_with_no_os_packages_is_refused_as_before() -> None:
    with pytest.raises(vulns.ReportError, match="no OS packages"):
        vulns.parse_trivy(_report(os_packages=False))


def test_with_the_images_entry_the_report_is_read_and_its_findings_are_gated() -> None:
    report = vulns.parse_trivy(_report(os_packages=False), os_unreadable=True)
    assert [f.id for f in report.findings] == ["CVE-1"]


def test_the_entry_does_not_let_through_a_report_that_shows_no_package_at_all() -> None:
    with pytest.raises(vulns.ReportError, match="no language packages"):
        vulns.parse_trivy(_report(os_packages=False, binary=False), os_unreadable=True)


def test_review_m2_the_entry_needs_language_packages_not_just_any_result() -> None:
    """A report whose only content is a secret scan or nothing a package scan produced is not a scan of the binary."""
    data = _report(os_packages=False, binary=False)
    data["Results"].append({"Target": "x", "Class": "secret", "Packages": [{"Name": "n"}]})
    with pytest.raises(vulns.ReportError, match="no language packages"):
        vulns.parse_trivy(data, os_unreadable=True)


def test_an_entry_for_an_image_whose_os_packages_are_readable_is_stale() -> None:
    with pytest.raises(vulns.ReportError, match="remove its os_packages_unreadable entry"):
        vulns.parse_trivy(_report(os_packages=True), os_unreadable=True)


# ------------------------------------------------------------------------------------------------ the entry
def test_the_entry_names_one_image_repository() -> None:
    allow = _allow(_entry())
    assert allow.os_unreadable(REF) is not None
    assert allow.os_unreadable(f"registry.example/{REF}") is not None  # the same repository in another registry
    assert allow.os_unreadable("caddy:2.11.9-alpine") is None
    assert allow.os_unreadable("authelia/authelia-extra:1") is None
    # review M1: the entry is one repository, not every repository whose name ends the same way
    assert allow.os_unreadable("someone/authelia/authelia:1") is None
    assert allow.os_unreadable("localhost:5000/authelia/authelia:1") is not None
    assert allow.os_unreadable("mirror.example/someone/authelia/authelia:1") is None
    assert allowlist.Allowlist([], []).os_unreadable(REF) is None


@pytest.mark.parametrize(
    ("entry", "needle"),
    [
        ({"reason": REASON, "review_by": "2026-12-10"}, "needs an image"),
        (_entry(image="authelia/authelia:4.39.28"), "without tag or digest"),
        (_entry(image="*"), "one image repository"),
        (_entry(image="trialbox-py"), "our own images"),
        (_entry(image="authelia"), "not a third-party image of deploy/images.lock"),  # review M1: `x/authelia` too
        (_entry(image="hapi"), "not a third-party image of deploy/images.lock"),
        (_entry(image="someone/else"), "not a third-party image of deploy/images.lock"),
        (_entry(image="\uff41uthelia/authelia"), "one image repository"),  # a full-width letter
        (_entry(reason="short"), "too short"),
        (_entry(review_by="2025-01-01"), "has passed"),
        (_entry(review_by="2027-11-12"), "days ahead"),
        (_entry(extra=1), "unknown key"),
    ],
)
def test_a_bad_entry_is_refused(entry: dict[str, Any], needle: str) -> None:
    _, errors = allowlist.parse({"os_packages_unreadable": [entry]}, today=ON)
    assert any(needle in e for e in errors), errors


def test_one_entry_per_image() -> None:
    _, errors = allowlist.parse({"os_packages_unreadable": [_entry(), _entry()]}, today=ON)
    assert any("duplicate" in e for e in errors), errors


# ------------------------------------------------------------------------------------------------ the gates use it
def test_the_gate_reads_the_entry_for_the_scanned_image_only(tmp_path: Path) -> None:
    mine, other = tmp_path / "authelia.trivy.json", tmp_path / "other.trivy.json"
    mine.write_text(json.dumps(_report(os_packages=False)), encoding="utf-8")
    other.write_text(json.dumps(_report(os_packages=False, artifact="some/other:1")), encoding="utf-8")
    result = vulns.trivy_gate([mine, other], _allow(_entry()))
    assert [e for e in result.errors if "authelia" in e] == []
    assert any("other.trivy.json" in e and "no OS packages" in e for e in result.errors)
    assert [f.id for f in result.failing] == ["CVE-1"]  # read, and still gated


def test_the_release_gates_pass_the_entry_to_the_report() -> None:
    text = (Path(vulns.__file__).parent / "release.py").read_text(encoding="utf-8")
    assert "os_unreadable=allow.os_unreadable(target.ref) is not None" in text


def test_the_shipped_list_has_the_one_image_the_owner_ruled_on() -> None:
    allow, _ = allowlist.load(today=None)
    assert [(e.image, e.review_by) for e in allow.os_packages_unreadable] == [(IMAGE, dt.date(2026, 12, 10))]
