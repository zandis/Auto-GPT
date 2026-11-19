"""Fetch a GPU profile's model weights into the folders the pin accepts (W-1; root review 23, runbook §27 step 10).

    python3 -m tools.fetch_weights --profile rtxpro6000 --dry-run      # what would be fetched; no network
    python3 -m tools.fetch_weights --profile rtxpro6000                # fetch, verify, move into place
    python3 -m tools.fetch_weights --profile rtxpro6000 --verify-only  # check what is there; no network
    make fetch-weights GPU=rtxpro6000 [ARGS=--dry-run]

**Where the list comes from.** Nothing here names a model. The profile's deployed pair is
``tools.pin_model.PROFILE_PAIRS`` (the same list ``pin_model --install`` pins), each build's row in
``models/registry.yaml`` names its expected weights (``expected``: the manifest sha256, the revision, and ``source``,
the measured serving record), and that record lists every file of the release with its size and sha256
(``model_files``). The file list is used only when its digest, in ``pin_model``'s manifest format, is the row's
``expected.manifest_sha256``: a record that disagrees with the registry is a broken pin record and nothing is
fetched. The judge's chat template is the row's ``chat_template`` (source, revision, file, sha256).

**Where it goes.** The models root and the folder names are resolved as the start resolves them (``deploy/poc.sh``
and compose): ``TB_MODELS_DIR`` from the environment (relative to ``trialbox/``), else from ``deploy/.env``
(relative to ``deploy/``), else ``deploy/models``; ``JUDGE_MODEL_DIR``, ``VERIFIER_MODEL_DIR`` and
``JUDGE_CHAT_TEMPLATE`` from the environment, else the default in the profile's compose file (the start's check does
not read them from ``deploy/.env``, so neither does this). ``deploy/.env`` is read as ``envfile_get`` reads it: a line
``KEY=value`` exactly, the last one wins, quotes removed. The resolved root is printed first. Every name must stay
under the root (no ``..``, no absolute path, no hidden part), the template may not lie inside a model folder, and
every destination, the stage and each part folder must resolve inside the real models root (no symbolic link on the
way; a part file with another hard link is refused).

**What is fetched.** Exactly the visible files of that list (hidden files such as ``.gitattributes`` are outside the
pin's manifest), from ``https://huggingface.co/<repository>/resolve/<revision>/<path>``, and the template file (at
most 1 MB: the pin gives no size for it). A list that names a refused type (``.bin``, ``.py`` and the other pickle or
code suffixes of ``pin_model``) or an unsafe path is refused before anything is asked for. One run at a time: a run
holds a lock on ``<models>/.fetch-weights/.lock`` (and checks it holds the file still at that path) and a second
run stops at once. Each file is written under ``<models>/.fetch-weights/`` (hidden, on the same disk; part files
opened without following links), resumed with an HTTP range after an interruption (a fault while asking or reading
is retried; one while writing is not), and checked against its size and pinned sha256; a file with another sha256 is
deleted and the run fails (it is not asked for again: that is not the network's fault). A full or unwritable disk
is said as such and not retried. Before a staged folder is moved it must hold the pinned files and nothing else: no
extra, hidden, linked or special entry, no empty folder; a staged folder that fails this is removed, so the next run
starts it clean. What arrived intact is kept for the next run; staged leftovers of folders no longer asked for are
removed. A folder already in place is never changed: if it holds the pinned build it is reported present, otherwise
the run stops and says to move it aside (also when one appears, even empty, during the run).

**What is sent.** Only the GET requests for those files (the hub may redirect them to its content store, over https
only). ``HF_TOKEN`` from the environment is sent only when the endpoint is the public hub itself, only to the hub's
own origin (scheme, host and port) and never to the origin a download is redirected to; it is never printed (a
token with spaces or control characters is refused without being shown). ``HF_ENDPOINT`` replaces the hub's address
(a mirror), https only, and never receives the token. Standard library and PyYAML only (``python3-yaml``, runbook §27
step 3): the publisher's tool is not needed. Nothing runs this at install or start: it runs only when asked.

Exit 0: every folder is the pinned build (``--dry-run``: the run could go ahead). 1: a download failed, a hash
differed, a folder is in the way, the disk is short or another run holds the lock, or (``--verify-only``) something
is missing or differs. 2: a usage error, an endpoint that is not https, a destination outside the
models root, or a pin record that cannot be used.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import errno
import fcntl
import hashlib
import http.client
import io
import json
import os
import re
import shutil
import ssl
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

import yaml

from tools.pin_model import PROFILE_PAIRS, REFUSED_SUFFIXES, manifest_sha256_of_files

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "models" / "registry.yaml"
LICENCE_REGISTER = ROOT / "docs" / "licences" / "register.csv"
HUB = "https://huggingface.co"
STAGE = ".fetch-weights"  # under the models root: hidden (outside every manifest), same disk (one rename)
PARTS = ".parts"  # inside a staged folder: the files still being written
LOCK = ".lock"  # in STAGE: one run at a time
MARGIN = 1 << 30  # free space kept beyond the download (1 GiB)
TEMPLATE_MAX = 1 << 20  # the template has no pinned size: a body above this is refused
CHUNK = 8 << 20
WAITS = (2, 5, 15)  # seconds before each further ask after a transfer fault; four asks per file in all
# what asking the hub or reading its answer may raise: retried. A fault while writing the file is local, not retried.
NET_FAULTS = (urllib.error.URLError, http.client.HTTPException, OSError)
TEMPLATE_VAR = "JUDGE_CHAT_TEMPLATE"
TOKEN_RE = re.compile(r"[\x21-\x7e]+")  # visible ASCII, no space or control character


class RecordError(RuntimeError):
    """The pin record cannot give a verified file list (exit 2)."""


class FetchError(RuntimeError):
    """A download, a hash, the disk or a folder in the way (exit 1)."""


class HubRefused(FetchError):
    """The hub answered with an HTTP error that asking again will not change, or an address is not https."""


class Outside(RecordError):
    """A destination, the stage or a part folder resolves outside the models root (exit 2)."""


class _NetFault(Exception):
    """A network fault while asking or reading: retried."""


@dataclass(frozen=True)
class PinnedFile:
    path: str  # relative to the folder (for the template: its file name)
    sha256: str
    size: int | None  # None: the pin record gives no size (the template)


@dataclass
class Target:
    """One thing to put under the models root: a model folder, or the judge's chat template (a single file)."""

    kind: str  # "folder" or "template"
    dest: str  # under the models root
    source: str  # the publisher's repository
    revision: str
    files: list[PinnedFile]
    builds: list[str] = field(default_factory=list)
    licence: dict[str, str] = field(default_factory=dict)
    manifest_sha256: str = ""  # folders: the expected manifest digest

    @property
    def size(self) -> int | None:
        sizes = [f.size for f in self.files]
        return None if any(s is None for s in sizes) else sum(s for s in sizes if s is not None)


