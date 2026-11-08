"""One-command demo (step 5, D-111): the whole step 1-4 flow on the synthetic hospital, seeded and checked, then the
console stays up for clicking through.

On start it runs exactly what ``e2e_simple`` runs (criteria pasted, FEAS report with funnel, investigator approval on
S20, SCREEN list and GOUT-COH cohort list, three investigator marks and one changed, the N1/N2 morning mail, the
REDCap simulator link with a consented and enrolled patient, the screening log), prints the check list, and serves
the console: role homes (S2/S3/S13), the header command field and the three languages (step 4).

    python -m tools.demo [--lang ja|zh-TW|en] [--port 8080] [--host 0.0.0.0]
    make demo                                               # same, on 127.0.0.1:8080
    docker build -f demo/Dockerfile -t trialbox-demo . && docker run -p 8080:8080 -e TB_DEMO_PASSWORD=... trialbox-demo

Accounts: admin, crc (coordinator), pi (investigator), cra (CRO, aggregate only), viewer; one password from
``TB_DEMO_PASSWORD`` (else a random one is printed). Stub model, no network, no secrets, data class D0. Every start
rebuilds the data, so a restart resets the demo. Never load real patient data into it.
"""

from __future__ import annotations

import argparse
import logging
import os
import secrets
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from tools import e2e_simple  # noqa: E402
from tools import feas_demo as fd  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", type=Path, default=Path(os.environ.get("TB_DEMO_DIR", "/tmp/tb-demo")))
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
    out = e2e_simple.run(a.dir, password, a.lang)
    print(e2e_simple.report(out))
    if a.no_serve:
        return 0 if out["ok"] else 1
    import uvicorn

    logging.disable(logging.NOTSET)
    print(f"\nconsole on http://{a.host}:{a.port}/home  accounts: {', '.join(x[0] for x in fd.ACCOUNTS)}")
    if not os.environ.get("TB_DEMO_PASSWORD"):
        print(f"password (all accounts): {password}")
    uvicorn.run(out["result"]["app"], host=a.host, port=a.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
