"""Build data/airports-links.json: the airport's own website for each of the 70 airports after the first 30 (AN23).

Source: OurAirports airports.csv (public domain, https://ourairports.com/data/). Only the home_link column is used.
Run it by hand now and then; the build does not run it and no test calls the network.

    curl -L -o scratch/airports.csv https://davidmegginson.github.io/ourairports-data/airports.csv
    python tools/build_airport_links.py --csv scratch/airports.csv --check

--check makes one GET per link (headers only, one at a time, with a pause) and records what came back.
A link is marked verified true only when that request returned a status below 400. Without --check nothing is
marked verified. Links the CSV does not hold can be listed in MANUAL below; they are marked origin "manual" and are
checked the same way. Stdlib only.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from desk.airports import BUSIEST_30, BUSIEST_100  # noqa: E402
from tools import check_links  # noqa: E402

SOURCE_NAME = "OurAirports (public domain)"
SOURCE_URL = "https://ourairports.com/data/"

# OurAirports leaves home_link empty for these, or holds a link that does not work. The address is the airport's own site;
# it replaces the CSV value, is marked origin "manual", is checked like the others and is marked verified only when the check passes.
MANUAL: dict[str, str] = {
    "TUL": "https://www.flytulsa.com/",
    "DSM": "https://www.flydsm.com/",
    "GRR": "https://www.grr.org/",
    "MSN": "https://www.msnairport.com/",
    "TYS": "https://www.flyknoxville.com/",
    "IND": "https://www.ind.com/",
    "COS": "https://www.flycos.com/",
    "PSP": "https://flypsp.com/",
}

# OurAirports lists this airport under another IATA code (its current name); the FAA code on this site stays the same.
ALIAS: dict[str, str] = {"PBI": "DJT"}


def _clean(url: str) -> str:
    url = (url or "").strip()
    parts = urllib.parse.urlsplit(url)
    return url if parts.scheme in ("http", "https") and parts.netloc and not any(ch.isspace() for ch in url) else ""


def read_links(csv_path: Path, codes: list[str]) -> dict[str, dict[str, Any]]:
    """home_link per IATA code from the OurAirports CSV (US large and medium airports)."""
    wanted = set(codes)
    found: dict[str, dict[str, Any]] = {}
    with csv_path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            code = (row.get("iata_code") or "").strip()
            code = next((k for k, v in ALIAS.items() if v == code), code)
            if code not in wanted or row.get("iso_country") != "US" or row.get("type") not in ("large_airport", "medium_airport"):
                continue
            link = _clean(row.get("home_link") or "")
            if link or code not in found:
                found[code] = {"home_link": link, "origin": "ourairports"}
    return found


def build(csv_path: Path, check: bool, previous: dict[str, Any] | None = None, now: datetime | None = None, opener: Callable | None = None,
          sleep: Callable[[float], None] = time.sleep, pause: float = 1.0) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    codes = [c for c in BUSIEST_100 if c not in BUSIEST_30]
    got = read_links(csv_path, codes)
    for code, url in MANUAL.items():
        got[code] = {"home_link": _clean(url), "origin": "manual"}
    airports: dict[str, Any] = {}
    for code in codes:
        entry = got.get(code) or {"home_link": "", "origin": "none"}
        item = {"home_link": entry["home_link"], "origin": entry["origin"], "verified": False, "status": None, "checked": ""}
        old = ((previous or {}).get("airports") or {}).get(code) or {}
        if check and entry["home_link"] and old.get("home_link") == entry["home_link"] and old.get("checked") and not (old.get("status") or 0) // 100 == 3:
            item.update({k: old[k] for k in ("verified", "status", "checked", "error") if k in old})
        elif check and entry["home_link"]:
            res = check_links.check_url(entry["home_link"], opener or check_links.default_opener, method="GET")
            item.update({"verified": bool(res["ok"]), "status": res["status"], "checked": day})
            if res["error"] and res["status"] is None:
                item["error"] = res["error"]
            sleep(pause)
        airports[code] = item
    return {
        "version": 1,
        "source": SOURCE_NAME,
        "source_url": SOURCE_URL,
        "checked_utc": day if check else "",
        "note": ("The airport's own website, from OurAirports (public domain). verified is true only when one GET request on the "
                 "checked date returned a status below 400; false means the site blocked the check, did not answer or the "
                 "address was not tested, not that the link is wrong."),
        "airports": airports,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", required=True, help="OurAirports airports.csv, downloaded once")
    ap.add_argument("--out", default=str(ROOT / "data" / "airports-links.json"))
    ap.add_argument("--previous", help="an earlier result: links already checked and unchanged are not requested again")
    ap.add_argument("--check", action="store_true", help="make one GET per link and record the result")
    a = ap.parse_args(argv)
    previous = json.loads(Path(a.previous).read_text(encoding="utf-8")) if a.previous else None
    doc = build(Path(a.csv), a.check, previous)
    Path(a.out).write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    ok = sum(1 for e in doc["airports"].values() if e["verified"])
    have = sum(1 for e in doc["airports"].values() if e["home_link"])
    print(f"airports-links: {have} links, {ok} verified, of {len(doc['airports'])} airports; wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
