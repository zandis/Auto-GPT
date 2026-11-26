"""Pin a local model build for this site: weight manifest -> registry sha256 -> site override (spec v4 §8.4, S1-07).

    python -m tools.pin_model --build qwen3.5-35b-a3b-candidate --model-dir deploy/models/qwen3.5-35b-a3b-q4 \\
        --served-name qwen3.5-35b-a3b-q4
    python -m tools.pin_model --build qwen3.5-35b-a3b-candidate --model-dir deploy/models/qwen3.5-35b-a3b-q4 --verify
    python -m tools.pin_model --resolve --env-file deploy/.env [--require judge]   # what PRODUCTION routes (D-738)

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
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
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


# D-887: the box rehearsal's media carries placeholder weights (tools/rehearse_box/rehearse.sh), never a model. Pinned
# on a rehearsal box only, as candidate, so that SCREEN runs through the gateway: it proves the path a box judges by,
# nothing about a model. Never promoted, never qualified.
PLACEHOLDER_ARCH = "TrialBoxRehearsalPlaceholder"
PLACEHOLDER_TRUST = "rehearsal_placeholder"
# the integrator's (i): a rehearsal box is VALIDATION (D3 on the box, D-823), or TEST as it was; never PRODUCTION
REHEARSAL_ENVS = ("TEST", "VALIDATION")


def is_placeholder(model_dir: Path) -> bool:
    """The rehearsal media's placeholder folder (its config.json names the placeholder architecture alone)."""
    import json

    try:
        cfg = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(cfg, dict) and cfg.get("architectures") == [PLACEHOLDER_ARCH]


def placeholder_refusal(env: dict[str, str], installed: Path, dirs: list[Path]) -> str | None:
    """None when the pair's folders are rehearsal placeholders that may be pinned here; "" when none is a placeholder
    (the release's rules apply); else why they may not be (nothing is pinned)."""
    import json

    marks = [is_placeholder(d) for d in dirs if d.is_dir()]
    if not any(marks):
        return ""
    if not all(marks):
        return "a real weight folder beside a rehearsal placeholder: nothing is pinned (no mixing)"
    if env.get("TB_ENV") not in REHEARSAL_ENVS or env.get("TB_REHEARSAL") != "1":
        return (f"rehearsal placeholder weights are pinned on a rehearsal box only (TB_ENV TEST or VALIDATION, "
                f"TB_REHEARSAL=1); this box is TB_ENV={env.get('TB_ENV') or '?'}: nothing is pinned")  # fmt: skip
    try:
        rec = json.loads(installed.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rec = {}
    if not isinstance(rec, dict) or rec.get("rehearsal_box") is not True:
        # the integrator's (i): the mark install.sh --rehearsal writes, recorded at the load; never a variable alone
        return (f"rehearsal placeholder weights, but {installed} records no rehearsal box (deploy/install.sh "
                "--rehearsal): nothing is pinned")  # fmt: skip
    if rec.get("rehearsal") is not True:
        return f"rehearsal placeholder weights, but the installed bundle is not a rehearsal bundle ({installed})"
    return None


def rehearsal_box_refusal(out: Path) -> str | None:
    """Why nothing is promoted or qualified on this box: the rehearsal mark beside the site pins
    (deploy/site/rehearsal.json, written by deploy/install.sh --rehearsal only); None on any other box."""
    mark = out.parent / "rehearsal.json"
    if mark.is_file():
        return (
            f"a rehearsal box ({mark}, deploy/install.sh --rehearsal): placeholder models, synthetic data only; "
            "nothing is promoted or qualified on it (D-887)"
        )
    return None


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
    placeholder: bool = False,
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
    if placeholder:  # D-887: install_pins checked the box, the bundle and every folder; this one is checked again
        if not is_placeholder(model_dir):
            raise PinError(f"{model_dir}: not the rehearsal media's placeholder; refused")
        if status not in (None, "candidate"):
            raise PinError(f"{build_id}: a rehearsal placeholder is pinned as candidate only")
        want_sha, want_rev, chat_template, status = None, None, None, "candidate"
    elif want_sha and m.sha256 != want_sha:
        raise PinError(
            f"{model_dir}: these are not the weights of {build_id}: manifest {m.sha256[:12]} ({m.files} files, "
            f"{m.bytes} bytes) differs from the expected {want_sha[:12]} in models/registry.yaml; refused"
        )
    if want_rev and revision and revision != want_rev:
        raise PinError(f"{build_id}: revision {revision} is not the expected {want_rev}; refused")
    if not want_sha and not trust_first_use and not placeholder:
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
            # timezone.utc, not datetime.UTC (3.11): tools.fetch_weights imports this module on the host's python3
            "pinned_at": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),  # noqa: UP017
            "trust": PLACEHOLDER_TRUST if placeholder else "expected" if want_sha else "first_use",
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


