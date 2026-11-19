"""Card 10K-9 (D-1362): the drill of RUNBOOK §22, "moving the box to another address"
(``docs/runbook/22-moving-the-box.md``), steps 3 and 4: the host name changes.

Step 3 as the page writes it: the new ``TB_TLS_HOSTNAME`` (and, with the hospital's certificate, the new certificate
files) go into ``deploy/.env`` and ``python -m console.cli check-tls`` checks them. The drill shows that check-tls
reads the variables it is run with, not ``deploy/.env``: run with the values of before the move it still passes on
the old name, which is why the page says to run it with the new values. With the new name and the old certificate it
fails; with the new certificate it passes. Step 4: the network sheet written before the move is stale for the new
``deploy/.env`` (``tools/network_sheet.py --check`` exits 1); written again it names the new host and not the old.
Steps 2, 5 and 6 (backup and shutdown, doctor from the new network, a sign-in from a clinic PC) need the box and its
network and are not rehearsed here; the page says so.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.test_runbook_12_certificate_renewal import certificate, check_tls
from tools import network_sheet

OLD, NEW = "trialbox.ward3.hosp.test", "trialbox.dc2.hosp.test"


def _env_file(deploy: Path, host: str, crt: Path, key: Path) -> Path:
    env = deploy / ".env"
    env.write_text(f"TB_ENV=PRODUCTION\nTB_TLS_MODE=hospital\nTB_TLS_HOSTNAME={host}\nTB_TLS_CERT_FILE={crt}\n"
                   f"TB_TLS_KEY_FILE={key}\nSMTP_HOST=mail.hosp.test\n", encoding="utf-8")  # fmt: skip
    return env


def _use(monkeypatch: pytest.MonkeyPatch, env: Path) -> None:
    """Run the next command with the values of ``deploy/.env`` (what the page means by "the same variables")."""
    for line in env.read_text(encoding="utf-8").splitlines():
        k, _, v = line.partition("=")
        if k.startswith("TB_TLS_"):
            monkeypatch.setenv(k, v)


def _sheet(env: Path, out: Path, check: bool = False) -> int:
    return network_sheet.main(["--env", str(env), "--out", str(out)] + (["--check"] if check else []))


def test_runbook_22_moving_the_box(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    deploy, site = tmp_path / "deploy", tmp_path / "deploy" / "site"
    site.mkdir(parents=True)
    for k in ("TB_TLS_MODE", "TB_TLS_HOSTNAME", "TB_TLS_CERT_FILE", "TB_TLS_KEY_FILE"):
        monkeypatch.delenv(k, raising=False)

    # before the move: the box answers on the old name with a certificate for it, and has its network sheet
    old_crt, old_key = tmp_path / "old.crt", tmp_path / "old.key"
    certificate(old_crt, old_key, [OLD], days=300)
    env = _env_file(deploy, OLD, old_crt, old_key)
    _use(monkeypatch, env)
    assert check_tls(capsys)[0] == 0
    sheet = site / "network-sheet"
    assert _sheet(env, sheet) == 0
    assert f"clinic PCs -> {OLD}:443" in (site / "network-sheet.en.md").read_text(encoding="utf-8")
    assert _sheet(env, sheet, check=True) == 0

    # step 3: the name changes; TB_TLS_HOSTNAME is set in deploy/.env, the certificate files not yet
    env = _env_file(deploy, NEW, old_crt, old_key)
    # check-tls does not read deploy/.env: with the variables of before the move it still checks the old name
    rc, out, _ = check_tls(capsys)
    assert rc == 0 and f"host {OLD}" in out
    # with the new values: the old certificate does not name the new host
    _use(monkeypatch, env)
    rc, out, err = check_tls(capsys)
    assert rc == 1 and f"host {NEW}" in out and f"FAIL: the certificate does not name {NEW}" in err
    # the new certificate files from hospital IT, set in deploy/.env too: check-tls passes on the new name
    new_crt, new_key = tmp_path / "new.crt", tmp_path / "new.key"
    certificate(new_crt, new_key, [NEW], days=397)
    env = _env_file(deploy, NEW, new_crt, new_key)
    _use(monkeypatch, env)
    rc, out, err = check_tls(capsys)
    assert rc == 0 and not err and f"host {NEW}" in out
    # where Caddy makes its own certificate (internal CA), the host name alone is checked
    monkeypatch.setenv("TB_TLS_MODE", "internal")
    rc, out, _ = check_tls(capsys)
    assert rc == 0 and f"host {NEW}" in out
    monkeypatch.setenv("TB_TLS_MODE", "hospital")

    # step 4: the sheet of before the move is stale for the new deploy/.env; written again it names the new host
    capsys.readouterr()
    assert _sheet(env, sheet, check=True) == 1
    assert "stale:" in capsys.readouterr().out
    assert _sheet(env, sheet) == 0
    for lang in network_sheet.LANGS:
        text = (site / f"network-sheet.{lang}.md").read_text(encoding="utf-8")
        assert NEW in text and OLD not in text, lang
    assert f"clinic PCs -> {NEW}:443" in (site / "network-sheet.en.md").read_text(encoding="utf-8")
    assert _sheet(env, sheet, check=True) == 0
