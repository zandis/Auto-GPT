// Browser end to end of the TrialBox POC console, driven by tests/e2e/test_console_poc.py (Node Playwright with the
// preinstalled Chromium; never runs `playwright install`).
//
//   node tests/e2e/console_poc.js <mode> <json-args>
//     web     {base, user, password, shots}            sign in, FEAS GZQO from the web, wait for the result, PDF download
//     thread  {base, user, password, job, shots, webmail}  the e-mail job's page shows the reply thread; web mail shot
//     viewer  {base, user, password, shots}            a viewer sees results but cannot start a job (UI and POST)
//     mailbox {base, user, password, subject, shots}   send a request through the console's test mailbox (GreenMail)
//     protocol {base, user, password, ruleset, shots}  compile the sample protocol, approve as compiled, resumed FEAS
//     propose {base, user, password, text, shots}      plain words -> classify_intent proposal -> confirm -> runs
//     cascade {base, user, password, shots}            v4 cascade run: funnel, recall certificate, DL-1 PDF
// Prints one JSON line with the findings; exit code 1 on any failed check.
"use strict";

const { chromium } = require("playwright");
const path = require("path");

const checks = [];
function check(ok, what) {
  checks.push({ ok: !!ok, what });
  if (!ok) {
    console.error("FAIL: " + what);
    process.exitCode = 1;
  }
}

async function shot(page, args, name) {
  if (!args.shots) return;
  await page.screenshot({ path: path.join(args.shots, name), fullPage: true });
}

async function login(page, args) {
  await page.goto(args.base + "/login", { waitUntil: "load" });
  await page.fill("#username", args.user);
  await page.fill("#password", args.password);
  await Promise.all([page.waitForURL(args.base + "/"), page.click("[data-testid=login-submit]")]);
  const who = await page.locator("[data-testid=whoami]").innerText();
  check(who.includes(args.user), `signed in as ${args.user} (${who})`);
}

async function waitState(page, url, done, timeoutMs) {
  const t0 = Date.now();
  let state = "";
  while (Date.now() - t0 < timeoutMs) {
    await page.goto(url, { waitUntil: "load" });
    state = (await page.locator("[data-testid=job-state]").innerText()).trim();
    if (done.includes(state)) return state;
    await page.waitForTimeout(3000);
  }
  return state;
}

