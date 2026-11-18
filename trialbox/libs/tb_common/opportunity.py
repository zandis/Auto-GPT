"""The trial-opportunity feed (D-467): what one site may tell sponsors and CROs about recruiting trials.

The owner's rule: only aggregates ever leave a site; no patient-level data, no identifiers, no free text from a
record. The site counts, in its own lake and for itself, how many of its patients the registry criteria of each
recruiting ClinicalTrials.gov study leave (:class:`StudyCounts`, exact, never published). :func:`build` reduces them to
the feed by these rules, and :func:`validate` (one schema for every key, type, range and multiple-of-t rule) refuses
anything else, before signing and again at the hub before a page shows it:

1. **Approved studies only.** Only studies on the steward's approved list are counted and published; an empty list
   publishes nothing (the list is edited on the steward page of T-742; the gate is here).
2. **Under the floor is not published.** A study with fewer than ``threshold`` eligible patients is left out of the
   feed (no ``<10`` row); the feed says only how many rows were left out, as "none", "some" or a rounded number at or
   above the floor. A study that could not be counted is a row with ``null`` counts and a fixed reason code.
3. **Rounded counts.** Every published count is a multiple of the threshold (``round_count``).
4. **Rate from rounded counts.** New eligible patients per month is published only from the rounded yearly count (the
   rule of FEAS ``lam_pub``: an exact mean of small counts reveals their sum), and not at all under the floor.
5. **Band from rounded inputs.** The 12-month enrolment band is simulated from the rounded inputs only, with a seed
   from a site secret that never leaves the site (so it cannot be replayed), and published rounded to the threshold;
   P10 and P90 are dropped when the band is narrower than the rounding.
6. **Funnel.** A criterion's drop is published only when the drop and its remainder are at or above the floor;
   otherwise that step and one neighbouring step are withheld (``smallcell.funnel_drops_publishable``).
7. **Cadence.** The feed is published once per period (default monthly; :data:`MIN_PERIOD_DAYS` is the floor below
   which :func:`sign` refuses), counted as of the period's first day, and within a period the published values do not
   change (:func:`publish_once`).
8. **A cap per condition**, declared as a setting with its reason by the caller, recorded in the feed and checked.

The site signs the canonical JSON with its Ed25519 key (:func:`sign`); ``key_sha256`` and the period are inside the
signed bytes. The hub reads a site key register (site id to key fingerprint and registered name, :func:`load_register`)
and shows a feed as verified only when its key is registered for its ``site_id`` and its label is the registered name
(:func:`status`); a feed past its period is shown as out of date.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from tb_common.crypto import ed25519_sign, ed25519_verify, sha256_bytes
from tb_common.smallcell import funnel_drops_publishable, round_count

SCHEMA = "tb-opportunity-feed/2"
DEFAULT_THRESHOLD = 10
MIN_THRESHOLD = 10  # the owner's floor for this feed (D-467); a site may only raise it
TOP_NOT_MATCHED = 3
#: the ruling's floor for the publication period: a shorter one makes day-to-day differencing possible again
MIN_PERIOD_DAYS = 28
DEFAULT_PERIOD_DAYS = 30
PERIOD_EPOCH = date(2026, 1, 1)  # periods are counted from here, so every site's periods line up
MIN_SECRET_BYTES = 16
PHASES = ("EARLY_PHASE1", "PHASE1", "PHASE2", "PHASE3", "PHASE4", "NA")
COUNTRIES: frozenset[str] = frozenset(
    json.loads((Path(__file__).with_name("opportunity_countries.json")).read_text(encoding="utf-8"))["countries"]
)
#: why a study is a row without counts (never a message: a message could carry text from the record)
REASONS = ("not_compiled", "no_countable_criteria", "count_failed")
REGISTRY_SOURCES = ("api", "cassette", "refdata", "synthetic")  # CtgovSearchResult.source, or a sample
WITHHELD_WORDS = ("none", "some")
MAX_COUNT = 10_000_000  # larger than any hospital; a guard against a nonsense count, not a policy
MAX_ROWS = 2000
MAX_CONDITIONS = 50
MAX_CAP = 200
LEN = {"title": 300, "sponsor": 200, "criterion": 200, "condition": 120, "site_label": 80}
_NCT = re.compile(r"^NCT[0-9]{8}$")
_SITE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_CTRL = re.compile(r"[\x00-\x1f\x7f]")


class FeedRefused(ValueError):
    """The feed would publish something the site must not publish, or is not a feed; nothing is signed or shown."""


@dataclass(frozen=True)
class StudyCounts:
    """One study's exact counts inside the site (never published as such) and its public registry facts.

    ``steps``: (label, patients remaining) for each counted criterion in order; the label is the criterion's own words
    from the public registry text (the caller checks that). ``prevalent``: eligible at the latest month-end;
    ``incident_12m``: first eligible in the last 12 months. ``reason``: a code of :data:`REASONS` when the study could
    not be counted (then the counts are ignored)."""

    nct_id: str
    title: str
    condition: str
    phases: tuple[str, ...] = ()
    sponsor: str | None = None
    countries: tuple[str, ...] = ()
    last_update: str = ""
    target_enrollment: int | None = None
    criteria_total: int = 0
    criteria_applied: int = 0
    steps: tuple[tuple[str, int], ...] = ()
    prevalent: int = 0
    incident_12m: int = 0
    reason: str | None = None


@dataclass(frozen=True)
class Period:
    start: date
    days: int

    @property
    def end(self) -> date:
        return self.start + timedelta(days=self.days)


#: (prevalent, monthly rate, seed) -> {"low", "mid", "high"}; the scenario passes FEAS's simulation with its rates
Simulator = Callable[[int, float, int], Mapping[str, float]]


def period_of(day: date, days: int = DEFAULT_PERIOD_DAYS) -> Period:
    """The publication period that holds ``day`` (periods of ``days`` counted from :data:`PERIOD_EPOCH`)."""
    if days < MIN_PERIOD_DAYS:
        raise FeedRefused(f"publication period of {days} days is under the floor of {MIN_PERIOD_DAYS}")
    k = (day - PERIOD_EPOCH).days // days
    return Period(PERIOD_EPOCH + timedelta(days=k * days), days)


def _text(value: Any, limit: int) -> str:
    return _CTRL.sub(" ", str(value or "")).strip()[:limit]


def _seed(secret: bytes, nct_id: str, period: Period) -> int:
    mac = hmac.new(secret, f"{nct_id}|{period.start.isoformat()}|{period.days}".encode(), hashlib.sha256)
    return int(mac.hexdigest()[:16], 16)


def _round_to(x: float, t: int) -> int:
    return int(t * int((max(x, 0.0) + t / 2) // t))


def rate(incident_12m: int, t: int) -> float | None:
    """New eligible patients per month, from the rounded yearly count only; ``None`` under the floor."""
    if incident_12m < t:
        return None
    pub = round_count(incident_12m, t)
    assert isinstance(pub, int)
    return round(pub / 12, 1)


def band(
    c: StudyCounts, t: int, period: Period, secret: bytes | None, simulate: Simulator | None
) -> dict[str, int | None] | None:
    """The 12-month enrolment band from the rounded inputs only, seeded by the site secret, rounded to ``t``."""
    if secret is None or simulate is None:
        return None
    prev = round_count(c.prevalent, t)
    yearly = round_count(c.incident_12m, t) if c.incident_12m >= t else 0
    assert isinstance(yearly, int)
    sim = simulate(prev if isinstance(prev, int) else 0, yearly / 12, _seed(secret, c.nct_id, period))
    lo, mid, hi = float(sim["low"]), float(sim["mid"]), float(sim["high"])
    out: dict[str, int | None] = {"low": _round_to(lo, t), "mid": _round_to(mid, t), "high": _round_to(hi, t)}
    if hi - lo < t:  # narrower than the rounding: P10 and P90 would say more than the rounding allows
        out["low"] = out["high"] = None
    return out


def not_matched(steps: Iterable[tuple[str, int]], t: int, top: int = TOP_NOT_MATCHED) -> list[dict[str, Any]]:
    """The criteria whose records did not match for the most patients, by the funnel rule (rule 6), rounded."""
    steps = list(steps)
    remaining = [n for _, n in steps]
    ok = funnel_drops_publishable(remaining, t)
    out = []
    for i in range(1, len(steps)):
        if ok[i]:
            pub = round_count(remaining[i - 1] - remaining[i], t)
            out.append({"criterion": _text(steps[i][0], LEN["criterion"]) or f"criterion {i + 1}", "removed": pub})
    out.sort(key=lambda d: (-int(d["removed"]), str(d["criterion"])))  # published values only: no exact order leaks
    return out[:top]


def _meta(c: StudyCounts) -> dict[str, Any]:
    te = c.target_enrollment
    return {
        "nct_id": c.nct_id,
        "title": _text(c.title, LEN["title"]),
        "condition": c.condition,
        "phases": sorted({p for p in c.phases if p in PHASES}),
        "sponsor": _text(c.sponsor, LEN["sponsor"]) or None,
        "countries": sorted({x for x in c.countries if x in COUNTRIES}),
        "last_update": str(c.last_update),
        "target_enrollment": te if _is_int(te) and 0 <= int(te or 0) <= MAX_COUNT else None,
        "criteria_total": int(c.criteria_total),
        "criteria_applied": int(c.criteria_applied),
    }


def row(
    c: StudyCounts, t: int, period: Period, secret: bytes | None, simulate: Simulator | None
) -> dict[str, Any] | None:
    """The published row of one study, or ``None`` when it must not be published (under the floor)."""
    if c.reason is not None:
        if c.reason not in REASONS:
            raise FeedRefused(f"{c.nct_id}: unknown reason code {c.reason!r}")
        return {
            **_meta(c),
            "status": "not_counted",
            "reason": c.reason,
            "eligible_now": None,
            "new_per_month": None,
            "enrol_12m": None,
            "not_matched": [],
        }
    if not c.steps:
        raise FeedRefused(f"{c.nct_id}: counted without a counted criterion")
    eligible = c.steps[-1][1]
    if eligible < t:
        return None
    return {
        **_meta(c),
        "status": "counted",
        "reason": None,
        "eligible_now": round_count(eligible, t),
        "new_per_month": rate(c.incident_12m, t),
        "enrol_12m": band(c, t, period, secret, simulate),
        "not_matched": not_matched(c.steps, t),
    }


def withheld_value(n: int, t: int) -> int | str:
    """How many rows were left out: "none", "some" (1 to t-1) or the number rounded, at or above the floor."""
    if n <= 0:
        return "none"
    if n < t:
        return "some"
    return round_count(n, t)


def build(
    *,
    site_id: str,
    site_label: str,
    country: str,
    period: Period,
    snapshot: str,
    registry_source: Iterable[str],
    conditions: list[str],
    counts: Iterable[StudyCounts],
    approved: Iterable[str],
    per_condition_cap: int,
    threshold: int = DEFAULT_THRESHOLD,
    secret: bytes | None = None,
    simulate: Simulator | None = None,
    synthetic: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The feed from the site's exact counts. Refuses (nothing is published) without approved studies, with a study
    that is not approved, over the cap of a condition, with a short secret, or with what :func:`validate` refuses."""
    ok = frozenset(approved)
    if not ok:
        raise FeedRefused("the steward's approved list is empty: nothing is published")
    if secret is not None and len(secret) < MIN_SECRET_BYTES:
        raise FeedRefused(f"the band secret must be at least {MIN_SECRET_BYTES} bytes")
    rows: list[dict[str, Any]] = []
    per: dict[str, int] = {}
    withheld = 0
    seen: set[str] = set()
    for c in counts:
        if c.nct_id not in ok:
            raise FeedRefused(f"{c.nct_id}: not on the steward's approved list")
        if c.nct_id in seen:
            raise FeedRefused(f"{c.nct_id}: counted twice")
        seen.add(c.nct_id)
        per[c.condition] = per.get(c.condition, 0) + 1
        if per[c.condition] > per_condition_cap:
            raise FeedRefused(f"{c.condition}: more than {per_condition_cap} studies")
        r = row(c, threshold, period, secret, simulate)
        if r is None:
            withheld += 1
        else:
            rows.append(r)
    feed = {
        "schema": SCHEMA,
        "site_id": site_id,
        "site_label": site_label,
        "country": country,
        "period": {"start": period.start.isoformat(), "days": period.days},
        "generated_at": (now or datetime.now(UTC)).astimezone(UTC).isoformat(timespec="seconds"),
        "snapshot": snapshot,
        "registry_source": sorted(set(registry_source)),
        "conditions": list(conditions),
        "threshold": threshold,
        "per_condition_cap": per_condition_cap,
        "synthetic": synthetic,
        "withheld_rows": withheld_value(withheld, threshold),
        "rows": rows,
    }
    validate(feed)
    return feed


