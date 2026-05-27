# Programming - Introduction Level
Group 4495

## FuelFinder — Live Fuel Prices for DE / AT / CH

FuelFinder is a Streamlit web app for comparing live fuel prices across Germany, Austria, and Switzerland. It offers two modes: a **nearby station finder** that maps the cheapest stations around any location, and a **trip planner** that calculates the cost-optimal refuel stops along a driving route.

This application was developed as part of the group project for the course "Programming - Introduction Level" at the University of St. Gallen.

## Features

- **Live price data** — Tankerkönig API (DE), Spritpreisrechner.at (AT), OpenStreetMap Overpass API (CH)
- **Address autocomplete** — Mapbox Geocoding API with instant suggestions as you type
- **Interactive map** — Mapbox Streets tiles with colour-coded station markers (green = cheapest third, orange = middle, red = most expensive, grey = no data)
- **Trip planner** — enter start and destination, specify tank size, current fuel, and consumption; the app computes a driving route via Mapbox Directions, searches for priced stations along the corridor, and picks the cheapest refuel stops using the classical Gas Station Problem greedy algorithm
- **Parallel API calls** — all route waypoints are searched simultaneously using `ThreadPoolExecutor`, cutting trip planner load time significantly
- **Cost summary** — total fuel cost, number of stops, and savings vs. the corridor average price
- **Cross-border search** — covers DE, AT, and CH in one query; bounding-box pre-checks skip irrelevant country APIs for faster results

## Technical Requirements

1. **Clear problem** — finds and compares live fuel prices across three countries and plans cost-optimal refuel stops on a route
2. **Data usage** — live data from three external APIs (Tankerkönig, Spritpreisrechner.at, Overpass) plus Mapbox for geocoding and routing
3. **Data visualisation** — interactive Folium/Mapbox map with colour-coded price tiers and route polyline
4. **User interaction** — address autocomplete search, fuel type selector, radius slider, vehicle parameter inputs
5. **Documentation** — detailed inline comments throughout the source code

## Installation

### Prerequisites

- Python 3.10 or higher
- pip
- A free Tankerkönig API key → [register here](https://creativecommons.tankerkoenig.de/)
- A free Mapbox access token → [register here](https://account.mapbox.com/)

### Steps (to be taken in Terminal)

1. Clone the repository
   ```
   git clone https://github.com/[your-repo]/fuelfinder
   cd fuelfinder
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

4. Set up your API keys — create a `.env` file in the project root:
   ```
   TANKERKOENIG_API_KEY=your_tankerkoenig_key_here
   MAPBOX_TOKEN=your_mapbox_token_here
   ```

## Running the App

```
streamlit run main.py
```

The app opens automatically at `http://localhost:8501`.

## Usage

### Find nearby (Mode 1)
1. Type a city, postcode, or address into the search box and select a suggestion
2. Choose a fuel type (E5, E10, Diesel) and search radius
3. Click **Search** — live prices load from all three countries
4. Explore the colour-coded map and station table

### Trip planner (Mode 2)
1. Enter a start location and destination via the autocomplete search boxes
2. Set your fuel type, tank capacity, current fuel level, and consumption (L/100 km)
3. Click **Plan trip** — the app fetches a driving route, searches for stations along the corridor, and runs the cost optimisation
4. Review the route map, headline metrics, and the detailed refuel plan table

## Data Source Limitations

| Source | Country | Prices | Notes |
|---|---|---|---|
| Tankerkönig | DE | Yes | Requires free API key; radius capped at 25 km |
| Spritpreisrechner.at | AT | Yes | No key needed; prices may be empty outside 12:00/14:00/16:00 reporting windows |
| OpenStreetMap Overpass | CH | Locations only | No public Swiss price database |

## Project Structure

```
FuelFinder/
├── main.py              # Streamlit app — all logic and UI
├── config.py            # Shared constants (radius defaults, API URLs, corridor settings)
├── requirements.txt     # Python dependencies
├── .env                 # API keys (not committed to git)
└── .streamlit/
    └── config.toml      # Dark theme, primary colour, font settings
```

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

## Sources and References

- **Tankerkönig API**: https://creativecommons.tankerkoenig.de/
- **OpenStreetMap Overpass API**: https://overpass-api.de/
- **Spritpreisrechner.at**: https://www.spritpreisrechner.at/
- **Mapbox Geocoding & Directions**: https://docs.mapbox.com/api/
- **Folium Documentation**: https://python-visualization.github.io/folium/
- **Pandas Documentation**: https://pandas.pydata.org/docs/
- **GeoPy Documentation**: https://geopy.readthedocs.io/
- **Nominatim / OpenStreetMap**: https://nominatim.org/
- **ChatGPT and GitHub Copilot**: Code optimisation, debugging, and README structuring

## Potential Future Features

- Integration of additional fuel types (LPG, hydrogen, EV charging)
- Price history tracking across multiple days
- User accounts for saving favourite locations and past trips
- Real-time traffic integration for smarter route suggestions
- Streamlit Cloud deployment with secrets management
