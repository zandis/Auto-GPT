"""Exercise the bypass inventory, including attempts to grow it together with the code."""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

import pytest

from tools import screening_inputs_guard as guard

FILE = "services/example.py"
LOCATION = (FILE, "entry")


def test_all_screening_input_boundaries_match_the_ratchet_and_git_base() -> None:
    guard.check_ratchet()


@pytest.mark.parametrize(
    ("source", "area"),
    [
        ("from adapter.backfill import backfill as load\nload(cfg)", "backfill"),
        ("import lake.client as c\nstart = c.LakeHttp.start_rebuild\nstart(client, request)", "rebuild"),
        ("choose = getattr(lake, 'generation')\nchoose()", "generation"),
        ("from os import replace as publish\np = root / 'CURRENT'\npublish(tmp, p)", "pointer"),
        ("from pathlib import Path as P\np = P(root, 'CURRENT')\nsave = p.write_text\nsave(gen)", "pointer"),
        ("build = dict\nopts = build(options=build(lake_generation=gen))", "generation"),
        ("k = 'lake_generation'\nopts = dict([(k, gen)])", "generation"),
        ("data.setdefault('job', {}).setdefault('options', {})['lake_generation'] = g", "generation"),
        ("from operator import setitem as write\nwrite(job['options'], 'generation', g)", "generation"),
        ("write = cfg['job']['options'].update\nwrite(lake_generation=g)", "generation"),
        ("from criteria_compiler.import_ruleset import install as load\nload(repo, path)", "importer"),
        ("from functools import partial\nlaunch = partial(lake.start_rebuild, day)\nlaunch()", "rebuild"),
        ("send = client.post\nsend(f'{base}/holds', json=dict(snapshot=g, pin=True))", "generation"),
        ("send = client.post\nsend('http://lake/promote', json=payload)", "pointer"),
        ("from adapter.ndjson import list_snapshots as available\ncurrent = available(folder)[-1]", "generation"),
        ("import datacore.dataops as d\nd.DataOps.decide(ledger, decision)", "steward"),
        ("from lake.source import omop_rows as rows\nlist(rows(source))", "builders"),
        ("def worker():\n    send = client.post\n    send('/promote', payload)\nworker()", "pointer"),
        ("ask = dict(type='INGEST')", "ingest"),
        ("from lake.client import LakeHttp as Client\nreader = Client(url)\nreader.generation()", "generation"),
        (
            "from other import admit_screening_inputs\ng,v = admit_screening_inputs(r)\nlake.hold(g, h, pin=True)",
            "generation",
        ),
        (
            "from tb_common.screening_inputs import admit_screening_inputs as admit\nadmit(r)\nlake.hold(g, h, pin=True)",
            "generation",
        ),
        (
            "from tb_common.screening_inputs import admit_screening_inputs as admit\nif ok:\n    g,v = admit(r)\nlake.hold(g, h, pin=True)",
            "generation",
        ),
        (
            "from tb_common.screening_inputs import admit_screening_inputs as admit\ng,v = admit(r)\nlake.hold(g or other, h, pin=True)",
            "generation",
        ),
    ],
)
def test_new_alias_construction_or_mutation_is_a_bypass(source: str, area: str) -> None:
    from textwrap import indent

    hits = guard.scan_source(FILE, "def entry():\n" + indent(source, "    "))
    assert any(counts[area] for counts in hits.values())


def test_a_pin_uses_the_gate_result() -> None:
    source = dedent(
        """\
        from tb_common.screening_inputs import admit_screening_inputs as admit
        def entry(record, use, digest, clearance, audit):
            g, v = admit(record, use, digest, clearance, audit)
            lake.hold(g, holder, pin=True)
        """
    )
    assert not guard.scan_source(FILE, source)
    assert LOCATION in guard.scan_source(FILE, source.replace("lake.hold(g,", "lake.hold(other,"))
    assert LOCATION in guard.scan_source(FILE, source.replace("lake.hold(g,", "lake.hold(v,"))
    changed = source.replace("    lake.hold", "    if fallback:\n        g = other\n    lake.hold")
    assert LOCATION in guard.scan_source(FILE, changed)


def test_inventory_covers_the_real_producers_and_leaves_screen_start_clear() -> None:
    entries = guard.inventory((guard.ROOT / guard.RATCHET).read_bytes())
    assert {
        ("services/adapter/ndjson.py", "_write_type"),
        ("services/lake/source.py", "lake_rows"),
        ("services/lake/source.py", "omop_rows"),
        ("services/adapter/backfill.py", "_publish"),
        ("services/lake/store.py", "Lake._point_alias"),
        ("services/lake/store.py", "Lake.promote"),
        ("services/lake/store.py", "Lake.start_rebuild.run"),
        ("services/datacore/dataops.py", "DataOps.decide"),
        ("services/criteria_compiler/import_ruleset.py", "install"),
        ("libs/tb_common/derived_store.py", "run_batch"),
    } <= entries
    for file, function, before, after in [
        ("services/orchestrator/scenarios/screen.py", "run", "rs, scope = start_screen(ctx)", "rs, scope = pick(ctx)"),
        ("services/orchestrator/scenarios/screen.py", "start_screen", "lake.admit_screen(", "lake.unchecked("),
        ("services/orchestrator/jobs.py", "PinnedLake.admit_screen", "= admit_screening_inputs(", "= bypass("),
    ]:
        assert (file, function) not in entries
        source = (guard.ROOT / file).read_text()
        assert (file, function) in guard.scan_source(file, source.replace(before, after))


@pytest.mark.parametrize("fault", ["unlisted", "obsolete", "added_with_json", "second_sink", "previously_removed"])
def test_editing_the_json_does_not_buy_a_bypass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    base = "def entry():\n    lake.rebuild()\n"
    current = base
    row = {"file": FILE, "function": "entry", "why": "The existing rebuild takes a date."}
    expected = [row]
    if fault == "unlisted":
        expected = []
    elif fault == "obsolete":
        current = "def entry(): pass"
    elif fault == "added_with_json":
        current += "def new():\n    lake.rebuild()\n"
        expected.append({**row, "function": "new"})
    elif fault == "second_sink":
        current += "    lake.rebuild()\n"
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    monkeypatch.setattr(guard, "RATCHET", "inventory.json")
    (tmp_path / "inventory.json").write_text(json.dumps(expected))
    monkeypatch.setattr(guard, "working_tree", lambda: guard.scan_source(FILE, current))
    monkeypatch.setattr(guard, "base_revision", lambda: "test-base")
    monkeypatch.setattr(guard, "base_files", lambda _: [(FILE, base)])

    def read_git(*args: str) -> bytes:
        if args[0] == "ls-tree":
            return b"present" if fault == "previously_removed" else b""
        if args[0] == "rev-parse":
            return b"trialbox/"
        assert args == ("show", "test-base:trialbox/inventory.json")
        return b"[]"

    monkeypatch.setattr(guard, "git", read_git)
    with pytest.raises(AssertionError, match=fault if fault in {"unlisted", "obsolete"} else "new screening"):
        guard.check_ratchet()


def test_base_is_configurable_and_defaults_to_origin_master(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guard, "git", lambda *args: args[-1].encode())
    monkeypatch.delenv(guard.BASE_ENV, raising=False)
    assert guard.base_revision() == "origin/master^{commit}"
    monkeypatch.setenv(guard.BASE_ENV, "review-base")
    assert guard.base_revision() == "review-base^{commit}"