# ------------------------------------------------------------------------------------------------- the schema
@dataclass
class _Check:
    errors: list[str] = field(default_factory=list)

    def need(self, cond: bool, msg: str) -> bool:
        if not cond:
            self.errors.append(msg)
        return cond


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _count(v: Any, t: int) -> bool:
    """A published patient count: a multiple of ``t``, at or above the floor, bounded."""
    return _is_int(v) and t <= v <= MAX_COUNT and v % t == 0


def _band_value(v: Any, t: int) -> bool:
    return _is_int(v) and 0 <= v <= MAX_COUNT and v % t == 0


def _rate_ok(v: Any, t: int) -> bool:
    """A rate that comes from a rounded yearly count at or above the floor (rule 4)."""
    if not isinstance(v, (int, float)) or isinstance(v, bool) or not 0 <= v <= MAX_COUNT:
        return False
    k = round(v * 12 / t)
    return k >= 1 and round(k * t / 12, 1) == v


def _str(v: Any, limit: int, *, empty: bool = False) -> bool:
    return isinstance(v, str) and len(v) <= limit and (empty or bool(v.strip())) and not _CTRL.search(v)


def _day(v: Any) -> bool:
    if not isinstance(v, str) or not _DATE.match(v):
        return False
    try:
        date.fromisoformat(v)
    except ValueError:
        return False
    return True