# LLM-007 (D-568): the variable that holds the length a profile's server is started with (compose passes it to
# --max-model-len), by the endpoint the build is served on
CONTEXT_VARS = {"serving": "JUDGE_MAX_LEN", "verifier": "VERIFIER_MAX_LEN"}
CONTEXT_UNMEASURED = ("", "unmeasured")  # deploy/platform/overlays/*/serving.env before the partition is measured


def set_context(build_id: str, context: int, out: Path = DEFAULT_OVERRIDE, registry_path: Path | None = None) -> None:
    """Write ``context_length`` into the pin of a build already pinned in ``out`` (a registry row that names none)."""
    from registry.registry import Registry, apply_override

    committed, _ = _committed(registry_path)
    doc = load_override(out)
    entry = doc["builds"].get(build_id)
    if not entry:
        raise PinError(f"{build_id} is not pinned in {out}")
    if isinstance(context, bool) or not isinstance(context, int) or context <= 0:
        raise PinError(f"{build_id}: a context is a whole number above zero, not {context!r}")
    entry["context_length"] = context
    Registry(apply_override(committed, doc))  # validates the merged registry; raises before writing
    _write_override(out, doc)


def install_context(
    build_id: str, endpoint: str, row: dict[str, Any], out: Path, env: dict[str, str], registry_path: Path | None
) -> tuple[bool, str]:
    """The context of a pinned build whose registry row names none, from the profile's variable (LLM-007): (ok, a
    note for the build's line). A row that names its context needs nothing. A length in the variable is written, and
    replaces another one in the pin (the partition was measured again); the note says both. A pin that carries another
    length than its row names (a stale site pin: the gateway sizes prompts from it) is put back to the row's."""
    have = (load_override(out)["builds"].get(build_id) or {}).get("context_length")
    if row.get("context_length"):
        if have is None or have == row["context_length"]:
            return True, ""
        set_context(build_id, int(row["context_length"]), out, registry_path)
        return True, f"; context {row['context_length']} (the registry's for this build; the pin had {have})"
    var = CONTEXT_VARS.get(endpoint, "")
    raw = _length_var(env, var)
    if raw.isascii() and raw.isdigit() and int(raw) > 0:
        if have == int(raw):
            return True, ""
        set_context(build_id, int(raw), out, registry_path)
        return True, f"; context {int(raw)} ({var}" + (f"; was {have})" if have else ")")
    # not measured yet (unset, or the platform's placeholder): said, and the pair's result stays; a value that is
    # set and is not a length is a mistake where the variable is set: not ok
    unmeasured = raw in CONTEXT_UNMEASURED
    if have:
        return unmeasured, "" if unmeasured else f"; {var} is {raw!r}, not a length: the pin keeps context {have}"
    return unmeasured, (
        f"; no context: the registry names none for this build and {var or 'its length'} is {raw!r} (the length the "
        "server runs with, a whole number): the weights are pinned, but the model routes nothing in PRODUCTION "
        "until it is set in the environment of pin_model --install (the platform: serving.env, then the pin job "
        f"again), or by hand: pin_model --build {build_id} --model-dir <folder> --context N"
    )


#: a profile served by another profile's compose file (install.sh: the rtx4090 box runs the rtx5090 file)
PROFILE_COMPOSE = {"rtx4090": "rtx5090"}


def _length_var(env: dict[str, str] | Any, var: str) -> str:
    """A length variable as compose reads it from deploy/.env: blanks and one pair of quotes around it dropped."""
    return (env.get(var) or "").strip().strip("\"'").strip()


def profile_context(gpu: str, endpoint: str, env: dict[str, str] | Any, deploy: Path | None = None) -> int | None:
    """The length the profile's server is started with: its variable as compose reads it from deploy/.env, else
    (unset or empty) the default the profile's compose file in ``deploy`` gives it
    (``--max-model-len=${JUDGE_MAX_LEN:-16384}``). None when the variable is the platform's placeholder or the file
    asks for it with no default (``${JUDGE_MAX_LEN:?...}``: compose stops without it; install_context says so).
    PinError when no length can be found: a value that is not a length (compose passes it to the server, which does
    not start), or no compose file of the profile, or one that does not name the variable."""
    var = CONTEXT_VARS.get(endpoint, "")
    raw = _length_var(env, var)
    if raw:
        if raw.isascii() and raw.isdigit() and int(raw) > 0:
            return int(raw)
        if raw in CONTEXT_UNMEASURED:
            return None
        raise PinError(f"{var} is {raw!r} in deploy/.env, not a length: the {gpu} server does not start with it")
    f = (deploy or ROOT / "deploy") / f"docker-compose.{PROFILE_COMPOSE.get(gpu, gpu)}.yml"
    if not f.is_file():
        raise PinError(f"no {f}: the length the {gpu} server runs with ({var}) cannot be read")
    text = f.read_text(encoding="utf-8")
    if m := re.search(r"\$\{" + re.escape(var) + r":-(\d+)\}", text):
        return int(m.group(1))
    if re.search(r"\$\{" + re.escape(var) + r":\?", text):
        return None
    raise PinError(f"{f} gives {var} no length: the length the {gpu} server runs with cannot be read")


