/* Air Travel Desk: "Watch live" button in the top bar on every page. Press it and a 16:9 YouTube player slides down under the header;
   Esc, the close button or pressing the button again slides it shut and removes the player. Nothing loads from YouTube (no iframe,
   no request, no cookie) until the first press, so page speed is unchanged. The home page's "Live now" card opens the same player. */
(function (root) {
  "use strict";

  var CHANNEL = "UCtEAjmjCJdR-pHgcZtIFI9w";

  /* YouTube live channel player; autoplay stays disabled after loading. Pure. */
  /* AN180 follow-up (21 Nov): the channel live URL now shows the music-only stream. data/live-main.json {"id": "..."} (written by the factory when the
     main broadcast id changes) names the MAIN broadcast; with a valid id the player embeds that video, otherwise it falls back to the channel stream. Pure. */
  function playerSrc(channel, id) {
    if (typeof id === "string" && /^[A-Za-z0-9_-]{11}$/.test(id)) { return "https://www.youtube.com/embed/" + id + "?autoplay=0"; }
    return "https://www.youtube.com/embed/live_stream?channel=" + encodeURIComponent(channel) + "&autoplay=0";
  }
  function mainWatchUrl(id) { return "https://www.youtube.com/watch?v=" + id; }

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
    var dot = el(doc, "span", "watch-btn-dot");
    dot.setAttribute("aria-hidden", "true");
    btn.appendChild(dot);
    btn.appendChild(el(doc, "span", "watch-btn-text", "Live stream"));
    var toggle = headerIn.querySelector(".theme-toggle");
    if (toggle) { headerIn.insertBefore(btn, toggle); } else { headerIn.appendChild(btn); }

    var drawer = el(doc, "section", "watch-drawer");
    drawer.id = "watch-drawer";
    drawer.setAttribute("aria-label", "Live video");
    drawer.hidden = true;
    drawer.inert = true;
    var inner = el(doc, "div", "watch-drawer-in");
    var bar = el(doc, "div", "watch-drawer-bar");
    bar.appendChild(el(doc, "p", "watch-drawer-note", "Loads from YouTube (Google), which can set its own cookies once it loads. The voice reads the FAA updates around the clock."));
    var close = el(doc, "button", "watch-close", "Close");
    close.type = "button";
    close.setAttribute("aria-label", "Close live video");
    var musicLink = el(doc, "a", "small", "Music only, no talking");   /* AN180: the music-only live stream; shown once data/live-music.json names it */
    musicLink.hidden = true;
    musicLink.rel = "noopener";
    bar.appendChild(musicLink);
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
    var lineup = el(doc, "p", "watch-lineup");           /* AN221: the show lineup page, right under the video */
    var lineupLink = el(doc, "a", "watch-lineup-link", "Show lineup: who is on air and when");
    lineupLink.href = "/shows";
    lineup.appendChild(lineupLink);
    inner.appendChild(lineup);
    drawer.appendChild(inner);
    header.parentNode.insertBefore(drawer, header.nextSibling);

    btn.setAttribute("aria-controls", drawer.id);

    var isOpen = false;
    var opener = btn;
    var hideTimer = null;
    var reduce = win.matchMedia && win.matchMedia("(prefers-reduced-motion: reduce)").matches;


    /* Only the facade press creates a third-party request. Playback needs the player's play button. */
    var mainId = null, mainReady = null;
    function loadMain() {      /* first press only: the page makes no request at load */
      if (mainReady) { return mainReady; }
      if (win.fetch) {
        win.fetch("/data/live-music.json", { credentials: "same-origin", cache: "no-cache" }).then(function (r) { return r.ok ? r.json() : null; }).then(function (j) {
          if (j && typeof j.id === "string" && /^[A-Za-z0-9_-]{11}$/.test(j.id)) { musicLink.href = mainWatchUrl(j.id); musicLink.hidden = false; }
        }).catch(function () {});
      }
      mainReady = (win.fetch ? win.fetch("/data/live-main.json", { credentials: "same-origin", cache: "no-cache" }).then(function (r) { return r.ok ? r.json() : null; }).then(function (j) {
      if (j && typeof j.id === "string" && /^[A-Za-z0-9_-]{11}$/.test(j.id)) {
        mainId = j.id;
        var links = doc.querySelectorAll('a[href$="@AirTravelDeskLive/live"]');       /* "Watch on YouTube" links go to the main broadcast, not the music one */
        for (var i = 0; i < links.length; i += 1) { links[i].href = mainWatchUrl(mainId); }
      }
    }).catch(function () {}) : Promise.resolve());
      return mainReady;
    }
    function mountPlayer() {
      loadMain().then(function () { mountFrame(); });
    }
    function mountFrame() {
      if (box.querySelector("iframe")) { return; }
      var f = doc.createElement("iframe");
      f.src = playerSrc(CHANNEL, mainId);
      f.className = "watch-player";
      f.title = "Air Travel Desk live video on YouTube";
      f.allowFullscreen = true;
      f.setAttribute("allow", "fullscreen");
      f.setAttribute("referrerpolicy", "strict-origin-when-cross-origin");
      box.insertBefore(f, mini);
    }

    function syncTeasers() {
      var teasers = doc.querySelectorAll("[data-watch-open]");
      for (var i = 0; i < teasers.length; i++) {
        teasers[i].setAttribute("aria-controls", drawer.id);
        teasers[i].setAttribute("aria-expanded", String(isOpen));
      }
    }

    function setOpen(next, trigger) {
      if (next === isOpen) { return; }
      isOpen = next;
      btn.setAttribute("aria-expanded", next ? "true" : "false");
      syncTeasers();
      win.clearTimeout(hideTimer);
      if (next) {
        opener = trigger;
        if (!box.querySelector("iframe")) { mountPlayer(); }
        drawer.hidden = false;
        drawer.inert = false;
        if (reduce) { drawer.classList.add("open"); } else { win.requestAnimationFrame(function () { win.requestAnimationFrame(function () { if (isOpen) { drawer.classList.add("open"); } }); }); }
        if (win.scrollY > 120) { win.scrollTo({ top: 0, behavior: reduce ? "auto" : "smooth" }); }
        if (opener !== btn) { close.focus({ preventScroll: true }); }
      } else {
        (opener.isConnected ? opener : btn).focus();
        drawer.inert = true;
        drawer.classList.remove("open");
        undock();
        var old = box.querySelector(".watch-holder, iframe");
        while (old) { old.parentNode.removeChild(old); old = box.querySelector(".watch-holder, iframe"); }                       /* removing the player stops the video and its sound */
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
    x.addEventListener("click", function () { setOpen(false); });
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
      function up() { docRem.call(doc, "pointermove", move); docRem.call(doc, "pointerup", up); if (shield.parentNode) { shield.parentNode.removeChild(shield); } }
      docAdd.call(doc, "pointermove", move);
      docAdd.call(doc, "pointerup", up);
      e.preventDefault();
    });


    /* ---- soft navigation: while the player is open, link clicks swap the page in place so the video keeps playing ---- */
    var tracked = [];                      /* listeners the page scripts add on window and document; removed before the next swap so they do not pile up */
    var winAdd = win.addEventListener, docAdd = doc.addEventListener;
    var winRem = win.removeEventListener, docRem = doc.removeEventListener;
    win.addEventListener = function (t, f, o) { tracked.push([win, t, f, o]); return winAdd.call(win, t, f, o); };
    doc.addEventListener = function (t, f, o) { tracked.push([doc, t, f, o]); return docAdd.call(doc, t, f, o); };
    var SKIP_SCRIPTS = /(^|\/)(theme|watch|alert|count)\.js$/;
    var softUsed = false, navSeq = 0;

    function softOk(a, e) {
      if (!isOpen || !a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) { return null; }
      if (a.target && a.target !== "_self") { return null; }
      if (a.hasAttribute("download")) { return null; }
      var u;
      try { u = new win.URL(a.href, win.location.href); } catch (err) { return null; }
      if (u.origin !== win.location.origin || (u.protocol !== "https:" && u.protocol !== "http:")) { return null; }
      if (u.pathname === win.location.pathname && u.search === win.location.search) { return null; }       /* same page or a hash jump: leave it to the browser */
      var last = u.pathname.split("/").pop();
      if (last.indexOf(".") >= 0 && !/\.html$/.test(last)) { return null; }                                 /* data files, images, the offline worker */
      if (/^\/(tv|step)(\/|\.html|$)/.test(u.pathname)) { return null; }
      return u;
    }

    function swapIn(ndoc, u) {
      var main = doc.querySelector("main"), nmain = ndoc.querySelector("main");
      if (!main || !nmain) { return false; }
      tracked.splice(0).forEach(function (r) { (r[0] === win ? winRem : docRem).call(r[0], r[1], r[2], r[3]); });
      doc.title = ndoc.title;
      ["meta[name=description]", "meta[property^='og:']", "meta[name^='twitter:']", "link[rel=canonical]"].forEach(function (sel) {
        var olds = doc.head.querySelectorAll(sel);
        for (var i = 0; i < olds.length; i++) { olds[i].parentNode.removeChild(olds[i]); }
        var news = ndoc.head.querySelectorAll(sel);
        for (var j = 0; j < news.length; j++) { doc.head.appendChild(doc.importNode(news[j], true)); }
      });
      var ld = doc.head.querySelectorAll("script[type='application/ld+json']");
      for (var k = 0; k < ld.length; k++) { ld[k].parentNode.removeChild(ld[k]); }
      var nld = ndoc.querySelectorAll("script[type='application/ld+json']");
      for (var m = 0; m < nld.length; m++) { var c = doc.createElement("script"); c.type = "application/ld+json"; c.textContent = nld[m].textContent; doc.head.appendChild(c); }
      doc.body.className = ndoc.body.className;
      var nav = doc.querySelector(".site-header .header-nav"), nnav = ndoc.querySelector(".site-header .header-nav");
      if (nav && nnav) { nav.textContent = ""; for (var z = 0; z < nnav.children.length; z++) { nav.appendChild(doc.importNode(nnav.children[z], true)); } }
      var foot = doc.querySelector(".site-footer"), nfoot = ndoc.querySelector(".site-footer");
      win.history.pushState({ soft: 1 }, "", u.href);
      softUsed = true;
      main.parentNode.replaceChild(doc.importNode(nmain, true), main);
      if (foot && nfoot) { foot.parentNode.replaceChild(doc.importNode(nfoot, true), foot); }
      syncTeasers();
      /* run the new page's own scripts again, in order, against the new address */
      var srcs = ndoc.querySelectorAll("script[src]");
      for (var n = 0; n < srcs.length; n++) {
        var raw = srcs[n].getAttribute("src");
        if (SKIP_SCRIPTS.test(raw)) { continue; }
        var ns = doc.createElement("script");
        ns.async = false;
        for (var q = 0; q < srcs[n].attributes.length; q++) {
          var at = srcs[n].attributes[q];
          if (at.name === "src" || at.name === "defer" || at.name === "async") { continue; }
          if (at.name === "type" && at.value === "text/atd-late") { continue; }       /* the airport pages hold their scripts back until the picture paints; after a swap, just run them */
          ns.setAttribute(at.name, at.value);
        }
        ns.src = new win.URL(raw, u.href).href;
        doc.body.appendChild(ns);
      }
      win.scrollTo(0, 0);
      var nm = doc.querySelector("main");
      if (nm) { nm.setAttribute("tabindex", "-1"); try { nm.focus({ preventScroll: true }); } catch (err2) { /* old browser */ } }
      return true;
    }

    function go(u, fromPop) {
      var seq = ++navSeq;
      var ctl = typeof win.AbortController === "function" ? new win.AbortController() : null;
      var t = win.setTimeout(function () { if (ctl) { ctl.abort(); } }, 10000);
      return win.fetch(u.href, { credentials: "same-origin", signal: ctl ? ctl.signal : undefined })
        .then(function (r) { win.clearTimeout(t); if (!r.ok) { throw new Error("HTTP " + r.status); } return r.text(); })
        .then(function (html) {
          if (seq !== navSeq) { return; }
          var ndoc = new win.DOMParser().parseFromString(html, "text/html");
          if (!ndoc.querySelector("main") || !ndoc.querySelector(".site-header")) { throw new Error("not a site page"); }
          if (fromPop) {
            var keep = win.history.pushState; win.history.pushState = function () {};      /* a Back or Forward already moved the address */
            try { if (!swapIn(ndoc, u)) { throw new Error("no main"); } } finally { win.history.pushState = keep; }
          } else if (!swapIn(ndoc, u)) { throw new Error("no main"); }
        })
        .catch(function () { win.clearTimeout(t); if (seq === navSeq) { win.location.href = u.href; } });
    }

    docAdd.call(doc, "click", function (e) {
      var a = e.target && e.target.closest ? e.target.closest("a[href]") : null;
      var u = softOk(a, e);
      if (!u) { return; }
      e.preventDefault();
      go(u, false);
    });
    winAdd.call(win, "popstate", function () {
      if (!softUsed) { return; }
      var u; try { u = new win.URL(win.location.href); } catch (err) { return; }
      go(u, true);
    });

    btn.addEventListener("click", function () { setOpen(!isOpen, btn); });
    close.addEventListener("click", function () { setOpen(false); });
    docAdd.call(doc, "keydown", function (e) {
      if (e.key === "Escape" && isOpen && !e.defaultPrevented) { setOpen(false); }
    });
    docAdd.call(doc, "click", function (e) {
      var teaser = e.target && e.target.closest ? e.target.closest("[data-watch-open]") : null;
      if (teaser && teaser !== btn) { setOpen(!isOpen, teaser); }
    });
    syncTeasers();
  }

  var api = { playerSrc: playerSrc, mainWatchUrl: mainWatchUrl, CHANNEL: CHANNEL };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; }
  if (root && root.document) { root.ATDWatch = api; start(root); }
})(typeof window !== "undefined" ? window : null);