FEED_KEYS = frozenset(
    {
        "schema",
        "site_id",
        "site_label",
        "country",
        "period",
        "generated_at",
        "snapshot",
        "registry_source",
        "conditions",
        "threshold",
        "per_condition_cap",
        "synthetic",
        "withheld_rows",
        "rows",
        "key_sha256",
        "signature",
    }
)
ROW_KEYS = frozenset(
    {
        "nct_id",
        "title",
        "condition",
        "phases",
        "sponsor",
        "countries",
        "last_update",
        "target_enrollment",
        "criteria_total",
        "criteria_applied",
        "status",
        "reason",
        "eligible_now",
        "new_per_month",
        "enrol_12m",
        "not_matched",
    }
)


def schema_errors(feed: Any) -> list[str]:
    """Every way ``feed`` is not a D-467 feed (empty when it is one). Exactly these keys, nothing nested beyond them."""
    c = _Check()
    if not c.need(isinstance(feed, Mapping), "the feed is not an object"):
        return c.errors
    keys = set(feed)
    c.need(not keys - FEED_KEYS, f"feed keys not allowed: {sorted(keys - FEED_KEYS)}")
    missing = FEED_KEYS - {"key_sha256", "signature"} - keys
    c.need(not missing, f"feed keys missing: {sorted(missing)}")
    if c.errors:
        return c.errors
    c.need(feed["schema"] == SCHEMA, f"unknown schema {feed['schema']!r}")
    t = feed["threshold"]
    if not c.need(
        _is_int(t) and MIN_THRESHOLD <= t <= 1000, f"threshold must be an integer of at least {MIN_THRESHOLD}"
    ):
        return c.errors
    c.need(isinstance(feed["site_id"], str) and bool(_SITE_ID.match(feed["site_id"])), "site_id")
    c.need(_str(feed["site_label"], LEN["site_label"]), "site_label")
    c.need(feed["country"] in COUNTRIES, "country not in the enumeration")
    per = feed["period"]
    if c.need(isinstance(per, Mapping) and set(per) == {"start", "days"}, "period"):
        days = per["days"]
        days_ok = c.need(
            _is_int(days) and MIN_PERIOD_DAYS <= days <= 366, f"period days must be {MIN_PERIOD_DAYS} to 366"
        )
        if days_ok and c.need(_day(per["start"]), "period start"):
            start = date.fromisoformat(per["start"])
            c.need((start - PERIOD_EPOCH).days % days == 0, "period start is not a period boundary")
    ga = feed["generated_at"]
    try:
        c.need(isinstance(ga, str) and len(ga) <= 40 and datetime.fromisoformat(ga).tzinfo is not None, "generated_at")
    except ValueError:
        c.errors.append("generated_at")
    c.need(_day(feed["snapshot"]), "snapshot")
    src = feed["registry_source"]
    c.need(
        isinstance(src, list) and len(src) <= len(REGISTRY_SOURCES) and all(s in REGISTRY_SOURCES for s in src),
        "registry_source",
    )
    conds = feed["conditions"]
    cond_ok = c.need(
        isinstance(conds, list)
        and len(conds) <= MAX_CONDITIONS
        and all(_str(x, LEN["condition"]) for x in conds)
        and len(set(conds)) == len(conds),
        "conditions",
    )
    cap = feed["per_condition_cap"]
    cap_ok = c.need(_is_int(cap) and 1 <= cap <= MAX_CAP, "per_condition_cap")
    c.need(isinstance(feed["synthetic"], bool), "synthetic")
    w = feed["withheld_rows"]
    c.need(w in WITHHELD_WORDS or _count(w, t), "withheld_rows must be none, some or a rounded number at the floor")
    if "key_sha256" in feed:
        c.need(isinstance(feed["key_sha256"], str) and bool(_HEX64.match(feed["key_sha256"])), "key_sha256")
    if "signature" in feed:
        sig = feed["signature"]
        c.need(
            isinstance(sig, Mapping)
            and set(sig) == {"alg", "body_sha256", "sig"}
            and sig.get("alg") == "ed25519"
            and isinstance(sig.get("body_sha256"), str)
            and bool(_HEX64.match(sig["body_sha256"]))
            and isinstance(sig.get("sig"), str)
            and len(sig["sig"]) <= 200,
            "signature",
        )
    rows = feed["rows"]
    if not c.need(isinstance(rows, list) and len(rows) <= MAX_ROWS, "rows"):
        return c.errors
    per_cond: dict[str, int] = {}
    nct_seen: set[str] = set()
    for i, r in enumerate(rows):
        c.errors.extend(f"rows[{i}]: {e}" for e in _row_errors(r, t, conds if cond_ok else []))
        if isinstance(r, Mapping):
            n = str(r.get("nct_id"))
            c.need(n not in nct_seen, f"rows[{i}]: {n} twice")
            nct_seen.add(n)
            k = str(r.get("condition"))
            per_cond[k] = per_cond.get(k, 0) + 1
    if cap_ok:
        over = sorted(k for k, n in per_cond.items() if n > cap)
        c.need(not over, f"more rows than the cap for {over}")
    return c.errors


