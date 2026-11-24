"""``python3 -m tools.trialbox decommission-plan``: the close-out and decommissioning checklist of one box (T-628,
D-413, RUNBOOK §20). It reads ``deploy/.env`` (the process environment wins) and ``deploy/docker-compose.yml`` and
prints, in order, the steps of §20 and every store that holds study data, on and off the box, with what happens to
it: **keep** (a record the hospital keeps for its retention time) or **purge** (NIST SP 800-88 Rev. 1 clear, purge
or destroy, then a line on the certificate ``docs/plan/sites/purge-certificate.md``).

It is a dry run: it reads settings and folder names only, opens no file, deletes nothing and needs no key. Standard
library only, so it runs with the host's ``python3`` from the install folder."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# The steps of RUNBOOK §20, in order. The id is the anchor word the page uses ("Step <n>, <id>"); a test holds
# the page and the certificate to this list.
STEPS: tuple[tuple[str, str], ...] = (
    ("announce", "Announce the close date; stop new screening; expire study accounts at the close date"),
    ("freeze", "Final freeze of the logs: last audit event, verify the chain, sign the head off the box"),
    ("archive", "Archive: final backup, audit archive, export ledger and records into one folder with SHA-256 sums"),
    ("verify", "Verify the archive on the hospital's store: sums, backup-verify, audit_verify --no-head"),
    ("handover", "Hand the archive to the trial office; it keeps it for the retention time"),
    ("crypto-erase", "Crypto-erase: destroy the KEK, the site keys and the backup private key"),
    ("purge", "Purge every store marked purge (NIST SP 800-88 Rev. 1: clear, purge or destroy per medium)"),
    ("certificate", "Fill one purge certificate per medium; the hospital keeps it with the archive record"),
)

KEEP, PURGE, ASK = "keep", "purge", "ask"


@dataclass(frozen=True)
class Store:
    """One place that holds study data or a key to it."""

    name: str
    where: str
    on_box: bool
    action: str  # keep, purge or ask (a store no setting names: ask hospital IT)
    note: str


def _split(v: str) -> list[str]:
    return [t for t in v.replace(",", " ").split() if t]


def _unquote(v: str) -> str:
    v = v.strip()
    return v[1:-1] if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'" else v


def read_env(deploy: Path, process_env: bool = True) -> dict[str, str]:
    """``deploy/.env`` with quotes removed; the process environment's ``TB_*`` wins (as the backup schedule)."""
    out: dict[str, str] = {}
    f = deploy / ".env"
    if f.is_file():
        for line in f.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, _, v = line.partition("=")
                out[k.strip()] = _unquote(v)
    if process_env:
        out.update({k: v for k, v in os.environ.items() if k.startswith("TB_")})
    return out


def compose_volumes(compose: Path) -> list[str]:
    """The top-level ``volumes:`` names of the compose file (no YAML library: the block's two-space keys)."""
    if not compose.is_file():
        return []
    names: list[str] = []
    inside = False
    for line in compose.read_text(encoding="utf-8").splitlines():
        if re.match(r"^volumes:\s*(#.*)?$", line):
            inside = True
            continue
        if inside:
            if line and not line[0].isspace() and not line.startswith("#"):
                break
            m = re.match(r"^  ([A-Za-z0-9_.-]+):", line)
            if m:
                names.append(m.group(1))
    return names


