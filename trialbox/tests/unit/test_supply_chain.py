"""Supply-chain gates (D-185, D-186): hashed lock, allow-list, pip-audit and Trivy gates, SBOMs, licences, release.

Offline: the scanners' JSON comes from small fixtures in ``tests/fixtures/supply_chain`` (the Trivy and lock-SBOM
fixtures are trimmed from real Trivy 0.75.0 and Syft 1.56.0 output of 2026-11-09). The tests that run
``uv export``/``uv lock --check --offline`` need only the pinned uv and skip without it. Dates are relative to the
day the tests run, so nothing expires in the test suite; "today" is injected through ``allowlist.today``.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import io
import json
import shutil
import tarfile
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.supply_chain import __main__ as cli
from tools.supply_chain import allowlist, licences, lock, release, sbom, scanners, vulns

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures" / "supply_chain"
TODAY = dt.date.today()
H1 = "a" * 64
H2 = "b" * 64
needs_uv = pytest.mark.skipif(
    shutil.which("uv") is None or lock.uv_version() != lock.UV_VERSION,
    reason=f"needs uv {lock.UV_VERSION} on PATH (another version may format the export differently)",
)
GOOD_REASON = "Not reachable: the box never parses untrusted fonts"


def days(n: int) -> str:
    """An ISO date ``n`` days from today."""
    return (TODAY + dt.timedelta(days=n)).isoformat()


def _allow(data: object) -> allowlist.Allowlist:
    allow, errors = allowlist.parse(data, today=TODAY)
    assert errors == []
    return allow


def _vuln(vid: str, package: str, review: int = 30) -> dict[str, str]:
    return {"id": vid, "package": package, "reason": GOOD_REASON, "review_by": days(review)}


def _lic(package: str, cls: str, **extra: str) -> dict[str, str]:
    return {"package": package, "class": cls, "reason": GOOD_REASON, "review_by": days(30), **extra}


def _write_allow(tmp_path: Path, data: object) -> Path:
    p = tmp_path / "allow.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def _json(name: str) -> Any:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _dump(tmp_path: Path, name: str, data: Any) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


# ---------------------------------------------------------------- the hashed lock (D-185)


def test_requirements_with_hashes_pass() -> None:
    text = (
        "# header\n"
        f"anyio==4.16.0 \\\n    --hash=sha256:{H1} \\\n    --hash=sha256:{H2}\n    # via httpx\n"
        f"brotli==1.2.1 ; platform_python_implementation == 'CPython' \\\n    --hash=sha256:{H1}\n"
    )
    assert lock.check_requirements_hashes(text) == []
    reqs = lock.parse_requirements(text)
    assert [(r.name, r.version, len(r.hashes)) for r in reqs] == [("anyio", "4.16.0", 2), ("brotli", "1.2.1", 1)]
    assert reqs[1].marker == "platform_python_implementation == 'CPython'"


@pytest.mark.parametrize(
    ("text", "needle"),
    [
        ("anyio==4.16.0\n", "has no --hash"),
        (f"anyio==4.16.0 --hash=md5:{'c' * 32}\n", "not sha256"),
        ("anyio==4.16.0 --hash=sha256:abc\n", "not sha256"),
        (f"anyio>=4 --hash=sha256:{H1}\n", "not pinned"),
        (f"-e ./libs\nanyio==4.16.0 --hash=sha256:{H1}\n", "option not allowed"),
        (f"--index-url https://example.invalid/simple\nanyio==4.16.0 --hash=sha256:{H1}\n", "option not allowed"),
        (f"anyio==4.16.0 --hash=sha256:{H1}\nanyio==4.15.0 --hash=sha256:{H2}\n", "more than once"),
        ("# only comments\n\n", "no requirements"),
    ],
)
def test_requirements_without_hashes_fail(text: str, needle: str) -> None:
    problems = lock.check_requirements_hashes(text)
    assert any(needle in p for p in problems), problems


def test_one_missing_hash_among_many_is_named() -> None:
    text = f"anyio==4.16.0 --hash=sha256:{H1}\nidna==3.11\nh11==0.16.0 --hash=sha256:{H2}\n"
    assert lock.check_requirements_hashes(text) == ["line 2: idna==3.11 has no --hash"]


def test_shipped_requirements_lock_is_fully_hashed() -> None:
    text = lock.REQUIREMENTS_LOCK.read_text(encoding="utf-8")
    assert lock.check_requirements_hashes(text) == []
    names = {r.name for r in lock.parse_requirements(text)}
    assert {"pypdf", "pillow", "psycopg", "cryptography"} <= names


def test_shipped_pip_audit_lock_is_hashed_and_pinned() -> None:
    text = lock.PIP_AUDIT_LOCK.read_text(encoding="utf-8")
    assert lock.check_requirements_hashes(text) == []
    assert {r.name: r.version for r in lock.parse_requirements(text)}["pip-audit"] == lock.PIP_AUDIT_VERSION


def test_shipped_requirements_lock_has_patched_versions() -> None:
    """Layer-2 review R-19: pypdf >= 6.21.4 and pillow >= 13 (advisories below them)."""
    reqs = {r.name: r.version for r in lock.parse_requirements(lock.REQUIREMENTS_LOCK.read_text(encoding="utf-8"))}
    assert tuple(int(x) for x in str(reqs["pypdf"]).split(".")[:3]) >= (6, 21, 4)
    assert int(str(reqs["pillow"]).split(".")[0]) >= 13


def test_shipped_uv_lock_records_sha256_for_every_file() -> None:
    assert lock.check_uv_lock((ROOT / "uv.lock").read_text(encoding="utf-8")) == []


def test_uv_lock_without_hash_or_from_git_fails() -> None:
    text = f"""
version = 1
[[package]]
name = "good"
version = "1.0"
source = {{ registry = "https://pypi.org/simple" }}
wheels = [{{ url = "https://x/good-1.0-py3-none-any.whl", hash = "sha256:{H1}" }}]

[[package]]
name = "nohash"
version = "1.0"
source = {{ registry = "https://pypi.org/simple" }}
sdist = {{ url = "https://x/nohash-1.0.tar.gz" }}

[[package]]
name = "fromgit"
version = "0.1"
source = {{ git = "https://example.invalid/x.git" }}

