"""Card 10K-9 (D-1362): the drill of RUNBOOK §20, close-out and decommissioning
(``docs/runbook/20-close-out-and-decommissioning.md``), steps 2 to 4 for the audit chain and the archive's sums.

On a synthetic audit chain: step 2's four ``tools/audit_verify.py`` commands run as the page writes them (the chain
verifies, a signed head is written to an anchor folder, the chain matches it, no foreign event), and the head written
on the close-out record is the one the chain keeps after them. Step 3: the chain and the anchor folder are copied to
``ARCHIVE/audit``, the plan goes to ``ARCHIVE/plan.json`` (``decommission-plan --json``), and the page's own command
makes ``SHA256SUMS``. Step 4 on a second folder: ``sha256sum -c SHA256SUMS`` and ``audit_verify.py ARCHIVE/audit
--heads ARCHIVE/audit/anchor`` pass, and both fail on a copy with one changed audit line. The final backup and its
``backup-verify``, the export ledger, and steps 1 and 5 to 8 (people, keys, media) are not rehearsed here; the page
says so.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from tb_common.audit import AuditLog

from tests.unit.test_decommission import _box
from tools import audit_verify as av
from tools.trialbox import __main__ as tb_main

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs" / "runbook" / "20-close-out-and-decommissioning.md"


def sums_command() -> str:
    """Step 3's command for the sums of the whole folder, as the page writes it."""
    text = PAGE.read_text(encoding="utf-8").replace("\n", " ")
    m = re.search(r"Then the sums of the whole folder: `([^`]+)`", text)
    assert m, "step 3 no longer gives the sums command"
    return m.group(1)


def _verify(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    capsys.readouterr()
    rc = av.main(list(argv))
    return rc, capsys.readouterr().out


def _head(capsys: pytest.CaptureFixture[str], audit: Path) -> dict[str, Any]:
    rc, out = _verify(capsys, str(audit), "--json")
    doc = json.loads(out)
    assert rc == 0 and doc["ok"], doc
    return dict(doc["head"])


def test_runbook_20_decommission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for k in [k for k in os.environ if k.startswith("TB_")]:
        monkeypatch.delenv(k)
    monkeypatch.setenv("TB_ENV", "TEST")
    audit, anchor, secrets = tmp_path / "data" / "audit", tmp_path / "anchor", tmp_path / "secrets"
    anchor.mkdir()
    log = AuditLog(audit, tz="Asia/Taipei")
    for user in ("crc.a", "crc.b", "inv.c"):  # step 1: the study accounts are disabled (synthetic names)
        log.append("console.user", actor="console", detail={"action": "disable", "user": user})
    assert av.main([str(audit), "--init-key", "--secrets", str(secrets)]) == 0

    # step 2, freeze: the page's four commands, in its order
    before = _head(capsys, audit)  # --json: the chain is whole and ends at HEAD.json
    assert before["lines"] == 3
    rc, out = _verify(capsys, str(audit), "--sign-head", "--to", str(anchor), "--secrets", str(secrets))
    assert rc == 0 and "1 of 1 anchor folders" in out
    assert len(list((anchor / "heads").glob("*.json"))) == 1
    rc, out = _verify(capsys, str(audit), "--heads", str(anchor))
    assert rc == 0 and "audit chain PASS" in out
    assert _verify(capsys, str(audit), "--foreign")[0] == 0
    # the head to write down is the one after the four commands: the signing is itself one event in the chain
    head = _head(capsys, audit)
    assert head["lines"] == before["lines"] + 1 and head["hash"] != before["hash"]
    last = json.loads((audit / head["file"]).read_text(encoding="utf-8").splitlines()[-1])
    assert last["event"] == "audit.head_signed"
    assert _head(capsys, audit) == head  # checking adds nothing: from here the chain does not change

    # step 3, archive: the chain as frozen with its anchor folder, the plan, then the sums of the whole folder
    archive = tmp_path / "hospital-store" / "ARCHIVE"
    archive.mkdir(parents=True)
    shutil.copytree(audit, archive / "audit")
    shutil.copytree(anchor, archive / "audit" / "anchor")
    deploy = _box(tmp_path)
    capsys.readouterr()
    assert tb_main.main(["decommission-plan", "--deploy", str(deploy), "--json"]) == 0
    (archive / "plan.json").write_text(capsys.readouterr().out, encoding="utf-8")
    plan = json.loads((archive / "plan.json").read_text(encoding="utf-8"))
    rows = {(s["name"], s["where"]): s["action"] for s in plan["stores"]}
    assert rows[("audit archive", "/mnt/share/audit-archive")] == "keep"  # keep rows: not purged in step 7
    assert rows[("audit anchor folder", "/mnt/share/anchors")] == "keep"
    assert rows[("backup target", "/mnt/share/tb")] == "purge"
    cmd = sums_command().replace("cd ARCHIVE", f"cd {shlex.quote(str(archive))}", 1)
    subprocess.run(["bash", "-c", cmd], check=True)
    listed = sorted(line.split("  ", 1)[1] for line in (archive / "SHA256SUMS").read_text().splitlines())
    files = sorted(f"./{p.relative_to(archive).as_posix()}" for p in archive.rglob("*")
                   if p.is_file() and p.name != "SHA256SUMS")  # fmt: skip
    assert listed == files and "./plan.json" in listed and f"./audit/{head['file']}" in listed

    # step 4, verify, on a second folder (the hospital's store)
    second = tmp_path / "second-medium" / "ARCHIVE"
    shutil.copytree(archive, second)
    ok = subprocess.run(["sha256sum", "-c", "SHA256SUMS"], cwd=second, capture_output=True, text=True, check=False)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    rc, out = _verify(capsys, str(second / "audit"), "--heads", str(second / "audit" / "anchor"))
    assert rc == 0 and "audit chain PASS" in out
    assert _head(capsys, second / "audit") == head  # the archive ends at the head on the close-out record

    # the checks catch a changed archive: one audit line edited on a third copy
    bad = tmp_path / "tampered" / "ARCHIVE"
    shutil.copytree(archive, bad)
    day = bad / "audit" / head["file"]
    day.write_text(day.read_text(encoding="utf-8").replace("crc.b", "crc.x"), encoding="utf-8")
    no = subprocess.run(["sha256sum", "-c", "SHA256SUMS"], cwd=bad, capture_output=True, text=True, check=False)
    assert no.returncode != 0 and "FAILED" in no.stdout
    assert _verify(capsys, str(bad / "audit"), "--heads", str(bad / "audit" / "anchor"))[0] != 0