def context_problems(
    gpu: str,
    out: Path = DEFAULT_OVERRIDE,
    env: dict[str, str] | Any = None,
    registry_path: Path | None = None,
    deploy: Path | None = None,
) -> list[str]:
    """Each build of the profile's pair whose pinned ``context_length`` (the registry with the site pin) is not the
    length the profile's server runs with: the gateway refuses every call ``model_mismatch`` when the server's is
    the smaller, and sizes prompts for a context nobody serves when it is the larger. A length that cannot be read
    (:func:`profile_context`) is a problem too, never a pass. ``deploy``: the box's deploy folder (its compose
    files)."""
    from registry.registry import DEFAULT_PATH, Registry

    builds = {b.build_id: b for b in Registry.load(registry_path or DEFAULT_PATH, out).builds}
    problems = []
    for build, endpoint, *_ in PROFILE_PAIRS.get(gpu, []):
        try:
            want = profile_context(gpu, endpoint, env or {}, deploy)
        except PinError as exc:
            problems.append(f"{build}: {exc}")
            continue
        have = builds[build].context_length if build in builds else None
        if want and have and want != have:
            problems.append(
                f"{build}: the pin's context_length is {have}, the {gpu} profile serves {want} "
                f"({CONTEXT_VARS[endpoint]}): re-run pin_model --install {gpu} for a stale pin, or set "
                f"{CONTEXT_VARS[endpoint]} to {have} in deploy/.env"
            )
    return problems


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
    placeholder = (entry.get("weights") or {}).get("trust") == PLACEHOLDER_TRUST
    if placeholder and not is_placeholder(model_dir):
        return False, f"{build_id}: pinned as a rehearsal placeholder, but {model_dir} is not one; re-pin"
    if want and pinned != want and not placeholder:  # D-887: a placeholder pin is checked against its own pin
        return False, f"{build_id}: the pin {pinned[:12]} is not the expected manifest {want[:12]}; re-pin the release"
    m = weight_manifest(model_dir)
    if m.sha256 != pinned:
        return False, f"{build_id}: weights changed since the pin ({m.sha256[:12]} != pinned {pinned[:12]})"
    tpl = (entry.get("weights") or {}).get("chat_template") or {}
    if tpl:
        # HW-005 (D-567): a template pinned before the registry named its hash (first use) is checked against the
        # registry now, not only against the pin's own record of it
        named = (template_of(_committed()[1].get(build_id) or {}) or {}).get("sha256")
        if named and tpl.get("sha256") != named:
            return False, (
                f"{build_id}: the pinned chat template {str(tpl.get('sha256'))[:12]} is not the registry's "
                f"{str(named)[:12]}; put the named file in place and re-pin (pin_model --install)"
            )
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


# ENG-003 (D-563): the embedder every profile's box runs (compose mounts deploy/models/embedder into the embed
# service): build, endpoint, model dir variable and default, served-name variable and default
EMBED_PIN = (EMBED_BUILD, "embed", "EMBED_MODEL_DIR", "embedder", "EMBED_MODEL", EMBED_BUILD)


