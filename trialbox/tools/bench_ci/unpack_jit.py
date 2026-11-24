"""The one-job runner configuration, unpacked into the runner's own files (card H-105, the review's F9).

The code host's just-in-time configuration is a base64 JSON object of the runner's three settings files, each
base64. They are written into the runner's folder, so the runner starts with no argument that carries a credential.
Anything else in the object, or a configuration of another form, is refused: the runner then does not start.

    python3 -I unpack_jit.py CONFIG_FILE RUNNER_DIR
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

FILES = (".runner", ".credentials", ".credentials_rsaparams")


def unpack(config: str) -> dict[str, bytes]:
    try:
        obj = json.loads(base64.b64decode(config.strip(), validate=True))
    except (binascii.Error, ValueError) as exc:
        raise ValueError("the configuration is not base64 JSON") from exc
    if not isinstance(obj, dict) or set(obj) != set(FILES):
        raise ValueError(f"the configuration holds {sorted(obj) if isinstance(obj, dict) else 'no object'}")
    out: dict[str, bytes] = {}
    for name in FILES:
        try:
            out[name] = base64.b64decode(str(obj[name]), validate=True)
        except binascii.Error as exc:
            raise ValueError(f"{name} is not base64") from exc
    return out


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("usage: unpack_jit.py CONFIG_FILE RUNNER_DIR", file=sys.stderr)
        return 2
    try:
        files = unpack(Path(args[0]).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"bench CI: the one-job configuration is refused: {exc}", file=sys.stderr)
        return 2
    for name, data in files.items():
        fd = os.open(Path(args[1]) / name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