[[package]]
name = "trialbox"
version = "1.0.0"
source = {{ editable = "." }}
"""
    problems = lock.check_uv_lock(text)
    assert any("nohash==1.0" in p and "no sha256" in p for p in problems)
    assert any("fromgit==0.1" in p and "not a registry" in p for p in problems)
    assert not any("good==" in p or "trialbox==" in p for p in problems)
    assert lock.check_uv_lock("not toml [[") != []


@needs_uv
def test_shipped_requirements_lock_equals_uv_export() -> None:
    """Stale check without the network: the checked-in export is exactly what uv.lock exports to."""
    expected = lock.export_requirements()
    actual = lock.REQUIREMENTS_LOCK.read_text(encoding="utf-8")
    assert expected == actual, "run `make lock`\n" + lock.diff(expected, actual)


def _copy_project(tmp_path: Path) -> Path:
    for name in ("pyproject.toml", "uv.lock", "README.md"):
        shutil.copy(ROOT / name, tmp_path / name)
    (tmp_path / "deploy").mkdir()
    shutil.copy(lock.REQUIREMENTS_LOCK, tmp_path / "deploy" / "requirements.lock")
    (tmp_path / "tools" / "supply_chain").mkdir(parents=True)
    shutil.copy(lock.PIP_AUDIT_LOCK, tmp_path / "tools" / "supply_chain" / "pip-audit.lock")
    return tmp_path


@needs_uv
def test_lock_check_fails_on_hand_edited_or_stale_lock(tmp_path: Path) -> None:
    root = _copy_project(tmp_path)
    assert lock.lock_check(root, offline=True) == []

    # a hand edit (a hash dropped) is caught: no longer the export of uv.lock
    req = root / "deploy" / "requirements.lock"
    text = req.read_text(encoding="utf-8")
    first_hash = next(line for line in text.splitlines() if "--hash=sha256:" in line)
    req.write_text(text.replace(first_hash + "\n", "", 1).replace(" \\\n    # via", "\n    # via", 1), "utf-8")
    problems = lock.lock_check(root, offline=True)
    assert any("differs from `uv export`" in p for p in problems)

    # pyproject gains a dependency that uv.lock does not have: uv.lock is stale
    req.write_text(text, encoding="utf-8")
    pp = root / "pyproject.toml"
    pp.write_text(
        pp.read_text(encoding="utf-8").replace('"zstandard', '"tb-not-a-real-package>=1",\n  "zstandard'), "utf-8"
    )
    problems = lock.lock_check(root, offline=True)
    assert any("uv.lock is stale" in p for p in problems), problems


@needs_uv
def test_lock_check_fails_on_unhashed_pip_audit_lock(tmp_path: Path) -> None:
    root = _copy_project(tmp_path)
    (root / "tools" / "supply_chain" / "pip-audit.lock").write_text("pip-audit==2.9.0\n", encoding="utf-8")
    assert any("pip-audit.lock" in p and "no --hash" in p for p in lock.lock_check(root, offline=True))


# ---------------------------------------------------------------- the allow-list (D-186)


def test_shipped_allowlist_is_valid() -> None:
    allow, errors = allowlist.load(today=None)
    assert errors == []
    assert {e.package for e in allow.licences} >= {"psycopg", "psycopg-binary", "docxtpl", "py7zr", "dulwich"}
    reasons = [e.reason for e in allow.vulnerabilities] + [e.reason for e in allow.licences]
    assert all(len(r) >= allowlist.MIN_REASON for r in reasons)


def test_shipped_allowlist_dates_are_within_the_window() -> None:
    """Judged on the day before the earliest review date: every entry then is valid and not too far ahead.
    (On the machine's real date, `make allowlist-check` in CI decides; an expired entry fails there, on purpose.)"""
    allow, _ = allowlist.load(today=None)
    dates = [e.review_by for e in allow.vulnerabilities] + [e.review_by for e in allow.licences]
    dates += [e.review_by for e in allow.budgets]
    _, errors = allowlist.load(today=min(dates) - dt.timedelta(days=1))
    assert errors == []


@pytest.mark.parametrize(
    ("entry", "needle"),
    [
        ({"id": "CVE-1", "package": "x", "review_by": days(30)}, "no reason"),
        ({"id": "CVE-1", "package": "x", "reason": "   ", "review_by": days(30)}, "no reason"),
        ({"id": "CVE-1", "package": "x", "reason": "fine", "review_by": days(30)}, "too short"),
        ({"id": "CVE-1", "package": "x", "reason": GOOD_REASON}, "review_by must be an ISO date"),
        ({"id": "CVE-1", "package": "x", "reason": GOOD_REASON, "review_by": "next year"}, "ISO date"),
        ({"id": "CVE-1", "package": "x", "reason": GOOD_REASON, "review_by": days(-1)}, "has passed"),
        ({"id": "CVE-1", "package": "x", "reason": GOOD_REASON, "review_by": days(181)}, "more than 180 days"),
        ({"package": "x", "reason": GOOD_REASON, "review_by": days(30)}, "no id"),
        ({"id": "CVE-1", "reason": GOOD_REASON, "review_by": days(30)}, "no package"),
        ({"id": "CVE-1", "package": "x", "reason": GOOD_REASON, "review_by": days(30), "expires": "x"}, "unknown key"),
    ],
)
def test_allowlist_rejects_vulnerability_entry(entry: dict[str, str], needle: str) -> None:
    allow, errors = allowlist.parse({"vulnerabilities": [entry]}, today=TODAY)
    assert any(needle in e for e in errors), errors
    assert allow.vulnerabilities == []  # a rejected entry accepts nothing


def test_allowlist_rejects_bad_licence_entries_and_duplicates() -> None:
    data = {
        "licences": [
            _lic("psycopg", "lgpl"),
            _lic("psycopg", "lgpl"),
            _lic("x", "LGPL-3.0"),
            {**_lic("y", "lgpl"), "reason": ""},
            _lic("dulwich", "dual"),  # no chosen
            _lic("z", "unknown"),  # no licence
            _lic("w", "lgpl", chosen="MIT"),  # chosen on a non-dual entry
        ],
        "vulnerabilities": [_vuln("CVE-1", "a"), _vuln("cve-1", "A")],
        "extra": [],
    }
    _, errors = allowlist.parse(data, today=TODAY)
    joined = "\n".join(errors)
    assert joined.count("duplicate entry") == 2  # second psycopg, cve-1 for A
    assert "class must be one of" in joined
    assert "no reason" in joined
    assert "must name the chosen permissive branch" in joined
    assert "must record the verified licence" in joined
    assert "'chosen' belongs to dual entries only" in joined
    assert "unknown top-level key 'extra'" in joined


@pytest.mark.parametrize(
    "text",
    [
        "vulnerabilities: {}\n",
        "vulnerabilities: ''\n",
        "licences: 3\n",
        f"licences:\n  - package: a\n    class: lgpl\n    class: gpl\n    reason: {GOOD_REASON}\n    review_by: {days(9)}\n",
        "vulnerabilities: []\nvulnerabilities: []\n",
    ],
)
def test_allowlist_rejects_non_lists_and_duplicate_keys(tmp_path: Path, text: str) -> None:
    p = tmp_path / "allow.yaml"
    p.write_text(text, encoding="utf-8")
    _, errors = allowlist.load(p, today=TODAY)
    assert errors, text


def test_allowlist_check_cli_rejects_entry_without_reason(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = _write_allow(tmp_path, {"vulnerabilities": [{"id": "CVE-2026-1", "package": "x", "review_by": days(30)}]})
    assert cli.main(["--allowlist", str(bad), "allowlist-check"]) == 1
    assert "no reason" in capsys.readouterr().err
    good = _write_allow(tmp_path, {"vulnerabilities": [_vuln("CVE-2026-1", "x")]})
    assert cli.main(["--allowlist", str(good), "allowlist-check"]) == 0


def test_cli_has_no_date_override() -> None:
    with pytest.raises(SystemExit):
        cli.main(["--today", "2020-01-01", "allowlist-check"])


# ---------------------------------------------------------------- pip-audit gate

LOCK3 = (
    f"annotated-types==0.8.0 --hash=sha256:{H1}\n"
    f"certifi==2026.7.22 --hash=sha256:{H1}\n"
    f"pillow==12.3.0 --hash=sha256:{H1}\n"
    f"brotlicffi==1.2.1.0 ; platform_python_implementation == 'PyPy' --hash=sha256:{H1}\n"
)


def test_lock_targets_evaluate_markers_for_the_box() -> None:
    assert vulns.lock_targets(LOCK3) == {"annotated-types": "0.8.0", "certifi": "2026.7.22", "pillow": "12.3.0"}
    shipped = vulns.lock_targets(lock.REQUIREMENTS_LOCK.read_text(encoding="utf-8"))
    assert "brotli" in shipped and "brotlicffi" not in shipped


def test_pip_audit_gate_fails_on_every_advisory() -> None:
    result = vulns.pip_audit_gate(FIX / "pip_audit_vulns.json", _allow({}), vulns.lock_targets(LOCK3))
    assert not result.ok and result.errors == []
    assert sorted(f.id for f in result.failing) == ["GHSA-p4wg-p73j-c528", "PYSEC-2026-4320", "PYSEC-2026-4327"]
    assert {f.package for f in result.failing} == {"certifi", "pillow"}  # names normalised


def test_pip_audit_gate_accepts_by_alias_for_its_package_and_reports_unused() -> None:
    allow = _allow(
        {
            "vulnerabilities": [
                _vuln("CVE-2026-112394", "Pillow"),  # by an alias, package written with other case
                _vuln("GHSA-p4wg-p73j-c528", "pillow"),
                _vuln("PYSEC-2026-4320", "requests"),  # another package: must not accept certifi's advisory
            ]
        }
    )
    result = vulns.pip_audit_gate(FIX / "pip_audit_vulns.json", allow, vulns.lock_targets(LOCK3))
    assert [f.id for f in result.failing] == ["PYSEC-2026-4320"]
    assert len(result.accepted) == 2 and all(why == GOOD_REASON for _, why in result.accepted)
    assert result.unused_entries == ["PYSEC-2026-4320"]
    assert "FAIL" in result.render("pip-audit gate")


def test_pip_audit_gate_passes_clean_report_of_the_same_set() -> None:
    expected = {"annotated-types": "0.8.0", "pillow": "13.0.0"}
    result = vulns.pip_audit_gate(FIX / "pip_audit_clean.json", _allow({}), expected)
    assert result.ok and result.failing == [] and result.errors == []


@pytest.mark.parametrize(
    ("expected", "needle"),
    [
        (
            {"annotated-types": "0.8.0", "pillow": "13.0.0", "idna": "3.11"},
            "idna==3.11 is in the lock but was not audited",
        ),
        ({"annotated-types": "0.8.0", "pillow": "12.3.0"}, "pillow: audited 13.0.0, locked 12.3.0"),
        ({"annotated-types": "0.8.0"}, "pillow==13.0.0 was audited but is not in the lock"),
    ],
)
def test_pip_audit_gate_fails_when_audited_set_is_not_the_lock(expected: dict[str, str], needle: str) -> None:
    result = vulns.pip_audit_gate(FIX / "pip_audit_clean.json", _allow({}), expected)
    assert not result.ok
    assert any(needle in e for e in result.errors), result.errors


@pytest.mark.parametrize("content", ['{"dependencies": []}', "[]", '{"x": 1}', "not json"])
def test_pip_audit_gate_fails_on_empty_or_unreadable_report(tmp_path: Path, content: str) -> None:
    p = tmp_path / "pa.json"
    p.write_text(content, encoding="utf-8")
    assert not vulns.pip_audit_gate(p, _allow({})).ok
    assert not vulns.pip_audit_gate(tmp_path / "missing.json", _allow({})).ok


def test_pip_audit_gate_fails_when_a_package_was_not_audited() -> None:
    result = vulns.pip_audit_gate(FIX / "pip_audit_skipped.json", _allow({}))
    assert not result.ok
    assert any("private-pkg" in e and "not audited" in e for e in result.errors)


def test_pip_audit_gate_cli_exit_codes(tmp_path: Path) -> None:
    lock_file = tmp_path / "req.lock"
    lock_file.write_text(f"annotated-types==0.8.0 --hash=sha256:{H1}\npillow==13.0.0 --hash=sha256:{H1}\n", "utf-8")
    base = ["--allowlist", str(_write_allow(tmp_path, {})), "pip-audit-gate", "--lock", str(lock_file)]
    assert cli.main([*base, str(FIX / "pip_audit_clean.json")]) == 0
    assert cli.main([*base, str(FIX / "pip_audit_vulns.json")]) == 1


def test_expired_allowlist_entry_fails_the_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """After review_by the gate fails on the allow-list itself, even with a clean report."""
    p = _write_allow(tmp_path, {"vulnerabilities": [_vuln("PYSEC-2026-4320", "certifi", review=10)]})
    lock_file = tmp_path / "req.lock"
    lock_file.write_text(f"annotated-types==0.8.0 --hash=sha256:{H1}\npillow==13.0.0 --hash=sha256:{H1}\n", "utf-8")
    argv = ["--allowlist", str(p), "pip-audit-gate", "--lock", str(lock_file), str(FIX / "pip_audit_clean.json")]
    assert cli.main(argv) == 0
    monkeypatch.setattr(allowlist, "today", lambda: TODAY + dt.timedelta(days=11))
    assert cli.main(argv) == 1


# ---------------------------------------------------------------- Trivy gate


def test_trivy_gate_default_policy() -> None:
    result = vulns.trivy_gate([FIX / "trivy_image.json", FIX / "trivy_clean.json"], _allow({}))
    assert not result.ok and result.errors == []
    # HIGH with a fix fails; the unfixed HIGH, the LOW and the MEDIUM are listed, not failing
    assert [f.id for f in result.failing] == ["CVE-2026-76844"]
    assert sorted(f.id for f in result.reported) == ["CVE-2011-3374", "CVE-2025-8869", "CVE-2026-76642"]


def test_trivy_gate_fail_unfixed_and_severity() -> None:
    result = vulns.trivy_gate([FIX / "trivy_image.json"], _allow({}), fail_unfixed=True)
    assert "CVE-2026-76642" in {f.id for f in result.failing}
    result = vulns.trivy_gate(
        [FIX / "trivy_image.json"], _allow({}), severities=frozenset({"CRITICAL", "HIGH", "MEDIUM"})
    )
    assert "CVE-2025-8869" in {f.id for f in result.failing}


def test_trivy_gate_allowlist_by_vendor_id_for_its_package() -> None:
    data = _json("trivy_image.json")
    ghsa = next(
        v for r in data["Results"] for v in r.get("Vulnerabilities", []) if v["VulnerabilityID"] == "CVE-2026-76844"
    )
    assert ghsa["PkgName"] == "zlib1g"
    allow = _allow({"vulnerabilities": [_vuln("CVE-2026-76844", "zlib1g")]})
    result = vulns.trivy_gate([FIX / "trivy_image.json"], allow)
    assert result.ok and len(result.accepted) == 1
    other = _allow({"vulnerabilities": [_vuln("CVE-2026-76844", "libc6")]})
    assert not vulns.trivy_gate([FIX / "trivy_image.json"], other).ok


def test_trivy_unscored_counts_as_high(tmp_path: Path) -> None:
    """Trivy's UNKNOWN (not scored yet): with a fix it fails like a HIGH; without one it is listed."""
    data = _json("trivy_image.json")
    unfixed = data["Results"][0]["Vulnerabilities"][2]
    unfixed["Severity"] = "UNKNOWN"
    fixed = dict(unfixed, VulnerabilityID="DSA-0000-1", FixedVersion="9.9", Severity="UNKNOWN")
    data["Results"][0]["Vulnerabilities"].append(fixed)
    result = vulns.trivy_gate([_dump(tmp_path, "t.json", data)], _allow({}))
    assert "DSA-0000-1" in {f.id for f in result.failing}
    assert unfixed["VulnerabilityID"] in {f.id for f in result.reported}
    assert release.split_report_mode([_finding("DSA-1", "UNKNOWN")], "greenmail/standalone", "report")[
        1
    ]  # report mode too


@pytest.mark.parametrize("severity", [None, "", "HIGH ", "high", "unknown", "SEVERE"])
def test_trivy_gate_fails_on_missing_or_odd_severity(tmp_path: Path, severity: str | None) -> None:
    data = _json("trivy_image.json")
    vuln = data["Results"][0]["Vulnerabilities"][2]  # the LOW one, unfixed
    if severity is None:
        del vuln["Severity"]
    else:
        vuln["Severity"] = severity
    result = vulns.trivy_gate([_dump(tmp_path, "t.json", data)], _allow({}))
    assert vuln["VulnerabilityID"] in {f.id for f in result.failing}


def _mutate(edit: Any) -> Any:
    data = _json("trivy_image.json")
    edit(data)
    return data


@pytest.mark.parametrize(
    ("data", "needle"),
    [
        ({"ArtifactName": "x"}, "no Results"),
        ({"ArtifactName": "x", "Results": None}, "no Results"),
        ({"ArtifactName": "x", "Results": []}, "no Results"),
        (_mutate(lambda d: d["Results"][0].pop("Packages")), "no OS packages"),
        (_mutate(lambda d: d["Results"].pop(1)), "no python-pkg packages"),
        (_mutate(lambda d: d.pop("ArtifactName")), "not a Trivy JSON report"),
    ],
)
def test_trivy_gate_fails_on_reports_that_show_nothing(tmp_path: Path, data: Any, needle: str) -> None:
    result = vulns.trivy_gate([_dump(tmp_path, "t.json", data)], _allow({}))
    assert not result.ok
    assert any(needle in e for e in result.errors), result.errors


def test_trivy_gate_expects_jars_in_the_jvm_image(tmp_path: Path) -> None:
    data = _json("trivy_clean.json")
    assert vulns.trivy_gate([_dump(tmp_path, "ok.json", data)], _allow({})).ok
    data["Results"] = [r for r in data["Results"] if r.get("Type") != "jar"]
    result = vulns.trivy_gate([_dump(tmp_path, "nojar.json", data)], _allow({}))
    assert any("no jar packages" in e for e in result.errors)


def test_trivy_gate_fails_without_reports_or_on_foreign_json() -> None:
    assert not vulns.trivy_gate([], _allow({})).ok
    assert not vulns.trivy_gate([FIX / "pip_audit_clean.json"], _allow({})).ok


def _db(cache: Path, sub: str, updated: dt.datetime | None) -> None:
    (cache / sub).mkdir(parents=True, exist_ok=True)
    meta = (
        {"Version": 2}
        if updated is None
        else {"Version": 2, "UpdatedAt": updated.strftime("%Y-%m-%dT%H:%M:%S.123456789Z")}
    )
    (cache / sub / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")


def test_trivy_db_age(tmp_path: Path) -> None:
    now = dt.datetime.now(dt.UTC)
    _db(tmp_path, "db", now - dt.timedelta(hours=5))
    _db(tmp_path, "java-db", now - dt.timedelta(days=2))
    problems, seen = vulns.db_problems(tmp_path, now)
    assert problems == [] and set(seen) == {"db", "java-db"}
    _db(tmp_path, "db", now - dt.timedelta(days=vulns.MAX_DB_AGE_DAYS + 1))
    assert any("days old" in p for p in vulns.db_problems(tmp_path, now)[0])
    _db(tmp_path, "db", None)
    assert any("no UpdatedAt" in p for p in vulns.db_problems(tmp_path, now)[0])
    shutil.rmtree(tmp_path / "java-db")
    assert any("java-db" in p for p in vulns.db_problems(tmp_path, now)[0])


def test_trivy_gate_cli_fails_on_old_db(tmp_path: Path) -> None:
    allow = str(_write_allow(tmp_path, {}))
    cache = tmp_path / "cache"
    now = dt.datetime.now(dt.UTC)
    _db(cache, "db", now)
    _db(cache, "java-db", now)
    argv = ["--allowlist", allow, "trivy-gate", "--cache-dir", str(cache), str(FIX / "trivy_clean.json")]
    assert cli.main(argv) == 0
    _db(cache, "db", now - dt.timedelta(days=30))
    assert cli.main(argv) == 1
    assert cli.main(["--allowlist", allow, "trivy-gate", "--cache-dir", str(cache), "--severity", "SEVERE", "x"]) == 2


def test_trivy_command_is_offline_and_ignores_local_config() -> None:
    cmd = vulns.trivy_command("trialbox-py:1.0.0", Path("/media/trivy"), Path("out.json"))
    for flag in (
        "--skip-db-update",
        "--skip-java-db-update",
        "--offline-scan",
        "--skip-version-check",
        "--list-all-pkgs",
    ):
        assert flag in cmd
    assert cmd[cmd.index("--ignorefile") + 1] == "" and cmd[cmd.index("--config") + 1] == ""
    assert cmd[cmd.index("--cache-dir") + 1] == "/media/trivy"
    assert cmd[cmd.index("--image-src") + 1] == "docker" and cmd[-1] == "trialbox-py:1.0.0"
    remote = vulns.trivy_command("r@sha256:ab", Path("c"), Path("o"), platform="linux/arm64", remote=True)
    assert remote[remote.index("--platform") + 1] == "linux/arm64" and "remote" in remote


def test_scanner_env_drops_trivy_settings() -> None:
    env, removed = vulns.scanner_env({"PATH": "/bin", "TRIVY_SEVERITY": "LOW", "trivy_ignorefile": "x"})
    assert env == {"PATH": "/bin"} and removed == ["TRIVY_SEVERITY", "trivy_ignorefile"]
    assert "SYFT_CHECK_FOR_APP_UPDATE" in sbom.syft_env({"SYFT_CONFIG": "x"})
    assert "SYFT_CONFIG" not in sbom.syft_env({"SYFT_CONFIG": "x"})


# ---------------------------------------------------------------- SBOM


def test_sbom_validate_and_lock_coverage() -> None:
    doc = _json("sbom_lock.cdx.json")
    assert sbom.validate(doc) == []
    assert sbom.validate({"bomFormat": "SPDX"}) != []
    assert sbom.validate({"bomFormat": "CycloneDX", "specVersion": "1.6", "components": []}) == ["no components"]
    text = (
        f"annotated-types==0.8.0 --hash=sha256:{H1}\n"
        f"Dulwich==1.2.21 --hash=sha256:{H1}\n"
        f"pypdf==7.0.0 --hash=sha256:{H1}\n"
        f"brotlicffi==1.2.1.0 ; platform_python_implementation == 'PyPy' --hash=sha256:{H1}\n"
    )
    assert sbom.lock_coverage(doc, text) == ["pypdf==7.0.0"]  # brotlicffi does not install on the box


def test_sbom_file_names() -> None:
    assert sbom.file_name("trialbox-py:1.0.0") == "trialbox-py_1.0.0.cdx.json"
    assert sbom.file_name("trialbox-py:1.0.0", "linux/arm64") == "trialbox-py_1.0.0_linux_arm64.cdx.json"
    assert (
        sbom.file_name("python@sha256:5e2bdb1b0d542d50aa", "linux/amd64") == "python_5e2bdb1b0d54_linux_amd64.cdx.json"
    )
    assert sbom.syft_command("x:1", Path("o.json"), platform="linux/arm64")[-2:] == ["--platform", "linux/arm64"]


def test_lock_sbom_refuses_a_directory_that_is_not_the_lock_env(tmp_path: Path) -> None:
    problems = sbom.lock_sbom(tmp_path, lock.REQUIREMENTS_LOCK, tmp_path / "o.json", {})
    assert problems and "make lock-env" in problems[0]


# ---------------------------------------------------------------- licences


@pytest.mark.parametrize(
    ("expr", "flags", "choices"),
    [
        ("MIT", set(), None),
        ("Apache-2.0", set(), None),
        ("MPL-2.0", set(), None),
        ("LGPL-3.0-only", {"lgpl"}, None),
        ("GNU Lesser General Public License v2 or later (LGPLv2+)", {"lgpl"}, None),
        ("GPL-2.0-or-later", {"gpl"}, None),
        ("GNU General Public License v3 (GPLv3)", {"gpl"}, None),
        ("GNU General Public Licence v3", {"gpl"}, None),  # British spelling
        ("GNU  General   Public\tLicense v3", {"gpl"}, None),  # repeated whitespace
        ("LicenseRef_GPL3", {"gpl"}, None),
        ("AGPL-3.0-only", {"agpl"}, None),
        ("GNU Affero General Public License v3", {"agpl"}, None),
        ("GPL-2.0-only WITH Classpath-exception-2.0", {"gpl"}, None),
        ("MIT AND GPL-3.0-only", {"gpl"}, None),
        ("Apache-2.0 OR BSD-3-Clause", set(), None),
        ("BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0", set(), None),
        # an OR counts a branch only if it is permissive; otherwise the choice needs an allow-list entry
        ("Apache-2.0 OR GPL-2.0-or-later", {"dual"}, {"Apache-2.0"}),
        ("AGPL-3.0-only OR MIT", {"dual"}, {"MIT"}),
        ("GPL-3.0-only OR LicenseRef-Commercial", {"gpl"}, None),
        ("BSD-3-Clause AND (GPL-2.0-only OR Proprietary)", {"gpl"}, None),
        ("GPL-3.0-only OR UNKNOWN", {"gpl"}, None),
        ("GPL-3.0-only OR NOASSERTION", {"gpl"}, None),
        ("GPL-2.0 OR later", {"gpl"}, None),
        ("LicenseRef-Proprietary OR NOASSERTION", {"unknown"}, None),
        ("(MIT OR GPL-3.0) AND LGPL-2.1", {"dual", "lgpl"}, {"MIT"}),
        # not on the known list: unknown, never a guess
        ("", {"unknown"}, None),
        ("Proprietary", {"unknown"}, None),
        ("LicenseRef-Commercial", {"unknown"}, None),
        ("BSD, Public Domain", {"unknown"}, None),
        ("sha256:3596f4f7d52f77bb4ae3b2b11fe14abbae564b43b566f64ea452c46a248b1157", {"unknown"}, None),
    ],
)
def test_classify(expr: str, flags: set[str], choices: set[str] | None) -> None:
    verdict = licences.classify(expr)
    assert verdict.flags == flags
    if choices is not None:
        assert verdict.choices == choices


def test_classify_free_text_end_to_end() -> None:
    """A full licence text is searched to the end; its warranty disclaimer's capital OR is not an expression."""
    disclaimer = " THE SOFTWARE IS PROVIDED AS IS, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED." * 20
    mit = "Copyright (c) 2026 Example\n\nPermission is hereby granted, free of charge, to any person obtaining a copy"
    assert licences.classify(mit + disclaimer).flags == set()
    assert licences.classify("GNU GENERAL PUBLIC LICENSE\nVersion 3" + disclaimer).flags == {"gpl"}
    late = mit + disclaimer + "\nThis part is under the GNU Affero General Public License v3."
    assert licences.classify(late).flags == {"agpl"}
    assert licences.classify("Some custom terms.\n" + disclaimer).flags == {"unknown"}


def _comp(name: str, licenses: Any = None, **extra: Any) -> dict[str, Any]:
    c: dict[str, Any] = {"type": "library", "name": name, "version": "1.0", "purl": f"pkg:pypi/{name}@1.0", **extra}
    if licenses is not None:
        c["licenses"] = licenses
    return c


def _rows(components: list[dict[str, Any]], allow: allowlist.Allowlist, **kw: bool) -> dict[str, licences.Row]:
    doc = {"bomFormat": "CycloneDX", "specVersion": "1.6", "components": components}
    return {r.package: r for r in licences.report({"x": doc}, allow, **kw)}


def test_licence_data_from_url_text_and_nested_components() -> None:
    gpl_text = base64_text("GNU GENERAL PUBLIC LICENSE Version 3, 29 June 2007")
    rows = _rows(
        [
            _comp("by-url", [{"license": {"url": "https://www.gnu.org/licenses/gpl-3.0.html"}}]),
            _comp("by-mit-url", [{"license": {"url": "https://opensource.org/licenses/MIT"}}]),
            _comp("by-text", [{"license": {"text": {"content": gpl_text, "encoding": "base64"}}}]),
            _comp("named-and-url", [{"license": {"id": "MIT", "url": "https://example.invalid/LICENSE"}}]),
            _comp("named-mit-gpl-url", [{"license": {"id": "MIT", "url": "https://www.gnu.org/licenses/agpl-3.0"}}]),
            _comp("none"),
            _comp(
                "parent", [{"license": {"id": "MIT"}}], components=[_comp("child", [{"license": {"id": "AGPL-3.0"}}])]
            ),
        ],
        _allow({}),
    )
    assert rows["by-url"].flags == {"gpl"}
    assert rows["by-mit-url"].flags == set()
    assert rows["by-text"].flags == {"gpl"}
    assert rows["named-and-url"].flags == set()  # a URL to the text does not make a named licence unknown
    assert rows["named-mit-gpl-url"].flags == {"agpl"}
    assert rows["none"].flags == {"unknown"} and rows["none"].failing
    assert rows["child"].flags == {"agpl"} and rows["child"].failing


def base64_text(text: str) -> str:
    import base64

    return base64.b64encode(text.encode()).decode()


def test_licence_report_flags_and_needs_matching_entries() -> None:
    allow = _allow(
        {
            "licences": [
                _lic("psycopg", "lgpl"),
                _lic("gpltool", "lgpl"),  # an LGPL entry does not accept a package that is GPL
                _lic("dulwich", "dual", chosen="Apache-2.0"),
                _lic("dualbad", "dual", chosen="BSD-3-Clause"),  # a branch the package does not offer
                _lic("nolicence", "unknown", licence="MIT, read in the wheel's LICENSE"),
            ]
        }
    )
    doc = _json("sbom_image.cdx.json")
    doc["components"].append(_comp("dualbad", [{"expression": "MIT OR GPL-3.0-only"}]))
    rows = {r.package: r for r in licences.report({"image": doc}, allow)}
    assert rows["psycopg"].flags == {"lgpl"} and not rows["psycopg"].failing
    assert rows["docxtpl"].failing
    assert rows["pgsearch-ext"].cls == "agpl" and rows["pgsearch-ext"].failing
    assert rows["gpltool"].cls == "gpl" and rows["gpltool"].failing
    assert rows["dulwich"].flags == {"dual"} and not rows["dulwich"].failing
    assert rows["dualbad"].failing
    assert rows["nolicence"].flags == {"unknown"} and not rows["nolicence"].failing
    assert rows["pydantic"].flags == set()
    assert "debian" not in rows  # the operating-system component is not a package
    # distro packages of the base image: listed, not failing, unless asked
    assert rows["bash"].cls == "gpl" and rows["bash"].ecosystem == "deb" and not rows["bash"].failing
    assert {r.package: r for r in licences.report({"image": doc}, allow, gate_os_packages=True)}["bash"].failing

    text = licences.render(licences.evaluate({"image": doc}, allow))
    assert "Result: FAIL (4 flagged without an allow-list entry, 0 budgets exceeded or missing)" in text
    assert "| pgsearch-ext | 0.1.0 | pypi | AGPL-3.0-only | agpl | **not allow-listed: agpl** |" in text
    assert "| pydantic |" not in text  # permissive rows are counted, not listed


def test_unknown_licence_fails_without_an_entry() -> None:
    rows = _rows([_comp("mystery"), _comp("hashname", [{"license": {"name": "sha256:" + H1}}])], _allow({}))
    assert rows["mystery"].failing and rows["hashname"].failing


def test_lock_sbom_fixture_needs_the_shipped_allowlist(tmp_path: Path) -> None:
    """The real lock SBOM (trimmed) passes with the shipped allow-list and fails without it."""
    sb = str(FIX / "sbom_lock.cdx.json")
    assert cli.main(["licences", sb]) == 0
    assert cli.main(["--allowlist", str(_write_allow(tmp_path, {})), "licences", sb]) == 1


def test_licence_cli_with_shipped_allowlist(tmp_path: Path) -> None:
    """The shipped allow-list accepts the LGPL packages but nothing AGPL or GPL."""
    out = tmp_path / "licences.md"
    assert cli.main(["licences", str(FIX / "sbom_image.cdx.json"), "--out", str(out)]) == 1
    text = out.read_text(encoding="utf-8")
    assert "| psycopg | 3.3.8 | pypi | LGPL-3.0-only | lgpl | lgpl: LGPL-3.0-only; used unmodified" in text
    assert "| pgsearch-ext |" in text and "**not allow-listed: agpl**" in text


def _image(name: str, components: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "metadata": {"component": {"type": "container", "name": name, "version": "1"}},
        "components": components,
    }


def _jar(name: str, licenses: Any = None) -> dict[str, Any]:
    c: dict[str, Any] = {"type": "library", "name": name, "version": "1.0", "purl": f"pkg:maven/org.x/{name}@1.0"}
    if licenses is not None:
        c["licenses"] = licenses
    return c


def _budget(image: str, eco: str, top: int) -> dict[str, Any]:
    return {"image": image, "ecosystem": eco, "max": top, "reason": GOOD_REASON, "review_by": days(30)}


@pytest.mark.parametrize(
    ("entry", "needle"),
    [
        (_budget("trialbox-jvm", "pypi", 3), "not budgeted"),
        (_budget("trialbox-py", "npm", 3), "not budgeted"),
        (_budget("localhost:5000/trialbox-jvm", "*", 3), "not budgeted"),
        (_budget("requirements.lock", "maven", 1) | {"ecosystem": "pypi"}, "not budgeted"),
        (_budget("vllm/vllm-openai", "*", -1), "whole number"),
        (_budget("vllm/vllm-openai", "*", True), "whole number"),
        ({"ecosystem": "*", "max": 1, "reason": GOOD_REASON, "review_by": days(3)}, "needs image and ecosystem"),
        (_budget("vllm/vllm-openai", "*", 1) | {"review_by": days(-2)}, "has passed"),
    ],
)
def test_allowlist_rejects_bad_budgets(entry: dict[str, Any], needle: str) -> None:
    allow, errors = allowlist.parse({"budgets": [entry]}, today=TODAY)
    assert any(needle in e for e in errors), errors
    assert allow.budgets == []


def test_allowlist_rejects_duplicate_budget() -> None:
    _, errors = allowlist.parse({"budgets": [_budget("postgres", "*", 1), _budget("postgres", "*", 2)]}, today=TODAY)
    assert any("duplicate" in e for e in errors)


def test_licence_budgets_for_our_images() -> None:
    """Our images: unknown jars are counted against a budget; pypi/npm unknowns and copyleft jars need entries."""
    jars = [_jar("a"), _jar("b")]
    sboms = {"jvm.cdx.json": _image("trialbox-jvm", jars)}
    assert not licences.evaluate(sboms, _allow({})).ok  # no budget
    budget = _allow({"budgets": [_budget("trialbox-jvm", "maven", 2)]})
    result = licences.evaluate(sboms, budget)
    assert result.ok and [(b.subject, b.ecosystem, b.count, b.max) for b in result.budgets] == [
        ("trialbox-jvm", "maven", 2, 2)
    ]
    grown = {"jvm.cdx.json": _image("trialbox-jvm", [*jars, _jar("c")])}
    assert not licences.evaluate(grown, budget).ok  # a new unknown jar fails until reviewed
    # the same budget in a registry build of the image (images-multiarch)
    assert licences.evaluate({"m.cdx.json": _image("localhost:5000/trialbox-jvm", jars)}, budget).ok
    gpl_jar = {"jvm.cdx.json": _image("trialbox-jvm", [*jars[:1], _jar("g", [{"license": {"id": "GPL-3.0-only"}}])])}
    result = licences.evaluate(gpl_jar, budget)
    assert [r.package for r, _ in result.failing] == ["g"]  # copyleft is never budgeted in our images
    pypi = {"py.cdx.json": _image("trialbox-py", [_comp("mystery")])}
    assert [r.package for r, _ in licences.evaluate(pypi, budget).failing] == ["mystery"]
    lock_doc = {"bomFormat": "CycloneDX", "specVersion": "1.6", "components": [_comp("mystery")]}
    assert [r.package for r, _ in licences.evaluate({"lock.cdx.json": lock_doc}, budget).failing] == ["mystery"]


def test_licence_budgets_for_third_party_images() -> None:
    """A third-party image's open flags (any ecosystem, copyleft too) count against one budget for the image."""
    comps = [_comp("mystery"), _comp("gplpkg", [{"license": {"id": "GPL-2.0-only"}}]), _jar("j")]
    sboms = {"v.cdx.json": _image("vllm/vllm-openai", comps)}
    assert not licences.evaluate(sboms, _allow({})).ok
    result = licences.evaluate(sboms, _allow({"budgets": [_budget("vllm/vllm-openai", "*", 3)]}))
    assert result.ok and result.failing == [] and result.budgets[0].count == 3
    loose = licences.evaluate(sboms, _allow({"budgets": [_budget("vllm/vllm-openai", "*", 5)]}))
    assert loose.ok and "budget can drop to 3" in licences.render(loose)
    tight = licences.evaluate(sboms, _allow({"budgets": [_budget("vllm/vllm-openai", "*", 2)]}))
    assert not tight.ok and "**over budget**" in licences.render(tight)


def test_shipped_budgets_cover_the_ci_counts() -> None:
    """The shipped budgets name our two jar-carrying images and the third-party images compose pulls."""
    allow, _ = allowlist.load(today=None)
    names = {(b.image, b.ecosystem) for b in allow.budgets}
    assert {("trialbox-jvm", "maven"), ("trialbox-demo", "maven"), ("vllm/vllm-openai", "*")} <= names
    assert not any(allowlist.is_own(b.image) and b.ecosystem in allowlist.STRICT_ECOSYSTEMS for b in allow.budgets)


# ---------------------------------------------------------------- release gates and the bundle


LAYERS = ["sha256:l1", "sha256:l2"]


def _report(image_id: str, digests: list[str], platform: str = "linux/amd64") -> vulns.TrivyReport:
    os_, arch = platform.split("/")[:2]
    data = _json("trivy_clean.json")
    data["Metadata"].update(
        ImageID=image_id, RepoDigests=digests, ImageConfig={"os": os_, "architecture": arch}, DiffIDs=LAYERS
    )
    return vulns.parse_trivy(data)


def _sbom(version: str, layers: list[str]) -> dict[str, Any]:
    comp = {
        "type": "library",
        "name": "x",
        "properties": [{"name": "syft:location:0:layerID", "value": v} for v in layers],
    }
    return {"metadata": {"component": {"type": "container", "name": "trialbox-py", "version": version}},
            "components": [comp]}  # fmt: skip


def test_identity_of_a_local_image() -> None:
    """Syft names a local image by its tag; its layers must be the image's layers."""
    target = release.Target("trialbox-py:1.0.0")
    pinned = {"image_id": "sha256:aa", "repo_digests": []}
    ok = _sbom("1.0.0", LAYERS[:1])
    assert release.identity_problems(target, pinned, _report("sha256:aa", []), ok) == []
    assert any("not the pinned" in p for p in release.identity_problems(target, pinned, _report("sha256:bb", []), ok))
    other = _sbom("1.0.0", ["sha256:elsewhere"])
    assert any(
        "not in the scanned image" in p
        for p in release.identity_problems(target, pinned, _report("sha256:aa", []), other)
    )
    assert any(
        "no image layers" in p
        for p in release.identity_problems(target, pinned, _report("sha256:aa", []), _sbom("1.0.0", []))
    )


def test_identity_of_a_registry_image_by_digest_and_platform() -> None:
    target = release.Target("python@sha256:ab", "linux/arm64", remote=True)
    pinned = {"image_id": None, "repo_digests": [target.ref]}
    doc = _sbom("sha256:ab", LAYERS)
    good = _report("sha256:cfg", ["python@sha256:ab"], "linux/arm64")
    assert release.identity_problems(target, pinned, good, doc) == []
    wrong_platform = _report("sha256:cfg", ["python@sha256:ab"], "linux/amd64")
    assert any("platform" in p for p in release.identity_problems(target, pinned, wrong_platform, doc))
    wrong_digest = _report("sha256:cfg", ["python@sha256:ff"], "linux/arm64")
    assert any("does not name the digest" in p for p in release.identity_problems(target, pinned, wrong_digest, doc))
    assert any("SBOM names" in p for p in release.identity_problems(target, pinned, good, _sbom("sha256:zz", LAYERS)))


def test_targets_and_repositories() -> None:
    assert release.parse_target("trialbox-py:1.0.0") == release.Target("trialbox-py:1.0.0")
    assert release.parse_target("registry:vllm/vllm-openai:v0.32.0=linux/arm64") == release.Target(
        "vllm/vllm-openai:v0.32.0", "linux/arm64", remote=True
    )
    assert release.repository("postgres:16-alpine@sha256:72") == "postgres"
    assert release.repository("localhost:5000/trialbox-py:1.0.0") == "localhost:5000/trialbox-py"
    assert release.pin_remote("postgres:16-alpine@sha256:72ab") == "postgres@sha256:72ab"


def test_release_gates_fail_closed_without_scanners_or_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))  # no docker, no trivy, no syft
    record = release.run_gates(
        [release.Target("trialbox-py:1.0.0"), release.Target("python:3.12", remote=True)],
        cache_dir=tmp_path / "cache",
        out_dir=tmp_path / "out",
        sbom_dir=tmp_path / "sbom",
        allow=_allow({}),
        allow_errors=[],
        lock_sbom=tmp_path / "missing.cdx.json",
    )
    assert record["ok"] is False
    assert all(not e["ok"] and e["errors"] for e in record["images"])
    assert any("needs a platform" in x for x in record["images"][1]["errors"])
    assert record["db_errors"] and "lock_sbom_error" in record
    saved = json.loads((tmp_path / "out" / "gates.json").read_text(encoding="utf-8"))
    assert saved["ok"] is False
    assert release.run_gates(
        [], cache_dir=tmp_path, out_dir=tmp_path / "o2", sbom_dir=tmp_path / "s2", allow=_allow({}), allow_errors=[],
        lock_sbom=None,
    )["ok"] is False  # fmt: skip


def _record(ok: bool = True, created: dt.datetime | None = None) -> dict[str, Any]:
    return {
        "ok": ok,
        "created": (created or dt.datetime.now(dt.UTC)).isoformat(),
        "images": [
            {"ref": "trialbox-py:1.0.0", "image_id": "sha256:aa", "ok": True},
            {"ref": "postgres@sha256:pp", "image_id": "sha256:pg", "ok": True},
            {"ref": "trialbox-jvm:1.0.0", "image_id": "sha256:jj", "ok": False},
        ],
    }


def test_bundle_carries_only_gated_images() -> None:
    assert release.bundle_problems(_record(), {"trialbox-py:1.0.0": "sha256:aa", "postgres:16": "sha256:pg"}) == []
    assert release.bundle_problems(_record(), {"trialbox-py:1.0.0": "sha256:rebuilt"})  # a new build is not gated
    assert release.bundle_problems(_record(), {"trialbox-jvm:1.0.0": "sha256:jj"})  # failed in the record
    assert release.bundle_problems(_record(ok=False), {"trialbox-py:1.0.0": "sha256:aa"})
    old = dt.datetime.now(dt.UTC) - dt.timedelta(days=vulns.MAX_DB_AGE_DAYS + 1)
    assert release.bundle_problems(_record(created=old), {"trialbox-py:1.0.0": "sha256:aa"})
    assert release.bundle_problems({"not": "a record"}, {})


# ---------------------------------------------------------------- report mode (owner decision 2026-11-10)


def _finding(fid: str, severity: str, fixed: str = "2.0") -> vulns.Finding:
    return vulns.Finding("trivy", "img", "pkg", "1.0", fid, (), severity, fixed)


def test_known_image_findings_lists_every_report_mode_image() -> None:
    path = ROOT / "deploy" / "security" / "known-image-findings.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "report mode" in text.lower().replace("\n", " ")
    assert "2026-12-10" in text and "security owner (to assign)" in text
    rows = {line.split("|")[1].strip() for line in text.splitlines() if line.startswith("| ") and "---" not in line}
    missing = sorted(name for name in release.VULN_REPORT_ONLY if name not in rows)
    assert missing == [], f"report-mode images without a row in {path.name}: {missing}"
    # our own images always block: trialbox-py from the start, trialbox-jvm and trialbox-demo since T-672; since
    # T-110b only the test-only mail servers are left in report mode
    assert not {"trialbox-py", "trialbox-jvm", "trialbox-demo", "trialbox-postgres"} & release.VULN_REPORT_ONLY
    assert not {"hapiproject/hapi", "vllm/vllm-openai", "postgres"} & release.VULN_REPORT_ONLY


def test_report_mode_defers_only_fixable_high_findings_of_named_images() -> None:
    failing = [
        _finding("CVE-1", "HIGH"),
        _finding("CVE-2", "CRITICAL"),
        _finding("CVE-3", "HIGH", fixed=""),  # only fails with --fail-unfixed: stays blocking
        _finding("CVE-4", "MEDIUM"),  # only fails with --severity ...MEDIUM: stays blocking
        _finding("CVE-5", "INVALID('HIGH ')"),
    ]
    blocking, deferred = release.split_report_mode(failing, "greenmail/standalone:2.1.3", "report")
    assert [f.id for f in deferred] == ["CVE-1", "CVE-2"]
    assert [f.id for f in blocking] == ["CVE-3", "CVE-4", "CVE-5"]
    assert release.split_report_mode(failing, "docker.io/greenmail/standalone@sha256:ab", "report")[1]
    assert release.split_report_mode(failing, "axllent/mailpit@sha256:ab", "report")[1]
    # T-110b: every image a bundle can carry blocks, the third-party ones too
    for shipped in ("hapiproject/hapi:v8.12.0-2", "vllm/vllm-openai@sha256:ab", "trialbox-postgres:16-1"):
        assert release.split_report_mode(failing, shipped, "report") == (failing, [])
    # our own images, and every image in block mode, keep every finding blocking (T-672: jvm and demo block)
    for own in (
        "trialbox-py:1.0.0",
        "trialbox-jvm:1.0.0",
        "localhost:5000/trialbox-jvm@sha256:ab",
        "trialbox-demo:step5",
    ):
        assert release.split_report_mode(failing, own, "report") == (failing, [])
    assert release.split_report_mode(failing, "vllm/vllm-openai@sha256:ab", "block") == (failing, [])


def test_report_mode_still_fails_on_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))  # no docker, no scanners: every image errors
    record = release.run_gates(
        [release.Target("trialbox-jvm:1.0.0")],
        cache_dir=tmp_path,
        out_dir=tmp_path / "out",
        sbom_dir=tmp_path / "sbom",
        allow=_allow({}),
        allow_errors=[],
        lock_sbom=None,
        vuln_mode="report",
    )
    assert record["ok"] is False and record["images"][0]["errors"]
    summary = (tmp_path / "out" / "summary.md").read_text(encoding="utf-8")
    assert "Release gates: FAIL" in summary and "mode: **report**" in summary
    with pytest.raises(vulns.ReportError):
        release.run_gates([], cache_dir=tmp_path, out_dir=tmp_path, sbom_dir=tmp_path, allow=_allow({}),
                          allow_errors=[], lock_sbom=None, vuln_mode="ignore")  # fmt: skip
    with pytest.raises(SystemExit):
        cli.main(["release-gates", "--image", "x", "--cache-dir", str(tmp_path), "--vuln-mode", "ignore"])