def install_pins(
    gpu: str,
    models_root: Path,
    out: Path = DEFAULT_OVERRIDE,
    env: dict[str, str] | None = None,
    registry_path: Path | None = None,
    *,
    with_embedder: bool = False,
    installed: Path | None = None,
    deploy: Path | None = None,
) -> tuple[bool, list[str]]:
    """Pin the profile's deployed pair at install (D-142, review R-01): the sha256 of the site's own weights, which
    must be the release's expected manifest (T-012b: a folder of other files is refused and nothing is pinned), the
    served name compose gives vLLM, and status ``candidate``. A PRODUCTION route accepts only a ``champion``, which
    ``--promote`` makes from a passing qualification record. A build already pinned keeps its weights pin
    (``--verify-all`` checks it; a pin that is not the expected manifest is reported and not ok), but
    its served name follows the one compose serves now, so an update that renames the served model does not leave the
    gateway asking vLLM for the old name (HTTP 404). A missing weights directory is reported and nothing is invented,
    so that model routes nothing until it is pinned. ``deploy``: the box's deploy folder, whose profile compose file
    gives the length the servers run with (install.sh: the mounted site folder, not the image's)."""
    e = env or {}
    pairs = PROFILE_PAIRS.get(gpu)
    if pairs is None:
        return False, [f"no deployed pair for GPU profile {gpu!r}"]
    if with_embedder:  # ENG-003 (D-563): the installer pins the embedder with the pair, on every profile
        pairs = [*pairs, EMBED_PIN]
    have = (load_override(out).get("builds") or {}) if out.exists() else {}
    known = _committed(registry_path)[1]
    # D-887: the rehearsal media's placeholders, pinned only when the box, the bundle and every pair folder say so
    dirs = [models_root / (e.get(p[2]) or p[3]) for p in pairs if p[0] != EMBED_BUILD]
    refusal = placeholder_refusal(e, installed or models_root.parent / "updates" / "installed.json", dirs)
    if refusal:
        return False, [refusal]
    placeholders = refusal is None
    ok, lines = True, []
    for build, endpoint, dir_var, dir_default, name_var, name_default in pairs:
        if placeholders:
            d = models_root / (e.get(dir_var) or dir_default)
            if build == EMBED_BUILD or not d.is_dir():
                lines.append(f"{build}: no rehearsal placeholder in {d}: not pinned")
                ok = ok and build == EMBED_BUILD
                continue
            name = e.get(name_var) or name_default
            try:
                m, _ = pin(build, d, served_name=name, endpoint=endpoint, out=out, status="candidate",
                           registry_path=registry_path, placeholder=True)  # fmt: skip
            except PinError as exc:
                ok = False
                lines.append(f"{build}: {exc}")
                continue
            lines.append(f"{build}: pinned {m.sha256[:12]} as candidate on {endpoint}: a rehearsal placeholder, which "
                         "proves the path a box judges by, nothing about a model; never promoted (D-887)")  # fmt: skip
            continue
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
            had = ((have.get(build) or {}).get("weights") or {}).get("chat_template") or {}
            # pinned before T-674 (no template in the pin), or before the registry named the template's hash
            # (HW-005, D-567: recorded on first use): the file is checked against the registry and the pin follows
            stale = bool(had) and bool(tpl and tpl.get("sha256")) and had.get("sha256") != (tpl or {}).get("sha256")
            if tpl_path is not None and (not had or stale):
                try:
                    add_template(build, tpl_path, out, registry_path)
                except PinError as exc:
                    ok = False
                    lines.append(f"{build}: {exc}")
                    continue
                note = (
                    f"; chat template {tpl_path.name} replaced by the registry's in the pin"
                    if stale
                    else f"; chat template {tpl_path.name} added to the pin"
                )
            ctx_ok, ctx_note = install_context(build, endpoint, known.get(build) or {}, out, e, registry_path)
            ok, note = ok and ctx_ok, note + ctx_note
            was = ((have.get(build) or {}).get("served") or {}).get(endpoint)
            if was != name:
                set_served(build, endpoint, name, out)
                lines.append(f"{build}: already pinned; served name on {endpoint} now {name!r} (was {was!r}){note}")
            else:
                lines.append(f"{build}: already pinned{note}")
            continue
        d = models_root / (e.get(dir_var) or dir_default)
        if not d.is_dir():
            ok = ok and build == EMBED_BUILD  # the embedder's absence is reported, the result is the pair's
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
            # the embedder with no manifest in the registry yet: reported, not a failure of the pair's install
            ok = ok and build == EMBED_BUILD and not want
            lines.append(f"{build}: {exc}")
            continue
        after = (
            "the embed service loads these weights and no others (D-429)"
            if build == EMBED_BUILD
            else "champion after trialbox eval qualify and --promote"
        )
        ctx_ok, ctx_note = install_context(build, endpoint, known.get(build) or {}, out, e, registry_path)
        ok = ok and ctx_ok
        lines.append(
            f"{build}: pinned {m.sha256[:12]} ({m.files} files) as candidate on {endpoint}; "
            f"{after}" + (f"; chat template {tpl['source']} at {tpl['revision']}" if tpl else "") + ctx_note
        )
    # the pair's pins against the length the profile's servers run with: refused here, before the night, not by the
    # gateway's model_mismatch on every call of it
    mismatched = context_problems(gpu, out, e, registry_path, deploy)
    return ok and not mismatched, lines + mismatched


