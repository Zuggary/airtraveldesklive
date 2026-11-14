from __future__ import annotations

import math
from typing import Optional

# 40 busiest US airports (plus BDL): code -> (spoken_name, lat, lon)
AIRPORTS: dict[str, tuple[str, float, float]] = {
    "ATL": ("Atlanta Hartsfield-Jackson", 33.641, -84.427),
    "DFW": ("Dallas Fort Worth", 32.897, -97.038),
    "DEN": ("Denver", 39.856, -104.674),
    "ORD": ("Chicago O'Hare", 41.974, -87.907),
    "LAX": ("Los Angeles International", 33.942, -118.408),
    "JFK": ("J F K", 40.641, -73.778),
    "LAS": ("Las Vegas Harry Reid", 36.084, -115.154),
    "MCO": ("Orlando International", 28.431, -81.308),
    "MIA": ("Miami International", 25.796, -80.287),
    "CLT": ("Charlotte Douglas", 35.214, -80.943),
    "SEA": ("Seattle-Tacoma", 47.450, -122.309),
    "PHX": ("Phoenix Sky Harbor", 33.437, -112.008),
    "EWR": ("Newark Liberty", 40.690, -74.174),
    "SFO": ("San Francisco International", 37.621, -122.379),
    "IAH": ("Houston Bush Intercontinental", 29.990, -95.337),
    "BOS": ("Boston Logan", 42.366, -71.010),
    "FLL": ("Fort Lauderdale", 26.073, -80.153),
    "MSP": ("Minneapolis-Saint Paul", 44.885, -93.222),
    "LGA": ("LaGuardia", 40.777, -73.874),
    "DTW": ("Detroit Metro", 42.212, -83.353),
    "PHL": ("Philadelphia International", 39.874, -75.242),
    "SLC": ("Salt Lake City", 40.789, -111.978),
    "BWI": ("Baltimore Washington", 39.177, -76.668),
    "IAD": ("Washington Dulles", 38.953, -77.457),
    "SAN": ("San Diego International", 32.734, -117.190),
    "DCA": ("Reagan National", 38.851, -77.040),
    "TPA": ("Tampa International", 27.977, -82.531),
    "BNA": ("Nashville International", 36.127, -86.678),
    "AUS": ("Austin-Bergstrom", 30.197, -97.666),
    "MDW": ("Chicago Midway", 41.786, -87.752),
    "HNL": ("Honolulu", 21.319, -157.922),
    "DAL": ("Dallas Love Field", 32.847, -96.852),
    "PDX": ("Portland International", 45.589, -122.595),
    "STL": ("St. Louis Lambert", 38.749, -90.370),
    "HOU": ("Houston Hobby", 29.645, -95.279),
    "SMF": ("Sacramento International", 38.695, -121.591),
    "SJC": ("San Jose International", 37.363, -121.929),
    "OAK": ("Oakland International", 37.721, -122.221),
    "RDU": ("Raleigh-Durham", 35.878, -78.788),
    "BDL": ("Bradley International", 41.939, -72.683),
}

# Official display names for every airport in AIRPORTS
DISPLAY: dict[str, str] = {
    "ATL": "Hartsfield-Jackson Atlanta International",
    "DFW": "Dallas Fort Worth International",
    "DEN": "Denver International",
    "ORD": "Chicago O'Hare International",
    "LAX": "Los Angeles International",
    "JFK": "John F. Kennedy International",
    "LAS": "Harry Reid International",
    "MCO": "Orlando International",
    "MIA": "Miami International",
    "CLT": "Charlotte Douglas International",
    "SEA": "Seattle-Tacoma International",
    "PHX": "Phoenix Sky Harbor International",
    "EWR": "Newark Liberty International",
    "SFO": "San Francisco International",
    "IAH": "George Bush Intercontinental",
    "BOS": "Boston Logan International",
    "FLL": "Fort Lauderdale-Hollywood International",
    "MSP": "Minneapolis-Saint Paul International",
    "LGA": "LaGuardia",
    "DTW": "Detroit Metropolitan Wayne County",
    "PHL": "Philadelphia International",
    "SLC": "Salt Lake City International",
    "BWI": "Baltimore/Washington International",
    "IAD": "Washington Dulles International",
    "SAN": "San Diego International",
    "DCA": "Ronald Reagan Washington National",
    "TPA": "Tampa International",
    "BNA": "Nashville International",
    "AUS": "Austin-Bergstrom International",
    "MDW": "Chicago Midway International",
    "HNL": "Daniel K. Inouye International",
    "DAL": "Dallas Love Field",
    "PDX": "Portland International",
    "STL": "St. Louis Lambert International",
    "HOU": "William P. Hobby",
    "SMF": "Sacramento International",
    "SJC": "San Jose Mineta International",
    "OAK": "Oakland International",
    "RDU": "Raleigh-Durham International",
    "BDL": "Bradley International",
}