# ---------------------------------------------------------------------------------------------------- where


def _safe_rel(rel: str) -> bool:
    """A relative path under a root: no absolute path, no empty, ``.`` or ``..`` part, no hidden part."""
    parts = rel.split("/")
    return bool(rel) and not rel.startswith("/") and all(p and not p.startswith(".") for p in parts)


def envfile_get(key: str, root: Path = ROOT) -> str:
    """``deploy/poc.sh``'s ``envfile_get``: the last line of ``deploy/.env`` that starts with ``KEY=`` exactly (no
    space before the key or round ``=``), every quote character removed, spaces kept."""
    path = root / "deploy" / ".env"
    if not path.is_file():
        return ""
    value = ""
    for line in path.read_text(encoding="utf-8").split("\n"):
        if line.startswith(key + "="):
            value = line[len(key) + 1 :]
    return value.replace('"', "").replace("'", "")


def compose_default(var: str, compose: Path) -> str:
    """``deploy/poc.sh``'s ``compose_default``: on the first line holding ``${VAR:-default}``, the last such default."""
    if not compose.is_file():
        return ""
    pattern = re.compile(r".*\$\{" + re.escape(var) + r":-([^}]*)\}")
    for line in compose.read_text(encoding="utf-8").split("\n"):
        m = pattern.match(line)
        if m:
            return m.group(1)
    return ""


def resolve_env(profile: str, env: dict[str, str], root: Path = ROOT) -> dict[str, str]:
    """The folder names the start checks (``deploy/poc.sh``, GPU preflight): the environment, else the profile's
    compose default; ``deploy/.env`` is not read for them, as the start does not read it."""
    compose = root / "deploy" / f"docker-compose.{profile}.yml"
    out: dict[str, str] = {}
    for var in ("JUDGE_MODEL_DIR", "VERIFIER_MODEL_DIR", TEMPLATE_VAR):
        value = env.get(var) or compose_default(var, compose)
        if value:
            out[var] = value
    return out


def models_root(env: dict[str, str], root: Path = ROOT) -> tuple[Path, str]:
    """(the models root, where it came from), as ``deploy/poc.sh``'s ``models_dir`` resolves it: ``TB_MODELS_DIR``
    from the environment (relative to ``trialbox/``), else from ``deploy/.env`` (relative to ``deploy/``), else
    ``deploy/models``."""
    m = env.get("TB_MODELS_DIR") or ""
    if m:
        came = "TB_MODELS_DIR (environment)"
        m = m if m.startswith("/") else f"{root}/{m.removeprefix('./')}"
    else:
        m = envfile_get("TB_MODELS_DIR", root)
        came = "TB_MODELS_DIR (deploy/.env)" if m else "the default"
        m = m or "./models"
        m = m if m.startswith("/") else f"{root}/deploy/{m.removeprefix('./')}"
    return Path(m.removesuffix("/") if m != "/" else m), came


def _inside(models: Path, path: Path) -> bool:
    """``path`` (under ``models``) resolves to the same place under the real models root: no link on the way."""
    real_root = os.path.realpath(models)
    return os.path.realpath(path) == os.path.join(real_root, os.path.relpath(path, models))


def _guard(models: Path, *paths: Path) -> None:
    for p in paths:
        if not _inside(models, p):
            raise Outside(
                f"{p} resolves to {os.path.realpath(p)}, outside the models root {os.path.realpath(models)} (a "
                "symbolic link on the way): refused; to keep the weights on another disk, point TB_MODELS_DIR there"
            )


def guard_targets(models: Path, targets: list[Target]) -> None:
    """Every destination, the stage and each part folder inside the real models root; :class:`Outside` if not."""
    stage = models / STAGE
    _guard(models, stage, stage / LOCK)
    for t in targets:
        _guard(models, models / t.dest, stage / t.dest, stage / t.dest / PARTS)


