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
})();
