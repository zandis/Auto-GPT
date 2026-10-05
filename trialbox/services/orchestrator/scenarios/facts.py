"""Patient facts for NHI application drafts and TWPAS bundles (SPEC §9.4, §9.5), read from the lake with the ruleset's
own ValueSets so that the draft shows exactly the data the criteria were evaluated on."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from lake.client import LakeAPI
from tb_common import derived
from tb_common.ruleset import Ruleset

MISSING = "[待補]"
STEROID_ATC_PREFIX = "H02AB"


@dataclass
class Facts:
    pid: str
    values: dict[str, Any] = field(default_factory=dict)
    dmards: list[dict[str, str]] = field(default_factory=list)
    das28: list[dict[str, str]] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def get(self, key: str) -> Any:
        return self.values.get(key)


def _codes(rs: Ruleset, vs_name: str) -> list[str]:
    vs = rs.valuesets.get(vs_name)
    if not vs:
        return []
    return [c["code"] for inc in vs["compose"]["include"] for c in inc.get("concept", [])]


def _vs_names(rs: Ruleset, kind: str, domain: str) -> list[str]:
    from criteria_compiler.semantics import atoms

    out: list[str] = []
    for c in rs.active():
        if c.kind != kind:
            continue
        for a in atoms(c.logic):
            if a.domain == domain and a.valueset not in out and a.valueset != "NONE" and not a.derived:
                out.append(a.valueset)
    return out


def _fmt(v: Any) -> str:
    if v is None:
        return MISSING
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".")
    return str(v)


def collect(lake: LakeAPI, rs: Ruleset, pid: str, run_date: date) -> Facts:
    f = Facts(pid)
    rd = run_date.isoformat()
    pat = lake.query("SELECT birth_date, sex FROM patient WHERE pid = $1", [pid]).to_pylist()
    if pat:
        bd = pat[0]["birth_date"]
        f.values["birth_date"] = bd.isoformat() if bd else None
        f.values["sex"] = {"male": "男", "female": "女"}.get(str(pat[0]["sex"]), pat[0]["sex"])
        if bd:
            f.values["age"] = run_date.year - bd.year - ((run_date.month, run_date.day) < (bd.month, bd.day))
    # diagnosis: earliest coded condition of the first inclusion ValueSet
    dx_vs = _vs_names(rs, "inclusion", "condition")
    if dx_vs:
        rows = lake.query(
            "SELECT code, min(coalesce(onset, recorded)) AS first FROM condition WHERE pid = $1 "
            "AND list_contains(CAST($2 AS VARCHAR[]), code) AND coalesce(onset, recorded) <= CAST($3 AS DATE) "
            "GROUP BY code ORDER BY first, code",
            [pid, _codes(rs, dx_vs[0]), rd],
        ).to_pylist()
        if rows:
            f.values["diagnosis_code"] = rows[0]["code"]
            f.values["diagnosis_date"] = rows[0]["first"].isoformat()
            f.values["diagnosis"] = (rs.valuesets[dx_vs[0]].get("title") or dx_vs[0]).replace("VS_", "")
    # DMARDs (inclusion medication ValueSets) and corticosteroids
    med_codes = [c for vs in _vs_names(rs, "inclusion", "medication") for c in _codes(rs, vs)]
    rows = lake.query(
        'SELECT name, atc, dose, start, "end" FROM medication WHERE pid = $1 AND start <= CAST($3 AS DATE) '
        "AND (list_contains(CAST($2 AS VARCHAR[]), atc) OR starts_with(atc, $4)) ORDER BY start, mid",
        [pid, med_codes, rd, STEROID_ATC_PREFIX],
    ).to_pylist()
    steroid: list[str] = []
    for r in rows:
        end = r["end"] or run_date
        days = (min(end, run_date) - r["start"]).days + 1
        item = {
            "name": r["name"] or r["atc"],
            "dose": r["dose"] or MISSING,
            "start": r["start"].isoformat(),
            "end": r["end"].isoformat() if r["end"] else MISSING,
            "days": str(days),
        }
        if str(r["atc"]).startswith(STEROID_ATC_PREFIX):
            steroid.append(f"{item['name']} {item['dose']}（{item['start']}–{item['end']}）")
        else:
            f.dmards.append(item)
    f.values["prednisolone"] = "；".join(steroid) if steroid else "無使用紀錄"
    # DAS28 at the required time points (latest components per window, as the criteria compute it)
    for label, lo, hi in (("最近一次（90日內）", -90, 0), ("前次（90–180日前）", -180, -91)):
        f.das28.append(_das28(lake, pid, run_date, label, lo, hi))
    # screening results
    for key, vs in (("hbsag", "VS_HBSAG"), ("ahbc", "VS_ANTI_HBC"), ("igra", "VS_IGRA")):
        codes = _codes(rs, vs)
        if not codes:
            continue
        r = lake.query(
            "SELECT value_code, CAST(effective AS DATE) AS d FROM observation WHERE pid = $1 "
            "AND list_contains(CAST($2 AS VARCHAR[]), code) AND CAST(effective AS DATE) <= CAST($3 AS DATE) "
            "ORDER BY effective DESC, oid DESC LIMIT 1",
            [pid, codes, rd],
        ).to_pylist()
        if r:
            res = {"LA6576-8": "陽性", "LA6577-6": "陰性"}.get(str(r[0]["value_code"]), str(r[0]["value_code"]))
            f.values[key] = f"{res}（{r[0]['d'].isoformat()}）"
    cxr = _codes(rs, "VS_CHEST_X_RAY")
    if cxr:
        r = lake.query(
            "SELECT effective, conclusion FROM report WHERE pid = $1 AND list_contains(CAST($2 AS VARCHAR[]), code) "
            "AND effective <= CAST($3 AS DATE) ORDER BY effective DESC, rid DESC LIMIT 1",
            [pid, cxr, rd],
        ).to_pylist()
        if r:
            f.values["cxr"] = f"胸部X光 {r[0]['effective'].isoformat()}：{r[0]['conclusion'] or ''}"
    tb = [x for x in (f.values.get("igra") and f"IGRA {f.values['igra']}", f.values.get("cxr")) if x]
    f.values["tb_screen"] = "；".join(tb) if tb else None
    # current approval (claims)
    claim = lake.query(
        "SELECT product, approval_end FROM claim WHERE pid = $1 AND outcome = 'approved' "
        "AND approval_end >= CAST($2 AS DATE) ORDER BY approval_end DESC LIMIT 1",
        [pid, rd],
    ).to_pylist()
    if claim:
        f.values["approval_end"] = claim[0]["approval_end"].isoformat()
        f.values["current_product"] = claim[0]["product"]
    return f


def _das28(lake: LakeAPI, pid: str, run_date: date, label: str, lo: int, hi: int) -> dict[str, str]:
    comps = {k: derived.CODES[k][1] for k in derived.COMPONENTS["das28"]}
    rows = lake.query(
        "SELECT code, value_num, CAST(effective AS DATE) AS d FROM observation WHERE pid = $1 "
        "AND list_contains(CAST($2 AS VARCHAR[]), code) AND CAST(effective AS DATE) BETWEEN CAST($3 AS DATE) "
        "AND CAST($4 AS DATE) AND value_num IS NOT NULL ORDER BY effective DESC, oid DESC",
        [
            pid,
            list(comps.values()),
            (run_date + timedelta(days=lo)).isoformat(),
            (run_date + timedelta(days=hi)).isoformat(),
        ],
    ).to_pylist()
    latest: dict[str, tuple[float, date]] = {}
    for r in rows:
        latest.setdefault(r["code"], (float(r["value_num"]), r["d"]))
    get = {k: latest.get(code) for k, code in comps.items()}
    out = {
        "label": label,
        "date": MISSING,
        "tjc": MISSING,
        "sjc": MISSING,
        "marker": MISSING,
        "ptga": MISSING,
        "score": MISSING,
        "method": MISSING,
    }
    if get["tjc28"]:
        out["tjc"] = _fmt(get["tjc28"][0])
    if get["sjc28"]:
        out["sjc"] = _fmt(get["sjc28"][0])
    if get["ptga"]:
        out["ptga"] = _fmt(get["ptga"][0])
    marker = get["esr"] or get["crp"]
    if marker:
        out["marker"] = f"{'ESR' if get['esr'] else 'CRP'} {_fmt(marker[0])}"
    dates = [v[1] for v in get.values() if v]
    if dates:
        out["date"] = max(dates).isoformat()
    if get["tjc28"] and get["sjc28"] and get["ptga"] and marker:
        t, s, g = get["tjc28"][0], get["sjc28"][0], get["ptga"][0]
        if get["esr"]:
            score, method = derived.das28_esr(t, s, g, get["esr"][0]), "DAS28-ESR"
        else:
            assert get["crp"] is not None
            score, method = derived.das28_crp(t, s, g, get["crp"][0]), "DAS28-CRP"
        out["score"], out["method"] = f"{score:.2f}", method
    return out


def course_facts(f: Facts) -> dict[str, Any]:
    """The de-identified fact set given to the ``draft_doc`` prompt (no identifiers, SPEC §7.6)."""
    recent, previous = [*f.das28, {}, {}][:2]
    out: dict[str, Any] = {
        "diagnosis": f.get("diagnosis"),
        "diagnosis_date": f.get("diagnosis_date"),
        "dmards": "、".join(f"{m['name']}（{m['days']}日）" for m in f.dmards) or None,
        "das28_latest": recent.get("score") if recent.get("score") != MISSING else None,
        "das28_latest_date": recent.get("date") if recent.get("date") != MISSING else None,
        "das28_previous": previous.get("score") if previous.get("score") != MISSING else None,
        "tb_screening": f.get("tb_screen"),
        "hbv_screening": f.get("hbsag"),
        "approval_end": f.get("approval_end"),
    }
    return {k: v for k, v in out.items() if v not in (None, "")}