# ---------------------------------------------------------------------------------------------------- the plan


def _licences(register: Path) -> dict[str, dict[str, str]]:
    if not register.is_file():
        return {}
    with register.open(encoding="utf-8", newline="") as fh:
        return {row["id"]: row for row in csv.DictReader(fh)}


def _licence_of(row: dict[str, Any], register: dict[str, dict[str, str]]) -> dict[str, str]:
    lic = row.get("licence") or {}
    reg = register.get(str(lic.get("register") or "")) or {}
    return {
        "name": str(reg.get("licence") or lic.get("name") or "not recorded"),
        "spdx": str(reg.get("spdx") or lic.get("spdx") or ""),
        "status": str(reg.get("status") or ("verified" if lic.get("verified") else "not verified")),
        "obligation": str(reg.get("obligation") or ""),
        "register": str(lic.get("register") or ""),
    }


def _record_files(row: dict[str, Any], root: Path) -> tuple[str, str, list[PinnedFile]]:
    """(source, revision, visible files) of a build's expected weights, from the measured record its row names; the
    list's manifest digest must be the row's ``expected.manifest_sha256``."""
    build = str(row.get("build_id"))
    exp = row.get("expected") or {}
    want, revision, rec = exp.get("manifest_sha256"), exp.get("revision"), exp.get("source")
    if not (want and revision and rec):
        raise RecordError(
            f"{build}: models/registry.yaml names no complete `expected` (manifest_sha256, revision, source): "
            "nothing can be fetched for it without guessing"
        )
    prov = row.get("provenance") or {}
    source = str(prov.get("source") or row.get("repository") or "")
    if not source or "/" not in source:
        raise RecordError(f"{build}: models/registry.yaml names no source repository")
    if prov.get("revision") and prov["revision"] != revision:
        raise RecordError(f"{build}: provenance revision {prov['revision']} is not expected revision {revision}")
    path = (root / str(rec)).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise RecordError(f"{build}: the measured record {rec} named by expected.source is not in this checkout")
    doc = json.loads(path.read_text(encoding="utf-8"))
    servers = [s for s in doc.get("servers") or [] if s.get("model") == source]
    if len(servers) != 1:
        raise RecordError(f"{build}: {rec} holds {len(servers)} servers of {source}, not one")
    files = servers[0].get("model_files")
    if not isinstance(files, list) or not files:
        raise RecordError(f"{build}: {rec} lists no model_files (path, bytes, sha256) for {source}")
    if manifest_sha256_of_files(files) != want:
        raise RecordError(
            f"{build}: the file list in {rec} does not give the expected manifest {str(want)[:12]}: the pin record "
            "disagrees with itself; nothing is fetched"
        )
    model_dir = str(servers[0].get("model_dir") or "")
    if model_dir and "/snapshots/" in model_dir and not model_dir.rstrip("/").endswith("/" + str(revision)):
        raise RecordError(f"{build}: {rec} measured another revision than {revision}")
    out: list[PinnedFile] = []
    for f in files:
        rel = str(f.get("path") or "")
        parts = rel.split("/")
        if rel.startswith("/") or any(p in ("", ".", "..") for p in parts):
            raise RecordError(f"{build}: {rec} names an unsafe path {rel!r}")
        if any(p.startswith(".") for p in parts):
            continue  # outside the pin's manifest (.gitattributes)
        if Path(rel).suffix.lower() in REFUSED_SUFFIXES:
            raise RecordError(f"{build}: {rec} lists {rel}, a refused file type (pickle weights or code)")
        out.append(PinnedFile(rel, str(f["sha256"]), int(f["bytes"]) if f.get("bytes") is not None else None))
    return source, str(revision), out


def plan(
    profile: str,
    env: dict[str, str] | None = None,
    *,
    registry: Path = REGISTRY,
    register: Path = LICENCE_REGISTER,
    root: Path = ROOT,
) -> list[Target]:
    """What the profile needs under the models root, every file with its pinned sha256; :class:`RecordError` when
    the pin record cannot give that without a guess. ``env`` holds the resolved folder names (:func:`resolve_env`)."""
    e = env if env is not None else {}
    pairs = PROFILE_PAIRS.get(profile)
    if pairs is None:
        raise RecordError(f"no deployed pair for GPU profile {profile!r} (known: {', '.join(sorted(PROFILE_PAIRS))})")
    doc = yaml.safe_load(registry.read_text(encoding="utf-8")) or {}
    rows = {str(b.get("build_id")): b for b in doc.get("builds") or []}
    licences = _licences(register)
    targets: dict[str, Target] = {}
    for build, _endpoint, dir_var, dir_default, *_ in pairs:
        row = rows.get(build)
        if row is None:
            raise RecordError(f"{build}: not in models/registry.yaml")
        raw = e.get(dir_var) or dir_default
        folder = raw.rstrip("/")
        if not _safe_rel(folder):
            raise RecordError(f"{dir_var}={raw!r} is not a folder name under the models root")
        source, revision, files = _record_files(row, root)
        exp = str((row.get("expected") or {}).get("manifest_sha256"))
        have = targets.get(folder)
        if have is not None:
            if have.kind != "folder" or have.manifest_sha256 != exp:
                raise RecordError(f"{build} and {have.builds[0]} want different things at {folder}")
            have.builds.append(build)
        else:
            targets[folder] = Target(
                "folder", folder, source, revision, files, [build], _licence_of(row, licences), exp
            )
        tpl = row.get("chat_template")
        if isinstance(tpl, dict) and tpl.get("file"):
            if not (tpl.get("sha256") and tpl.get("source") and tpl.get("revision")):
                raise RecordError(f"{build}: chat_template has no sha256, source or revision: it cannot be fetched")
            dest = e.get(TEMPLATE_VAR) or str(tpl["file"])
            if not _safe_rel(dest):
                raise RecordError(f"{TEMPLATE_VAR}={dest!r} is not a file path under the models root")
            if dest in targets:
                if targets[dest].kind != "template" or targets[dest].files[0].sha256 != tpl["sha256"]:
                    raise RecordError(f"two builds want different things at {dest}")
                targets[dest].builds.append(build)
                continue
            targets[dest] = Target(
                "template",
                dest,
                str(tpl["source"]),
                str(tpl["revision"]),
                [PinnedFile(Path(str(tpl["file"])).name, str(tpl["sha256"]), None)],
                [build],
                _licence_of(row, licences),
            )
    dests = list(targets)
    for a in dests:
        for b in dests:
            if a != b and b.startswith(a + "/"):
                raise RecordError(f"{b} lies inside {a}: each folder must hold only its pinned files")
    return list(targets.values())


