// H-21 (D-1138): the life-cycle walk on a phone. tests/e2e/life_cycle_walk.js loads this module only when the plan
// has a "viewport" (a phone: {"width": 390, "height": 844}) and calls it at its existing places: the browser context,
// each page reached, each click (is the control on the screen and not covered?), the menu a phone hides the top bar
// behind, an expectation the phone's page does not show, and a control the phone cannot reach. Every measure goes to
// the step's "layout" in the log, with a screenshot in the plan's "shots" folder (outside the repository).
"use strict";

function phoneWalk(plan, api) {
  const phone = plan.viewport;
  const seen = new Set(); // measures already logged (step, kind, path, what)
  const masked = api.masked;
  const clicked = api.clicked;
  let rec = null;
  const sync = () => { rec = api.rec(); };

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
    // a control inside a closed group of the menu (layout.phone_first folds More in two levels, D-1222): its group
    // opened first, as a person would, and logged as its own measure
    // (a role locator does not see a link in a closed group, so the group is found by the link's text)
    const quoted = JSON.stringify(text).replace(/^"|"$/g, "").includes("'") ? `"${text}"` : `'${text}'`;
    // the menu's closed group (<details>), or the week page's study fold (a check box and its label, D-1222)
    const fold = p.locator(`xpath=//details[not(@open)][.//a[normalize-space()=${quoted}]]/summary | `
      + `//div[contains(@class,"pf-fold")][.//a[normalize-space()=${quoted}]]/preceding-sibling::label[1]`).last();
    if (!(await locator.isVisible().catch(() => false)) && (await fold.count())) {
      const label = ((await fold.innerText()) || "").replace(/\s+/g, " ").trim();
      await fold.click();
      clicked(label);
      await note(p, "behind a second fold", `"${text}" sits in the closed group "${label}"`);
    }
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
  
  async function notShown(p, what) {
    // what the desktop page shows and the phone's does not: a measure of the phone (a finding must name it)
    await note(p, "not shown on the phone", what);
    return false;
  }

  async function cannotReach(p, why) {
    await note(p, "cannot be reached", why.slice(0, 200));
  }

  const wrap = (f) => async (...args) => { sync(); return f(...args); };
  return {
    context: { viewport: { width: phone.width, height: phone.height }, isMobile: true, hasTouch: true },
    measure: wrap(measure),
    reachable: wrap(reachable),
    openMenu: wrap(openMenu),
    notShown: wrap(notShown),
    cannotReach: wrap(cannotReach),
  };
}

module.exports = { phoneWalk };
