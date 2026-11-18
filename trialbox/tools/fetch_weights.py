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

**What is fetched.** Exactly the visible files of that list (hidden files such as ``.gitattributes`` are outside the
pin's manifest), from ``https://huggingface.co/<repository>/resolve/<revision>/<path>``, and the template file. A list
that names a refused type (``.bin``, ``.py`` and the other pickle or code suffixes of ``pin_model``) is refused before
anything is asked for. Each file is written under ``<models>/.fetch-weights/`` (hidden, on the same disk), resumed
with an HTTP range after an interruption, and checked against its size and pinned sha256; a file with another sha256
is deleted and the run fails (it is not asked for again: that is not the network's fault). Only when the staged
folder's manifest is the expected one is it moved into place, by one rename; a staged folder holding any file not in
the list is refused. A folder already in place is never changed: if it holds the pinned build it is reported present,
otherwise the run stops and says to move it aside.

**What is sent.** Only the GET requests for those files (the hub may redirect them to its content store, over https
only). ``HF_TOKEN`` from the environment is sent to the hub's own host when it is set (a gated repository) and never to
the host a download is redirected to; it is never printed. ``HF_ENDPOINT`` replaces the hub's address (a mirror),
https only. Standard library and PyYAML only (``python3-yaml``, runbook §27 step 3): the publisher's tool is not
needed. Nothing runs this at install or start: it runs only when asked.

Exit 0: every folder is the pinned build. 1: a download failed, a hash differed, a folder is in the way, or (with
``--verify-only``) something is missing or differs. 2: a usage error or a pin record that cannot be used.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import http.client
import io
import json
import os
import shutil
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
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
MARGIN = 1 << 30  # free space kept beyond the download (1 GiB)
CHUNK = 8 << 20
WAITS = (2, 5, 15)  # seconds before each further ask after a transfer fault; four asks per file in all
TRANSFER_FAULTS = (urllib.error.URLError, OSError, http.client.HTTPException, TimeoutError)
TEMPLATE_VAR = "JUDGE_CHAT_TEMPLATE"


class RecordError(RuntimeError):
    """The pin record cannot give a verified file list (exit 2)."""


class FetchError(RuntimeError):
    """A download, a hash or a folder in the way (exit 1)."""


class HubRefused(FetchError):
    """The hub answered with an HTTP error that asking again will not change."""


@dataclass(frozen=True)
class PinnedFile:
    path: str  # relative to the folder (or, for the template, to the models root)
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
        "evidence": str(reg.get("evidence") or ""),
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
        if any(part.startswith(".") for part in rel.split("/")):
            continue  # outside the pin's manifest (.gitattributes)
        if rel.startswith("/") or ".." in rel.split("/") or not rel:
            raise RecordError(f"{build}: {rec} names an unsafe path {rel!r}")
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
    the pin record cannot give that without a guess."""
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
        folder = e.get(dir_var) or dir_default
        if not folder or folder.startswith((".", "/")) or ".." in folder.split("/"):
            raise RecordError(f"{dir_var}={folder!r} is not a folder name under the models root")
        source, revision, files = _record_files(row, root)
        exp = str((row.get("expected") or {}).get("manifest_sha256"))
        have = targets.get(folder)
        if have is not None:
            if have.manifest_sha256 != exp:
                raise RecordError(f"{build} and {have.builds[0]} want different weights in the one folder {folder}")
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
            if dest in targets:
                if targets[dest].files[0].sha256 != tpl["sha256"]:
                    raise RecordError(f"two builds want different chat templates at {dest}")
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
    return list(targets.values())


# ---------------------------------------------------------------------------------------------------- transport


class Transport:
    """HTTPS GETs with an optional range. ``open`` returns (status, total size or None, response stream)."""

    allowed: tuple[str, ...] = ("https",)

    def __init__(self, token: str | None = None, hub_host: str | None = None) -> None:
        self._token = token
        self._hub_host = hub_host
        ctx = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE") or None)
        transport = self

        class _Redirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
                transport.check_url(newurl)
                new = super().redirect_request(req, fp, code, msg, headers, newurl)
                if new is not None and urllib.parse.urlsplit(newurl).hostname != transport._hub_host:
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

    def check_url(self, url: str) -> None:
        if urllib.parse.urlsplit(url).scheme not in self.allowed:
            raise HubRefused(f"{urllib.parse.urlsplit(url).hostname}: only https is fetched (asked for {url[:8]}…)")

    def open(self, url: str, start: int = 0) -> tuple[int, int | None, IO[bytes]]:
        self.check_url(url)
        req = urllib.request.Request(url, headers={"User-Agent": "trialbox-fetch-weights"})
        if start:
            req.add_header("Range", f"bytes={start}-")
        if self._token and urllib.parse.urlsplit(url).hostname == self._hub_host:
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
        self.check_url(final)
        total: int | None = None
        crange = resp.headers.get("Content-Range") or ""
        if resp.status == 206 and "/" in crange and crange.rsplit("/", 1)[1].isdigit():
            total = int(crange.rsplit("/", 1)[1])
        elif resp.headers.get("Content-Length", "").isdigit():
            total = int(resp.headers["Content-Length"]) + (start if resp.status == 206 else 0)
        return resp.status, total, resp


# ---------------------------------------------------------------------------------------------------- fetching


def _say(msg: str) -> None:
    print(msg, flush=True)


def _human(n: int | None) -> str:
    if n is None:
        return "size not in the pin record"
    for unit, scale in (("GB", 1e9), ("MB", 1e6), ("kB", 1e3)):
        if n >= scale:
            return f"{n / scale:.1f} {unit}"
    return f"{n} bytes"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def url_of(hub: str, source: str, revision: str, path: str) -> str:
    return f"{hub.rstrip('/')}/{source}/resolve/{revision}/{urllib.parse.quote(path)}"


def fetch_file(
    transport: Transport,
    url: str,
    part: Path,
    pinned: PinnedFile,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Write ``url`` to ``part``, resuming what is already there, until it holds the pinned bytes; the file is
    deleted and :class:`FetchError` raised when its size or sha256 is not the pinned one."""
    part.parent.mkdir(parents=True, exist_ok=True)
    asks = 0
    while True:
        have = part.stat().st_size if part.exists() else 0
        if pinned.size is not None and have > pinned.size:
            part.unlink()
            have = 0
        if pinned.size is not None and have == pinned.size:
            break
        try:
            status, _total, stream = transport.open(url, have)
            if status == 416:  # nothing after `have`: the server holds no more bytes; the hash decides
                break
            mode = "ab" if status == 206 and have else "wb"
            with stream, part.open(mode) as out:
                while chunk := stream.read(CHUNK):
                    out.write(chunk)
                    if pinned.size is not None and out.tell() > pinned.size:
                        raise FetchError(f"{pinned.path}: the hub sent more than the pinned {pinned.size} bytes")
            if pinned.size is None or part.stat().st_size >= pinned.size:
                break
            raise http.client.IncompleteRead(b"", pinned.size - part.stat().st_size)
        except FetchError:
            raise
        except TRANSFER_FAULTS as exc:
            if asks >= len(WAITS):
                raise FetchError(
                    f"{pinned.path}: the transfer failed {asks + 1} times ({type(exc).__name__}); what arrived is "
                    f"kept and the next run resumes it"
                ) from None
            sleep(WAITS[asks])
            asks += 1
    got = _sha256(part)
    size = part.stat().st_size
    if (pinned.size is not None and size != pinned.size) or got != pinned.sha256:
        part.unlink()
        raise FetchError(
            f"{pinned.path}: sha256 {got[:12]} ({size} bytes) is not the pinned {pinned.sha256[:12]}"
            + (f" ({pinned.size} bytes)" if pinned.size is not None else "")
            + ": refused and deleted; nothing was moved into place"
        )


def _visible_files(folder: Path) -> list[str]:
    return sorted(
        p.relative_to(folder).as_posix()
        for p in folder.rglob("*")
        if p.is_file() and not any(part.startswith(".") for part in p.relative_to(folder).parts)
    )


def check_folder(folder: Path, target: Target) -> list[str]:
    """What differs between ``folder`` and the target's pinned files (empty: it is the pinned build)."""
    if not folder.is_dir():
        return [f"{folder} is missing"]
    want = {f.path: f for f in target.files}
    have = _visible_files(folder)
    problems = [f"{folder / p}: not in the pin (an extra file)" for p in have if p not in want]
    for rel, f in want.items():
        p = folder / rel
        if not p.is_file():
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
    if not path.is_file():
        return [f"{path} is missing"]
    if _sha256(path) != target.files[0].sha256:
        return [f"{path}: sha256 is not the pinned {target.files[0].sha256[:12]}"]
    return []


def _present(models: Path, t: Target) -> bool:
    dest = models / t.dest
    if t.kind == "folder":
        return dest.exists() and not check_folder(dest, t)
    return dest.exists() and not check_template(dest, t)


def _missing_bytes(models: Path, t: Target) -> int:
    """Bytes still to download for a target (what a staged part already holds is not counted again)."""
    stage = models / STAGE / t.dest
    total = 0
    for f in t.files:
        done = stage / f.path if t.kind == "folder" else stage / Path(t.dest).name
        if done.is_file():
            continue
        part = stage / PARTS / f.path
        total += max(0, (f.size or 0) - (part.stat().st_size if part.exists() else 0))
    return total


def _existing(path: Path) -> Path:
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


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
    for i, f in enumerate(t.files, 1):
        done = stage / f.path if t.kind == "folder" else stage / Path(t.dest).name
        if done.is_file() and _sha256(done) == f.sha256:
            continue
        _say(f"  [{i}/{len(t.files)}] {f.path} ({_human(f.size)})")
        part = parts / f.path
        fetch_file(transport, url_of(hub, t.source, t.revision, f.path), part, f, sleep=sleep)
        done.parent.mkdir(parents=True, exist_ok=True)
        os.replace(part, done)
    shutil.rmtree(parts, ignore_errors=True)
    dest = models / t.dest
    if t.kind == "folder":
        problems = check_folder(stage, t)
        if problems:
            raise FetchError(f"{t.dest}: the staged folder is not the pinned build: " + "; ".join(problems[:5]))
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(stage, dest)
    else:
        staged = stage / Path(t.dest).name
        problems = check_template(staged, t)
        if problems:
            raise FetchError("; ".join(problems))
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged, dest)
        shutil.rmtree(stage, ignore_errors=True)


def _cleanup_stage(models: Path) -> None:
    root = models / STAGE
    if root.is_dir():
        for p in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if p.is_dir() and not any(p.iterdir()):
                p.rmdir()
        if not any(root.iterdir()):
            root.rmdir()


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
    models: Path,
    *,
    dry_run: bool = False,
    verify_only: bool = False,
    env: dict[str, str] | None = None,
    transport: Transport | None = None,
    free_bytes: Callable[[Path], int] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    registry: Path = REGISTRY,
    register: Path = LICENCE_REGISTER,
    root: Path = ROOT,
) -> int:
    e = dict(os.environ) if env is None else env
    try:
        targets = plan(profile, e, registry=registry, register=register, root=root)
    except (RecordError, OSError, ValueError, KeyError, yaml.YAMLError) as exc:
        print(f"fetch-weights: the pin record cannot be used: {exc}", file=sys.stderr)
        return 2
    _say(f"fetch-weights: profile {profile}, models folder {models}")
    _say("The pin record (models/registry.yaml and the measured record it names) asks for:")
    _describe(targets)
    known = [t.size for t in targets]
    total = sum(s for s in known if s is not None)
    _say(f"In all about {_human(total)}" + (" plus the template (small)" if None in known else "") + ".")

    if verify_only:
        bad = 0
        for t in targets:
            problems = (check_folder if t.kind == "folder" else check_template)(models / t.dest, t)
            _say(f"{'ok' if not problems else 'NOT OK'}: {t.dest}")
            for p in problems[:10]:
                _say(f"    {p}")
            bad += bool(problems)
        _say("All present and pinned." if not bad else f"{bad} of {len(targets)} not as pinned.")
        return 1 if bad else 0

    present = [t for t in targets if _present(models, t)]
    todo = [t for t in targets if t not in present]
    for t in present:
        _say(f"already present and pinned: {t.dest}")
    in_the_way = [t for t in todo if (models / t.dest).exists()]
    if in_the_way:
        for t in in_the_way:
            problems = (check_folder if t.kind == "folder" else check_template)(models / t.dest, t)
            print(f"fetch-weights: {models / t.dest} exists and is not the pinned build:", file=sys.stderr)
            for p in problems[:5]:
                print(f"    {p}", file=sys.stderr)
        print(
            "fetch-weights: nothing is changed in a folder already there; move it aside "
            "(for example `mv <folder> <folder>.old`) and run again",
            file=sys.stderr,
        )
        return 1
    if not todo:
        _say("Nothing to fetch: every folder is the pinned build.")
        _next_step(targets, profile)
        return 0

    need = sum(_missing_bytes(models, t) for t in todo)
    free = (free_bytes or (lambda p: shutil.disk_usage(p).free))(_existing(models))
    _say(f"To download: about {_human(need)}; free under {models}: {_human(free)}.")
    short = free < need + MARGIN
    if dry_run:
        if short:
            _say(f"Not enough free disk: {_human(need + MARGIN)} needed (the download and 1 GB to spare).")
        hub = (e.get("HF_ENDPOINT") or HUB).rstrip("/")
        for t in todo:
            for f in t.files:
                _say(f"  would fetch {url_of(hub, t.source, t.revision, f.path)}  ({_human(f.size)})")
        _say("Dry run: nothing was downloaded or written.")
        return 0
    if short:
        print(
            f"fetch-weights: not enough free disk under {models}: {_human(free)} free, {_human(need + MARGIN)} needed "
            "(the download and 1 GB to spare); free some space or set TB_MODELS_DIR to a larger disk",
            file=sys.stderr,
        )
        return 1

    hub = (e.get("HF_ENDPOINT") or HUB).rstrip("/")
    tr = transport or Transport(e.get("HF_TOKEN") or None, urllib.parse.urlsplit(hub).hostname)
    try:
        tr.check_url(hub)
    except HubRefused as exc:
        print(f"fetch-weights: HF_ENDPOINT: {exc}", file=sys.stderr)
        return 2
    models.mkdir(parents=True, exist_ok=True)
    for t in todo:
        _say(f"Fetching {t.dest} from {t.source} at {t.revision[:12]}")
        try:
            fetch_target(models, t, tr, hub, sleep=sleep)
        except FetchError as exc:
            print(f"fetch-weights: {exc}", file=sys.stderr)
            print(
                f"fetch-weights: {t.dest} was not put in place; what arrived intact stays under {models / STAGE} "
                "and the next run resumes it",
                file=sys.stderr,
            )
            return 1
        _say(f"ok: {t.dest} is the pinned build")
    _cleanup_stage(models)
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
        help="the models root (default: TB_MODELS_DIR, else deploy/models)",
    )
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="list what would be fetched; no network, no writes")
    mode.add_argument("--verify-only", action="store_true", help="check the folders against the pin; no network")
    a = ap.parse_args(argv)
    models = a.models_dir or Path(os.environ.get("TB_MODELS_DIR") or ROOT / "deploy" / "models")
    return run(a.profile, models.resolve(), dry_run=a.dry_run, verify_only=a.verify_only)


if __name__ == "__main__":
    sys.exit(main())
