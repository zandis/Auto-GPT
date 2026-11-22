// 10F-1 (D-1387, the review's M-5 and L-6): a person's chosen text size and colour mode in a real browser. Driven by
// tests/console/test_prefs_layout_10f1.py, which renders the pages with the in-process box (the person's own
// preferences set) and writes them with console.css into one folder; this script opens each file in Node Playwright
// with the preinstalled Chromium (never `playwright install`) and measures:
//
//   * the page never scrolls sideways;
//   * a wide table that does not fit its box at this text size scrolls inside its .scroll box: the box clips and
//     scrolls (overflow-x auto or scroll), is focusable (tabindex 0) and shows a focus ring of at least 2 px;
//   * "print-light": printed, a card in a dark mode has the paper's background (white).
//
//   node tests/console/prefs_layout_10f1.js '{"dir": "...", "pages": [{"file", "width", "height", "lang", "checks"}]}'
//
// Prints one JSON line {checks, failed, results}; exit code 1 on any failed check.
"use strict";

const { chromium } = require("playwright");
const path = require("path");

async function measure(page) {
  return page.evaluate(() => {
    const out = { scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth, boxes: [] };
    for (const el of document.querySelectorAll(".scroll")) {
      const cs = getComputedStyle(el);
      if (cs.display === "none") continue;
      const over = el.scrollWidth > el.clientWidth + 1;
      el.focus();
      const ring = getComputedStyle(el);
      out.boxes.push({
        over,
        scrollWidth: el.scrollWidth,
        clientWidth: el.clientWidth,
        overflowX: cs.overflowX,
        tabindex: el.getAttribute("tabindex"),
        outline: ring.outlineStyle === "none" ? 0 : parseFloat(ring.outlineWidth),
        right: el.getBoundingClientRect().right,
      });
      el.blur();
    }
    return out;
  });
}

(async () => {
  const args = JSON.parse(process.argv[2]);
  const browser = await chromium.launch();
  const results = [];
  let checks = 0;
  let failed = 0;
  const check = (ok, what) => {
    checks += 1;
    if (!ok) {
      failed += 1;
      console.error("FAIL: " + what);
    }
    return ok;
  };
  try {
    for (const p of args.pages) {
      const ctx = await browser.newContext({ viewport: { width: p.width, height: p.height }, locale: p.lang });
      const page = await ctx.newPage();
      await page.goto("file://" + path.join(args.dir, p.file), { waitUntil: "load" });
      const name = `${p.file}@${p.width}`;
      if ((p.checks || []).includes("print-light")) {
        await page.emulateMedia({ media: "print" });
        const bg = await page.evaluate(() => {
          const c = document.querySelector(".card");
          return c ? getComputedStyle(c).backgroundColor : "";
        });
        check(bg === "rgb(255, 255, 255)", `${name}: a printed card's background is ${bg}`);
        results.push({ file: p.file, width: p.width, print: bg });
        await ctx.close();
        continue;
      }
      const m = await measure(page);
      check(m.scrollWidth <= m.innerWidth, `${name}: the page scrolls sideways (${m.scrollWidth} > ${m.innerWidth})`);
      for (const b of m.boxes) {
        check(b.right <= m.innerWidth + 1, `${name}: a table box ends outside the window (${JSON.stringify(b)})`);
        if (!b.over) continue;
        check(["auto", "scroll"].includes(b.overflowX), `${name}: a wide table's box does not scroll (${JSON.stringify(b)})`);
        check(b.tabindex === "0", `${name}: a wide table's box cannot take focus (${JSON.stringify(b)})`);
        check(b.outline >= 2, `${name}: a wide table's box shows no focus ring (${JSON.stringify(b)})`);
      }
      if ((p.checks || []).includes("has-wide-table")) {
        check(m.boxes.some((b) => b.over), `${name}: the table was expected not to fit its box at this size`);
      }
      results.push({ file: p.file, width: p.width, boxes: m.boxes, scrollWidth: m.scrollWidth });
      await ctx.close();
    }
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify({ checks, failed, results }));
  process.exitCode = failed ? 1 : 0;
})().catch((e) => {
  console.error(e);
  console.log(JSON.stringify({ checks: 0, failed: 1, error: String(e) }));
  process.exitCode = 1;
});
