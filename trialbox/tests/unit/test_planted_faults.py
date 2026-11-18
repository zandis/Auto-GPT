"""H-32 (D-1110): the planted-faults harness, on stand-ins. No box, no database: how a page is read, which lines are
new, what counts as shown, in the language, on /metrics and in the mail, which runbook page a text names, the clock's
stand-in time server and the certificate maker; and that the faults, their runbook quotes and the findings file agree
with the tree. The drill itself is ``tests/e2e/test_planted_faults_drill.py``."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tb_common import audit, metrics

from tools import planted_faults as pf

pytestmark = [pytest.mark.nodb]

ROOT = Path(__file__).resolve().parents[2]
FINDINGS = ROOT / "docs/plan/measurements/planted-faults-2026-11-18/findings.json"
PAGE = ROOT / "docs/plan/measurements/planted-faults-2026-11-18.md"
CERT = pf.BY_KEY["certificate"]


def test_the_seven_faults_are_the_cards() -> None:
    assert [f.words for f in pf.FAULTS] == [
        "backup target gone", "disk nearly full", "morning mail not sent", "certificate near its end", "clock off",
        "model service down", "feed folder empty",
    ]  # fmt: skip
    for f in pf.FAULTS:
        assert set(f.keywords) == set(pf.LANGS), f.key
        assert ("stand-in" in f.planted) or f.planted.startswith("real"), f.key  # each says which it is


def test_a_page_is_read_as_lines_with_its_links() -> None:
    page = (
        "<html><head><title>x</title></head><body><nav>menu</nav><main><h2>Backups</h2>"
        "<p><span class='pill ok'>3 hours ago</span></p><a href='/admin/ops?tab=backups'>Open</a>"
        "<ul><li>disk / 40 % full</li></ul></main></body></html>"
    )
    lines = pf.page_lines(page)
    assert lines == ["Backups", "3 hours ago", "Open </admin/ops?tab=backups>", "disk / 40 % full"]
    assert "menu" not in " ".join(lines)  # the <main> part only


def test_only_new_lines_count_and_a_moved_number_is_not_new() -> None:
    before = ["Backups", "3 hours ago", "disk / 40 % full"]
    after = ["Backups", "4 hours ago", "disk / 41 % full", "certificate ends in 12 days"]
    assert pf.new_lines(before, after) == ["certificate ends in 12 days"]


def test_a_line_in_english_on_a_ja_page_is_not_in_the_language() -> None:
    new = {
        "en": ["certificate ends in 12 days: ask hospital IT"],
        "zh-TW": ["憑證將於 12 天後到期"],
        "ja": ["システム状態：異常：certificate ends in 12 days"],  # a translated level before an English check text
    }
    v = pf.page_verdict(CERT, new)
    assert [v[lang]["verdict"] for lang in pf.LANGS] == ["shown", "shown", "not in the language"]
    assert pf.page_verdict(CERT, {})["en"]["verdict"] == "not shown"


def test_metrics_are_read_by_check_and_only_the_faults_own_check_counts_as_shown() -> None:
    hl = metrics.Health(datetime(2026, 11, 18, tzinfo=UTC), (
        metrics.Check("canary", metrics.OK, "ok"), metrics.Check("certificate", metrics.RED, "ends"),
        metrics.Check("disk:/data", metrics.WARN, "72 %", 72.0),
    ))  # fmt: skip
    got = pf.parse_metrics(metrics.prometheus(hl, "console"))
    assert got == {"level": "red", "checks": {"canary": "ok", "certificate": "red", "disk:/data": "warn"}}
    green = {"level": "ok", "checks": {"canary": "ok", "certificate": "ok", "disk:/data": "ok"}}
    assert pf.metrics_verdict(CERT, green, got)["verdict"] == "shown"
    disk = pf.metrics_verdict(pf.BY_KEY["disk_full"], green, got)
    assert disk["verdict"] == "shown" and set(disk["moved"]) == {"certificate", "disk:/data"}
    assert pf.metrics_verdict(pf.BY_KEY["clock_off"], green, got)["verdict"] == "shown by another check"
    assert pf.metrics_verdict(CERT, green, green)["verdict"] == "not shown"


def test_the_mail_counts_red_lines_per_reader_and_ignores_the_green_ones() -> None:
    admins = {"it@hospa.test": "en", "itja@hospa.test": "ja"}
    mails = [
        pf.Mail("notice", "HEALTH", "it@hospa.test", "TrialBox health: RED",
                "Box health: RED: certificate ends in 12 days\n- [RED] certificate ends in 12 days", "en"),
        pf.Mail("notice", "HEALTH", "itja@hospa.test", "TrialBox システム状態：RED",
                "システム状態：異常：certificate ends in 12 days\n- [RED] certificate ends in 12 days", "ja"),
        pf.Mail("notice", "HEALTH", "it@hospa.test", "next day", "- [ok] certificate 200 days left", "en"),
    ]  # fmt: skip
    v = pf.mail_verdict(CERT, mails, admins)
    assert v["verdict"] == "not in the language" and v["per_admin"] == {"it@hospa.test": 1, "itja@hospa.test": 1}
    assert pf.mail_verdict(CERT, mails[2:], admins)["verdict"] == "not shown"  # an ok line is not a notice
    assert pf.mail_verdict(CERT, mails[:1], admins)["verdict"] == "shown"


def test_a_runbook_reference_resolves_to_its_page() -> None:
    refs = pf.runbook_refs(["What to do: docs/RUNBOOK.md §5 (Backup).", "see docs/runbook/04-disk-full.md"])
    assert refs == ["docs/RUNBOOK.md §5", "docs/runbook/04-disk-full.md"]
    assert pf.resolve_ref(refs[0]) == ["docs/runbook/05-updates-backup-restore-secrets.md"]
    v = pf.runbook_verdict(pf.BY_KEY["backup_target"], ["What to do: docs/RUNBOOK.md §5 (Backup)."])
    assert v["leads_there"] and v["expected_exists"]
    assert not pf.runbook_verdict(pf.BY_KEY["disk_full"], ["disk / 94 % full"])["leads_there"]


def test_every_runbook_page_and_quoted_step_is_in_the_tree() -> None:
    for f in pf.FAULTS:
        if f.runbook:
            assert (ROOT / f.runbook).is_file(), f.key
        for s in f.steps:
            lines = (ROOT / s.page).read_text(encoding="utf-8").splitlines()
            near = " ".join(lines[max(0, s.line - 3) : s.line + 2])
            head = s.quote.split("`")[1] if "`" in s.quote else s.quote[:30]
            assert head in near, (f.key, s.page, s.line, head)
            assert bool(s.cmd) != bool(s.needs), (f.key, s.line)  # run here, or say what it needs


def test_the_time_server_stand_in_gives_the_offset_the_products_check_reads() -> None:
    with pf.SntpStandIn(-600.0) as srv:
        st = audit.clock_state({"TB_NTP_SERVER": srv.address})
    assert st.offset is not None and 595 < st.offset < 605  # this clock reads 600 s ahead of the server


def test_the_certificate_maker_ends_when_asked(tmp_path: Path) -> None:
    end = pf.make_cert(tmp_path / "c.pem", tmp_path / "k.pem", 12)
    assert abs((metrics.cert_not_after(tmp_path / "c.pem") - end).total_seconds()) < 2
    assert (tmp_path / "k.pem").stat().st_mode & 0o777 == 0o600
    facts = metrics.cert_facts({"TB_TLS_MODE": "hospital", "TB_TLS_CERT_FILE": str(tmp_path / "c.pem")})
    assert metrics.check_cert(facts, datetime.now(UTC), metrics.Thresholds()).level == metrics.RED


def test_the_table_says_one_line_per_fault() -> None:
    rec = {"faults": [{"fault": "clock_off", "error": "OSError: x"}]}
    assert pf.table(rec) == ["clock_off: could not be planted: OSError: x"]


def test_the_findings_file_names_the_drills_faults_and_the_page() -> None:
    data = json.loads(FINDINGS.read_text(encoding="utf-8"))
    assert data["card"] == "H32" and data["source"] == str(PAGE.relative_to(ROOT))
    text = PAGE.read_text(encoding="utf-8")
    for row in data["findings"]:
        assert row["id"].startswith("H32-") and row["fault"] in pf.BY_KEY, row["id"]
        assert row["id"] in text, row["id"]  # the page is the full account of each row
