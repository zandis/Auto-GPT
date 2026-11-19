"""Card 10C-1c: the corpus of ordinary operational log lines the scrubber must leave byte-identical.

    python tests/fixtures/log_scrub/make_operational_lines.py   # rewrites operational_lines.txt

Each line is one of the repository's own log calls (``log.info("...%s...", ...)`` in services/, libs/ and tools/),
its placeholders filled in turn (twice, with other values) with the values an operational line carries: ids (ULIDs, UUIDs, 32-hex pseudonyms),
counts, durations, paths, hashes, versions, dates and times, HTTP statuses, service and study names. Then lines in
the shapes the box writes without a call of its own (the request middleware's line, uvicorn's start lines, the
scheduler's). No value is a person's or a patient's: a bare number of eight digits is left out, since it is the
contract's chart-number shape and the site rule scrubs it by design.
"""

from __future__ import annotations

import itertools
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).with_name("operational_lines.txt")
CALL = re.compile(
    r"""\b(?:log|logger|LOG|_log|LOGGER|_logger)\.(?:debug|info|warning|error|exception|critical)\(\s*(["'])((?:(?!\1)[^\\\n]|\\.){8,200})\1"""
)
PLACEHOLDER = re.compile(r"%(?:\.\d+)?[sdrfi]")
VALUES = [
    "01JITCOMPILE7Q4K9ZT2M5XW3B",
    "3f2b8c1e-9a4d-4c6e-8f00-2d7a1b5c9e43",
    "1ee23f8bc69240ca7c572e40510f985b",
    "1234",
    "0.42",
    "/data/lake/2026-11-08/part-0001.parquet",
    "sha256:9c56cc51b374c3ba189210d5b6d4bf57790d351c96c47c02190ecf1e430635ab",
    "v1.4.2",
    "2026-11-19T03:00:00Z",
    "200",
    "orchestrator",
    "STUDY-JP-001",
    "12.3 ms",
    "ScreeningJob",
    "ValueError",
    "17",
    "main",
    "trialbox_wf",
    "2026-11-08",
    "night",
    "5",
    "ruleset-onc-7 v3",
    "TimeoutError",
    "/api/v1/jobs/{job_id}",
    "998",
    "llm-service",
    "65536",
    "ja",
    "redcap",
    "1.0.0",
]


def calls() -> list[str]:
    found: list[str] = []
    for top in ("services", "libs", "tools"):
        for p in sorted((ROOT / top).rglob("*.py")):
            if "generated" in p.parts or "__pycache__" in p.parts:
                continue
            for m in CALL.finditer(p.read_text(encoding="utf-8", errors="ignore")):
                found.append(m.group(2).encode().decode("unicode_escape", errors="ignore") if "\\" in m.group(2)
                             else m.group(2))  # fmt: skip
    return sorted(set(found))


def filled(fmt: str, values: itertools.cycle[str]) -> str:
    out = PLACEHOLDER.sub(lambda m: next(values) if m.group(0)[-1] in "sr" else str(len(next(values))), fmt)
    out = re.sub(r"\{[^{}]{0,40}\}", lambda _m: next(values), out)  # an f-string's fields
    return out.replace("%%", "%")


EXTRA = [
    "GET /api/v1/jobs/{job_id} 200 12.3ms",
    "POST /api/v1/studies/{rs}/records/{record} 422 4.1ms",
    "INFO:     Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)",
    "INFO:     Started server process [41]",
    "INFO:     Waiting for application startup.",
    "INFO:     Application startup complete.",
    'Added job "night_chain" to job store "default"',
    "Running job \"retention (trigger: cron[hour='2', minute='20'])\" (scheduled at 2026-11-19 02:20:00+09:00)",
    'Job "retention" executed successfully',
    "2026-11-19T03:00:00.123+00:00 orchestrator job 01JITCOMPILE7Q4K9ZT2M5XW3B SCREENING -> DONE in 41.2 s",
    "lake: 12 parquet files, 1.4 GiB, 3 snapshots kept, sha256 9c56cc51b374c3ba",
    "embed cache hit 98.2% (41233 of 41987 chunks)",
    "model llm-service ready: 2 GPUs, 128 GB, max_model_len=32768",
    "backup trialbox-2026-11-19.tbbak written: 4.2 GB in 312 s",
    "restic snapshot 7f3a9c2e saved, 1532 files, 0 errors",
    "disk /data 61% used (1.2 TB free)",
    "audit chain verified: 2026-11-18.jsonl 14211 events, head 4be1f0c2",
    "release v1.0.0+build.20261118 installed; rollback point rb-20261119T0300Z kept",
    "ingest feed ss-mix2 day 2026-11-18: 5123 files, 0 quarantined, 211 MB",
    "retry 3/5 after 2.0 s (ConnectTimeout)",
    "pid 1ee23f8bc69240ca7c572e40510f985b recomputed in 0.8 s",
    "study STUDY-JP-001 v7 published to 3 sites",
    "trace 4bf92f3577b34da6a3ce929d0e0e4736 span 00f067aa0ba902b7",
    "container trialbox-console-1 restarts=0 status=running health=healthy",
    "ruleset onc-7@3 compiled: 41 criteria, 0 warnings, 2.3 s",
    "TZ Asia/Tokyo; site day 2026-11-18T00:00:00+09:00 to 2026-11-19T00:00:00+09:00",
    "HTTP/1.1 503 Service Unavailable from http://lake:8081/health after 5.0 s",
    "worker 2 of 4 idle",
    "cron 00:20 logs daily: collected 11 services, pruned 2 days",
    "version 2026.11.18-rc2 (git 06c9796f)",
]


def main() -> None:
    lines: list[str] = []
    for shift in (0, 7):  # each call twice, with other values in its places
        values = itertools.cycle(VALUES[shift:] + VALUES[:shift])
        lines += [filled(f, values) for f in calls()]
    lines = sorted(set(lines)) + EXTRA
    lines = [ln for ln in lines if "\n" not in ln and not re.search(r"(?<!\d)\d{8}(?!\d)", ln)]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(lines)} lines -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
