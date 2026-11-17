// J-3 (D-1222): the phone tasks of the journey review (section E, "Which tasks belong on a phone"), each done on a
// 390 x 844 phone with the flag layout.phone_first on, in one page language. Driven by tests/e2e/test_phone_walk.py
// (the task list is tests/e2e/phone_walk_plan.py). Node Playwright with the preinstalled Chromium; never runs
// `playwright install`.
//
//   node tests/e2e/phone_walk.js '{"base": "...", "password": "...", "lang": "en", "shots": "<dir>", "pick": 0,
//                                  "tasks": ["mail_list", ...]}'
//
// Each task records its taps, whether it was done, and a screenshot; every page it opens is checked for sideways
// scroll. A candidate the investigator marks is a NEW one (no mark yet), and every mark and outcome is undone after,
// so the seeded data stays as it was. Prints one JSON line; exit 1 on a failure.
"use strict";

const { chromium } = require("playwright");
const path = require("path");

const args = JSON.parse(process.argv[2] || "{}");
const BASE = args.base;
const PHONE = { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 1 };
const RS = "GZQO";
const MAIL = "http://mail.test"; // another site: the browser serves its page (route), so a link from it is cross-site

const checks = [];
const results = [];
function check(ok, what) {
  checks.push({ ok: !!ok, what });
  if (!ok) {
    console.error("FAIL: " + what);
    process.exitCode = 1;
  }
  return !!ok;
}

async function phone(browser) {
  const ctx = await browser.newContext({ ...PHONE, locale: args.lang });
  await ctx.route(MAIL + "/**", (r) => r.fulfill({ contentType: "text/html", body: ctx._mail || "<p>mail</p>" }));
  return ctx;
}

async function signIn(page, user) {
  await page.fill("#username", user);
  await page.fill("#password", args.password);
  await Promise.all([page.waitForLoadState("load"), page.click("[data-testid=login-submit]")]);
}

async function session(browser, user) {
  const ctx = await phone(browser);
  const page = await ctx.newPage();
  await page.goto(BASE + "/login?lang=" + args.lang);
  await signIn(page, user);
  await page.goto(BASE + "/account");
  const csrf = await page.locator("input[name=csrf]").first().getAttribute("value");
  await page.request.post(BASE + "/lang", { form: { csrf, lang: args.lang, back: "/" } });
  return { ctx, page };
}

async function fits(page, what) {
  const sw = await page.evaluate(() => document.documentElement.scrollWidth);
  return check(sw <= 390, `${args.lang} ${what}: nothing scrolls sideways (${sw} px)`);
}

async function shot(page, task) {
  const file = path.join(args.shots, `phone-${task}-${args.lang}.png`);
  await page.screenshot({ path: file });
  return file;
}

function record(task, taps, done, file, note) {
  results.push({ task, lang: args.lang, taps, done: !!done, shot: file || "", note: note || "" });
}

async function load(page, fn) {
  await Promise.all([page.waitForNavigation({ waitUntil: "load" }), fn()]); // a tap that opens a page: wait for that page
}

async function setFlag(browser) {
  const { ctx, page } = await session(browser, "admin");
  await page.goto(BASE + "/ops/flags");
  const now = await page.locator("[data-flag='layout.phone_first'] [data-testid=flag-value]").getAttribute("data-value");
  if (now !== "on") {
    const csrf = await page.locator("input[name=csrf]").first().getAttribute("value");
    const r = await page.request.post(BASE + "/ops/flags", {
      form: { csrf, name: "layout.phone_first", value: "on", reason: "J-3 phone walk (D-1222)", confirm: "yes", old: now || "" },
      maxRedirects: 0,
    });
    check(r.status() === 303, `flag layout.phone_first set on by the administrator (${r.status()})`);
    await page.waitForTimeout(5500); // the flag's read cache (tb_common.flags.CACHE_SECONDS)
  }
  await ctx.close();
}

// a NEW candidate (no mark yet) of the week list, one per language so the walks do not meet
async function newCandidate(page) {
  await page.goto(`${BASE}/studies/${RS}/week?list=all`);
  const pids = await page.locator("table.worklist tbody tr").evaluateAll((rows) =>
    rows.filter((r) => !r.querySelector("[data-testid^=mark-]")).map((r) => new URL(r.querySelector("a.rowlink").href).searchParams.get("pid")));
  return pids[(args.pick || 0) + 2] || pids[0];
}

async function toastAndUndo(page, what) {
  check(await page.locator("[data-testid=done]").isVisible(), `${args.lang} ${what}: the done line shows`);
  const undo = page.locator("[data-testid=undo], [data-testid=outcome-undo]").first();
  await load(page, () => undo.click());
  check(!(await page.locator("[data-testid=current-mark]").count()) || what.startsWith("outcome"), `${args.lang} ${what}: undone`);
}

