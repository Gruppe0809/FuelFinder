# Programming - Introduction Level
Group 4495

## FuelFinder — Live Fuel Prices for DE / AT / CH

FuelFinder is a Streamlit web app for comparing live fuel prices across Germany, Austria, and Switzerland. It has two modes: a **nearby station finder** that shows the cheapest stations around any location on a colour-coded map, and a **trip planner** that calculates the cheapest places to refuel along a driving route.

This application was developed as part of the group project for the course "Programming - Introduction Level" at the University of St. Gallen.

---

## What the App Does

### Mode 1 — Find Nearby Fuel

The user types a city, postcode, or address into the search box. The app converts that text into GPS coordinates (geocoding), then calls three different APIs simultaneously to collect all open fuel stations within the chosen radius:

- **Germany**: Tankerkönig API — returns live prices updated every few minutes
- **Austria**: Spritpreisrechner.at (E-Control) — returns prices where available (Austrian law limits price changes to three fixed times per day: 12:00, 14:00, and 16:00)
- **Switzerland**: OpenStreetMap Overpass API — returns station locations only (Switzerland has no public fuel price database)

All results are merged into a single sorted list. The map shows each station as a colour-coded dot:
- **Green** = cheapest third of stations found
- **Orange** = middle third
- **Red** = most expensive third
- **Grey** = no price data available

### Mode 2 — Trip Planner

The user enters a start location, a destination, and their vehicle's fuel parameters (tank size, current fuel level, fuel consumption in L/100 km). The app then runs a multi-step process:

1. **Route calculation** — fetches a real driving route from Mapbox Directions (or OSRM as a fallback). The route is a sequence of GPS waypoints covering the full road path.

2. **Station search along the route** — the route is divided into evenly-spaced sample points (every ~20 km). At each sample point, all three country APIs are called in parallel to find nearby stations. Any station further than 5 km from the route line is discarded. Duplicates (the same station appearing near multiple sample points) are removed. The result is a list of all priced stations along the corridor, sorted in driving order.

3. **Cost optimisation** — the app runs the refuel planning algorithm (see below) to decide exactly where to stop and how many litres to buy at each stop.

4. **Results** — the route map shows the full driving path, green pins for chosen refuel stops, and grey dots for all other stations that were found. A table below lists each stop with the price, litres purchased, and cost.

---

## The Refuel Planning Algorithm

The trip planner uses a classic algorithm known as the **"Gas Station Problem"** (greedy approach). The core insight is:

> If a cheaper station is reachable on your current fuel, there is no point paying more now. Only fill up here if there is nothing cheaper within reach.

### How it works step by step

The algorithm simulates driving the route from start to destination. At each fuel station it encounters, it makes one of two decisions:

**Case 1 — A cheaper station is in range:**
Buy just enough fuel to reach that cheaper station. Don't buy more than needed here since the cheaper fuel is coming up.

**Case 2 — No cheaper station is in range:**
Fill the tank completely. This is the cheapest fuel available for the foreseeable stretch of the route, so it makes sense to stock up.

The destination is added as a virtual station with a price of €0/L. This means the algorithm naturally stops buying fuel once the destination can be reached — there is no point filling up beyond what is needed to arrive.

### Minimum fill-up rule

A practical constraint is added on top of the algorithm: **each stop must purchase at least 10 litres**. Without this limit, the algorithm might suggest stopping for 1–3 litres just to save a few cents, which is not realistic. If the calculated amount to buy is less than 10 L, it is rounded up to 10 L (or however much fits in the tank, whichever is smaller).

### Feasibility check

If any gap between consecutive stations along the route is longer than the car's maximum range on a full tank, the algorithm returns the trip as **infeasible** and tells the user which gap is the problem.

### Example

Imagine a 400 km trip with stations at the following prices and positions:

| Position (km) | Price (€/L) |
|---|---|
| 50 | 1.85 |
| 120 | 1.72 |
| 230 | 1.90 |
| 310 | 1.68 |
| 380 | 1.75 |

