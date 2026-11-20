// 9k-6b (D-1389): data-guard in Chromium through Node Playwright (the preinstalled browser; never installed here).
// Driven by tests/console/test_form_errors_9k6b.py, which writes the pages and console.css into one folder (the page holds console.js).
//
//   node tests/console/form_guard_9k6b.js '{"dir": "<pages>", "pages": [{"name", "file", "expect": bool, "type": "<selector>"|null}]}'
//
// For each page: click in it type into `type` when given, then
// send it a cancelable beforeunload event: the page handler must cancel it (the browser would ask) exactly when
// `expect` says so.
// A page shown again after a refused post must ask (its typed values are not saved); a fresh page must not ask
// until a guarded field is edited. Prints one JSON line {checked, failed: {name: what}}.
"use strict";

const { chromium } = require("playwright");
const path = require("path");

(async () => {
  const args = JSON.parse(process.argv[2]);
  const failed = {};
  let checked = 0;
  const browser = await chromium.launch();
  try {
    for (const s of args.pages) {
      const ctx = await browser.newContext({ viewport: { width: 1280, height: 860 }, colorScheme: "light" });
      try {
        const page = await ctx.newPage();
        await page.goto("file://" + path.join(args.dir, s.file), { waitUntil: "load" });
        await page.click("body", { position: { x: 5, y: 5 } });
        if (s.type) await page.fill(s.type, "x");
        // what leaving the page asks of the page's own handler: a beforeunload event it cancels is "ask first"
        const asked = await page.evaluate(() => {
          const e = new Event("beforeunload", { cancelable: true });
          window.dispatchEvent(e);
          return e.defaultPrevented;
        });
        if (asked !== s.expect) throw new Error("asked=" + asked + ", expected " + s.expect);
        checked += 1;
      } catch (e) {
        failed[s.name] = String(e && e.message ? e.message : e).slice(0, 300);
      } finally {
        await ctx.close();
      }
    }
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify({ checked, failed }));
  process.exit(Object.keys(failed).length ? 1 : 0);
})().catch((e) => {
  console.log(JSON.stringify({ checked: 0, failed: { "*": String(e && e.message ? e.message : e).slice(0, 300) } }));
  process.exit(1);
});
