"""The host's time zone, read one way by the install's questions (``tools.box.plan.detect``) and by
``deploy/check_host.sh``: ``/etc/timezone``, else the zone the ``/etc/localtime`` link names. Empty: neither names one.

Standard library only, and run as a script by check_host.sh (``python3 libs/tb_common/host_zone.py [host root]``):
the host's ``python3`` reads it before any image is loaded.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def read(host_root: Path = Path("/")) -> str:
    named = host_root / "etc/timezone"
    if named.is_file():
        name = named.read_text(encoding="utf-8").strip()
        if name:
            return name
    link = host_root / "etc/localtime"
    if link.is_symlink():
        target = os.readlink(link)
        if "zoneinfo/" in target:
            return target.split("zoneinfo/", 1)[1]
    return ""


if __name__ == "__main__":
    print(read(Path(sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else "/")))
