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

**No trust on first use** (T-012b, LLM-007). The committed registry names each local build's expected weights
(``expected.manifest_sha256``, ``expected.revision``). A folder whose manifest differs is refused, whatever it holds
(the review's folder of one 16-byte file). A build with nothing expected is refused too, unless ``--trust-first-use``
is given: the pin is then a ``candidate`` marked ``weights.trust: first_use``, for evaluation, and it can never be
promoted.

``--install <gpu>`` (``deploy/install.sh``, D-142) pins the GPU profile's deployed pair from the site's own weights as
``candidate``; a build already pinned is left alone. ``champion`` is reached only through ``qualify``:
``--promote BUILD --record <record.json>`` checks the record with ``tools.qualify.check_record`` (passed, every step,
not edited, for this build and for PRODUCTION), checks that it qualified exactly the pinned weights, and writes
``status: champion`` with the record's reference. ``pin`` never writes ``champion``, and a re-pin drops the status and
the reference.

``--name-judge <gpu>`` prints the judge the profile serves, by its role and the registry's own label (alias, build,
``model_name``, pinned or not), for ``deploy/install.sh`` to name it (T-632, D-382); it reads only the registry and
the site override, never the weights.

**The chat template** (T-674, D-392, DEP-007). A judge build's registry row names ``chat_template``: the
developer's template at a pinned revision, a file under the models root that compose passes to vLLM with
``--chat-template``. ``--chat-template FILE`` (and ``--install``, from ``JUDGE_CHAT_TEMPLATE`` or the row's ``file``)
hashes it into the pin: ``weights.chat_template`` holds its path under the models root, sha256, source and revision,
and ``manifests/<build_id>.template.sha256`` holds its ``sha256sum`` line. A file whose sha256 differs from the row's
``chat_template.sha256`` is refused. Every deployed row names it (HW-005, D-567); a row that has none (one being
prepared) gets the file recorded as ``trust: first_use``. ``--install`` refuses a judge build whose template file
is missing, because vLLM would not
start with the flag. The weight manifest and its digest are unchanged: the template is a second file of the pin.

**The embedder** (T-607, D-429; LLM-014, DEP-010). The embedder is one build of the ``e-embed`` alias
(:data:`EMBED_BUILD`), pinned like a model on the ``embed`` endpoint::

    python -m tools.pin_model --build e-embed-1 --model-dir deploy/models/embedder --served-name e-embed-1 \
        --endpoint embed

Its folder must hold safetensors weights (sentence-transformers loads no GGUF; D-429: "safetensors from the
publisher"). ``embed-service`` in PRODUCTION reads this pin from the site override and refuses weights whose manifest
differs (``services/embed_service/embedder.py``); ``--verify-all`` re-checks it with the other builds.

``--verify`` recomputes the manifest and exits 1 when it differs from the pinned sha256 (SEC-64: weights changed
since the pin); it writes nothing. ``--verify-all deploy/models`` does that for every build in the override (each
under its recorded ``model_dir``); ``deploy/install.sh`` runs it before a GPU stack starts. Exit 2 on a usage error
or a refused model directory.
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


EMBED_BUILD = "e-embed-1"  # the embedder's build (D-429); services/embed_service/embedder.py names the same
EMBED_ALIAS = "e-embed"


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


def manifest_sha256_of_files(files: list[dict[str, Any]]) -> str:
    """The manifest digest of a file list as ``tools/serving_config.py`` records it (``model_files``: path, sha256),
    in this tool's format: the expected value of a release can be taken from its measured serving record."""
    keep = sorted(
        (f for f in files if not any(part.startswith(".") for part in str(f["path"]).split("/"))),
        key=lambda f: str(f["path"]),
    )
    text = "".join(f"{f['sha256']}  {f['path']}\n" for f in keep)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _committed(registry_path: Path | None = None) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    from registry.registry import DEFAULT_PATH

    doc: dict[str, Any] = yaml.safe_load((registry_path or DEFAULT_PATH).read_text(encoding="utf-8")) or {}
    return doc, {str(b.get("build_id")): b for b in doc.get("builds") or []}


def template_of(row: dict[str, Any]) -> dict[str, Any] | None:
    """The row's ``chat_template`` (source, revision, file, sha256), or None for a build served with its own."""
    tpl = row.get("chat_template")
    return dict(tpl) if isinstance(tpl, dict) and tpl.get("file") else None


def pin_template(build_id: str, row: dict[str, Any], path: Path) -> dict[str, Any]:
    """The pin's ``chat_template`` entry for ``path``; :class:`PinError` when the build names no template, the file
    is missing, or its sha256 is not the one the registry names."""
    tpl = template_of(row)
    if tpl is None:
        raise PinError(f"{build_id}: models/registry.yaml names no chat_template for this build")
    if not path.is_file():
        raise PinError(
            f"{build_id}: no chat template at {path}: the judge starts with --chat-template (DEP-007); put "
            f"{tpl.get('source')} {tpl.get('file')} at revision {tpl.get('revision')} there; refused"
        )
    sha = file_sha256(path)
    want = tpl.get("sha256")
    if want and sha != want:
        raise PinError(
            f"{build_id}: chat template {path.name} {sha[:12]} is not the expected {str(want)[:12]} of "
            f"{tpl.get('source')} at {tpl.get('revision')}; refused"
        )
    return {
        "file": str(tpl["file"]),
        "sha256": sha,
        "source": tpl.get("source"),
        "revision": tpl.get("revision"),
        "trust": "expected" if want else "first_use",
    }


def expected_of(row: dict[str, Any]) -> tuple[str | None, str | None]:
    exp = row.get("expected") or {}
    return (exp.get("manifest_sha256") or None), (exp.get("revision") or None)


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
    trust_first_use: bool = False,
    chat_template: Path | None = None,
) -> tuple[Manifest, Path]:
    """Compute the manifest, check it against the build's expected weights, write it and the override entry; returns
    (manifest, override path). ``chat_template`` is the template file the server is started with (T-674): it is
    checked after the weights and recorded in the pin. The merged registry is loaded before anything is written, so
    an override the gateway would refuse is never produced."""
    from registry.registry import Registry, apply_override

    committed, known = _committed(registry_path)
    if status == "champion":
        raise PinError(
            "champion only through qualify: pin as candidate, run `trialbox eval qualify`, then "
            "`python -m tools.pin_model --promote BUILD --record <record.json>`"
        )
    if build_id not in known:
        raise PinError(f"unknown build {build_id!r}; known: {', '.join(sorted(known))}")
    if known[build_id].get("serving") == "stub":
        raise PinError("the stub build is not pinned (it routes unpinned in DEV/TEST only)")
    if not served_name:
        raise PinError(
            "--served-name is required (the name the serving endpoint reports, e.g. vLLM --served-model-name)"
        )
    m = weight_manifest(model_dir)
    if known[build_id].get("alias") == EMBED_ALIAS and not any(
        line.endswith(".safetensors") for line in m.text.splitlines()
    ):
        raise PinError(f"{model_dir}: the embedder needs .safetensors weights (D-429), not GGUF; refused")
    want_sha, want_rev = expected_of(known[build_id])
    if want_sha and m.sha256 != want_sha:
        raise PinError(
            f"{model_dir}: these are not the weights of {build_id}: manifest {m.sha256[:12]} ({m.files} files, "
            f"{m.bytes} bytes) differs from the expected {want_sha[:12]} in models/registry.yaml; refused"
        )
    if want_rev and revision and revision != want_rev:
        raise PinError(f"{build_id}: revision {revision} is not the expected {want_rev}; refused")
    if not want_sha and not trust_first_use:
        raise PinError(
            f"{build_id}: models/registry.yaml names no expected weights (expected.manifest_sha256), so these files "
            "cannot be checked; refused (no trust on first use). Pin with --trust-first-use for an evaluation "
            "candidate that can never be promoted"
        )
    if not want_sha and status not in (None, "candidate"):
        raise PinError(f"{build_id}: weights trusted on first use are pinned as candidate only")
    template = pin_template(build_id, known[build_id], chat_template) if chat_template is not None else None
    revision = revision or want_rev
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
            "trust": "expected" if want_sha else "first_use",
        },
    }
    if template:
        entry["weights"]["chat_template"] = template
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
    template_manifest = manifest_path.with_name(f"{build_id}.template.sha256")
    if template:
        template_manifest.write_text(f"{template['sha256']}  {Path(template['file']).name}\n", encoding="utf-8")
    elif template_manifest.exists():
        template_manifest.unlink()
    _write_override(out, doc)
    return m, out


