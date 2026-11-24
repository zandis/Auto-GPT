"""Lane B card B-1 (the release bundle's 702 findings, 2026-11-22): the D-622 entry for every finding of one package
in the pinned engine image is matched on the scanned CONTENT's digest, not only on the reference's text.

The bench scanned the pinned engine image under its tag (``vllm/vllm-openai:v0.32.0``, a local image pulled by
tag); the entry matched only a reference ending in the lock's digest, so all 702 kernel-header findings failed the
gate while the same content, scanned by ``tag@digest``, passed. Invariant, both ways:

* the content the lock pins passes under any name, when the scanner or the image store records it as that
  repository at that digest;
* other content (another digest, another repository, no digest at all) fails exactly as before, and the gate says
  plainly that the scan was not of the pinned digest and what the lock pins.

Nothing about the entry's reach changes otherwise: one package, one image, dated; the threshold is untouched.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tools.supply_chain import allowlist, release, sbom, vulns

pytestmark = pytest.mark.nodb

IMAGE = "vllm/vllm-openai"
LOCK = json.loads((allowlist.ROOT / "deploy" / "images.lock").read_text(encoding="utf-8"))
ENTRY = next(e for e in LOCK["third_party"].values() if e["image"].startswith(IMAGE + ":"))
DIGEST = ENTRY["digest"]
TAG = ENTRY["image"]  # vllm/vllm-openai:v0.32.0, as the measured serving record names it
OTHER = "sha256:" + "c" * 64
PLATFORM_MANIFEST = ENTRY["platforms"]["linux/amd64"]["manifest"]  # a digest, but not the index digest the lock pins
PKG = "linux-libc-dev"
REASON = "Ubuntu kernel headers of the upstream image, build-time files and not the running kernel"
ON = dt.date(2026, 11, 22)


def _allow() -> allowlist.Allowlist:
    entries: list[dict[str, Any]] = [
        {"id": "*", "package": PKG, "image": IMAGE, "reason": REASON, "review_by": "2027-01-10"},
        {"id": "CVE-2026-1", "package": "openssl", "image": IMAGE, "reason": REASON, "review_by": "2027-01-10"},
    ]
    allow, errors = allowlist.parse({"vulnerabilities": entries}, today=ON)
    assert errors == [], errors
    return allow


def _headers(n: int = 3) -> list[vulns.Finding]:
    return [
        vulns.Finding("trivy", "img", PKG, "6.8.0-147.147", f"CVE-2026-9{i:04d}", (), "HIGH", "6.8.0-151.151")
        for i in range(n)
    ]


def _fails() -> Any:
    return vulns.trivy_fails(vulns.DEFAULT_FAIL_SEVERITIES, False)


# ------------------------------------------------------------------------------------- the pinned content passes
@pytest.mark.parametrize(
    "digests",
    [
        (f"{IMAGE}@{DIGEST}",),  # docker image inspect RepoDigests of a local pull by tag
        (f"docker.io/{IMAGE}@{DIGEST}",),  # the same, as the scanner writes it with the registry
        (f"{IMAGE}@{OTHER}", f"{IMAGE}@{DIGEST}"),  # one of several
    ],
)
def test_the_pinned_content_scanned_by_its_tag_is_accepted(digests: tuple[str, ...]) -> None:
    result = vulns.gate(_headers(), _allow(), fails=_fails(), subject=TAG, digests=digests)
    assert result.failing == [] and len(result.accepted) == 3, result.render("t")
    assert result.errors == []


def test_the_pinned_reference_itself_still_passes_with_no_recorded_digests() -> None:
    result = vulns.gate(_headers(), _allow(), fails=_fails(), subject=f"{TAG}@{DIGEST}")
    assert result.failing == [] and result.errors == []


# ------------------------------------------------------------------------------------------ other content fails
@pytest.mark.parametrize(
    ("subject", "digests"),
    [
        (TAG, ()),  # a name alone: the bench's 702
        (TAG, (f"{IMAGE}@{OTHER}",)),  # the tag now points at other content
        (TAG, (f"{IMAGE}@{PLATFORM_MANIFEST}",)),  # a platform's manifest is not the pinned index
        (f"{IMAGE}@{OTHER}", (f"{IMAGE}@{OTHER}",)),
        (TAG, (f"someone/vllm-openai@{DIGEST}",)),  # the pinned digest under another repository
        (TAG, (f"someone/{IMAGE}@{DIGEST}",)),  # a longer path that only ends the same way
        (TAG, (DIGEST,)),  # a bare digest names no repository
    ],
)
def test_other_content_still_fails_and_the_gate_says_why(subject: str, digests: tuple[str, ...]) -> None:
    result = vulns.gate(_headers(), _allow(), fails=_fails(), subject=subject, digests=digests)
    assert [f.package for f in result.failing] == [PKG] * 3
    assert len(result.errors) == 1, result.errors
    msg = result.errors[0]
    assert "not the lock's" in msg and PKG in msg and DIGEST in msg and "scan the pinned reference" in msg
    assert not result.ok


def test_another_repository_with_the_pinned_digest_recorded_is_not_the_pinned_image() -> None:
    result = vulns.gate(_headers(), _allow(), fails=_fails(), subject="someone/other:1", digests=(f"{IMAGE}@{DIGEST}",))
    assert len(result.failing) == 3 and result.errors == []  # not this entry's repository: no D-622 message either


def test_the_per_finding_entries_are_unchanged_by_the_digests() -> None:
    f = vulns.Finding("trivy", "img", "openssl", "3.0.13", "CVE-2026-1", (), "CRITICAL", "3.0.14")
    g = vulns.Finding("trivy", "img", "openssl", "3.0.13", "CVE-2026-2", (), "CRITICAL", "3.0.14")
    result = vulns.gate([f, g], _allow(), fails=_fails(), subject=TAG, digests=(f"{IMAGE}@{DIGEST}",))
    assert [x.id for x, _ in result.accepted] == ["CVE-2026-1"] and result.failing == [g]
    assert result.errors == []  # a new finding of another package fails as always, with no D-622 message


def test_a_finding_the_scanner_could_not_grade_still_fails_at_the_pinned_content_with_no_d622_message() -> None:
    bad = vulns.Finding("trivy", "img", PKG, "6.8.0-147.147", "CVE-2026-1", (), "INVALID(None)", "6.8.0-151.151")
    result = vulns.gate([bad], _allow(), fails=_fails(), subject=TAG, digests=(f"{IMAGE}@{DIGEST}",))
    assert result.failing == [bad] and result.errors == []


def test_no_subject_no_entry_and_no_message() -> None:  # the lock's own gate (pip-audit) has no image
    result = vulns.gate(_headers(1), _allow(), fails=_fails(), digests=(f"{IMAGE}@{DIGEST}",))
    assert len(result.failing) == 1 and result.errors == []


def test_an_unreadable_lock_accepts_nothing_by_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    allow = _allow()  # read while the lock is readable; the gate then runs without it
    monkeypatch.setattr(allowlist, "IMAGES_LOCK", allowlist.ROOT / "no-such-images.lock")
    result = vulns.gate(_headers(1), allow, fails=_fails(), subject=TAG, digests=(f"{IMAGE}@{DIGEST}",))
    assert len(result.failing) == 1 and "nothing readable" in result.errors[0]


# -------------------------------------------------------------------------------- the release gates pass them on
FIX = allowlist.ROOT / "tests" / "fixtures" / "supply_chain"


def _gate_local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, store_digests: list[str]) -> dict[str, Any]:
    """``run_gates`` on a local image named by its tag, the scanners and the image store stood in: the scanner's
    report holds three kernel-header findings and the image store's record of the content (``store_digests``)."""
    data = json.loads((FIX / "trivy_clean.json").read_text(encoding="utf-8"))
    data["ArtifactName"] = TAG
    data["Metadata"].update(ImageID="sha256:cfg", RepoDigests=store_digests, RepoTags=[TAG])
    data["Results"][0]["Vulnerabilities"] = [
        {"VulnerabilityID": f.id, "PkgName": f.package, "InstalledVersion": f.version, "Severity": f.severity,
         "FixedVersion": f.fixed}
        for f in _headers()
    ]  # fmt: skip

    def fake_run(cmd: list[str], **_kw: Any) -> subprocess.CompletedProcess[str]:
        Path(cmd[cmd.index("--output") + 1]).write_text(json.dumps(data), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)  # the module release.py calls
    monkeypatch.setattr(
        release, "inspect_local", lambda ref: {"image_id": "sha256:cfg", "repo_digests": store_digests,
                                               "platform": "linux/amd64"}
    )  # fmt: skip

    def fake_syft(_source: str, out: Path, *_a: Any, **_k: Any) -> dict[str, Any]:
        doc: dict[str, Any] = {"metadata": {}, "components": []}
        out.write_text(json.dumps(doc), encoding="utf-8")
        return doc

    monkeypatch.setattr(sbom, "run_syft", fake_syft)
    monkeypatch.setattr(release, "identity_problems", lambda *a, **k: [])
    record = release.run_gates(
        [release.Target(TAG)], cache_dir=tmp_path / "c", out_dir=tmp_path / "o", sbom_dir=tmp_path / "s",
        allow=_allow(), allow_errors=[], lock_sbom=None, now=dt.datetime(2026, 11, 22, tzinfo=dt.UTC),
    )  # fmt: skip
    entry: dict[str, Any] = record["images"][0]
    return entry


def test_the_release_gates_pass_the_pinned_content_pulled_by_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _gate_local(tmp_path, monkeypatch, [f"{IMAGE}@{DIGEST}"])
    assert entry.get("errors") == [], entry.get("errors")
    assert entry["failing"] == [] and entry["ok"] is True
    assert len(entry["accepted"]) == 3


def test_the_release_gates_refuse_other_content_by_tag_and_record_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _gate_local(tmp_path, monkeypatch, [f"{IMAGE}@{OTHER}"])
    assert len(entry["failing"]) == 3 and entry["ok"] is False
    assert any("not the lock's" in e and DIGEST in e and OTHER in e for e in entry["errors"]), entry["errors"]
