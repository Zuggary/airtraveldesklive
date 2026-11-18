from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Optional

# 40 busiest US airports (plus BDL), then the next-busiest ones: code -> (spoken_name, lat, lon)
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
    "SNA": ("John Wayne Santa Ana", 33.676, -117.868),
    "MSY": ("New Orleans Louis Armstrong", 29.993, -90.258),
    "PIT": ("Pittsburgh International", 40.491, -80.233),
    "IND": ("Indianapolis International", 39.717, -86.294),
    "CMH": ("Columbus John Glenn", 39.998, -82.892),
    "CLE": ("Cleveland Hopkins", 41.411, -81.850),
    "MCI": ("Kansas City International", 39.298, -94.714),
    "SAT": ("San Antonio International", 29.534, -98.470),
    "OGG": ("Maui Kahului", 20.899, -156.430),
    "BUR": ("Burbank Hollywood Burbank", 34.201, -118.359),
    "ONT": ("Ontario International", 34.056, -117.601),
    "LGB": ("Long Beach", 33.818, -118.152),
    "RSW": ("Fort Myers Southwest Florida", 26.536, -81.755),
    "JAX": ("Jacksonville International", 30.494, -81.688),
    "MKE": ("Milwaukee Mitchell", 42.947, -87.897),
    "ABQ": ("Albuquerque Sunport", 35.040, -106.609),
    "BOI": ("Boise", 43.564, -116.223),
    "OMA": ("Omaha Eppley", 41.303, -95.894),
    "RNO": ("Reno-Tahoe", 39.499, -119.768),
    "TUS": ("Tucson International", 32.116, -110.941),
    "ELP": ("El Paso International", 31.807, -106.378),
    "PVD": ("Providence T. F. Green", 41.724, -71.428),
    "ALB": ("Albany International", 42.748, -73.802),
    "BUF": ("Buffalo Niagara", 42.941, -78.732),
    "ORF": ("Norfolk International", 36.895, -76.201),
    "RIC": ("Richmond International", 37.505, -77.320),
    "CHS": ("Charleston International", 32.899, -80.041),
    "SAV": ("Savannah Hilton Head", 32.128, -81.202),
    "MEM": ("Memphis International", 35.042, -89.977),
    "SDF": ("Louisville Muhammad Ali", 38.174, -85.736),
    "OKC": ("Oklahoma City Will Rogers", 35.393, -97.601),
    "TUL": ("Tulsa International", 36.198, -95.888),
    "DJT": ("President Donald J. Trump International Airport", 26.6832, -80.0956),
    "CVG": ("Cincinnati Northern Kentucky", 39.049, -84.668),
    "SRQ": ("Sarasota Bradenton", 27.395, -82.554),
    "DSM": ("Des Moines International", 41.534, -93.663),
    "GEG": ("Spokane International", 47.620, -117.534),
    "ICT": ("Wichita Eisenhower", 37.650, -97.433),
    "MHT": ("Manchester Boston Regional", 42.933, -71.436),
    "PWM": ("Portland Jetport, Maine", 43.646, -70.309),
    "BTV": ("Burlington International", 44.472, -73.153),
    "ANC": ("Anchorage Ted Stevens", 61.174, -149.996),
    "COS": ("Colorado Springs", 38.806, -104.701),
    "GSO": ("Greensboro Piedmont Triad", 36.098, -79.937),
    "BHM": ("Birmingham-Shuttlesworth", 33.563, -86.754),
    "LIT": ("Little Rock", 34.729, -92.224),
    "GRR": ("Grand Rapids Ford", 42.881, -85.523),
    "DAY": ("Dayton International", 39.902, -84.219),
    "SYR": ("Syracuse Hancock", 43.111, -76.106),
    "ROC": ("Rochester International", 43.119, -77.672),
    "TYS": ("Knoxville McGhee Tyson", 35.811, -83.994),
    "PSP": ("Palm Springs", 33.83, -116.507),
    "MSN": ("Madison Dane County", 43.14, -89.338),
    "LEX": ("Lexington Blue Grass", 38.037, -84.606),
    "HSV": ("Huntsville International", 34.637, -86.775),
    "FAT": ("Fresno Yosemite", 36.776, -119.718),
    "MYR": ("Myrtle Beach", 33.68, -78.928),
    "KOA": ("Kona", 19.739, -156.046),
    "LIH": ("Lihue Kauai", 21.976, -159.339),
    "PNS": ("Pensacola International", 30.473, -87.187),
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
    "SNA": "John Wayne Airport, Orange County",
    "MSY": "Louis Armstrong New Orleans International",
    "PIT": "Pittsburgh International",
    "IND": "Indianapolis International",
    "CMH": "John Glenn Columbus International",
    "CLE": "Cleveland Hopkins International",
    "MCI": "Kansas City International",
    "SAT": "San Antonio International",
    "OGG": "Kahului Airport, Maui",
    "BUR": "Hollywood Burbank Airport",
    "ONT": "Ontario International",
    "LGB": "Long Beach Airport",
    "RSW": "Southwest Florida International",
    "JAX": "Jacksonville International",
    "MKE": "General Mitchell International",
    "ABQ": "Albuquerque International Sunport",
    "BOI": "Boise Airport",
    "OMA": "Eppley Airfield, Omaha",
    "RNO": "Reno-Tahoe International",
    "TUS": "Tucson International",
    "ELP": "El Paso International",
    "PVD": "T. F. Green International, Providence",
    "ALB": "Albany International",
    "BUF": "Buffalo Niagara International",
    "ORF": "Norfolk International",
    "RIC": "Richmond International",
    "CHS": "Charleston International",
    "SAV": "Savannah/Hilton Head International",
    "MEM": "Memphis International",
    "SDF": "Louisville Muhammad Ali International",
    "OKC": "Will Rogers World Airport, Oklahoma City",
    "TUL": "Tulsa International",
    "DJT": "President Donald J. Trump International Airport",
    "CVG": "Cincinnati/Northern Kentucky International",
    "SRQ": "Sarasota-Bradenton International",
    "DSM": "Des Moines International",
    "GEG": "Spokane International",
    "ICT": "Wichita Dwight D. Eisenhower National",
    "MHT": "Manchester-Boston Regional",
    "PWM": "Portland International Jetport",
    "BTV": "Burlington International",
    "ANC": "Ted Stevens Anchorage International",
    "COS": "Colorado Springs Airport",
    "GSO": "Piedmont Triad International",
    "BHM": "Birmingham-Shuttlesworth International",
    "LIT": "Bill and Hillary Clinton National",
    "GRR": "Gerald R. Ford International",
    "DAY": "James M. Cox Dayton International",
    "SYR": "Syracuse Hancock International",
    "ROC": "Frederick Douglass Greater Rochester International",
    "TYS": "McGhee Tyson Airport, Knoxville",
    "PSP": "Palm Springs International",
    "MSN": "Dane County Regional, Madison",
    "LEX": "Blue Grass Airport, Lexington",
    "HSV": "Huntsville International",
    "FAT": "Fresno Yosemite International",
    "MYR": "Myrtle Beach International",
    "KOA": "Kona International, Ellison Onizuka",
    "LIH": "Lihue Airport, Kauai",
    "PNS": "Pensacola International",
}


