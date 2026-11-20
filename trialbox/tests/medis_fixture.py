"""An INVENTED release in the shape of MEDIS-DC's ICD10対応標準病名マスター (card 10B-22, D-1261), and a stand-in for
``adapter.licensed.load_release`` / ``check_release`` (card 10B-2c, pull request #1238) until that lands on master.

Nothing here is MEDIS data: every management number, exchange code, name and modifier is made up (the names are
built from the syllables テスト and ダミー; the codes start with Z or 99). Only the SHAPE is the release's: a zip
``byomei<nnn>.zip`` with ``byomei<nnn>/readme.txt`` (its first line names the version and the revision date),
``main/nmain<nnn>.txt`` (病名基本テーブル, 20 columns), ``main/mdfy<nnn>.txt`` (修飾語テーブル, 10 columns),
``main/index<nnn>.txt`` (索引テーブル, 9 columns), ``option/ttl_*.txt`` (one line of column titles each) and the
specification as ``dcmnts/spc<nnn>.pdf`` and ``.doc``; Shift_JIS, every field double-quoted, no header row.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Any

DISEASE_COLUMNS = (
    "変更区分", "病名管理番号", "病名表記", "病名表記カナ", "採択区分", "病名交換用コード", "ＩＣＤ１０‐２０１３",
    "ＩＣＤ１０‐２０１３複数分類コード", "予備１", "予備２", "レセ電算コード", "傷病名省略名称", "使用分野", "変更履歴番号",
    "更新日付", "移行先病名管理番号", "単独使用禁止区分", "保険請求外区分", "予備３", "予備４",
)  # fmt: skip
MODIFIER_COLUMNS = (
    "変更区分", "修飾語管理番号", "修飾語表記", "修飾語表記カナ", "修飾語交換用コード", "接続位置区分", "修飾語区分",
    "排他グループコード", "レセ電算修飾語コード", "修飾語説明用ラベル",
)  # fmt: skip
INDEX_COLUMNS = (
    "索引用語", "対応用語コード", "病名修飾語区分", "かな漢字区分", "同義語区分", "異字体区分", "第１版採用表記区分",
    "言語区分（将来用予約）", "省略区分（将来用予約）",
)  # fmt: skip

# (変更区分, 病名管理番号, 病名表記, カナ, 病名交換用コード, ICD-10 2013, 複数分類, 移行先, 採択区分, 使用分野,
# 単独使用禁止区分): invented rows covering each case the release has: unchanged, new, changed, deleted with a
# successor, deleted without one, an exchange code on two rows (a level 1 name and its 採択区分 3 synonym), no ICD-10,
# a 複数分類コード, an ICD-10 the ICD-10-CM list lacks, a sub-classification letter, a hyphen inside the value, a
# dental and a Kampo entry, an entry usually written with a modifier
DISEASES: tuple[tuple[str, ...], ...] = (
    ("0", "99000001", "テスト病甲", "テストビョウコウ", "ZA01", "E119", "", "", "1", "1", "00"),
    ("3", "99000002", "テスト病乙", "テストビョウオツ", "ZA02", "I10", "", "", "1", "1", "01"),
    ("5", "99000003", "ダミー性テスト炎", "ダミーセイテストエン", "ZA03", "J189", "", "", "2", "4", "00"),
    ("1", "99000004", "旧テスト症", "キュウテストショウ", "ZA04", "K529", "", "99000005", "1", "1", "00"),
    ("3", "99000005", "新テスト症", "シンテストショウ", "ZA05", "K529", "", "", "1", "1", "00"),
    ("0", "99000006", "テスト病丙", "テストビョウヘイ", "ZA06", "M199", "", "", "1", "1", "00"),
    ("0", "99000007", "テスト病丙型", "テストビョウヘイガタ", "ZA06", "M199", "", "", "3", "1", "00"),
    ("0", "99000008", "ダミー症候群", "ダミーショウコウグン", "ZA08", "", "", "", "1", "1", "00"),
    ("0", "99000009", "テスト二重病", "テストニジュウビョウ", "ZA09", "E142", "N083", "", "1", "1", "00"),
    ("0", "99000010", "テスト病丁", "テストビョウテイ", "ZA10", "U049", "", "", "1", "1", "00"),
    ("1", "99000011", "廃止テスト病", "ハイシテストビョウ", "ZA11", "R688", "", "", "1", "1", "00"),
    ("0", "99000012", "テスト亜分類症", "テストアブンルイショウ", "ZA12", "E109a", "", "", "1", "1", "00"),
    ("0", "99000013", "テスト範囲症", "テストハンイショウ", "ZA13", "A15-9", "", "", "1", "1", "00"),
    ("0", "99000014", "テスト漢方証", "テストカンポウショウ", "ZA14", "R53", "", "", "2", "2", "00"),
)
# (変更区分, 修飾語管理番号, 修飾語表記, カナ, 交換用コード, 接続位置区分, 修飾語区分)
MODIFIERS: tuple[tuple[str, ...], ...] = (
    ("0", "99010001", "ダミー側", "ダミーソク", "ZM01", "1", "A1000000"),
    ("0", "99010002", "テスト性", "テストセイ", "ZM02", "2", "A2000000"),
    ("1", "99010003", "廃止修飾", "ハイシシュウショク", "ZM03", "3", "A3000000"),
)
# (索引用語, 対応用語コード (an exchange code), 病名修飾語区分, かな漢字区分, 同義語区分, 異字体区分): upper-case
# half-width as the release writes them
INDEX: tuple[tuple[str, ...], ...] = (
    ("テストビヨウコウ", "ZA01", "1", "2", "0", "9"),
    ("テスト病A", "ZA01", "1", "1", "1", "9"),
    ("テスト病甲型", "ZA01", "1", "1", "0", "2"),
    ("旧テスト症ノ別名", "ZA04", "1", "1", "1", "9"),
    ("テスト関連病", "ZA02", "1", "1", "2", "9"),
    ("テスト非推奨名", "ZA02", "1", "1", "8", "9"),
    ("テスト検索語", "ZA02", "1", "1", "9", "9"),
    ("テスト廃語", "0000", "1", "1", "0", "9"),
    ("ダミーガワ", "ZM01", "2", "1", "0", "9"),
)


def _line(cells: list[str]) -> str:
    return ",".join(f'"{c}"' for c in cells)


def tables(n: str = "999") -> dict[str, bytes]:
    """The three tables, Shift_JIS, quoted, no header row."""
    nmain = []
    for change, no, name, kana, ex, icd, multi, succ, adoption, field, no_solo in DISEASES:
        row = [change, no, name, kana, adoption, ex, icd, multi, "", "", f"9{no[2:]}", name, field, "1", "20260601",
               succ, no_solo, "0", "", ""]  # fmt: skip
        nmain.append(_line(row))
    mdfy = [
        _line([c, no, name, kana, ex, pos, cls, "", f"9{no[4:]}", ""]) for c, no, name, kana, ex, pos, cls in MODIFIERS
    ]
    idx = [_line([term, code, kind, kk, syn, var, "0", "", ""]) for term, code, kind, kk, syn, var in INDEX]
    return {
        f"nmain{n}.txt": ("\r\n".join(nmain) + "\r\n").encode("cp932"),
        f"mdfy{n}.txt": ("\r\n".join(mdfy) + "\r\n").encode("cp932"),
        f"index{n}.txt": ("\r\n".join(idx) + "\r\n").encode("cp932"),
    }


def release_zip(n: str = "999", version: str = "V9.99", revised: str = "2026年6月1日", *,
                extra: dict[str, bytes] | None = None, drop: tuple[str, ...] = ()) -> bytes:  # fmt: skip
    """The invented release as MEDIS lays it out, zipped (``extra``: more members by path; ``drop``: base names
    left out)."""
    buf = io.BytesIO()
    readme = f"ICD10対応標準病名マスター　{version}　{revised}改訂\r\n（テスト用に作った架空の版）\r\n".encode("cp932")
    files = {f"byomei{n}/readme.txt": readme}
    files |= {f"byomei{n}/main/{k}": v for k, v in tables(n).items()}
    for name, cols in (
        ("ttl_main.txt", DISEASE_COLUMNS),
        ("ttl_mdfy.txt", MODIFIER_COLUMNS),
        ("ttl_idx.txt", INDEX_COLUMNS),
    ):
        files[f"byomei{n}/option/{name}"] = (_line(list(cols)) + "\r\n").encode("cp932")
    files[f"byomei{n}/dcmnts/spc{n}.pdf"] = b"%PDF-1.4 invented specification"
    files[f"byomei{n}/dcmnts/spc{n}.doc"] = b"invented specification"
    files = {k: v for k, v in files.items() if k.rsplit("/", 1)[-1] not in drop}
    files |= extra or {}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


# ------------------------------------------------- the release as #1238's loader stores it (card 10B-2c, D-1257)
def concepts() -> dict[str, dict[str, Any]]:
    """``licensed.tables()["medis"]`` of the invented release, in #1238's shape: one concept for each exchange code,
    its preferred row's name and ICD-10 (as written; empty when the current rows disagree), every row in
    ``extra["rows"]``."""
    import json

    groups: dict[str, list[dict[str, str]]] = {}
    for change, no, name, kana, ex, icd, multi, succ, adoption, field, no_solo in DISEASES:
        row = {"no": no, "name": name, "icd": icd, "kana": kana, "change": change, "adoption": adoption,
               "multi_class": multi, "field": field, "successor": succ, "no_solo": no_solo}  # fmt: skip
        groups.setdefault(ex, []).append({k: v for k, v in row.items() if v})
    out: dict[str, dict[str, Any]] = {}
    for ex, members in groups.items():
        current = [r for r in members if r.get("change") in ("0", "3", "5")]
        best = min(current or members, key=lambda r: (r.get("adoption", "9"), r["no"]))
        icds = {r.get("icd", "") for r in current if r.get("icd")}
        icd = best.get("icd", "") if len(icds) <= 1 else ""
        extra = {"management_no": best["no"], **{k: v for k, v in best.items() if k not in ("no", "name", "icd")},
                 "rows": members}  # fmt: skip
        out[ex] = {"display": best["name"], "target_system": "http://hl7.org/fhir/sid/icd-10" if icd else "",
                   "target_code": icd, "extra": json.dumps(extra, ensure_ascii=False)}  # fmt: skip
    return out


def lookup_term(term: str) -> list[dict[str, str]]:
    """``TermStore.lookup_term`` of the invented index (#1238): the rows of one 索引用語, after NFKC."""
    import unicodedata

    t = unicodedata.normalize("NFKC", term).strip()
    return [{"term": a, "code": c, "target_kind": k, "kana_kanji": kk, "synonym": syn, "variant": var}
            for a, c, k, kk, syn, var in sorted(INDEX, key=lambda r: r[1]) if a == t]  # fmt: skip


def install_standin(monkeypatch: Any) -> None:
    """#1238's check_release / load_release, while they are not on master; the real ones once they are."""
    from adapter import licensed

    if not hasattr(licensed, "load_release"):
        monkeypatch.setattr(licensed, "check_release", check_release, raising=False)
        monkeypatch.setattr(licensed, "load_release", load_release, raising=False)


# ---------------------------------------------------------------------------- the stand-in loader (until #1238)
def _readme(folder: Path) -> tuple[str, str]:
    from adapter.licensed import LicensedError

    if not (folder / "readme.txt").is_file():
        raise LicensedError("LIC-RELEASE-MISSING", "the release lacks readme.txt")
    text = (folder / "readme.txt").read_bytes().decode("cp932").splitlines()[0]
    m = re.search(r"V(\d+\.\d+)\s+(\d{4})年(\d{1,2})月(\d{1,2})日", text.replace("　", " "))
    if m is None:
        from adapter.licensed import LicensedError

        raise LicensedError("LIC-RELEASE-README", "readme.txt's first line does not give the version and date")
    return m.group(1), f"{int(m.group(2)):04d}-{int(m.group(3)):02d}-{int(m.group(4)):02d}"


def _find(folder: Path, prefix: str) -> Path:
    from adapter.licensed import LicensedError

    got = sorted(p for p in folder.iterdir() if p.name.lower().startswith(prefix))
    if not got:
        raise LicensedError("LIC-RELEASE-MISSING", f"the release lacks {prefix}*.txt")
    return got[0]


def check_release(source: Path) -> dict[str, Any]:
    """Stand-in of ``licensed.check_release`` (#1238): what a load would do, writing nothing."""
    from adapter import licensed

    folder = Path(source)
    version, released = _readme(folder)
    skipped: list[tuple[str, int, str]] = []
    d = licensed.parse("medis", _find(folder, "nmain").read_bytes(), list(DISEASE_COLUMNS))
    m = licensed.parse("medis_modifier", _find(folder, "mdfy").read_bytes(), list(MODIFIER_COLUMNS))
    skipped += [("medis", n, w) for n, w in d.skipped] + [("medis_modifier", n, w) for n, w in m.skipped]
    idx = _find(folder, "index").read_bytes().decode("cp932").splitlines()
    import hashlib

    digest = hashlib.sha256(b"".join(p.read_bytes() for p in sorted(folder.iterdir()))).hexdigest()
    return {"version": version, "released": released, "disease_rows": len(d.concepts),
            "disease_current": sum(1 for c in d.concepts if '"change": "1"' not in c["extra"]),
            "modifier_rows": len(m.concepts), "index_rows": len([x for x in idx if x.strip()]),
            "skipped": skipped, "sha256": digest}  # fmt: skip


def load_release(store: Any, source: Path, *, by: str, audit_dir: Any = None) -> dict[str, Any]:
    """Stand-in of ``licensed.load_release(store, source, *, by)`` (#1238): the same answer as the check, after
    loading the disease and modifier tables with the loader of master."""
    out = check_release(source)
    folder = Path(source)
    store.load("medis", _find(folder, "nmain").read_bytes(), version=out["version"], source="nmain", by=by,
               columns=list(DISEASE_COLUMNS))  # fmt: skip
    store.load("medis_modifier", _find(folder, "mdfy").read_bytes(), version=out["version"], source="mdfy", by=by,
               columns=list(MODIFIER_COLUMNS))  # fmt: skip
    return out
