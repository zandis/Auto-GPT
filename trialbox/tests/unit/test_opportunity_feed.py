"""Trial-opportunity feed (D-467): only aggregates leave a site, and the review's attacks (T-740 review, findings 1 to
11) stay closed. Each attack the reviewer ran is a test here."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pyarrow as pa
import pytest
from criteria_compiler.ctgov import CtGov
from opportunity_hub import dashboard
from opportunity_hub.dashboard import render
from orchestrator.clients import StepFailed
from orchestrator.scenarios import feas_compute as fc
from orchestrator.scenarios import opportunity as scen
from tb_common import opportunity as opp
from tb_common import optout as optout_mod
from tb_common.crypto import ed25519_generate
from tb_common.ruleset import Ruleset
from tb_common.smallcell import funnel_drops_publishable
from tb_contracts import CtgovSearchRequest

from tools import opportunity_feed as tool

ROOT = Path(__file__).resolve().parents[2]
T = 10
PERIOD = opp.period_of(date(2026, 11, 12))
SECRET = b"s" * 32
NCT = "NCT00000001"


def _sim(prevalent: int, monthly: float, seed: int) -> dict[str, float]:
    out = fc.simulate(
        prevalent=prevalent,
        monthly_rate=monthly,
        reach=0.6,
        accept=0.35,
        capacity=None,
        months=12,
        iterations=500,
        seed=seed,
    )
    return {k: float(out[k]) for k in ("low", "mid", "high")}


def _counts(
    steps: list[int] | None = None, *, prevalent: int = 400, incident: int = 148, nct: str = NCT, **kw: Any
) -> opp.StudyCounts:
    remaining = steps if steps is not None else [1000, 702, 698, 437]
    labels = ["pool", "eGFR < 30", "prior anti-amyloid", "MRI exclusion", "e", "f", "g"]
    return opp.StudyCounts(
        nct_id=nct,
        title="A study",
        condition="AD",
        phases=("PHASE3",),
        sponsor="Sponsor",
        countries=("Taiwan", "Atlantis"),
        last_update="2026-11-01",
        target_enrollment=300,
        criteria_total=6,
        criteria_applied=len(remaining),
        steps=tuple(zip(labels, remaining, strict=False)),
        prevalent=prevalent,
        incident_12m=incident,
        **kw,
    )


def _feed(counts: list[opp.StudyCounts], **kw: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "site_id": "tw",
        "site_label": "Taiwan",
        "country": "Taiwan",
        "period": PERIOD,
        "snapshot": "2026-11-11",
        "registry_source": ["cassette"],
        "conditions": ["AD"],
        "counts": counts,
        "approved": {c.nct_id for c in counts} or {NCT},
        "per_condition_cap": 20,
        "secret": SECRET,
        "simulate": _sim,
        "now": datetime(2026, 11, 12, 3, 45, tzinfo=UTC),
    }
    args.update(kw)
    return opp.build(**args)


def _row(c: opp.StudyCounts) -> dict[str, Any] | None:
    return opp.row(c, T, PERIOD, SECRET, _sim)


def test_counts_rounded_and_not_matched_by_the_funnel_rule() -> None:
    r = _row(_counts())
    assert r is not None
    assert r["eligible_now"] == 440 and r["status"] == "counted" and r["reason"] is None
    assert r["new_per_month"] == 12.5  # 148 -> 150 a year -> 12.5 a month
    assert r["countries"] == ["Taiwan"]  # not in the enumeration: dropped at the site
    # drops 298 (remainder 702), 4 (under the floor: withheld, and its neighbour 261 with it), so only one is listed
    assert r["not_matched"] == [{"criterion": "eGFR < 30", "removed": 300}]


# -- finding 1: the rate came from the exact yearly count ------------------------------------------------------------
def test_f1_one_new_patient_a_year_publishes_no_rate() -> None:
    """Reviewer: eligible 120 with 0.1 a month meant exactly one new eligible patient in 12 months."""
    r = _row(_counts([300, 120], incident=1))
    assert r is not None and r["eligible_now"] == 120 and r["new_per_month"] is None


def test_f1_a_published_rate_never_pins_the_yearly_count() -> None:
    seen: dict[float | None, set[int]] = defaultdict(set)
    for n in range(0, 400):
        seen[opp.rate(n, T)].add(n)
    assert seen[None] == set(range(T))
    for value, ns in seen.items():
        if value is not None:
            assert len(ns) >= T // 2, (value, ns)  # the rounding's own interval, never one value
            assert opp._rate_ok(value, T)


# -- finding 2: the band could be inverted ----------------------------------------------------------------------------
def test_f2_the_band_does_not_pin_the_prevalent_count() -> None:
    """Reviewer: P10/P50/P90 with a public seed pinned the prevalent count to 1 to 4 values. Now every published row
    (count, rate and band) is shared by at least the rounding's interval of prevalent counts."""
    groups: dict[str, set[int]] = defaultdict(set)
    for prevalent in range(15, 260):
        r = _row(_counts([prevalent + 300, prevalent], prevalent=prevalent, incident=0))
        groups[json.dumps(r, sort_keys=True)].add(prevalent)
    assert groups and min(len(v) for v in groups.values()) >= T // 2