def test_summary_lists_every_finding_and_bundle_refuses_report_mode_images() -> None:
    row = release.finding_row(_finding("CVE-2026-1", "HIGH"))
    record = {
        "ok": True,
        "created": dt.datetime.now(dt.UTC).isoformat(),
        "vuln_mode": "report",
        "licences": {"ok": True, "failing": []},
        "images": [
            {"ref": "trialbox-py:1.0.0", "platform": "linux/amd64", "image_id": "sha256:py", "ok": True},
            {"ref": "hapiproject/hapi:v8.12.0-2", "platform": "linux/arm64", "image_id": "sha256:hapi", "ok": True,
             "report_mode_findings": [row]},
        ],
    }  # fmt: skip
    text = release.summary_markdown(record)
    assert "### hapiproject/hapi:v8.12.0-2 (linux/arm64)" in text
    assert "| reported | CVE-2026-1 | HIGH | pkg | 1.0 | 2.0 |" in text
    assert "known-image-findings.md" in text
    assert release.bundle_problems(record, {"trialbox-py:1.0.0": "sha256:py"}) == []
    assert release.bundle_problems(record, {"hapiproject/hapi:v8.12.0-2": "sha256:hapi"})  # passed only in report mode


def test_arm64_gates_name_the_amd64_only_images() -> None:
    # none since D-348: MailHog (amd64 only) gave way to Mailpit, and every locked third-party image has an arm64 build
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "SC_AMD64_ONLY ?=\n" in makefile
    lock = json.loads((ROOT / "deploy" / "images.lock").read_text(encoding="utf-8"))
    assert all("linux/arm64" in e["platforms"] for e in lock["third_party"].values())
    assert "mailhog" not in str(release.VULN_REPORT_ONLY)


