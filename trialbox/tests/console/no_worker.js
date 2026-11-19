// D-1370 (9f-11, review 02/J-11): no service worker registers on a console page. A page this console rendered (with
// its own Content-Security-Policy, both from tests/console/test_no_offline_copy.py; the path is the one argument) is
// served by a small local server, and the page is asked to register a service worker. Planted beside it: the same
// page served without the console's policy, where the same request does register, so the check is seen to catch a
// registration. Prints one JSON line: {case: result}. Synthetic data only.
"use strict";

const fs = require("fs");
const http = require("http");
const { chromium } = require("playwright");

const PAGE = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
let BOX = "http://127.0.0.1";

const server = http.createServer((req, res) => {
  const u = new URL(req.url, BOX);
  req.resume();
  if (u.pathname === "/sw.js") {
    res.writeHead(200, { "content-type": "text/javascript" });
    return res.end("self.addEventListener('fetch', function () {});");
  }
  const head = { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" };
  if (u.pathname === "/console") head["content-security-policy"] = PAGE.csp;
  else if (u.pathname !== "/planted") { res.writeHead(404); return res.end(); }
  res.writeHead(200, head);
  return res.end(PAGE.html);
});

async function attempt(browser, name) {
  const ctx = await browser.newContext();
  const p = await ctx.newPage();
  const refused = [];
  p.on("console", (m) => { if (/Content Security Policy/i.test(m.text())) refused.push(m.text()); });
  await p.goto(`${BOX}/${name}`);
  const at_load = refused.length; // the console's own inline script ran under its policy (nothing refused at load)
  const register = await p.evaluate(() => navigator.serviceWorker.register("/sw.js").then(
    () => "registered", (e) => `refused: ${e && e.name}`));
  const registrations = await p.evaluate(() => navigator.serviceWorker.getRegistrations().then((r) => r.length));
  await ctx.close();
  return { register, registrations, refused_at_load: at_load };
}

(async () => {
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  BOX = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch();
  const out = {};
  try {
    out.the_console_page = await attempt(browser, "console");
    const planted = await attempt(browser, "planted");
    out.planted_without_the_policy = { register: planted.register, registrations: planted.registrations };
  } finally {
    await browser.close();
    server.close();
  }
  console.log(JSON.stringify(out));
})();