def _write_override(out: Path, doc: dict[str, Any]) -> None:
    header = (
        "# Site registry override (tools/pin_model.py). Not committed: pins of this box's model builds only.\n"
        "# The gateway reads it through TB_REGISTRY_OVERRIDE; re-check the weights with `python -m tools.pin_model"
        " --verify`.\n"
    )
    out.write_text(header + yaml.safe_dump(doc, sort_keys=True, allow_unicode=True), encoding="utf-8")


def set_served(build_id: str, endpoint: str, served_name: str, out: Path = DEFAULT_OVERRIDE) -> None:
    """Change the served name of a build already pinned in ``out``; its weights and sha256 stay as pinned. The gateway
    sends this name as each request's ``model`` and checks that the upstream echoes it (MOD-6)."""
    from registry.registry import DEFAULT_PATH, Registry, apply_override

    if not served_name:
        raise PinError("a served name is required (vLLM --served-model-name)")
    doc = load_override(out)
    entry = doc["builds"].get(build_id)
    if not entry:
        raise PinError(f"{build_id} is not pinned in {out}")
    entry["served"] = {**(entry.get("served") or {}), endpoint: served_name}
    committed = yaml.safe_load(DEFAULT_PATH.read_text(encoding="utf-8")) or {}
    Registry(apply_override(committed, doc))  # validates the merged registry; raises before writing
    _write_override(out, doc)


