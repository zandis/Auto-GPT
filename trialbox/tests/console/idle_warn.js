// D-1370 (9g-19, A11Y-3): the idle warning in Chromium. The pages are the console's own, rendered by the console for
// tests/console/test_idle_warning.py (their path is the one argument), served here with the console's own
// Content-Security-Policy and stylesheet by a small local server; the browser's clock is moved forward with
// Playwright's clock, so nobody waits ten minutes. "/help?keep=1" stands for the console's answer to the warning's
// requests: the session's times (204 and two headers, as the console's need() answers them), or, once the test says the
// server ended the session, the console's redirect to the sign-in. "auto=1" (the check before the lock) is counted
// apart from "Stay signed in".
// Prints one JSON line: {case: result}. Synthetic data only.
"use strict";

const fs = require("fs");
const path = require("path");
const http = require("http");
const { chromium } = require("playwright");

const PAGES = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const CSS = fs.readFileSync(path.join(__dirname, "..", "..", "services", "console", "static", "console.css"), "utf8");
let BOX = "http://127.0.0.1";
const state = { ended: false, stay: 0, checks: 0, idleLeft: 600, absLeft: 28000 };
const reset = () => Object.assign(state, { ended: false, stay: 0, checks: 0, idleLeft: 600, absLeft: 28000 });

const server = http.createServer((req, res) => {
  const u = new URL(req.url, BOX);
  req.resume();
  const send = (type, body, extra = {}) => { res.writeHead(200, { "content-type": type, ...extra }); res.end(body); };
  if (u.pathname === "/static/console.css") return send("text/css", CSS);
  if (u.pathname === "/help" && u.searchParams.get("keep") === "1") {
    if (u.searchParams.get("auto") === "1") state.checks += 1; else state.stay += 1;
    if (state.ended) { res.writeHead(303, { location: "/login?why=idle" }); return res.end(); }
    res.writeHead(204, { "x-tb-idle-left": String(state.idleLeft), "x-tb-abs-left": String(state.absLeft) });
    return res.end();
  }
  if (u.pathname === "/late") { // the same page, delivered three seconds after it was asked for
    return setTimeout(() => send("text/html; charset=utf-8", PAGES.en, { "content-security-policy": PAGES.csp }), 3000);
  }
  if (u.pathname === "/login") return send("text/html", "<!doctype html><title>sign in</title>");
  const name = u.pathname.slice(1) || "en";
  if (!PAGES[name] || name === "csp") { res.writeHead(404); return res.end(); }
  return send("text/html; charset=utf-8", PAGES[name], { "content-security-policy": PAGES.csp, "cache-control": "no-store" });
});

const pause = (ms) => new Promise((r) => setTimeout(r, ms)); // Node's own clock, not the page's

async function until(p, fn, arg) {
  for (let i = 0; i < 100; i++) {
    if (await p.evaluate(fn, arg)) return true;
    await pause(50);
  }
  return false;
}

const look = (p) => p.evaluate(() => {
  const w = document.getElementById("idle-warn");
  const a = document.activeElement;
  return {
    hidden: w.hidden, state: w.getAttribute("data-state") || "", role: w.getAttribute("role"),
    title: document.getElementById("idle-warn-title").textContent,
    stay: w.querySelector("[data-idle-stay]").textContent, stay_hidden: w.querySelector("[data-idle-stay]").hidden,
    seen: w.checkVisibility() ? ["stay", "close"].filter((b) => w.querySelector(`[data-idle-${b}]`).checkVisibility()) : [],
    focus: (a && (a.getAttribute("data-testid") || a.id)) || "",
    typed: (document.getElementById("cmd-q") || {}).value,
  };
});

async function fresh(browser, name) {
  const ctx = await browser.newContext();
  const p = await ctx.newPage();
  await p.clock.install();
  await p.goto(`${BOX}/${name}`);
  return { ctx, p };
}

