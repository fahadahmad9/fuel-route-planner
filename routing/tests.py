from django.test import TestCase
from django.test import SimpleTestCase, override_settings
from django.core.cache import cache
from rest_framework.test import APITestCase

import numpy as np
import requests
import random
from unittest.mock import patch

from routing.models import Station
from routing.services.geo import GeoError, resolve_location
from routing.services.geo import _load_city_table
from routing.services.optimizer import OptimizerError, optimize_fuel_stops
from routing.services.ors import RoutingError, get_route
from routing.services.route import (
    cumulative_miles,
    find_stations_along_route,
    haversine_miles,
    sample_route,
)
from routing.services.stations import get_index, reset_index


def dynamic_programming_fuel_cost(total_miles, stations):
    """Return the exact minimum cost with fuel discretized to tenths."""
    tank_units = 500
    mpg = 10.0
    ordered = sorted(stations, key=lambda station: station["mile_marker"])
    positions = [0.0] + [
        float(station["mile_marker"]) for station in ordered
    ] + [float(total_miles)]
    prices = [None] + [float(station["price"]) for station in ordered] + [0.0]
    infinity = float("inf")
    costs = [infinity] * (tank_units + 1)
    costs[500] = 0.0

    for index in range(len(positions) - 1):
        distance_units = round(
            (positions[index + 1] - positions[index]) / mpg * 10
        )
        next_costs = [infinity] * (tank_units + 1)
        for fuel_units, cost in enumerate(costs):
            if cost == infinity:
                continue
            max_purchase = 0 if index == 0 else tank_units - fuel_units
            for purchase_units in range(max_purchase + 1):
                remaining = fuel_units + purchase_units - distance_units
                if remaining < 0:
                    continue
                purchase_cost = (
                    0.0
                    if index == 0
                    else purchase_units / 10 * prices[index]
                )
                next_costs[remaining] = min(
                    next_costs[remaining],
                    cost + purchase_cost,
                )
        costs = next_costs

    return min(costs)


class ResolveLocationTests(TestCase):
    def test_dallas_city_resolves(self):
        location = resolve_location("Dallas, TX")
        self.assertGreater(location["lat"], 32.70)
        self.assertLess(location["lat"], 32.90)
        self.assertGreater(location["lng"], -97.0)
        self.assertLess(location["lng"], -96.6)

    def test_city_lookup_is_case_insensitive(self):
        lowercase = resolve_location("dallas,tx")
        titlecase = resolve_location("Dallas, TX")
        self.assertEqual(lowercase["lat"], titlecase["lat"])
        self.assertEqual(lowercase["lng"], titlecase["lng"])

    def test_full_state_name_matches_state_code(self):
        full_name = resolve_location("Kansas City, Missouri")
        code = resolve_location("Kansas City, MO")
        self.assertEqual(
            (full_name["lat"], full_name["lng"]),
            (code["lat"], code["lng"]),
        )

    def test_lowercase_full_state_name_resolves(self):
        location = resolve_location("dallas, texas")
        self.assertGreater(location["lat"], 32.70)
        self.assertLess(location["lat"], 32.90)

    def test_district_of_columbia_resolves(self):
        location = resolve_location("Washington, District of Columbia")
        self.assertEqual(location["label"], "Washington, DC")
        self.assertGreater(location["lat"], 38.8)
        self.assertLess(location["lat"], 39.0)

    def test_unknown_full_state_name_raises(self):
        with self.assertRaises(GeoError):
            resolve_location("Springfield, Narnia")

    def test_coordinates_resolve(self):
        location = resolve_location("32.78,-96.8")
        self.assertEqual(location, {
            "lat": 32.78,
            "lng": -96.8,
            "label": "32.78,-96.8",
        })

    def test_non_us_state_raises(self):
        with self.assertRaises(GeoError):
            resolve_location("Toronto, ON")

    def test_coordinates_outside_usa_raise(self):
        with self.assertRaises(GeoError):
            resolve_location("51.5,-0.12")

    def test_unknown_city_raises(self):
        with self.assertRaises(GeoError):
            resolve_location("Nowhereville, TX")


class StationIndexTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Station.objects.bulk_create([
            Station(
                opis_id=1001,
                name="Dallas Station",
                address="Dallas address",
                city="Dallas",
                state="TX",
                price=3.00,
                lat=32.78306,
                lng=-96.80667,
            ),
            Station(
                opis_id=1002,
                name="Oklahoma City Station",
                address="Oklahoma City address",
                city="Oklahoma City",
                state="OK",
                price=3.10,
                lat=35.4676,
                lng=-97.5164,
            ),
            Station(
                opis_id=1003,
                name="Los Angeles Station",
                address="Los Angeles address",
                city="Los Angeles",
                state="CA",
                price=4.00,
                lat=34.0522,
                lng=-118.2437,
            ),
        ])

    def setUp(self):
        reset_index()

    def tearDown(self):
        reset_index()

    def test_dallas_radius_returns_only_dallas(self):
        index = get_index()
        matches = index.query_radius(np.array([[32.78, -96.8]]), 10)
        self.assertEqual(len(matches), 1)
        self.assertEqual([int(index.ids[i]) for i in matches[0]], [1001])

    def test_nearest_to_points_keeps_closest_point(self):
        index = get_index()
        nearest = index.nearest_to_points(
            np.array([[32.78, -96.8], [32.79, -96.81]]),
            10,
        )
        dallas_index = int(np.where(index.ids == 1001)[0][0])
        self.assertEqual(nearest[dallas_index][0], 0)
        self.assertLess(nearest[dallas_index][1], 10)

    def test_get_index_is_cached_and_resettable(self):
        first = get_index()
        self.assertIs(first, get_index())
        reset_index()
        self.assertIsNot(first, get_index())


class RouteComputationTests(SimpleTestCase):
    def test_haversine_distance(self):
        distance = haversine_miles(34.05, -118.24, 40.71, -74.0)
        self.assertAlmostEqual(float(distance), 2445, delta=20)

    def test_cumulative_miles(self):
        coords = np.array([[32.78, -96.8], [34.0, -97.0], [35.47, -97.52]])
        cumulative = cumulative_miles(coords)
        expected = haversine_miles(
            coords[:-1, 0],
            coords[:-1, 1],
            coords[1:, 0],
            coords[1:, 1],
        )
        self.assertEqual(cumulative[0], 0)
        self.assertTrue(np.all(np.diff(cumulative) > 0))
        self.assertAlmostEqual(cumulative[-1], float(np.sum(expected)))

    def test_sample_route(self):
        coords = np.array([[32.78, -96.8], [35.47, -97.52]])
        cumulative = cumulative_miles(coords)
        points, miles = sample_route(coords, cumulative, step_miles=3)
        self.assertEqual(miles[0], 0)
        self.assertEqual(miles[-1], cumulative[-1])
        self.assertTrue(np.all(np.diff(miles) <= 3.000001))
        self.assertEqual(points.shape[1], 2)
        self.assertEqual(points.shape[0], miles.shape[0])


class RouteStationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Station.objects.bulk_create([
            Station(
                opis_id=2001, name="Dallas Station", address="Dallas address",
                city="Dallas", state="TX", price=3.00,
                lat=32.78306, lng=-96.80667,
            ),
            Station(
                opis_id=2002, name="Oklahoma City Station",
                address="Oklahoma City address", city="Oklahoma City",
                state="OK", price=3.10, lat=35.4676, lng=-97.5164,
            ),
            Station(
                opis_id=2003, name="Los Angeles Station",
                address="Los Angeles address", city="Los Angeles",
                state="CA", price=4.00, lat=34.0522, lng=-118.2437,
            ),
        ])

    def setUp(self):
        reset_index()

    def tearDown(self):
        reset_index()

    def test_find_stations_along_route(self):
        coords = np.array([
            [32.78306, -96.80667],
            [34.125, -97.16],
            [35.4676, -97.5164],
        ])
        result = find_stations_along_route(
            coords,
            corridor_miles=5,
            step_miles=3,
        )
        names = [station["name"] for station in result["stations"]]
        self.assertIn("Dallas Station", names)
        self.assertIn("Oklahoma City Station", names)
        self.assertNotIn("Los Angeles Station", names)
        self.assertLess(
            next(s["mile_marker"] for s in result["stations"]
                 if s["name"] == "Dallas Station"),
            next(s["mile_marker"] for s in result["stations"]
                 if s["name"] == "Oklahoma City Station"),
        )


