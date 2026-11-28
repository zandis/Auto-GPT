"""``python3 -m tools.box``: the box installer's steps that are not shell (T-729, D-466).

    python3 -m tools.box detect [--deploy deploy]                       # this machine, as JSON
    python3 -m tools.box plan --hardware hw.json --provisional --deploy deploy --out deploy/site/box/answers.json
    python3 -m tools.box plan --hardware hw.json --owner owner.json --deploy deploy --out ...
    python3 -m tools.box ask --hardware hw.json --out owner.json        # the four questions, on this terminal (M1)
    python3 -m tools.box propose --deploy deploy                         # what the network, disks and records suggest
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
import contextlib
import json
import os
import shlex
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tb_common import firstrun
from tb_common.box_answers import OwnerAnswers, fill, parse, without_backup

from tools.box.plan import DEPLOY, Hardware, PlanError, detect, plan, provisional, write
from tools.trialbox.private_file import replace_private

# made by the install (or the wizard's first write) and never replaced by an apply: the database and services hold them
KEEP = frozenset({"POSTGRES_PASSWORD", "IMAP_PASS", "SMTP_PASS", "TB_SERVICE_TOKEN", "CLOUD_LLM_API_KEY"})
CHARTNO_RULE = "TB_CHARTNO_RULE"
# services/adapter/pidmap.py: one row per patient the box has loaded, and the chart numbers of a night that is
# staged and not yet promoted
PID_TABLES = ("pidmap.pid_map", "pidmap.pending")


def _compose_psql(deploy: Path) -> list[str]:
    default = f"docker compose --project-directory {shlex.quote(str(deploy))}"
    compose = shlex.split(os.environ.get("TB_COMPOSE") or default)
    return [*compose, "exec", "-T", "db", "psql", "-U", "trialbox", "-d", "trialbox_wf", "-tAc"]


def _run(argv: list[str]) -> str:
    return subprocess.run(argv, check=True, capture_output=True, text=True, timeout=60).stdout


def pid_map_rows(deploy: Path, run: Callable[[list[str]], str] = _run) -> int | None:
    """How many rows the pid map holds (loaded patients, and the chart numbers of staged nights), asked of the
    box's database; 0 when neither table exists yet (no ingest ever ran); None when the database cannot be asked."""
    psql = _compose_psql(deploy)
    try:
        total = 0
        for table in PID_TABLES:  # fixed names, never a caller's text
            if run([*psql, f"SELECT to_regclass('{table}') IS NOT NULL"]).strip() == "t":
                total += int(run([*psql, f"SELECT count(*) FROM {table}"]).strip())  # nosec B608
        return total
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
            f"{CHARTNO_RULE} is {present} and the answers say {wanted}: the pid map holds {n} rows made under "
            f"{present}, and another rule would give those chart numbers other pseudonyms. The rule is set before "
            "the first night only"
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
    replace_private(env_file, "\n".join(lines) + "\n")  # H-110 (M-IB-2): whole, 0600, never in place
    return changed


