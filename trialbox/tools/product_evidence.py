"""Which paid runs count as evidence of the shipped product (lane G's validation reset, 2026-11-14).

The reset plan is ``docs/plan/measurements/validation-reset-2026-11-14.md``. Two things make a run's results NOT
evidence of the shipped box, and a paid launch refuses either one unless the operator says ``--not-product-evidence``
(the run then goes ahead and its plan and report say, by name, why it is not product evidence):

1. **A part that is not the product path** (:data:`NOT_PRODUCT_PARTS`). They stay in the driver because the
   rehearsal and other lanes' tests use them; they must not be paid for as validation.
2. **A serving setup that differs from the shipped compose** (:func:`serving_differences`): the VM script
   ``deploy/gcp/complete-run-vm.sh`` starts its own vLLM servers, and the shipped box
   (``deploy/docker-compose.rtxpro6000.yml``) starts them with the developer's chat template, the vLLM image by
   digest and the weights at the revisions ``models/registry.yaml`` expects. Each missing one is a difference.

Static reads of files in the tree only: nothing here calls a service, starts anything or needs the network.

    python -m tools.complete_run --launch-gate <run>/plan.json [--not-product-evidence] [--dry]
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VM_SCRIPT = ROOT / "deploy" / "gcp" / "complete-run-vm.sh"
COMPOSE = ROOT / "deploy" / "docker-compose.rtxpro6000.yml"
REGISTRY = ROOT / "models" / "registry.yaml"
RESET_PLAN = "docs/plan/measurements/validation-reset-2026-11-14.md"

# the driver parts that do not exercise the product path: tag -> why (the reset plan, section 4)
NOT_PRODUCT_PARTS: dict[str, str] = {
    "scenario-public-trec": (
        "tools.mlbench's bench prompt sent straight to the model servers: no gateway, no product judge prompt, "
        "no cascade, no two-model decision (tools/scenarios.py sc_trec)"
    ),
    "scenario-public-mimic": (
        "the in-process stub answers (tools.cascade_e2e), and the MIMIC-IV demo has no notes: no model is tested "
        "(tools/scenarios.py sc_mimic)"
    ),
}
# the shipped box's two model servers: their pinned builds in models/registry.yaml (the RTX PRO 6000 profile)
SHIPPED_BUILDS = ("gemma-4-26b-a4b-it-rtxpro6000", "qwen3.5-9b-rtxpro6000")
_IMAGE = re.compile(r"vllm/vllm-openai:[\w.-]+(?:@sha256:[0-9a-f]{64})?")
_CHAT_TEMPLATE = re.compile(r"(?<![\w-])--chat-template[= ]")


def not_product_parts(tags: Iterable[str]) -> list[str]:
    """``"<tag>: <why>"`` for each tag that is not the product path, in the order given."""
    return [f"{t}: {NOT_PRODUCT_PARTS[t]}" for t in dict.fromkeys(tags) if t in NOT_PRODUCT_PARTS]


def _code(text: str) -> str:
    """The shell text without its comment lines (a comment naming a flag does not pass it)."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def expected_revisions(registry: dict[str, Any]) -> dict[str, str]:
    """``build_id -> expected revision`` for the shipped pair (empty string when the registry has none)."""
    out = {}
    for b in registry.get("builds") or []:
        if isinstance(b, dict) and b.get("build_id") in SHIPPED_BUILDS:
            out[str(b["build_id"])] = str((b.get("expected") or {}).get("revision") or "")
    return out


