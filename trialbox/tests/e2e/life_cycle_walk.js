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
// H-21 (D-1138): with the plan's "viewport" (a phone: {"width": 390, "height": 844}) the same walk runs in a phone-sized
// browser and measures every page it reaches and every control it clicks: a horizontal page scroll, a control off the
// screen or covered by another, a tap target under the size the spec names, text cut, a table wider than the screen.
// Each measure goes to the step's "layout" in the log, with a screenshot in the plan's "shots" folder (outside the
// repository). A control the phone cannot reach stops the step with what Playwright saw (a reasoned stop).
//
// One JSON line on stdout; exit 1 on a failed check.
"use strict";

const fs = require("fs");
const { chromium } = require("playwright");

const plan = JSON.parse(process.argv[2] || "{}");
const phone = plan.viewport || null; // H-21: a phone-sized walk measures its pages
const seen = new Set(); // layout measures already logged (step, kind, path, what)
const base = plan.base;
const acc = plan.accounts;
const checks = [];
const ctx = {}; // role (or "person") -> page
const vars = { job: "" }; // values read from the product on the way ({job}, {pid}, {short}, {record}, {chart})
const stopped = new Set(); // steps stopped with a recorded finding
let current = "";
let rec = null; // the record of the step being walked
let phoneStop = 0; // H-21: the step where the phone could not go on

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
  const view = phone ? { viewport: { width: phone.width, height: phone.height }, isMobile: true, hasTouch: true } : {};
  const c = await browser.newContext({ locale, extraHTTPHeaders: { "Accept-Language": plan.lang }, ...view });
  const p = await c.newPage();
  p.setDefaultTimeout(30000);
  await p.goto(base + "/login", { waitUntil: "load" });
  await measure(p);
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

// H-21 (D-133): on a phone the menu, the language and Sign out sit behind one "Menu" button. Its label is hidden from
// assistive technology (aria-hidden), so it is found by its data-testid, and the walk records that.
async function openMenu(p) {
  if (!phone) return;
  const toggle = p.locator("#menu-toggle");
  if (!(await toggle.count()) || (await toggle.isChecked())) return;
  const button = p.locator("[data-testid=menu-button]");
  const label = ((await button.innerText().catch(() => "")) || "").replace(/\s+/g, " ").trim();
  const back = p.locator("main [data-testid=sheet-back]");
  if ((await reachable(p, button, label)) && (await back.count()) && (await back.isVisible())) {
    // the patient sheet's bar covers the Menu button: the sheet's own Back first, as a person would
    const text = ((await back.innerText()) || "").replace(/\s+/g, " ").trim();
    await Promise.all([p.waitForEvent("framenavigated"), back.click()]);
    await p.waitForLoadState("load");
    clicked(text);
    await measure(p);
  }
  await button.click();
  clicked(label);
  await note(p, "behind the menu", `"${label}" (aria-hidden, found by data-testid menu-button) opened before the top bar's links, the language or More`);
  await measure(p);
}

async function chooseLanguage(p, label, apply, waitS) {
  await openMenu(p);
  const form = p.locator("header form").filter({ has: p.locator("#lang") });
  await form.locator("#lang").selectOption(plan.lang);
  await click(p, form.locator("button[type=submit]"), waitS, apply);
  const again = p.locator("header form").filter({ has: p.locator("#lang") });
  check((await p.getAttribute("html", "lang")) === plan.lang, `the page is in ${plan.lang} after the switch`);
  check((await again.getByLabel(label, { exact: true }).count()) === 1, `the language box is labelled "${label}"`);
  check((await again.getByRole("button", { name: apply, exact: true, includeHidden: !!phone }).count()) === 1, `its button reads "${apply}"`);
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
  await reachable(p, locator, text);
  await Promise.all([
    p.waitForEvent("framenavigated", { timeout: waitS * 1000 }),
    locator.click({ noWaitAfter: true }),
  ]);
  await p.waitForLoadState("load", { timeout: waitS * 1000 });
  await settle(p);
  clicked(text);
  await measure(p);
}