def write_whole(path: Path, text: str, mode: int = 0o600) -> None:
    """``text`` to ``path`` by a new file beside it renamed over it: an interrupted write leaves the old file. The
    owner of a file that is there is kept (as root)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            if os.geteuid() == 0 and path.exists():
                os.fchown(f.fileno(), path.stat().st_uid, path.stat().st_gid)
            os.fchmod(f.fileno(), mode)
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise
    folder = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(folder)  # the rename too
    finally:
        os.close(folder)


def owner_answers(raw: dict[str, Any], disks: tuple[str, ...]) -> tuple[OwnerAnswers, list[str]]:
    """The answers of a file: what it does not name at its default. A second disk this machine does not have (the
    answers of another box, replayed) is left for later and said; any other wrong answer is refused."""
    raw, notes = fill(raw), []
    answers, problems = parse(raw, disks=disks)
    if answers is None and {p.field for p in problems} == {"backup_disk"}:
        notes.append("backups: the disk the answers name is not on this machine; they stay on it for now")
        answers, problems = parse(without_backup(raw), disks=disks)
    if answers is None:
        raise PlanError("; ".join(map(str, problems)))
    return answers, notes


def keep_answers(deploy: Path, a: OwnerAnswers) -> None:
    """The replay file: the same answers on another machine give the same settings (no password, no passphrase)."""
    write_whole(deploy / "site" / "box" / "owner.json", json.dumps(a.to_json(), ensure_ascii=False, indent=1) + "\n")


def apply(folder: Path, hw: Hardware, deploy: Path) -> list[str]:
    """The owner's answers into the box's settings (needs the image: ``tools.settings_wizard`` validates)."""
    import tempfile

    from tools import settings_wizard

    raw = firstrun.read(folder / firstrun.ANSWERS)
    try:
        answers, notes = owner_answers(raw, tuple(d.path for d in hw.disks))
    except PlanError as exc:
        raise PlanError(f"the first-run answers do not parse: {exc}") from None
    p = plan(answers, hw, deploy)
    write(p, deploy, deploy / "site" / "box" / "answers.json")
    settings, env, warnings = settings_wizard.build(p.wizard_answers, [deploy / "site" / "mapping"])
    chartno_change(deploy / ".env", env.get(CHARTNO_RULE, ""), lambda: pid_map_rows(deploy))  # before any write
    with tempfile.TemporaryDirectory() as tmp:
        settings_wizard.write(settings, env, deploy / "settings.yaml", Path(tmp) / ".env")
    merge_env(deploy / ".env", env)
    keep_answers(deploy, answers)
    (folder / firstrun.ANSWERS).unlink(missing_ok=True)
    return [*notes, *p.warnings, *warnings]


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
    p.add_argument("--keep", action="store_true", help="a site file that is there stays as it is (the IT form)")
    q = sub.add_parser("ask", help="the four questions, on this terminal (M1)")
    q.add_argument("--hardware", type=Path, required=True)
    q.add_argument("--out", type=Path, required=True)
    q.add_argument("--environment", default="")
    q.add_argument("--seed", type=Path, help="a site seed the vendor signed (verified before: tools.site_seed verify)")
    pr = sub.add_parser("propose", help="what this machine's network, disks and records suggest (read-only)")
    pr.add_argument("--deploy", type=Path, default=DEPLOY)
    sp = sub.add_parser("settings-patch")
    sp.add_argument("--deploy", type=Path, default=DEPLOY)
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
        elif args.cmd == "ask":
            from tools.box import ask

            hw = Hardware.from_json(json.loads(args.hardware.read_text(encoding="utf-8")))
            seed: dict[str, Any] = {}
            if args.seed is not None:
                from tools import site_seed

                seed = site_seed.answers(args.seed)
            got = ask.four(hw, environment=args.environment, seed=seed)
            write_whole(args.out, json.dumps(got, ensure_ascii=False, indent=1) + "\n")
            print(ask.offered_text(str(got["language"])))
        elif args.cmd == "propose":
            from tools.box import detect as found

            found.write(args.deploy)
        elif args.cmd == "settings-patch":  # in the image: the settings are YAML
            from tools.box import needs_apply

            needs_apply.patch_settings(args.deploy, json.load(sys.stdin))
        elif args.cmd == "code":
            print(firstrun.make_code(args.firstrun))
        elif args.cmd == "plan":
            hw = Hardware.from_json(json.loads(args.hardware.read_text(encoding="utf-8")))
            notes: list[str] = []
            if args.provisional:
                answers = provisional(hw)
            else:
                answers, notes = owner_answers(json.loads(args.owner.read_text(encoding="utf-8")),
                                               tuple(x.path for x in hw.disks))  # fmt: skip
            bp = plan(answers, hw, args.deploy)
            if args.keep:  # the IT form: install.sh writes the environment itself (D-837)
                bp.wizard_answers["env_extra"] = {k: v for k, v in bp.env_extra.items() if k != "TB_ENV"}
            write(bp, args.deploy, args.out, keep=args.keep)
            if not args.provisional:
                keep_answers(args.deploy, answers)
            for w in [*notes, *bp.warnings]:
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
