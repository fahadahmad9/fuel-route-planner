import csv
from pathlib import Path
from django.core.management.base import BaseCommand
from routing.models import Station

# This Django management command loads fuel station data from CSV files into the database.

class Command(BaseCommand):
    help = "Load fuel stations from CSV data."

    US_STATES = {
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
        "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
        "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
        "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
        "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
        "DC",
    }
    CITY_COLUMNS = {"city_ascii", "state_id", "lat", "lng", "population"}
    FUEL_COLUMNS = {
        "OPIS Truckstop ID",
        "Truckstop Name",
        "Address",
        "City",
        "State",
        "Rack ID",
        "Retail Price",
    }

    @staticmethod
    def normalize_city(city):
        return " ".join(city.strip().lower().split())

    @staticmethod
    def parse_delimiter(line):
        return "\t" if line.count("\t") > line.count(",") else ","

    def read_city_data(self, path):
        cities = {}
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            headers = set(reader.fieldnames or [])
            if not self.CITY_COLUMNS.issubset(headers):
                self.stdout.write(f"Actual headers for {path}: {reader.fieldnames}")
                return None

            for row in reader:
                try:
                    city = self.normalize_city(row["city_ascii"])
                    state = row["state_id"].strip().upper()
                    lat = float(row["lat"].strip())
                    lng = float(row["lng"].strip())
                    population = int(float(row["population"].strip()))
                except (AttributeError, TypeError, ValueError):
                    continue

                key = (city, state)
                existing = cities.get(key)
                if existing is None or population > existing[2]:
                    cities[key] = (lat, lng, population)

        return cities

    def read_fallback_data(self, path, cities):
        fallback_cities = {}
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            for row in reader:
                try:
                    city = self.normalize_city(row["city_ascii"])
                    state = row["state_id"].strip().upper()
                    lat = float(row["lat"].strip())
                    lng = float(row["lng"].strip())
                    population = int(float(row["population"].strip()))
                except (AttributeError, TypeError, ValueError):
                    continue

                key = (city, state)
                existing = fallback_cities.get(key)
                if existing is None or population > existing[2]:
                    fallback_cities[key] = (lat, lng, population)

        for key, coordinates in fallback_cities.items():
            if key not in cities:
                cities[key] = coordinates

    def read_fuel_data(self, path):
        stations = {}
        loaded = 0
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            first_line = file.readline()
            delimiter = self.parse_delimiter(first_line)
            fieldnames = [field.strip() for field in first_line.rstrip("\r\n").split(delimiter)]
            if not self.FUEL_COLUMNS.issubset(fieldnames):
                self.stdout.write(f"Actual headers for {path}: {fieldnames}")
                return None, loaded

            reader = csv.DictReader(file, fieldnames=fieldnames, delimiter=delimiter)
            for row in reader:
                row = {key.strip(): (value or "").strip() for key, value in row.items()}
                try:
                    opis_id = int(row["OPIS Truckstop ID"])
                    price = float(row["Retail Price"])
                except (KeyError, TypeError, ValueError):
                    continue

                loaded += 1
                existing = stations.get(opis_id)
                if existing is None or price < existing["price"]:
                    stations[opis_id] = {
                        "opis_id": opis_id,
                        "name": row["Truckstop Name"],
                        "address": row["Address"],
                        "city": row["City"],
                        "state": row["State"].upper(),
                        "price": price,
                    }

        return stations, loaded

    def handle(self, *args, **options):
        base_dir = Path(__file__).resolve().parents[3]
        city_data = self.read_city_data(base_dir / "data" / "uscities.csv")
        if city_data is None:
            return

        self.read_fallback_data(base_dir / "data" / "us_places_fallback.csv", city_data)
        stations, loaded = self.read_fuel_data(base_dir / "data" / "fuel_prices.csv")
        if stations is None:
            return

        unmatched = set()
        unmatched_count = 0
        non_us_count = 0
        matched_stations = []
        for station in stations.values():
            if station["state"] not in self.US_STATES:
                non_us_count += 1
                continue

            key = (self.normalize_city(station["city"]), station["state"])
            coordinates = city_data.get(key)
            if coordinates is None:
                unmatched_count += 1
                unmatched.add((station["city"].strip(), station["state"]))
                continue

            station["lat"], station["lng"] = coordinates[:2]
            matched_stations.append(Station(**station))

        Station.objects.all().delete()
        Station.objects.bulk_create(matched_stations, batch_size=1000)

        self.stdout.write(f"Stations loaded: {len(matched_stations)}")
        self.stdout.write(f"Unique stations: {len(stations)}")
        self.stdout.write(f"Skipped non-US: {non_us_count}")
        self.stdout.write(f"Unmatched US: {unmatched_count}")
        self.stdout.write("Unmatched US City, State pairs:")
        for city, state in sorted(unmatched)[:20]:
            self.stdout.write(f"{city}, {state}")