def install_embedder(
    models_root: Path,
    out: Path = DEFAULT_OVERRIDE,
    env: dict[str, str] | None = None,
    registry_path: Path | None = None,
) -> tuple[bool, list[str]]:
    """Pin ``e-embed-1`` alone, for a box without a GPU (D-1066, D-998): a feasibility-only PRODUCTION box runs the
    embed service on the CPU, which refuses to start there without a pin (``EmbedderRefused``). Strict where
    ``install_pins`` tolerates the embedder: no weights, other weights, or a pin that is not the release's expected
    manifest each fail (the bundle carries the folder: ``tools/release.py`` refuses a site bundle without it)."""
    e = env or {}
    build, endpoint, dir_var, dir_default, name_var, name_default = EMBED_PIN
    d = models_root / (e.get(dir_var) or dir_default)
    name = e.get(name_var) or name_default
    have = (load_override(out).get("builds") or {}) if out.exists() else {}
    want = expected_of(_committed(registry_path)[1].get(build) or {})[0]
    pinned = (have.get(build) or {}).get("sha256")
    if pinned:
        if want and pinned != want:
            return False, [f"{build}: pinned {pinned[:12]} is not the expected manifest {want[:12]}: the embed service "
                           "refuses it; put the release's embedder in place and pin it again"]  # fmt: skip
        return True, [f"{build}: already pinned"]
    if not d.is_dir():
        return False, [f"{build}: no weights in {d}: every site bundle carries the embedder (D-1066), and a box "
                       "without a GPU pins it there; install from a bundle that carries it"]  # fmt: skip
    try:
        m, _ = pin(build, d, served_name=name, endpoint=endpoint, out=out, status="candidate",
                   registry_path=registry_path)  # fmt: skip
    except PinError as exc:
        return False, [f"{build}: {exc}"]
    return True, [f"{build}: pinned {m.sha256[:12]} ({m.files} files) as candidate on {endpoint}; the embed service "
                  "loads these weights and no others (D-429), on the CPU of a box without a GPU (D-1066)"]  # fmt: skip


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

    from registry.registry import SCREENING_ROLES, Registry, apply_override

    from tools.qualify import check_record

    if (why := rehearsal_box_refusal(out)) is not None:
        raise PinError(f"{build_id}: {why}")
    if ((load_override(out)["builds"].get(build_id) or {}).get("weights") or {}).get("trust") == PLACEHOLDER_TRUST:
        raise PinError(f"{build_id}: a rehearsal placeholder pin is never promoted (D-887): it is not a model")
    pinned_tpl = ((load_override(out)["builds"].get(build_id) or {}).get("weights") or {}).get("chat_template") or {}
    if pinned_tpl.get("trust") == "first_use":  # HW-005 (D-567)
        raise PinError(
            f"{build_id}: its chat template was trusted on first use and cannot be promoted; put the registry's "
            "file in place and run --install"
        )
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
    role, qualified = next((role, b) for role, b in rec["builds"].items() if b["build_id"] == build_id)
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
        "promoted_at": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),  # noqa: UP017
    }
    if role in SCREENING_ROLES and qualified.get("thinking_mode") == "on":
        entry["qualification"]["thinking_on_role"] = role
    committed, _ = _committed()
    Registry(apply_override(committed, doc))  # validates the merged registry; raises before writing
    _write_override(out, doc)
    return str(rec["record_id"])


SHIPPED_RECORDS = ROOT / "deploy" / "qualification"  # D-569: <profile>/<record>.json, in the bundle's host tree
IMAGES_LOCK = ROOT / "deploy" / "images.lock"


def _shipped_mismatch(rec: Any, gpu: str, builds: list[str], pins: dict[str, Any], lock_digest: str) -> str:
    """Why this record is not the qualification of this box's pinned pair (empty: it is)."""
    from tools.qualify import check_record

    problems = check_record(rec, profile=gpu, environment="PRODUCTION")
    if problems:
        return "; ".join(problems)
    by_build = {b["build_id"]: b for b in rec["builds"].values()}
    for build in builds:
        if build not in by_build:
            return f"the record does not name build {build}"
        if by_build[build].get("weights_sha256") != pins[build]["sha256"]:
            return (
                f"the record qualified other weights for {build} ({str(by_build[build].get('weights_sha256'))[:12]}) "
                f"than the pinned ones ({pins[build]['sha256'][:12]})"
            )
    detail = ((rec.get("steps") or {}).get("serving_record") or {}).get("detail") or {}
    image = detail.get("model_server_image") or {}
    if not image.get("digest"):
        return "the record does not name the model server image it was taken with (a record from before D-569)"
    if image["digest"] != lock_digest:
        return (
            f"the record was taken with model server image {str(image['digest'])[:19]}, this release pins "
            f"{lock_digest[:19]} (deploy/images.lock)"
        )
    for build in builds:
        pinned_tpl = ((pins[build].get("weights") or {}).get("chat_template") or {}).get("sha256")
        if not pinned_tpl:
            continue
        if not detail.get("chat_template_sha256"):
            return "the record does not name the judge's chat template it was taken with"
        if detail["chat_template_sha256"] != pinned_tpl:
            return (
                f"the record was taken with chat template {str(detail['chat_template_sha256'])[:12]}, the pin of "
                f"{build} holds {str(pinned_tpl)[:12]}"
            )
    return ""


PENDING_NAME = "shipped-promotion.pending.json"  # beside the override: a shipped promotion not yet canaried


def _pending(out: Path) -> dict[str, Any]:
    import json

    path = out.parent / PENDING_NAME
    try:
        doc = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError):
        return {"unreadable": True}
    return doc if isinstance(doc, dict) else {"unreadable": True}


def _qualified(entry: dict[str, Any]) -> bool:
    """The registry's rule for a champion that PRODUCTION routes (``Build.qualified_for_production``)."""
    q = entry.get("qualification") or {}
    return (
        entry.get("status") == "champion"
        and q.get("qualifies_production") is True
        and bool(entry.get("sha256"))
        and q.get("weights_sha256") == entry.get("sha256")
    )


