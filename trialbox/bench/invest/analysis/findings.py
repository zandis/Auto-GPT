"""The battery's command line and the ``FINDINGS`` renderer (INVEST-1 §2, §3 step 1). Prints counts, never rows.

    # the battery over one set's runs (a repeat for the unstable table); --real, or any run not marked synthetic or
    # public: suppressed, refused, then written (residual clusters are made in memory, no records file)
    python -m bench.invest.analysis.findings battery --runs <dir>[,<dir>] [--repeat <dir>[,<dir>]] --name syn50k \\
        --out battery.json [--records residual.json] [--real]
    # the residual clusters (labels from ``cluster``) named and folded into the battery file
    python -m bench.invest.analysis.findings residual --battery battery.json --records residual.json \\
        --labels labels.json [--real --runs <dir>[,<dir>]]
    # FINDINGS-R<N>.md from the battery files, the metamorphic result and the real-data aggregate
    python -m bench.invest.analysis.findings render --battery a.json[,b.json] [--real twin.json] \\
        [--metamorphic m.json] --round R1 --out FINDINGS-R1.md
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path
from typing import Any

from bench.invest import export
from bench.invest.analysis import battery, cluster, taxonomy


def _dirs(arg: str | None) -> list[Path]:
    return [r for a in (arg or "").split(",") if a for r in battery.runs_under(Path(a))]


def residual_records(
    con: Any, b: Mapping[str, Any], meta: Mapping[tuple[str, str], Mapping[str, Any]], top: int = battery.TOP
) -> list[dict[str, Any]]:
    """The failure groups outside the ``top`` deterministic clusters, with their criterion's wording: the long tail
    the embedder clusters."""
    head = {tuple(c[k] for k in battery.GROUP_KEY) for c in b["clusters"][:top]}
    out = []
    for f in battery.failure_rows(con, meta):
        if f["side"] != "patient" or tuple(f[k] for k in battery.GROUP_KEY) in head:
            continue
        text = meta.get((f["protocol_id"], f["criterion_id"]), {}).get("text")
        if isinstance(text, dict):
            text = text.get("en") or text.get("original") or next(iter(text.values()), None)
        out.append({**f, "text": text})
    return out


def known_ids(meta: Mapping[tuple[str, str], Any], extra: Collection[str] = ()) -> set[str]:
    return {p for p, _ in meta} | {c for _, c in meta} | set(extra)


def _warn(msg: str) -> None:
    print(f"WARN: {msg}", file=sys.stderr)


def cmd_battery(a: argparse.Namespace) -> int:
    con = battery.open_runs(_dirs(a.runs))
    protos = [r[0] for r in con.execute("SELECT DISTINCT protocol_id FROM match_stage").fetchall()]
    meta = battery.criteria_meta(protos)
    rep = battery.open_runs(_dirs(a.repeat)) if a.repeat else None
    b = battery.run_battery(con, meta, rep, a.name)
    # protected unless every input run says it is synthetic or public: the flag can only add protection
    protected = bool(a.real) or not (battery.is_open(con) and (rep is None or battery.is_open(rep)))
    if protected and not a.real:
        _warn("a run is not marked synthetic or public: exporting the protected (suppressed, checked) form")
    recs = residual_records(con, b, meta) if a.records else []
    if a.records and not protected:
        Path(a.records).write_text(json.dumps(recs, ensure_ascii=False) + "\n", encoding="utf-8")
    elif recs:  # real: the records hold exact small counts, so they are clustered here and never written
        x, embedder = cluster.embed([cluster.record_text(r) for r in recs], a.embedder_path)
        labels, method = cluster.cluster(x)
        b["residual"] = cluster.residual_clusters(recs, labels)
        b["residual_method"] = {"clustering": method, "embedder": embedder, "namer": "rule"}
    b["protected"] = protected
    if protected:
        pids = export.pids_of(con) | (export.pids_of(rep) if rep is not None else set())
        out = battery.protect(b, pids, known_ids(meta, protos))
        battery.write_real(a.out, b, pids, known_ids(meta, protos))
    else:
        out = b
        Path(a.out).write_text(json.dumps(b, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"set": out["set"], "criterion_rows": out["criterion_rows"],
                      "failure_rows": out["failure_rows"], "trial_failure_rows": out["trial_failure_rows"],
                      "clusters": _cell(len(b["clusters"]), protected), "real": protected}))  # fmt: skip
    return 0


def _cell(n: int, protected: bool) -> int | None:
    return None if protected and n < export.MIN_CELL else n


def cmd_residual(a: argparse.Namespace) -> int:
    b = json.loads(Path(a.battery).read_text("utf-8"))
    con = battery.open_runs(_dirs(a.runs)) if a.runs else None
    # a battery keeps the protection it was written with; one with no marker is protected unless its ledgers are open
    marked = b["protected"] is not False if "protected" in b else not (con and battery.is_open(con))
    protected = bool(a.real) or marked
    if protected and con is None:
        _warn(
            "residual update skipped: it could expose patient identifiers without the source ledger (--runs) "
            "to check against; the battery file is unchanged"
        )
        print(json.dumps({"residual_clusters": None, "skipped": True}))
        return 0
    recs = json.loads(Path(a.records).read_text("utf-8"))
    lab = json.loads(Path(a.labels).read_text("utf-8"))
    b["residual"] = cluster.residual_clusters(recs, lab["labels"])
    b["residual_method"] = {"clustering": lab["method"], "embedder": lab["embedder"],
                            "namer": "rule"}  # fmt: skip
    n = len(b["residual"])
    if protected:  # the final payload is suppressed and checked against the source ledger's patient ids
        b["protected"] = True
        pids = export.pids_of(con)
        protos = sorted({r["protocol_id"] for r in recs} | {p for c in b["clusters"] for p in c["protocols"]})
        meta = battery.criteria_meta(protos)
        battery.write_real(Path(a.battery), b, pids, known_ids(meta, protos))
    else:
        Path(a.battery).write_text(json.dumps(b, indent=1, sort_keys=True, ensure_ascii=False) + "\n", "utf-8")
    print(json.dumps({"residual_clusters": _cell(n, protected), **b["residual_method"]}))
    return 0


# ---- rendering ------------------------------------------------------------------------------------------------------


def _n(v: Any) -> str:
    return "<10" if v is None else f"{v:,}" if isinstance(v, int) else str(v)


def _pct(v: Any) -> str:
    return "—" if v is None else f"{100 * v:.0f} %"


def _table(head: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[str]:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out


def _top_criteria(c: Mapping[str, Any], k: int = 3) -> str:
    return ", ".join(f"{cid} ({_n(n)})" for cid, n in list(c.get("criteria", {}).items())[:k]) or "—"


def clusters_table(b: Mapping[str, Any], top: int = battery.TOP) -> list[str]:
    rows = [
        [c["cluster_id"], f"{c['code']} {c['label']}", c["stage"], c["family"], c["reason_code"] or "—",
         c["unknown_kind"] or "—", _n(c["n"]), _pct(c["preventable_share"]), c["instrument"], _top_criteria(c)]
        for c in b["clusters"][:top]
    ]  # fmt: skip
    head = ["id", "code", "stage", "family", "reason", "unknown kind", "rows", "preventable", "instrument moved"]
    return _table([*head, "largest criteria"], rows)


def residual_table(b: Mapping[str, Any], top: int = 10) -> list[str]:
    if not b.get("residual"):
        return ["(no residual clustering in this file)"]
    m = b.get("residual_method", {})
    rows = [
        [c["cluster_id"], c["name"], _n(c["n"]), _n(c["size"]), _pct(c["preventable_share"]),
         ", ".join(c["codes"]), ", ".join(c["stages"]), _top_criteria(c, 2)]
        for c in b["residual"][:top]
    ]  # fmt: skip
    return [
        f"Method: {m.get('clustering')}, embedder `{m.get('embedder')}`, names by {m.get('namer')}.",
        "",
        *_table(["id", "name", "rows", "records", "preventable", "codes", "stages", "largest criteria"], rows),
    ]


def codes_table(b: Mapping[str, Any]) -> list[str]:
    rows = [
        [code, taxonomy.CODES[code], _n(v["n"]), _n(v["preventable_n"]), _n(v["undetermined_n"]),
         taxonomy.INSTRUMENT[code]]
        for code, v in b["by_code"].items()
    ]  # fmt: skip
    return _table(["code", "label", "rows", "preventable", "undetermined", "instrument"], rows)


def gap_table(b: Mapping[str, Any], top: int = 15) -> list[str]:
    rows = [[g["view"], g["field"], g["reason_code"], _n(g["n"]), _n(g["criteria"]), _n(g["protocols"])]
            for g in b["data_gap"][:top]]  # fmt: skip
    return _table(["view", "field (value set)", "reason", "unknown rows", "criteria", "protocols"], rows)


def unstable_table(b: Mapping[str, Any]) -> list[str]:
    rows = [r for r in b["unstable"] if r["changed"]]
    if not b["unstable"]:
        return ["(no repeat ledger joined)"]
    compared = sum(r["n"] or 0 for r in b["unstable"])
    head = [f"{_n(compared)} answers compared; {len(rows)} criteria changed at least one verdict; coded criteria "
            f"changed: {sum(1 for r in rows if r['coded_bug'])}.", ""]  # fmt: skip
    return head + _table(
        ["protocol", "criterion", "basis", "compared", "changed", "rate"],
        [[r["protocol_id"], r["criterion_id"], r["basis"], _n(r["n"]), _n(r["changed"]), r["rate"]] for r in rows],
    )


def accuracy_table(b: Mapping[str, Any]) -> list[str]:
    if not b["accuracy"]:
        return ["(no gold in this set)"]
    return _table(
        ["protocol", "gold rows", "correct", "wrong decided", "decided on unknown", "missed"],
        [[r["protocol_id"], _n(r["n"]), _n(r["correct"]), _n(r["wrong_decided"]), _n(r["decided_on_unknown"]),
          _n(r["missed"])] for r in b["accuracy"]],
    )  # fmt: skip


def cost_table(b: Mapping[str, Any]) -> list[str]:
    rows = [[r["protocol_id"], r["stage"], _n(r["n"]), _n(r["calls"]), _n(r["timed"]), r["p50_ms"] or "—",
             r["p99_ms"] or "—"] for r in b["cost"] if r["calls"] or r["timed"]]  # fmt: skip
    if not rows:
        return ["(no model calls and no timed stage in this set)"]
    return _table(["protocol", "stage", "rows", "model calls kept", "timed rows", "p50 ms", "p99 ms"], rows)


def _failing(criteria: Mapping[str, int], k: int = 6) -> str:
    return ", ".join(f"{c} ({n})" for c, n in list(criteria.items())[:k]) or "—"


def metamorphic_table(m: Mapping[str, Any]) -> list[str]:
    head = [f"{m['patients']:,} synthetic patients, {len(m['rulesets'])} rulesets, {m['base_answers']:,} base answers; "
            f"suite: **{'PASS' if m['pass'] else 'FAIL'}**.", ""]  # fmt: skip
    rows = [[t["transform"], f"{t['compared']:,}", f"{t['not_comparable']:,}", f"{t['broken']:,}",
             "pass" if t["pass"] else "FAIL", _failing(t["criteria"])] for t in m["transforms"]]  # fmt: skip
    return head + _table(["transform", "compared", "not comparable", "broken", "result", "failing criteria"], rows)


def _set_row(b: Mapping[str, Any]) -> list[str]:
    if "trial_failure_rows" not in b:  # written before the split: one combined total, no patient-side share
        return [b["set"], _n(b["criterion_rows"]), f"{_n(b['failure_rows'])} (patient and trial combined)", "—", "—"]
    share = _pct(b["failure_rows"] / b["criterion_rows"]) if b["criterion_rows"] and b["failure_rows"] else "—"
    return [b["set"], _n(b["criterion_rows"]), _n(b["failure_rows"]), _n(b["trial_failure_rows"]), share]


def _failure_cells(r: Mapping[str, Any]) -> str:
    if "trial_failure_rows" not in r:
        return f"{_n(r['failure_rows'])} failure rows (patient and trial combined)"
    return f"{_n(r['failure_rows'])} patient failure rows, {_n(r['trial_failure_rows'])} trial failure rows"


def real_section(r: Mapping[str, Any]) -> list[str]:
    """The real-data part: refused first (no identifier, quote or day date, no unsuppressed small count), then
    rendered from counts alone."""
    battery.refuse(r, (), _ids_in(r))
    out = [f"Set `{r['set']}`: {_n(r['criterion_rows'])} criterion rows, {_failure_cells(r)}. "
           "Counts only; cells below 10 shown as <10.", "", "Codes:", ""]  # fmt: skip
    out += [*codes_table(r), "", "Clusters (deterministic):", "", *clusters_table(r)]
    out += ["", "Residual clusters:", "", *residual_table(r), "", "Data-gap map:", "", *gap_table(r)]
    return out


def _ids_in(r: Mapping[str, Any]) -> set[str]:
    """Ruleset and criterion ids as the real file names them (it passed the full check on the machine that wrote it;
    off it, the renderer re-checks dates, quotes, small counts and the shape of every identifier)."""
    ids: set[str] = set()
    for c in r.get("clusters", []) + r.get("residual", []):
        ids |= set(c.get("protocols", {}))
        for k in c.get("criteria", {}):
            ids |= set(k.split("/"))
    return ids


def render(
    batteries: Sequence[Mapping[str, Any]],
    real: Mapping[str, Any] | None,
    metamorphic: Mapping[str, Any] | None,
    rnd: str,
    prior: str | None = None,
) -> str:
    out = [f"# FINDINGS-{rnd}: the analysis battery (INVEST-1 §2)", ""]
    out += ["Generated by `bench/invest/analysis/findings.py render`. Synthetic and public sets are read in full; the "
            "real-data section holds counts only.", ""]  # fmt: skip
    if prior:
        out += [f"The round's instrument table (§1.3) is in {prior}.", ""]
    sets = [_set_row(b) for b in [*batteries, *([real] if real else [])]]
    head = ["set", "criterion rows", "failure rows", "trial failure rows", "failure share"]
    out += ["## Sets", "", *_table(head, sets)]
    for b in batteries:
        out += ["", f"## Set `{b['set']}`", "", f"### Top {battery.TOP} clusters (deterministic)", ""]
        out += [*clusters_table(b), "", "### Residual clusters (embedded, named)", "", *residual_table(b)]
        out += ["", "### By code", "", *codes_table(b), "", "### Data-gap map", "", *gap_table(b)]
        out += ["", "### Unstable criteria (repeat join)", "", *unstable_table(b)]
        out += ["", "### Against gold", "", *accuracy_table(b)]
        rt = b["retrieval"]
        out += ["", "### Retrieval ranks", "", "no data: no ledger row carries a gold passage rank" if rt["status"] ==
                "no_data" else json.dumps(rt["rows"])]  # fmt: skip
        out += ["", "### Cost", "", *cost_table(b)]
    if metamorphic:
        out += ["", "## Metamorphic invariants (synthetic lake, coded stages)", "", *metamorphic_table(metamorphic)]
    if real:
        out += ["", "## Real data (counts only)", "", *real_section(real)]
    return "\n".join(out) + "\n"


def cmd_render(a: argparse.Namespace) -> int:
    bats = [json.loads(Path(p).read_text("utf-8")) for p in a.battery.split(",") if p]
    real = json.loads(Path(a.real).read_text("utf-8")) if a.real else None
    meta = json.loads(Path(a.metamorphic).read_text("utf-8")) if a.metamorphic else None
    Path(a.out).write_text(render(bats, real, meta, a.round, a.prior), encoding="utf-8")
    print(f"written {a.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("battery")
    p.add_argument("--runs", required=True)
    p.add_argument("--repeat")
    p.add_argument("--name", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--records", type=Path)
    p.add_argument("--embedder-path")
    p.add_argument("--real", action="store_true")
    p.set_defaults(fn=cmd_battery)
    p = sub.add_parser("residual")
    p.add_argument("--battery", type=Path, required=True)
    p.add_argument("--records", type=Path, required=True)
    p.add_argument("--labels", type=Path, required=True)
    p.add_argument("--runs")
    p.add_argument("--real", action="store_true")
    p.set_defaults(fn=cmd_residual)
    p = sub.add_parser("render")
    p.add_argument("--battery", required=True)
    p.add_argument("--real")
    p.add_argument("--metamorphic")
    p.add_argument("--round", default="R1")
    p.add_argument("--prior")
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(fn=cmd_render)
    a = ap.parse_args(argv)
    return int(a.fn(a))


if __name__ == "__main__":
    raise SystemExit(main())
