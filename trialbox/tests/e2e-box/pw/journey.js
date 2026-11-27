// e2e-box journey runner. stdin: JSON {actions:[...]} ; stdout: one JSON line per action.
// action: {id, as, method: GET|POST|SCAN|API_GET|API_POST, path, form?, json?, files?, lang?, viewport?, save?: {name: regex}}
//   GET/POST use the role's signed-in page session (POST adds the CSRF token read from the last page or `csrfFrom`);
//   API_* use the role's bearer token from POST /api/v1/session (password + TOTP); SCAN loads the page in a browser
//   tab and reports raw text keys, English words on a ja/zh page, and horizontal overflow at the viewport.
// ${name} in path/form values is replaced by a value saved earlier (save: regex over Location or body, group 1).
const { chromium } = require('playwright');
const fs = require('fs'), crypto = require('crypto'), path = require('path');
const E = process.env.E2E_OUT, CREDS = E + '/creds', BASE = process.env.TB_URL;
const load = n => JSON.parse(fs.readFileSync(path.join(CREDS, n + '.json')));
function b32(s) { const a = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'; let bits = ''; const out = [];
  for (const c of s.replace(/=+$/, '').toUpperCase().replace(/\s/g, '')) bits += a.indexOf(c).toString(2).padStart(5, '0');
  for (let i = 0; i + 8 <= bits.length; i += 8) out.push(parseInt(bits.slice(i, i + 8), 2)); return Buffer.from(out); }
function totp(k) { const c = Buffer.alloc(8); c.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000)));
  const h = crypto.createHmac('sha1', b32(k)).update(c).digest(); const o = h[h.length - 1] & 15;
  return String(((h.readUInt32BE(o) & 0x7fffffff) % 1e6)).padStart(6, '0'); }
const lastStep = {}; // user -> last 30 s step used (the box refuses a replayed code)
async function freshCode(page, user, key) {
  let step = Math.floor(Date.now() / 30000);
  if (lastStep[user] === step || Date.now() % 30000 > 27000) { await page.waitForTimeout(31000 - (Date.now() % 30000)); step = Math.floor(Date.now() / 30000); }
  lastStep[user] = step; return totp(key);
}
const sessions = {}; const vars = JSON.parse(process.env.VARS || '{}');
const sub = s => typeof s === 'string' ? s.replace(/\$\{(\w+)\}/g, (_, k) => vars[k] ?? '') : s;
let browser;
async function session(user) {
  if (sessions[user]) return sessions[user];
  const a = load(user);
  const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1366, height: 900 } });
  const page = await ctx.newPage(); const t0 = Date.now();
  await page.goto(BASE + '/login'); await page.fill('#username', user); await page.fill('#password', a.password);
  await page.click('[data-testid=login-submit]'); await page.waitForLoadState('networkidle');
  if (page.url().includes('/login/totp')) { await page.fill('#code', await freshCode(page, user, a.totp)); await page.click('[data-testid=totp-submit]'); await page.waitForLoadState('networkidle'); }
  const s = { ctx, page, a, csrf: '', loginMs: Date.now() - t0, landed: new URL(page.url()).pathname };
  s.csrf = await page.$eval('input[name=csrf]', e => e.value).catch(() => '');
  sessions[user] = s; return s;
}
async function token(user) {
  const s = await session(user); if (s.token !== undefined) return s.token;
  const r = await s.ctx.request.post(BASE + '/api/v1/session', { data: { username: user, password: s.a.password, code: await freshCode(s.page, user, s.a.totp), lang: 'en' } });
  s.token = r.ok() ? (await r.json()).token : null; s.tokenStatus = r.status(); return s.token;
}
const cell = (st, loc) => st >= 200 && st < 300 ? 'Y' : st >= 300 && st < 400 ? (/\/login/.test(loc || '') ? 'L' : 'Y')
  : st === 403 ? '-' : st === 404 ? 'n' : st === 401 ? 'L' : st === 503 ? 'U' : [400, 409, 410, 422, 429].includes(st) ? 'Y' : 'E';

async function scan(s, act) {
  const lang = act.lang || 'en', vp = act.viewport || 'desktop';
  if (s.lang !== lang) { // the account's own language switch (POST /lang)
    await s.ctx.request.post(BASE + '/lang', { form: { lang, csrf: s.csrf, back: '/' }, maxRedirects: 0 }); s.lang = lang; }
  const page = s.scanPage || (s.scanPage = await s.ctx.newPage());
  await page.setViewportSize(vp === 'phone' ? { width: 390, height: 844 } : { width: 1366, height: 900 });
  const t0 = Date.now(); const r = await page.goto(BASE + sub(act.path), { waitUntil: 'networkidle' }).catch(e => null);
  const ms = Date.now() - t0;
  const res = await page.evaluate((lang) => {
    const txt = []; const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (w.nextNode()) { const n = w.currentNode; const p = n.parentElement; if (!p || ['SCRIPT', 'STYLE', 'CODE', 'PRE'].includes(p.tagName) || p.closest('.mono,code,pre,[translate=no]')) continue;
      const t = n.textContent.replace(/\s+/g, ' ').trim(); if (t) txt.push(t); }
    const keys = [...new Set(txt.filter(t => /^[a-z][a-z0-9_]*(\.[a-z0-9_-]+){1,5}$/.test(t) && !/\.(pdf|csv|xlsx|json|txt|md|html|png|zip|gz|tar)$/.test(t) && !/^[a-z0-9-]+\.(test|local|com|org|net|tw|jp)$/.test(t)))];
    const cjk = /[぀-ヿ㐀-鿿]/;
    const english = lang === 'en' ? [] : [...new Set(txt.filter(t => !cjk.test(t) && /([A-Za-z]{3,}[ ,.]+){3,}[A-Za-z]{3,}/.test(t)))];
    const de = document.documentElement; const vw = de.clientWidth;
    const wide = [...document.querySelectorAll('body *')].filter(e => { const b = e.getBoundingClientRect(); return b.width > 0 && b.right > vw + 2 && !e.closest('.scroll,[style*=overflow]') && getComputedStyle(e).position !== 'fixed'; }).length;
    return { title: document.title, keys: keys.slice(0, 15), nkeys: keys.length, english: english.slice(0, 6), nenglish: english.length, overflowPx: de.scrollWidth - vw, wideEls: wide, htmlLang: de.lang };
  }, lang).catch(e => ({ error: e.message.slice(0, 120) }));
  return { status: r ? r.status() : 0, final: new URL(page.url()).pathname, ms, ...res };
}

