"""Trial-opportunity feed tools (D-467).

    python -m tools.opportunity_feed keygen --out DIR
    python -m tools.opportunity_feed sign FEED.json --key site.key --pub site.pub --out-dir OUTBOX
    python -m tools.opportunity_feed verify SIGNED.json --pub site.pub --register site-keys.json
    python -m tools.opportunity_feed dashboard SIGNED.json=site.pub ... --register site-keys.json --out PAGE.html
        [--lang ja] [--fragment] [--allow-unverified]   (the last only with TB_ENV=DEV or TEST)
    python -m tools.opportunity_feed sample --out-dir DIR

``keygen`` writes the site's Ed25519 key pair and its band secret (both stay on the site) and prints the line for the
hub's site key register. ``sign`` publishes once per period: a feed already published for the period stays unchanged.
``sample`` builds the demo page with no network and no lake: the studies are the synthetic registry records of the
compiler's cassettes and every patient count is synthetic, seeded by NCT id and site, so the page says so. The site's
real feed comes from :func:`orchestrator.scenarios.opportunity.build_feed`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opportunity_hub.dashboard import render
from tb_common import opportunity as opp
from tb_common.config import environment_name
from tb_common.crypto import ed25519_generate

SAMPLE_CONDITIONS = ["Gout", "Rheumatoid Arthritis"]
SAMPLE_SITES: tuple[dict[str, str], ...] = (
    {"site_id": "jp-demo", "site_label": "Japan head hospital (synthetic)", "country": "Japan"},
    {"site_id": "tw-demo", "site_label": "Taiwan medical center (synthetic)", "country": "Taiwan"},
)


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def synthetic_counts(study: Any, condition: str, site_id: str) -> opp.StudyCounts:
    """Seeded synthetic counts for one registry study (no lake): a pool and a funnel over its registry criteria."""
    from orchestrator.scenarios.opportunity import registry_label

    rng = random.Random(int(hashlib.sha256(f"{study.nct_id}|{site_id}".encode()).hexdigest()[:12], 16))
    bullets = [ln.strip(" *-\t") for ln in study.eligibility_text.splitlines() if ln.strip().startswith(("*", "-"))]
    crit = [b for b in bullets if len(b) > 8][:6]
    remaining = rng.randint(15, 2400)
    steps = [(registry_label([crit[0] if crit else None], study.eligibility_text, 1), remaining)]
    for i, label in enumerate(crit[1:], start=2):
        remaining = int(remaining * rng.uniform(0.55, 0.99))
        steps.append((registry_label([label], study.eligibility_text, i), remaining))
    return opp.StudyCounts(
        nct_id=study.nct_id,
        title=study.title,
        condition=condition,
        phases=tuple(study.phases or ()),
        sponsor=study.sponsor,
        countries=tuple(study.countries or ()),
        last_update=str(study.last_update),
        target_enrollment=study.enrollment,
        criteria_total=len(bullets),
        criteria_applied=len(steps),
        steps=tuple(steps),
        prevalent=int(remaining * rng.uniform(0.5, 0.9)),
        incident_12m=int(remaining * rng.uniform(0.0, 0.5)),
    )


def _simulator(reach: float = 0.6, accept: float = 0.35) -> opp.Simulator:
    from orchestrator.scenarios.feas_compute import simulate

    def run(prevalent: int, monthly: float, seed: int) -> dict[str, float]:
        out = simulate(
            prevalent=prevalent,
            monthly_rate=monthly,
            reach=reach,
            accept=accept,
            capacity=None,
            months=12,
            iterations=500,
            seed=seed,
        )
        return {k: float(out[k]) for k in ("low", "mid", "high")}

    return run


def sample(out_dir: Path) -> Path:
    from criteria_compiler.ctgov import CtGov
    from tb_contracts import CtgovSearchRequest

    reg = CtGov(mode="cassette")
    studies = {c: reg.search(CtgovSearchRequest(condition=c)).studies for c in SAMPLE_CONDITIONS}
    now = datetime.now(UTC)
    period = opp.period_of(now.date())
    register: dict[str, dict[str, str]] = {}
    pubs: dict[str, bytes] = {}
    feeds: list[dict[str, Any]] = []
    for site in SAMPLE_SITES:
        priv, pub = ed25519_generate()  # throwaway keys: the sample is not any site's feed
        counts = [synthetic_counts(s, c, site["site_id"]) for c in SAMPLE_CONDITIONS for s in studies[c]]
        feed = opp.build(
            site_id=site["site_id"],
            site_label=site["site_label"],
            country=site["country"],
            period=period,
            snapshot=now.date().isoformat(),
            registry_source=["synthetic"],
            conditions=SAMPLE_CONDITIONS,
            counts=counts,
            approved={c.nct_id for c in counts},
            per_condition_cap=opp.FeedSettings().per_condition_cap,
            secret=secrets.token_bytes(32),
            simulate=_simulator(),
            synthetic=True,
            now=now,
        )
        path = opp.publish_once(out_dir, feed, priv, pub)
        feeds.append(json.loads(path.read_text(encoding="utf-8")))
        pubs[site["site_id"]] = pub
        register[site["site_id"]] = {"name": site["site_label"], "key_sha256": opp.key_fingerprint(pub)}
    _write(out_dir / "site-keys.json", {"sites": register})
    shown = [(f, opp.status(f, pubs[f["site_id"]], register, now.date())) for f in feeds]
    page = out_dir / "trial-opportunity-board.html"
    page.write_text(render(shown, standalone=False), encoding="utf-8")
    (out_dir / "trial-opportunity-board.standalone.html").write_text(render(shown), encoding="utf-8")
    return page


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="opportunity_feed", description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keygen")
    k.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("sign")
    s.add_argument("feed", type=Path)
    s.add_argument("--key", type=Path, required=True)
    s.add_argument("--pub", type=Path, required=True)
    s.add_argument("--out-dir", type=Path, required=True)
    v = sub.add_parser("verify")
    v.add_argument("feed", type=Path)
    v.add_argument("--pub", type=Path, required=True)
    v.add_argument("--register", type=Path, required=True)
    d = sub.add_parser("dashboard")
    d.add_argument("feeds", nargs="+", help="FEED.json=PUB.pem (a feed without a key is not verified)")
    d.add_argument("--register", type=Path, required=True)
    d.add_argument("--out", type=Path, required=True)
    d.add_argument("--lang", default="en", choices=["en", "ja", "zh-TW"])
    d.add_argument("--fragment", action="store_true")
    d.add_argument("--allow-unverified", action="store_true", help="DEV or TEST only; the page says so plainly")
    m = sub.add_parser("sample")
    m.add_argument("--out-dir", type=Path, required=True)
    a = ap.parse_args(argv)

    if a.cmd == "keygen":
        priv, pub = ed25519_generate()
        a.out.mkdir(parents=True, exist_ok=True)
        for name, data in (("site.key", priv), ("band.secret", secrets.token_hex(32).encode())):
            (a.out / name).write_bytes(data)
            (a.out / name).chmod(0o600)
        (a.out / "site.pub").write_bytes(pub)
        print(f"wrote site.key, band.secret (both stay on the site) and site.pub in {a.out}")
        print(
            f'register entry: "<site_id>": {{"name": "<registered name>", "key_sha256": "{opp.key_fingerprint(pub)}"}}'
        )
    elif a.cmd == "sign":
        feed = json.loads(a.feed.read_text(encoding="utf-8"))
        print(f"published {opp.publish_once(a.out_dir, feed, a.key.read_bytes(), a.pub.read_bytes())}")
    elif a.cmd == "verify":
        feed = json.loads(a.feed.read_text(encoding="utf-8"))
        st = opp.status(feed, a.pub.read_bytes(), opp.load_register(a.register), datetime.now(UTC).date())
        print(st)
        return 0 if st == opp.VERIFIED else 1
    elif a.cmd == "dashboard":
        env = environment_name(os.environ)
        if a.allow_unverified and env not in ("DEV", "TEST"):
            print(f"--allow-unverified is refused with TB_ENV={env} (DEV or TEST only)")
            return 2
        register = opp.load_register(a.register)
        today = datetime.now(UTC).date()
        feeds: list[tuple[dict[str, Any], str]] = []
        for spec in a.feeds:
            path, _, pub = spec.partition("=")
            feed = json.loads(Path(path).read_text(encoding="utf-8"))
            errs = opp.schema_errors(feed)
            if errs:
                print(f"{path}: not a feed; refused ({'; '.join(errs[:3])})")
                return 1
            st = opp.status(feed, Path(pub).read_bytes() if pub else None, register, today)
            if st == opp.UNVERIFIED and not a.allow_unverified:
                print(f"{path}: not verified against the site key register; refused")
                return 1
            feeds.append((feed, st))
        a.out.write_text(render(feeds, lang=a.lang, standalone=not a.fragment), encoding="utf-8")
        print(f"wrote {a.out}")
    elif a.cmd == "sample":
        print(f"wrote {sample(a.out_dir)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
