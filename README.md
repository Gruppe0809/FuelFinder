# Programming - Introduction Level
Group 4495

## FuelFinder — Live Fuel Prices for DE / AT / CH

FuelFinder is a Streamlit web app for comparing live fuel prices across Germany, Austria, and Switzerland. It has two modes: a **nearby station finder** that shows the cheapest stations around any location on a colour-coded map, and a **trip planner** that calculates the cheapest places to refuel along a driving route.

This application was developed as part of the group project for the course "Programming - Introduction Level" at the University of St. Gallen.

## Motivation

Recent geopolitcal events, most notably the escalation of conflict in Iran in early 2026, have been disrupting oil prices. Brent crude crossed $100 per barrel for the first time since 2022, and retail fuel costs jumped across Europe between February and May, with diesel rising faster than petrol. Even after the spring ceasefire, analysts expect the supply effects to persist for years.

For drivers in the DACH region, the result is sharply higher pump prices and a much wider gap between cheap and expensive stations: often 15–30 cents per litre between neighbouring forecourts, and considerably more between Autobahn service areas and rural stations, or across the German, Austrian, and Swiss borders. A weekly commuter filling a 50 L tank can easily spend several hundred euros more per year than necessary just by stopping at the wrong station.

FuelFinder addresses this gap: it shows live prices around any location in Germany, Austria, and Switzerland in one view, and computes cost-optimal refuel stops for trips between any two points across the region.
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

Clicking any marker opens a popup with the station name, brand, price, and an **"Open in Google Maps"** link that takes you directly to that location in Google Maps.

### Mode 2 — Trip Planner

The user enters a start location, a destination, and their vehicle's fuel parameters (tank size, current fuel level, fuel consumption in L/100 km). The app then runs a multi-step process:

1. **Route calculation** — fetches a real driving route from Mapbox Directions (or OSRM as a fallback). The route is a sequence of GPS waypoints covering the full road path.

2. **Station search along the route** — the route is divided into evenly-spaced sample points (every ~20 km). At each sample point, all three country APIs are called in parallel to find nearby stations. Any station further than 5 km from the route line is discarded. Duplicates (the same station appearing near multiple sample points) are removed. The result is a list of all stations along the corridor, sorted in driving order.

3. **Handling stations without prices** — Switzerland has no public fuel price database, so Swiss stations are returned without a price. If the route passes through a mix of countries, the app calculates the average price of all stations that do have a price (the "corridor average") and uses that as an estimated price for unpriced stations, so the algorithm can still plan the full route. These estimated prices are clearly marked with "(est.)" on the map.

4. **No-prices fallback (intra-Swiss routes)** — if the route is entirely within Switzerland and no station has a real price, the cost optimiser is skipped. Instead, the app runs a **range-based stop planner**: starting from the current fuel level, it calculates how far the car can travel, finds all stations within that range, picks the **furthest reachable one** (to minimise stops), fills to a full tank there, and repeats until the destination is reachable. The map shows green pins for recommended stops and grey dots for all other stations, with a disclaimer that no cost data is available.

5. **Cost optimisation** — when at least some price data is available, the app runs the greedy refuel planning algorithm (see below) to decide exactly where to stop and how many litres to buy at each stop.

6. **Results** — the route map shows the full driving path, green pins for chosen refuel stops, and grey dots for all other stations that were found. A summary shows total cost, litres to buy, number of stops, and a comparison of the **average price you actually paid per litre** against the corridor average (the mean price of all stations found along the route). A table below lists each stop with the price, litres purchased, and cost.

7. **Google Maps integration** — every station popup on the map includes an "Open in Google Maps" link for that specific location. Below the route map, an **"Open route in Google Maps"** button opens the full planned trip in Google Maps with all recommended refuel stops already added as waypoints, so the user can follow turn-by-turn navigation directly.

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

### Handling stations without a known price

Not all stations return a price — Swiss stations never do, and Austrian stations may be missing a price outside the three official reporting windows (12:00, 14:00, 16:00). The algorithm needs a price for every station to make comparisons, so the app handles this in two steps:

1. **Corridor average fill-in** — if at least one station on the route has a real price, the app calculates the average of those prices and uses it as an estimate for any station that has no price. These estimated prices are labelled "(est.)" on the map so the user knows they are not real values.

2. **No-prices fallback** — if the route is entirely within Switzerland (or another area with no price data), there are no real prices at all, so using a made-up average would be meaningless. In this case the greedy algorithm is skipped entirely and the range-based planner runs instead (see Step 4 above).

### Range-based stop planner (no-price routes)

When no price data is available, a simpler algorithm runs that plans stops purely based on how far the car can travel:

1. Calculate the maximum distance reachable on the current fuel level.
2. Find all fuel stations within that distance along the route.
3. Pick the **furthest reachable station** — stopping as late as possible minimises the total number of stops.
4. Fill up to a full tank at that station.
5. Repeat from the new position until the destination is reachable.

This gives the user a practical plan (where to stop and roughly how much to fill) even when prices are unknown.

### The corridor average and your average price paid

After a trip is planned, the results show two price figures:

- **Corridor average** — the unweighted mean price of every real-price station found along the route. This represents the "random stop" baseline.
- **Your average price paid** — total cost ÷ total litres bought at the chosen stops.

It is possible for the corridor average to be **lower** than your actual average paid. This is not a bug. It happens when cheap stations are clustered near the start of the route where the tank is already full, so the car drives past them without stopping. Those cheap stations still pull the corridor average down, but they do not reduce the actual cost because no fuel was purchased there. The algorithm is still optimal — it picks the cheapest stops given the actual fuel level at each point on the route.

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

1. Set the folder where you want to store the files and clone the repository
   ```
   cd /YOUR/FOLDER/HERE
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

## Warnings and Known Limitations

If the app displays a warning message (e.g. "Switzerland unavailable", "Austria unavailable", or a timeout error), this is almost always caused by a temporary issue with one of the external APIs — for example, the Overpass API rate-limiting requests or a short server outage. **This is outside our control.** Simply waiting a minute and trying again usually resolves it. The app is designed to continue working with the data it does receive, so a warning from one country does not prevent results from the other two from showing.

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
