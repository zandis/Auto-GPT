"""VLLM-HEADERS (D-622), the owner's ruling of 2026-11-12: one dated allow-list entry may accept every finding of
ONE package in ONE third-party image. It is written ``id: "*"`` with a package and an image; never for an image of
ours, never without either, never for a repository the project does not pin. Everything else about an entry holds:
a reason, a review date, the gates fail when the date has passed."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import pytest

from tools.supply_chain import allowlist, vulns

pytestmark = pytest.mark.nodb

IMAGE = "vllm/vllm-openai"
LOCK = json.loads((allowlist.ROOT / "deploy" / "images.lock").read_text(encoding="utf-8"))
DIGEST = next(e["digest"] for e in LOCK["third_party"].values() if e["image"].startswith(IMAGE + ":"))
REF = f"{IMAGE}:v0.32.0@{DIGEST}"  # the pinned image, as the release gates name it
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
        f"someone/vllm/vllm-openai:1@{DIGEST}",
        f"vllm/vllm-openai-x:1@{DIGEST}",
        # review M2: the ruling is for the PINNED image: another digest, or none (a local image under that name)
        f"{IMAGE}:v0.33.0@sha256:" + "c" * 64,
        f"{IMAGE}:v0.32.0",
        IMAGE,
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
    assert wide == [(PKG, IMAGE, dt.date(2027, 1, 10))]
    assert not [e for e in allow.vulnerabilities if e.package == PKG and e.id != "*"]  # the 257 per-id entries


# ------------------------------------------------------------------------------------------------ the review
def test_review_a_finding_the_scanner_could_not_grade_or_name_is_not_accepted_by_the_wide_entry() -> None:
    """An entry for one id accepts a finding someone looked at. The wide entry accepts findings nobody has seen:
    one with a severity the gate cannot read, or with no id, still fails."""
    allow = _allow(_entry())
    odd = vulns.Finding("trivy", "img", PKG, "6.8.0-147.147", "CVE-9", (), f"{vulns.INVALID}('x')", "")
    nameless = vulns.Finding("trivy", "img", PKG, "6.8.0-147.147", "?", (), "HIGH", "")
    result = vulns.gate([odd, nameless, _finding("CVE-1")], allow, subject=REF)
    assert sorted(f.id for f in result.failing) == ["?", "CVE-9"] and len(result.accepted) == 1


def test_review_the_lock_that_cannot_be_read_refuses_every_wide_entry(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    for text in ("", "[]", '{"third_party": []}', "not json"):
        lock = tmp_path / "images.lock"
        lock.write_text(text, encoding="utf-8")
        monkeypatch.setattr(allowlist, "IMAGES_LOCK", lock)
        _, errors = allowlist.parse({"vulnerabilities": [_entry()]}, today=ON)
        assert any("not a third-party image of deploy/images.lock" in e for e in errors), (text, errors)
    monkeypatch.setattr(allowlist, "IMAGES_LOCK", tmp_path / "none")
    _, errors = allowlist.parse({"vulnerabilities": [_entry()]}, today=ON)
    assert errors


def test_review_two_wide_entries_and_other_images_entries() -> None:
    _, errors = allowlist.parse({"vulnerabilities": [_entry(), _entry(package="Linux_libc.dev")]}, today=ON)
    assert any("duplicate entry" in e for e in errors), errors
    other = _entry(id="CVE-1", image="hapiproject/hapi")  # the same package in another image: its own entry stays
    _allow(_entry(), other)
    _, errors = allowlist.parse({"vulnerabilities": [_entry(review_by="2025-01-01"), _entry(id="CVE-1")]}, today=ON)
    assert not any("covered by the entry for every id" in e for e in errors)  # a refused wide entry covers nothing


@pytest.mark.parametrize("image", ["docker.io/vllm/vllm-openai", "vllm/*", "library/caddy", "VLLM/vllm-openai"])
def test_review_the_image_is_written_as_the_lock_writes_it(image: str) -> None:
    _, errors = allowlist.parse({"vulnerabilities": [_entry(image=image)]}, today=ON)
    assert errors, image


def test_review_the_documents_say_what_the_entry_does() -> None:
    root = allowlist.ROOT
    for path in ("deploy/security/known-image-findings.md", "docs/security/08-supply-chain.md",
                 "deploy/supply-chain-allowlist.yaml"):  # fmt: skip
        assert "D-622" in (root / path).read_text(encoding="utf-8"), path
    assert "D-622" in (allowlist.__doc__ or "")