def test_make_bundle_checks_the_gate_record() -> None:
    script = (ROOT / "tools" / "make_bundle.sh").read_text(encoding="utf-8")
    assert "--gates) GATES=" in script and "tools.supply_chain bundle-check" in script
    assert "--gates is required" in script  # T-110b: not optional


# ---------------------------------------------------------------- pinned scanners


def _tarball(name: str, body: bytes) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name)
        info.size = len(body)
        tar.addfile(info, io.BytesIO(body))
        readme = tarfile.TarInfo("README.md")
        readme.size = 2
        tar.addfile(readme, io.BytesIO(b"hi"))
    return buf.getvalue()


def test_scanner_archive_must_match_the_pinned_sha256(tmp_path: Path) -> None:
    data = _tarball("trivy", b"#!/bin/sh\necho trivy\n")
    scanners.verify(data, hashlib.sha256(data).hexdigest(), "trivy")
    with pytest.raises(scanners.ScannerError, match="refusing"):
        scanners.verify(data + b"x", hashlib.sha256(data).hexdigest(), "trivy")
    path = scanners.extract(data, "trivy", tmp_path)
    assert path.read_bytes().startswith(b"#!/bin/sh") and not (tmp_path / "bin" / "README.md").exists()
    with pytest.raises(scanners.ScannerError, match="not in the archive"):
        scanners.extract(_tarball("other", b"x"), "syft", tmp_path)


