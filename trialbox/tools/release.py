"""Release identity (T-110b, D-340): the version, the tag, and ``release.json``, the record of one signed bundle.

    python -m tools.release version            # the version, from pyproject.toml (the one place it is written)
    python -m tools.release tag                # the release tag for it: trialbox-v<version>
    python -m tools.release build --id 2026.11-1 --release-seq 3 --gates build/supply-chain/gates.json \\
        --sbom-dir dist/sbom --out-dir STAGE/meta --image REF=ARCHIVE ... -- kind:path=dest ...
    python -m tools.release check dist/trialbox-2026.11-1.tar

``build`` is run by ``tools/make_bundle.sh`` once the images are saved. It refuses to write anything unless every
saved image (by the config digest inside its archive, which is its image id) is a passing image of a gate record of
at most seven days (the same rule as ``tools.supply_chain bundle-check``), and every image has the SBOM that record
names, with the same sha256. It then writes into ``--out-dir``:

* ``release.json`` (``schemas/release.schema.json``): version, release id and sequence, source commit and tag, the
  gate record's sha256, every image (tag, config digest, source reference, platform, archive, SBOM), every SBOM, and
  every payload file of the bundle with its sha256 and size;
* ``images.lock``: the release's image lock: ``deploy/images.lock`` with each image's digest filled, plus every other
  image of the bundle, so that ``verify_update.py`` finds the two files agreeing (D-210);
* ``sbom/``: the SBOMs, licence report and SBOM index copied from ``--sbom-dir`` and the gate record; and
  ``items.txt``, the extra ``kind:path=dest`` items the bundle must carry for them.

``check`` opens a built bundle and fails unless its ``release.json`` is valid and names every payload file with the
sha256 the signed manifest gives it, and every image archive with its SBOM in the bundle.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib
from collections.abc import Collection, Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
IMAGES_LOCK = ROOT / "deploy" / "images.lock"
FORMAT = "trialbox-release/1"
TAG_PREFIX = "trialbox-v"
KINDS = ("model", "ruleset", "image", "refdata", "other", "host", "terminology")
# V-18 (D-1182): a terminology payload is a code system the box may carry, under the loader command that loads it
# (``<command>/<file>``); a licensed system (LOINC, WHO ICD-10, ATC, SNOMED CT, the UMLS) never goes in a bundle
TERMINOLOGY_COMMANDS = ("icd10cm", "icd10pcs", "nhi-drugs", "nhi-services")
# what the bundle carries next to the image SBOMs (tools/supply_chain release-gates writes them in the SBOM folder)
SBOM_EXTRAS = ("requirements.lock.cdx.json", "licences.md", "index.json")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class ReleaseError(Exception):
    """The release cannot be built or does not hold together."""


# ------------------------------------------------------------------------------------------------ identity
def version(pyproject: Path = PYPROJECT) -> str:
    """The version of the release: ``[project] version`` in pyproject.toml, the only place it is written."""
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    v = data.get("project", {}).get("version")
    if not isinstance(v, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+([.+-][0-9A-Za-z.-]+)?", v):
        raise ReleaseError(f"{pyproject}: [project] version {v!r} is not a release version")
    return v


def tag_for(v: str) -> str:
    return f"{TAG_PREFIX}{v}"


def _git(*args: str) -> str | None:
    try:
        proc = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=False)
    except OSError:
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def tree_changes(root: Path | None = None) -> list[str]:
    """What makes the checkout of ``root`` differ from its commit (D-631): every changed, staged or untracked (not
    ignored) file of the project folder, as ``git status --porcelain`` names it, and every file git was told not to
    look at (``assume-unchanged``, ``skip-worktree``: ``git status`` is silent on those). Empty: the tree is its
    commit. A folder that is no checkout is not a commit either. ``tools/make_bundle.sh`` asks git the same and
    refuses to build; the host tree is packed from the files on disk, untracked ones included."""
    root = root or ROOT
    git = ["git", "-C", str(root), "-c", "core.quotePath=false"]
    try:
        st = subprocess.run([*git, "status", "--porcelain", "--untracked-files=all", "--", "."],
                            capture_output=True, text=True, check=False)  # fmt: skip
        hid = subprocess.run([*git, "ls-files", "-v", "--", "."], capture_output=True, text=True, check=False)
    except OSError:
        return ["not a git checkout: a release is built from a commit"]
    if st.returncode != 0 or hid.returncode != 0:
        return ["not a git checkout: a release is built from a commit"]
    out = [ln for ln in st.stdout.splitlines() if ln.strip()]
    out += [
        f"{ln}   (hidden from git: assume-unchanged or skip-worktree)"
        for ln in hid.stdout.splitlines()
        if re.match(r"([a-z]|S) ", ln)
    ]
    return out


def source(v: str) -> dict[str, Any]:
    """The commit the release is built from, whether the tree had changes (an untracked file is one, D-631), and
    the release tag when HEAD has it."""
    commit = _git("rev-parse", "HEAD")
    status = tree_changes(ROOT)
    tags = (_git("tag", "--points-at", "HEAD") or "").split()
    return {
        "commit": commit if commit and re.fullmatch(r"[0-9a-f]{40}", commit) else None,
        "dirty": bool(status),
        "tag": tag_for(v) if tag_for(v) in tags else None,
    }


# ------------------------------------------------------------------------------------------------ helpers
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def parse_item(text: str) -> tuple[str, Path, str]:
    """``kind:path[=dest]`` as ``tools/sign_bundle.py`` takes it."""
    kind, _, rest = text.partition(":")
    src, _, dest = rest.partition("=")
    if kind not in KINDS or not src:
        raise ReleaseError(f"bad bundle item {text!r} (kind:path[=dest], kind one of {', '.join(KINDS)})")
    out = dest or Path(src).name
    if kind == "terminology" and (out.split("/", 1)[0] not in TERMINOLOGY_COMMANDS or "/" not in out):
        raise ReleaseError(f"bad bundle item {text!r}: a terminology file goes in as <command>/<file>, the command one "
                           f"of {', '.join(TERMINOLOGY_COMMANDS)} (a licensed code system never ships)")  # fmt: skip
    return kind, Path(src), out


def archive_configs(archive: Path) -> dict[str, str]:
    """A ``docker save`` archive's ``{tag: config digest}`` (manifest.json; ``Config`` is ``<hex>.json`` or
    ``blobs/sha256/<hex>``)."""
    try:
        with tarfile.open(archive) as tf:
            member = tf.extractfile("manifest.json")
            if member is None:
                raise ReleaseError(f"{archive.name}: no manifest.json (not a docker save archive)")
            entries = json.loads(member.read())
    except (OSError, KeyError, tarfile.TarError, json.JSONDecodeError) as exc:
        raise ReleaseError(f"{archive.name}: cannot read its manifest.json ({exc})") from exc
    out: dict[str, str] = {}
    for e in entries if isinstance(entries, list) else []:
        name = str(e.get("Config", "")).rsplit("/", 1)[-1].removesuffix(".json")
        digest = f"sha256:{name}" if re.fullmatch(r"[0-9a-f]{64}", name) else ""
        for t in e.get("RepoTags") or []:
            out[str(t)] = digest
    if not out or not all(out.values()):
        raise ReleaseError(f"{archive.name}: the archive names no tagged image with a config digest")
    return out


def _manifest_entries(archive: Path) -> list[dict[str, Any]]:
    try:
        with tarfile.open(archive) as tf:
            member = tf.extractfile("manifest.json")
            entries = json.loads(member.read()) if member is not None else []
    except (OSError, KeyError, tarfile.TarError, json.JSONDecodeError) as exc:
        raise ReleaseError(f"{archive.name}: cannot read its manifest.json ({exc})") from exc
    return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []


def archive_platform(archive: Path) -> str | None:
    """``os/architecture`` of the image in a ``docker save`` archive, from its config (what the box will load), or
    None when the config names none."""
    entries = _manifest_entries(archive)
    if not entries:
        return None
    try:
        with tarfile.open(archive) as tf:
            member = tf.extractfile(str(entries[0].get("Config", "")))
            cfg = json.loads(member.read()) if member is not None else {}
    except (OSError, KeyError, tarfile.TarError, json.JSONDecodeError):
        return None
    arch = cfg.get("architecture") if isinstance(cfg, dict) else None
    return f"{cfg.get('os') or 'linux'}/{arch}" if arch else None


def archive_image_count(archive: Path) -> int:
    """How many images a ``docker save`` archive holds: every ``manifest.json`` entry, tagged or not (an untagged
    second image has no tag for :func:`archive_configs` to see)."""
    return len({str(e.get("Config", "")) for e in _manifest_entries(archive)})


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_MAX_MANIFEST_BYTES = 4 * 1024 * 1024  # an image index or manifest is a few kilobytes; a layer is never read


def _leads_to(tf: tarfile.TarFile, names: set[str], digest: str, config: str, depth: int = 0) -> bool:
    """Does the blob ``digest`` of the archive (an index or a manifest) name ``config``, itself or through the
    manifests it lists? The blob's bytes must hash to its name."""
    name = f"blobs/sha256/{digest.removeprefix('sha256:')}"
    if depth > 3 or not _DIGEST.fullmatch(digest) or name not in names:
        return False
    info = tf.getmember(name)
    if not info.isfile() or info.size > _MAX_MANIFEST_BYTES:
        return False
    member = tf.extractfile(info)
    data = member.read() if member is not None else b""
    if "sha256:" + hashlib.sha256(data).hexdigest() != digest:
        return False
    try:
        doc = json.loads(data)
    except json.JSONDecodeError:
        return False
    if not isinstance(doc, dict):
        return False
    if isinstance(doc.get("config"), dict) and doc["config"].get("digest") == config:
        return True
    return any(
        isinstance(m, dict) and _leads_to(tf, names, str(m.get("digest")), config, depth + 1)
        for m in doc.get("manifests") or []
    )


