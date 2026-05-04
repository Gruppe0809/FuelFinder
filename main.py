"""
FuelFinder v2 — Streamlit web app for live fuel-price comparison and trip planning.

Single-file design (matches the original repo layout). Code is organised into
clear sections:

    1. Setup & constants
    2. Data layer       — geocoding, distance, country-specific fetchers
    3. Trip planner     — OSRM routing, corridor search, cost optimisation
    4. UI               — Streamlit pages

Run locally:
    pip install -r requirements.txt
    cp .env.example .env       # add your TANKERKOENIG_API_KEY
    streamlit run main.py      # → http://localhost:8501

Project: HSG "Programming – Introduction Level", Group 4495.
"""

# ===========================================================================
# 1. SETUP & CONSTANTS
# ===========================================================================
import math
import os
from dataclasses import dataclass, field
from typing import Optional

import folium
import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv
from geopy.geocoders import Nominatim
from streamlit_folium import st_folium

from config import (
    DEFAULT_FUEL_TYPE,
    DEFAULT_RADIUS_KM,
    FUEL_TYPES,
    MAX_RADIUS_KM,
    OSRM_URL,
    ROUTE_CORRIDOR_KM,
    ROUTE_SAMPLE_INTERVAL_KM,
    TOP_N_RESULTS,
)

# Load .env for local development. On Streamlit Cloud, secrets are read
# from `st.secrets` instead — see `get_api_key()` below.
load_dotenv()

# API endpoints
TANKERKOENIG_URL = "https://creativecommons.tankerkoenig.de/json/list.php"
ECONTROL_URL = "https://api.e-control.at/sprit/1.0/search/gas-stations/by-address"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Nominatim / Overpass / OSRM all expect a descriptive User-Agent.
USER_AGENT = "FuelFinder/2.0 (HSG Group 4495 – student project)"

# Tankerkönig caps search radius at 25 km.
TANKERKOENIG_MAX_RADIUS = 25


def get_api_key() -> str:
    """Read TANKERKOENIG_API_KEY from .env (local dev) or st.secrets (cloud)."""
    key = os.getenv("TANKERKOENIG_API_KEY", "").strip()
    if key:
        return key
    try:
        return st.secrets.get("TANKERKOENIG_API_KEY", "").strip()
    except Exception:
        return ""


# ===========================================================================
# 2. DATA LAYER
# ===========================================================================

@dataclass
class GeoResult:
    """Result of a geocoding lookup."""
    lat: float
    lon: float
    address: str


@dataclass
class FetchResult:
    """Combined fetcher output: stations + non-fatal warnings."""
    stations: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def extend(self, other: "FetchResult") -> None:
        self.stations.extend(other.stations)
        self.warnings.extend(other.warnings)