# ---------------------------------------------------------------------------------------------------- transport


def origin(url: str) -> tuple[str, str, int]:
    """(scheme, host, port) of an address, the port made explicit."""
    u = urllib.parse.urlsplit(url)
    return u.scheme, (u.hostname or "").lower(), u.port or {"https": 443, "http": 80}.get(u.scheme, 0)


class Transport:
    """HTTPS GETs with an optional range. ``open`` returns (status, total size or None, response stream).
    ``token`` goes only to ``token_origin`` (the hub's scheme, host and port), never after a redirect elsewhere."""

    def __init__(self, token: str | None = None, token_origin: tuple[str, str, int] | None = None) -> None:
        self._token = token
        self._token_origin = token_origin
        ctx = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE") or None)
        transport = self

        class _Redirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
                transport.check_url(newurl)
                new = super().redirect_request(req, fp, code, msg, headers, newurl)
                if new is not None and origin(newurl) != transport._token_origin:
                    new.remove_header("Authorization")  # the token goes to the hub alone, never to its CDN
                return new

        opener = urllib.request.OpenerDirector()
        for handler in (
            urllib.request.ProxyHandler(),
            urllib.request.HTTPHandler(),
            urllib.request.HTTPSHandler(context=ctx),
            _Redirect(),
            urllib.request.HTTPErrorProcessor(),
            urllib.request.HTTPDefaultErrorHandler(),
        ):
            opener.add_handler(handler)
        self._opener = opener

    @classmethod
    def url_ok(cls, url: str) -> bool:
        return urllib.parse.urlsplit(url).scheme == "https"

    def check_url(self, url: str) -> None:
        if not self.url_ok(url):
            raise HubRefused(f"{urllib.parse.urlsplit(url).hostname}: only https is fetched (asked for {url[:8]}…)")

    def open(self, url: str, start: int = 0) -> tuple[int, int | None, IO[bytes]]:
        self.check_url(url)
        req = urllib.request.Request(url, headers={"User-Agent": "trialbox-fetch-weights"})
        if start:
            req.add_header("Range", f"bytes={start}-")
        if self._token and origin(url) == self._token_origin:
            req.add_header("Authorization", f"Bearer {self._token}")
        try:
            resp = self._opener.open(req, timeout=60)
        except urllib.error.HTTPError as exc:
            if exc.code == 416 and start:
                return 416, None, exc.fp or io.BytesIO()
            if exc.code in (401, 403):
                raise HubRefused(
                    f"the hub refused {url.split('/resolve/', maxsplit=1)[0]} (HTTP {exc.code}): if the repository "
                    "is gated, accept its terms on its page while signed in, make a read token in the hub's settings "
                    "(Access Tokens) and run again with HF_TOKEN set in the environment"
                ) from None
            if exc.code == 404:
                raise HubRefused(f"not on the hub at the pinned revision (HTTP 404): {url}") from None
            raise
        final = resp.geturl()
        if not self.url_ok(final):
            resp.close()
            self.check_url(final)
        total: int | None = None
        crange = resp.headers.get("Content-Range") or ""
        if resp.status == 206 and "/" in crange and crange.rsplit("/", 1)[1].isdigit():
            total = int(crange.rsplit("/", 1)[1])
        elif resp.headers.get("Content-Length", "").isdigit():
            total = int(resp.headers["Content-Length"]) + (start if resp.status == 206 else 0)
        return resp.status, total, resp


def token_for(env: dict[str, str], hub: str) -> str | None:
    """The token to send: ``HF_TOKEN`` stripped, only for the public hub; :class:`FetchError` (never naming the
    token) when it holds spaces or control characters."""
    raw = env.get("HF_TOKEN") or ""
    tok = raw.strip()
    if not tok:
        return None
    if not TOKEN_RE.fullmatch(tok):
        raise FetchError(
            "HF_TOKEN holds a space or a control character: it is not sent (it is not shown either); set it again "
            "with the token alone"
        )
    return tok if hub.rstrip("/") == HUB else None


