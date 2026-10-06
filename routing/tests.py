from django.test import TestCase

from routing.services.geo import GeoError, resolve_location


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
