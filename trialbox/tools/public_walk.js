// Browser walk of every screen on the public-data console (tools/public_e2e.py --serve): 5 roles x 3 languages x
// desktop and phone. Node Playwright with the preinstalled Chromium; never runs `playwright install`.
//
//   node tools/public_walk.js '{"base": "...", "password": "...", "walk": "<dir>/walk.json", "shots": "<dir>"}'
//   TB_SHOT_PASSWORD=... node tools/public_walk.js '{"base": "...", "walk": ...}'   # the password off the command line
//
// For every page a role can open it checks: HTTP status (200, or the expected 403/404), the page language (html
// lang), no raw catalogue key left on the page (an untranslated string such as "admin.health.title"), no "None" or
// "undefined" in the text, on a Japanese or Chinese page no cell in English (D-119), and on the phone no horizontal
// scroll. One screenshot per role/language/view/page
// (viewport, scale 1) and a few full-page ones at scale 2. Then the investigator marks a patient by pressing the
// buttons (Need info, then Withdraw), the coordinator uses the command field, and (TB-PLAN-04 step 4, D-129) the
// coordinator on a 390 px phone in Japanese saves a consent and a visit on the Entry page, edits the consent, and the
// History page shows the edit (old and new).
//
// TB-PLAN-04 step 4b (D-133): every page also runs axe-core (fails on a serious or critical issue; axe comes from
// node_modules when installed, else the vendored copy in tools/vendor, injected with addScriptTag because the
// console's security policy allows no other script), checks that every interactive target is at least 44 px (a link
// inside a sentence is WCAG 2.5.5's exception), and the six core tasks of the novice review are walked with their taps
// counted; the counts go into walk.json ("taps") and must be at or below the review's "could" column. Prints one JSON
// line.
//
// TB-PLAN-04 step 5 (D-134): the lifecycle pages (participants, one participant, visits, the visit schedule, the
// enrolment report) for every role that may open them, and task T7: the coordinator, on a phone in Japanese, marks
// today's visit done from the home page ("Done today", then Save; target 2 to 3 taps).
//
// TB-PLAN-04 step 5b (D-135): the site set-up pages on the practice site (readiness, the wizard, charts, the
// proposed-fact review list, hospital codes, "please check", lists, patients, the criteria check, help) for the
// coordinator, the investigator and the administrator (403 for viewer and CRA), Ask TrialBox for every role, and two
// tasks: T8 the coordinator confirms a proposed fact on a phone (target 2 taps), T9 the coordinator pastes a chart
// (target 3 taps: the chart number, the text, Read).
// Review 2026-11-09 P-04 (D-143): "Excluded patients and why" for the investigator and the coordinator (403 for viewer
// and CRA).
"use strict";