def _row_errors(r: Any, t: int, conditions: list[str]) -> list[str]:
    c = _Check()
    if not c.need(isinstance(r, Mapping), "not an object"):
        return c.errors
    keys = set(r)
    if not c.need(keys == ROW_KEYS, f"row keys not allowed or missing: {sorted(keys ^ ROW_KEYS)}"):
        return c.errors
    c.need(isinstance(r["nct_id"], str) and bool(_NCT.match(r["nct_id"])), "nct_id")
    c.need(_str(r["title"], LEN["title"], empty=True), "title")
    c.need(r["condition"] in conditions, "condition not one of the feed's conditions")
    ph = r["phases"]
    c.need(isinstance(ph, list) and all(p in PHASES for p in ph) and len(set(ph)) == len(ph), "phases")
    c.need(r["sponsor"] is None or _str(r["sponsor"], LEN["sponsor"]), "sponsor")
    co = r["countries"]
    c.need(
        isinstance(co, list) and all(x in COUNTRIES for x in co) and len(set(co)) == len(co),
        "countries",
    )
    c.need(_day(r["last_update"]), "last_update")
    te = r["target_enrollment"]
    c.need(te is None or (_is_int(te) and 0 <= te <= MAX_COUNT), "target_enrollment")
    tot, app = r["criteria_total"], r["criteria_applied"]
    c.need(_is_int(tot) and _is_int(app) and 0 <= app <= tot <= 1000, "criteria_total / criteria_applied")
    nm = r["not_matched"]
    if r["status"] == "not_counted":
        c.need(r["reason"] in REASONS, "reason code")
        c.need(
            r["eligible_now"] is None and r["new_per_month"] is None and r["enrol_12m"] is None and nm == [],
            "a row not counted carries no counts",
        )
        return c.errors
    if not c.need(r["status"] == "counted" and r["reason"] is None, "status"):
        return c.errors
    c.need(_count(r["eligible_now"], t), f"eligible_now must be a multiple of {t} at or above it")
    c.need(r["new_per_month"] is None or _rate_ok(r["new_per_month"], t), "new_per_month not from a rounded count")
    b = r["enrol_12m"]
    if b is not None and c.need(isinstance(b, Mapping) and set(b) == {"low", "mid", "high"}, "enrol_12m keys"):
        lo, mid, hi = b["low"], b["mid"], b["high"]
        c.need(_band_value(mid, t), "enrol_12m mid")
        if lo is None or hi is None:
            c.need(lo is None and hi is None, "enrol_12m: low and high together")
        else:
            c.need(
                _band_value(lo, t) and _band_value(hi, t) and _is_int(mid) and lo <= mid <= hi and hi - lo >= t,
                "enrol_12m low/high",
            )
    if c.need(isinstance(nm, list) and len(nm) <= TOP_NOT_MATCHED, "not_matched"):
        for x in nm:
            c.need(
                isinstance(x, Mapping)
                and set(x) == {"criterion", "removed"}
                and _str(x["criterion"], LEN["criterion"])
                and _count(x["removed"], t),
                "not_matched item",
            )
    return c.errors


