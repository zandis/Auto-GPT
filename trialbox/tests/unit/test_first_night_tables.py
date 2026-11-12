"""NEW-DIN-8 (DIN-008, D-583): the first night needs every table the mapping declares.

Before: the completeness gate compared a night with the last good night. On the first night there is none, so
``lab.csv`` missing or ``medication.csv`` with a header only passed, moved ``CURRENT`` and became the baseline: the
table was never asked for again. Go-live night is a first night.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from adapter.ndjson import snapshot_dir
from adapter.pipeline import COMPLETENESS, HELD, PASSED, AdapterConfig, run_ingest
from tb_contracts import RebuildResult

ROOT = Path(__file__).resolve().parents[2]
SITE_A = ROOT / "tests/fixtures/synthetic_patients/site-a"
MAPPING = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
NIGHT = "2026-11-01"


class _Rebuild:
    def __init__(self, lake_dir: Path) -> None:
        self.lake_dir, self.calls = lake_dir, 0

    def __call__(self, snap: str, nd: Path) -> RebuildResult:
        self.calls += 1
        (self.lake_dir / "db").mkdir(parents=True, exist_ok=True)
        (self.lake_dir / "CURRENT").write_text(snap)
        return RebuildResult(snapshot=snap, tables={}, chunks=0, embedded_new=0, seconds=0.0)


def _site(tmp: Path, url: str, **kw: Any) -> tuple[AdapterConfig, _Rebuild, Path]:
    feed = tmp / "feed"
    shutil.copytree(SITE_A, feed, ignore=shutil.ignore_patterns("*.json"))
    sec = tmp / "secrets"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(b"k" * 32)
    rb = _Rebuild(tmp / "lake")
    sep = "&" if "?" in url else "?"
    cfg = AdapterConfig(lake_dir=tmp / "lake", secrets_dir=sec, mapping_path=MAPPING, site_id="T", rebuild=rb,
                        audit_dir=tmp / "audit", db_url=f"{url}{sep}tb_prefix=first{os.getpid()}_", **kw)  # fmt: skip
    return cfg, rb, feed


def _header_only(path: Path) -> None:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        header = next(csv.reader(fh))
    with path.open("w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerow(header)


def _night(cfg: AdapterConfig, feed: Path, snap: str = NIGHT) -> Any:
    return run_ingest(cfg, "csv", str(feed), snapshot=snap, load_fhir=False, validate=False)


@pytest.mark.parametrize(("table", "how", "word"), [("lab", "missing", "missing"), ("medication", "empty", "empty"),
                                                    ("diagnosis", "missing", "missing"), ("note", "empty", "empty")])  # fmt: skip
def test_a_first_night_without_a_mapped_table_is_held(tmp_path: Path, pg_cluster_url: str, table: str, how: str,
                                                      word: str) -> None:  # fmt: skip
    cfg, rb, feed = _site(tmp_path, pg_cluster_url, first_night_all_tables=True)
    (feed / f"{table}.csv").unlink() if how == "missing" else _header_only(feed / f"{table}.csv")
    rep = _night(cfg, feed)
    assert rep.held and not rep.passed and rb.calls == 0
    assert not (cfg.lake_dir / "CURRENT").exists()  # nothing was published: there is no baseline with a hole in it
    out = snapshot_dir(cfg.lake_dir, NIGHT)
    assert (out / HELD).exists() and not (out / PASSED).exists()
    text = " ".join(rep.errors)
    assert f"{table}: table {word} and no earlier good night had it" in text and "optional_tables" in text
    problems = json.loads((out / COMPLETENESS).read_text(encoding="utf-8"))["problems"]
    assert [p.split(":")[0] for p in problems] == [table]
    # the extract is repaired: the same night passes and is the baseline
    shutil.copy(SITE_A / f"{table}.csv", feed / f"{table}.csv")
    again = _night(cfg, feed)
    assert again.passed and (cfg.lake_dir / "CURRENT").read_text().strip() == NIGHT


def test_a_table_the_site_does_not_have_is_listed_as_optional(tmp_path: Path, pg_cluster_url: str) -> None:
    cfg, rb, feed = _site(tmp_path, pg_cluster_url, first_night_all_tables=True, optional_tables=("claim", "report"))
    (feed / "claim.csv").unlink()
    _header_only(feed / "report.csv")
    rep = _night(cfg, feed)
    assert rep.passed and not rep.held and rb.calls == 1


def test_a_whole_first_night_passes(tmp_path: Path, pg_cluster_url: str) -> None:
    cfg, rb, feed = _site(tmp_path, pg_cluster_url, first_night_all_tables=True)
    assert _night(cfg, feed).passed and rb.calls == 1


def test_the_rule_is_for_the_first_night_only_a_later_night_is_judged_against_the_last_good_one(
    tmp_path: Path, pg_cluster_url: str
) -> None:
    cfg, _rb, feed = _site(tmp_path, pg_cluster_url, first_night_all_tables=True, optional_tables=("claim",))
    (feed / "claim.csv").unlink()
    assert _night(cfg, feed).passed
    rep = _night(cfg, feed, "2026-11-02")  # claim is still absent: optional, and not in the baseline
    assert rep.passed
    (feed / "lab.csv").unlink()  # T-611's own rule still holds the later night
    rep = _night(cfg, feed, "2026-11-03")
    assert rep.held and "lab: table missing (last good night" in " ".join(rep.errors)


def test_the_override_of_a_night_lets_a_first_night_through_with_its_reason(
    tmp_path: Path, pg_cluster_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tb_common import feedguard

    cfg, rb, feed = _site(tmp_path, pg_cluster_url, first_night_all_tables=True)
    (feed / "claim.csv").unlink()
    monkeypatch.setenv(feedguard.OVERRIDE_ENV, f"{NIGHT}: the claims extract follows next week")
    rep = _night(cfg, feed)
    assert rep.passed and rb.calls == 1
    events = [json.loads(x) for f in sorted((tmp_path / "audit").glob("*.jsonl")) for x in f.read_text().splitlines()]
    done = [e for e in events if e["event"] == "ingest.done"][-1]
    assert "claims extract follows next week" in done["detail"]["drop_override"]


def test_the_product_s_entry_always_sets_the_rule() -> None:
    """``adapter.cli.build_config`` is the only way the box starts a night; no setting turns the rule off."""
    import inspect

    from adapter import cli

    src = inspect.getsource(cli.build_config)
    assert "first_night_all_tables=True" in src
    assert AdapterConfig.__dataclass_fields__["first_night_all_tables"].default is False  # tools and tests opt in


# ---------------------------------------------------------------- the adversarial review of PR #351 (2026-11-12)
def test_a_delta_is_never_the_first_night(tmp_path: Path, pg_cluster_url: str) -> None:
    """H1: ``--since`` on an empty lake passed with ``lab.csv`` missing and became the baseline."""
    cfg, rb, feed = _site(tmp_path, pg_cluster_url, first_night_all_tables=True)
    (feed / "lab.csv").unlink()
    rep = run_ingest(cfg, "csv", str(feed), snapshot=NIGHT, since="2026-10-01", load_fhir=False, validate=False)
    assert rep.held and rb.calls == 0 and not (cfg.lake_dir / "CURRENT").exists()
    assert "run a full load" in " ".join(rep.errors or [])


@pytest.mark.parametrize("baseline", ["no completeness record", "the table had no rows"])
def test_a_table_no_earlier_good_night_had_is_still_asked_for(tmp_path: Path, pg_cluster_url: str,
                                                              baseline: str) -> None:  # fmt: skip
    """H2, M1: the night after a first load (the back-fill writes no completeness record), and the night after a
    night that an override or an older build let through with the table empty."""
    cfg, _rb, feed = _site(tmp_path, pg_cluster_url)  # an earlier good night, made without the rule
    (feed / "lab.csv").unlink()
    assert _night(cfg, feed).passed
    if baseline == "no completeness record":
        (snapshot_dir(cfg.lake_dir, NIGHT) / COMPLETENESS).unlink()
    cfg.first_night_all_tables = True
    rep = _night(cfg, feed, "2026-11-02")
    assert rep.held and "lab: table missing and no earlier good night had it" in " ".join(rep.errors)
    assert (cfg.lake_dir / "CURRENT").read_text().strip() == NIGHT
    shutil.copy(SITE_A / "lab.csv", feed / "lab.csv")
    assert _night(cfg, feed, "2026-11-02").passed


def test_an_override_lets_one_night_through_and_the_next_night_asks_again(
    tmp_path: Path, pg_cluster_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tb_common import feedguard

    cfg, _rb, feed = _site(tmp_path, pg_cluster_url, first_night_all_tables=True)
    (feed / "lab.csv").unlink()
    monkeypatch.setenv(feedguard.OVERRIDE_ENV, f"{NIGHT}: the lab extract follows tomorrow")
    assert _night(cfg, feed).passed
    monkeypatch.delenv(feedguard.OVERRIDE_ENV)
    rep = _night(cfg, feed, "2026-11-02")
    assert rep.held and "lab: table missing and no earlier good night had it" in " ".join(rep.errors)


def test_a_table_of_deleted_rows_only_is_empty(tmp_path: Path, pg_cluster_url: str) -> None:
    """M2: "with rows" counted the source rows before the deleted ones were set aside."""
    cfg, rb, feed = _site(tmp_path, pg_cluster_url, first_night_all_tables=True)
    with (feed / "claim.csv").open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    with (feed / "claim.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=[*rows[0], "deleted"])
        w.writeheader()
        w.writerows({**r, "deleted": "1"} for r in rows)
    rep = _night(cfg, feed)
    assert rep.held and rb.calls == 0 and "claim: table empty and no earlier good night had it" in " ".join(rep.errors)


def test_a_file_set_aside_for_its_form_is_not_also_called_empty(tmp_path: Path, pg_cluster_url: str) -> None:
    """L1: the quarantine's own error is the reason; "empty ... goes under optional_tables" misled."""
    cfg, _rb, feed = _site(tmp_path, pg_cluster_url, first_night_all_tables=True)
    (feed / "claim.csv").write_bytes(b"\xff\xfe\x00\x00 not a csv \x81\x00")
    rep = _night(cfg, feed)
    text = " ".join(rep.errors)
    assert rep.held and "claim:" in text and "no earlier good night had it" not in text


def test_the_shipped_settings_name_the_way_out() -> None:
    import yaml

    doc = yaml.safe_load((ROOT / "deploy/settings.example.yaml").read_text(encoding="utf-8"))
    assert doc["feed_completeness"]["optional_tables"] == []