def promote_shipped(
    gpu: str,
    records: Path = SHIPPED_RECORDS,
    out: Path = DEFAULT_OVERRIDE,
    *,
    images_lock: Path = IMAGES_LOCK,
    now: datetime | None = None,
) -> tuple[bool, list[str]]:
    """HW-003 (D-569): promote the profile's pinned pair from a shipped qualification record. One record under
    ``records/<gpu>/`` must pass ``check_record`` for the profile and PRODUCTION, name every build of the pair, and
    have qualified exactly the pinned weights, the model server image of ``images_lock`` and the chat template in
    the judge's pin. Every build is promoted from that one record, or none, and the promotion waits for the box's
    canary (:data:`PENDING_NAME`, :func:`confirm_shipped`). A pair that is champion on a shipped record is checked
    against that record again, and put back when the release no longer matches it. (ok, lines): not ok when the
    pair is not champion after the call."""
    import json

    from tools.qualify import PROFILES

    pairs = PROFILE_PAIRS.get(gpu)
    if pairs is None:
        return False, [f"no deployed pair for GPU profile {gpu!r}"]
    if gpu not in PROFILES:
        return False, [
            f"profile {gpu} has no qualification profile (tools/qualify.py), so no record can be shipped for it: "
            "the pair stays candidate until it is qualified on this box (RUNBOOK §11)"
        ]
    builds = [p[0] for p in pairs]
    known = _committed()[1]
    pins = (load_override(out).get("builds") or {}) if out.exists() else {}
    missing = [b for b in builds if not (pins.get(b) or {}).get("sha256")]
    if missing:
        return False, [f"{b}: not pinned in {out}: pin the pair first (--install)" for b in missing]
    for b in builds:  # a judge whose registry row names a template is never promoted without it in the pin
        if template_of(known.get(b) or {}) and not ((pins[b].get("weights") or {}).get("chat_template") or {}):
            return False, [f"{b}: pinned without the chat template its registry row names: run --install first"]
    lock = json.loads(images_lock.read_text(encoding="utf-8")) if images_lock.is_file() else {}
    digest = str(((lock.get("third_party") or {}).get("vllm") or {}).get("digest") or "")
    folder = records / gpu
    lines: list[str] = []
    if all(_qualified(pins[b]) for b in builds):
        # champion already. On a shipped record: the release may have changed since (an update): check it again
        shipped = {str((pins[b].get("qualification") or {}).get("record") or "") for b in builds}
        paths = [folder / name for name in shipped if name and (folder / name).is_file()]
        if len(shipped) == 1 and paths:
            try:
                why = _shipped_mismatch(json.loads(paths[0].read_text(encoding="utf-8")), gpu, builds, pins, digest)
            except (OSError, ValueError) as exc:
                why = f"not a readable qualification record ({exc})"
            if why:
                rid = str(pins[builds[0]]["qualification"].get("record_id"))
                return False, [f"{paths[0].name}: {why}", *demote_pair(gpu, out, record_id=rid)]
        if _pending(out):
            return True, [f"{b}: champion on a shipped record; the promotion waits for the canary" for b in builds]
        return True, [f"{b}: already champion on record {pins[b]['qualification'].get('record_id')}" for b in builds]
    files = sorted(folder.glob("*.json")) if folder.is_dir() else []
    if not files:
        return False, [
            f"no shipped qualification record for profile {gpu} in {folder}: the pair stays candidate and "
            "routes nothing in PRODUCTION (the vendor's record for these weights rides in the release under "
            "deploy/qualification/; or qualify on this box: RUNBOOK §11)"
        ]
    for path in files:
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            lines.append(f"{path.name}: not a readable qualification record ({exc})")
            continue
        why = _shipped_mismatch(rec, gpu, builds, pins, digest)
        if why:
            lines.append(f"{path.name}: {why}")
            continue
        before = out.read_text(encoding="utf-8")
        pending = out.parent / PENDING_NAME
        try:
            # written first: a promotion that is interrupted is found waiting for its canary, never "already"
            pending.write_text(json.dumps({"gpu": gpu, "record_id": rec["record_id"], "record": path.name}) + "\n",
                               encoding="utf-8")  # fmt: skip
            for build in builds:
                if not _qualified(pins[build]):
                    promote(build, path, out, now=now)
        except Exception as exc:  # both or neither, whatever went wrong
            out.write_text(before, encoding="utf-8")
            pending.unlink(missing_ok=True)
            lines.append(f"{path.name}: {exc}")
            continue
        detail = rec["steps"]["serving_record"]["detail"]
        return True, [
            *(
                f"{b}: champion on shipped record {rec['record_id']} ({path.name}); waits for the canary"
                for b in builds
            ),
            f"the record was taken on {detail.get('gpu') or rec.get('driver')} with driver "
            f"{detail.get('driver') or rec.get('driver')}: the canary on this box decides whether this card answers "
            "as that one did; on another driver or card edition, take a serving capture",
        ]
    return False, lines


def confirm_shipped(gpu: str, out: Path = DEFAULT_OVERRIDE) -> bool:
    """The box's canary passed after a shipped promotion: it no longer waits. False when nothing waited."""
    pending = out.parent / PENDING_NAME
    if not pending.is_file() or _pending(out).get("gpu") not in (gpu, None):
        return False
    pending.unlink()
    return True


