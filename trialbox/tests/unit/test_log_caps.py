"""T-108d (D-389; OPS-034, OPS-037): the container log caps hold a full SCREEN night, a day that lost its start to
rotation is reported as a log gap, and the host's own log files rotate.

The night is simulated, not measured (G1 is parked): docker's json-file rotation is replayed at 1/1000 scale (the
caps and the volume both divided by 1000), with the review's estimate of the busiest service's night."""

from __future__ import annotations

import gzip
import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tools.trialbox import logs as tl

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
SCALE = 1000
DAY = date(2026, 11, 8)  # a synthetic night; the site zone is UTC here
LINE = 300  # bytes a request line (the review's estimate)


class JsonFileLog:
    """Docker's json-file driver: append to <id>-json.log, rotate at max-size, keep max-file files in all."""

    def __init__(self, folder: Path, max_size: int, max_file: int) -> None:
        self.path = folder / "c0ffee-json.log"
        self.max_size, self.max_file = max_size, max_file
        self.path.write_text("")

    def write(self, ts: datetime, text: str) -> None:
        if self.path.stat().st_size >= self.max_size:
            oldest = self.path.with_name(f"{self.path.name}.{self.max_file - 1}")
            oldest.unlink(missing_ok=True)
            for n in range(self.max_file - 2, 0, -1):
                f = self.path.with_name(f"{self.path.name}.{n}")
                if f.exists():
                    f.rename(self.path.with_name(f"{self.path.name}.{n + 1}"))
            self.path.rename(self.path.with_name(f"{self.path.name}.1"))
            self.path.write_text("")
        stamp = ts.strftime("%Y-%m-%dT%H:%M:%S.%f") + "123Z"
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"log": text + "\n", "stream": "stdout", "time": stamp}) + "\n")

    def lines(self, since: datetime, until: datetime) -> bytes:
        files = sorted(self.path.parent.glob(self.path.name + ".*"), key=lambda f: -int(f.name.rsplit(".", 1)[1]))
        out = []
        for f in [*files, self.path]:
            for raw in f.read_text(encoding="utf-8").splitlines():
                rec = json.loads(raw)
                t = datetime.fromisoformat(rec["time"][:26] + "+00:00")
                if since <= t < until:
                    out.append(f"{rec['time']} {rec['log']}")
        return "".join(out).encode()


def compose_caps() -> tuple[str, int]:
    text = (DEPLOY / "docker-compose.yml").read_text(encoding="utf-8")
    m = re.search(r'max-size: "\$\{TB_LOG_MAX_SIZE:-(\w+)\}", max-file: "\$\{TB_LOG_MAX_FILE:-(\d+)\}"', text)
    assert m, "the x-logging anchor reads TB_LOG_MAX_SIZE and TB_LOG_MAX_FILE"
    return m.group(1), int(m.group(2))