const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const args = JSON.parse(process.argv[2] || "{}");
function axeSource() {
  try {
    return fs.readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");
  } catch (e) {
    return fs.readFileSync(path.join(__dirname, "vendor", "axe.min.js"), "utf8");
  }
}
const AXE = axeSource();
// the novice review's task table (docs/reviews/2026-11-08-ux-review-novice.md §2), "taps it could take"
const TAPS_MAX = { T1: 2, T2: 2, T3: 2, T4: 10, T5: 5, T6: 3, T7: 3, T8: 2, T9: 3 };
const W = JSON.parse(fs.readFileSync(args.walk, "utf8"));
const T = W.trial;
const C = W.cohort;
const LR = W.life_record; // D-134: a participant with today's visit and a serious AE
const SQ = `ws=${W.site_ws || "practice"}&study=${T}`; // D-135: the practice site, loaded by public_e2e stage 5c
const SITE = [`/site?${SQ}`, `/site/start?${SQ}&step=2`, `/site/charts?${SQ}`, `/site/facts?${SQ}`, `/site/codes?${SQ}`, `/site/checks?${SQ}`, `/site/sheets?${SQ}`, `/site/people?${SQ}`, `/site/patients?${SQ}`, `/site/help?${SQ}`];
// D-141: the study team's pages (candidates across the hospital, a candidate opened with a purpose, referrals, the
// delegation log, IRB and consent form) and the steward's lists
const TEAM = [`/studies/${T}/candidates`, `/studies/${T}/candidates/${W.pid_marked}?purpose=eligibility`, `/studies/${T}/referrals`, `/studies/${T}/team`, `/studies/${T}/irb`, "/site/staff"];
const LIFE = [`/studies/${T}/subjects`, `/studies/${T}/subjects/${LR}`, `/studies/${T}/visits`, `/studies/${T}/schedule`, `/studies/${T}/enrolment`];
// Review 2026-11-09 J-03 to J-05 (D-146): viewer and CRA open no CASE job page, registry, audit trail, runs list, study
// set-up or sources page and no REDCap connection page (403); the viewer still opens a feasibility run's page
const AGG_ONLY_FORBIDDEN = [`/pilot/jobs/${W.case_job}`, `/pilot/registry/${C}`, "/audit", "/jobs", `/studies/${T}/setup`, `/studies/${T}/sources`, "/admin/redcap"];
const PAGES = {
  common: ["/home", "/help", "/account", "/notices/received", "/settings/notices", "/no-such-page", `/ask?q=next&${SQ}`],
  pi: [
    "/week",
    `/studies/${T}/week?list=all`,
    `/studies/${T}/patients/${W.pid_marked}`,
    `/studies/${C}/cohort`,
    `/studies/${T}/feasibility`,
    `/pilot/jobs/${W.approval_job}/approval`,
    `/studies/${T}/screening-log`,
    `/studies/${T}/excluded`,
    `/studies/${T}/sources`,
    `/studies/${T}/conflicts`,
    `/studies/${T}/forms`,
    ...LIFE,
    ...SITE,
    ...TEAM,
    "/reports",
  ],
  crc: [
    `/studies/${T}/week?list=all`,
    `/studies/${T}/patients/${W.pid_marked}`,
    `/studies/${C}/cohort`,
    `/studies/${T}/feasibility`,
    `/studies/${T}/screening-log`,
    `/studies/${T}/excluded`,
    `/studies/${T}/setup`,
    "/studies/NOPE-01/setup",
    `/studies/${T}/sources`,
    `/studies/${T}/conflicts?all=1`,
    `/studies/${T}/forms`,
    `/studies/${T}/entry?record=${W.record}&form=tb_consent`,
    `/studies/${T}/entry?record=${W.record}&form=tb_visit&event=v1`,
    `/studies/${T}/history?record=${W.record}`,
    ...LIFE,
    ...SITE,
    ...TEAM,
    "/site/opt-outs",
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
  admin: ["/admin?tab=health", "/admin/notice", "/admin?tab=jobs", "/admin?tab=sources", "/admin/redcap", "/ops/users", "/audit", "/jobs", `/studies/${T}/subjects`, `/studies/${T}/enrolment`, `/site?${SQ}`, `/site/codes?${SQ}`, `/site/help?${SQ}`],
  viewer: ["/reports", "/reports/research-office", `/studies/${T}/week?list=all`, "/admin?tab=health", `/studies/${T}/subjects`, `/studies/${T}/visits`, `/site?${SQ}`, `/site/facts?${SQ}`, `/studies/${T}/excluded`, `/pilot/jobs/${W.feas_job}`, ...AGG_ONLY_FORBIDDEN, `/studies/${T}/candidates`, `/studies/${T}/referrals`],
  cra: ["/reports", "/reports/research-office", `/studies/${T}/week?list=all`, "/admin?tab=health", `/studies/${T}/subjects`, `/studies/${T}/enrolment`, `/site?${SQ}`, `/site/facts?${SQ}`, `/studies/${T}/excluded`, ...AGG_ONLY_FORBIDDEN, `/studies/${T}/candidates`, `/studies/${T}/referrals`],
};
// pages a role must not open: a 403 page (in the chosen language), never a 500
const FORBIDDEN = {
  pi: ["/admin?tab=health", "/site/opt-outs"],
  crc: ["/admin?tab=health", "/admin/notice"],
  viewer: [`/studies/${T}/week?list=all`, "/admin?tab=health", `/studies/${T}/subjects`, `/studies/${T}/visits`, `/site?${SQ}`, `/site/facts?${SQ}`, `/studies/${T}/excluded`, ...AGG_ONLY_FORBIDDEN, `/studies/${T}/candidates`, `/studies/${T}/referrals`],
  cra: [`/studies/${T}/week?list=all`, "/admin?tab=health", "/notices/received", "/settings/notices", "/reports/research-office", `/studies/${T}/subjects`, `/studies/${T}/enrolment`, `/site?${SQ}`, `/site/facts?${SQ}`, `/studies/${T}/excluded`, ...AGG_ONLY_FORBIDDEN, `/studies/${T}/candidates`, `/studies/${T}/referrals`],
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
const KEY = /\b(?:admin|mark|outcome|log|week|home|help|account|notice|notices|report|reports|feas|screen|study|studies|patient|case|consent|setup|redcap|lang|cmd|registry|problem|reason|job|jobs|approval|protocol|request|ops|users|life|site|ask)\.[a-z_]+(?:\.[a-z_]+)*\b/;

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

// D-133: every interactive target at least 44 x 44 px. A checkbox or radio counts by its label; a link inside a
// sentence (an inline link with other words around it) is the WCAG 2.5.5 exception; hidden and screen-reader-only
// elements are not targets.
function smallTargets() {
  const vis = (el) => {
    const s = getComputedStyle(el);
    return s.display !== "none" && s.visibility !== "hidden" && el.getClientRects().length > 0;
  };
  const inSentence = (el) => {
    if (getComputedStyle(el).display !== "inline") return false;
    const block = el.parentElement;
    const rest = (block ? block.innerText : "").replace(el.innerText, "");
    return /[\p{L}\p{N}]{2,}/u.test(rest);
  };
  const out = [];
  let n = 0;
  for (const el of document.querySelectorAll("a[href], button, input:not([type=hidden]), select, textarea, summary, [role=button]")) {
    if (el.closest(".sr, .skip") || el.matches(".menu-toggle")) continue;
    let t = el;
    if (el.matches("input[type=checkbox], input[type=radio]")) t = el.closest("label") || document.querySelector(`label[for="${el.id}"]`) || el;
    if (!vis(t)) continue;
    n++;
    if (el.tagName === "A" && inSentence(el)) continue;
    const r = t.getBoundingClientRect();
    if (r.width < 44 - 0.5 || r.height < 44 - 0.5)
      out.push(`${el.tagName.toLowerCase()} "${(el.innerText || el.value || el.getAttribute("aria-label") || "").trim().slice(0, 24)}" ${Math.round(r.width)}x${Math.round(r.height)}`);
  }
  return { n, small: out };
}

async function axeCheck(page) {
  await page.addScriptTag({ content: AXE });
  return page.evaluate(async () => {
    const res = await axe.run(document, { resultTypes: ["violations"] });
    return res.violations.map((v) => ({ id: v.id, impact: v.impact, n: v.nodes.length, ex: v.nodes.slice(0, 2).map((x) => x.target.join(" ")) }));
  });
}

async function openMenu(page) {
  const b = page.locator("[data-testid=menu-button]");
  if ((await b.count()) && (await b.isVisible())) await b.click();
}

async function signIn(page, user, L, password) {
  await page.goto(args.base + "/login", { waitUntil: "load" });
  await page.fill("#username", user);
  await page.fill("#password", password || args.password || process.env.TB_SHOT_PASSWORD);
  await Promise.all([page.waitForLoadState("load"), page.click("[data-testid=login-submit]")]);
  await page.waitForSelector("[data-testid=whoami]", { state: "attached", timeout: 20000 });
  await openMenu(page);
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
    const tg = await page.evaluate(smallTargets);
    r.targets = tg.n;
    r.small = tg.small.length;
    if (tg.small.length) r.why.push(`targets under 44 px: ${tg.small.slice(0, 3).join(", ")}${tg.small.length > 3 ? ` (+${tg.small.length - 3})` : ""}`);
    r.axe = await axeCheck(page);
    const grave = r.axe.filter((v) => v.impact === "serious" || v.impact === "critical");
    if (grave.length) r.why.push(`axe: ${grave.map((v) => `${v.id} (${v.impact}, ${v.n}: ${v.ex.join(" | ")})`).join("; ")}`);
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

// D-133: the six core tasks of the novice review, walked with their taps counted (a click, a choice in a list, a
// field typed or Enter each count one; signing in and the language switch before a task do not, as in the review).
const TAPS = {};
async function task(browser, name, opts, fn) {
  const ctx = await browser.newContext({ ...opts, bypassCSP: true });
  const page = await ctx.newPage();
  const r = { tag: name, page: `task ${name}`, expect: `at most ${TAPS_MAX[name]} taps`, ok: true, why: [] };
  let taps = 0;
  const tap = async (what) => {
    taps++;
    if (typeof what === "function") await what();
  };
  try {
    await fn(page, tap, r);
  } catch (e) {
    r.why.push(e.message.split("\n")[0]);
  }
  r.taps = taps;
  TAPS[name] = taps;
  if (taps > TAPS_MAX[name]) r.why.push(`${taps} taps (the review's target is ${TAPS_MAX[name]})`);
  if (args.shots) await page.screenshot({ path: path.join(args.shots, `task-${name}.png`), fullPage: false }).catch(() => {});
  r.ok = r.why.length === 0;
  rec(r);
  await ctx.close();
}
const inView = (sel) => (page) =>
  page.evaluate((s) => {
    const el = document.querySelector(s);
    if (!el) return false;
    const b = el.getBoundingClientRect();
    return b.height > 0 && b.top >= -1 && b.bottom <= window.innerHeight + 1;
  }, sel);
const clickNav = (page, sel) => Promise.all([page.waitForLoadState("load"), page.click(sel)]);

async function tasks(browser) {
  const phone = (locale) => ({ viewport: VIEWS[1].viewport, isMobile: true, hasTouch: true, locale });
  const desk = (locale) => ({ viewport: VIEWS[0].viewport, locale });
  // T1: the investigator, on a phone in Japanese, marks one patient of this week's list: tap the row (the sheet opens
  // in place, with the mark bar in view), tap the mark. Undo afterwards (not counted) leaves the data as it was.
  await task(browser, "T1", phone("ja-JP"), async (page, tap, r) => {
    await signIn(page, "pi", LANGS[1]);
    await page.goto(`${args.base}/studies/${T}/week?list=all`, { waitUntil: "load" });
    const row = page.locator("a.rowlink").first();
    const short = ((await row.getAttribute("data-testid")) || "").replace("open-", "");
    await tap(() => clickNav(page, "a.rowlink >> nth=0"));
    if (!(await page.locator(".chartp.sheet").count())) r.why.push("the row did not open the patient sheet");
    if (!(await inView("[data-testid=markbar]")(page))) r.why.push("the mark bar is not in view without scrolling");
    if (!(await inView("[data-testid=why]")(page))) r.why.push("the why line is not in view");
    await tap(() => clickNav(page, `[data-testid=need_info-${short}]`));
    if (!(await page.locator("[data-testid=done]").count())) r.why.push("no toast after the mark");
    await clickNav(page, "[data-testid=undo]");
  });
  // T2: the coordinator, on a desktop in Chinese, records a contact outcome: the call task on the home page, then the
  // outcome (only offered after the investigator's Approach, D-133 / F-36).
  await task(browser, "T2", desk("zh-TW"), async (page, tap, r) => {
    // the precondition: the investigator has approved a patient (Approach); a call task is then on the coordinator's
    // home page. The walk's own patient (W.pid_fresh) is used; the action check above withdrew its earlier mark.
    const pp = await page.context().newPage();
    await signIn(pp, "pi", LANGS[0]);
    await pp.goto(`${args.base}/studies/${T}/patients/${W.pid_fresh}`, { waitUntil: "load" });
    await clickNav(pp, `[data-testid=approach-${W.pid_fresh.slice(0, 8)}]`);
    await pp.close();
    await page.context().clearCookies();
    await signIn(page, "crc", LANGS[2]);
    await page.goto(`${args.base}/home`, { waitUntil: "load" });
    const call = page.locator(`[data-testid=task-call] a[href*="${W.pid_fresh}"]`).first();
    if (!(await call.count())) throw new Error("no call task on the coordinator's home page");
    await tap(() => Promise.all([page.waitForLoadState("load"), call.click()]));
    await tap(() => clickNav(page, "[data-testid=outcome-not_reached]"));
    if (!(await page.locator("[data-testid=done]").count())) r.why.push("no confirmation after the outcome");
  });
  // T3: the coordinator, on a phone in Japanese, finds why a patient is listed: type the patient code in the search
  // field (kept outside the menu on a phone) and press Enter; the why line is in view.
  await task(browser, "T3", phone("ja-JP"), async (page, tap, r) => {
    await signIn(page, "crc", LANGS[1]);
    await page.goto(`${args.base}/home`, { waitUntil: "load" });
    await tap(() => page.fill("[data-testid=cmd-q]", W.pid_marked.slice(0, 8)));
    await tap(() => Promise.all([page.waitForLoadState("load"), page.press("[data-testid=cmd-q]", "Enter")]));
    if (!(await inView("[data-testid=why]")(page))) r.why.push(`the why line is not in view (${new URL(page.url()).pathname})`);
  });
  // T4: the coordinator, on a desktop in English, opens the study set-up from home, reads the REDCap fields, picks two
  // of them from the dictionary and saves the whole page once.
  await task(browser, "T4", desk("en-US"), async (page, tap, r) => {
    await signIn(page, "crc", LANGS[0]);
    await page.goto(`${args.base}/home`, { waitUntil: "load" });
    await tap(() => clickNav(page, `[data-testid=setup-${T}]`));
    await tap(() => clickNav(page, "[data-testid=read-fields]"));
    if (!(await page.locator("[data-testid=dict-read]").count())) {
      const err = await page.locator("[data-testid=setup-error]").allInnerTexts();
      throw new Error(`the REDCap fields were not read: ${err.join(" / ").slice(0, 160)}`);
    }
    for (const f of ["consent_field", "enrol_field"]) {
      const sel = `[data-testid=pick-${f}]`;
      const cur = await page.locator(sel).inputValue();
      await tap(() => page.selectOption(sel, cur));
    }
    await tap(() => clickNav(page, "[data-testid=save-setup]"));
    if (!(await page.locator("[data-testid=setup-saved]").count())) {
      const err = await page.locator("[data-testid=setup-error]").allInnerTexts();
      r.why.push(`not saved: ${err.join(" / ").slice(0, 160)}`);
    }
  });
  // T5: the administrator, on a desktop in Japanese, adds a coordinator and checks the system: Create account, the
  // user name and the study, Create, then home (the system tile). The one-time password is read once from the page.
  let made = null;
  await task(browser, "T5", desk("ja-JP"), async (page, tap, r) => {
    await signIn(page, "admin", LANGS[1]);
    await page.goto(`${args.base}/home`, { waitUntil: "load" });
    const name = `nurse${Date.now() % 100000}`;
    await tap(() => clickNav(page, "[data-testid=create-account]"));
    await tap(() => page.fill("#username", name));
    await tap(() => page.fill("#studies", "NEW-01"));
    await tap(() => clickNav(page, "[data-testid=users-add]"));
    if (/[?&]pw=/.test(page.url())) r.why.push("the one-time password is in the address");
    const pw = await page.locator("[data-testid=users-pw-field]").inputValue().catch(() => "");
    if (!/^([a-z2-9]{4}-){4}[a-z2-9]{4}$/.test(pw)) r.why.push("no readable one-time password on the page");
    made = { name, pw };
    await tap(() => clickNav(page, "[data-testid=nav] a[href='/home']"));
    if (!(await page.locator("[data-testid=tile-system]").isVisible())) r.why.push("the system tile is not on the home page");
  });
  // T6: the new coordinator's first day, on a phone in Chinese: sign in with the one-time password (3 taps); the home
  // page names the one thing to do; a study that does not exist answers 404 (F-37).
  await task(browser, "T6", phone("zh-TW"), async (page, tap, r) => {
    if (!made || !made.pw) throw new Error("T5 made no account");
    await page.goto(`${args.base}/login`, { waitUntil: "load" });
    if ((await page.getAttribute("html", "lang")) !== "zh-TW") r.why.push("the sign-in page is not in the browser's language");
    await tap(() => page.fill("#username", made.name));
    await tap(() => page.fill("#password", made.pw));
    await tap(() => clickNav(page, "[data-testid=login-submit]"));
    if (!(await page.locator("[data-testid=send-protocol]").isVisible())) r.why.push("the first-day home page has no next step");
    const resp = await page.goto(`${args.base}/studies/NEW-01/setup`, { waitUntil: "load" });
    if (!resp || resp.status() !== 404) r.why.push(`an unknown study answered ${resp ? resp.status() : "nothing"}, not 404`);
  });
  // T7 (D-134): the coordinator, on a phone in Japanese, marks today's visit done: "Done today" on the home page opens
  // the visit form filled in for today (done, today's date, in the window); Save. The list then no longer shows it.
  await task(browser, "T7", phone("ja-JP"), async (page, tap, r) => {
    await signIn(page, "crc", LANGS[1]);
    await page.goto(`${args.base}/home`, { waitUntil: "load" });
    const done = `[data-testid="done-${LR}-v1"]`;
    if (!(await page.locator(done).count())) throw new Error("today's visit is not on the coordinator's home page");
    await tap(() => clickNav(page, `${done} >> nth=0`));
    if (!(await page.locator("[data-testid=f-vs_status-1]").isChecked())) r.why.push("the visit form is not filled in as done");
    if (!(await inView("[data-testid=entry-save]")(page))) await page.locator("[data-testid=entry-save]").scrollIntoViewIfNeeded();
    await tap(() => clickNav(page, "[data-testid=entry-save]"));
    if (!(await page.locator("[data-testid=visit-saved]").count())) {
      const errs = await page.locator(".error").allInnerTexts();
      r.why.push(`not saved: ${errs.join(" / ").slice(0, 160)}`);
    }
    if (await page.locator(done).count()) r.why.push("the visit is still on the list after Save");
  });
  // T8 (D-135): the coordinator, on a phone in Japanese, confirms an item read from a chart: "Check them" on the
  // readiness page opens the review list, where the item sits beside the chart's words; Confirm. Target 2 taps.
  await task(browser, "T8", phone("ja-JP"), async (page, tap, r) => {
    await signIn(page, "crc", LANGS[1]);
    await page.goto(`${args.base}/site?${SQ}`, { waitUntil: "load" });
    if (!(await page.locator("[data-testid=fix-proposed]").count())) throw new Error("no item to check on the readiness page");
    await tap(() => clickNav(page, "[data-testid=fix-proposed]"));
    const first = page.locator("[data-testid^=confirm-]").first();
    const id = ((await first.getAttribute("data-testid")) || "").replace("confirm-", "");
    if (!(await page.locator(`[data-testid=quote-${id}]`).count())) r.why.push("the item is not beside the chart's words");
    await tap(() => Promise.all([page.waitForLoadState("load"), first.click()]));
    if (!(await page.locator("[data-testid=fact-done]").count())) r.why.push("no confirmation after Confirm");
    if (await page.locator(`[data-testid=confirm-${id}]`).count()) r.why.push("the item is still waiting");
  });
  // T9 (D-135): the coordinator, on a phone in Chinese, pastes a chart copied from the EMR screen: the chart number,
  // the text, Read. Target 3 taps.
  await task(browser, "T9", phone("zh-TW"), async (page, tap, r) => {
    await signIn(page, "crc", LANGS[2]);
    await page.goto(`${args.base}/site/charts?${SQ}`, { waitUntil: "load" });
    await tap(() => page.fill("[data-testid=chart-no]", "10000009"));
    await tap(() => page.fill("[data-testid=chart-text]", "門診紀錄 2026年10月2日\n診斷：痛風\n檢驗：尿酸 9.2 mg/dL\n"));
    await tap(() => clickNav(page, "[data-testid=chart-save]"));
    if (!(await page.locator("[data-testid=chart-saved]").count())) {
      const errs = await page.locator(".error").allInnerTexts();
      r.why.push(`not read: ${errs.join(" / ").slice(0, 160)}`);
    }
  });
}

(async () => {
  const browser = await chromium.launch();
  try {
    for (const user of ROLES)
      for (const L of LANGS)
        for (const V of VIEWS) {
          const tag = `${user}/${L.lang}/${V.name}`;
          const ctx = await browser.newContext({ viewport: V.viewport, isMobile: !!V.isMobile, hasTouch: !!V.hasTouch, locale: L.locale, bypassCSP: true });
          const page = await ctx.newPage();
          try {
            await signIn(page, user, L);
            const forb = new Set(FORBIDDEN[user] || []);
            for (const p of [...PAGES.common, ...(PAGES[user] || [])]) {
              await visit(page, tag, p, p === "/no-such-page" || p.includes("/NOPE-") ? 404 : forb.has(p) ? 403 : 200);
            }
          } catch (e) {
            rec({ tag, page: "sign-in", expect: 200, ok: false, why: [e.message.split("\n")[0]] });
          } finally {
            await ctx.close();
          }
        }
    await actions(browser);
    await tasks(browser);
    if (args.shots) await bigShots(browser);
  } finally {
    await browser.close();
  }
  const failed = results.filter((r) => !r.ok);
  if (args.out) fs.writeFileSync(args.out, JSON.stringify(results, null, 1));
  const pages = results.filter((r) => r.axe);
  const axeAll = {};
  for (const r of pages) for (const v of r.axe) axeAll[v.impact] = (axeAll[v.impact] || 0) + 1;
  const summary = {
    pages: pages.length,
    axe_by_impact: axeAll,
    targets: pages.reduce((a, r) => a + (r.targets || 0), 0),
    targets_under_44: pages.reduce((a, r) => a + (r.small || 0), 0),
    taps: TAPS,
    taps_max: TAPS_MAX,
  };
  W.taps = TAPS;
  W.walk_summary = summary;
  fs.writeFileSync(args.walk, JSON.stringify(W));
  console.log(JSON.stringify({ checks: results.length, failed: failed.length, summary, failures: failed.slice(0, 80).map((r) => `${r.tag} ${r.page}: ${r.why.join("; ")}`) }));
})();
