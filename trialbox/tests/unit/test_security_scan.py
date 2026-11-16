"""T-654 (ENG-010, ENG-011): the secret scan and the static security scan of CI job ``security`` fail on a planted
finding and pass on clean files; the ignore file needs a reason and a count.

The planted keys are made here, in a temporary folder, at run time: they are not in the repository, so the
repository's own scan never sees them, and they are visibly fake (no real key material, the PEM body says so)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools import security_scan as sc

# split so that this file itself holds no key-shaped text
PEM_HEAD = "-----BEGIN " + "RSA PRIVATE KEY" + "-----"
PEM_TAIL = "-----END " + "RSA PRIVATE KEY" + "-----"
FAKE_AWS_ID = "AKIA" + "ZZFAKEKEYFORTEST"


def _no_ignores(tmp_path: Path) -> Path:
    p = tmp_path / "ignores.yaml"
    p.write_text("secrets: []\nsast: []\n", encoding="utf-8")
    return p


def _plant_key(root: Path) -> None:
    (root / "config").mkdir(parents=True)
    (root / "config" / "deploy.pem").write_text(
        f"{PEM_HEAD}\nTHIS-IS-A-FAKE-KEY-FOR-THE-SCAN-TEST\n{PEM_TAIL}\n", encoding="utf-8"
    )
    (root / "config" / "cloud.ini").write_text(f"[cloud]\naccess_key_id = {FAKE_AWS_ID}\n", encoding="utf-8")


def test_planted_fake_key_fails_the_secret_scan(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "repo"
    _plant_key(root)
    (root / "clean.py").write_text("password_env = 'TB_DEMO_PASSWORD'\n", encoding="utf-8")
    rc = sc.main(["secrets", "--root", str(root), "--ignores", str(_no_ignores(tmp_path))])
    out = capsys.readouterr().out
    assert rc == 1
    assert "config/deploy.pem: Private Key: 1 found, 0 accepted (lines 1)" in out
    assert "config/cloud.ini: AWS Access Key: 1 found, 0 accepted (lines 2)" in out
    assert "clean.py" not in out
    # the place and the rule are printed, never the matched text
    assert FAKE_AWS_ID not in out and "THIS-IS-A-FAKE" not in out


def test_clean_tree_passes_the_secret_scan(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("import os\nTOKEN = os.environ['TB_TOKEN']\n", encoding="utf-8")
    (root / "b.json").write_text('{"sha256": "' + "ab" * 32 + '"}\n', encoding="utf-8")  # digests are not secrets
    assert sc.main(["secrets", "--root", str(root), "--ignores", str(_no_ignores(tmp_path))]) == 0
    assert "secrets: PASS" in capsys.readouterr().out


def test_an_ignore_accepts_its_count_and_no_more(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _plant_key(root)
    ign = tmp_path / "ignores.yaml"
    ign.write_text(
        "secrets:\n"
        "  - {path: config/deploy.pem, rule: Private Key, count: 1, reason: a test key made by this test}\n"
        "  - {path: config/cloud.ini, rule: AWS Access Key, count: 1, reason: a test key made by this test}\n",
        encoding="utf-8",
    )
    assert sc.main(["secrets", "--root", str(root), "--ignores", str(ign)]) == 0
    with (root / "config" / "cloud.ini").open("a", encoding="utf-8") as f:
        f.write(f"second = {FAKE_AWS_ID[:-1]}Q\n")
    assert sc.main(["secrets", "--root", str(root), "--ignores", str(ign)]) == 1


@pytest.mark.parametrize(
    "row",
    [
        "{path: a.py, rule: B602, count: 1}",
        "{path: a.py, rule: B602, count: 1, reason: ok}",
        "{path: a.py, rule: B602, count: 0, reason: a long enough reason}",
        "{rule: B602, count: 1, reason: a long enough reason}",
    ],
)
def test_an_ignore_without_reason_or_count_is_refused(tmp_path: Path, row: str) -> None:
    ign = tmp_path / "ignores.yaml"
    ign.write_text(f"sast:\n  - {row}\n", encoding="utf-8")
    with pytest.raises(sc.ScanError):
        sc.load_ignores(ign, "sast")
    assert sc.main(["sast", "--root", str(tmp_path), "--ignores", str(ign)]) == 2


def test_planted_shell_injection_fails_the_static_scan(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "repo"
    (root / "tools").mkdir(parents=True)
    (root / "tools" / "run.py").write_text(
        "import subprocess\nimport sys\n\n\ndef go() -> None:\n    subprocess.run(sys.argv[1], shell=True)\n",
        encoding="utf-8",
    )
    (root / "tools" / "ok.py").write_text("import subprocess\n\nsubprocess.run(['true'], check=True)\n", "utf-8")
    rc = sc.main(["sast", "--root", str(root), "--ignores", str(_no_ignores(tmp_path))])
    out = capsys.readouterr().out
    assert rc == 1
    assert "tools/run.py: B602: 1 found, 0 accepted (lines 6)" in out
    assert "ok.py" not in out


def test_clean_code_passes_the_static_scan(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "libs").mkdir(parents=True)
    (root / "libs" / "m.py").write_text("import yaml\n\n\ndef f(t: str) -> object:\n    return yaml.safe_load(t)\n")
    assert sc.main(["sast", "--root", str(root), "--ignores", str(_no_ignores(tmp_path))]) == 0


def test_stale_ignore_is_a_note_not_a_failure() -> None:
    ign = [sc.Ignore("a.py", "B608", 2, "values are bound as parameters")]
    failures, notes = sc.judge([sc.Finding("a.py", "B608", 3)], ign)
    assert failures == []
    assert notes == ["a.py: B608: the ignore accepts 2, 1 found"]


def test_the_repository_ignore_file_is_valid_and_every_path_exists() -> None:
    for scan in sc.SCANS:
        rows = sc.load_ignores(sc.IGNORES, scan)
        assert rows, scan
        for row in rows:
            assert (sc.ROOT / row.path).is_file(), row.path
    table = sc.ignores_table(sc.IGNORES)
    assert table.startswith("| Scan | File | Rule | Count | Reason |")


def test_an_ignore_that_matches_nothing_fails() -> None:
    """Security review 2026-11-13: a dead ignore (the code it named is gone) let the next finding of its rule in that
    file pass unseen; it now fails until it is removed."""
    ign = [sc.Ignore("a.py", "B608", 1, "values are bound as parameters"), sc.Ignore("b.py", "B324", 1, "md5 of x")]
    failures, notes = sc.judge([sc.Finding("a.py", "B608", 3)], ign)
    assert failures == ["b.py: B324: the ignore accepts 1 and nothing is found: remove it"]
    assert notes == []
