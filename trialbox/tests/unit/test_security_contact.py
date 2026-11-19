"""The public security contact (card 10G-9, D-1239): one file holds it, every policy file points there, the release
target refuses a bundle while it is not set, and the website's security.txt is RFC 9116's shape.

The contact is the owner's to choose: while ``deploy/security/contact.json`` holds the placeholder, these tests pass
(master stays green) and ``make release-bundle`` fails at its first step."""

from __future__ import annotations

import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tools import security_contact as sc

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT.parent
POLICY = ROOT / "docs" / "security"
POINTERS = [
    REPO / ".github" / "SECURITY.md",
    POLICY / "13-vulnerability-disclosure.md",
    POLICY / "13-vulnerability-disclosure-ja.md",
    POLICY / "13-vulnerability-disclosure-zh-tw.md",
]
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")


def _doc(**over: Any) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(sc.CONTACT_FILE.read_text(encoding="utf-8"))
    doc.update(over)
    return doc


def test_the_contact_file_reads_and_names_its_fields() -> None:
    doc = sc.load()
    assert set(doc) >= {"contact", "encryption", "preferred_languages", "policy", "github_private_reporting"}
    assert doc["preferred_languages"] == ["en", "ja", "zh-TW"]
    assert doc["policy"].endswith("trialbox/docs/security/13-vulnerability-disclosure.md")
    # the contact is either the owner's URI or not set; nothing in between passes as set
    assert sc.is_uri(doc["contact"]) == (not sc.problems(doc))


def test_the_placeholder_lives_in_one_file_only() -> None:
    doc = sc.load()
    if sc.is_uri(doc["contact"]):
        pytest.skip("the owner has set the contact")
    token = doc["contact"]
    found = subprocess.run(
        ["git", "-C", str(REPO), "grep", "-l", "-F", "--untracked", "-e", token],
        capture_output=True,
        text=True,
        check=False,
    )
    assert found.returncode in (0, 1), found.stderr
    holders = found.stdout.split()
    assert holders == ["trialbox/deploy/security/contact.json"], holders


@pytest.mark.parametrize("path", POINTERS, ids=lambda p: p.name)
def test_every_policy_file_points_to_the_contact_file_and_writes_no_address(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "deploy/security/contact.json" in text
    assert not EMAIL.findall(text), "an address belongs in deploy/security/contact.json only"


@pytest.mark.parametrize("path", POINTERS[1:], ids=lambda p: p.name)
def test_the_policy_says_what_a_reporter_must_not_do_in_each_language(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    words = {
        "13-vulnerability-disclosure.md": ("real patient data", "hospital's box", "Safe harbour", "45 days", "JVN"),
        "13-vulnerability-disclosure-ja.md": (
            "実在の患者データ",
            "稼働しているボックス",
            "セーフハーバー",
            "45 日",
            "JVN",
        ),
        "13-vulnerability-disclosure-zh-tw.md": ("真實病人資料", "正在運作的設備", "安全港", "TWCERT/CC", "JVN"),
    }[path.name]
    for w in words:
        assert w in text, (path.name, w)
    assert "tools/apply_update.sh" in text  # how a fix reaches an offline box


@pytest.mark.parametrize(
    ("value", "ok"),
    [
        ("mailto:security@example.org", True),
        ("https://example.org/security", True),
        ("NOT-A-URI-EXAMPLE", False),
        ("security@example.org", False),  # RFC 9116: a URI, so mailto:
        ("http://example.org/security", False),
        ("mailto:", False),
        ("mailto:a@b@example.org", False),
        ("", False),
    ],
)
def test_a_contact_is_set_only_as_a_mailto_or_https_uri(value: str, ok: bool) -> None:
    assert sc.is_uri(value) is ok
    assert (not sc.problems(_doc(contact=value))) is ok


def test_release_check_refuses_a_release_and_lets_a_rehearsal_through(tmp_path: Path) -> None:
    unset = tmp_path / "unset.json"
    unset.write_text(json.dumps(_doc(contact="NOT-A-URI-EXAMPLE")), encoding="utf-8")
    good = tmp_path / "set.json"
    good.write_text(json.dumps(_doc(contact="mailto:security@example.org")), encoding="utf-8")
    release = ["--key", "k", "--id", "2026.12-1", "--release-seq", "4", "--out", "x.tar"]
    assert sc.main(["--file", str(unset), "release-check", *release]) == 1
    assert sc.main(["--file", str(unset), "release-check"]) == 1
    assert sc.main(["--file", str(unset), "release-check", "--rehearsal", *release]) == 0
    assert sc.main(["--file", str(unset), "release-check", *release, "--allow-dirty", "a rehearsal"]) == 0
    assert sc.main(["--file", str(good), "release-check", *release]) == 0
    assert sc.main(["--file", str(tmp_path / "missing.json"), "release-check", "--rehearsal"]) == 1


def test_release_bundle_runs_the_check_before_the_gates() -> None:
    make = (ROOT / "Makefile").read_text(encoding="utf-8")
    m = re.search(r"^release-bundle:(.*)$", make, re.M)
    assert m and m.group(1).split()[0] == "security-contact-check", m
    recipe = re.search(r"^security-contact-check:\n\t(.+)$", make, re.M)
    assert recipe and "tools.security_contact release-check $(BUNDLE_ARGS)" in recipe.group(1)


def test_security_txt_has_rfc_9116_fields_and_is_not_written_while_unset() -> None:
    with pytest.raises(sc.ContactError):
        sc.security_txt(_doc(contact="NOT-A-URI-EXAMPLE"))
    now = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
    doc = _doc(
        contact="mailto:security@example.org",
        encryption="https://example.org/pgp.asc",
        github_private_reporting="https://github.com/zandis/Auto-GPT/security/advisories/new",
    )
    lines = sc.security_txt(doc, now=now).splitlines()
    fields = [ln.split(":", 1)[0] for ln in lines if not ln.startswith("#")]
    assert fields.count("Contact") == 2 and fields[0] == "Contact"
    assert fields.count("Expires") == 1  # RFC 9116 2.5.5: exactly once
    assert "Expires: 2027-05-18T12:00:00Z" in lines  # 180 days, under a year
    assert "Preferred-Languages: en, ja, zh-TW" in lines
    assert any(ln.startswith("Policy: https://") for ln in lines)
    assert any(ln.startswith("Encryption: https://") for ln in lines)


def test_an_optional_field_that_is_not_https_is_a_problem() -> None:
    assert sc.problems(_doc(contact="mailto:security@example.org", encryption="ftp://example.org/k.asc"))
    assert not sc.problems(_doc(contact="mailto:security@example.org", encryption=None))