# ---------------------------------------------------------------------------------------------------- fetching


def _say(msg: str) -> None:
    print(msg, flush=True)


def _err(msg: str) -> None:
    print(f"fetch-weights: {msg}", file=sys.stderr, flush=True)


def _human(n: int | None) -> str:
    if n is None:
        return "size not in the pin record"
    for unit, scale in (("GB", 1e9), ("MB", 1e6), ("kB", 1e3)):
        if n >= scale:
            return f"{n / scale:.1f} {unit}"
    return f"{n} bytes"


def _local(exc: OSError, what: Path) -> FetchError:
    """A local file error in plain words; the disk being full is said as such."""
    if exc.errno in (errno.ENOSPC, errno.EDQUOT):
        return FetchError(f"the disk is full at {what}: free some space (or set TB_MODELS_DIR to a larger disk)")
    if exc.errno in (errno.EACCES, errno.EPERM, errno.EROFS):
        return FetchError(f"no permission to write {what} ({exc.strerror})")
    if exc.errno == errno.ELOOP:
        return FetchError(f"{what} is a symbolic link: refused")
    return FetchError(f"{what}: {exc.strerror or exc}")


@contextlib.contextmanager
def _on_disk(what: Path) -> Iterator[None]:
    try:
        yield
    except FetchError:
        raise
    except OSError as exc:
        raise _local(exc, what) from None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as fh:
        while chunk := fh.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _regular(path: Path) -> bool:
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except FileNotFoundError:
        return False


def url_of(hub: str, source: str, revision: str, path: str) -> str:
    return f"{hub.rstrip('/')}/{source}/resolve/{revision}/{urllib.parse.quote(path)}"


def _open_part(part: Path, append: bool) -> IO[bytes]:
    """The part file, never through a link and never truncated here: the caller truncates it (a fresh start) only
    after checking it has no other hard link."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | (os.O_APPEND if append else 0)
    return os.fdopen(os.open(part, flags, 0o644), "ab" if append else "wb")


def fetch_file(
    transport: Transport,
    url: str,
    part: Path,
    pinned: PinnedFile,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Write ``url`` to ``part``, resuming what is already there, until it holds the pinned bytes; the file is
    deleted and :class:`FetchError` raised when its size or sha256 is not the pinned one. A network fault is asked
    again (``WAITS``); a local error (disk full, permission) is not."""
    cap = pinned.size if pinned.size is not None else TEMPLATE_MAX
    with _on_disk(part):
        part.parent.mkdir(parents=True, exist_ok=True)
        if part.is_symlink() or (part.exists() and not _regular(part)):
            raise FetchError(f"{part} is not a regular file: refused")
        if part.exists() and os.lstat(part).st_nlink > 1:
            raise FetchError(f"{part} has another hard link: refused (nothing was written to it)")
    asks = 0
    while True:
        with _on_disk(part):
            have = part.stat().st_size if part.exists() else 0
            if have > cap:
                part.unlink()
                have = 0
        if pinned.size is not None and have == pinned.size:
            break
        try:
            try:
                status, _total, stream = transport.open(url, have)
            except FetchError:
                raise
            except NET_FAULTS as exc:
                raise _NetFault(type(exc).__name__) from None
            if status == 416:  # nothing after `have`: the server holds no more bytes; the hash decides
                stream.close()
                break
            append = status == 206 and have > 0
            with stream:
                with _on_disk(part):
                    out = _open_part(part, append)
                    if os.fstat(out.fileno()).st_nlink > 1:
                        out.close()
                        raise FetchError(f"{part} has another hard link: refused")
                    if not append:
                        out.truncate(0)
                with out:
                    while True:
                        try:
                            chunk = stream.read(CHUNK)
                        except NET_FAULTS as exc:
                            raise _NetFault(type(exc).__name__) from None
                        if not chunk:
                            break
                        with _on_disk(part):
                            out.write(chunk)
                            written = out.tell()
                        if written > cap:
                            with _on_disk(part):
                                out.close()
                                part.unlink()
                            raise FetchError(
                                f"{pinned.path}: the hub sent more than the "
                                + (f"pinned {pinned.size} bytes" if pinned.size is not None else f"{cap} bytes allowed")
                                + ": refused and deleted"
                            )
            with _on_disk(part):
                size = part.stat().st_size
            if pinned.size is None or size >= pinned.size:
                break
            raise _NetFault("IncompleteRead")
        except _NetFault as fault:
            if asks >= len(WAITS):
                raise FetchError(
                    f"{pinned.path}: the transfer failed {asks + 1} times ({fault}); what arrived is kept and the "
                    "next run resumes it"
                ) from None
            sleep(WAITS[asks])
            asks += 1
    with _on_disk(part):
        got = _sha256(part)
        size = part.stat().st_size
        if got != pinned.sha256:
            part.unlink()
            raise FetchError(
                f"{pinned.path}: sha256 {got[:12]} ({size} bytes) is not the pinned {pinned.sha256[:12]}"
                + (f" ({pinned.size} bytes)" if pinned.size is not None else "")
                + ": refused and deleted; nothing was moved into place"
            )


