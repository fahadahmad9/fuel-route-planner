from django.test import TestCase

import numpy as np

from routing.models import Station
from routing.services.geo import GeoError, resolve_location
from routing.services.stations import get_index, reset_index


class ResolveLocationTests(TestCase):
    def test_dallas_city_resolves(self):
        location = resolve_location("Dallas, TX")
        self.assertAlmostEqual(location["lat"], 32.78306, places=3)
        self.assertAlmostEqual(location["lng"], -96.80667, places=3)

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
