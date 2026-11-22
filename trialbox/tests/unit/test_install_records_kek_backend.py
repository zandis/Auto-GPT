import re
from pathlib import Path


def test_install_records_kek_backend(monkeypatch: None) -> None:
    """
    Ensure that the installer records the KEK back‑end used
    (TB_KEK_BACKEND) in ``deploy/.env``.  The install script should
    contain an ``envset TB_KEK_BACKEND`` line after sealing the keys.
    """
    # Resolve the path to the installer script relative to this test file
    script_path = Path(__file__).resolve().parents[2] / "deploy" / "install.sh"
    content = script_path.read_text(encoding="utf-8")
    # The script must write the KEK back‑end into .env
    assert re.search(r"^\s*envset\s+TB_KEK_BACKEND\s+", content, re.MULTILINE), (
        "install.sh should record TB_KEK_BACKEND in deploy/.env"
    )
