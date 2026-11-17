// H-10 (D-1121): the new-study walk in a browser, driven by tests/e2e/test_new_study_walk.py. Node Playwright with the
// preinstalled Chromium; never runs `playwright install`.
//
//   node tests/e2e/new_study_walk.js '<the plan as JSON>'
//
// The plan is tests/e2e/new_study_walk_plan.py's plan_json: one page language, one new ruleset id, every text
// resolved from the console's own catalogue. This file knows no text of its own: it finds links and buttons by
// their role and exact name, fields by their label, and the console's existing data-testid marks. It waits on page
// states, never on time. One JSON line on stdout; exit 1 on a failed check.
//
// The plan's "accounts": {"mode": "four", "password": ..., "coordinator": user, "steward": ..., ...} signs each role in
// with its own account; {"mode": "one", "password": ..., "person": user} signs one person in and switches the acting
// role (D-1063) on the account page before each step. When the box offers no acting role the walk stops at once and
// prints {"skipped": "not available on this box: <what the box showed>"}.
"use strict";

const { chromium } = require("playwright");

const plan = JSON.parse(process.argv[2] || "{}");
const base = plan.base;
const acc = plan.accounts;
const checks = [];
const ctx = {}; // role (or "person") -> page
let job = "";
let current = "";

function check(ok, what) {
  checks.push({ ok: !!ok, what });
  if (!ok) {
    console.error("FAIL: " + what);
    process.exitCode = 1;
  }
  return !!ok;
}