async function web(page, args, out) {
  await page.goto(args.base + "/login", { waitUntil: "load" });
  check((await page.locator("[data-testid=banner]").innerText()).includes("synthetic data only"), "pilot banner");
  await shot(page, args, "01-login.png");
  await login(page, args);
  check((await page.locator("[data-testid=health]").innerText()).includes("orchestrator"), "health panel");
  await shot(page, args, "02-overview.png");
  await page.goto(args.base + "/pilot/request", { waitUntil: "load" });
  await page.selectOption("#feas-rs", "GZQO");
  await Promise.all([page.waitForURL(/\/pilot\/jobs\//), page.click("[data-testid=start-feas]")]);
  const url = page.url();
  out.job = url.split("/").pop();
  check((await page.locator("[data-testid=job-line]").innerText()).trim() === "FEAS GZQO", "equivalent line FEAS GZQO");
  const state = await waitState(page, url, ["done", "failed"], 15 * 60 * 1000);
  check(state === "done", `web FEAS job ${out.job} done (state ${state})`);
  check(await page.locator("[data-testid=funnel] tbody tr").count() > 3, "attrition table rendered");
  const pdfLink = page.locator("a[data-file$='.pdf']").first();
  const [download] = await Promise.all([page.waitForEvent("download"), pdfLink.click()]);
  const file = await download.path();
  const head = require("fs").readFileSync(file).subarray(0, 5).toString();
  check(head === "%PDF-", `downloaded ${download.suggestedFilename()} is a PDF`);
  out.pdf = download.suggestedFilename();
  check((await page.locator("[data-testid=thread]").innerText()).includes(`Done ${out.job}`), "Done mail in the thread");
  await shot(page, args, "04-result.png");
  await page.goto(args.base + "/jobs", { waitUntil: "load" });
  check((await page.locator(`tr[data-job='${out.job}']`).count()) === 1, "job in the job list");
  await shot(page, args, "03-jobs.png");
  await page.goto(args.base + "/audit", { waitUntil: "load" });
  check((await page.locator("[data-testid=audit]").innerText()).includes("console.request"), "audit shows console.request");
}

async function thread(page, args, out) {
  await login(page, args);
  const url = `${args.base}/pilot/jobs/${args.job}`;
  const state = await waitState(page, url, ["done", "failed"], 10 * 60 * 1000);
  check(state === "done", `e-mail job ${args.job} done in the console`);
  const text = await page.locator("[data-testid=thread]").innerText();
  check(text.includes("→ box"), "inbound mail in the thread");
  check(text.includes(`Received ${args.job}`) && text.includes(`Done ${args.job}`), "Received and Done replies in the thread");
  await shot(page, args, "05-email-job.png");
  if (args.webmail) {
    await page.goto(args.webmail, { waitUntil: "networkidle" });
    await page.waitForTimeout(1500);
    await shot(page, args, "06-webmail.png");
  }
}

async function viewer(page, args, out) {
  await login(page, args);
  await page.goto(args.base + "/pilot/request", { waitUntil: "load" });
  check(await page.locator("[data-testid=start-feas]").isDisabled(), "start button disabled for a viewer");
  const csrf = await page.locator("input[name=csrf]").first().inputValue();
  const status = await page.evaluate(async (c) => {
    const body = new URLSearchParams({ csrf: c, kind: "FEAS", ruleset: "GZQO" });
    const r = await fetch("/pilot/request", { method: "POST", body, redirect: "manual" });
    return r.status;
  }, csrf);
  check(status === 403, `viewer POST /pilot/request refused (HTTP ${status})`);
  out.viewer_post = status;
  await shot(page, args, "07-viewer-request.png");
}

async function mailbox(page, args, out) {
  await login(page, args);
  await page.goto(args.base + "/pilot/mailbox", { waitUntil: "load" });
  await page.fill("#subject", args.subject);
  await Promise.all([page.waitForLoadState("load"), page.click("[data-testid=mail-send]")]);
  check(await page.locator("[data-testid=mail-sent]").count() === 1, "test mail sent");
  await shot(page, args, "08-test-mailbox.png");
}

async function protocol(page, args, out) {
  await login(page, args);
  await page.goto(args.base + "/pilot/protocol", { waitUntil: "load" });
  await page.fill("#ruleset", args.ruleset);
  await page.check("[data-testid=use-sample]");
  await Promise.all([page.waitForURL(/\/pilot\/jobs\//), page.click("[data-testid=compile]")]);
  const feasUrl = page.url();
  out.feas = feasUrl.split("/").pop();
  let state = await waitState(page, feasUrl, ["awaiting_approval", "done", "failed"], 20 * 60 * 1000);
  check(state === "awaiting_approval", `protocol compiled, waiting for approval (state ${state})`);
  check(await page.locator("[data-testid=review]").count() === 1, "review panel shown");
  await shot(page, args, "09-review.png");
  await Promise.all([page.waitForURL(/\/pilot\/jobs\//), page.click("[data-testid=approve]")]);
  const apprUrl = page.url();
  out.approve = apprUrl.split("/").pop();
  state = await waitState(page, apprUrl, ["done", "failed"], 20 * 60 * 1000);
  check(state === "done", `APPROVE job done (state ${state})`);
  state = await waitState(page, feasUrl, ["done", "failed"], 20 * 60 * 1000);
  check(state === "done", `resumed FEAS on the approved ruleset done (state ${state})`);
  check(await page.locator("[data-testid=funnel] tbody tr").count() > 3, "attrition table of the new ruleset");
}

async function proposeFlow(page, args, out) {
  await login(page, args);
  await page.goto(args.base + "/pilot/request", { waitUntil: "load" });
  await page.fill("#text", args.text);
  await Promise.all([page.waitForLoadState("load"), page.click("[data-testid=propose]")]);
  const line = (await page.locator("[data-testid=proposal-line]").innerText()).trim();
  out.line = line;
  check(line.startsWith("FEAS GZQO"), `proposal ${line}`);
  check(!(await page.content()).includes(args.text), "free text not echoed back");
  await shot(page, args, "11-proposal.png");
  await Promise.all([page.waitForURL(/\/pilot\/jobs\//), page.click("[data-testid=confirm]")]);
  const state = await waitState(page, page.url(), ["done", "failed"], 15 * 60 * 1000);
  check(state === "done", `confirmed proposal ran (state ${state})`);
}

async function cascade(page, args, out) {
  await login(page, args);
  await page.goto(args.base + "/pilot/cascade", { waitUntil: "load" });
  await Promise.all([page.waitForURL(/\/pilot\/cascade\/[0-9A-Z]+/), page.click("[data-testid=cascade-start]")]);
  const url = page.url();
  const t0 = Date.now();
  let state = "running";
  while (Date.now() - t0 < 15 * 60 * 1000) {
    await page.goto(url, { waitUntil: "load" });
    state = (await page.locator("[data-testid=cascade-state]").innerText()).trim();
    if (state !== "running") break;
    await page.waitForTimeout(3000);
  }
  check(state === "done", `cascade run done (state ${state})`);
  check(await page.locator("[data-testid=cascade-funnel]").count() === 1, "cascade funnel shown");
  check(await page.locator("[data-testid=certificate]").count() === 1, "recall certificate shown");
  const [download] = await Promise.all([page.waitForEvent("download"), page.click("a[data-file=dl1_pdf]")]);
  const head = require("fs").readFileSync(await download.path()).subarray(0, 5).toString();
  check(head === "%PDF-", "DL-1 PDF downloaded");
  await shot(page, args, "10-cascade.png");
}

async function main() {
  const mode = process.argv[2];
  const args = JSON.parse(process.argv[3] || "{}");
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, acceptDownloads: true });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  const out = { mode };
  try {
    if (mode === "web") await web(page, args, out);
    else if (mode === "thread") await thread(page, args, out);
    else if (mode === "viewer") await viewer(page, args, out);
    else if (mode === "mailbox") await mailbox(page, args, out);
    else if (mode === "protocol") await protocol(page, args, out);
    else if (mode === "cascade") await cascade(page, args, out);
    else if (mode === "propose") await proposeFlow(page, args, out);
    else check(false, `unknown mode ${mode}`);
    check(errors.length === 0, `no page errors (${errors.join("; ")})`);
  } catch (e) {
    check(false, `exception: ${e && e.stack ? e.stack : e}`);
  } finally {
    await browser.close();
  }
  out.checks = checks;
  console.log(JSON.stringify(out));
}

main();
