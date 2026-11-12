"""``python3 -m tools.box``: the box installer's steps that are not shell (T-729, D-466).

    python3 -m tools.box detect [--deploy deploy]                       # this machine, as JSON
    python3 -m tools.box plan --hardware hw.json --provisional --deploy deploy --out deploy/site/box/answers.json
    python3 -m tools.box plan --hardware hw.json --owner owner.json --deploy deploy --out ...
    python3 -m tools.box code --firstrun /run/trialbox-firstrun          # a new one-time code (printed once)
    python -m tools.box apply --firstrun DIR --hardware hw.json --deploy deploy   # in the trialbox-py image

``plan`` writes the site files under ``--deploy`` and the settings wizard's answers file, and prints the install's
flags on its last line (``install-args: --mode gpu --gpu rtxpro6000``). ``detect``, ``plan`` and ``code`` need only
the standard library (the host's ``python3``, before the bundle's images are loaded). ``apply`` runs after the owner
finished the first-run wizard: it reads the owner's answers from the first-run folder, plans again with them, writes
``settings.yaml`` through the settings wizard and merges the owner's lines into the existing ``deploy/.env`` (the
service passwords and tokens the install made are kept), and removes the answers.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from tb_common import firstrun
from tb_common.box_answers import OwnerAnswers, parse

from tools.box.plan import DEPLOY, Hardware, PlanError, detect, plan, provisional, write

# made by the install (or the wizard's first write) and never replaced by an apply: the database and services hold them
KEEP = frozenset({"POSTGRES_PASSWORD", "IMAP_PASS", "SMTP_PASS", "TB_SERVICE_TOKEN", "CLOUD_LLM_API_KEY"})
CHARTNO_RULE = "TB_CHARTNO_RULE"
PID_MAP = "pidmap.pid_map"  # services/adapter/pidmap.py: one row per patient the box has loaded


def _compose_psql(deploy: Path) -> list[str]:
    default = f"docker compose --project-directory {shlex.quote(str(deploy))}"
    compose = shlex.split(os.environ.get("TB_COMPOSE") or default)
    return [*compose, "exec", "-T", "db", "psql", "-U", "trialbox", "-d", "trialbox_wf", "-tAc"]


def _run(argv: list[str]) -> str:
    return subprocess.run(argv, check=True, capture_output=True, text=True, timeout=60).stdout


def pid_map_rows(deploy: Path, run: Callable[[list[str]], str] = _run) -> int | None:
    """How many patients the box has loaded (rows of the pid map), asked of the box's database; 0 when the table
    does not exist yet (no ingest ever ran); None when the database cannot be asked."""
    psql = _compose_psql(deploy)
    try:
        if run([*psql, f"SELECT to_regclass('{PID_MAP}') IS NOT NULL"]).strip() != "t":
            return 0
        return int(run([*psql, f"SELECT count(*) FROM {PID_MAP}"]).strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def chartno_change(env_file: Path, new: str, rows: Callable[[], int | None]) -> None:
    """D-579: the chart-number rule changes only while the pid map is empty. A rule set on a box that has loaded
    patients gives their chart numbers other pseudonyms (and the pid map then reports a wrong site key). No rule
    and ``asis`` are the same rule. Raises :class:`PlanError`; says nothing when the rule stays as it is."""
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    have = [ln.split("=", 1)[1].strip() for ln in lines if ln.startswith(f"{CHARTNO_RULE}=")]
    present, wanted = (have[-1] if have and have[-1] else "asis"), (new.strip() or "asis")
    if present == wanted:
        return
    n = rows()
    if n is None:
        raise PlanError(
            f"{CHARTNO_RULE} is {present} and the answers say {wanted}: the database could not be asked whether "
            "patients are loaded, so the rule is not changed (start the box and apply again)"
        )
    if n:
        raise PlanError(
            f"{CHARTNO_RULE} is {present} and the answers say {wanted}: the box holds {n} patients under {present}, "
            "and another rule would give their chart numbers other pseudonyms. The rule is set before the first "
            "night only"
        )


def merge_env(env_file: Path, new: dict[str, str]) -> list[str]:
    """``new`` into ``env_file``: each key replaced in place or added; :data:`KEEP` keys never touched. Returns the
    keys that changed."""
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    have = {ln.split("=", 1)[0]: i for i, ln in enumerate(lines) if "=" in ln and not ln.startswith("#")}
    changed = []
    for k, v in new.items():
        if k in KEEP and k in have:
            continue
        line = f"{k}={v}"
        if k in have:
            if lines[have[k]] != line:
                lines[have[k]] = line
                changed.append(k)
        else:
            lines.append(line)
            changed.append(k)
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    env_file.chmod(0o600)
    return changed


def apply(folder: Path, hw: Hardware, deploy: Path) -> list[str]:
    """The owner's answers into the box's settings (needs the image: ``tools.settings_wizard`` validates)."""
    import tempfile

    from tools import settings_wizard

    raw = firstrun.read(folder / firstrun.ANSWERS)
    answers, problems = parse(raw, disks=tuple(d.path for d in hw.disks))
    if answers is None:
        raise PlanError("the first-run answers do not parse: " + "; ".join(map(str, problems)))
    p = plan(answers, hw, deploy)
    write(p, deploy, deploy / "site" / "box" / "answers.json")
    settings, env, warnings = settings_wizard.build(p.wizard_answers, [deploy / "site" / "mapping"])
    chartno_change(deploy / ".env", env.get(CHARTNO_RULE, ""), lambda: pid_map_rows(deploy))  # before any write
    with tempfile.TemporaryDirectory() as tmp:
        settings_wizard.write(settings, env, deploy / "settings.yaml", Path(tmp) / ".env")
    merge_env(deploy / ".env", env)
    (folder / firstrun.ANSWERS).unlink(missing_ok=True)
    return [*p.warnings, *warnings]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools.box", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("detect")
    d.add_argument("--deploy", type=Path, default=DEPLOY)
    p = sub.add_parser("plan")
    p.add_argument("--hardware", type=Path, required=True)
    who = p.add_mutually_exclusive_group(required=True)
    who.add_argument("--provisional", action="store_true", help="before the owner's answers: serve the wizard only")
    who.add_argument("--owner", type=Path, help="the owner's answers (JSON)")
    p.add_argument("--deploy", type=Path, default=DEPLOY)
    p.add_argument("--out", type=Path, required=True)
    c = sub.add_parser("code")
    c.add_argument("--firstrun", type=Path, required=True)
    a = sub.add_parser("apply")
    a.add_argument("--firstrun", type=Path, required=True)
    a.add_argument("--hardware", type=Path, required=True)
    a.add_argument("--deploy", type=Path, default=DEPLOY)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "detect":
            print(json.dumps(detect(args.deploy).to_json(), ensure_ascii=False, indent=1))
        elif args.cmd == "code":
            print(firstrun.make_code(args.firstrun))
        elif args.cmd == "plan":
            hw = Hardware.from_json(json.loads(args.hardware.read_text(encoding="utf-8")))
            answers: OwnerAnswers | None
            if args.provisional:
                answers = provisional(hw)
            else:
                answers, problems = parse(json.loads(args.owner.read_text(encoding="utf-8")),
                                          disks=tuple(x.path for x in hw.disks))  # fmt: skip
                if answers is None:
                    raise PlanError("; ".join(map(str, problems)))
            bp = plan(answers, hw, args.deploy)
            write(bp, args.deploy, args.out)
            for w in bp.warnings:
                print(f"note: {w}", file=sys.stderr)
            print("install-args: " + " ".join(bp.install_args))
        else:
            hw = Hardware.from_json(json.loads(args.hardware.read_text(encoding="utf-8")))
            for w in apply(args.firstrun, hw, args.deploy):
                print(f"note: {w}", file=sys.stderr)
            print(f"applied the owner's answers to {args.deploy}/settings.yaml and {args.deploy}/.env")
    except PlanError as exc:
        print(f"box: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
