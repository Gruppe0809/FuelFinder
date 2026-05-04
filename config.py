# config.py — shared constants for FuelFinder

# ---- Search defaults (Mode 01) ---------------------------------------------
DEFAULT_RADIUS_KM = 10
MAX_RADIUS_KM = 50
DEFAULT_FUEL_TYPE = "E5"           # one of: E5 | E10 | Diesel
FUEL_TYPES = ["E5", "E10", "Diesel"]
TOP_N_RESULTS = 15

# ---- Trip planner (Mode 02) ------------------------------------------------
OSRM_URL = "https://router.project-osrm.org/route/v1/driving"

# How densely we sample the route to look for nearby stations. Smaller =
# more thorough but more API calls (each adds ~1–2 s). 20 km is a good
# trade-off — at typical highway speeds it's a sample every ~12 minutes
# of driving, well within Tankerkönig's 25 km radius cap.
ROUTE_SAMPLE_INTERVAL_KM = 20

# How far off the route line a station can be while still counting as
# "on the way". Most German Autobahn stations are within 1–3 km of the
# centreline; 5 km also catches stations on parallel B-roads.
ROUTE_CORRIDOR_KM = 5