def archive_identities(archive: Path) -> tuple[str, ...]:
    """Every digest that names the one image of a ``docker save`` archive: its config digest and, when the archive
    holds exactly one image, each digest of its ``index.json`` whose blob in the archive leads to that config
    (OPS-004, D-570). Docker's image id, which the release gates record, is the config digest on the classic image
    store and the index digest on the containerd store. ``index.json`` is text: a digest counts only when the
    archive's own blobs bind it to the image's content. With more than one image in the archive (an untagged one
    counts) only the config digest is returned."""
    configs = sorted(set(archive_configs(archive).values()))
    if len(configs) != 1 or archive_image_count(archive) != 1:
        return tuple(configs)
    config = configs[0]
    try:
        with tarfile.open(archive) as tf:
            names = set(tf.getnames())
            member = tf.extractfile("index.json") if "index.json" in names else None
            index = json.loads(member.read()) if member is not None else {}
            listed = [str(m.get("digest")) for m in (index.get("manifests") or []) if isinstance(m, dict)]
            more = [d for d in listed if d != config and _leads_to(tf, names, d, config)]
    except (OSError, KeyError, tarfile.TarError, json.JSONDecodeError) as exc:
        raise ReleaseError(f"{archive.name}: cannot read its index.json ({exc})") from exc
    return (config, *dict.fromkeys(more))