def add_template(build_id: str, path: Path, out: Path = DEFAULT_OVERRIDE, registry_path: Path | None = None) -> None:
    """Record the chat template in the pin of a build pinned without one (a box pinned before T-674)."""
    from registry.registry import Registry, apply_override

    committed, known = _committed(registry_path)
    doc = load_override(out)
    entry = doc["builds"].get(build_id)
    if not entry:
        raise PinError(f"{build_id} is not pinned in {out}")
    template = pin_template(build_id, known.get(build_id) or {}, path)
    entry.setdefault("weights", {})["chat_template"] = template
    Registry(apply_override(committed, doc))  # validates the merged registry; raises before writing
    (out.parent / "manifests").mkdir(parents=True, exist_ok=True)
    (out.parent / "manifests" / f"{build_id}.template.sha256").write_text(
        f"{template['sha256']}  {Path(template['file']).name}\n", encoding="utf-8"
    )
    _write_override(out, doc)


def verify(
    build_id: str, model_dir: Path, out: Path = DEFAULT_OVERRIDE, models_root: Path | None = None
) -> tuple[bool, str]:
    """(ok, message): the directory's manifest digest equals the pinned sha256 of ``build_id`` in the override, and
    the pin is the build's expected manifest when the registry names one. A pinned chat template is re-checked under
    ``models_root`` (default: the model directory's parent)."""
    doc = load_override(out)
    entry = (doc.get("builds") or {}).get(build_id, {})
    pinned = entry.get("sha256")
    if not pinned:
        return False, f"{build_id} is not pinned in {out}"
    want = expected_of(_committed()[1].get(build_id) or {})[0]
    if want and pinned != want:
        return False, f"{build_id}: the pin {pinned[:12]} is not the expected manifest {want[:12]}; re-pin the release"
    m = weight_manifest(model_dir)
    if m.sha256 != pinned:
        return False, f"{build_id}: weights changed since the pin ({m.sha256[:12]} != pinned {pinned[:12]})"
    tpl = (entry.get("weights") or {}).get("chat_template") or {}
    if tpl:
        path = (models_root or model_dir.parent) / str(tpl.get("file"))
        if not path.is_file():
            return False, f"{build_id}: the pinned chat template {path} is missing"
        if file_sha256(path) != tpl.get("sha256"):
            return False, f"{build_id}: chat template changed since the pin ({path.name})"
        return True, (
            f"{build_id}: {m.files} files match the pinned manifest {pinned[:12]}; chat template "
            f"{str(tpl.get('sha256'))[:12]}"
        )
    return True, f"{build_id}: {m.files} files match the pinned manifest {pinned[:12]}"


