"""Tests for /stories/thanksgiving: trace integrity, self-updating builder stages, workflow & check_site wiring.

Zero network calls: uses committed fixtures under tests/fixtures/ for all synthetic/stage tests,
and verifies the built stories/thanksgiving/index.html against data/tsa-history.json and readings/.
"""
from __future__ import annotations

import html as html_lib
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desk import airports as desk_airports  # noqa: E402
from desk import tsa as desk_tsa  # noqa: E402
from tools import build_airport_pages as bap  # noqa: E402
from tools import build_stories as bs  # noqa: E402
from tools import check_site  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
OWN_HOSTS = {"", "www.airtraveldesklive.com"}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
ET_ZONE = ZoneInfo("America/New_York")


def _resolve_dotted(obj: dict, dotted: str):
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, list):
            cur = cur[int(part)]
        elif isinstance(cur, dict):
            cur = cur[part]
        else:
            raise KeyError(f"Cannot resolve {dotted!r} at {part!r}")
    return cur


def _canonical_merged_history(hist_doc: dict, state_doc: dict) -> dict:
    hours = list(hist_doc.get("hours") or [])
    n_h = len(hours)
    merged = bap._history_rows(hist_doc.get("airports") or {}, n_h)
    closures = {
        desk_airports.canonical_code(ev.get("airport"))
        for ev in (state_doc.get("events") or [])
        if isinstance(ev, dict) and ev.get("kind") == "closure"
    }
    op_rows = []
    closure_rows = []
    clear_missing = []
    for code, strip in sorted(merged.items()):
        d = strip.count("d")
        s = strip.count("s")
        c = strip.count("c")
        m = strip.count("-")
        nc = d + s
        is_clos = (nc == n_h and s == n_h and code in closures)
        if nc == 0:
            clear_missing.append(m)
        elif is_clos:
            closure_rows.append({"code": code, "strip": strip, "d": d, "s": s, "c": c, "m": m, "nc": nc})
        else:
            op_rows.append({"code": code, "strip": strip, "d": d, "s": s, "c": c, "m": m, "nc": nc})
    peak_op = max((sum(1 for r in op_rows if r["strip"][i] in ("d", "s")) for i in range(n_h)), default=0)
    return {
        "hours": hours,
        "n_hours": n_h,
        "merged": merged,
        "op_rows": op_rows,
        "closure_rows": closure_rows,
        "clear_count": len(clear_missing),
        "clear_missing_min": min(clear_missing) if clear_missing else 0,
        "clear_missing_max": max(clear_missing) if clear_missing else 0,
        "peak_op": peak_op,
    }


def _verify_trace_entry(eid: str, entry: dict, loaded_files: dict[str, dict]) -> None:
    rel_file = entry.get("file")
    if not rel_file or rel_file not in loaded_files:
        raise AssertionError(f"Trace entry {eid!r} points to unknown file {rel_file!r}")
    doc = loaded_files[rel_file]
    if not entry.get("source") or not entry.get("url"):
        raise AssertionError(f"Trace entry {eid!r} missing source or url")

    op = entry.get("op")
    val = entry.get("value")
    if op == "direct":
        actual = _resolve_dotted(doc, entry["field"])
        if actual != val:
            raise AssertionError(f"Trace {eid!r} mismatch: {val!r} != {actual!r} ({rel_file}:{entry['field']})")
    elif op == "sum":
        actual = sum(int(_resolve_dotted(doc, p)) for p in entry["inputs"])
        if actual != val:
            raise AssertionError(f"Trace {eid!r} sum mismatch: {val!r} != {actual!r}")
    elif op == "diff":
        a = entry["args"]["a"]
        b = entry["args"]["b"]
        actual = sum(int(_resolve_dotted(doc, p)) for p in a) - sum(int(_resolve_dotted(doc, p)) for p in b)
        if actual != val:
            raise AssertionError(f"Trace {eid!r} diff mismatch: {val!r} != {actual!r}")
    elif op == "pct_change":
        a = entry["args"]["a"]
        b = entry["args"]["b"]
        dec = int(entry["args"].get("decimals", 1))
        sa = sum(int(_resolve_dotted(doc, p)) for p in a)
        sb = sum(int(_resolve_dotted(doc, p)) for p in b)
        actual = round(((sa - sb) / sb) * 100.0, dec)
        if entry["args"].get("abs"):
            actual = abs(actual)
        if actual != val:
            raise AssertionError(f"Trace {eid!r} pct mismatch: {val!r} != {actual!r}")
    elif op == "millions":
        dec = int(entry["args"].get("decimals", 2))
        total = sum(int(_resolve_dotted(doc, p)) for p in entry["inputs"])
        actual = round(total / 1_000_000.0, dec)
        if actual != val:
            raise AssertionError(f"Trace {eid!r} millions mismatch: {val!r} != {actual!r}")
    elif op == "year_in_history":
        years = [int(y) for y in doc.get("years") or []]
        if int(val) not in years:
            raise AssertionError(f"Trace {eid!r} year {val!r} not in {years}")
    elif op == "corridor_date":
        d_val = date.fromisoformat(str(val))
        ty = int(entry["args"]["target_year"])
        all_years = sorted({int(y) for y in (doc.get("years") or [])} | {ty})
        valid_dates = set()
        for y in all_years:
            tg = desk_tsa.thanksgiving(y)
            for k in range(-14, 7):
                valid_dates.add(tg + timedelta(days=k))
        if d_val not in valid_dates and d_val.isoformat() not in doc.get("days", {}):
            raise AssertionError(f"Trace {eid!r} date {d_val} outside valid Thanksgiving corridor")
    elif op == "corridor_offset":
        if not (-11 <= int(val) <= 4):
            raise AssertionError(f"Trace {eid!r} offset {val!r} out of range -11..+4")
    elif op == "corridor_meta":
        kind = entry["args"]["kind"]
        ty = int(entry["args"]["target_year"])
        tg = desk_tsa.thanksgiving(ty)
        days_map = doc.get("days") or {}
        if kind == "corridor_len":
            expected = 16
        elif kind == "core_len":
            expected = 9
        elif kind == "trail_len":
            expected = 7
        elif kind == "counted_corridor":
            expected = sum(1 for k in range(-11, 5) if (tg + timedelta(days=k)).isoformat() in days_map)
        elif kind == "counted_core":
            expected = sum(1 for k in range(-4, 5) if (tg + timedelta(days=k)).isoformat() in days_map)
        elif kind == "years_len":
            expected = len(doc.get("years") or [])
        elif kind == "zero":
            expected = 0
        else:
            raise AssertionError(f"Unknown corridor_meta kind {kind!r}")
        if expected != val:
            raise AssertionError(f"Trace {eid!r} {kind} mismatch: {val!r} != {expected!r}")
    elif op == "scale_tick":
        ty = int(entry["args"]["target_year"])
        cmp_years = [int(y) for y in entry["args"]["cmp_years"]]
        days_map = doc.get("days") or {}
        vals = []
        for y in [ty] + cmp_years:
            tg = desk_tsa.thanksgiving(y)
            for k in range(-11, 5):
                iso = (tg + timedelta(days=k)).isoformat()
                if iso in days_map:
                    vals.append(int(days_map[iso]))
        max_m = math.ceil(max(vals or [3_000_000]) / 500_000) * 0.5
        if not (0.0 <= float(val) <= max_m):
            raise AssertionError(f"Trace {eid!r} tick {val!r} exceeds scale max {max_m}")
    elif op == "timestamp_view":
        actual_iso = str(_resolve_dotted(doc, entry["field"]))
        if actual_iso != val:
            raise AssertionError(f"Trace {eid!r} timestamp mismatch: {val!r} != {actual_iso!r}")
    elif op == "hist_hours_days":
        expected = round(len(doc.get("hours") or []) / 24.0, 1)
        if expected == int(expected):
            expected = int(expected)
        if expected != val:
            raise AssertionError(f"Trace {eid!r} hours->days mismatch: {val!r} != {expected!r}")
    elif op == "hist_canonical_counts":
        state_file = entry["args"]["state_file"]
        state_doc = loaded_files.get(state_file, {})
        summary = _canonical_merged_history(doc, state_doc)
        kind = entry["args"]["kind"]
        expected_map = {
            "hours_len": summary["n_hours"],
            "canonical_total": len(summary["merged"]),
            "disrupted": len(summary["op_rows"]),
            "closures": len(summary["closure_rows"]),
            "stops": sum(1 for r in summary["op_rows"] if r["s"] > 0),
            "clear": summary["clear_count"],
            "clear_missing_min": summary["clear_missing_min"],
            "clear_missing_max": summary["clear_missing_max"],
            "peak_excl_sna": summary["peak_op"],
            "rows_total": int(doc.get("rows") or 0),
        }
        if kind not in expected_map or expected_map[kind] != val:
            raise AssertionError(f"Trace {eid!r} {kind} mismatch: {val!r} != {expected_map.get(kind)!r}")
    elif op == "hist_airport":
        merged = bap._history_rows(doc.get("airports") or {}, len(doc.get("hours") or []))
        code = entry["args"]["code"]
        strip = merged[code]
        kind = entry["args"]["kind"]
        n_h = len(doc.get("hours") or [])
        if kind == "d":
            expected = strip.count("d")
        elif kind == "s":
            expected = strip.count("s")
        elif kind == "c":
            expected = strip.count("c")
        elif kind == "missing":
            expected = strip.count("-")
        elif kind == "non_clear":
            expected = strip.count("d") + strip.count("s")
        elif kind == "share_pct":
            expected = round(((strip.count("d") + strip.count("s")) / n_h) * 100.0, 1)
        elif kind == "first_non_clear_utc":
            idx = next((i for i, ch in enumerate(strip) if ch in ("d", "s")), None)
            expected = doc["hours"][idx] if idx is not None else ""
        else:
            raise AssertionError(f"Unknown hist_airport kind {kind!r}")
        if expected != val:
            raise AssertionError(f"Trace {eid!r} {code}.{kind} mismatch: {val!r} != {expected!r}")
    elif op == "hist_tick":
        n_h = len(doc.get("hours") or [])
        if not (0 <= int(val) <= n_h):
            raise AssertionError(f"Trace {eid!r} tick {val!r} outside 0..{n_h}")
    elif op == "hist_clear_share":
        if val != 0.0:
            raise AssertionError(f"Trace {eid!r} expected 0.0 clear share, got {val!r}")
    else:
        raise AssertionError(f"Unknown trace op {op!r} on {eid!r}")