def serving_differences(vm_script: str, compose: str, registry: dict[str, Any]) -> list[str]:
    """How the VM script's model serving differs from the shipped compose; empty when it does not."""
    vm, shipped = _code(vm_script), _code(compose)
    out = []
    if _CHAT_TEMPLATE.search(shipped) and not _CHAT_TEMPLATE.search(vm):
        out.append("chat template: the shipped judge starts with --chat-template (the developer's file, D-392); "
                   "the VM script passes none, so the server renders the weights folder's own template")  # fmt: skip
    ship_img = next(iter(_IMAGE.findall(shipped)), "")
    vm_img = re.search(r"^\s*VLLM=(\S+)", vm, re.M)
    if ship_img and (vm_img.group(1) if vm_img else "") != ship_img:
        out.append(f"vLLM image: shipped {ship_img}; the VM script runs "
                   f"{vm_img.group(1) if vm_img else 'an image it does not name'} (not the same digest)")  # fmt: skip
    revs = expected_revisions(registry)
    missing = [b for b in SHIPPED_BUILDS if not revs.get(b) or revs[b] not in vm]
    if missing:
        out.append("weights: the VM script does not load or check the revisions models/registry.yaml expects for "
                   + ", ".join(f"{b} ({revs.get(b) or 'none in the registry'})" for b in missing))  # fmt: skip
    return out


def tree_serving_differences(root: Path = ROOT) -> list[str]:
    """:func:`serving_differences` for the files of this tree."""
    import yaml

    vm = (root / VM_SCRIPT.relative_to(ROOT)).read_text(encoding="utf-8")
    compose = (root / COMPOSE.relative_to(ROOT)).read_text(encoding="utf-8")
    registry = yaml.safe_load((root / REGISTRY.relative_to(ROOT)).read_text(encoding="utf-8")) or {}
    return serving_differences(vm, compose, registry)


def plan_tags(plan: dict[str, Any]) -> list[str]:
    """Every part tag of a driver plan (``plan.json``: its shards' tags), in order."""
    tags = [t for s in (plan.get("plan") or {}).get("shards") or [] for t in s.get("tags") or []]
    return list(dict.fromkeys(tags + list(plan.get("only") or [])))


def launch_gate(plan_path: Path, accept: bool, dry: bool = False, root: Path = ROOT) -> int:
    """Record in ``plan.json`` whether the run can be product evidence, and say why not. Returns 0 when the launch
    may go ahead (no reason, or ``accept``), 8 when it must refuse; a dry run only says what a launch would do."""
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    reasons = [f"serving: {d}" for d in tree_serving_differences(root)]
    reasons += [f"part {r}" for r in not_product_parts(plan_tags(plan))]
    plan["product_evidence"] = not reasons
    plan["not_product_evidence"] = reasons
    if not reasons:
        print("product evidence: the serving setup is the shipped compose's and every part is the product path")
    elif dry:
        print(f"# a launch would refuse here without --not-product-evidence ({RESET_PLAN}):")
        print("\n".join(f"#   {r}" for r in reasons))
    elif accept:
        print(f"NOT product evidence (--not-product-evidence given; {RESET_PLAN}): the plan and the report say why:")
        print("\n".join(f"  {r}" for r in reasons))
    else:
        print(f"refused: this run would not be evidence of the shipped product ({RESET_PLAN}). Nothing was started.\n"
              + "\n".join(f"  {r}" for r in reasons)
              + "\nFix the serving setup or drop the parts; or launch with --not-product-evidence, and the plan and "
              "the report mark every result as not product evidence.")  # fmt: skip
        return 8
    if not dry:
        plan_path.write_text(json.dumps(plan, indent=1) + "\n", encoding="utf-8")
    return 0


def report_reasons(plan: dict[str, Any], tags: Iterable[str]) -> list[str]:
    """Why a run's results are not product evidence, for its report: what the plan recorded at launch, else (a plan
    from before the reset, or none) that the serving was not recorded as the shipped one; plus its non-product
    parts."""
    if plan.get("product_evidence") is True:
        reasons: list[str] = []
    elif plan.get("not_product_evidence"):
        reasons = [str(r) for r in plan["not_product_evidence"]]
    else:
        reasons = ["serving: not recorded as the shipped compose's (a plan from before the validation reset of "
                   "2026-11-14, or no plan)"]  # fmt: skip
    for r in not_product_parts(tags):
        if f"part {r}" not in reasons:
            reasons.append(f"part {r}")
    return reasons