def verify_all(models_root: Path, out: Path = DEFAULT_OVERRIDE) -> tuple[bool, list[str]]:
    """Re-check every build pinned in the override against ``models_root/<weights.model_dir>`` (install and start:
    a box whose weights changed since the pin does not start, SEC-64). An override with no pins is not ok."""
    doc = load_override(out)
    builds = doc.get("builds") or {}
    if not builds:
        return False, [f"nothing is pinned in {out}"]
    ok, lines = True, []
    for build_id, entry in sorted(builds.items()):
        model_dir = ((entry or {}).get("weights") or {}).get("model_dir")
        if not model_dir:
            if (entry or {}).get("provider_pin"):
                lines.append(f"{build_id}: provider-pinned remote build, no local weights to check")
                continue
            ok = False
            lines.append(f"{build_id}: no weights.model_dir in the pin; re-pin it with tools/pin_model.py")
            continue
        d = models_root / str(model_dir)
        if not d.is_dir():
            ok = False
            lines.append(f"{build_id}: model directory {d} is missing")
            continue
        try:
            good, msg = verify(str(build_id), d, out, models_root)
        except PinError as exc:
            good, msg = False, f"{build_id}: {exc}"
        ok = ok and good
        lines.append(msg)
    return ok, lines


# The pair's served names (vLLM --served-model-name), one per model on every path: every GPU profile's compose default,
# the measured serving records (deploy/measured/serving_config.<gpu>.json), the cloud runs (deploy/gcp/*.sh) and
# tools/complete_run.py. A pin with any other name makes vLLM answer 404 to every call the gateway sends (the first
# complete run, 2026-11-09: compose said gemma-4-26b-a4b-it, the card served local/gemma-4-26b-a4b-nvfp4).
JUDGE_SERVED = "local/gemma-4-26b-a4b-nvfp4"
# T-674: the compose variable that names the judge's chat template under the models root (--chat-template)
TEMPLATE_VAR = "JUDGE_CHAT_TEMPLATE"
VERIFIER_SERVED = "local/qwen3.5-9b-awq"