def validate_story_trace(
    html_path: Path,
    *,
    repo_root: Path = ROOT,
    file_overrides: dict[str, Path] | None = None,
) -> dict:
    """Validate that EVERY number/date/offset in <main> is traced AND matches its underlying JSON file."""
    raw_html = html_path.read_text(encoding="utf-8")
    m_trace = re.search(r'<script type="application/json" id="trace">(.*?)</script>', raw_html, re.S)
    if not m_trace:
        raise AssertionError(f"Missing #trace JSON script in {html_path}")
    trace = json.loads(m_trace.group(1))
    entries = trace.get("entries") or {}
    if not entries:
        raise AssertionError("Trace entries dict is empty")

    # Load all referenced JSON files and verify every entry against disk
    overrides = file_overrides or {}
    loaded: dict[str, dict] = {}
    for eid, entry in entries.items():
        rel = entry.get("file")
        if rel and rel not in loaded:
            fpath = overrides.get(rel) or (repo_root / rel)
            if not fpath.is_file() and rel.startswith("readings/"):
                fpath = repo_root / "data" / rel.split("/", 1)[1]  # site keeps FAA summaries under data/
            if not fpath.is_file():
                raise AssertionError(f"Referenced trace file missing: {fpath}")
            loaded[rel] = json.loads(fpath.read_text(encoding="utf-8"))
        sf = (entry.get("args") or {}).get("state_file")
        if sf and sf not in loaded:
            spath = overrides.get(sf) or (repo_root / sf)
            if spath.is_file():
                loaded[sf] = json.loads(spath.read_text(encoding="utf-8"))
        _verify_trace_entry(eid, entry, loaded)

    # Extract rendered text + SVG <text>/<title>/<desc> + aria-label inside <main>
    m_main = re.search(r"<main\b[^>]*>(.*?)</main>", raw_html, re.S)
    if not m_main:
        raise AssertionError("Missing <main> element")
    main_html = m_main.group(1)
    main_clean = re.sub(r"<script.*?</script>|<style.*?</style>|<!--.*?-->", " ", main_html, flags=re.S)
    visible_text = html_lib.unescape(re.sub(r"<[^>]+>", " ", main_clean))
    aria_texts = [html_lib.unescape(x) for x in re.findall(r'aria-label="([^"]+)"', main_clean)]
    combined = visible_text + " " + " ".join(aria_texts)

    # Build lookup sets ONLY from entries that just passed _verify_trace_entry!
    traced_iso_ts = {
        str(e["value"])
        for e in entries.values()
        if e.get("op") in ("timestamp_view", "hist_airport") and isinstance(e.get("value"), str) and "T" in e["value"]
    }
    traced_dates = {
        str(e["value"])
        for e in entries.values()
        if e.get("op") == "corridor_date"
    }
    # Also allow dates derived from verified timestamp_view entries
    for iso in traced_iso_ts:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        traced_dates.add(dt.date().isoformat())
        traced_dates.add(dt.astimezone(ET_ZONE).date().isoformat())

    traced_offsets = {e["rendered"] for e in entries.values() if e.get("op") == "corridor_offset"}
    traced_rendered_nums = set()
    for e in entries.values():
        r = str(e.get("rendered") or "")
        traced_rendered_nums.add(r)
        if r.endswith("M"):
            traced_rendered_nums.add(r[:-1])

    # 1) Match ISO UTC timestamps (e.g. 2026-11-19T09:30:12Z or 2026-11-16T19:00Z)
    def _consume_iso_ts(match: re.Match[str]) -> str:
        tok = match.group(0)
        if tok not in traced_iso_ts:
            raise AssertionError(f"Rendered ISO timestamp {tok!r} is not in #trace")
        return " "

    work = re.sub(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?Z\b", _consume_iso_ts, combined)

    # 2) Match ISO dates (e.g. 2026-11-17)
    def _consume_iso_date(match: re.Match[str]) -> str:
        tok = match.group(0)
        if tok not in traced_dates:
            raise AssertionError(f"Rendered ISO date {tok!r} is not in #trace")
        return " "

    work = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", _consume_iso_date, work)

    # 3) Match human Month Day[, Year] (e.g. "Nov 17, 2026", "Nov 17", "NOV 17, 2026")
    month_pat = r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})(?:,\s*(\d{4}))?\b"

    def _consume_human_date(match: re.Match[str]) -> str:
        full = match.group(0)
        m_name = full[:3].capitalize()
        m_num = MONTHS.index(m_name) + 1
        day = int(match.group(1))
        yr_str = match.group(2)
        if yr_str:
            iso = f"{int(yr_str):04d}-{m_num:02d}-{day:02d}"
            if iso not in traced_dates:
                raise AssertionError(f"Rendered date {full!r} ({iso}) is not in #trace")
        else:
            if not any(d.endswith(f"-{m_num:02d}-{day:02d}") for d in traced_dates):
                raise AssertionError(f"Rendered date {full!r} is not in #trace")
        return " "

    work = re.sub(month_pat, _consume_human_date, work, flags=re.IGNORECASE)

    # 4) Match clock times (e.g. "7:00 PM EST", "2:00 PM", "9:30 AM") -> verify against traced timestamps
    valid_clocks = set()
    for iso in traced_iso_ts:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        for z in (ET_ZONE, ZoneInfo("America/Chicago"), ZoneInfo("America/Denver"), ZoneInfo("America/Phoenix"), ZoneInfo("America/Los_Angeles"), timezone.utc):
            loc = dt.astimezone(z)
            hr = loc.hour % 12 or 12
            ampm = "AM" if loc.hour < 12 else "PM"
            valid_clocks.add(f"{hr}:{loc.minute:02d} {ampm}")

    def _consume_clock(match: re.Match[str]) -> str:
        clk = f"{int(match.group(1))}:{match.group(2)} {match.group(3).upper()}"
        if clk not in valid_clocks:
            raise AssertionError(f"Rendered clock time {clk!r} does not match any traced timestamp")
        return " "

    work = re.sub(r"\b(\d{1,2}):(\d{2})\s*(AM|PM)\b", _consume_clock, work, flags=re.IGNORECASE)

    # 5) Match T±k corridor offsets
    def _consume_offset(match: re.Match[str]) -> str:
        tok = match.group(0)
        if tok not in traced_offsets:
            raise AssertionError(f"Rendered offset {tok!r} is not in #trace")
        return " "

    work = re.sub(r"\bT(?:0|[+-]\d+)\b", _consume_offset, work)

    # 6) Every remaining numeric token (integers, decimals, signed %, M-abbreviated floats) MUST be in traced_rendered_nums
    # Also allow "72h" -> "72"
    work = re.sub(r"(\d+)h\b", r"\1", work)
    num_tokens = re.findall(r"[+-]?\d(?:[\d,]*\d)?(?:\.\d+)?%?", work)
    missing = [tok for tok in num_tokens if tok not in traced_rendered_nums]
    if missing:
        raise AssertionError(f"Rendered numeric tokens missing from #trace: {sorted(set(missing))}")

    return trace



