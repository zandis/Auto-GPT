"""Capture trialgpt.app (Foundation 29) results for the public synthetic NCBI cohort patients by driving its public
web interface with Playwright, the way a clinician would use it.

    python -m trialgpt_local.h2h.capture --cohort sigir --patients 10 [--delay 60] [--select first]

Rules built in:
* only patients of the public synthetic cohorts (SIGIR, TREC 2021/2022) can be sent — never CGRD or any real data;
* one patient at a time with ``--delay`` seconds between patients (default 60);
* resumable: a patient already captured is skipped;
* everything the app returned is kept as evidence: its own API responses (``extractEventsFromFile``,
  ``searchTrials``), a results screenshot and the choices made for the user.

The app's flow (2026-10): "How does it work" dialog (Begin) -> privacy notice (I agree) -> note in the search box ->
"results are AI-generated" notice (Yes) -> "Who are you?" (healthcare professional) -> "Help us be accurate": choose
the main diagnosis among the extracted conditions and a preferred country -> Search -> ranked trials. The diagnosis
choice is a human step; ``--select`` fixes it reproducibly: ``first`` (default) = the app's own first-listed
condition, ``all`` = every extracted condition.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from trialgpt_local import datasets
from trialgpt_local.config import settings

if TYPE_CHECKING:
    from playwright.async_api import ProxySettings

URL = "https://trialgpt.app/"
CHROME = os.environ.get("TG_CHROME", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")


def out_dir() -> Path:
    d = settings().results_dir / "h2h" / "trialgpt_app"
    d.mkdir(parents=True, exist_ok=True)
    return d


async def _capture_one(page: Any, note: str, select: str, country: str | None) -> dict[str, Any]:
    api: dict[str, Any] = {}

    async def on_resp(r: Any) -> None:
        if "/api/" in r.url and r.request.method == "POST":
            name = r.url.split("/api/", 1)[1].split("?")[0]
            try:
                body = await r.json()
            except Exception:
                body = None
            api[name] = {"status": r.status, "request": r.request.post_data, "response": body}

    page.on("response", lambda r: asyncio.ensure_future(on_resp(r)))
    await page.goto(URL, wait_until="networkidle", timeout=120000)
    # onboarding dialog and privacy notice (both are DOM-clicked: the dialog's scroll container intercepts pointers)
    await page.evaluate(
        "() => { const b = [...document.querySelectorAll('ngb-modal-window button')]"
        ".find(b => b.innerText.trim() === 'Begin'); if (b) b.click(); }"
    )
    await page.wait_for_timeout(1500)
    agree = page.get_by_role("button", name="I agree")
    if await agree.count():
        await agree.first.click()
        await page.wait_for_timeout(1000)
    await page.locator("input.search-disease-input").fill(note)
    await page.locator("button.search-button").first.click()
    yes = page.get_by_role("button", name="Yes", exact=True)
    await yes.first.wait_for(timeout=60000)
    await yes.first.click()
    hcp = page.get_by_text("I am a healthcare professional")
    await hcp.first.wait_for(timeout=180000)
    await hcp.first.click()
    await page.get_by_text("Help us be accurate").wait_for(timeout=120000)
    pills = page.locator("span.pill")
    names = [n.strip() for n in await pills.all_inner_texts()]
    diseases = (api.get("extractEventsFromFile", {}).get("response") or {}).get("events", {}).get("conditions", [])
    disease_names = [d.get("value", "") for d in diseases]
    chosen = disease_names[:1] if select == "first" else disease_names
    for name in chosen:
        await page.locator("span.pill", has_text=name).first.click()
        await page.wait_for_timeout(300)
    if country:
        await page.locator("select").first.select_option(label=country)
    selected_country = await page.locator("select").first.evaluate("e => e.options[e.selectedIndex].text")
    t0 = time.perf_counter()
    await page.get_by_role("button", name="Search").click()
    for _ in range(240):  # up to 4 minutes for the search
        if "searchTrials" in api:
            break
        await page.wait_for_timeout(1000)
    secs = time.perf_counter() - t0
    await page.wait_for_timeout(4000)
    shot = await page.screenshot(full_page=True)
    trials = ((api.get("searchTrials") or {}).get("response") or {}).get("clinicalTrials") or []
    return {
        "ranked": [t.get("NCTId") for t in trials if t.get("NCTId")],
        "trials": trials,
        "selected_conditions": chosen,
        "offered_pills": names,
        "country": selected_country,
        "search_seconds": round(secs, 1),
        "api": api,
        "_screenshot": shot,
    }


async def run(cohort: str, patients: int | None, delay: float, select: str, country: str | None) -> None:
    from playwright.async_api import async_playwright

    co = datasets.load(cohort)  # public synthetic cohorts only: the patient list comes from here, not from input
    pids = [e["patient_id"] for e in co.retrieved]
    if patients:
        import random

        pids = sorted(random.Random(13).sample(pids, min(patients, len(pids))))
    d = out_dir()
    async with async_playwright() as p:
        proxy: ProxySettings | None = {"server": os.environ["HTTPS_PROXY"]} if os.environ.get("HTTPS_PROXY") else None
        browser = await p.chromium.launch(
            executable_path=CHROME if Path(CHROME).exists() else None, proxy=proxy, args=["--no-sandbox"]
        )
        for i, pid in enumerate(pids):
            target = d / f"{pid}.json"
            if target.exists():
                continue
            ctx = await browser.new_context(viewport={"width": 1280, "height": 900}, locale="en-US")
            page = await ctx.new_page()
            started = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            try:
                res = await _capture_one(page, co.queries[pid], select, country)
                (d / f"{pid}.png").write_bytes(res.pop("_screenshot"))
                bundle = await page.evaluate(
                    "() => [...document.scripts].map(s => s.src).filter(s => s.includes('main-'))"
                )
                rec = {
                    "patient_id": pid,
                    "cohort": cohort,
                    "captured_at": started,
                    "select_policy": select,
                    "app_bundle": bundle,
                    "note_sha256": hashlib.sha256(co.queries[pid].encode()).hexdigest(),
                    **res,
                }
                target.write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
                print(
                    f"[{i + 1}/{len(pids)}] {pid}: {len(res['ranked'])} trials for {res['selected_conditions']} "
                    f"({res['search_seconds']}s)",
                    flush=True,
                )
            except Exception as exc:
                (d / f"{pid}.error.txt").write_text(f"{started} {type(exc).__name__}: {exc}\n", encoding="utf-8")
                print(f"[{i + 1}/{len(pids)}] {pid}: FAILED {type(exc).__name__}: {str(exc)[:200]}", flush=True)
            finally:
                await ctx.close()
            if i < len(pids) - 1:
                await asyncio.sleep(delay)
        await browser.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m trialgpt_local.h2h.capture")
    ap.add_argument("--cohort", choices=datasets.COHORTS, required=True)
    ap.add_argument("--patients", type=int, help="seeded sample size (default: all patients of the cohort)")
    ap.add_argument("--delay", type=float, default=60.0, help="seconds between patients (be gentle: default 60)")
    ap.add_argument("--select", choices=("first", "all"), default="first", help="which extracted conditions to select")
    ap.add_argument("--country", help="preferred country label in the app (default: the app's own default)")
    a = ap.parse_args(argv)
    if a.delay < 20:
        ap.error("--delay below 20 s is not allowed: this is a free public service")
    asyncio.run(run(a.cohort, a.patients, a.delay, a.select, a.country))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
