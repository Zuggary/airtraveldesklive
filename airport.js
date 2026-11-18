/* Air Travel Desk airport pages: daylight tile and live status. Built by tools/build_airport_pages.py; do not edit.
   AN43: one shared, cached, deferred file in place of 26 KB of inline script per page. It reads the airport
   from its own script tag (data-code, data-tz, data-short). It paints once; no timer refreshes the page. */
var ATD_ME = document.currentScript;
  (function () {
    "use strict";
    var p = document.getElementById("sun-now");
    var src = document.getElementById("sun-now-source");
    var tile = document.getElementById("sun-tile");
    if (!p || !window.Sun) { return; }
    function paint() {
      try {
        var tz = p.getAttribute("data-tz"), now = Date.now();
        var s = window.Sun.hubSun(parseFloat(p.getAttribute("data-lat")), parseFloat(p.getAttribute("data-lon")), tz, now);
        var F = function (ms) { return window.Sun.fmtTime(ms, tz); };
        var head = "", sub = "";
        if (s.state === "polar_day") { head = "Sun stays up"; }
        else if (s.state === "polar_night") { head = "Sun stays down"; }
        else if (s.sunrise !== null && s.sunrise > now) { head = "Sunrise " + F(s.sunrise); sub = "Sunset " + F(s.sunset); }
        else if (s.sunset !== null && s.sunset > now) { head = "Sunset " + F(s.sunset); sub = "Sunrise was " + F(s.sunrise); }
        else { head = "Sunrise " + F(s.sunrise + 86400000); sub = "Sunset was " + F(s.sunset); }
        var zone = new Intl.DateTimeFormat("en-US", { timeZone: tz, timeZoneName: "short" }).formatToParts(new Date()).filter(function (x) { return x.type === "timeZoneName"; })[0];
        p.textContent = head;
        p.hidden = false;
        if (src) { src.textContent = (sub ? sub + ". " : "") + "Local time at the airport" + (zone ? " (" + zone.value + ")" : "") + "."; src.hidden = false; }
        if (tile) { tile.hidden = false; }
      } catch (e) { p.hidden = true; if (src) { src.hidden = true; } if (tile) { tile.hidden = true; } }
    }
    paint();
  })();
  (function () {
    "use strict";
    var KIND = (ATD_ME && ATD_ME.getAttribute("data-kind")) || "inland";
    var LAT = ATD_ME && ATD_ME.getAttribute("data-lat") ? parseFloat(ATD_ME.getAttribute("data-lat")) : null;
    var LON = ATD_ME && ATD_ME.getAttribute("data-lon") ? parseFloat(ATD_ME.getAttribute("data-lon")) : null;
    var aerial = ({"FLL": {"day": "airports/ap-FLL-day", "night": "airports/ap-FLL-night"}, "MIA": {"day": "airports/ap-MIA-day", "night": "airports/ap-MIA-night"}, "ATL": {"day": "airports/ap-ATL-day", "night": "airports/ap-ATL-night"}, "SFO": {"day": "airports/ap-SFO-day", "night": "airports/ap-SFO-night"}, "DEN": {"day": "airports/ap-DEN-day", "night": "airports/ap-DEN-night"}, "DFW": {"day": "airports/ap-DFW-day", "night": "airports/ap-DFW-night"}, "ORD": {"day": "airports/ap-ORD-day", "night": "airports/ap-ORD-night"}, "LAX": {"day": "airports/ap-LAX-day", "night": "airports/ap-LAX-night"}, "JFK": {"day": "airports/ap-JFK-day", "night": "airports/ap-JFK-night"}, "LAS": {"day": "airports/ap-LAS-day", "night": "airports/ap-LAS-night"}, "MCO": {"day": "airports/ap-MCO-day", "night": "airports/ap-MCO-night"}, "CLT": {"day": "airports/ap-CLT-day", "night": "airports/ap-CLT-night"}, "SEA": {"day": "airports/ap-SEA-day", "night": "airports/ap-SEA-night"}, "PHX": {"day": "airports/ap-PHX-day", "night": "airports/ap-PHX-night"}, "EWR": {"day": "airports/ap-EWR-day", "night": "airports/ap-EWR-night"}, "IAH": {"day": "airports/ap-IAH-day", "night": "airports/ap-IAH-night"}, "BOS": {"day": "airports/ap-BOS-day", "night": "airports/ap-BOS-night"}, "MSP": {"day": "airports/ap-MSP-day", "night": "airports/ap-MSP-night"}, "LGA": {"day": "airports/ap-LGA-day", "night": "airports/ap-LGA-night"}, "DTW": {"day": "airports/ap-DTW-day", "night": "airports/ap-DTW-night"}, "PHL": {"day": "airports/ap-PHL-day", "night": "airports/ap-PHL-night"}, "SLC": {"day": "airports/ap-SLC-day", "night": "airports/ap-SLC-night"}, "BWI": {"day": "airports/ap-BWI-day", "night": "airports/ap-BWI-night"}, "DCA": {"day": "airports/ap-DCA-day", "night": "airports/ap-DCA-night"}, "SAN": {"day": "airports/ap-SAN-day", "night": "airports/ap-SAN-night"}, "IAD": {"day": "airports/ap-IAD-day", "night": "airports/ap-IAD-night"}, "TPA": {"day": "airports/ap-TPA-day", "night": "airports/ap-TPA-night"}, "BNA": {"day": "airports/ap-BNA-day", "night": "airports/ap-BNA-night"}, "AUS": {"day": "airports/ap-AUS-day", "night": "airports/ap-AUS-night"}, "MDW": {"day": "airports/ap-MDW-day", "night": "airports/ap-MDW-night"}, "MSY": {"day": "airports/ap-MSY-day", "night": "airports/ap-MSY-night"}, "SJC": {"day": "airports/ap-SJC-day", "night": "airports/ap-SJC-night"}, "HNL": {"day": "airports/ap-HNL-day", "night": "airports/ap-HNL-night"}, "STL": {"day": "airports/ap-STL-day", "night": "airports/ap-STL-night"}, "SMF": {"day": "airports/ap-SMF-day", "night": "airports/ap-SMF-night"}, "BDL": {"day": "airports/ap-BDL-day", "night": "airports/ap-BDL-night"}, "PIT": {"day": "airports/ap-PIT-day", "night": "airports/ap-PIT-night"}, "CMH": {"day": "airports/ap-CMH-day", "night": "airports/ap-CMH-night"}, "MCI": {"day": "airports/ap-MCI-day", "night": "airports/ap-MCI-night"}, "OGG": {"day": "airports/ap-OGG-day", "night": "airports/ap-OGG-night"}, "ONT": {"day": "airports/ap-ONT-day", "night": "airports/ap-ONT-night"}, "RSW": {"day": "airports/ap-RSW-day", "night": "airports/ap-RSW-night"}, "MKE": {"day": "airports/ap-MKE-day", "night": "airports/ap-MKE-night"}, "BOI": {"day": "airports/ap-BOI-day", "night": "airports/ap-BOI-night"}, "RNO": {"day": "airports/ap-RNO-day", "night": "airports/ap-RNO-night"}, "ELP": {"day": "airports/ap-ELP-day", "night": "airports/ap-ELP-night"}, "ALB": {"day": "airports/ap-ALB-day", "night": "airports/ap-ALB-night"}, "ORF": {"day": "airports/ap-ORF-day", "night": "airports/ap-ORF-night"}, "CHS": {"day": "airports/ap-CHS-day", "night": "airports/ap-CHS-night"}, "MEM": {"day": "airports/ap-MEM-day", "night": "airports/ap-MEM-night"}, "OKC": {"day": "airports/ap-OKC-day", "night": "airports/ap-OKC-night"}, "PBI": {"day": "airports/ap-PBI-day", "night": "airports/ap-PBI-night"}, "SRQ": {"day": "airports/ap-SRQ-day", "night": "airports/ap-SRQ-night"}, "GEG": {"day": "airports/ap-GEG-day", "night": "airports/ap-GEG-night"}, "MHT": {"day": "airports/ap-MHT-day", "night": "airports/ap-MHT-night"}, "BTV": {"day": "airports/ap-BTV-day", "night": "airports/ap-BTV-night"}, "COS": {"day": "airports/ap-COS-day", "night": "airports/ap-COS-night"}, "BHM": {"day": "airports/ap-BHM-day", "night": "airports/ap-BHM-night"}, "GRR": {"day": "airports/ap-GRR-day", "night": "airports/ap-GRR-night"}, "SYR": {"day": "airports/ap-SYR-day", "night": "airports/ap-SYR-night"}, "TYS": {"day": "airports/ap-TYS-day", "night": "airports/ap-TYS-night"}, "MSN": {"day": "airports/ap-MSN-day", "night": "airports/ap-MSN-night"}, "HSV": {"day": "airports/ap-HSV-day", "night": "airports/ap-HSV-night"}, "MYR": {"day": "airports/ap-MYR-day", "night": "airports/ap-MYR-night"}, "LIH": {"day": "airports/ap-LIH-day", "night": "airports/ap-LIH-night"}, "PDX": {"day": "airports/ap-PDX-day", "night": "airports/ap-PDX-night"}, "HOU": {"day": "airports/ap-HOU-day", "night": "airports/ap-HOU-night"}, "RDU": {"day": "airports/ap-RDU-day", "night": "airports/ap-RDU-night"}, "SNA": {"day": "airports/ap-SNA-day", "night": "airports/ap-SNA-night"}, "IND": {"day": "airports/ap-IND-day", "night": "airports/ap-IND-night"}, "CLE": {"day": "airports/ap-CLE-day", "night": "airports/ap-CLE-night"}, "SAT": {"day": "airports/ap-SAT-day", "night": "airports/ap-SAT-night"}, "BUR": {"day": "airports/ap-BUR-day", "night": "airports/ap-BUR-night"}, "LGB": {"day": "airports/ap-LGB-day", "night": "airports/ap-LGB-night"}, "JAX": {"day": "airports/ap-JAX-day", "night": "airports/ap-JAX-night"}, "ABQ": {"day": "airports/ap-ABQ-day", "night": "airports/ap-ABQ-night"}, "OMA": {"day": "airports/ap-OMA-day", "night": "airports/ap-OMA-night"}, "TUS": {"day": "airports/ap-TUS-day", "night": "airports/ap-TUS-night"}, "PVD": {"day": "airports/ap-PVD-day", "night": "airports/ap-PVD-night"}, "BUF": {"day": "airports/ap-BUF-day", "night": "airports/ap-BUF-night"}, "RIC": {"day": "airports/ap-RIC-day", "night": "airports/ap-RIC-night"}, "SAV": {"day": "airports/ap-SAV-day", "night": "airports/ap-SAV-night"}, "SDF": {"day": "airports/ap-SDF-day", "night": "airports/ap-SDF-night"}, "TUL": {"day": "airports/ap-TUL-day", "night": "airports/ap-TUL-night"}, "CVG": {"day": "airports/ap-CVG-day", "night": "airports/ap-CVG-night"}, "DSM": {"day": "airports/ap-DSM-day", "night": "airports/ap-DSM-night"}, "ICT": {"day": "airports/ap-ICT-day", "night": "airports/ap-ICT-night"}, "PWM": {"day": "airports/ap-PWM-day", "night": "airports/ap-PWM-night"}, "ANC": {"day": "airports/ap-ANC-day", "night": "airports/ap-ANC-night"}, "GSO": {"day": "airports/ap-GSO-day", "night": "airports/ap-GSO-night"}, "LIT": {"day": "airports/ap-LIT-day", "night": "airports/ap-LIT-night"}, "DAY": {"day": "airports/ap-DAY-day", "night": "airports/ap-DAY-night"}, "ROC": {"day": "airports/ap-ROC-day", "night": "airports/ap-ROC-night"}, "PSP": {"day": "airports/ap-PSP-day", "night": "airports/ap-PSP-night"}, "LEX": {"day": "airports/ap-LEX-day", "night": "airports/ap-LEX-night"}, "FAT": {"day": "airports/ap-FAT-day", "night": "airports/ap-FAT-night"}, "KOA": {"day": "airports/ap-KOA-day", "night": "airports/ap-KOA-night"}, "PNS": {"day": "airports/ap-PNS-day", "night": "airports/ap-PNS-night"}, "DAL": {"day": "airports/ap-DAL-day", "night": "airports/ap-DAL-night"}})[ATD_ME && ATD_ME.getAttribute("data-code")];
    var box = document.querySelector("#ap-hero .band-art");
    var hero = document.getElementById("ap-hero");
    if (!box || !hero) { return; }
    var lvlNow = (/\bap-hero--(\w+)/.exec(hero.className) || [])[1] || "clear";
    function isDay() {
      try { if (LAT === null || !window.Sun) { return null; } var ms = Date.now(); return window.Sun.altitude(LAT, LON, ms, window.Sun.subsolar(ms)) > -0.833; } catch (e) { return null; }
    }
    function keyFor(lvl, day) {
      if (aerial) { return aerial[day ? "day" : "night"]; }
      if (lvl === "night") { return "ap-sched-night"; }
      if (lvl === "delay" || lvl === "stop" || lvl === "closed") { return "ap-" + lvl + (day ? "-day" : "-night"); }
      return day ? "ap-clear-day" : "airport-" + KIND;
    }
    function paint(key) {
      if (box.getAttribute("data-art") === key) { return; }
      var base = "../assets/art/" + key;
      var src = box.querySelector("source"), img = box.querySelector("img");
      if (!src || !img) { return; }
      if (aerial) {
        var url = base + ".webp";
        src.setAttribute("type", "image/webp");
        src.setAttribute("srcset", url + " 1600w");
        img.removeAttribute("srcset");
        img.setAttribute("width", "1600");
        img.setAttribute("height", "700");
        img.setAttribute("src", url);
        box.setAttribute("data-art", key);
        var checked = document.getElementById("checked-line");
        if (checked && !document.getElementById("ap-art-credit")) {
          var credit = document.createElement("p");
          credit.id = "ap-art-credit";
          credit.className = "last-checked";
          credit.textContent = {"FLL": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "MIA": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "ATL": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "SFO": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "DEN": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "DFW": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "ORD": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "LAX": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "JFK": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "LAS": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "MCO": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "CLT": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "SEA": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "PHX": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "EWR": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "IAH": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "BOS": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "MSP": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "LGA": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "DTW": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "PHL": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "SLC": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "BWI": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "DCA": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "SAN": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "IAD": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "TPA": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "BNA": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "AUS": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "MDW": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "MSY": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "SJC": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "HNL": "Aerial imagery: Sentinel-2 cloudless (EOX / Copernicus). Night view is a rendering, not a photograph.", "STL": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "SMF": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "BDL": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "PIT": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "CMH": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "MCI": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "OGG": "Aerial imagery: Sentinel-2 cloudless (EOX / Copernicus). Night view is a rendering, not a photograph.", "ONT": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "RSW": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "MKE": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "BOI": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "RNO": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "ELP": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "ALB": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "ORF": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "CHS": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "MEM": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "OKC": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "PBI": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "SRQ": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "GEG": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "MHT": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "BTV": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "COS": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "BHM": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "GRR": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "SYR": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "TYS": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "MSN": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "HSV": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "MYR": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "LIH": "Aerial imagery: Sentinel-2 cloudless (EOX / Copernicus). Night view is a rendering, not a photograph.", "PDX": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "HOU": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "RDU": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "SNA": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "IND": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "CLE": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "SAT": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "BUR": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "LGB": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "JAX": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "ABQ": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "OMA": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "TUS": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "PVD": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "BUF": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "RIC": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "SAV": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "SDF": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "TUL": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "CVG": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "DSM": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "ICT": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "PWM": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "ANC": "Aerial imagery: Sentinel-2 cloudless (EOX / Copernicus). Night view is a rendering, not a photograph.", "GSO": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "LIT": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "DAY": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "ROC": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "PSP": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "LEX": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "FAT": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "KOA": "Aerial imagery: Sentinel-2 cloudless (EOX / Copernicus). Night view is a rendering, not a photograph.", "PNS": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.", "DAL": "Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph."}[ATD_ME && ATD_ME.getAttribute("data-code")] || "";
          checked.insertAdjacentElement("afterend", credit);
        }
        return;
      }
      var sizes = key.indexOf("airport-") === 0 ? [1440, 2880] : [720, 1440];
      function set(ext) { return sizes.map(function (w) { return base + "-" + w + "." + ext + " " + w + "w"; }).join(", "); }
      src.setAttribute("srcset", set("avif"));
      img.setAttribute("srcset", set("jpg"));
      img.setAttribute("src", base + "-" + sizes[0] + ".jpg");
      box.setAttribute("data-art", key);
    }
    function update(lvl) {
      if (lvl) { lvlNow = lvl; }
      var d = isDay();
      if (d === null) { return; }
      paint(keyFor(lvlNow, d));
    }
    window.ATDHeroArt = update;
    update();
  })();
  (function () {
    "use strict";
    var CODE = (ATD_ME && ATD_ME.getAttribute("data-code")) || "";
    var TZ = (ATD_ME && ATD_ME.getAttribute("data-tz")) || "";
    var SHORT = (ATD_ME && ATD_ME.getAttribute("data-short")) || CODE;
    var box = document.getElementById("right-now");
    var statusChip = document.getElementById("status-chip");
    var wxChip = document.getElementById("weather-chip");
    var verdictEl = document.getElementById("ap-verdict");
    var hero = document.getElementById("ap-hero");
    if (!box) { return; }
    var INITIAL_LVL = hero ? ((/\bap-hero--(\w+)/.exec(hero.className) || [])[1] || "") : "";
    var LEVEL_TEXT = { clear: "Clear: no FAA delay or ground stop listed.", delay: "Delays: FAA delay program in effect.", stop: "Ground stop: FAA ground stop in effect.", closed: "Closed: FAA airport closure in effect.", night: "Closed overnight: the FAA lists a daily closure." };
    var BADGE_CLASS = { clear: "badge badge--clear", delay: "badge badge--delay", stop: "badge badge--stop", closed: "badge badge--stop", night: "badge badge--night" };
    var BADGE_LABEL = { clear: "No FAA delays reported", delay: "Delays", stop: "Ground stop", closed: "Closed", night: "Closed overnight" };
    // AN35: a closure the FAA lists as daily (events[].daily, UTC hours "0730-1415") is calm. Same rule as prerender_text.closure_schedule.
    var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    function listedUtc(t) {
      var m = /([A-Z][a-z]{2}) (\d{1,2}) at (\d{2}):(\d{2}) UTC/.exec(String(t || "")), mo = m ? MONTHS.indexOf(m[1]) : -1;
      if (mo < 0) { return null; }
      var n = new Date();
      return Date.UTC(n.getUTCFullYear() + (mo < n.getUTCMonth() - 6 ? 1 : 0), mo, +m[2], +m[3], +m[4]);
    }
    function localClock(ms) {
      try { var o = { hour: "numeric", minute: "2-digit" }; if (TZ) { o.timeZone = TZ; } return new Intl.DateTimeFormat("en-US", o).format(new Date(ms)).replace(/\u202f/g, " "); } catch (e) { return ""; }
    }
    function closureSchedule(ev, atMs) {
      if (!ev || ev.kind !== "closure") { return null; }
      var m = /^(\d{2})(\d{2})-(\d{2})(\d{2})$/.exec(String(ev.daily || ""));
      if (!m) { return null; }
      var s = +m[1] * 60 + +m[2], e = +m[3] * 60 + +m[4];
      if (s === e || s >= 1440 || e >= 1440) { return null; }
      var now = atMs == null ? Date.now() : atMs, d = new Date(now), t = d.getUTCHours() * 60 + d.getUTCMinutes();
      var inW = s < e ? (t >= s && t < e) : (t >= s || t < e);
      var st = listedUtc(ev.start), en = listedUtc(ev.reopen);
      if ((st && now < st - 864e5) || (en && now >= en)) { inW = false; }
      function nextAt(min) { var b = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(), Math.floor(min / 60), min % 60); return b > now ? b : b + 864e5; }
      return { in_window: inW, reopen: localClock(nextAt(e)), close: localClock(nextAt(s)) };
    }
    function nightSchedule(a) { var r = null; (a.events || []).forEach(function (ev) { var x = !r && closureSchedule(ev); if (x) { r = x; } }); return r; }
    function effLevel(a, atMs) {
      var evs = (a.events || []).filter(Boolean), cl = evs.filter(function (ev) { return ev.kind === "closure"; });
      if (cl.length || a.level === "closed") {
        var sc = cl.map(function (ev) { return closureSchedule(ev, atMs); });
        if (cl.length && sc.every(Boolean)) {
          if (sc.some(function (x) { return x.in_window; })) { return "night"; }
          var rest = evs.filter(function (ev) { return ev.kind !== "closure"; });
          if (rest.some(function (ev) { return ev.kind === "ground_stop"; })) { return "stop"; }
          return rest.length ? "delay" : "clear";
        }
        return "closed";
      }
      return LEVEL_TEXT[a.level] && a.level !== "night" ? a.level : "clear";
    }
    var WX_LABEL = { fresh: "Weather now: ", stale: "Last weather report: " };
    function badgeLabel(a, lvl) {
      if (lvl === "delay" && Array.isArray(a.events) && a.events.some(function (ev) { return ev && ev.kind === "ground_delay"; })) { return "Ground delay program"; }
      return BADGE_LABEL[lvl];
    }
    var CARD_REASON_WORDS = {
      "MIT": "traffic spacing (miles-in-trail)", "MINIT": "traffic spacing (minutes-in-trail)",
      "WX": "weather", "VOLUME": "traffic volume", "EQUIPMENT": "equipment",
      "RUNWAY": "runway", "RWY/TWY": "runway or taxiway", "STAFFING": "staffing", "OTHER": "other"
    };
    function reasonText(reason) {
      return String(reason || "").split(";").map(function (part) {
        var terms = part.trim().replace(/^TM\s+Initiatives\s*:\s*/i, "").split(/\s*:\s*/).filter(Boolean);
        var known = terms.some(function (term) { return Object.hasOwn(CARD_REASON_WORDS, term.toUpperCase()); });
        var words = terms.map(function (term) {
          var key = term.toUpperCase();
          if (Object.hasOwn(CARD_REASON_WORDS, key)) { return CARD_REASON_WORDS[key]; }
          return known ? term.toLowerCase() : term.toLowerCase().replace(/[a-z]+/g, function (word) {
            return word.charAt(0).toUpperCase() + word.slice(1);
          });
        }).filter(function (word, index, list) { return list.indexOf(word) === index; });
        var text = words.join(/^(MIT|MINIT)$/i.test(terms[0]) ? " due to " : ", ");
        return text.charAt(0).toUpperCase() + text.slice(1);
      }).filter(Boolean).join("; ");
    }
    function el(tag, cls, text) {
      var n = document.createElement(tag);
      if (cls) { n.className = cls; }
      if (text != null) { n.textContent = text; }
      return n;
    }
    function srcLine(cls, before, linkText, after) {
      var p = el("p", cls);
      if (before) { p.appendChild(document.createTextNode(before)); }
      var a = el("a", "tap", linkText);
      a.href = "/sources";
      p.appendChild(a);
      if (after) { p.appendChild(document.createTextNode(after)); }
      return p;
    }
    // One tile: a label, the value, then the source in brackets.
    function tile(cls, label, value, linkText, after) {
      var d = el("div", "fact " + cls), p = el("p");
      p.appendChild(el("span", "fact-k", label.replace(/ $/, "")));
      p.appendChild(document.createTextNode(" "));
      p.appendChild(el("span", "fact-v", value));
      p.appendChild(document.createTextNode(" "));
      var s = el("span", "fact-src");
      var a = el("a", "tap", linkText); a.href = "/sources"; s.appendChild(a);
      s.appendChild(document.createTextNode(after));
      p.appendChild(s);
      d.appendChild(p);
      return d;
    }
    // AN34 r2: wind in miles per hour, same rule as prerender_text.wind_text.
    function mph(kt) { return Math.round(kt * 1.15078); }
    function windText(w, gusts) { if (Math.round(w.wind_kt) === 0) { return "calm"; } return mph(w.wind_kt) + " mph" + (gusts && w.gust_kt ? " gusting " + mph(w.gust_kt) + " mph" : ""); }
    // AN34 r2: the help card follows the live state (three steps when delayed or closed, quiet when clear).
    function scaleHelp(lvl) {
      var card = document.getElementById("help-card");
      if (!card) { return; }
      var hot = lvl === "delay" || lvl === "stop" || lvl === "closed";
      card.className = "airport-section help-card" + (hot ? " help-card--hot help-card--" + (lvl === "delay" ? "amber" : "red") : "");
      var hh = document.getElementById("stuck-heading");
      if (hh) { hh.textContent = hot ? "Flying through " + CODE + " today?" : "If your flight is hit"; }
      var steps = card.querySelector(".help-hot");
      if (steps) { steps.hidden = !hot; }
      // Checking the airline leads in every state.
      var sb = document.getElementById("stuck-btn"), fb = document.getElementById("flight-btn");
      if (sb) { sb.className = "btn btn-ghost"; }
      if (fb) { fb.className = "btn btn-accent"; }
    }
    var STALE_MIN = 30;
    function ageMin(iso) {
      var ms = Date.parse(iso || "");
      return isFinite(ms) ? Math.max(0, Math.floor((Date.now() - ms) / 60000)) : null;
    }
    function isStale(m) { return m == null || m > STALE_MIN; }
    function durText(m) {
      if (m < 60) { return m + " min"; }
      if (m < 1440) { var h = Math.floor(m / 60); return h === 1 ? "1 hour" : h + " hours"; }
      var d = Math.floor(m / 1440);
      return d === 1 ? "1 day" : d + " days";
    }
    function agoText(m) {
      if (m == null) { return "age unknown"; }
      return m < 1 ? "less than 1 min ago" : durText(m) + " ago";
    }
    function oldText(m) {
      if (m == null) { return "of unknown age"; }
      if (m < 60) { return m === 1 ? "1 minute old" : m + " minutes old"; }
      return durText(m) + " old";
    }
    function ageLabel(iso, stale) {
      var m = ageMin(iso);
      return m == null ? "update time unknown" : (stale ? "last updated " : "updated ") + agoText(m);
    }
    function minutesOf(t) {
      var h = /(\d+)\s*hours?/i.exec(t || ""), m = /(\d+)\s*minutes?/i.exec(t || "");
      return (!h && !m) ? null : (h ? parseInt(h[1], 10) * 60 : 0) + (m ? parseInt(m[1], 10) : 0);
    }
    function dur(min) { var h = Math.floor(min / 60), m = min % 60; return h && m ? h + "\u00a0h " + m + "\u00a0min" : h ? h + "\u00a0h" : m + "\u00a0min"; }
    var ZONES = { eastern: "America/New_York", central: "America/Chicago", mountain: "America/Denver", pacific: "America/Los_Angeles", alaska: "America/Anchorage", hawaii: "Pacific/Honolulu" };
    function zoneParts(ms, zone) {
      var f = new Intl.DateTimeFormat("en-US", { timeZone: zone, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric" });
      var o = {};
      f.formatToParts(new Date(ms)).forEach(function (p) { o[p.type] = parseInt(p.value, 10); });
      return o;
    }
    function localToMs(y, mo, d, h, mi, zone) {
      var guess = Date.UTC(y, mo - 1, d, h, mi);
      for (var i = 0; i < 2; i++) {
        var p = zoneParts(guess, zone);
        guess += Date.UTC(y, mo - 1, d, h, mi) - Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute);
      }
      return guess;
    }
    function forecastEnd(text, issuedIso, tz) {
      var m = /\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b(?:\s+(eastern|central|mountain|pacific|alaska|hawaii))?/i.exec(String(text || ""));
      var issued = Date.parse(issuedIso || "");
      if (!m || !isFinite(issued)) { return null; }
      var zone = (m[4] && ZONES[m[4].toLowerCase()]) || tz;
      if (!zone) { return null; }
      try {
        var h = parseInt(m[1], 10) % 12 + (m[3].toLowerCase() === "pm" ? 12 : 0), mi = m[2] ? parseInt(m[2], 10) : 0;
        var base = zoneParts(issued, zone);
        for (var add = 0; add < 3; add++) {
          var day = new Date(Date.UTC(base.year, base.month - 1, base.day + add));
          var c = localToMs(day.getUTCFullYear(), day.getUTCMonth() + 1, day.getUTCDate(), h, mi, zone);
          if (c > issued) { return c; }
        }
      } catch (e) { return null; }
      return null;
    }
    function forecastExpired(text, issuedIso) {
      var end = forecastEnd(text, issuedIso, TZ);
      return end == null || end <= Date.now();
    }
    function showStale(iso, forced) {
      var n = document.getElementById("stale-notice");
      if (!n) { return; }
      var m = ageMin(iso);
      if (!forced && !isStale(m)) { n.hidden = true; return; }
      n.textContent = "This data is " + oldText(m) + ", not live. ";
      n.appendChild(el("span", "sn-long", "FAA's own page: "));
      var l = el("a", "stale-link");
      l.appendChild(el("span", "sn-wide", "nasstatus.faa.gov"));
      l.appendChild(el("span", "sn-short", "FAA status"));
      l.href = "https://nasstatus.faa.gov";
      l.target = "_blank";
      l.rel = "noopener noreferrer";
      n.appendChild(l);
      n.hidden = false;
    }
    // AN34 round 4: "Early Monday, 1:27 AM in Atlanta", the FAA check time in the airport zone. Same rule as prerender_text.airport_dateline.
    function datelineText(iso) {
      var ms = Date.parse(iso || "");
      if (!isFinite(ms)) { return ""; }
      try {
        var o = { weekday: "long", hour: "numeric", hourCycle: "h23" }; if (TZ) { o.timeZone = TZ; }
        var parts = {}; new Intl.DateTimeFormat("en-US", o).formatToParts(new Date(ms)).forEach(function (x) { parts[x.type] = x.value; });
        var h = parseInt(parts.hour, 10) % 24, d = parts.weekday, c = clockLabel(iso).replace(/ [A-Z]{2,5}$/, "");
        var lead = h < 5 ? "Early " + d : d + " " + (h < 12 ? "morning" : h < 17 ? "afternoon" : h < 21 ? "evening" : "night");
        return lead + ", " + c + " in " + SHORT;
      } catch (e) { return ""; }
    }
    function clockLabel(iso) {
      var ms = Date.parse(iso || "");
      if (!isFinite(ms)) { return ""; }
      try {
        var opts = { hour: "numeric", minute: "2-digit", timeZoneName: "short" };
        if (TZ) { opts.timeZone = TZ; }
        return new Intl.DateTimeFormat("en-US", opts).format(new Date(ms));
      } catch (e) { return ""; }
    }
    function checkedText(iso, stale) {
      var c = clockLabel(iso);
      var m = ageMin(iso);
      return c ? (stale ? "last checked " : "checked ") + c + " (" + agoText(m == null ? 0 : m) + ")" : "check time unknown";
    }
    // The H1 in plain words. Same rule as _verdict in tools/build_airport_pages.py.
    function verdict(a, lvl, stale, label, asOf) {
      var h = el("span"), em = function (t) { return el("em", null, t); }, tx = function (t) { return document.createTextNode(t); };
      if (["clear", "delay", "stop", "closed"].indexOf(a.level) < 0) { h.appendChild(tx("Last known status: FAA status unavailable.")); return h; } if (stale) { h.appendChild(tx(label + " at " + SHORT + ", " + asOf + ".")); return h; }
      if (lvl === "night") { h.appendChild(tx(SHORT + " is ")); h.appendChild(em("closed overnight")); h.appendChild(tx(".")); return h; }
      if (lvl === "closed") { h.appendChild(tx(SHORT + " is ")); h.appendChild(em("closed")); h.appendChild(tx(" to flights.")); return h; }
      if (lvl === "stop") { h.appendChild(em("Ground stop:")); h.appendChild(tx(" flights to " + SHORT + " are held where they are.")); return h; }
      if (lvl === "delay") { h.appendChild(tx("The FAA lists ")); h.appendChild(em("delays")); h.appendChild(tx(" at " + SHORT + ".")); return h; }
      h.appendChild(tx("No FAA delays at " + SHORT + " ")); h.appendChild(em("right now")); h.appendChild(tx(".")); return h;
    }
    // AN35: the one place the FAA data age is stated (the stale banner states it when the data is old). Same rule as prerender_text.faa_age_parts.
    function faaParts(iso, stale) {
      var c = clockLabel(iso), m = ageMin(iso);
      if (!c) { return ["Source: ", ", check time unknown."]; }
      return stale ? ["Source: ", ", last checked " + c + "."] : ["FAA data " + (m < 1 ? "under 1 min" : durText(m)) + " old, checked " + c + ". Source: ", "."];
    }
    var CAT_WORDS = { MVFR: "reduced ceiling or visibility", IFR: "low ceiling or poor visibility", LIFR: "very low ceiling or visibility" };
    // Same rule as outlook_text in tools/build_airport_pages.py.
    function outlookText(w) {
      var t = String(w.next3h_text || "").trim();
      if (!t) { return ""; }
      var cat = String(w.next3h_cat || "").toUpperCase();
      if (CAT_WORDS[cat] && !/cloud|ceiling|visib|fog|mist|haze/i.test(t)) { t += " (" + cat + ": " + CAT_WORDS[cat] + ")"; }
      if (w.next3h_storms && !/storm/i.test(t)) { t += ". Storms possible"; }
      return t;
    }
    // The TSA wait line is built with the page; only its age text moves on.
    var tsaLine = document.getElementById("ap-tsa");
    if (tsaLine) {
      var tsaAge = tsaLine.querySelector(".gl-age"), tsaMin = ageMin(tsaLine.getAttribute("data-utc"));
      if (tsaAge && tsaMin != null) { if (tsaMin > 60) { tsaLine.hidden = true; } else { tsaAge.textContent = oldText(tsaMin); } }
    }
    var checkedLine = document.getElementById("checked-line");
    var heading = document.getElementById("ap-now-word");
    var legacyReminder = hero && hero.querySelector(".ap-hero-main > .small");
    if (legacyReminder && legacyReminder.textContent.indexOf("No FAA program does not guarantee") === 0) { legacyReminder.hidden = true; }
    function statusMeaning(a, lvl, stale) {
      if (stale || !a || ["clear", "delay", "stop", "closed"].indexOf(a.level) < 0) { return "Last known status: airport-wide conditions are unconfirmed. Check your flight with your airline."; }
      var kinds = (a.events || []).filter(Boolean).map(function (e) { return e.kind; }), meaning; var directions = (a.events || []).filter(Boolean).filter(function (e) { return e.kind === "delay"; }).map(function (e) { return String(e.direction || "").toLowerCase(); }); var departure = kinds.indexOf("departure_delay") >= 0 || directions.indexOf("departure") >= 0;
      if (lvl === "closed" || lvl === "night") { meaning = "The airport is closed to arrivals and departures."; }
      else if (lvl === "stop") { meaning = "Flights bound for this airport are held at their departure airports."; }
      else if (kinds.indexOf("ground_delay") >= 0) { meaning = "Flights bound for this airport are delayed at their departure airports."; if (departure) { meaning += " Departures are also delayed airport-wide."; } }
      else if (departure && directions.indexOf("arrival") >= 0) { meaning = "Arrivals and departures are delayed airport-wide."; }
      else if (departure) { meaning = "Departures are delayed airport-wide."; }
      else if (directions.indexOf("arrival") >= 0) { meaning = "Arrivals are delayed airport-wide."; }
      else if (lvl === "clear") { meaning = a.level === "clear" && !kinds.length ? "No FAA program is listed. Your flight may still be delayed." : "No FAA arrival or departure programs are active."; }
      else { meaning = "The FAA lists airport-wide delays."; }
      return meaning + " Check your flight with your airline.";
    }
    function addHelpLinks(n) {
      if (!n) { return; }
      var links = [["ground-stop", "What is a ground stop?"], ["ground-delay", "What is a ground delay?"], ["weather-disruption", "Weather disruption"], ["cancellation", "Cancellation"]];
      links.forEach(function (item) { var a = el("a", "tap", item[1]); a.href = "/help/" + item[0] + ".html"; n.appendChild(el("span", null, " ")); n.appendChild(a); });
    }
    function meaningElement() {
      var n = document.getElementById("ap-meaning");
      if (!n && checkedLine && checkedLine.parentNode) {
        n = el("p", "ap-lead"); n.id = "ap-meaning";
        checkedLine.parentNode.insertBefore(n, checkedLine);
      }
      // Shared JS also upgrades pages generated before the explanation was added.
      var old = hero ? hero.querySelectorAll(".ap-lead, .ap-out, .ap-explain, .ap-help-links") : [];
      for (var i = 0; i < old.length; i++) { if (old[i] !== n) { old[i].hidden = true; } }
      return n;
    }
    function setUnavailable() {
      scaleHelp("stale");
      if (heading) { heading.textContent = "Last known status"; }
      var meaning = meaningElement(); if (meaning) { meaning.textContent = statusMeaning(null, "unknown", true); meaning.hidden = false; addHelpLinks(meaning); }
      if (verdictEl) { verdictEl.textContent = "Last known status: FAA status unavailable."; }
      if (checkedLine) { checkedLine.textContent = "FAA NAS status: not available right now."; }
      if (statusChip) {
        statusChip.className = "badge status-chip";
        statusChip.textContent = "Status unavailable";
      }
      if (wxChip) { wxChip.hidden = true; }
    }
    function render(data) {
      var updMin = ageMin(data && data.updated_utc);
      var stale = isStale(updMin) || ((data && data.stale_feeds) || []).indexOf("FAA") >= 0;
      showStale(data && data.updated_utc, stale);
      if (heading) { heading.textContent = stale ? "Last known status" : (datelineText(data && data.updated_utc) || "Latest FAA check"); }
      var a = data && data.airports && data.airports[CODE];
      if (checkedLine && a) {
        checkedLine.textContent = "";
        var fp = faaParts(data.updated_utc, stale);
        var cl = el("a", "tap", "FAA NAS status");
        cl.href = "/sources";
        checkedLine.appendChild(document.createTextNode(fp[0]));
        checkedLine.appendChild(cl);
        checkedLine.appendChild(document.createTextNode(fp[1]));
      }
      if (!a) {
        setUnavailable();
        box.textContent = "";
        box.appendChild(el("p", null, "Airport status is not available right now. See nasstatus.faa.gov."));
        return;
      }
      var lvl = effLevel(a, stale ? Date.parse(data.updated_utc) : null);
      var meaning = meaningElement(); if (meaning) { meaning.textContent = statusMeaning(a, lvl, stale); meaning.hidden = false; addHelpLinks(meaning); }
      var unknown = ["clear", "delay", "stop", "closed"].indexOf(a.level) < 0; if (unknown && heading) { heading.textContent = "Last known status"; } var label = unknown ? "Last known status: unavailable" : badgeLabel(a, lvl);
      var asClock = clockLabel(data.updated_utc);
      var chipText = stale ? "As of " + (asClock || "an unknown time") + ": " + label.charAt(0).toLowerCase() + label.slice(1) : label;
      var badgeCls = stale || unknown ? "badge badge--stale" : BADGE_CLASS[lvl];
      if (statusChip) {
        statusChip.className = badgeCls + " status-chip";
        statusChip.textContent = chipText;
      }
      var asOf = "as of " + (asClock || "an unknown time") + " (" + agoText(updMin) + ")";
      if (verdictEl) { verdictEl.textContent = ""; verdictEl.appendChild(verdict(a, lvl, stale, label, asOf)); }
      if (hero) { hero.className = hero.className.replace(/\bap-hero--\w+/, "ap-hero--" + (stale || unknown ? "stale" : lvl)); }
      if (window.ATDHeroArt) { window.ATDHeroArt(stale || unknown ? "stale" : lvl); }
      scaleHelp(stale ? "stale" : lvl);
      var map = document.getElementById("ap-map"); if (map) { map.setAttribute("data-status", stale || unknown ? "stale" : lvl); }
      var pulse = document.querySelector("#ap-now-title .pulse");
      if (pulse) { pulse.className = "pulse pulse--" + (stale ? "stale" : lvl); }
      var w = a.wx;
      if (wxChip) {
        if (w && w.now_text && !stale) {
          var chipWx = "Weather: " + w.now_text;
          if (w.wind_kt != null) { chipWx += ", wind " + windText(w, false); }
          wxChip.textContent = chipWx;
          wxChip.hidden = false;
        } else {
          wxChip.hidden = true;
        }
      }
      box.textContent = "";
      // AN34 round 3: the H1 is the one status block; a stale page names the last FAA reason under it.
      var reasonEl = document.getElementById("ap-reason");
      // The pre-rendered lead under the H1 explains the build-time state; when the state has changed since, drop it and name the reason here.
      var leads = hero ? hero.querySelectorAll(".ap-out, .ap-explain, .ap-alt") : [];
      var changed = (stale ? "stale" : lvl) !== INITIAL_LVL;
      if (changed) { for (var li = 0; li < leads.length; li++) { leads[li].hidden = true; } }
      var hasLead = !changed && leads.length > 0;
      if (reasonEl) { reasonEl.textContent = a.reason && lvl !== "clear" && lvl !== "night" ? "Reason listed: " + reasonText(a.reason) + "." : ""; reasonEl.hidden = !reasonEl.textContent; }
      if (w && w.now_text) {
        var wxText = w.now_text + (w.temp_f != null ? ", " + Math.round(w.temp_f) + "\u00b0F" : "");
        if (w.wind_kt != null) { wxText += ", wind " + windText(w, true); }
        var obsIso = w.obs_utc || data.updated_utc;
        var wxStale = stale || isStale(ageMin(obsIso));
        var wxAfter = wxStale
          ? ", " + (clockLabel(w.obs_utc) ? "observed " + clockLabel(w.obs_utc) + ", " : "") + agoText(ageMin(obsIso))
          : ", observed " + clockLabel(w.obs_utc) + ", " + ageLabel(obsIso, false);
        box.appendChild(tile("fact--wx", wxStale ? WX_LABEL.stale : WX_LABEL.fresh, wxText, "aviationweather.gov METAR", wxAfter));
      }
      // AN35: the next 3 hours sit in the hero (above the fold), with the TAF source and its age. Same rule as _render_live.
      var nx = document.getElementById("ap-next3");
      if (nx) {
        var label = "", taf = w && (w.taf_issue_utc || data.updated_utc);
        if (w && w.next3h_text && outlookText(w)) {
          if (!stale) { label = "Next 3 hours"; } else if (!forecastExpired(w.next3h_text, taf)) { label = "Forecast issued " + clockLabel(taf); }
        }
        nx.textContent = "";
        if (label) {
          nx.appendChild(el("span", "gl-k", label + ":")); nx.appendChild(document.createTextNode(" "));
          nx.appendChild(el("span", "gl-v", outlookText(w))); nx.appendChild(document.createTextNode(" "));
          var gs = el("span", "gl-src"), ga = el("a", "tap", "aviationweather.gov TAF"); ga.href = "/sources"; gs.appendChild(ga);
          if (!stale && clockLabel(taf)) { gs.appendChild(document.createTextNode(", issued " + clockLabel(taf) + " (" + oldText(ageMin(taf)) + ")")); }
          nx.appendChild(gs);
        }
        nx.hidden = !label;
      }
      var alerts = Array.isArray(a.alerts) ? a.alerts : [];
      var foot = el("div", "fact-foot");
      foot.appendChild(el("p", null, alerts.length ? "Alerts: " + alerts.join(", ") : "Alerts: none listed."));
      foot.appendChild(srcLine("credit", "Sources: ", "FAA NAS status, aviationweather.gov METAR and TAF", "."));
      box.appendChild(foot);
    }
    fetch("../data/airports.json?ts=" + Date.now(), { cache: "no-store" })
      .then(function (r) { if (!r.ok) { throw new Error("HTTP " + r.status); } return r.json(); })
      .then(render)
      .catch(function () {
        if (box.getAttribute("data-prerendered") === "1") { return; }
        setUnavailable();
        box.textContent = "";
        box.appendChild(el("p", null, "Could not load live status right now. See nasstatus.faa.gov."));
      });
  })();
