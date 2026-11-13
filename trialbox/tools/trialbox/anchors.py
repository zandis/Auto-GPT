"""ANCHOR-MOUNT (D-638): the console reads the signed heads of the audit chain on an installed box.

The anchor folders (``TB_AUDIT_ANCHOR_TARGETS`` in ``deploy/.env``) are host paths. The console's audit page checks
the chain against their signed heads, but the console did not mount them, so compose cleared the name for it
(D-562). A list of host paths cannot be written as one line of a compose file, so the installer writes a small
compose file of its own, ``deploy/site/compose.anchors.yml``, and keeps it in ``COMPOSE_FILE``:

* each folder is mounted into the console **read-only**, at ``/anchors/<n>/<the folder's name>``: never over a
  folder of the image, and the page shows the folder's own name;
* a folder that is not there is not made on the host (``create_host_path: false``): the console then does not
  start, and the installer says which folder;
* the console gets ``TB_AUDIT_ANCHOR_TARGETS`` with the paths inside the container.

Nothing else of the box changes: no other service gets a folder, and the console cannot write a signed head.
``trialbox doctor`` (check ``anchor_mount``) says when folders are set and the file is missing, not in
``COMPOSE_FILE``, or written for other folders.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path

ENV = "TB_AUDIT_ANCHOR_TARGETS"
NAME = "site/compose.anchors.yml"  # under deploy/: deploy/site is the site's own folder and survives an update
INSIDE = "/anchors"
HEADER = (
    "# Written by the installer (python3 -m tools.trialbox anchors-compose; D-638). Do not edit: change\n"
    f"# {ENV} in deploy/.env and run deploy/install.sh again.\n"
)


class AnchorError(ValueError):
    """An anchor folder that cannot be mounted as it is written."""


def plan(env: Mapping[str, str]) -> list[tuple[str, str]]:
    """``(host folder, path inside the console)`` for each folder of ``TB_AUDIT_ANCHOR_TARGETS``, in its order; a
    folder named twice is one."""
    out: list[tuple[str, str]] = []
    for raw in (env.get(ENV) or "").split(os.pathsep):
        folder = raw.strip()
        if not folder or folder in [h for h, _ in out]:
            continue
        parts = folder.split("/")
        if (
            not folder.startswith("/")
            or folder.rstrip("/") == ""
            or any(p in (".", "..") for p in parts)
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in folder)
        ):
            raise AnchorError(
                f"{ENV}: {folder!r} is not a plain absolute folder (no '.', no '..', no control character)"
            )
        folder = folder.rstrip("/")
        out.append((folder, f"{INSIDE}/{len(out)}/{folder.rsplit('/', 1)[1]}"))
    return out


def _lit(s: str) -> str:
    """A string as compose reads it literally: JSON quoting is YAML's, and ``$`` is not the start of a variable."""
    return json.dumps(s.replace("$", "$$"), ensure_ascii=False)


def compose_text(folders: list[tuple[str, str]]) -> str:
    lines = [HEADER.rstrip("\n"), "services:", "  console:", "    environment:"]
    lines.append(f"      {ENV}: {_lit(os.pathsep.join(i for _, i in folders))}")
    lines.append("    volumes:")
    for host, inside in folders:
        lines += [
            "      - type: bind",
            f"        source: {_lit(host)}",
            f"        target: {_lit(inside)}",
            "        read_only: true",
            "        bind: {create_host_path: false}",
        ]
    return "\n".join(lines) + "\n"


def write(deploy: Path, env: Mapping[str, str]) -> Path | None:
    """Write ``deploy/site/compose.anchors.yml`` for the folders of ``env``; with no folder the file is taken away.
    The path written, or None."""
    path = deploy / NAME
    folders = plan(env)
    if not folders:
        path.unlink(missing_ok=True)
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".new")
    tmp.write_text(compose_text(folders), encoding="utf-8")
    tmp.chmod(0o644)  # every later compose command reads it, as root: only its owner changes it
    tmp.replace(path)
    return path


def problem(deploy: Path, env: Mapping[str, str]) -> str:
    """Why the console of this box does not read the anchor folders of ``env``; empty when it does or none is set."""
    try:
        folders = plan(env)
    except AnchorError as exc:
        return str(exc)
    if not folders:
        return ""
    path = deploy / NAME
    if not path.is_file():
        return f"deploy/{NAME} is not there (a box installed before the console could read the anchor folders)"
    if path.read_text(encoding="utf-8") != compose_text(folders):
        return f"deploy/{NAME} was written for other folders than {ENV} names now"
    listed = [f for f in (env.get("COMPOSE_FILE") or "").split(os.pathsep) if f.endswith("/" + NAME)]
    if not listed:
        return f"deploy/{NAME} is not in COMPOSE_FILE of deploy/.env, so no compose command reads it"
    return ""


def read_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() and not key.lstrip().startswith("#"):
                out[key.strip()] = value.strip()
    return out


def main_action(deploy: Path) -> int:
    """``trialbox anchors-compose``: write (or take away) the file for ``deploy/.env``; print its path when written."""
    import sys

    try:
        path = write(deploy, read_env(deploy / ".env"))
    except AnchorError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if path is not None:
        print(path)
    return 0
