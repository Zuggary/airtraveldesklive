#!/usr/bin/env python3
"""Build data/airport-names.json: every US airport code -> [name, city, state], from the OurAirports airports.csv (public domain).

Usage: python3 tools/build_airport_names.py /path/to/airports.csv [out.json]
Keys: the IATA code, the FAA/local code, and the ICAO ident without its leading K (so "TEB" and "KTEB" both resolve).
Closed airports are dropped; heliports, seaplane bases and balloonports are kept only when they have an IATA or local code (the FAA feed names them).
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from desk.airports import CITY, DISPLAY, canonical_code  # noqa: E402

KEEP_TYPES = {"large_airport", "medium_airport", "small_airport", "seaplane_base", "heliport"}


def build(csv_path: str) -> dict:
    out: dict[str, list[str]] = {}
    rank = {"large_airport": 0, "medium_airport": 1, "small_airport": 2, "seaplane_base": 3, "heliport": 4}
    best: dict[str, int] = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if (r.get("iso_country") or r["iso_region"].split("-")[0]) != "US" or r["type"] not in KEEP_TYPES:
                continue
            name = (r["name"] or "").strip()
            if not name:
                continue
            state = r["iso_region"].split("-")[-1] if r["iso_region"] else ""
            val = [name, (r["municipality"] or "").strip(), state]
            keys = set()
            for k in (r["iata_code"], r["local_code"], r["gps_code"], r["ident"]):
                k = canonical_code(k)
                if not k:
                    continue
                keys.add(k)
                if len(k) == 4 and k.startswith("K") and k[1:].isalnum():
                    keys.add(k[1:])
            for k in keys:
                if len(k) < 3 or len(k) > 4:
                    continue
                if k not in out or rank[r["type"]] < best[k]:
                    out[k] = [DISPLAY[k], *CITY[k].split(", ")] if k == "DJT" else val
                    best[k] = rank[r["type"]]
    return {
        "version": 1,
        "source": "OurAirports airports.csv (public domain), US airports",
        "built_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(out),
        "airports": dict(sorted(out.items())),
    }


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "data" / "airport-names.json"
    data = build(sys.argv[1])
    dst.write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{data['count']} codes -> {dst} ({dst.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
