"""GPU sizing estimate for a TrialBox site (clinical review 2026-11, section 7). Arithmetic, not measurement.

    python -m tools.gpu_sizing                      # the table for every listed hardware option
    python -m tools.gpu_sizing --hardware spark     # one option
    python -m tools.gpu_sizing --json               # machine-readable
    python -m tools.gpu_sizing --model gpt-oss-120b-mxfp4 --context 32768 --hardware rtx-pro-6000

What it adds up, per model placed on a device: the published weight size, the KV cache for the chosen context
(2 x layers x KV heads x head size x 2 bytes, sliding-window layers credited at their window), a serving-engine
allowance (CUDA graphs, activations) and, on a unified-memory machine, the rest of the stack (HAPI FHIR, two
Postgres, DuckDB spill, services). Throughput is memory bandwidth divided by the active bytes read per token, times
an efficiency factor. Every figure marked "assumed" below comes from the model family, not the exact checkpoint:
re-run after measuring on the device (RUNBOOK §8 measures the Spark). Feasibility, NAV and COHORT need no GPU at all;
only protocol extraction and note criteria (SCREEN, CASE) use one.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass

GIB = 1024**3


@dataclass(frozen=True)
class Model:
    id: str
    role: str  # judge | verifier | embedder | guard
    weights_gb: float  # published checkpoint size on disk
    active_params_b: float  # parameters read per token (MoE: active experts + attention + embeddings)
    bytes_per_param: float  # of the quantisation
    layers: int
    kv_heads: int
    head_dim: int
    sliding_fraction: float = 0.0  # share of layers with a sliding window
    window: int = 0  # that window, tokens
    licence: str = ""
    origin: str = ""
    assumed: str = ""  # what is taken from the family, not the checkpoint

    def kv_gb(self, context: int, sequences: int = 1) -> float:
        per_token = 2 * self.kv_heads * self.head_dim * 2  # K and V, bf16
        full = self.layers * (1 - self.sliding_fraction) * per_token * context
        sliding = self.layers * self.sliding_fraction * per_token * min(context, self.window or context)
        return (full + sliding) * sequences / GIB

    def tokens_per_s(self, bandwidth_gbs: float, efficiency: float = 0.35) -> float:
        active_bytes = self.active_params_b * 1e9 * self.bytes_per_param
        return bandwidth_gbs * 1e9 * efficiency / active_bytes


@dataclass(frozen=True)
class Hardware:
    id: str
    name: str
    memory_gb: float
    bandwidth_gbs: float
    unified: bool  # the models share memory with the rest of the stack
    devices: int = 1
    note: str = ""


# weights: published release sizes; configs: layer count, KV heads, head size from the model configuration where known
MODELS: dict[str, Model] = {
    m.id: m
    for m in (
        Model(
            "gpt-oss-120b-mxfp4",
            "judge",
            63.0,
            5.1,
            0.56,  # MXFP4 experts (4.25 bit) with bf16 attention and embeddings
            36,
            8,
            64,
            sliding_fraction=0.5,
            window=128,
            licence="Apache-2.0",
            origin="US",
        ),
        Model(
            "gemma-4-26b-a4b-fp8",
            "verifier",
            27.0,
            4.0,
            1.0,
            48,
            8,
            256,
            sliding_fraction=0.8,
            window=1024,
            licence="Gemma",
            origin="US",
            assumed="layer count, KV heads, head size and the 5:1 local:global pattern are taken from Gemma 3 27B",
        ),
        Model(
            "gemma-4-26b-a4b-q4",
            "verifier",
            15.0,
            4.0,
            0.56,
            48,
            8,
            256,
            sliding_fraction=0.8,
            window=1024,
            licence="Gemma",
            origin="US",
            assumed="as gemma-4-26b-a4b-fp8",
        ),
        Model(
            "qwen3.5-35b-a3b-q4",
            "judge",
            20.0,
            3.3,
            0.56,
            48,
            4,
            128,
            licence="Apache-2.0",
            origin="PRC",
            assumed="layer count, KV heads and head size are taken from Qwen3-30B-A3B",
        ),
        Model(
            "qwen3.6-35b-a3b-q4",
            "verifier",
            20.0,
            3.3,
            0.56,
            48,
            4,
            128,
            licence="Apache-2.0",
            origin="PRC",
            assumed="as qwen3.5-35b-a3b-q4",
        ),
        Model(
            "gpt-oss-20b-mxfp4",
            "judge",
            13.0,
            3.6,
            0.56,
            24,
            8,
            64,
            sliding_fraction=0.5,
            window=128,
            licence="Apache-2.0",
            origin="US",
        ),
        Model(
            "gemma-4-31b-q4",
            "judge",
            19.0,
            31.0,
            0.56,
            60,
            16,
            128,
            sliding_fraction=0.83,
            window=1024,
            licence="Gemma",
            origin="US",
            assumed="dense; layer count, KV heads, head size and the 5:1 local:global pattern taken from Gemma 3 27B",
        ),
        Model(
            "qwen3.8-27b-q4",
            "judge",
            17.0,
            27.0,
            0.56,
            64,
            4,
            256,
            sliding_fraction=0.75,
            window=1,
            licence="Apache-2.0",
            origin="PRC",
            assumed="dense; Qwen3.5-27B layout (3 of 4 layers linear attention, fixed-size state counted as ~0)",
        ),
        Model(
            "qwen3.5-9b-q8",
            "judge",
            10.0,
            9.0,
            1.06,
            32,
            4,
            256,
            sliding_fraction=0.75,
            window=1,
            licence="Apache-2.0",
            origin="PRC",
            assumed="as qwen3.8-27b-q4, 32 layers",
        ),
        Model(
            "qwen3.5-9b-q4",
            "verifier",
            5.5,
            9.0,
            0.56,
            32,
            4,
            256,
            sliding_fraction=0.75,
            window=1,
            licence="Apache-2.0",
            origin="PRC",
            assumed="as qwen3.5-9b-q8",
        ),
        Model("bge-m3", "embedder", 2.2, 0.57, 2.0, 24, 16, 64, licence="MIT", origin="PRC"),
        Model(
            "gpt-oss-safeguard-20b-mxfp4",
            "guard",
            13.0,
            3.6,
            0.56,
            24,
            8,
            64,
            sliding_fraction=0.5,
            window=128,
            licence="Apache-2.0",
            origin="US",
        ),
    )
}

HARDWARE: dict[str, Hardware] = {
    h.id: h
    for h in (
        Hardware("cpu", "No GPU (8-core workstation, 32 GB RAM)", 0, 0, False, note="structured criteria only"),
        Hardware("rtx-5080", "One RTX 5080 (16 GB, consumer)", 16, 960, False),
        Hardware("rtx-3090", "One RTX 3090 (24 GB, consumer, used market)", 24, 936, False),
        Hardware("rtx-4090", "One RTX 4090 (24 GB, consumer)", 24, 1008, False),
        Hardware("rtx-5090", "One RTX 5090 (32 GB, consumer)", 32, 1792, False),
        Hardware("2x-rtx-4090", "Two RTX 4090 (2 x 24 GB, consumer)", 24, 1008, False, devices=2),
        Hardware("2x-rtx-5090", "Two RTX 5090 (2 x 32 GB, consumer)", 32, 1792, False, devices=2),
        Hardware("rtx-pro-4500", "One RTX PRO 4500 Blackwell (32 GB)", 32, 896, False),
        Hardware("rtx-pro-5000", "One RTX PRO 5000 Blackwell (48 GB)", 48, 1344, False),
        Hardware("rtx-pro-6000", "One RTX PRO 6000 Blackwell (96 GB)", 96, 1792, False),
        Hardware("2x-rtx-pro-6000", "Two RTX PRO 6000 Blackwell (192 GB)", 96, 1792, False, devices=2),
        Hardware("spark", "NVIDIA DGX Spark (GB10, 128 GB unified)", 128, 273, True),
        Hardware("2x-spark", "Two DGX Spark linked (256 GB unified)", 128, 273, True, devices=2),
    )
}

ENGINE_GB = 3.0  # vLLM / llama.cpp working set per served model (graphs, activations, sampler)
STACK_GB = {"HAPI FHIR + JVM": 6.0, "Postgres x2": 4.0, "DuckDB lake spill": 4.0, "console + services": 2.0, "OS": 3.0}
EMBED_GB = MODELS["bge-m3"].weights_gb + 0.5

# the configurations the review compares: hardware -> ([(model id, context tokens)], concurrent sequences)
PLANS: dict[str, tuple[list[tuple[str, int]], int]] = {
    "cpu": ([], 1),
    # consumer cards (2026-11 assessment): one 4-bit model per card, 8k context (a criterion check is ~500 tokens;
    # protocol extraction needs more and runs on the 5090 or larger); the both-must-block pair needs two cards
    # a 16 GB card (RTX 5080) is ~0.4 GB short for gpt-oss-20b once the 3 GB engine allowance is counted; not planned
    "rtx-3090": ([("gemma-4-26b-a4b-q4", 8_192)], 2),
    "rtx-4090": ([("gemma-4-26b-a4b-q4", 8_192)], 2),
    "rtx-5090": ([("gemma-4-26b-a4b-q4", 16_384)], 4),
    "2x-rtx-4090": ([("gemma-4-26b-a4b-q4", 8_192), ("qwen3.6-35b-a3b-q4", 8_192)], 1),
    "2x-rtx-5090": ([("gemma-4-26b-a4b-q4", 16_384), ("qwen3.6-35b-a3b-q4", 16_384)], 4),
    "rtx-pro-4500": ([("qwen3.5-35b-a3b-q4", 16_384)], 2),
    "rtx-pro-5000": ([("gemma-4-26b-a4b-fp8", 32_768)], 4),
    "rtx-pro-6000": ([("gpt-oss-120b-mxfp4", 32_768)], 4),
    "2x-rtx-pro-6000": ([("gpt-oss-120b-mxfp4", 65_536), ("gemma-4-26b-a4b-fp8", 32_768)], 4),
    # the pair fits the Spark only with the judge at 32k, the verifier at 16k and two sequences at a time (nightly
    # batch pace); with 64k/32k and four sequences it is about 10 GB short once the rest of the stack is counted
    "spark": ([("gpt-oss-120b-mxfp4", 32_768), ("gemma-4-26b-a4b-fp8", 16_384)], 2),
    "2x-spark": ([("gpt-oss-120b-mxfp4", 65_536), ("gemma-4-26b-a4b-fp8", 32_768)], 4),
}


def place(hw: Hardware, plan: list[tuple[str, int]], sequences: int = 4) -> dict[str, object]:
    """Memory need of ``plan`` on ``hw``: models spread one per device (round robin), the stack on device 0 when
    memory is unified. Returns the per-device totals, headroom and the per-model throughput estimate."""
    per_device = [0.0] * hw.devices
    items = []
    for i, (mid, ctx) in enumerate(plan):
        m = MODELS[mid]
        kv = m.kv_gb(ctx, sequences)
        need = m.weights_gb + kv + ENGINE_GB
        per_device[i % hw.devices] += need
        items.append(
            {
                "model": mid,
                "role": m.role,
                "context": ctx,
                "sequences": sequences,
                "weights_gb": round(m.weights_gb, 1),
                "kv_gb": round(kv, 1),
                "need_gb": round(need, 1),
                "tokens_per_s": round(m.tokens_per_s(hw.bandwidth_gbs), 0) if hw.bandwidth_gbs else None,
                "device": i % hw.devices,
                "assumed": m.assumed,
            }
        )
    stack = sum(STACK_GB.values()) + EMBED_GB if hw.unified else 0.0
    if hw.unified:
        per_device[-1] += stack  # the last device carries the rest of the stack (the only one, or the verifier's)
    headroom = [round(hw.memory_gb - used, 1) for used in per_device]
    return {
        "hardware": hw.id,
        "name": hw.name,
        "memory_gb": hw.memory_gb,
        "devices": hw.devices,
        "models": items,
        "stack_gb": round(stack, 1),
        "used_gb": [round(u, 1) for u in per_device],
        "headroom_gb": headroom,
        "fits": all(h >= 0 for h in headroom) if hw.memory_gb else None,
        "note": hw.note,
    }


def table(rows: list[dict[str, object]]) -> str:
    out = ["hardware | models (context) | used / memory GB | headroom GB | tok/s per sequence (estimate)"]
    for r in rows:
        models = r["models"]
        assert isinstance(models, list)
        names = "; ".join(f"{m['model']} ({int(m['context']) // 1024}k)" for m in models) or "none: structured only"
        if models:
            names += f", {models[0]['sequences']} seq"
        used = " + ".join(str(u) for u in r["used_gb"]) if isinstance(r["used_gb"], list) else "0"
        head = " / ".join(str(h) for h in r["headroom_gb"]) if isinstance(r["headroom_gb"], list) else "-"
        tps = "; ".join(str(m["tokens_per_s"]) for m in models if m["tokens_per_s"]) or "-"
        fit = "" if r["fits"] in (True, None) else "  DOES NOT FIT"
        out.append(f"{r['name']} | {names} | {used} / {r['memory_gb']} | {head}{fit} | {tps}")
    out.append("")
    out.append("Estimates from published sizes and model configurations; nothing measured on a device.")
    out.append(f"Per model: weights + KV cache (bf16) + {ENGINE_GB:.0f} GB engine; unified memory adds the stack:")
    out.append("  " + ", ".join(f"{k} {v:.0f} GB" for k, v in STACK_GB.items()) + f", embedder {EMBED_GB:.1f} GB.")
    assumed = sorted({f"{m.id}: {m.assumed}" for m in MODELS.values() if m.assumed})
    out.extend(["Assumed (family, not checkpoint): " + a for a in assumed])
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hardware", choices=sorted(HARDWARE), help="one option (default: every option in PLANS)")
    ap.add_argument("--model", action="append", choices=sorted(MODELS), help="replace the plan with these models")
    ap.add_argument("--context", type=int, default=32_768, help="context tokens for --model (default 32768)")
    ap.add_argument("--sequences", type=int, default=4, help="concurrent sequences for --model (default 4)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    ids = [a.hardware] if a.hardware else list(PLANS)
    rows = []
    for hid in ids:
        plan, seq = ([(m, a.context) for m in a.model], a.sequences) if a.model else PLANS.get(hid, ([], 1))
        rows.append(place(HARDWARE[hid], plan, seq))
    if a.json:
        print(json.dumps({"rows": rows, "models": {k: asdict(v) for k, v in MODELS.items()}}, indent=1))
    else:
        print(table(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