const CASES = {
  async warned_then_stayed(browser) {
    reset();
    const { ctx, p } = await fresh(browser, "en");
    await p.fill("#cmd-q", "half-typed note");
    await p.clock.runFor("08:58");
    const before = (await look(p)).hidden;
    await p.clock.runFor("00:03");
    const at = await look(p);
    if (process.env.TB_IDLE_SHOT) await p.screenshot({ path: process.env.TB_IDLE_SHOT }); // by hand: the warning, seen
    await p.keyboard.press("Enter"); // the focus is on "Stay signed in"
    await until(p, () => document.getElementById("idle-warn").hidden);
    const after = { ...(await look(p)), stay: state.stay };
    await p.clock.runFor("09:01");
    const again = await look(p);
    await p.keyboard.press("Escape"); // on the warning, Escape is "Stay signed in"
    await until(p, () => document.getElementById("idle-warn").hidden);
    const esc = { hidden: (await look(p)).hidden, stay_requests: state.stay };
    await ctx.close();
    return {
      at_8m58: before,
      at_9m01: { hidden: at.hidden, state: at.state, role: at.role, title: at.title, focus: at.focus, seen: at.seen },
      after_enter: { hidden: after.hidden, stay_requests: after.stay, focus: after.focus, typed: after.typed },
      again_9m01_after_the_press: { hidden: again.hidden, state: again.state }, escape: esc,
    };
  },
  async locked_keeps_the_text(browser) {
    reset();
    const { ctx, p } = await fresh(browser, "en");
    await p.fill("#cmd-q", "half-typed note");
    await p.clock.runFor("09:01");
    await p.keyboard.press("Enter");
    await until(p, () => document.getElementById("idle-warn").hidden);
    const url = p.url();
    state.ended = true; // nobody answers the second warning: the server locks the session
    await p.clock.runFor("10:01");
    await until(p, () => document.getElementById("idle-warn").getAttribute("data-state") === "locked");
    const got = await look(p);
    await p.click("[data-idle-close]");
    await p.clock.runFor("05:00");
    const closed = (await look(p)).hidden;
    await ctx.close();
    return {
      state: got.state, title: got.title, stay_hidden: got.stay_hidden, typed: got.typed, url_same: url === `${BOX}/en`,
      stay_requests: state.stay, focus: got.focus, closed_stays_closed: closed, seen: got.seen, checks: state.checks,
    };
  },
  async server_already_ended(browser) {
    reset();
    const { ctx, p } = await fresh(browser, "en");
    await p.clock.runFor("09:01");
    state.ended = true; // another tab signed out, or the box restarted: "Stay" meets the sign-in
    await p.click("[data-idle-stay]");
    await until(p, () => document.getElementById("idle-warn").getAttribute("data-state") === "locked");
    const got = await look(p);
    state.ended = false;
    await ctx.close();
    return { state: got.state, title: got.title };
  },
  async another_tab_kept_it_awake(browser) {
    reset();
    const { ctx, p } = await fresh(browser, "en");
    await p.clock.runFor("09:01"); // the warning; nobody answers it here, but another tab is in use
    state.idleLeft = 300; // that tab's last request was five minutes ago
    await p.clock.runFor("01:00");
    await until(p, () => document.getElementById("idle-warn").hidden);
    const lock = await look(p);
    await p.clock.runFor("03:58");
    const before = (await look(p)).hidden;
    await p.clock.runFor("00:05");
    const again = await look(p);
    await ctx.close();
    return {
      at_lock: { hidden: lock.hidden, state: lock.state, checks: state.checks }, before_that: before,
      warned_again: { hidden: again.hidden, state: again.state },
    };
  },
  async late_page(browser) {
    reset();
    const ctx = await browser.newContext();
    const p = await ctx.newPage();
    await p.clock.install();
    await p.goto(`${BOX}/late`); // the server counted from before the three seconds the page took to arrive
    await p.clock.runFor(537500); // 8:57.5 after the page arrived, past 9:00 after the navigation started
    const got = await look(p);
    await ctx.close();
    return { warned_within_3s_early: !got.hidden && got.state === "soon" };
  },
  async absolute_limit(browser) {
    const { ctx, p } = await fresh(browser, "limit");
    await p.clock.runFor("04:01");
    const got = await look(p);
    await ctx.close();
    return { at_4m01: { hidden: got.hidden, state: got.state, stay_hidden: got.stay_hidden, title: got.title, seen: got.seen } };
  },
  async japanese(browser) {
    const { ctx, p } = await fresh(browser, "ja");
    await p.clock.runFor("09:01");
    const got = await look(p);
    await ctx.close();
    return { title: got.title, stay: got.stay };
  },
};

(async () => {
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  BOX = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch();
  const out = {};
  try {
    for (const [name, run] of Object.entries(CASES)) {
      try { out[name] = await run(browser); } catch (e) { out[name] = { error: String(e && e.stack || e) }; }
    }
  } finally {
    await browser.close();
    server.close();
  }
  console.log(JSON.stringify(out));
})();
