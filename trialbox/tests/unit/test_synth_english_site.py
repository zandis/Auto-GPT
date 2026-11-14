"""NEW-B-42 (D-743): an English-style site in the synthetic hospital (the owner's D-502: every data set end to end
in en, ja and zh-TW).

A site's record style was JP or TW only; English was 10 % of each site's notes, on patients with Japanese or
Taiwanese records. An ``EN`` site writes the Taiwanese table layout (the one ``tw_core/demo_his.yaml`` reads: its
drug, diagnosis, lab and procedure names are already English) with English identities (patient and doctor names,
an identifier that is no country's national number, a phone number of the range kept for fiction) and every note
in English. Synthetic data only."""

from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path

from tools.synth.generator import Generator
from tools.synth.reserved import is_reserved
from tools.synth_hospital import DEFAULT_LANG_MIX, PROFILES, parse_sites, run

ROOT = Path(__file__).resolve().parents[2]
REF = date(2026, 11, 1)
CJK = re.compile(r"[　-ヿ㐀-鿿＀-￯]")


def test_an_english_site_writes_english_identities_and_notes() -> None:
    g = Generator(7, "EN-T", REF, 300, "4", style="EN", lang_mix={"en": 1.0}, gold=True)
    data = g.run()
    for p in data.tables["patient"]:
        assert re.fullmatch(r"[A-Z][a-z]+ [A-Z][a-z'-]+", p["name"]), p["name"]
        assert re.fullmatch(r"SYN\d{7}", p["id_no"]), p["id_no"]  # no country's national number
        assert re.fullmatch(r"555-01\d\d", p["phone"]), p["phone"]  # the range kept for fiction
        assert not is_reserved("phone", p["phone"]) and not is_reserved("name", p["name"])
    assert set(g.note_lang.values()) == {"en"}
    assert data.tables["note"] and not any(CJK.search(n["text"]) for n in data.tables["note"])
    assert data.tables["practitioner"] and not any(CJK.search(r["name"]) for r in data.tables["practitioner"])
    for table, rows in data.tables.items():  # nothing of the site is written in Chinese or Japanese
        for r in rows:
            assert not any(isinstance(v, str) and CJK.search(v) for v in r.values()), (table, r)


def test_the_profile_and_the_sites_option_know_the_style() -> None:
    assert DEFAULT_LANG_MIX["EN"] == {"en": 1.0}
    assert PROFILES["ci-en"]["sites"] == "en-a:EN:2500,en-b:EN:2500"
    (spec,) = parse_sites("en-a:EN:100", 1, DEFAULT_LANG_MIX)
    assert spec.style == "EN" and spec.lang_mix == {"en": 1.0}


def test_a_small_english_run_passes_the_hospitals_checks_and_is_deterministic(tmp_path: Path) -> None:
    kw = {"sites": "en-a:EN:600", "chunk": 300}
    a = run(tmp_path / "a", **kw)  # type: ignore[arg-type]
    b = run(tmp_path / "b", **kw)  # type: ignore[arg-type]
    assert a.passed, a.failures
    assert a.summary["digest"] == b.summary["digest"]
    with (tmp_path / "a" / "en-a" / "patient.csv").open(encoding="utf-8", newline="") as fh:
        assert len(list(csv.DictReader(fh))) == 600


def test_the_taiwanese_mapping_reads_an_english_site(tmp_path: Path) -> None:
    from adapter.pipeline import AdapterConfig, run_ingest

    run(tmp_path / "synth", sites="en-a:EN:200", chunk=200)
    (tmp_path / "sec").mkdir()
    (tmp_path / "sec" / "site_hmac.key").write_bytes(b"k" * 32)
    cfg = AdapterConfig(lake_dir=tmp_path / "lake", secrets_dir=tmp_path / "sec", site_id="EN-A",
                        mapping_path=ROOT / "services/adapter/mapping/tw_core/demo_his.yaml",
                        audit_dir=tmp_path / "audit")  # fmt: skip
    rep = run_ingest(cfg, "csv", str(tmp_path / "synth" / "en-a"), snapshot="2026-10-31", load_fhir=False,
                     rebuild_lake=False, validate=False)  # fmt: skip
    assert rep.passed, rep.errors
    assert rep.counts["Patient"] == 200 and rep.counts.get("Condition", 0) > 0
    assert rep.counts.get("DocumentReference", 0) > 0  # the English notes