# D-142 (review R-01): the pair each GPU profile's compose file serves, as (build, endpoint, model dir variable and
# default, served-name variable and default). ``install_pins`` pins it from the site's own weights at install.
PROFILE_PAIRS: dict[str, list[tuple[str, str, str, str, str, str]]] = {
    "rtxpro6000": [
        ("gemma-4-26b-a4b-it-rtxpro6000", "serving", "JUDGE_MODEL_DIR", "gemma-4-26b-a4b-it-4bit", "JUDGE_MODEL",
         JUDGE_SERVED),
        ("qwen3.5-9b-rtxpro6000", "verifier", "VERIFIER_MODEL_DIR", "qwen3.5-9b-4bit", "VERIFIER_MODEL",
         VERIFIER_SERVED),
    ],
    "gb10": [
        ("gemma-4-26b-a4b-it-spark", "serving", "JUDGE_MODEL_DIR", "gemma-4-26b-a4b-it-4bit", "JUDGE_MODEL",
         JUDGE_SERVED),
        ("qwen3.5-9b-spark", "verifier", "VERIFIER_MODEL_DIR", "qwen3.5-9b-4bit", "VERIFIER_MODEL", VERIFIER_SERVED),
    ],
    "rtx5090": [
        ("gemma-4-26b-a4b-it-rtx5090", "serving", "JUDGE_MODEL_DIR", "gemma-4-26b-a4b-it-4bit", "JUDGE_MODEL",
         JUDGE_SERVED),
        ("qwen3.5-9b-rtx5090", "verifier", "VERIFIER_MODEL_DIR", "qwen3.5-9b-4bit", "VERIFIER_MODEL", VERIFIER_SERVED),
    ],
    # D-409: the B200 on two MIG instances (deploy/platform overlays/shared-quota, docker-compose.shared-quota.yml);
    # the platform's pin job (overlays/shared-quota/pin.yaml) runs --install shared-quota against the models claim
    "shared-quota": [
        ("gemma-4-26b-a4b-it-sharedquota", "serving", "JUDGE_MODEL_DIR", "gemma-4-26b-a4b-it-4bit", "JUDGE_MODEL",
         JUDGE_SERVED),
        ("qwen3.5-9b-sharedquota", "verifier", "VERIFIER_MODEL_DIR", "qwen3.5-9b-4bit", "VERIFIER_MODEL",
         VERIFIER_SERVED),
    ],
    "rtx4090": [  # judge alone (the verifier is scaled to 0; TB_NOTE_BLOCK=never)
        ("gemma-4-26b-a4b-it-rtx5090", "serving", "JUDGE_MODEL_DIR", "gemma-4-26b-a4b-it-4bit", "JUDGE_MODEL",
         JUDGE_SERVED),
    ],
}  # fmt: skip


def install_pins(
    gpu: str,
    models_root: Path,
    out: Path = DEFAULT_OVERRIDE,
    env: dict[str, str] | None = None,
    registry_path: Path | None = None,
) -> tuple[bool, list[str]]:
    """Pin the profile's deployed pair at install (D-142, review R-01): the sha256 of the site's own weights, which
    must be the release's expected manifest (T-012b: a folder of other files is refused and nothing is pinned), the
    served name compose gives vLLM, and status ``candidate``. A PRODUCTION route accepts only a ``champion``, which
    ``--promote`` makes from a passing qualification record. A build already pinned keeps its weights pin
    (``--verify-all`` checks it; a pin that is not the expected manifest is reported and not ok), but
    its served name follows the one compose serves now, so an update that renames the served model does not leave the
    gateway asking vLLM for the old name (HTTP 404). A missing weights directory is reported and nothing is invented,
    so that model routes nothing until it is pinned."""
    e = env or {}
    pairs = PROFILE_PAIRS.get(gpu)
    if pairs is None:
        return False, [f"no deployed pair for GPU profile {gpu!r}"]
    have = (load_override(out).get("builds") or {}) if out.exists() else {}
    known = _committed(registry_path)[1]
    ok, lines = True, []
    for build, endpoint, dir_var, dir_default, name_var, name_default in pairs:
        name = e.get(name_var) or name_default
        pinned = (have.get(build) or {}).get("sha256")
        want = expected_of(known.get(build) or {})[0]
        if pinned and want and pinned != want:  # an earlier install trusted these files on first use
            ok = False
            lines.append(f"{build}: pinned {pinned[:12]} is not the expected manifest {want[:12]}: it routes nothing; "
                         "put the release's weights in place and re-pin it")  # fmt: skip
            continue
        tpl = template_of(known.get(build) or {})
        tpl_path = models_root / (e.get(TEMPLATE_VAR) or str(tpl["file"])) if tpl else None
        if pinned:
            note = ""
            if tpl_path is not None and not ((have.get(build) or {}).get("weights") or {}).get("chat_template"):
                try:  # pinned before T-674: the template the server now starts with joins the pin
                    add_template(build, tpl_path, out, registry_path)
                except PinError as exc:
                    ok = False
                    lines.append(f"{build}: {exc}")
                    continue
                note = f"; chat template {tpl_path.name} added to the pin"
            was = ((have.get(build) or {}).get("served") or {}).get(endpoint)
            if was != name:
                set_served(build, endpoint, name, out)
                lines.append(f"{build}: already pinned; served name on {endpoint} now {name!r} (was {was!r}){note}")
            else:
                lines.append(f"{build}: already pinned{note}")
            continue
        d = models_root / (e.get(dir_var) or dir_default)
        if not d.is_dir():
            ok = False
            lines.append(f"{build}: no weights in {d}: this model routes nothing until it is pinned (RUNBOOK §8)")
            continue
        try:
            m, _ = pin(
                build,
                d,
                served_name=name,
                endpoint=endpoint,
                out=out,
                status="candidate",
                registry_path=registry_path,
                chat_template=tpl_path,
            )
        except PinError as exc:
            ok = False
            lines.append(f"{build}: {exc}")
            continue
        lines.append(
            f"{build}: pinned {m.sha256[:12]} ({m.files} files) as candidate on {endpoint}; "
            "champion after trialbox eval qualify and --promote"
            + (f"; chat template {tpl['source']} at {tpl['revision']}" if tpl else "")
        )
    return ok, lines


