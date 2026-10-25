// TrialBox Test Bench: live job logs over Server-Sent Events. When a job ends, the result block (hx-trigger
// "jobdone") is asked to load. Without htmx the page still links to /jobs/<id>/view.
(function () {
  "use strict";
  function attach(root) {
    root.querySelectorAll("[data-job]").forEach(function (el) {
      if (el.dataset.attached || el.dataset.status !== "running") return;
      el.dataset.attached = "1";
      var log = el.querySelector(".log");
      var result = el.querySelector(".job-result");
      var shown = log ? log.textContent.split("\n").filter(Boolean).length : 0;
      var seen = 0;
      var es = new EventSource("/jobs/" + el.dataset.job + "/events");
      es.addEventListener("log", function (ev) {
        seen += 1;
        if (seen <= shown || !log) return; // lines already rendered server-side
        log.textContent += ev.data + "\n";
        log.scrollTop = log.scrollHeight;
      });
      es.addEventListener("done", function (ev) {
        es.close();
        el.dataset.status = ev.data;
        if (result && window.htmx) {
          window.htmx.trigger(result, "jobdone");
        } else if (result) {
          fetch("/jobs/" + el.dataset.job + "/result").then(function (r) { return r.text(); })
            .then(function (html) { result.innerHTML = html; });
        }
      });
      es.onerror = function () { /* the browser retries; "done" closes the stream */ };
    });
  }
  document.addEventListener("DOMContentLoaded", function () { attach(document); });
  document.addEventListener("htmx:afterSettle", function (ev) { attach(ev.target || document); });
})();
