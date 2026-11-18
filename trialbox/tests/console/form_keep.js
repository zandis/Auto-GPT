// D-1222 (E-M3): the console's own script (static/console.js, section 6) on pages served by the browser itself
// (a small local server in this script, no box), in one tab, as a person moves between them. Driven by
// tests/console/test_phone_first.py. Prints one JSON line: {case: result}. Synthetic data only.
"use strict";

const fs = require("fs");
const path = require("path");
const http = require("http");
const { chromium } = require("playwright");

const JS = fs.readFileSync(path.join(__dirname, "..", "..", "services", "console", "static", "console.js"), "utf8");
let BOX = "http://127.0.0.1";
const FORM = "/studies/GZQO/entry?record=S-1&event=ae1&form=tb_adverse_event&back=subject";

function page(user, body) {
  const meta = user ? `<meta name="tb-user" content="${user}">` : "";
  return `<!doctype html><html><head>${meta}</head><body>${body}<script>${JS}</script></body></html>`;
}

function form(user, values = {}) {
  const id = `${user}|GZQO|S-1|ae1|tb_adverse_event`;
  const term = values.term ? ` value="${values.term}"` : "";
  return page(user, `<main><form method="post" action="/studies/GZQO/entry" id="entry" data-guard data-keep="${id}"
    data-keep-msg="Fields restored: {n}." data-keep-discard="Discard">
    <input type="hidden" name="csrf" value="x"><input type="hidden" name="record" value="S-1">
    <input type="hidden" name="event" value="ae1"><input type="hidden" name="form" value="tb_adverse_event">
    <input type="hidden" name="back" value="subject">
    <input id="term" name="f_ae_term" type="text"${term}>
    <label><input type="radio" name="f_ae_serious" value="1" id="s1"> yes</label>
    <label><input type="radio" name="f_ae_serious" value="0"> no</label>
    <button type="submit" id="save">Save</button></form></main>`);
}

const signInPage = page("", `<form method="post" action="/login"><input name="username"><button id="in">in</button></form>`);

let state = {};
const server = http.createServer((req, res) => {
  const u = new URL(req.url, BOX);
  const html = (b) => { res.writeHead(200, { "content-type": "text/html" }); res.end(b); };
  const go = (to) => { res.writeHead(303, { location: to }); res.end(); };
  req.resume();
  req.on("end", () => {
    if (u.pathname === "/login" && req.method === "POST") { state.user = state.next || state.user; return go("/home"); }
    if (u.pathname === "/login") return html(signInPage);
    if (u.pathname === "/studies/GZQO/entry" && req.method === "POST") {
      if (state.ended) return go("/login?why=idle");
      if (state.again) return html(form(state.user, { term: "as saved" })); // saved, the same form shown again
      return go("/studies/GZQO/history?record=S-1");
    }
    if (u.pathname === "/studies/GZQO/entry") return html(form(state.user));
    return html(page(state.user, `<main><h1 id="h">${u.pathname}</h1></main>`));
  });
});

async function tab(browser, s) {
  state = s;
  const ctx = await browser.newContext();
  return { ctx, page: await ctx.newPage() };
}

const keys = (p) => p.evaluate(() => Object.keys(sessionStorage).filter((k) => k.indexOf("tb-form") === 0).sort());

async function typeAndSaveAfterTheSessionEnded(browser, state) {
  const { ctx, page: p } = await tab(browser, state);
  await p.goto(BOX + FORM);
  await p.fill("#term", "gout flare, knee");
  await p.check("#s1");
  state.ended = true;
  await Promise.all([p.waitForURL("**/login?why=idle"), p.click("#save")]);
  state.ended = false;
  return { ctx, p };
}

