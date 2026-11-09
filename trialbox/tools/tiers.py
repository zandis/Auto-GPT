"""Install tiers from measured serving records only (TB-PLAN-04 step 8, D-138).

``deploy/install.sh --tier small|medium|large`` installs one of the three boxes we sell (D-124), and only when that
box's GPU profile has a serving-configuration record taken on its own, uncapped card (the record rule of
``tools/serving_config.py measured``, D-112). There is no override: a tier is a promise that the box was measured.
A trial boot of an unmeasured card stays possible with ``--gpu <profile>`` and ``TB_ACCEPT_UNMEASURED_GPU=1``, which
is not a tier install.

    ========  ==============  =====================================  ===================================
    tier      ``--gpu``       box                                    serving
    ========  ==============  =====================================  ===================================
    small     ``rtx5090``     one RTX 5090 (32 GB), small sites      the pair with the sleep swap, 8k
    medium    ``gb10``        DGX Spark (GB10, 128 GB unified)       the pair resident, 16k
    large     ``rtxpro6000``  RTX PRO 6000 (96 GB), head hospitals   the pair resident, 32k
    ========  ==============  =====================================  ===================================

The record is the site's (``deploy/site/serving_config.<gpu>.json``) or the vendor's, shipped with the kit
(``deploy/measured/serving_config.<gpu>.json``); the site's wins, as in ``install.sh``. The card in the machine must
be the tier's card (``deploy/gpu_profile.sh``). Standard library only: ``install.sh`` runs it with the host's
``python3`` before anything is loaded or started.

    python3 tools/tiers.py check --tier large [--deploy deploy] [--arch x86_64 --card "NVIDIA RTX PRO 6000 ..."]
    # stdout: "<gpu> <record>"; exit 0 when the tier may be installed, 3 with the reason on stderr when not
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from pathlib import Path

try:  # as ``tools.tiers`` (tests) or as a script (``python3 tools/tiers.py`` from install.sh)
    from tools import serving_config
except ImportError:  # pragma: no cover - script mode
    import serving_config  # type: ignore[no-redef,import-not-found]

ROOT = Path(__file__).resolve().parents[1]
TIERS: dict[str, str] = {"small": "rtx5090", "medium": "gb10", "large": "rtxpro6000"}
BOX: dict[str, str] = {
    "rtx5090": "one RTX 5090 (32 GB)",
    "gb10": "a DGX Spark (GB10)",
    "rtxpro6000": "one RTX PRO 6000 (96 GB)",
}
REFUSED = 3


class Refused(Exception):
    """The tier may not be installed on this machine; the message says what is missing and how to get it."""


def record_paths(deploy: Path, gpu: str) -> list[Path]:
    """Where a measurement of ``gpu`` may be, in the order install.sh reads them (the site's first)."""
    return [deploy / "site" / f"serving_config.{gpu}.json", deploy / "measured" / f"serving_config.{gpu}.json"]


def card_name() -> str:
    """The first card nvidia-smi reports, or "" when there is no driver or no card."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip().splitlines()[0].strip() if out.returncode == 0 and out.stdout.strip() else ""


def profile_of(arch: str, card: str, deploy: Path) -> str:
    """The GPU profile ``deploy/gpu_profile.sh`` gives this machine (one table for install.sh and this check)."""
    out = subprocess.run(
        ["sh", str(deploy / "gpu_profile.sh"), arch, card], check=True, capture_output=True, text=True, timeout=30
    )
    return out.stdout.strip()


def how_to_measure(tier: str, gpu: str) -> str:
    return (
        f"To get a record: boot this box once as a trial with `TB_ACCEPT_UNMEASURED_GPU=1 deploy/install.sh <bundle> "
        f"--gpu {gpu}` (not a tier install), let both model servers start, then run `python3 tools/serving_config.py "
        f"capture --container judge=trialbox-llm-service-1 --container verifier=trialbox-llm-verifier-1 "
        f"--models-dir deploy/models --out deploy/site/serving_config.{gpu}.json` on the box (RUNBOOK section 1, "
        "'Tiers'); or ask Aimedics for the vendor record of this card (deploy/measured/). "
        f"Then re-run with --tier {tier}."
    )


def resolve(
    tier: str, deploy: Path | None = None, arch: str | None = None, card: str | None = None
) -> tuple[str, Path]:
    """``(gpu profile, record)`` for a tier that may be installed here; :class:`Refused` otherwise."""
    deploy = deploy or ROOT / "deploy"
    if tier not in TIERS:
        raise Refused(f"unknown tier {tier!r}: use small, medium or large")
    gpu = TIERS[tier]
    arch = arch if arch is not None else platform.machine()
    card = card if card is not None else card_name()
    if not card:
        raise Refused(
            f"tier {tier} needs {BOX[gpu]}, and this machine shows no NVIDIA card (nvidia-smi found none). Install the "
            "driver and the container toolkit (docs/HARDENING.md), or install without a tier (--mode stub: "
            "structured criteria only)."
        )
    here = profile_of(arch, card, deploy)
    if here != gpu:
        mine = next((t for t, g in TIERS.items() if g == here), None)
        hint = f"this card is tier {mine}" if mine else "this card is not one of the three measured boxes"
        raise Refused(f"tier {tier} is {BOX[gpu]}, but this machine's card is {card!r} ({here} profile): {hint}.")
    for path in record_paths(deploy, gpu):
        if not path.is_file():
            continue
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise Refused(f"{path} is not a readable serving record ({exc}). {how_to_measure(tier, gpu)}") from exc
        why = serving_config.measured_for(rec, gpu)
        if why:
            raise Refused(
                f"tier {tier}: {path} is not a measurement of the {gpu} profile on its own card: {'; '.join(why)}. "
                + how_to_measure(tier, gpu)
            )
        return gpu, path
    where = " or ".join(str(p) for p in record_paths(deploy, gpu))
    raise Refused(
        f"tier {tier} ({BOX[gpu]}) has no measured serving record: neither {where} exists, so TrialBox has never been "
        f"measured on this card and will not install it as a tier. {how_to_measure(tier, gpu)}"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="may this tier be installed on this machine")
    c.add_argument("--tier", required=True)
    c.add_argument("--deploy", type=Path, default=ROOT / "deploy")
    c.add_argument("--arch", default=None, help="default: this machine")
    c.add_argument("--card", default=None, help="default: nvidia-smi's first card")
    sub.add_parser("table", help="print the tier table")
    a = ap.parse_args(argv)
    if a.cmd == "table":
        for t, g in TIERS.items():
            print(f"{t}\t{g}\t{BOX[g]}")
        return 0
    try:
        gpu, rec = resolve(a.tier, a.deploy, a.arch, a.card)
    except Refused as exc:
        print(f"install: refused: {exc}", file=sys.stderr)
        return REFUSED
    print(f"{gpu} {rec}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
