// Browser walk of every screen on the public-data console (tools/public_e2e.py --serve): 5 roles x 3 languages x
// desktop and phone. Node Playwright with the preinstalled Chromium; never runs `playwright install`.
//
//   node tools/public_walk.js '{"base": "...", "password": "...", "walk": "<dir>/walk.json", "shots": "<dir>"}'
//
// For every page a role can open it checks: HTTP status (200, or the expected 403/404), the page language (html
// lang), no raw catalogue key left on the page (an untranslated string such as "admin.health.title"), no "None" or
// "undefined" in the text, on a Japanese or Chinese page no cell in English (D-119), and on the phone no horizontal
// scroll. One screenshot per role/language/view/page
// (viewport, scale 1) and a few full-page ones at scale 2. Then the investigator marks a patient by pressing the
// buttons (Need info, then Withdraw), the coordinator uses the command field, and (TB-PLAN-04 step 4, D-129) the
// coordinator on a 390 px phone in Japanese saves a consent and a visit on the Entry page, edits the consent, and the
// History page shows the edit (old and new). Prints one JSON line.
"use strict";

const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const args = JSON.parse(process.argv[2] || "{}");
const W = JSON.parse(fs.readFileSync(args.walk, "utf8"));
const T = W.trial;
const C = W.cohort;
const PAGES = {
  common: ["/home", "/help", "/account", "/notices/received", "/settings/notices", "/no-such-page"],
  pi: [
    "/week",
    `/studies/${T}/week?list=all`,
    `/studies/${T}/patients/${W.pid_marked}`,
    `/studies/${C}/cohort`,
    `/studies/${T}/feasibility`,
    `/pilot/jobs/${W.approval_job}/approval`,
    `/studies/${T}/screening-log`,
    `/studies/${T}/sources`,
    `/studies/${T}/conflicts`,
    `/studies/${T}/forms`,
    "/reports",
  ],
  crc: [
    `/studies/${T}/week?list=all`,
    `/studies/${T}/patients/${W.pid_marked}`,
    `/studies/${C}/cohort`,
    `/studies/${T}/feasibility`,
    `/studies/${T}/screening-log`,
    `/studies/${T}/setup`,
    `/studies/${T}/sources`,
    `/studies/${T}/conflicts?all=1`,
    `/studies/${T}/forms`,
    `/studies/${T}/entry?record=${W.record}&form=tb_consent`,
    `/studies/${T}/entry?record=${W.record}&form=tb_visit&event=v1`,
    `/studies/${T}/history?record=${W.record}`,
    "/pilot/protocol",
    "/pilot/request",
    "/pilot/case",
    "/pilot/consent",
    `/pilot/jobs/${W.feas_job}`,
    `/pilot/jobs/${W.case_job}`,
    `/pilot/jobs/${W.consent_job}`,
    `/pilot/registry/${C}`,
    "/reports",
    "/reports/research-office",
    "/jobs",
  ],
  admin: ["/admin?tab=health", "/admin?tab=jobs", "/admin?tab=sources", "/admin/redcap", "/ops/users", "/audit", "/jobs"],
  viewer: ["/reports", "/reports/research-office", `/studies/${T}/week?list=all`, "/admin?tab=health"],
  cra: ["/reports", "/reports/research-office", `/studies/${T}/week?list=all`, "/admin?tab=health"],
};
// pages a role must not open: a 403 page (in the chosen language), never a 500
const FORBIDDEN = {
  pi: ["/admin?tab=health"],
  crc: ["/admin?tab=health"],
  viewer: [`/studies/${T}/week?list=all`, "/admin?tab=health"],
  cra: [`/studies/${T}/week?list=all`, "/admin?tab=health", "/notices/received", "/settings/notices", "/reports/research-office"],
};
const ROLES = ["admin", "crc", "pi", "viewer", "cra"];
const LANGS = [
  { lang: "en", locale: "en-US" },
  { lang: "ja", locale: "ja-JP" },
  { lang: "zh-TW", locale: "zh-TW" },
];
const VIEWS = [
  { name: "desktop", viewport: { width: 1280, height: 860 } },
  { name: "phone", viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true },
];
const BIG = new Set([
  "pi/en/desktop/" + `/studies/${T}/week?list=all`,
  "pi/ja/desktop/" + `/studies/${T}/patients/${W.pid_marked}`,
  "crc/zh-TW/desktop/" + `/studies/${T}/feasibility`,
  "crc/en/desktop/" + `/studies/${T}/screening-log`,
  "admin/ja/desktop//admin?tab=health",
  "pi/zh-TW/phone/" + `/studies/${T}/week?list=all`,
  "crc/ja/phone//home",
]);

