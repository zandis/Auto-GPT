// T-684 (UX-023, UX-025, UX-037): the console's layout in a real browser, in ja and zh-TW (and en), on a desktop and
// a phone. Driven by tests/console/test_cjk_layout.py, which renders the pages with the in-process box and writes
// them with console.css into one folder; this script opens each file in Node Playwright with the preinstalled
// Chromium (it never runs `playwright install`) and measures:
//
//   * no pill, state badge or button breaks a label so that a line holds one character (確/認/待/ち, 退/回);
//   * no CJK pill or state badge (one word, no space) wraps at all;
//   * the page does not scroll sideways;
//   * every link and button of the patient panel starts inside the window (the clipped "ask the doctor" link);
//   * on the full patient page the mark bar is on the first screen (sticky at the bottom);
//   * on the week page the first patient row starts on the first screen of a desktop, and the worklist fits its box.
//
//   node tests/console/cjk_layout.js '{"dir": "...", "pages": [{"file", "width", "height", "checks": [...]}], "shots": ""}'
//
// Prints one JSON line {checks, failed, results}; exit code 1 on any failed check.
"use strict";

const { chromium } = require("playwright");
const path = require("path");

const SELECTORS = ".pill, .state, button, .button, .markbar a, nav:not(.rail) a, .rail a > span:first-child";

async function measure(page) {
  return page.evaluate((sel) => {
    const out = { oneChar: [], wrapped: [], bad: [] };
    const visible = (el) => {
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && cs.display !== "none";
    };
    // lines of an element's own text: one entry per line box, holding the characters on it
    const lines = (el) => {
      const rows = [];
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      const range = document.createRange();
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        const s = n.textContent;
        for (let i = 0; i < s.length; i++) {
          if (/\s/.test(s[i])) continue;
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
      }
      return rows;
    };
    for (const el of document.querySelectorAll(sel)) {
      if (!visible(el)) continue;
      const text = el.textContent.replace(/\s+/g, " ").trim();
      if ([...text.replace(/\s/g, "")].length < 2) continue;
      const rows = lines(el);
      if (rows.length > 1 && rows.some((r) => [...r.text].length === 1)) out.oneChar.push(text);
      // a CJK pill (no space in it) is one word and never wraps; an English one may wrap at a space
      if (rows.length > 1 && (el.matches(".pill") || el.matches(".state")) && !/\s/.test(text)) out.wrapped.push(text);
    }
    out.scrollWidth = document.documentElement.scrollWidth;
    out.innerWidth = window.innerWidth;
    out.innerHeight = window.innerHeight;
    for (const el of document.querySelectorAll("#chart a, #chart button, [data-testid=ask-doctor]")) {
      if (!visible(el)) continue;
      const r = el.getBoundingClientRect();
      if (r.left < 0 || r.right > window.innerWidth + 1) out.bad.push(el.textContent.trim().slice(0, 40));
    }
    const bar = document.querySelector("[data-testid=markbar]");
    if (bar && visible(bar)) {
      const r = bar.getBoundingClientRect();
      out.markbar = { top: r.top, bottom: r.bottom };
    }
    const row = document.querySelector("table.worklist tbody tr");
    if (row) out.firstRow = row.getBoundingClientRect().top;
    const box = document.querySelector(".scroll:has(> table.worklist)");
    if (box) out.worklist = { scrollWidth: box.scrollWidth, clientWidth: box.clientWidth };
    return out;
  }, SELECTORS);
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
      if (args.shots) {
        // a screenshot is for the reader; a capture error is not a layout failure
        await page.screenshot({ path: path.join(args.shots, p.file.replace(/\.html$/, `-${p.width}.png`)) }).catch(() => {});
      }
      const m = await measure(page);
      const name = `${p.file}@${p.width}`;
      check(m.oneChar.length === 0, `${name}: one character on a line in ${JSON.stringify(m.oneChar)}`);
      check(m.wrapped.length === 0, `${name}: a pill wraps: ${JSON.stringify(m.wrapped)}`);
      check(m.scrollWidth <= m.innerWidth, `${name}: the page scrolls sideways (${m.scrollWidth} > ${m.innerWidth})`);
      check(m.bad.length === 0, `${name}: clipped at the window edge: ${JSON.stringify(m.bad)}`);
      for (const c of p.checks || []) {
        if (c === "markbar-first-screen") {
          check(m.markbar && m.markbar.bottom <= m.innerHeight + 1 && m.markbar.top >= 0,
            `${name}: the mark bar is not on the first screen (${JSON.stringify(m.markbar)})`);
        } else if (c === "worklist-fits") {
          check(m.worklist && m.worklist.scrollWidth <= m.worklist.clientWidth + 1,
            `${name}: the worklist scrolls sideways inside its box (${JSON.stringify(m.worklist)})`);
        } else if (c === "row-first-screen") {
          check(m.firstRow !== undefined && m.firstRow < m.innerHeight * 0.6,
            `${name}: the first patient row starts at y=${m.firstRow} of ${m.innerHeight}`);
        }
      }
      results.push({ file: p.file, width: p.width, firstRow: m.firstRow, markbar: m.markbar, oneChar: m.oneChar });
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
