"""``python -m tools.trialbox <command>`` (spec v4 §18). Commands: ``doctor``, ``eval``, ``backup-keygen``,
``backup``, ``backup-check`` (D-178), ``backup-verify``, ``restore`` (D-126, ``tools/trialbox/backup.py``);
``backup-nightly``, ``backup-status`` and ``backup-install`` (the schedule, the age alert and install.sh's backup
step, D-187, D-274, ``backup_schedule.py``); ``secrets``
(per-service tokens, D-128 / D-138, ``svc_secrets.py``), ``logs`` (retention, ``logs.py``) and ``update`` (the update
path behind ``tools/apply_update.sh``, ``update.py``); ``doctor --platform``, ``platform-images`` and
``platform-egress`` for a hospital platform (D-211, ``platform.py``) and ``platform-day2`` for its backup, restore,
logs, audit archive and digest updates (T-633, D-416, ``platform_day2.py``); ``exports`` lists the export ledger (D-149,
``tb_common.flowledger``); ``ops`` runs the console's operations requests and writes their status (D-178, ``ops.py``);
``watchdog`` restarts an unhealthy service and audits it (T-108a, D-360, ``watchdog.py``);
``eval qualify`` qualifies a model pair for a hardware profile and writes the record (D-313, ``tools/qualify.py``);
``mail status`` and ``mail resolve`` show and settle the mail outbox, in the mail-gateway container (T-108c, D-401,
``services/mail_gateway/admin.py``).
``support-bundle`` writes one PHI-free file for a support ticket (T-209b, D-405, ``tools/support_bundle.py``).
``secrets``, ``logs``, ``update``, ``ops`` and ``watchdog`` need only the standard library, so they run with the
host's ``python3`` from the install folder: ``sudo python3 -m tools.trialbox secrets rotate``."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["platform-day2"]:  # its own options (platform_day2.py); `pg` passes its arguments through
        from tools.trialbox import platform_day2

        return platform_day2.main(args[1:])
    if args[:2] == ["eval", "qualify"]:  # its own options (tools/qualify.py), not a suite of eval/suites/
        from tools import qualify

        return qualify.main(args[2:])
    if args[:1] == ["support-bundle"]:  # its own options (tools/support_bundle.py)
        from tools import support_bundle

        return support_bundle.main(args[1:])
    ap = argparse.ArgumentParser(prog="trialbox")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("doctor", help="v4 deployment checks; exit 1 on any FAIL")
    d.add_argument("--env-file", type=Path, default=None)
    d.add_argument("--settings", type=Path, default=None)
    d.add_argument("--routing", type=Path, default=None)
    d.add_argument("--lake-dir", type=Path, default=None, help="the adapter's lake (default TB_LAKE_DIR)")
    d.add_argument("--json", action="store_true")
    d.add_argument("--live", action="store_true", help="also ask the model servers (served names, key; D-177)")
    d.add_argument("--serving", action="store_true", help="only the live model-server check (install.sh)")
    d.add_argument(
        "--verify-all",
        action="store_true",
        help="also hash every pinned model's weights against its pin; a mismatch makes the gateway refuse (D-393)",
    )
    d.add_argument("--weights", action="store_true", help="only the weights check (the timer and the update, D-393)")
    d.add_argument("--platform", action="store_true", help="the install checks on a hospital platform (D-211)")
    d.add_argument("--no-gpu", action="store_true", help="--platform: the GPU checks report 'skipped: no device'")
    d.add_argument("--evidence", type=Path, default=None, help="--platform: write the IQ evidence JSON here")
    d.add_argument("--release", type=Path, default=None, help="--platform: release.json (default: the provisional one)")
    d.add_argument("--manifests", type=Path, default=None, help="--platform: rendered manifests instead of the cluster")
    d.add_argument(
        "--compose-config",
        type=Path,
        default=None,
        help="--platform, --two-device: `docker compose config --format json` (--two-device: its services)",
    )
    d.add_argument(
        "--two-device", action="store_true", help="also check this device of the GB10 two-device form (T-214, D-373)"
    )
    pi = sub.add_parser("platform-images", help="the release-images component from release.json (D-211)")
    pi.add_argument("--release", type=Path, default=None)
    pi.add_argument("--check", action="store_true", help="exit 1 when the committed component differs")
    pi.add_argument("--env", action="store_true", help="print the compose image variables (platform form)")
    pe = sub.add_parser(
        "platform-egress",
        help="the egress allowlist and the doctor job's egress as NetworkPolicy YAML (deploy/egress.py, D-211)",
    )
    pe.add_argument("--env-file", type=Path, default=None)
    e = sub.add_parser("eval", help="run a public evaluation suite and archive the result; 'eval qualify': D-313")
    e.add_argument("suite")
    e.add_argument("--archive", type=Path, default=None)
    k = sub.add_parser("backup-keygen", help="make the backup key pair: private for hospital IT, public for the box")
    k.add_argument("--private", type=Path, required=True, help="e.g. a file on a USB stick that goes in the envelope")
    k.add_argument("--public", type=Path, required=True, help="e.g. deploy/secrets/backup.pub")
    b = sub.add_parser("backup", help="one encrypted backup of databases and files to each --to directory")
    b.add_argument("--to", type=Path, action="append", required=True, help="NAS share, USB disk, second disk ...")
    b.add_argument("--public", type=Path, default=Path(os.environ.get("TB_BACKUP_PUBKEY", "deploy/secrets/backup.pub")))
    b.add_argument("--dir", action="append", default=[], help="name=path (default: TB_BACKUP_DIRS or the volumes)")
    b.add_argument("--keep", type=int, default=int(os.environ.get("TB_BACKUP_KEEP", "14")))
    ck = sub.add_parser("backup-check", help="check a backup is whole without the key (D-178; JSON)")
    ck.add_argument("file", type=Path)
    v = sub.add_parser("backup-verify", help="decrypt a backup and check every hash (needs the private key)")
    v.add_argument("file", type=Path)
    v.add_argument("--key", type=Path, required=True)
    v.add_argument("--deploy", type=Path, default=None, help="where deploy/site/backup-verified.json goes (T-209a)")
    r = sub.add_parser("restore", help="restore databases and files from a backup (needs the private key)")
    r.add_argument("file", type=Path)
    r.add_argument("--key", type=Path, required=True)
    r.add_argument("--dir", action="append", default=[])
    r.add_argument("--yes", action="store_true", help="replace the current data (moved aside, not deleted)")
    r.add_argument(
        "--public",
        type=Path,
        default=Path(os.environ.get("TB_BACKUP_PUBKEY", "deploy/secrets/backup.pub")),
        help="the box's public key: a box that holds data is first kept as an encrypted copy (D-274)",
    )
    r.add_argument(
        "--keep-to",
        type=Path,
        default=Path(os.environ.get("TB_RESTORE_KEEP_DIR", "deploy/pre-restore")),
        help="where that copy goes (default: TB_RESTORE_KEEP_DIR or deploy/pre-restore)",
    )
    r.add_argument("--no-copy", action="store_true", help="keep no copy of the box first (audited)")
    r.add_argument("--other-site", action="store_true", help="restore a backup of another site (new hardware)")
    r.add_argument("--older-ok", action="store_true", help="restore a backup older than 14 days")
    kept = Path(__file__).resolve().parents[2] / "deploy" / "refdata" / "loaded"
    r.add_argument("--refdata", type=Path, default=Path(os.environ.get("TB_REFDATA_DIR") or kept),
                   help="the kept reference packs (default: TB_REFDATA_DIR or deploy/refdata/loaded)")  # fmt: skip
    deploy = Path(__file__).resolve().parents[2] / "deploy"
    bn = sub.add_parser("backup-nightly", help="the scheduled backup to TB_BACKUP_TARGETS, then pgBackRest (D-187)")
    bn.add_argument("--deploy", type=Path, default=deploy)
    bs = sub.add_parser("backup-status", help="age of the newest good off-box backup; exit 1 and alert when too old")
    bs.add_argument("--deploy", type=Path, default=deploy)
    bs.add_argument("--json", action="store_true")
    bs.add_argument("--quiet", action="store_true", help="print nothing when all is well (cron)")
    bi = sub.add_parser("backup-install", help="install.sh's backup step: cron, WAL archiving, first backup (D-274)")
    bi.add_argument("--deploy", type=Path, default=deploy)
    bi.add_argument("--cron-dir", type=Path, default=Path("/etc/cron.d"))
    bi.add_argument("--no-first-run", action="store_true", help="install the cron file only; no first backup")
    s = sub.add_parser("secrets", help="per-service tokens: init, status, rotate (never prints a value)")
    s.add_argument("action", choices=["init", "status", "rotate"])
    s.add_argument("--service", action="append", default=[], help="rotate only these (a service, operator or db)")
    s.add_argument("--deploy", type=Path, default=deploy)
    s.add_argument("--no-restart", action="store_true", help="rotate the files only; restart the services yourself")
    lg = sub.add_parser("logs", help="log retention: collect, prune, archive-audit, daily (all three)")
    lg.add_argument("action", choices=["collect", "prune", "archive-audit", "daily"])
    lg.add_argument("--deploy", type=Path, default=deploy)
    lg.add_argument("--day", default=None, help="collect: the day to collect (default: yesterday)")
    u = sub.add_parser("update", help="apply a verified, staged bundle: backup, apply, migrate, check, roll back")
    u.add_argument("--stage", type=Path, required=True)
    u.add_argument("--summary", type=Path, required=True, help="verify_update.py's JSON summary")
    u.add_argument("--target", choices=["compose", "demo"], default=os.environ.get("TB_UPDATE_TARGET", "compose"))
    u.add_argument("--deploy", type=Path, default=deploy)
    u.add_argument("--no-backup", action="store_true", help="skip the D-126 backup (audited; not for a real box)")
    op = sub.add_parser("ops", help="the console's operations requests: run them, write the status (D-178)")
    op.add_argument("action", choices=["run", "status", "metrics-token"])
    op.add_argument("--deploy", type=Path, default=deploy)
    op.add_argument("--ops-dir", type=Path, default=None, help="default: TB_OPS_DIR or deploy/ops")
    op.add_argument("--local", action="store_true", help="a box in this process (no docker compose)")
    op.add_argument("--watch", type=int, default=0, help="run again every N seconds (0: once)")
    wd = sub.add_parser("watchdog", help="restart an unhealthy service and audit it (T-108a, D-360)")
    wd.add_argument("--deploy", type=Path, default=deploy)
    wd.add_argument("--interval", type=int, default=0, help="run again every N seconds (0: one pass, for a timer)")
    wd.add_argument("--after-minutes", type=float, default=2.0, help="unhealthy this long before a restart")
    wd.add_argument("--max-restarts", type=int, default=3, help="restarts per service in the window, then a person")
    wd.add_argument("--window-hours", type=float, default=6.0)
    wd.add_argument("--dry-run", action="store_true", help="say what would be done; change nothing")
    wd.add_argument("--json", action="store_true")
    sub.add_parser("support-bundle", help="one PHI-free file for a support ticket (T-209b; --out DIR, --help)")
    fl = sub.add_parser("exports", help="the export ledger: every file that left the box (D-149)")
    fl.add_argument("--audit", type=Path, default=Path(os.environ.get("TB_AUDIT_DIR", "/data/audit")))
    fl.add_argument("--days", type=int, default=30)
    fl.add_argument("--json", action="store_true")
    ml = sub.add_parser("mail", help="the mail outbox: status, resolve (T-108c, D-401; in the mail-gateway container)")
    ml.add_argument("action", choices=["status", "resolve"])
    ml.add_argument("key", nargs="?", default=None, help="resolve: one held send key (none: send the queue now)")
    mg = ml.add_mutually_exclusive_group()
    for flag, what in (("sent", "it did arrive"), ("resend", "send it again now"), ("drop", "give up")):
        mg.add_argument(f"--{flag}", dest="decision", action="store_const", const=flag, help=what)
    ml.add_argument("--by", default=None, help="who decides (default: the user)")
    ml.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "mail":
        from mail_gateway import admin as mail_admin

        return mail_admin.main(a.action, a.key, a.decision, a.by, a.json)
    if a.cmd == "exports":
        return _exports_cmd(a)
    if a.cmd == "secrets":
        return _secrets_cmd(a)
    if a.cmd == "ops":
        from tools.trialbox import ops as tb_ops

        return tb_ops.main(a.action, a.deploy, a.ops_dir, a.local, a.watch)
    if a.cmd == "watchdog":
        from tools.trialbox import watchdog as tb_watchdog

        return tb_watchdog.main(a.deploy, interval=a.interval, after_minutes=a.after_minutes,
                                max_restarts=a.max_restarts, window_hours=a.window_hours, dry_run=a.dry_run,
                                as_json=a.json)  # fmt: skip
    if a.cmd == "logs":
        from tools.trialbox import logs as tb_logs

        return tb_logs.main_action(a.action, a.deploy, a.day)
    if a.cmd == "update":
        from tools.trialbox import update as tb_update

        return tb_update.main_apply(a.stage, a.summary, a.target, a.deploy, backup=not a.no_backup)
    if a.cmd in ("backup-nightly", "backup-status", "backup-install"):
        from tools.trialbox import backup_schedule as bsch

        if a.cmd == "backup-install":
            return bsch.main_install(a.deploy, a.cron_dir, first=not a.no_first_run)
        if a.cmd == "backup-nightly":
            return bsch.main_nightly(a.deploy)
        return bsch.main_status(a.deploy, a.json, a.quiet)
    if a.cmd in ("backup-keygen", "backup", "backup-check", "backup-verify", "restore"):
        return _backup_cmd(a)
    if a.cmd in ("platform-images", "platform-egress"):
        return _platform_cmd(a)
    if a.cmd == "doctor":
        from tools.trialbox import doctor

        which = doctor.LIVE if a.serving else (doctor.CHECKS + doctor.LIVE if a.live else doctor.CHECKS)
        if a.weights:
            which = (doctor.LIVE if a.serving else ()) + doctor.WEIGHTS
        elif a.verify_all:
            which = which + doctor.WEIGHTS
        inp = doctor.inputs_from(env_file=a.env_file, settings=a.settings, routing=a.routing, lake=a.lake_dir)
        if a.two_device:
            from tools import two_device as td

            which = which + doctor.TWO_DEVICE
            inp.compose_config = td.compose_config_for(
                inp.env.get("TB_LINK_ROLE", ""), a.compose_config, inp.deploy or td.ROOT / "deploy"
            )
        if not a.platform:
            checks = doctor.run(inp, which)
        else:
            from tools.trialbox import platform as pf

            try:
                pinp = pf.inputs_from(a, inp.env, inp.routing_path)
            except (pf.PlatformError, OSError, ValueError) as exc:
                print(f"doctor --platform: {exc}", file=sys.stderr)
                return 1
            inp.env = pinp.env  # the base checks see what the pods see (the rendered ConfigMaps included)
            inp.platform = True  # no host cron on a cluster: site_tz compares no host zone (D-315)
            checks = doctor.run(inp, which) + pf.run(pinp)
            if a.evidence is not None:
                a.evidence.parent.mkdir(parents=True, exist_ok=True)
                doc = pf.evidence(checks, pinp)
                a.evidence.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
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


def _platform_cmd(a: argparse.Namespace) -> int:
    from tools.trialbox import platform as pf

    if a.cmd == "platform-egress":
        import yaml

        from tools.trialbox.doctor import _egress, inputs_from

        env = pf.platform_env(inputs_from(env_file=a.env_file, settings=None, routing=None, lake=None).env)
        eg = _egress()
        pols, warnings = eg.render_networkpolicy(eg.allowlist(env, eg.ROUTING))
        doctor_pol, doctor_warnings = pf.render_doctor_policy(env)  # the install-check job's own egress (D-211)
        ops_pol, ops_warnings = pf.render_ops_policy(env)  # the log job's API server (T-633, D-416)
        pols = [*pols, *([doctor_pol] if doctor_pol else []), *([ops_pol] if ops_pol else [])]
        for w in [*warnings, *doctor_warnings, *ops_warnings]:
            print(f"warning: {w}", file=sys.stderr)
        print(yaml.safe_dump_all(pols, sort_keys=False, allow_unicode=True) if pols else "# no egress allowed", end="")
        return 0
    rel = a.release or pf.RELEASE
    try:
        if a.env:
            print("\n".join(pf.compose_env(pf.load_release(rel))))
            return 0
        if a.check:
            same = pf.component_matches(rel)
            print(
                f"{pf.COMPONENT.parent}: "
                + ("matches release.json" if same else "differs from release.json: regenerate")
            )
            return 0 if same else 1
        for f in pf.write_component(rel):
            print(f"wrote {f}")
    except pf.PlatformError as exc:
        print(f"platform-images: {exc}", file=sys.stderr)
        return 1
    return 0


def _exports_cmd(a: argparse.Namespace) -> int:
    """What left this box in the last ``--days`` days: when, channel, file, level, approval, recipients, sha256."""
    from dataclasses import asdict
    from datetime import UTC, datetime, timedelta

    from tb_common.flowledger import exports

    rows = exports(a.audit, since=datetime.now(UTC) - timedelta(days=a.days))
    if a.json:
        print(json.dumps([asdict(r) for r in rows], indent=1, ensure_ascii=False))
        return 0
    for r in rows:
        to = ", ".join(r.recipients) or "-"
        print(f"{r.ts[:19]}  {r.channel:<16} {r.identifier_level:<13} {r.filename}  to {to}  [{r.approval}]  "
              f"sha256 {r.sha256[:16]}")  # fmt: skip
    print(f"{len(rows)} exports in the last {a.days} days")
    return 0


def _secrets_cmd(a: argparse.Namespace) -> int:
    from tools.trialbox import svc_secrets as sx

    try:
        if a.action == "status":
            for row in sx.status(a.deploy):
                print("  ".join(f"{k}={v}" for k, v in row.items()))
            return 0
        if a.action == "init":
            res = sx.init(a.deploy)
            print(
                f"tokens made for: {', '.join(res.created) or 'none (all present)'}; "
                f"registry {sx.registry_path(a.deploy)}"
            )
            if res.legacy_kept:
                print("the old shared token still works (with a warning) until: trialbox secrets rotate")
            return 0
        res = sx.rotate(a.deploy, a.service, do_restart=not a.no_restart)
        print(f"rotated: {', '.join(res.rotated)}")
        print(f"restarted: {', '.join(res.restarted) or 'none (restart them yourself)'}")
        print("old shared token: " + ("still accepted (rotate every token to end it)" if res.legacy_kept else "gone"))
        return 0
    except sx.SecretsError as exc:
        print(f"secrets: {exc}", file=sys.stderr)
        return 1


def _backup_cmd(a: argparse.Namespace) -> int:
    from tools.trialbox import backup as bk

    try:
        if a.cmd == "backup-keygen":
            fp = bk.keygen(a.private, a.public)
            print(f"backup key {fp}: give {a.private} to hospital IT in a sealed envelope; the box keeps {a.public}")
            return 0
        if a.cmd == "backup":
            dirs = bk.layout(os.environ, a.dir)
            for f in bk.backup(a.to, a.public, dirs=dirs, keep=a.keep):
                print(f"wrote {f}")
            return 0
        if a.cmd == "backup-check":
            print(json.dumps(bk.check(a.file), indent=1, ensure_ascii=False))
            return 0
        if a.cmd == "backup-verify":
            res = bk.verify(a.file, a.key)
            print(json.dumps(res, indent=1, ensure_ascii=False))
            from tb_common import metrics  # T-209a (D-379, OPS-047): the health check is red 100 days after this

            metrics.record_verified(
                a.deploy or Path(__file__).resolve().parents[2] / "deploy", {**res, "file": a.file.name}
            )
            return 0
        if not a.yes:
            print("restore replaces the box's databases and data folders (the old folders are kept aside): add --yes")
            return 2
        out = bk.restore(a.file, a.key, dirs=bk.layout(os.environ, a.dir), refdata_dir=a.refdata,
                         public_key=a.public, keep_to=a.keep_to, no_copy=a.no_copy, other_site=a.other_site,
                         max_age_days=None if a.older_ok else bk.RESTORE_MAX_AGE_DAYS)  # fmt: skip
        print(json.dumps(out, indent=1, ensure_ascii=False))
        for w in out["warnings"]:
            print(f"restore: warning: {w}", file=sys.stderr)
        if out["refdata"]["missing"]:  # D-187: a backup holds no vendor pack rows; the box is not whole without them
            print(f"restore: the reference data is NOT loaded: put {', '.join(out['refdata']['missing'])}.tar in "
                  f"{a.refdata} (the update bundle or the vendor) and run this restore again, or load it with "
                  "python -m tb_common.refdata load <pack> (RUNBOOK §5)", file=sys.stderr)  # fmt: skip
            return 3
        return 0
    except bk.BackupError as exc:
        print(f"{a.cmd}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