def test_f2_band_from_rounded_inputs_seeded_by_the_site_secret() -> None:
    r = _row(_counts([900, 437], prevalent=437, incident=148))
    assert r is not None and r["enrol_12m"] is not None
    assert all(v is None or v % T == 0 for v in r["enrol_12m"].values())
    same = _row(_counts([900, 441], prevalent=441, incident=150))  # the same rounded inputs
    assert same is not None and same["enrol_12m"] == r["enrol_12m"]
    other = opp.band(_counts(prevalent=437), T, PERIOD, b"t" * 32, _sim)
    seeds = {opp._seed(SECRET, NCT, PERIOD), opp._seed(b"t" * 32, NCT, PERIOD)}
    assert len(seeds) == 2 and other is not None  # no secret, no replay: the seed is not public
    bare = opp.row(_counts(), T, PERIOD, None, _sim)
    assert bare is not None and bare["enrol_12m"] is None  # no secret: no band at all


def test_f2_a_band_narrower_than_the_rounding_keeps_only_the_middle() -> None:
    narrow = opp.band(_counts(), T, PERIOD, SECRET, lambda p, m, s: {"low": 21.0, "mid": 24.0, "high": 28.0})
    assert narrow == {"low": None, "mid": 20, "high": None}


# -- finding 3 and 9: probe studies, small rows, zero ----------------------------------------------------------------
@pytest.mark.parametrize("eligible", [0, 1, 9])
def test_f3_a_row_under_the_floor_is_not_published(eligible: int) -> None:
    feed = _feed([_counts([50, eligible])])
    assert feed["rows"] == [] and feed["withheld_rows"] == "some"
    assert '"<10"' not in json.dumps(feed)


def test_f3_withheld_rows_are_reported_only_as_none_some_or_a_rounded_number() -> None:
    assert [opp.withheld_value(n, T) for n in (0, 1, 9, 10, 14, 15)] == ["none", "some", "some", 10, 10, 20]
    many = [_counts([50, 3], nct=f"NCT0000{i:04d}") for i in range(12)]
    assert _feed(many)["withheld_rows"] == 10


def test_f3_only_approved_studies_and_an_empty_list_publishes_nothing() -> None:
    with pytest.raises(opp.FeedRefused, match="approved list is empty"):
        _feed([_counts()], approved=set())
    with pytest.raises(opp.FeedRefused, match="not on the steward's approved list"):
        _feed([_counts()], approved={"NCT99999999"})


def test_f3_a_cap_per_condition() -> None:
    three = [_counts(nct=f"NCT0000000{i}") for i in range(3)]
    assert len(_feed(three, per_condition_cap=3)["rows"]) == 3
    with pytest.raises(opp.FeedRefused, match="more than 2 studies"):
        _feed(three, per_condition_cap=2)
    feed = _feed(three[:2], per_condition_cap=2)
    with pytest.raises(opp.FeedRefused, match="cap"):
        opp.validate({**feed, "per_condition_cap": 1})


