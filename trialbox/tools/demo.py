"""One-command demo (step 5, D-111): the whole step 1-4 flow on the synthetic hospital, seeded and checked, then the
console stays up for clicking through.

On start it runs exactly what ``e2e_simple`` runs (criteria pasted, FEAS report with funnel, investigator approval on
S20, SCREEN list and GOUT-COH cohort list, three investigator marks and one changed, the N1/N2 morning mail, the
REDCap simulator link with a consented and enrolled patient, the screening log), prints the check list, and serves
the console: role homes (S2/S3/S13), the header command field and the three languages (step 4).

    python -m tools.demo [--lang ja|zh-TW|en] [--port 8080] [--host 0.0.0.0]
    make demo                                               # same, on 127.0.0.1:8080
    docker build -f demo/Dockerfile -t trialbox-demo . && docker run -p 8080:8080 -e TB_DEMO_PASSWORD=... trialbox-demo

Accounts: admin, crc (coordinator), pi (investigator), subpi (sub-investigator), cra (CRO, aggregate only), viewer;
one password from ``TB_DEMO_PASSWORD`` (else a random one is printed). Stub model, no network, no secrets, data class
D0. Every start rebuilds the data, so a restart resets the demo. Never load real patient data into it.
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import os
import secrets
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from tools import e2e_simple  # noqa: E402
from tools import feas_demo as fd  # noqa: E402

SEEDED = [*(x[0] for x in fd.ACCOUNTS), "subpi"]  # e2e_simple adds the sub-investigator (stage 15)


@contextlib.contextmanager
def https_seeding() -> Iterator[None]:
    """T-501 (ROLE-002, OPS-007): seed over ``https://testserver``. The image sets ``TB_CONSOLE_SECURE_COOKIE=1``; the
    seeding clients of e2e_simple are in-process ``TestClient``s, which send a Secure cookie back only over https."""
    from fastapi.testclient import TestClient

    init = TestClient.__init__

    def https_init(self: TestClient, app: Any, base_url: str = "https://testserver", *args: Any, **kw: Any) -> None:
        init(self, app, base_url, *args, **kw)

    TestClient.__init__ = https_init  # type: ignore[method-assign]
    try:
        yield
    finally:
        TestClient.__init__ = init  # type: ignore[method-assign]


def mark_temp_root() -> None:
    """T-501 (OPS-077): the cluster for_work starts lives under ``TB_TEST_ROOT`` when one is set; mark that root, so
    the next run with the same root is not refused as a folder of other files."""
    if os.environ.get("TB_TEST_ROOT") and not os.environ.get("TB_DB_URL") and not os.environ.get("TB_PG_DIR"):
        from tools import pglocal

        pglocal.mark_test_root(Path(os.environ["TB_TEST_ROOT"]))


def main(argv: list[str] | None = None) -> int:
    from tb_common.config import adopt_site_tz

    adopt_site_tz()  # a synthetic site in one process: its site.tz as TB_TZ (D-315)
    from tools.pglocal import scratch_root  # D-201: never a fixed /tmp path

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", type=Path, default=Path(os.environ.get("TB_DEMO_DIR") or scratch_root() / "tb-demo"))
    ap.add_argument("--lang", default=os.environ.get("TB_DEMO_LANG", "ja"), choices=["ja", "zh-TW", "en"])
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    ap.add_argument("--host", default=os.environ.get("TB_DEMO_HOST", "127.0.0.1"))
    ap.add_argument("--no-serve", action="store_true", help="seed and check, then exit")
    ap.add_argument("--fresh", action="store_true", help="accepted for compatibility; every start is fresh")
    a = ap.parse_args(argv)
    os.environ.setdefault("TB_ENV", "DEV")
    logging.disable(logging.INFO)
    if a.dir.exists():
        shutil.rmtree(a.dir)
    a.dir.mkdir(parents=True)
    password = os.environ.get("TB_DEMO_PASSWORD") or secrets.token_urlsafe(12)
    mark_temp_root()
    with https_seeding():
        out = e2e_simple.run(a.dir, password, a.lang)
    print(e2e_simple.report(out))
    if a.no_serve:
        return 0 if out["ok"] else 1
    import uvicorn

    logging.disable(logging.NOTSET)
    print(f"\nconsole on http://{a.host}:{a.port}/home  accounts: {', '.join(SEEDED)}")
    if not os.environ.get("TB_DEMO_PASSWORD"):
        print(f"password (all accounts): {password}")
    uvicorn.run(out["result"]["app"], host=a.host, port=a.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
