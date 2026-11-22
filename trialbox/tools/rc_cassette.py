"""Record or replay a REDCap cassette: the ICD-04 calls against one real REDCap test project (STD-060, CR-062; T-115).

    read -rs TB_RC_CASSETTE_TOKEN; export TB_RC_CASSETTE_TOKEN
    python -m tools.rc_cassette record --url https://redcap.site.example/ \\
        --out tests/fixtures/redcap_cassettes/site-a-16.json [--since 2026-01-01] [--write rows.json]
    unset TB_RC_CASSETTE_TOKEN
    python -m tools.rc_cassette replay tests/fixtures/redcap_cassettes/site-a-16.json

``record`` runs ``rc_bridge.cassette.icd04_run`` against the project and writes every request (never the token) and
answer. Use a test project with synthetic records only, never a production project: the answers are committed.
``--write`` imports the rows of a JSON file with ``forceAutoNumber`` (the write-back path); leave it out to read only.
The token is read from the environment variable named by ``--token-env``, never from the command line.
``replay`` runs the same calls against the file and exits 1 when the client reads any answer differently now.
CI replays every file in ``tests/fixtures/redcap_cassettes/`` (``tests/unit/test_edc_t115.py``).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import httpx  # noqa: E402
from rc_bridge.cassette import Recording, icd04_run, replay, save  # noqa: E402
from rc_bridge.client import RcError, RedcapClient  # noqa: E402


def record(url: str, token_env: str, out: Path, since: str, write: Path | None) -> int:
    token = (os.environ.get(token_env) or "").strip()
    if not token:
        print(f"set {token_env} to the test project's API token", file=sys.stderr)
        return 2
    rows = json.loads(write.read_text(encoding="utf-8")) if write else None
    rec = Recording(httpx.HTTPTransport())
    try:
        with RedcapClient(url, token, http=httpx.Client(transport=rec, timeout=30.0)) as c:
            results = icd04_run(c, since, rows)
    except RcError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 1
    version = results.get("version")
    save(out, version=version if isinstance(version, str) else "", source="redcap", results=results,
         exchanges=rec.exchanges, since=since, write=rows)  # fmt: skip
    print(f"wrote {out} ({len(rec.exchanges)} exchanges, REDCap {version})")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.rc_cassette", description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("--url", required=True, help="the REDCap base URL (https:// only)")
    r.add_argument("--token-env", default="TB_RC_CASSETTE_TOKEN")
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--since", default="", help="also export with dateRangeBegin (YYYY-MM-DD HH:MM:SS)")
    r.add_argument("--write", type=Path, default=None, help="a JSON list of rows to import with forceAutoNumber")
    p = sub.add_parser("replay")
    p.add_argument("file", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "record":
        return record(a.url, a.token_env, a.out, a.since, a.write)
    now, then = replay(a.file)
    if now != then:
        print(f"{a.file}: the client reads the recorded answers differently now", file=sys.stderr)
        for k in sorted(set(now) | set(then)):
            if now.get(k) != then.get(k):
                print(f"  {k}", file=sys.stderr)
        return 1
    print(f"{a.file}: {len(now)} calls replayed equal")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