def stores(deploy: Path, env: Mapping[str, str]) -> list[Store]:
    """Every store, on the box first, from the settings; then the ones no setting names (action ``ask``)."""
    root = Path(env.get("TB_DOCKER_VOLUMES") or "/var/lib/docker/volumes")
    project = env.get("COMPOSE_PROJECT_NAME") or "trialbox"  # H-106 (OCR 1452-1): a test box's own volumes
    out: list[Store] = []
    for vol in compose_volumes(deploy / "docker-compose.yml"):
        note = {"tb-secrets": "keys: after the crypto-erase", "audit-data": "after the freeze and the archive"}.get(
            vol, "study data: after the archive"
        )
        out.append(Store(f"volume {vol}", str(root / f"{project}_{vol}" / "_data"), True, PURGE, note))
    for pair in _split(env.get("TB_BACKUP_DIRS", "")):
        name, _, path = pair.partition("=")
        out.append(Store(f"backup folder {name}", path or name, True, PURGE, "TB_BACKUP_DIRS"))
    out.append(Store("secrets folder", str(deploy / "secrets"), True, PURGE, "KEK file or shares' copies, keys"))
    out.append(Store("settings file", str(deploy / ".env"), True, PURGE, "passwords of the box's accounts"))
    out.append(Store("service logs", env.get("TB_LOG_DIR") or str(deploy / "logs"), True, PURGE, "TB_LOG_DIR"))
    for key, label in (("TB_MODELS_DIR", "model weights"), ("TB_EMBED_MODEL_PATH", "embedder weights")):
        if env.get(key):
            out.append(Store(label, env[key], True, PURGE, f"{key}; public weights, no patient data"))
    out.append(Store("host disks", "every disk of the box (system and data)", True, PURGE, "last, after the rest"))
    for t in _split(env.get("TB_BACKUP_TARGETS", "")):
        out.append(Store("backup target", t, False, PURGE, "TB_BACKUP_TARGETS; the final backup is archived first"))
    for t in _split(env.get("TB_BACKUP_OFFBOX", "")):
        out.append(Store("declared off-box target", t, False, PURGE, "TB_BACKUP_OFFBOX"))
    if env.get("TB_PGBACKREST_REPO"):
        out.append(Store("pgBackRest repository", env["TB_PGBACKREST_REPO"], False, PURGE, "TB_PGBACKREST_REPO"))
    archive = env.get("TB_AUDIT_ARCHIVE_DIR") or str(Path(env.get("TB_LOG_DIR") or deploy / "logs") / "audit-archive")
    keep = "copied into the archive at step 3, then kept for the audit retention"
    out.append(Store("audit archive", archive, not env.get("TB_AUDIT_ARCHIVE_DIR"), KEEP, keep))
    for t in _split(env.get("TB_AUDIT_ANCHOR_TARGETS", "")):
        out.append(Store("audit anchor folder", t, False, KEEP, "signed heads; kept with the audit archive"))
    for name, note in (
        ("USB disks", "any disk a backup, a transfer or an update bundle was carried on"),
        ("backup private key", "held by hospital IT; destroyed at crypto-erase"),
        ("KEK shares or passphrase", "held by the key stewards; destroyed at crypto-erase"),
        ("hospital platform volumes", "shared host only: the platform team purges the TrialBox volumes"),
        ("printed lists and exports", "paper and files that left the box (the export ledger lists the files)"),
    ):
        out.append(Store(name, "not in the settings: ask hospital IT", False, ASK, note))
    return out


def plan(deploy: Path, env: Mapping[str, str]) -> dict[str, Any]:
    return {
        "site": env.get("TB_SITE_ID", ""),
        "dry_run": True,
        "steps": [{"n": i, "id": sid, "what": what} for i, (sid, what) in enumerate(STEPS, 1)],
        "stores": [asdict(s) for s in stores(deploy, env)],
    }


def render(p: Mapping[str, Any]) -> str:
    lines = [f"Decommissioning plan (dry run, RUNBOOK §20) for site {p['site'] or '(TB_SITE_ID not set)'}", ""]
    lines += [f"Step {s['n']}, {s['id']}: {s['what']}" for s in p["steps"]]
    lines += ["", "Stores (action, on or off the box, name, where, note):"]
    for s in p["stores"]:
        side = "on box " if s["on_box"] else "off box"
        lines.append(f"  {s['action']:<5} {side}  {s['name']}: {s['where']} ({s['note']})")
    lines += ["", "Nothing was changed. Each purge row needs a line on the purge certificate."]
    return "\n".join(lines)


def main(deploy: Path, as_json: bool = False) -> int:
    p = plan(deploy, read_env(deploy))
    print(json.dumps(p, indent=1, ensure_ascii=False) if as_json else render(p))
    return 0
