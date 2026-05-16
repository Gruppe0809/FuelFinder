"""
FuelFinder v2 — Streamlit web app for live fuel-price comparison and trip planning.

The app has two modes:
  1. "Find nearby"   — enter a location and radius, see the cheapest stations on a map
  2. "Trip planner"  — enter start/destination, the app finds the optimal refuel stops

Data sources:
  - Germany  : Tankerkoenig API  (requires free API key)
  - Austria  : E-Control / Spritpreisrechner.at API  (no key needed)
  - Switzerland : OpenStreetMap Overpass API  (no key needed, locations only — no prices)

Maps & routing powered by Mapbox (free tier).

Run locally:
    pip install -r requirements.txt
    cp .env.example .env       # fill in your API keys
    streamlit run main.py      # opens http://localhost:8501

Project: HSG "Programming - Introduction Level", Group 4495.
"""

# ===========================================================================
# 1. IMPORTS & SETUP
# ===========================================================================

import math                           # for haversine distance formula
import os                             # for reading environment variables
from concurrent.futures import ThreadPoolExecutor, as_completed  # parallel API calls
from dataclasses import dataclass, field  # for clean data container classes
from typing import Optional           # for type hints (Optional = value or None)

import certifi                       # trusted SSL certificate bundle (fixes macOS SSL issues)
import folium                        # interactive map rendering
import pandas as pd                  # data tables
import requests                      # HTTP calls to all external APIs
import streamlit as st               # the web app framework
from dotenv import load_dotenv       # reads API keys from the .env file
from geopy.geocoders import Nominatim  # fallback geocoder if Mapbox is unavailable
from streamlit_folium import st_folium  # embeds folium maps inside Streamlit
from streamlit_searchbox import st_searchbox  # address autocomplete search box widget
from urllib.parse import quote as url_quote   # URL-encodes strings for API requests

# macOS Python (installed from python.org) ships without system SSL certificates.
# Pointing requests at certifi's own bundle fixes "SSL certificate verify failed" errors.
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

# Import shared constants from config.py so they live in one place.
from config import (
    DEFAULT_FUEL_TYPE,        # which fuel type is pre-selected in the UI
    DEFAULT_RADIUS_KM,        # default search radius in km
    FUEL_TYPES,               # list of supported fuel types: ["E5", "E10", "Diesel"]
    MAX_RADIUS_KM,            # slider upper limit
    OSRM_URL,                 # fallback routing server (used if no Mapbox token)
    ROUTE_CORRIDOR_KM,        # how far off the route a station can be and still count
    ROUTE_SAMPLE_INTERVAL_KM, # how often we sample the route to search for stations
    TOP_N_RESULTS,            # max stations to show in the results table
)

# ---------------------------------------------------------------------------
# Custom CSS — injected once in main() via st.markdown(unsafe_allow_html=True)
# ---------------------------------------------------------------------------
_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

/* ── Global typography ─────────────────────────────────────────────────── */
html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
}

/* ── Hide default Streamlit chrome ─────────────────────────────────────── */
#MainMenu, footer { visibility: hidden; }
[data-testid="stToolbar"]    { display: none !important; }
[data-testid="stDecoration"] { display: none !important; }

/* ── Page background ───────────────────────────────────────────────────── */
.stApp { background: #0D1117; }

/* ── Tighten the main content padding ─────────────────────────────────── */
.main .block-container {
    padding-top: 2.5rem !important;
    padding-left: 3rem   !important;
    padding-right: 3rem  !important;
    max-width: 1400px    !important;
}

/* ── Sidebar ───────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] > div:first-child {
    background: #010409 !important;
    border-right: 1px solid #21262D !important;
    padding: 2rem 1.5rem !important;
}

/* ── Primary button ────────────────────────────────────────────────────── */
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
.stButton > button[kind="primary"]:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 5px 18px rgba(249,115,22,0.45) !important;
}
.stButton > button[kind="primary"]:active {
    transform: translateY(0) !important;
}

/* ── Metric cards ──────────────────────────────────────────────────────── */
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

