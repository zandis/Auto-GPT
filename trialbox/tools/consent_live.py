"""Run the consent explainer (``orchestrator.scenarios.consent``) on one consent form against real models.

Development tool, D0 only: the consent form must be synthetic or public. It calls an OpenAI-compatible endpoint
directly (default OpenRouter, key in ``OPENROUTER_API_KEY``): the draft model writes and translates, the verifier
model checks and back-translates, exactly as the CONSENT job does on the box. It writes the explainer record, the
review sheet and the DRAFT patient pages to ``--out``; ``--site`` also writes the record the public site renders
(``site/data/consent_<study>.json``)::

    OPENROUTER_API_KEY=... .venv/bin/python -m tools.consent_live tests/fixtures/consent/GZQO_ICF_v2.md --site
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "libs", ROOT / "services"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from orchestrator.reports import consent_html  # noqa: E402
from orchestrator.scenarios import consent  # noqa: E402
from tb_common.crypto import sha256_bytes  # noqa: E402
from tb_common.llm import LlmClient  # noqa: E402

OPENROUTER = "https://openrouter.ai/api/v1"


def prices(base: str) -> dict[str, tuple[float, float]]:
    """USD per token (prompt, completion) from the endpoint's model list, for the cost line; empty if unavailable."""
    import httpx

    try:
        rows = httpx.get(f"{base}/models", timeout=30).json()["data"]
        return {r["id"]: (float(r["pricing"]["prompt"]), float(r["pricing"]["completion"])) for r in rows}
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        return {}


def client(base: str, model: str, key: str) -> LlmClient:
    c = LlmClient(base, model, timeout=300.0)
    if key:
        c.http.headers["Authorization"] = f"Bearer {key}"
    return c


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    ap.add_argument("icf", type=Path, help="consent form (.md or .txt; synthetic or public only)")
    ap.add_argument("--study", default="GZQO")
    ap.add_argument("--langs", default="en,ja,zh-TW")
    ap.add_argument("--base-url", default=OPENROUTER)
    ap.add_argument("--model", default="openai/gpt-oss-120b", help="draft and translation model")
    ap.add_argument("--verifier", default="google/gemma-4-26b-a4b-it", help="second model; '' for none")
    ap.add_argument("--out", type=Path, default=ROOT / ".cache" / "consent_live")
    ap.add_argument("--site", action="store_true", help="also write site/data/consent_<study>.json")
    args = ap.parse_args(argv)
    key = os.environ.get("OPENROUTER_API_KEY", "") if args.base_url == OPENROUTER else ""
    if args.base_url == OPENROUTER and not key:
        print("consent_live: set OPENROUTER_API_KEY", file=sys.stderr)
        return 2
    data = args.icf.read_bytes()
    paras = consent.paragraphs_from_text(data.decode("utf-8-sig"))
    source = consent.detect_language(" ".join(p["text"] for p in paras))
    langs = consent.parse_langs(args.langs)
    if source not in langs:
        langs = [source, *langs]
    m = consent.Models(
        client(args.base_url, args.model, key), client(args.base_url, args.verifier, key) if args.verifier else None
    )
    t0 = time.perf_counter()
    mask = consent.ContactMask(r"^\d{8}$")
    masked = [{**p, "text": mask.mask(p["text"]), "heading": mask.mask(p["heading"])} for p in paras]
    body = mask.unmask(consent.draft(m, args.study, masked, source, langs, "live"))
    rec = {
        "schema": consent.SCHEMA,
        "study": args.study,
        "job_id": "live",
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "site": "DEMO-A",
        "requested_by": "consent_live",
        "icf": {"filename": args.icf.name, "sha256": sha256_bytes(data), "language": source, "paragraphs": len(paras)},
        "source_language": source,
        "models": {"draft": args.model, "verifier": args.verifier or None},
        **body,
        "release": None,
    }
    rec["counts"] = consent.counts(rec)
    seconds = round(time.perf_counter() - t0, 1)
    p_in, p_out = prices(args.base_url).get(args.model, (0.0, 0.0))
    cost = m.tokens_in * p_in + m.tokens_out * p_out  # both models priced as the draft model: an estimate
    rec["run"] = {"seconds": seconds, "calls": m.calls, "tokens_in": m.tokens_in, "tokens_out": m.tokens_out}
    args.out.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(rec, ensure_ascii=False, indent=1, sort_keys=True)
    (args.out / f"consent_{args.study}.json").write_text(blob, encoding="utf-8")
    (args.out / f"consent_{args.study}_review.html").write_bytes(consent_html.review(rec))
    for lang in rec["languages"]:
        page = consent_html.patient(rec, lang, consent.released_view(rec, lang, [], []), release=None)
        (args.out / f"consent_{args.study}_{lang}_DRAFT.html").write_bytes(page)
    if args.site:
        (ROOT / "site" / "data" / f"consent_{args.study.lower()}.json").write_text(blob + "\n", encoding="utf-8")
    print(json.dumps({**rec["counts"], **rec["run"], "approx_usd": round(cost, 4), "issues": rec["issues"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