def validate(feed: Any) -> None:
    errs = schema_errors(feed)
    if errs:
        raise FeedRefused("; ".join(errs[:10]))


# ---------------------------------------------------------------------------------------------- signature
def canonical(feed: Mapping[str, Any]) -> bytes:
    body = {k: v for k, v in feed.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def key_fingerprint(public_pem: bytes) -> str:
    return sha256_bytes(public_pem)


def sign(feed: Mapping[str, Any], private_pem: bytes, public_pem: bytes) -> dict[str, Any]:
    """The signed feed: the key's fingerprint goes inside the signed bytes with the period (whose floor
    :func:`validate` checks: a period under :data:`MIN_PERIOD_DAYS` is refused here)."""
    body = {k: v for k, v in feed.items() if k != "signature"}
    body["key_sha256"] = key_fingerprint(public_pem)
    validate(body)
    data = canonical(body)
    return {
        **body,
        "signature": {
            "alg": "ed25519",
            "body_sha256": sha256_bytes(data),
            "sig": base64.b64encode(ed25519_sign(private_pem, data)).decode("ascii"),
        },
    }


def verify(feed: Mapping[str, Any], public_pem: bytes) -> bool:
    """The signature holds for ``public_pem`` and the signed fingerprint is that key's. Whose key it is, is the
    register's question (:func:`status`)."""
    if schema_errors(feed) or "signature" not in feed or "key_sha256" not in feed:
        return False
    if feed["key_sha256"] != key_fingerprint(public_pem):
        return False
    try:
        raw = base64.b64decode(str(feed["signature"]["sig"]), validate=True)
        return bool(ed25519_verify(public_pem, canonical(feed), raw))
    except (ValueError, binascii.Error):
        return False


# ---------------------------------------------------------------------------------------------- the hub's view
VERIFIED, UNVERIFIED, OUT_OF_DATE = "verified", "unverified", "out_of_date"


def load_register(path: Path, site_id: re.Pattern[str] = _SITE_ID) -> dict[str, dict[str, str]]:
    """The hub's site key register: ``{"sites": {site_id: {"name": registered name, "key_sha256": fingerprint}}}``
    (the full hub store and accounts are T-743's). The alliance root reads its register of member sites in the same
    form (``tb_common.alliance``, D-1320), with the site ids of ``settings.yaml`` (``site_id``)."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    sites = raw.get("sites") if isinstance(raw, Mapping) else None
    if not isinstance(sites, Mapping):
        raise FeedRefused(f"{path}: not a site key register")
    out: dict[str, dict[str, str]] = {}
    for sid, ent in sites.items():
        if not (
            isinstance(ent, Mapping)
            and site_id.match(str(sid))
            and _HEX64.match(str(ent.get("key_sha256", "")))
            and _str(ent.get("name"), LEN["site_label"])
        ):
            raise FeedRefused(f"{path}: entry {sid!r} needs a name and a key_sha256")
        out[str(sid)] = {"name": str(ent["name"]), "key_sha256": str(ent["key_sha256"])}
    return out


def status(
    feed: Mapping[str, Any],
    public_pem: bytes | None,
    register: Mapping[str, Mapping[str, str]],
    today: date,
) -> str:
    """``verified`` when the schema holds, the key is the one registered for the feed's ``site_id``, the label is the
    registered name and the signature holds; ``out_of_date`` when all that holds but the period is over; else
    ``unverified``."""
    ent = register.get(str(feed.get("site_id")))
    if public_pem is None or ent is None:
        return UNVERIFIED
    if key_fingerprint(public_pem) != ent["key_sha256"] or feed.get("site_label") != ent["name"]:
        return UNVERIFIED
    if not verify(feed, public_pem):
        return UNVERIFIED
    per = feed["period"]
    end = date.fromisoformat(per["start"]) + timedelta(days=int(per["days"]))
    return OUT_OF_DATE if today >= end else VERIFIED


# ---------------------------------------------------------------------------------------------- publication
def publish_once(out_dir: Path, feed: Mapping[str, Any], private_pem: bytes, public_pem: bytes) -> Path:
    """Sign and write the feed for its period, unless this site already published one for the period: then the one
    already published stays, unchanged (rule 7: within a period the published values do not change)."""
    validate(feed)
    per = feed["period"]
    path = out_dir / f"feed-{feed['site_id']}-{per['start']}-{per['days']}d.json"
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        if not verify(old, public_pem):
            raise FeedRefused(f"{path}: the feed already published for this period does not verify")
        return path
    out_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sign(feed, private_pem, public_pem), ensure_ascii=False, indent=2) + "\n", "utf-8")
    return path


# ---------------------------------------------------------------------------------------------- settings
@dataclass(frozen=True)
class FeedSettings:
    """The site's declared settings for the feed (``tb_common.config.DECLARED``, each with its reason)."""

    per_condition_cap: int = 20
    period_days: int = DEFAULT_PERIOD_DAYS
    approved_file: str = ""
    secret_file: str = ""


def settings(environ: Mapping[str, str]) -> FeedSettings:
    cap = int(environ.get("TB_OPPORTUNITY_PER_CONDITION") or 20)
    days = int(environ.get("TB_OPPORTUNITY_PERIOD_DAYS") or DEFAULT_PERIOD_DAYS)
    if not 1 <= cap <= MAX_CAP:
        raise FeedRefused(f"TB_OPPORTUNITY_PER_CONDITION must be 1 to {MAX_CAP}")
    if days < MIN_PERIOD_DAYS:
        raise FeedRefused(f"TB_OPPORTUNITY_PERIOD_DAYS must be at least {MIN_PERIOD_DAYS}")
    return FeedSettings(
        per_condition_cap=cap,
        period_days=days,
        approved_file=environ.get("TB_OPPORTUNITY_APPROVED_FILE") or "",
        secret_file=environ.get("TB_OPPORTUNITY_SECRET_FILE") or "",
    )


def load_approved(path: str | Path) -> frozenset[str]:
    """The steward's approved list (``{"approved": ["NCT…", …]}``, written by the page of T-742). No file, no list:
    an empty set, so nothing is published."""
    if not path or not Path(path).exists():
        return frozenset()
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    ids = raw.get("approved") if isinstance(raw, Mapping) else None
    if not isinstance(ids, list) or not all(isinstance(x, str) and _NCT.match(x) for x in ids):
        raise FeedRefused(f"{path}: the approved list must be {{'approved': [NCT ids]}}")
    return frozenset(ids)


def load_secret(path: str | Path) -> bytes | None:
    """The site's band secret (never leaves the site, never in a feed); ``None`` without one (no band published)."""
    if not path or not Path(path).exists():
        return None
    data = Path(path).read_bytes().strip()
    if len(data) < MIN_SECRET_BYTES:
        raise FeedRefused(f"{path}: the band secret must be at least {MIN_SECRET_BYTES} bytes")
    return data