def test_f3_f9_a_study_not_counted_is_null_with_a_reason_code() -> None:
    feed = _feed([_counts(reason="not_compiled")])
    (r,) = feed["rows"]
    assert r["status"] == "not_counted" and r["reason"] == "not_compiled"
    assert r["eligible_now"] is None and r["new_per_month"] is None and r["enrol_12m"] is None
    with pytest.raises(opp.FeedRefused, match="reason code"):
        _feed([_counts(reason="the lake said: patient P0001 broke it")])


# -- finding 4: day-to-day differencing --------------------------------------------------------------------------------
def test_f4_the_period_has_a_floor_and_sign_refuses_under_it() -> None:
    with pytest.raises(opp.FeedRefused):
        opp.period_of(date(2026, 11, 12), 27)
    feed = _feed([_counts()])
    priv, pub = ed25519_generate()
    with pytest.raises(opp.FeedRefused, match="period days"):
        opp.sign({**feed, "period": {"start": "2026-11-12", "days": 1}}, priv, pub)
    with pytest.raises(opp.FeedRefused, match="period boundary"):
        opp.sign({**feed, "period": {"start": "2026-11-12", "days": 30}}, priv, pub)
    assert opp.period_of(PERIOD.start) == opp.period_of(PERIOD.end - (PERIOD.end - PERIOD.start) / 30) == PERIOD


def test_f4_within_a_period_the_published_values_do_not_change(tmp_path: Path) -> None:
    """Reviewer: a nightly feed with deterministic rounding flips a value on the night one patient changes."""
    priv, pub = ed25519_generate()
    first = opp.publish_once(tmp_path, _feed([_counts([900, 445])]), priv, pub)
    before = first.read_bytes()
    again = opp.publish_once(tmp_path, _feed([_counts([900, 444])]), priv, pub)  # one patient fewer the next night
    assert again == first and first.read_bytes() == before
    assert json.loads(before)["rows"][0]["eligible_now"] == 450
    nxt = opp.publish_once(tmp_path, _feed([_counts([900, 444])], period=opp.period_of(PERIOD.end)), priv, pub)
    assert nxt != first and json.loads(nxt.read_text())["rows"][0]["eligible_now"] == 440


# -- finding 5: differencing across a funnel ---------------------------------------------------------------------------
def test_f5_funnel_rule_and_its_complement() -> None:
    assert funnel_drops_publishable([1000, 702, 698, 437], T) == [False, True, False, False]
    assert funnel_drops_publishable([100, 37, 34], T) == [False, False, False]
    assert funnel_drops_publishable([100, 80, 60, 40], T) == [False, True, True, True]
    assert funnel_drops_publishable([100, 80, 78, 50, 30], T) == [False, True, False, False, True]
    assert funnel_drops_publishable([100, 95, 90], T) == [False, False, False]  # two small drops cover each other


def test_f5_differencing_37_34_cannot_recover_3() -> None:
    """In the style of T-316a: 37 then 34 (a drop of 3). Every funnel consistent with what is published leaves the
    drop open over more than one value, so the 3 is not recovered."""
    target = _row(_counts([100, 37, 34], prevalent=34, incident=0))
    assert target is not None and target["not_matched"] == []
    drops = set()
    for r1 in range(30, 60):
        for r2 in range(25, r1 + 1):
            if _row(_counts([100, r1, r2], prevalent=r2, incident=0)) == target:
                drops.add(r1 - r2)
    assert 3 in drops and len(drops) > 5


def test_f5_two_overlapping_trials_37_and_34_differ_by_a_multiple_of_the_floor() -> None:
    a = _row(_counts([100, 37], prevalent=37, incident=0, nct="NCT00000001"))
    b = _row(_counts([100, 37, 34], prevalent=34, incident=0, nct="NCT00000002"))
    assert a is not None and b is not None
    assert (a["eligible_now"] - b["eligible_now"]) % T == 0 and a["eligible_now"] - b["eligible_now"] != 3


# -- finding 6: opted-out patients were counted -------------------------------------------------------------------------
GZQO = Ruleset.load(ROOT / "rulesets" / "GZQO")


