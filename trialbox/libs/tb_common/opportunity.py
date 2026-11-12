"""The trial-opportunity feed (D-467): what one site may tell sponsors and CROs about recruiting trials.

One feed per site and night. It lists actively recruiting ClinicalTrials.gov studies in the site's therapeutic areas
and, for each, how many of the site's patients the study's registry criteria leave (an automatic, unreviewed compile
counted in the lake, as COHORT's trial simulation does). Only aggregates leave the site:

* every count is published with controlled rounding to the feed threshold (``round_count``: 1..t-1 become ``"<t"``,
  larger counts the nearest multiple of t), so neighbouring counts never expose a small cell;
* the rates and the 12-month enrolment band are dropped when the eligible count is a small cell;
* "top exclusions" are the drops between consecutive counted criteria, rounded the same way;
* :func:`guard` refuses any key outside the allow-list and any count that is not rounded, so a later change that
  adds a patient-level field fails before the feed is signed.

The site signs the canonical JSON with its Ed25519 key (:func:`sign`); the hub verifies it (:func:`verify`) before the
dashboard shows it. A signed feed is the provenance record: the sponsor can re-ask the same question and compare.
"""

from __future__ import annotations

import base64
import itertools
import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from tb_common.crypto import ed25519_sign, ed25519_verify, sha256_bytes
from tb_common.smallcell import round_count

SCHEMA = "tb-opportunity-feed/1"
DEFAULT_THRESHOLD = 10
TOP_EXCLUSIONS = 3

FEED_KEYS = frozenset(
    {
        "schema",
        "site_id",
        "site_label",
        "country",
        "generated_at",
        "snapshot",
        "registry_source",
        "registry_sha256",
        "conditions",
        "threshold",
        "synthetic",
        "rows",
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
        "eligible_now",
        "new_per_month",
        "enrol_12m",
        "top_exclusions",
        "note",
    }
)
EXCLUSION_KEYS = frozenset({"criterion", "removed"})


class FeedRefused(ValueError):
    """The feed would publish something the site must not publish; nothing is signed."""


def _round(value: int | str | None, t: int) -> int | str | None:
    if value is None:
        return None
    if isinstance(value, str):  # already suppressed on site at a lower threshold
        return f"<{t}"
    return round_count(int(value), t)


def _num(value: int | str | None) -> int | None:
    return value if isinstance(value, int) else None


def exclusions(steps: Iterable[Mapping[str, Any]], t: int, top: int = TOP_EXCLUSIONS) -> list[dict[str, Any]]:
    """The criteria that remove the most patients, from the counted steps in order.

    The first counted criterion defines the pool (its drop from the whole lake is not a trial-specific exclusion and
    is not known here); each later criterion's drop is the previous remaining count minus its own. A drop next to a
    suppressed count is unknown and skipped. Drops are rounded like any published count, and a drop that rounds to
    zero is not listed."""
    applied = [s for s in steps if s.get("applied")]
    drops: list[tuple[int, str]] = []
    for prev, cur in itertools.pairwise(applied):
        a, b = _num(prev.get("remaining")), _num(cur.get("remaining"))
        if a is None or b is None or a <= b:
            continue
        drops.append((a - b, str(cur.get("label") or cur.get("criterion_id") or "")))
    drops.sort(key=lambda d: (-d[0], d[1]))
    out = []
    for n, label in drops[:top]:
        r = round_count(n, t)
        if r == 0:
            continue
        out.append({"criterion": label[:200], "removed": r})
    return out


