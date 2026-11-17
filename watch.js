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
    var frame = el(doc, "div", "watch-frame");
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
        if (!frame.firstChild) {
          var f = doc.createElement("iframe");
          f.src = playerSrc(CHANNEL, PARENTS);
          f.title = "Air Travel Desk live video on Twitch";
          f.allowFullscreen = true;
          f.setAttribute("allow", "autoplay; fullscreen");
          f.setAttribute("referrerpolicy", "strict-origin-when-cross-origin");
          f.className = "watch-player";
          frame.appendChild(f);
        }
        drawer.hidden = false;
        if (reduce) { drawer.classList.add("open"); } else { win.requestAnimationFrame(function () { win.requestAnimationFrame(function () { drawer.classList.add("open"); }); }); }
        if (win.scrollY > 120) { win.scrollTo({ top: 0, behavior: reduce ? "auto" : "smooth" }); }
        if (fromTeaser) { close.focus(); }
      } else {
        drawer.classList.remove("open");
        frame.textContent = "";                                  /* removing the player stops the video and its sound */
        hideTimer = win.setTimeout(function () { if (!isOpen) { drawer.hidden = true; } }, reduce ? 0 : 320);
      }
    }

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