function esc(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

async function signIn(browser, user) {
  // the sign-in page opens in the browser's language (console.i18n.pick_language): the plan's
  const locale = { en: "en-US", "zh-TW": "zh-TW", ja: "ja-JP" }[plan.lang];
  const c = await browser.newContext({ locale, extraHTTPHeaders: { "Accept-Language": plan.lang } });
  const p = await c.newPage();
  p.setDefaultTimeout(30000);
  await p.goto(base + "/login", { waitUntil: "load" });
  await p.fill("#username", user);
  await p.fill("#password", acc.password);
  await Promise.all([
    p.waitForLoadState("load"),
    p.getByRole("button", { name: plan.signin, exact: true }).click(),
  ]);
  await p.waitForSelector("[data-testid=whoami]", { state: "attached" });
  await chooseLanguage(p, plan.language_label, plan.language_apply, 30);
  return p;
}

// The header's language form (its select has the id "lang"). Before the switch the page is in the account's own
// language, so the form is found by its id; after it, the label and the button must read as the plan's language says.
async function chooseLanguage(p, label, apply, waitS) {
  const form = p.locator("header form").filter({ has: p.locator("#lang") });
  await form.locator("#lang").selectOption(plan.lang);
  await click(p, form.locator("button[type=submit]"), waitS);
  const again = p.locator("header form").filter({ has: p.locator("#lang") });
  check((await p.getAttribute("html", "lang")) === plan.lang, `the page is in ${plan.lang} after the switch`);
  check((await again.getByLabel(label, { exact: true }).count()) === 1, `the language box is labelled "${label}"`);
  check((await again.getByRole("button", { name: apply, exact: true }).count()) === 1, `its button reads "${apply}"`);
}

// D-1063: the acting-role choice the account page offers, read from the page (a select or radios whose values are
// console roles). Returns null when there is none, with what the page showed instead.
async function actingRoleControl(p) {
  await p.goto(base + "/account", { waitUntil: "load" });
  const sel = p.locator("main select").filter({ has: p.locator("option[value=coordinator]") });
  if ((await sel.count()) > 0) return { kind: "select", el: sel.first() };
  const radio = p.locator("main input[type=radio][value=coordinator]");
  if ((await radio.count()) > 0) return { kind: "radio" };
  return null;
}

const CONSOLE_ROLE = { coordinator: "coordinator", steward: "steward", investigator: "investigator", operator: "admin" };

async function actAs(browser, role) {
  if (acc.mode === "four") {
    if (!ctx[role]) ctx[role] = await signIn(browser, acc[role]);
    return ctx[role];
  }
  if (!ctx.person) ctx.person = await signIn(browser, acc.person);
  const p = ctx.person;
  if (current !== role) {
    const control = await actingRoleControl(p);
    if (!control) return null;
    const value = CONSOLE_ROLE[role];
    const form = control.kind === "select" ? control.el.locator("xpath=ancestor::form") : p.locator("main form").filter({ has: p.locator(`input[type=radio][value=${value}]`) });
    if (control.kind === "select") await control.el.selectOption(value);
    else await p.check(`main input[type=radio][value=${value}]`);
    await Promise.all([p.waitForLoadState("load"), form.locator("button[type=submit]").first().click()]);
    current = role;
  }
  return p;
}

async function settle(p) {
  await p.waitForLoadState("load");
  const m = new URL(p.url()).pathname.match(/^\/pilot\/jobs\/([0-9A-HJKMNP-TV-Z]{26})/);
  if (m && !job) job = m[1];
}

async function click(p, locator, waitS) {
  await Promise.all([
    p.waitForEvent("framenavigated", { timeout: waitS * 1000 }),
    locator.click({ noWaitAfter: true }),
  ]);
  await p.waitForLoadState("load", { timeout: waitS * 1000 });
  await settle(p);
}

async function act(p, a, tag) {
  const exact = { exact: true };
  switch (a.do) {
    case "signin":
      return;
    case "language":
      return chooseLanguage(p, a.label, a.text, a.wait_s);
    case "nav":
      return click(p, p.getByRole("navigation", { name: "main" }).getByRole("link", { name: a.text, exact: true }), a.wait_s);
    case "more":
      await p.locator("[data-testid=nav-more] summary").filter({ hasText: plan.more }).click();
      return click(p, p.locator("[data-testid=nav-more]").getByRole("link", { name: a.text, exact: true }), a.wait_s);
    case "link":
      return click(p, p.locator("main").getByRole("link", { name: a.text, exact: true }).first(), a.wait_s);
    case "row_link":
      return click(p, p.getByRole("row").filter({ hasText: a.within }).getByRole("link", { name: a.text, exact: true }), a.wait_s);
    case "fill":
      return p.locator("main").getByLabel(a.label, exact).fill(a.value);
    case "select":
      return p.locator("main").getByLabel(a.label, exact).selectOption(a.value);
    case "radio":
      return p.locator("main").getByLabel(a.label, exact).check();
    case "button":
      return click(p, p.locator("main").getByRole("button", { name: a.text, exact: true }), a.wait_s);
    case "form": {
      const button = p.getByRole("button", { name: a.text, exact: true });
      const form = p.locator("main form").filter({ has: button });
      await form.locator("select").selectOption(a.value);
      return click(p, form.getByRole("button", { name: a.text, exact: true }), a.wait_s);
    }
    case "open_all": {
      // every amber row's "Open", one by one: each opens the row and reloads the page (the PI's check, D-146)
      const link = () => p.locator("main").getByRole("link", { name: a.text, exact: true });
      let n = 0;
      while ((await link().count()) > 0 && n < 50) {
        await click(p, link().first(), a.wait_s);
        n += 1;
      }
      return check(n > 0 && (await link().count()) === 0, `${tag}: every amber row opened (${n})`);
    }
    case "label_all": {
      // D-309: a zh-TW or ja page asks a short label of each pasted criterion before approval
      if (plan.lang === "en") return;
      const missing = () => p.locator("main [data-testid^=label-missing-]");
      let n = 0;
      while ((await missing().count()) > 0 && n < 50) {
        const id = (await missing().first().getAttribute("data-testid")).replace("label-missing-", "");
        const form = p.locator("main form").filter({ has: p.locator(`[data-testid="label-${id}"]`) });
        await form.locator(`[data-testid="label-${id}"]`).fill(plan.labels[id] || id);
        await click(p, form.getByRole("button", { name: a.text, exact: true }), a.wait_s);
        n += 1;
      }
      return check((await missing().count()) === 0, `${tag}: every criterion has a ${plan.lang} label (${n} given)`);
    }
    case "see":
      return see(p, a, tag);
    default:
      throw new Error("unknown action " + a.do);
  }
}

async function see(p, a, tag) {
  const path = new URL(p.url()).pathname;
  switch (a.kind) {
    case "h1": {
      const h = (await p.locator("main h1").first().innerText()).replace(/\s+/g, " ");
      return check(h.includes(a.text), `${tag}: heading has "${a.text}" (${h}) at ${path}`);
    }
    case "state": {
      const s = await p.getAttribute("[data-testid=job-state]", "data-state");
      return check(s === a.value, `${tag}: job state ${a.value} (${s}) at ${path}`);
    }
    case "shown":
      return check((await p.locator(`[data-testid="${a.value}"]`).count()) > 0, `${tag}: shows ${a.value} at ${path}`);
    case "gone":
      return check((await p.locator(`[data-testid="${a.value}"]`).count()) === 0, `${tag}: no ${a.value} at ${path}`);
    case "says": {
      const t = (await p.locator("main").innerText()).replace(/\s+/g, " ");
      return check(t.includes(a.text.replace(/\s+/g, " ")), `${tag}: says "${a.text.slice(0, 80)}" at ${path}`);
    }
    case "path":
      return check(new RegExp(a.value).test(path), `${tag}: path ${a.value} (${path})`);
    default:
      throw new Error("unknown expectation " + a.kind);
  }
}

// A role boundary: the request the page would send, with the page's own form token (every signed-in page has one in
// its header), must be answered 403 with the product's refusal page.
async function refuse(browser, r, tag) {
  const p = await actAs(browser, r.role);
  if (!p) return false;
  const path = r.path.replace("{job}", job);
  const out = await p.evaluate(
    async ([method, path, fields]) => {
      const csrf = (document.querySelector("input[name=csrf]") || {}).value || "";
      const init = { method, redirect: "manual" };
      if (method === "POST") init.body = new URLSearchParams({ csrf, ...fields });
      const res = await fetch(path, init);
      const html = await res.text();
      const doc = new DOMParser().parseFromString(html, "text/html");
      const h = doc.querySelector("main h1");
      return { status: res.status, h1: h ? h.textContent.trim() : "" };
    },
    [r.method, path, r.fields],
  );
  return check(
    out.status === 403 && out.h1.includes(plan.forbidden),
    `${tag}: ${r.role} ${r.method} ${path} refused (${out.status}, "${out.h1}")`,
  );
}

(async () => {
  const browser = await chromium.launch();
  const t0 = Date.now();
  let skipped = "";
  try {
    for (const st of plan.steps) {
      const tag = `step ${st.n} (${st.role}, ${plan.lang})`;
      const p = await actAs(browser, st.role);
      if (!p) {
        skipped = "not available on this box: its account page (/account) offers no acting-role choice (D-1063)";
        break;
      }
      try {
        for (const a of st.acts) await act(p, a, tag);
        for (const r of st.refusals) await refuse(browser, r, tag);
      } catch (e) {
        check(false, `${tag}: ${e.message.split("\n")[0]} at ${new URL(p.url()).pathname}`);
        break;
      }
      if (checks.some((c) => !c.ok)) break; // a later step stands on this one
    }
  } finally {
    await browser.close();
  }
  const failed = checks.filter((c) => !c.ok);
  console.log(
    JSON.stringify({
      lang: plan.lang,
      rs: plan.rs,
      skipped,
      checks: checks.length,
      failed: failed.length,
      failures: failed.map((c) => c.what),
      seconds: Math.round((Date.now() - t0) / 1000),
    }),
  );
})();
