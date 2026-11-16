"""Build-or-reuse §3.4 (wave 1): detect-secrets, the scanner CI runs over the tracked tree (T-654), over a support
bundle as the box writes it. The bundle's own checks (D-405, D-723) know the box's secret settings and the patient
patterns; a generic scanner also finds a secret no setting names: a private key or a cloud token a service printed
into its log."""

from __future__ import annotations

import gzip
import tarfile
from collections import Counter
from pathlib import Path

import pytest

from tests.unit.test_support_bundle_no_secret import NOW, _runner, box  # noqa: F401
from tools import security_scan
from tools import support_bundle as sb

#: a private key as a service could print it (built here, never a real key; split so no scanner reads this file)
PEM = "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA" + "q" * 60 + "\n-----END " + "RSA PRIVATE KEY-----"
AWS = "AKIA" + "IOSFODNN7" + "EXAMPLE"  # the documentation's example access key id


def _scan(archive: Path, where: Path) -> list[security_scan.Finding]:
    where.mkdir()
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(where, filter="data")
    files = sorted(str(p.relative_to(where)) for p in where.rglob("*") if p.is_file())
    return security_scan.scan_secrets(where, files)


def _log(deploy: Path, text: str) -> None:
    day = deploy.parent / "logs" / "services" / "2026-11-13"
    with gzip.open(day / "lake.log.gz", "wb") as fh:
        fh.write(text.encode())


def test_a_bundle_of_a_box_with_every_secret_set_passes_detect_secrets(
    box: tuple[Path, dict[str, str]],  # noqa: F811
    tmp_path: Path,
) -> None:
    deploy, values = box
    out = sb.build(deploy, tmp_path / "usb", runner=_runner(values), now=NOW, say=lambda _: None)
    assert _scan(out, tmp_path / "x") == []


@pytest.mark.parametrize("planted", [PEM, f"aws_access_key_id = {AWS}"])
def test_a_secret_no_setting_names_does_not_leave_in_a_bundle(
    box: tuple[Path, dict[str, str]],  # noqa: F811
    tmp_path: Path,
    planted: str,
) -> None:
    deploy, values = box
    _log(deploy, f"2026-11-13T01:00:00Z lake | a dump of the config:\n{planted}\n")
    said: list[str] = []
    out = sb.build(deploy, tmp_path / "usb", runner=_runner(values), now=NOW, say=said.append)
    assert _scan(out, tmp_path / "x") == [], "a secret the bundle did not know left in it"
    assert any("credential(s) from logs/" in s for s in said)  # said, with the kind, never the value


def test_each_kind_of_credential_is_replaced_and_a_key_block_goes_whole() -> None:
    body = "Mq" + "x" * 62
    gh = "ghp_" + "A1b2" * 9
    slack = "xoxb-" + "1234567890-abcdefghij"
    jwt = "eyJ" + "hbGciOiJIUzI1" + ".eyJ" + "zdWIiOiIxMjM0" + ".SflKxwRJSMeKKF2QT4"
    text = f"start\n{PEM}\nkey={AWS}\ntoken {gh}\n{slack}\nauth: Bearer {jwt}\nend\n"
    out, found = sb.hide_credentials(text)
    for gone in (PEM, "MIIEowIBAAKCAQEA", AWS, gh, slack, jwt):
        assert gone not in out
    assert found == {"private key": 1, "AWS access key": 1, "GitHub token": 1, "Slack token": 1, "JSON web token": 1}
    assert out.startswith("start\n[credential removed: private key]\n") and out.endswith("end\n")
    cut, n = sb.hide_credentials("-----BEGIN " + f"PRIVATE KEY-----\n{body}\n")  # a log cut inside the block
    assert body not in cut and n == {"private key": 1}


def test_ordinary_log_text_is_left_alone() -> None:
    text = ("2026-11-13T01:00:00Z lake | snapshot 2026-10-04 sha256 " + "ab12" * 16 + " job 01JITCOMPILE00000000000000"
            "\nAKIA is a word here; ghp_short; eyJ alone\n")  # fmt: skip
    assert sb.hide_credentials(text) == (text, {})


def test_a_bundle_that_would_still_hold_a_credential_is_not_written(
    box: tuple[Path, dict[str, str]],  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deploy, values = box
    _log(deploy, f"2026-11-13T01:00:00Z lake | {AWS}\n")
    monkeypatch.setattr(sb, "hide_credentials", lambda text: (text, Counter()))  # as if the pass had missed it
    with pytest.raises(sb.BundleRefused, match="AWS access key"):
        sb.build(deploy, tmp_path / "usb", runner=_runner(values), now=NOW, say=lambda _: None)
    assert not list((tmp_path / "usb").glob("*.tar.gz"))
