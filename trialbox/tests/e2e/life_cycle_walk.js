// H-20 (D-1135): the whole-life-cycle walk in a browser, driven by tests/e2e/test_life_cycle_walk.py. Node Playwright
// with the preinstalled Chromium; never runs `playwright install`.
//
//   node tests/e2e/life_cycle_walk.js '<the plan as JSON>'
//
// The plan is tests/e2e/life_cycle_walk_plan.py's plan_json: one page language, one new ruleset id, every text
// resolved from the console's own catalogue; H-10's eleven steps (tests/e2e/new_study_walk_plan.py) unchanged, then
// the life-cycle steps. It finds links and buttons by their role and exact name, fields by their label; where the
// plan must find a thing another way (a data-testid, an address typed in) the act says so and the walk records it as
// a guess. It waits on page states, never on time.
//
// It records, per step, in the JSON file the plan's "log" names (outside the repository): the page reached (path and
// heading), the clicks from the previous step's page (count and texts), the time, the guesses and the refusals. A
// "stop" act is a reasoned stop read from the product: where the page shows what the plan names (the product does not
// do what its documents say, or the box lacks what the step needs), the walk records the page's own words and goes on
// with the next step that does not stand on this one; it never asserts the fault as correct.
//
// One JSON line on stdout; exit 1 on a failed check.
"use strict";

const fs = require("fs");
const { chromium } = require("playwright");

const plan = JSON.parse(process.argv[2] || "{}");
const base = plan.base;
const acc = plan.accounts;
const checks = [];
const ctx = {}; // role (or "person") -> page
const vars = { job: "" }; // values read from the product on the way ({job}, {pid}, {short}, {record}, {chart})
const stopped = new Set(); // steps stopped with a recorded finding
let current = "";
let rec = null; // the record of the step being walked

function check(ok, what) {
  checks.push({ ok: !!ok, what });
  if (!ok) {
    console.error("FAIL: " + what);
    process.exitCode = 1;
  }
  return !!ok;
}

function fill(s) {
  return String(s || "").replace(/\{(job|pid|record|short|chart)\}/g, (_, k) => vars[k] || "");
}

// what the log may hold: never a pseudonym in full or a chart number, only their names
function masked(s) {
  let out = String(s || "");
  for (const k of ["chart", "pid"]) if (vars[k]) out = out.split(vars[k]).join(`{${k}}`);
  return out;
}

function guess(a) {
  if (rec && a.finding) rec.guesses.push({ finding: a.finding, detail: a.guess });
}

function clicked(text) {
  if (rec) rec.clicks.push(masked(text));
}

async function signIn(browser, user) {
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
  clicked(plan.signin);
  await chooseLanguage(p, plan.language_label, plan.language_apply, 30);
  return p;
}

async function chooseLanguage(p, label, apply, waitS) {
  const form = p.locator("header form").filter({ has: p.locator("#lang") });
  await form.locator("#lang").selectOption(plan.lang);
  await click(p, form.locator("button[type=submit]"), waitS, apply);
  const again = p.locator("header form").filter({ has: p.locator("#lang") });
  check((await p.getAttribute("html", "lang")) === plan.lang, `the page is in ${plan.lang} after the switch`);
  check((await again.getByLabel(label, { exact: true }).count()) === 1, `the language box is labelled "${label}"`);
  check((await again.getByRole("button", { name: apply, exact: true }).count()) === 1, `its button reads "${apply}"`);
}

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
  if (m && !vars.job) vars.job = m[1];
}

async function click(p, locator, waitS, text) {
  await Promise.all([
    p.waitForEvent("framenavigated", { timeout: waitS * 1000 }),
    locator.click({ noWaitAfter: true }),
  ]);
  await p.waitForLoadState("load", { timeout: waitS * 1000 });
  await settle(p);
  clicked(text);
}