# ---- AN-names: every other US airport (OurAirports, public domain) so no card shows a bare code ----
_NAMES_PATH = Path(__file__).resolve().parent.parent / "data" / "airport-names.json"
_NAMES: Optional[dict[str, list[str]]] = None


def _names() -> dict[str, list[str]]:
    """code -> [name, city, state] for US airports, loaded once; {} if the data file is missing."""
    global _NAMES
    if _NAMES is None:
        try:
            _NAMES = json.loads(_NAMES_PATH.read_text(encoding="utf-8")).get("airports", {})
        except (OSError, ValueError):
            _NAMES = {}
    return _NAMES


def canonical_code(code: str | None) -> str:
    """Normalize West Palm Beach feed identifiers to the public airport code."""
    norm = (code or "").strip().upper()
    return "DJT" if norm in {"PBI", "KPBI", "KDJT"} else norm


def airport_rows(rows: dict | None) -> dict:
    """Normalize airport-keyed data, preferring a canonical entry over its aliases."""
    rows = rows or {}
    return {canonical_code(code): rows.get(canonical_code(code), row) for code, row in rows.items()}


def full_name(code: str) -> Optional[str]:
    """Official name of any US airport ('Teterboro Airport'), or None if the code is unknown."""
    norm = canonical_code(code)
    if norm in DISPLAY:
        return DISPLAY[norm]
    row = _names().get(norm)
    return row[0] if row else None


def city_state(code: str) -> str:
    """'Teterboro, NJ' for any US airport we know, else ''."""
    row = _names().get(canonical_code(code))
    if not row:
        return ""
    return ", ".join(x for x in (row[1], row[2]) if x)


def display(code: str) -> str:
    """Return the official display name for an airport code, or the code itself."""
    norm = canonical_code(code)
    name = full_name(norm)
    if name:
        return name
    return norm or (code or "")


def spoken(code: str) -> str:
    """Return the spoken name for an airport code; the full name for other US airports; else spaced letters + 'airport'."""
    norm = canonical_code(code)
    if norm in AIRPORTS:
        return AIRPORTS[norm][0]
    if not norm:
        return "unknown airport"
    name = full_name(norm)
    if name:
        return name
    return f"{' '.join(norm)} airport"