def ors_response(distance=160934.4, duration=3600):
    return {
        "features": [{
            "geometry": {
                "type": "LineString",
                "coordinates": [[-96.8, 32.78], [-97.5, 35.47]],
            },
            "properties": {
                "summary": {"distance": distance, "duration": duration},
            },
        }],
    }


class ORSClientTests(SimpleTestCase):
    @patch("routing.services.ors.requests.post")
    @override_settings(ORS_API_KEY="test-key")
    def test_get_route_success(self, post):
        response = post.return_value
        response.status_code = 200
        response.json.return_value = ors_response()
        result = get_route(
            {"lat": 32.78, "lng": -96.8},
            {"lat": 35.47, "lng": -97.5},
        )
        self.assertEqual(result["coords"], [(32.78, -96.8), (35.47, -97.5)])
        self.assertAlmostEqual(result["distance_miles"], 100)
        self.assertEqual(result["duration_hours"], 1)
        post.assert_called_once()

    @patch("routing.services.ors.time.sleep")
    @patch("routing.services.ors.requests.post")
    @override_settings(ORS_API_KEY="test-key")
    def test_get_route_retries_timeout(self, post, sleep):
        response = post.return_value
        response.status_code = 200
        response.json.return_value = ors_response()
        post.side_effect = [requests.Timeout(), response]
        self.assertEqual(
            get_route(
                {"lat": 32.78, "lng": -96.8},
                {"lat": 35.47, "lng": -97.5},
            )["duration_hours"],
            1,
        )
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(0.5)

    @patch("routing.services.ors.requests.post")
    @override_settings(ORS_API_KEY="test-key")
    def test_get_route_errors(self, post):
        for status_code in (401, 404, 429):
            post.reset_mock()
            post.return_value.status_code = status_code
            with self.assertRaises(RoutingError):
                get_route({"lat": 1, "lng": 1}, {"lat": 2, "lng": 2})
            self.assertEqual(post.call_count, 1)

    @patch("routing.services.ors.time.sleep")
    @patch("routing.services.ors.requests.post")
    @override_settings(ORS_API_KEY="test-key")
    def test_get_route_two_timeouts(self, post, sleep):
        post.side_effect = [requests.Timeout(), requests.Timeout()]
        with self.assertRaises(RoutingError):
            get_route({"lat": 1, "lng": 1}, {"lat": 2, "lng": 2})
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(0.5)

    @patch("routing.services.ors.requests.post")
    @override_settings(ORS_API_KEY="")
    def test_get_route_requires_api_key(self, post):
        with self.assertRaises(RoutingError):
            get_route({"lat": 1, "lng": 1}, {"lat": 2, "lng": 2})
        post.assert_not_called()


class CityTableRegressionTests(SimpleTestCase):
    def test_new_york_resolves(self):
        location = resolve_location("New York, NY")
        self.assertGreater(location["lat"], 40.5)
        self.assertLess(location["lat"], 41.0)
        self.assertGreater(location["lng"], -74.3)
        self.assertLess(location["lng"], -73.7)

    def test_los_angeles_resolves(self):
        location = resolve_location("Los Angeles, CA")
        self.assertGreater(location["lat"], 33.5)
        self.assertLess(location["lat"], 34.5)

    def test_st_louis_aliases_resolve_to_same_coordinates(self):
        st_louis = resolve_location("St. Louis, MO")
        saint_louis = resolve_location("Saint Louis, MO")
        self.assertEqual(
            (st_louis["lat"], st_louis["lng"]),
            (saint_louis["lat"], saint_louis["lng"]),
        )

    def test_city_table_contains_us_cities(self):
        self.assertGreater(len(_load_city_table()), 20000)


