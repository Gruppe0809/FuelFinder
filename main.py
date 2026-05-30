"""
FuelFinder - Streamlit web app for comparing live fuel prices in Germany, Austria and Switzerland.

Mode 1 (Find nearby): type a location, choose a radius, see a map with the cheapest stations.
Mode 2 (Trip planner): enter start + destination, we find the cheapest stops along the route.

Run with: streamlit run main.py
HSG Programming - Introduction Level, Group 4495
"""

# ===========================================================================
# 1. IMPORTS & SETUP
# ===========================================================================

# these are all the external libraries we need
# each one needs to be installed with pip (see requirements.txt)

import math                           # standard Python math library - we use it for the distance formula
import os                             # lets us read environment variables like API keys
from concurrent.futures import ThreadPoolExecutor, as_completed  # for running multiple API calls at the same time (parallel)
from dataclasses import dataclass, field  # dataclass is a Python feature that makes it easier to define simple data containers
from typing import Optional           # Optional[X] means a variable can be either type X or None

import certifi                        # provides SSL certificates so HTTPS requests work on macOS
import folium                         # library for creating interactive maps (uses Leaflet.js under the hood)
import pandas as pd                   # used for creating the results table (DataFrame)
import requests                       # standard library for making HTTP requests to web APIs
import streamlit as st                # the main web app framework - handles the UI, routing, and state
from dotenv import load_dotenv        # reads key=value pairs from the .env file into the environment
from geopy.geocoders import Nominatim # geocoder from OpenStreetMap - converts addresses to GPS coordinates
from streamlit_folium import st_folium  # a bridge component that embeds folium maps inside a Streamlit page
from streamlit_searchbox import st_searchbox  # a Streamlit component that adds an autocomplete search box
from urllib.parse import quote as url_quote   # encodes special characters in strings so they can be used in URLs (e.g. spaces become %20)

# macOS ships Python without trusting the usual system SSL certificates
# this tells the requests library where to find a trusted certificate bundle
# without this, any HTTPS request on macOS might throw an "SSL verify failed" error
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

# import shared settings from config.py - we put all configurable values there
# so they are easy to change without hunting through the code
from config import (
    DEFAULT_FUEL_TYPE,        # which fuel type is selected when the app loads (E5)
    DEFAULT_RADIUS_KM,        # default search radius shown in the slider
    FUEL_TYPES,               # list of all supported fuel types: ["E5", "E10", "Diesel"]
    MAX_RADIUS_KM,            # the maximum value the radius slider can go to
    OSRM_URL,                 # URL of the backup routing server (used if Mapbox token is missing)
    ROUTE_CORRIDOR_KM,        # a station is only included if it's within this many km of the route
    ROUTE_SAMPLE_INTERVAL_KM, # we check for stations every X km along the route
    TOP_N_RESULTS,            # only show this many stations in the results table
)

# ---------------------------------------------------------------------------
# Custom CSS - injected into the page to override Streamlit's default styling
# We use this to get a dark GitHub-style theme with orange accent colours
# ---------------------------------------------------------------------------
_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

/* use Inter (a clean modern sans-serif font) everywhere on the page */
html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
}

/* hide the default Streamlit hamburger menu and footer bar */
#MainMenu, footer { visibility: hidden; }
[data-testid="stToolbar"]    { display: none !important; }
[data-testid="stDecoration"] { display: none !important; }

/* dark navy background for the whole app */
.stApp { background: #0D1117; }

/* tighten padding and set a max width for the main content area */
.main .block-container {
    padding-top: 2.5rem !important;
    padding-left: 3rem   !important;
    padding-right: 3rem  !important;
    max-width: 1400px    !important;
}

/* dark sidebar with a subtle right border */
[data-testid="stSidebar"] > div:first-child {
    background: #010409 !important;
    border-right: 1px solid #21262D !important;
    padding: 2rem 1.5rem !important;
}

/* hide the sidebar collapse/expand toggle button */
[data-testid="collapsedControl"],
button[kind="header"][aria-label="Close sidebar"],
section[data-testid="stSidebar"] > div > button {
    display: none !important;
}

/* orange gradient for the Search / Plan trip buttons */
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #F97316 0%, #DC6309 100%) !important;
    color: #fff !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    font-size: 0.875rem !important;
    padding: 0.55rem 1.6rem !important;
    letter-spacing: 0.2px !important;
    box-shadow: 0 2px 8px rgba(249,115,22,0.25) !important;
    transition: all 0.2s ease !important;
}
/* slight lift effect when hovering over the button */
.stButton > button[kind="primary"]:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 5px 18px rgba(249,115,22,0.45) !important;
}
.stButton > button[kind="primary"]:active {
    transform: translateY(0) !important;
}

/* dark card style for the metric boxes (distance, cost, stops) */
[data-testid="metric-container"] {
    background: #161B22 !important;
    border: 1px solid #21262D !important;
    border-radius: 14px !important;
    padding: 1.25rem 1.4rem !important;
}
[data-testid="stMetricValue"] {
    font-size: 1.75rem !important;
    font-weight: 700 !important;
    letter-spacing: -0.5px !important;
    color: #E6EDF3 !important;
}
[data-testid="stMetricLabel"] > div {
    font-size: 0.65rem !important;
    font-weight: 700 !important;
    text-transform: uppercase !important;
    letter-spacing: 1.2px !important;
    color: #6E7681 !important;
}
[data-testid="stMetricDelta"] > div {
    font-size: 0.8rem !important;
    font-weight: 600 !important;
}

