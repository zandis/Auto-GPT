"""Card H-148 (the integrator's 7170464780): the box rehearsal ingests under the site's day, not UTC's.

At 18:00Z it is 02:00 the next day in Taipei: the box's own nightly ingest had made that day's snapshot, and
``tools/rehearse_box/box.sh`` ingested with ``date -u +%F``, the day before, so its SCREEN step failed
("ingest of synthetic hospital A failed"). The day is the site's: the zone the product reads with no settings object
(``tb_common.config.site_tz``: ``TB_TZ``, which compose requires to be ``site.tz``, D-315), from the box's own
``deploy/.env``; no zone is no day, never UTC's.

The clock is held: a stand-in ``date`` answers for one fixed instant and honours ``TZ`` and ``-u`` as the real one
does. The SCREEN step's own ingest lines run, with box.sh's own helpers and the box's compose stood in."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BOX_SH = ROOT / "tools" / "rehearse_box" / "box.sh"

pytestmark = pytest.mark.nodb

AT = "2026-11-25T18:00:00Z"  # 02:00 on 2026-11-26 in Asia/Taipei and Asia/Tokyo (+08:00, +09:00)
DATE = f"""#!/bin/sh
exec /bin/date -d "{AT}" "$@"
"""


def _helpers(text: str) -> str:
    """box.sh's one-line helpers (``envget`` and, when there, ``site_day``): the functions the snapshot reads."""
    keep = [ln for ln in text.splitlines() if re.match(r"(envget|site_day)\(\) \{", ln)]
    assert any(ln.startswith("envget() {") for ln in keep)
    return "\n".join(keep) + "\n"


def _ingest_lines(text: str) -> str:
    """The SCREEN step's lines that ingest synthetic hospital A (inside its ``if [ ! -f "$W/ingested" ]``)."""
    block = text[text.index("\nscreen)\n") :]
    head = block.index('if [ ! -f "$W/ingested" ]; then\n') + len('if [ ! -f "$W/ingested" ]; then\n')
    body = block[head : block.index('touch "$W/ingested"', head)]
    assert "adapter.cli run" in body and "site-a" in body, body
    return body


def _day(tmp_path: Path, env_lines: str) -> subprocess.CompletedProcess[str]:
    text = BOX_SH.read_text(encoding="utf-8")
    box = tmp_path / "box"
    (box / "deploy").mkdir(parents=True)
    (box / "deploy" / ".env").write_text(env_lines, encoding="utf-8")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "date").write_text(DATE, encoding="utf-8")
    (bindir / "date").chmod(0o755)
    body = (
        'fail() { echo "FAIL: $*" >&2; exit 1; }\n'
        # the box's compose, stood in: it prints the snapshot the ingest was given, and nothing else runs
        'dc() { while [ $# -gt 0 ]; do [ "$1" = --snapshot ] && { echo "snapshot=$2"; return 0; }; shift; done; '
        'echo "snapshot=none"; }\n' + _helpers(text) + _ingest_lines(text)
    )
    env = {**os.environ, "PATH": f"{bindir}:/usr/bin:/bin", "BOX": str(box), "W": str(tmp_path), "TZ": "UTC"}
    return subprocess.run(["bash", "-c", body], capture_output=True, text=True, env=env, check=False)


@pytest.mark.parametrize(("zone", "day"), [("Asia/Taipei", "2026-11-26"), ("Asia/Tokyo", "2026-11-26"),
                                           ("America/New_York", "2026-11-25")])  # fmt: skip
def test_the_screen_ingests_under_the_sites_day(tmp_path: Path, zone: str, day: str) -> None:
    res = _day(tmp_path, f"COMPOSE_FILE=docker-compose.yml\nTB_TZ={zone}\n")
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == f"snapshot={day}", (zone, res.stdout, res.stderr)


def test_no_site_zone_is_no_day(tmp_path: Path) -> None:
    """As the product: no zone is an error (D-315), not UTC's day."""
    res = _day(tmp_path, "COMPOSE_FILE=docker-compose.yml\n")
    assert res.returncode != 0 and "snapshot=" not in res.stdout, res.stdout
    assert "TB_TZ" in res.stderr
