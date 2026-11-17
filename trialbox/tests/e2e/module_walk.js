// H-29 (D-1103): the module walks in a browser, driven by tests/e2e/test_module_walks.py. It is H-20's driver
// (tests/e2e/life_cycle_walk.js), loaded from that file as it stands, not a copy: the same sign-in, acting role,
// language switch, acts, expectations, reasoned stops, refusals and per-step JSON log. Two lines of it are widened
// when it is loaded: the "unknown action" and "unknown expectation" ends of its two switches hand the acts and
// expectations it does not know to the functions below, which run inside its scope (its helpers, its log record).
// tests/e2e/test_module_walks.py fails when either line is not in H-20's driver exactly once.
//
//   node tests/e2e/module_walk.js '<the plan as JSON>'
//
// The acts added here are the ones a module's forms need and H-20's walk did not:
//   * "field":  type ``value`` into the input whose label starts with ``label`` (a built-in form's field label: the
//               form marks a required field with a star after the label, so the label is not the field's whole name);
//   * "choose": in the group of choices whose legend starts with ``label``, choose the one labelled ``text``;
//   * "check":  tick the box labelled ``label`` (exactly);
//   * "pick":   choose ``value`` in the select whose label starts with ``label`` (a select of a built-in form, or a
//               filter whose label holds a hint after its name).
// and the expectation "absent": the main part of the page does not hold ``text`` (or ``value``, a remembered one).
// One JSON line on stdout; exit 1 on a failed check (H-20's driver writes both).
"use strict";

const fs = require("fs");
const path = require("path");
const Module = require("module");

const DRIVER = path.join(__dirname, "life_cycle_walk.js");
const SEAMS = [
  ['default:\n      throw new Error("unknown action " + a.do);', "default:\n      return moduleAct(p, a);"],
  ['default:\n      throw new Error("unknown expectation " + a.kind);', "default:\n      return moduleHolds(p, a);"],
];

// The functions below are appended to H-20's driver (their source, as written here) and run in its scope: they use
// its check, clicked, fill, masked and rec. They are never called in this file.
/* global fill, rec, clicked, masked */
function startsWith(label) {
  return new RegExp("^\\s*" + String(label).replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
}

async function labelled(p, label) {
  const l = p.locator("main label").filter({ hasText: startsWith(label) }).first();
  const id = await l.getAttribute("for");
  return id ? p.locator("main").locator("#" + id) : l.locator("input, select, textarea").first();
}

async function moduleAct(p, a) {
  const text = fill(a.text);
  const value = fill(a.value);
  switch (a.do) {
    case "field":
      if (rec) rec.inputs.push(a.label);
      return (await labelled(p, a.label)).fill(value);
    case "pick":
      if (rec) rec.inputs.push(a.label);
      return (await labelled(p, a.label)).selectOption(value);
    case "choose": {
      const legend = p.locator("legend", { hasText: startsWith(a.label) });
      const group = p.locator("main fieldset").filter({ has: legend }).first();
      await group.getByLabel(text, { exact: true }).check();
      return clicked(a.label + ": " + text);
    }
    case "check":
      await p.locator("main").getByLabel(a.label, { exact: true }).first().check();
      return clicked(a.label);
    default:
      throw new Error("unknown action " + a.do);
  }
}

async function moduleHolds(p, a) {
  const where = new URL(p.url()).pathname;
  switch (a.kind) {
    case "absent": {
      const t = (await p.locator("main").innerText()).replace(/\s+/g, " ");
      const what = fill(a.text) || fill(a.value);
      return [Boolean(what) && !t.includes(what), `does not show "${masked(what).slice(0, 60)}" at ${masked(where)}`];
    }
    default:
      throw new Error("unknown expectation " + a.kind);
  }
}

const EXTENSION = [startsWith, labelled, moduleAct, moduleHolds].map((f) => f.toString()).join("\n\n");

function load() {
  let src = fs.readFileSync(DRIVER, "utf8");
  for (const [seam, widened] of SEAMS) {
    if (src.split(seam).length !== 2) throw new Error("H-20's driver changed: the line to widen is not there once: " + seam);
    src = src.replace(seam, widened);
  }
  const m = new Module(DRIVER, module);
  m.filename = DRIVER;
  m.paths = Module._nodeModulePaths(path.dirname(DRIVER));
  m._compile(src + "\n" + EXTENSION, DRIVER);
}

load();
