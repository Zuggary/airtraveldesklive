"""AN11 item 1: hub weather now and for the next 3 hours (aviationweather.gov METAR and TAF, free, no key).

Writes <out>/wx.json. The flight category (VFR/MVFR/IFR/LIFR) is only used for the chip colour; the words
on screen are plain ("clear", "low clouds", "fog", "storms"). Times are the hub's own local am/pm, never Z.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from desk import demo, feeds, timefmt
from desk.airports import AIRPORTS, BUSIEST_100, TZ

SOURCE = "aviationweather.gov (METAR, TAF)"
BASE = "https://aviationweather.gov/api/data"
EVERY_SEC = 600.0
WINDOW_SEC = 3 * 3600
MAX_OBS_AGE = 90 * 60
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
CAT_RANK = {"VFR": 0, "MVFR": 1, "IFR": 2, "LIFR": 3}


# Stations outside the lower 48 do not use K + code. These are the ICAO ids for the Hawaii and Alaska airports on the list.
ICAO_OTHER = {"HNL": "PHNL", "OGG": "PHOG", "KOA": "PHKO", "LIH": "PHLI", "ANC": "PANC"}


def icao(code: str) -> Optional[str]:
    """'K' + code for the lower 48; the listed PH/PA id for Hawaii and Anchorage; None for anything else."""
    code = (code or "").upper()
    if code not in AIRPORTS:
        return None
    if code in ICAO_OTHER:
        return ICAO_OTHER[code]
    _, lat, lon = AIRPORTS[code]
    if not (24 <= lat <= 50 and -125 <= lon <= -66):
        return None
    return "K" + code


def wanted_codes(event_airports: list[str]) -> list[str]:
    out: list[str] = []
    for c in list(BUSIEST_100) + [str(a).upper() for a in event_airports]:
        if icao(c) and c not in out:
            out.append(c)
    return out


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _num(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"\d+(?:\.\d+)?", str(v))
    return float(m.group(0)) if m else None


def ceiling_ft(clouds: list[dict[str, Any]], vert_vis: Any = None) -> Optional[int]:
    """Lowest BKN/OVC/OVX layer (feet), or vertical visibility; None when no ceiling."""
    best: Optional[float] = None
    for c in clouds or []:
        if str(c.get("cover") or "").upper() in ("BKN", "OVC", "OVX") and c.get("base") is not None:
            b = float(c["base"])
            best = b if best is None else min(best, b)
    vv = _num(vert_vis)
    if vv is not None:
        vv = vv * 100 if vv < 100 else vv
        best = vv if best is None else min(best, vv)
    return int(best) if best is not None else None


def flight_category(ceiling: Optional[float], vis_sm: Optional[float]) -> str:
    """FAA categories: VFR >3000 ft and >5 sm; MVFR 1000-3000 or 3-5; IFR 500-<1000 or 1-<3; LIFR <500 or <1."""
    rank = 0
    if ceiling is not None:
        rank = max(rank, 3 if ceiling < 500 else 2 if ceiling < 1000 else 1 if ceiling <= 3000 else 0)
    if vis_sm is not None:
        rank = max(rank, 3 if vis_sm < 1 else 2 if vis_sm < 3 else 1 if vis_sm <= 5 else 0)
    return ("VFR", "MVFR", "IFR", "LIFR")[rank]


_WX_TOKEN = re.compile(r"^[-+]?(?:VC)?(?:MI|PR|BC|DR|BL|SH|TS|FZ)?(?:DZ|RA|SN|SG|IC|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PY|PO|SQ|FC|SS|DS)*$")


def wx_words(wx_string: str) -> set[str]:
    """Plain words from standard weather codes: TS, SN, FG, RA, BR, FZ. Vicinity-only (VC) groups are ignored."""
    out: set[str] = set()
    for tok in (wx_string or "").upper().split():
        t = tok.lstrip("+-")
        if t.startswith("VC") or not _WX_TOKEN.match(tok):
            continue
        if "TS" in t:
            out.add("storms")
        if "SN" in t or "SG" in t:
            out.add("snow")
        if "RA" in t or "DZ" in t:
            out.add("rain")
        if "FG" in t:
            out.add("fog")
        if "BR" in t:
            out.add("mist")
        if "FZ" in t:
            out.add("freezing")
    return out


def describe(cat: str, ceiling: Optional[float], vis_sm: Optional[float], words: set[str]) -> str:
    """Plain traveler words for one set of conditions. At most two pieces."""
    pieces: list[str] = []
    if "freezing" in words and ("rain" in words or "fog" in words):
        pieces.append("freezing rain" if "rain" in words else "freezing fog")
    elif "storms" in words:
        pieces.append("storms")
    else:
        for w in ("snow", "rain", "fog", "mist"):
            if w in words:
                pieces.append(w)
                break
    if cat in ("IFR", "LIFR"):
        if "fog" not in pieces and ceiling is not None and ceiling < 1000:
            pieces.append("low clouds")
        elif not pieces:
            pieces.append("poor visibility")
    elif cat == "MVFR" and not pieces:
        pieces.append("some low clouds" if (ceiling is not None and ceiling <= 3000) else "reduced visibility")
    if not pieces:
        pieces.append("clear")
    return " and ".join(pieces[:2])


def _metar_words(m: dict[str, Any]) -> set[str]:
    raw = str(m.get("rawOb") or "")
    body = raw.split(" RMK")[0]
    return wx_words(str(m.get("wxString") or "") or " ".join(t for t in body.split() if _WX_TOKEN.match(t) and re.search(r"[A-Z]{2}", t) and not re.match(r"^(?:K[A-Z]{3}|METAR|SPECI|AUTO|COR|CLR|SKC|NSC|CAVOK)$", t)))


def parse_metar(m: dict[str, Any], now_ts: float) -> Optional[dict[str, Any]]:
    obs = m.get("obsTime")
    if not isinstance(obs, (int, float)) or now_ts - obs > MAX_OBS_AGE:
        return None
    vis = _num(m.get("visib"))
    ceil = ceiling_ft(m.get("clouds") or [], m.get("vertVis"))
    cat = str(m.get("fltCat") or "").upper()
    if cat not in CAT_RANK:
        cat = flight_category(ceil, vis)
    words = _metar_words(m)
    return {
        "cat": cat, "obs_utc": _iso(obs), "wind_kt": _num(m.get("wspd")), "gust_kt": _num(m.get("wgst")),
        "vis_sm": vis, "ceiling_ft": ceil, "now_text": describe(cat, ceil, vis, words),
    }


def _period_cat(p: dict[str, Any]) -> tuple[str, Optional[float], Optional[float]]:
    vis = _num(p.get("visib"))
    ceil = ceiling_ft(p.get("clouds") or [], p.get("vertVis"))
    return flight_category(ceil, vis), ceil, vis


def taf_next3h(taf: dict[str, Any], now_ts: float, tz: Optional[str]) -> Optional[dict[str, Any]]:
    """Worst forecast period overlapping [now, now+3h]. PROB30 groups are left out (30% is not 'expected')."""
    lo, hi = now_ts, now_ts + WINDOW_SEC
    worst = None
    for p in taf.get("fcsts") or []:
        f, t = p.get("timeFrom"), p.get("timeTo")
        if not isinstance(f, (int, float)) or not isinstance(t, (int, float)) or t <= lo or f >= hi:
            continue
        prob = p.get("probability")
        if isinstance(prob, (int, float)) and prob < 40:
            continue
        cat, ceil, vis = _period_cat(p)
        words = wx_words(str(p.get("wxString") or ""))
        ts = "storms" in words
        key = (max(CAT_RANK[cat], 2 if ts else 0), CAT_RANK[cat], ts)
        if worst is None or key > worst[0]:
            worst = (key, p, cat, ceil, vis, words, ts)
    if worst is None:
        return None
    _, p, cat, ceil, vis, words, ts = worst
    start, end = max(lo, float(p["timeFrom"])), min(hi, float(p["timeTo"]))
    text = describe(cat, ceil, vis, words)
    if start - lo > 600:
        when = "likely after " + timefmt.say_when(datetime.fromtimestamp(start, timezone.utc), tz, datetime.fromtimestamp(now_ts, timezone.utc))
    else:
        when = "through " + timefmt.say_when(datetime.fromtimestamp(end, timezone.utc), tz, datetime.fromtimestamp(now_ts, timezone.utc))
    return {"next3h_text": f"{text} {when}", "next3h_cat": cat, "next3h_storms": ts,
            "next3h_from_utc": _iso(start), "next3h_to_utc": _iso(end)}


def build(metars: list[dict[str, Any]], tafs: list[dict[str, Any]], now_ts: float) -> dict[str, Any]:
    by_taf = {str(t.get("icaoId")): t for t in tafs}
    hubs: dict[str, Any] = {}
    for m in metars:
        ic = str(m.get("icaoId") or "")
        code = next((c for c, i in ICAO_OTHER.items() if i == ic), ic[1:] if ic.startswith("K") else ic)
        rec = parse_metar(m, now_ts)
        if rec is None or code not in AIRPORTS:
            continue
        taf = by_taf.get(ic)
        if taf:
            nxt = taf_next3h(taf, now_ts, TZ.get(code))
            if nxt:
                rec.update(nxt)
            iss = taf.get("issueTime") or taf.get("bulletinTime")
            if iss:
                rec["taf_issue_utc"] = str(iss)[:19] + "Z"
        rec["alert"] = rec["cat"] in ("IFR", "LIFR") or rec.get("next3h_cat") in ("IFR", "LIFR") or bool(rec.get("next3h_storms"))
        hubs[code] = rec
    return {"fetched_utc": _iso(now_ts), "source": SOURCE, "hubs": hubs}


def _shift(obj: Any, delta: float) -> Any:
    """Replay only: move every timestamp of a recorded response so the recording reads as 'now'."""
    num_keys = {"obsTime", "timeFrom", "timeTo", "validTimeFrom", "validTimeTo"}
    iso_keys = {"reportTime", "issueTime", "bulletinTime", "receiptTime", "dbPopTime"}
    if isinstance(obj, list):
        return [_shift(x, delta) for x in obj]
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in num_keys and isinstance(v, (int, float)):
                out[k] = v + delta
            elif k in iso_keys and isinstance(v, str) and len(v) >= 19:
                d = datetime.strptime(v[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc) + timedelta(seconds=delta)
                out[k] = d.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            else:
                out[k] = _shift(v, delta)
        return out
    return obj


def _parse_iso(s: str) -> float:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def is_fresh(out_dir: Path, now_ts: float, every: float = EVERY_SEC) -> bool:
    try:
        d = json.loads((Path(out_dir) / "wx.json").read_text(encoding="utf-8"))
        return 0 <= now_ts - _parse_iso(d["fetched_utc"]) < every
    except (OSError, ValueError, KeyError):
        return False


def maybe_fetch(
    out_dir: Path | str,
    now_ts: Optional[float] = None,
    replay: bool = False,
    fetcher: Optional[Callable[[str], str]] = None,
    attempts: Optional[dict[str, float]] = None,
    event_airports: Optional[list[str]] = None,
) -> str:
    """Refresh wx.json at most every 10 minutes (failed tries count too). Returns 'skip' or 'ok'; raises on error."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    now = time.time() if now_ts is None else now_ts
    if is_fresh(out, now):
        return "skip"
    if attempts is not None:
        last = attempts.get("wx")
        if last is not None and 0 <= now - last < EVERY_SEC:
            return "skip"
        attempts["wx"] = now
    codes = wanted_codes(event_airports or [])
    if replay:
        rec = json.loads((FIXTURES / "wx-recorded.json").read_text(encoding="utf-8"))["recorded_ts"]
        delta = now - rec
        sfx = "-synthetic" if demo.on() else ""
        metars = _shift(json.loads((FIXTURES / f"wx-metar{sfx}.json").read_text(encoding="utf-8")), delta)
        tafs = _shift(json.loads((FIXTURES / f"wx-taf{sfx}.json").read_text(encoding="utf-8")), delta)
        # a replay run reads a recording: keep only the airports it holds, and say so in the source line
        have = {m.get("icaoId") for m in metars}
        codes = [c for c in codes if icao(c) in have]
    else:
        ids = ",".join(icao(c) for c in codes if icao(c))
        get = fetcher or feeds.fetch
        metars = json.loads(get(f"{BASE}/metar?ids={ids}&format=json"))
        tafs = json.loads(get(f"{BASE}/taf?ids={ids}&format=json"))
    if not isinstance(metars, list) or not isinstance(tafs, list):
        raise ValueError("unexpected METAR/TAF response")
    payload = build(metars, tafs, now)
    from desk.radar import _atomic_write
    _atomic_write(out / "wx.json", json.dumps(payload).encode("utf-8"))
    return "ok"
