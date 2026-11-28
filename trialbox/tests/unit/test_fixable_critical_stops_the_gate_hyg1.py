"""Release hygiene item 1: a fixable CRITICAL finding in an image is a stop of the release gates.

Before, a dated allow-list entry could accept any finding of an image, a CRITICAL one with a fixed version included.
Now no entry accepts it in an image scan: the image moves to the fixed version, or the release stops. A CRITICAL with
no fix, a fixable HIGH, and the locked Python packages' audit (no image) keep the allow-list's dated entries. The
test-only mail servers, which no bundle carries, stay report-only. Fixed dates; synthetic findings only.
"""

from __future__ import annotations

import datetime as dt

from tools.supply_chain import allowlist, release, vulns

TODAY = dt.date(2026, 11, 27)
IMAGE = "example/fhir-server:1.0.0"
REASON = "Not reachable: the server has no route out of the box"


def _allow(package: str, vid: str, image: str | None = IMAGE) -> allowlist.Allowlist:
    entry = {"id": vid, "package": package, "reason": REASON, "review_by": "2027-01-10"}
    if image:
        entry["image"] = image.split(":")[0]
    allow, errors = allowlist.parse({"vulnerabilities": [entry]}, today=TODAY)
    assert errors == []
    return allow


def _finding(vid: str, severity: str, fixed: str) -> vulns.Finding:
    return vulns.Finding("trivy", IMAGE, "libexample", "1.0", vid, (), severity, fixed)


def _gate(f: vulns.Finding, subject: str | None = IMAGE) -> vulns.GateResult:
    fails = vulns.trivy_fails(vulns.DEFAULT_FAIL_SEVERITIES, False)
    return vulns.gate([f], _allow("libexample", f.id, subject), fails=fails, subject=subject)


def test_a_fixable_critical_in_an_image_is_never_accepted_by_the_allow_list() -> None:
    got = _gate(_finding("CVE-2026-0001", "CRITICAL", "1.1"))
    assert [f.id for f in got.failing] == ["CVE-2026-0001"] and got.accepted == [] and not got.ok
    assert any("CVE-2026-0001" in e and "fixable CRITICAL" in e for e in got.errors)


def test_a_critical_without_a_fix_and_a_fixable_high_keep_their_dated_entries() -> None:
    assert _gate(_finding("CVE-2026-0002", "CRITICAL", "")).ok
    assert _gate(_finding("CVE-2026-0003", "HIGH", "1.1")).ok


def test_the_locked_packages_audit_has_no_image_and_keeps_its_entries() -> None:
    assert _gate(_finding("CVE-2026-0004", "CRITICAL", "1.1"), subject=None).ok


def test_the_test_only_mail_servers_stay_report_only() -> None:
    f = _finding("CVE-2026-0005", "CRITICAL", "1.1")
    blocking, deferred = release.split_report_mode([f], "greenmail/standalone:2.1.3", "report")
    assert blocking == [] and deferred == [f]