class FuelOptimizerTests(SimpleTestCase):
    def station(self, opis_id, mile_marker, price, city="Test"):
        return {
            "opis_id": opis_id,
            "name": f"{city} Station",
            "address": "Test address",
            "city": city,
            "state": "TX",
            "lat": 32.0,
            "lng": -96.0,
            "price": price,
            "mile_marker": mile_marker,
            "off_route_miles": 0.0,
        }

    def test_short_trip_has_no_stops(self):
        result = optimize_fuel_stops(300, [])
        self.assertEqual(result["stops"], [])
        self.assertEqual(result["total_cost"], 0.0)

    def test_thousand_mile_trip_is_feasible_at_hand_computed_cost(self):
        stations = [
            self.station(1, 400, 4.00),
            self.station(2, 450, 3.00),
            self.station(3, 800, 3.50),
        ]
        result = optimize_fuel_stops(1000, stations)
        # Free initial fuel reaches mile 450; buy 45 gallons at $3,
        # then 5 gallons at $3.50 for miles 800-1000: $152.50 total.
        self.assertEqual(result["total_cost"], 152.5)
        self.assertEqual([stop["opis_id"] for stop in result["stops"]], [2, 3])
        self.assertTrue(all(stop["gallons_purchased"] >= 0 for stop in result["stops"]))
        self.assertEqual(result["stops"][-1]["mile_marker"], 800)

    def test_cheaper_station_gets_only_required_fuel(self):
        result = optimize_fuel_stops(900, [
            self.station(1, 400, 4.00),
            self.station(2, 700, 3.00),
        ])
        first_stop = result["stops"][0]
        self.assertEqual(first_stop["opis_id"], 1)
        self.assertAlmostEqual(first_stop["gallons_purchased"], 20.0)
        self.assertLess(first_stop["gallons_purchased"], 50.0)

    def test_large_gap_is_infeasible(self):
        with self.assertRaises(OptimizerError):
            optimize_fuel_stops(1000, [self.station(1, 501, 3.00)])

    def test_same_mile_marker_keeps_cheapest_station(self):
        result = optimize_fuel_stops(900, [
            self.station(1, 400, 4.00, "Expensive"),
            self.station(2, 400, 3.00, "Cheap"),
            self.station(3, 800, 3.50),
        ])
        self.assertEqual(result["stops"][0]["opis_id"], 2)

    def test_purchase_and_cost_totals_match_stops(self):
        result = optimize_fuel_stops(1000, [
            self.station(1, 400, 4.00),
            self.station(2, 450, 3.00),
            self.station(3, 800, 3.50),
        ])
        self.assertAlmostEqual(
            result["gallons_purchased"],
            sum(stop["gallons_purchased"] for stop in result["stops"]),
        )
        self.assertAlmostEqual(
            result["total_cost"],
            sum(stop["cost"] for stop in result["stops"]),
        )

    def test_replay_never_runs_out_of_fuel(self):
        result = optimize_fuel_stops(1000, [
            self.station(1, 400, 4.00),
            self.station(2, 450, 3.00),
            self.station(3, 800, 3.50),
        ])
        fuel = 50.0
        previous_mile = 0.0
        for stop in result["stops"]:
            fuel -= (stop["mile_marker"] - previous_mile) / 10.0
            self.assertGreaterEqual(fuel, -1e-6)
            fuel += stop["gallons_purchased"]
            previous_mile = stop["mile_marker"]
        fuel -= (1000 - previous_mile) / 10.0
        self.assertGreaterEqual(fuel, -1e-6)
        remainder = result["gallons_purchased"] + 50 - 1000 / 10
        self.assertGreaterEqual(remainder, 0)
        if abs(fuel) < 1e-6:
            self.assertLess(remainder, 1e-6)

    def test_greedy_cost_is_close_to_dynamic_programming_optimum(self):
        for seed in (42, 43, 44):
            rng = random.Random(seed)
            stations = []
            for index in range(25):
                mile_marker = round(
                    (index + 1) * 75 + rng.randint(-15, 15),
                    1,
                )
                stations.append({
                    "opis_id": seed * 1000 + index,
                    "name": f"Station {index}",
                    "address": "Test address",
                    "city": "Test",
                    "state": "TX",
                    "lat": 32.0,
                    "lng": -96.0,
                    "price": round(rng.uniform(2.8, 3.8), 2),
                    "mile_marker": mile_marker,
                    "off_route_miles": 0.0,
                })

            greedy = optimize_fuel_stops(2000, stations)
            optimum = dynamic_programming_fuel_cost(2000, stations)
            print(
                f"seed {seed}: greedy ${greedy['total_cost']:.2f}, "
                f"DP ${optimum:.2f}"
            )
            self.assertAlmostEqual(
                greedy["total_cost"],
                optimum,
                delta=1.00,
            )


