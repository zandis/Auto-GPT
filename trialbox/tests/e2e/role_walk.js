// Build step 4 browser walk (D-110), driven by tests/e2e/test_role_walk.py: every role signs in, in every language,
// on desktop and on phone, against the role demo (tools/role_demo.py). Node Playwright with the preinstalled
// Chromium; never runs `playwright install`.
//
//   node tests/e2e/role_walk.js '{"base": "...", "password": "...", "shots": "<dir or empty>"}'
//
// For each of 5 roles x 3 languages x 2 viewports it checks: sign-in lands on the role's home; the page is in the
// chosen language (html lang, the command field's placeholder); the header command field opens the help panel
// from a phrase in that language; on the phone there is no horizontal scroll. Prints one JSON line; exit 1 on failure.
"use strict";

const { chromium } = require("playwright");
const path = require("path");

const args = JSON.parse(process.argv[2] || "{}");
const ROLES = [
  { user: "admin", home: "/home", mark: "[data-testid=admin-tabs]" },
  { user: "crc", home: "/home", mark: "[data-testid=cmd]" },
  { user: "pi", home: "/week|/studies/GZQO/week", mark: "[data-testid=cmd]" },
  { user: "viewer", home: "/reports", mark: "[data-testid=cmd]" },
  { user: "cra", home: "/reports", mark: "[data-testid=cmd]" },
];
const LANGS = [
  { lang: "en", locale: "en-US", accept: "en", help: "help", placeholder: "What do you need?" },
  { lang: "ja", locale: "ja-JP", accept: "ja", help: "ヘルプ", placeholder: "何をしますか？" },
  { lang: "zh-TW", locale: "zh-TW", accept: "zh-TW", help: "說明", placeholder: "需要什麼？" },
];
const VIEWS = [
  { name: "desktop", viewport: { width: 1280, height: 860 } },
  { name: "phone", viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true },
];
// screenshots the build asks for (deviceScaleFactor 2)
const SHOTS = {
  "pi/ja/desktop": "step4-pi-home-ja.png",
  "crc/ja/desktop": "step4-crc-home-ja.png",
  "admin/ja/desktop": "step4-admin-ja.png",
  "pi/zh-TW/phone": "step4-pi-home-zh-TW-phone.png",
};

const checks = [];
function check(ok, what) {
  checks.push({ ok: !!ok, what });
  if (!ok) {
    console.error("FAIL: " + what);
    process.exitCode = 1;
  }
}

async function walk(browser, role, L, V) {
  const tag = `${role.user}/${L.lang}/${V.name}`;
  const ctx = await browser.newContext({
    viewport: V.viewport,
    isMobile: !!V.isMobile,
    hasTouch: !!V.hasTouch,
    locale: L.locale,
    extraHTTPHeaders: { "Accept-Language": L.accept },
    deviceScaleFactor: SHOTS[tag] && args.shots ? 2 : 1,
  });
  const page = await ctx.newPage();
  try {
    await page.goto(args.base + "/login", { waitUntil: "load" });
    await page.fill("#username", role.user);
    await page.fill("#password", args.password);
    await Promise.all([page.waitForLoadState("load"), page.click("[data-testid=login-submit]")]);
    // D-975: signed in = the header names the person. On a phone the name sits in the menu, which stays folded until
    // opened (console.css .menu-body), so wait for it in the page, not for it to be shown; the walk opens the menu
    // below and checks the name is shown there
    await page.waitForSelector("[data-testid=whoami]", { state: "attached", timeout: 20000 });
    const url = new URL(page.url());
    check(new RegExp(`^(${role.home})$`).test(url.pathname), `${tag}: lands on its home (${url.pathname})`);
    check((await page.locator(role.mark).count()) > 0, `${tag}: home shows ${role.mark}`);
    check((await page.getAttribute("html", "lang")) === L.lang, `${tag}: page language ${L.lang}`);
    const ph = await page.getAttribute("[data-testid=cmd-q]", "placeholder");
    check(ph === L.placeholder, `${tag}: command field placeholder (${ph})`);
    if (V.name === "phone") {
      const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      check(over <= 1, `${tag}: no horizontal scroll on the phone (${over}px)`);
      // D-975: the person's name is in the folded menu; opening it shows the name
      await page.click("[data-testid=menu-button]");
      check(await page.isVisible("[data-testid=whoami]"), `${tag}: the menu opens and shows who is signed in`);
      await page.click("[data-testid=menu-button]");
    }
    if (SHOTS[tag] && args.shots) {
      await page.screenshot({ path: path.join(args.shots, SHOTS[tag]), fullPage: true });
    }
    await page.fill("[data-testid=cmd-q]", L.help);
    await Promise.all([page.waitForLoadState("load"), page.press("[data-testid=cmd-q]", "Enter")]);
    await page.waitForSelector("[data-testid=help-panel]", { timeout: 10000 });
    check(new URL(page.url()).pathname === "/help", `${tag}: "${L.help}" in the field opens the help panel`);
    if (V.name === "phone") {
      const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      check(over <= 1, `${tag}: help panel fits the phone (${over}px)`);
    }
    await page.goto(args.base + "/account", { waitUntil: "load" });
    check((await page.locator("[data-testid=account-facts]").count()) === 1, `${tag}: My account opens`);
  } catch (e) {
    check(false, `${tag}: ${e.message.split("\n")[0]}`);
  } finally {
    await ctx.close();
  }
}

(async () => {
  const browser = await chromium.launch();
  try {
    for (const role of ROLES) for (const L of LANGS) for (const V of VIEWS) await walk(browser, role, L, V);
  } finally {
    await browser.close();
  }
  const failed = checks.filter((c) => !c.ok);
  console.log(JSON.stringify({ checks: checks.length, failed: failed.length, failures: failed.map((c) => c.what) }));
})();