const CASES = {
  async restored_once_with_a_notice(browser) {
    const state = { user: "crc" };
    const { ctx, p } = await typeAndSaveAfterTheSessionEnded(browser, state);
    await Promise.all([p.waitForURL((u) => u.pathname === "/studies/GZQO/entry"), p.click("#in")]);
    await p.waitForSelector("[data-testid=form-restored]");
    const got = {
      url: p.url().replace(BOX, ""), term: await p.inputValue("#term"), serious: await p.isChecked("#s1"),
      notice: await p.textContent("[data-testid=form-restored] span"),
      marked: await p.evaluate(() => document.querySelectorAll(".restored").length),
    };
    await p.goto(BOX + FORM); // a later visit: nothing comes back
    got.later = await p.inputValue("#term");
    got.laterNotice = await p.locator("[data-testid=form-restored]").count();
    await ctx.close();
    return got;
  },
  async discard(browser) {
    const state = { user: "crc" };
    const { ctx, p } = await typeAndSaveAfterTheSessionEnded(browser, state);
    await Promise.all([p.waitForURL((u) => u.pathname === "/studies/GZQO/entry"), p.click("#in")]);
    await p.click("[data-testid=form-discard]");
    const got = { term: await p.inputValue("#term"), notice: await p.locator("[data-testid=form-restored]").count(), keys: await keys(p) };
    await ctx.close();
    return got;
  },
  async another_account_signs_in(browser) {
    const state = { user: "crc", next: "crc2" };
    const { ctx, p } = await typeAndSaveAfterTheSessionEnded(browser, state);
    await Promise.all([p.waitForURL("**/home"), p.click("#in")]);
    await p.waitForTimeout(300);
    const got = { url: p.url().replace(BOX, ""), keys: await keys(p) };
    await ctx.close();
    return got;
  },
  async saved_with_a_live_session(browser) {
    const state = { user: "crc" };
    const { ctx, page: p } = await tab(browser, state);
    await p.goto(BOX + FORM);
    await p.fill("#term", "x");
    await Promise.all([p.waitForURL("**/history**"), p.click("#save")]);
    const got = { keys: await keys(p) };
    await ctx.close();
    return got;
  },
  async saved_and_shown_again(browser) {
    const state = { user: "crc", again: true };
    const { ctx, page: p } = await tab(browser, state);
    await p.goto(BOX + FORM);
    await p.fill("#term", "x");
    await Promise.all([p.waitForLoadState("load"), p.click("#save")]);
    await p.waitForSelector("#term");
    const got = { keys: await keys(p), term: await p.inputValue("#term"), notice: await p.locator("[data-testid=form-restored]").count() };
    await ctx.close();
    return got;
  },
  async left_on_purpose(browser) {
    const state = { user: "crc" };
    const { ctx, page: p } = await tab(browser, state);
    await p.goto(BOX + FORM);
    await p.fill("#term", "x");
    const typed = await keys(p);
    await p.goto(BOX + "/studies/GZQO/week");
    const got = { typed, after: await keys(p) };
    await ctx.close();
    return got;
  },
  async older_than_12_hours(browser) {
    const state = { user: "crc" };
    const { ctx, page: p } = await tab(browser, state);
    await p.goto(BOX + "/home");
    await p.evaluate(() => sessionStorage.setItem("tb-form:crc|GZQO|S-1|ae1|tb_adverse_event",
      JSON.stringify({ user: "crc", at: Date.now() - 13 * 3600 * 1000, v: { f_ae_term: "old" } })));
    await p.goto(BOX + "/home");
    const got = { keys: await keys(p) };
    await ctx.close();
    return got;
  },
  async the_address_carries_the_form(browser) {
    const state = { user: "crc" };
    const { ctx, page: p } = await tab(browser, state);
    await p.goto(BOX + "/studies/GZQO/entry"); // a refused save shows the form at the bare address
    await p.fill("#term", "x");
    state.ended = true;
    await Promise.all([p.waitForURL("**/login?why=idle"), p.click("#save")]);
    const got = { sent: await p.evaluate(() => JSON.parse(sessionStorage.getItem("tb-form-sent")).url) };
    await ctx.close();
    return got;
  },
};

(async () => {
  await new Promise((ok) => server.listen(0, "127.0.0.1", ok));
  BOX = "http://127.0.0.1:" + server.address().port;
  const browser = await chromium.launch();
  const out = {};
  try {
    for (const [name, fn] of Object.entries(CASES)) {
      try { out[name] = await fn(browser); } catch (e) { out[name] = { error: e.message.split("\n")[0] }; }
    }
  } finally {
    await browser.close();
    server.close();
  }
  console.log(JSON.stringify(out));
})();