class RouteAPITests(APITestCase):
    def setUp(self):
        cache.clear()

    def fake_route(self, distance=600.0):
        return {
            "coords": [
                (32.78, -96.8),
                (35.47, -97.5),
            ],
            "distance_miles": distance,
            "duration_hours": 10.0,
            "geometry": {"type": "LineString", "coordinates": []},
        }

    def test_route_map_renders_template(self):
        response = self.client.get("/api/route/map/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "routing/map.html")

    def fake_stations(self):
        return {
            "total_miles": 600.0,
            "stations": [
                {
                    "opis_id": 1,
                    "name": "First Station",
                    "address": "1 Main St",
                    "city": "Dallas",
                    "state": "TX",
                    "lat": 32.78,
                    "lng": -96.8,
                    "price": 3.0,
                    "mile_marker": 300.0,
                    "off_route_miles": 0.0,
                },
                {
                    "opis_id": 2,
                    "name": "Second Station",
                    "address": "2 Main St",
                    "city": "Oklahoma City",
                    "state": "OK",
                    "lat": 35.47,
                    "lng": -97.5,
                    "price": 3.2,
                    "mile_marker": 500.0,
                    "off_route_miles": 0.0,
                },
            ],
        }

    def fake_optimized(self):
        return {
            "total_miles": 600.0,
            "total_gallons": 60.0,
            "gallons_purchased": 10.0,
            "total_cost": 30.0,
            "stops": [
                {
                    **self.fake_stations()["stations"][0],
                    "gallons_purchased": 10.0,
                    "cost": 30.0,
                },
            ],
        }

    @patch("routing.views.optimize_fuel_stops")
    @patch("routing.views.find_stations_along_route")
    @patch("routing.views.get_route")
    def test_route_endpoint_returns_formatted_route(
        self,
        get_route_mock,
        find_stations_mock,
        optimize_mock,
    ):
        get_route_mock.return_value = {
            "coords": [
                (32.78, -96.8),
                (35.47, -97.5),
            ],
            "distance_miles": 600.0,
            "duration_hours": 10.0,
            "geometry": {"type": "LineString", "coordinates": []},
        }
        find_stations_mock.return_value = self.fake_stations()
        optimize_mock.return_value = self.fake_optimized()

        response = self.client.post(
            "/api/route/",
            {
                "start": "Dallas, TX",
                "finish": "Oklahoma City, OK",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        for key in (
            "start",
            "finish",
            "distance_miles",
            "total_gallons",
            "total_fuel_cost",
            "assumptions",
            "fuel_stops",
            "route_geojson",
            "map_url",
        ):
            self.assertIn(key, body)
        self.assertEqual(
            [stop["mile_marker"] for stop in body["fuel_stops"]],
            sorted(stop["mile_marker"] for stop in body["fuel_stops"]),
        )
        self.assertEqual(
            body["total_fuel_cost"],
            round(sum(stop["cost"] for stop in body["fuel_stops"]), 2),
        )
        get_route_mock.assert_called_once()

    @patch("routing.views.optimize_fuel_stops")
    @patch("routing.views.find_stations_along_route")
    @patch("routing.views.get_route")
    def test_identical_requests_use_cached_payload(
        self,
        get_route_mock,
        find_stations_mock,
        optimize_mock,
    ):
        get_route_mock.return_value = self.fake_route()
        find_stations_mock.return_value = self.fake_stations()
        optimize_mock.return_value = self.fake_optimized()
        first = self.client.get(
            "/api/route/",
            {"start": "Dallas, TX", "finish": "Oklahoma City, OK"},
        )
        second = self.client.get(
            "/api/route/",
            {"start": "Dallas, TX", "finish": "Oklahoma City, OK"},
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first["X-Cache"], "MISS")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second["X-Cache"], "HIT")
        self.assertEqual(get_route_mock.call_count, 1)
        self.assertEqual(find_stations_mock.call_count, 1)
        self.assertEqual(optimize_mock.call_count, 1)

    @patch("routing.views.optimize_fuel_stops")
    @patch("routing.views.find_stations_along_route")
    @patch("routing.views.get_route")
    def test_normalized_inputs_share_cache_key(
        self,
        get_route_mock,
        find_stations_mock,
        optimize_mock,
    ):
        get_route_mock.return_value = self.fake_route()
        find_stations_mock.return_value = self.fake_stations()
        optimize_mock.return_value = self.fake_optimized()
        first = self.client.get(
            "/api/route/",
            {"start": "Los Angeles, CA", "finish": "Dallas, TX"},
        )
        second = self.client.get(
            "/api/route/",
            {"start": "  los angeles,  ca ", "finish": "dallas, tx"},
        )
        self.assertEqual(first["X-Cache"], "MISS")
        self.assertEqual(second["X-Cache"], "HIT")
        self.assertEqual(get_route_mock.call_count, 1)

    def test_error_responses_are_not_cached(self):
        first = self.client.get(
            "/api/route/",
            {"start": "Toronto, ON", "finish": "Dallas, TX"},
        )
        second = self.client.get(
            "/api/route/",
            {"start": "Toronto, ON", "finish": "Dallas, TX"},
        )
        self.assertEqual(first.status_code, 400)
        self.assertEqual(second.status_code, 400)
        self.assertNotEqual(first["X-Cache"], "HIT")
        self.assertNotEqual(second["X-Cache"], "HIT")

    @patch("routing.views.find_stations_along_route")
    @patch("routing.views.get_route")
    def test_short_route_has_zero_fuel_stops_and_cost(
        self,
        get_route_mock,
        find_stations_mock,
    ):
        get_route_mock.return_value = self.fake_route(distance=300.0)
        find_stations_mock.return_value = {"total_miles": 300.0, "stations": []}
        response = self.client.get(
            "/api/route/",
            {"start": "Dallas, TX", "finish": "Oklahoma City, OK"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["fuel_stops"], [])
        self.assertEqual(body["total_fuel_cost"], 0.0)
        get_route_mock.assert_called_once()

    def test_missing_finish_returns_bad_request(self):
        response = self.client.get("/api/route/", {"start": "Dallas, TX"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_non_us_location_returns_bad_request(self):
        response = self.client.get(
            "/api/route/",
            {"start": "Dallas, TX", "finish": "Toronto, ON"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    @patch("routing.views.get_route")
    def test_ors_failure_returns_bad_gateway(self, get_route_mock):
        get_route_mock.side_effect = RoutingError("No drivable route was found.")
        response = self.client.get(
            "/api/route/",
            {"start": "Dallas, TX", "finish": "Oklahoma City, OK"},
        )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {
            "error": "No drivable route was found.",
        })
