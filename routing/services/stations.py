# This module provides a spatial index for stations, 
# allowing efficient querying of nearby stations based on latitude and longitude. 
# It uses a KD-tree for fast nearest neighbor searches and supports querying within a specified radius.

import numpy as np
from scipy.spatial import cKDTree
from routing.models import Station

EARTH_RADIUS_MILES = 3958.8
REFERENCE_LATITUDE = 38.0

class StationIndex:
    def __init__(self):
        rows = list(
            Station.objects.filter(
                lat__isnull=False,
                lng__isnull=False,
            ).order_by("id").values_list(
                "opis_id",
                "name",
                "address",
                "city",
                "state",
                "price",
                "lat",
                "lng",
            )
        )
        self.ids = np.array([row[0] for row in rows], dtype=np.int64)
        self.names = np.array([row[1] for row in rows], dtype=object)
        self.addresses = np.array([row[2] for row in rows], dtype=object)
        self.cities = np.array([row[3] for row in rows], dtype=object)
        self.states = np.array([row[4] for row in rows], dtype=object)
        self.prices = np.array([row[5] for row in rows], dtype=float)
        self.lats = np.array([row[6] for row in rows], dtype=float)
        self.lngs = np.array([row[7] for row in rows], dtype=float)
        self.tree = cKDTree(self.project(self.lats, self.lngs))

    @staticmethod
    def project(lats, lngs):
        lats = np.asarray(lats, dtype=float)
        lngs = np.asarray(lngs, dtype=float)
        reference_latitude = np.radians(REFERENCE_LATITUDE)
        x = EARTH_RADIUS_MILES * np.radians(lngs) * np.cos(reference_latitude)
        y = EARTH_RADIUS_MILES * np.radians(lats)
        return np.column_stack((x, y))

    def query_radius(self, points_lat_lng, radius_miles):
        points = np.asarray(points_lat_lng, dtype=float)
        projected_points = self.project(points[:, 0], points[:, 1])
        return self.tree.query_ball_point(projected_points, radius_miles)

    def nearest_to_points(self, points_lat_lng, radius_miles):
        points = np.asarray(points_lat_lng, dtype=float)
        projected_points = self.project(points[:, 0], points[:, 1])
        candidates = self.tree.query_ball_point(projected_points, radius_miles)
        nearest = {}
        for point_index, station_indices in enumerate(candidates):
            if not station_indices:
                continue
            station_indices = np.asarray(station_indices, dtype=int)
            deltas = self.tree.data[station_indices] - projected_points[point_index]
            distances = np.linalg.norm(deltas, axis=1)
            for station_index, distance in zip(station_indices, distances):
                station_index = int(station_index)
                distance = float(distance)
                current = nearest.get(station_index)
                if current is None or distance < current[1]:
                    nearest[station_index] = (point_index, distance)
        return nearest

    def station_dict(self, i):
        return {
            "opis_id": int(self.ids[i]),
            "name": str(self.names[i]),
            "address": str(self.addresses[i]),
            "city": str(self.cities[i]),
            "state": str(self.states[i]),
            "price": float(self.prices[i]),
            "lat": float(self.lats[i]),
            "lng": float(self.lngs[i]),
        }

_index = None

def get_index():
    global _index
    if _index is None:
        _index = StationIndex()
    return _index

def reset_index():
    global _index
    _index = None
