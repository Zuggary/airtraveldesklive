/* Interactive progressive enhancement for /stories/thanksgiving.
   Reads embedded #story-data JSON only; zero network requests, zero storage, zero external libs. */
(function (root) {
  "use strict";

  function fmtInt(n) {
    if (n == null || !isFinite(n)) { return "Not yet published by TSA"; }
    return Math.round(Number(n)).toLocaleString("en-US");
  }

  function millions(n) {
    if (n == null || !isFinite(n)) { return "—"; }
    return (Number(n) / 1e6).toFixed(2) + " million";
  }

  function millionsShort(n) {
    if (n == null || !isFinite(n)) { return ""; }
    return (Number(n) / 1e6).toFixed(2) + "M";
  }

  function signedPct(now, ly) {
    if (now == null || ly == null || !isFinite(now) || !isFinite(ly) || ly === 0) {
      return { text: "awaiting TSA count", cls: "story-delta--warn", pct: null };
    }
    var p = ((Number(now) - Number(ly)) / Number(ly)) * 100;
    var sign = p > 0 ? "+" : "";
    return {
      text: sign + p.toFixed(1) + "%",
      cls: p >= 0 ? "story-delta--up" : "story-delta--down",
      pct: Math.round(p * 10) / 10
    };
  }

  function signedDiff(now, ly) {
    if (now == null || ly == null || !isFinite(now) || !isFinite(ly)) { return "—"; }
    var d = Math.round(Number(now) - Number(ly));
    return (d > 0 ? "+" : "") + d.toLocaleString("en-US");
  }

  function clampTipPos(cx, cy, vw, vh, tw, th) {
    var pad = 12;
    var x = cx + 14;
    if (x + tw + pad > vw) { x = Math.max(pad, cx - tw - 14); }
    var y = cy - th - 12;
    if (y < pad) { y = Math.min(vh - th - pad, cy + 16); }
    return { x: Math.round(Math.max(pad, x)), y: Math.round(Math.max(pad, y)) };
  }

  function yearTakeaway(data, cmpYear) {
    var meta = data && data.years && data.years[String(cmpYear)];
    if (!meta) { return ""; }
    var coreCounted = data.core_counted || 0;
    if (coreCounted === 0 && data.corr_counted > 0 && data.corr_cmp && data.corr_cmp[String(cmpYear)]) {
      var cr = data.corr_cmp[String(cmpYear)];
      var scr = signedPct(data.corr_now, cr.total);
      var cmpPeakC = meta.peak_count != null ? millions(meta.peak_count) : "—";
      return "Across the first " + data.corr_counted + " corridor days (" + data.corr_label + "), TSA screened " +
        fmtInt(data.corr_now) + " travelers this year vs " + fmtInt(cr.total) + " in " + cmpYear + " (" + scr.text + "); " +
        cmpYear + " Thanksgiving week peaked at " + cmpPeakC + " on " + meta.peak_label + ".";
    }
    if (coreCounted === 0 && data.trail7_cmp && data.trail7_cmp[String(cmpYear)]) {
      var tr = data.trail7_cmp[String(cmpYear)];
      var s = signedPct(data.trail7_now, tr.total);
      var cmpPeak = meta.peak_count != null ? millions(meta.peak_count) : "—";
      return "Across the 7 days (" + data.trail7_label + "), TSA screened " + fmtInt(data.trail7_now) +
        " travelers this year vs " + fmtInt(tr.total) + " in " + cmpYear + " (" + s.text + " vs " + cmpYear +
        "); " + cmpYear + " Thanksgiving week peaked at " + cmpPeak + " on " + meta.peak_label + ".";
    }
    if (meta.counted_sum != null && meta.cmp_counted_sum != null) {
      var sc = signedPct(meta.counted_sum, meta.cmp_counted_sum);
      return "Across " + coreCounted + " of 9 Thanksgiving week days counted so far, TSA screened " +
        fmtInt(meta.counted_sum) + " flyers in " + data.target_year + " vs " + fmtInt(meta.cmp_counted_sum) +
        " in " + cmpYear + " (" + sc.text + ").";
    }
    return "Comparing " + data.target_year + " daily TSA checkpoint counts against " + cmpYear + " aligned by weekday relative to Thanksgiving.";
  }

  function clampCursorDx(cx, halfW, minX, maxX) {
    return Math.max(minX + halfW - cx, Math.min(maxX - halfW - cx, 0));
  }

  var api = {
    fmtInt: fmtInt,
    millions: millions,
    millionsShort: millionsShort,
    signedPct: signedPct,
    signedDiff: signedDiff,
    clampTipPos: clampTipPos,
    clampCursorDx: clampCursorDx,
    yearTakeaway: yearTakeaway
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }

  if (typeof document === "undefined") { return; }

  function init() {
    var rawEl = document.getElementById("story-data");
    if (!rawEl) { return; }
    var data;
    try { data = JSON.parse(rawEl.textContent); } catch (e) { return; }

    var cmpYear = String(data.default_cmp_year || "2025");
    var days = data.days || [];
    var selectedIdx = typeof data.default_day_idx === "number" ? data.default_day_idx : 0;
    var manualOverrideUntil = 0;

    var scrub = document.getElementById("rush-scrub");
    var scrubVal = document.getElementById("rush-scrub-val");
    var prevBtn = document.getElementById("rush-prev");
    var nextBtn = document.getElementById("rush-next");
    var readout = document.getElementById("rush-readout");
    var takeaway = document.getElementById("rush-takeaway");
    var yearBtns = Array.prototype.slice.call(document.querySelectorAll("[data-cmp-year]"));
    var stepItems = Array.prototype.slice.call(document.querySelectorAll(".story-step"));
    var stepBtns = Array.prototype.slice.call(document.querySelectorAll(".story-step-btn"));
    var desktopSvg = document.getElementById("rush-svg-desktop");
    var mobileSvg = document.getElementById("rush-svg-mobile");
    var tip = document.getElementById("story-tip");

    function hideTip() {
      if (tip) { tip.hidden = true; tip.textContent = ""; }
    }

    function showTip(title, lines, clientX, clientY) {
      if (!tip || clientX == null || clientY == null) { return; }
      tip.textContent = "";
      var strong = document.createElement("strong");
      strong.textContent = title;
      tip.appendChild(strong);
      lines.forEach(function (ln) {
        var div = document.createElement("div");
        div.textContent = ln;
        tip.appendChild(div);
      });
      tip.hidden = false;
      var rect = tip.getBoundingClientRect();
      var pos = clampTipPos(clientX, clientY, window.innerWidth, window.innerHeight, rect.width || 220, rect.height || 70);
      tip.style.left = pos.x + "px";
      tip.style.top = pos.y + "px";
    }

    function updateReadout() {
      var d = days[selectedIdx];
      if (!d || !readout) { return; }
      var cmp = (d.years && d.years[cmpYear]) || {};
      var nowVal = d.count;
      var lyVal = cmp.count;
      var s = signedPct(nowVal, lyVal);

      var dayEl = document.getElementById("rush-ro-day");
      var nowEl = document.getElementById("rush-ro-now");
      var lyEl = document.getElementById("rush-ro-ly");
      if (dayEl) {
        dayEl.textContent = d.label + " (" + d.offset_label + ")";
      }
      if (nowEl) {
        nowEl.textContent = "";
        nowEl.appendChild(document.createTextNode(nowVal != null ? fmtInt(nowVal) : "Not yet published by TSA"));
        var sub = document.createElement("span");
        sub.textContent = nowVal != null
          ? "in " + data.target_year + " (" + signedDiff(nowVal, lyVal) + ", " + s.text + " vs " + cmpYear + ")"
          : data.target_year + " awaiting TSA daily release";
        if (nowVal != null && s.cls) { sub.className = s.cls; }
        nowEl.appendChild(sub);
      }
      if (lyEl) {
        lyEl.textContent = "";
        lyEl.appendChild(document.createTextNode(lyVal != null ? fmtInt(lyVal) : "—"));
        var sub2 = document.createElement("span");
        sub2.textContent = cmp.label ? ("in " + cmpYear + " (" + cmp.label + " · same weekday)") : (cmpYear + " comparison");
        lyEl.appendChild(sub2);
      }
    }

    function updateDesktopBars() {
      if (!desktopSvg) { return; }
      var maxM = Number(desktopSvg.getAttribute("data-max-val")) || 3500000;
      var xLeft = Number(desktopSvg.getAttribute("data-x-left")) || 48;
      var xRight = Number(desktopSvg.getAttribute("data-x-right")) || 744;
      var yTop = Number(desktopSvg.getAttribute("data-y-top")) || 84;
      var yBot = Number(desktopSvg.getAttribute("data-y-bot")) || 318;
      var plotH = yBot - yTop;

      var cmpLabel = desktopSvg.querySelector("#rush-d-cmp-legend");
      if (cmpLabel) { cmpLabel.textContent = cmpYear + " same weekday"; }

      var peakIdx = -1, peakVal = -1, latestIdx = -1, lullIdx = -1;
      days.forEach(function (d, i) {
        if (d.count != null) { latestIdx = i; }
        if (d.k === 0) { lullIdx = i; }
        var cmp = (d.years && d.years[cmpYear]) || {};
        var val = cmp.count;
        var rect = desktopSvg.querySelector('[data-d-ly-bar="' + i + '"]');
        var cap = desktopSvg.querySelector('[data-d-ly-cap="' + i + '"]');
        if (rect) {
          if (val != null) {
            var h = Math.max(2, (val / maxM) * plotH);
            var y = yBot - h;
            rect.setAttribute("y", y.toFixed(1));
            rect.setAttribute("height", h.toFixed(1));
            rect.removeAttribute("visibility");
            if (cap) {
              cap.setAttribute("y1", y.toFixed(1));
              cap.setAttribute("y2", y.toFixed(1));
              cap.removeAttribute("visibility");
            }
            if (val > peakVal) { peakVal = val; peakIdx = i; }
          } else {
            rect.setAttribute("visibility", "hidden");
            if (cap) { cap.setAttribute("visibility", "hidden"); }
          }
        }
      });

      var peakText = desktopSvg.querySelector("#rush-d-peak-text");
      var peakLine = desktopSvg.querySelector("#rush-d-peak-line");
      var peakBy = yBot;
      var peakTy = 72;
      if (peakText && peakIdx >= 0) {
        var hit = desktopSvg.querySelector('[data-d-ly-bar="' + peakIdx + '"]');
        if (hit) {
          var bx = Number(hit.getAttribute("x")) + Number(hit.getAttribute("width")) / 2;
          peakBy = Number(hit.getAttribute("y"));
          peakTy = Math.max(72, peakBy - 15);
          var tx = peakIdx >= 11 ? (xRight - 4) : bx;
          peakText.setAttribute("x", tx.toFixed(1));
          peakText.setAttribute("y", peakTy.toFixed(1));
          peakText.setAttribute("text-anchor", peakIdx >= 11 ? "end" : "middle");
          var suffix = (cmpYear === "2025" && data.record_date === days[peakIdx].years["2025"].date) ? " record" : "";
          peakText.textContent = cmpYear + " peak: " + millionsShort(peakVal) + suffix;
          if (peakLine) {
            peakLine.setAttribute("x1", bx.toFixed(1));
            peakLine.setAttribute("x2", bx.toFixed(1));
            peakLine.setAttribute("y1", (peakBy - 3).toFixed(1));
            peakLine.setAttribute("y2", (peakTy + 4).toFixed(1));
          }
        }
      }

      var lullText = desktopSvg.querySelector("#rush-d-lull-text");
      var lullVal = desktopSvg.querySelector("#rush-d-lull-v");
      var lullKey = desktopSvg.querySelector("#rush-d-lull-k");
      var lullLine = desktopSvg.querySelector("#rush-d-lull-line");
      if (lullText && lullIdx >= 0) {
        var ld = days[lullIdx];
        var lVal = ld.count != null ? ld.count : ((ld.years && ld.years[cmpYear] && ld.years[cmpYear].count) || 0);
        var lHit = desktopSvg.querySelector('[data-d-ly-bar="' + lullIdx + '"]');
        var lDayEl = desktopSvg.querySelector('[data-day-idx="' + lullIdx + '"]');
        var lCx = lDayEl ? Number(lDayEl.getAttribute("data-cx")) : 548;
        var lBx = ld.count != null ? (lCx + 7.5) : (lHit ? Number(lHit.getAttribute("x")) + Number(lHit.getAttribute("width")) / 2 : lCx - 7.5);
        var lBy = yBot - (lVal / maxM) * plotH;
        var lTy = lBy - 12;
        var lTx = lCx + 3.5;
        lullText.setAttribute("x", lTx.toFixed(1));
        lullText.setAttribute("y", lTy.toFixed(1));
        if (lullKey) { lullKey.setAttribute("x", lTx.toFixed(1)); }
        if (lullVal) {
          lullVal.setAttribute("x", lTx.toFixed(1));
          lullVal.textContent = millionsShort(lVal);
        } else {
          lullText.textContent = "T0 lull: " + millionsShort(lVal);
        }
        if (lullLine) {
          lullLine.setAttribute("x1", lBx.toFixed(1));
          lullLine.setAttribute("x2", lBx.toFixed(1));
          lullLine.setAttribute("y1", (lBy - 3).toFixed(1));
          lullLine.setAttribute("y2", (lTy + 3).toFixed(1));
        }
      }

      var nowText = desktopSvg.querySelector("#rush-d-now-text");
      var nowLine = desktopSvg.querySelector("#rush-d-now-line");
      if (nowText && latestIdx >= 0) {
        var nd = days[latestIdx];
        var nHitG = desktopSvg.querySelector('[data-day-idx="' + latestIdx + '"]');
        var nCx = nHitG ? Number(nHitG.getAttribute("data-cx")) : xLeft;
        var nBx = nCx + 7.5;
        var nBy = yBot - (nd.count / maxM) * plotH;
        var nbMax = nd.count;
        for (var j = Math.max(0, latestIdx - 1); j <= Math.min(days.length - 1, latestIdx + 3); j++) {
          if (days[j].count != null && days[j].count > nbMax) { nbMax = days[j].count; }
          var yc = days[j].years && days[j].years[cmpYear] && days[j].years[cmpYear].count;
          if (yc != null && yc > nbMax) { nbMax = yc; }
        }
        var nbMinY = yBot - (nbMax / maxM) * plotH;
        var nowTy, nowTx, nowAnchor;
        if (Math.abs(latestIdx - peakIdx) <= 2 && Math.abs(nBy - peakBy) < 42) {
          nowTy = peakTy + 22;
          nowTx = xRight - 4;
          nowAnchor = "end";
        } else {
          nowTy = Math.max(72, Math.min(nBy - 15, nbMinY - 18));
          nowAnchor = latestIdx <= 2 ? "start" : (latestIdx >= 13 ? "end" : "middle");
          nowTx = Math.max(xLeft + 4, Math.min(xRight - 4, nBx));
        }
        var nLyVal = nd.years && nd.years[cmpYear] && nd.years[cmpYear].count;
        var nShort = nd.short || "";
        var nLbl = nLyVal != null
          ? (nShort + ": " + millionsShort(nd.count) + " (" + signedPct(nd.count, nLyVal).text + ")")
          : (nShort + ": " + millionsShort(nd.count));
        nowText.setAttribute("x", nowTx.toFixed(1));
        nowText.setAttribute("y", nowTy.toFixed(1));
        nowText.setAttribute("text-anchor", nowAnchor);
        nowText.textContent = nLbl;
        if (nowLine) {
          nowLine.setAttribute("x1", nBx.toFixed(1));
          nowLine.setAttribute("x2", nBx.toFixed(1));
          nowLine.setAttribute("y1", (nBy - 4).toFixed(1));
          nowLine.setAttribute("y2", (nowTy + 4).toFixed(1));
        }
      }
    }

    function updateMobileBars() {
      if (!mobileSvg) { return; }
      var maxM = Number(mobileSvg.getAttribute("data-max-val")) || 3500000;
      var x0 = Number(mobileSvg.getAttribute("data-x-zero")) || 58;
      var xMax = Number(mobileSvg.getAttribute("data-x-max")) || 212;
      var plotW = xMax - x0;

      var cmpLegend = mobileSvg.querySelector("#rush-m-cmp-legend");
      if (cmpLegend) { cmpLegend.textContent = cmpYear + " same weekday"; }

      days.forEach(function (d, i) {
        var cmp = (d.years && d.years[cmpYear]) || {};
        var val = cmp.count;
        var rect = mobileSvg.querySelector('[data-m-ly-bar="' + i + '"]');
        var lbl = mobileSvg.querySelector('[data-m-val="' + i + '"]');
        if (rect) {
          if (val != null) {
            var w = Math.max(2, (val / maxM) * plotW);
            rect.setAttribute("width", w.toFixed(1));
            rect.removeAttribute("visibility");
          } else {
            rect.setAttribute("visibility", "hidden");
          }
        }
        if (lbl) {
          if (d.count != null) {
            var s = val != null ? (" " + signedPct(d.count, val).text) : "";
            lbl.textContent = millionsShort(d.count) + s;
            lbl.setAttribute("class", "sv-anno");
          } else if (val != null && (d.k === -1 || d.k === 0 || d.k === 3 || i === selectedIdx)) {
            lbl.textContent = cmpYear + ": " + millionsShort(val);
            lbl.setAttribute("class", i === selectedIdx ? "sv-label" : "sv-muted");
          } else {
            lbl.textContent = "";
            lbl.setAttribute("class", "sv-muted");
          }
        }
      });
    }

    function syncDaySelection() {
      if (selectedIdx < 0) { selectedIdx = 0; }
      if (selectedIdx >= days.length) { selectedIdx = days.length - 1; }
      if (scrub) { scrub.value = String(selectedIdx); }
      if (prevBtn) { prevBtn.disabled = selectedIdx <= 0; }
      if (nextBtn) { nextBtn.disabled = selectedIdx >= days.length - 1; }

      var d = days[selectedIdx];
      var dayPill = d ? ((d.short ? d.short + " · " : "") + d.offset_label) : "";
      if (scrubVal && dayPill) { scrubVal.textContent = "Selected: " + dayPill; }

      // Move Signature Moment sightline cursor on desktop SVG (clamped pill inside plot edges)
      if (desktopSvg && d) {
        var xLeft = Number(desktopSvg.getAttribute("data-x-left")) || 48;
        var xRight = Number(desktopSvg.getAttribute("data-x-right")) || 744;
        var hit = desktopSvg.querySelector('[data-day-idx="' + selectedIdx + '"]');
        var cursor = desktopSvg.querySelector("#rush-cursor");
        var tagRect = desktopSvg.querySelector("#rush-cursor-tag");
        var tagText = desktopSvg.querySelector("#rush-cursor-tag-text");
        if (hit && cursor) {
          var cx = Number(hit.getAttribute("data-cx")) || 0;
          var pillW = tagRect ? (Number(tagRect.getAttribute("width")) || 122) : 122;
          var dx = clampCursorDx(cx, pillW / 2, xLeft, xRight);
          cursor.setAttribute("transform", "translate(" + cx.toFixed(1) + ", 0)");
          if (tagRect) { tagRect.setAttribute("x", (dx - pillW / 2).toFixed(1)); }
          if (tagText) {
            tagText.setAttribute("x", dx.toFixed(1));
            tagText.textContent = dayPill;
          }
        }
      }

      document.querySelectorAll(".sv-day-hit").forEach(function (el) {
        var idx = Number(el.getAttribute("data-day-idx"));
        el.classList.toggle("is-selected", idx === selectedIdx);
      });

      stepItems.forEach(function (li) {
        var idx = Number(li.getAttribute("data-step-idx"));
        li.classList.toggle("is-active", idx === selectedIdx);
      });

      updateMobileBars();
      updateReadout();
    }

    function setCmpYear(yr) {
      cmpYear = String(yr);
      yearBtns.forEach(function (b) {
        b.setAttribute("aria-pressed", b.getAttribute("data-cmp-year") === cmpYear ? "true" : "false");
      });
      if (takeaway) { takeaway.textContent = yearTakeaway(data, cmpYear); }
      updateDesktopBars();
      updateMobileBars();
      syncDaySelection();
    }

    yearBtns.forEach(function (b) {
      b.addEventListener("click", function () {
        setCmpYear(b.getAttribute("data-cmp-year"));
      });
    });

    function manualSelectDay(idx) {
      manualOverrideUntil = Date.now() + 3000;
      selectedIdx = Math.max(0, Math.min(days.length - 1, idx));
      syncDaySelection();
    }

    if (scrub) {
      scrub.addEventListener("input", function () {
        manualSelectDay(Number(scrub.value));
      });
    }
    if (prevBtn) {
      prevBtn.addEventListener("click", function () { manualSelectDay(selectedIdx - 1); });
    }
    if (nextBtn) {
      nextBtn.addEventListener("click", function () { manualSelectDay(selectedIdx + 1); });
    }

    stepBtns.forEach(function (btn) {
      btn.addEventListener("click", function () {
        var li = btn.closest(".story-step");
        if (li) { manualSelectDay(Number(li.getAttribute("data-step-idx"))); }
      });
    });

    if ("IntersectionObserver" in window && stepItems.length) {
      var io = new IntersectionObserver(function (entries) {
        if (Date.now() < manualOverrideUntil) { return; }
        entries.forEach(function (entry) {
          if (entry.isIntersecting && entry.intersectionRatio >= 0.55) {
            var idx = Number(entry.target.getAttribute("data-step-idx"));
            if (!isNaN(idx) && idx !== selectedIdx) {
              selectedIdx = idx;
              syncDaySelection();
            }
          }
        });
      }, { threshold: [0.55], rootMargin: "-8% 0px -42% 0px" });
      stepItems.forEach(function (el) { io.observe(el); });
    }

    function dayTipLines(d) {
      var cmp = (d.years && d.years[cmpYear]) || {};
      var s = signedPct(d.count, cmp.count);
      var l1 = data.target_year + ": " + (d.count != null ? fmtInt(d.count) : "awaiting TSA release");
      var l2 = cmpYear + " (" + (cmp.label || cmpYear) + "): " + (cmp.count != null ? fmtInt(cmp.count) : "—");
      var l3 = d.count != null && cmp.count != null ? ("Diff: " + signedDiff(d.count, cmp.count) + " (" + s.text + ")") : d.offset_label;
      return [l1, l2, l3];
    }

    document.querySelectorAll(".sv-day-hit").forEach(function (el) {
      var idx = Number(el.getAttribute("data-day-idx"));
      el.addEventListener("click", function (ev) {
        manualSelectDay(idx);
        var d = days[idx];
        if (d) { showTip(d.label + " · " + d.offset_label, dayTipLines(d), ev.clientX, ev.clientY); }
      });
      el.addEventListener("pointermove", function (ev) {
        var d = days[idx];
        if (d) { showTip(d.label + " · " + d.offset_label, dayTipLines(d), ev.clientX, ev.clientY); }
      });
      el.addEventListener("pointerleave", hideTip);
      el.addEventListener("keydown", function (ev) {
        if (ev.key === "ArrowRight" || ev.key === "ArrowDown") { ev.preventDefault(); manualSelectDay(selectedIdx + 1); }
        else if (ev.key === "ArrowLeft" || ev.key === "ArrowUp") { ev.preventDefault(); manualSelectDay(selectedIdx - 1); }
        else if (ev.key === "Home") { ev.preventDefault(); manualSelectDay(0); }
        else if (ev.key === "End") { ev.preventDefault(); manualSelectDay(days.length - 1); }
        else if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); manualSelectDay(idx); }
      });
    });

    // -------- Section 2: FAA Hourly Delay Explorer --------
    var faa = data.faa || {};
    var hours = faa.hours || [];
    var rows = faa.rows || [];
    var delayHour = typeof faa.peak_hour_idx === "number" ? faa.peak_hour_idx : 0;
    var selectedAp = faa.default_ap || (rows[0] && rows[0].code) || "";
    var activeFilter = "all";

    var dScrub = document.getElementById("delay-scrub");
    var dScrubVal = document.getElementById("delay-scrub-val");
    var dPrev = document.getElementById("delay-prev");
    var dNext = document.getElementById("delay-next");
    var dReadout = document.getElementById("delay-readout");
    var dFilterBtns = Array.prototype.slice.call(document.querySelectorAll("[data-delay-filter]"));
    var dDesktopSvg = document.getElementById("delay-svg-desktop");
    var dMobileSvg = document.getElementById("delay-svg-mobile");

    function updateDelayReadout() {
      if (!dReadout) { return; }
      var h = hours[delayHour];
      var hLabel = h ? (h.et + " (" + h.utc + ")") : "";
      var activeOps = [];
      var snaState = null;
      rows.forEach(function (r) {
        if (r.is_closure_listing) {
          snaState = r.strip.charAt(delayHour);
          return;
        }
        var ch = r.strip.charAt(delayHour);
        if (ch === "d" || ch === "s") {
          activeOps.push(r.code + " (" + (ch === "s" ? "stop/closure" : "delay") + ")");
        }
      });

      var timeEl = document.getElementById("delay-ro-time");
      var activeEl = document.getElementById("delay-ro-active");
      var apEl = document.getElementById("delay-ro-ap");
      if (timeEl) { timeEl.textContent = hLabel; }
      if (activeEl) {
        activeEl.textContent = "";
        activeEl.appendChild(document.createTextNode(
          activeOps.length
            ? (activeOps.length + (activeOps.length === 1 ? " airport" : " airports") + " with active delay/stop: " + activeOps.join(", "))
            : "0 operational delay/stop listings at this hourly check"
        ));
        var sub = document.createElement("span");
        sub.textContent = snaState === "s" ? "Plus SNA nightly closure listing." : "All operational hubs checked.";
        activeEl.appendChild(sub);
      }
      if (apEl) {
        var rSel = rows.filter(function (x) { return x.code === selectedAp; })[0];
        if (rSel) {
          apEl.textContent = "";
          apEl.appendChild(document.createTextNode(rSel.code + " · " + rSel.short + ": " + rSel.non_clear + " non-clear hourly checks"));
          var subAp = document.createElement("span");
          subAp.textContent = rSel.d + " delay, " + rSel.s + " stop/closure" + (rSel.first_onset_local ? " · first non-clear " + rSel.first_onset_local : "");
          apEl.appendChild(subAp);
        }
      }
    }

    function syncDelayHour() {
      if (delayHour < 0) { delayHour = 0; }
      if (delayHour >= hours.length) { delayHour = Math.max(0, hours.length - 1); }
      if (dScrub) { dScrub.value = String(delayHour); }
      if (dPrev) { dPrev.disabled = delayHour <= 0; }
      if (dNext) { dNext.disabled = delayHour >= hours.length - 1; }

      var h = hours[delayHour];
      if (dScrubVal && h) { dScrubVal.textContent = "Selected: " + h.et; }
      var opCount = h && typeof h.op_active === "number" ? h.op_active : 0;
      var isPeak = delayHour === faa.peak_hour_idx;

      if (dDesktopSvg) {
        var xStart = Number(dDesktopSvg.getAttribute("data-strip-x")) || 196;
        var stripW = Number(dDesktopSvg.getAttribute("data-strip-w")) || 468;
        var cellW = Number(dDesktopSvg.getAttribute("data-strip-cw")) || 6.5;
        var cur = dDesktopSvg.querySelector("#delay-hour-cursor");
        var tagRect = dDesktopSvg.querySelector("#delay-d-cursor-tag");
        var tagText = dDesktopSvg.querySelector("#delay-d-cursor-text");
        if (cur) {
          var cx = xStart + delayHour * cellW + cellW / 2;
          var pillW = tagRect ? (Number(tagRect.getAttribute("width")) || 144) : 144;
          var dx = clampCursorDx(cx, pillW / 2, xStart, xStart + stripW);
          cur.setAttribute("transform", "translate(" + cx.toFixed(1) + ", 0)");
          if (tagRect) { tagRect.setAttribute("x", (dx - pillW / 2).toFixed(1)); }
          if (tagText) {
            tagText.setAttribute("x", dx.toFixed(1));
            tagText.textContent = isPeak
              ? ("Peak: " + opCount + " airports")
              : (opCount + (opCount === 1 ? " airport" : " airports"));
          }
        }
      }

      if (dMobileSvg) {
        var mxStart = Number(dMobileSvg.getAttribute("data-strip-x")) || 4;
        var mCellW = Number(dMobileSvg.getAttribute("data-strip-cw")) || 4.2778;
        var mCur = dMobileSvg.querySelector("#delay-m-hour-cursor");
        var mTagRect = dMobileSvg.querySelector("#delay-m-cursor-tag");
        var mTagText = dMobileSvg.querySelector("#delay-m-cursor-text");
        if (mCur) {
          var mcx = mxStart + delayHour * mCellW + mCellW / 2;
          var mPillW = mTagRect ? (Number(mTagRect.getAttribute("width")) || 128) : 128;
          var mdx = clampCursorDx(mcx, mPillW / 2, 2, 315);
          mCur.setAttribute("transform", "translate(" + mcx.toFixed(1) + ", 0)");
          if (mTagRect) { mTagRect.setAttribute("x", (mdx - mPillW / 2).toFixed(1)); }
          if (mTagText) {
            mTagText.setAttribute("x", mdx.toFixed(1));
            mTagText.textContent = isPeak ? ("Peak: " + opCount + " airports") : (opCount + (opCount === 1 ? " airport" : " airports"));
          }
        }
      }
      updateDelayReadout();
    }

    function applyDelayFilter(mode) {
      activeFilter = mode;
      dFilterBtns.forEach(function (b) {
        b.setAttribute("aria-pressed", b.getAttribute("data-delay-filter") === mode ? "true" : "false");
      });
      [dDesktopSvg, dMobileSvg].forEach(function (svg) {
        if (!svg) { return; }
        var rowH = Number(svg.getAttribute("data-row-h")) || 28;
        var y0 = Number(svg.getAttribute("data-rows-y")) || 98;
        var visIdx = 0;
        svg.querySelectorAll(".sv-ap-row").forEach(function (g) {
          var hasStop = g.getAttribute("data-has-stop") === "1";
          var show = mode === "all" || hasStop;
          if (!show) {
            g.setAttribute("display", "none");
            return;
          }
          g.removeAttribute("display");
          var baseY = Number(g.getAttribute("data-base-y")) || y0;
          var targetY = y0 + visIdx * rowH;
          g.setAttribute("transform", "translate(0, " + (targetY - baseY).toFixed(1) + ")");
          visIdx += 1;
        });
        ["#delay-hour-cursor-line", "#delay-m-hour-cursor-line"].forEach(function (sel) {
          var line = svg.querySelector(sel);
          if (line) {
            line.setAttribute("y2", (y0 + visIdx * rowH).toFixed(1));
          }
        });
        svg.querySelectorAll(".sv-col-grid").forEach(function (line) {
          line.setAttribute("y2", (y0 + visIdx * rowH).toFixed(1));
        });
        var foot = svg.querySelector(".sv-sna-foot");
        if (foot) {
          var footBase = Number(foot.getAttribute("data-base-y")) || y0;
          var footY = y0 + visIdx * rowH + 14;
          foot.setAttribute("transform", "translate(0, " + (footY - footBase).toFixed(1) + ")");
          var vb = (svg.getAttribute("data-orig-vb") || svg.getAttribute("viewBox") || "").split(" ");
          if (vb.length === 4) {
            if (!svg.getAttribute("data-orig-vb")) { svg.setAttribute("data-orig-vb", vb.join(" ")); }
            var newH = footY + (Number(svg.getAttribute("data-foot-h")) || 70);
            svg.setAttribute("viewBox", vb[0] + " " + vb[1] + " " + vb[2] + " " + Math.round(newH));
          }
        }
      });
    }

    dFilterBtns.forEach(function (b) {
      b.addEventListener("click", function () {
        applyDelayFilter(b.getAttribute("data-delay-filter"));
      });
    });

    if (dScrub) {
      dScrub.addEventListener("input", function () {
        delayHour = Number(dScrub.value);
        syncDelayHour();
      });
    }
    if (dPrev) {
      dPrev.addEventListener("click", function () { delayHour -= 1; syncDelayHour(); });
    }
    if (dNext) {
      dNext.addEventListener("click", function () { delayHour += 1; syncDelayHour(); });
    }

    document.querySelectorAll(".sv-ap-hit").forEach(function (el) {
      var code = el.getAttribute("data-ap-code");
      var r = rows.filter(function (x) { return x.code === code; })[0];
      function selectAp(ev) {
        selectedAp = code;
        document.querySelectorAll(".sv-ap-hit").forEach(function (other) {
          other.classList.toggle("is-selected", other.getAttribute("data-ap-code") === code);
        });
        updateDelayReadout();
        if (r && ev && ev.clientX != null) {
          showTip(r.code + " · " + r.short, [
            r.non_clear + " of " + hours.length + " checks (" + r.share_pct.toFixed(1) + "%)",
            r.d + " delay checks · " + r.s + " stop/closure checks",
            r.first_onset_local ? ("First non-clear: " + r.first_onset_local) : ""
          ].filter(Boolean), ev.clientX, ev.clientY);
        }
      }
      el.addEventListener("click", selectAp);
      el.addEventListener("pointermove", function (ev) {
        if (r) {
          showTip(r.code + " · " + r.short, [
            r.non_clear + " of " + hours.length + " checks (" + r.share_pct.toFixed(1) + "%)",
            r.d + " delay checks · " + r.s + " stop/closure checks",
            r.first_onset_local ? ("First non-clear: " + r.first_onset_local) : ""
          ].filter(Boolean), ev.clientX, ev.clientY);
        }
      });
      el.addEventListener("pointerleave", hideTip);
      el.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); selectAp(ev); }
      });
    });

    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") { hideTip(); }
    });
    document.addEventListener("pointerdown", function (ev) {
      if (!ev.target || !ev.target.closest || !ev.target.closest(".story-svg")) { hideTip(); }
    });

    syncDaySelection();
    syncDelayHour();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(typeof window !== "undefined" ? window : globalThis);