// the text of a page's alert (an error or a refusal), as the product wrote it
async function alertText(p) {
  const a = p.locator("main [role=alert], main .error");
  return (await a.count()) ? (await a.first().innerText()).replace(/\s+/g, " ").trim() : "";
}

async function act(p, a, tag) {
  const exact = { exact: true };
  const text = fill(a.text);
  const value = fill(a.value);
  switch (a.do) {
    case "signin":
      return;
    case "language":
      return chooseLanguage(p, a.label, a.text, a.wait_s);
    case "nav":
      return click(p, p.getByRole("navigation", { name: "main" }).getByRole("link", { name: text, exact: true }), a.wait_s, text);
    case "more":
      await p.locator("[data-testid=nav-more] summary").filter({ hasText: plan.more }).click();
      clicked(plan.more);
      return click(p, p.locator("[data-testid=nav-more]").getByRole("link", { name: text, exact: true }), a.wait_s, text);
    case "link":
      return click(p, p.locator("main").getByRole("link", { name: text, exact: true }).first(), a.wait_s, text);
    case "row_link":
      return click(p, p.getByRole("row").filter({ hasText: fill(a.within) }).getByRole("link", { name: text, exact: true }), a.wait_s, text);
    case "link_start": {
      // a link whose name starts with the product's text (the worklist's list links end with their count)
      guess(a);
      const re = new RegExp("^\\s*" + text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
      return click(p, p.locator("main").getByRole("link", { name: re }).first(), a.wait_s, text);
    }
    case "card_link": {
      // the link in the card whose heading is ``within`` (the home page's study card)
      guess(a);
      const card = p.locator("main section").filter({ has: p.getByRole("heading", { name: fill(a.within), exact: true }) });
      return click(p, card.getByRole("link", { name: text, exact: true }).first(), a.wait_s, text);
    }
    case "fill":
      if (rec) rec.inputs.push(a.label);
      return p.locator("main").getByLabel(a.label, exact).first().fill(value);
    case "select":
      if (rec) rec.inputs.push(a.label);
      return p.locator("main").getByLabel(a.label, exact).first().selectOption(value);
    case "radio":
      clicked(a.label);
      return p.locator("main").getByLabel(a.label, exact).check();
    case "button":
      return click(p, p.locator("main").getByRole("button", { name: text, exact: true }).first(), a.wait_s, text);
    case "form": {
      const button = p.getByRole("button", { name: text, exact: true });
      const form = p.locator("main form").filter({ has: button });
      await form.locator("select").selectOption(value);
      return click(p, form.getByRole("button", { name: text, exact: true }), a.wait_s, text);
    }
    case "goto":
      // a page reached only by typing its address: a guess, recorded
      guess(a);
      await p.goto(base + value, { waitUntil: "load" });
      clicked(`(typed) ${masked(value)}`);
      return settle(p);
    case "first_row_link": {
      // the first row of the table ``data-testid=within``: the tester picks one by a name only the product knows
      guess(a);
      const link = p.locator(`main [data-testid="${a.within}"] tbody tr`).first().getByRole("link").first();
      const label = (await link.innerText()).replace(/\s+/g, " ").trim();
      return click(p, link, a.wait_s, label);
    }
    case "remember": {
      // a value the product shows, kept for a later step: from the address (``value``: a regular expression with
      // one group) or from the element ``within`` (a CSS selector)
      guess(a);
      if (a.within) {
        const el = p.locator(a.within).first();
        vars[a.label] = ((await el.count()) ? await el.innerText() : "").replace(/\s+/g, " ").trim();
      } else {
        const u = new URL(p.url());
        const m = (u.pathname + u.search).match(new RegExp(a.value));
        vars[a.label] = m ? decodeURIComponent(m[1]) : "";
      }
      if (a.label === "pid" && vars.pid) vars.short = vars.pid.slice(0, 8);
      return check(vars[a.label], `${tag}: read the ${a.label} from the page`);
    }
    case "worker_ran": {
      // H-25 (D-1124): the opt-out worker's next run after the opt-out, as the audit trail shows it. The newest run on
      // the page when the steward opens it is noted; the walk then waits on the product's own page (read again every
      // 2 s, up to wait_s) for a newer one. The page shows the run, not what it did (F-22): the clears are read from
      // the audit log by the test (test_life_cycle_walk.py), and step 22 reads the health check.
      const row = 'tr[data-event="optout.worker"]';
      const first = async () => (await p.locator(`main ${row}`).count()) ? await p.locator(`main ${row} td[title]`).first().getAttribute("title") : "";
      const before = await first();
      const url = new URL(p.url());
      await p.waitForFunction(
        ([path, before, row]) => {
          const x = new XMLHttpRequest();
          x.open("GET", path, false);
          x.send();
          const d = new DOMParser().parseFromString(x.responseText, "text/html");
          const cell = d.querySelector(`${row} td[title]`);
          return !!cell && cell.getAttribute("title") !== before;
        },
        [url.pathname + url.search, before, row],
        { polling: 2000, timeout: a.wait_s * 1000 },
      );
      await p.reload({ waitUntil: "load" });
      await settle(p);
      const after = await first();
      check(after && after !== before, `${tag}: the audit trail shows a run of the opt-out worker after the opt-out`);
      const detail = ((await p.locator(`main ${row} td[data-src=audit]`).first().textContent()) || "").trim();
      if (!detail) guess({ finding: a.finding, guess: "the run's detail is empty on the page" });
      if (rec) rec.read.worker = masked(detail.slice(0, 300)) || "(no detail on the page)";
      return;
    }
    case "read": {
      // a text the product shows, kept in the log (what a finding quotes)
      const els = p.locator(a.within);
      const texts = [];
      for (let i = 0; i < Math.min(await els.count(), 12); i++) texts.push((await els.nth(i).innerText()).replace(/\s+/g, " ").trim());
      if (rec) rec.read[a.label] = masked(texts.join(" | "));
      return;
    }
    case "open_all": {
      const link = () => p.locator("main").getByRole("link", { name: text, exact: true });
      let n = 0;
      while ((await link().count()) > 0 && n < 50) {
        await click(p, link().first(), a.wait_s, text);
        n += 1;
      }
      return check(n > 0 && (await link().count()) === 0, `${tag}: every amber row opened (${n})`);
    }
    case "label_all": {
      if (plan.lang === "en") return;
      const missing = () => p.locator("main [data-testid^=label-missing-]");
      let n = 0;
      while ((await missing().count()) > 0 && n < 50) {
        const id = (await missing().first().getAttribute("data-testid")).replace("label-missing-", "");
        const form = p.locator("main form").filter({ has: p.locator(`[data-testid="label-${id}"]`) });
        await form.locator(`[data-testid="label-${id}"]`).fill(plan.labels[id] || id);
        await click(p, form.getByRole("button", { name: text, exact: true }), a.wait_s, text);
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

async function holds(p, a) {
  const text = fill(a.text);
  const value = fill(a.value);
  const path = new URL(p.url()).pathname;
  switch (a.kind) {
    case "h1": {
      const h = (await p.locator("main h1").first().innerText()).replace(/\s+/g, " ");
      return [h.includes(text), `heading has "${text}" (${h}) at ${path}`];
    }
    case "state": {
      const s = await p.getAttribute("[data-testid=job-state]", "data-state");
      return [s === value, `job state ${value} (${s}) at ${path}`];
    }
    case "shown":
      return [(await p.locator(`[data-testid="${value}"]`).count()) > 0, `shows ${value} at ${path}`];
    case "gone":
      return [(await p.locator(`[data-testid="${value}"]`).count()) === 0, `no ${value} at ${path}`];
    case "says": {
      const t = (await p.locator("main").innerText()).replace(/\s+/g, " ");
      return [t.includes(text.replace(/\s+/g, " ")), `says "${text.slice(0, 80)}" at ${path}`];
    }
    case "path":
      return [new RegExp(value).test(path), `path ${value} (${path})`];
    case "body": {
      // the response's own text (a page with no main part, such as /metrics)
      const t = await p.evaluate(() => document.body.innerText);
      return [t.includes(value), `the response holds "${value}" at ${path}`];
    }
    default:
      throw new Error("unknown expectation " + a.kind);
  }
}

async function see(p, a, tag) {
  const [ok, what] = await holds(p, a);
  return check(ok, `${tag}: ${what}`);
}

// A reasoned stop: when the page shows what ``a`` names, the step stops with the product's own words recorded.
async function stopIf(p, a, tag) {
  const [ok] = await holds(p, a);
  if (!ok) return false;
  const words = (await alertText(p)) || fill(a.value);
  rec.stopped = { finding: a.finding, why: a.why, page: masked(words), path: masked(new URL(p.url()).pathname) };
  stopped.add(rec.n);
  console.error(`STOP: ${tag}: ${a.why} (${words})`);
  return true;
}

async function refuse(browser, r, tag) {
  const p = await actAs(browser, r.role);
  if (!p) return false;
  const path = fill(r.path);
  const fields = Object.fromEntries(Object.entries(r.fields).map(([k, v]) => [k, fill(v)]));
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
    [r.method, path, fields],
  );
  if (rec) rec.refusals.push({ role: r.role, request: masked(`${r.method} ${path}`), status: out.status });
  return check(
    out.status === 403 && out.h1.includes(plan.forbidden),
    `${tag}: ${r.role} ${r.method} ${path} refused (${out.status}, "${out.h1}")`,
  );
}

async function heading(p) {
  const h = p.locator("main h1");
  return (await h.count()) ? (await h.first().innerText()).replace(/\s+/g, " ").trim() : "";
}

(async () => {
  const browser = await chromium.launch();
  const t0 = Date.now();
  const steps = [];
  let skipped = "";
  try {
    for (const st of plan.steps) {
      const tag = `step ${st.n} (${st.role}, ${plan.lang})`;
      const t1 = Date.now();
      rec = { n: st.n, key: st.key, role: st.role, lane: st.lane, lang: plan.lang, at: new Date().toISOString(),
              clicks: [], inputs: [], read: {}, guesses: [...(st.guesses || [])], refusals: [], stopped: null };
      steps.push(rec);
      if ((st.after || []).some((n) => stopped.has(n))) {
        rec.stopped = { finding: "", why: "stands on a step that stopped", page: "", path: "" };
        stopped.add(st.n);
        continue;
      }
      const p = await actAs(browser, st.role);
      if (!p) {
        skipped = "not available on this box: its account page (/account) offers no acting-role choice (D-1063)";
        break;
      }
      try {
        for (const a of st.acts) {
          if (a.do === "stop") {
            if (await stopIf(p, a, tag)) break;
            continue;
          }
          await act(p, a, tag);
        }
        if (!rec.stopped) for (const r of st.refusals) await refuse(browser, r, tag);
      } catch (e) {
        check(false, `${tag}: ${e.message.split("\n")[0]} at ${new URL(p.url()).pathname}`);
      }
      rec.path = masked(new URL(p.url()).pathname);
      rec.heading = masked(await heading(p));
      rec.seconds = Math.round((Date.now() - t1) / 100) / 10;
      if (checks.some((c) => !c.ok)) break; // a later step stands on this one
    }
  } finally {
    await browser.close();
  }
  const failed = checks.filter((c) => !c.ok);
  const out = {
    lang: plan.lang,
    rs: plan.rs,
    skipped,
    checks: checks.length,
    failed: failed.length,
    failures: failed.map((c) => c.what),
    stopped: steps.filter((s) => s.stopped).map((s) => s.n),
    seconds: Math.round((Date.now() - t0) / 1000),
  };
  if (plan.log) fs.writeFileSync(plan.log, JSON.stringify({ ...out, steps }, null, 1));
  console.log(JSON.stringify(out));
})();
