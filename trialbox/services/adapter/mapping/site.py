"""Where a site's mapping file is found (T-632, D-382; review OPS-011).

A site's own mapping is not in the image. It lives in the site folder on the host, ``deploy/site/mapping/`` (kept
by every update, D-367), which compose mounts read-only into the adapter at ``/etc/trialbox/mapping``. A relative
``settings.data_source.mapping`` such as ``mapping/tw_core/site_c.yaml`` is looked up there first, then in the
image (``services/adapter/``), so the shipped examples keep working:

1. every folder of ``TB_MAPPING_DIR`` (``:``-separated) and the caller's extra folders, in that order;
2. ``/etc/trialbox/mapping`` (the adapter's mount of ``deploy/site/mapping``);
3. the image: ``services/adapter/<mapping>``.

In a site folder the leading ``mapping/`` is dropped: ``mapping/tw_core/site_c.yaml`` is
``deploy/site/mapping/tw_core/site_c.yaml``. A site mapping that ``extends`` a shared profile mapping by a relative
path (the templates say ``extends: ../tw_core/demo_his.yaml``) finds it in the image when the site folder has no
copy: :func:`resolve_extends` (next to the file, then the same place in the image, then the image's folder of that
name).
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

PACKAGED = Path(__file__).resolve().parent  # services/adapter/mapping
ADAPTER_ROOT = PACKAGED.parent  # what a relative settings path is relative to in the image
SITE_MOUNT = Path("/etc/trialbox/mapping")  # deploy/site/mapping in the adapter container (deploy/docker-compose.yml)
DEFAULT = "mapping/tw_core/demo_his.yaml"


def site_dirs(extra: Iterable[Path] = ()) -> list[Path]:
    """The site mapping folders, first match wins."""
    out = [Path(p) for p in (os.environ.get("TB_MAPPING_DIR") or "").split(":") if p]
    out += [Path(p) for p in extra]
    out.append(SITE_MOUNT)
    return out


def _in_site(name: Path) -> Path:
    return Path(*name.parts[1:]) if name.parts[:1] == ("mapping",) and len(name.parts) > 1 else name


def resolve(mapping: str | Path | None, extra: Iterable[Path] = ()) -> Path:
    """The mapping file a ``data_source.mapping`` value names. An absolute path is taken as it is; a relative one is
    the first site folder's file that exists, else the image's (which may not exist: the caller reports that)."""
    name = Path(str(mapping or DEFAULT))
    if name.is_absolute():
        return name
    for d in site_dirs(extra):
        cand = d / _in_site(name)
        try:
            if cand.is_file():
                return cand
        except OSError:  # an unreadable or absent mount
            continue
    return ADAPTER_ROOT / name


def where(path: Path) -> str:
    """``site`` when the file is in a site folder, ``image`` when it is the shipped one, else ``path``."""
    try:
        path.resolve().relative_to(ADAPTER_ROOT)
        return "image"
    except ValueError:
        pass
    for d in site_dirs():
        try:
            path.resolve().relative_to(d.resolve())
            return "site"
        except (ValueError, OSError):
            continue
    return "path"


def resolve_extends(path: Path, extends: str) -> Path:
    """The base a mapping at ``path`` extends. Next to the file first; for a site mapping whose folder has no copy of
    the shared base, the same relative place in the image's mapping folder."""
    base = Path(extends)
    if base.is_absolute():
        return base
    near = (path.parent / base).resolve()
    if near.exists():
        return near
    for d in site_dirs():
        try:
            rel = path.parent.resolve().relative_to(d.resolve())
        except (ValueError, OSError):
            continue
        cand = (PACKAGED / rel / base).resolve()
        if cand.exists():
            return cand
    shipped = PACKAGED / Path(*[p for p in base.parts if p not in ("..", ".")])  # ../tw_core/x -> the image's tw_core/x
    return shipped if shipped.is_file() else near
