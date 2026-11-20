// 9k-10 (D-1385): the phase strip in a real browser. Driven by tests/console/test_phase_strip_9k10.py, which writes the
// pages with console.css into one folder. For each page and each strip on it: the cells fall on at most two rows, the
// page does not scroll sideways, no cell holds a line of one character, and no cell is wider than the strip.
//   node tests/console/phase_strip.js '{"dir": "...", "pages": [{"file", "width", "height", "lang"}]}'
"use strict";
const { chromium } = require("playwright");
const path = require("path");

(async () => {
  const args = JSON.parse(process.argv[2]);
  const browser = await chromium.launch();
  const failures = [];
  const seen = [];
  try {
    for (const p of args.pages) {
      const ctx = await browser.newContext({ viewport: { width: p.width, height: p.height }, locale: p.lang });
      const page = await ctx.newPage();
      await page.goto("file://" + path.join(args.dir, p.file), { waitUntil: "load" });
      const m = await page.evaluate(() => {
        const strips = [...document.querySelectorAll("ol.ps")].filter((o) => o.getBoundingClientRect().width > 0);
        return {
          scroll: document.documentElement.scrollWidth - window.innerWidth,
          strips: strips.map((o) => {
            const box = o.getBoundingClientRect();
            const cells = [...o.children].map((li) => li.getBoundingClientRect());
            const rows = new Set(cells.map((r) => Math.round(r.top)));
            const lone = [];
            for (const li of o.children) {
              const range = document.createRange();
              const rows2 = [];
              const w = document.createTreeWalker(li.querySelector("b"), NodeFilter.SHOW_TEXT);
              for (let n = w.nextNode(); n; n = w.nextNode()) {
                for (let i = 0; i < n.textContent.length; i++) {
                  if (/\s/.test(n.textContent[i])) continue;
                  range.setStart(n, i);
                  range.setEnd(n, i + 1);
                  const r = range.getBoundingClientRect();
                  if (!r.width) continue;
                  let row = rows2.find((x) => Math.abs(x.top - r.top) < r.height / 2);
                  if (!row) rows2.push((row = { top: r.top, n: 0 }));
                  row.n += 1;
                }
              }
              if (rows2.length > 1 && rows2.some((x) => x.n === 1)) lone.push(li.textContent.trim());
            }
            return {
              rows: rows.size,
              count: cells.length,
              wide: cells.filter((r) => r.right > box.right + 1 || r.left < box.left - 1).length,
              lone,
              current: o.querySelectorAll('[aria-current="step"]').length,
            };
          }),
        };
      });
      const name = `${p.file}@${p.width}`;
      if (!m.strips.length) failures.push(`${name}: no strip on the page`);
      if (m.scroll > 0) failures.push(`${name}: the page scrolls sideways by ${m.scroll}px`);
      for (const s of m.strips) {
        if (s.rows > 2) failures.push(`${name}: the strip of ${s.count} takes ${s.rows} rows`);
        if (s.wide) failures.push(`${name}: ${s.wide} cell(s) outside the strip`);
        if (s.lone.length) failures.push(`${name}: one character on a line in ${JSON.stringify(s.lone)}`);
        if (s.current !== 1) failures.push(`${name}: ${s.current} current items`);
      }
      seen.push({ name, strips: m.strips.map((s) => [s.count, s.rows]) });
      await ctx.close();
    }
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify({ failed: failures.length, failures, seen }));
  process.exitCode = failures.length ? 1 : 0;
})().catch((e) => {
  console.error(e);
  console.log(JSON.stringify({ failed: 1, failures: [String(e)], seen: [] }));
  process.exitCode = 1;
});