def gate_entry(by_id: dict[Any, dict[str, Any]], archive: Path) -> dict[str, Any] | None:
    """The gate record's entry (keyed by its ``image_id``) for the image of ``archive``, or None."""
    return next((by_id[i] for i in archive_identities(archive) if i in by_id), None)


def repository(ref: str) -> str:
    ref = ref.split("@", 1)[0]
    head, _, last = ref.rpartition("/")
    name = last.split(":", 1)[0]
    return f"{head}/{name}" if head else name


def image_name(ref: str, lock: dict[str, Any]) -> str:
    """The key of an image in release.json and images.lock: the lock's name when the lock pins this reference
    (``db``), else ``py`` for ``trialbox-py``, else the repository's last part (``hapi``, ``vllm-openai``)."""
    for name, entry in (lock.get("images") or {}).items():
        if isinstance(entry, dict) and entry.get("image") == ref:
            return str(name)
    last = repository(ref).rsplit("/", 1)[-1]
    return last.removeprefix("trialbox-") if last.startswith("trialbox-") else last


def gate_problems(
    record: Any, configs: Mapping[str, str | tuple[str, ...]], now: dt.datetime | None = None
) -> list[str]:
    """The release gates' own rule (``tools.supply_chain.release.bundle_problems``) over the archives' digests
    (one, or every digest that names the archive's image: :func:`archive_identities`)."""
    from tools.supply_chain.release import bundle_problems

    return bundle_problems(record, configs, now=now)