def _shift_end_day(text: str) -> str:
    """'seven days ending Tue Nov 17, 2026' -> same text with the end day one earlier (a wrong date on purpose)."""
    m = re.search(r"([A-Za-z]{3}) ([A-Za-z]{3}) (\d+), (\d{4})", text)
    d = datetime.strptime(f"{m.group(2)} {m.group(3)} {m.group(4)}", "%b %d %Y").date() - timedelta(days=1)
    return text.replace(m.group(0), f"{d:%a} {d:%b} {d.day}, {d.year}")


def _shift_start_day(text: str) -> str:
    """'Flyers in 7 days (Nov 11 to Nov 17, 2026, TSA)' -> start one day earlier (a wrong range on purpose)."""
    m = re.search(r"\(([A-Za-z]{3}) (\d+) to", text)
    d = datetime.strptime(f"{m.group(1)} {m.group(2)} 2026", "%b %d %Y").date() - timedelta(days=1)
    return text.replace(m.group(0), f"({d:%b} {d.day} to")


class TestStoryTraceAndBuilder(unittest.TestCase):
    def test_built_story_page_trace_and_structure(self) -> None:
        story_html = ROOT / "stories" / "thanksgiving" / "index.html"
        story_css = ROOT / "stories" / "thanksgiving" / "story.css"
        story_js = ROOT / "stories" / "thanksgiving" / "story.js"
        self.assertTrue(story_html.is_file(), "Run tools/build_stories.py before tests")
        self.assertTrue(story_css.is_file())
        self.assertTrue(story_js.is_file())

        text = story_html.read_text(encoding="utf-8")
        # Validate trace completeness and exact data agreement against real data/tsa-history.json + readings/
        trace = validate_story_trace(story_html, repo_root=ROOT)
        self.assertGreater(len(trace["entries"]), 100)

        # Single H1, landmarks, accessible tables, early FAA label, no analytics/3rd party requests
        self.assertEqual(len(re.findall(r"<h1\b", text)), 1)
        self.assertIn('<main id="main-content"', text)
        self.assertIn("<nav ", text)
        self.assertIn("<footer ", text)
        self.assertIn("early", text.lower())
        self.assertEqual(text.count("<details class=\"story-table-details\">"), 2)
        self.assertIn("Show table: daily TSA checkpoint counts", text)
        self.assertIn("Show table: FAA hourly readings by airport", text)
        self.assertIn('id="rush-svg-desktop"', text)
        self.assertIn('id="rush-svg-mobile"', text)
        self.assertIn('id="delay-svg-desktop"', text)
        self.assertIn('id="delay-svg-mobile"', text)
        self.assertNotIn("count.js", text)

        # No third-party requests in scripts, stylesheets, or images
        for src in re.findall(r'<script[^>]+src="([^"]+)"', text):
            self.assertIn((urlparse(src).hostname or "").lower(), OWN_HOSTS, src)
        for href in re.findall(r'<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"', text):
            self.assertIn((urlparse(href).hostname or "").lower(), OWN_HOSTS, href)

        # Total story weight well under 1 MB
        total_bytes = story_html.stat().st_size + story_css.stat().st_size + story_js.stat().st_size
        self.assertLess(total_bytes, 1_000_000)

        # CSS respects reduced motion & uses tokens
        css_text = story_css.read_text(encoding="utf-8")
        self.assertIn("prefers-reduced-motion: reduce", css_text)
        self.assertIn("--story-sweep-ms: 0ms", css_text)
        self.assertNotRegex(css_text, r"#[0-9a-fA-F]{3,6}\b")

    def test_fixture_builds_across_holiday_stages_no_network(self) -> None:
        stages = [
            ("pre", FIX / "tsa-story-2026.html", "2026-11-19T12:00:00Z", "seven days ending Tue Nov 17, 2026 versus the same seven days in 2025"),
            ("mid", FIX / "story-stages" / "tsa-2026-mid.html", "2026-11-26T12:00:00Z", "Early Thanksgiving week reading:"),
            ("full", FIX / "story-stages" / "tsa-2026-full.html", "2026-12-01T12:00:00Z", "Thanksgiving week screened"),
        ]
        for label, html_2026, now_iso, expected_h1 in stages:
            with self.subTest(stage=label):
                with tempfile.TemporaryDirectory() as tmp:
                    t = Path(tmp)
                    fx_dir = t / "fx"
                    fx_dir.mkdir()
                    shutil.copy2(FIX / "tsa-story-2024.html", fx_dir / "tsa-2024.html")
                    shutil.copy2(FIX / "tsa-story-2025.html", fx_dir / "tsa-2025.html")
                    shutil.copy2(html_2026, fx_dir / "tsa-2026.html")

                    data_dir = t / "data"
                    readings_dir = t / "readings"
                    out_dir = t / "stories"
                    data_dir.mkdir()
                    readings_dir.mkdir()
                    shutil.copy2(FIX / "history-summary-story.json", readings_dir / "history-summary.json")
                    shutil.copy2(ROOT / "data" / "state.json", readings_dir / "state.json")

                    bs.build_all(
                        data_dir=data_dir,
                        readings_dir=readings_dir,
                        out_dir=out_dir,
                        sitemap_path=None,
                        now=datetime.fromisoformat(now_iso.replace("Z", "+00:00")),
                        fixture_dir=fx_dir,
                    )
                    built = out_dir / "thanksgiving" / "index.html"
                    page = built.read_text(encoding="utf-8")
                    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S).group(1)
                    self.assertIn(expected_h1, h1)
                    if label == "mid":
                        self.assertIn("early", h1.lower())

                    # Map relative paths inside #trace to our temp dir
                    overrides = {
                        "tsa-history.json": data_dir / "tsa-history.json",
                        "data/tsa-history.json": data_dir / "tsa-history.json",
                        "history-summary.json": readings_dir / "history-summary.json",
                        "readings/history-summary.json": readings_dir / "history-summary.json",
                        "state.json": readings_dir / "state.json",
                        "readings/state.json": readings_dir / "state.json",
                    }
                    # Normalize trace file labels to actual paths in temp test
                    trace_m = re.search(r'<script type="application/json" id="trace">(.*?)</script>', page, re.S)
                    trace_obj = json.loads(trace_m.group(1))
                    for e in trace_obj["entries"].values():
                        overrides.setdefault(e["file"], data_dir / "tsa-history.json" if "tsa" in e["file"] else (readings_dir / "history-summary.json" if "history" in e["file"] else readings_dir / "state.json"))
                        sf = (e.get("args") or {}).get("state_file")
                        if sf:
                            overrides.setdefault(sf, readings_dir / "state.json")
                    validate_story_trace(built, repo_root=t, file_overrides=overrides)
                    stage_tsa = json.loads((data_dir / "tsa-history.json").read_text(encoding="utf-8"))
                    stage_faa = json.loads((readings_dir / "history-summary.json").read_text(encoding="utf-8"))
                    stage_ty = bs._target_thanksgiving_year(stage_tsa, datetime.fromisoformat(now_iso.replace("Z", "+00:00")))
                    bs.verify_story_date_windows(page, tsa=stage_tsa, faa_hist=stage_faa, target_year=stage_ty)

    def test_fails_when_rendered_number_missing_from_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            data_dir = t / "data"
            readings_dir = t / "readings"
            out_dir = t / "stories"
            fx_dir = t / "fx"
            for d in (data_dir, readings_dir, fx_dir):
                d.mkdir()
            for y in ("2024", "2025", "2026"):
                shutil.copy2(FIX / f"tsa-story-{y}.html", fx_dir / f"tsa-{y}.html")
            shutil.copy2(FIX / "history-summary-story.json", readings_dir / "history-summary.json")
            shutil.copy2(ROOT / "data" / "state.json", readings_dir / "state.json")

            bs.build_all(
                data_dir=data_dir,
                readings_dir=readings_dir,
                out_dir=out_dir,
                sitemap_path=None,
                now=datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc),
                fixture_dir=fx_dir,
            )
            built = out_dir / "thanksgiving" / "index.html"
            orig = built.read_text(encoding="utf-8")
            overrides = {
                "tsa-history.json": data_dir / "tsa-history.json",
                "history-summary.json": readings_dir / "history-summary.json",
                "state.json": readings_dir / "state.json",
            }
            trace_obj = json.loads(re.search(r'<script type="application/json" id="trace">(.*?)</script>', orig, re.S).group(1))
            for e in trace_obj["entries"].values():
                overrides.setdefault(e["file"], data_dir / "tsa-history.json" if "tsa" in e["file"] else readings_dir / "history-summary.json")

            for bad_snippet in (
                "<p>Invented forecast: 9,876,543 travelers</p>",
                '<text class="sv-label" x="10" y="10">41.7%</text>',
                '<td class="num">123,456</td>',
            ):
                with self.subTest(bad=bad_snippet):
                    tampered = orig.replace("</main>", bad_snippet + "</main>", 1)
                    built.write_text(tampered, encoding="utf-8")
                    with self.assertRaises(AssertionError):
                        validate_story_trace(built, repo_root=t, file_overrides=overrides)

    def test_fails_when_trace_value_mismatches_data_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            data_dir = t / "data"
            readings_dir = t / "readings"
            out_dir = t / "stories"
            fx_dir = t / "fx"
            for d in (data_dir, readings_dir, fx_dir):
                d.mkdir()
            for y in ("2024", "2025", "2026"):
                shutil.copy2(FIX / f"tsa-story-{y}.html", fx_dir / f"tsa-{y}.html")
            shutil.copy2(FIX / "history-summary-story.json", readings_dir / "history-summary.json")
            shutil.copy2(ROOT / "data" / "state.json", readings_dir / "state.json")

            bs.build_all(
                data_dir=data_dir,
                readings_dir=readings_dir,
                out_dir=out_dir,
                sitemap_path=None,
                now=datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc),
                fixture_dir=fx_dir,
            )
            built = out_dir / "thanksgiving" / "index.html"
            tsa_p = data_dir / "tsa-history.json"
            tsa_obj = json.loads(tsa_p.read_text(encoding="utf-8"))
            tsa_obj["days"]["2026-11-17"] += 1  # mutate data file without rebuilding HTML
            tsa_p.write_text(json.dumps(tsa_obj), encoding="utf-8")

            overrides = {}
            trace_obj = json.loads(re.search(r'<script type="application/json" id="trace">(.*?)</script>', built.read_text(encoding="utf-8"), re.S).group(1))
            for e in trace_obj["entries"].values():
                overrides.setdefault(e["file"], tsa_p if "tsa" in e["file"] else (readings_dir / "history-summary.json" if "history" in e["file"] else readings_dir / "state.json"))

            with self.assertRaises(AssertionError):
                validate_story_trace(built, repo_root=t, file_overrides=overrides)

    def test_workflow_allowlist_home_link_and_check_site_wiring(self) -> None:
        yml = (ROOT / ".github" / "workflows" / "status.yml").read_text(encoding="utf-8")
        self.assertIn("tools/build_stories.py", yml)
        self.assertIn("data/tsa-history.json", yml)
        self.assertIn("_site/stories/thanksgiving/index.html", yml)
        self.assertIn("cp stories/thanksgiving/index.html stories/thanksgiving/story.css stories/thanksgiving/story.js _site/stories/thanksgiving/", yml)
        self.assertRegex(yml, r"for f in [^;]*\btsa-history\.json\b")
        self.assertLess(yml.index("tools/build_stories.py"), yml.index("Prepare _site directory"))

        home = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="/stories/thanksgiving"', home)
        sitemap = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
        self.assertIn("https://www.airtraveldesklive.com/stories/thanksgiving", sitemap)

        # check_site.py must catch broken /stories/ paths in JS as well as HTML
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            (site / "index.html").write_text('<a href="/stories/thanksgiving">Story</a><script src="/app.js"></script>', encoding="utf-8")
            (site / "stories" / "thanksgiving").mkdir(parents=True)
            (site / "stories" / "thanksgiving" / "index.html").write_text('<a href="/">Home</a>', encoding="utf-8")
            (site / "app.js").write_text('const u = "/stories/thanksgiving";', encoding="utf-8")
            self.assertEqual(check_site.broken_references(site), [])
            (site / "app.js").write_text('const bad = "/stories/missing";', encoding="utf-8")
            self.assertEqual(check_site.broken_references(site), [("app.js", "/stories/missing")])

    def test_round2_critique_invariants(self) -> None:
        story_html = ROOT / "stories" / "thanksgiving" / "index.html"
        story_css = ROOT / "stories" / "thanksgiving" / "story.css"
        text = story_html.read_text(encoding="utf-8")
        css_text = story_css.read_text(encoding="utf-8")

        # Scoped H1 (<=160 chars) while <title> and meta carry the full phrasing
        h1 = html_lib.unescape(re.search(r'<h1[^>]*>(.*?)</h1>', text, re.S).group(1)).strip()
        title = html_lib.unescape(re.search(r'<title>(.*?)</title>', text, re.S).group(1)).strip()
        meta_desc = html_lib.unescape(re.search(r'<meta name="description" content="([^"]+)"', text).group(1)).strip()
        self.assertLessEqual(len(h1), 160, f"H1 too long: {h1!r}")
        self.assertGreater(len(title), len(h1))
        tsa_latest = date.fromisoformat(json.loads((ROOT / "data" / "tsa-history.json").read_text(encoding="utf-8"))["latest_date"])
        expect_end = f"seven days ending {tsa_latest:%a} {tsa_latest:%b} {tsa_latest.day}, {tsa_latest.year}"
        self.assertRegex(h1, r"\d+(?:\.\d+)?%")
        self.assertIn(expect_end, h1)
        self.assertIn("same seven days in 2025", h1)
        self.assertIn("3.13M", h1)
        self.assertIn("Nov 30, 2025", h1)
        self.assertRegex(meta_desc, r"\d+(?:\.\d+)?%")

        # Chart stage precedes callout steps in DOM for mobile chart-first flow
        self.assertLess(text.index('<div class="story-stage">'), text.index('<ol class="story-steps"'))

        # Plain-language interaction guide lines and live slider outputs
        self.assertEqual(text.count('class="story-chart-guide"'), 2)
        self.assertIn('id="rush-scrub-val"', text)
        self.assertIn('id="delay-scrub-val"', text)
        self.assertIn('class="story-segmented"', text)

        # Mobile FAA chart retains hourly timeline cells and interactive cursor
        m2_match = re.search(r'<svg id="delay-svg-mobile".*?</svg>', text, re.S)
        self.assertIsNotNone(m2_match)
        m2_svg = m2_match.group(0)
        self.assertIn('id="delay-m-hour-cursor"', m2_svg)
        self.assertIn('class="sv-bar-delay"', m2_svg)
        self.assertIn('class="sv-bar-stop"', m2_svg)

        # No SVG text size below 12px and no hex colors in story.css
        svg_font_sizes = [float(x) for x in re.findall(r'\.svg-(?:mobile|desktop)[^{]*\{[^}]*font-size:\s*([\d.]+)px', css_text, re.S)]
        self.assertTrue(svg_font_sizes)
        self.assertTrue(all(sz >= 12.0 for sz in svg_font_sizes), svg_font_sizes)
        self.assertNotRegex(css_text, r"#[0-9a-fA-F]{3,6}\b")

    def test_round3_per_element_overflow_and_critique_invariants(self) -> None:
        story_html = ROOT / "stories" / "thanksgiving" / "index.html"
        story_css = ROOT / "stories" / "thanksgiving" / "story.css"
        text = story_html.read_text(encoding="utf-8")
        css_text = story_css.read_text(encoding="utf-8")

        # Root-relative assets work both with and without trailing slash
        self.assertIn('href="/tokens.css"', text)
        self.assertIn('href="/stories/thanksgiving/story.css"', text)
        self.assertIn('src="/stories/thanksgiving/story.js"', text)

        # Desktop hero right half (KPI ledger beside copy), plain traveler KPI copy, mobile stacked ledger labels
        self.assertNotIn('class="story-hero-latest"', text)
        self.assertIn("airports with delays in 72-hour FAA archive", text)
        self.assertIn('data-label="Licence"', text)
        self.assertIn('data-label="Fetched"', text)
        self.assertIn('Selected:', text)
        self.assertIn("@media (min-width: 600px)", css_text)
        self.assertIn("::-webkit-slider-thumb", css_text)
        self.assertIn("::-webkit-slider-runnable-track", css_text)
        self.assertNotRegex(css_text, r"#[0-9a-fA-F]{3,6}\b")

        # Per-element bounding-box & typography audit via Playwright (local route, zero network)
        pw_script = r'''
import json, mimetypes, sys
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

root = Path(sys.argv[1])
def handle_route(route):
    u = urlparse(route.request.url)
    if u.hostname != "atd.local":
        return route.abort()
    rel = u.path.lstrip("/")
    p = root / rel
    if p.is_dir():
        p = p / "index.html"
    if not p.is_file() and (root / rel / "index.html").is_file():
        p = root / rel / "index.html"
    if not p.is_file() and (root / (rel + ".html")).is_file():
        p = root / (rel + ".html")
    if not p.is_file():
        return route.fulfill(status=404, body="")
    ctype, _ = mimetypes.guess_type(str(p))
    if p.suffix == ".woff2":
        ctype = "font/woff2"
    route.fulfill(status=200, content_type=ctype or "application/octet-stream", body=p.read_bytes())

AUDIT_JS = """(expectedVw) => {
    const vw = window.innerWidth;
    const docSW = document.documentElement.scrollWidth;
    const bodySW = document.body.scrollWidth;
    const violations = [];
    let checked = 0;
    let maxRight = 0;
    for (const el of document.querySelectorAll("*")) {
        const st = getComputedStyle(el);
        if (st.display === "none" || st.visibility === "hidden") continue;
        const r = el.getBoundingClientRect();
        if (r.width === 0 && r.height === 0) continue;
        if (el.classList.contains("skip-link") && document.activeElement !== el) continue;
        let p = el.parentElement, inScroller = false;
        while (p && p !== document.body && p !== document.documentElement) {
            const pst = getComputedStyle(p);
            if (pst.overflowX === "auto" || pst.overflowX === "scroll") { inScroller = true; break; }
            p = p.parentElement;
        }
        if (inScroller) continue;
        checked++;
        const isChrome = (el.tagName === "HTML" || el.tagName === "BODY" || el.classList.contains("site-header") || el.classList.contains("site-footer") || el.classList.contains("watch-drawer"));
        const rightLimit = isChrome ? vw : (vw - 16);
        const leftLimit = isChrome ? 0 : 16;
        if (!isChrome && r.right > maxRight) maxRight = r.right;
        if (r.right > rightLimit + 0.5 || r.left < leftLimit - 0.5) {
            violations.push({
                tag: el.tagName, cls: String(el.className), id: el.id,
                left: Math.round(r.left * 10) / 10, right: Math.round(r.right * 10) / 10,
                limit: rightLimit, text: (el.textContent || "").trim().slice(0, 40)
            });
        }
    }
    const fs = sel => {
        const n = document.querySelector(sel);
        return n ? parseFloat(getComputedStyle(n).fontSize) : null;
    };
    const svgMob = document.querySelector("#rush-svg-mobile");
    const stepsEl = document.querySelector(".story-steps");
    const cmpBtns = Array.from(document.querySelectorAll("[data-cmp-year]")).map(b => {
        const br = b.getBoundingClientRect();
        return { text: b.textContent.trim(), top: Math.round(br.top), height: Math.round(br.height), right: Math.round(br.right), scrollW: b.scrollWidth, clientW: b.clientWidth };
    });
    const metricsLefts = Array.from(document.querySelectorAll(".story-metric")).map(m => Math.round(m.getBoundingClientRect().left));
    const heroCopy = document.querySelector(".story-hero-copy")?.getBoundingClientRect();
    const heroMetrics = document.querySelector(".story-metrics")?.getBoundingClientRect();

    // Round 4 touch-target check across all visible interactive controls
    const smallTargets = [];
    for (const el of document.querySelectorAll("a, button, input, summary, [role='button']")) {
        const st = getComputedStyle(el);
        if (st.display === "none" || st.visibility === "hidden") continue;
        const r = el.getBoundingClientRect();
        if (r.width === 0 && r.height === 0) continue;
        if (el.classList.contains("skip-link")) continue;
        if (r.height < 43.5) {
            smallTargets.push({
                tag: el.tagName, cls: String(el.className), id: el.id,
                h: Math.round(r.height * 10) / 10, w: Math.round(r.width * 10) / 10,
                text: (el.textContent || el.getAttribute("aria-label") || "").trim().slice(0, 30)
            });
        }
    }
    const aboutNav = Array.from(document.querySelectorAll(".header-nav a")).find(a => a.textContent.trim() === "About");
    const aboutRect = aboutNav ? aboutNav.getBoundingClientRect() : null;
    const hdrLinks = Array.from(document.querySelectorAll(".header-nav a")).map(a => {
        const r = a.getBoundingClientRect();
        return {
            text: a.textContent.trim(),
            left: Math.round(r.left * 10) / 10,
            right: Math.round(r.right * 10) / 10,
            w: Math.round(r.width * 10) / 10,
            h: Math.round(r.height * 10) / 10,
        };
    });

    // Check every visible SVG for any overlapping <text> labels
    const svgTextOverlaps = [];
    for (const svg of document.querySelectorAll("svg.story-svg")) {
        if (getComputedStyle(svg).display === "none") continue;
        const sr = svg.getBoundingClientRect();
        const texts = Array.from(svg.querySelectorAll("text")).filter(t => {
            if (!t.textContent.trim()) return false;
            let g = t.closest("g");
            while (g && g !== svg) {
                if (g.getAttribute("display") === "none") return false;
                g = g.parentElement;
            }
            return true;
        }).map(t => {
            const r = t.getBoundingClientRect();
            return {
                text: t.textContent.trim(),
                left: r.left - sr.left, right: r.right - sr.left,
                top: r.top - sr.top, bottom: r.bottom - sr.top,
            };
        });
        for (let i = 0; i < texts.length; i++) {
            for (let j = i + 1; j < texts.length; j++) {
                const a = texts[i], b = texts[j];
                const dx = Math.min(a.right, b.right) - Math.max(a.left, b.left);
                const dy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
                if (dx > 0.5 && dy > 0.5) {
                    svgTextOverlaps.push({ svg: svg.id, a: a.text, b: b.text, dx: Math.round(dx * 10) / 10, dy: Math.round(dy * 10) / 10 });
                }
            }
        }
    }

    // Minimum font sizes across visible text nodes & SVG <text>
    const smallTexts = [];
    const minReq = vw >= 1000 ? 15.0 : 14.0;
    for (const el of document.querySelectorAll("main p, main li, main span, main label, main output, main button, main summary, main caption, main th, main td, main a, .header-nav a, .site-footer p, .site-footer a, svg text")) {
        const st = getComputedStyle(el);
        if (st.display === "none" || st.visibility === "hidden") continue;
        const r = el.getBoundingClientRect();
        if (r.width === 0 && r.height === 0) continue;
        if (el.closest("svg") && getComputedStyle(el.closest("svg")).display === "none") continue;
        const sz = parseFloat(st.fontSize);
        if (sz < minReq - 0.05) {
            smallTexts.push({ tag: el.tagName, cls: String(el.className), fs: sz, text: (el.textContent || "").trim().slice(0, 30) });
        }
    }

    // Selected badge contrast computation
    const parseRgb = s => {
        const m = String(s).match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
        return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : [0, 0, 0];
    };
    const relLum = rgb => {
        const lin = c => { const v = c / 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
        return 0.2126 * lin(rgb[0]) + 0.7152 * lin(rgb[1]) + 0.0722 * lin(rgb[2]);
    };
    const contrast = (fg, bg) => {
        const l1 = relLum(parseRgb(fg)), l2 = relLum(parseRgb(bg));
        return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    };
    const scrubEl = document.querySelector("#rush-scrub-val");
    const scrubSt = scrubEl ? getComputedStyle(scrubEl) : null;
    const scrubContrast = scrubSt ? Math.round(contrast(scrubSt.color, scrubSt.backgroundColor) * 100) / 100 : null;

    // Phone FAA SVG checks
    const delayMob = document.querySelector("#delay-svg-mobile");
    let delayMobInfo = null;
    if (delayMob && getComputedStyle(delayMob).display !== "none") {
        const rows = Array.from(delayMob.querySelectorAll(".sv-ap-hit")).map(g => {
            const cEl = g.querySelector(".sv-code");
            const nEl = g.querySelector(".sv-ap-name");
            const cBox = cEl ? cEl.getBoundingClientRect() : null;
            const nBox = nEl ? nEl.getBoundingClientRect() : null;
            return {
                code: cEl?.textContent?.trim() || "",
                name: nEl?.textContent?.trim() || "",
                codeBottom: cBox ? Math.round(cBox.bottom * 10) / 10 : null,
                nameTop: nBox ? Math.round(nBox.top * 10) / 10 : null,
            };
        });
        const badNamePlacement = rows.filter(r => r.codeBottom == null || r.nameTop == null || r.nameTop < r.codeBottom - 2.0);
        const ticks = Array.from(delayMob.querySelectorAll(".sv-date-tick")).map(t => {
            const b = t.getBoundingClientRect();
            return { text: t.textContent.trim(), left: b.left, right: b.right };
        });
        const tickGaps = [];
        for (let i = 1; i < ticks.length; i++) {
            tickGaps.push(Math.round((ticks[i].left - ticks[i - 1].right) * 10) / 10);
        }
        const cells = Array.from(delayMob.querySelectorAll(".sv-hr-cell"));
        const cellWidths = cells.map(c => Number(c.getAttribute("width")) || 0);
        const sfoCells = Array.from(delayMob.querySelectorAll("[data-ap-code='SFO'] .sv-hr-cell")).map(c => ({
            x: Number(c.getAttribute("x")), w: Number(c.getAttribute("width"))
        })).sort((a, b) => a.x - b.x);
        const sfoGaps = [];
        for (let i = 1; i < sfoCells.length; i++) {
            if (sfoCells[i].x - sfoCells[i - 1].x < 6.0) {
                sfoGaps.push(Math.round((sfoCells[i].x - (sfoCells[i - 1].x + sfoCells[i - 1].w)) * 100) / 100);
            }
        }
        delayMobInfo = {
            rowCount: rows.length,
            missingNames: rows.filter(r => !r.code || !r.name),
            badNamePlacement,
            ticks, tickGaps,
            minCellW: cellWidths.length ? Math.min(...cellWidths) : 0,
            minAdjGap: sfoGaps.length ? Math.min(...sfoGaps) : 0,
        };
    }

    return {
        expectedVw, vw, docSW, bodySW, checked,
        maxRight: Math.round(maxRight * 10) / 10,
        violations: violations.slice(0, 20),
        violationCount: violations.length,
        chartTopY: svgMob ? Math.round(svgMob.getBoundingClientRect().top) : null,
        chartBotY: svgMob ? Math.round(svgMob.getBoundingClientRect().bottom) : null,
        stepsTopY: stepsEl ? Math.round(stepsEl.getBoundingClientRect().top) : null,
        cmpBtns, metricsLefts,
        heroCopyRight: heroCopy ? Math.round(heroCopy.right) : null,
        heroMetricsLeft: heroMetrics ? Math.round(heroMetrics.left) : null,
        heroMetricsWidth: heroMetrics ? Math.round(heroMetrics.width) : null,
        smallTargets,
        hdrLinks,
        svgTextOverlaps,
        aboutRight: aboutRect ? Math.round(aboutRect.right * 10) / 10 : null,
        aboutHeight: aboutRect ? Math.round(aboutRect.height * 10) / 10 : null,
        smallTexts: smallTexts.slice(0, 20),
        smallTextCount: smallTexts.length,
        scrubContrast,
        delayMobInfo,
        fonts: {
            crumb: fs(".crumb"), kicker: fs(".story-kicker"), dek: fs(".story-dek"),
            mLabel: fs(".story-metric-label"), mSub: fs(".story-metric-sub"),
            ro: fs(".story-readout-stat"), roSub: fs(".story-readout-stat span"),
            cmpBtn: fs("[data-cmp-year]"), scrubVal: fs("#rush-scrub-val"),
        },
        scrubVal: document.querySelector("#rush-scrub-val")?.textContent || "",
        delayVal: document.querySelector("#delay-scrub-val")?.textContent || "",
    };
}"""

results = {}
with sync_playwright() as p:
    browser = p.chromium.launch()
    # 1) Mobile 375x812 checks across trailing-slash, non-slash, touch device, details open, interactive, light theme
    for key, path, mob, state, scheme in [
        ("m_375_default", "/stories/thanksgiving/", False, "default", "dark"),
        ("m_375_touch", "/stories/thanksgiving/", True, "default", "dark"),
        ("m_375_noslash", "/stories/thanksgiving", False, "default", "dark"),
        ("m_375_interactive", "/stories/thanksgiving/", False, "interactive", "dark"),
        ("m_375_details_open", "/stories/thanksgiving/", False, "details", "dark"),
        ("m_375_light", "/stories/thanksgiving/", False, "default", "light"),
        ("m_375_index", "/stories/", False, "default", "dark"),
    ]:
        ctx = browser.new_context(viewport={"width": 375, "height": 812}, is_mobile=mob, color_scheme=scheme)
        ctx.route("**/*", handle_route)
        page = ctx.new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.on("requestfailed", lambda r: errs.append(r.url))
        page.goto(f"http://atd.local{path}", wait_until="networkidle")
        if state == "interactive":
            page.click('[data-cmp-year="2019"]')
            page.click('[data-delay-filter="stops"]')
            page.fill("#rush-scrub", "15")
            page.dispatch_event("#rush-scrub", "input")
            page.fill("#delay-scrub", "0")
            page.dispatch_event("#delay-scrub", "input")
        elif state == "details":
            page.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
        r = page.evaluate(AUDIT_JS, 375)
        r["errors"] = errs
        results[key] = r
        ctx.close()

    # 2) Desktop 1440x900 checks
    for key, path, state, scheme in [
        ("d_1440_default", "/stories/thanksgiving/", "default", "dark"),
        ("d_1440_interactive", "/stories/thanksgiving/", "interactive", "dark"),
        ("d_1440_details_open", "/stories/thanksgiving/", "details", "dark"),
        ("d_1440_light", "/stories/thanksgiving/", "default", "light"),
        ("d_1440_index", "/stories/", "default", "dark"),
    ]:
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme=scheme)
        ctx.route("**/*", handle_route)
        page = ctx.new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.on("requestfailed", lambda r: errs.append(r.url))
        page.goto(f"http://atd.local{path}", wait_until="networkidle")
        if state == "interactive":
            page.click('[data-cmp-year="2019"]')
            page.click('[data-delay-filter="stops"]')
        elif state == "details":
            page.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
        r = page.evaluate(AUDIT_JS, 1440)
        r["errors"] = errs
        results[key] = r
        ctx.close()

    browser.close()
print(json.dumps(results))
'''
        py_bin = sys.executable
        try:
            import playwright.sync_api  # noqa: F401
        except ImportError:
            alt = Path.home() / "factory-scratch" / "an2-venv" / "bin" / "python"
            if alt.is_file():
                py_bin = str(alt)
            else:
                self.skipTest("Playwright not installed in environment")

        proc = subprocess.run([py_bin, "-c", pw_script, str(ROOT)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        results = json.loads(proc.stdout)

        for key, res in results.items():
            with self.subTest(viewport=key):
                self.assertEqual(res["errors"], [], f"{key} errors: {res['errors']}")
                self.assertEqual(res["vw"], res["expectedVw"], key)
                self.assertLessEqual(res["docSW"], res["vw"], f"{key} docSW={res['docSW']} > {res['vw']}")
                self.assertLessEqual(res["bodySW"], res["vw"], f"{key} bodySW={res['bodySW']} > {res['vw']}")
                self.assertGreater(res["checked"], 50, key)
                self.assertEqual(res["violationCount"], 0, f"{key} overflow elements: {res['violations']}")
                self.assertLessEqual(res["maxRight"], res["vw"] - 16 + 0.5, key)
                self.assertEqual(res["smallTargets"], [], f"{key} targets < 44px: {res['smallTargets']}")
                self.assertEqual(res["smallTextCount"], 0, f"{key} small texts: {res['smallTexts']}")
                self.assertEqual(res["svgTextOverlaps"], [], f"{key} SVG text overlaps: {res['svgTextOverlaps']}")
                for hl in res["hdrLinks"]:
                    self.assertGreaterEqual(hl["h"], 44.0, f"{key} nav link height < 44: {hl}")
                    self.assertGreaterEqual(hl["w"], 44.0, f"{key} nav link width < 44: {hl}")
                    if res["vw"] == 375:
                        self.assertGreaterEqual(hl["left"], 15.5, f"{key} nav link left out of gutter: {hl}")
                        self.assertLessEqual(hl["right"], 359.5, f"{key} nav link right out of gutter: {hl}")

        m_def = results["m_375_default"]
        self.assertLess(m_def["chartTopY"], 1218, f"Mobile Chart 1 below 1.5 screens: {m_def['chartTopY']}")
        self.assertGreater(m_def["stepsTopY"], m_def["chartBotY"], "Mobile callouts must sit under Chart 1")
        self.assertTrue(all(x == 16 for x in m_def["metricsLefts"]), f"KPIs must stack single-column at 375: {m_def['metricsLefts']}")
        self.assertEqual(len({b["top"] for b in m_def["cmpBtns"]}), 1, f"Compare buttons should sit on 1 row: {m_def['cmpBtns']}")
        for b in m_def["cmpBtns"]:
            self.assertGreaterEqual(b["height"], 44, b)
            self.assertLessEqual(b["scrollW"], b["clientW"] + 1, f"Clipped button text: {b}")
            self.assertLessEqual(b["right"], 359, b)
        self.assertLessEqual(m_def["aboutRight"], 359.5, m_def["aboutRight"])
        self.assertGreaterEqual(m_def["aboutHeight"], 44.0, m_def["aboutHeight"])
        for fname, fval in m_def["fonts"].items():
            self.assertGreaterEqual(fval, 14.0, f"Mobile font {fname}={fval} < 14px")
        self.assertGreaterEqual(m_def["scrubContrast"], 7.0, m_def["scrubContrast"])
        self.assertGreaterEqual(results["m_375_light"]["scrubContrast"], 7.0, results["m_375_light"]["scrubContrast"])
        self.assertTrue(m_def["scrubVal"].startswith("Selected:"), m_def["scrubVal"])
        self.assertTrue(m_def["delayVal"].startswith("Selected:"), m_def["delayVal"])

        dmob = m_def["delayMobInfo"]
        self.assertIsNotNone(dmob)
        self.assertGreater(dmob["rowCount"], 10)
        self.assertEqual(dmob["missingNames"], [], f"Phone FAA chart missing names: {dmob['missingNames']}")
        self.assertEqual(dmob["badNamePlacement"], [], f"Phone FAA names not on own line: {dmob['badNamePlacement']}")
        self.assertTrue(all(g >= 25.0 for g in dmob["tickGaps"]), f"Phone FAA date ticks packed: {dmob['ticks']} gaps={dmob['tickGaps']}")
        self.assertGreaterEqual(dmob["minCellW"], 2.8, dmob)
        self.assertGreaterEqual(dmob["minAdjGap"], 1.0, dmob)

        d_def = results["d_1440_default"]
        self.assertGreater(d_def["heroMetricsWidth"], 400, "Desktop hero right half must render visible KPI ledger")
        self.assertGreaterEqual(d_def["heroMetricsLeft"], d_def["heroCopyRight"], "Desktop hero KPI ledger must sit beside copy")
        for fname, fval in d_def["fonts"].items():
            self.assertGreaterEqual(fval, 15.0, f"Desktop font {fname}={fval} < 15px")
        self.assertGreaterEqual(d_def["scrubContrast"], 7.0, d_def["scrubContrast"])
        self.assertGreaterEqual(results["d_1440_light"]["scrubContrast"], 7.0, results["d_1440_light"]["scrubContrast"])

    def test_round4_number_check_and_repetition_cap(self) -> None:
        story_html = ROOT / "stories" / "thanksgiving" / "index.html"
        html_doc = story_html.read_text(encoding="utf-8")
        tsa = json.loads((ROOT / "data" / "tsa-history.json").read_text(encoding="utf-8"))
        faa_hist = json.loads((ROOT / "data" / "history-summary.json").read_text(encoding="utf-8"))
        faa_state = json.loads((ROOT / "data" / "state.json").read_text(encoding="utf-8"))
        faa = bs._merge_faa_rows(faa_hist, faa_state)
        target_year = bs._target_thanksgiving_year(tsa, datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc))

        # Passes cleanly on the built story
        bs.verify_story_numbers(html_doc, tsa=tsa, faa=faa, target_year=target_year)

        # Builder check MUST fail on mismatched vs baseline, inverted parenthetical, missing SNA closure tally, or bad check breakdown
        bad_cases = [
            ("<p>+4.4% vs 2025 (16,246,108)</p>", "ambiguous/inverted parenthetical"),
            ("<p>16,246,108 this year vs 15,000,000 in 2025 (+4.4%)</p>", "wrong 2025 baseline"),
            ("<p>16,246,108 this year vs 15,559,295 in 2025 (+9.9%)</p>", "wrong pct math"),
            ("<li><p>13 of 100</p><p>86 clear in all 72 hourly checks</p></li>", "FAA tally KPI 99 != 100"),
            ("<p>13 of 100 airports delayed; 86 clear in all 72 hourly checks</p>", "FAA tally sentence 99 != 100"),
            ("<p>35 non-clear hourly checks<span>31 delay, 5 stop/closure</span></p>", "check breakdown 36 != 35"),
        ]
        for snippet, label in bad_cases:
            with self.subTest(bad=label):
                tampered = html_doc.replace("</main>", f"{snippet}</main>", 1)
                with self.assertRaises(ValueError):
                    bs.verify_story_numbers(tampered, tsa=tsa, faa=faa, target_year=target_year)

        # Each key headline/metric number appears at most twice in <main> outside <svg> and <details>
        main_raw = re.search(r"<main\b[^>]*>(.*?)</main>", html_doc, re.S).group(1)
        main_no_tables = re.sub(r"<details.*?</details>|<svg.*?</svg>|<script.*?</script>", " ", main_raw, flags=re.S)
        prose = html_lib.unescape(re.sub(r"<[^>]+>", " ", main_no_tables))
        prose = re.sub(r"\s+", " ", prose)
        for tok in (
            "16,246,108", "15,559,295", "1,956,731", "1,816,617",
            "3,134,613", "+4.4%", "+7.7%", "3.13M",
            "13", "86", "100", "72", "35",
        ):
            cnt = len(re.findall(r"(?<![\d.,])" + re.escape(tok) + r"(?![\d.,%])", prose))
            self.assertLessEqual(cnt, 2, f"Token {tok!r} repeated {cnt} times (>2) in story prose/KPIs: {prose}")

    def test_round5_headline_scope_and_date_window_check(self) -> None:
        story_html = ROOT / "stories" / "thanksgiving" / "index.html"
        html_doc = story_html.read_text(encoding="utf-8")
        tsa = json.loads((ROOT / "data" / "tsa-history.json").read_text(encoding="utf-8"))
        faa_hist = json.loads((ROOT / "data" / "history-summary.json").read_text(encoding="utf-8"))
        target_year = bs._target_thanksgiving_year(tsa, datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc))

        # Passes cleanly on the built story
        bs.verify_story_date_windows(html_doc, tsa=tsa, faa_hist=faa_hist, target_year=target_year)

        # Builder check MUST reject inconsistent FAA windows, unscoped H1s, and wrong TSA ranges
        bad_replacements = [
            (
                "Early reading · 3-day FAA hourly archive",
                "Early reading · 3-day FAA archive (Nov 16 to Nov 18)",
                "FAA Nov 16 to Nov 18 mismatch",
            ),
            (
                "Early reading · 3-day FAA hourly archive",
                "Early reading · 3-day FAA archive (Nov 16-18)",
                "FAA Nov 16-18 hyphenated mismatch",
            ),
            (
                "Early reading · 3-day FAA hourly archive",
                "Early reading · 3-day FAA archive (Nov 16–18)",
                "FAA Nov 16–18 en-dash mismatch",
            ),
            (
                "Nov 15, 7:00 PM EST to Nov 18, 6:00 PM EST",
                "Nov 15, 8:00 PM EST to Nov 18, 6:00 PM EST",
                "FAA wrong timestamp start",
            ),
            (
                re.search(r"<h1\b[^>]*>.*?</h1>", html_doc, re.S).group(0),
                '<h1 class="story-title">2026 is +4.4% on 2025; the record remains 3.13M set on Nov 30, 2025</h1>',
                "Unscoped H1",
            ),
            (
                re.search(r"seven days ending [A-Za-z]{3} [A-Za-z]{3} \d+, 2026", html_doc).group(0),
                _shift_end_day(re.search(r"seven days ending [A-Za-z]{3} [A-Za-z]{3} \d+, 2026", html_doc).group(0)),
                "H1 wrong 7-day end date",
            ),
            (
                re.search(r"Flyers in 7 days \([A-Za-z]{3} \d+ to [A-Za-z]{3} \d+, 2026, TSA\)", html_doc).group(0),
                _shift_start_day(re.search(r"Flyers in 7 days \([A-Za-z]{3} \d+ to [A-Za-z]{3} \d+, 2026, TSA\)", html_doc).group(0)),
                "KPI 2 wrong 7-day range",
            ),
            (
                "16-day corridor (Nov 15 to Nov 30, 2026)",
                "16-day corridor (Nov 15 to Nov 29, 2026)",
                "Dek wrong corridor range",
            ),
        ]
        for old, new, label in bad_replacements:
            with self.subTest(bad=label):
                self.assertIn(old, html_doc, f"Missing target for negative test {label}")
                tampered = html_doc.replace(old, new, 1)
                with self.assertRaises(ValueError):
                    bs.verify_story_date_windows(tampered, tsa=tsa, faa_hist=faa_hist, target_year=target_year)



if __name__ == "__main__":
    unittest.main()
