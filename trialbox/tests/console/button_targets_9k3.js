// 9k-3 (D-1375): every visible button and button-styled link is at least 44 x 44 px, measured in Chromium through
// Node Playwright (the preinstalled browser; this script never installs one). Driven by
// tests/console/test_button_targets_9k3.py, which writes the pages and console.css into one folder.
//
//   node tests/console/button_targets_9k3.js '{"dir": "<pages>", "pages": [{"name", "file", "width", "height"}]}'
//
// Prints one JSON line {measured, failed: {name: error}, small: {name: ["<text> <w>x<h>"]}}.
"use strict";

const { chromium } = require("playwright");
const path = require("path");

(async () => {
  const args = JSON.parse(process.argv[2]);
  const failed = {};
  const small = {};
  let measured = 0;
  const browser = await chromium.launch();
  try {
    for (const s of args.pages) {
      const ctx = await browser.newContext({ viewport: { width: s.width, height: s.height }, colorScheme: "light" });
      try {
        const page = await ctx.newPage();
        await page.goto("file://" + path.join(args.dir, s.file), { waitUntil: "load" });
        const found = await page.evaluate(() => {
          const out = [];
          let n = 0;
          for (const el of document.querySelectorAll("button, .button, input[type=submit]")) {
            const r = el.getBoundingClientRect();
            const cs = getComputedStyle(el);
            if (!r.width || !r.height || cs.visibility === "hidden" || cs.display === "none") continue;
            if (el.closest("[hidden], .sr")) continue;
            n += 1;
            if (r.height < 43.5 || r.width < 43.5) {
              out.push(el.textContent.replace(/\s+/g, " ").trim().slice(0, 40) + " " + Math.round(r.width) + "x" + Math.round(r.height));
            }
          }
          return { out, n };
        });
        measured += found.n;
        if (found.out.length) small[s.name] = found.out;
      } catch (e) {
        failed[s.name] = String(e && e.message ? e.message : e).slice(0, 300);
      } finally {
        await ctx.close();
      }
    }
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify({ measured, failed, small }));
  process.exit(Object.keys(failed).length ? 1 : 0);
})().catch((e) => {
  console.log(JSON.stringify({ measured: 0, failed: { "*": String(e && e.message ? e.message : e).slice(0, 300) }, small: {} }));
  process.exit(1);
});