# ------------------------------------------------------------------------------------------------ build
def build(
    *,
    release_id: str,
    release_seq: int,
    gates: Path,
    sbom_dir: Path,
    out_dir: Path,
    images: list[tuple[str, Path]],
    items: list[tuple[str, Path, str]],
    images_lock: Path = IMAGES_LOCK,
    now: dt.datetime | None = None,
    pyproject: Path = PYPROJECT,
    rehearsal: bool = False,
    jobs: Collection[str] = (),
    platform: str | None = None,
) -> dict[str, Any]:
    """Check the bundle's images against the gate record, collect their SBOMs, write release.json and images.lock.

    ``images``: (requested reference, saved archive); the archive must also be one of ``items`` (kind ``image``).
    ``platform`` (``os/arch``, make_bundle.sh ``--platform``): every archive must be an image of it; each image's
    ``platform`` in release.json is its archive's own, which the update path compares with the host."""
    now = now or dt.datetime.now(dt.UTC)
    v = version(pyproject)
    if stray := sorted(set(jobs) - {ref for ref, _ in images}):
        raise ReleaseError(f"job image(s) {', '.join(stray)}: not an image of the bundle")
    if not images:
        raise ReleaseError("the bundle carries no image")
    try:
        record_bytes = gates.read_bytes()
        record = json.loads(record_bytes)
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseError(f"no readable gate record {gates}: {exc}") from exc
    lock = json.loads(images_lock.read_text(encoding="utf-8"))
    dest_of = {src.resolve(): dest for kind, src, dest in items if kind == "image"}

    # 1. every saved image passed the gates, by the digest inside its archive (what the box will load)
    saved: list[tuple[str, Path, str, str]] = []  # (requested ref, archive, tag in archive, config digest)
    for ref, archive in images:
        if archive.resolve() not in dest_of:
            raise ReleaseError(f"{ref}: its archive {archive.name} is not an image item of the bundle")
        configs = archive_configs(archive)
        count = max(len(set(configs.values())), archive_image_count(archive))  # an untagged image counts (D-570)
        if count != 1:
            raise ReleaseError(f"{archive.name}: one image per archive (found {count})")
        tag, digest = sorted(configs.items())[0]
        got = archive_platform(archive)
        if platform and got != platform:
            raise ReleaseError(
                f"{ref}: its archive is an image for {got or 'no named platform'}, the bundle is for {platform} (a "
                "local image of another architecture: pull it with --platform)"
            )
        saved.append((ref, archive, tag, digest))
    problems = gate_problems(record, {f"{ref} ({tag})": archive_identities(a) for ref, a, tag, _ in saved}, now=now)
    if problems:
        raise ReleaseError("; ".join(problems))

    # 2. the SBOM of each image, as the record names it, copied into the bundle unchanged
    by_id: dict[str, dict[str, Any]] = {}
    for e in record.get("images", []):
        if e.get("ok") and e.get("image_id"):
            by_id.setdefault(str(e["image_id"]), e)
    sbom_out = out_dir / "sbom"
    sbom_out.mkdir(parents=True, exist_ok=True)
    extra_items: list[tuple[str, Path, str]] = []
    sboms: list[dict[str, Any]] = []

    def take_sbom(name: str, want: str | None, subject: str) -> str:
        src = sbom_dir / name
        if not src.is_file():
            raise ReleaseError(f"{subject}: its SBOM {name} is not in {sbom_dir}")
        got = sha256_file(src)
        if want is not None and got != want:
            raise ReleaseError(f"{subject}: SBOM {name} has sha256 {got}, the gate record says {want}")
        dst = sbom_out / name
        if not dst.exists():
            shutil.copyfile(src, dst)
            extra_items.append(("other", dst, f"sbom/{name}"))
            sboms.append({"path": f"sbom/{name}", "sha256": got, "subject": subject})
        return got

    rel_images: dict[str, dict[str, Any]] = {}
    for ref, archive, tag, digest in saved:
        entry = gate_entry(by_id, archive)  # by any digest that names the image (D-570: either image store)
        if entry is None or not entry.get("sbom"):
            raise ReleaseError(f"{ref}: the gate record names no SBOM for image {digest}")
        sha = take_sbom(str(entry["sbom"]), entry.get("sbom_sha256"), tag)
        name = image_name(tag, lock)
        if name in rel_images:
            raise ReleaseError(f"two images of the bundle have the name {name!r} ({rel_images[name]['image']}, {tag})")
        rel_images[name] = {
            "image": tag,
            "digest": digest,
            "source": ref,
            "platform": archive_platform(archive) or entry.get("platform"),
            "repo_digests": sorted(entry.get("repo_digests") or []),
            "archive": dest_of[archive.resolve()],
            "sbom": f"sbom/{entry['sbom']}",
            "sbom_sha256": sha,
            # D-968: a job image (the nightly backup) runs as a one-off container, no compose service runs it
            "runs": "job" if ref in jobs else "service",
        }
    for name in SBOM_EXTRAS:
        if not (sbom_dir / name).is_file():
            raise ReleaseError(f"{name} is not in {sbom_dir} (make release-gates writes it)")
        take_sbom(name, None, "requirements.lock" if name.endswith(".cdx.json") else "release")

    # the gate record itself, so the site can read what was scanned and how (release.json carries its sha256)
    shutil.copyfile(gates, sbom_out / "gates.json")
    extra_items.append(("other", sbom_out / "gates.json", "sbom/gates.json"))

    # 3. the release's image lock: the repository's lock with the digests filled, and the bundle's other images
    bundle_lock: dict[str, Any] = {k: v2 for k, v2 in lock.items() if k != "images"}
    bundle_lock["images"] = {}
    for name, img in sorted(rel_images.items()):
        base = dict((lock.get("images") or {}).get(name) or {})
        base.update(image=img["image"], digest=img["digest"])
        bundle_lock["images"][name] = base

    # 4. every payload file of the bundle (SBOMs included), each with its sha256 and size
    components = [
        {"path": dest, "kind": kind, "sha256": sha256_file(src), "size": src.stat().st_size}
        for kind, src, dest in [*items, *extra_items]
    ]
    paths = [dest for _, _, dest in [*items, *extra_items]]
    if len(paths) != len(set(paths)):
        raise ReleaseError(f"two bundle files share a path: {sorted({p for p in paths if paths.count(p) > 1})}")
    rel = {
        "format": FORMAT,
        "product": "trialbox",
        "version": v,
        "release_id": release_id,
        "release_seq": release_seq,
        "created_at": now.isoformat(timespec="seconds"),
        "source": source(v),
        "gates": {
            "record_sha256": hashlib.sha256(record_bytes).hexdigest(),
            "created": str(record.get("created")),
            "ok": True,
            "vuln_mode": str(record.get("vuln_mode", "block")),
        },
        "images": rel_images,
        "sboms": sboms,
        "components": components,
    }
    if rehearsal:  # D-726: a bundle for a rehearsal box; a PRODUCTION or VALIDATION box refuses it
        rel["rehearsal"] = True
    from tb_contracts import validate

    validate("release", rel)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "release.json").write_text(json.dumps(rel, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "images.lock").write_text(json.dumps(bundle_lock, indent=2) + "\n", encoding="utf-8")
    (out_dir / "items.txt").write_text("".join(f"{k}:{s}={d}\n" for k, s, d in extra_items), encoding="utf-8")
    return rel


# ------------------------------------------------------------------------------------------------ check
def problems(release: Any, manifest: dict[str, Any], lock: Any = None) -> list[str]:
    """What a bundle's release.json fails to name, against its signed manifest (and images.lock)."""
    from tb_contracts import validate

    out: list[str] = []
    try:
        validate("release", release)
    except Exception as exc:
        return [f"release.json is not a valid release record: {str(exc)[:300]}"]
    files = {str(f["path"]): f for f in manifest.get("files", [])}
    comps = {str(c["path"]): c for c in release["components"]}
    for path, f in sorted(files.items()):
        c = comps.get(path)
        if c is None:
            out.append(f"{path}: in the bundle but not named by release.json")
        elif c["sha256"] != f.get("sha256") or c["kind"] != f.get("kind"):
            out.append(
                f"{path}: release.json gives {c['kind']} {c['sha256']}, the manifest {f.get('kind')} {f.get('sha256')}"
            )
    out += [f"{p}: named by release.json but not in the bundle" for p in sorted(set(comps) - set(files))]
    archives = {img["archive"] for img in release["images"].values()}
    out += [f"{p}: an image archive release.json does not pin" for p, f in sorted(files.items())
            if f.get("kind") == "image" and p not in archives]  # fmt: skip
    for name, img in sorted(release["images"].items()):
        if img["archive"] not in files:
            out.append(f"image {name}: archive {img['archive']} is not in the bundle")
        sb = files.get(img["sbom"])
        if sb is None:
            out.append(f"image {name}: SBOM {img['sbom']} is not in the bundle")
        elif sb.get("sha256") != img["sbom_sha256"]:
            out.append(f"image {name}: SBOM {img['sbom']} sha256 differs from release.json")
        if not _DIGEST.match(str(img.get("digest"))):
            out.append(f"image {name}: no digest")
    if release.get("release_seq") != manifest.get("release_seq"):
        seq, mseq = release.get("release_seq"), manifest.get("release_seq")
        out.append(f"release_seq {seq} differs from the manifest's {mseq}")
    if lock is not None:
        from tools.update_status import images_problems

        out += images_problems(release, lock)
    return out


def embedder_problems(
    release: dict[str, Any], manifest: dict[str, Any], registry_path: Path | None = None
) -> list[str]:
    """D-1066 (D-998): a bundle for a site carries the embedder, ``e-embed-1``, whole in ``embedder/``: a box without
    a GPU (a feasibility-only site, a PRODUCTION product form) pins it at install, and every box's embed service loads
    it. Its files, as the signed manifest lists them, must hash to the registry's expected manifest (the pin's own
    format, ``tools.pin_model.manifest_sha256_of_files``). A rehearsal bundle, which a site box refuses (D-726), is
    exempt: its placeholders are no model."""
    import yaml

    from tools.pin_model import EMBED_BUILD, expected_of, manifest_sha256_of_files

    if release.get("rehearsal") is True:
        return []
    # H-95: a software pack carries no weights; the embedder's ride in its model pack, checked there
    if (manifest.get("pack") or {}).get("kind") == "software":
        return []
    # TB_RELEASE_REGISTRY: the unit tests' synthetic registry only (a release reads the one it ships)
    path = registry_path or Path(os.environ.get("TB_RELEASE_REGISTRY") or ROOT / "models" / "registry.yaml")
    reg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    row: dict[str, Any] = next((b for b in reg.get("builds") or [] if b.get("build_id") == EMBED_BUILD), {})
    want = expected_of(row)[0]
    files = [{"path": str(f["path"]).removeprefix("embedder/"), "sha256": f.get("sha256")}
             for f in manifest.get("files", []) if str(f.get("path", "")).startswith("embedder/")]  # fmt: skip
    if not files:
        what = f"{row.get('repository', '?')} at {str(row.get('revision', '?'))[:12]}"
        return [
            f"embedder/: the bundle carries no {EMBED_BUILD} ({what}, the whole folder the registry's expected "
            "manifest names); every site bundle carries it (D-1066): pass its folder as embedder/ under make_bundle.sh "
            "--models"
        ]
    got = manifest_sha256_of_files(files)
    if want and got != want:
        return [f"embedder/: these {len(files)} files are not the release's {EMBED_BUILD}: manifest {got[:12]} "
                f"differs from the expected {want[:12]} in models/registry.yaml"]  # fmt: skip
    return []


def gates_mode_line(bundle: Path) -> str:
    """D-884: the gates' vuln mode as ``release check`` says it; "report" is never read as a green release."""
    try:
        with tarfile.open(bundle) as tf:
            m = tf.extractfile("release.json")
            rel = json.loads(m.read()) if m is not None else {}
    except (OSError, KeyError, tarfile.TarError, json.JSONDecodeError):
        return "gates mode unknown"
    mode = str(((rel or {}).get("gates") or {}).get("vuln_mode") or "unknown")
    return f"gates {mode}" if mode == "block" else f"gates {mode}: not a green release"


def check_bundle(bundle: Path) -> list[str]:
    """Open a signed bundle (tools/sign_bundle.py layout) and check its release.json against the manifest."""
    try:
        with tarfile.open(bundle) as tf:

            def read(name: str) -> Any:
                m = tf.extractfile(name)
                return None if m is None else json.loads(m.read())

            names = set(tf.getnames())
            manifest = read("manifest.json")
            release = read("release.json") if "release.json" in names else None
            lock = read("images.lock") if "images.lock" in names else None
            payload = {n.removeprefix("files/") for n in names if n.startswith("files/")}
    except (OSError, KeyError, tarfile.TarError, json.JSONDecodeError) as exc:
        return [f"{bundle}: cannot read the bundle ({exc})"]
    if release is None:
        return ["the bundle carries no release.json"]
    out = problems(release, manifest, lock)
    out += embedder_problems(release, manifest)
    listed = {str(f["path"]) for f in manifest.get("files", [])}
    out += [f"{p}: a payload file the manifest does not list" for p in sorted(payload - listed)]
    return out


# ------------------------------------------------------------------------------------------------ CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("version", help="the release version (pyproject.toml)")
    sub.add_parser("tag", help="the release tag for the version")
    b = sub.add_parser("build", help="release.json and images.lock for a bundle (tools/make_bundle.sh)")
    b.add_argument("--id", required=True)
    b.add_argument("--release-seq", type=int, required=True)
    b.add_argument("--gates", type=Path, required=True, help="the passing gate record (make release-gates)")
    b.add_argument("--sbom-dir", type=Path, required=True)
    b.add_argument("--out-dir", type=Path, required=True)
    b.add_argument("--images-lock", type=Path, default=IMAGES_LOCK)
    b.add_argument("--image", action="append", default=[], metavar="REF=ARCHIVE")
    b.add_argument("--rehearsal", action="store_true", help="a bundle for a rehearsal box only (D-726)")
    b.add_argument("--job", action="append", default=[], metavar="REF", help="an --image the box runs as a job (D-968)")
    b.add_argument("--platform", default=None, help="os/arch every image archive must be (make_bundle.sh --platform)")
    b.add_argument("items", nargs="*", help="kind:path[=dest], every payload file of the bundle")
    c = sub.add_parser("check", help="does a built bundle's release.json name every component?")
    c.add_argument("bundle", type=Path)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "version":
            print(version())
        elif args.cmd == "tag":
            print(tag_for(version()))
        elif args.cmd == "build":
            imgs = []
            for text in args.image:
                ref, sep, archive = text.rpartition("=")
                if not sep or not ref:
                    raise ReleaseError(f"--image {text!r}: REF=ARCHIVE")
                imgs.append((ref, Path(archive)))
            rel = build(
                release_id=args.id,
                release_seq=args.release_seq,
                gates=args.gates,
                sbom_dir=args.sbom_dir,
                out_dir=args.out_dir,
                images=imgs,
                items=[parse_item(i) for i in args.items],
                images_lock=args.images_lock,
                rehearsal=args.rehearsal,
                jobs=args.job,
                platform=args.platform,
            )
            print(
                f"release: {rel['version']} {rel['release_id']} (seq {rel['release_seq']}): {len(rel['images'])} "
                f"images, {len(rel['sboms'])} SBOM files, {len(rel['components'])} components"
            )
        else:
            found = check_bundle(args.bundle)
            for p in found:
                print(f"release check: {p}", file=sys.stderr)
            print(f"release check: {'FAIL' if found else 'PASS'} ({args.bundle.name}; {gates_mode_line(args.bundle)})")
            return 1 if found else 0
    except ReleaseError as exc:
        print(f"release: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
