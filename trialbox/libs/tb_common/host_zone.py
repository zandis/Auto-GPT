"""The host's time zone, read one way by the install's questions (``tools.box.plan.detect``), by
``deploy/check_host.sh`` and by doctor on the host: the zone the active ``/etc/localtime`` link names (what the
processes run on, and what ``timedatectl set-timezone`` changes), else ``/etc/timezone``. Empty: neither names one.

Standard library only, and run as a script by check_host.sh (``python3 -I libs/tb_common/host_zone.py [host root]``):
the host's ``python3`` reads it before any image is loaded.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def read(host_root: Path = Path("/")) -> str:
    link = host_root / "etc/localtime"
    try:
        target = os.readlink(link) if link.is_symlink() else ""
        if "zoneinfo/" in target:
            name = target.split("zoneinfo/", 1)[1]
            for tree in ("posix/", "right/"):  # the same zone in zoneinfo's other trees
                name = name.removeprefix(tree)
            return name
        named = host_root / "etc/timezone"
        return named.read_text(encoding="utf-8").strip() if named.is_file() else ""
    except OSError:
        return ""


if __name__ == "__main__":
    print(read(Path(sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else "/")))
