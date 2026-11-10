"""``adapter`` CLI (SPEC §4.6)::

    adapter run --source {cgrd_sql|csv|fhir_bulk|ssmix2} [--path DIR | --dsn DSN] [--since DATE] [--snapshot DATE]
                [--no-fhir] [--no-lake] [--no-validate]
    adapter validate [--snapshot DATE] [--per-type 50] [--file RESOURCES.json|.ndjson] [--lake DIR]   # JP Core (D-137)

Configuration comes from the environment/settings (``TB_LAKE_DIR``, ``TB_SECRETS_DIR``, ``FHIR_BASE_URL``, mapping
from ``settings.data_source.mapping``). Exit status 0 = report passed, 1 = failed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from tb_common.config import ConfigError, load
from tb_common.logging import setup_logging
from tb_contracts import RebuildResult, dump

from adapter.pipeline import AdapterConfig, run_ingest

MAPPING_ROOT = Path(__file__).resolve().parent


def _registry(reg: Any) -> tuple[str, str] | None:
    """settings.registry_source -> AdapterConfig.registry (unset: the data source's own registry table)."""
    if reg is None or reg.type is None:
        return None
    if reg.type == "none":
        return ("none", "")
    if reg.type == "csv":
        return ("csv", reg.path or "")
    return ("sql", os.environ.get(reg.dsn_env, "") if reg.dsn_env else (reg.path or ""))


def build_config() -> tuple[AdapterConfig, str, str]:
    cfg = load()
    ds = cfg.settings.data_source
    mapping = Path(ds.mapping or "mapping/tw_core/demo_his.yaml")
    if not mapping.is_absolute():
        mapping = MAPPING_ROOT / mapping
    lake_dir = Path(os.environ.get("TB_LAKE_DIR", Path(cfg.env.data_dir) / "lake"))

    def rebuild(snapshot: str, ndjson_dir: Path) -> RebuildResult:
        mode = os.environ.get("TB_ADAPTER_LAKE", "http")
        if mode == "local":
            from embed_service.embedder import from_env as embedder_from_env
            from lake.store import Lake

            st = Lake(lake_dir, cfg.env.tz).rebuild(
                snapshot, embedder_from_env(os.environ.get("TB_LAKE_EMBEDDER", "hash")), ndjson_dir
            )
            return RebuildResult(
                snapshot=st.snapshot,
                tables=st.tables,
                chunks=st.chunks,
                embedded_new=st.embedded_new,
                seconds=st.seconds,
            )
        import httpx
        from tb_common.service_auth import auth_headers

        resp = httpx.post(
            f"{cfg.env.lake_url.rstrip('/')}/rebuild", json={"snapshot": snapshot}, timeout=7200, headers=auth_headers()
        )
        if resp.status_code >= 400:  # D-271: the lake's reason reaches the ingest report, not only its log
            try:
                detail = str(resp.json().get("detail"))
            except ValueError:
                detail = resp.text[:500]
            if resp.status_code == 409:
                from adapter.pipeline import RebuildRefused

                raise RebuildRefused(f"the lake refused snapshot {snapshot}: {detail}")
            raise RuntimeError(f"lake service answered {resp.status_code}: {detail}")
        return RebuildResult.model_validate(resp.json())

    ret = cfg.settings.retention
    ac = AdapterConfig(
        lake_dir=lake_dir,
        secrets_dir=Path(cfg.env.secrets_dir),
        mapping_path=mapping,
        site_id=cfg.settings.site.id,
        tz=cfg.env.tz,
        fhir_base_url=cfg.env.fhir_base_url,
        audit_dir=cfg.env.audit_path,
        validation_max_pct=cfg.settings.thresholds.validation_error_max_pct,
        rebuild=rebuild,
        registry=_registry(cfg.settings.registry_source),
        keep_nightly=int(ret.nightly_snapshots if ret and ret.nightly_snapshots is not None else 3),
        keep_month_end_months=int(
            ret.month_end_snapshots_months if ret and ret.month_end_snapshots_months is not None else 36
        ),
    )
    default_path = ds.path or (os.environ.get(ds.dsn_env, "") if ds.dsn_env else "")
    return ac, ds.type, default_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="adapter", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--source", choices=["cgrd_sql", "csv", "fhir_bulk", "ssmix2"])
    run.add_argument("--path", help="directory (csv, fhir_bulk, ssmix2)")
    run.add_argument("--dsn", help="SQLAlchemy DSN (cgrd_sql)")
    run.add_argument("--since")
    run.add_argument("--snapshot")
    run.add_argument("--no-fhir", action="store_true")
    run.add_argument("--no-lake", action="store_true")
    run.add_argument("--no-validate", action="store_true")
    val = sub.add_parser("validate", help="JP Core $validate over a sample of a snapshot, or over a file (D-137)")
    val.add_argument("--snapshot", help="the snapshot (default: the newest)")
    val.add_argument("--per-type", type=int, default=50, help="resources of each type to check (default 50)")
    val.add_argument("--file", type=Path, help="a resource, a Bundle, a JSON list or NDJSON to check instead")
    val.add_argument("--lake", type=Path, help="the lake folder (default: TB_LAKE_DIR or the settings)")
    args = ap.parse_args(argv)
    setup_logging("adapter")
    if args.cmd == "validate":
        return validate_cmd(args)
    try:
        ac, default_kind, default_path = build_config()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    kind = args.source or default_kind
    path = args.dsn or args.path or default_path
    report = run_ingest(
        ac,
        kind,
        path,
        since=args.since,
        snapshot=args.snapshot,
        load_fhir=not args.no_fhir,
        rebuild_lake=not args.no_lake,
        validate=not args.no_validate,
    )
    print(json.dumps(dump(report), ensure_ascii=False, indent=1))
    return 0 if report.passed else 1


def read_resources(data: bytes) -> list[dict[str, Any]]:
    """One resource, a Bundle, a JSON list, or NDJSON."""
    text = data.decode("utf-8-sig").strip()
    if not text:
        return []
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(doc, list):
        return [r for r in doc if isinstance(r, dict)]
    if isinstance(doc, dict) and doc.get("resourceType") == "Bundle":
        return [e["resource"] for e in doc.get("entry") or [] if isinstance(e, dict) and e.get("resource")]
    return [doc] if isinstance(doc, dict) else []


def validate_cmd(args: argparse.Namespace) -> int:
    """``adapter validate``: prints the result; exit 0 when no sampled resource fails, 1 otherwise."""
    from adapter import licensed
    from adapter.ndjson import list_snapshots, snapshot_dir
    from adapter.validate.jpcore import JpCoreValidator, sample_per_type, validate_snapshot

    terms = licensed.tables()
    if args.file:
        rep = JpCoreValidator(terms).validate(sample_per_type(read_resources(args.file.read_bytes()), args.per_type))
    else:
        lake = args.lake or Path(os.environ.get("TB_LAKE_DIR") or "")
        if not str(lake):
            lake = build_config()[0].lake_dir
        snap = args.snapshot or (list_snapshots(lake) or [""])[-1]
        if not snap:
            print(f"no snapshot in {lake}", file=sys.stderr)
            return 2
        rep = validate_snapshot(snapshot_dir(lake, snap), args.per_type, terms)
    out = rep.as_json()
    out.pop("failures", None)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if rep.errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
