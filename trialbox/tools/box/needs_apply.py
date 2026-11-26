"""The host's half of the page "Information still needed" (M1, U5-5; D-1280): one item's answer into the box.

The console writes a request in the operations folder (``tools/trialbox/ops.py``, action ``site_needs``); the host's
runner calls :func:`run`. Only what the item names is changed, in ``deploy/.env`` and ``settings.yaml``, each written
whole and renamed; every other line stays as it is, a person's own change included. The item then leaves the stand-ins
list, so its gate lifts. Order: the files first, the mark last: cut off in between, the item is still open and the same
answer is given again.

A value that cannot be used is refused with its reason and changes nothing: the item stays open.

:func:`clean` is what the page checks an answer with too. Standard library at import (the host's ``python3``).
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from tb_common import box_answers as ba
from tb_common import host_folders, site_country, site_needs

from tools.box.plan import BOX_SOURCE_MOUNT, chart_pattern, site_id

#: the fields the page asks for each item; an item that is not here is given on the host (the backup key's ceremony)
FIELDS: dict[str, tuple[str, ...]] = {
    "data_source": ("source_kind", "source_dir"),
    "chart_number": ("chartno_example", "chartno_rule"),
    "backup_target": ("backup_dir", "second_disk"),
    "backup_alarm": ("health_page_person",),
    "audit_share": ("anchor_dir",),
    "site_name": ("site_name",),
    "office_mailbox": ("sae_office_mailbox",),
    "mail_relay": ("smtp_host", "smtp_port"),
    "request_mailbox": ("imap_host", "mta_authserv_id"),
    "certificate": ("tls_root_confirmed_by",),
}
SOURCE_KINDS = ("csv", ba.SourceKind.SSMIX2.value)
ITEM_FIELDS = tuple(f for fields in FIELDS.values() for f in fields)


class NeedsError(ValueError):
    """What was given cannot be used; ``code`` is a message key (``stillneeded.err.<code>``)."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code


@dataclass
class Change:
    env: dict[str, str] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)  # dotted path -> value
    owner: dict[str, Any] = field(default_factory=dict)  # the replay file's answers


def rule_of(example: str) -> str:
    """The rule of one chart number as printed: its width, digits or hexadecimal."""
    text = example.strip()
    if text.isascii() and text.isdigit():
        return f"digits:{len(text)}"
    return f"hex:{len(text)}" if text.isascii() and all(c in "0123456789abcdefABCDEF" for c in text) and text else ""


