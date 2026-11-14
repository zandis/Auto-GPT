"""Stand-in for the box's console CONTAINER in the box-run rehearsal: the REAL console app (console.app.create_app,
with its real first-run pages, console.firstrun) served over TLS on 127.0.0.1, in process, on the first-run folder the
real deploy/box-install.sh writes its one-time code to. What is replaced: the container, Caddy in front of it (the
certificate here is the rehearsal's own, for the box's provisional name) and the orchestrator behind it (the console
tests' FakeBackend; the first run asks nothing of it). Its accounts store is a throwaway PostgreSQL of tools/pglocal
(as the unit tests use), removed when the console stops. The paid run reaches the installed box's console through Caddy
on 443.

    <venv python> console.py <first-run folder> <work folder> <port> <cert> <key>
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT), str(ROOT / "libs"), str(ROOT / "services")]

import os  # noqa: E402
import tempfile  # noqa: E402

import uvicorn  # noqa: E402
from console.app import create_app  # noqa: E402
from console.auth import UserStore  # noqa: E402
from tb_common.audit import AuditLog  # noqa: E402

from tests.console.test_console_app import PILOT_ENV, FakeBackend  # noqa: E402
from tools import pglocal  # noqa: E402

fr, work, port, cert, key = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]), sys.argv[4], sys.argv[5]
# under the test clusters' own root (as tests/conftest.py): the server runs as postgres and must reach its folder
pglocal.scratch_root().mkdir(parents=True, exist_ok=True)
pg = Path(tempfile.mkdtemp(prefix="tb-boxrun-pg-", dir=pglocal.scratch_root()))
(work / "pg-root").write_text(str(pg))
pglocal.claim(pg)
pg.chmod(0o755)  # as tests/conftest.py: the server runs as postgres and must reach it
os.environ["TB_DB_URL"] = pglocal.ensure(pg)
env = {**PILOT_ENV, "TB_CONSOLE_DIR": str(work / "console"), "TB_FIRSTRUN_DIR": str(fr), "TB_CONSOLE_MFA": "totp"}
app = create_app(env, backend=FakeBackend(), audit=AuditLog(work / "audit"), users=UserStore())
try:
    uvicorn.run(app, host="127.0.0.1", port=port, ssl_certfile=cert, ssl_keyfile=key, log_level="warning")
finally:
    pglocal.remove(pg)