def label(code: str) -> str:
    """'TEB (Teterboro Airport)' for airports outside the 100 on the board, plain code for the 100 (their names are on screen)."""
    norm = canonical_code(code)
    if norm in AIRPORTS or not norm:
        return norm
    name = full_name(norm)
    return f"{norm} ({name})" if name else norm


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
    "SNA": "America/Los_Angeles",
    "MSY": "America/Chicago",
    "PIT": "America/New_York",
    "IND": "America/Indiana/Indianapolis",
    "CMH": "America/New_York",
    "CLE": "America/New_York",
    "MCI": "America/Chicago",
    "SAT": "America/Chicago",
    "OGG": "Pacific/Honolulu",
    "BUR": "America/Los_Angeles",
    "ONT": "America/Los_Angeles",
    "LGB": "America/Los_Angeles",
    "RSW": "America/New_York",
    "JAX": "America/New_York",
    "MKE": "America/Chicago",
    "ABQ": "America/Denver",
    "BOI": "America/Boise",
    "OMA": "America/Chicago",
    "RNO": "America/Los_Angeles",
    "TUS": "America/Phoenix",
    "ELP": "America/Denver",
    "PVD": "America/New_York",
    "ALB": "America/New_York",
    "BUF": "America/New_York",
    "ORF": "America/New_York",
    "RIC": "America/New_York",
    "CHS": "America/New_York",
    "SAV": "America/New_York",
    "MEM": "America/Chicago",
    "SDF": "America/Kentucky/Louisville",
    "OKC": "America/Chicago",
    "TUL": "America/Chicago",
    "DJT": "America/New_York",
    "CVG": "America/New_York",
    "SRQ": "America/New_York",
    "DSM": "America/Chicago",
    "GEG": "America/Los_Angeles",
    "ICT": "America/Chicago",
    "MHT": "America/New_York",
    "PWM": "America/New_York",
    "BTV": "America/New_York",
    "ANC": "America/Anchorage",
    "COS": "America/Denver",
    "GSO": "America/New_York",
    "BHM": "America/Chicago",
    "LIT": "America/Chicago",
    "GRR": "America/Detroit",
    "DAY": "America/New_York",
    "SYR": "America/New_York",
    "ROC": "America/New_York",
    "TYS": "America/New_York",
    "PSP": "America/Los_Angeles",
    "MSN": "America/Chicago",
    "LEX": "America/New_York",
    "HSV": "America/Chicago",
    "FAT": "America/Los_Angeles",
    "MYR": "America/New_York",
    "KOA": "Pacific/Honolulu",
    "LIH": "Pacific/Honolulu",
    "PNS": "America/Chicago",
}

# AIRPORTS is in traffic order (FAA 2024 boardings); the board uses the first 30.
BUSIEST_30: list[str] = list(AIRPORTS.keys())[:30]

# AN15 Stage 2: the board shows the first 100 of AIRPORTS (traffic rank order, rank 1 = ATL).
BUSIEST_100: list[str] = list(AIRPORTS.keys())[:100]

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
    "SNA": "John Wayne",
    "MSY": "New Orleans",
    "PIT": "Pittsburgh",
    "IND": "Indianapolis",
    "CMH": "Columbus",
    "CLE": "Cleveland",
    "MCI": "Kansas City",
    "SAT": "San Antonio",
    "OGG": "Maui",
    "BUR": "Burbank",
    "ONT": "Ontario CA",
    "LGB": "Long Beach",
    "RSW": "Fort Myers",
    "JAX": "Jacksonville",
    "MKE": "Milwaukee",
    "ABQ": "Albuquerque",
    "BOI": "Boise",
    "OMA": "Omaha",
    "RNO": "Reno",
    "TUS": "Tucson",
    "ELP": "El Paso",
    "PVD": "Providence",
    "ALB": "Albany",
    "BUF": "Buffalo",
    "ORF": "Norfolk",
    "RIC": "Richmond",
    "CHS": "Charleston",
    "SAV": "Savannah",
    "MEM": "Memphis",
    "SDF": "Louisville",
    "OKC": "Oklahoma City",
    "TUL": "Tulsa",
    "DJT": "West Palm Beach",
    "CVG": "Cincinnati",
    "SRQ": "Sarasota",
    "DSM": "Des Moines",
    "GEG": "Spokane",
    "ICT": "Wichita",
    "MHT": "Manchester NH",
    "PWM": "Portland ME",
    "BTV": "Burlington VT",
    "ANC": "Anchorage",
    "COS": "Colorado Springs",
    "GSO": "Greensboro",
    "SJC": "San Jose",
    "STL": "St. Louis",
    "PDX": "Portland",
    "RDU": "Raleigh-Durham",
    "OAK": "Oakland",
    "DAL": "Dallas Love",
    "BDL": "Hartford",
    "HOU": "Houston Hobby",
    "HNL": "Honolulu",
    "SMF": "Sacramento",
    "BHM": "Birmingham",
    "LIT": "Little Rock",
    "GRR": "Grand Rapids",
    "DAY": "Dayton",
    "SYR": "Syracuse",
    "ROC": "Rochester NY",
    "TYS": "Knoxville",
    "PSP": "Palm Springs",
    "MSN": "Madison",
    "LEX": "Lexington",
    "HSV": "Huntsville",
    "FAT": "Fresno",
    "MYR": "Myrtle Beach",
    "KOA": "Kona",
    "LIH": "Kauai",
    "PNS": "Pensacola",
}