def clean(item: str, given: Mapping[str, str]) -> Change:
    """What an answer changes. Raises :class:`NeedsError` for an item the page does not take and a value that cannot
    be used."""
    if item not in FIELDS:
        raise NeedsError("item", f"{item[:40]} is not filled in on the page")
    v = {k: str(given.get(k) or "").strip()[:255] for k in FIELDS[item]}
    if any(ch < " " or ch in "\u0085  \x7f" for x in v.values() for ch in x):
        raise NeedsError("plain")

    def host(name: str) -> str:
        text = v[name].lower()
        if not ba._HOST.fullmatch(text):
            raise NeedsError("host")
        return text

    def folder(name: str) -> str:
        got = host_folders.allowed(v[name])
        if not got:
            raise NeedsError("folder")
        return got

    def person(name: str) -> str:
        got = ba.person_name(v[name])
        if not got:
            raise NeedsError("person")
        return got

    if item == "site_name":
        if not v["site_name"] or v["site_name"] == ba.PLACEHOLDER_NAME:
            raise NeedsError("required")
        sid = site_id(v["site_name"])  # the id is the hospital's name's, never the stand-in's the install derived
        return Change({"TB_SITE_ID": sid}, {"site.name": v["site_name"], "site.id": sid}, {"site_name": v["site_name"]})
    if item == "office_mailbox":
        if not ba.MAILBOX.fullmatch(v["sae_office_mailbox"]):
            raise NeedsError("mail")
        return Change({"TB_SAE_OFFICE_MAILBOX": v["sae_office_mailbox"]}, {}, dict(v))
    if item == "mail_relay":
        port = v["smtp_port"] or "587"
        if not (port.isascii() and port.isdigit() and 1 <= int(port) <= 65535):
            raise NeedsError("port")
        got = {"smtp_host": host("smtp_host"), "smtp_port": port}
        return Change({"SMTP_HOST": got["smtp_host"], "SMTP_PORT": port}, {}, got)
    if item == "request_mailbox":
        auth = host("mta_authserv_id")
        return Change({"IMAP_HOST": host("imap_host"), "TB_MAIL_AUTHSERV_ID": auth}, {}, {"mta_authserv_id": auth})
    if item == "backup_alarm":
        who = person("health_page_person")
        return Change({"TB_BACKUP_ALERT_WATCHER": who}, {}, {"health_page_person": who})
    if item == "certificate":
        who, day = person("tls_root_confirmed_by"), date.today().isoformat()
        env = {"TB_TLS_ROOT_CONFIRMED_BY": who, "TB_TLS_ROOT_CONFIRMED_ON": day}
        return Change(env, {}, {"tls_root_confirmed_by": who, "tls_root_confirmed_on": day})
    if item == "audit_share":
        where = folder("anchor_dir")
        return Change({"TB_AUDIT_ANCHOR_TARGETS": where}, {}, {"anchor_dir": where})
    if item == "backup_target":
        where = folder("backup_dir")
        env = {"TB_BACKUP_TARGETS": where}
        if v["second_disk"]:
            env["TB_BACKUP_OFFBOX"] = where
        return Change(env, {}, {})  # the replay file keeps no disk or share of this machine
    if item == "chart_number":
        text = v["chartno_rule"] or rule_of(v["chartno_example"])
        rule = ba.chartno_rule({"chartno_rule": text}) if text else None
        if not rule:
            raise NeedsError("chartno")
        return Change(
            {"TB_CHARTNO_RULE": rule, "TB_CHARTNO_RULE_ANSWERED": "yes"},
            {"mrn_regex": chart_pattern(rule)},
            {"chartno_rule": rule},
        )
    kind, where = v["source_kind"], folder("source_dir")
    if kind not in SOURCE_KINDS:
        raise NeedsError("source")
    settings = {"data_source.type": kind, "data_source.path": BOX_SOURCE_MOUNT}
    if kind == ba.SourceKind.SSMIX2:  # the country whose shipped mapping reads it (the country layer)
        country = next(c for c in site_country.COUNTRIES if site_country.reads_ssmix2(c))
        settings["data_source.mapping"] = str(site_country.defaults(country).mapping)
        owner = {"source": kind, "country": country, "ssmix2_root": where}
    else:
        owner = {"source": "spreadsheet", "source_dir": where}
    return Change({"TB_SOURCE_DIR": where, "TB_SOURCE_MOUNT": BOX_SOURCE_MOUNT}, settings, owner)


# ------------------------------------------------------------------------------------------------ the host
def check_on_host(item: str, change: Change, deploy: Path, rows: Callable[[], int | None] | None = None) -> None:
    """What only the host can tell: the folder is there and is what it must be, and no patient is loaded under another
    chart-number rule."""
    from tools.box.__main__ import chartno_change, pid_map_rows
    from tools.box.plan import PlanError
    from tools.trialbox import finish_check as fc

    env = {**fc.read_env(deploy / ".env"), **change.env}
    production = fc.environment(env) == "PRODUCTION"
    why = ""
    try:
        if item == "audit_share":
            why = "; ".join(fc.anchor_problems(deploy, env, fc.Host.from_environ(), production))
        elif item == "backup_target":
            host = fc.Host.from_environ()
            base = fc._base(deploy, env, host)
            # OCR 1523-12: each target that cannot be used is said, whatever the last one is
            bad = (fc.folder_problem(t, host, base) or fc.off_the_box(t, host, deploy, env)
                   for t in fc.backup_targets(env))  # fmt: skip
            why = "; ".join(b for b in bad if b)
        elif item == "data_source" and not Path(change.env["TB_SOURCE_DIR"]).is_dir():
            why = f"{change.env['TB_SOURCE_DIR']} is not a folder on this machine"
        elif item == "chart_number":
            try:
                chartno_change(deploy / ".env", change.env["TB_CHARTNO_RULE"], rows or (lambda: pid_map_rows(deploy)))
            except PlanError as exc:
                why = str(exc)
    except PermissionError as exc:
        why = f"{exc.filename} cannot be read on this machine"
    if why:
        raise NeedsError("unusable", f"given, but not usable: {why}")