def night(tmp_path: Path, volume: int) -> tuple[Path, Any, JsonFileLog]:
    """Fill one container's log with the day before, a day of console traffic, a SCREEN night of ``volume`` bytes
    and the 20 minutes until the collector runs; return a deploy folder and a fake docker over it."""
    size, files = compose_caps()
    log = JsonFileLog(tmp_path, tl.size_bytes(size) // SCALE, files)
    start = datetime(2026, 11, 8, tzinfo=UTC)
    per_line = "x" * (LINE - 40)
    n_night = volume // SCALE // LINE

    def burst(t0: datetime, span: timedelta, n: int, tag: str) -> None:
        for i in range(n):
            log.write(t0 + span * i / max(1, n), f"{tag} {i} {per_line}")

    burst(start - timedelta(hours=6), timedelta(hours=6), n_night // 4, "before")
    burst(start, timedelta(hours=1), n_night, "screen")  # 00:00 to 01:00: the SCREEN night
    burst(start + timedelta(hours=7), timedelta(hours=11), n_night, "day")  # the day's console and mail traffic
    burst(start + timedelta(days=1), timedelta(minutes=20), n_night // 50, "after")
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text(f"TB_LOG_DIR={tmp_path / 'logs'}\nTB_TZ=UTC\nTB_LOG_MAX_SIZE={size}\n")

    def run(argv: Any) -> bytes:
        argv = list(argv)
        if argv[-2:] == ["--all", "--services"]:
            return b"gateway\n"
        if "-q" in argv:
            return b"c0ffee\n"
        if "inspect" in argv:
            return f"{log.path}|{tl.size_bytes(size) // SCALE}|{files}\n".encode()
        if "logs" in argv:
            since = datetime.fromisoformat(argv[argv.index("--since") + 1].replace("Z", "+00:00"))
            until = datetime.fromisoformat(argv[argv.index("--until") + 1].replace("Z", "+00:00"))
            return log.lines(since, until)
        raise AssertionError(argv)

    return deploy, run, log


def test_the_compose_caps_are_the_documented_provisional_ones() -> None:
    size, files = compose_caps()
    assert (size, files) == (tl.DEFAULT_LOG_MAX_SIZE, tl.DEFAULT_LOG_MAX_FILE)
    cap = tl.log_cap({})
    assert cap == 100 * 2**20 * 10
    # a day of the estimated busiest service, with docker's JSON wrapping, fits about three times (unmeasured, D-389)
    day = 2 * tl.NIGHT_ESTIMATE_BYTES * (LINE + tl.JSON_LINE_OVERHEAD) // LINE
    assert cap >= 1.4 * day
    assert tl.log_cap({"TB_LOG_MAX_SIZE": "1g", "TB_LOG_MAX_FILE": "3"}) == 3 * 2**30
    with pytest.raises(ValueError, match="log size"):
        tl.size_bytes("lots")


def test_a_full_screen_night_leaves_no_log_gap(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    deploy, run, _log = night(tmp_path, tl.NIGHT_ESTIMATE_BYTES)
    assert tl.main_action("collect", deploy, DAY.isoformat(), run) == 0
    cov = json.loads((tmp_path / "logs/services" / DAY.isoformat() / "COVERAGE.json").read_text())
    g = cov["services"]["gateway"]
    assert g["gap"] is False and cov["caps_measured"] is False
    assert 0 < g["share_of_cap"] < tl.HEADROOM_WARN  # room to spare: no warning either
    assert "LOG GAP" not in capsys.readouterr().err
    collected = (tmp_path / "logs/services" / DAY.isoformat() / "gateway.log.gz").read_bytes()
    text = gzip.decompress(collected).decode()
    assert "screen 0 " in text and f"screen {tl.NIGHT_ESTIMATE_BYTES // SCALE // LINE - 1} " in text  # whole night


def test_a_night_too_big_for_the_cap_is_reported_as_a_gap(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    deploy, run, _log = night(tmp_path, 4 * tl.NIGHT_ESTIMATE_BYTES)
    assert tl.main_action("daily", deploy, DAY.isoformat(), run, today=DAY + timedelta(days=1)) == 1
    err = capsys.readouterr().err
    assert "LOG GAP on 2026-11-08 in gateway" in err and "TB_LOG_MAX_SIZE" in err
    gap, _thin = tl.gaps(tmp_path / "logs", DAY)
    assert gap == ["gateway"]


def test_oldest_kept_reads_the_oldest_rotated_file(tmp_path: Path) -> None:
    log = JsonFileLog(tmp_path, 200, 3)
    t0 = datetime(2026, 11, 8, tzinfo=UTC)
    for i in range(20):
        log.write(t0 + timedelta(minutes=i), "y" * 100)
    kept, rotated = tl.oldest_kept(log.path)
    assert rotated == 2 and kept is not None and kept > t0  # the first lines are gone
    assert tl.oldest_kept(tmp_path / "missing-json.log") == (None, 0)


def test_the_host_logs_rotate() -> None:
    """OPS-037: every /var/log/trialbox-*.log a cron line or the installer writes is covered by the logrotate file,
    and the installer installs it."""
    rot = (DEPLOY / "logrotate/trialbox").read_text(encoding="utf-8")
    globs = re.findall(r"^(/var/log/\S+) \{", rot, re.M)
    assert globs == ["/var/log/trialbox-*.log"]
    written = set()
    for f in [DEPLOY / "install.sh", *sorted((DEPLOY / "backup").glob("*.cron"))]:
        written |= set(re.findall(r"/var/log/trialbox-[\w.-]+\.log", f.read_text(encoding="utf-8")))
    assert {"/var/log/trialbox-retention.log", "/var/log/trialbox-backup.log"} <= written
    for body in ("weekly", "rotate 53", "compress", "missingok", "notifempty"):
        assert re.search(rf"^\s+{body}$", rot, re.M), body
    assert "install -m 644 deploy/logrotate/trialbox /etc/logrotate.d/trialbox" in (DEPLOY / "install.sh").read_text()