(async () => {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  browser = await chromium.launch({ args: ['--host-resolver-rules=MAP *.local 127.0.0.1'] });
  for (const act of input.actions) {
    const out = { id: act.id, as: act.as, method: act.method, path: sub(act.path) };
    try {
      if (/\$\{\w+\}/.test(act.path) && /\/$|\/\/|=$/.test(sub(act.path))) throw new Error('a value this step needs was not saved by an earlier step');
      const s = await session(act.as); out.loginMs = s.loginMs; out.landed = s.landed;
      let t0 = Date.now(); let r;
      if (act.method === 'SCAN') Object.assign(out, await scan(s, act));
      else if (act.method === 'WAIT') { // GET until the text matches `until` (or `fail` matches), every `every` s, `max` tries
        let n = 0, txt = '', st = 0; const re = new RegExp(act.until), bad = act.fail ? new RegExp(act.fail) : null;
        for (; n < (act.max || 60); n++) {
          const r = await s.ctx.request.get(BASE + sub(act.path), { failOnStatusCode: false, timeout: 60000 }); st = r.status();
          txt = await r.text(); // raw HTML: until/fail may name attributes (data-state="done")
          if (re.test(txt) || (bad && bad.test(txt))) break; await s.page.waitForTimeout((act.every || 10) * 1000);
        }
        out.ms = Date.now() - t0; out.status = st; out.polls = n + 1; out.matched = re.test(txt); out.failed = bad ? bad.test(txt) : false;
        out.cell = out.matched ? 'Y' : 'E'; out.body = txt.replace(/<script[\s\S]*?<\/script>/g, ' ').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').slice(0, act.keepBody || 300);
        for (const [k, rx] of Object.entries(act.save || {})) { const mm = txt.match(new RegExp(rx)); if (mm) { vars[k] = mm[1]; out['saved_' + k] = mm[1]; } }
      }
      else {
        const url = BASE + sub(act.path); const opt = { maxRedirects: 0, failOnStatusCode: false, timeout: act.timeout || 120000 };
        if (act.method === 'GET') r = await s.ctx.request.get(url, opt);
        else if (act.method === 'POST') {
          if (act.csrfFrom) { await s.page.goto(BASE + sub(act.csrfFrom)); s.csrf = await s.page.$eval('input[name=csrf]', e => e.value).catch(() => s.csrf); }
          const form = { csrf: s.csrf }; for (const [k, v] of Object.entries(act.form || {})) form[k] = sub(v);
          if (act.files) { const mp = { ...form }; for (const [k, f] of Object.entries(act.files)) mp[k] = { name: f.name, mimeType: f.mime || 'text/plain', buffer: Buffer.from(sub(f.text), 'utf8') }; r = await s.ctx.request.post(url, { ...opt, multipart: mp }); }
          else r = await s.ctx.request.post(url, { ...opt, form });
        } else {
          const tk = await token(act.as); out.tokenStatus = s.tokenStatus; t0 = Date.now(); // latency without the sign-in wait
          const h = tk ? { Authorization: 'Bearer ' + tk } : {};
          r = act.method === 'API_GET' ? await s.ctx.request.get(url, { ...opt, headers: h }) : await s.ctx.request.post(url, { ...opt, headers: h, data: act.json || {} });
        }
        out.ms = Date.now() - t0; out.status = r.status(); out.location = r.headers()['location'] || ''; out.cell = cell(out.status, out.location);
        const body = await r.text().catch(() => ''); out.bytes = body.length;
        if (out.status >= 400) {
          const al = [...body.matchAll(/(?:role="alert"|class="error"|data-testid="problem[a-z-]*")[^>]*>([\s\S]{0,800}?)<\/(?:p|div|section|strong)>/g)].map(m => m[1].replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()).filter(Boolean);
          const main = (body.split(/<main[^>]*>/)[1] || body).replace(/<script[\s\S]*?<\/script>/g, ' ').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
          out.err = (al.join(' | ') || main).slice(0, 400);
        }
        const m = body.match(/<input[^>]+name="csrf"[^>]+value="([^"]+)"/); if (m) s.csrf = m[1];
        for (const [k, re] of Object.entries(act.save || {})) { const mm = (out.location + '\n' + body).match(new RegExp(re)); if (mm) { vars[k] = mm[1]; out['saved_' + k] = mm[1]; } }
        if (act.keepBody) out.body = body.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, act.keepBody);
      }
    } catch (e) { out.error = e.message.slice(0, 200); }
    console.log(JSON.stringify(out));
  }
  console.error('VARS ' + JSON.stringify(Object.fromEntries(Object.entries(vars).filter(([k]) => !k.startsWith('secret_')))));
  await browser.close();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
