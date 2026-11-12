"""VLLM-HEADERS (D-622), the owner's ruling of 2026-11-12: one dated allow-list entry may accept every finding of
ONE package in ONE third-party image. It is written ``id: "*"`` with a package and an image; never for an image of
ours, never without either, never for a repository the project does not pin. Everything else about an entry holds:
a reason, a review date, the gates fail when the date has passed."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from tools.supply_chain import allowlist, vulns

pytestmark = pytest.mark.nodb

IMAGE = "vllm/vllm-openai"
REF = f"{IMAGE}:v0.32.0@sha256:" + "b" * 64
PKG = "linux-libc-dev"
REASON = "Ubuntu kernel headers of the upstream image, build-time files and not the running kernel"
ON = dt.date(2026, 11, 12)


def _entry(**over: Any) -> dict[str, Any]:
    return {"id": "*", "package": PKG, "image": IMAGE, "reason": REASON, "review_by": "2026-12-10", **over}


def _allow(*entries: dict[str, Any]) -> allowlist.Allowlist:
    allow, errors = allowlist.parse({"vulnerabilities": list(entries)}, today=ON)
    assert errors == [], errors
    return allow


def _finding(fid: str, package: str = PKG) -> vulns.Finding:
    return vulns.Finding("trivy", "img", package, "6.8.0-147.147", fid, (), "HIGH", "6.8.0-150.150")


# ------------------------------------------------------------------------------------------------ what it accepts
def test_every_id_of_the_package_in_the_image_is_accepted() -> None:
    allow = _allow(_entry())
    result = vulns.gate([_finding("CVE-2026-74668"), _finding("CVE-2026-89973")], allow, subject=REF)
    assert result.failing == [] and len(result.accepted) == 2
    assert all(reason == REASON for _f, reason in result.accepted)
    assert result.unused_entries == []


def test_another_package_of_the_same_image_still_fails() -> None:
    result = vulns.gate([_finding("CVE-1", "openssl")], _allow(_entry()), subject=REF)
    assert [f.id for f in result.failing] == ["CVE-1"]


@pytest.mark.parametrize(
    "subject",
    [
        "hapiproject/hapi:v8@sha256:" + "c" * 64,
        "trialbox-py:1.0.0",
        "someone/vllm/vllm-openai:1",
        "vllm/vllm-openai-x:1",
    ],
)
def test_the_same_package_in_any_other_image_still_fails(subject: str) -> None:
    result = vulns.gate([_finding("CVE-1")], _allow(_entry()), subject=subject)
    assert [f.id for f in result.failing] == ["CVE-1"], subject


def test_the_entry_matches_its_repository_in_another_registry_and_nothing_without_a_subject() -> None:
    allow = _allow(_entry())
    assert vulns.gate([_finding("CVE-1")], allow, subject=f"mirror.example/{REF}").failing == []
    assert [f.id for f in vulns.gate([_finding("CVE-1")], allow, subject=None).failing] == ["CVE-1"]  # the lock's gate


# ------------------------------------------------------------------------------------------------ what it refuses
@pytest.mark.parametrize(
    ("entry", "needle"),
    [
        (_entry(image=None), "needs an image"),  # every image: a blanket rule
        (_entry(package=None), "no package"),
        (_entry(package="*"), "one package"),
        (_entry(image="trialbox-py"), "our own images"),
        (_entry(image="vllm"), "not a third-party image of deploy/images.lock"),  # a word that many names end in
        (_entry(image="someone/else"), "not a third-party image of deploy/images.lock"),
        (_entry(image="vllm/vllm-openai:v0.32.0"), "without tag or digest"),
        (_entry(reason="short"), "too short"),
        (_entry(review_by="2025-01-01"), "has passed"),
        (_entry(review_by="2027-11-12"), "days ahead"),
    ],
)
def test_a_wider_or_undated_entry_is_refused(entry: dict[str, Any], needle: str) -> None:
    entry = {k: v for k, v in entry.items() if v is not None}
    _, errors = allowlist.parse({"vulnerabilities": [entry]}, today=ON)
    assert any(needle in e for e in errors), errors


def test_an_entry_for_one_id_beside_the_entry_for_all_is_refused_as_dead_weight() -> None:
    one = _entry(id="CVE-2026-74668")
    _, errors = allowlist.parse({"vulnerabilities": [_entry(), one]}, today=ON)
    assert any("covered by the entry for every id" in e for e in errors), errors


def test_a_review_date_that_has_passed_fails_the_gate() -> None:
    allow, errors = allowlist.parse({"vulnerabilities": [_entry()]}, today=dt.date(2026, 12, 11))
    assert any("has passed" in e for e in errors)
    assert [f.id for f in vulns.gate([_finding("CVE-1")], allow, subject=REF).failing] == ["CVE-1"]


# ------------------------------------------------------------------------------------------------ the shipped list
def test_the_shipped_list_has_the_one_entry_the_owner_ruled_on() -> None:
    allow, errors = allowlist.load(today=ON)
    assert errors == []
    wide = [(e.package, e.image, e.review_by) for e in allow.vulnerabilities if e.id == "*"]
    assert wide == [(PKG, IMAGE, dt.date(2026, 12, 10))]
    assert not [e for e in allow.vulnerabilities if e.package == PKG and e.id != "*"]  # the 257 per-id entries