const results = [];
function rec(r) {
  results.push(r);
  if (!r.ok) process.exitCode = 1;
}
function slug(p) {
  return p.replace(/^\//, "").replace(/[^A-Za-z0-9]+/g, "_").slice(0, 60) || "root";
}
const KEY = /\b(?:admin|mark|outcome|log|week|home|help|account|notice|notices|report|reports|feas|screen|study|studies|patient|case|consent|setup|redcap|lang|cmd|registry|problem|reason|job|jobs|approval|protocol|request|ops|users)\.[a-z_]+(?:\.[a-z_]+)*\b/;

// the study's own words and the names from the data are shown as written (walk.json "authored", D-119)
const AUTHORED = (W.authored || []).filter((x) => x && x.length >= 3);

// D-119: on a Japanese or Chinese page, a user-facing cell (a leaf element's own text) made only of ASCII words is
// untranslated text. Codes, numbers, dates, ids, quotes from the notes, code blocks, the study's own words and
// anything marked with its own lang (a language name in the language menu) are not counted.
function englishCells(authored) {
  const SKIP = "script,style,code,pre,kbd,samp,blockquote,q,textarea,.quote,.mono,.code,[data-src],[data-file],[data-authored],[lang]:not(html),[aria-hidden=true],option";
  const out = [];
  const seen = new Set();
  const visible = (el) => {
    const s = getComputedStyle(el);
    return s.display !== "none" && s.visibility !== "hidden" && el.getClientRects().length > 0;
  };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const el = n.parentElement;
    if (!el || el.closest(SKIP) || !visible(el)) continue;
    let t = n.nodeValue.replace(/\s+/g, " ").trim();
    if (!t || !/^[\x00-\x7F]+$/.test(t)) continue;
    for (const a of authored) if (t.includes(a)) t = t.split(a).join(" ");
    // what is left once codes, ids, emails, urls, numbers and units are gone
    const words = t
      .replace(/https?:\/\/\S+|\S+@\S+|\b[A-Z0-9][A-Z0-9_.:\/-]*\d[A-Z0-9_.:\/-]*\b|\b[A-Z]{2,}[A-Z0-9-]*\b|\b[0-9a-f]{6,}\b/g, " ")
      .match(/[A-Za-z]{3,}/g);
    if (!words || words.length < 1) continue;
    if (words.length === 1 && /^(ok|csv|pdf|json|xlsx|html|ecog|redcap|fhir|trialbox|sql|cql|api|mrn|ulid|utc|jst|cst)$/i.test(words[0])) continue;
    if (!seen.has(t)) {
      seen.add(t);
      out.push(t.slice(0, 80));
    }
  }
  return out;
}

async function signIn(page, user, L) {
  await page.goto(args.base + "/login", { waitUntil: "load" });
  await page.fill("#username", user);
  await page.fill("#password", args.password);
  await Promise.all([page.waitForLoadState("load"), page.click("[data-testid=login-submit]")]);
  await page.waitForSelector("[data-testid=whoami]", { timeout: 20000 });
  await page.selectOption("select#lang", L.lang);
  await Promise.all([page.waitForLoadState("load"), page.click("form[action='/lang'] button[type=submit]")]);
}

async function visit(page, tag, p, expect) {
  const key = `${tag}/${p}`;
  const r = { tag, page: p, expect, ok: true, why: [] };
  try {
    const resp = await page.goto(args.base + p, { waitUntil: "load" });
    const status = resp ? resp.status() : 0;
    r.status = status;
    if (expect === 200 && status !== 200) r.why.push(`status ${status}`);
    if (expect !== 200 && status !== expect && !(expect === 403 && [303, 302, 404].includes(status))) r.why.push(`status ${status} (want ${expect})`);
    if (status >= 500) r.why.push(`server error ${status}`);
    const lang = await page.getAttribute("html", "lang");
    if (lang !== tag.split("/")[1]) r.why.push(`html lang ${lang}`);
    const text = await page.evaluate(() => document.body.innerText);
    const k = p.startsWith("/audit") || p.startsWith("/pilot/jobs/") ? null : text.match(KEY); // audit event names are data
    if (k) r.why.push(`raw key "${k[0]}"`);
    const bad = text.match(/\b(None|undefined|NaN|Traceback)\b/);
    if (bad) r.why.push(`"${bad[0]}" on the page`);
    const lng = tag.split("/")[1];
    if (lng !== "en" && !p.startsWith("/audit")) {
      const eng = await page.evaluate(englishCells, AUTHORED);
      if (eng.length) r.why.push(`English on a ${lng} page: ${eng.slice(0, 4).map((x) => JSON.stringify(x)).join(", ")}${eng.length > 4 ? ` (+${eng.length - 4})` : ""}`);
      r.english = eng;
    }
    if (tag.endsWith("/phone")) {
      const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      if (over > 1) r.why.push(`horizontal scroll ${over}px`);
    }
    if (args.shots) {
      const file = `${tag.replace(/\//g, "-")}-${slug(p)}.png`;
      await page.screenshot({ path: path.join(args.shots, file), fullPage: false });
      r.shot = file;
    }
  } catch (e) {
    r.why.push(e.message.split("\n")[0]);
  }
  r.ok = r.why.length === 0;
  rec(r);
  if (BIG.has(key) && args.shots) {
    // a second, full-page screenshot at device scale 2 for the report
    r.big = true;
  }
}

