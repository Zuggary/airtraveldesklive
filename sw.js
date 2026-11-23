/* Air Travel Desk service worker: offline support using same-origin caching only. */
(function () {
  "use strict";

  var CACHE_PREFIX = "atd-offline-";
  var CACHE_NAME = "atd-offline-v20";
  var STATIC_FILES = [
    "./",
    "./airports/",
    "./stuck",
    "./help/",
    "./help/ground-stop.html",
    "./help/ground-delay.html",
    "./help/weather-disruption.html",
    "./help/cancellation.html",
    "./about",
    "./sources",
    "./tokens.css",
    "./style.css",
    "./theme.js",
    "./watch.js",
    "./app.js",
    "./lib.js",
    "./sun.js",
    "./apmap.js",
    "./stuck.js",
    "./sources.js",
    "./fonts/public-sans-latin-wght-normal.woff2",
    "./fonts/barlow-condensed-600.woff2",
    "./fonts/barlow-condensed-700.woff2",
    "./brand/logo.svg",
    "./data/dot-commitments.json",
    "./data/airports.json",
    "./data/airport-guide.json",
    "./favicon.svg",
    "./favicon.png"
  ];

  function scopeUrl(rel) {
    return new URL(rel, self.registration.scope);
  }

  function staticPathSet() {
    var set = {};
    for (var i = 0; i < STATIC_FILES.length; i++) {
      set[scopeUrl(STATIC_FILES[i]).pathname] = true;
    }
    return set;
  }

  function isDataJson(pathname) {
    var dataPrefix = scopeUrl("./data/").pathname;
    return pathname.indexOf(dataPrefix) === 0 && pathname.slice(-5) === ".json";
  }

  self.addEventListener("install", function (event) {
    event.waitUntil(
      caches.open(CACHE_NAME).then(function (cache) {
        return cache.addAll(STATIC_FILES.map(function (f) { return scopeUrl(f).pathname; }));
      }).then(function () {
        return self.skipWaiting();
      })
    );
  });

  self.addEventListener("activate", function (event) {
    event.waitUntil(
      caches.keys().then(function (keys) {
        return Promise.all(keys.map(function (key) {
          if (key !== CACHE_NAME && key.indexOf(CACHE_PREFIX) === 0) { return caches.delete(key); }
        }));
      }).then(function () {
        return self.clients.claim();
      })
    );
  });

  self.addEventListener("fetch", function (event) {
    var req = event.request;
    if (req.method !== "GET") { return; }

    var url;
    try {
      url = new URL(req.url);
    } catch (e) {
      return;
    }

    // Never cache or intercept off-origin requests.
    if (url.origin !== self.location.origin) { return; }

    var staticPaths = staticPathSet();
    var cacheKey = url.pathname;

    // Site files: network first with a 4-second timeout, so updates reach visitors at once;
    // the cached copy answers when the network is slow or down (airport wifi).
    if (staticPaths[cacheKey]) {
      event.respondWith(
        caches.open(CACHE_NAME).then(function (cache) {
          var net = fetch(req).then(function (resp) {
            if (resp && resp.ok && resp.type === "basic") { cache.put(cacheKey, resp.clone()); }
            return resp;
          });
          var slow = new Promise(function (resolve) { setTimeout(resolve, 4000); }).then(function () {
            return cache.match(cacheKey).then(function (c) { return c || net; });
          });
          return Promise.race([net, slow]).catch(function () {
            return cache.match(cacheKey).then(function (c) { return c || Response.error(); });
          });
        })
      );
      return;
    }

    // The art (assets/art) is not precached. Each picture is saved the first time a page shows it (cache first after that).
    if (cacheKey.indexOf(scopeUrl("./assets/art/").pathname) === 0) {
      event.respondWith(
        caches.open(CACHE_NAME).then(function (cache) {
          return cache.match(cacheKey).then(function (hit) {
            if (hit) { return hit; }
            return fetch(req).then(function (resp) {
              if (resp && resp.ok && resp.type === "basic") { cache.put(cacheKey, resp.clone()); }
              return resp;
            });
          });
        })
      );
      return;
    }

    // Network-first for data/state.json and other data/*.json.
    if (isDataJson(cacheKey)) {
      event.respondWith(
        caches.open(CACHE_NAME).then(function (cache) {
          return fetch(req).then(function (resp) {
            if (resp && resp.ok && resp.type === "basic") {
              cache.put(cacheKey, resp.clone());
            }
            return resp;
          }).catch(function () {
            return cache.match(cacheKey);
          });
        })
      );
    }
  });
})();
