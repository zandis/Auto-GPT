// 9k-6a (D-1376): the keyboard on a page shown again after a failed POST, measured in Chromium through Node
// Playwright (the preinstalled browser; this script never installs one). Driven by
// tests/console/test_form_errors_9k6a.py, which writes the pages and console.css into one folder.
//
//   node tests/console/form_errors_keys_9k6a.js '{"dir": "<pages>", "pages": [{"name", "file", "fields": [ids]}]}'
//
// For each page: when it has loaded, focus is on the error summary (autofocus, no script of ours); one Tab reaches
// the summary's first link; Enter on each link moves focus to its field (the id the link names), in order.
// Prints one JSON line {checked, failed: {name: what}}.
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
        const url = "file://" + path.join(args.dir, s.file);
        await page.goto(url, { waitUntil: "load" });
        const active = () => page.evaluate(() => {
          const a = document.activeElement;
          return a ? (a.id || (a.classList.contains("fm-summary") ? "fm-summary" : a.tagName + ":" + (a.getAttribute("href") || ""))) : "";
        });
        // autofocus is applied at the next rendering update after load, not at load itself: wait for it (5 s)
        const focused = () => page.waitForFunction(() => {
          const a = document.activeElement;
          return !!a && a.classList.contains("fm-summary");
        }, null, { timeout: 5000 }).catch(() => null);
        await focused();
        let got = await active();
        if (got !== "fm-summary") throw new Error("on load the focus is on " + got + ", not the summary");
        await page.keyboard.press("Tab");
        got = await active();
        if (got !== "A:#" + s.fields[0]) throw new Error("Tab from the summary reached " + got);
        for (let i = 0; i < s.fields.length; i++) {
          await page.goto(url, { waitUntil: "load" });
          await focused();
          if ((await active()) !== "fm-summary") throw new Error("after a reload the focus is not on the summary");
          for (let k = 0; k <= i; k++) await page.keyboard.press("Tab");
          got = await active();
          if (got !== "A:#" + s.fields[i]) throw new Error("Tab " + (i + 1) + " reached " + got);
          await page.keyboard.press("Enter");
          await page.waitForTimeout(50);
          got = await active();
          if (got !== s.fields[i]) throw new Error("the link to " + s.fields[i] + " moved focus to " + got);
        }
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
