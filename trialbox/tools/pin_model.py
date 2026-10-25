"""Pin a local model build for this site: weight manifest -> registry sha256 -> site override (spec v4 §8.4, S1-07).

    python -m tools.pin_model --build qwen3.5-35b-a3b-candidate --model-dir deploy/models/qwen3.5-35b-a3b-q4 \\
        --served-name qwen3.5-35b-a3b-q4
    python -m tools.pin_model --build qwen3.5-35b-a3b-candidate --model-dir deploy/models/qwen3.5-35b-a3b-q4 --verify

The **weight manifest** of a model directory lists every regular file below it as ``<sha256>  <relative path>``
(``sha256sum`` format, paths with ``/``, sorted by path, LF line ends). The build's registry ``sha256`` is the SHA-256
of that manifest text, as the comment in ``models/registry.yaml`` defines it. The manifest is written next to the
override (``manifests/<build_id>.sha256``) so ``sha256sum -c`` can re-check the weights by hand.

The pin goes into the **site override** (default ``deploy/site/registry.site.yaml``, read by the gateway through
``TB_REGISTRY_OVERRIDE``), never into the committed registry. Pins of other builds already in the override are kept.
Only safetensors or GGUF weights are accepted; pickle-format weights and Python files in the model directory are
refused (SEC-63: no pickle loading, no ``trust_remote_code``). Hidden files and directories (``.cache``, ``.git``)
are not part of the manifest.

``--verify`` recomputes the manifest and exits 1 when it differs from the pinned sha256 (SEC-64: weights changed
since the pin); it writes nothing. Exit 2 on a usage error or a refused model directory.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OVERRIDE = ROOT / "deploy" / "site" / "registry.site.yaml"
WEIGHT_SUFFIXES = (".safetensors", ".gguf")
REFUSED_SUFFIXES = (".bin", ".pt", ".pth", ".pkl", ".pickle", ".ckpt", ".py", ".pyc")
CHUNK = 8 << 20


class PinError(RuntimeError):
    pass


@dataclass(frozen=True)
class Manifest:
    text: str  # sha256sum-format lines
    sha256: str  # digest of ``text`` (the registry pin)
    files: int
    bytes: int


def _visible(path: Path, root: Path) -> bool:
    return not any(part.startswith(".") for part in path.relative_to(root).parts)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def weight_manifest(model_dir: Path) -> Manifest:
    """The manifest of ``model_dir``; :class:`PinError` when the directory holds no safetensors/GGUF weights or holds
    a refused file type."""
    if not model_dir.is_dir():
        raise PinError(f"{model_dir}: not a directory")
    files = sorted(
        (p for p in model_dir.rglob("*") if p.is_file() and _visible(p, model_dir)),
        key=lambda p: p.relative_to(model_dir).as_posix(),
    )
    refused = [p.relative_to(model_dir).as_posix() for p in files if p.suffix.lower() in REFUSED_SUFFIXES]
    if refused:
        raise PinError(f"{model_dir}: refused file types (pickle weights or code): {', '.join(refused[:5])}")
    if not any(p.suffix.lower() in WEIGHT_SUFFIXES for p in files):
        raise PinError(f"{model_dir}: no .safetensors or .gguf weights found")
    lines = [f"{file_sha256(p)}  {p.relative_to(model_dir).as_posix()}\n" for p in files]
    text = "".join(lines)
    return Manifest(
        text, hashlib.sha256(text.encode("utf-8")).hexdigest(), len(files), sum(p.stat().st_size for p in files)
    )


def load_override(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"kind": "registry-site-override", "builds": {}}
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if doc.get("kind") != "registry-site-override":
        raise PinError(f"{path}: not a registry site override (kind)")
    doc.setdefault("builds", {})
    return doc


def pin(
    build_id: str,
    model_dir: Path,
    *,
    served_name: str,
    endpoint: str = "serving",
    out: Path = DEFAULT_OVERRIDE,
    status: str | None = None,
    revision: str | None = None,
    registry_path: Path | None = None,
    now: datetime | None = None,
) -> tuple[Manifest, Path]:
    """Compute the manifest, write it and the override entry; returns (manifest, override path). The merged registry
    is loaded before anything is written, so an override the gateway would refuse is never produced."""
    from registry.registry import DEFAULT_PATH, Registry, apply_override

    reg_path = registry_path or DEFAULT_PATH
    committed = yaml.safe_load(reg_path.read_text(encoding="utf-8")) or {}
    known = {str(b.get("build_id")): b for b in committed.get("builds") or []}
    if build_id not in known:
        raise PinError(f"unknown build {build_id!r}; known: {', '.join(sorted(known))}")
    if known[build_id].get("serving") == "stub":
        raise PinError("the stub build is not pinned (it routes unpinned in DEV/TEST only)")
    if not served_name:
        raise PinError(
            "--served-name is required (the name the serving endpoint reports, e.g. vLLM --served-model-name)"
        )
    m = weight_manifest(model_dir)
    doc = load_override(out)
    doc["base_version"] = committed.get("version")
    entry: dict[str, Any] = {
        "sha256": m.sha256,
        "served": {endpoint: served_name},
        "weights": {
            "manifest": f"manifests/{build_id}.sha256",
            "files": m.files,
            "bytes": m.bytes,
            "model_dir": model_dir.name,
            "pinned_at": (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    }
    if status:
        entry["status"] = status
    if revision:
        entry["revision"] = revision
    doc["builds"][build_id] = entry
    Registry(apply_override(committed, doc))  # validates the merged registry; raises before writing
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = out.parent / "manifests" / f"{build_id}.sha256"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(m.text, encoding="utf-8")
    header = (
        "# Site registry override (tools/pin_model.py). Not committed: pins of this box's model builds only.\n"
        "# The gateway reads it through TB_REGISTRY_OVERRIDE; re-check the weights with `python -m tools.pin_model"
        " --verify`.\n"
    )
    out.write_text(header + yaml.safe_dump(doc, sort_keys=True, allow_unicode=True), encoding="utf-8")
    return m, out


def verify(build_id: str, model_dir: Path, out: Path = DEFAULT_OVERRIDE) -> tuple[bool, str]:
    """(ok, message): the directory's manifest digest equals the pinned sha256 of ``build_id`` in the override."""
    doc = load_override(out)
    pinned = (doc.get("builds") or {}).get(build_id, {}).get("sha256")
    if not pinned:
        return False, f"{build_id} is not pinned in {out}"
    m = weight_manifest(model_dir)
    if m.sha256 != pinned:
        return False, f"{build_id}: weights changed since the pin ({m.sha256[:12]} != pinned {pinned[:12]})"
    return True, f"{build_id}: {m.files} files match the pinned manifest {pinned[:12]}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", required=True, help="build_id in models/registry.yaml")
    ap.add_argument("--model-dir", type=Path, required=True)
    ap.add_argument("--served-name", default="", help="name the endpoint reports (vLLM --served-model-name)")
    ap.add_argument("--endpoint", default="serving", help="routing.yaml endpoint that serves the build")
    ap.add_argument("--out", type=Path, default=DEFAULT_OVERRIDE, help="site override file")
    ap.add_argument("--status", default=None, choices=["candidate", "qualified", "shadow", "champion"])
    ap.add_argument("--revision", default=None, help="upstream revision (commit or tag) of the weights")
    ap.add_argument("--verify", action="store_true", help="re-check the weights against the pin; write nothing")
    args = ap.parse_args(argv)
    try:
        if args.verify:
            good, msg = verify(args.build, args.model_dir, args.out)
            print(msg)
            return 0 if good else 1
        m, path = pin(
            args.build,
            args.model_dir,
            served_name=args.served_name,
            endpoint=args.endpoint,
            out=args.out,
            status=args.status,
            revision=args.revision,
        )
    except (PinError, ValueError) as exc:
        print(f"pin_model: {exc}", file=sys.stderr)
        return 2
    print(f"pinned {args.build}: sha256 {m.sha256} ({m.files} files, {m.bytes} bytes) -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
