# Programming - Introduction Level
Group 4495
 
## FuelFinder - Fuel Price Tracker for CH/DE/AT
 
FuelFinder is a Python command-line application developed to find and compare live fuel prices near any location in Switzerland, Germany, and Austria. The app allows users to compare prices across multiple data sources and find the cheapest station in their area.
 
This application was developed as part of the group project for the course "Programming - Introduction Level" at the University of St. Gallen.
 
## Features
 
- **Live Price Data**: Fetches real-time fuel prices via the Tankerkönig API (DE), Spritpreisrechner.at (AT), and OpenStreetMap Overpass API (CH)
- **Location Search**: Converts any city name or postcode into coordinates via the Nominatim geocoding API
- **Price Comparison**: Sorts and filters stations by fuel type (E5, E10, Diesel) and search radius
- **Interactive Map**: Color-coded station markers (green = cheap, red = expensive) with popups showing name, brand, price, and distance — saved as `fuel_map.html`
- **Terminal Output**: Clean price table printed directly in the terminal using `rich`
- **Cross-border Search**: Covers stations in Switzerland, Germany, and Austria in one query
## Technical Requirements
 
1. **Clear Problem**: The app solves the problem of finding and comparing fuel prices across three countries in real time
2. **Data Usage**: The app fetches live data via three external APIs (Tankerkönig, Spritpreisrechner.at, OpenStreetMap Overpass)
3. **Data Visualization**: Interactive Folium map with color-coded price tiers
4. **User Interaction**: Terminal prompts for location, fuel type, and search radius
5. **Documentation**: Detailed comments throughout the source code
## Installation
 
### Prerequisites
 
- Python 3.8 or higher
- pip (Python Package Manager)
- A free Tankerkönig API key → [register here](https://creativecommons.tankerkoenig.de/)
### Installation Steps
 
1. Clone the repository or download the files
   ```
   git clone https://github.com/[your-repo]/fuelfinder
   cd fuelfinder
   ```
 
2. Create a virtual environment (recommended)
   ```
   python -m venv venv
   ```
 
3. Activate the virtual environment
   ```
   source venv/bin/activate
   ```
 
4. Install dependencies
   ```
   pip install -r requirements.txt
   ```
 
5. Set up your API key
   ```
   cp .env.example .env
   ```
   Open `.env` and paste your Tankerkönig API key:
   ```
   TANKERKOENIG_API_KEY=your_key_here
   ```
 
## Running the App
 
After installation, start the app with:
 
```
python main.py
```
 
Follow the prompts in the terminal. The results will be displayed as a price table and an interactive map (`fuel_map.html`) will open automatically in your browser.
 
## Usage
 
1. Enter the start location (city name or postcode)
2. Select a fuel type: E5, E10, or Diesel
3. Enter a search radius in km
4. Wait while the app fetches live prices from all three sources
5. View the results in the terminal table
6. Explore the interactive map that opens automatically in your browser
## External Dependencies
 
- **requests**: Sends HTTP requests to all fuel price APIs
- **python-dotenv**: Loads the API key securely from the `.env` file
- **pandas**: Merges, sorts, and filters station data across all sources
- **folium**: Generates the interactive HTML map with color-coded markers
- **geopy**: Geocoding — converts city names and postcodes to lat/lng coordinates
- **rich**: Renders the formatted price table in the terminal
- **tabulate**: Fallback table formatting
## Sources and References
 
- **Tankerkönig API**: https://creativecommons.tankerkoenig.de/
- **OpenStreetMap Overpass API**: https://overpass-api.de/
- **Spritpreisrechner.at**: https://www.spritpreisrechner.at/
- **GeoPy Documentation**: https://geopy.readthedocs.io/
- **Folium Documentation**: https://python-visualization.github.io/folium/
- **Pandas Documentation**: https://pandas.pydata.org/docs/
- **Nominatim / OpenStreetMap**: https://nominatim.org/
- **ChatGPT and GitHub Copilot**: Code optimization, debugging, and README structuring
## Notes for Further Development
 
The following features could be added in future versions:
- Integration of additional fuel types such as LPG or hydrogen
- Connection to real-time traffic data for smarter route suggestions
- Implementation of a Flask web interface with form-based input and embedded map
- Option to save and compare multiple searches over time
- Price history tracking across different days
