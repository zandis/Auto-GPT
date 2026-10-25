// Browser smoke test of the TrialBox Test Bench (docs/HANDOFF.md §5), driven by tests/testbench/test_testbench_browser.py.
//
//   node tests/testbench/browser_smoke.js http://127.0.0.1:8765 [screenshot-dir]
//
// Opens every page and checks the banner, then clicks "Run end to end" on the synthetic site A fixture and waits for
// PASS. Uses the preinstalled Chromium (PLAYWRIGHT_BROWSERS_PATH); never runs `playwright install`.
"use strict";

const { chromium } = require("playwright");
const path = require("path");

const BANNER = "TEST BENCH: synthetic and open data only, not a clinical tool";
const PAGES = ["/", "/run", "/dataplat", "/llm", "/guard", "/recall", "/match"];

function fail(msg) {
  console.error("FAIL: " + msg);
  process.exitCode = 1;
}

async function main() {
  const base = process.argv[2] || "http://127.0.0.1:8765";
  const shots = process.argv[3] || "";
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  try {
    for (const p of PAGES) {
      const resp = await page.goto(base + p, { waitUntil: "load" });
      if (!resp || resp.status() !== 200) fail(`${p}: HTTP ${resp && resp.status()}`);
      const banner = (await page.locator("[data-testid=banner]").innerText()).trim();
      if (banner !== BANNER) fail(`${p}: banner is ${JSON.stringify(banner)}`);
      console.log(`ok page ${p}`);
    }
    // htmx loaded from the vendored file (no CDN)
    await page.goto(base + "/run", { waitUntil: "load" });
    const hasHtmx = await page.evaluate(() => typeof window.htmx === "object" && !!window.htmx.version);
    if (!hasHtmx) fail("htmx is not loaded");
    if (shots) {
      await page.goto(base + "/", { waitUntil: "load" });
      await page.screenshot({ path: path.join(shots, "testbench-home.png"), fullPage: true });
      await page.goto(base + "/run", { waitUntil: "load" });
    }
    // a finished job from an earlier run may already be shown: wait for the new job's panel, then its result
    const before = await page.evaluate(() => {
      const el = document.querySelector("#run-output [data-job]");
      return el ? el.getAttribute("data-job") : null;
    });
    await page.click("[data-testid=run-synthea_site_a]");
    await page.waitForFunction(
      (prev) => {
        const el = document.querySelector("#run-output [data-job]");
        return !!el && el.getAttribute("data-job") !== prev;
      },
      before,
      { timeout: 60000 },
    );
    const jid = await page.locator("#run-output [data-job]").getAttribute("data-job");
    console.log(`job ${jid} started`);
    const status = page.locator(`#job-${jid} [data-testid=result-status]`);
    await status.waitFor({ timeout: 600000 });
    const text = (await status.innerText()).trim();
    if (text !== "PASS") fail(`Run end to end shows ${JSON.stringify(text)}`);
    else console.log("ok run end to end: PASS");
    const log = await page.locator(`#job-${jid} [data-testid=log]`).innerText();
    if (!log.includes("finished")) fail("live log did not stream to the end");
    const banner = (await page.locator("[data-testid=banner]").innerText()).trim();
    if (banner !== BANNER) fail("banner missing after the run");
    if (shots) {
      await page.screenshot({ path: path.join(shots, "testbench-run-e2e.png"), fullPage: true });
    }
    // the PHI guard page redacts through htmx
    await page.goto(base + "/guard", { waitUntil: "load" });
    await page.click("[data-testid=guard-run]");
    const red = await page.locator("[data-testid=redacted]").innerText({ timeout: 30000 });
    if (!red.includes("[TW_NATIONAL_ID]")) fail(`guard did not redact: ${red}`);
    else console.log("ok guard redaction");
    if (errors.length) fail("page errors: " + errors.join(" | "));
  } finally {
    await browser.close();
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