class _Lake:
    """Ten synthetic patients who pass every counted criterion at the latest month-end."""

    def __init__(self, rs: Ruleset) -> None:
        st = fc.steps(rs)
        self.applied = [s for s in st if s.applied]
        self.variants = fc.build_variants(rs, dict(rs.manifest.variants or {}), st)
        self.queries = 0

    def query(self, sql: str, params: list[Any], snapshot: str) -> pa.Table:
        pids = [f"P{i:04d}" for i in range(1, 11)]
        from matching.batches import ALL_PATIENTS_SQL

        if sql == ALL_PATIENTS_SQL:  # NEW-B-53: the snapshot's patients, asked before the funnel's batches
            return pa.table({"pid": pids})
        self.queries += 1
        cols: dict[str, list[Any]] = {"pid": pids}
        for i in range(len(self.applied)):
            cols[f"f{i}"] = [True] * 10
            cols[f"r{i}"] = [True] * 10
            cols[f"u{i}"] = [False] * 10
        for j in range(len(self.variants) + 1):
            cols[f"w{j}"] = [True] * 10
        cols["first_eligible"] = [date(2026, 3, 31)] * 10
        cols["prevalent"] = [True] * 10
        return pa.table(cols)


class _Cov:
    @classmethod
    def load(cls, *a: Any, **k: Any) -> _Cov:
        return cls()

    def patients(self, domain: str) -> set[str]:
        return set()


@pytest.fixture
def lakeless(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fc, "Coverage", _Cov)
    monkeypatch.setattr(fc, "site_basis", lambda lake, snap: (set(), set()))


def test_f6_feas_counts_leave_out_the_excluded_pseudonyms(lakeless: None) -> None:
    p = fc.FeasParams(run_date=date(2026, 11, 1), snapshot="2026-11-01", lookback_months=12, iterations=1)
    lake: Any = _Lake(GZQO)
    _, raw = fc.compute(lake, GZQO, p)
    _, less = fc.compute(lake, GZQO, fc.FeasParams(**{**p.__dict__, "exclude_pids": frozenset({"P0002"})}))
    assert raw.start_n == 10 and less.start_n == 9 and less.prevalent == 9
    assert all(v == 9 for v in less.remaining.values())


class _Compiler:
    def ctgov_search(self, req: CtgovSearchRequest) -> Any:
        return CtGov(mode="cassette").search(req)


class _Audit:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def append(self, kind: str, **kw: Any) -> None:
        self.events.append((kind, kw))


def _ctx(lake: _Lake) -> Any:
    return SimpleNamespace(
        today=lambda: date(2026, 11, 12),
        job=SimpleNamespace(job_id="j-opp", received_at=datetime(2026, 11, 12, 3, 45, tzinfo=UTC)),
        services=SimpleNamespace(compiler=_Compiler(), lake=lake),
        orch=SimpleNamespace(audit=_Audit()),
        cfg=SimpleNamespace(settings=SimpleNamespace(calibration_defaults=None)),
    )


def _build(ctx: Any, **kw: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "site_id": "tw",
        "site_label": "Taiwan",
        "country": "Taiwan",
        "conditions": ["Gout"],
        "snapshot": "2026-11-11",
        "approved": {"NCT99000001"},
        "per_condition_cap": 20,
        "secret": SECRET,
    }
    args.update(kw)
    return scen.build_feed(ctx, **args)


