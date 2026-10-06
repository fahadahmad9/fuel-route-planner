from django.test import TestCase
from django.test import SimpleTestCase, override_settings

import numpy as np
import requests
from unittest.mock import patch

from routing.models import Station
from routing.services.geo import GeoError, resolve_location
from routing.services.geo import _load_city_table
from routing.services.ors import RoutingError, get_route
from routing.services.route import (
    cumulative_miles,
    find_stations_along_route,
    haversine_miles,
    sample_route,
)
from routing.services.stations import get_index, reset_index


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
