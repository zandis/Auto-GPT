// e2e-box account driver. Secrets live in the 0600 creds folder and are never printed.
//   node acct.js first-admin            sign in as admin (password + enrolment code from creds), authenticator, new password
//   node acct.js add USER ROLE AFF STUDIES MAILBOX   as admin, add an account on /ops/users; keeps the code or password
//   node acct.js enrol USER             first sign-in with the enrolment code: password, authenticator
//   node acct.js login USER             plain sign-in (password, TOTP, forced change) and print where it lands
const { chromium } = require('playwright');
const fs = require('fs'), crypto = require('crypto'), path = require('path');
const E = process.env.E2E_OUT, CREDS = E + '/creds', BASE = process.env.TB_URL;
fs.mkdirSync(CREDS, { recursive: true, mode: 0o700 });
const load = n => { try { return JSON.parse(fs.readFileSync(path.join(CREDS, n + '.json'))); } catch { return null; } };
const save = (n, o) => fs.writeFileSync(path.join(CREDS, n + '.json'), JSON.stringify(o), { mode: 0o600 });
const newPw = () => 'E2e-' + crypto.randomBytes(12).toString('base64url') + '-7q';
function b32(s) { const a = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'; let bits = ''; const out = [];
  for (const c of s.replace(/=+$/, '').toUpperCase().replace(/\s/g, '')) bits += a.indexOf(c).toString(2).padStart(5, '0');
  for (let i = 0; i + 8 <= bits.length; i += 8) out.push(parseInt(bits.slice(i, i + 8), 2)); return Buffer.from(out); }
function totp(k) { const c = Buffer.alloc(8); c.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000)));
  const h = crypto.createHmac('sha1', b32(k)).update(c).digest(); const o = h[h.length - 1] & 15;
  return String(((h.readUInt32BE(o) & 0x7fffffff) % 1e6)).padStart(6, '0'); }
const p = u => new URL(u).pathname;

async function totpStep(page, a, name, out) {
  if (!page.url().includes('/login/totp')) return;
  const key = await page.$('[data-testid=totp-key]'); if (key) { a.totp = (await key.inputValue()) || (await key.textContent()).trim(); save(name, a); out.push('authenticator key shown'); }
  const ec = await page.$('[data-testid=totp-enrol-code]'); if (ec && a.enrol) { await ec.fill(a.enrol); out.push('enrolment code typed'); }
  for (let k = 0; k < 3; k++) {
    if (Date.now() % 30000 > 27000) await page.waitForTimeout(31000 - (Date.now() % 30000));
    await page.fill('#code', totp(a.totp)); await page.click('[data-testid=totp-submit]'); await page.waitForLoadState('networkidle');
    if (!page.url().includes('/login/totp')) break; await page.waitForTimeout(31000 - (Date.now() % 30000));
  }
  out.push('after totp -> ' + p(page.url()));
}
async function forcedChange(page, a, name, out) {
  if (!(await page.$('#pw-new'))) return;
  const np = newPw(); await page.fill('#pw-cur', a.password); await page.fill('#pw-new', np); await page.fill('#pw-again', np);
  await page.click('#pw-again >> xpath=ancestor::form//button[@type="submit"]'); await page.waitForLoadState('networkidle');
  a.password = np; delete a.enrol; save(name, a); out.push('password changed -> ' + p(page.url()));
}
async function login(page, name, out) {
  const a = load(name); if (!a) throw new Error('no creds for ' + name);
  const t0 = Date.now();
  await page.goto(BASE + '/login'); await page.fill('#username', name); await page.fill('#password', a.password);
  await page.click('[data-testid=login-submit]'); await page.waitForLoadState('networkidle');
  out.push('login -> ' + p(page.url()));
  const err = await page.$('[data-testid=login-error], [data-testid=login-locked], [data-testid=login-slowed]');
  if (err) out.push('login message: ' + (await err.textContent()).trim().slice(0, 120));
  await totpStep(page, a, name, out); await forcedChange(page, a, name, out);
  if (p(page.url()) === '/login') { // after a password change the box asks for a fresh sign-in
    await page.fill('#username', name); await page.fill('#password', a.password);
    await page.click('[data-testid=login-submit]'); await page.waitForLoadState('networkidle'); await totpStep(page, a, name, out);
  }
  out.push(`signed in as ${name} in ${Date.now() - t0} ms, lands on ${p(page.url())}`);
  return a;
}