const TASKS = {
  // PI: the morning mail's link, tapped with a live session: the week list, a patient on the first screen
  async mail_list(browser) {
    const { ctx, page } = await session(browser, "pi");
    ctx._mail = `<!doctype html><title>mail</title><a id="go" href="${BASE}/studies/${RS}/week">week</a>`;
    await page.goto(MAIL + "/inbox");
    await Promise.all([page.waitForURL((u) => u.href.startsWith(BASE + "/studies/"), { timeout: 20000 }), page.click("#go")]);
    await page.waitForLoadState("load");
    const signin = await page.locator("form[action='/login']").count();
    check(signin === 0, `${args.lang} mail link with a live session: the week page, not the sign-in form`);
    const top = await page.evaluate(() => Math.round(document.querySelector("table.worklist tbody tr").getBoundingClientRect().top));
    check(top < 844, `${args.lang} the first patient row is on the first screen (top ${top} px)`);
    check(await page.locator("body.phone-first [data-testid=study-fold]").isVisible(), `${args.lang} the Study fold shows below the list`);
    await fits(page, "week page");
    const file = await shot(page, "mail_list");
    // the Study fold opens and holds the study's links
    await page.click("[data-testid=study-fold]");
    check(await page.locator("[data-testid=team-nav]").isVisible(), `${args.lang} the Study fold opens on the team's links`);
    await fits(page, "week page, Study fold open");
    await ctx.close();
    // no session: sign-in, then back on the asked page
    const c2 = await phone(browser);
    c2._mail = `<!doctype html><title>mail</title><a id="go" href="${BASE}/studies/${RS}/week">week</a>`;
    const p2 = await c2.newPage();
    await p2.goto(MAIL + "/inbox");
    await Promise.all([p2.waitForURL((u) => u.href.startsWith(BASE + "/login"), { timeout: 20000 }), p2.click("#go")]);
    await p2.waitForSelector("form[action='/login']");
    await signIn(p2, "pi");
    check(new URL(p2.url()).pathname === `/studies/${RS}/week`, `${args.lang} mail link without a session: sign-in leads back to the week page`);
    await c2.close();
    record("mail_list", 1, top < 844 && signin === 0, file, `first row top ${top} px`);
  },

  // PI: tap a row; the sheet shows the evidence before the note and the reason
  async evidence(browser, state) {
    const { ctx, page } = await session(browser, "pi");
    state.pid = await newCandidate(page);
    await page.goto(`${BASE}/studies/${RS}/week?list=all`);
    await load(page, () => page.locator(`a.rowlink[href*="${state.pid}"]`).click());
    const order = await page.evaluate(() => {
      const crit = document.querySelector(".chartp .critl"), note = document.querySelector(".chartp input[name=note]");
      return { crit: !!crit, before: !!(crit && note && crit.compareDocumentPosition(note) & 4),
        top: crit ? Math.round(crit.getBoundingClientRect().top) : null };
    });
    check(order.crit && order.before, `${args.lang} the sheet shows the criteria before the note and the reason`);
    check(order.top !== null && order.top < 844, `${args.lang} the evidence starts on the first screen (${order.top} px)`);
    check(await page.locator("[data-testid=markbar]").isVisible(), `${args.lang} the mark bar is in view`);
    await fits(page, "patient sheet");
    record("evidence", 1, order.before, await shot(page, "evidence"));
    await ctx.close();
  },

  // PI: Need info (and Not suitable with a reason) on the new candidate, each undone
  async mark(browser, state) {
    const { ctx, page } = await session(browser, "pi");
    const s = state.pid.slice(0, 8);
    await page.goto(`${BASE}/studies/${RS}/week?list=all`);
    await load(page, () => page.locator(`a.rowlink[href*="${state.pid}"]`).click());
    await load(page, () => page.click(`[data-testid=need_info-${s}]`));
    const file = await shot(page, "mark");
    await toastAndUndo(page, "Need info");
    await fits(page, "after a mark");
    record("mark", 2, true, file);
    // Not suitable: the reason (a select: two taps on a phone), then the button
    await page.selectOption(`[data-testid=reason-${s}]`, { index: 1 });
    await load(page, () => page.click(`[data-testid=not_suitable-${s}]`));
    await toastAndUndo(page, "Not suitable");
    record("not_suitable", 4, true, "");
    await ctx.close();
  },

  // CRC: after the PI's Approach, the contact outcome from the list in two taps; undone, and the Approach withdrawn
  async outcome(browser, state) {
    const pi = await session(browser, "pi");
    const s = state.pid.slice(0, 8);
    await pi.page.goto(`${BASE}/studies/${RS}/week?list=all&pid=${state.pid}#chart`);
    const approach = pi.page.locator(`[data-testid=approach-${s}]`);
    if (!check(await approach.count(), `${args.lang} the PI may mark Approach`)) { record("outcome", 0, false, "", "no Approach"); return; }
    await load(pi.page, () => approach.click());
    const { ctx, page } = await session(browser, "crc");
    await page.goto(`${BASE}/studies/${RS}/week?list=all`);
    await load(page, () => page.locator(`a.rowlink[href*="${state.pid}"]`).click());
    const out = page.locator("[data-testid=outcome-not_reached]");
    check(await out.isVisible(), `${args.lang} the outcome buttons show on the sheet`);
    await fits(page, "outcome sheet");
    await load(page, () => out.click());
    const file = await shot(page, "outcome");
    check(await page.locator("[data-testid=done]").isVisible(), `${args.lang} outcome: the done line shows`);
    await load(page, () => page.click("[data-testid=outcome-undo]"));
    await ctx.close();
    await pi.page.goto(`${BASE}/studies/${RS}/week?list=all&pid=${state.pid}#chart`);
    await load(pi.page, () => pi.page.click(`[data-testid=withdraw-${s}]`));
    check(!(await pi.page.locator("[data-testid=current-mark]").count()), `${args.lang} the Approach is withdrawn again`);
    record("outcome", 2, true, file);
    await pi.ctx.close();
  },

  // CRC: the task list is the home page (no tap)
  async tasks(browser) {
    const { ctx, page } = await session(browser, "crc");
    await page.goto(BASE + "/home");
    const h = await page.evaluate(() => document.documentElement.scrollHeight);
    const ok = await fits(page, "coordinator's home");
    record("tasks", 0, ok, await shot(page, "tasks"), `page ${h} px high`);
    await ctx.close();
  },

  // both: the participant's number typed in the header's field
  async lookup(browser, state) {
    const { ctx, page } = await session(browser, "crc");
    await page.goto(BASE + "/home");
    await page.fill("[data-testid=cmd-q]", state.pid.slice(0, 8));
    await load(page, () => page.press("[data-testid=cmd-q]", "Enter"));
    const ok = check(page.url().includes(`/patients/${state.pid}`), `${args.lang} the number opens the patient`);
    await fits(page, "patient page");
    record("lookup", 1, ok, await shot(page, "lookup"), "type the number, then Go");
    await ctx.close();
  },

  // CRC: an SAE form half filled, the session ends, Save meets the sign-in page; after sign-in the text is back
  async sae_form(browser) {
    const { ctx, page } = await session(browser, "crc");
    await page.goto(`${BASE}/studies/${RS}/subjects`);
    const rec = await page.locator(`main a[href*='/studies/${RS}/subjects/']`).first().getAttribute("href");
    await page.goto(BASE + rec);
    // the participant's page: its visits and its step trail as cards, nothing cut off or squeezed
    const cells = await page.evaluate(() => Array.from(document.querySelectorAll("table.pf-cards td[data-label]"))
      .filter((td) => td.offsetParent).map((td) => { const r = td.getBoundingClientRect(); return [Math.round(r.right), Math.round(r.width)]; }));
    check(cells.length > 0 && cells.every(([right, width]) => right <= 390 && width > 200),
      `${args.lang} the participant's visits and steps are cards within the screen (${cells.length} cells)`);
    await fits(page, "participant page");
    await shot(page, "participant");
    await load(page, () => page.click("[data-testid=ae-add]"));
    const field = page.locator("form#entry input[type=text]:not([disabled]), form#entry textarea:not([disabled])").first();
    const typed = "Synthetic test: gout flare of the knee, 3 days";
    await field.fill(typed);
    await fits(page, "AE form");
    const form = page.url();
    await ctx.addCookies([{ name: "tb_console", value: "a-session-that-has-ended", url: BASE }]); // the idle lock
    await load(page, () => page.click("[data-testid=entry-save]"));
    check(new URL(page.url()).pathname === "/login", `${args.lang} Save after the session ended meets the sign-in page`);
    await signIn(page, "crc");
    await page.waitForURL((u) => u.href.includes("form=tb_adverse_event"), { timeout: 15000 }).catch(() => {});
    const back = page.url() === form;
    const value = back ? await field.inputValue() : "";
    check(back, `${args.lang} after sign-in the tab is back on the AE form`);
    check(value === typed, `${args.lang} the typed text is restored (${JSON.stringify(value)})`);
    if (back) await field.scrollIntoViewIfNeeded();
    const file = await shot(page, "sae_form");
    record("sae_form", 3, back && value === typed, file, "plus the fields; 0 taps to get the text back after sign-in");
    await ctx.close(); // not saved: the seeded record stays as it was
  },
};

(async () => {
  const browser = await chromium.launch();
  const state = {};
  try {
    await setFlag(browser);
    for (const name of args.tasks || Object.keys(TASKS)) {
      try {
        await TASKS[name](browser, state);
      } catch (e) {
        check(false, `${args.lang} ${name}: ${e.message.split("\n")[0]}`);
      }
    }
  } finally {
    await browser.close();
  }
  const failed = checks.filter((c) => !c.ok);
  console.log(JSON.stringify({ lang: args.lang, checks: checks.length, failed: failed.length, failures: failed.map((c) => c.what), results }));
})();