// the text of a page's alert (an error or a refusal), as the product wrote it
async function alertText(p) {
  const a = p.locator("main [role=alert], main .error");
  return (await a.count()) ? (await a.first().innerText()).replace(/\s+/g, " ").trim() : "";
}

// ------------------------------------------------------------------------------------------- H-21: the phone's measures
// What a phone-sized page shows that does not fit, measured in the page (D-1138). The rules are the UI spec's
// (docs/plan/design/09-ui-ux-spec.md §10 and its WCAG table): no horizontal page scroll at 390 px (1.4.10, FR-UI-09);
// targets at least 24 x 24 px, the PI's mark buttons at least 44 x 44 px on a phone (2.5.8); and the card's 44 px for
// every other control, logged as its own kind. A control inside a box that scrolls on its own (a wide table's frame)
// is not "off the screen": the table is logged as wide instead.
function pageMeasures() {
  const vw = document.documentElement.clientWidth;
  const out = { hscroll: Math.max(0, document.documentElement.scrollWidth - vw), off: [], small24: [], small44: [], mark44: [], cut: [], wide: [] };
  // shown to a sighted person now: not a screen-reader-only label (1 px, clipped) and not a skip link waiting off the
  // screen for keyboard focus
  const shown = (e) => {
    const r = e.getBoundingClientRect();
    const s = getComputedStyle(e);
    if (r.width <= 1 || r.height <= 1 || s.visibility === "hidden" || s.display === "none") return false;
    if (s.clip && s.clip !== "auto") return false;
    if (s.clipPath && s.clipPath !== "none") return false;
    if ((s.position === "absolute" || s.position === "fixed") && (r.right <= 0 || r.bottom <= 0)) return false;
    return !e.closest("details:not([open]) > :not(summary)");
  };
  const scroller = (e) => {
    for (let a = e.parentElement; a && a !== document.body; a = a.parentElement) {
      const ox = getComputedStyle(a).overflowX;
      if ((ox === "auto" || ox === "scroll") && a.scrollWidth > a.clientWidth + 1) return a;
    }
    return null;
  };
  const name = (e) => (e.getAttribute("aria-label") || e.innerText || e.value || e.getAttribute("data-testid") || e.id || e.tagName).replace(/\s+/g, " ").trim().slice(0, 50);
  const ctrls = [...document.querySelectorAll("a[href], button, input:not([type=hidden]), select, textarea, summary")].filter(shown);
  for (const e of ctrls) {
    const r = e.getBoundingClientRect();
    if (!scroller(e) && (r.right > vw + 1 || r.left < -1)) out.off.push(name(e));
    // a link inside running text is exempt (WCAG 2.5.8 "inline"); a check box or radio is measured with its label
    const inline = e.tagName === "A" && !e.classList.contains("button") && getComputedStyle(e).display === "inline" && !!e.closest("p, li, td, dd, span");
    if (inline || e.type === "checkbox" || e.type === "radio") continue;
    const size = `${name(e)} ${Math.round(r.width)}x${Math.round(r.height)}`;
    const mark = e.name === "mark" || (e.dataset.testid || "").match(/^(approach|need_info|not_suitable|not_now)-/);
    if (r.width < 24 || r.height < 24) out.small24.push(size);
    else if (mark && (r.width < 44 || r.height < 44)) out.mark44.push(size);
    else if (r.width < 44 || r.height < 44) out.small44.push(size);
  }
  for (const e of document.querySelectorAll("h1, h2, h3, button, a.button, label, th, .pill")) {
    if (!shown(e)) continue;
    const s = getComputedStyle(e);
    if ((s.overflowX === "hidden" || s.overflowX === "clip" || s.textOverflow === "ellipsis") && e.scrollWidth > e.clientWidth + 1) out.cut.push(name(e));
  }
  for (const t of document.querySelectorAll("table")) {
    if (!shown(t)) continue;
    const r = t.getBoundingClientRect();
    if (r.width > vw + 1) out.wide.push(`${t.dataset.testid || t.className || "table"} ${Math.round(r.width)} px${scroller(t) ? ", scrolls in its own frame" : ", the page scrolls"}`);
  }
  return out;
}

