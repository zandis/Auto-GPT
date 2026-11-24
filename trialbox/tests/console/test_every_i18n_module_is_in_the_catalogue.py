"""9i-1: every ``services/console/i18n_*.py`` is in the console's catalogue as soon as ``console.i18n`` is imported.

A page module used to join its own catalogue when it was imported. The users page (/ops/users, on every box) read
``role.steward``, which only the pilot's break-glass page joined: the page answered or raised by what an earlier test
in the same worker had imported (the nightly's random order, shard 4/6 on 2026-11-19). The check runs in a fresh
interpreter that imports ``console.i18n`` alone, so no earlier import in the suite can hide a missing join."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "services" / "console"

#: imports console.i18n alone, keeps its catalogue, then reads each module's EN, JA and ZH: the keys not in it
PROBE = """
import importlib, json, sys
from console import i18n
have = {lang: set(cat) for lang, cat in i18n.CATALOGUES.items()}
gaps = {}
for name in sys.argv[1:]:
    mod = importlib.import_module("console." + name)
    for attr, lang in (("EN", "en"), ("JA", "ja"), ("ZH", "zh-TW")):
        miss = sorted(set(getattr(mod, attr)) - have[lang])
        if miss:
            gaps[name + "." + attr] = miss[:5] + (["..."] if len(miss) > 5 else [])
print(json.dumps(gaps))
"""


def test_each_i18n_module_is_joined_when_the_catalogue_is_imported() -> None:
    names = sorted(p.stem for p in CONSOLE.glob("i18n_*.py"))
    assert len(names) > 40, names  # the folder was read, not an empty glob
    child = subprocess.run(
        [sys.executable, "-c", PROBE, *names],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(str(ROOT / p) for p in ("libs", "services", "."))},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert child.returncode == 0, child.stderr[-2000:]
    assert json.loads(child.stdout) == {}