/* orange progress bar used during trip planning */
.stProgress > div > div > div > div {
    background: linear-gradient(90deg, #F97316, #DC6309) !important;
    border-radius: 4px !important;
}

/* rounded corners on info/warning/error boxes */
[data-testid="stAlert"] { border-radius: 10px !important; }

/* expander (collapsible section) styling */
details summary {
    border-radius: 8px !important;
    font-weight: 500 !important;
    font-size: 0.875rem !important;
}

/* subtle horizontal divider lines */
hr {
    border-color: #21262D !important;
    margin: 1rem 0 !important;
}

/* rounded border around data tables */
[data-testid="stDataFrame"] > div {
    border: 1px solid #21262D !important;
    border-radius: 12px !important;
    overflow: hidden !important;
}

/* smaller grey caption text */
.stCaption p { color: #6E7681 !important; font-size: 0.78rem !important; }

/* large page title + subtitle at the top of each mode */
.ff-page-header { margin-bottom: 2rem; }
.ff-page-header h1 {
    font-size: 2rem;
    font-weight: 800;
    letter-spacing: -0.8px;
    color: #E6EDF3;
    margin: 0 0 0.3rem 0;
    line-height: 1.15;
}
.ff-page-header p {
    color: #6E7681;
    font-size: 0.9rem;
    margin: 0;
    font-weight: 400;
}

/* small uppercase section label (used above the map and table) */
.ff-section {
    font-size: 0.65rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: #6E7681;
    margin: 2rem 0 0.75rem 0;
    padding-bottom: 0.6rem;
    border-bottom: 1px solid #21262D;
}

/* "FuelFinder" logo text in the sidebar */
.ff-brand-name {
    font-size: 1.3rem;
    font-weight: 800;
    letter-spacing: -0.5px;
    color: #E6EDF3;
    margin: 0;
}
.ff-brand-tag {
    font-size: 0.75rem;
    color: #6E7681;
    margin: 0.15rem 0 0 0;
    font-weight: 400;
}

/* navigation pill buttons in the sidebar */
.ff-nav-pill {
    display: block;
    padding: 0.6rem 1rem;
    border-radius: 8px;
    font-size: 0.875rem;
    font-weight: 500;
    color: #8B949E;
    cursor: pointer;
    transition: all 0.15s;
    margin-bottom: 4px;
    text-decoration: none;
}
.ff-nav-pill.active {
    background: #21262D;
    color: #E6EDF3;
    font-weight: 600;
}

/* small footer text at the bottom of the sidebar */
.ff-sidebar-footer {
    font-size: 0.72rem;
    color: #484F58;
    line-height: 1.8;
}
.ff-sidebar-footer a {
    color: #6E7681;
    text-decoration: none;
}
.ff-sidebar-footer a:hover { color: #E6EDF3; }

/* rounded badge showing number of results */
.ff-result-count {
    display: inline-block;
    background: #21262D;
    color: #8B949E;
    border-radius: 20px;
    padding: 0.25rem 0.75rem;
    font-size: 0.78rem;
    font-weight: 600;
    margin-bottom: 1rem;
}
</style>
"""

# load our API keys from the .env file
# after this line, os.getenv("TANKERKOENIG_API_KEY") and os.getenv("MAPBOX_TOKEN") will work
load_dotenv()

# ---------------------------------------------------------------------------
# API endpoint URLs - the web addresses we send requests to
# ---------------------------------------------------------------------------
TANKERKOENIG_URL    = "https://creativecommons.tankerkoenig.de/json/list.php"       # German fuel prices
ECONTROL_URL        = "https://api.e-control.at/sprit/1.0/search/gas-stations/by-address"  # Austrian fuel prices
OVERPASS_URL        = "https://overpass-api.de/api/interpreter"                     # OpenStreetMap data (Switzerland)
MAPBOX_GEOCODING_URL  = "https://api.mapbox.com/geocoding/v5/mapbox.places"         # address -> coordinates
MAPBOX_DIRECTIONS_URL = "https://api.mapbox.com/directions/v5/mapbox/driving"       # route planning

# many public APIs require a User-Agent header so they can identify who is making the request
# this is a requirement for Nominatim and Overpass - they block requests without it
USER_AGENT = "FuelFinder/2.0 (HSG Group 4495 - student project)"

# Tankerkoenig won't accept a radius larger than 25 km - it's a hard API limit
TANKERKOENIG_MAX_RADIUS = 25

# rough geographic bounding boxes for each country
# format: (min_latitude, max_latitude, min_longitude, max_longitude)
# we use these to quickly skip API calls for countries the user isn't searching near
_DE_BBOX = (47.3, 55.1,  5.9, 15.0)  # Germany
_AT_BBOX = (46.4, 49.0,  9.5, 17.2)  # Austria
_CH_BBOX = (45.8, 47.9,  5.9, 10.5)  # Switzerland


def _near_country(lat: float, lon: float, radius_km: float,
                  bbox: tuple[float, float, float, float]) -> bool:
    """
    Returns True if the search circle (centre lat/lon, radius in km) might overlap with the country.
    We use this to avoid calling an API for a country that is clearly not in the search area.
    For example if someone searches near Paris, we skip the Austria and Switzerland APIs entirely.
    """
    lat_min, lat_max, lon_min, lon_max = bbox

    # 1 degree of latitude is roughly 111 km, so we divide by 111 to convert km to degrees
    # this gives us a rough "buffer" in degrees around the search point
    buf = radius_km / 111.0

    # check if the search circle (with buffer) overlaps the country's bounding box
    return (lat - buf < lat_max and lat + buf > lat_min and
            lon - buf < lon_max and lon + buf > lon_min)


# ---------------------------------------------------------------------------
# Functions to retrieve API keys
# We check the .env file first (local development), then Streamlit Cloud secrets
# ---------------------------------------------------------------------------

def get_api_key() -> str:
    """Returns the Tankerkoenig API key as a string, or '' if it's not configured."""
    # os.getenv reads the value from the environment (loaded from .env by load_dotenv above)
    key = os.getenv("TANKERKOENIG_API_KEY", "").strip()
    if key:
        return key
    # if running on Streamlit Cloud, secrets are managed through their dashboard instead of .env
    try:
        return st.secrets.get("TANKERKOENIG_API_KEY", "").strip()
    except Exception:
        return ""  # return empty string if neither source has the key


def get_mapbox_token() -> str:
    """Returns the Mapbox access token as a string, or '' if it's not configured."""
    token = os.getenv("MAPBOX_TOKEN", "").strip()
    if token:
        return token
    try:
        return st.secrets.get("MAPBOX_TOKEN", "").strip()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Mapbox address autocomplete
# ---------------------------------------------------------------------------

# this dictionary stores geocoding results as the user types in the search box
# key = the address string the user sees, value = GeoResult with lat/lon
# we cache them here so we don't need to call the API again when the user clicks Search
_geo_cache: dict[str, "GeoResult"] = {}


def _mapbox_suggestions(query: str) -> list[str]:
    """
    This function is called automatically every time the user types a character in the search box.
    It sends the partial query to Mapbox and returns a list of up to 5 matching place name strings.
    The coordinates for each suggestion are saved in _geo_cache for later use.
    """
    # don't bother calling the API if the user has only typed 1 character
    if len(query) < 2:
        return []

    token = get_mapbox_token()
    if not token:
        return []  # can't use Mapbox without a token

    # the address text needs to be URL-encoded before we can put it in the request URL
    # e.g. "St. Gallen" becomes "St.%20Gallen" (spaces are not allowed raw in URLs)
    url = f"{MAPBOX_GEOCODING_URL}/{url_quote(query, safe='')}.json"

    try:
        # send the request with a 5-second timeout so the UI doesn't hang
        resp = requests.get(url, params={"access_token": token, "limit": 5}, timeout=5)
        data = resp.json()  # parse the JSON response into a Python dictionary
    except Exception:
        return []  # if anything goes wrong (network error, timeout etc.) return nothing

    results = []
    # "features" is the list of matching locations in the Mapbox response
    for f in data.get("features", []):
        name = f["place_name"]   # the full human-readable address string
        lon, lat = f["center"]   # Mapbox gives coordinates as [longitude, latitude] (note the reversed order!)

        # save the coordinates so we can look them up instantly when the user clicks Search
        _geo_cache[name] = GeoResult(lat=lat, lon=lon, address=name)
        results.append(name)

    return results  # Streamlit will show these as dropdown options


def _mapbox_tile_url() -> Optional[str]:
    """
    Returns the URL template for Mapbox Streets map tiles (the visual background of the map).
    Folium replaces {z}, {x}, {y} with the actual tile coordinates when loading the map.
    Returns None if no Mapbox token is set - folium will use free OpenStreetMap tiles instead.
    """
    token = get_mapbox_token()
    if not token:
        return None
    # the double braces {{ }} in an f-string produce literal { } characters
    # we need this because folium expects {z}/{x}/{y} as placeholders in the URL
    return (
        f"https://api.mapbox.com/styles/v1/mapbox/streets-v12/tiles/256"
        f"/{{z}}/{{x}}/{{y}}?access_token={token}"
    )


# ===========================================================================
# 2. DATA LAYER — data classes, geocoding, distance, country fetchers
# ===========================================================================

# We use Python dataclasses to define simple data containers
# A dataclass is basically a class where you just declare the fields - Python handles __init__ etc.

@dataclass
class GeoResult:
    """Stores the result of converting an address into GPS coordinates."""
    lat: float      # latitude (north-south position)
    lon: float      # longitude (east-west position)
    address: str    # the full address string as returned by the geocoder


@dataclass
class FetchResult:
    """
    Holds the output from one of our country fetcher functions (fetch_germany, etc.).
    stations: a list of dictionaries, one per fuel station found
    warnings: a list of warning messages to show the user (e.g. "API key missing")
    """
    # field(default_factory=list) means each new FetchResult gets its own empty list
    # (if we just wrote stations: list = [] all instances would share the same list, which would cause bugs)
    stations: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def extend(self, other: "FetchResult") -> None:
        """Merge the stations and warnings from another FetchResult into this one."""
        self.stations.extend(other.stations)
        self.warnings.extend(other.warnings)


# ---------------------------------------------------------------------------
# Distance calculation using the Haversine formula
# ---------------------------------------------------------------------------

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculates the straight-line distance in km between two GPS coordinates.

    We can't just use Pythagoras (a^2 + b^2 = c^2) here because the Earth is a sphere,
    not a flat surface. The Haversine formula accounts for the Earth's curvature and gives
    accurate results for short and medium distances.
    """
    R = 6371.0  # Earth's average radius in km

    # Python's math.sin/cos work in radians, but GPS coordinates are in degrees
    # so we convert: radians = degrees * pi / 180  (math.radians does this for us)
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)   # difference in latitude, converted to radians
    dlmb = math.radians(lon2 - lon1)   # difference in longitude, converted to radians

    # the actual Haversine formula
    # 'a' is a intermediate value between 0 and 1 representing the square of half the chord length
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2

    # convert 'a' to a distance in km
    return 2 * R * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Geocoding — convert a text address to GPS coordinates
# ---------------------------------------------------------------------------

# @st.cache_data tells Streamlit to remember the result of this function
# if the same query is passed again within 86400 seconds (24 hours), it returns the cached result
# instead of calling the API again - this makes the app faster and avoids hitting API limits
@st.cache_data(ttl=86400, show_spinner=False)
def geocode(query: str) -> Optional[GeoResult]:
    """
    Converts a place name or address (like "Munich" or "8001 Zurich") into GPS coordinates.

    We try three options in order:
    1. Check if we already have it cached from the autocomplete search (fastest - no API call)
    2. Try the Mapbox Geocoding API (accurate, fast, needs token)
    3. Fall back to Nominatim/OpenStreetMap (free, no key needed, slightly slower)

    Returns None if the location can't be found anywhere.
    """
    # if the user selected this from the dropdown, we already saved the coordinates in _geo_cache
    # this is the most common case and avoids any API calls
    if query in _geo_cache:
        return _geo_cache[query]

    token = get_mapbox_token()
    if token:
        # use Mapbox - it's more accurate than Nominatim, especially for partial addresses
        url = f"{MAPBOX_GEOCODING_URL}/{url_quote(query, safe='')}.json"
        try:
            resp = requests.get(url, params={"access_token": token, "limit": 1}, timeout=10)
            data = resp.json()
            features = data.get("features", [])
            if not features:
                return None  # no results found for this query
            f = features[0]  # take the top result
            lon, lat = f["center"]  # important: Mapbox returns [longitude, latitude], not [latitude, longitude]
            return GeoResult(lat=lat, lon=lon, address=f["place_name"])
        except Exception:
            return None  # if the request fails for any reason, fall through to Nominatim

    # fallback: Nominatim is OpenStreetMap's free geocoding service - no registration needed
    geocoder = Nominatim(user_agent=USER_AGENT, timeout=10)
    try:
        location = geocoder.geocode(query)  # this sends the request to Nominatim
    except Exception:
        return None
    if location is None:
        return None  # Nominatim also couldn't find it
    return GeoResult(lat=location.latitude, lon=location.longitude, address=location.address)


# ---------------------------------------------------------------------------
# Country fetcher functions — one for each data source
# Each function fetches stations for one country and returns a FetchResult
# ---------------------------------------------------------------------------

# cache results for 5 minutes - fuel prices update frequently so we don't cache for too long
@st.cache_data(ttl=300, show_spinner=False)
def fetch_germany(lat: float, lon: float, radius_km: float, fuel_type: str) -> FetchResult:
    """
    Fetches live fuel prices from the German Tankerkoenig API.
    Returns a FetchResult with a list of stations (each station is a dictionary).
    Only returns stations that are currently open and have a price listed.
    Requires a free API key from creativecommons.tankerkoenig.de.
    """
    result = FetchResult()  # start with an empty result

    # if the search location is clearly not in Germany, skip the API call entirely
    if not _near_country(lat, lon, radius_km, _DE_BBOX):
        return result  # returns empty result - no stations, no warnings

    api_key = get_api_key()
    if not api_key:
        # no key = we can't use this API, add a warning so the user knows
        result.warnings.append("Germany skipped: TANKERKOENIG_API_KEY not set.")
        return result

    # the Tankerkoenig API silently ignores any radius above 25 km
    # so we cap it ourselves and tell the user if we had to reduce their radius
    capped = min(radius_km, TANKERKOENIG_MAX_RADIUS)
    if radius_km > TANKERKOENIG_MAX_RADIUS:
        result.warnings.append(
            f"Germany radius capped at {TANKERKOENIG_MAX_RADIUS} km (Tankerkoenig API limit)."
        )

    # build the query parameters for the API request
    # the API uses different names for fuel types (e5, e10, diesel) than we do (E5, E10, Diesel)
    params = {
        "lat": lat,
        "lng": lon,
        "rad": capped,
        "sort": "price",   # ask the API to return cheapest stations first
        "type": {"E5": "e5", "E10": "e10", "Diesel": "diesel"}[fuel_type],  # map our name to API name
        "apikey": api_key,
    }

    try:
        resp = requests.get(TANKERKOENIG_URL, params=params, timeout=15)
        resp.raise_for_status()  # this throws an exception if the server returns an error (4xx or 5xx)
        data = resp.json()       # convert the JSON response text into a Python dictionary
    except requests.RequestException as e:
        # something went wrong with the network request - add a warning and return empty
        result.warnings.append(f"Germany unavailable: {e}")
        return result

    # Tankerkoenig uses an "ok" field in the JSON to signal API-level errors
    # (e.g. invalid API key) rather than using HTTP error codes
    if not data.get("ok"):
        result.warnings.append(f"Germany unavailable: {data.get('message', 'unknown error')}")
        return result

    # loop through the list of stations in the API response
    for s in data.get("stations", []):
        # skip stations that are currently closed
        if not s.get("isOpen"):
            continue

        price = s.get("price")
        if not price:
            continue  # skip stations that don't have a price listed right now

        # the API returns address parts separately, so we join them into one readable string
        street = (s.get("street") or "").strip()
        house  = (s.get("houseNumber") or "").strip()
        post   = str(s.get("postCode") or "").strip()
        place  = (s.get("place") or "").strip()

        # add this station as a dictionary to our results list
        # we use the same dictionary structure for all three countries so the rest of the
        # code can treat them identically regardless of which API they came from
        result.stations.append({
            "name":        (s.get("name") or "Unknown").strip(),
            "brand":       (s.get("brand") or "").strip(),
            "address":     f"{street} {house}, {post} {place}".strip(", ").strip(),
            "country":     "DE",
            "lat":         s.get("lat"),
            "lon":         s.get("lng"),
            "price":       float(price),       # price per litre in euros
            "fuel_type":   fuel_type,
            "distance_km": float(s.get("dist", 0.0)),
            "source":      "Tankerkoenig",
        })

    return result


@st.cache_data(ttl=300, show_spinner=False)
def fetch_austria(lat: float, lon: float, radius_km: float, fuel_type: str) -> FetchResult:
    """
    Fetches Austrian fuel station data from the E-Control / Spritpreisrechner.at API.
    No API key needed - this is a free public government API.

    Two quirks to know about:
    1. The API ignores our radius and always returns the ~10 nearest stations,
       so we have to filter by distance ourselves after getting the response.
    2. Austria doesn't distinguish between E5 and E10 - both are just "Super 95" (SUP).
    3. Prices can be empty because Austrian law only allows price updates at 12:00, 14:00 and 16:00.
       Outside those times some stations may not have a current price listed.
    """
    result = FetchResult()

    # skip if not near Austria
    if not _near_country(lat, lon, radius_km, _AT_BBOX):
        return result

    # map our fuel type names to the names this API expects
    fuel_map = {"E5": "SUP", "E10": "SUP", "Diesel": "DIE"}

    params = {
        "latitude":      lat,
        "longitude":     lon,
        "fuelType":      fuel_map[fuel_type],
        "includeClosed": "false",   # we only want stations that are open right now
    }

    try:
        resp = requests.get(
            ECONTROL_URL, params=params,
            headers={"User-Agent": USER_AGENT},  # required by the API
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()  # the response is a list of station objects (not wrapped in a dict)
    except requests.RequestException as e:
        result.warnings.append(f"Austria unavailable: {e}")
        return result

    # loop through each station in the list
    for s in data:
        # the location info is nested inside a "location" sub-dictionary
        loc = s.get("location") or {}
        slat, slon = loc.get("latitude"), loc.get("longitude")

        if slat is None or slon is None:
            continue  # skip stations that don't have GPS coordinates

        # calculate how far this station is from our search point
        d = haversine_km(lat, lon, slat, slon)

        # the API doesn't filter by radius (it always returns the nearest ~10),
        # so we have to check ourselves and skip stations that are too far away
        if d > radius_km:
            continue

        # prices are in a list - get the first price if it exists
        prices = s.get("prices") or []
        amount = prices[0].get("amount") if prices else None  # could be None if no price available

        # build the address from its parts
        addr_parts = [
            (loc.get("address") or "").strip(),
            f"{(loc.get('postalCode') or '').strip()} {(loc.get('city') or '').strip()}".strip(),
        ]

        result.stations.append({
            "name":        (s.get("name") or "Unknown").strip(),
            "brand":       "",  # the Austrian API doesn't include brand info
            "address":     ", ".join(p for p in addr_parts if p),  # join non-empty parts with comma
            "country":     "AT",
            "lat":         slat,
            "lon":         slon,
            "price":       float(amount) if amount else None,  # None means no price available right now
            "fuel_type":   fuel_type,
            "distance_km": d,
            "source":      "Spritpreisrechner.at",
        })

    return result


@st.cache_data(ttl=300, show_spinner=False)
def fetch_switzerland(lat: float, lon: float, radius_km: float, fuel_type: str) -> FetchResult:
    """
    Fetches Swiss fuel station locations from OpenStreetMap via the Overpass API.
    No API key needed. However, Switzerland has no public fuel price database,
    so we can only show station locations (grey markers) without prices.
    Occasionally OpenStreetMap volunteers tag prices manually, but this is rare.
    """
    result = FetchResult()

    # skip if not near Switzerland
    if not _near_country(lat, lon, radius_km, _CH_BBOX):
        return result

    radius_m = int(radius_km * 1000)  # Overpass expects radius in metres, not kilometres

    # Overpass QL is a special query language for fetching OpenStreetMap data
    # this query finds all fuel stations within our radius that are inside Switzerland
    # we restrict to Switzerland using the ISO country code to avoid stations from neighbouring countries
    overpass_query = f"""
    [out:json][timeout:25];
    area["ISO3166-1"="CH"][admin_level=2]->.ch;
    (
      node["amenity"="fuel"](around:{radius_m},{lat},{lon})(area.ch);
      way["amenity"="fuel"](around:{radius_m},{lat},{lon})(area.ch);
    );
    out center tags;
    """

    try:
        # Overpass uses POST requests (unlike most APIs that use GET)
        resp = requests.post(
            OVERPASS_URL,
            data={"data": overpass_query},
            headers={"User-Agent": USER_AGENT},
            timeout=30,  # Overpass can be slow, so we give it a longer timeout
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        result.warnings.append(f"Switzerland unavailable: {e}")
        return result

    # OSM can return two types of elements: nodes (a single point) or ways (a polygon/area)
    # large fuel stations might be mapped as a polygon (way) rather than a single point
    for el in data.get("elements", []):
        tags = el.get("tags") or {}  # tags contain metadata like name, brand, address

        if el.get("type") == "node":
            # a node is a single GPS point
            slat, slon = el.get("lat"), el.get("lon")
        else:
            # a way (polygon) has a "center" field with the centre point of the shape
            c = el.get("center") or {}
            slat, slon = c.get("lat"), c.get("lon")

        if slat is None or slon is None:
            continue  # skip elements with no coordinates

        # the Overpass "around" radius is approximate, so we verify the distance ourselves
        d = haversine_km(lat, lon, slat, slon)
        if d > radius_km:
            continue

        # check if any OSM contributor has tagged the fuel price on this station
        # OSM uses keys like "charge:e5" or "price:diesel" for prices
        price = None
        for key in (f"charge:{fuel_type.lower()}", f"price:{fuel_type.lower()}"):
            if key in tags:
                try:
                    price = float(tags[key])  # try to convert the tag value to a number
                    break
                except ValueError:
                    pass  # if the value isn't a valid number, just ignore it

        # build address from OSM address tags - these are often incomplete or missing
        addr_parts = [
            f"{(tags.get('addr:street') or '').strip()} {(tags.get('addr:housenumber') or '').strip()}".strip(),
            f"{(tags.get('addr:postcode') or '').strip()} {(tags.get('addr:city') or '').strip()}".strip(),
        ]

        result.stations.append({
            "name":        tags.get("name") or tags.get("brand") or "Tankstelle",
            "brand":       tags.get("brand") or "",
            "address":     ", ".join(p for p in addr_parts if p),
            "country":     "CH",
            "lat":         slat,
            "lon":         slon,
            "price":       price,   # almost always None - Switzerland has no public price data
            "fuel_type":   fuel_type,
            "distance_km": d,
            "source":      "OpenStreetMap",
        })

    return result


# ---------------------------------------------------------------------------
# Combine results from all three countries into one sorted list
# ---------------------------------------------------------------------------

def gather_all(lat: float, lon: float, radius_km: float, fuel_type: str) -> FetchResult:
    """
    Calls all three country fetchers and merges their results into one list.

    Sorting logic:
    - Stations with a price come first, sorted cheapest to most expensive.
    - Stations without a price (Switzerland, or Austria outside update windows) go last,
      sorted by distance from the search point.
    """
    combined = FetchResult()

    # call each country's fetcher and add its results to the combined list
    combined.extend(fetch_germany(lat, lon, radius_km, fuel_type))
    combined.extend(fetch_austria(lat, lon, radius_km, fuel_type))
    combined.extend(fetch_switzerland(lat, lon, radius_km, fuel_type))

    # sort the combined list using a tuple key:
    # - first sort by whether price is None (False = has price, sorts first; True = no price, sorts last)
    # - then by price ascending (cheapest first)
    # - then by distance (closest first, as tiebreaker)
    combined.stations.sort(
        key=lambda s: (
            s["price"] is None,
            s["price"] if s["price"] is not None else float("inf"),
            s["distance_km"],
        )
    )
    return combined


# ===========================================================================
# 3. TRIP PLANNER — routing, corridor search, cost optimisation
# ===========================================================================

@dataclass
class Route:
    """Represents a driving route between two locations."""
    points: list[tuple[float, float]]  # ordered list of (lat, lon) waypoints along the route
    total_km: float                    # total driving distance in kilometres


@dataclass
class RefuelStop:
    """Represents one refuelling decision along the trip."""
    station: dict   # the station where we stop (a dictionary from gather_all)
    liters: float   # how many litres to buy here
    cost: float     # total cost for this stop (= liters × price per litre)


@dataclass
class TripPlan:
    """The complete output of the refuelling optimiser."""
    stops: list[RefuelStop]   # list of refuel stops in the order you encounter them
    total_cost: float         # total amount spent on fuel for the whole trip
    total_distance_km: float  # total route distance in km
    fuel_remaining_l: float   # how many litres are left in the tank when you arrive
    feasible: bool            # False if the trip can't be completed (gap between stations too large)
    message: str = ""         # human-readable explanation if feasible is False


# ---------------------------------------------------------------------------
# Routing — fetch a driving route from A to B
# ---------------------------------------------------------------------------

# cache for 1 hour - the route between two fixed points doesn't change
@st.cache_data(ttl=3600, show_spinner=False)
def get_route(start_lat: float, start_lon: float,
              end_lat: float, end_lon: float) -> Optional[Route]:
    """
    Fetches a driving route between two GPS coordinates using Mapbox Directions.
    Falls back to OSRM (a free open-source routing engine) if no Mapbox token is set.
    Returns a Route object, or None if the route can't be calculated.

    Watch out: both Mapbox and OSRM expect coordinates as longitude,latitude (reversed!)
    in their URLs, which is the opposite of how we store them everywhere else.
    """
    token = get_mapbox_token()

    # coordinates in the URL must be in lon,lat order (NOT lat,lon like everywhere else)
    coords = f"{start_lon},{start_lat};{end_lon},{end_lat}"

    if token:
        # use Mapbox Directions - more accurate, supports traffic
        url    = f"{MAPBOX_DIRECTIONS_URL}/{coords}"
        params = {"geometries": "geojson", "overview": "full", "access_token": token}
    else:
        # use the free public OSRM demo server as a backup
        url    = f"{OSRM_URL}/{coords}"
        params = {"overview": "full", "geometries": "geojson"}

    try:
        resp = requests.get(url, params=params, timeout=20,
                            headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException:
        return None  # route request failed

    routes = data.get("routes", [])
    if not routes:
        return None  # no route found (e.g. points on different islands)

    route = routes[0]  # take the first (best) route suggested

    # GeoJSON coordinates are stored as [longitude, latitude]
    # we swap them to (latitude, longitude) to match our convention throughout the code
    points = [(c[1], c[0]) for c in route["geometry"]["coordinates"]]

    # distance from the API is in metres, so divide by 1000 to get kilometres
    return Route(points=points, total_km=route["distance"] / 1000.0)


# ---------------------------------------------------------------------------
# Route geometry helper functions
# ---------------------------------------------------------------------------

def _cumulative_km(points: list[tuple[float, float]]) -> list[float]:
    """
    Takes a list of GPS waypoints and returns the cumulative distance from the start for each one.
    For example, if the route has 4 points, it might return [0.0, 1.5, 4.2, 9.8].
    This tells us "point 0 is at km 0, point 1 is at km 1.5, point 3 is at km 9.8" etc.
    We need this to know how far along the route any given station is.
    """
    cum = [0.0]  # start at 0 km
    for i in range(1, len(points)):
        # add the distance from the previous point to get the running total
        cum.append(cum[-1] + haversine_km(*points[i - 1], *points[i]))
    return cum


def _project_onto_route(
    station_lat: float, station_lon: float,
    points: list[tuple[float, float]], cumulative: list[float],
) -> tuple[float, float]:
    """
    Finds where a fuel station sits relative to the driving route.

    We loop through every waypoint on the route and find the one closest to the station.
    Then we return:
    - route_km: how many km from the start that closest waypoint is (the station's position on the route)
    - offroad_km: how far the station is from the route line (its detour distance)

    This lets us filter out stations that are too far off the road, and sort the
    remaining stations in the order you'd encounter them while driving.
    """
    best_dist = float("inf")  # start with "infinity" so any real distance will be smaller
    best_km   = 0.0

    for i, (plat, plon) in enumerate(points):
        d = haversine_km(station_lat, station_lon, plat, plon)
        if d < best_dist:
            best_dist = d
            best_km   = cumulative[i]  # remember how far along the route this point is

    return best_km, best_dist  # position along route, distance from route


# ---------------------------------------------------------------------------
# Search for all fuel stations within a band (corridor) around the route
# ---------------------------------------------------------------------------

def stations_along_route(
    route: Route,
    fuel_type: str,
    sample_interval_km: float = ROUTE_SAMPLE_INTERVAL_KM,
    corridor_km: float = ROUTE_CORRIDOR_KM,
    progress_callback=None,
) -> tuple[list[dict], list[str]]:
    """
    Finds all priced fuel stations within a certain distance of the driving route.

    How it works:
    1. Pick evenly-spaced "sample points" along the route (every ~20 km by default).
    2. At each sample point, search for nearby stations using gather_all().
    3. For each station found, check if it's within corridor_km of the route line.
    4. Remove duplicate stations (the same station might appear near multiple sample points).
    5. Return the stations sorted in driving order (closest to start first).

    We run all the API calls in parallel using threads so the whole thing is much faster.
    """
    cumulative = _cumulative_km(route.points)  # get the km position of every waypoint

    # pick which route waypoints to use as sample points
    # we start at the beginning and add one every sample_interval_km
    sample_indices: list[int] = [0]  # always start from the first point
    next_target = sample_interval_km
    for i, c in enumerate(cumulative):
        if c >= next_target:
            sample_indices.append(i)
            next_target += sample_interval_km

    # always include the very last point so we find stations near the destination
    if sample_indices[-1] != len(route.points) - 1:
        sample_indices.append(len(route.points) - 1)

    # we search with a slightly larger radius than the corridor width
    # so we don't miss stations that are just barely within the corridor
    api_radius_km = max(corridor_km * 2, 8)

    seen: set[tuple[float, float]] = set()  # set of (lat, lon) pairs we've already added
    found: list[dict] = []
    warnings: list[str] = []

    # run all API calls in parallel using a thread pool
    # without this, a 600 km route with 30 sample points would take ~60 seconds sequentially
    # with parallel execution it takes about as long as a single API call (~2-3 seconds)
    waypoint_coords = [route.points[idx] for idx in sample_indices]
    total = len(waypoint_coords)

    # pre-fill the results list with empty FetchResults (one slot per waypoint)
    results_ordered: list[FetchResult] = [FetchResult()] * total

    with ThreadPoolExecutor(max_workers=8) as executor:
        # submit one gather_all() call per waypoint; store future -> index mapping
        future_to_n = {
            executor.submit(gather_all, plat, plon, api_radius_km, fuel_type): n
            for n, (plat, plon) in enumerate(waypoint_coords)
        }
        completed = 0
        # as_completed() yields futures as they finish (not necessarily in submission order)
        for future in as_completed(future_to_n):
            n = future_to_n[future]           # which waypoint index this result belongs to
            results_ordered[n] = future.result()  # store result in the correct slot
            completed += 1
            if progress_callback:
                # tell the UI how many waypoints we've processed (for the progress bar)
                progress_callback(completed - 1, total)

    # now process results in route order (not completion order)
    for result in results_ordered:
        # collect unique warnings (avoid showing the same warning multiple times)
        for w in result.warnings:
            if w not in warnings:
                warnings.append(w)

        for s in result.stations:
            # deduplicate: if we've already added this station (from a nearby sample point),
            # skip it. We round to 4 decimal places which is about 11 metres of precision.
            key = (round(s["lat"], 4), round(s["lon"], 4))
            if key in seen:
                continue
            seen.add(key)

            # find where this station sits on the route
            route_km, offroad_km = _project_onto_route(
                s["lat"], s["lon"], route.points, cumulative
            )

            # skip stations that are too far off the road (e.g. behind a mountain)
            if offroad_km > corridor_km:
                continue

            # add the route position info to a copy of the station dict
            enriched = dict(s)           # copy so we don't modify the cached original
            enriched["route_km"]   = route_km    # km from start where you'd stop
            enriched["offroad_km"] = offroad_km  # km off the main road
            found.append(enriched)

    # some stations (mostly Swiss) have no price data
    # fill in the average price of all priced stations so they can still be used
    # by the optimiser - better than skipping them entirely and creating gaps in the route
    priced = [s["price"] for s in found if s["price"] is not None]
    if priced:
        avg_price = sum(priced) / len(priced)
        for s in found:
            if s["price"] is None:
                s["price"] = avg_price
                s["price_estimated"] = True  # mark it so we can show a note on the map popup
            else:
                s["price_estimated"] = False
    else:
        # no real price data at all along this route (e.g. an intra-Swiss trip)
        # we can't estimate anything meaningful, so leave prices as None and flag it
        for s in found:
            s["price_estimated"] = False
        warnings.append("__no_prices__")

    # sort stations by their position along the route (so we process them in driving order)
    found.sort(key=lambda s: s["route_km"])
    return found, warnings


# ---------------------------------------------------------------------------
# Fuel cost optimisation — find the cheapest combination of stops
# ---------------------------------------------------------------------------

def plan_trip(
    stations: list[dict],
    total_distance_km: float,
    tank_capacity_l: float,
    current_fuel_l: float,
    consumption_l_per_100km: float,
) -> TripPlan:
    """
    Finds the cheapest set of refuelling stops for a road trip.

    This uses a well-known greedy algorithm called the "Gas Station Problem":

    The core idea is simple: if there's a cheaper station coming up that you can reach,
    only buy enough fuel to get there. If no cheaper station is in range, fill up now
    because this is the cheapest fuel you'll see for a while.

    The destination is added as a fake station with price=0 so the algorithm knows
    to stop buying fuel once you can reach the end.

    Returns a TripPlan with feasible=False if the tank isn't big enough to bridge a gap.
    """
    # how many litres the car burns per km (e.g. 6.5L/100km -> 0.065 L/km)
    consumption_per_km = consumption_l_per_100km / 100.0

    # the furthest the car can go on a full tank
    fuel_range_km = tank_capacity_l / consumption_per_km

    # sanity check the inputs
    if tank_capacity_l <= 0 or consumption_l_per_100km <= 0:
        return TripPlan([], 0.0, total_distance_km, current_fuel_l, False,
                        "Tank capacity and consumption must be positive.")
    if current_fuel_l > tank_capacity_l:
        return TripPlan([], 0.0, total_distance_km, current_fuel_l, False,
                        "Current fuel exceeds tank capacity.")

    # add the destination as a virtual "free" station at the end
    # the algorithm will naturally stop buying fuel once it can reach this station
    DEST = {
        "name": "Destination", "lat": None, "lon": None,
        "price": 0.0, "route_km": total_distance_km,
        "country": "-", "brand": "",
    }

    # filter out stations at the very start or end (only keep stations between start and destination)
    points = [s for s in stations if 0 < s["route_km"] < total_distance_km] + [DEST]

    pos_km = 0.0           # current position on the route in km from start
    fuel_l = current_fuel_l  # current amount of fuel in the tank
    stops: list[RefuelStop] = []  # list of stops we decide to make

    # keep driving until we reach the destination
    while pos_km < total_distance_km - 1e-6:  # 1e-6 is a tiny buffer for floating point errors

        # check if we are currently at a fuel station
        current = next(
            (p for p in points if abs(p["route_km"] - pos_km) < 1e-3 and p is not DEST),
            None  # None if we're not at any station
        )

        # calculate how far we can reach from here
        # if we're at a station, assume we could fill up to a full tank
        max_fuel_here = tank_capacity_l if current is not None else fuel_l
        reach_km = pos_km + max_fuel_here / consumption_per_km

        # find all stations (and the destination) that we can reach from here
        candidates = [p for p in points if pos_km < p["route_km"] <= reach_km + 1e-6]

        if not candidates:
            # even a completely full tank can't reach the next station - the trip is impossible
            ahead = [p for p in points if p["route_km"] > pos_km]
            if not ahead:
                return TripPlan(stops, sum(s.cost for s in stops), total_distance_km,
                                fuel_l, False,
                                "No stations ahead and destination unreachable.")
            next_stop = min(ahead, key=lambda p: p["route_km"])
            gap = next_stop["route_km"] - pos_km
            return TripPlan(stops, sum(s.cost for s in stops), total_distance_km,
                            fuel_l, False,
                            f"Gap of {gap:.0f} km before next station exceeds "
                            f"tank range of {fuel_range_km:.0f} km.")

        if current is None:
            # we're at the start (not at any station yet)
            # just drive to the cheapest station we can currently reach
            target = min(candidates, key=lambda p: p["price"])
            distance = target["route_km"] - pos_km
            fuel_l -= distance * consumption_per_km
            pos_km = target["route_km"]
            continue  # restart the loop at the new position

        # we're at a station - apply the greedy algorithm decision:
        # look for a cheaper station we can reach from here on our current fuel + a full tank
        cheaper_ahead = [p for p in candidates if p["price"] < current["price"]]

        if cheaper_ahead:
            # there's a cheaper station in range - buy just enough to get there
            next_cheaper = min(cheaper_ahead, key=lambda p: p["route_km"])  # take the nearest cheaper one
            distance     = next_cheaper["route_km"] - pos_km
            fuel_needed  = distance * consumption_per_km    # how much fuel we need to reach it
            buy          = max(0.0, fuel_needed - fuel_l)   # only buy what we don't already have
            target       = next_cheaper
        else:
            # no cheaper station in range - fill up completely before continuing
            buy      = tank_capacity_l - fuel_l  # top up to a full tank
            target   = max(candidates, key=lambda p: p["route_km"])  # drive as far as possible
            distance = target["route_km"] - pos_km

        # record this refuel stop if we actually need to buy fuel
        if buy > 0:
            # don't stop for tiny amounts - it's not worth pulling off the road for less than 10L
            # we round up to the minimum, but never more than what fits in the tank
            MIN_FILL_L = 10.0
            buy = max(buy, MIN_FILL_L)
            buy = min(buy, tank_capacity_l - fuel_l)  # make sure we don't overfill the tank
            stops.append(RefuelStop(
                station=current,
                liters=buy,
                cost=buy * current["price"],  # total cost = litres × price per litre
            ))
            fuel_l += buy  # add the purchased fuel to the tank

        # drive to the chosen next point and update position + fuel level
        fuel_l -= distance * consumption_per_km
        pos_km  = target["route_km"]

        # floating point arithmetic can leave tiny negative values like -0.0000001
        # this just rounds those to zero to avoid false "out of fuel" errors
        if -1e-6 < fuel_l < 0:
            fuel_l = 0.0
        if fuel_l < 0:
            return TripPlan(stops, sum(s.cost for s in stops), total_distance_km,
                            fuel_l, False, "Ran out of fuel - refuel logic error.")

    # we reached the destination - return the complete plan
    return TripPlan(
        stops=stops,
        total_cost=sum(s.cost for s in stops),
        total_distance_km=total_distance_km,
        fuel_remaining_l=fuel_l,
        feasible=True,
    )


# ---------------------------------------------------------------------------
# Range-based stop planner — used when no price data is available (e.g. Switzerland)
# ---------------------------------------------------------------------------

def plan_trip_no_prices(
    stations: list[dict],
    total_distance_km: float,
    tank_capacity_l: float,
    current_fuel_l: float,
    consumption_l_per_100km: float,
) -> TripPlan:
    """
    Plans refuel stops using only range / distance — no prices needed.

    Strategy: always drive to the furthest station reachable on current fuel,
    fill up to a full tank there, and repeat until the destination is reachable.
    This gives the minimum number of stops without any cost information.
    """
    consumption_per_km = consumption_l_per_100km / 100.0
    fuel_range_km = tank_capacity_l / consumption_per_km

    if tank_capacity_l <= 0 or consumption_l_per_100km <= 0:
        return TripPlan([], 0.0, total_distance_km, current_fuel_l, False,
                        "Tank capacity and consumption must be positive.")

    # only consider stations between start and destination
    points = sorted(
        [s for s in stations if 0 < s["route_km"] < total_distance_km],
        key=lambda s: s["route_km"],
    )

    pos_km = 0.0
    fuel_l = current_fuel_l
    stops: list[RefuelStop] = []

    while True:
        # how far can we reach from here on current fuel?
        reach_km = pos_km + fuel_l / consumption_per_km

        # can we already make it to the destination?
        if reach_km >= total_distance_km - 1e-6:
            break

        # find all stations reachable on current fuel
        reachable = [s for s in points if pos_km < s["route_km"] <= reach_km + 1e-6]

        if not reachable:
            # even a full tank can't reach the next station
            ahead = [s for s in points if s["route_km"] > pos_km]
            if not ahead:
                return TripPlan(stops, 0.0, total_distance_km, fuel_l, False,
                                "Destination unreachable — no more stations ahead.")
            next_s = min(ahead, key=lambda s: s["route_km"])
            gap = next_s["route_km"] - pos_km
            return TripPlan(stops, 0.0, total_distance_km, fuel_l, False,
                            f"Gap of {gap:.0f} km to next station exceeds "
                            f"tank range of {fuel_range_km:.0f} km.")

        # pick the furthest reachable station to minimise the number of stops
        chosen = max(reachable, key=lambda s: s["route_km"])

        # drive there
        distance = chosen["route_km"] - pos_km
        fuel_l  -= distance * consumption_per_km
        pos_km   = chosen["route_km"]

        # fill up to a full tank (price unknown, so cost = 0)
        buy    = tank_capacity_l - fuel_l
        fuel_l = tank_capacity_l
        stops.append(RefuelStop(station=chosen, liters=buy, cost=0.0))

    return TripPlan(
        stops=stops,
        total_cost=0.0,
        total_distance_km=total_distance_km,
        fuel_remaining_l=fuel_l,
        feasible=True,
    )


# ===========================================================================
# 4. UI — map builders and page renderers
# ===========================================================================

def build_map(stations: list[dict], origin_lat: float, origin_lon: float,
              fuel_type: str) -> folium.Map:
    """
    Creates the interactive map for Mode 1 (Find nearby).
    Markers are colour coded by price:
    green = cheapest third, orange = middle third, red = most expensive, grey = no price.
    """
    # use Mapbox Streets map tiles if we have a token, otherwise fall back to free OpenStreetMap tiles
    tile_url = _mapbox_tile_url()
    fmap = folium.Map(
        location=[origin_lat, origin_lon],  # centre the map on the search location
        zoom_start=11,                       # zoom level (higher = more zoomed in)
        tiles=tile_url or "OpenStreetMap",
        attr='© <a href="https://www.mapbox.com/">Mapbox</a>' if tile_url else "© OpenStreetMap contributors",
        max_zoom=22 if tile_url else 18,
    )

    # add a blue "home" marker at the search location
    folium.Marker(
        [origin_lat, origin_lon],
        popup="Your search location",
        icon=folium.Icon(color="blue", icon="home", prefix="fa"),  # "fa" = Font Awesome icon set
    ).add_to(fmap)

    if not stations:
        return fmap  # nothing to show - return the empty map

    # calculate the price thresholds that divide stations into three equal groups
    priced = sorted(s["price"] for s in stations if s["price"] is not None)
    if len(priced) >= 3:
        q_low  = priced[len(priced) // 3]       # top boundary of the cheap third
        q_high = priced[2 * len(priced) // 3]   # top boundary of the middle third
    else:
        q_low = q_high = float("inf")  # if fewer than 3 stations, don't try to split into thirds

    # add a circle marker for each station
    for s in stations:
        # decide the marker colour based on which price tier the station falls into
        if s["price"] is None:
            color, price_str = "gray", "no price data"
        elif s["price"] <= q_low:
            color, price_str = "green", f"{s['price']:.3f}"   # cheap
        elif s["price"] <= q_high:
            color, price_str = "orange", f"{s['price']:.3f}"  # middle
        else:
            color, price_str = "red", f"{s['price']:.3f}"     # expensive

        # this HTML string shows up in a popup when the user clicks on the marker
        popup_html = (
            f"<b>{s['name']}</b><br>"
            f"Brand: {s['brand'] or '-'}<br>"
            f"{fuel_type}: <b>{price_str}</b><br>"
            f"Distance: {s['distance_km']:.1f} km<br>"
            f"Country: {s['country']} ({s['source']})"
        )
        folium.CircleMarker(
            location=[s["lat"], s["lon"]],
            radius=8,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.85,
            popup=folium.Popup(popup_html, max_width=300),
        ).add_to(fmap)

    return fmap


def build_trip_map(route: Route, all_corridor_stations: list[dict],
                   plan: TripPlan, fuel_type: str) -> folium.Map:
    """
    Creates the interactive map for Mode 2 (Trip planner).
    Shows a blue route line, green pins for chosen refuel stops,
    and small grey dots for all other stations along the corridor.
    """
    if not route.points:
        return folium.Map()  # return a blank map if there's no route

    # centre the map roughly in the middle of the route
    mid = route.points[len(route.points) // 2]
    tile_url = _mapbox_tile_url()
    fmap = folium.Map(
        location=mid, zoom_start=7,  # zoom out more than Mode 1 since we're showing a whole route
        tiles=tile_url or "OpenStreetMap",
        attr='© <a href="https://www.mapbox.com/">Mapbox</a>' if tile_url else "© OpenStreetMap contributors",
        max_zoom=22 if tile_url else 18,
    )

    # draw the driving route as a blue polyline (connected set of line segments)
    folium.PolyLine(route.points, color="#185FA5", weight=5, opacity=0.7).add_to(fmap)

    # add start and destination markers
    folium.Marker(route.points[0], popup="Start",
                  icon=folium.Icon(color="green", icon="play", prefix="fa")).add_to(fmap)
    folium.Marker(route.points[-1], popup="Destination",
                  icon=folium.Icon(color="red", icon="flag-checkered", prefix="fa")).add_to(fmap)

    # build a set of (lat, lon) coordinates for the chosen stops
    # we use this to avoid drawing them as grey dots in the next loop
    chosen_keys = {(s.station["lat"], s.station["lon"]) for s in plan.stops
                   if s.station["lat"] is not None}

    # draw all corridor stations that were NOT chosen as small grey dots
    for s in all_corridor_stations:
        if (s["lat"], s["lon"]) in chosen_keys:
            continue  # this station is a chosen stop, we'll draw it as a green pin below
        folium.CircleMarker(
            location=[s["lat"], s["lon"]],
            radius=4,
            color="#9a948c",
            fill=True, fill_opacity=0.4, weight=0,
            popup=folium.Popup(
                f"<b>{s['name']}</b><br>"
                + (f"{fuel_type}: {s['price']:.3f}{'(est.)' if s.get('price_estimated') else ''}<br>"
                   if s.get('price') is not None else "Price: unavailable<br>")
                + f"At km {s['route_km']:.0f} of route",
                max_width=240,
            ),
        ).add_to(fmap)

    # draw the chosen refuel stops as numbered green gas pump markers
    for n, stop in enumerate(plan.stops, start=1):
        s = stop.station
        if s["lat"] is None:
            continue  # skip the virtual destination station (it has no real coordinates)
        # show "(est.)" next to the price if it was filled in from the corridor average
        price_label = (f"{s['price']:.3f} (est.)" if s.get("price_estimated") else f"{s['price']:.3f}") if s.get("price") is not None else "unavailable"
        popup_html = (
            f"<b>Stop {n}: {s['name']}</b><br>"
            f"{fuel_type}: <b>{price_label}</b> / L<br>"
            f"Refuel: <b>{stop.liters:.1f} L</b> "
            f"(EUR{stop.cost:.2f})<br>"
            f"At km {s['route_km']:.0f} of route<br>"
            f"{s['country']} ({s['source']})"
        )
        folium.Marker(
            location=[s["lat"], s["lon"]],
            popup=folium.Popup(popup_html, max_width=280),
            icon=folium.Icon(color="green", icon="gas-pump", prefix="fa"),
            tooltip=f"Stop {n} - {stop.liters:.1f} L",  # shown on hover
        ).add_to(fmap)

    return fmap


# ---------------------------------------------------------------------------
# Page renderer functions — one per app mode
# ---------------------------------------------------------------------------

def render_static_mode() -> None:
    """
    Renders Mode 1 - Find nearby fuel stations.
    Shows the header, search inputs, then the map and table with results.
    Results are stored in st.session_state so they survive Streamlit reruns.
    """
    # inject the page header HTML
    st.markdown(
        '<div class="ff-page-header">'
        '<h1>Find nearby fuel</h1>'
        '<p>Live prices for E5, E10 and Diesel across Germany, Austria and Switzerland.</p>'
        '</div>',
        unsafe_allow_html=True,
    )

    # lay out the input controls in a three-column row
    # the numbers [3, 1, 1] set the relative widths (location box is 3x wider)
    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        # st_searchbox shows an input field with autocomplete dropdown
        # it calls _mapbox_suggestions() every time the user types a character
        # it returns the place name string that was selected, or None if nothing was chosen yet
        selected_place = st_searchbox(
            _mapbox_suggestions,
            key="static_location_search",
            placeholder="e.g. Zurich, Wien, Munchen",
            label="Location",
            clear_on_submit=False,  # keep the selected value visible after clicking Search
        )
    with col2:
        fuel_type = st.selectbox("Fuel type", FUEL_TYPES,
                                 index=FUEL_TYPES.index(DEFAULT_FUEL_TYPE))
    with col3:
        radius = st.slider("Radius (km)", 1, MAX_RADIUS_KM, DEFAULT_RADIUS_KM)

    # the search button - type="primary" gives it the orange style from our CSS
    search_clicked = st.button("Search", type="primary", key="static_search")

    # this block only runs when the button is clicked
    # Streamlit re-runs the whole script on every interaction, so we need this check
    if search_clicked:
        if not selected_place:
            st.error("Please select a location from the dropdown.")
            st.session_state.pop("search_result", None)  # clear any old results
            return

        # look up coordinates - they should already be in the cache if the user used autocomplete
        geo = _geo_cache.get(selected_place)
        if geo is None:
            # not in cache - call the geocoding API
            with st.spinner(f"Geocoding '{selected_place}'..."):
                geo = geocode(selected_place)
        if geo is None:
            st.error(f"Could not find '{selected_place}'.")
            st.session_state.pop("search_result", None)
            return

        # fetch stations from all three countries
        with st.spinner("Fetching live prices from DE / AT / CH..."):
            result = gather_all(geo.lat, geo.lon, radius, fuel_type)

        # store the results in Streamlit's session_state
        # session_state persists between reruns (unlike regular variables which reset each time)
        # this is how we keep the results on screen when the user interacts with other UI elements
        st.session_state.search_result = {
            "geo":       geo,
            "stations":  result.stations,
            "warnings":  result.warnings,
            "fuel_type": fuel_type,
        }

    # try to load results from session_state (they persist even if the button wasn't just clicked)
    sr = st.session_state.get("search_result")
    if not sr:
        # no results yet - show a hint
        st.info("Enter a location above and click **Search** to find live fuel prices.")
        return

    # unpack the results from the dictionary
    geo            = sr["geo"]
    stations       = sr["stations"]
    warnings       = sr["warnings"]
    fuel_type_used = sr["fuel_type"]

    # show the resolved address as a green success banner
    st.success(f"  {geo.address}")

    # if any API had issues (missing key, timeout etc.) show them in a collapsible section
    if warnings:
        with st.expander(f"  {len(warnings)} warning(s)"):
            for w in warnings:
                st.write(f"- {w}")

    # only show the top N results to keep the page manageable
    top = stations[:TOP_N_RESULTS]
    if not top:
        st.warning("No stations found in this radius. Try widening the search.")
        return

    st.markdown(
        f"**{len(stations)} stations** found - showing top **{len(top)}** for **{fuel_type_used}**."
    )

    # --- MAP ---
    st.markdown('<div class="ff-section">Map</div>', unsafe_allow_html=True)
    fmap = build_map(top, geo.lat, geo.lon, fuel_type_used)
    # st_folium renders the folium map as an interactive component in the Streamlit page
    # returned_objects=[] means we don't need to capture any click events from the map
    st_folium(fmap, height=420, width='stretch', returned_objects=[])
    st.caption("Green = cheapest third | Orange = middle third | Red = most expensive | Grey = no price data")

    # --- TABLE ---
    st.markdown('<div class="ff-section">Stations</div>', unsafe_allow_html=True)
    df = pd.DataFrame(top)        # convert the list of station dicts to a pandas DataFrame
    df.index = df.index + 1       # make the row numbers start at 1 instead of 0
    # rename columns to be more readable and select only the ones we want to show
    df = df.rename(columns={
        "country": "Country", "name": "Station", "brand": "Brand",
        "address": "Address", "price": "Price", "distance_km": "Dist (km)",
        "source": "Source",
    })[["Country", "Station", "Brand", "Address", "Price", "Dist (km)", "Source"]]
    st.dataframe(
        df, width='stretch',
        column_config={
            "Price":     st.column_config.NumberColumn(format="%.3f"),  # show 3 decimal places
            "Dist (km)": st.column_config.NumberColumn(format="%.1f"),  # show 1 decimal place
        },
    )


def render_dynamic_mode() -> None:
    """
    Renders Mode 2 - Trip planner.
    User fills in start, destination, and vehicle details and clicks Plan trip.
    We get a route from the API, search for stations along it, then run the optimiser.
    """
    st.markdown(
        '<div class="ff-page-header">'
        '<h1>Trip planner</h1>'
        '<p>Plan a route and let us pick the cheapest places to stop.</p>'
        '</div>',
        unsafe_allow_html=True,
    )

    # two search boxes next to each other for start and destination
    col_a, col_b = st.columns(2)
    with col_a:
        start_q = st_searchbox(
            _mapbox_suggestions,
            key="trip_start_search",
            placeholder="e.g. Berlin",
            label="Start",
            clear_on_submit=False,
        )
    with col_b:
        end_q = st_searchbox(
            _mapbox_suggestions,
            key="trip_end_search",
            placeholder="e.g. Munich",
            label="Destination",
            clear_on_submit=False,
        )

    # four vehicle parameter inputs in a row
    col_c, col_d, col_e, col_f = st.columns(4)
    with col_c:
        fuel_type = st.selectbox("Fuel type", FUEL_TYPES,
                                 index=FUEL_TYPES.index(DEFAULT_FUEL_TYPE),
                                 key="trip_fuel")
    with col_d:
        tank_capacity = st.number_input("Tank (L)", min_value=10.0, max_value=200.0,
                                        value=50.0, step=5.0, key="trip_tank")
    with col_e:
        current_fuel = st.number_input("Fuel now (L)", min_value=0.0, max_value=200.0,
                                       value=10.0, step=1.0, key="trip_current")
    with col_f:
        consumption = st.number_input("L / 100 km", min_value=2.0, max_value=25.0,
                                      value=6.5, step=0.5, key="trip_cons")

    plan_clicked = st.button("Plan trip", type="primary", key="trip_plan")

    if plan_clicked:
        # check the inputs make sense before making any API calls
        if current_fuel > tank_capacity:
            st.error("Current fuel can't exceed tank capacity.")
            return
        if not start_q or not end_q:
            st.error("Please select both a start and a destination from the dropdowns.")
            return

        # get coordinates for start and destination (from cache if possible)
        start = _geo_cache.get(start_q)
        if start is None:
            with st.spinner("Geocoding start..."):
                start = geocode(start_q)

        end = _geo_cache.get(end_q)
        if end is None:
            with st.spinner("Geocoding destination..."):
                end = geocode(end_q)

        if start is None:
            st.error(f"Could not find start '{start_q}'.")
            return
        if end is None:
            st.error(f"Could not find destination '{end_q}'.")
            return

        # step 1: get the driving route from Mapbox/OSRM
        with st.spinner("Computing driving route..."):
            route = get_route(start.lat, start.lon, end.lat, end.lon)
        if route is None:
            st.error("Could not compute a route between those points.")
            return

        # step 2: find all priced stations within the corridor around the route
        # this is the slowest step since it makes many parallel API calls
        progress_bar = st.progress(0.0, text="Searching for stations along the route...")

        def _progress(n: int, total: int) -> None:
            # update the progress bar as each waypoint finishes
            progress_bar.progress((n + 1) / max(total, 1),
                                  text=f"Searching waypoint {n + 1} of {total}...")

        corridor_stations, corridor_warnings = stations_along_route(
            route, fuel_type, progress_callback=_progress,
        )
        progress_bar.empty()  # remove the progress bar once done

        # check if we have any real price data along the route
        has_prices = "__no_prices__" not in corridor_warnings

        if has_prices:
            # step 3: run the greedy algorithm to find the cheapest combination of stops
            with st.spinner("Optimising refuel stops..."):
                plan = plan_trip(
                    stations=corridor_stations,
                    total_distance_km=route.total_km,
                    tank_capacity_l=tank_capacity,
                    current_fuel_l=current_fuel,
                    consumption_l_per_100km=consumption,
                )
        else:
            # no price data - plan stops based on range only (furthest reachable station each time)
            with st.spinner("Planning stops based on fuel range..."):
                plan = plan_trip_no_prices(
                    stations=corridor_stations,
                    total_distance_km=route.total_km,
                    tank_capacity_l=tank_capacity,
                    current_fuel_l=current_fuel,
                    consumption_l_per_100km=consumption,
                )

        # save everything to session_state so results persist across Streamlit reruns
        st.session_state.trip_result = {
            "start":             start,
            "end":               end,
            "route":             route,
            "corridor_stations": corridor_stations,
            "corridor_warnings": corridor_warnings,
            "has_prices":        has_prices,
            "plan":              plan,
            "fuel_type":         fuel_type,
            "consumption":       consumption,
            "current_fuel":      current_fuel,
        }

    # check if we have results to display
    tr = st.session_state.get("trip_result")
    if not tr:
        st.info(
            "Fill in the inputs above and click **Plan trip**. "
            "We'll fetch a driving route, find every priced station along the way, "
            "and pick the cheapest places to stop using the classical *gas station "
            "problem* algorithm."
        )
        return

    # unpack the saved results
    plan              = tr["plan"]
    route             = tr["route"]
    fuel_type_used    = tr["fuel_type"]
    corridor_stations = tr["corridor_stations"]
    has_prices        = tr.get("has_prices", True)

    st.success(f"  {tr['start'].address}  ->  {tr['end'].address}")

    # show any non-internal warnings in a collapsible section
    # (filter out "__no_prices__" which is an internal flag, not a user-facing message)
    user_warnings = [w for w in tr["corridor_warnings"] if not w.startswith("__")]
    if user_warnings:
        with st.expander(f"  {len(user_warnings)} warning(s)"):
            for w in user_warnings:
                st.write(f"- {w}")

    # if there's no price data, show range-based stop plan with a disclaimer
    if not has_prices:
        st.warning(
            "No live fuel price data was found along this route (e.g. intra-Swiss route). "
            "Stops are planned based on your fuel range — the app picks the furthest reachable "
            "station each time to minimise the number of stops. Costs cannot be shown without price data."
        )

        if not plan.feasible:
            st.error(f"Trip not feasible: {plan.message}")
            return

        # show summary metrics (no costs, just distance and stops)
        fuel_needed_total = max(0.0, route.total_km * tr["consumption"] / 100.0 - tr["current_fuel"])
        c1, c2, c3 = st.columns(3)
        c1.metric("Distance", f"{route.total_km:.0f} km")
        c2.metric("Fuel to buy", f"{fuel_needed_total:.1f} L")
        c3.metric("Refuel stops", str(len(plan.stops)))

        st.markdown('<div class="ff-section">Recommended stops (range-based)</div>', unsafe_allow_html=True)
        fmap = build_trip_map(route, corridor_stations, plan, fuel_type_used)
        st_folium(fmap, height=460, width='stretch', returned_objects=[])
        st.caption(
            f"Green pin = recommended stop | Grey dot = other station | "
            f"{len(corridor_stations)} stations found along the route"
        )

        if plan.stops:
            rows = []
            for n, stop in enumerate(plan.stops, 1):
                s = stop.station
                rows.append({
                    "Stop": n,
                    "Station": s.get("name", "Unknown"),
                    "At km": f"{s['route_km']:.0f}",
                    "Fill (L)": f"{stop.liters:.1f}",
                    "Price": "No data",
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        return

    if not plan.feasible:
        st.error(f"Trip not feasible: {plan.message}")
        return

    # calculate metrics for the summary cards
    # total litres the car needs to refuel (route consumption minus what's already in the tank)
    fuel_needed_total   = max(0.0, route.total_km * tr["consumption"] / 100.0 - tr["current_fuel"])
    total_liters_bought = sum(s.liters for s in plan.stops)

    # actual average price paid = total cost divided by total litres bought
    actual_avg_price = plan.total_cost / total_liters_bought if total_liters_bought > 0 else 0.0

    # corridor average = mean price of all real (non-estimated) stations found along the route
    # note: this is the unweighted average of all stations on the route, not just the ones we stop at.
    # it CAN be lower than actual_avg_price when cheap stations are reachable without stopping
    # (e.g. they're near the start when the tank is already full) — that's not a bug.
    real_priced = [s["price"] for s in corridor_stations if not s.get("price_estimated")]
    avg_price   = sum(real_priced) / len(real_priced) if real_priced else 0.0

    # display five summary metric cards
    metrics = st.columns(5)
    metrics[0].metric("Distance",        f"{route.total_km:,.0f} km")
    metrics[1].metric("Total fuel cost", f"EUR {plan.total_cost:,.2f}")
    metrics[2].metric("Fuel to buy",     f"{total_liters_bought:.1f} L")
    metrics[3].metric("Refuel stops",    f"{len(plan.stops)}")
    if avg_price > 0 and actual_avg_price > 0:
        diff = actual_avg_price - avg_price   # positive = you paid more than average
        metrics[4].metric(
            "Your avg vs corridor avg",
            f"EUR {actual_avg_price:.3f}/L",
            delta=f"{diff:+.3f} EUR/L",
            delta_color="inverse",  # red when positive (paying above average), green when negative
            help=(
                "Your avg price = total cost ÷ total litres bought at your stops. "
                f"Corridor average = EUR {avg_price:.3f}/L (mean of all {len(real_priced)} "
                "real-price stations found along the route). "
                "Your avg can be above the corridor average when range constraints force stops "
                "at expensive stations, or when cheap stations near the start are skipped "
                "because the tank is already full."
            ),
        )
    else:
        metrics[4].metric("Avg price paid", f"EUR {actual_avg_price:.3f}/L" if actual_avg_price > 0 else "-")

    # caption: corridor average and total fuel calculation
    if avg_price > 0:
        st.caption(
            f"Corridor average: **EUR {avg_price:.3f}/L** · "
            f"Your avg paid: **EUR {actual_avg_price:.3f}/L** · "
            f"Total fuel needed: **{fuel_needed_total:.1f} L** "
            f"({route.total_km:.0f} km × {tr['consumption']} L/100km − {tr['current_fuel']:.0f} L already in tank)"
        )

    # --- ROUTE MAP ---
    st.markdown('<div class="ff-section">Route and refuel stops</div>', unsafe_allow_html=True)
    fmap = build_trip_map(route, corridor_stations, plan, fuel_type_used)
    st_folium(fmap, height=460, width='stretch', returned_objects=[])
    st.caption(
        f"Green pin = chosen refuel stop | Grey dot = other station in corridor | "
        f"{len(corridor_stations)} stations along the route"
    )

    # --- REFUEL PLAN TABLE ---
    if plan.stops:
        st.markdown('<div class="ff-section">Refuel plan</div>', unsafe_allow_html=True)
        rows = []
        for n, stop in enumerate(plan.stops, start=1):
            s = stop.station
            rows.append({
                "#":             n,
                "At km":         f"{s['route_km']:.0f}",
                "Station":       s["name"],
                "Country":       s["country"],
                "Price (EUR/L)": s["price"],
                "Refuel (L)":    stop.liters,
                "Cost (EUR)":    stop.cost,
            })
        df = pd.DataFrame(rows)
        st.dataframe(
            df, hide_index=True, width='stretch',
            column_config={
                "Price (EUR/L)": st.column_config.NumberColumn(format="%.3f"),
                "Refuel (L)":   st.column_config.NumberColumn(format="%.1f"),
                "Cost (EUR)":   st.column_config.NumberColumn(format="%.2f"),
            },
        )
        st.caption(
            f"Arriving with **{plan.fuel_remaining_l:.1f} L** in the tank. "
            "The optimiser buys just enough fuel at each stop to reach the next "
            "cheaper option, and fills up only when nothing cheaper is reachable."
        )
    else:
        # if no stops were needed, just show a message
        st.info(
            f"No refuelling needed - your starting fuel covers the whole trip "
            f"(arriving with **{plan.fuel_remaining_l:.1f} L** to spare)."
        )


# ===========================================================================
# 5. ENTRY POINT
# ===========================================================================

def main() -> None:
    """Sets up the page, injects CSS, builds the sidebar, and calls the right page renderer."""
    st.set_page_config(
        page_title="FuelFinder - DACH fuel prices",
        page_icon="",
        layout="wide",  # "wide" uses the full browser width instead of the narrow default
        initial_sidebar_state="expanded",  # sidebar always open, no collapse button
    )

    # inject the custom CSS (defined at the top of the file) into the page HTML
    st.markdown(_CSS, unsafe_allow_html=True)

    # build the sidebar - this runs every time the page loads
    with st.sidebar:
        # app logo / title
        st.markdown(
            '<p class="ff-brand-name">FuelFinder</p>'
            '<p class="ff-brand-tag">Live prices across DE &middot; AT &middot; CH</p>',
            unsafe_allow_html=True,
        )
        st.divider()

        # mode selector - user picks between the two app modes here
        mode = st.radio(
            "Mode",
            ["Find nearby", "Trip planner"],
            label_visibility="collapsed",  # hide the "Mode" label since it's obvious from context
        )
        st.divider()

        # credits and data sources at the bottom of the sidebar
        st.markdown(
            '<div class="ff-sidebar-footer">'
            'Data: <a href="https://creativecommons.tankerkoenig.de/" target="_blank">Tankerkoenig</a> &middot; '
            '<a href="https://www.spritpreisrechner.at/" target="_blank">Spritpreisrechner.at</a> &middot; '
            '<a href="https://www.openstreetmap.org/" target="_blank">OpenStreetMap</a><br>'
            'Routing &amp; Maps: <a href="https://www.mapbox.com/" target="_blank">Mapbox</a><br><br>'
            'HSG &mdash; Group 4495<br><em>Programming - Introduction Level</em>'
            '</div>',
            unsafe_allow_html=True,
        )

    # call the correct page renderer depending on which mode the user selected
    if mode == "Find nearby":
        render_static_mode()
    else:
        render_dynamic_mode()


# run the whole thing
if __name__ == "__main__":
    main()