def display(code: str) -> str:
    """Return the official display name for an airport code, or the code itself."""
    norm = (code or "").strip().upper()
    if norm in DISPLAY:
        return DISPLAY[norm]
    return norm or (code or "")


def spoken(code: str) -> str:
    """Return the spoken name for an airport code, or spaced letters + 'airport'."""
    norm = (code or "").strip().upper()
    if norm in AIRPORTS:
        return AIRPORTS[norm][0]
    if not norm:
        return "unknown airport"
    return f"{' '.join(norm)} airport"


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometers between two WGS84 points."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_airport(lat: float, lon: float, max_km: float = 150.0) -> Optional[str]:
    """Return spoken name of nearest known airport within max_km, or None."""
    best_name: Optional[str] = None
    best_dist = max_km
    for name, alat, alon in AIRPORTS.values():
        dist = _haversine_km(lat, lon, alat, alon)
        if dist <= best_dist:
            best_dist = dist
            best_name = name
    return best_name


# ---- AN6 screen round: time zones, short names, board list ----

# IANA time zone per airport (used for the local time on each disruption card).
TZ: dict[str, str] = {
    "ATL": "America/New_York", "DFW": "America/Chicago", "DEN": "America/Denver",
    "ORD": "America/Chicago", "LAX": "America/Los_Angeles", "JFK": "America/New_York",
    "LAS": "America/Los_Angeles", "MCO": "America/New_York", "MIA": "America/New_York",
    "CLT": "America/New_York", "SEA": "America/Los_Angeles", "PHX": "America/Phoenix",
    "EWR": "America/New_York", "SFO": "America/Los_Angeles", "IAH": "America/Chicago",
    "BOS": "America/New_York", "FLL": "America/New_York", "MSP": "America/Chicago",
    "LGA": "America/New_York", "DTW": "America/New_York", "PHL": "America/New_York",
    "SLC": "America/Denver", "BWI": "America/New_York", "IAD": "America/New_York",
    "SAN": "America/Los_Angeles", "DCA": "America/New_York", "TPA": "America/New_York",
    "BNA": "America/Chicago", "AUS": "America/Chicago", "MDW": "America/Chicago",
    "HNL": "Pacific/Honolulu", "DAL": "America/Chicago", "PDX": "America/Los_Angeles",
    "STL": "America/Chicago", "HOU": "America/Chicago", "SMF": "America/Los_Angeles",
    "SJC": "America/Los_Angeles", "OAK": "America/Los_Angeles", "RDU": "America/New_York",
    "BDL": "America/New_York",
}

# AIRPORTS is in traffic order (FAA 2024 boardings); the board uses the first 30.
BUSIEST_30: list[str] = list(AIRPORTS.keys())[:30]

# Short names for the board tiles.
SHORT: dict[str, str] = {
    "ATL": "Atlanta", "DFW": "Dallas-Ft Worth", "DEN": "Denver", "ORD": "Chicago O'Hare",
    "LAX": "Los Angeles", "JFK": "New York JFK", "LAS": "Las Vegas", "MCO": "Orlando",
    "MIA": "Miami", "CLT": "Charlotte", "SEA": "Seattle", "PHX": "Phoenix",
    "EWR": "Newark", "SFO": "San Francisco", "IAH": "Houston Bush", "BOS": "Boston",
    "FLL": "Ft Lauderdale", "MSP": "Minneapolis", "LGA": "LaGuardia", "DTW": "Detroit",
    "PHL": "Philadelphia", "SLC": "Salt Lake City", "BWI": "Baltimore", "IAD": "Dulles",
    "SAN": "San Diego", "DCA": "Reagan", "TPA": "Tampa", "BNA": "Nashville",
    "AUS": "Austin", "MDW": "Chicago Midway",
}