def _entries(folder: Path) -> tuple[list[str], list[str]]:
    """(the visible regular files, what may not be there: links, special files, hidden entries, empty folders)."""
    files: list[str] = []
    bad: list[str] = []
    for dirpath, dirnames, filenames in os.walk(folder, followlinks=False):
        d = Path(dirpath)
        rel_d = d.relative_to(folder)
        for name in dirnames + filenames:
            p = d / name
            rel = (rel_d / name).as_posix()
            mode = os.lstat(p).st_mode
            if name.startswith("."):
                bad.append(f"{p}: a hidden entry")
            elif stat.S_ISLNK(mode):
                bad.append(f"{p}: a symbolic link")
            elif stat.S_ISDIR(mode):
                if not any(p.iterdir()):
                    bad.append(f"{p}: an empty folder")
            elif stat.S_ISREG(mode):
                files.append(rel)
            else:
                bad.append(f"{p}: not a regular file")
        dirnames[:] = [n for n in dirnames if not n.startswith(".") and not (d / n).is_symlink()]
    return sorted(files), bad


def check_folder(folder: Path, target: Target, *, strict: bool = False) -> list[str]:
    """What differs between ``folder`` and the target's pinned files (empty: it is the pinned build). ``strict``
    (a staged folder before its move) also refuses hidden entries, links, special files and empty folders."""
    if folder.is_symlink() or not folder.is_dir():
        return [f"{folder} is missing" if not folder.exists() else f"{folder} is not a folder"]
    want = {f.path: f for f in target.files}
    have, bad = _entries(folder)
    problems = list(bad) if strict else [b for b in bad if "hidden" not in b and "empty" not in b]
    problems += [f"{folder / p}: not in the pin (an extra file)" for p in have if p not in want]
    for rel, f in want.items():
        p = folder / rel
        if rel not in have:
            if not any(b.startswith(f"{p}:") for b in bad):
                problems.append(f"{p}: missing")
        elif f.size is not None and p.stat().st_size != f.size:
            problems.append(f"{p}: {p.stat().st_size} bytes, pinned {f.size}")
        elif _sha256(p) != f.sha256:
            problems.append(f"{p}: sha256 is not the pinned {f.sha256[:12]}")
    if not problems:
        files = [{"path": f.path, "sha256": f.sha256} for f in target.files]
        if manifest_sha256_of_files(files) != target.manifest_sha256:  # the plan checked it; held here as well
            problems.append(f"{folder}: manifest is not the expected {target.manifest_sha256[:12]}")
    return problems


def check_template(path: Path, target: Target) -> list[str]:
    if not path.exists() and not path.is_symlink():
        return [f"{path} is missing"]
    if not _regular(path):
        return [f"{path} is not a regular file"]
    if _sha256(path) != target.files[0].sha256:
        return [f"{path}: sha256 is not the pinned {target.files[0].sha256[:12]}"]
    return []


def _check(models: Path, t: Target) -> list[str]:
    return (check_folder if t.kind == "folder" else check_template)(models / t.dest, t)


def _exists(p: Path) -> bool:
    return p.exists() or p.is_symlink()


def _done_path(stage: Path, t: Target, f: PinnedFile) -> Path:
    return stage / f.path if t.kind == "folder" else stage / Path(t.dest).name


def _missing_bytes(models: Path, t: Target) -> int:
    """Bytes still to download for a target (what a staged part already holds is not counted again)."""
    stage = models / STAGE / t.dest
    total = 0
    for f in t.files:
        if _regular(_done_path(stage, t, f)):
            continue
        part = stage / PARTS / f.path
        total += max(0, (f.size or 0) - (part.stat().st_size if _regular(part) else 0))
    return total


def _existing(path: Path) -> Path:
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


def _discard(stage: Path) -> None:
    if stage.is_symlink() or stage.is_file():
        stage.unlink()
    elif stage.exists():
        shutil.rmtree(stage)


