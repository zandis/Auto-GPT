# ruff: noqa: F811 - the box fixture is imported from test_console_app and taken by name
"""9f-11 (D-1370, review 02/J-11, owner decision 11 of plan 9): the console leaves nothing of a clinical page on a
device. No service worker, no offline cache of clinical pages, no scan of a signed consent, no web push through an
outside push service. The rule is written in ``docs/security/05-data-protection.md``; these tests hold it.

Each check runs on the console as it is and, beside it, on a planted case that breaks the rule, so a check that could
never fail is seen: the file scan on a planted ``navigator.serviceWorker.register``, the push-host scan on a planted
host, and in Chromium (``tests/console/no_worker.js``) a service worker that does register on the same page served
without the console's policy. The test fails if a service worker registers on the console's page."""

from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from console import phone
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from tests.console.test_console_app import _done_screen, _ulid, box, login  # noqa: F401 - the fixture by name
from tests.console.test_phone_first import _node_playwright
from tests.console.test_role_route_matrix import _fill

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "services" / "console"
SCRIPT = Path(__file__).with_name("no_worker.js")
TEXT = (".html", ".htm", ".js", ".mjs", ".ts", ".css", ".json", ".webmanifest", ".svg", ".py", ".txt", ".md")

# What would keep a page, or send to a push service, from the browser. The tab's session storage is not here: it holds
# a form while it is typed (D-777, D-1222), dies with the tab and is dropped on save, on leaving and on sign-out.
OFFLINE = {
    "a service worker": re.compile(r"serviceWorker|\bserviceworker\b|importScripts", re.I),
    "web push": re.compile(r"PushManager|pushManager|PushSubscription|\bNotification\s*\(|Notification\.request"),
    "a page cache": re.compile(
        r"\bcaches\.(?:open|match|put|keys)|CacheStorage|applicationCache|\.appcache\b|<html[^>]*\smanifest="
    ),
    "a lasting browser store": re.compile(r"localStorage|indexedDB|openDatabase\("),
}
PUSH_HOSTS = re.compile(
    r"push\.apple\.com|fcm\.googleapis\.com|android\.googleapis\.com|push\.services\.mozilla\.com|"
    r"notify\.windows\.com|wns\.windows\.com|onesignal\.com|pusher\.com"
)


def offline_findings(name: str, text: str) -> list[str]:
    return [f"{name}: {what}" for what, pattern in OFFLINE.items() if pattern.search(text)]


def _console_files() -> list[Path]:
    return sorted(p for p in CONSOLE.rglob("*") if p.is_file() and p.suffix in TEXT and "__pycache__" not in p.parts)


def test_the_scan_sees_a_planted_service_worker_push_and_store() -> None:
    planted = {
        "sw.html": '<script>navigator.serviceWorker.register("/sw.js")</script>',
        "manifest.json": json.dumps({**phone.manifest(), "serviceworker": {"src": "/sw.js"}}),
        "push.js": "reg.pushManager.subscribe({userVisibleOnly: true})",
        "cache.js": "caches.open('pages').then(c => c.add('/studies/GZQO/week'))",
        "store.js": "localStorage.setItem('tb-form', note)",
        "worker.js": "importScripts('/static/sw-lib.js')",
    }
    for name, text in planted.items():
        assert offline_findings(name, text), name
    assert PUSH_HOSTS.search("https://web.push.apple.com/QGuQyavXutnMH...") and PUSH_HOSTS.search("fcm.googleapis.com")


def test_no_file_of_the_console_registers_a_worker_pushes_or_keeps_a_page() -> None:
    files = _console_files()
    assert len(files) > 100 and CONSOLE / "static" / "console.js" in files  # the scan reads the console
    found = [f for p in files for f in offline_findings(str(p.relative_to(ROOT)), p.read_text(encoding="utf-8"))]
    found += offline_findings("the web manifest", json.dumps(phone.manifest()))
    assert not found, found


def test_no_outside_push_service_is_named_anywhere_the_box_runs_from() -> None:
    hits = []
    for top in ("services", "libs", "deploy", "tools"):
        for p in (ROOT / top).rglob("*"):
            if (
                p.is_file()
                and p.suffix in (*TEXT, ".yaml", ".yml", ".toml", ".conf", ".sh", ".env", "")
                and ("__pycache__" not in p.parts)
            ):
                try:
                    text = p.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                if PUSH_HOSTS.search(text):
                    hits.append(str(p.relative_to(ROOT)))
    assert not hits, hits


