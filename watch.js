/* Air Travel Desk: "Watch live" button in the top bar on every page. Press it and a 16:9 Twitch player slides down under the header;
   Esc, the close button or pressing the button again slides it shut and removes the player. Nothing loads from Twitch (no iframe,
   no request, no cookie) until the first press, so page speed is unchanged. The home page's "Live now" card opens the same player. */
(function (root) {
  "use strict";

  var CHANNEL = "airtraveldesklive";
  var PARENTS = ["www.airtraveldesklive.com", "airtraveldesklive.com"];

  /* The player address: the channel, the two site domains as parent, muted so a phone does not start loud. Pure. */
  function playerSrc(channel, parents) {
    return "https://player.twitch.tv/?channel=" + encodeURIComponent(channel) +
      parents.map(function (p) { return "&parent=" + encodeURIComponent(p); }).join("") + "&muted=true";
  }

  function el(doc, tag, cls, text) {
    var n = doc.createElement(tag);
    if (cls) { n.className = cls; }
    if (text) { n.textContent = text; }
    return n;
  }

  function start(win) {
    var doc = win.document;
    var header = doc.querySelector(".site-header");
    var headerIn = doc.querySelector(".site-header .header-in");
    if (!header || !headerIn) { return; }

    var btn = el(doc, "button", "watch-btn");
    btn.type = "button";
    btn.setAttribute("aria-expanded", "false");
    btn.setAttribute("aria-controls", "watch-drawer");
    btn.appendChild(el(doc, "span", "watch-btn-dot"));
    btn.appendChild(el(doc, "span", "watch-btn-text", "Watch live"));
    var toggle = headerIn.querySelector(".theme-toggle");
    if (toggle) { headerIn.insertBefore(btn, toggle); } else { headerIn.appendChild(btn); }

    var drawer = el(doc, "section", "watch-drawer");
    drawer.id = "watch-drawer";
    drawer.setAttribute("aria-label", "Live video");
    drawer.hidden = true;
    var inner = el(doc, "div", "watch-drawer-in");
    var bar = el(doc, "div", "watch-drawer-bar");
    bar.appendChild(el(doc, "p", "watch-drawer-note", "Plays from Twitch, which sets its own cookies once it loads. The voice reads the FAA updates around the clock."));
    var close = el(doc, "button", "watch-close", "Close");
    close.type = "button";
    close.setAttribute("aria-label", "Close live video");
    bar.appendChild(close);
    var frame = el(doc, "div", "watch-frame");           /* the in-flow 16:9 slot: it keeps its size when the player docks, so nothing shifts */
    var box = el(doc, "div", "watch-box");               /* the player lives here and never moves in the DOM (moving an iframe reloads it); docking only restyles this box */
    frame.appendChild(box);
    var mini = el(doc, "div", "watch-mini-ctl");
    mini.hidden = true;
    var grab = el(doc, "span", "watch-grab");
    grab.setAttribute("aria-hidden", "true");
    var expand = el(doc, "button", "watch-mini-btn", "\u2191");
    expand.type = "button";
    expand.setAttribute("aria-label", "Back to the player at the top of the page");
    var x = el(doc, "button", "watch-mini-btn", "\u00d7");
    x.type = "button";
    x.setAttribute("aria-label", "Close live video");
    mini.appendChild(grab);
    mini.appendChild(expand);
    mini.appendChild(x);
    box.appendChild(mini);
    inner.appendChild(bar);
    inner.appendChild(frame);
    drawer.appendChild(inner);
    header.parentNode.insertBefore(drawer, header.nextSibling);

    var isOpen = false;
    var hideTimer = null;
    var reduce = win.matchMedia && win.matchMedia("(prefers-reduced-motion: reduce)").matches;

    function setOpen(next, fromTeaser) {
      if (next === isOpen) { return; }
      isOpen = next;
      btn.setAttribute("aria-expanded", next ? "true" : "false");
      win.clearTimeout(hideTimer);
      if (next) {
        if (!box.querySelector("iframe")) {
          var f = doc.createElement("iframe");
          f.src = playerSrc(CHANNEL, PARENTS);
          f.title = "Air Travel Desk live video on Twitch";
          f.allowFullscreen = true;
          f.setAttribute("allow", "autoplay; fullscreen");
          f.setAttribute("referrerpolicy", "strict-origin-when-cross-origin");
          f.className = "watch-player";
          box.insertBefore(f, mini);
        }
        drawer.hidden = false;
        if (reduce) { drawer.classList.add("open"); } else { win.requestAnimationFrame(function () { win.requestAnimationFrame(function () { drawer.classList.add("open"); }); }); }
        if (win.scrollY > 120) { win.scrollTo({ top: 0, behavior: reduce ? "auto" : "smooth" }); }
        if (fromTeaser) { close.focus(); }
      } else {
        drawer.classList.remove("open");
        undock();
        var old = box.querySelector("iframe");
        if (old) { box.removeChild(old); }                       /* removing the player stops the video and its sound */
        hideTimer = win.setTimeout(function () { if (!isOpen) { drawer.hidden = true; } }, reduce ? 0 : 320);
      }
    }

    var docked = false, io = null, dragged = null;
    function dock() {
      if (docked || !isOpen) { return; }
      docked = true;
      frame.classList.add("docked");
      mini.hidden = false;
    }
    function undock() {
      docked = false;
      frame.classList.remove("docked");
      mini.hidden = true;
      box.style.left = box.style.top = box.style.right = box.style.bottom = "";
      dragged = null;
    }
    if (typeof win.IntersectionObserver === "function") {
      io = new win.IntersectionObserver(function (entries) {
        var e = entries[entries.length - 1];
        if (!isOpen) { return; }
        if (!e.isIntersecting && e.boundingClientRect.bottom < 0) { dock(); } else if (e.isIntersecting) { undock(); }
      }, { threshold: 0 });
      io.observe(frame);
    }
    expand.addEventListener("click", function () { undock(); win.scrollTo({ top: 0, behavior: reduce ? "auto" : "smooth" }); });
    x.addEventListener("click", function () { setOpen(false); btn.focus(); });
    /* desktop: drag the mini player by its top strip; it stays inside the window */
    grab.addEventListener("pointerdown", function (e) {
      if (win.innerWidth < 700 || e.button > 0) { return; }
      var r = box.getBoundingClientRect();
      var dx = e.clientX - r.left, dy = e.clientY - r.top;
      var shield = el(doc, "div", "watch-shield");           /* keeps the iframe from swallowing pointer moves */
      box.appendChild(shield);
      function move(ev) {
        var l = Math.max(0, Math.min(win.innerWidth - r.width, ev.clientX - dx));
        var t = Math.max(0, Math.min(win.innerHeight - r.height, ev.clientY - dy));
        box.style.left = l + "px"; box.style.top = t + "px"; box.style.right = "auto"; box.style.bottom = "auto";
        dragged = true;
      }
      function up() { doc.removeEventListener("pointermove", move); doc.removeEventListener("pointerup", up); if (shield.parentNode) { shield.parentNode.removeChild(shield); } }
      doc.addEventListener("pointermove", move);
      doc.addEventListener("pointerup", up);
      e.preventDefault();
    });

    btn.addEventListener("click", function () { setOpen(!isOpen, false); });
    close.addEventListener("click", function () { setOpen(false); btn.focus(); });
    doc.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && isOpen) { setOpen(false); btn.focus(); }
    });
    var cards = doc.querySelectorAll("[data-watch-open]");
    for (var i = 0; i < cards.length; i++) {
      cards[i].addEventListener("click", function () { setOpen(true, true); });
    }
  }

  var api = { playerSrc: playerSrc, CHANNEL: CHANNEL, PARENTS: PARENTS };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; }
  if (root && root.document) { root.ATDWatch = api; start(root); }
})(typeof window !== "undefined" ? window : null);