With a 50 L tank, 10 L of starting fuel, and 7 L/100 km consumption:

- At km 50 (€1.85): a cheaper station at km 120 is in range → buy just enough to get there
- At km 120 (€1.72): the station at km 310 (€1.68) is cheaper but too far away on current fuel → fill up completely since nothing cheaper is reachable
- At km 230 (€1.90): skip — we have enough fuel to reach km 310
- At km 310 (€1.68): cheapest station on the route → fill up to make it to the destination

---

## Technical Requirements

1. **Clear problem** — finds and compares live fuel prices across three countries and plans cost-optimal refuel stops on a route
2. **Data usage** — live data from three external APIs (Tankerkönig, Spritpreisrechner.at, Overpass) plus Mapbox for geocoding and routing
3. **Data visualisation** — interactive Folium/Mapbox map with colour-coded price tiers and route polyline
4. **User interaction** — address autocomplete search, fuel type selector, radius slider, vehicle parameter inputs
5. **Documentation** — detailed inline comments throughout the source code

---

## Installation

### Prerequisites

- Python 3.10 or higher
- pip

### Steps (to be taken in Terminal)

1. Clone the repository
   ```
   git clone https://github.com/Gruppe0809/FuelFinder
   cd FuelFinder
   ```

2. Create and activate a virtual environment
   ```
   python -m venv venv
   source venv/bin/activate
   ```

3. Install dependencies
   ```
   pip install -r requirements.txt
   ```

> **Note:** API keys are already included in the `.env` file — no additional setup required.

## Running the App

```
streamlit run main.py
```

The app opens automatically at `http://localhost:8501`.

---

## Data Source Limitations

| Source | Country | Prices | Notes |
|---|---|---|---|
| Tankerkönig | DE | Yes | Requires free API key; radius capped at 25 km |
| Spritpreisrechner.at | AT | Yes | No key needed; prices may be empty outside 12:00/14:00/16:00 reporting windows |
| OpenStreetMap Overpass | CH | Locations only | No public Swiss price database |

---

## Project Structure

```
FuelFinder/
├── main.py              # Streamlit app — all logic and UI
├── config.py            # Shared constants (radius defaults, API URLs, corridor settings)
├── requirements.txt     # Python dependencies
├── .env                 # API keys (included in repository)
└── .streamlit/
    └── config.toml      # Dark theme, primary colour, font settings
```

---

## External Dependencies

- **streamlit** — web app framework
- **streamlit-folium** — embeds Folium maps inside Streamlit
- **streamlit-searchbox** — address autocomplete widget
- **folium** — interactive map rendering
- **requests** — HTTP calls to all external APIs
- **pandas** — station data tables
- **geopy** — fallback geocoder (Nominatim) when Mapbox is unavailable
- **python-dotenv** — loads API keys from `.env`
- **certifi** — trusted SSL certificate bundle (fixes macOS SSL errors)

---

## Sources and References

- **Tankerkönig API**: https://creativecommons.tankerkoenig.de/
- **OpenStreetMap Overpass API**: https://overpass-api.de/
- **Spritpreisrechner.at**: https://www.spritpreisrechner.at/
- **Mapbox Geocoding & Directions**: https://docs.mapbox.com/api/
- **Folium Documentation**: https://python-visualization.github.io/folium/
- **Pandas Documentation**: https://pandas.pydata.org/docs/
- **GeoPy Documentation**: https://geopy.readthedocs.io/
- **Nominatim / OpenStreetMap**: https://nominatim.org/
- **ChatGPT, Claude and GitHub Copilot**: Code optimisation, debugging, and README structuring

---

## Potential Future Features

- Integration of additional fuel types (LPG, hydrogen, EV charging)
- Price history tracking across multiple days
- User accounts for saving favourite locations and past trips
- Real-time traffic integration for smarter route suggestions
- Streamlit Cloud deployment with secrets management
