"""What `make rehearse-box` needs before it builds anything (D-883).

The release gates in the media step refuse a missing or week-old Trivy database, and the media plus the images loaded
back from it fill a small disk; both used to fail half an hour into the run. This checks them first:

    python -m tools.rehearse_box.preflight --work DIR --trivy-cache DIR [--docker-root DIR] [--min-free-gb N]

Exit 0 with one ``ok:`` line; exit 1 with one line per problem and what to do.
"""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

from tools.supply_chain import vulns

DEFAULT_MIN_FREE_GB = 30  # media (the bundle of the box's images) + the images loaded back + the host image


def _free(path: Path) -> int:
    while not path.exists() and path != path.parent:
        path = path.parent  # a work dir not made yet: the disk it will be on
    return shutil.disk_usage(path).free


def problems(
    work: Path,
    trivy_cache: Path,
    *,
    min_free_gb: int = DEFAULT_MIN_FREE_GB,
    now: dt.datetime | None = None,
    docker_root: Path | None = None,
    free: Callable[[Path], int] = _free,
) -> list[str]:
    out = [
        f"{p}: run `make trivy-db` (the release gates of the media step need a database at most "
        f"{vulns.MAX_DB_AGE_DAYS} days old)"
        for p in vulns.db_problems(trivy_cache, now or dt.datetime.now(dt.UTC))[0]
    ]
    need = min_free_gb << 30
    places = [("the work dir", work)]
    if docker_root is not None and docker_root.is_dir():  # a remote daemon's root is not a folder here
        places.append(("Docker's root", docker_root))
    for what, path in places:
        got = free(path)
        if got < need:
            out.append(
                f"{what} {path} has {got / (1 << 30):.1f} GB free, the rehearsal needs {min_free_gb} GB: free space, "
                "point TB_REHEARSE_DIR elsewhere, or set TB_REHEARSE_MIN_FREE_GB"
            )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.rehearse_box.preflight", description=__doc__)
    ap.add_argument("--work", required=True, type=Path)
    ap.add_argument("--trivy-cache", required=True, type=Path)
    ap.add_argument("--docker-root", type=Path)
    ap.add_argument("--min-free-gb", type=int, default=DEFAULT_MIN_FREE_GB)
    a = ap.parse_args(argv)
    got = problems(a.work, a.trivy_cache, min_free_gb=a.min_free_gb, docker_root=a.docker_root)
    for p in got:
        print(p)
    if got:
        return 1
    print(f"ok: Trivy database fresh, at least {a.min_free_gb} GB free for the work dir")
    return 0


if __name__ == "__main__":
    sys.exit(main())
