import csv
import re
from functools import lru_cache

from django.conf import settings


US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC",
}

MIN_LATITUDE = 24.0
MAX_LATITUDE = 50.0
MIN_LONGITUDE = -125.0
MAX_LONGITUDE = -66.0


class GeoError(ValueError):
    pass


def normalize(city):
    city = city.strip().lower().replace(".", "")
    city = " ".join(city.split())
    return re.sub(r"\bst\b", "saint", city)


def _parse_delimiter(line):
    return "\t" if line.count("\t") > line.count(",") else ","


def _read_places(path, cities, allow_existing):
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        first_line = file.readline()
        delimiter = _parse_delimiter(first_line)
        fieldnames = [
            field.strip()
            for field in next(
                csv.reader([first_line], delimiter=delimiter)
            )
        ]
        required_columns = {"city_ascii", "state_id", "lat", "lng"}
        missing_columns = required_columns.difference(fieldnames)
        if missing_columns:
            raise RuntimeError(
                f"Required columns missing from {path}: "
                f"{sorted(missing_columns)}; found {fieldnames}"
            )
        reader = csv.DictReader(file, fieldnames=fieldnames, delimiter=delimiter)
        for row in reader:
            try:
                city = normalize(row["city_ascii"])
                state = row["state_id"].strip().upper()
                lat = float(row["lat"].strip())
                lng = float(row["lng"].strip())
                population = int(float(row["population"].strip()))
            except (AttributeError, KeyError, TypeError, ValueError):
                continue

            key = (city, state)
            existing = cities.get(key)
            if existing is None or (allow_existing and population > existing[2]):
                cities[key] = (lat, lng, population)


@lru_cache(maxsize=1)
def _load_city_table():
    data_dir = settings.BASE_DIR / "data"
    cities = {}
    _read_places(data_dir / "uscities.csv", cities, True)

    fallback_cities = {}
    _read_places(data_dir / "us_places_fallback.csv", fallback_cities, True)
    for key, coordinates in fallback_cities.items():
        if key not in cities:
            cities[key] = coordinates

    return {key: (value[0], value[1]) for key, value in cities.items()}


def _in_bounds(lat, lng):
    return (
        MIN_LATITUDE <= lat <= MAX_LATITUDE
        and MIN_LONGITUDE <= lng <= MAX_LONGITUDE
    )


def resolve_location(text: str) -> dict:
    if not isinstance(text, str) or not text.strip():
        raise GeoError("Location input cannot be empty.")

    value = text.strip()
    if "," not in value:
        raise GeoError("Location must be 'City, ST' or 'lat,lng'.")

    first, second = value.rsplit(",", 1)
    try:
        lat = float(first.strip())
        lng = float(second.strip())
    except ValueError:
        city = first.strip()
        state = second.strip().upper()
        if state not in US_STATES:
            raise GeoError(f"Unknown US state code: {state or '<empty>'}.")
        coordinates = _load_city_table().get((normalize(city), state))
        if coordinates is None:
            raise GeoError(f"City not found: {city}, {state}.")
        return {
            "lat": float(coordinates[0]),
            "lng": float(coordinates[1]),
            "label": f"{city}, {state}",
        }

    if not _in_bounds(lat, lng):
        raise GeoError("Coordinates are outside the contiguous USA.")
    return {"lat": lat, "lng": lng, "label": value}
