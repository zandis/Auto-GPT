// One screenshot per stage of tools/complete_run.py (TB-PLAN-04 step 9, D-139): sign in to the console as the role
// that does the stage, in the run's language, open the page that shows the stage's result, take the picture.
// Node Playwright with the preinstalled Chromium; never runs `playwright install`.
//
//   TB_SHOT_PASSWORD=... node tools/stage_shots.js '{"base": "http://127.0.0.1:PORT", "out": "<dir>",
//       "items": [{"name": "h-ja-03", "user": "pi", "lang": "ja", "path": "/studies/GZQO/week?list=all"}]}'
//
// An item with "url" instead of "user" (a stage with no console of its own: install, backup, update) opens that page,
// the stage's check table written by complete_run, without signing in. The password comes from the environment only
// (never argv, never printed). Prints one JSON line: per item the file, the HTTP status and the page's html lang.
"use strict";

const { chromium } = require("playwright");
const path = require("path");

const args = JSON.parse(process.argv[2] || "{}");
const PASSWORD = process.env.TB_SHOT_PASSWORD || "";

async function signIn(page, user, lang) {
  await page.goto(args.base + "/login", { waitUntil: "load" });
  await page.fill("#username", user);
  await page.fill("#password", PASSWORD);
  await Promise.all([page.waitForLoadState("load"), page.click("[data-testid=login-submit]")]);
  await page.waitForSelector("[data-testid=whoami]", { state: "attached", timeout: 20000 });
  const b = page.locator("[data-testid=menu-button]");
  if ((await b.count()) && (await b.isVisible())) await b.click();
  await page.selectOption("select#lang", lang);
  await Promise.all([page.waitForLoadState("load"), page.click("form[action='/lang'] button[type=submit]")]);
}

(async () => {
  const browser = await chromium.launch();
  const out = [];
  const contexts = new Map(); // one signed-in context per (user, lang)
  try {
    for (const it of args.items || []) {
      const key = `${it.user}/${it.lang}`;
      const r = { name: it.name, path: it.path, ok: false };
      try {
        if (it.url) {
          const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
          const page = await ctx.newPage();
          await page.goto(it.url, { waitUntil: "load" });
          r.status = 200;
          r.file = `${it.name}.png`;
          await page.screenshot({ path: path.join(args.out, r.file), fullPage: true });
          await ctx.close();
          r.ok = true;
          out.push(r);
          continue;
        }
        if (!contexts.has(key)) {
          const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, locale: it.lang });
          const page = await ctx.newPage();
          await signIn(page, it.user, it.lang);
          contexts.set(key, { ctx, page });
        }
        const { page } = contexts.get(key);
        const resp = await page.goto(args.base + it.path, { waitUntil: "load" });
        r.status = resp ? resp.status() : 0;
        r.lang = await page.getAttribute("html", "lang");
        r.file = `${it.name}.png`;
        await page.screenshot({ path: path.join(args.out, r.file), fullPage: false });
        r.ok = r.status === 200;
      } catch (e) {
        r.error = e.message.split("\n")[0];
      }
      out.push(r);
    }
  } finally {
    for (const { ctx } of contexts.values()) await ctx.close();
    await browser.close();
  }
  console.log(JSON.stringify(out));
})();
