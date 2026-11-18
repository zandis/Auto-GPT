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
  // while it is typed, so a session that ends before it is saved does not lose it. It is put back only once: on the
  // way back from the sign-in after a save met the ended session, with a notice saying how many fields came back and
  // a button that throws them away, the fields marked. Never on a later visit. Dropped: when a save reaches a live session (also
  // when the same form is shown again), when the person leaves the form without saving, after 12 hours, and whenever
  // the page's account (meta tb-user) is not the entry's; signing out drops every kept form. After the sign-in, the
  // home page sends the tab back to the form's own address (record, event, form), never another account's.
  try {
    var PRE = "tb-form:", SENT = "tb-form-sent", VIA = "tb-form-via-sign-in", BACK = "tb-form-restore";
    var AGE = 12 * 3600 * 1000, now = Date.now();
    var who = document.querySelector("meta[name='tb-user']");
    var me = who ? who.getAttribute("content") : null;
    var signIn = !!document.querySelector("form[action^='/login']");
    var read = function (k) {
      try { return JSON.parse(sessionStorage.getItem(k) || "null"); } catch (e) { return null; }
    };
    var owner = function (id) { return String(id || "").split("|")[0]; };
    var drop = function (k) { sessionStorage.removeItem(k); };
    for (var i = sessionStorage.length - 1; i >= 0; i--) {
      var k = sessionStorage.key(i), e = k && k.indexOf(PRE) === 0 ? read(k) : null;
      if (k && k.indexOf(PRE) === 0 && (!e || !(now - e.at < AGE) || (me && e.user !== me))) drop(k);
    }
    var sent = read(SENT), here = {}, going = false;
    if (sent && (!(now - sent.at < AGE) || (me && owner(sent.id) !== me))) { drop(SENT); drop(VIA); sent = null; }
    if ((read(BACK) || {}).user !== me && me) drop(BACK);
    document.querySelectorAll("form[data-keep]").forEach(function (f) { here[f.getAttribute("data-keep")] = true; });
    if (sent && signIn) {
      sessionStorage.setItem(VIA, "1");
    } else if (sent && me) {
      var via = sessionStorage.getItem(VIA);
      drop(SENT); drop(VIA);
      if (!via) {
        drop(PRE + sent.id); // the save reached a live session
      } else {
        sessionStorage.setItem(BACK, JSON.stringify({ id: sent.id, user: me }));
        if (!here[sent.id] && /^\/[^/\\]/.test(sent.url) && ["/", "/home"].indexOf(window.location.pathname) >= 0) {
          going = true;
          window.location.replace(sent.url);
        }
      }
    }
    var back = read(BACK);
    document.querySelectorAll("form[data-keep]").forEach(function (f) {
      var id = f.getAttribute("data-keep"), key = PRE + id, submitting = false;
      var fields = function () {
        return Array.prototype.filter.call(f.elements, function (x) {
          return x.name && !x.disabled && ["hidden", "submit", "button"].indexOf(x.type) < 0;
        });
      };
      if (back && back.id === id) {
        drop(BACK);
        var kept = read(key), put = [];
        if (kept && kept.user === me) {
          var all = fields(), had = {};
          all.forEach(function (x) { if (x.checked) had[x.name] = true; }); // a group with a box ticked stays as shown
          all.forEach(function (x) {
            var v = (kept.v || {})[x.name];
            if (v === undefined) return;
            if (x.type === "checkbox" || x.type === "radio") {
              if (!had[x.name] && v.indexOf(x.value) >= 0) { x.checked = true; put.push(x); }
            } else if (!x.value) { x.value = v; put.push(x); }
          });
        }
        if (put.length) {
          if (f.hasAttribute("data-guard")) dirty = true;
          put.forEach(function (x) { x.classList.add("restored"); });
          var note = document.createElement("p"), btn = document.createElement("button"), span = document.createElement("span");
          note.className = "warn";
          note.setAttribute("role", "status");
          note.setAttribute("data-testid", "form-restored");
          span.textContent = (f.getAttribute("data-keep-msg") || "{n}").replace("{n}", String(put.length)) + " ";
          btn.type = "button";
          btn.className = "secondary small";
          btn.setAttribute("data-testid", "form-discard");
          btn.textContent = f.getAttribute("data-keep-discard") || "×";
          btn.addEventListener("click", function () {
            put.forEach(function (x) {
              if (x.type === "checkbox" || x.type === "radio") x.checked = false; else x.value = "";
              x.classList.remove("restored");
            });
            drop(key);
            note.parentNode.removeChild(note);
          });
          note.appendChild(span);
          note.appendChild(btn);
          f.parentNode.insertBefore(note, f);
        }
      }
      var save = function () {
        var out = {}, any = false;
        fields().forEach(function (x) {
          if (x.type === "checkbox" || x.type === "radio") {
            if (x.checked) { (out[x.name] = out[x.name] || []).push(x.value); any = true; }
          } else if (x.value) { out[x.name] = x.value; any = true; }
        });
        if (any && me) sessionStorage.setItem(key, JSON.stringify({ user: me, at: Date.now(), v: out }));
        else drop(key);
      };
      f.addEventListener("input", save);
      f.addEventListener("change", save);
      f.addEventListener("submit", function () {
        submitting = true;
        var q = ["record", "event", "form", "back"].map(function (n) {
          var x = f.querySelector("input[type=hidden][name=" + n + "]");
          return x && x.value ? n + "=" + encodeURIComponent(x.value) : "";
        }).filter(Boolean).join("&");
        var to = (f.getAttribute("action") || window.location.pathname) + (q ? "?" + q : "");
        sessionStorage.setItem(SENT, JSON.stringify({ id: id, at: Date.now(), url: to }));
        drop(VIA);
      });
      window.addEventListener("pagehide", function () { if (!submitting) drop(key); }); // left without saving
    });
    if (back && !going) drop(BACK); // one time only: never on a later visit
    document.querySelectorAll("form[action='/logout']").forEach(function (f) {
      f.addEventListener("submit", function () {
        for (var j = sessionStorage.length - 1; j >= 0; j--) {
          var n = sessionStorage.key(j);
          if (n && n.indexOf("tb-form") === 0) drop(n);
        }
      });
    });
  } catch (e) { /* no session storage: the page works as before */ }
})();
