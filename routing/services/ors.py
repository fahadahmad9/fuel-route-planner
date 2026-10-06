import time

import requests
from django.conf import settings


class RoutingError(Exception):
    pass


ORS_URL = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"


def get_route(start: dict, finish: dict) -> dict:
    api_key = settings.ORS_API_KEY
    if not api_key:
        raise RoutingError("OpenRouteService API key is not configured.")

    payload = {
        "coordinates": [
            [start["lng"], start["lat"]],
            [finish["lng"], finish["lat"]],
        ],
        "instructions": False,
        "radiuses": [-1, -1],
    }
    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json",
    }

    response = None
    for attempt in range(2):
        try:
            response = requests.post(
                ORS_URL,
                headers=headers,
                json=payload,
                timeout=(5, 20),
            )
        except (requests.Timeout, requests.ConnectionError) as error:
            if attempt == 0:
                time.sleep(0.5)
                continue
            raise RoutingError(
                "OpenRouteService could not be reached after retrying."
            ) from error

        if 500 <= response.status_code <= 599 and attempt == 0:
            time.sleep(0.5)
            continue
        break

    if response.status_code in (401, 403):
        raise RoutingError("OpenRouteService rejected the API key.")
    if response.status_code == 404:
        raise RoutingError("No drivable route was found between the points.")
    if response.status_code == 429:
        raise RoutingError("OpenRouteService rate limit exceeded.")
    if response.status_code != 200:
        raise RoutingError(
            f"OpenRouteService returned an unexpected error "
            f"(HTTP {response.status_code})."
        )

    try:
        data = response.json()
        feature = data["features"][0]
        geometry = feature["geometry"]
        coordinates = geometry["coordinates"]
        summary = feature["properties"]["summary"]
        distance_miles = float(summary["distance"]) / 1609.344
        duration_hours = float(summary["duration"]) / 3600
        route_coords = [(float(lat), float(lng)) for lng, lat in coordinates]
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise RoutingError("OpenRouteService returned malformed route data.") from error

    return {
        "coords": route_coords,
        "distance_miles": distance_miles,
        "duration_hours": duration_hours,
        "geometry": geometry,
    }