# City and state labels for the search box and the page subtitles. A label only (AN23: 100 airports).
CITY: dict[str, str] = {
    "ATL": "Atlanta, GA", "DFW": "Dallas-Fort Worth, TX", "DEN": "Denver, CO", "ORD": "Chicago, IL",
    "LAX": "Los Angeles, CA", "JFK": "New York, NY", "LAS": "Las Vegas, NV", "MCO": "Orlando, FL",
    "MIA": "Miami, FL", "CLT": "Charlotte, NC", "SEA": "Seattle, WA", "PHX": "Phoenix, AZ",
    "EWR": "Newark, NJ", "SFO": "San Francisco, CA", "IAH": "Houston, TX", "BOS": "Boston, MA",
    "FLL": "Fort Lauderdale, FL", "MSP": "Minneapolis, MN", "LGA": "New York, NY", "DTW": "Detroit, MI",
    "PHL": "Philadelphia, PA", "SLC": "Salt Lake City, UT", "BWI": "Baltimore, MD", "IAD": "Washington, DC",
    "SAN": "San Diego, CA", "DCA": "Washington, DC", "TPA": "Tampa, FL", "BNA": "Nashville, TN",
    "AUS": "Austin, TX", "MDW": "Chicago, IL",
    "HNL": "Honolulu, HI", "DAL": "Dallas, TX", "PDX": "Portland, OR", "STL": "St. Louis, MO",
    "HOU": "Houston, TX", "SMF": "Sacramento, CA", "SJC": "San Jose, CA", "OAK": "Oakland, CA",
    "RDU": "Raleigh-Durham, NC", "BDL": "Hartford, CT", "SNA": "Santa Ana, CA", "MSY": "New Orleans, LA",
    "PIT": "Pittsburgh, PA", "IND": "Indianapolis, IN", "CMH": "Columbus, OH", "CLE": "Cleveland, OH",
    "MCI": "Kansas City, MO", "SAT": "San Antonio, TX", "OGG": "Kahului, HI", "BUR": "Burbank, CA",
    "ONT": "Ontario, CA", "LGB": "Long Beach, CA", "RSW": "Fort Myers, FL", "JAX": "Jacksonville, FL",
    "MKE": "Milwaukee, WI", "ABQ": "Albuquerque, NM", "BOI": "Boise, ID", "OMA": "Omaha, NE",
    "RNO": "Reno, NV", "TUS": "Tucson, AZ", "ELP": "El Paso, TX", "PVD": "Providence, RI",
    "ALB": "Albany, NY", "BUF": "Buffalo, NY", "ORF": "Norfolk, VA", "RIC": "Richmond, VA",
    "CHS": "Charleston, SC", "SAV": "Savannah, GA", "MEM": "Memphis, TN", "SDF": "Louisville, KY",
    "OKC": "Oklahoma City, OK", "TUL": "Tulsa, OK", "DJT": "West Palm Beach, FL", "CVG": "Cincinnati, OH",
    "SRQ": "Sarasota, FL", "DSM": "Des Moines, IA", "GEG": "Spokane, WA", "ICT": "Wichita, KS",
    "MHT": "Manchester, NH", "PWM": "Portland, ME", "BTV": "Burlington, VT", "ANC": "Anchorage, AK",
    "COS": "Colorado Springs, CO", "GSO": "Greensboro, NC", "BHM": "Birmingham, AL", "LIT": "Little Rock, AR",
    "GRR": "Grand Rapids, MI", "DAY": "Dayton, OH", "SYR": "Syracuse, NY", "ROC": "Rochester, NY",
    "TYS": "Knoxville, TN", "PSP": "Palm Springs, CA", "MSN": "Madison, WI", "LEX": "Lexington, KY",
    "HSV": "Huntsville, AL", "FAT": "Fresno, CA", "MYR": "Myrtle Beach, SC", "KOA": "Kailua-Kona, HI",
    "LIH": "Lihue, HI", "PNS": "Pensacola, FL",
}
