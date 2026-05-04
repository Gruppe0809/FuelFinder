import os
import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("TANKERKOENIG_API")
BASE_URL = "https://creativecommons.tankerkoenig.de/json"

# ---------------------------------------------------------------------------
# Public API methods
# ---------------------------------------------------------------------------

def _to_station_dict(raw: dict) -> dict:
    """
    Converts a raw API station object into the shared station format
    used across the whole project.
    """
    def safe_price(value):
        """Returns float price or None if missing/false."""
        if value is None or value is False:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    return {
        "id":           raw.get("id"), # unique station ID
        "name":         raw.get("name"), # station name
        "brand":        raw.get("brand"), # brand (e.g. "SHELL")
        "street":       raw.get("street"), # street name
        "house_number": raw.get("houseNumber"), # house number
        "post_code":    raw.get("postCode"), # postal code
        "place":        raw.get("place"), # city/place
        "lat":          raw.get("lat"), # latitude
        "lng":          raw.get("lng"), # longitude
        "dist":         raw.get("dist"), # distance from search point in km (None if not from radius search)
        "is_open":      raw.get("isOpen", False), # whether station is currently open
        "e5":           safe_price(raw.get("e5")), # Super E5 price in €
        "e10":          safe_price(raw.get("e10")), # E10 price in €
        "diesel":       safe_price(raw.get("diesel")), # Diesel price in €
    }

def get_stations_by_radius(lat: float, lng: float, radius: float, fuel_type: str = "all") -> pd.DataFrame:
    """
    Fetches stations and prices within a given radius of a location.
 
    Args:
        lat:        Latitude of the search location
        lng:        Longitude of the search location
        radius:     Search radius in km (max 25)
        fuel_type:  'e5', 'e10', 'diesel', or 'all' (default: 'all')
    """
    if not API_KEY:
        raise EnvironmentError("TANKERKOENIG_API key not found. Check your .env file.")
 
    params = {
        "lat":    lat,
        "lng":    lng,
        "rad":    radius,
        "type":   fuel_type,
        "sort":   "dist",
        "apikey": API_KEY,
    }
 
    try:
        response = requests.get(f"{BASE_URL}/list.php", params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        print(f"[Tankerkönig] Network error: {e}")
        return pd.DataFrame()
 
    if not data.get("ok"):
        print(f"[Tankerkönig] API error: {data.get('message', 'Unknown error')}")
        return pd.DataFrame()
    
    # Get list of stations from API response, if it doesn't exist return empty list
    stations_raw = data.get("stations", [])

    stations = []
    for s in stations_raw:
        station = _to_station_dict(s)
        stations.append(station)

    return pd.DataFrame(stations)

def get_station_details(station_id: str) -> dict | None:
    """Fetches full details for a single station by ID (opening times, overrides, and current prices)."""
    if not API_KEY:
        raise EnvironmentError("TANKERKOENIG_API key not found.")

    params = {
        "id":     station_id,
        "apikey": API_KEY,
    }

    try:
        response = requests.get(f"{BASE_URL}/detail.php", params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        print(f"[Tankerkönig] Network error: {e}")
        return None

    if not data.get("ok"):
        print(f"[Tankerkönig] API error: {data.get('message', 'Unknown error')}")
        return None

    return data.get("station")

    # Output

    #     data = {
    #     "ok": True,
    #     "station": {
    #         "name": "Shell",
    #         "price": 1.82
    #     }
    # }

    # data.get("station")

# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def get_cheapest_station(df: pd.DataFrame, fuel_type: str = "diesel") -> pd.Series | None:
    """Returns the cheapest station for a given fuel type."""
    available = df[df[fuel_type].notna()]
    if available.empty:
        print(f"No stations with {fuel_type} available.")
        return None
    return available.loc[available[fuel_type].idxmin()]

def get_n_cheapest_stations(df: pd.DataFrame, fuel_type: str = "diesel", n: int = 5) -> pd.DataFrame:
    """Return n cheapest stations from dataframe"""
    if df.empty:
        return df
    
    available = df[df[fuel_type].notna()]
    result = available.nsmallest(n, fuel_type)
    return result.reset_index(drop=True)

def sort_stations_by_distance(df: pd.DataFrame) -> pd.DataFrame:
    """Returns the DataFrame sorted by distance from the search point, closest first."""
    sorted_df = df.sort_values("dist")
    return sorted_df.reset_index(drop=True)

def filter_open_stations(df: pd.DataFrame) -> pd.DataFrame:
    """Returns only the stations that are currently open."""
    open_stations = df[df["is_open"] == True]
    return open_stations.reset_index(drop=True)