def judge_line(gpu: str, out: Path = DEFAULT_OVERRIDE, registry: Path | None = None) -> str:
    """The judge of a GPU profile in one line, from the configuration only: the role's alias, the build the profile
    serves, the registry's ``model_name`` for it and the site's pin (T-632, D-382)."""
    pairs = PROFILE_PAIRS.get(gpu)
    if not pairs:
        raise PinError(f"no deployed pair for GPU profile {gpu!r}")
    build = next(b for b, endpoint, *_ in pairs if endpoint == "serving")
    reg = yaml.safe_load((registry or ROOT / "models" / "registry.yaml").read_text(encoding="utf-8")) or {}
    entry = next((b for b in reg.get("builds") or [] if b.get("build_id") == build), None)
    if entry is None:
        raise PinError(f"build {build} of profile {gpu} is not in models/registry.yaml")
    have = ((load_override(out).get("builds") or {}) if out.exists() else {}).get(build) or {}
    pin_txt = f"pinned {str(have['sha256'])[:12]}" if have.get("sha256") else "not pinned (routes nothing yet)"
    label = entry.get("model_name") or build
    return f"judge ({entry.get('alias')}): {label}; build {build}; {pin_txt}"


def promote(
    build_id: str,
    record_path: Path,
    out: Path = DEFAULT_OVERRIDE,
    *,
    environment: str = "PRODUCTION",
    now: datetime | None = None,
) -> str:
    """Make ``build_id`` the champion from a qualification record (T-012b: the only way to ``champion``). Refused
    when ``tools.qualify.check_record`` finds a problem (failed or missing step, edited body, another build, synthetic
    weights for PRODUCTION), when the build is not pinned, was trusted on first use, or when the record qualified other
    weights than the pinned ones. Returns the record id."""
    import json

    from registry.registry import Registry, apply_override

    from tools.qualify import check_record

    try:
        rec = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PinError(f"{record_path}: not a readable qualification record ({exc})") from exc
    problems = check_record(rec, build_id=build_id, environment=environment)
    if problems:
        raise PinError(f"{record_path}: does not qualify {build_id}: " + "; ".join(problems))
    doc = load_override(out)
    entry = doc["builds"].get(build_id)
    if not entry or not entry.get("sha256"):
        raise PinError(f"{build_id} is not pinned in {out}: pin its weights first")
    if (entry.get("weights") or {}).get("trust") == "first_use":
        raise PinError(
            f"{build_id}: weights trusted on first use cannot be promoted; name them in models/registry.yaml"
        )
    qualified = next(b for b in rec["builds"].values() if b["build_id"] == build_id)
    if qualified.get("weights_sha256") != entry["sha256"]:
        raise PinError(
            f"{build_id}: the record qualified weights {str(qualified.get('weights_sha256'))[:12]}, "
            f"the pin is {entry['sha256'][:12]}; qualify the pinned weights"
        )
    entry["status"] = "champion"
    entry["qualification"] = {
        "record_id": rec["record_id"],
        "record": record_path.name,
        "sha256": rec["sha256"],
        "profile": rec["profile"],
        "weights_sha256": entry["sha256"],
        "qualifies_production": bool(rec.get("qualifies_production")),
        "promoted_at": (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    committed, _ = _committed()
    Registry(apply_override(committed, doc))  # validates the merged registry; raises before writing
    _write_override(out, doc)
    return str(rec["record_id"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", help="build_id in models/registry.yaml")
    ap.add_argument("--model-dir", type=Path)
    ap.add_argument("--served-name", default="", help="name the endpoint reports (vLLM --served-model-name)")
    ap.add_argument("--endpoint", default="serving", help="routing.yaml endpoint that serves the build")
    ap.add_argument("--out", type=Path, default=DEFAULT_OVERRIDE, help="site override file")
    ap.add_argument(
        "--status", default=None, choices=["candidate", "qualified", "shadow"], help="never champion: see --promote"
    )
    ap.add_argument(
        "--trust-first-use",
        action="store_true",
        help="pin a build with no expected weights in the registry, as an evaluation candidate never promoted",
    )
    ap.add_argument("--promote", metavar="BUILD", help="make BUILD champion from --record (a passing qualify record)")
    ap.add_argument("--record", type=Path, help="--promote: the qualification record (eval/qualification/*.json)")
    ap.add_argument("--environment", default="PRODUCTION", help="--promote: the environment the record must qualify")
    ap.add_argument("--revision", default=None, help="upstream revision (commit or tag) of the weights")
    ap.add_argument(
        "--chat-template",
        type=Path,
        default=None,
        help="the template file the server gets with --chat-template (a judge build's registry chat_template)",
    )
    ap.add_argument("--verify", action="store_true", help="re-check the weights against the pin; write nothing")
    ap.add_argument(
        "--verify-all",
        type=Path,
        metavar="MODELS_ROOT",
        help="re-check every pinned build against MODELS_ROOT/<model_dir>; exit 1 on any mismatch or no pins",
    )
    ap.add_argument(
        "--install",
        metavar="GPU",
        help="pin GPU profile's deployed pair from --models-root (install.sh); exit 1 when weights are missing",
    )
    ap.add_argument("--models-root", type=Path, default=ROOT / "deploy" / "models")
    ap.add_argument(
        "--name-judge", metavar="GPU", help="print the judge GPU profile serves (install.sh); write nothing"
    )
    args = ap.parse_args(argv)
    if args.name_judge:
        try:
            print(judge_line(args.name_judge, args.out))
        except PinError as exc:
            print(f"pin_model: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.promote:
        if args.record is None:
            ap.error("--promote needs --record")
        try:
            rid = promote(args.promote, args.record, args.out, environment=args.environment)
        except PinError as exc:
            print(f"pin_model: {exc}", file=sys.stderr)
            return 1
        print(f"promoted {args.promote} to champion on record {rid}")
        return 0
    if args.install:
        import os

        try:
            good, lines = install_pins(args.install, args.models_root, args.out, dict(os.environ))
        except PinError as exc:
            print(f"pin_model: {exc}", file=sys.stderr)
            return 2
        print("\n".join(lines))
        return 0 if good else 1
    if args.verify_all is not None:
        try:
            good, lines = verify_all(args.verify_all, args.out)
        except PinError as exc:
            print(f"pin_model: {exc}", file=sys.stderr)
            return 2
        print("\n".join(lines))
        return 0 if good else 1
    if not args.build or args.model_dir is None:
        ap.error("--build and --model-dir are required (or use --verify-all MODELS_ROOT)")
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
            trust_first_use=args.trust_first_use,
            chat_template=args.chat_template,
        )
    except (PinError, ValueError) as exc:
        print(f"pin_model: {exc}", file=sys.stderr)
        return 2
    print(f"pinned {args.build}: sha256 {m.sha256} ({m.files} files, {m.bytes} bytes) -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
