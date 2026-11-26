"""R1+1 walk: ``adapter run --snapshot "$(date -u +%F)"`` before 09:00 at a site in Asia/Tokyo named the day before.
The FHIR load refused it ("fhir is built from <site date>; a build from the older <utc date> is refused"), the lake
step took it, and the run died on the publish record (FileNotFoundError).

Now every step names the night by one date, the site's (``tb_common.generation.site_today``): the adapter's run and
back-fill, and the site seed that loads the sample. A ``--snapshot`` older than a night the box already holds (the
lake's ``CURRENT`` or the FHIR store's generation) is refused before any step, with one message. Synthetic data
only."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from adapter.ndjson import snapshot_dir
from adapter.pipeline import FutureNight, HeldNightUnread, OlderNight, refuse_older_night, run_ingest
from tb_common import generation

from tests.unit.test_dataflow_lake_p0 import _cfg, _csv, _row
from tools import site_seed
from tools.box.plan import SAMPLE_FEED

AT = datetime(2026, 11, 26, 23, 30, tzinfo=UTC)  # 08:30 on the 27th in Tokyo; still the 26th in UTC


class _At(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> Any:
        return AT.astimezone(tz)


def test_the_site_date_is_the_site_zone_s_never_utc_s(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(generation, "datetime", _At)
    assert generation.site_today("Asia/Tokyo").isoformat() == "2026-11-27"
    assert generation.site_today("UTC").isoformat() == "2026-11-26"
    with pytest.raises(ValueError, match="TB_TZ"):
        generation.site_today("")


def _events(tmp_path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for f in sorted((tmp_path / "audit").glob("*.jsonl")):
        out += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x]
    return out


def test_a_snapshot_older_than_the_served_night_is_refused_before_any_step(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    cfg.lake_dir.mkdir(parents=True)
    (cfg.lake_dir / "CURRENT").write_text("2026-10-02.g1\n", encoding="utf-8")
    _csv(tmp_path / "feed", [_row("D1", "2026-09-01")])
    with pytest.raises(OlderNight) as got:
        run_ingest(cfg, "csv", str(tmp_path / "feed"), snapshot="2026-10-01", load_fhir=False, validate=False)
    said = str(got.value)
    assert "--snapshot 2026-10-01 is not the site's date" in said
    assert "the lake already holds the newer night 2026-10-02" in said
    assert isinstance(got.value, FutureNight)  # the command line and the HTTP run say "refused, nothing was read"
    assert not snapshot_dir(cfg.lake_dir, "2026-10-01").exists() and not (cfg.lake_dir / "tmp").exists()
    (ev,) = [e for e in _events(tmp_path) if e.get("detail", {}).get("refused") == "older_night"]
    assert ev["event"] == "ingest.failed" and ev["detail"]["reason"] == said


def test_the_served_night_again_a_newer_night_and_a_name_that_is_not_a_date_are_not_judged(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    cfg.lake_dir.mkdir(parents=True)
    (cfg.lake_dir / "CURRENT").write_text("2026-10-02\n", encoding="utf-8")
    today = generation.site_today(cfg.tz)
    for snap in ("2026-10-02", "2026-10-03", "golden", today.isoformat()):
        refuse_older_night(cfg, snap, today)
    with pytest.raises(OlderNight):
        refuse_older_night(cfg, "2026-10-01", today)


def test_the_fhir_store_s_newer_night_refuses_a_rerun_of_the_served_night(tmp_path: Path, db_url: str) -> None:
    """The walk's case: the lake still served the UTC-dated night while the FHIR store held the site's date."""
    from datacore.generations import Built

    with Built() as book:
        book.finish("fhir", book.begin("fhir", "2026-10-02"))
    cfg = _cfg(tmp_path)
    cfg.lake_dir.mkdir(parents=True)
    (cfg.lake_dir / "CURRENT").write_text("2026-10-01\n", encoding="utf-8")
    with pytest.raises(OlderNight, match="the FHIR store already holds the newer night 2026-10-02"):
        run_ingest(cfg, "csv", str(tmp_path / "no-feed"), snapshot="2026-10-01", load_fhir=False, validate=False)


def test_a_ledger_that_cannot_be_read_refuses_a_hand_given_night_before_any_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review R2 / M1: with a trial database configured, a failed read is not "the FHIR store holds nothing"."""
    from datacore import generations

    class Down:
        def __enter__(self) -> Any:
            raise ConnectionRefusedError("connection refused")

        def __exit__(self, *_a: Any) -> None:
            return None

    monkeypatch.setattr(generations, "Built", Down)
    cfg = _cfg(tmp_path)
    cfg.lake_dir.mkdir(parents=True)
    (cfg.lake_dir / "CURRENT").write_text("2026-09-30\n", encoding="utf-8")  # the lake alone would let it pass
    _csv(tmp_path / "feed", [_row("D1", "2026-09-01")])
    with pytest.raises(HeldNightUnread, match="FHIR store's newest night could not be read") as got:
        run_ingest(cfg, "csv", str(tmp_path / "feed"), snapshot="2026-10-01", load_fhir=False, validate=False)
    assert isinstance(got.value, FutureNight) and "ConnectionRefusedError" in str(got.value)
    assert not snapshot_dir(cfg.lake_dir, "2026-10-01").exists() and not (cfg.lake_dir / "tmp").exists()
    (ev,) = [e for e in _events(tmp_path) if e.get("detail", {}).get("refused") == "held_night_unread"]
    assert ev["event"] == "ingest.failed"


def test_the_site_seed_loads_the_sample_under_the_site_s_date(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / "settings.yaml").write_text("site:\n  id: a\ndepartments: []\n", encoding="utf-8")
    (deploy / ".env").write_text(f"TB_ENV=TEST\nTB_TZ=Asia/Tokyo\nTB_SOURCE_DIR={SAMPLE_FEED}\n", encoding="utf-8")
    monkeypatch.setattr(generation, "datetime", _At)
    calls: list[list[str]] = []

    def sh(argv: list[str], text: str | None = None) -> str:
        calls.append(argv)
        return ""

    site_seed.run(deploy, sh)
    (load,) = [c for c in calls if "adapter.cli" in c]
    assert load[load.index("--snapshot") + 1] == "2026-11-27"  # not the UTC date, 2026-11-26


def test_the_site_seed_refuses_a_box_without_its_zone(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / "settings.yaml").write_text("site:\n  id: a\ndepartments: []\n", encoding="utf-8")
    (deploy / ".env").write_text(f"TB_ENV=TEST\nTB_SOURCE_DIR={SAMPLE_FEED}\n", encoding="utf-8")
    with pytest.raises(site_seed.SeedError, match="TB_TZ"):
        site_seed.run(deploy, lambda *_a, **_k: "")
