/* TrialBox site: language toggle for chart labels, tooltips, demo walkthrough. No external requests. */
(function () {
  "use strict";
  var root = document.documentElement;
  root.classList.add("js");

  // ---- EN / 日本語 toggle (pages with data-toggle="lang"; landing pages link to their own translations instead)
  function setLang(lang, remember) {
    if (root.getAttribute("data-toggle") !== "lang") return;
    root.setAttribute("data-lang", lang);
    var buttons = document.querySelectorAll("[data-set-lang]");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].setAttribute("aria-pressed", buttons[i].getAttribute("data-set-lang") === lang ? "true" : "false");
    }
    if (remember) {
      try { localStorage.setItem("tb-lang", lang); } catch (e) { /* storage blocked: toggle still works */ }
    }
  }
  document.addEventListener("click", function (ev) {
    var t = ev.target && ev.target.closest ? ev.target.closest("[data-set-lang]") : null;
    if (t) { ev.preventDefault(); setLang(t.getAttribute("data-set-lang"), true); }
  });
  setLang(root.getAttribute("data-lang") || "en", false);

  // ---- tooltips on chart rows (hover and keyboard focus)
  var tip = null;
  function showTip(el) {
    var text = el.getAttribute("data-tip");
    if (!text) return;
    if (root.getAttribute("data-lang") === "ja" && el.getAttribute("data-tip-ja")) text = el.getAttribute("data-tip-ja");
    if (!tip) { tip = document.createElement("div"); tip.className = "tip"; tip.setAttribute("role", "tooltip"); document.body.appendChild(tip); }
    tip.textContent = text;
    var r = el.getBoundingClientRect();
    tip.style.display = "block";
    var w = tip.offsetWidth, h = tip.offsetHeight;
    var x = Math.min(window.innerWidth - w - 8, Math.max(8, r.left + r.width / 2 - w / 2));
    var y = r.top - h - 8;
    if (y < 8) y = r.bottom + 8;
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  }
  function hideTip() { if (tip) tip.style.display = "none"; }
  document.addEventListener("mouseover", function (ev) {
    var el = ev.target && ev.target.closest ? ev.target.closest("[data-tip]") : null;
    if (el) showTip(el); else hideTip();
  });
  document.addEventListener("focusin", function (ev) {
    var el = ev.target && ev.target.closest ? ev.target.closest("[data-tip]") : null;
    if (el) showTip(el); else hideTip();
  });
  document.addEventListener("scroll", hideTip, { passive: true });

  // ---- walkthrough stepper (demo page); without JS every panel is visible
  var panels = document.querySelectorAll(".step-panel");
  var tabs = document.querySelectorAll(".stepper [data-step]");
  if (panels.length && tabs.length) {
    var current = 0;
    function show(i, focus) {
      current = Math.max(0, Math.min(panels.length - 1, i));
      for (var p = 0; p < panels.length; p++) panels[p].hidden = p !== current;
      for (var t = 0; t < tabs.length; t++) {
        tabs[t].setAttribute("aria-selected", t === current ? "true" : "false");
        tabs[t].tabIndex = t === current ? 0 : -1;
      }
      var prev = document.getElementById("step-prev"), next = document.getElementById("step-next");
      if (prev) prev.disabled = current === 0;
      if (next) next.disabled = current === panels.length - 1;
      if (focus) tabs[current].focus();
      try { history.replaceState(null, "", "#" + panels[current].id); } catch (e) { /* file:// */ }
    }
    for (var k = 0; k < tabs.length; k++) {
      tabs[k].addEventListener("click", function (ev) { show(parseInt(ev.currentTarget.getAttribute("data-step"), 10), false); });
      tabs[k].addEventListener("keydown", function (ev) {
        if (ev.key === "ArrowRight") { ev.preventDefault(); show(current + 1, true); }
        if (ev.key === "ArrowLeft") { ev.preventDefault(); show(current - 1, true); }
      });
    }
    var pb = document.getElementById("step-prev"), nb = document.getElementById("step-next");
    if (pb) pb.addEventListener("click", function () { show(current - 1, false); });
    if (nb) nb.addEventListener("click", function () { show(current + 1, false); });
    var start = 0;
    for (var q = 0; q < panels.length; q++) if ("#" + panels[q].id === location.hash) start = q;
    show(start, false);
  }
})();
