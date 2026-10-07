# Fuel Route Planner

Django API that takes a start and finish in the USA and returns the driving route, the cheapest fuel stops along it (500-mile range, 10 mpg), and the total fuel cost. It also includes a Leaflet map page.

## How it works
1. **Local geocoding:** `"City, ST"` is resolved from a bundled city table, so there are no geocoding API calls.
2. **One routing call:** a single OpenRouteService directions request per uncached route.
3. **Station matching:** fuel stations are held in memory and indexed with a KD-tree, then matched to points along the route with their mile markers.
4. **Optimizer:** a greedy cost-minimizing strategy, cross-checked against a DP solution in the tests.
5. **Caching:** successful responses are cached for 24 hours. A repeat request makes zero external calls.

## Setup
```bash
python -m venv .venv
.venv\Scripts\activate          # Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # add your free OpenRouteService key
python manage.py migrate
python manage.py load_stations
python manage.py runserver
```
Get a free ORS key at openrouteservice.org.

## Usage
**JSON API**
```
GET  /api/route/?start=Los Angeles, CA&finish=New York, NY
POST /api/route/   {"start": "Los Angeles, CA", "finish": "New York, NY"}
```
Returns `distance_miles`, `total_gallons`, `total_fuel_cost`, `fuel_stops[]`, `route_geojson` and `map_url`. Response headers include `X-Cache` (HIT/MISS) and `X-Response-Time-ms`.

**Map page**
```
/api/route/map/?start=Los Angeles, CA&finish=New York, NY
```

Errors return JSON `{"error": ...}`: 400 for invalid input, 422 when no station is reachable within 500 miles, 502 when routing fails.

## Assumptions
- Max range is 500 miles and fuel economy is 10 mpg (a 50-gallon tank).
- The tank starts full and the initial fuel is not billed.
- The optimizer minimizes cost only, with no minimum purchase per stop, so small top-ups can appear.
- Inputs: `"City, ST"` or `"lat,lng"` inside the USA.

## Known limitations
- Station coordinates are **city centroids**, accurate to a few miles, not exact addresses.
- About 58 US stations (of roughly 6,600) could not be matched to a city and are excluded. Canadian stations are dropped.
- The cache is in-memory and per process (use Redis in production).
- Only stations within 5 miles of the route are considered (route sampled every 3 miles). Off-route distance is not added to cost, so a chosen stop can be up to 5 miles off the highway.

## Data and credits
- Fuel prices: provided assessment file (deduplicated, lowest price per OPIS ID).
- City coordinates: [SimpleMaps US Cities](https://simplemaps.com/data/us-cities) and [GeoNames](https://www.geonames.org/) (fallback, `data/us_places_fallback.csv`).
- Routing: [OpenRouteService](https://openrouteservice.org/). Map: Leaflet with OpenStreetMap tiles.

## Tests
```bash
python manage.py test routing
```