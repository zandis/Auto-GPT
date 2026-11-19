// 10C-13 (D-1229): a printed page's dates in the "both" form (2026年（令和8年）10月5日) at a phone's width. Driven by
// tests/console/test_printed_dates_layout.py, which writes the pages into one folder; this script opens each file in
// Node Playwright with the preinstalled Chromium (it never runs `playwright install`) and measures:
//
//   * how wide the page is (scrollWidth): the test compares it with the same page with Western dates;
//   * every occurrence of each given date text is on the page, and no line of it holds one character.
//
//   node tests/console/printed_dates_layout.js '{"dir": "...", "pages": [{"file", "width", "height", "dates": [...]}]}'
//
// Prints one JSON line {checks, failed, results}; exit code 1 on any failed check.
"use strict";

const { chromium } = require("playwright");
const path = require("path");

async function measure(page, dates) {
  return page.evaluate((dates) => {
    const out = { scrollWidth: document.documentElement.scrollWidth, found: {}, oneChar: [] };
    const range = document.createRange();
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const s = n.textContent;
      for (const d of dates) {
        for (let at = s.indexOf(d); at >= 0; at = s.indexOf(d, at + d.length)) {
          out.found[d] = (out.found[d] || 0) + 1;
          const rows = [];
          for (let i = at; i < at + d.length; i++) {
            range.setStart(n, i);
            range.setEnd(n, i + 1);
            const r = range.getBoundingClientRect();
            if (!r.width && !r.height) continue;
            let row = rows.find((x) => Math.abs(x.top - r.top) < r.height / 2);
            if (!row) {
              row = { top: r.top, text: "" };
              rows.push(row);
            }
            row.text += s[i];
          }
          if (rows.length > 1 && rows.some((r) => [...r.text].length === 1)) out.oneChar.push(rows.map((r) => r.text));
        }
      }
    }
    return out;
  }, dates);
}

(async () => {
  const args = JSON.parse(process.argv[2]);
  const browser = await chromium.launch();
  const results = [];
  let failed = 0;
  let checks = 0;
  try {
    for (const p of args.pages) {
      const ctx = await browser.newContext({ viewport: { width: p.width, height: p.height }, deviceScaleFactor: 1 });
      const page = await ctx.newPage();
      await page.goto("file://" + path.join(args.dir, p.file));
      const m = await measure(page, p.dates);
      const problems = [];
      for (const d of p.dates) if (!m.found[d]) problems.push("not on the page: " + d);
      for (const rows of m.oneChar) problems.push("a line of one character: " + JSON.stringify(rows));
      checks += p.dates.length;
      failed += problems.length;
      results.push({ file: p.file, width: p.width, scrollWidth: m.scrollWidth, problems });
      await ctx.close();
    }
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify({ checks, failed, results }));
  process.exit(failed ? 1 : 0);
})();
