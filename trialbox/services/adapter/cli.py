"""``adapter`` CLI (SPEC §4.6)::

    adapter run --source {cgrd_sql|csv|fhir_bulk|ssmix2} [--path DIR | --dsn DSN] [--since DATE] [--snapshot DATE]
                [--no-fhir] [--no-lake] [--no-validate]

Configuration comes from the environment/settings (``TB_LAKE_DIR``, ``TB_SECRETS_DIR``, ``FHIR_BASE_URL``, mapping
from ``settings.data_source.mapping``). Exit status 0 = report passed, 1 = failed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from tb_common.config import ConfigError, load
from tb_common.logging import setup_logging
from tb_contracts import RebuildResult, dump

from adapter.pipeline import AdapterConfig, run_ingest

MAPPING_ROOT = Path(__file__).resolve().parent


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

        resp = httpx.post(f"{cfg.env.lake_url.rstrip('/')}/rebuild", json={"snapshot": snapshot}, timeout=7200)
        resp.raise_for_status()
        return RebuildResult.model_validate(resp.json())

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
    args = ap.parse_args(argv)
    setup_logging("adapter")
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


if __name__ == "__main__":
    raise SystemExit(main())