async function shot(p, kind) {
  if (!plan.shots || !rec) return "";
  const file = `${plan.shots}/${plan.lang}-step${rec.n}-${kind}-${rec.layout.length}.png`;
  await p.screenshot({ path: file, fullPage: false }).catch(() => {});
  return file.split("/").pop();
}

async function note(p, kind, what) {
  if (!rec) return;
  const path = masked(new URL(p.url()).pathname);
  const key = `${rec.n} ${kind} ${path} ${what}`;
  if (seen.has(key)) return;
  seen.add(key);
  rec.layout.push({ kind, path, what: masked(what), shot: await shot(p, kind) });
}

async function measure(p) {
  if (!phone || !rec) return;
  const m = await p.evaluate(pageMeasures);
  if (m.hscroll > 0) await note(p, "page scrolls sideways", `${m.hscroll} px wider than the screen`);
  for (const [kind, list] of [["off the screen", m.off], ["target under 24 px", m.small24], ["mark button under 44 px", m.mark44],
    ["target under 44 px", m.small44], ["text cut", m.cut], ["table wider than the screen", m.wide]]) {
    if (list.length) await note(p, kind, `${list.length}: ${[...new Set(list)].slice(0, 6).join("; ")}`);
  }
}

// before a click on a phone: the control on the screen and not covered (what the finger would hit)
async function reachable(p, locator, text) {
  if (!phone) return;
  await locator.scrollIntoViewIfNeeded({ timeout: 5000 }).catch(() => {});
  const hit = await locator.evaluate((e) => {
    const r = e.getBoundingClientRect();
    const x = r.left + r.width / 2;
    const y = r.top + r.height / 2;
    if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) return "off";
    const top = document.elementFromPoint(x, y);
    if (!top || top === e || e.contains(top) || top.contains(e)) return "";
    return (top.getAttribute("data-testid") || top.className || top.tagName).toString().slice(0, 40);
  }).catch(() => "");
  if (hit === "off") await note(p, "off the screen", `the control "${text}" stays off the screen after scrolling`);
  else if (hit) await note(p, "covered", `the control "${text}" is covered by ${hit}`);
  return hit;
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
      await openMenu(p);
      return click(p, p.getByRole("navigation", { name: "main" }).getByRole("link", { name: text, exact: true }), a.wait_s, text);
    case "more":
      {
        await openMenu(p);
        const more = p.locator("[data-testid=nav-more] summary").filter({ hasText: plan.more });
        await reachable(p, more, plan.more);
        await more.click();
        clicked(plan.more);
        await measure(p);
      }
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
      await settle(p);
      return measure(p);
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
  if (!ok && phone) {
    // H-21: what the desktop page shows and the phone's does not is a measure of the phone, recorded (a finding must
    // name it) rather than a failed check
    await note(p, "not shown on the phone", what);
    return false;
  }
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
              clicks: [], inputs: [], read: {}, layout: [], guesses: [...(st.guesses || [])], refusals: [], stopped: null };
      steps.push(rec);
      if ((st.after || []).some((n) => stopped.has(n)) || phoneStop) {
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
        const why = e.message.split("\n")[0];
        if (phone) {
          // H-21: on a phone a control that cannot be reached stops the walk there, with what Playwright saw; the
          // later steps stand on it
          await note(p, "cannot be reached", why.slice(0, 200));
          rec.stopped = { finding: "phone", why: "a control the phone cannot reach", page: masked(why.slice(0, 300)), path: masked(new URL(p.url()).pathname) };
          stopped.add(rec.n);
          phoneStop = rec.n;
        } else {
          check(false, `${tag}: ${why} at ${new URL(p.url()).pathname}`);
        }
      }
      rec.path = masked(new URL(p.url()).pathname);
      rec.heading = masked(await heading(p));
      rec.seconds = Math.round((Date.now() - t1) / 100) / 10;
      await measure(p);
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
