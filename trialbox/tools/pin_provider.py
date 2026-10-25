"""Pin a hosted model build to one dated provider version (spec v4 §8.4, S1-07, S1-14).

    python -m tools.pin_provider --build or-qwen3.6-35b-a3b --model qwen/qwen3.6-35b-a3b --provider DeepInfra
    python -m tools.pin_provider --build or-qwen3.6-35b-a3b --verify

A hosted build (``serving: hosted`` in ``models/registry.yaml``) has no weights to hash, so it is pinned by a
**provider descriptor**: the endpoint, the model id, the dated ``canonical_slug`` and ``created`` time OpenRouter
publishes for that id, the provider that serves it (display name and endpoint tag), the provider's quantisation and the
pin date. The build's ``sha256`` is :func:`registry.registry.provider_pin_sha` of that descriptor. The gateway then
asks OpenRouter for that provider only (no fallback) and refuses a response that reports another model or provider.

The model list and provider endpoints are public (``GET /api/v1/models``, ``GET /api/v1/models/<id>/endpoints``): no API
key is read or needed. Without ``--provider`` the cheapest endpoint that honours ``response_format``,
``structured_outputs`` and ``seed`` is chosen (input + 4 x output price; the judge prompt is input-heavy but reasoning
models are output-heavy).

The pin goes into a **site override** (default ``deploy/site/registry.site.yaml``, gitignored, read by the gateway
through ``TB_REGISTRY_OVERRIDE``), like ``tools/pin_model.py``; pins of other builds in the file are kept. The merged
registry is validated before anything is written.

``--verify`` re-reads the public model list and exits 1 when the model id now points at another dated version
(``canonical_slug`` or ``created`` changed) or the pinned provider no longer serves it; it writes nothing.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

from tools.pin_model import DEFAULT_OVERRIDE, PinError, load_override

ROOT = Path(__file__).resolve().parents[1]
OPENROUTER = "https://openrouter.ai/api/v1"
REQUIRED_PARAMS = ("response_format", "structured_outputs", "seed")


@dataclass(frozen=True)
class Offer:
    """One provider endpoint of a model, with its USD prices per token."""

    provider: str
    tag: str
    quantization: str
    usd_in: float
    usd_out: float
    params: tuple[str, ...]

    @property
    def score(self) -> float:
        return self.usd_in + 4 * self.usd_out


def _get(http: httpx.Client, url: str) -> Any:
    resp = http.get(url)
    if resp.status_code >= 400:
        raise PinError(f"GET {url}: HTTP {resp.status_code}")
    return resp.json()


def model_info(http: httpx.Client, model: str, base: str = OPENROUTER) -> dict[str, Any]:
    """The public model-list entry of ``model`` (``id``, ``canonical_slug``, ``created``, ``pricing``)."""
    for m in _get(http, f"{base}/models").get("data") or []:
        if m.get("id") == model:
            return dict(m)
    raise PinError(f"model {model!r} is not in the provider's model list")


def offers(http: httpx.Client, model: str, base: str = OPENROUTER) -> list[Offer]:
    data = _get(http, f"{base}/models/{model}/endpoints").get("data") or {}
    out = []
    for e in data.get("endpoints") or []:
        pricing = e.get("pricing") or {}
        out.append(
            Offer(
                provider=str(e.get("provider_name") or ""),
                tag=str(e.get("tag") or e.get("provider_name") or ""),
                quantization=str(e.get("quantization") or "unknown"),
                usd_in=float(pricing.get("prompt") or 0.0),
                usd_out=float(pricing.get("completion") or 0.0),
                params=tuple(str(p) for p in e.get("supported_parameters") or ()),
            )
        )
    return [o for o in out if o.provider]


def choose(candidates: list[Offer], provider: str | None = None) -> Offer:
    """The named provider (display name or tag), else the cheapest one that honours :data:`REQUIRED_PARAMS`."""
    if provider:
        for o in candidates:
            if provider in (o.provider, o.tag):
                return o
        raise PinError(f"provider {provider!r} does not serve this model; offers: {[o.tag for o in candidates]}")
    usable = [o for o in candidates if all(p in o.params for p in REQUIRED_PARAMS)]
    if not usable:
        raise PinError(f"no provider honours {REQUIRED_PARAMS}")
    return min(usable, key=lambda o: (o.score, o.tag))


def descriptor(info: dict[str, Any], offer: Offer, *, endpoint: str, now: datetime) -> dict[str, Any]:
    return {
        "endpoint": endpoint,
        "model": str(info["id"]),
        "canonical_slug": str(info.get("canonical_slug") or info["id"]),
        "created": int(info["created"]),
        "provider": offer.provider,
        "provider_tag": offer.tag,
        "quantization": offer.quantization,
        "pinned_at": now.strftime("%Y-%m-%d"),
    }


def pin(
    build_id: str,
    model: str,
    *,
    http: httpx.Client,
    provider: str | None = None,
    endpoint: str = "openrouter",
    out: Path = DEFAULT_OVERRIDE,
    base: str = OPENROUTER,
    registry_path: Path | None = None,
    now: datetime | None = None,
) -> tuple[dict[str, Any], str, Offer, Path]:
    """Write the pin of ``build_id``; returns (descriptor, sha256, chosen offer, override path)."""
    from registry.registry import DEFAULT_PATH, HOSTED, Registry, apply_override, provider_pin_sha

    reg_path = registry_path or DEFAULT_PATH
    committed = yaml.safe_load(reg_path.read_text(encoding="utf-8")) or {}
    known = {str(b.get("build_id")): b for b in committed.get("builds") or []}
    if build_id not in known:
        raise PinError(f"unknown build {build_id!r}")
    if known[build_id].get("serving") != HOSTED:
        raise PinError(f"{build_id} is not a hosted build (serving: {HOSTED}); local builds use tools/pin_model.py")
    info = model_info(http, model, base)
    offer = choose(offers(http, model, base), provider)
    desc = descriptor(info, offer, endpoint=endpoint, now=now or datetime.now(UTC))
    sha = provider_pin_sha(desc)
    doc = load_override(out)
    doc["base_version"] = committed.get("version")
    doc["builds"][build_id] = {"sha256": sha, "served": {endpoint: desc["model"]}, "provider_pin": desc}
    Registry(apply_override(committed, doc))  # validates the merged registry; raises before writing
    out.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# Site registry override (tools/pin_model.py, tools/pin_provider.py). Not committed: this site's pins only.\n"
        "# Hosted builds: re-check with `python -m tools.pin_provider --build <id> --verify`.\n"
    )
    out.write_text(header + yaml.safe_dump(doc, sort_keys=True, allow_unicode=True), encoding="utf-8")
    return desc, sha, offer, out


def verify(
    build_id: str, *, http: httpx.Client, out: Path = DEFAULT_OVERRIDE, base: str = OPENROUTER
) -> tuple[bool, str]:
    """(ok, message): the pinned descriptor still names the live dated version and a live provider endpoint."""
    from registry.registry import provider_pin_sha

    entry = (load_override(out).get("builds") or {}).get(build_id) or {}
    desc = entry.get("provider_pin")
    if not desc:
        return False, f"{build_id} has no provider pin in {out}"
    if entry.get("sha256") != provider_pin_sha(desc):
        return False, f"{build_id}: sha256 does not match its descriptor"
    info = model_info(http, str(desc["model"]), base)
    live = (str(info.get("canonical_slug") or info["id"]), int(info["created"]))
    if live != (desc["canonical_slug"], desc["created"]):
        return False, f"{build_id}: {desc['model']} now points at {live[0]} (pinned {desc['canonical_slug']})"
    tags = {o.tag for o in offers(http, str(desc["model"]), base)}
    if desc["provider_tag"] not in tags:
        return False, f"{build_id}: provider {desc['provider_tag']} no longer serves {desc['model']}"
    return (
        True,
        f"{build_id}: {desc['canonical_slug']} via {desc['provider_tag']} matches the pin {entry['sha256'][:12]}",
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", required=True, help="hosted build_id in models/registry.yaml")
    ap.add_argument("--model", default="", help="provider model id, e.g. qwen/qwen3.6-35b-a3b")
    ap.add_argument("--provider", default=None, help="provider display name or endpoint tag (default: cheapest)")
    ap.add_argument("--endpoint", default="openrouter", help="routing.yaml endpoint")
    ap.add_argument("--out", type=Path, default=DEFAULT_OVERRIDE, help="site override file")
    ap.add_argument("--verify", action="store_true", help="re-check the pin against the live model list")
    args = ap.parse_args(argv)
    with httpx.Client(timeout=30.0) as http:
        try:
            if args.verify:
                good, msg = verify(args.build, http=http, out=args.out)
                print(msg)
                return 0 if good else 1
            if not args.model:
                raise PinError("--model is required")
            desc, sha, offer, path = pin(
                args.build, args.model, http=http, provider=args.provider, endpoint=args.endpoint, out=args.out
            )
        except (PinError, ValueError, httpx.HTTPError) as exc:
            print(f"pin_provider: {exc}", file=sys.stderr)
            return 2
    print(
        f"pinned {args.build}: {desc['canonical_slug']} via {desc['provider_tag']} ({desc['quantization']}, "
        f"${offer.usd_in * 1e6:.3f}/${offer.usd_out * 1e6:.3f} per M in/out) sha256 {sha} -> {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
