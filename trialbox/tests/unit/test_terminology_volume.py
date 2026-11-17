"""TERM-VOL (D-991): the code systems loaded at install reach the services that read them.

TERM-1 (D-858) and TERM-2 (D-1113 to D-1116) load tables into ``TB_TERMINOLOGY_DIR`` (``/data/terminology``), but no
compose service mounted that folder, so a table loaded on a box was read by nothing (lane H, #936). Now:

* the named volume ``tb-terminology`` is mounted read-only at ``/data/terminology`` in every service that imports
  ``criteria_compiler.terminology.mapper``: criteria-compiler, orchestrator (``feas_compute``) and console
  (``backend``, ``coded_view``); no compose service writes it;
* ``deploy/terminology.sh`` is the one writer: ``python -m tools.terminology_install`` in the box's Python image with
  the volume read-write, the site's staging folder ``deploy/site/terminology`` read-only at ``/stage``, no network;
* the host check's doctor sees the volume read-only, so its ``terminology`` line reports what the services read;
* the installer makes the staging folder; a backup takes the volume (a restored box reads the tables it had);
* the box rehearsal loads a synthetic site list at install and finds it in criteria-compiler's container.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from tools.trialbox import backup as bk
from tools.trialbox import update as up

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
READERS = ("criteria-compiler", "orchestrator", "console")
MOUNT = "tb-terminology:/data/terminology:ro"


class _Compose(yaml.SafeLoader):
    """Compose's own tags (``!reset``, ``!override``) read as plain values."""


_Compose.add_multi_constructor("!", lambda loader, suffix, node: None)


def _load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = yaml.load(path.read_text(encoding="utf-8"), Loader=_Compose)
    return data or {}


def _compose(name: str = "docker-compose.yml") -> dict[str, Any]:
    return _load(DEPLOY / name)


def _mounts(svc: dict[str, Any]) -> list[str]:
    return [m if isinstance(m, str) else f"{m.get('source')}:{m.get('target')}" for m in svc.get("volumes") or []]


def test_every_reader_mounts_the_volume_read_only() -> None:
    c = _compose()
    assert "tb-terminology" in (c.get("volumes") or {})
    for svc in READERS:
        assert MOUNT in _mounts(c["services"][svc]), f"{svc} does not read the loaded tables"


#: the packages that read the loaded tables at run time (a ``Terminology(...)`` or the resolver), and the service that
#: runs each: sitesetup is the orchestrator's (``setup_api``). The others that import the mapper take constants only
#: (matching: SYSTEMS, YJ_STEM, FAMILY_EXT; omop: the shipped tables' folder).
RUNS_IN = {"criteria_compiler": "criteria-compiler", "orchestrator": "orchestrator", "sitesetup": "orchestrator",
           "console": "console"}  # fmt: skip
_READS = re.compile(r"\bTerminology\(|^\s*from criteria_compiler\.terminology import [^\n]*\bresolver\b", re.M)


def test_the_readers_are_the_services_that_read_the_tables() -> None:
    """A package that starts reading the loaded tables must name its service here, and that service gets the mount."""
    readers = set()
    for f in (ROOT / "services").rglob("*.py"):
        if "/tests/" not in f.as_posix() and _READS.search(f.read_text(encoding="utf-8", errors="replace")):
            readers.add(f.relative_to(ROOT / "services").parts[0])
    assert readers <= set(RUNS_IN), f"{sorted(readers - set(RUNS_IN))} read the loaded tables: name their service"
    assert {RUNS_IN[p] for p in readers} == set(READERS)


def test_no_compose_service_writes_it() -> None:
    for f in sorted(DEPLOY.glob("docker-compose*.yml")):
        for name, svc in (_load(f).get("services") or {}).items():
            for m in _mounts(svc or {}):
                if m.split(":")[0] == "tb-terminology" or ":/data/terminology" in m:
                    assert m.endswith(":ro"), f"{f.name}: {name} mounts the terminology volume writable: {m}"


