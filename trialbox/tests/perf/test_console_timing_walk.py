# ruff: noqa: F811 - the box fixture is imported and taken by name
"""The console's ten-page timing walk (D-1245, card 10E-13, review 13 item 13-14): p95 server time under 300 ms.

Each of the ten pages of ``tests/console/timing_walk.py`` on the console test box (synthetic studies and patients, the
in-memory stand-in orchestrator, no model): ``tools.console_timing.WARMUP`` answers not counted, then ``REPEAT``
answers whose time is read from the console's ``Server-Timing`` header; a page whose p95 is over the budget twice
fails. The report is ``$TB_CONSOLE_TIMING_OUT/console_timing.md`` (and ``.json``) when that is set.

Marker ``perf``: not in the unit run. The rules (and the planted slow page that must fail) are
``tests/console/test_console_timing.py``, on every pull request.

    TB_CONSOLE_TIMING_OUT=out/ pytest tests/perf/test_console_timing_walk.py -m perf
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from tests.console.test_console_app import box  # noqa: F401
from tests.console.timing_walk import TEN, ten_pages
from tools import console_timing as ct

pytestmark = [pytest.mark.perf]


def test_the_ten_pages_answer_within_the_budget(box: dict[str, Any], tmp_path: Path) -> None:
    rep = ct.walk(ten_pages(box))
    out = Path(os.environ.get("TB_CONSOLE_TIMING_OUT") or tmp_path / "console-timing")
    rep.write(out)
    print(rep.markdown())
    assert len(rep.pages) == len(TEN) and all(len(t.times) == ct.REPEAT for t in rep.pages if not t.broken)
    assert not rep.failed(), rep.markdown()
