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
  // 7. D-1370 (9g-19, A11Y-3): shortly before the idle lock (a minute; half the limit when it is shorter) a warning with
  // "Stay signed in"; at the session's absolute end the same warning without it (that limit is never extended). The
  // times come from the server with the page and count from the navigation's start on the page's own monotonic clock
  // (performance.now: the server's count began later, so the page errs early, and a jump of the system clock moves
  // nothing). "Stay signed in" asks a stay page the person may open anyway (data-stay-url) with keep=1: activity, as
  // any page is, answered with the times and no page. A redirect elsewhere than the sign-in (the password page) means
  // signed in, time unknown: no lock is shown. When the page becomes visible again it asks quietly too. Before showing the lock the page asks again with auto=1 as well (not activity):
  // another tab may have kept the session awake, and then the warning is armed again from the times it answers. The
  // page is never reloaded or left, so what was typed stays where it is; nothing typed is read or stored here.
  var iw = document.getElementById("idle-warn");
  if (iw && window.performance && window.fetch) {
    var num = function (n) { return Math.max(0, Number(iw.getAttribute(n)) || 0) * 1000; };
    var clock = function () { return window.performance.now(); }; // 0 is the navigation's start
    var idleMs = num("data-idle"), lead = num("data-lead"), idleEnd = num("data-idle-left"), absEnd = num("data-abs-left");
    var stay = iw.querySelector("[data-idle-stay]"), close = iw.querySelector("[data-idle-close]");
    var title = document.getElementById("idle-warn-title"), text = document.getElementById("idle-warn-text");
    var base = iw.getAttribute("data-stay-url") || "/";
    var shown = "", timer = null, asked = false, before = null, dismissed = "", checking = false;
    var say = function (kind) {
      shown = kind;
      title.textContent = iw.getAttribute("data-" + kind + "-title") || "";
      text.textContent = iw.getAttribute("data-" + kind + "-text") || "";
      iw.setAttribute("data-state", kind);
      stay.hidden = kind !== "soon";
      close.hidden = kind === "soon";
      if (iw.hidden) { before = document.activeElement; iw.hidden = false; }
      (kind === "soon" ? stay : close).focus();
    };
    var hide = function () {
      iw.hidden = true;
      iw.removeAttribute("data-state");
      dismissed = shown; // a closed warning is not shown again (the lock still is)
      shown = "";
      if (before && before.focus && document.body.contains(before)) before.focus(); // back where the person typed
      before = null;
    };
    // the session's state from the server: "ended" (sent to the sign-in), or the seconds it has left
    var ask = function (quiet) {
      var sent = clock();
      return fetch(base + (base.indexOf("?") < 0 ? "?" : "&") + "keep=1" + (quiet ? "&auto=1" : ""),
        { credentials: "same-origin", cache: "no-store" }).then(function (r) {
        if (new URL(r.url, window.location.href).pathname === "/login") return { ended: true };
        if (r.redirected) return { unknown: true }; // sent elsewhere (the password page): signed in, time unknown
        var idle = Number(r.headers.get("x-tb-idle-left")), abs = Number(r.headers.get("x-tb-abs-left"));
        if (!r.ok || !isFinite(idle) || !isFinite(abs) || r.headers.get("x-tb-idle-left") === null) return null;
        return { ended: idle <= 0 || abs <= 0, idleEnd: sent + idle * 1000, absEnd: sent + abs * 1000 };
      });
    };
    var rearm = function (got) {
      idleEnd = got.idleEnd;
      absEnd = got.absEnd;
      if (shown) hide();
      dismissed = "";
      tick();
    };
    var tick = function () {
      if (timer) clearTimeout(timer);
      if (shown === "locked" || dismissed === "locked" || checking) return;
      var now = clock(), end = Math.min(idleEnd, absEnd);
      if (now >= end) { // before saying so, ask whether another tab kept the session awake
        checking = true;
        ask(true).then(function (got) {
          checking = false;
          if (got && got.unknown) { if (shown) hide(); dismissed = "locked"; return; } // cannot tell: say nothing
          if (got && !got.ended && Math.min(got.idleEnd, got.absEnd) > clock() + 1000) rearm(got); else say("locked");
        }, function () { checking = false; say("locked"); });
        return;
      }
      if (now >= end - lead && !shown && !dismissed) say(absEnd <= idleEnd ? "limit" : "soon");
      var next = now >= end - lead ? end : end - lead;
      timer = setTimeout(tick, Math.max(250, Math.min(next - now, 15000)));
    };
    stay.addEventListener("click", function () {
      if (asked) return;
      asked = true;
      ask(false).then(function (got) {
        asked = false;
        if (got && got.ended) { say("locked"); return; }
        if (got && got.unknown) { hide(); return; }
        if (got) rearm(got); // else the box did not answer as expected: the warning stays, the person may press again
      }, function () { asked = false; }); // no answer (the network): the warning stays
    });
    close.addEventListener("click", hide);
    iw.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      e.preventDefault();
      if (shown === "soon") stay.click(); else hide(); // Escape on the warning is "Stay signed in"
    });
    // a device that slept: its monotonic clock may not have counted the sleep, so ask (quietly) for the time left
    document.addEventListener("visibilitychange", function () {
      if (document.hidden || checking || shown === "locked" || dismissed === "locked") return;
      checking = true;
      ask(true).then(function (got) {
        checking = false;
        if (got && got.ended) say("locked"); else if (got && !got.unknown) rearm(got); else tick();
      }, function () { checking = false; tick(); });
    });
    tick();
  }
})();
