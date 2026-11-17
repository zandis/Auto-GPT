// H-29 (D-1103): the module walks in a browser, driven by tests/e2e/test_module_walks.py. The browser driver is H-20's
// (tests/e2e/life_cycle_walk.js), required as it is: the same sign-in, acting role, language switch, acts,
// expectations, reasoned stops, refusals and per-step JSON log. This file only adds, through the driver's ``extend``,
// the acts and the expectation a module's forms need and H-20's walk did not:
//
//   * "field":  type ``value`` into the input whose label starts with ``label`` (a built-in form's field label: the
//               form marks a required field with a star after the label, so the label is not the field's whole name);
//   * "choose": in the group of choices whose legend starts with ``label``, choose the one labelled ``text``;
//   * "check":  tick the box labelled ``label`` (exactly);
//   * "pick":   choose ``value`` in the select whose label starts with ``label``;
//   * expectation "absent": the main part of the page does not hold ``text`` (or ``value``).
//
//   node tests/e2e/module_walk.js '<the plan as JSON>'
//
// One JSON line on stdout; exit 1 on a failed check (H-20's driver writes both).
"use strict";

const driver = require("./life_cycle_walk.js");

function startsWith(label) {
  return new RegExp("^\\s*" + String(label).replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
}

async function labelled(p, label) {
  const l = p.locator("main label").filter({ hasText: startsWith(label) }).first();
  const id = await l.getAttribute("for");
  return id ? p.locator("main").locator("#" + id) : l.locator("input, select, textarea").first();
}

driver.extend({
  acts: {
    async field(p, a, tag, h) {
      if (h.rec) h.rec.inputs.push(a.label);
      return (await labelled(p, a.label)).fill(h.fill(a.value));
    },
    async pick(p, a, tag, h) {
      if (h.rec) h.rec.inputs.push(a.label);
      return (await labelled(p, a.label)).selectOption(h.fill(a.value));
    },
    async choose(p, a, tag, h) {
      const legend = p.locator("legend", { hasText: startsWith(a.label) });
      const group = p.locator("main fieldset").filter({ has: legend }).first();
      await group.getByLabel(h.fill(a.text), { exact: true }).check();
      return h.clicked(a.label + ": " + h.fill(a.text));
    },
    async check(p, a, tag, h) {
      await p.locator("main").getByLabel(a.label, { exact: true }).first().check();
      return h.clicked(a.label);
    },
  },
  holds: {
    async absent(p, a, h) {
      const where = new URL(p.url()).pathname;
      const t = (await p.locator("main").innerText()).replace(/\s+/g, " ");
      const what = h.fill(a.text) || h.fill(a.value);
      return [Boolean(what) && !t.includes(what), `does not show "${h.masked(what).slice(0, 60)}" at ${h.masked(where)}`];
    },
  },
});

driver.main();