async function bigShots(browser) {
  for (const key of BIG) {
    const [user, lang, view, ...rest] = key.split("/");
    const p = rest.join("/").replace(/^\//, "/");
    const V = VIEWS.find((v) => v.name === view);
    const L = LANGS.find((l) => l.lang === lang);
    const ctx = await browser.newContext({ viewport: V.viewport, isMobile: !!V.isMobile, hasTouch: !!V.hasTouch, locale: L.locale, deviceScaleFactor: 2 });
    const page = await ctx.newPage();
    try {
      await signIn(page, user, L);
      await page.goto(args.base + p, { waitUntil: "load" });
      await page.screenshot({ path: path.join(args.shots, `big-${user}-${lang}-${view}-${slug(p)}.png`), fullPage: true });
    } catch (e) {
      rec({ tag: `${user}/${lang}/${view}`, page: p, expect: "big shot", ok: false, why: [e.message.split("\n")[0]] });
    } finally {
      await ctx.close();
    }
  }
}

async function actions(browser) {
  // the investigator marks a fresh patient with the buttons on S5, then withdraws the mark (desktop, English)
  const ctx = await browser.newContext({ viewport: VIEWS[0].viewport, locale: "en-US" });
  const page = await ctx.newPage();
  const short = W.pid_fresh.slice(0, 8);
  const r = { tag: "pi/en/desktop", page: `S5 mark buttons ${short}`, expect: "Need info, then Withdraw", ok: true, why: [] };
  try {
    await signIn(page, "pi", LANGS[0]);
    await page.goto(`${args.base}/studies/${T}/patients/${W.pid_fresh}`, { waitUntil: "load" });
    await page.fill(`#note-${short}`, "ECOG not in the note");
    await Promise.all([page.waitForLoadState("load"), page.click(`[data-testid=need_info-${short}]`)]);
    await page.goto(`${args.base}/studies/${T}/patients/${W.pid_fresh}`, { waitUntil: "load" });
    const cur = await page.locator("[data-testid=current-mark]").innerText().catch(() => "");
    if (!/Need info/i.test(cur)) r.why.push(`current mark after Need info: "${cur}"`);
    await Promise.all([page.waitForLoadState("load"), page.click(`[data-testid=withdraw-${short}]`)]);
    await page.goto(`${args.base}/studies/${T}/patients/${W.pid_fresh}`, { waitUntil: "load" });
    const left = await page.locator("[data-testid=current-mark]").count();
    if (left !== 0) r.why.push("a current mark is still shown after Withdraw");
    if (args.shots) await page.screenshot({ path: path.join(args.shots, "action-pi-mark-withdraw.png"), fullPage: true });
  } catch (e) {
    r.why.push(e.message.split("\n")[0]);
  }
  r.ok = r.why.length === 0;
  rec(r);
  // the coordinator types a study code, a patient short id and "help" in the header command field
  const r2 = { tag: "crc/ja/desktop", page: "command field", expect: "study, patient, help", ok: true, why: [] };
  const p2 = await ctx.newPage();
  try {
    await signIn(p2, "crc", LANGS[1]);
    for (const [q, want] of [[T, /\/home|\/studies\//], [W.pid_marked.slice(0, 8), /\/cmd|\/studies\//], ["ヘルプ", /\/help/]]) {
      await p2.fill("[data-testid=cmd-q]", q);
      await Promise.all([p2.waitForLoadState("load"), p2.press("[data-testid=cmd-q]", "Enter")]);
      if (!want.test(new URL(p2.url()).pathname)) r2.why.push(`"${q}" went to ${new URL(p2.url()).pathname}`);
    }
  } catch (e) {
    r2.why.push(e.message.split("\n")[0]);
  }
  r2.ok = r2.why.length === 0;
  rec(r2);
  await ctx.close();
  await phoneEntry(browser);
}

// TB-PLAN-04 step 4 (D-129): the coordinator, on the phone in Japanese, saves a consent and then a visit, edits the
// consent, and the history shows the edit. The visit date only appears once "done" is ticked (branching in the
// browser, by the page's stylesheet).
async function phoneEntry(browser) {
  const V = VIEWS[1];
  const ctx = await browser.newContext({ viewport: V.viewport, isMobile: true, hasTouch: true, locale: "ja-JP" });
  const page = await ctx.newPage();
  const r = { tag: "crc/ja/phone", page: `entry ${W.record}`, expect: "consent, visit, edit in the history", ok: true, why: [] };
  const entry = (form, event) => `${args.base}/studies/${T}/entry?record=${encodeURIComponent(W.record)}&form=${form}${event ? `&event=${event}` : ""}`;
  const noScroll = async (what) => {
    const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    if (over > 1) r.why.push(`${what}: horizontal scroll ${over}px`);
  };
  const save = async (what) => {
    await Promise.all([page.waitForLoadState("load"), page.click("[data-testid=entry-save]")]);
    if (!(await page.locator("[data-testid=entry-saved]").count())) {
      const errs = await page.locator(".error").allInnerTexts();
      r.why.push(`${what} not saved: ${errs.join(" / ").slice(0, 160)}`);
    }
  };
  try {
    await signIn(page, "crc", LANGS[1]);
    const stamp = Date.now() % 100000;
    const v1 = `v2.${stamp}`;
    const v2 = `v3.${stamp}`;
    await page.goto(entry("tb_consent"), { waitUntil: "load" });
    await noScroll("consent form");
    if (!(await page.getByText("同意取得日").count())) r.why.push("the consent form is not in Japanese");
    await page.fill("#f_ic_date", "2026-11-02");
    await page.fill("#f_ic_version", v1);
    await page.check("[data-testid=f-ic_copy-1]");
    await save("consent");
    await page.goto(entry("tb_visit", "v1"), { waitUntil: "load" });
    if (await page.locator(".q-vs_date").isVisible()) r.why.push("the visit date shows before the visit is marked done");
    await page.check("[data-testid=f-vs_status-1]");
    if (!(await page.locator(".q-vs_date").isVisible())) r.why.push("the visit date stays hidden once the visit is done");
    await page.fill("#f_vs_date", "2026-11-09");
    await page.check("[data-testid=f-vs_window-1]");
    await page.fill("#f_vs_weight", "61.5");
    await noScroll("visit form");
    await save("visit");
    await page.goto(entry("tb_consent"), { waitUntil: "load" });
    await page.fill("#f_ic_version", v2);
    await save("consent edit");
    await noScroll("history");
    const rows = await page.locator("[data-testid=history] tbody tr").allInnerTexts();
    if (!rows.some((t) => t.includes(v1) && t.includes(v2))) r.why.push(`the history does not show ${v1} -> ${v2}`);
    if (!rows.some((t) => t.includes("61.5"))) r.why.push("the history does not show the visit");
    if (args.shots) await page.screenshot({ path: path.join(args.shots, "action-crc-ja-phone-entry-history.png"), fullPage: true });
  } catch (e) {
    r.why.push(e.message.split("\n")[0]);
  }
  r.ok = r.why.length === 0;
  rec(r);
  await ctx.close();
}

(async () => {
  const browser = await chromium.launch();
  try {
    for (const user of ROLES)
      for (const L of LANGS)
        for (const V of VIEWS) {
          const tag = `${user}/${L.lang}/${V.name}`;
          const ctx = await browser.newContext({ viewport: V.viewport, isMobile: !!V.isMobile, hasTouch: !!V.hasTouch, locale: L.locale });
          const page = await ctx.newPage();
          try {
            await signIn(page, user, L);
            const forb = new Set(FORBIDDEN[user] || []);
            for (const p of [...PAGES.common, ...(PAGES[user] || [])]) {
              await visit(page, tag, p, p === "/no-such-page" ? 404 : forb.has(p) ? 403 : 200);
            }
          } catch (e) {
            rec({ tag, page: "sign-in", expect: 200, ok: false, why: [e.message.split("\n")[0]] });
          } finally {
            await ctx.close();
          }
        }
    await actions(browser);
    if (args.shots) await bigShots(browser);
  } finally {
    await browser.close();
  }
  const failed = results.filter((r) => !r.ok);
  if (args.out) fs.writeFileSync(args.out, JSON.stringify(results, null, 1));
  console.log(JSON.stringify({ checks: results.length, failed: failed.length, failures: failed.slice(0, 80).map((r) => `${r.tag} ${r.page}: ${r.why.join("; ")}`) }));
})();