def demote_pair(gpu: str, out: Path = DEFAULT_OVERRIDE, *, record_id: str | None = None) -> list[str]:
    """Put back to ``candidate`` the builds of the profile that the shipped record promoted (``record_id``; default:
    the promotion that waits for its canary), and drop their qualification reference (D-569). A build that is
    champion on another record (qualified on this box) is not touched. With neither (a demotion by hand, nothing
    waiting) every champion of the pair is put back. The weights' pins stay. One line per build
    put back; the waiting mark is removed."""
    from registry.registry import Registry, apply_override

    doc = load_override(out)
    rid = record_id or _pending(out).get("record_id")  # none: a demotion by hand of the whole pair
    lines = []
    for build, *_ in PROFILE_PAIRS.get(gpu) or []:
        entry = doc["builds"].get(build)
        if not entry or entry.get("status") != "champion":
            continue
        if rid and (entry.get("qualification") or {}).get("record_id") != rid:
            continue
        entry["status"] = "candidate"
        entry.pop("qualification", None)
        lines.append(f"{build}: back to candidate (its qualification reference is removed; the weights stay pinned)")
    if lines:
        Registry(apply_override(_committed()[0], doc))  # validates the merged registry; raises before writing
        _write_override(out, doc)
    (out.parent / PENDING_NAME).unlink(missing_ok=True)
    return lines


# ------------------------------------------------------------------------------------------------ resolve (D-738)
@dataclass(frozen=True)
class RouteRow:
    """One role and data class on PRODUCTION: the build the gateway would call, or why none."""

    role: str
    data_class: str
    route: str | None
    alias: str | None
    endpoint: str | None
    build: str | None
    served: str | None
    refusals: list[str]


def resolve_roles(
    registry: Any, policy: Any, env: dict[str, str], classes: tuple[str, ...] = ("D1", "D3")
) -> list[RouteRow]:
    """PIN-RESOLVE (D-738), lane G's blocker 6: the gateway's own path for each role of the routing table and each
    data class, on PRODUCTION with the box's topology and profile: the route and its candidates
    (``RoutingPolicy.candidates``, the no-fallback rule of a patient role included, D-276), then the registry's
    resolution of each candidate in order (``Registry.resolve``). A candidate the registry refuses is passed, as the
    gateway passes it; nothing is sent to a model."""
    from gateway.core import GatewayConfig
    from gateway.policy import Refusal
    from registry.registry import RegistryError
    from tb_common.policy.classes import Environment
    from tb_contracts.dataclass import ClassLabel, DataClass

    cfg = GatewayConfig.from_env({**env, "TB_ENV": "PRODUCTION"})
    rows: list[RouteRow] = []
    for role in sorted(r for r in policy.roles if not r.startswith("shadow:") and "*" not in r):
        for cls in classes:
            label = ClassLabel(data_class=DataClass(cls))
            try:
                route, cands = policy.candidates(role, label, cfg.topology, Environment.PRODUCTION, cfg.profile,
                                                 cloud_opt_in=cfg.cloud_opt_in)  # fmt: skip
            except Refusal as exc:
                rows.append(RouteRow(role, cls, None, None, None, None, None, [f"{exc.reason}: {exc}"]))
                continue
            if policy.no_fallback(route, role):
                cands = [c for c in cands if c.alias == route.builds[0][0]]
            refusals: list[str] = []
            row = RouteRow(role, cls, route.id, None, None, None, None, refusals)
            for c in cands:
                try:
                    res = registry.resolve(c.alias, c.endpoint.name, role=role, env=Environment.PRODUCTION)
                except RegistryError as exc:
                    refusals.append(f"{c.alias}@{c.endpoint.name}: {exc.reason}: {exc}")
                    continue
                row = RouteRow(role, cls, route.id, c.alias, c.endpoint.name, res.build.build_id, res.served_name,
                               refusals)  # fmt: skip
                break
            else:
                if not cands:
                    refusals.append(f"no_eligible_build: route {route.id}'s first build may not take {cls}")
            rows.append(row)
    return rows