(async () => {
  const [cmd, user, role, aff, studies, mailbox] = process.argv.slice(2);
  const browser = await chromium.launch({ args: ['--host-resolver-rules=MAP *.local 127.0.0.1'] });
  const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1400, height: 1000 } });
  const page = await ctx.newPage(); const out = []; let ok = true;
  if (cmd === 'first-admin' || cmd === 'login') {
    await login(page, cmd === 'first-admin' ? 'admin' : user, out);
    ok = !p(page.url()).startsWith('/login');
  } else if (cmd === 'add') {
    await login(page, 'admin', out);
    await page.goto(BASE + '/ops/users'); await page.waitForLoadState('networkidle');
    const f = page.locator('form:has([data-testid=users-add])');
    await f.locator('#username').fill(user); await f.locator('#role').selectOption(role);
    if (mailbox) await f.locator('#mailbox').fill(mailbox);
    await f.locator('#affiliation').selectOption(aff || 'hospital'); if (studies && studies !== '-') await f.locator('#studies').fill(studies);
    await f.locator('[data-testid=users-add]').click(); await page.waitForLoadState('networkidle');
    const code = await page.$('[data-testid=enrol-code-value]'); const pw = await page.$('[data-testid=users-pw-field]');
    const req = await page.$('[data-testid=account-requested]');
    if (code) { save(user, { enrol: ((await code.inputValue().catch(() => '')) || (await code.textContent())).trim(), role }); out.push(`${user}: enrolment code shown once (kept)`); }
    else if (pw) { save(user, { password: ((await pw.inputValue().catch(() => '')) || (await pw.textContent())).trim(), role }); out.push(`${user}: one-time password shown once (kept)`); }
    else if (req) { out.push(`${user}: request waits for a second person`); ok = 'requested'; }
    else { out.push('no code, password or request on ' + p(page.url()) + ' : ' + (await page.textContent('main').catch(() => '')).replace(/\s+/g, ' ').slice(0, 200)); ok = false; }
  } else if (cmd === 'confirm') { // node acct.js confirm USER BY : BY (a steward) confirms USER's waiting request
    await login(page, role, out);
    await page.goto(BASE + '/ops/accounts/requests'); await page.waitForLoadState('networkidle');
    const n = await page.locator('[data-testid=request-confirm]').count(); out.push(`requests waiting: ${n}`);
    if (!n) ok = false; else {
      await page.locator('[data-testid=request-confirm]').first().click(); await page.waitForLoadState('networkidle');
      const sec = await page.$('[data-testid=request-secret]');
      if (sec) { const v = ((await sec.inputValue().catch(() => '')) || (await sec.textContent())).trim().split(/\s+/).pop();
        save(user, { enrol: v, password: '' }); out.push(`${user}: secret shown once to ${role} (kept)`); }
      else { out.push('no secret shown: ' + (await page.textContent('main')).replace(/\s+/g, ' ').slice(0, 200)); ok = false; }
    }
  } else if (cmd === 'enrol') {
    const a = load(user); const np = newPw();
    await page.goto(BASE + '/enrol'); await page.fill('#username', user); await page.fill('#enrol_code', a.enrol);
    await page.fill('#password', np); await page.fill('#password2', np);
    await page.click('[data-testid=enrol-submit]'); await page.waitForLoadState('networkidle');
    const err = await page.$('[data-testid=enrol-error], [data-testid=enrol-code-used]');
    if (err) { out.push('enrol refused: ' + (await err.textContent()).trim().slice(0, 160)); ok = false; }
    else { a.password = np; save(user, a); out.push('enrol -> ' + p(page.url())); await totpStep(page, a, user, out); await forcedChange(page, a, user, out);
      delete a.enrol; save(user, a);
      if (p(page.url()).startsWith('/login')) await login(page, user, out);
      ok = !p(page.url()).startsWith('/login') && !p(page.url()).startsWith('/enrol'); out.push('lands on ' + p(page.url())); }
  }
  console.log(out.join('\n')); await browser.close(); process.exit(ok === true ? 0 : ok === 'requested' ? 3 : 1);
})().catch(e => { console.error('ERR', e.message.slice(0, 300)); process.exit(1); });
