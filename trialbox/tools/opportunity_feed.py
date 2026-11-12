"""Trial-opportunity feed tools (D-449).

    python -m tools.opportunity_feed keygen --out DIR
    python -m tools.opportunity_feed sign FEED.json --key site.key --pub site.pub --out SIGNED.json
    python -m tools.opportunity_feed verify SIGNED.json --pub site.pub
    python -m tools.opportunity_feed dashboard SIGNED.json[=site.pub] ... --out PAGE.html [--lang ja] [--fragment]
    python -m tools.opportunity_feed sample --out-dir DIR [--offline FILE.json]

``sample`` builds the demo page: the studies are the real recruiting ClinicalTrials.gov records of today (API v2, two
sites' therapeutic areas and countries) and every patient count is synthetic, seeded by NCT id, so the page says so.
It never reads a lake. The site's real feed comes from :func:`orchestrator.scenarios.opportunity.build_feed`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from opportunity_hub.dashboard import render
from tb_common import opportunity as opp
from tb_common.crypto import ed25519_generate

CTGOV = "https://clinicaltrials.gov/api/v2/studies"
SAMPLE_SITES: tuple[dict[str, Any], ...] = (
    {
        "site_id": "jp-demo",
        "site_label": "Japan head hospital (synthetic)",
        "country": "Japan",
        "conditions": ["Alzheimer Disease", "Rheumatoid Arthritis"],
        "pool": 500_000,
    },
    {
        "site_id": "tw-demo",
        "site_label": "Taiwan medical center (synthetic)",
        "country": "Taiwan",
        "conditions": ["Alzheimer Disease", "Rheumatoid Arthritis"],
        "pool": 500_000,
    },
)


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch_recruiting(condition: str, country: str, limit: int = 12) -> list[dict[str, Any]]:
    params: dict[str, str | int] = {
        "query.cond": condition,
        "query.locn": country,
        "filter.overallStatus": "RECRUITING|NOT_YET_RECRUITING",
        "query.term": "AREA[StudyType]INTERVENTIONAL",
        "pageSize": limit,
        "sort": "LastUpdatePostDate:desc",
    }
    r = httpx.get(CTGOV, params=params, timeout=30)
    r.raise_for_status()
    return list(r.json().get("studies") or [])


_GENERIC = (
    "prior treatment with an investigational drug",
    "significant renal or hepatic impairment",
    "active malignancy within 5 years",
    "pregnancy or breastfeeding",
)
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*(.+?)\s*$")


def _criteria(text: str) -> list[str]:
    """The exclusion bullets of an eligibility text (the inclusion ones when there is no exclusion block)."""
    low = text.lower()
    cut = low.find("exclusion criteria")
    part = text[cut:] if cut >= 0 else text
    out = []
    for line in part.splitlines():
        m = _BULLET.match(line)
        if m and len(m.group(1)) > 8:
            out.append(m.group(1)[:160])
    return out


def synthetic_sim(study: dict[str, Any], site_id: str) -> dict[str, Any]:
    """A trial-simulation row with seeded synthetic counts for one real registry study."""
    ps = study.get("protocolSection") or {}
    ident = ps.get("identificationModule") or {}
    status = ps.get("statusModule") or {}
    design = ps.get("designModule") or {}
    nct = str(ident.get("nctId"))
    rng = random.Random(int(hashlib.sha256(f"{nct}|{site_id}".encode()).hexdigest()[:12], 16))
    crit = _criteria(str((ps.get("eligibilityModule") or {}).get("eligibilityCriteria") or "")) or list(_GENERIC)
    total = max(len(crit) + 3, 4)
    applied_n = min(total, 2 + rng.randint(1, max(1, min(6, len(crit) + 1))))
    pool = rng.randint(120, 2400)
    steps = [{"criterion_id": "C0", "label": "condition, age and sex", "applied": True, "remaining": pool}]
    remaining = pool
    for i, label in enumerate(crit[: applied_n - 1], start=1):
        remaining = int(remaining * rng.uniform(0.55, 0.97))
        steps.append({"criterion_id": f"C{i}", "label": label, "applied": True, "remaining": remaining})
    eligible = remaining if rng.random() > 0.12 else rng.randint(1, 9)
    monthly = round(eligible * rng.uniform(0.02, 0.06), 1)
    mid = round(min(eligible, eligible * rng.uniform(0.08, 0.2) + monthly * 4), 0)
    return {
        "nct_id": nct,
        "title": ident.get("briefTitle") or ident.get("officialTitle") or nct,
        "phases": list(design.get("phases") or []),
        "countries": [],
        "sponsor": ((ps.get("sponsorCollaboratorsModule") or {}).get("leadSponsor") or {}).get("name"),
        "last_update": (status.get("lastUpdatePostDateStruct") or {}).get("date") or "",
        "target_enrollment": (design.get("enrollmentInfo") or {}).get("count"),
        "criteria_total": total,
        "criteria_applied": len(steps),
        "eligible_now": eligible,
        "new_per_month": monthly,
        "enrol_12m_low": round(mid * 0.6),
        "enrol_12m_mid": mid,
        "enrol_12m_high": round(mid * 1.5),
        "steps": steps,
        "note": "synthetic counts for the sample page",
    }


def sample(out_dir: Path, offline: Path | None = None) -> Path:
    cache: dict[str, list[dict[str, Any]]] = {}
    if offline:
        cache = json.loads(offline.read_text(encoding="utf-8"))
    signed: list[tuple[dict[str, Any], bool]] = []
    now = datetime.now(UTC)
    for site in SAMPLE_SITES:
        priv, pub = ed25519_generate()
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for cond in site["conditions"]:
            key = f"{cond}|{site['country']}"
            if key not in cache:
                cache[key] = fetch_recruiting(str(cond), str(site["country"]))
            for st in cache[key]:
                sim = synthetic_sim(st, str(site["site_id"]))
                if sim["nct_id"] in seen:
                    continue
                seen.add(sim["nct_id"])
                rows.append(opp.row_from_sim(sim, str(cond)))
        feed = opp.build(
            site_id=str(site["site_id"]),
            site_label=str(site["site_label"]),
            country=str(site["country"]),
            snapshot=now.date().isoformat(),
            registry_source="live",
            registry_sha256=hashlib.sha256(json.dumps(cache, sort_keys=True).encode()).hexdigest(),
            conditions=list(site["conditions"]),
            rows=rows,
            synthetic=True,
            now=now,
        )
        s = opp.sign(feed, priv, pub)
        _write(out_dir / f"feed-{site['site_id']}.json", s)
        signed.append((s, opp.verify(s, pub)))
    _write(out_dir / "ctgov-cache.json", cache)
    page = out_dir / "trial-opportunity-board.html"
    page.write_text(render(signed, standalone=False), encoding="utf-8")
    (out_dir / "trial-opportunity-board.standalone.html").write_text(render(signed), encoding="utf-8")
    return page


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="opportunity_feed", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keygen")
    k.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("sign")
    s.add_argument("feed", type=Path)
    s.add_argument("--key", type=Path, required=True)
    s.add_argument("--pub", type=Path, required=True)
    s.add_argument("--out", type=Path, required=True)
    v = sub.add_parser("verify")
    v.add_argument("feed", type=Path)
    v.add_argument("--pub", type=Path, required=True)
    d = sub.add_parser("dashboard")
    d.add_argument("feeds", nargs="+", help="FEED.json=PUB.pem (a feed without a key is shown as not verified)")
    d.add_argument("--out", type=Path, required=True)
    d.add_argument("--lang", default="en", choices=["en", "ja", "zh-TW"])
    d.add_argument("--fragment", action="store_true")
    d.add_argument("--allow-unverified", action="store_true")
    m = sub.add_parser("sample")
    m.add_argument("--out-dir", type=Path, required=True)
    m.add_argument("--offline", type=Path, help="a ctgov-cache.json from an earlier sample (no network)")
    a = ap.parse_args(argv)

    if a.cmd == "keygen":
        priv, pub = ed25519_generate()
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "site.key").write_bytes(priv)
        (a.out / "site.key").chmod(0o600)
        (a.out / "site.pub").write_bytes(pub)
        print(f"wrote {a.out / 'site.key'} and {a.out / 'site.pub'}")
    elif a.cmd == "sign":
        feed = json.loads(a.feed.read_text(encoding="utf-8"))
        _write(a.out, opp.sign(feed, a.key.read_bytes(), a.pub.read_bytes()))
        print(f"signed {a.out}")
    elif a.cmd == "verify":
        ok = opp.verify(json.loads(a.feed.read_text(encoding="utf-8")), a.pub.read_bytes())
        print("verified" if ok else "NOT verified")
        return 0 if ok else 1
    elif a.cmd == "dashboard":
        feeds: list[tuple[dict[str, Any], bool]] = []
        for spec in a.feeds:
            path, _, pub = spec.partition("=")
            feed = json.loads(Path(path).read_text(encoding="utf-8"))
            ok = bool(pub) and opp.verify(feed, Path(pub).read_bytes())
            if not ok and not a.allow_unverified:
                print(f"{path}: signature not verified; refused (pass --allow-unverified to show it marked)")
                return 1
            feeds.append((feed, ok))
        a.out.write_text(render(feeds, lang=a.lang, standalone=not a.fragment), encoding="utf-8")
        print(f"wrote {a.out}")
    elif a.cmd == "sample":
        print(f"wrote {sample(a.out_dir, a.offline)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