def _env_file(path: Path | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if path is None or not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip("\"'")
    return out


def resolve_main(env_file: Path | None, out: Path, require: list[str]) -> int:
    """``--resolve``: one line a role and class; exit 1 when a ``--require`` role does not route on D3."""
    import os

    from gateway.policy import RoutingPolicy
    from registry.registry import Registry

    env = {k: v for k, v in os.environ.items() if k.startswith("TB_")}
    env.update(_env_file(env_file))
    env["TB_REGISTRY_OVERRIDE"] = str(out)
    policy = RoutingPolicy.load(Path(env["TB_ROUTING_PATH"])) if env.get("TB_ROUTING_PATH") else RoutingPolicy.load()
    rows = resolve_roles(Registry.from_env(env), policy, env)
    print(f"PRODUCTION, topology {env.get('TB_TOPOLOGY', 'A')}, profile {env.get('TB_PROFILE', 'P-GB10')}, "
          f"site pins {out}{'' if out.is_file() else ' (none)'}")  # fmt: skip
    for r in rows:
        if r.build:
            print(f"{r.role} {r.data_class} -> {r.build} ({r.alias}@{r.endpoint}, served {r.served}; route {r.route})")
        else:
            print(
                f"{r.role} {r.data_class} -> none (route {r.route or '-'}): {'; '.join(r.refusals) or 'no candidate'}"
            )
    bad = [n for n in require if not any(r.role == n and r.data_class == "D3" and r.build for r in rows)]
    for n in bad:
        print(f"pin_model: {n} does not route on D3 in PRODUCTION", file=sys.stderr)
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", help="build_id in models/registry.yaml")
    ap.add_argument("--model-dir", type=Path)
    ap.add_argument(
        "--context",
        type=int,
        metavar="N",
        help="with --build: the length the model server runs with, for a build whose registry row names no "
        "context_length (LLM-007)",
    )
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
    ap.add_argument(
        "--promote-shipped",
        metavar="GPU",
        help="promote the profile's pinned pair from a shipped record (D-569); exit 0 promoted and waiting for the "
        "canary, 3 no record matches, 4 the pair was champion already",
    )
    ap.add_argument("--records", type=Path, default=SHIPPED_RECORDS, help="--promote-shipped: the records' folder")
    ap.add_argument("--images-lock", type=Path, default=IMAGES_LOCK, help="--promote-shipped: deploy/images.lock")
    ap.add_argument("--demote-pair", metavar="GPU", help="put the profile's promoted pair back to candidate (D-569)")
    ap.add_argument("--confirm-shipped", metavar="GPU", help="the canary passed after --promote-shipped (D-569)")
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
    ap.add_argument(
        "--install-embedder",
        action="store_true",
        help="pin e-embed-1 alone from --models-root (install.sh, a box without a GPU, D-1066); exit 1 when it is not",
    )
    ap.add_argument("--registry", type=Path, default=None, help="the release registry (default models/registry.yaml)")
    ap.add_argument("--models-root", type=Path, default=ROOT / "deploy" / "models")
    ap.add_argument(
        "--deploy",
        type=Path,
        default=None,
        help="--install: the box's deploy folder, whose docker-compose.<gpu>.yml gives the servers' length "
        "(default: the folder above --models-root, as installed.json is found)",
    )
    ap.add_argument(
        "--name-judge", metavar="GPU", help="print the judge GPU profile serves (install.sh); write nothing"
    )
    ap.add_argument("--resolve", action="store_true", help="print the build PRODUCTION routes each role to (D-738)")
    ap.add_argument("--env-file", type=Path, default=None, help="--resolve: the box's deploy/.env (topology, profile)")
    ap.add_argument("--require", action="append", default=[], help="--resolve: exit 1 unless this role routes on D3")
    args = ap.parse_args(argv)
    if args.resolve:
        return resolve_main(args.env_file, args.out, args.require)
    if args.name_judge:
        try:
            print(judge_line(args.name_judge, args.out))
        except PinError as exc:
            print(f"pin_model: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.promote_shipped:
        if (why := rehearsal_box_refusal(args.out)) is not None:  # a note for the installer, as a placeholder is
            print(f"{why}; no shipped record is looked for")
            return 5
        pinned = (load_override(args.out).get("builds") or {}) if args.out.exists() else {}
        trusts = {b: ((e or {}).get("weights") or {}).get("trust") for b, e in pinned.items()}
        held = sorted(b for b, t in trusts.items() if t == PLACEHOLDER_TRUST)
        if held:  # D-887: never promoted, so nothing to look for: said, and the installer takes it as a note
            print(f"{', '.join(held)}: rehearsal placeholder, never promoted; no shipped record is looked for (D-887)")
            return 5
        try:
            good, lines = promote_shipped(args.promote_shipped, args.records, args.out, images_lock=args.images_lock)
        except (PinError, ValueError) as exc:
            print(f"pin_model: {exc}", file=sys.stderr)
            return 2
        print("\n".join(lines))
        if good and all("already champion" in ln for ln in lines):
            return 4  # champion before, and nothing waits for a canary: the install leaves the pair alone
        return 0 if good else 3
    if args.confirm_shipped:
        return 0 if confirm_shipped(args.confirm_shipped, args.out) else 1
    if args.demote_pair:
        try:
            print("\n".join(demote_pair(args.demote_pair, args.out)))
        except (PinError, ValueError) as exc:
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
    if args.install_embedder:
        import os

        try:
            good, lines = install_embedder(args.models_root, args.out, dict(os.environ), args.registry)
        except PinError as exc:
            print(f"pin_model: {exc}", file=sys.stderr)
            return 2
        print("\n".join(lines))
        return 0 if good else 1
    if args.install:
        import os

        deploy = args.deploy or args.models_root.parent
        try:
            good, lines = install_pins(args.install, args.models_root, args.out, dict(os.environ),
                                       with_embedder=True, deploy=deploy)  # fmt: skip
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
    if args.context is not None and args.context <= 0:
        print(f"pin_model: --context is a whole number above zero, not {args.context}", file=sys.stderr)
        return 2
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
    if args.context is not None:
        try:
            set_context(args.build, args.context, args.out)
        except (PinError, ValueError) as exc:
            print(f"pin_model: {exc}", file=sys.stderr)
            return 2
        print(f"{args.build}: context {args.context}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
