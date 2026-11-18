"""Build data/sources.json: every feed the site reads, with licence, terms link, update rhythm and last-checked time.

The list below is the one source of truth for sources.html (a test compares the two). Last-checked times are read
from the data files the other build steps wrote. A missing file gives a null time, never a made-up one.
Standard library only. No network. Run after build_status.py, build_web.py and build_places.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
GOV = "https://www.usa.gov/government-works"
ODBL = "https://opendatacommons.org/licenses/odbl/1-0/"

# kind of time: "time" = a UTC timestamp, "date" = a day only, "static" = a file that does not change.
# file + key say where the last-checked time is read from.
SOURCES: list[dict[str, Any]] = [
    {"id": "faa-nas", "group": "site", "name": "FAA NAS status", "page": "https://nasstatus.faa.gov/",
     "terms": GOV, "licence": "U.S. government work", "used_for": "Airport delays, ground delays, ground stops and closures",
     "update": "About every minute; the site reads it every 5 minutes", "file": "state.json", "key": "updated_utc", "kind": "time"},
    {"id": "nws", "group": "site", "name": "National Weather Service alerts", "page": "https://www.weather.gov/",
     "terms": "https://www.weather.gov/disclaimer", "licence": "U.S. government work",
     "used_for": "Active weather alerts near airports (api.weather.gov)",
     "update": "Every 10 minutes", "file": "status.json", "key": "updated_utc", "kind": "time"},
    {"id": "aviationweather", "group": "site", "name": "aviationweather.gov METAR and TAF", "page": "https://aviationweather.gov/",
     "terms": GOV, "licence": "U.S. government work",
     "used_for": "Airport weather reports, 3-hour forecasts and convective SIGMETs",
     "update": "Every 10 minutes (SIGMETs every 15 minutes)", "file": "wx.json", "key": "fetched_utc", "kind": "time"},
    {"id": "spc", "group": "site", "name": "NOAA Storm Prediction Center outlooks", "page": "https://www.spc.noaa.gov/",
     "terms": GOV, "licence": "U.S. government work", "used_for": "Day-1 convective storm outlook areas",
     "update": "Every 15 minutes", "file": "storms.json", "key": "fetched_utc", "kind": "time"},
    {"id": "nhc", "group": "site", "name": "NOAA National Hurricane Center", "page": "https://www.nhc.noaa.gov/",
     "terms": GOV, "licence": "U.S. government work", "used_for": "Active tropical storms and hurricanes",
     "update": "Every 30 minutes", "file": "nhc.json", "key": "fetched_utc", "kind": "time"},
    {"id": "mrms", "group": "site", "name": "NOAA radar (MRMS base reflectivity)", "page": "https://opengeo.ncep.noaa.gov/",
     "terms": GOV, "licence": "U.S. government work", "used_for": "Radar image over the lower 48 states",
     "update": "Every 5 minutes", "file": "radar.json", "key": "fetched_utc", "kind": "time"},
    {"id": "tsa", "group": "site", "name": "TSA checkpoint numbers", "page": "https://www.tsa.gov/travel/passenger-volumes",
     "terms": GOV, "licence": "U.S. government work", "used_for": "Daily passenger screening counts and holiday comparisons",
     "update": "Daily", "file": "tsa.json", "key": "fetched_utc", "kind": "time"},
    {"id": "bts", "group": "site", "name": "Bureau of Transportation Statistics on-time data", "page": "https://www.bts.gov/",
     "terms": GOV, "licence": "U.S. government work", "used_for": "Monthly airline and airport on-time and cancellation rates",
     "update": "Monthly", "file": "bts.json", "key": "checked_utc", "kind": "time"},
    {"id": "adsb-lol", "group": "site", "name": "adsb.lol", "page": "https://www.adsb.lol/",
     "terms": ODBL, "licence": "ODbL 1.0; credit required",
     "used_for": "Aircraft positions for map trails, traffic counts and holding notes",
     "update": "Every 5 minutes (full sweep about every 15 minutes)", "file": "national.json", "key": "fetched_utc", "kind": "time"},
    {"id": "osm", "group": "site", "name": "OpenStreetMap via Overpass", "page": "https://www.openstreetmap.org/",
     "terms": "https://www.openstreetmap.org/copyright", "licence": "ODbL (© OpenStreetMap contributors)",
     "used_for": "Hotels and car rental places near each airport",
     "update": "Weekly for the first 30 airports; the other 70 in small hourly batches, each about weekly", "file": "places.json", "key": "fetched_utc", "kind": "time"},
    {"id": "dot-dashboard", "group": "site", "name": "U.S. DOT Airline Cancellation and Delay Dashboard",
     "page": "https://www.transportation.gov/airconsumer/airline-cancellation-delay-dashboard",
     "terms": GOV, "licence": "U.S. government work", "used_for": "Airline customer service commitments table",
     "update": "Changed by hand when DOT changes the page; page last updated 2025-09-11",
     "file": "dot-commitments.json", "key": "read_by_lane_1", "kind": "date"},
    {"id": "dot-ask-first", "group": "site", "name": "U.S. DOT air consumer pages (refunds, tarmac delays, complaints) and 14 CFR 260.6",
     "page": "https://www.transportation.gov/airconsumer",
     "terms": GOV, "licence": "U.S. government work", "used_for": "The rules in the Ask before you pay section of the stuck guide",
     "update": "Read by hand on the date shown; each rule on the page shows its own read date",
     "file": "ask-first-sources.json", "key": "read", "kind": "date"},
    {"id": "ourairports", "group": "site", "name": "OurAirports", "page": "https://ourairports.com/data/",
     "terms": "https://ourairports.com/data/", "licence": "Public domain",
     "used_for": "The website address of each airport after the first 30",
     "update": "Read once on the check date and saved in this site's files", "file": "airports-links.json", "key": "checked_utc", "kind": "date"},
    {"id": "airport-sites", "group": "site", "name": "Airport operators' own websites", "page": "/airports/",
     "terms": "/airports/", "licence": "Links only; no text copied",
     "used_for": "Official airport guide links and security wait page links",
     "update": "Links tested by script on the check date; some sites block the test", "file": "airport-guide.json", "key": "checked_utc", "kind": "date"},
    {"id": "natural-earth", "group": "site", "name": "Natural Earth map outlines", "page": "https://www.naturalearthdata.com/",
     "terms": "https://www.naturalearthdata.com/about/terms-of-use/", "licence": "Public domain",
     "used_for": "U.S. state borders on the map", "update": "Static map file", "file": None, "key": None, "kind": "static"},
    {"id": "sun", "group": "site", "name": "Sun position (computed from NOAA solar equations, no network)", "page": "https://gml.noaa.gov/grad/solcalc/calcdetails.html",
     "terms": "https://gml.noaa.gov/grad/solcalc/calcdetails.html", "licence": "Public domain method",
     "used_for": "Day and night shading on the TV map and sunrise and sunset on each airport page",
     "update": "Computed in your browser every minute; nothing is fetched", "file": None, "key": None, "kind": "static"},
    {"id": "goes", "group": "stream", "name": "NOAA GOES-19 satellite images", "page": "https://www.star.nesdis.noaa.gov/GOES/",
     "terms": GOV, "licence": "U.S. government work", "used_for": "Satellite loop in TV mode on the stream",
     "update": "About every 10 minutes", "file": None, "key": None, "kind": "stream"},
    {"id": "caltrans", "group": "stream", "name": "Caltrans highway camera images", "page": "https://cwwp2.dot.ca.gov/",
     "terms": "https://cwwp2.dot.ca.gov/", "licence": "Public feed; check terms on the page",
     "used_for": "Highway camera views near LAX, SFO and SAN in TV mode on the stream",
     "update": "Every few minutes", "file": None, "key": None, "kind": "stream"},
    {"id": "wsdot", "group": "stream", "name": "WSDOT highway camera images", "page": "https://wsdot.wa.gov/traffic/api/",
     "terms": "https://wsdot.wa.gov/traffic/api/", "licence": "Public feed; access code required; check terms on the page",
     "used_for": "Highway camera view near SEA in TV mode on the stream",
     "update": "Every few minutes", "file": None, "key": None, "kind": "stream"},
]

STORY_SOURCES: dict[str, Any] = {
    "description": "Some on-air airport stories draw facts from Wikipedia (CC BY-SA 4.0), rephrased, not copied.",
    "licence": "CC BY-SA 4.0",
    "terms": "https://creativecommons.org/licenses/by-sa/4.0/",
    "articles": [
        {"name": title, "page": "https://en.wikipedia.org/wiki/" + title.replace(" ", "_")}
        for title in (
            "Washington Dulles International Airport",
            "Miami International Airport",
            "Newark Liberty International Airport",
            "Harry Reid International Airport",
            "Dallas Fort Worth International Airport",
        )
    ],
    "photo_credits": "Photo credits on airport cards link to Wikimedia Commons file pages with author and licence.",
}


NOT_USED: list[str] = [
    "Airline websites and apps: not read. Airline status pages are linked, never copied.",
    "Paid flight-tracking sites (FlightAware, Flightradar24): their terms do not allow this use.",
    "FAA SWIM and other login-only aviation feeds: not used.",
    "Reader reports, social posts and news articles: never copied or used for a status.",
    "Ad scripts and tracking pixels: none on this site. The only analytics is Cloudflare Web Analytics, which counts visits without cookies (see the privacy page).",
]


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read(path: Path) -> Optional[dict[str, Any]]:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def build(data_dir: Path, now: Optional[datetime] = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    out = []
    for s in SOURCES:
        checked = None
        if s["file"]:
            d = _read(data_dir / s["file"])
            v = d.get(s["key"]) if d else None
            checked = v if isinstance(v, str) and v else None
        out.append({
            "id": s["id"], "group": s["group"], "name": s["name"], "page": s["page"], "terms": s["terms"],
            "licence": s["licence"], "used_for": s["used_for"], "update": s["update"],
            "kind": s["kind"], "file": s["file"], "checked": checked,
        })
    return {"generated_utc": iso_utc(now), "sources": out, "story_sources": STORY_SOURCES, "not_used": NOT_USED}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(ROOT / "data"), help="data folder: read the feed files here and write sources.json here")
    a = ap.parse_args(argv)
    out = Path(a.out)
    doc = build(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "sources.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print("sources.json: %d sources, %d with a time" % (len(doc["sources"]), sum(1 for s in doc["sources"] if s["checked"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
