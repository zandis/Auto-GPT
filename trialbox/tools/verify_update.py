"""Verify (and stage) a signed offline update bundle (SPEC §10.1 "Updates"; DECISIONS D-77, D-210).

Bundle = an uncompressed tar holding exactly:

* ``manifest.json``     — ``UpdateManifest`` 1.4.0 (schemas/update_manifest.schema.json): bundle id, signer,
                          ``release_seq``, ``min_installed_version``, ``key_id``, ``not_after``, the sha256 of the
                          members below, an optional key ``rotation``, an optional ``pack`` (H-95), and the files
                          with path, kind, sha256, size;
* ``manifest.json.sig`` — base64 Ed25519 signature of the manifest bytes by a vendor key the box trusts;
* ``compat.json``       — the compatibility table (bundle × schema × vocabulary release × model pin × prompt
                          registry, ``tools/update_status.py``), required;
* ``release.json``, ``images.lock`` — the release record (provisional until T-110: ``images`` = {name: {image,
                          digest}}) and the release's image lock (T-104); required when the bundle carries images
                          (``images.lock``: else the box's own ``--images-lock``);
* ``files/<path>``      — one payload per manifest entry, nothing else. At most one of kind ``host``: the host tree
                          (``trialbox-host.tar``, T-631, D-367: compose files, host tools, configuration), whose own
                          ``HOST-SHA256SUMS`` and member rules (``tools/host_tree.py``) are checked with its sha256.

Everything that decides whether the bundle may be applied is checked **before any payload is read or staged**:
members safe (regular files only, no absolute or ``..`` paths, no duplicates), the signature with a trusted key
(nothing of the manifest is parsed before it verifies) and ``key_id`` naming exactly that key, the manifest schema,
``not_after``, the key rotation, ``release_seq`` above the installed one (unless ``--allow-downgrade REASON``, which
the update path audits as ``update.downgrade``) and the installed one not below ``min_installed_version``,
``compat.json`` against the box's recorded state, ``release.json``'s image digests equal to ``images.lock`` (a null
digest is refused, never read as "nothing to compare"), every size, and the free space for the staged copy. Then each
payload is hashed while it is copied from the same open file (``DIR/<kind>/<path>.part``, created exclusively,
renamed only when every hash matched). Rejected: exit 1, nothing staged.

H-95, load from the stick: ``--stream KIND`` (``image``, ``model``) hashes that kind's payloads here like every other
payload, from the bundle, but stages none of them: no copy of the weights or the image archives is written on the box.
The update path then reads them from the bundle once more and hashes each again while it is loaded
(``tools/trialbox/update.py``, ``load_streamed_images`` and ``stream_models``): a payload whose second read does not
hash to the signed sha256 is never loaded. The space to stage counts the staged kinds only.

H-95, two packs: a ``pack`` of kind ``model`` carries only the engine image and the weights (payload kinds image and
model); a ``pack`` of kind ``software`` carries no weights and names the model pack it needs by that pack's bundle id
and the sha256 of its signed manifest.json. ``--model-pack-record deploy/updates/model-pack.json`` is the model pack
the box holds (written by the update path after a model pack loads). A software pack whose model pack is not that one
is refused (exit 1, nothing staged). A model pack's ``release_seq`` is compared with that record, not with
``installed.json``. A manifest without ``pack`` is a whole bundle, verified as before.

The trust: ``--trust deploy/updates/trust.json`` when that file exists (``--pubkey`` is then ignored), else the one
or two ``--pubkey`` files. ``--installed deploy/updates/installed.json`` (absent: a box at ``release_seq`` 0). No
environment variable changes a check.

    python tools/verify_update.py bundle.tar --pubkey deploy/keys/vendor_ed25519.pub [--stage DIR] \\
        [--trust deploy/updates/trust.json] [--installed deploy/updates/installed.json] [--images-lock FILE] \\
        [--allow-downgrade REASON] [--stream image --stream model] [--model-pack-record FILE]
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import shutil
import sys
import tarfile
from collections.abc import Callable, Collection, Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

MANIFEST = "manifest.json"
SIGNATURE = "manifest.json.sig"
COMPAT = "compat.json"
RELEASE = "release.json"
IMAGES_LOCK = "images.lock"
META = {COMPAT: "compat_sha256", RELEASE: "release_sha256", IMAGES_LOCK: "images_lock_sha256"}
PAYLOAD = "files/"
STAGE_MARGIN = 1.05
MAX_META_BYTES = 4 << 20


class Rejected(Exception):
    pass


def _safe(name: str) -> PurePosixPath:
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts or not p.parts or name != str(p) or "\\" in name:
        raise Rejected(f"unsafe path in bundle: {name!r}")
    return p


def raw_public(key: Any) -> bytes:
    from cryptography.hazmat.primitives import serialization

    return bytes(key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))


def key_id(key: Any) -> str:
    """``ed25519:`` + the first 16 hex of the sha256 of the raw public key (the manifest's ``key_id``)."""
    return "ed25519:" + hashlib.sha256(raw_public(key)).hexdigest()[:16]


def _from_raw(b64: str) -> Any:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        return Ed25519PublicKey.from_public_bytes(base64.b64decode(b64.strip(), validate=True))
    except ValueError as exc:
        raise Rejected("a public key is not a base64 raw 32-byte Ed25519 key") from exc


def load_public_key(path: Path) -> Any:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    data = path.read_bytes()
    if data.lstrip().startswith(b"-----BEGIN"):
        key = load_pem_public_key(data)
    else:
        key = _from_raw(data.decode("ascii", errors="replace"))
    if not isinstance(key, Ed25519PublicKey):
        raise Rejected("vendor key is not an Ed25519 public key")
    return key


def trusted_keys(trust: dict[str, Any] | None, pubkeys: Sequence[Path]) -> tuple[dict[str, Any], dict[str, Any]]:
    """``({key_id: key}, the trust record)``: ``trust.json`` when there is one, else the given key files (≤ 2)."""
    from tools.update_status import MAX_TRUSTED_KEYS, TRUST_FORMAT

    if trust is not None:
        keys = {}
        for kid, rec in trust["keys"].items():
            k = _from_raw(str(rec.get("public_key", "")))
            if key_id(k) != kid:
                raise Rejected(f"trust.json: key {kid} does not match its public key")
            if kid in (trust.get("retired") or {}):
                raise Rejected(f"trust.json: key {kid} is both trusted and retired")
            keys[kid] = k
        if len(keys) > MAX_TRUSTED_KEYS:
            raise Rejected(f"trust.json trusts {len(keys)} keys (at most {MAX_TRUSTED_KEYS})")
        return keys, trust
    if not pubkeys:
        raise Rejected("no trusted vendor key (deploy/keys/vendor_ed25519.pub)")
    if len(pubkeys) > MAX_TRUSTED_KEYS:
        raise Rejected(f"at most {MAX_TRUSTED_KEYS} trusted vendor keys")
    keys = {}
    for p in pubkeys:
        k = load_public_key(p)
        keys[key_id(k)] = k
    rec = {
        "format": TRUST_FORMAT,
        "keys": {
            kid: {"public_key": base64.b64encode(raw_public(k)).decode(), "source": "deploy/keys"}
            for kid, k in keys.items()
        },
        "retired": {},
        "rotations": [],
    }
    return keys, rec


def _parse_time(text: str, what: str) -> datetime:
    try:
        t = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Rejected(f"{what} is not a date-time: {text!r}") from exc
    if t.tzinfo is None:
        raise Rejected(f"{what} has no time zone: {text!r}")
    return t


def _rotate(manifest: dict[str, Any], trust: dict[str, Any], manifest_sha: str) -> dict[str, Any]:
    """The trust after this bundle (unchanged without a rotation). A rotation bundle is accepted once."""
    from tools.update_status import MAX_TRUSTED_KEYS

    after: dict[str, Any] = json.loads(json.dumps(trust))
    rot = manifest.get("rotation")
    if not rot:
        return after
    if manifest_sha in after.get("rotations", []):
        raise Rejected("this key rotation bundle was already applied (a rotation is accepted once)")
    new = _from_raw(rot["add_public_key"])
    nid = rot["add_key_id"]
    if key_id(new) != nid:
        raise Rejected("rotation: add_key_id does not name add_public_key")
    if nid in after["keys"]:
        raise Rejected(f"rotation: key {nid} is already trusted")
    if nid in (after.get("retired") or {}):
        raise Rejected(f"rotation: key {nid} was retired and is never trusted again")
    retire = rot.get("retire_key_id")
    if retire is not None and retire not in after["keys"]:
        raise Rejected(f"rotation: key {retire} to retire is not trusted")
    after["keys"][nid] = {"public_key": rot["add_public_key"], "source": f"rotation {manifest['bundle_id']}"}
    if retire is not None:
        del after["keys"][retire]
        after.setdefault("retired", {})[retire] = {"by": manifest["bundle_id"]}
    if len(after["keys"]) > MAX_TRUSTED_KEYS:
        raise Rejected(f"rotation: the box would trust {len(after['keys'])} keys (at most {MAX_TRUSTED_KEYS}); "
                       "retire one in the same rotation")  # fmt: skip
    after["rotations"] = [*after.get("rotations", []), manifest_sha]
    return after


def verify(
    bundle: Path,
    pubkey: Path | Sequence[Path] | None = None,
    stage: Path | None = None,
    *,
    trust_file: Path | None = None,
    installed_file: Path | None = None,
    images_lock: Path | None = None,
    allow_downgrade: str | None = None,
    now: datetime | None = None,
    disk_free: Callable[[Path], int] | None = None,
    stream_kinds: Collection[str] = (),
    model_pack_record: Path | None = None,
    model_pack_candidate: Path | None = None,
) -> dict[str, Any]:
    from cryptography.exceptions import InvalidSignature

    from tools import update_status as us

    pubkeys = [pubkey] if isinstance(pubkey, Path) else list(pubkey or [])
    try:
        trust_rec, trust_sha = us.load_trust_with_sha(trust_file)
        inst = us.load_installed(installed_file)
    except ValueError as exc:
        raise Rejected(f"the box's update state is unreadable: {exc}") from exc
    keys, trust_rec = trusted_keys(trust_rec, pubkeys)
    try:
        tf = tarfile.open(bundle, "r:")  # noqa: SIM115 - closed below
    except (tarfile.TarError, OSError) as exc:
        raise Rejected(f"not a tar bundle: {exc}") from exc
    with tf:
        members = {}
        try:
            listing = tf.getmembers()
        except tarfile.TarError as exc:  # H10G43-04: a bundle cut inside a member fails here, not at open
            raise Rejected(f"a damaged or cut-short tar bundle: {exc}") from exc
        for m in listing:
            if m.isdir():
                _safe(m.name.rstrip("/"))
                continue
            if not m.isfile():
                raise Rejected(f"bundle member {m.name!r} is not a regular file")
            _safe(m.name)
            if m.name in members:
                raise Rejected(f"duplicate member {m.name!r}")
            members[m.name] = m
        if MANIFEST not in members or SIGNATURE not in members:
            raise Rejected("manifest.json and manifest.json.sig are required")

        def read(name: str) -> bytes:
            if members[name].size > MAX_META_BYTES:
                raise Rejected(f"{name} is larger than {MAX_META_BYTES} bytes")
            f = tf.extractfile(members[name])
            assert f is not None
            return f.read()

        manifest_bytes = read(MANIFEST)
        try:
            sig = base64.b64decode(read(SIGNATURE).strip(), validate=True)
        except ValueError as exc:
            raise Rejected("signature does not verify with a trusted vendor key") from exc
        signed_by = None
        for kid, key in keys.items():
            try:
                key.verify(sig, manifest_bytes)
            except InvalidSignature:
                continue
            signed_by = kid
            break
        if signed_by is None:
            raise Rejected("signature does not verify with a trusted vendor key")
        try:
            manifest = json.loads(manifest_bytes)
        except ValueError as exc:
            raise Rejected("manifest.json is not JSON") from exc
        errs = _schema_errors(manifest)
        if errs:
            raise Rejected("manifest violates update_manifest schema: " + "; ".join(errs[:5]))
        if manifest["key_id"] != signed_by:
            raise Rejected(f"manifest key_id {manifest['key_id']} is not the key that signed it ({signed_by})")
        t_now = now or datetime.now(UTC)
        not_after = _parse_time(manifest["not_after"], "not_after")
        if t_now > not_after:
            raise Rejected(f"the bundle expired at {manifest['not_after']} (not_after)")
        if _parse_time(manifest["created_at"], "created_at") > not_after:
            raise Rejected("created_at is after not_after")
        manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
        trust_after = _rotate(manifest, trust_rec, manifest_sha)

        held = candidate_identity(model_pack_candidate) if model_pack_candidate else load_model_pack(model_pack_record)
        pack_problem = pack_problems(manifest, held)
        if pack_problem:  # H-94 (1): the pack does not hold together with what the box holds
            raise Rejected(pack_problem)
        is_model_pack = (manifest.get("pack") or {}).get("kind") == "model"
        seq, have = int(manifest["release_seq"]), int(inst["release_seq"])
        if have < int(manifest["min_installed_version"]):
            raise Rejected(f"the box is at release_seq {have}; this bundle needs at least "
                           f"{manifest['min_installed_version']} installed first (min_installed_version)")  # fmt: skip
        # H-95: a model pack's order is the model packs' own (the record of the one the box holds)
        last = held if is_model_pack else inst
        if is_model_pack:
            have = int((held or {}).get("release_seq") or 0)
        downgrade = None
        # D-833: the very bundle that is installed (same sequence, same manifest) is a repeat, not a downgrade:
        # install.sh run again continues from where it stopped, and the update answers "already installed". A key
        # rotation is never repeated (_rotate refuses it above)
        repeat = seq == have and manifest_sha == (last or {}).get("manifest_sha256") and not manifest.get("rotation")
        if seq <= have and not repeat:
            if not allow_downgrade or not allow_downgrade.strip():
                raise Rejected(f"release_seq {seq} is not above the installed {have} (a downgrade or a repeat); "
                               "refused (--allow-downgrade REASON overrides it, audited)")  # fmt: skip
            if manifest.get("rotation"):
                raise Rejected("a key rotation bundle is never applied as a downgrade")
            downgrade = {"from_release_seq": have, "to_release_seq": seq, "reason": allow_downgrade.strip()[:500]}

        meta: dict[str, Any] = {}
        for name, field in META.items():
            listed = manifest.get(field)
            if (name in members) != (listed is not None):
                where = "its sha256 is not in the manifest" if name in members else "it is not in the bundle"
                raise Rejected(f"{name}: listed in only one of the manifest and the bundle ({where})")
            if name in members:
                body = read(name)
                if hashlib.sha256(body).hexdigest() != listed:
                    raise Rejected(f"{name}: sha256 mismatch")
                try:
                    meta[name] = json.loads(body)
                except ValueError as exc:
                    raise Rejected(f"{name} is not JSON") from exc
                if not isinstance(meta[name], dict):
                    raise Rejected(f"{name} is not a JSON object")
        problems = us.compat_problems(meta[COMPAT], manifest["bundle_id"])
        if problems:
            raise Rejected("; ".join(problems))
        ok, why, notes = us.compat_check(meta[COMPAT], inst.get("state") or {})
        if not ok:
            raise Rejected(f"compatibility table (compat.json): {why}")
        release = meta.get(RELEASE)
        if release is not None and release.get("release_seq") not in (None, seq):
            raise Rejected(f"release.json release_seq {release.get('release_seq')} differs from the manifest's {seq}")
        if release is not None or any(f["kind"] == "image" for f in manifest["files"]):
            lock = meta.get(IMAGES_LOCK)
            if lock is None and images_lock is not None and images_lock.is_file():
                try:
                    lock = json.loads(images_lock.read_text(encoding="utf-8"))
                except ValueError as exc:
                    raise Rejected(f"{images_lock} is not JSON") from exc
            img = us.images_problems(release, lock)
            if img:
                raise Rejected("image digests: " + "; ".join(img[:5]))

        listed_files = {}
        for f in manifest["files"]:
            p = _safe(f["path"])
            if p.name.endswith(".part"):
                raise Rejected(f"{f['path']}: a payload path may not end in .part")
            listed_files[f"{PAYLOAD}{p}"] = f
        if len(listed_files) != len(manifest["files"]):
            raise Rejected("manifest lists a path twice")
        if sum(f["kind"] == "host" for f in manifest["files"]) > 1:
            raise Rejected("more than one host tree (payload kind host) in the bundle")
        names = set(listed_files)
        for n in names:
            if {str(q) for q in PurePosixPath(n).parents} & names:
                raise Rejected(f"{n}: a payload path is also used as a folder")
        present = {n for n in members if n not in (MANIFEST, SIGNATURE, *META)}
        if present - names:
            raise Rejected(f"files not in the manifest: {sorted(present - names)[:5]}")
        if names - present:
            raise Rejected(f"files missing from the bundle: {sorted(names - present)[:5]}")
        for name, entry in listed_files.items():
            if members[name].size != entry["size"]:
                raise Rejected(f"{entry['path']}: size {members[name].size} != manifest {entry['size']}")
        if stage is not None:  # H-95: a streamed kind is never staged, so it needs no room here
            need = int(sum(int(f["size"]) for f in manifest["files"] if f["kind"] not in stream_kinds) * STAGE_MARGIN)
            stage_fs = stage if stage.exists() else next(q for q in stage.parents if q.exists())
            free_of = disk_free or _free_bytes
            free = free_of(stage_fs)
            if free < need:
                raise Rejected(f"not enough disk space to stage the bundle in {stage_fs}: needs {gb(need)} "
                               f"(payloads + 5 %), free {gb(free)}; nothing was changed")  # fmt: skip
        try:
            _check_payloads(tf, members, listed_files, stage, stream_kinds)
        except Rejected:
            if stage is not None:
                _cleanup(stage)
            raise
        if stage is not None:
            for part in sorted(stage.rglob("*.part")):
                part.rename(part.with_suffix(""))
            (stage / MANIFEST).write_bytes(manifest_bytes)
    # trust_sha256: the trust.json this bundle was verified against (None: the deploy/keys files); the update path
    # refuses under its lock when trust.json is no longer exactly that file (a rotation applied in between)
    manifest.update(manifest_sha256=manifest_sha, compat=meta[COMPAT], release=release, trust_after=trust_after,
                    trust_sha256=trust_sha, downgrade=downgrade, compat_notes=notes, repeat=repeat,
                    streamed=sorted({f["kind"] for f in manifest["files"]} & set(stream_kinds)))  # fmt: skip
    return dict(manifest)


MODEL_PACK_KINDS = ("image", "model")


def load_model_pack(path: Path | None) -> dict[str, Any] | None:
    """H-95: the model pack the box holds (``deploy/updates/model-pack.json``), None when it holds none. A record
    that cannot be read is refused, never read as "none"."""
    if path is None or not path.exists():
        return None
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Rejected(f"the box's model pack record {path} is unreadable: {exc}") from exc
    if not isinstance(rec, dict) or not SHA256.match(str(rec.get("manifest_sha256") or "")):
        raise Rejected(f"the box's model pack record {path} names no manifest sha256")
    return rec


def candidate_identity(path: Path) -> dict[str, Any]:
    """H-95, a dry run only (apply_update.sh --dry-run --with-model-pack FILE): the model pack about to be loaded,
    as if the box held it. Its own signature and hashes are its own dry run's; here only its identity is read."""
    try:
        with tarfile.open(path, "r:") as tf:
            m = tf.extractfile("manifest.json")
            body = m.read(MAX_META_BYTES + 1) if m is not None else b""
        manifest = json.loads(body)
    except (OSError, KeyError, ValueError, tarfile.TarError) as exc:
        raise Rejected(f"{path}: not a model pack ({exc})") from exc
    if not isinstance(manifest, dict) or (manifest.get("pack") or {}).get("kind") != "model":
        raise Rejected(f"{path}: not a model pack")
    return {"bundle_id": manifest.get("bundle_id"), "manifest_sha256": hashlib.sha256(body).hexdigest()}


def held_text(held: dict[str, Any] | None) -> str:
    if held is None:
        return "the box holds no model pack"
    return f"the box holds model pack {held.get('bundle_id')} (manifest sha256 {held.get('manifest_sha256')})"


def pack_problems(manifest: dict[str, Any], held: dict[str, Any] | None) -> str:
    """H-95: why this pack may not be applied on a box that holds ``held`` ("" when it may). The model pack is named
    by its signed identity: its bundle id and the sha256 of its signed manifest.json, never by a file or folder."""
    pack = manifest.get("pack")
    if not pack:
        return ""
    kinds = sorted({f["kind"] for f in manifest["files"]})
    if pack["kind"] == "model":
        stray = [k for k in kinds if k not in MODEL_PACK_KINDS]
        if stray:
            return f"a model pack carries only the engine image and the weights, not {', '.join(stray)}"
        return ""
    if "model" in kinds:
        return "a software pack carries no weights (payload kind model): they ride in its model pack"
    need = pack["requires_model"]
    if held is None or held.get("manifest_sha256") != need["manifest_sha256"]:
        return (f"this software pack needs model pack {need['bundle_id']} (signed manifest sha256 "
                f"{need['manifest_sha256']}); {held_text(held)}. Load that model pack first "
                "(deploy/install.sh <software pack> --model-pack <model pack>, or tools/apply_update.sh <model pack>); "
                "nothing was changed")  # fmt: skip
    return ""


def _schema_errors(manifest: Any) -> list[str]:
    """``schemas/update_manifest.schema.json`` through tb_contracts (jsonschema) when the host has it, else the same
    rules in the standard library. A clean site host (Ubuntu 24.04 with python3-cryptography) has no jsonschema, and
    on a first install the trialbox-py image that has it is inside the bundle being verified (found by the box
    rehearsal, D-176). The signature is checked before either."""
    try:
        from tb_contracts import schema_errors
    except ImportError:
        return _stdlib_schema_errors(manifest)
    return list(schema_errors("update_manifest", manifest))


KINDS = ("model", "ruleset", "image", "refdata", "other", "host")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
KEY_ID = re.compile(r"^ed25519:[0-9a-f]{16}$")
BUNDLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
REQUIRED = ("bundle_id", "created_at", "signer", "files", "release_seq", "min_installed_version", "key_id",
            "not_after", "compat_sha256")  # fmt: skip
OPTIONAL = ("description", "release_sha256", "images_lock_sha256", "rotation", "pack")


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_time(v: Any) -> bool:
    try:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _stdlib_schema_errors(m: Any) -> list[str]:
    """The rules of schemas/update_manifest.schema.json 1.4.0 (D-210; kind host: D-367; pack: H-95) in the standard library;
    tests/unit/test_verify_update_stdlib.py holds the two in step."""
    if not isinstance(m, dict):
        return ["manifest is not an object"]
    errs = [f"missing {k}" for k in REQUIRED if k not in m]
    errs += [f"unexpected {k}" for k in m if k not in REQUIRED + OPTIONAL]
    strings = ("bundle_id", "created_at", "signer", "not_after")
    errs += [f"{k} is not a string" for k in strings if k in m and not isinstance(m[k], str)]
    if isinstance(m.get("bundle_id"), str) and not BUNDLE_ID.match(m["bundle_id"]):
        errs.append("bundle_id has characters outside A-Z a-z 0-9 . _ - (or is too long)")
    if m.get("description") is not None and not isinstance(m["description"], str):
        errs.append("description is not a string")
    for k in ("created_at", "not_after"):
        if isinstance(m.get(k), str) and not _is_time(m[k]):
            errs.append(f"{k} is not a date-time")
    for k, low in (("release_seq", 1), ("min_installed_version", 0)):
        if k in m and not (_is_int(m[k]) and m[k] >= low):
            errs.append(f"{k} is not an integer >= {low}")
    if "key_id" in m and not (isinstance(m["key_id"], str) and KEY_ID.match(m["key_id"])):
        errs.append("key_id is not ed25519:<16 hex>")
    for k in ("compat_sha256", "release_sha256", "images_lock_sha256"):
        if k in m and not (isinstance(m[k], str) and SHA256.match(m[k])):
            errs.append(f"{k} is not 64 lowercase hex digits")
    if "rotation" in m:
        errs += _rotation_errors(m["rotation"])
    if "pack" in m:
        errs += _pack_errors(m["pack"])
    files = m.get("files")
    if "files" in m and not isinstance(files, list):
        return [*errs, "files is not an array"]
    for i, f in enumerate(files or []):
        if not isinstance(f, dict):
            errs.append(f"files[{i}] is not an object")
            continue
        errs += [f"files[{i}]: missing {k}" for k in ("path", "sha256", "kind", "size") if k not in f]
        errs += [f"files[{i}]: unexpected {k}" for k in f if k not in ("path", "sha256", "kind", "size")]
        if "path" in f and not (isinstance(f["path"], str) and 1 <= len(f["path"]) <= 400):
            errs.append(f"files[{i}]: path is not a string of 1 to 400 characters")
        if "sha256" in f and not (isinstance(f["sha256"], str) and SHA256.match(f["sha256"])):
            errs.append(f"files[{i}]: sha256 is not 64 lowercase hex digits")
        if "kind" in f and f["kind"] not in KINDS:
            errs.append(f"files[{i}]: kind {f['kind']!r} is not one of {', '.join(KINDS)}")
        if "size" in f and not (_is_int(f["size"]) and f["size"] >= 0):
            errs.append(f"files[{i}]: size is not an integer >= 0")
    return errs


def _pack_errors(p: Any) -> list[str]:
    if not isinstance(p, dict) or p.get("kind") not in ("model", "software"):
        return ["pack is not an object of kind model or software"]
    allowed = ("kind",) if p["kind"] == "model" else ("kind", "requires_model")
    errs = [f"pack: unexpected {k}" for k in p if k not in allowed]
    if p["kind"] == "software":
        r = p.get("requires_model")
        if not isinstance(r, dict):
            return [*errs, "pack: a software pack names the model pack it needs (requires_model)"]
        errs += [f"pack.requires_model: missing {k}" for k in ("bundle_id", "manifest_sha256") if k not in r]
        errs += [f"pack.requires_model: unexpected {k}" for k in r if k not in ("bundle_id", "manifest_sha256")]
        if "bundle_id" in r and not (isinstance(r["bundle_id"], str) and BUNDLE_ID.match(r["bundle_id"])):
            errs.append("pack.requires_model: bundle_id is not a bundle id")
        if "manifest_sha256" in r and not (isinstance(r["manifest_sha256"], str) and SHA256.match(r["manifest_sha256"])):
            errs.append("pack.requires_model: manifest_sha256 is not 64 lowercase hex digits")
    return errs


def _rotation_errors(r: Any) -> list[str]:
    if not isinstance(r, dict):
        return ["rotation is not an object"]
    errs = [f"rotation: missing {k}" for k in ("add_key_id", "add_public_key") if k not in r]
    errs += [f"rotation: unexpected {k}" for k in r if k not in ("add_key_id", "add_public_key", "retire_key_id")]
    if "add_key_id" in r and not (isinstance(r["add_key_id"], str) and KEY_ID.match(r["add_key_id"])):
        errs.append("rotation: add_key_id is not ed25519:<16 hex>")
    if "add_public_key" in r and not isinstance(r["add_public_key"], str):
        errs.append("rotation: add_public_key is not a string")
    retire = r.get("retire_key_id")
    if retire is not None and not (isinstance(retire, str) and KEY_ID.match(retire)):
        errs.append("rotation: retire_key_id is not ed25519:<16 hex>")
    return errs


def _free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def gb(n: float) -> str:
    return f"{n / 1e9:.2f} GB ({int(n)} bytes)"


def _check_payloads(
    tf: tarfile.TarFile,
    members: dict[str, tarfile.TarInfo],
    listed: dict[str, Any],
    stage: Path | None,
    stream_kinds: Collection[str] = (),
) -> None:
    for name, entry in sorted(listed.items()):
        m = members[name]
        f = tf.extractfile(m)
        assert f is not None
        h = hashlib.sha256()
        out = None
        if stage is not None and entry["kind"] not in stream_kinds:
            target = stage / entry["kind"] / str(_safe(entry["path"]))
            target.parent.mkdir(parents=True, exist_ok=True)
            out = target.with_suffix(target.suffix + ".part").open("xb")
        try:
            while chunk := f.read(1 << 20):
                h.update(chunk)
                if out is not None:
                    out.write(chunk)
        finally:
            if out is not None:
                out.close()
        if h.hexdigest() != entry["sha256"]:
            raise Rejected(f"{entry['path']}: sha256 mismatch")
        if entry["kind"] == "host":  # T-631: the tree's own sums and member rules, before anything is unpacked
            _check_host(tf, m, stage, entry)


def _check_host(tf: tarfile.TarFile, m: tarfile.TarInfo, stage: Path | None, entry: dict[str, Any]) -> None:
    from tools import host_tree

    try:
        if stage is not None:
            target = stage / "host" / str(_safe(entry["path"]))
            with target.with_suffix(target.suffix + ".part").open("rb") as fh:
                host_tree.check_tar(fh)
        else:
            f = tf.extractfile(m)
            assert f is not None
            host_tree.check_tar(f)
    except host_tree.HostTreeError as exc:
        raise Rejected(f"{entry['path']}: host tree: {exc}") from exc


def _cleanup(stage: Path) -> None:
    for p in sorted(stage.rglob("*"), reverse=True):
        if p.is_file() or p.is_symlink():
            p.unlink()
        elif p.is_dir():
            p.rmdir()


SUMMARY_KEYS = ("bundle_id", "signer", "manifest_sha256", "release_seq", "min_installed_version", "key_id",
                "not_after", "compat", "release", "rotation", "trust_after", "trust_sha256", "downgrade",
                "compat_notes", "repeat", "pack", "streamed")  # fmt: skip


def summary(m: dict[str, Any]) -> dict[str, Any]:
    """What ``tools/apply_update.sh`` hands to the update path (``python3 -m tools.trialbox update --summary``)."""
    out = {k: m.get(k) for k in SUMMARY_KEYS}
    out["files"] = [{"path": f["path"], "kind": f["kind"], "size": f["size"]} for f in m["files"]]
    return out


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    for p in (root, root / "libs"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bundle", type=Path)
    ap.add_argument("--pubkey", type=Path, action="append", default=[], help="a trusted key (at most two)")
    ap.add_argument("--stage", type=Path)
    ap.add_argument("--trust", type=Path, help="deploy/updates/trust.json (used instead of --pubkey when it exists)")
    ap.add_argument("--installed", type=Path, help="deploy/updates/installed.json")
    ap.add_argument("--images-lock", type=Path, help="the box's deploy/images.lock (when the bundle carries none)")
    ap.add_argument("--allow-downgrade", metavar="REASON", help="accept a release_seq not above the installed one")
    ap.add_argument("--stream", action="append", default=[], choices=MODEL_PACK_KINDS,
                    help="H-95: hash this kind's payloads but stage none (the update path loads them from the bundle)")
    ap.add_argument("--model-pack-record", type=Path, help="deploy/updates/model-pack.json: the model pack the box holds")
    ap.add_argument("--model-pack-candidate", type=Path, help="a dry run only: check against this model pack instead")
    args = ap.parse_args(argv)
    try:
        m = verify(args.bundle, args.pubkey, args.stage, trust_file=args.trust, installed_file=args.installed,
                   images_lock=args.images_lock, allow_downgrade=args.allow_downgrade, stream_kinds=args.stream,
                   model_pack_record=args.model_pack_record,
                   model_pack_candidate=args.model_pack_candidate)  # fmt: skip
    except Rejected as exc:
        print(f"REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary(m), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
