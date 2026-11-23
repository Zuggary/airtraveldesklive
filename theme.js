/* AN38: theme switch. Three states: System (default, no data-theme), Light, Dark. The choice is kept in localStorage (guarded). The inline snippet in <head> applies it before paint. */
(function () {
  "use strict";
  var KEY = "atd-theme", ORDER = ["system", "light", "dark"], LABEL = { system: "System", light: "Light", dark: "Dark" };
  function read() { try { var v = localStorage.getItem(KEY); return v === "light" || v === "dark" ? v : "system"; } catch (e) { return "system"; } }
  function write(v) { try { if (v === "system") { localStorage.removeItem(KEY); } else { localStorage.setItem(KEY, v); } } catch (e) { /* private mode: the choice lasts for this page only */ } }
  function apply(v) {
    var h = document.documentElement;
    if (v === "light" || v === "dark") { h.setAttribute("data-theme", v); } else { h.removeAttribute("data-theme"); }
    var metas = document.querySelectorAll('meta[name="theme-color"]');
    for (var i = 0; i < metas.length; i++) {
      if (!metas[i].hasAttribute("data-orig")) { metas[i].setAttribute("data-orig", metas[i].getAttribute("media") || ""); }
      if (v === "system") { metas[i].setAttribute("media", metas[i].getAttribute("data-orig")); }
      else { var dark = /dark/.test(metas[i].getAttribute("data-orig")); if ((v === "dark") === dark) { metas[i].removeAttribute("media"); } else { metas[i].setAttribute("media", "not all"); } }
    }
  }
  function paint(btn, v) {
    btn.setAttribute("data-mode", v);
    btn.setAttribute("aria-label", "Theme: " + LABEL[v] + ". Press to change.");
    btn.setAttribute("title", "Theme: " + LABEL[v]);
  }
  var cur = read();
  apply(cur);
  function init() {
    var btns = document.querySelectorAll("[data-theme-toggle]");
    for (var i = 0; i < btns.length; i++) {
      (function (btn) {
        paint(btn, cur);
        btn.addEventListener("click", function () {
          cur = ORDER[(ORDER.indexOf(cur) + 1) % ORDER.length];
          write(cur); apply(cur);
          var all = document.querySelectorAll("[data-theme-toggle]");
          for (var k = 0; k < all.length; k++) { paint(all[k], cur); }
          try { window.dispatchEvent(new Event("atd-theme")); } catch (e) { /* old browser */ }
        });
      })(btns[i]);
    }
  }
  // 23 Nov: on phones the header is brand + Menu. The Menu button is added here, so without JavaScript the full nav stays visible.
  function menu() {
    var hdr = document.querySelector(".header-in");
    if (!hdr || hdr.querySelector(".menu-btn")) { return; }
    var nav = hdr.querySelector(".header-nav");
    if (!nav) { return; }
    if (!nav.id) { nav.id = "site-menu"; }
    var b = document.createElement("button");
    b.type = "button"; b.className = "menu-btn"; b.textContent = "Menu";
    b.setAttribute("aria-expanded", "false"); b.setAttribute("aria-controls", nav.id);
    var tog = hdr.querySelector("[data-theme-toggle]");
    if (tog) { hdr.insertBefore(b, tog); } else { hdr.appendChild(b); }
    document.documentElement.classList.add("has-menu");
    function set(open) { hdr.classList.toggle("menu-open", open); b.setAttribute("aria-expanded", open ? "true" : "false"); }
    b.addEventListener("click", function () { set(!hdr.classList.contains("menu-open")); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && hdr.classList.contains("menu-open")) { set(false); b.focus(); } });
  }
  function boot() { init(); menu(); }
  if (document.readyState === "loading") { document.addEventListener("DOMContentLoaded", boot); } else { boot(); }
})();