def test_f6_build_feed_leaves_out_an_opted_out_patient(lakeless: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ten synthetic patients meet the criteria; one opts out as of the job's receipt, so nine are counted and the
    row (now under the floor) is not published."""
    monkeypatch.setattr(scen, "_compiled", lambda ctx, s, d: (GZQO, None, d))
    asked: list[str | None] = []

    def register(url: str | None = None, as_of: str | None = None) -> frozenset[str]:
        asked.append(as_of)
        return gone

    monkeypatch.setattr(optout_mod, "opted_out", register)
    gone: frozenset[str] = frozenset()
    feed = _build(_ctx(_Lake(GZQO)))
    assert [r["eligible_now"] for r in feed["rows"]] == [10]
    gone = frozenset({"P0007"})
    feed = _build(_ctx(_Lake(GZQO)))
    assert feed["rows"] == [] and feed["withheld_rows"] == "some"
    assert asked == ["2026-11-12T03:45:00+00:00"] * 2


def test_f3_build_feed_counts_only_approved_studies(lakeless: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scen, "_compiled", lambda ctx, s, d: (GZQO, None, d))
    monkeypatch.setattr(optout_mod, "opted_out", lambda url=None, as_of=None: frozenset())
    lake = _Lake(GZQO)
    ctx = _ctx(lake)
    feed = _build(ctx)
    assert [r["nct_id"] for r in feed["rows"]] == ["NCT99000001"] and lake.queries == 1  # 3 found, 1 approved
    with pytest.raises(opp.FeedRefused, match="approved list is empty"):
        _build(ctx, approved=set())
    assert lake.queries == 1
    two = _build(_ctx(_Lake(GZQO)), approved={"NCT99000001", "NCT99000002", "NCT99000003"}, per_condition_cap=2)
    assert len(two["rows"]) == 2 and two["per_condition_cap"] == 2
    (kind, ev), *_ = ctx.orch.audit.events
    assert kind == "opportunity.feed" and ev["detail"]["published"] == 1


def test_f7_a_failed_compile_carries_a_code_never_its_message(lakeless: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """The old row copied ``StepFailed.message`` into ``note``; now nothing of it reaches the feed."""

    def boom(ctx: Any, s: Any, d: Any) -> Any:
        raise StepFailed("compiling", "SECRET-MESSAGE about P0001 from the record")

    monkeypatch.setattr(scen, "_compiled", boom)
    monkeypatch.setattr(optout_mod, "opted_out", lambda url=None, as_of=None: frozenset())
    feed = _build(_ctx(_Lake(GZQO)))
    assert feed["rows"][0]["reason"] == "not_compiled"
    text = json.dumps(feed)
    assert "SECRET" not in text and "P0001" not in text and "note" not in text


def test_registry_label_only_from_the_registry_text() -> None:
    text = "Exclusion Criteria:\n* Estimated GFR below 30 mL/min/1.73 m2.\n"
    assert scen.registry_label(["estimated  GFR below 30"], text, 2) == "estimated GFR below 30"
    assert scen.registry_label(["Patient P0001 had eGFR 12", None], text, 3) == "criterion 3"


# -- finding 7: one schema for the whole feed --------------------------------------------------------------------------
def _signed() -> tuple[dict[str, Any], bytes, bytes]:
    priv, pub = ed25519_generate()
    return opp.sign(_feed([_counts()]), priv, pub), priv, pub


def _bad_variants(feed: dict[str, Any]) -> list[dict[str, Any]]:
    row = feed["rows"][0]
    out = []
    for change in (
        {"enrol_12m": {"low": "<img src=x onerror=alert(1)>", "mid": 20, "high": 40, "pid": "P0001"}},  # reviewer ran
        {"eligible_now": 10**12},  # reviewer ran
        {"eligible_now": 437},
        {"eligible_now": 0},
        {"eligible_now": "<10"},
        {"new_per_month": 0.1},
        {"new_per_month": "12"},
        {"criteria_total": -1},
        {"criteria_applied": 99},
        {"target_enrollment": "300 <b>"},
        {"phases": ["PHASE9"]},
        {"countries": ["<script>"]},
        {"note": "free text"},
        {"title": "x" * 301},
        {"not_matched": [{"criterion": "a", "removed": 5}]},
        {"not_matched": [{"criterion": "a", "removed": 10, "pid": "P1"}]},
        {"status": "counted", "reason": "count_failed"},
        {"nct_id": "javascript:alert(1)"},
    ):
        out.append({**feed, "rows": [{**row, **change}]})
    out.append({**feed, "pid": "P0001"})
    out.append({**feed, "site_label": "Taiwan\n<script>"})
    out.append({**feed, "site_label": "x" * 81})
    out.append({**feed, "country": "Atlantis"})
    out.append({**feed, "threshold": 5})
    out.append({**feed, "withheld_rows": 3})
    out.append({k: v for k, v in feed.items() if k != "withheld_rows"})
    return out


def test_f7_the_schema_refuses_every_unchecked_field_before_signing_and_at_verify() -> None:
    signed, priv, pub = _signed()
    assert opp.schema_errors(signed) == [] and opp.verify(signed, pub)
    for bad in _bad_variants(signed):
        assert opp.schema_errors(bad), bad
        with pytest.raises(opp.FeedRefused):
            opp.sign(bad, priv, pub)
        assert not opp.verify(bad, pub)
        with pytest.raises(opp.FeedRefused):
            render([(bad, opp.UNVERIFIED)])


# -- finding 8: the dashboard ------------------------------------------------------------------------------------------
JS = (ROOT / "services/opportunity_hub/dashboard.js").read_text(encoding="utf-8")


def test_f8_the_page_script_inserts_no_feed_value_unescaped() -> None:
    """Reviewer: the band, the rate and the criteria counts went into ``innerHTML`` raw. A feed value may enter the
    markup only through ``esc(...)`` (or as a comparison)."""
    concat = r"\+\s*\(?\s*(?:r|b|x|f)\.[\w.]+(?![\w.])(?!\s*===)"
    lead = r"(?<![\w.(])(?:r|b|x|f)\.[\w.]+\s*(?:\+|\?\?)"
    assert re.findall(concat, JS) == [] and re.findall(lead, JS) == []


_DOM = """
const els = {}; const el = (id) => els[id] || (els[id] = {id, value: '', innerHTML: '', textContent: '',
  dataset: {}, addEventListener() {}});
globalThis.document = {getElementById: (id) => id === 'tb-data' ? {textContent: process.argv[2]} : el(id),
  querySelectorAll: () => [], documentElement: {}};
require(process.argv[1]);
process.stdout.write(JSON.stringify(Object.values(els).map((e) => e.innerHTML)));
"""


def test_f8_hostile_values_come_out_escaped(tmp_path: Path) -> None:
    """The same check run: the script given values the schema would refuse still writes no markup of them."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    signed, _, _ = _signed()
    evil = "<img src=x onerror=alert(1)>"
    row = {**signed["rows"][0], "site": evil, "title": evil, "new_per_month": evil, "criteria_applied": evil}
    row["enrol_12m"] = {"low": evil, "mid": evil, "high": evil}
    row["not_matched"] = [{"criterion": evil, "removed": evil}]
    data = {
        "lang": "en",
        "labels": dashboard.LABELS,
        "threshold": 10,
        "feeds": [{"site": evil, "state": evil, "period": {"start": evil, "days": evil}, "withheld": evil}],
        "rows": [row],
    }
    script = tmp_path / "dash.js"
    script.write_text(JS, encoding="utf-8")
    out = subprocess.run(
        [node, "-e", _DOM, str(script), json.dumps(data)], capture_output=True, text=True, check=True, timeout=60
    ).stdout
    html = "".join(json.loads(out))
    assert "&lt;img" in html and "<img" not in html


def test_f8_the_page_holds_only_validated_feeds_and_says_when_one_is_not_verified() -> None:
    signed, _, _ = _signed()
    page = render([(signed, opp.VERIFIED)], lang="ja")
    assert page.startswith("<!doctype html>") and "治験機会ボード" in page and NCT in page
    assert 'class="banner bad"' not in page
    shown = render([(signed, opp.UNVERIFIED)], standalone=False)
    assert "<html" not in shown and 'class="banner bad"' in shown and '"state": "unverified"' in shown
    with pytest.raises(ValueError):
        render([(signed, "trusted")])


def test_f8_allow_unverified_is_refused_outside_dev_and_test(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    signed, _, _ = _signed()
    f = tmp_path / "feed.json"
    f.write_text(json.dumps(signed), encoding="utf-8")
    reg = tmp_path / "keys.json"
    reg.write_text(json.dumps({"sites": {}}), encoding="utf-8")
    out = tmp_path / "page.html"
    argv = ["dashboard", str(f), "--register", str(reg), "--out", str(out)]
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    assert tool.main([*argv, "--allow-unverified"]) == 2 and not out.exists()
    assert tool.main(argv) == 1 and not out.exists()  # not verified: refused without the flag
    monkeypatch.setenv("TB_ENV", "TEST")
    assert tool.main([*argv, "--allow-unverified"]) == 0 and 'class="banner bad"' in out.read_text(encoding="utf-8")


# -- finding 10: the key register, the signed fingerprint and freshness ------------------------------------------------
def test_f10_status_needs_the_registered_key_and_name_and_a_current_period() -> None:
    signed, _priv, pub = _signed()
    _, other = ed25519_generate()
    reg = {"tw": {"name": "Taiwan", "key_sha256": opp.key_fingerprint(pub)}}
    today = PERIOD.start
    assert opp.status(signed, pub, reg, today) == opp.VERIFIED
    assert opp.status(signed, pub, reg, PERIOD.end) == opp.OUT_OF_DATE  # an old feed replayed
    assert opp.status(signed, pub, {}, today) == opp.UNVERIFIED  # no register entry
    assert opp.status(signed, None, reg, today) == opp.UNVERIFIED
    assert opp.status(signed, pub, {"tw": {**reg["tw"], "name": "Another hospital"}}, today) == opp.UNVERIFIED
    self_signed = opp.sign(_feed([_counts()]), *ed25519_generate())  # any key, any label: not "signed by site"
    assert opp.status(self_signed, other, reg, today) == opp.UNVERIFIED
    moved = {**signed, "key_sha256": opp.key_fingerprint(other)}
    assert not opp.verify(moved, pub) and not opp.verify(moved, other)  # the fingerprint is inside the signed bytes
    late = {**signed, "period": {"start": opp.period_of(PERIOD.end).start.isoformat(), "days": 30}}
    assert not opp.verify(late, pub)  # so is the period
    tampered = json.loads(json.dumps(signed))
    tampered["rows"][0]["eligible_now"] = 990
    assert not opp.verify(tampered, pub)


def test_f10_the_register_file(tmp_path: Path) -> None:
    p = tmp_path / "keys.json"
    p.write_text(json.dumps({"sites": {"tw": {"name": "Taiwan", "key_sha256": "a" * 64}}}), encoding="utf-8")
    assert opp.load_register(p) == {"tw": {"name": "Taiwan", "key_sha256": "a" * 64}}
    p.write_text(json.dumps({"sites": {"tw": {"name": "Taiwan", "key_sha256": "short"}}}), encoding="utf-8")
    with pytest.raises(opp.FeedRefused):
        opp.load_register(p)


# -- settings and the sample -------------------------------------------------------------------------------------------
def test_settings_and_files(tmp_path: Path) -> None:
    s = opp.settings({})
    assert (s.per_condition_cap, s.period_days) == (20, 30)
    with pytest.raises(opp.FeedRefused):
        opp.settings({"TB_OPPORTUNITY_PERIOD_DAYS": "1"})
    with pytest.raises(opp.FeedRefused):
        opp.settings({"TB_OPPORTUNITY_PER_CONDITION": "0"})
    assert opp.load_approved(tmp_path / "missing.json") == frozenset()
    (tmp_path / "a.json").write_text(json.dumps({"approved": ["NCT99000001"]}), encoding="utf-8")
    assert opp.load_approved(tmp_path / "a.json") == {"NCT99000001"}
    (tmp_path / "b.json").write_text(json.dumps({"approved": ["P0001"]}), encoding="utf-8")
    with pytest.raises(opp.FeedRefused):
        opp.load_approved(tmp_path / "b.json")
    assert opp.load_secret("") is None
    (tmp_path / "s").write_bytes(b"short")
    with pytest.raises(opp.FeedRefused):
        opp.load_secret(tmp_path / "s")


def test_sample_offline_from_the_synthetic_cassettes(tmp_path: Path) -> None:
    page = tool.sample(tmp_path / "out")
    assert page.exists()
    reg = opp.load_register(tmp_path / "out" / "site-keys.json")
    feeds = sorted((tmp_path / "out").glob("feed-*.json"))
    assert len(feeds) == len(tool.SAMPLE_SITES)
    for path in feeds:
        feed = json.loads(path.read_text(encoding="utf-8"))
        assert feed["synthetic"] is True and opp.schema_errors(feed) == []
        assert feed["key_sha256"] == reg[feed["site_id"]]["key_sha256"]
    assert "<img" not in page.read_text(encoding="utf-8")
