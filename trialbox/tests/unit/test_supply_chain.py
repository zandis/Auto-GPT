"""Supply-chain gates (D-185, D-186): hashed lock, allow-list, pip-audit and Trivy gates, SBOM checks, licences.

Offline: the scanners' JSON comes from small fixtures in ``tests/fixtures/supply_chain``. The two tests that run
``uv export``/``uv lock --check --offline`` need only the uv binary and skip without it.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path

import pytest
import yaml

from tools.supply_chain import __main__ as cli
from tools.supply_chain import allowlist, licences, lock, sbom, vulns

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures" / "supply_chain"
TODAY = dt.date(2026, 11, 10)
H1 = "a" * 64
H2 = "b" * 64
needs_uv = pytest.mark.skipif(
    shutil.which("uv") is None or lock.uv_version() != lock.UV_VERSION,
    reason=f"needs uv {lock.UV_VERSION} on PATH (another version may format the export differently)",
)


def _allow(data: object, today: dt.date | None = TODAY) -> allowlist.Allowlist:
    allow, errors = allowlist.parse(data, today=today)
    assert errors == []
    return allow


def _write_allow(tmp_path: Path, data: object) -> Path:
    p = tmp_path / "allow.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


GOOD_REASON = "Not reachable: the box never parses untrusted fonts"


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
    text = (ROOT / "deploy" / "requirements.lock").read_text(encoding="utf-8")
    assert lock.check_requirements_hashes(text) == []
    names = {r.name for r in lock.parse_requirements(text)}
    assert {"pypdf", "pillow", "psycopg", "cryptography"} <= names


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
    return tmp_path


@needs_uv
def test_lock_check_fails_on_hand_edited_or_stale_lock(tmp_path: Path) -> None:
    root = _copy_project(tmp_path)
    assert lock.lock_check(root, offline=True) == []

    # a hand edit (a hash dropped) is caught twice: no hash, and no longer the export of uv.lock
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


# ---------------------------------------------------------------- the allow-list (D-186)


def test_shipped_allowlist_is_valid() -> None:
    allow, errors = allowlist.load(today=None)
    assert errors == []
    assert {e.package for e in allow.licences} >= {"psycopg", "psycopg-binary", "docxtpl", "py7zr"}
    reasons = [e.reason for e in allow.vulnerabilities] + [e.reason for e in allow.licences]
    assert all(len(r) >= allowlist.MIN_REASON for r in reasons)


def test_shipped_allowlist_dates_are_valid_today() -> None:
    _, errors = allowlist.load(today=TODAY)
    assert errors == []


@pytest.mark.parametrize(
    ("entry", "needle"),
    [
        ({"id": "CVE-1", "review_by": "2027-01-01"}, "no reason"),
        ({"id": "CVE-1", "reason": "   ", "review_by": "2027-01-01"}, "no reason"),
        ({"id": "CVE-1", "reason": "fine", "review_by": "2027-01-01"}, "too short"),
        ({"id": "CVE-1", "reason": GOOD_REASON}, "review_by must be an ISO date"),
        ({"id": "CVE-1", "reason": GOOD_REASON, "review_by": "next year"}, "review_by must be an ISO date"),
        ({"id": "CVE-1", "reason": GOOD_REASON, "review_by": "2026-11-01"}, "has passed"),
        ({"id": "CVE-1", "reason": GOOD_REASON, "review_by": "2028-01-01"}, "more than 180 days"),
        ({"reason": GOOD_REASON, "review_by": "2027-01-01"}, "no id"),
        ({"id": "CVE-1", "reason": GOOD_REASON, "review_by": "2027-01-01", "expires": "x"}, "unknown key"),
    ],
)
def test_allowlist_rejects_vulnerability_entry(entry: dict[str, str], needle: str) -> None:
    allow, errors = allowlist.parse({"vulnerabilities": [entry]}, today=TODAY)
    assert any(needle in e for e in errors), errors
    assert allow.vulnerabilities == []  # a rejected entry accepts nothing


def test_allowlist_rejects_bad_licence_entries_and_duplicates() -> None:
    ok = {"package": "psycopg", "class": "lgpl", "reason": GOOD_REASON, "review_by": "2027-01-01"}
    data = {
        "licences": [ok, dict(ok), {**ok, "package": "x", "class": "LGPL-3.0"}, {**ok, "reason": ""}],
        "vulnerabilities": [
            {"id": "CVE-1", "reason": GOOD_REASON, "review_by": "2027-01-01"},
            {"id": "cve-1", "reason": GOOD_REASON, "review_by": "2027-01-01"},
        ],
        "extra": [],
    }
    _, errors = allowlist.parse(data, today=TODAY)
    joined = "\n".join(errors)
    assert joined.count("duplicate entry") == 3  # second psycopg, the bad-reason psycopg, cve-1
    assert "class must be one of" in joined
    assert "no reason" in joined
    assert "unknown top-level key 'extra'" in joined


def test_allowlist_check_cli_rejects_entry_without_reason(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = _write_allow(tmp_path, {"vulnerabilities": [{"id": "CVE-2026-1", "review_by": "2027-01-01"}]})
    assert cli.main(["--allowlist", str(bad), "--today", "2026-11-10", "allowlist-check"]) == 1
    assert "no reason" in capsys.readouterr().err
    good = _write_allow(
        tmp_path, {"vulnerabilities": [{"id": "CVE-2026-1", "reason": GOOD_REASON, "review_by": "2027-01-01"}]}
    )
    assert cli.main(["--allowlist", str(good), "--today", "2026-11-10", "allowlist-check"]) == 0


# ---------------------------------------------------------------- pip-audit gate


def test_pip_audit_gate_fails_on_every_advisory() -> None:
    result = vulns.pip_audit_gate(FIX / "pip_audit_vulns.json", _allow({}))
    assert not result.ok
    assert sorted(f.id for f in result.failing) == ["GHSA-p4wg-p73j-c528", "PYSEC-2026-4320", "PYSEC-2026-4327"]
    assert {f.package for f in result.failing} == {"certifi", "pillow"}  # names normalised


def test_pip_audit_gate_accepts_by_alias_and_package_and_reports_unused() -> None:
    allow = _allow(
        {
            "vulnerabilities": [
                # by an alias, scoped to the package (written with other case)
                {"id": "CVE-2026-112394", "package": "Pillow", "reason": GOOD_REASON, "review_by": "2027-01-01"},
                {"id": "GHSA-p4wg-p73j-c528", "reason": GOOD_REASON, "review_by": "2027-01-01"},
                # scoped to another package: must not accept certifi's advisory
                {"id": "PYSEC-2026-4320", "package": "requests", "reason": GOOD_REASON, "review_by": "2027-01-01"},
            ]
        }
    )
    result = vulns.pip_audit_gate(FIX / "pip_audit_vulns.json", allow)
    assert [f.id for f in result.failing] == ["PYSEC-2026-4320"]
    assert len(result.accepted) == 2 and all(why == GOOD_REASON for _, why in result.accepted)
    assert result.unused_entries == ["PYSEC-2026-4320"]
    assert "FAIL" in result.render("pip-audit gate")


def test_pip_audit_gate_passes_clean_report() -> None:
    result = vulns.pip_audit_gate(FIX / "pip_audit_clean.json", _allow({}))
    assert result.ok and result.failing == [] and result.errors == []


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
    empty = _write_allow(tmp_path, {})
    base = ["--allowlist", str(empty), "--today", "2026-11-10", "pip-audit-gate"]
    assert cli.main([*base, str(FIX / "pip_audit_clean.json")]) == 0
    assert cli.main([*base, str(FIX / "pip_audit_vulns.json")]) == 1


def test_expired_allowlist_entry_fails_the_gate(tmp_path: Path) -> None:
    """After review_by the entry no longer accepts the finding and the gate fails on the allow-list too."""
    data = {"vulnerabilities": [{"id": "PYSEC-2026-4320", "reason": GOOD_REASON, "review_by": "2026-12-01"}]}
    p = _write_allow(tmp_path, data)
    base = ["--allowlist", str(p), "pip-audit-gate", str(FIX / "pip_audit_clean.json")]
    assert cli.main(["--today", "2026-11-10", *base]) == 0
    assert cli.main(["--today", "2026-12-02", *base]) == 1


# ---------------------------------------------------------------- Trivy gate


def test_trivy_gate_default_policy() -> None:
    result = vulns.trivy_gate([FIX / "trivy_image.json", FIX / "trivy_clean.json"], _allow({}))
    assert not result.ok
    # HIGH and CRITICAL with a fix fail; the unfixed CRITICAL and the MEDIUM are listed, not failing
    assert sorted(f.id for f in result.failing) == ["CVE-2026-0001", "CVE-2026-112394"]
    assert sorted(f.id for f in result.reported) == ["CVE-2026-0002", "CVE-2026-0003"]
    assert {f.target for f in result.failing} == {
        "trialbox-py:1.0.0:trialbox-py:1.0.0 (debian 13.1)",
        "trialbox-py:1.0.0:Python",
    }


def test_trivy_gate_fail_unfixed_and_severity() -> None:
    result = vulns.trivy_gate([FIX / "trivy_image.json"], _allow({}), fail_unfixed=True)
    assert "CVE-2026-0002" in {f.id for f in result.failing}
    result = vulns.trivy_gate(
        [FIX / "trivy_image.json"], _allow({}), severities=frozenset({"CRITICAL", "HIGH", "MEDIUM"})
    )
    assert "CVE-2026-0003" in {f.id for f in result.failing}


def test_trivy_gate_allowlist_by_vendor_id() -> None:
    allow = _allow(
        {
            "vulnerabilities": [
                {"id": "GHSA-4558-3h8r-v8xp", "package": "pillow", "reason": GOOD_REASON, "review_by": "2027-01-01"},
                {"id": "CVE-2026-0001", "package": "libssl3t64", "reason": GOOD_REASON, "review_by": "2027-01-01"},
            ]
        }
    )
    result = vulns.trivy_gate([FIX / "trivy_image.json"], allow)
    assert result.ok and len(result.accepted) == 2


def test_trivy_gate_fails_without_reports_or_on_foreign_json(tmp_path: Path) -> None:
    assert not vulns.trivy_gate([], _allow({})).ok
    assert not vulns.trivy_gate([FIX / "pip_audit_clean.json"], _allow({})).ok
    assert vulns.trivy_gate([FIX / "trivy_clean.json"], _allow({})).ok


def test_trivy_offline_command_never_updates() -> None:
    cmd = vulns.trivy_offline_command("trialbox-py:1.0.0", Path("/media/trivy"), Path("out.json"))
    for flag in ("--skip-db-update", "--skip-java-db-update", "--skip-check-update", "--offline-scan"):
        assert flag in cmd
    assert cmd[cmd.index("--cache-dir") + 1] == "/media/trivy"
    assert cmd[-1] == "trialbox-py:1.0.0"


def test_trivy_cli_rejects_unknown_severity(tmp_path: Path) -> None:
    empty = _write_allow(tmp_path, {})
    argv = ["--allowlist", str(empty), "trivy-gate", "--severity", "SEVERE", str(FIX / "trivy_clean.json")]
    assert cli.main(argv) == 2


# ---------------------------------------------------------------- SBOM


def test_sbom_validate_and_lock_coverage() -> None:
    doc = json.loads((FIX / "sbom_lock.cdx.json").read_text(encoding="utf-8"))
    assert sbom.validate(doc) == []
    assert sbom.validate({"bomFormat": "SPDX"}) != []
    assert sbom.validate({"bomFormat": "CycloneDX", "specVersion": "1.6", "components": []}) == ["no components"]
    text = (
        f"annotated-types==0.8.0 --hash=sha256:{H1}\n"
        f"Dulwich==1.2.21 --hash=sha256:{H1}\n"
        f"pypdf==7.0.0 --hash=sha256:{H1}\n"
    )
    assert sbom.lock_coverage(doc, text) == ["pypdf==7.0.0"]


def test_sbom_file_names() -> None:
    assert sbom.file_name("trialbox-py:1.0.0") == "trialbox-py_1.0.0.cdx.json"
    assert sbom.file_name("file:deploy/requirements.lock") == "requirements.lock.cdx.json"
    assert sbom.syft_command("x:1", Path("o.json")) == ["syft", "scan", "x:1", "-o", "cyclonedx-json=o.json"]


# ---------------------------------------------------------------- licences


@pytest.mark.parametrize(
    ("expr", "cls", "dual"),
    [
        ("MIT", "ok", False),
        ("Apache-2.0", "ok", False),
        ("LGPL-3.0-only", "lgpl", False),
        ("GNU Lesser General Public License v2 or later (LGPLv2+)", "lgpl", False),
        ("GPL-2.0-or-later", "gpl", False),
        ("GNU General Public License v3 (GPLv3)", "gpl", False),
        ("AGPL-3.0-only", "agpl", False),
        ("GNU Affero General Public License v3", "agpl", False),
        ("Apache-2.0 OR GPL-2.0-or-later", "ok", True),
        ("(MIT OR GPL-3.0) AND LGPL-2.1", "lgpl", True),
        ("MIT AND GPL-3.0-only", "gpl", False),
        ("GPL-2.0-only WITH Classpath-exception-2.0", "gpl", False),
        ("", "unknown", False),
    ],
)
def test_classify(expr: str, cls: str, dual: bool) -> None:
    assert licences.classify(expr) == (cls, dual)


def test_classify_free_text_by_its_head() -> None:
    """Full licence texts: a disclaimer's capital OR is not an expression; the title decides."""
    disclaimer = " THE SOFTWARE IS PROVIDED AS IS, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED." * 20
    assert licences.classify("GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007\n" + disclaimer)[0] == "gpl"
    assert licences.classify("Copyright (c) 2026 Example\n\nPermission is hereby granted" + disclaimer)[0] == "ok"
    # a mention of the GPL deep inside a permissive text (bundled-component notes) is not the package's licence
    assert licences.classify("BSD 3-Clause License\n" + disclaimer + " FreeType: FTL OR GPL-2.0-or-later")[0] == "ok"