def test_the_loader_is_the_one_writer() -> None:
    sh = (DEPLOY / "terminology.sh").read_text(encoding="utf-8")
    assert "python -m tools.terminology_install" in sh
    assert re.search(r"_tb-terminology:/data/terminology[\"' ]", sh), "the volume, read-write, only here"
    assert "/deploy/site/terminology:/stage:ro" in sh
    assert "--network none" in sh
    assert "TB_TERMINOLOGY_DIR=/data/terminology" in sh


def test_the_doctor_of_the_host_check_sees_it_read_only() -> None:
    sh = (DEPLOY / "check_host.sh").read_text(encoding="utf-8")
    assert re.search(r"TERM_MOUNT=\"\$\{?TERM_VOL\}?:/data/terminology:ro\"", sh)
    run = sh[sh.index("doctor_in_image() {") :]
    assert '${TERM_MOUNT:+-v "$TERM_MOUNT"}' in run.split("python -m tools.trialbox doctor")[0]


def test_the_installer_makes_the_staging_folder() -> None:
    sh = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    assert re.search(r"^mkdir -p [^\n]*deploy/site/terminology", sh, re.M)


def test_a_backup_takes_the_loaded_tables() -> None:
    assert bk.DEFAULT_DIRS["terminology"] == "tb-terminology"
    assert up.BACKUP_VOLUMES["terminology"] == "tb-terminology"


def test_the_rehearsal_finds_a_table_loaded_at_install_in_the_compiler() -> None:
    box = (ROOT / "tools" / "rehearse_box" / "box.sh").read_text(encoding="utf-8")
    m = re.search(r"\nterminology\)\n(.*?)\n  ;;\n", box, re.S)
    assert m, "box.sh has no terminology phase"
    step = m.group(1)
    assert "deploy/terminology.sh site-list /stage/" in step
    assert f"for svc in {' '.join(READERS)}; do" in step, "the step must look in every reader"
    assert 'dc exec -T "$svc" python -c "$read_it"' in step
    assert re.search(r"touch /data/terminology/[^\n]*\n\s*fail ", step), "a reader that can write must fail"
    steps = re.findall(r"^step ([a-z-]+) ", (ROOT / "tools/rehearse_box/rehearse.sh").read_text(encoding="utf-8"), re.M)
    assert "terminology" in steps and steps.index("terminology") > steps.index("install")


def test_the_platform_form_is_the_same() -> None:
    """D-991 (train 69): the platform form mounts the claim read-only in the same readers; only the restore job (as
    for every claim) mounts it writable; the backup takes it read-only under the appliance's name."""
    docs = [
        d for d in yaml.safe_load_all((DEPLOY / "platform" / "base" / "apps.yaml").read_text(encoding="utf-8")) if d
    ]
    docs += [
        d for d in yaml.safe_load_all((DEPLOY / "platform" / "base" / "day2.yaml").read_text(encoding="utf-8")) if d
    ]
    seen: dict[str, list[dict[str, Any]]] = {}
    for d in docs:
        spec = (d.get("spec") or {}).get("template") or ((d.get("spec") or {}).get("jobTemplate") or {}).get(
            "spec", {}
        ).get("template")
        if not spec:
            continue
        pod = spec["spec"]
        for c in pod.get("containers", []) + pod.get("initContainers", []):
            for m in c.get("volumeMounts") or []:
                if m["name"] == "tb-terminology":
                    seen.setdefault(d["metadata"]["name"], []).append(m)
    readers = {n for n, ms in seen.items() if all(m.get("readOnly") for m in ms)}
    writers = {n for n, ms in seen.items() if not all(m.get("readOnly") for m in ms)}
    assert set(READERS) <= readers and "trialbox-backup" in readers
    assert writers == {"trialbox-restore"}
    storage = list(yaml.safe_load_all((DEPLOY / "platform" / "base" / "storage.yaml").read_text(encoding="utf-8")))
    assert any(
        d and d["kind"] == "PersistentVolumeClaim" and d["metadata"]["name"] == "tb-terminology" for d in storage
    )