def fetch_target(
    models: Path,
    t: Target,
    transport: Transport,
    hub: str,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    stage = models / STAGE / t.dest
    parts = stage / PARTS
    _guard(models, models / t.dest, stage, parts)
    with _on_disk(stage):
        if stage.is_symlink() or (stage.exists() and not stage.is_dir()):
            _discard(stage)
    for i, f in enumerate(t.files, 1):
        done = _done_path(stage, t, f)
        with _on_disk(done):
            if _regular(done) and os.lstat(done).st_nlink == 1 and _sha256(done) == f.sha256:
                continue
            if _exists(done):
                _discard(done)
        _say(f"  [{i}/{len(t.files)}] {f.path} ({_human(f.size)})")
        part = parts / f.path
        _guard(models, part.parent, done.parent)
        fetch_file(transport, url_of(hub, t.source, t.revision, f.path), part, f, sleep=sleep)
        with _on_disk(done):
            _guard(models, done.parent)
            done.parent.mkdir(parents=True, exist_ok=True)
            os.replace(part, done)
    with _on_disk(parts):
        if _exists(parts):
            _discard(parts)
    dest = models / t.dest
    if t.kind == "folder":
        problems = check_folder(stage, t, strict=True)
        if problems:
            with _on_disk(stage):
                _discard(stage)
            raise FetchError(
                f"{t.dest}: the staged folder is not the pinned build, so it was removed (the next run starts it "
                "again): " + "; ".join(problems[:5])
            )
        with _on_disk(dest):
            _guard(models, dest)  # before anything is made on the way to it
            dest.parent.mkdir(parents=True, exist_ok=True)
            _guard(models, dest)
            if _exists(dest):
                raise FetchError(f"{dest} appeared during the run (it is left as it is); move it aside and run again")
            os.rename(stage, dest)
    else:
        staged = stage / Path(t.dest).name
        problems = check_template(staged, t)
        if problems:
            with _on_disk(stage):
                _discard(stage)
            raise FetchError("; ".join(problems))
        with _on_disk(dest):
            _guard(models, dest)  # before anything is made on the way to it
            dest.parent.mkdir(parents=True, exist_ok=True)
            _guard(models, dest)
            try:
                os.link(staged, dest)  # never replaces: fails when something is there
            except FileExistsError:
                raise FetchError(
                    f"{dest} appeared during the run (it is left as it is); move it aside and run again"
                ) from None
            _discard(stage)


def _tidy_stage(models: Path, targets: list[Target]) -> None:
    """Remove staged leftovers no current target can reuse, and empty folders; the lock file stays."""
    root = models / STAGE
    if not root.is_dir():
        return
    keep = [Path(t.dest) for t in targets]
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        rel = Path(dirpath).relative_to(root)
        descend = []
        for name in list(dirnames) + filenames:
            r = rel / name
            if r == Path(LOCK) or any(r == k or r.is_relative_to(k) for k in keep):
                continue  # the lock, or a current target's stage (reused)
            if name in dirnames and not (root / r).is_symlink() and any(k.is_relative_to(r) for k in keep):
                descend.append(name)
                continue
            _discard(root / r)
        dirnames[:] = descend
    for p in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        r = p.relative_to(root)
        if any(r == k or r.is_relative_to(k) for k in keep):
            continue  # inside a target's stage: the strict check before the move judges it
        if p.is_dir() and not p.is_symlink() and not any(p.iterdir()):
            p.rmdir()


@contextlib.contextmanager
def _lock(models: Path) -> Iterator[bool]:
    """An exclusive lock for the run (True), or False when another run holds it."""
    path = models / STAGE / LOCK
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        held = os.fstat(fd)
        try:
            now = os.lstat(path)
        except FileNotFoundError:
            yield False  # the lock file was replaced: another run may hold the new one
            return
        yield (held.st_dev, held.st_ino) == (now.st_dev, now.st_ino)
    finally:
        os.close(fd)


# ---------------------------------------------------------------------------------------------------- the command


def _describe(targets: list[Target]) -> None:
    for t in targets:
        what = "folder" if t.kind == "folder" else "file"
        _say(f"- {t.dest} ({what}, {len(t.files)} file(s), {_human(t.size)})")
        _say(f"    from {t.source} at revision {t.revision}; for {', '.join(t.builds)}")
        lic = t.licence
        _say(f"    licence: {lic.get('name')} ({lic.get('spdx') or 'no SPDX id'}), register {lic.get('status')}")


def run(
    profile: str,
    models: Path | None = None,
    *,
    dry_run: bool = False,
    verify_only: bool = False,
    env: dict[str, str] | None = None,
    transport_cls: type[Transport] = Transport,
    free_bytes: Callable[[Path], int] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    registry: Path = REGISTRY,
    register: Path = LICENCE_REGISTER,
    root: Path = ROOT,
) -> int:
    e = dict(os.environ) if env is None else env
    if models is None:
        models, came_from = models_root(e, root)
    else:
        came_from = "--models-dir"
    models = models.absolute()
    _say(f"fetch-weights: models root {models} (from {came_from}); profile {profile}")
    try:
        targets = plan(profile, resolve_env(profile, e, root), registry=registry, register=register, root=root)
    except (RecordError, OSError, ValueError, KeyError, yaml.YAMLError) as exc:
        _err(f"the pin record cannot be used: {exc}")
        return 2
    try:
        guard_targets(models, targets)
    except Outside as exc:
        _err(str(exc))
        return 2
    _say("The pin record (models/registry.yaml and the measured record it names) asks for:")
    _describe(targets)
    known = [t.size for t in targets]
    total = sum(s for s in known if s is not None)
    _say(f"In all about {_human(total)}" + (" plus the template (small)" if None in known else "") + ".")

    if verify_only:
        bad = 0
        for t in targets:
            problems = _check(models, t)
            _say(f"{'ok' if not problems else 'NOT OK'}: {t.dest}")
            for p in problems[:10]:
                _say(f"    {p}")
            bad += bool(problems)
        _say("All present and pinned." if not bad else f"{bad} of {len(targets)} not as pinned.")
        return 1 if bad else 0

    hub = (e.get("HF_ENDPOINT") or HUB).rstrip("/")
    if not transport_cls.url_ok(hub):
        _err(f"HF_ENDPOINT {hub[:8]}…: only an https address is fetched")
        return 2
    try:
        token = token_for(e, hub)
    except FetchError as exc:
        _err(str(exc))
        return 2
    if e.get("HF_TOKEN", "").strip() and token is None:
        _say("HF_TOKEN is set but not sent: the endpoint is not the public hub (HF_ENDPOINT).")
    if dry_run:
        return _dry_run(models, targets, hub, free_bytes)
    try:
        with _lock(models) as got:
            if not got:
                _err(f"another fetch-weights run holds {models / STAGE / LOCK}: wait for it to end, then run again")
                return 1
            return _fetch(models, targets, profile, hub, transport_cls(token, origin(hub)), free_bytes, sleep)
    except Outside as exc:
        _err(str(exc))
        return 2
    except FetchError as exc:
        _err(str(exc))
        return 1
    except OSError as exc:
        _err(str(_local(exc, models / STAGE)))
        return 1


def _in_the_way(models: Path, todo: list[Target]) -> int:
    for t in todo:
        _err(f"{models / t.dest} exists and is not the pinned build:")
        for p in _check(models, t)[:5]:
            print(f"    {p}", file=sys.stderr)
    _err(
        "nothing is changed in a folder already there; move it aside (for example `mv <folder> <folder>.old`) and "
        "run again"
    )
    return 1


def _need_and_free(models: Path, todo: list[Target], free_bytes: Callable[[Path], int] | None) -> tuple[int, int]:
    need = sum(_missing_bytes(models, t) for t in todo)
    free = (free_bytes or (lambda p: shutil.disk_usage(p).free))(_existing(models))
    _say(f"To download: about {_human(need)}; free under {models}: {_human(free)}.")
    return need, free


def _short(models: Path, need: int, free: int) -> str:
    return (
        f"not enough free disk under {models}: {_human(free)} free, {_human(need + MARGIN)} needed (the download and "
        "1 GB to spare); free some space or set TB_MODELS_DIR to a larger disk"
    )


def _dry_run(models: Path, targets: list[Target], hub: str, free_bytes: Callable[[Path], int] | None) -> int:
    present = [t for t in targets if _exists(models / t.dest) and not _check(models, t)]
    todo = [t for t in targets if t not in present]
    for t in present:
        _say(f"already present and pinned: {t.dest}")
    rc = 0
    in_the_way = [t for t in todo if _exists(models / t.dest)]
    if in_the_way:
        rc = _in_the_way(models, in_the_way)
    need, free = _need_and_free(models, todo, free_bytes)
    if todo and free < need + MARGIN:
        _err(_short(models, need, free))
        rc = 1
    for t in todo:
        for f in t.files:
            _say(f"  would fetch {url_of(hub, t.source, t.revision, f.path)}  ({_human(f.size)})")
    _say("Dry run: nothing was downloaded or written." + (" The real run would stop (see above)." if rc else ""))
    return rc


def _fetch(
    models: Path,
    targets: list[Target],
    profile: str,
    hub: str,
    transport: Transport,
    free_bytes: Callable[[Path], int] | None,
    sleep: Callable[[float], None],
) -> int:
    present = [t for t in targets if _exists(models / t.dest) and not _check(models, t)]
    todo = [t for t in targets if t not in present]
    for t in present:
        _say(f"already present and pinned: {t.dest}")
    in_the_way = [t for t in todo if _exists(models / t.dest)]
    if in_the_way:
        return _in_the_way(models, in_the_way)
    with _on_disk(models / STAGE):
        _tidy_stage(models, todo)
    if not todo:
        _say("Nothing to fetch: every folder is the pinned build.")
        _next_step(targets, profile)
        return 0
    need, free = _need_and_free(models, todo, free_bytes)
    if free < need + MARGIN:
        _err(_short(models, need, free))
        return 1
    for t in todo:
        _say(f"Fetching {t.dest} from {t.source} at {t.revision[:12]}")
        try:
            fetch_target(models, t, transport, hub, sleep=sleep)
        except FetchError as exc:
            _err(str(exc))
            _err(f"{t.dest} was not put in place; what arrived intact stays under {models / STAGE} for the next run")
            return 1
        _say(f"ok: {t.dest} is the pinned build")
    with _on_disk(models / STAGE):
        _tidy_stage(models, [])
    _next_step(targets, profile)
    return 0


def _next_step(targets: list[Target], profile: str) -> None:
    _say("")
    _say("Fetched and verified against the pin:")
    for t in targets:
        lic = t.licence
        _say(f"- {t.dest}: {t.source} at {t.revision}; licence {lic.get('name')} ({lic.get('status')})")
        if lic.get("obligation"):
            _say(f"    obligation (licence register {lic.get('register')}): {lic['obligation']}")
    _say(
        "Next step: start the stack, which pins these folders: "
        + ("TB_LLM_MODE=gpu deploy/poc.sh" if profile == "rtxpro6000" else "the start of your install form")
        + " (runbook §27 step 11)."
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], prog="python3 -m tools.fetch_weights")
    ap.add_argument("--profile", required=True, help=f"GPU profile ({', '.join(sorted(PROFILE_PAIRS))})")
    ap.add_argument(
        "--models-dir",
        type=Path,
        default=None,
        help="the models root (default: as the start resolves it: TB_MODELS_DIR, deploy/.env, deploy/models)",
    )
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="list what would be fetched; no network, no writes")
    mode.add_argument("--verify-only", action="store_true", help="check the folders against the pin; no network")
    a = ap.parse_args(argv)
    token = (os.environ.get("HF_TOKEN") or "").strip()
    try:
        return run(a.profile, a.models_dir, dry_run=a.dry_run, verify_only=a.verify_only)
    except Exception as exc:  # a last guard: no traceback, and never the token
        text = f"{type(exc).__name__}: {exc}"
        if token:
            text = text.replace(token, "<HF_TOKEN>")
        _err(f"stopped on an unexpected error: {text}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
