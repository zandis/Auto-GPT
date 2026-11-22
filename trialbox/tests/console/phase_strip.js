// 9k-10 (D-1385): the phase strip in a real browser. Driven by tests/console/test_phase_strip_9k10.py, which writes the
// pages with console.css into one folder. For each page and each strip on it: the cells fall on at most two columns of rows on a phone (two on a desktop), the
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
                  if (/\s/.test(n.textContent[i]) || n.parentElement.closest(".sr")) continue;
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
            // every label whole: the cell and its text neither scroll nor spill (no clipping, no ellipsis)
            const cut = [];
            for (const li of o.children) {
              const lr = li.getBoundingClientRect();
              for (const el of li.querySelectorAll("b, .who")) {
                const er = el.getBoundingClientRect();
                if (!er.width) continue;
                // the visible text only: the screen-reader words (.sr) sit off to the side by design
                const r2 = document.createRange();
                let first = null;
                let last = null;
                const w2 = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
                for (let n = w2.nextNode(); n; n = w2.nextNode()) {
                  if (n.parentElement.closest(".sr") || !n.textContent.trim()) continue;
                  first = first || n;
                  last = n;
                }
                if (!first) continue;
                r2.setStart(first, 0);
                r2.setEnd(last, last.textContent.length);
                const tr = r2.getBoundingClientRect();
                if (tr.right > lr.right + 0.5 || tr.left < lr.left - 0.5 || tr.bottom > lr.bottom + 0.5) cut.push(li.textContent.trim());
              }
              if (li.scrollWidth > li.clientWidth || li.scrollHeight > li.clientHeight) cut.push("scroll: " + li.textContent.trim());
            }
            // the marks per state, from computed style: a tick only on done, an underline only on current
            const marks = [...o.children].map((li) => {
              const cs = getComputedStyle(li);
              const tick = getComputedStyle(li.querySelector("b"), "::before").content;
              return {
                state: li.dataset.state,
                tick: /✓/.test(tick),
                underline: cs.boxShadow !== "none" && /inset/.test(cs.boxShadow),
                dashed: cs.backgroundImage.includes("gradient"),
                fill: cs.backgroundColor,
              };
            });
            return {
              cut,
              marks,
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
        if (p.large) {
          // enlarged text on a phone: one column, one item per row (a row limit of n alone could never fail)
          if (s.rows !== s.count) failures.push(`${name}: the strip of ${s.count} takes ${s.rows} rows at enlarged text (one column: ${s.count})`);
        } else {
          const maxRows = p.width <= 760 ? Math.ceil(s.count / 2) : 2;
          if (s.rows > maxRows) failures.push(`${name}: the strip of ${s.count} takes ${s.rows} rows (at most ${maxRows})`);
        }
        if (s.wide) failures.push(`${name}: ${s.wide} cell(s) outside the strip`);
        if (s.lone.length) failures.push(`${name}: one character on a line in ${JSON.stringify(s.lone)}`);
        if (s.cut.length) failures.push(`${name}: a label is cut: ${JSON.stringify(s.cut)}`);
        for (const mk of s.marks) {
          if (mk.tick !== (mk.state === "done")) failures.push(`${name}: tick on ${mk.state} item is ${mk.tick}`);
          if (mk.underline !== (mk.state === "current")) failures.push(`${name}: underline on ${mk.state} item is ${mk.underline}`);
          if (mk.dashed !== (mk.state === "off")) failures.push(`${name}: dashed line on ${mk.state} item is ${mk.dashed}`);
        }
        if (s.current !== 1) failures.push(`${name}: ${s.current} current items`);
      }
      if (p.forced) {
        await page.emulateMedia({ forcedColors: "active" });
        const f = await page.evaluate(() => [...document.querySelectorAll('ol.ps li[aria-current="step"]')].map((li) => getComputedStyle(li).borderBottomWidth));
        if (!f.length || f.some((w) => parseFloat(w) < 3)) failures.push(`${name}: in forced colours the current item has no line (${f})`);
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
