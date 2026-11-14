/* Air Travel Desk: fills the "Last checked" column of sources.html from data/sources.json. */
(function () {
  "use strict";
  var A = window.ATD;
  var status = document.getElementById("src-status");

  function done(msg) { if (status) { status.textContent = msg; } }

  fetch("data/sources.json", { cache: "no-store" })
    .then(function (r) { if (!r.ok) { throw new Error("HTTP " + r.status); } return r.json(); })
    .then(function (d) {
      var byId = {};
      (d.sources || []).forEach(function (s) { byId[s.id] = s; });
      var rows = document.querySelectorAll("tr[data-src]");
      Array.prototype.forEach.call(rows, function (tr) {
        var cell = tr.querySelector(".src-checked");
        var s = byId[tr.getAttribute("data-src")];
        if (!cell) { return; }
        if (!s) { cell.textContent = "No time on file"; return; }
        var v = A.checkedView(s.kind, s.checked);
        cell.textContent = v.text + (v.age ? " (" + v.age + ")" : "");
      });
      done("Check times built " + A.checkedView("time", d.generated_utc).age + ".");
    })
    .catch(function () {
      Array.prototype.forEach.call(document.querySelectorAll(".src-checked"), function (c) { c.textContent = "Could not load"; });
      done("Could not load the check times. The list below is still correct.");
    });
})();
