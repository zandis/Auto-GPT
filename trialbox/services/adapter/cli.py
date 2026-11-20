"""``adapter`` CLI (SPEC §4.6)::

    adapter run --source {cgrd_sql|csv|fhir_bulk|ssmix2} [--path DIR | --dsn DSN] [--since DATE] [--snapshot DATE]
                [--no-fhir] [--no-lake] [--no-validate]
    adapter validate [--snapshot DATE] [--per-type 50] [--file RESOURCES.json|.ndjson] [--lake DIR]   # JP Core (D-137)
    adapter backfill [--source KIND] [--path DIR | --dsn DSN] [--snapshot DATE] [--first-years N]
                     [--work DIR] [--no-lake] [--no-validate]   # all history, by year, newest first (T-305b)
    adapter keys-init [--secrets DIR]          # the install ceremony's key step (T-612)
    adapter pid-merge --from CHART --into CHART --reason TEXT --ticket ID   # a chart-number merge (T-659b)

Configuration comes from the environment/settings (``TB_LAKE_DIR``, ``TB_SECRETS_DIR``, ``FHIR_BASE_URL``, mapping
from ``settings.data_source.mapping``). A relative mapping is looked up in the site's mapping folder first
(``deploy/site/mapping``, mounted at ``/etc/trialbox/mapping``; ``TB_MAPPING_DIR``), then in the image
(``adapter.mapping.site``, T-632). Exit status 0 = report passed, 1 = failed, 2 = refused before the night
started (configuration, or the site key missing or changed: T-612).

``keys-init`` makes ``site_hmac.key`` and ``pid_map.key`` in the secrets folder (``TB_SECRETS_DIR``) when absent and
never replaces one; it prints each key's fingerprint, never a key. It is the only place a site key is made: the
ingest refuses a night without one (T-612, DATA-004).

``TB_DATA_CONTRACTS`` turns on the data contracts (T-659b, D-370): a built-in set's name (``demo_his``) or a folder of
contract files. ``pid-merge`` records a chart-number merge in the append-only ``pid_alias`` table; no pid is re-keyed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from tb_common.config import ConfigError, load
from tb_common.id_rule import IdRuleError
from tb_common.logging import setup_logging
from tb_contracts import RebuildResult, dump

from adapter import site_profile
from adapter.governance import contracts_dir
from adapter.mapping.site import resolve as resolve_mapping
from adapter.pipeline import AdapterConfig, FutureNight, LakeBudgetError, NoRoomForNight, SiteKeyError, run_ingest

MAPPING_ROOT = Path(__file__).resolve().parent  # the image's mappings (adapter.mapping.site: the site's come first)


def _standards(profiles: Any) -> dict[str, str]:
    """settings.profiles as names and versions (10B-6, D-1233)."""
    return {k: str(v) for k, v in (profiles.model_dump() if profiles is not None else {}).items() if v is not None}


def _registry(reg: Any) -> tuple[str, str] | None:
    """settings.registry_source -> AdapterConfig.registry (unset: the data source's own registry table)."""
    if reg is None or reg.type is None:
        return None
    if reg.type == "none":
        return ("none", "")
    if reg.type == "csv":
        return ("csv", reg.path or "")
    return ("sql", os.environ.get(reg.dsn_env, "") if reg.dsn_env else (reg.path or ""))


class HttpLakeStep:
    """The adapter's lake step over HTTP: the start (``POST /rebuild``) and the state reads (``GET /rebuild/<s>``)
    through ``httpx``'s module calls with the box's service token, each a short request (T-690, D-472)."""

    def __init__(self, lake_url: str, poll: Any = None) -> None:
        self.base, self.poll = lake_url.rstrip("/"), poll

    def _ask(self, method: str, path: str, **kw: Any) -> Any:
        import httpx
        from tb_common.service_auth import auth_headers

        resp = getattr(httpx, method)(f"{self.base}{path}", timeout=60, headers=auth_headers(), **kw)
        resp.raise_for_status()
        return resp

    def _call(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        """The lake's answer, a JSON object, or ``lake.client.LakeBadAnswer`` (D-673): never another body."""
        from lake.client import _object

        return _object(self._ask(method, path, **kw))

    def rebuild(self, snapshot: str, promote: bool = True) -> dict[str, Any]:
        from lake.client import follow_rebuild

        body: dict[str, Any] = {"snapshot": snapshot} if promote else {"snapshot": snapshot, "promote": False}
        return follow_rebuild(
            lambda: self._call("post", "/rebuild", json=body),
            lambda: self._call("get", f"/rebuild/{snapshot}"),
            snapshot,
            self.poll,
        )

    def promote(self, snapshot: str, generation: str | None = None) -> bool:
        """T-723 (D-489): the publish's last step: the built night becomes the served one (False: a newer one is).
        ``generation`` (D-531): the one this publish built; the lake refuses (409) when the date is another now."""
        body = {"snapshot": snapshot, **({"generation": generation} if generation else {})}
        from lake.client import _key

        # D-673: a 200 without ``promoted`` is an error of the lake, not "a newer night is served"
        return bool(_key(self._ask("post", "/promote", json=body), "promoted", (bool,)))


def http_rebuild(lake: Any, snapshot: str, promote: bool = True) -> RebuildResult:
    """The night's lake step over HTTP (T-690, D-472): the rebuild is started as a job on the lake service and followed
    to its end, never timed (OD-10; before, 7,200 s: a longer rebuild failed the night while the lake finished it and
    moved CURRENT). Busy stays busy (``LakeBusy``: the night is run again, D-462); a refusal of the data is
    ``RebuildRefused`` (a held night, D-271); anything else, or a lake that stopped answering, fails the step."""
    from lake.store import LakeBusy, RebuildError

    from adapter.pipeline import RebuildRefused

    try:
        out = lake.rebuild(snapshot) if promote else lake.rebuild(snapshot, promote=False)
    except LakeBusy:
        raise
    except RebuildError as exc:
        raise RebuildRefused(f"the lake refused snapshot {snapshot}: {exc}") from None
    return RebuildResult(
        snapshot=out.get("snapshot") or snapshot,
        tables=out.get("tables") or {},
        chunks=int(out.get("chunks") or 0),
        embedded_new=int(out.get("embedded_new") or 0),
        seconds=float(out.get("seconds") or 0),
        generation=out.get("generation") or None,
    )


def build_config() -> tuple[AdapterConfig, str, str]:
    cfg = load()
    ds = cfg.settings.data_source
    mapping = resolve_mapping(ds.mapping)  # T-632: the site's folder first, then the image
    if not mapping.is_file():
        raise ConfigError(
            f"mapping file {ds.mapping or mapping} not found in the site mapping folder (deploy/site/mapping) "
            "or the image"
        )
    lake_dir = Path(os.environ.get("TB_LAKE_DIR", Path(cfg.env.data_dir) / "lake"))

    def rebuild(snapshot: str, ndjson_dir: Path, promote: bool = True) -> RebuildResult:
        mode = os.environ.get("TB_ADAPTER_LAKE", "http")
        if mode == "local":
            from embed_service.embedder import from_env as embedder_from_env
            from lake.store import Lake

            from adapter import failure

            # the adapter's own settings are read outside the wrap: a wrong one is said in its own words
            embedder = embedder_from_env(os.environ.get("TB_LAKE_EMBEDDER", "hash"))
            lake = Lake(lake_dir, cfg.env.tz, cfg.settings.mrn_regex)
            st = failure.local_lake(  # D-669: an engine error leaves as the lake's safe answer, as over HTTP
                lambda: lake.rebuild(snapshot, embedder, ndjson_dir, promote=promote, check=not promote)
            )
            return RebuildResult(
                snapshot=st.snapshot,
                tables=st.tables,
                chunks=st.chunks,
                embedded_new=st.embedded_new,
                seconds=st.seconds,
                generation=st.generation or None,
            )
        return http_rebuild(HttpLakeStep(cfg.env.lake_url), snapshot, promote)

    def build(snapshot: str, ndjson_dir: Path) -> RebuildResult:
        """T-723 (D-489): the publish's first step: the night is built and judged, not served yet."""
        return rebuild(snapshot, ndjson_dir, promote=False)

    def promote(snapshot: str, generation: str | None = None) -> bool:
        if os.environ.get("TB_ADAPTER_LAKE", "http") == "local":
            from lake.store import Lake

            from adapter import failure

            lake = Lake(lake_dir, cfg.env.tz, cfg.settings.mrn_regex)
            return failure.local_lake(lambda: lake.promote_built(snapshot, generation))  # D-669
        return HttpLakeStep(cfg.env.lake_url).promote(snapshot, generation)

    ret = cfg.settings.retention
    fc = cfg.settings.feed_completeness  # T-611
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
        build=build,
        promote=promote,
        registry=_registry(cfg.settings.registry_source),
        keep_nightly=int(ret.nightly_snapshots if ret and ret.nightly_snapshots is not None else 3),
        keep_month_end_months=int(
            ret.month_end_snapshots_months if ret and ret.month_end_snapshots_months is not None else 36
        ),
        table_max_drop_pct=float(fc.max_table_drop_pct) if fc else 10.0,
        required_tables=tuple(fc.required_tables) if fc else (),
        optional_tables=tuple(fc.optional_tables) if fc else (),
        first_night_all_tables=True,  # NEW-DIN-8 (D-583): no setting turns it off; optional_tables is the knob
        source_encoding=ds.encoding,  # T-615b
        mrn_regex=cfg.settings.mrn_regex,  # T-629 (FIT-U09)
        contracts_dir=contracts_dir(os.environ.get("TB_DATA_CONTRACTS")),  # T-659b
        site_profile=site_profile.find(),  # 10B-6 (D-1233): the site mapping folder's profile/, else none
        profile_standards=_standards(cfg.settings.profiles),  # 10B-6: a profile's versions agree with these
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
    bf = sub.add_parser("backfill", help="load all history by year, newest first, resumable (T-305b, D-403)")
    bf.add_argument("--source", choices=["cgrd_sql", "csv", "fhir_bulk", "ssmix2"])
    bf.add_argument("--path", help="directory (csv, fhir_bulk, ssmix2)")
    bf.add_argument("--dsn", help="SQLAlchemy DSN (cgrd_sql)")
    bf.add_argument("--snapshot")
    bf.add_argument(
        "--first-years", type=int, default=5, help="publish once after the newest N years (0: only at the end)"
    )
    bf.add_argument("--work", type=Path, help="the work folder (default: <lake>/backfill/<snapshot>)")
    bf.add_argument("--no-lake", action="store_true")
    bf.add_argument("--no-validate", action="store_true")
    val = sub.add_parser("validate", help="JP Core $validate over a sample of a snapshot, or over a file (D-137)")
    val.add_argument("--snapshot", help="the snapshot (default: the newest)")
    val.add_argument("--per-type", type=int, default=50, help="resources of each type to check (default 50)")
    val.add_argument("--file", type=Path, help="a resource, a Bundle, a JSON list or NDJSON to check instead")
    val.add_argument("--lake", type=Path, help="the lake folder (default: TB_LAKE_DIR or the settings)")
    keys = sub.add_parser("keys-init", help="make the site keys when absent (the install ceremony, T-612)")
    keys.add_argument("--secrets", type=Path, help="the secrets folder (default: TB_SECRETS_DIR or the settings)")
    merge = sub.add_parser("pid-merge", help="record a chart-number merge in the alias table (T-659b)")
    merge.add_argument("--from", dest="old", required=True, help="the chart number merged away")
    merge.add_argument("--into", dest="new", required=True, help="the surviving chart number")
    merge.add_argument("--reason", required=True)
    merge.add_argument("--ticket", required=True)
    args = ap.parse_args(argv)
    setup_logging("adapter")
    if args.cmd == "validate":
        return validate_cmd(args)
    if args.cmd == "keys-init":
        return keys_init(args.secrets)
    try:
        ac, default_kind, default_path = build_config()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    if args.cmd == "pid-merge":
        return pid_merge(ac, args.old, args.new, args.reason, args.ticket)
    kind = args.source or default_kind
    path = args.dsn or args.path or default_path
    from adapter.runs import RunLock, RunLockHeld

    try:  # D-1253 deep review: a night or a back-fill from the command line holds the run lock as the service's does,
        lock = RunLock(ac.lake_dir)  # so the one id-rule rebuild (and a second run) keeps it out
    except RunLockHeld as exc:
        print(f"refused, nothing was read or written: {exc}", file=sys.stderr)
        return 2
    try:
        if args.cmd == "backfill":
            return backfill_cmd(ac, kind, path, args)
        return _run_cmd(ac, kind, path, args)
    finally:
        lock.release()


def _run_cmd(ac: AdapterConfig, kind: str, path: str, args: argparse.Namespace) -> int:
    """``adapter run``: one night (the caller holds the run lock)."""
    try:
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
    except (SiteKeyError, FutureNight, NoRoomForNight, LakeBudgetError, IdRuleError) as exc:
        print(f"night refused, nothing was read or written: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(dump(report), ensure_ascii=False, indent=1))
    return 0 if report.passed else 1


def backfill_cmd(ac: AdapterConfig, kind: str, path: str, args: argparse.Namespace) -> int:
    """``adapter backfill``: the whole history as one snapshot; run it again to resume (T-305b, D-403)."""
    from adapter.backfill import backfill

    try:
        rep = backfill(
            ac,
            kind,
            path,
            snapshot=args.snapshot,
            work_dir=args.work,
            first_years=args.first_years,
            validate=not args.no_validate,
            rebuild_lake=not args.no_lake,
        )
    except (SiteKeyError, FutureNight, IdRuleError) as exc:
        print(f"back-fill refused, nothing was read or written: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(rep.as_dict(), ensure_ascii=False, indent=1))
    return 0 if rep.state == "published" else 1


def pid_merge(ac: AdapterConfig, old: str, new: str, reason: str, ticket: str) -> int:
    """T-659b (D-370): chart number ``old`` was merged into ``new``; prints the two pids, never a chart number."""
    from adapter.pidmap import AliasError

    pm = ac.pidmap()
    try:
        a, b = pm.merge(ac.site_key(), old, new, reason, ticket)
    except AliasError as exc:
        print(f"merge refused: {exc}", file=sys.stderr)
        return 1
    finally:
        pm.close()
    print(json.dumps({"old_pid": a, "pid": b}))
    return 0


def keys_init(secrets: Path | None = None) -> int:
    """T-612: the install ceremony's key step. Makes each missing key, keeps each present one, prints fingerprints."""
    from tb_common.crypto import SITE_KEY_FILE, KeyMissingError, create_key, key_fingerprint, load_key

    if secrets is None:
        raw = os.environ.get("TB_SECRETS_DIR")
        if not raw:
            try:
                raw = load().env.secrets_dir
            except ConfigError as exc:
                print(f"configuration error: {exc}", file=sys.stderr)
                return 2
        secrets = Path(raw)
    for name in (SITE_KEY_FILE, "pid_map.key"):
        path = secrets / name
        made = create_key(path)
        try:
            fp = key_fingerprint(load_key(path))
        except KeyMissingError as exc:  # an empty file is never overwritten: it may be a restore gone wrong
            print(f"{name}: {exc}; put the site's key back from the backup", file=sys.stderr)
            return 1
        print(f"{name}: {'made' if made else 'kept'} (fingerprint {fp})")
    return 0


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
