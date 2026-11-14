"""AN12 item 1: the DESK LOG ticker. Only items a viewer acts on, and none repeats inside 10 minutes.

Kinds: new, updated, ended (FAA changes), stop (an active ground stop with its end time), wx (hub weather in the
next 3 hours), hold (aircraft that look to be holding), owed (the passenger-rights link). "Still in effect" lines
and recaps stay in the voice and never come here. Squawks never come here.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from desk import timefmt
from desk.screen import duration_minutes, minutes_text

COOLDOWN_SEC = 600.0
OWED_COOLDOWN_SEC = 900.0
KEEP_SEC = 900.0
MAX_ITEMS = 16
MAX_WX = 3
OWED_TEXT = "Delayed? Check what you're owed · downtimecredit.com/flights"
KIND_NAME = {"ground_stop": "ground stop", "ground_delay": "ground delay", "delay": "delays", "closure": "closure"}


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    try:
        return datetime.strptime(str(s)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _numbers(ev: dict[str, Any]) -> str:
    f = ev.get("fields") or {}
    kind = ev.get("kind")
    if kind == "ground_delay":
        for key, label in (("avg", "avg"), ("max", "max")):
            m = duration_minutes(f.get(key))
            if m is not None:
                return f"{label} {minutes_text(m)}"
    if kind == "delay":
        lo, hi = duration_minutes(f.get("min")), duration_minutes(f.get("max"))
        who = (f.get("direction") or "").strip().lower()
        who = f" ({who}s)" if who else ""
        if lo is not None and hi is not None:
            return f"{minutes_text(lo)} to {minutes_text(hi)}{who}"
        if hi is not None:
            return f"up to {minutes_text(hi)}{who}"
    return ""


def _end_text(ev: dict[str, Any], now: datetime) -> str:
    dt = _parse_iso(ev.get("end_utc"))
    if dt is not None:
        if (now - dt).total_seconds() > 300:
            return "past listed end time"
        return "until " + timefmt.caption_when(dt, ev.get("tz"), now)
    return "end time not given"


def _reopen_text(ev: dict[str, Any], now: datetime) -> str:
    dt = timefmt.parse_faa_when(str((ev.get("fields") or {}).get("reopen") or ""), now)
    return ("reopens " + timefmt.caption_when(dt, ev.get("tz"), now)) if dt else ""


TAGS = {"new": "NEW", "updated": "UPDATED", "ended": "ENDED", "stop": "GROUND STOP", "wx": "WEATHER", "hold": "HOLDING", "owed": "YOUR RIGHTS"}


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def change_text(change: dict[str, Any], now: datetime) -> Optional[tuple[str, str]]:
    """(kind, text) for one FAA change, or None for anything that is not an FAA airport event. The tag and the source go beside the text."""
    ev = change["event"]
    kind = ev.get("kind")
    if kind not in KIND_NAME or ev.get("source") != "FAA":
        return None
    code = str(ev.get("airport") or "").upper()
    if not code:
        return None
    ct = change["change"]
    name = KIND_NAME[kind]
    reason = str(ev.get("reason") or "").strip()
    reason = "" if (not reason or reason.upper().startswith("OTHER:")) else reason
    if ct == "cleared":
        return "ended", f"{_cap(name)} at {code} has ended"
    detail = _end_text(ev, now) if kind == "ground_stop" else (_reopen_text(ev, now) if kind == "closure" else _numbers(ev))
    bits = [x for x in (detail, reason) if x]
    return ("new" if ct == "new" else "updated"), f"{_cap(name)} at {code}" + (" · " + " · ".join(bits) if bits else "")


class Ticker:
    def __init__(self, cooldown: float = COOLDOWN_SEC, keep_sec: float = KEEP_SEC, max_items: int = MAX_ITEMS) -> None:
        self.cooldown = cooldown
        self.keep_sec = keep_sec
        self.same_text_sec = 0.0
        self.max_items = max_items
        self.sent: dict[str, float] = {}
        self.items: list[dict[str, Any]] = []

    def restore(self, items: Optional[list[dict[str, Any]]]) -> int:
        """Website job: each run starts fresh, so read back the items the last published state.json carried.
        Their keys and times keep the no-repeat rule alive across runs."""
        n = 0
        for it in items or []:
            dt = _parse_iso(it.get("t_utc"))
            key, text = it.get("key"), it.get("text")
            if dt is None or not key or not text:
                continue
            ts = dt.timestamp()
            self.sent[key] = max(self.sent.get(key, 0.0), ts)
            self.items.append({**{k: v for k, v in it.items()}, "ts": ts})
            n += 1
        return n

    def _cool(self, key: str) -> float:
        return OWED_COOLDOWN_SEC if key == "owed" else self.cooldown

    def add(self, key: str, kind: str, text: str, now_ts: float, src: str = "", as_of_utc: Optional[str] = None) -> bool:
        last = self.sent.get(key)
        if last is not None and now_ts - last < self._cool(key):
            return False
        # the same words never show twice inside the window (the longer of the cooldown and, on the web, the keep time)
        for it in self.items:
            if it["text"] == text and now_ts - it["ts"] < max(self.cooldown, self.same_text_sec):
                return False
        self.sent[key] = now_ts
        self.items.append({"id": f"{key}@{int(now_ts)}", "key": key, "kind": kind, "tag": TAGS.get(kind, kind.upper()), "text": text, "src": src,
                           "as_of_utc": as_of_utc or _iso(now_ts), "t_utc": _iso(now_ts), "ts": now_ts})
        return True

    def update(self, now_ts: float, changes: Optional[list[dict[str, Any]]], events: list[dict[str, Any]],
               wx_data: Optional[dict[str, Any]], holding_state: Optional[dict[str, Any]], first_poll: bool = False) -> list[dict[str, Any]]:
        now = datetime.fromtimestamp(now_ts, timezone.utc)
        if not first_poll:
            for ch in changes or []:
                got = change_text(ch, now)
                if not got:
                    continue
                kind, text = got
                ev = ch["event"]
                if self.add(f"{kind}:{ev.get('id')}:{text}", kind, text, now_ts, "FAA", _iso(now_ts)) and ev.get("kind") == "ground_stop":
                    self.sent[f"stop:{ev.get('id')}"] = now_ts      # its end time just aired; the stop line waits 10 minutes
        for ev in events:
            if ev.get("kind") == "ground_stop" and ev.get("source") == "FAA" and ev.get("airport"):
                code = str(ev["airport"]).upper()
                self.add(f"stop:{ev.get('id')}", "stop", f"Ground stop at {code} · {_end_text(ev, now)}", now_ts, "FAA", _iso(now_ts))
        hubs = (wx_data or {}).get("hubs") or {}
        risky = [(c, h) for c, h in hubs.items() if h.get("next3h_text") and (h.get("next3h_storms") or h.get("next3h_cat") in ("IFR", "LIFR"))]
        risky.sort(key=lambda ch: (not ch[1].get("next3h_storms"), ch[1].get("next3h_cat") != "LIFR", ch[0]))
        for code, h in risky[:MAX_WX]:
            self.add(f"wx:{code}:{h['next3h_text']}", "wx", f"{code} · {h['next3h_text']} (next 3 h)", now_ts, "TAF",
                     h.get("taf_issue_utc") or (wx_data or {}).get("fetched_utc"))
        for code, h in sorted((holding_state or {}).items()):
            self.add(f"hold:{code}", "hold", f"{h.get('count')} aircraft look to be holding near {code}", now_ts, "adsb.lol", h.get("as_of_utc"))
        self.add("owed", "owed", OWED_TEXT, now_ts)
        return self.feed(now_ts)

    def feed(self, now_ts: float) -> list[dict[str, Any]]:
        self.items = [i for i in self.items if now_ts - i["ts"] <= self.keep_sec][-self.max_items:]
        return [{k: v for k, v in i.items() if k != "ts"} for i in self.items]