def test_a_consent_is_recorded_as_facts_never_as_a_scan() -> None:
    """The consent record is dates, versions, initials and ticks (``tb_consent``); no form field takes a file, no page
    asks the camera, and the consent page's one file is the study's consent document to draft from (no image)."""
    rows = list(csv.DictReader((ROOT / "services" / "datacore" / "builtin" / "forms.csv").open(encoding="utf-8")))
    consent = {r["field_type"] for r in rows if r["form_name"] == "tb_consent"}
    assert consent and consent <= {"text", "radio", "notes"}, consent
    assert "file" not in {r["field_type"] for r in rows}
    templates = sorted((CONSOLE / "templates").glob("*.html"))
    assert not [p.name for p in templates if re.search(r"\bcapture(=|\s|>)", p.read_text(encoding="utf-8"))]
    for p in templates:
        if "consent" in p.name:
            for accept in re.findall(r'type="file"[^>]*accept="([^"]*)"', p.read_text(encoding="utf-8")):
                assert "image" not in accept and not re.search(r"\.(png|jpe?g|heic|tiff?|gif)\b", accept), p.name


def _directives(csp: str) -> dict[str, str]:
    return {d.split()[0]: " ".join(d.split()[1:]) for d in (x.strip() for x in csp.split(";")) if d}


def test_the_policy_forbids_workers_by_name() -> None:
    """The header the console sends, read directive by directive: ``worker-src 'none'`` is there, and removing it (as
    planted here) is seen."""
    from console import app as console_app

    assert _directives(console_app.CSP)["worker-src"] == "'none'"
    planted = console_app.CSP.replace("; worker-src 'none'", "")
    assert "worker-src" not in _directives(planted)


def test_every_page_says_no_store_and_no_worker(box: dict[str, Any]) -> None:
    """Every GET route of the console, as the administrator and as a coordinator (who opens patient-level pages), is
    answered with ``Cache-Control: no-store`` and a policy that forbids workers, whatever its status. Only the web
    manifest and the favicon, which hold nothing of a patient, may be cached (D-1222)."""
    users = box["users"]
    users.create("crc", "coordinator", "role-matrix-password-01", "crc@hospa.test")
    job_id = _ulid(990)
    _done_screen(box["backend"], job_id)
    routes = sorted({r.path for r in box["app"].routes if isinstance(r, APIRoute) and "GET" in (r.methods or ())})
    assert len(routes) > 150
    bad = []
    for name, pw in (("admin", None), ("crc", "role-matrix-password-01")):
        c, _ = login(box["app"], name, pw) if pw else login(box["app"])
        for path in routes:
            if path in ("/logout",):
                continue
            r = c.get(_fill(path, job_id), follow_redirects=False)
            if (
                r.headers.get("cache-control") != "no-store"
                or _directives(r.headers.get("content-security-policy", "")).get("worker-src") != "'none'"
            ):
                bad.append((name, path, r.status_code, r.headers.get("cache-control")))
    assert not bad, bad
    anon = TestClient(box["app"])
    for path in ("/static/console.js", "/static/console.css", "/login"):
        r = anon.get(path)
        assert r.headers["cache-control"] == "no-store" and "worker-src 'none'" in r.headers["content-security-policy"]
    for path in ("/manifest.webmanifest", "/favicon.ico"):
        r = anon.get(path)
        assert r.headers["cache-control"] == phone.CACHE and "worker-src 'none'" in r.headers["content-security-policy"]
    assert "serviceworker" not in anon.get("/manifest.webmanifest").text.lower()


@pytest.mark.skipif(not _node_playwright(), reason="Node Playwright is not installed")
def test_in_a_browser_no_service_worker_registers_on_a_console_page(box: dict[str, Any], tmp_path: Path) -> None:
    c, _ = login(box["app"])
    r = c.get("/help")
    page = tmp_path / "page.json"
    page.write_text(json.dumps({"html": r.text, "csp": r.headers["content-security-policy"]}), encoding="utf-8")
    out = subprocess.run([shutil.which("node") or "node", str(SCRIPT), str(page)], cwd=ROOT, capture_output=True,
                         text=True, timeout=300, check=False)  # fmt: skip
    assert out.returncode == 0, out.stdout + out.stderr
    got = json.loads(out.stdout.strip().splitlines()[-1])
    # planted: the same page without the console's policy, where a service worker does register; the check sees it
    assert got["planted_without_the_policy"] == {"register": "registered", "registrations": 1}, got
    console = got["the_console_page"]
    assert console["register"].startswith("refused"), console  # worker-src 'none' (and the hash-only script-src)
    assert console["registrations"] == 0 and console["refused_at_load"] == 0, console  # the page itself ran as usual
