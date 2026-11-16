"""AN43: per-airport 12-month BTS on-time profile for the airport pages' static context.

Reads BTS "Reporting Carrier On-Time Performance" monthly zips (US public domain,
https://www.transtats.bts.gov/) and writes data/an43/bts-profile.json:
departures from each airport (Origin) and arrivals to it (Dest), by month, by departure hour block,
by carrier and by destination, cancellation reasons, delay-cause minutes and taxi-out time.

Usage: python3 tools/an43_bts_profile.py <zip_dir> [out_json]
"""
from __future__ import annotations

import csv
import io
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAUSES = ("CarrierDelay", "WeatherDelay", "NASDelay", "SecurityDelay", "LateAircraftDelay")
CAUSE_WORD = {"CarrierDelay": "airline", "WeatherDelay": "extreme weather", "NASDelay": "air traffic system",
              "SecurityDelay": "security", "LateAircraftDelay": "late incoming aircraft"}
CANCEL_WORD = {"A": "airline", "B": "weather", "C": "air traffic system", "D": "security"}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def is1(v: str) -> bool:
    return v in ("1", "1.00", "1.0")


def num(v: str) -> float:
    try:
        return float(v)
    except ValueError:
        return 0.0


class Dep:
    __slots__ = ("sched", "canc", "done", "ontime", "late_min", "late_n", "taxi", "taxi_n", "canc_code")

    def __init__(self) -> None:
        self.sched = self.canc = self.done = self.ontime = self.late_n = self.taxi_n = 0
        self.late_min = self.taxi = 0.0
        self.canc_code: dict[str, int] = {}

    def add(self, r: list[str], ix: dict[str, int]) -> None:
        self.sched += 1
        if is1(r[ix["Cancelled"]]):
            self.canc += 1
            c = r[ix["CancellationCode"]] or "?"
            self.canc_code[c] = self.canc_code.get(c, 0) + 1
            return
        d15 = r[ix["DepDel15"]]
        if d15 == "":
            return
        self.done += 1
        if is1(d15):
            self.late_n += 1
            self.late_min += num(r[ix["DepDelay"]])
        else:
            self.ontime += 1
        t = r[ix["TaxiOut"]]
        if t:
            self.taxi += num(t)
            self.taxi_n += 1

    def out(self) -> dict:
        pct = lambda a, b: round(a / b * 100, 1) if b else None
        return {"flights": self.sched, "ontime": pct(self.ontime, self.done), "cancel": pct(self.canc, self.sched),
                "late_avg_min": round(self.late_min / self.late_n, 1) if self.late_n else None,
                "taxi_out_min": round(self.taxi / self.taxi_n, 1) if self.taxi_n else None,
                "cancel_reasons": {CANCEL_WORD.get(k, k): v for k, v in sorted(self.canc_code.items(), key=lambda kv: -kv[1])}}


class Arr:
    __slots__ = ("done", "ontime", "cause")

    def __init__(self) -> None:
        self.done = self.ontime = 0
        self.cause = dict.fromkeys(CAUSES, 0.0)

    def add(self, r: list[str], ix: dict[str, int]) -> None:
        if is1(r[ix["Cancelled"]]) or is1(r[ix["Diverted"]]) or r[ix["ArrDel15"]] == "":
            return
        self.done += 1
        if is1(r[ix["ArrDel15"]]):
            for c in CAUSES:
                self.cause[c] += num(r[ix[c]])
        else:
            self.ontime += 1

    def out(self) -> dict:
        tot = sum(self.cause.values())
        return {"flights": self.done, "ontime": round(self.ontime / self.done * 100, 1) if self.done else None,
                "cause_share": {CAUSE_WORD[c]: round(v / tot * 100, 1) for c, v in self.cause.items()} if tot else {}}


def main(zip_dir: Path, out_path: Path) -> None:
    keep = {p.stem for p in (ROOT / "airports").glob("*.html") if len(p.stem) == 3 and p.stem.isupper()}
    dep: dict = {}; arr: dict = {}; months_seen = set()
    nat_dep, nat_arr = Dep(), Arr()

    def slot(store, key, cls):
        o = store.get(key)
        if o is None:
            o = store[key] = cls()
        return o

    zips = sorted(zip_dir.glob("otp_*.zip"), key=lambda p: tuple(int(x) for x in p.stem.split("_")[1:]))
    zips = zips[-12:]
    for zp in zips:
        with zipfile.ZipFile(zp) as zf:
            name = [n for n in zf.namelist() if n.lower().endswith(".csv")][0]
            with zf.open(name) as raw:
                rd = csv.reader(io.TextIOWrapper(raw, encoding="utf-8", newline=""))
                head = next(rd); ix = {h: i for i, h in enumerate(head)}
                need = max(ix[c] for c in ("Origin", "Dest", "LateAircraftDelay", "CancellationCode", "TaxiOut"))
                for r in rd:
                    if len(r) <= need:
                        continue
                    y, m = int(r[ix["Year"]]), int(r[ix["Month"]]); months_seen.add((y, m))
                    o, d, car = r[ix["Origin"]], r[ix["Dest"]], r[ix["Reporting_Airline"]]
                    blk = r[ix["DepTimeBlk"]][:2]
                    nat_dep.add(r, ix); nat_arr.add(r, ix)
                    if o in keep:
                        for k in (("all",), ("m", m), ("h", blk), ("c", car), ("d", d)):
                            slot(dep, (o,) + k, Dep).add(r, ix)
                    if d in keep:
                        slot(arr, (d, "all"), Arr).add(r, ix)
        print("read", zp.name, flush=True)

    sys.path.insert(0, str(ROOT))
    from desk.bts import CARRIER_NAMES
    ms = sorted(months_seen)
    prof = {}
    for code in sorted(keep):
        a = dep.get((code, "all"))
        if not a:
            continue
        g = lambda kind: {k[2]: v.out() for k, v in dep.items() if k[0] == code and k[1] == kind}
        by_m = {MONTHS[int(k) - 1]: v for k, v in sorted(g("m").items())}
        by_h = dict(sorted(g("h").items()))
        by_c = sorted(g("c").items(), key=lambda kv: -kv[1]["flights"])[:6]
        by_d = sorted(g("d").items(), key=lambda kv: -kv[1]["flights"])[:8]
        prof[code] = {"departures": a.out(), "arrivals": arr[(code, "all")].out() if (code, "all") in arr else None,
                      "by_month": by_m, "by_hour_block": by_h,
                      "carriers": [{"code": k, "name": CARRIER_NAMES.get(k, k), **v} for k, v in by_c],
                      "top_destinations": [{"code": k, **v} for k, v in by_d]}
    out = {"source": "BTS Reporting Carrier On-Time Performance, https://www.transtats.bts.gov/ (US public domain)",
           "period": f"{MONTHS[ms[0][1]-1]} {ms[0][0]} to {MONTHS[ms[-1][1]-1]} {ms[-1][0]}", "months": len(ms),
           "definition": "Departure on time = left the gate less than 15 minutes late (DepDel15 = 0), among flights that "
                         "were not cancelled. Arrival on time = ArrDel15 = 0. Delay causes are shares of reported delay "
                         "minutes on late arrivals. Hour block = scheduled departure hour (local).",
           "built_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "nation": {"departures": nat_dep.out(), "arrivals": nat_arr.out()}, "airports": prof}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, separators=(",", ":")))
    print("wrote", out_path, len(prof), "airports,", out["period"])


if __name__ == "__main__":
    main(Path(sys.argv[1]).expanduser(), Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "data" / "an43" / "bts-profile.json")
