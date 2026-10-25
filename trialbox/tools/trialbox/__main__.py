"""``python -m tools.trialbox <command>`` (spec v4 §18). Commands in this build: ``doctor``, ``eval``."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trialbox")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("doctor", help="v4 deployment checks; exit 1 on any FAIL")
    d.add_argument("--env-file", type=Path, default=None)
    d.add_argument("--settings", type=Path, default=None)
    d.add_argument("--routing", type=Path, default=None)
    d.add_argument("--dataplat-workdir", type=Path, default=None)
    d.add_argument("--json", action="store_true")
    e = sub.add_parser("eval", help="run a public evaluation suite and archive the result")
    e.add_argument("suite")
    e.add_argument("--archive", type=Path, default=None)
    a = ap.parse_args(argv)
    if a.cmd == "doctor":
        from tools.trialbox import doctor

        checks = doctor.run(
            doctor.inputs_from(env_file=a.env_file, settings=a.settings, routing=a.routing, dataplat=a.dataplat_workdir)
        )
        if a.json:
            print(json.dumps([c.__dict__ for c in checks], indent=1, ensure_ascii=False))
        else:
            print(doctor.render(checks))
        return 0 if doctor.ok(checks) else 1
    from tools.trialbox import eval as tb_eval

    with tempfile.TemporaryDirectory(prefix=f"eval-{a.suite}-") as tmp:
        try:
            result, path = tb_eval.run_suite(a.suite, Path(tmp), a.archive or tb_eval.ARCHIVE)
        except tb_eval.SuiteRefused as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 2
    print(json.dumps({k: v for k, v in result.items() if k != "datasets"}, indent=1, ensure_ascii=False))
    print(f"archived: {path}")
    return 1 if result.get("passed") is False else 0


if __name__ == "__main__":
    raise SystemExit(main())
