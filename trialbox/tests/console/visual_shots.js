// 9k-17 (D-1377): the first screen of each page written by tests/console/visual_pages.py, in Chromium through Node
// Playwright (the browser the walks use; this script never installs one). One PNG per shot, of the window only (not
// the full page), light colour scheme, animations stopped and the caret hidden, so two runs of one tree on one
// machine give the same pixels. Run by tools/visual_regression.py:
//
//   node tests/console/visual_shots.js '{"dir": "<pages>", "out": "<pngs>", "shots": [{"name", "file", "width", "height"}]}'
//
// With "measure": true it also lists, per shot, every visible button and button-styled link smaller than 44 x 44 px
// (9k-3, D-1375: every target at least 44 px) in "small": {name: ["<text> <w>x<h>"]}.
//
// Prints one JSON line {shot, failed: {name: error}, small}; exit code 1 when a shot could not be taken.
"use strict";

const { chromium } = require("playwright");
const path = require("path");

(async () => {
  const args = JSON.parse(process.argv[2]);
  const failed = {};
  const small = {};
  let shot = 0;
  const browser = await chromium.launch();
  try {
    for (const s of args.shots) {
      const ctx = await browser.newContext({
        viewport: { width: s.width, height: s.height },
        deviceScaleFactor: 1,
        colorScheme: "light",
        reducedMotion: "reduce",
        locale: "en-US",
        timezoneId: "UTC",
      });
      try {
        const page = await ctx.newPage();
        await page.goto("file://" + path.join(args.dir, s.file), { waitUntil: "load" });
        await page.evaluate(() => document.fonts && document.fonts.ready);
        await page.screenshot({ path: path.join(args.out, s.name + ".png"), animations: "disabled", caret: "hide" });
        if (args.measure) {
          const found = await page.evaluate(() => {
            const out = [];
            for (const el of document.querySelectorAll("button, .button, input[type=submit]")) {
              const r = el.getBoundingClientRect();
              const cs = getComputedStyle(el);
              if (!r.width || !r.height || cs.visibility === "hidden" || cs.display === "none") continue;
              if (el.closest("[hidden], .sr")) continue;
              if (r.height < 43.5 || r.width < 43.5) {
                out.push(el.textContent.replace(/\s+/g, " ").trim().slice(0, 40) + " " + Math.round(r.width) + "x" + Math.round(r.height));
              }
            }
            return out;
          });
          if (found.length) small[s.name] = found;
        }
        shot += 1;
      } catch (e) {
        failed[s.name] = String(e && e.message ? e.message : e).slice(0, 300);
      } finally {
        await ctx.close();
      }
    }
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify({ shot, failed, small }));
  process.exit(Object.keys(failed).length ? 1 : 0);
})().catch((e) => {
  console.log(JSON.stringify({ shot: 0, failed: { "*": String(e && e.message ? e.message : e).slice(0, 300) } }));
  process.exit(1);
});
