(function () {
  "use strict";
  // D-133. Allowed by its hash in the page's Content-Security-Policy; every page works without it.
  // 1. A "Copy" button next to a read-only value (the one-time password): shown only when it can work.
  document.querySelectorAll("button[data-copy]").forEach(function (b) {
    var src = document.getElementById(b.getAttribute("data-copy"));
    if (!src || !navigator.clipboard) return;
    b.hidden = false;
    b.addEventListener("click", function () {
      navigator.clipboard.writeText(src.value || src.textContent || "").then(function () {
        b.textContent = b.getAttribute("data-done") || b.textContent;
      });
    });
  });
  // 2. "Back" on an error page goes back in the browser's history (without a script it is the home page).
  document.querySelectorAll("a[data-back]").forEach(function (a) {
    a.addEventListener("click", function (e) {
      if (window.history.length > 1) { e.preventDefault(); window.history.back(); }
    });
  });
  // 3. A form marked data-guard warns before the page is left with edits not yet saved.
  var dirty = false;
  document.querySelectorAll("form[data-guard]").forEach(function (f) {
    f.addEventListener("input", function () { dirty = true; });
    f.addEventListener("change", function () { dirty = true; });
    f.addEventListener("submit", function () { dirty = false; });
  });
  window.addEventListener("beforeunload", function (e) {
    if (!dirty) return;
    e.preventDefault();
    e.returnValue = "";
  });
  // 4. D-776 (D-509): the first sign-in from a one-time link, <box>/enrol#u=<name>&c=<code>. The part after "#" never
  // reaches the server; on the first sign-in it fills the two fields. On every page (a signed-in person is sent on to
  // the home page with it) a code after "#" is then removed from the address bar and the Back history.
  var frag = window.location.hash.length > 1 ? new URLSearchParams(window.location.hash.slice(1)) : null;
  if (frag && frag.get("c")) {
    var link = document.querySelector("form[data-enrol-link]");
    var u = link && link.querySelector("#username"), c = link && link.querySelector("#enrol_code");
    if (u && frag.get("u") && !u.value) u.value = frag.get("u");
    if (c) c.value = frag.get("c");
    if (window.history.replaceState) window.history.replaceState(null, "", window.location.pathname + window.location.search);
  }
  // 5. D-777 (UX-007): a mark's note is kept in this tab's session storage while it is typed, so a session that ends
  // before the mark is sent does not lose it: after sign-in, back on that patient's page, it is put back (never over
  // a note typed since). A saved mark (its done toast) drops it.
  try {
    document.querySelectorAll("[data-mark-saved]").forEach(function (t) {
      sessionStorage.removeItem("tb-note:" + t.getAttribute("data-mark-saved"));
    });
    document.querySelectorAll("input[data-keep-note]").forEach(function (n) {
      var key = "tb-note:" + n.getAttribute("data-keep-note");
      var kept = sessionStorage.getItem(key);
      if (kept && !n.value) n.value = kept;
      n.addEventListener("input", function () {
        if (n.value) sessionStorage.setItem(key, n.value); else sessionStorage.removeItem(key);
      });
    });
  } catch (e) { /* no session storage (a private mode that refuses it): the page works as before */ }
  // 6. D-1222 (E-M3): a long form marked data-keep (an AE's or a visit's form) is kept in this tab's session storage
  // while it is typed, as a mark's note is, so a session that ends before Save does not lose it: back on the same form
  // after sign-in, the kept values go into the fields still empty (never over a value shown) and count as unsaved
  // edits. A sent form is dropped on the next page that is neither a sign-in page nor that same form (the save reached
  // a live session). A save that met the sign-in page instead (the session had ended) keeps it, and when the sign-in
  // lands on the home page (no page was kept: the console sends no Referer) the tab goes back to the form's own address,
  // a path of this console. Sign out drops every kept form.
  try {
    var SENT = "tb-form-sent", AT = "tb-form-sent-at", VIA = "tb-form-via-sign-in";
    var sent = sessionStorage.getItem(SENT);
    var here = false, signIn = !!document.querySelector("form[action^='/login']");
    document.querySelectorAll("form[data-keep]").forEach(function (f) {
      var id = f.getAttribute("data-keep"), key = "tb-form:" + id;
      if (id === sent) here = true;
      var fields = function () {
        return Array.prototype.filter.call(f.elements, function (e) {
          return e.name && !e.disabled && ["hidden", "submit", "button"].indexOf(e.type) < 0;
        });
      };
      var kept = JSON.parse(sessionStorage.getItem(key) || "null");
      if (kept) {
        var all = fields(), had = {}, back = false;
        all.forEach(function (x) { if (x.checked) had[x.name] = true; });  // a group with a box ticked stays as shown
        all.forEach(function (e) {
          var v = kept[e.name];
          if (v === undefined) return;
          if (e.type === "checkbox" || e.type === "radio") {
            if (!had[e.name] && v.indexOf(e.value) >= 0) e.checked = back = true;
          } else if (!e.value) {
            e.value = v;
            back = true;
          }
        });
        if (back && f.hasAttribute("data-guard")) dirty = true;
      }
      var save = function () {
        var out = {};
        fields().forEach(function (e) {
          if (e.type === "checkbox" || e.type === "radio") {
            if (e.checked) (out[e.name] = out[e.name] || []).push(e.value);
          } else if (e.value) out[e.name] = e.value;
        });
        if (Object.keys(out).length) sessionStorage.setItem(key, JSON.stringify(out)); else sessionStorage.removeItem(key);
      };
      f.addEventListener("input", save);
      f.addEventListener("change", save);
      f.addEventListener("submit", function () {
        sessionStorage.setItem(SENT, id);
        sessionStorage.setItem(AT, window.location.pathname + window.location.search);
        sessionStorage.removeItem(VIA);
      });
    });
    if (sent && signIn) {
      sessionStorage.setItem(VIA, "1");
    } else if (sent) {
      var via = sessionStorage.getItem(VIA), at = sessionStorage.getItem(AT) || "";
      [SENT, AT, VIA].forEach(function (k) { sessionStorage.removeItem(k); });
      if (!here && !via) {
        sessionStorage.removeItem("tb-form:" + sent);
      } else if (!here && /^\/[^/\\]/.test(at) && ["/", "/home"].indexOf(window.location.pathname) >= 0) {
        window.location.replace(at);
      }
    }
    document.querySelectorAll("form[action='/logout']").forEach(function (f) {
      f.addEventListener("submit", function () {
        for (var i = sessionStorage.length - 1; i >= 0; i--) {
          var k = sessionStorage.key(i);
          if (k && k.indexOf("tb-form") === 0) sessionStorage.removeItem(k);
        }
      });
    });
  } catch (e) { /* no session storage: the page works as before */ }
})();
