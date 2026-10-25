"""``python -m tools.testbench [--host 127.0.0.1] [--port 8765]``: serve the Test Bench (refuses unless TB_ENV is
DEV or TEST, and refuses a non-loopback bind outside its dev container)."""

from __future__ import annotations

import argparse
import os

from tools.testbench.safety import check_bind_host, startup_checks


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools.testbench", description=__doc__)
    ap.add_argument("--host", default=os.environ.get("TB_TESTBENCH_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("TB_TESTBENCH_PORT", "8765")))
    args = ap.parse_args(argv)
    check_bind_host(args.host)
    startup_checks()
    import uvicorn

    from tools.testbench.app import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