def test_every_scanner_asset_is_pinned_for_both_platforms() -> None:
    for tool in ("syft", "trivy"):
        for arch in ("amd64", "arm64"):
            a = scanners.asset(tool, arch)
            assert len(a.sha256) == 64 and int(a.sha256, 16) >= 0
            assert a.url.startswith("https://github.com/") and a.version in a.url


def test_workflows_pin_every_action_to_a_commit() -> None:
    wf = ROOT.parent / ".github" / "workflows"
    if not wf.is_dir():
        pytest.skip("workflows not in this checkout")
    for f in sorted(wf.glob("trialbox-*.yml")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if "uses:" in line:
                ref = line.split("uses:", 1)[1].split("#", 1)[0].strip()
                assert "@" in ref and len(ref.rsplit("@", 1)[1]) == 40, f"{f.name}: {line.strip()}"
                int(ref.rsplit("@", 1)[1], 16)
            if "image:" in line and "@sha256:" not in line:
                pytest.fail(f"{f.name}: service image without a digest: {line.strip()}")


def test_dockerfiles_pin_their_bases_by_digest() -> None:
    for path in ("deploy/docker/python.Dockerfile", "deploy/docker/jvm.Dockerfile", "demo/Dockerfile"):
        text = (ROOT / path).read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.startswith("FROM ") and "${" not in line:
                assert "@sha256:" in line, f"{path}: {line}"
            if line.startswith("ARG ") and "_IMAGE=" in line and "trialbox-" not in line:
                assert "@sha256:" in line, f"{path}: {line}"


def _copy_sources(dockerfile: Path) -> list[str]:
    out: list[str] = []
    for line in dockerfile.read_text(encoding="utf-8").replace("\\\n", " ").splitlines():
        parts = line.split()
        if not parts or parts[0] != "COPY" or any(p.startswith("--from") for p in parts):
            continue
        out += [p for p in parts[1:-1] if not p.startswith("--")]
    return out


@pytest.mark.parametrize("path", ["deploy/docker/python.Dockerfile", "deploy/docker/jvm.Dockerfile", "demo/Dockerfile"])
def test_every_copy_source_exists_and_is_in_the_build_context(path: str) -> None:
    """`make images` copies only what is in the repository (or made by make, under .cache/) and not ignored by the
    build context rules that apply to that Dockerfile (``<Dockerfile>.dockerignore``, else the root file)."""
    import fnmatch

    dockerfile = ROOT / path
    own = dockerfile.parent / (dockerfile.name + ".dockerignore")
    rules = (own if own.is_file() else ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    patterns = [r.strip().rstrip("/") for r in rules if r.strip() and not r.startswith("#")]
    for src in _copy_sources(dockerfile):
        if src != "." and not src.startswith(".cache/"):
            assert (ROOT / src).exists(), f"{path}: COPY {src}: no such file in the repository"
        if src != ".":
            assert not any(fnmatch.fnmatch(src, p) for p in patterns), f"{path}: COPY {src} is ignored by the context"


def test_shipped_fixtures_are_small() -> None:
    assert all(p.stat().st_size < 20_000 for p in FIX.iterdir())


def test_copy_does_not_touch_fixtures() -> None:
    before = copy.deepcopy(_json("trivy_image.json"))
    _mutate(lambda d: d["Results"].clear())
    assert _json("trivy_image.json") == before


def test_uv_floor_is_the_advisory_fix() -> None:
    # DEP-006: uv below 0.13.4 trusts a compromised CA root (GHSA-hq85-5cpj-mr62); the pinned uv is at or above it
    assert lock.MIN_UV_VERSION == "0.13.4"
    assert not lock.uv_too_old(lock.UV_VERSION)
    assert lock.uv_too_old("0.11.32")
    assert lock.uv_too_old("0.13.3")
    assert not lock.uv_too_old("0.13.4")
    assert not lock.uv_too_old("1.0.0")
    assert lock.uv_too_old("?")