def row_from_sim(sim: Mapping[str, Any], condition: str, t: int = DEFAULT_THRESHOLD) -> dict[str, Any]:
    """One feed row from a COHORT trial-simulation row (``TrialSimRow`` as a dict)."""
    eligible = _round(sim.get("eligible_now", 0), t)
    small = isinstance(eligible, str) or eligible == 0
    band = None
    if not small and sim.get("enrol_12m_mid") is not None:
        band = {k: round(float(sim[f"enrol_12m_{k}"])) for k in ("low", "mid", "high")}
    npm = sim.get("new_per_month")
    return {
        "nct_id": str(sim["nct_id"]),
        "title": str(sim.get("title") or "")[:300],
        "condition": condition,
        "phases": list(sim.get("phases") or []),
        "sponsor": sim.get("sponsor"),
        "countries": list(sim.get("countries") or []),
        "last_update": str(sim.get("last_update") or ""),
        "target_enrollment": sim.get("target_enrollment"),
        "criteria_total": int(sim.get("criteria_total") or 0),
        "criteria_applied": int(sim.get("criteria_applied") or 0),
        "eligible_now": eligible,
        "new_per_month": None if small or npm is None else round(float(npm), 1),
        "enrol_12m": band,
        "top_exclusions": [] if small else exclusions(sim.get("steps") or [], t),
        "note": str(sim.get("note") or "")[:300],
    }


def build(
    *,
    site_id: str,
    site_label: str,
    country: str,
    snapshot: str,
    registry_source: str,
    registry_sha256: str | None,
    conditions: list[str],
    rows: list[dict[str, Any]],
    threshold: int = DEFAULT_THRESHOLD,
    synthetic: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    feed = {
        "schema": SCHEMA,
        "site_id": site_id,
        "site_label": site_label,
        "country": country,
        "generated_at": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
        "snapshot": snapshot,
        "registry_source": registry_source,
        "registry_sha256": registry_sha256,
        "conditions": conditions,
        "threshold": threshold,
        "synthetic": synthetic,
        "rows": rows,
    }
    guard(feed)
    return feed


def _published_count(v: Any, t: int) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return v >= 0 and v % t == 0
    return isinstance(v, str) and v == f"<{t}"


def guard(feed: Mapping[str, Any]) -> None:
    """Refuse a feed that holds anything but the allowed aggregate fields, or an unrounded count."""
    extra = set(feed) - FEED_KEYS
    if extra:
        raise FeedRefused(f"feed keys not allowed: {sorted(extra)}")
    if feed.get("schema") != SCHEMA:
        raise FeedRefused(f"unknown schema {feed.get('schema')!r}")
    t = feed.get("threshold")
    if not isinstance(t, int) or t < 5:
        raise FeedRefused("threshold must be an integer of at least 5")
    for row in feed.get("rows") or []:
        extra = set(row) - ROW_KEYS
        if extra:
            raise FeedRefused(f"{row.get('nct_id')}: row keys not allowed: {sorted(extra)}")
        if not _published_count(row.get("eligible_now"), t):
            raise FeedRefused(f"{row.get('nct_id')}: eligible count is not rounded to {t}")
        for ex in row.get("top_exclusions") or []:
            if set(ex) - EXCLUSION_KEYS or not _published_count(ex.get("removed"), t):
                raise FeedRefused(f"{row.get('nct_id')}: exclusion row not allowed or not rounded")
        if isinstance(row.get("eligible_now"), str) and (row.get("new_per_month") or row.get("enrol_12m")):
            raise FeedRefused(f"{row.get('nct_id')}: rates published next to a small cell")


def canonical(feed: Mapping[str, Any]) -> bytes:
    body = {k: v for k, v in feed.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def sign(feed: dict[str, Any], private_pem: bytes, public_pem: bytes) -> dict[str, Any]:
    guard(feed)
    data = canonical(feed)
    return {
        **feed,
        "signature": {
            "alg": "ed25519",
            "key_sha256": sha256_bytes(public_pem)[:16],
            "body_sha256": sha256_bytes(data),
            "sig": base64.b64encode(ed25519_sign(private_pem, data)).decode("ascii"),
        },
    }


def verify(feed: Mapping[str, Any], public_pem: bytes) -> bool:
    sig = feed.get("signature")
    if not isinstance(sig, Mapping) or sig.get("alg") != "ed25519":
        return False
    try:
        guard(feed)
    except FeedRefused:
        return False
    return bool(ed25519_verify(public_pem, canonical(feed), base64.b64decode(str(sig.get("sig", "")))))