def patch_settings(deploy: Path, patch: Mapping[str, Any]) -> None:
    """The named paths of ``settings.yaml``, every other value as it was (comments after the first lines are not
    kept); checked as the services check it before it takes the file's place."""
    import yaml
    from tb_common.config import load_settings

    from tools.box.__main__ import write_whole

    path = deploy / "settings.yaml"
    if path.is_symlink():
        raise NeedsError("unusable", "settings.yaml is a link: not written")
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for dotted, value in patch.items():
        *parents, leaf = dotted.split(".")
        node = doc
        for p in parents:  # a key left empty in the file is none
            if not isinstance(node.setdefault(p, {}) or {}, dict):
                raise NeedsError("unusable", f"settings.yaml: {p} is not a list of settings: not written")
            node[p] = node[p] or {}
            node = node[p]
        node[leaf] = value
    head = "".join(ln for ln in path.read_text(encoding="utf-8").splitlines(True)[:3] if ln.startswith("#"))
    text = head + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)
    trial = path.with_name(".settings.trial.yaml")
    try:
        write_whole(trial, text)
        load_settings(trial)
    finally:
        trial.unlink(missing_ok=True)
    write_whole(path, text, path.stat().st_mode & 0o777)


def _patch(deploy: Path, patch: Mapping[str, Any]) -> None:
    try:
        import yaml  # noqa: F401
    except ModuleNotFoundError:  # the host's python3 may have no YAML: the image's does
        image = os.environ.get("TB_IMAGE") or "trialbox-py:1.0.0"
        subprocess.run(
            ["docker", "run", "--rm", "-i", "--user", "0", "--network", "none", "-v", f"{deploy}:/d", image,
             "python", "-m", "tools.box", "settings-patch", "--deploy", "/d"],
            input=json.dumps(patch), text=True, capture_output=True, timeout=120, check=True,
        )  # fmt: skip
        return
    patch_settings(deploy, patch)


def run(
    deploy: Path,
    args: Mapping[str, str],
    *,
    restart: bool,
    rows: Callable[[], int | None] | None = None,
    sh: Callable[..., Any] = subprocess.run,
) -> tuple[str, list[str]]:
    """One item's answer into the box, then the services on the new settings (``restart``). Returns the summary and the
    keys that changed: never a value."""
    from tools.box.__main__ import merge_env, write_whole

    item = str(args.get("item") or "")
    change = clean(item, args)
    check_on_host(item, change, deploy, rows)
    if change.settings:
        _patch(deploy, change.settings)
    changed = merge_env(deploy / ".env", change.env) if change.env else []
    owner = deploy / "site" / "box" / "owner.json"
    if change.owner and owner.is_file():
        kept = json.loads(owner.read_text(encoding="utf-8"))
        write_whole(owner, json.dumps({**kept, **change.owner}, ensure_ascii=False, indent=1) + "\n")
    site_needs.mark(deploy, item, stand_in=False)
    site_needs.write_host_given(deploy)
    if restart:
        if item == "audit_share":
            sh(["python3", "-m", "tools.trialbox", "finish-check", "--deploy", str(deploy), "--mount-anchors",
                "--anchor-only"], check=True, timeout=120)  # fmt: skip
        sh(["docker", "compose", "--project-directory", str(deploy), "up", "-d"], check=True, timeout=900)
    return f"filled in: {item}", [*changed, *sorted(change.settings)]


def doctor_checks(deploy: Path, env: Mapping[str, str], settings: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    """The rows of ``tools/trialbox/doctor_m1.py`` (F0's hook): one WARN per open item, naming the page; PASS when none
    is open. Never a FAIL: a missing item blocks only the step that needs it, at its gate."""
    stand, problems = site_needs.read_stand_ins(deploy)
    files = [f for f in ("secrets/backup.pub",) if (deploy / f).is_file()]
    rows = [("site_needs_list", "WARN", p) for p in problems]
    if ba.PLACEHOLDER_SITE_ID in (env.get("TB_SITE_ID"), (settings.get("site") or {}).get("id")):
        rows.append(("site_id", "WARN", "site name not set: the site id is the install's stand-in; go-live and the "
                     'first backup are refused until it is given on the page "Information still needed"'))  # fmt: skip
    for n, state in site_needs.still_needed(env=env, settings=settings, files=files, stand_ins=stand):
        steps = ", ".join(site_needs.STEPS[s]["en"] for s in n.before)
        rows.append((f"still_needed:{n.key}", "WARN",
                     f'{n.title["en"]} ({state}): needed before {steps}; page "Information still needed"'))  # fmt: skip
    return rows or [("still_needed", "PASS", "nothing is still needed")]