/* ── Progress bar ──────────────────────────────────────────────────────── */
.stProgress > div > div > div > div {
    background: linear-gradient(90deg, #F97316, #DC6309) !important;
    border-radius: 4px !important;
}

/* ── Alerts ────────────────────────────────────────────────────────────── */
[data-testid="stAlert"] { border-radius: 10px !important; }

/* ── Expander ──────────────────────────────────────────────────────────── */
details summary {
    border-radius: 8px !important;
    font-weight: 500 !important;
    font-size: 0.875rem !important;
}

/* ── Dividers ──────────────────────────────────────────────────────────── */
hr {
    border-color: #21262D !important;
    margin: 1rem 0 !important;
}

/* ── DataFrames ────────────────────────────────────────────────────────── */
[data-testid="stDataFrame"] > div {
    border: 1px solid #21262D !important;
    border-radius: 12px !important;
    overflow: hidden !important;
}

/* ── Captions ──────────────────────────────────────────────────────────── */
.stCaption p { color: #6E7681 !important; font-size: 0.78rem !important; }

/* ── Custom component classes used in this app ─────────────────────────── */

/* Page hero header */
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

/* Section label (replaces st.subheader) */
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

/* Sidebar brand block */
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

/* Sidebar nav pill */
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

/* Sidebar footer links */
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

/* Result count badge */
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

# Load key=value pairs from the .env file into the process environment.
# This makes TANKERKOENIG_API_KEY and MAPBOX_TOKEN available via os.getenv().
load_dotenv()

# ---------------------------------------------------------------------------
# API endpoint URLs
# ---------------------------------------------------------------------------
TANKERKOENIG_URL    = "https://creativecommons.tankerkoenig.de/json/list.php"
ECONTROL_URL        = "https://api.e-control.at/sprit/1.0/search/gas-stations/by-address"
OVERPASS_URL        = "https://overpass-api.de/api/interpreter"
MAPBOX_GEOCODING_URL  = "https://api.mapbox.com/geocoding/v5/mapbox.places"
MAPBOX_DIRECTIONS_URL = "https://api.mapbox.com/directions/v5/mapbox/driving"

# Many APIs (Nominatim, Overpass) require a descriptive User-Agent string
# so they can identify and contact us if our usage causes problems.
USER_AGENT = "FuelFinder/2.0 (HSG Group 4495 - student project)"

# Tankerkoenig hard-caps the search radius at 25 km regardless of what we send.
TANKERKOENIG_MAX_RADIUS = 25

# Approximate bounding boxes for each country (lat_min, lat_max, lon_min, lon_max).
# Used to skip country API calls when the search point is clearly outside that country,
# which is the main speed-up for the trip planner on routes that don't cross all three.
_DE_BBOX = (47.3, 55.1,  5.9, 15.0)
_AT_BBOX = (46.4, 49.0,  9.5, 17.2)
_CH_BBOX = (45.8, 47.9,  5.9, 10.5)


def _near_country(lat: float, lon: float, radius_km: float,
                  bbox: tuple[float, float, float, float]) -> bool:
    """Return True if the search circle could overlap the given country bounding box."""
    lat_min, lat_max, lon_min, lon_max = bbox
    # Convert radius to degrees (rough but good enough for a bounding-box pre-check)
    buf = radius_km / 111.0
    return (lat - buf < lat_max and lat + buf > lat_min and
            lon - buf < lon_max and lon + buf > lon_min)


# ---------------------------------------------------------------------------
# API key helpers — check .env first, then Streamlit Cloud secrets
# ---------------------------------------------------------------------------

def get_api_key() -> str:
    """Return the Tankerkoenig API key, or empty string if not configured."""
    key = os.getenv("TANKERKOENIG_API_KEY", "").strip()
    if key:
        return key
    # On Streamlit Cloud, secrets are stored in the dashboard rather than .env
    try:
        return st.secrets.get("TANKERKOENIG_API_KEY", "").strip()
    except Exception:
        return ""


def get_mapbox_token() -> str:
    """Return the Mapbox access token, or empty string if not configured."""
    token = os.getenv("MAPBOX_TOKEN", "").strip()
    if token:
        return token
    try:
        return st.secrets.get("MAPBOX_TOKEN", "").strip()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Mapbox geocoding helpers (used by the address search box)
# ---------------------------------------------------------------------------

# Module-level dict that caches geocoding results from the search box.
# When the user picks a suggestion, its coordinates are stored here so
# we can look them up instantly when the Search / Plan trip button is clicked
# without making a second API call.
_geo_cache: dict[str, "GeoResult"] = {}


def _mapbox_suggestions(query: str) -> list[str]:
    """
    Called by st_searchbox on every keystroke.
    Sends the partial query to the Mapbox Geocoding API and returns up to 5
    matching place names. Coordinates are stored in _geo_cache for later lookup.
    """
    if len(query) < 2:
        # Don't call the API for very short queries — avoids spamming requests
        return []
    token = get_mapbox_token()
    if not token:
        return []  # can't search without a token

    # The search text goes in the URL path, so it must be URL-encoded
    url = f"{MAPBOX_GEOCODING_URL}/{url_quote(query, safe='')}.json"
    try:
        resp = requests.get(url, params={"access_token": token, "limit": 5}, timeout=5)
        data = resp.json()
    except Exception:
        return []  # silently return no suggestions on network error

    results = []
    for f in data.get("features", []):
        name = f["place_name"]          # human-readable address string
        lon, lat = f["center"]          # Mapbox returns [longitude, latitude]
        # Store the coordinates under the place name so we can retrieve them later
        _geo_cache[name] = GeoResult(lat=lat, lon=lon, address=name)
        results.append(name)
    return results


def _mapbox_tile_url() -> Optional[str]:
    """
    Returns the Mapbox Streets tile URL template for folium.
    The {z}/{x}/{y} placeholders are filled by folium at render time.
    Double braces {{ }} produce literal { } in the f-string.
    Returns None if no token is set (folium falls back to OpenStreetMap).
    """
    token = get_mapbox_token()
    if not token:
        return None
    return (
        f"https://api.mapbox.com/styles/v1/mapbox/streets-v12/tiles/256"
        f"/{{z}}/{{x}}/{{y}}?access_token={token}"
    )


# ===========================================================================
# 2. DATA LAYER — data classes, geocoding, distance, country fetchers
# ===========================================================================

@dataclass
class GeoResult:
    """Holds the result of a geocoding lookup: coordinates + display address."""
    lat: float
    lon: float
    address: str


@dataclass
class FetchResult:
    """
    Container returned by every country fetcher.
    stations — list of station dicts (one per station found)
    warnings — non-fatal messages shown to the user (e.g. API key missing)
    """
    stations: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def extend(self, other: "FetchResult") -> None:
        """Merge another FetchResult into this one (used in gather_all)."""
        self.stations.extend(other.stations)
        self.warnings.extend(other.warnings)


# ---------------------------------------------------------------------------
# Distance calculation
# ---------------------------------------------------------------------------

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the straight-line distance between two GPS coordinates in km.
    Uses the Haversine formula, which accounts for the Earth's curvature.
    This is more accurate than a flat Euclidean distance for geographic points.
    """
    R = 6371.0  # Earth's mean radius in km
    # Convert degrees to radians (math trig functions require radians)
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)   # latitude difference
    dlmb = math.radians(lon2 - lon1)   # longitude difference
    # Haversine formula
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Geocoding — convert a place name or address to coordinates
# ---------------------------------------------------------------------------

@st.cache_data(ttl=86400, show_spinner=False)
def geocode(query: str) -> Optional[GeoResult]:
    """
    Convert a free-text location (city name, postcode, address) to lat/lon.
    Results are cached for 24 hours (ttl=86400 seconds) so repeated lookups
    of the same location don't re-call the API.

    Priority:
      1. Check _geo_cache (populated by the search box — instant, no API call)
      2. Mapbox Geocoding API (if token is set)
      3. Nominatim / OpenStreetMap (free fallback, no key needed)
    """
    # If the user selected this from the autocomplete dropdown, we already
    # have the coordinates cached — return immediately without an API call.
    if query in _geo_cache:
        return _geo_cache[query]

    token = get_mapbox_token()
    if token:
        # Use Mapbox Geocoding API — faster and more accurate than Nominatim
        url = f"{MAPBOX_GEOCODING_URL}/{url_quote(query, safe='')}.json"
        try:
            resp = requests.get(url, params={"access_token": token, "limit": 1}, timeout=10)
            data = resp.json()
            features = data.get("features", [])
            if not features:
                return None
            f = features[0]
            lon, lat = f["center"]  # Mapbox returns [lon, lat], not [lat, lon]
            return GeoResult(lat=lat, lon=lon, address=f["place_name"])
        except Exception:
            return None

    # Fallback: Nominatim (OpenStreetMap's free geocoder, no API key needed)
    geocoder = Nominatim(user_agent=USER_AGENT, timeout=10)
    try:
        location = geocoder.geocode(query)
    except Exception:
        return None
    if location is None:
        return None
    return GeoResult(lat=location.latitude, lon=location.longitude, address=location.address)


# ---------------------------------------------------------------------------
# Country fetchers — one function per data source
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def fetch_germany(lat: float, lon: float, radius_km: float, fuel_type: str) -> FetchResult:
    """
    Fetch live German fuel prices from the Tankerkoenig API.
    Results are cached for 5 minutes (ttl=300) — prices update frequently.
    Requires a free API key from creativecommons.tankerkoenig.de.

    The API returns stations sorted by price (cheapest first).
    Only open stations with a known price are included in the result.
    """
    result = FetchResult()

    # Skip immediately if the search point is clearly outside Germany
    if not _near_country(lat, lon, radius_km, _DE_BBOX):
        return result

    api_key = get_api_key()

    # Skip Germany entirely if no API key is configured
    if not api_key:
        result.warnings.append("Germany skipped: TANKERKOENIG_API_KEY not set.")
        return result

    # The API hard-caps the radius at 25 km — cap our request and warn the user
    capped = min(radius_km, TANKERKOENIG_MAX_RADIUS)
    if radius_km > TANKERKOENIG_MAX_RADIUS:
        result.warnings.append(
            f"Germany radius capped at {TANKERKOENIG_MAX_RADIUS} km (Tankerkoenig API limit)."
        )

    # Map our fuel type names to the API's expected values
    params = {
        "lat": lat, "lng": lon, "rad": capped,
        "sort": "price",   # return cheapest stations first
        "type": {"E5": "e5", "E10": "e10", "Diesel": "diesel"}[fuel_type],
        "apikey": api_key,
    }

    try:
        resp = requests.get(TANKERKOENIG_URL, params=params, timeout=15)
        resp.raise_for_status()  # raises an exception if HTTP status is 4xx/5xx
        data = resp.json()
    except requests.RequestException as e:
        result.warnings.append(f"Germany unavailable: {e}")
        return result

    # The API signals errors in the response body rather than HTTP status codes
    if not data.get("ok"):
        result.warnings.append(f"Germany unavailable: {data.get('message', 'unknown error')}")
        return result

    # Parse each station from the API response into our standard station dict format
    for s in data.get("stations", []):
        if not s.get("isOpen"):
            continue  # skip closed stations
        price = s.get("price")
        if not price:
            continue  # skip stations with no price reported

        # Build a readable address string from the separate address fields
        street = (s.get("street") or "").strip()
        house  = (s.get("houseNumber") or "").strip()
        post   = str(s.get("postCode") or "").strip()
        place  = (s.get("place") or "").strip()

        result.stations.append({
            "name":        (s.get("name") or "Unknown").strip(),
            "brand":       (s.get("brand") or "").strip(),
            "address":     f"{street} {house}, {post} {place}".strip(", ").strip(),
            "country":     "DE",
            "lat":         s.get("lat"),
            "lon":         s.get("lng"),
            "price":       float(price),
            "fuel_type":   fuel_type,
            "distance_km": float(s.get("dist", 0.0)),
            "source":      "Tankerkoenig",
        })
    return result


@st.cache_data(ttl=300, show_spinner=False)
def fetch_austria(lat: float, lon: float, radius_km: float, fuel_type: str) -> FetchResult:
    """
    Fetch Austrian fuel station data from the E-Control / Spritpreisrechner.at API.
    No API key required — this is a public government API.

    Important limitations:
    - The API ignores the radius parameter and always returns the ~10 nearest stations.
      We apply our own distance filter client-side.
    - Austria has no E5/E10 distinction — both map to "SUP" (Super 95).
    - Prices may be empty outside business hours (Austrian law allows price changes
      only at 12:00, 14:00, and 16:00). When empty, stations still appear as grey markers.
    """
    result = FetchResult()

    # Skip immediately if the search point is clearly outside Austria
    if not _near_country(lat, lon, radius_km, _AT_BBOX):
        return result

    # Map our fuel type names to the E-Control API's expected values
    fuel_map = {"E5": "SUP", "E10": "SUP", "Diesel": "DIE"}
    params = {
        "latitude":     lat,
        "longitude":    lon,
        "fuelType":     fuel_map[fuel_type],
        "includeClosed": "false",  # only return currently open stations
    }

    try:
        resp = requests.get(
            ECONTROL_URL, params=params,
            headers={"User-Agent": USER_AGENT}, timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()  # returns a list of station objects
    except requests.RequestException as e:
        result.warnings.append(f"Austria unavailable: {e}")
        return result

    for s in data:
        loc = s.get("location") or {}
        slat, slon = loc.get("latitude"), loc.get("longitude")
        if slat is None or slon is None:
            continue  # skip stations with no GPS coordinates

        # Apply our own radius filter since the API ignores it
        d = haversine_km(lat, lon, slat, slon)
        if d > radius_km:
            continue

        # Extract the price — may be empty outside reporting hours
        prices = s.get("prices") or []
        amount = prices[0].get("amount") if prices else None

        # Build a readable address from the location sub-object
        addr_parts = [
            (loc.get("address") or "").strip(),
            f"{(loc.get('postalCode') or '').strip()} {(loc.get('city') or '').strip()}".strip(),
        ]
        result.stations.append({
            "name":        (s.get("name") or "Unknown").strip(),
            "brand":       "",  # E-Control API does not return brand information
            "address":     ", ".join(p for p in addr_parts if p),
            "country":     "AT",
            "lat":         slat,
            "lon":         slon,
            "price":       float(amount) if amount else None,  # None = no price available
            "fuel_type":   fuel_type,
            "distance_km": d,
            "source":      "Spritpreisrechner.at",
        })
    return result


@st.cache_data(ttl=300, show_spinner=False)
def fetch_switzerland(lat: float, lon: float, radius_km: float, fuel_type: str) -> FetchResult:
    """
    Fetch Swiss fuel station locations from the OpenStreetMap Overpass API.
    No API key required — Overpass is a free public service.

    Important limitation:
    Switzerland has NO public fuel price database. This function returns station
    locations only (shown as grey markers with no price). Prices are occasionally
    tagged in OSM by volunteers, but this is rare.

    The Overpass query filters by the Switzerland country area (ISO3166-1 = CH)
    to prevent stations from neighbouring countries (e.g. Austria near Vienna)
    from being incorrectly included.
    """
    result = FetchResult()

    # Skip the slow Overpass call if the search point is clearly outside Switzerland.
    # This is the biggest single speed-up for routes that don't pass through Switzerland.
    if not _near_country(lat, lon, radius_km, _CH_BBOX):
        return result

    radius_m = int(radius_km * 1000)  # Overpass requires the radius in metres

    # Overpass QL query:
    # - First define Switzerland as an area using its ISO country code
    # - Then find all fuel nodes/ways within our search radius AND inside that area
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
        # Overpass uses POST requests for queries
        resp = requests.post(
            OVERPASS_URL, data={"data": overpass_query},
            headers={"User-Agent": USER_AGENT}, timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        result.warnings.append(f"Switzerland unavailable: {e}")
        return result

    for el in data.get("elements", []):
        tags = el.get("tags") or {}

        # OSM returns either nodes (points) or ways (polygons for large stations).
        # Ways have a "center" field with the centroid coordinates.
        if el.get("type") == "node":
            slat, slon = el.get("lat"), el.get("lon")
        else:
            c = el.get("center") or {}
            slat, slon = c.get("lat"), c.get("lon")

        if slat is None or slon is None:
            continue

        # Apply distance filter (Overpass "around" is approximate)
        d = haversine_km(lat, lon, slat, slon)
        if d > radius_km:
            continue

        # Some OSM contributors tag fuel prices — check for common key formats
        price = None
        for key in (f"charge:{fuel_type.lower()}", f"price:{fuel_type.lower()}"):
            if key in tags:
                try:
                    price = float(tags[key])
                    break
                except ValueError:
                    pass  # ignore non-numeric price tags

        # Build address from OSM address tags (often incomplete or missing)
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
            "price":       price,  # None for almost all Swiss stations
            "fuel_type":   fuel_type,
            "distance_km": d,
            "source":      "OpenStreetMap",
        })
    return result


# ---------------------------------------------------------------------------
# Aggregator — merge all three country results into one sorted list
# ---------------------------------------------------------------------------

def gather_all(lat: float, lon: float, radius_km: float, fuel_type: str) -> FetchResult:
    """
    Run all three country fetchers in sequence and combine their results.

    Sorting order:
      1. Stations WITH a price come first, sorted cheapest to most expensive.
      2. Stations WITHOUT a price (Switzerland, and Austria outside reporting hours)
         come last, sorted by distance.
    """
    combined = FetchResult()
    combined.extend(fetch_germany(lat, lon, radius_km, fuel_type))
    combined.extend(fetch_austria(lat, lon, radius_km, fuel_type))
    combined.extend(fetch_switzerland(lat, lon, radius_km, fuel_type))

    combined.stations.sort(
        key=lambda s: (
            s["price"] is None,   # False (has price) sorts before True (no price)
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
    """A driving route returned by the Mapbox Directions / OSRM API."""
    points: list[tuple[float, float]]  # ordered list of (lat, lon) waypoints
    total_km: float                    # total driving distance in km


@dataclass
class RefuelStop:
    """One refuelling decision made by the optimiser."""
    station: dict   # the station dict from gather_all
    liters: float   # how many litres to buy at this stop
    cost: float     # total cost at this stop (liters × price per litre)


@dataclass
class TripPlan:
    """The complete output of the trip optimiser."""
    stops: list[RefuelStop]   # ordered list of refuel stops
    total_cost: float         # sum of all stop costs
    total_distance_km: float  # total route length
    fuel_remaining_l: float   # fuel left in the tank on arrival
    feasible: bool            # False if the trip cannot be completed with the given tank
    message: str = ""         # explanation when feasible=False


# ---------------------------------------------------------------------------
# Routing — get a driving route between two points
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def get_route(start_lat: float, start_lon: float,
              end_lat: float, end_lon: float) -> Optional[Route]:
    """
    Fetch a driving route from Mapbox Directions (falls back to OSRM if no token).
    Result is cached for 1 hour — routes between fixed points don't change.

    Both Mapbox and OSRM use longitude-first coordinate order in their URLs,
    which is the opposite of the (lat, lon) convention used everywhere else.
    We swap back to (lat, lon) when building the Route object.
    """
    token = get_mapbox_token()
    # Coordinates in the URL must be lon,lat (note the swap)
    coords = f"{start_lon},{start_lat};{end_lon},{end_lat}"

    if token:
        url    = f"{MAPBOX_DIRECTIONS_URL}/{coords}"
        params = {"geometries": "geojson", "overview": "full", "access_token": token}
    else:
        # Fallback to the public OSRM demo server (no key needed)
        url    = f"{OSRM_URL}/{coords}"
        params = {"overview": "full", "geometries": "geojson"}

    try:
        resp = requests.get(url, params=params, timeout=20,
                            headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException:
        return None

    routes = data.get("routes", [])
    if not routes:
        return None

    route = routes[0]
    # GeoJSON coordinates are [lon, lat] — swap to our (lat, lon) convention
    points = [(c[1], c[0]) for c in route["geometry"]["coordinates"]]
    return Route(points=points, total_km=route["distance"] / 1000.0)


# ---------------------------------------------------------------------------
# Route geometry helpers
# ---------------------------------------------------------------------------

def _cumulative_km(points: list[tuple[float, float]]) -> list[float]:
    """
    For each point along the route, calculate the total km driven from the start.
    This turns a list of GPS points into a list of distances like [0, 1.2, 3.5, ...].
    Used to position stations along the route in the optimiser.
    """
    cum = [0.0]
    for i in range(1, len(points)):
        cum.append(cum[-1] + haversine_km(*points[i - 1], *points[i]))
    return cum


def _project_onto_route(
    station_lat: float, station_lon: float,
    points: list[tuple[float, float]], cumulative: list[float],
) -> tuple[float, float]:
    """
    Find the closest point on the route to a given station.

    Returns:
      route_km    — how far along the route (in km) the closest point is
      offroad_km  — how far the station is from that closest point (detour distance)

    This lets us sort stations by their position along the route, and filter out
    stations that are too far off the road to be worth stopping at.
    """
    best_dist = float("inf")
    best_km   = 0.0
    for i, (plat, plon) in enumerate(points):
        d = haversine_km(station_lat, station_lon, plat, plon)
        if d < best_dist:
            best_dist = d
            best_km   = cumulative[i]
    return best_km, best_dist


# ---------------------------------------------------------------------------
# Corridor station search — find priced stations along the route
# ---------------------------------------------------------------------------

def stations_along_route(
    route: Route,
    fuel_type: str,
    sample_interval_km: float = ROUTE_SAMPLE_INTERVAL_KM,
    corridor_km: float = ROUTE_CORRIDOR_KM,
    progress_callback=None,
) -> tuple[list[dict], list[str]]:
    """
    Find all priced fuel stations within a corridor around the driving route.

    Strategy:
      1. Pick evenly-spaced sample points along the route every `sample_interval_km`.
      2. Call gather_all() at each sample point to fetch nearby stations.
      3. Discard stations farther than `corridor_km` from the route line.
      4. Deduplicate: the same station may appear at multiple sample points.
      5. Sort stations by their position along the route (route_km).

    The result is a list of station dicts with two extra fields added:
      route_km   — position along the route where you would stop (km from start)
      offroad_km — how far off the main road the station is
    """
    cumulative = _cumulative_km(route.points)

    # Build a list of indices into route.points, one per sample interval
    sample_indices: list[int] = [0]
    next_target = sample_interval_km
    for i, c in enumerate(cumulative):
        if c >= next_target:
            sample_indices.append(i)
            next_target += sample_interval_km
    # Always include the final point so we don't miss stations near the destination
    if sample_indices[-1] != len(route.points) - 1:
        sample_indices.append(len(route.points) - 1)

    # Use a slightly larger API radius than the corridor to catch stations
    # that are near the line but might be just outside a tight radius query
    api_radius_km = max(corridor_km * 2, 8)

    seen: set[tuple[float, float]] = set()  # tracks (lat, lon) pairs already added
    found: list[dict] = []
    warnings: list[str] = []

    # Fetch all waypoints in parallel instead of sequentially.
    # ThreadPoolExecutor spawns worker threads — each thread calls gather_all() for
    # one waypoint while the others run concurrently. For a 600 km route this turns
    # ~30 sequential API calls into a single parallel batch, cutting wait time
    # from ~60 s down to roughly the time of the single slowest call.
    waypoint_coords = [route.points[idx] for idx in sample_indices]
    total = len(waypoint_coords)
    results_ordered: list[FetchResult] = [FetchResult()] * total

    with ThreadPoolExecutor(max_workers=8) as executor:
        # Submit one task per waypoint, keyed by its index so we can order results
        future_to_n = {
            executor.submit(gather_all, plat, plon, api_radius_km, fuel_type): n
            for n, (plat, plon) in enumerate(waypoint_coords)
        }
        completed = 0
        for future in as_completed(future_to_n):
            n = future_to_n[future]
            results_ordered[n] = future.result()
            completed += 1
            if progress_callback:
                # Update progress bar from the main thread as each future finishes
                progress_callback(completed - 1, total)

    # Process results in route order (deduplicate across all waypoints)
    for result in results_ordered:
        # Deduplicate warning messages
        for w in result.warnings:
            if w not in warnings:
                warnings.append(w)

        for s in result.stations:
            if s["price"] is None:
                continue  # corridor optimiser needs actual prices to compare

            # Deduplicate stations by rounded coordinates (4 decimal places ≈ 11m)
            key = (round(s["lat"], 4), round(s["lon"], 4))
            if key in seen:
                continue
            seen.add(key)

            # Find where this station projects onto the route
            route_km, offroad_km = _project_onto_route(
                s["lat"], s["lon"], route.points, cumulative
            )
            if offroad_km > corridor_km:
                continue  # station is too far off the road

            # Add route position fields to the station dict
            enriched = dict(s)
            enriched["route_km"]   = route_km
            enriched["offroad_km"] = offroad_km
            found.append(enriched)

    # Sort stations in driving order (by position along the route)
    found.sort(key=lambda s: s["route_km"])
    return found, warnings


# ---------------------------------------------------------------------------
# Cost-optimal refuel planning — the "gas station problem" algorithm
# ---------------------------------------------------------------------------

def plan_trip(
    stations: list[dict],
    total_distance_km: float,
    tank_capacity_l: float,
    current_fuel_l: float,
    consumption_l_per_100km: float,
) -> TripPlan:
    """
    Find the cheapest set of refuel stops for a given route.

    This implements the classical "Gas Station Problem" greedy algorithm
    (Khuller, Mitchell & Vazirani 2007). The rule at each station is:

      - If a CHEAPER station is reachable on our current tank:
          Buy just enough fuel to reach that cheaper station.
          (No point paying more here when cheaper fuel is ahead.)

      - If NO cheaper station is reachable:
          Fill the tank completely.
          (Current station is the cheapest option in range — stock up now.)

    The destination is added as a virtual "free" station (price = 0) so the
    algorithm naturally stops buying fuel once the destination is reachable.

    Returns TripPlan with feasible=False if a gap between stations exceeds
    the vehicle's maximum range on a full tank.
    """
    consumption_per_km = consumption_l_per_100km / 100.0
    fuel_range_km = tank_capacity_l / consumption_per_km  # max range on a full tank

    # Validate inputs
    if tank_capacity_l <= 0 or consumption_l_per_100km <= 0:
        return TripPlan([], 0.0, total_distance_km, current_fuel_l, False,
                        "Tank capacity and consumption must be positive.")
    if current_fuel_l > tank_capacity_l:
        return TripPlan([], 0.0, total_distance_km, current_fuel_l, False,
                        "Current fuel exceeds tank capacity.")

    # Add the destination as a virtual station with price=0 at the end of the route
    DEST = {
        "name": "Destination", "lat": None, "lon": None,
        "price": 0.0, "route_km": total_distance_km,
        "country": "-", "brand": "",
    }
    # Only include stations that are strictly between start and destination
    points = [s for s in stations if 0 < s["route_km"] < total_distance_km] + [DEST]

    pos_km = 0.0          # current position along the route (km from start)
    fuel_l = current_fuel_l
    stops: list[RefuelStop] = []

    while pos_km < total_distance_km - 1e-6:
        # Check if we are currently standing at a station
        current = next(
            (p for p in points if abs(p["route_km"] - pos_km) < 1e-3 and p is not DEST),
            None
        )

        # Maximum fuel we can have at this position
        max_fuel_here = tank_capacity_l if current is not None else fuel_l
        reach_km = pos_km + max_fuel_here / consumption_per_km

        # All stations/destination we can reach from here
        candidates = [p for p in points if pos_km < p["route_km"] <= reach_km + 1e-6]

        if not candidates:
            # Even a full tank can't reach the next station — trip is infeasible
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
            # We're at the start and not at a station — just drive to the cheapest reachable point
            target = min(candidates, key=lambda p: p["price"])
            distance = target["route_km"] - pos_km
            fuel_l -= distance * consumption_per_km
            pos_km = target["route_km"]
            continue

        # Apply the greedy lookahead rule
        cheaper_ahead = [p for p in candidates if p["price"] < current["price"]]

        if cheaper_ahead:
            # A cheaper station is in range — buy just enough to reach it
            next_cheaper = min(cheaper_ahead, key=lambda p: p["route_km"])
            distance     = next_cheaper["route_km"] - pos_km
            fuel_needed  = distance * consumption_per_km
            buy          = max(0.0, fuel_needed - fuel_l)  # only buy what we're short
            target       = next_cheaper
        else:
            # Nothing cheaper in range — fill up and drive as far as possible
            buy      = tank_capacity_l - fuel_l
            target   = max(candidates, key=lambda p: p["route_km"])
            distance = target["route_km"] - pos_km

        if buy > 0:
            stops.append(RefuelStop(
                station=current, liters=buy, cost=buy * current["price"],
            ))
            fuel_l += buy

        # Drive to the chosen target
        fuel_l -= distance * consumption_per_km
        pos_km  = target["route_km"]

        # Correct tiny floating-point errors (e.g. -0.000001 litres)
        if -1e-6 < fuel_l < 0:
            fuel_l = 0.0
        if fuel_l < 0:
            return TripPlan(stops, sum(s.cost for s in stops), total_distance_km,
                            fuel_l, False, "Ran out of fuel - refuel logic error.")

    return TripPlan(
        stops=stops,
        total_cost=sum(s.cost for s in stops),
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
    Build the interactive map for Mode 01 (Find nearby).

    Markers are colour-coded by price tier:
      Green  = cheapest third of stations
      Orange = middle third
      Red    = most expensive third
      Grey   = no price data (Switzerland, or Austria outside reporting hours)
    """
    # Use Mapbox Streets tiles if a token is available, else fall back to OpenStreetMap
    tile_url = _mapbox_tile_url()
    fmap = folium.Map(
        location=[origin_lat, origin_lon], zoom_start=11,
        tiles=tile_url or "OpenStreetMap",
        attr='© <a href="https://www.mapbox.com/">Mapbox</a>' if tile_url else "© OpenStreetMap contributors",
        max_zoom=22 if tile_url else 18,
    )

    # Blue home marker for the search location
    folium.Marker(
        [origin_lat, origin_lon],
        popup="Your search location",
        icon=folium.Icon(color="blue", icon="home", prefix="fa"),
    ).add_to(fmap)

    if not stations:
        return fmap

    # Calculate price tercile thresholds for colour-coding
    priced = sorted(s["price"] for s in stations if s["price"] is not None)
    if len(priced) >= 3:
        q_low  = priced[len(priced) // 3]       # top of the cheap third
        q_high = priced[2 * len(priced) // 3]   # top of the middle third
    else:
        q_low = q_high = float("inf")  # not enough stations to split into thirds

    for s in stations:
        # Assign colour based on price tier
        if s["price"] is None:
            color, price_str = "gray", "no price data"
        elif s["price"] <= q_low:
            color, price_str = "green", f"{s['price']:.3f}"
        elif s["price"] <= q_high:
            color, price_str = "orange", f"{s['price']:.3f}"
        else:
            color, price_str = "red", f"{s['price']:.3f}"

        # HTML content shown when the user clicks a marker
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
    Build the interactive map for Mode 02 (Trip planner).

    Shows:
      - A blue polyline for the driving route
      - Green flag markers at the start and end
      - Large green pin markers for the chosen refuel stops (numbered)
      - Small grey dots for other priced stations along the corridor
    """
    if not route.points:
        return folium.Map()

    # Centre the map on the route's midpoint
    mid = route.points[len(route.points) // 2]
    tile_url = _mapbox_tile_url()
    fmap = folium.Map(
        location=mid, zoom_start=7,
        tiles=tile_url or "OpenStreetMap",
        attr='© <a href="https://www.mapbox.com/">Mapbox</a>' if tile_url else "© OpenStreetMap contributors",
        max_zoom=22 if tile_url else 18,
    )

    # Draw the full driving route as a blue line
    folium.PolyLine(route.points, color="#185FA5", weight=5, opacity=0.7).add_to(fmap)

    # Start and destination markers
    folium.Marker(route.points[0], popup="Start",
                  icon=folium.Icon(color="green", icon="play", prefix="fa")).add_to(fmap)
    folium.Marker(route.points[-1], popup="Destination",
                  icon=folium.Icon(color="red", icon="flag-checkered", prefix="fa")).add_to(fmap)

    # Collect coordinates of chosen stops so we can skip them in the grey dot loop
    chosen_keys = {(s.station["lat"], s.station["lon"]) for s in plan.stops
                   if s.station["lat"] is not None}

    # Draw all other corridor stations as small grey dots (not chosen by optimiser)
    for s in all_corridor_stations:
        if (s["lat"], s["lon"]) in chosen_keys:
            continue
        folium.CircleMarker(
            location=[s["lat"], s["lon"]],
            radius=4,
            color="#9a948c",
            fill=True, fill_opacity=0.4, weight=0,
            popup=folium.Popup(
                f"<b>{s['name']}</b><br>{fuel_type}: {s['price']:.3f}<br>"
                f"At km {s['route_km']:.0f} of route",
                max_width=240,
            ),
        ).add_to(fmap)

    # Draw chosen refuel stops as large numbered green markers
    for n, stop in enumerate(plan.stops, start=1):
        s = stop.station
        if s["lat"] is None:
            continue  # skip the virtual destination sentinel
        popup_html = (
            f"<b>Stop {n}: {s['name']}</b><br>"
            f"{fuel_type}: <b>{s['price']:.3f}</b> / L<br>"
            f"Refuel: <b>{stop.liters:.1f} L</b> "
            f"(EUR{stop.cost:.2f})<br>"
            f"At km {s['route_km']:.0f} of route<br>"
            f"{s['country']} ({s['source']})"
        )
        folium.Marker(
            location=[s["lat"], s["lon"]],
            popup=folium.Popup(popup_html, max_width=280),
            icon=folium.Icon(color="green", icon="gas-pump", prefix="fa"),
            tooltip=f"Stop {n} - {stop.liters:.1f} L",
        ).add_to(fmap)

    return fmap


# ---------------------------------------------------------------------------
# Page renderers — one function per app mode
# ---------------------------------------------------------------------------

def render_static_mode() -> None:
    """
    Mode 01 — Find nearby fuel stations.

    Flow:
      1. User types a location into the autocomplete search box.
      2. Mapbox Geocoding API returns suggestions as they type.
      3. User selects a suggestion and clicks Search.
      4. We call all three country fetchers in parallel (cached) and display results.
    """
    st.markdown(
        '<div class="ff-page-header">'
        '<h1>Find nearby fuel</h1>'
        '<p>Live prices for E5, E10 and Diesel across Germany, Austria and Switzerland.</p>'
        '</div>',
        unsafe_allow_html=True,
    )

    # --- Input row ---
    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        # st_searchbox calls _mapbox_suggestions() on every keystroke and shows a dropdown.
        # The return value is the place name the user selected (or None if nothing selected).
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

    search_clicked = st.button("Search", type="primary", key="static_search")

    # Only run the search when the button is clicked
    if search_clicked:
        if not selected_place:
            st.error("Please select a location from the dropdown.")
            st.session_state.pop("search_result", None)
            return

        # Look up coordinates from the cache (set by _mapbox_suggestions when the
        # user typed and selected). If somehow not cached, fall back to geocode().
        geo = _geo_cache.get(selected_place)
        if geo is None:
            with st.spinner(f"Geocoding '{selected_place}'..."):
                geo = geocode(selected_place)
        if geo is None:
            st.error(f"Could not find '{selected_place}'.")
            st.session_state.pop("search_result", None)
            return

        # Fetch stations from all three countries
        with st.spinner("Fetching live prices from DE / AT / CH..."):
            result = gather_all(geo.lat, geo.lon, radius, fuel_type)

        # Store results in session_state so they survive Streamlit reruns
        # (Streamlit reruns the entire script on every user interaction)
        st.session_state.search_result = {
            "geo":       geo,
            "stations":  result.stations,
            "warnings":  result.warnings,
            "fuel_type": fuel_type,
        }

    # --- Display results (from session_state, persists across reruns) ---
    sr = st.session_state.get("search_result")
    if not sr:
        st.info("Enter a location above and click **Search** to find live fuel prices.")
        return

    geo           = sr["geo"]
    stations      = sr["stations"]
    warnings      = sr["warnings"]
    fuel_type_used = sr["fuel_type"]

    st.success(f"  {geo.address}")

    # Show any non-fatal API warnings in a collapsible section
    if warnings:
        with st.expander(f"  {len(warnings)} warning(s)"):
            for w in warnings:
                st.write(f"- {w}")

    # Limit display to TOP_N_RESULTS stations
    top = stations[:TOP_N_RESULTS]
    if not top:
        st.warning("No stations found in this radius. Try widening the search.")
        return

    st.markdown(
        f"**{len(stations)} stations** found - showing top **{len(top)}** for **{fuel_type_used}**."
    )

    # Map
    st.markdown('<div class="ff-section">Map</div>', unsafe_allow_html=True)
    fmap = build_map(top, geo.lat, geo.lon, fuel_type_used)
    st_folium(fmap, height=420, width='stretch', returned_objects=[])
    st.caption("Green = cheapest third | Orange = middle third | Red = most expensive | Grey = no price data")

    # Table
    st.markdown('<div class="ff-section">Stations</div>', unsafe_allow_html=True)
    df = pd.DataFrame(top)
    df.index = df.index + 1  # start index at 1 instead of 0
    df = df.rename(columns={
        "country": "Country", "name": "Station", "brand": "Brand",
        "address": "Address", "price": "Price", "distance_km": "Dist (km)",
        "source": "Source",
    })[["Country", "Station", "Brand", "Address", "Price", "Dist (km)", "Source"]]
    st.dataframe(
        df, width='stretch',
        column_config={
            "Price":      st.column_config.NumberColumn(format="%.3f"),
            "Dist (km)":  st.column_config.NumberColumn(format="%.1f"),
        },
    )


def render_dynamic_mode() -> None:
    """
    Mode 02 — Trip planner with cost-optimal refuel stops.

    Flow:
      1. User enters start and destination via autocomplete search boxes.
      2. User enters vehicle parameters (tank size, current fuel, consumption).
      3. On "Plan trip":
           a. Get route from Mapbox Directions API.
           b. Sample the route every ROUTE_SAMPLE_INTERVAL_KM and fetch stations.
           c. Run the gas station optimisation algorithm.
           d. Display the route map, stop table, and cost summary.
    """
    st.markdown(
        '<div class="ff-page-header">'
        '<h1>Trip planner</h1>'
        '<p>Plan a route and let us pick the cheapest places to stop.</p>'
        '</div>',
        unsafe_allow_html=True,
    )

    # --- Location inputs (autocomplete search boxes) ---
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

    # --- Vehicle parameters ---
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
        # Validate inputs before making any API calls
        if current_fuel > tank_capacity:
            st.error("Current fuel can't exceed tank capacity.")
            return
        if not start_q or not end_q:
            st.error("Please select both a start and a destination from the dropdowns.")
            return

        # Resolve coordinates (from cache if available, else geocode)
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

        # Step 1: Get the driving route
        with st.spinner("Computing driving route..."):
            route = get_route(start.lat, start.lon, end.lat, end.lon)
        if route is None:
            st.error("Could not compute a route between those points.")
            return

        # Step 2: Find stations along the route (slowest step — many API calls)
        progress_bar = st.progress(0.0, text="Searching for stations along the route...")
        def _progress(n: int, total: int) -> None:
            # Update the progress bar after each waypoint is searched
            progress_bar.progress((n + 1) / max(total, 1),
                                  text=f"Searching waypoint {n + 1} of {total}...")
        corridor_stations, corridor_warnings = stations_along_route(
            route, fuel_type, progress_callback=_progress,
        )
        progress_bar.empty()

        # Step 3: Run the cost-optimisation algorithm
        with st.spinner("Optimising refuel stops..."):
            plan = plan_trip(
                stations=corridor_stations,
                total_distance_km=route.total_km,
                tank_capacity_l=tank_capacity,
                current_fuel_l=current_fuel,
                consumption_l_per_100km=consumption,
            )

        # Store everything in session_state so results survive reruns
        st.session_state.trip_result = {
            "start":             start,
            "end":               end,
            "route":             route,
            "corridor_stations": corridor_stations,
            "corridor_warnings": corridor_warnings,
            "plan":              plan,
            "fuel_type":         fuel_type,
            "consumption":       consumption,
            "current_fuel":      current_fuel,
        }

    # --- Display results ---
    tr = st.session_state.get("trip_result")
    if not tr:
        st.info(
            "Fill in the inputs above and click **Plan trip**. "
            "We'll fetch a driving route, find every priced station along the way, "
            "and pick the cheapest places to stop using the classical *gas station "
            "problem* algorithm."
        )
        return

    plan              = tr["plan"]
    route             = tr["route"]
    fuel_type_used    = tr["fuel_type"]
    corridor_stations = tr["corridor_stations"]

    st.success(f"  {tr['start'].address}  ->  {tr['end'].address}")

    if tr["corridor_warnings"]:
        with st.expander(f"  {len(tr['corridor_warnings'])} warning(s)"):
            for w in tr["corridor_warnings"]:
                st.write(f"- {w}")

    if not plan.feasible:
        st.error(f"Trip not feasible: {plan.message}")
        return

    # --- Headline metrics ---
    # Calculate a "baseline cost" (what you'd pay buying fuel at the corridor average)
    # to show how much the optimiser saves compared to stopping anywhere.
    fuel_needed_total = max(0.0, route.total_km * tr["consumption"] / 100.0 - tr["current_fuel"])
    if corridor_stations:
        avg_price     = sum(s["price"] for s in corridor_stations) / len(corridor_stations)
        baseline_cost = fuel_needed_total * avg_price
    else:
        avg_price     = 0.0
        baseline_cost = 0.0

    metrics = st.columns(4)
    metrics[0].metric("Distance",       f"{route.total_km:,.0f} km")
    metrics[1].metric("Total fuel cost", f"EUR{plan.total_cost:,.2f}")
    metrics[2].metric("Refuel stops",   f"{len(plan.stops)}")
    if avg_price > 0:
        savings = baseline_cost - plan.total_cost
        metrics[3].metric(
            "vs. corridor average",
            f"EUR{plan.total_cost:,.2f}",
            delta=f"-EUR{savings:,.2f}" if savings >= 0 else f"+EUR{-savings:,.2f}",
            delta_color="inverse",  # green = we saved money (negative delta is good here)
        )
    else:
        metrics[3].metric("vs. average", "-")

    # --- Route map ---
    st.markdown('<div class="ff-section">Route and refuel stops</div>', unsafe_allow_html=True)
    fmap = build_trip_map(route, corridor_stations, plan, fuel_type_used)
    st_folium(fmap, height=460, width='stretch', returned_objects=[])
    st.caption(
        f"Green pin = chosen refuel stop | Grey dot = other priced station in corridor | "
        f"{len(corridor_stations)} priced stations along the route"
    )

    # --- Refuel stop table ---
    if plan.stops:
        st.markdown('<div class="ff-section">Refuel plan</div>', unsafe_allow_html=True)
        rows = []
        for n, stop in enumerate(plan.stops, start=1):
            s = stop.station
            rows.append({
                "#":           n,
                "At km":       f"{s['route_km']:.0f}",
                "Station":     s["name"],
                "Country":     s["country"],
                "Price (EUR/L)": s["price"],
                "Refuel (L)":  stop.liters,
                "Cost (EUR)":  stop.cost,
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
        st.info(
            f"No refuelling needed - your starting fuel covers the whole trip "
            f"(arriving with **{plan.fuel_remaining_l:.1f} L** to spare)."
        )


# ===========================================================================
# 5. ENTRY POINT
# ===========================================================================

def main() -> None:
    """
    App entry point — configures the page and routes to the correct mode.
    Called automatically by Streamlit when the script runs.
    """
    st.set_page_config(
        page_title="FuelFinder - DACH fuel prices",
        page_icon="",
        layout="wide",  # use the full browser width
    )

    # Inject the custom CSS once per page load
    st.markdown(_CSS, unsafe_allow_html=True)

    # Sidebar — navigation and data source credits
    with st.sidebar:
        st.markdown(
            '<p class="ff-brand-name">FuelFinder</p>'
            '<p class="ff-brand-tag">Live prices across DE &middot; AT &middot; CH</p>',
            unsafe_allow_html=True,
        )
        st.divider()
        mode = st.radio(
            "Mode",
            ["Find nearby", "Trip planner"],
            label_visibility="collapsed",
        )
        st.divider()
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

    # Route to the correct page based on sidebar selection
    if mode == "Find nearby":
        render_static_mode()
    else:
        render_dynamic_mode()


# Standard Python idiom: only run main() when this file is executed directly,
# not when it is imported as a module.
if __name__ == "__main__":
    main()