# ----- Helpers --------------------------------------------------------------
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two coordinates, in kilometres."""
    R = 6371.0  # mean Earth radius in km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


@st.cache_data(ttl=86400, show_spinner=False)
def geocode(query: str) -> Optional[GeoResult]:
    """Convert a free-text location to coordinates. Returns None if not found."""
    geocoder = Nominatim(user_agent=USER_AGENT, timeout=10)
    location = geocoder.geocode(query)
    if location is None:
        return None
    return GeoResult(lat=location.latitude, lon=location.longitude, address=location.address)


# ----- Germany — Tankerkönig -----------------------------------------------
@st.cache_data(ttl=300, show_spinner=False)
def fetch_germany(lat: float, lon: float, radius_km: float, fuel_type: str) -> FetchResult:
    api_key = get_api_key()
    result = FetchResult()

    if not api_key:
        result.warnings.append("Germany skipped: TANKERKOENIG_API_KEY not set.")
        return result

    capped = min(radius_km, TANKERKOENIG_MAX_RADIUS)
    if radius_km > TANKERKOENIG_MAX_RADIUS:
        result.warnings.append(
            f"Germany radius capped at {TANKERKOENIG_MAX_RADIUS} km (Tankerkönig API limit)."
        )

    params = {
        "lat": lat, "lng": lon, "rad": capped,
        "sort": "price",
        "type": {"E5": "e5", "E10": "e10", "Diesel": "diesel"}[fuel_type],
        "apikey": api_key,
    }
    try:
        resp = requests.get(TANKERKOENIG_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        result.warnings.append(f"Germany unavailable: {e}")
        return result

    if not data.get("ok"):
        result.warnings.append(f"Germany unavailable: {data.get('message', 'unknown error')}")
        return result

    for s in data.get("stations", []):
        if not s.get("isOpen"):
            continue
        price = s.get("price")
        if not price:
            continue
        street = (s.get("street") or "").strip()
        house = (s.get("houseNumber") or "").strip()
        post = (s.get("postCode") or "").strip()
        place = (s.get("place") or "").strip()
        result.stations.append({
            "name": (s.get("name") or "Unknown").strip(),
            "brand": (s.get("brand") or "").strip(),
            "address": f"{street} {house}, {post} {place}".strip(", ").strip(),
            "country": "DE",
            "lat": s.get("lat"),
            "lon": s.get("lng"),
            "price": float(price),
            "fuel_type": fuel_type,
            "distance_km": float(s.get("dist", 0.0)),
            "source": "Tankerkönig",
        })
    return result


# ----- Austria — E-Control / Spritpreisrechner -----------------------------
@st.cache_data(ttl=300, show_spinner=False)
def fetch_austria(lat: float, lon: float, radius_km: float, fuel_type: str) -> FetchResult:
    """API ignores radius and returns ~10 nearest stations — we filter client-side.
    Austria has no E5/E10 split in the database; both map to SUP (Super 95)."""
    result = FetchResult()
    fuel_map = {"E5": "SUP", "E10": "SUP", "Diesel": "DIE"}
    params = {
        "latitude": lat, "longitude": lon,
        "fuelType": fuel_map[fuel_type],
        "includeClosed": "false",
    }
    try:
        resp = requests.get(
            ECONTROL_URL, params=params,
            headers={"User-Agent": USER_AGENT}, timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        result.warnings.append(f"Austria unavailable: {e}")
        return result

    for s in data:
        loc = s.get("location") or {}
        slat, slon = loc.get("latitude"), loc.get("longitude")
        if slat is None or slon is None:
            continue
        d = haversine_km(lat, lon, slat, slon)
        if d > radius_km:
            continue
        prices = s.get("prices") or []
        amount = prices[0].get("amount") if prices else None
        if not amount:
            continue
        addr_parts = [
            (loc.get("address") or "").strip(),
            f"{(loc.get('postalCode') or '').strip()} {(loc.get('city') or '').strip()}".strip(),
        ]
        result.stations.append({
            "name": (s.get("name") or "Unknown").strip(),
            "brand": "",
            "address": ", ".join(p for p in addr_parts if p),
            "country": "AT",
            "lat": slat, "lon": slon,
            "price": float(amount),
            "fuel_type": fuel_type,
            "distance_km": d,
            "source": "Spritpreisrechner.at",
        })
    return result


# ----- Switzerland — OpenStreetMap Overpass --------------------------------
@st.cache_data(ttl=300, show_spinner=False)
def fetch_switzerland(lat: float, lon: float, radius_km: float, fuel_type: str) -> FetchResult:
    """OSM gives station LOCATIONS only — Switzerland has no public price feed.
    Stations without prices appear as grey markers and `—` in the table."""
    result = FetchResult()
    radius_m = int(radius_km * 1000)
    overpass_query = f"""
    [out:json][timeout:25];
    (
      node["amenity"="fuel"](around:{radius_m},{lat},{lon});
      way["amenity"="fuel"](around:{radius_m},{lat},{lon});
    );
    out center tags;
    """
    try:
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
        country_tag = (tags.get("addr:country") or "").upper()
        if country_tag and country_tag != "CH":
            continue
        if el.get("type") == "node":
            slat, slon = el.get("lat"), el.get("lon")
        else:
            c = el.get("center") or {}
            slat, slon = c.get("lat"), c.get("lon")
        if slat is None or slon is None:
            continue
        d = haversine_km(lat, lon, slat, slon)
        if d > radius_km:
            continue

        # OSM rarely tags prices, but we check a couple of common conventions.
        price = None
        for key in (f"charge:{fuel_type.lower()}", f"price:{fuel_type.lower()}"):
            if key in tags:
                try:
                    price = float(tags[key])
                    break
                except ValueError:
                    pass

        addr_parts = [
            f"{(tags.get('addr:street') or '').strip()} {(tags.get('addr:housenumber') or '').strip()}".strip(),
            f"{(tags.get('addr:postcode') or '').strip()} {(tags.get('addr:city') or '').strip()}".strip(),
        ]
        result.stations.append({
            "name": tags.get("name") or tags.get("brand") or "Tankstelle",
            "brand": tags.get("brand") or "",
            "address": ", ".join(p for p in addr_parts if p),
            "country": "CH",
            "lat": slat, "lon": slon,
            "price": price,
            "fuel_type": fuel_type,
            "distance_km": d,
            "source": "OpenStreetMap",
        })
    return result


# ----- Aggregator -----------------------------------------------------------
def gather_all(lat: float, lon: float, radius_km: float, fuel_type: str) -> FetchResult:
    """Run all three fetchers and merge into one sorted result."""
    combined = FetchResult()
    combined.extend(fetch_germany(lat, lon, radius_km, fuel_type))
    combined.extend(fetch_austria(lat, lon, radius_km, fuel_type))
    combined.extend(fetch_switzerland(lat, lon, radius_km, fuel_type))

    # Sort: priced stations first (cheapest first), then no-price by distance.
    combined.stations.sort(
        key=lambda s: (
            s["price"] is None,                     # False sorts before True
            s["price"] if s["price"] is not None else float("inf"),
            s["distance_km"],
        )
    )
    return combined


# ===========================================================================
# 3. TRIP PLANNER — routing, corridor search, optimisation
# ===========================================================================

@dataclass
class Route:
    """Driving route from OSRM. Points are (lat, lon) in order."""
    points: list[tuple[float, float]]
    total_km: float


@dataclass
class RefuelStop:
    """One refuel decision: where, how much, what it costs."""
    station: dict       # priced station dict from gather_all
    liters: float       # litres to refuel
    cost: float         # liters × price


@dataclass
class TripPlan:
    """Full trip outcome from the optimiser."""
    stops: list[RefuelStop]
    total_cost: float
    total_distance_km: float
    fuel_remaining_l: float
    feasible: bool                       # False if trip can't be completed
    message: str = ""                    # explanation when infeasible


# ----- OSRM routing ---------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def get_route(start_lat: float, start_lon: float,
              end_lat: float, end_lon: float) -> Optional[Route]:
    """Fetch a driving route from the OSRM public demo server.

    Note: OSRM uses {longitude},{latitude} order in the URL — opposite of
    most other APIs. Returns None if the route can't be computed.
    """
    coords = f"{start_lon},{start_lat};{end_lon},{end_lat}"
    url = f"{OSRM_URL}/{coords}"
    params = {"overview": "full", "geometries": "geojson"}

    try:
        resp = requests.get(url, params=params, timeout=20,
                            headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException:
        return None

    if data.get("code") != "Ok" or not data.get("routes"):
        return None

    route = data["routes"][0]
    # GeoJSON gives [lon, lat] pairs — swap for our (lat, lon) convention.
    points = [(c[1], c[0]) for c in route["geometry"]["coordinates"]]
    return Route(points=points, total_km=route["distance"] / 1000.0)


def _cumulative_km(points: list[tuple[float, float]]) -> list[float]:
    """For each route point, the kilometres travelled from the start."""
    cum = [0.0]
    for i in range(1, len(points)):
        cum.append(cum[-1] + haversine_km(*points[i - 1], *points[i]))
    return cum


def _project_onto_route(
    station_lat: float, station_lon: float,
    points: list[tuple[float, float]], cumulative: list[float],
) -> tuple[float, float]:
    """Find the closest point on the route to a station.

    Returns (route_km, perpendicular_km) — distance from start along the route,
    and how far off the route the station sits.
    """
    best_dist = float("inf")
    best_km = 0.0
    for i, (plat, plon) in enumerate(points):
        d = haversine_km(station_lat, station_lon, plat, plon)
        if d < best_dist:
            best_dist = d
            best_km = cumulative[i]
    return best_km, best_dist


# ----- Corridor station search ---------------------------------------------
def stations_along_route(
    route: Route,
    fuel_type: str,
    sample_interval_km: float = ROUTE_SAMPLE_INTERVAL_KM,
    corridor_km: float = ROUTE_CORRIDOR_KM,
    progress_callback=None,
) -> tuple[list[dict], list[str]]:
    """Find priced stations along the route corridor.

    Strategy:
      1. Pick sample waypoints every `sample_interval_km` along the route.
      2. Run the existing fetchers at each waypoint with a small radius.
      3. Keep only stations within `corridor_km` of the route geometry.
      4. Deduplicate by rounded (lat, lon) — same physical station found at
         neighbouring waypoints would otherwise appear twice.
      5. Sort by route_km so the optimiser sees them in driving order.

    Returns (stations, warnings). Each station dict gets two extra fields:
      route_km   = distance from route start to the closest route point
      offroad_km = perpendicular detour to reach the station
    """
    cumulative = _cumulative_km(route.points)

    # Pick waypoint indices roughly every `sample_interval_km`.
    sample_indices: list[int] = [0]
    next_target = sample_interval_km
    for i, c in enumerate(cumulative):
        if c >= next_target:
            sample_indices.append(i)
            next_target += sample_interval_km
    if sample_indices[-1] != len(route.points) - 1:
        sample_indices.append(len(route.points) - 1)

    # Search radius per waypoint. The corridor is the geometric goal; the API
    # radius needs to be a bit larger to actually return stations near the line.
    api_radius_km = max(corridor_km * 2, 8)

    seen: set[tuple[float, float]] = set()
    found: list[dict] = []
    warnings: list[str] = []

    for n, idx in enumerate(sample_indices):
        plat, plon = route.points[idx]
        if progress_callback:
            progress_callback(n, len(sample_indices))
        result = gather_all(plat, plon, api_radius_km, fuel_type)

        # Deduplicate warnings — same fetcher at 30 waypoints would otherwise
        # produce 30 copies of the same warning.
        for w in result.warnings:
            if w not in warnings:
                warnings.append(w)

        for s in result.stations:
            if s["price"] is None:               # corridor optimisation needs prices
                continue
            key = (round(s["lat"], 4), round(s["lon"], 4))
            if key in seen:
                continue
            seen.add(key)

            route_km, offroad_km = _project_onto_route(
                s["lat"], s["lon"], route.points, cumulative
            )
            if offroad_km > corridor_km:
                continue

            enriched = dict(s)
            enriched["route_km"] = route_km
            enriched["offroad_km"] = offroad_km
            found.append(enriched)

    found.sort(key=lambda s: s["route_km"])
    return found, warnings


# ----- Cost-optimal refuel planning ----------------------------------------
def plan_trip(
    stations: list[dict],
    total_distance_km: float,
    tank_capacity_l: float,
    current_fuel_l: float,
    consumption_l_per_100km: float,
) -> TripPlan:
    """Greedy gas-station algorithm (Khuller-Mitchell-Vazirani 2007).

    The rule, applied at every station we stop at:
      - Look ahead within the remaining tank's reach.
      - If a CHEAPER station is reachable: buy just enough fuel to reach it.
      - Otherwise: fill the tank — cheap fuel now beats expensive fuel later.

    The destination is treated as a virtual "free" station so the algorithm
    naturally minimises fuel-on-arrival without any special-casing.

    Returns a TripPlan with feasible=False if the trip can't be completed
    (e.g. a station gap larger than the tank's range).
    """
    consumption_per_km = consumption_l_per_100km / 100.0
    fuel_range_km = tank_capacity_l / consumption_per_km   # full tank → km

    # Sanity check on inputs
    if tank_capacity_l <= 0 or consumption_l_per_100km <= 0:
        return TripPlan([], 0.0, total_distance_km, current_fuel_l, False,
                        "Tank capacity and consumption must be positive.")
    if current_fuel_l > tank_capacity_l:
        return TripPlan([], 0.0, total_distance_km, current_fuel_l, False,
                        "Current fuel exceeds tank capacity.")

    # Build the list of decision points: each priced station + the destination.
    DEST = {
        "name": "Destination", "lat": None, "lon": None,
        "price": 0.0, "route_km": total_distance_km,
        "country": "—", "brand": "",
    }
    points = [s for s in stations if 0 < s["route_km"] < total_distance_km] + [DEST]

    # Walk the route, decision by decision.
    pos_km = 0.0
    fuel_l = current_fuel_l
    stops: list[RefuelStop] = []

    while pos_km < total_distance_km - 1e-6:
        # Are we standing at a station? (pos_km matches a station's route_km)
        current = next((p for p in points if abs(p["route_km"] - pos_km) < 1e-3
                                          and p is not DEST), None)

        # Effective reach depends on whether we can refuel here:
        # if we're at a station we can fill up; otherwise we must use what we have.
        max_fuel_here = tank_capacity_l if current is not None else fuel_l
        reach_km = pos_km + max_fuel_here / consumption_per_km

        # Stations / destination strictly ahead, reachable from here.
        candidates = [p for p in points if pos_km < p["route_km"] <= reach_km + 1e-6]

        if not candidates:
            # Even filling up here (or the tank we have) can't reach anything ahead.
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
            # We're at trip start (pos_km == 0) and not at a station — can't refuel here.
            # Drive to the cheapest reachable station/destination.
            target = min(candidates, key=lambda p: p["price"])
            distance = target["route_km"] - pos_km
            fuel_l -= distance * consumption_per_km
            pos_km = target["route_km"]
            continue

        # We're standing at `current`. Apply the lookahead rule.
        cheaper_ahead = [p for p in candidates if p["price"] < current["price"]]

        if cheaper_ahead:
            # Buy just enough to reach the nearest cheaper station.
            next_cheaper = min(cheaper_ahead, key=lambda p: p["route_km"])
            distance = next_cheaper["route_km"] - pos_km
            fuel_needed = distance * consumption_per_km
            buy = max(0.0, fuel_needed - fuel_l)
            target = next_cheaper
        else:
            # Nothing cheaper within reach — fill up and drive to the FARTHEST
            # reachable point (driving past stations we don't stop at is fine).
            buy = tank_capacity_l - fuel_l
            target = max(candidates, key=lambda p: p["route_km"])
            distance = target["route_km"] - pos_km

        if buy > 0:
            stops.append(RefuelStop(
                station=current, liters=buy, cost=buy * current["price"],
            ))
            fuel_l += buy

        # Drive to the chosen target.
        fuel_l -= distance * consumption_per_km
        pos_km = target["route_km"]

        # Numerical hygiene
        if -1e-6 < fuel_l < 0:
            fuel_l = 0.0
        if fuel_l < 0:
            return TripPlan(stops, sum(s.cost for s in stops), total_distance_km,
                            fuel_l, False, "Ran out of fuel — refuel logic error.")

    return TripPlan(
        stops=stops,
        total_cost=sum(s.cost for s in stops),
        total_distance_km=total_distance_km,
        fuel_remaining_l=fuel_l,
        feasible=True,
    )


# ===========================================================================
# 4. UI
# ===========================================================================

def build_map(stations: list[dict], origin_lat: float, origin_lon: float, fuel_type: str) -> folium.Map:
    """Build a folium map with origin + colour-coded station markers (Mode 01)."""
    fmap = folium.Map(location=[origin_lat, origin_lon], zoom_start=11)

    folium.Marker(
        [origin_lat, origin_lon],
        popup="Your search location",
        icon=folium.Icon(color="blue", icon="home", prefix="fa"),
    ).add_to(fmap)

    if not stations:
        return fmap

    # Price terciles for colour-coding (priced stations only).
    priced = sorted(s["price"] for s in stations if s["price"] is not None)
    if len(priced) >= 3:
        q_low = priced[len(priced) // 3]
        q_high = priced[2 * len(priced) // 3]
    else:
        q_low = q_high = float("inf")

    for s in stations:
        if s["price"] is None:
            color, price_str = "gray", "no price data"
        elif s["price"] <= q_low:
            color, price_str = "green", f"{s['price']:.3f}"
        elif s["price"] <= q_high:
            color, price_str = "orange", f"{s['price']:.3f}"
        else:
            color, price_str = "red", f"{s['price']:.3f}"

        popup_html = (
            f"<b>{s['name']}</b><br>"
            f"Brand: {s['brand'] or '—'}<br>"
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
    """Map for Mode 02: route polyline + chosen refuel stops + other corridor stations."""
    if not route.points:
        return folium.Map()

    # Centre on route midpoint
    mid = route.points[len(route.points) // 2]
    fmap = folium.Map(location=mid, zoom_start=7)

    # Route polyline
    folium.PolyLine(route.points, color="#185FA5", weight=5, opacity=0.7).add_to(fmap)

    # Start + end markers
    folium.Marker(route.points[0], popup="Start",
                  icon=folium.Icon(color="green", icon="play", prefix="fa")).add_to(fmap)
    folium.Marker(route.points[-1], popup="Destination",
                  icon=folium.Icon(color="red", icon="flag-checkered", prefix="fa")).add_to(fmap)

    # Coordinates of chosen stops, so we can dim the others.
    chosen_keys = {(s.station["lat"], s.station["lon"]) for s in plan.stops
                   if s.station["lat"] is not None}

    # Other priced corridor stations as small grey dots.
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

    # Chosen refuel stops as prominent green markers, numbered.
    for n, stop in enumerate(plan.stops, start=1):
        s = stop.station
        if s["lat"] is None:                # destination sentinel — never picked
            continue
        popup_html = (
            f"<b>Stop {n}: {s['name']}</b><br>"
            f"{fuel_type}: <b>{s['price']:.3f}</b> / L<br>"
            f"Refuel: <b>{stop.liters:.1f} L</b> "
            f"(€{stop.cost:.2f})<br>"
            f"At km {s['route_km']:.0f} of route<br>"
            f"{s['country']} ({s['source']})"
        )
        folium.Marker(
            location=[s["lat"], s["lon"]],
            popup=folium.Popup(popup_html, max_width=280),
            icon=folium.Icon(color="green", icon="gas-pump", prefix="fa"),
            tooltip=f"Stop {n} — {stop.liters:.1f} L",
        ).add_to(fmap)

    return fmap


def render_static_mode() -> None:
    """Mode 01 — find the cheapest fuel near a location."""
    st.title("⛽ Find nearby fuel")
    st.caption("Live prices for E5, E10 and Diesel across Switzerland, Germany, and Austria.")

    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        location = st.text_input("Location", placeholder="e.g. Münster, 9000, or Wien")
    with col2:
        fuel_type = st.selectbox("Fuel type", FUEL_TYPES,
                                 index=FUEL_TYPES.index(DEFAULT_FUEL_TYPE))
    with col3:
        radius = st.slider("Radius (km)", 1, MAX_RADIUS_KM, DEFAULT_RADIUS_KM)

    search_clicked = st.button("Search", type="primary", key="static_search")

    if search_clicked:
        if not location.strip():
            st.error("Please enter a location.")
            st.session_state.pop("search_result", None)
            return
        with st.spinner(f"Geocoding '{location}'…"):
            geo = geocode(location.strip())
        if geo is None:
            st.error(f"Could not find '{location}'.")
            st.session_state.pop("search_result", None)
            return
        with st.spinner("Fetching live prices from DE / AT / CH…"):
            result = gather_all(geo.lat, geo.lon, radius, fuel_type)
        st.session_state.search_result = {
            "geo": geo,
            "stations": result.stations,
            "warnings": result.warnings,
            "fuel_type": fuel_type,
        }

    sr = st.session_state.get("search_result")
    if not sr:
        st.info("Enter a location above and click **Search** to find live fuel prices.")
        return

    geo = sr["geo"]; stations = sr["stations"]
    warnings = sr["warnings"]; fuel_type_used = sr["fuel_type"]

    st.success(f"📍 {geo.address}")
    if warnings:
        with st.expander(f"⚠ {len(warnings)} warning(s)"):
            for w in warnings:
                st.write(f"- {w}")

    top = stations[:TOP_N_RESULTS]
    if not top:
        st.warning("No stations found in this radius. Try widening the search.")
        return

    st.markdown(
        f"**{len(stations)} stations** found · showing top **{len(top)}** for **{fuel_type_used}**."
    )

    st.subheader("Map")
    fmap = build_map(top, geo.lat, geo.lon, fuel_type_used)
    st_folium(fmap, height=420, use_container_width=True, returned_objects=[])
    st.caption("🟢 cheapest third · 🟠 middle third · 🔴 most expensive · ⚪ no price data (CH)")

    st.subheader("Stations")
    df = pd.DataFrame(top)
    df.index = df.index + 1
    df = df.rename(columns={
        "country": "Country", "name": "Station", "brand": "Brand",
        "address": "Address", "price": "Price", "distance_km": "Dist (km)",
        "source": "Source",
    })[["Country", "Station", "Brand", "Address", "Price", "Dist (km)", "Source"]]
    st.dataframe(
        df, use_container_width=True,
        column_config={
            "Price":     st.column_config.NumberColumn(format="%.3f"),
            "Dist (km)": st.column_config.NumberColumn(format="%.1f"),
        },
    )


def render_dynamic_mode() -> None:
    """Mode 02 — plan a trip with cost-optimal refuel stops."""
    st.title("🛣 Trip planner")
    st.caption("Plan a route and let us pick the cheapest places to stop.")

    # ---- Inputs --------------------------------------------------------
    col_a, col_b = st.columns(2)
    with col_a:
        start_q = st.text_input("Start", placeholder="e.g. Berlin", key="trip_start")
    with col_b:
        end_q = st.text_input("Destination", placeholder="e.g. Munich", key="trip_end")

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
        if current_fuel > tank_capacity:
            st.error("Current fuel can't exceed tank capacity.")
            return
        if not start_q.strip() or not end_q.strip():
            st.error("Please enter both a start and a destination.")
            return

        with st.spinner("Geocoding…"):
            start = geocode(start_q.strip())
            end = geocode(end_q.strip())
        if start is None:
            st.error(f"Could not find start '{start_q}'.")
            return
        if end is None:
            st.error(f"Could not find destination '{end_q}'.")
            return

        with st.spinner("Computing driving route…"):
            route = get_route(start.lat, start.lon, end.lat, end.lon)
        if route is None:
            st.error("OSRM couldn't compute a route between those points.")
            return

        # Find stations along the corridor (slow step — many fetches)
        progress_bar = st.progress(0.0, text="Searching for stations along the route…")
        def _progress(n: int, total: int) -> None:
            progress_bar.progress((n + 1) / max(total, 1),
                                  text=f"Searching waypoint {n + 1} of {total}…")
        corridor_stations, corridor_warnings = stations_along_route(
            route, fuel_type, progress_callback=_progress,
        )
        progress_bar.empty()

        with st.spinner("Optimising refuel stops…"):
            plan = plan_trip(
                stations=corridor_stations,
                total_distance_km=route.total_km,
                tank_capacity_l=tank_capacity,
                current_fuel_l=current_fuel,
                consumption_l_per_100km=consumption,
            )

        st.session_state.trip_result = {
            "start": start, "end": end, "route": route,
            "corridor_stations": corridor_stations,
            "corridor_warnings": corridor_warnings,
            "plan": plan, "fuel_type": fuel_type,
            "consumption": consumption,
            "current_fuel": current_fuel,
        }

    tr = st.session_state.get("trip_result")
    if not tr:
        st.info(
            "Fill in the inputs above and click **Plan trip**. "
            "We'll fetch a driving route, find every priced station along the way, "
            "and pick the cheapest places to stop using the classical *gas station "
            "problem* algorithm."
        )
        return

    plan = tr["plan"]; route = tr["route"]
    fuel_type_used = tr["fuel_type"]
    corridor_stations = tr["corridor_stations"]

    st.success(f"📍 {tr['start'].address}  →  {tr['end'].address}")
    if tr["corridor_warnings"]:
        with st.expander(f"⚠ {len(tr['corridor_warnings'])} warning(s)"):
            for w in tr["corridor_warnings"]:
                st.write(f"- {w}")

    if not plan.feasible:
        st.error(f"Trip not feasible: {plan.message}")
        return

    # ---- Headline metrics + naive baseline comparison -----------------
    fuel_needed_total = max(0.0, route.total_km * tr["consumption"] / 100.0 - tr["current_fuel"])
    if corridor_stations:
        avg_price = sum(s["price"] for s in corridor_stations) / len(corridor_stations)
        baseline_cost = fuel_needed_total * avg_price
    else:
        avg_price = 0.0
        baseline_cost = 0.0

    metrics = st.columns(4)
    metrics[0].metric("Distance", f"{route.total_km:,.0f} km")
    metrics[1].metric("Total fuel cost", f"€{plan.total_cost:,.2f}")
    metrics[2].metric("Refuel stops", f"{len(plan.stops)}")
    if avg_price > 0:
        savings = baseline_cost - plan.total_cost
        metrics[3].metric(
            "vs. corridor average",
            f"€{plan.total_cost:,.2f}",
            delta=f"−€{savings:,.2f}" if savings >= 0 else f"+€{-savings:,.2f}",
            delta_color="inverse",
        )
    else:
        metrics[3].metric("vs. average", "—")

    # ---- Map -----------------------------------------------------------
    st.subheader("Route and refuel stops")
    fmap = build_trip_map(route, corridor_stations, plan, fuel_type_used)
    st_folium(fmap, height=460, use_container_width=True, returned_objects=[])
    st.caption(
        f"🟢 chosen refuel stop · ⚪ other priced station in corridor · "
        f"{len(corridor_stations)} priced stations along the route"
    )

    # ---- Stops table --------------------------------------------------
    if plan.stops:
        st.subheader("Refuel plan")
        rows = []
        for n, stop in enumerate(plan.stops, start=1):
            s = stop.station
            rows.append({
                "#": n,
                "At km": f"{s['route_km']:.0f}",
                "Station": s["name"],
                "Country": s["country"],
                "Price (€/L)": s["price"],
                "Refuel (L)": stop.liters,
                "Cost (€)": stop.cost,
            })
        df = pd.DataFrame(rows)
        st.dataframe(
            df, hide_index=True, use_container_width=True,
            column_config={
                "Price (€/L)": st.column_config.NumberColumn(format="%.3f"),
                "Refuel (L)":  st.column_config.NumberColumn(format="%.1f"),
                "Cost (€)":    st.column_config.NumberColumn(format="%.2f"),
            },
        )
        st.caption(
            f"Arriving with **{plan.fuel_remaining_l:.1f} L** in the tank. "
            "The optimiser refuels just enough at each stop to reach the next "
            "cheaper option, and fills up only when nothing cheaper is in range."
        )
    else:
        st.info(
            f"No refuelling needed — your starting fuel is enough for the whole trip "
            f"(arriving with **{plan.fuel_remaining_l:.1f} L** to spare)."
        )


# ---------------------------------------------------------------------------
# Main entry-point
# ---------------------------------------------------------------------------
def main() -> None:
    st.set_page_config(
        page_title="FuelFinder — DACH fuel prices",
        page_icon="⛽",
        layout="wide",
    )

    with st.sidebar:
        st.title("⛽ FuelFinder")
        st.caption("Live fuel prices · CH · DE · AT")
        st.divider()
        mode = st.radio(
            "Mode",
            ["Find nearby", "Trip planner"],
            label_visibility="collapsed",
        )
        st.divider()
        st.caption(
            "Data: [Tankerkönig](https://creativecommons.tankerkoenig.de/), "
            "[Spritpreisrechner.at](https://www.spritpreisrechner.at/), "
            "[OpenStreetMap](https://www.openstreetmap.org/). "
            "Routing: [OSRM](https://project-osrm.org/)."
        )
        st.caption("HSG · Group 4495 · *Programming – Introduction Level*")

    if mode == "Find nearby":
        render_static_mode()
    else:
        render_dynamic_mode()


if __name__ == "__main__":
    main()