def _image_rows(allow: allowlist.Allowlist, **kw: bool) -> dict[str, licences.Row]:
    doc = json.loads((FIX / "sbom_image.cdx.json").read_text(encoding="utf-8"))
    return {r.package: r for r in licences.report({"image": doc}, allow, **kw)}


def test_licence_report_flags_copyleft_and_needs_entries() -> None:
    allow = _allow(
        {
            "licences": [
                {"package": "psycopg", "class": "lgpl", "reason": GOOD_REASON, "review_by": "2027-01-01"},
                # an LGPL entry does not accept a package that is GPL
                {"package": "gpltool", "class": "lgpl", "reason": GOOD_REASON, "review_by": "2027-01-01"},
            ]
        }
    )
    rows = _image_rows(allow)
    assert rows["psycopg"].cls == "lgpl" and not rows["psycopg"].failing and rows["psycopg"].accepted == GOOD_REASON
    assert rows["docxtpl"].cls == "lgpl" and rows["docxtpl"].failing
    assert rows["pgsearch-ext"].cls == "agpl" and rows["pgsearch-ext"].failing
    assert rows["gpltool"].cls == "gpl" and rows["gpltool"].failing
    assert rows["dulwich"].cls == "ok" and rows["dulwich"].dual and not rows["dulwich"].failing
    assert rows["pydantic"].cls == "ok"
    assert rows["nolicence"].cls == "unknown" and not rows["nolicence"].failing
    assert "debian" not in rows  # the operating-system component is not a package
    # distro packages of the base image: listed, not failing, unless asked
    assert rows["bash"].cls == "gpl" and rows["bash"].ecosystem == "deb" and not rows["bash"].failing
    assert _image_rows(allow, gate_os_packages=True)["bash"].failing

    text = licences.render(list(rows.values()))
    assert "Result: FAIL (3 flagged without an allow-list entry)" in text
    assert "| pgsearch-ext | 0.1.0 | pypi | AGPL-3.0-only | AGPL | **not allow-listed** |" in text
    assert "| pydantic |" not in text  # permissive rows are counted, not listed


def test_licence_cli_with_shipped_allowlist(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The shipped allow-list accepts the LGPL packages but nothing AGPL or GPL."""
    out = tmp_path / "licences.md"
    rc = cli.main(["--today", "2026-11-10", "licences", str(FIX / "sbom_image.cdx.json"), "--out", str(out)])
    assert rc == 1
    text = out.read_text(encoding="utf-8")
    assert "| psycopg | 3.3.8 | pypi | LGPL-3.0-only | LGPL | LGPL-3.0-only; used unmodified" in text
    assert "| pgsearch-ext |" in text and "**not allow-listed**" in text
    ok_doc = tmp_path / "ok.cdx.json"
    ok_doc.write_text((FIX / "sbom_lock.cdx.json").read_text(encoding="utf-8"), encoding="utf-8")
    assert cli.main(["--today", "2026-11-10", "licences", str(ok_doc)]) == 0
    capsys.readouterr()
