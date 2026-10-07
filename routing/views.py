import hashlib
import time
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache
from django.shortcuts import render
from rest_framework.response import Response
from rest_framework.views import APIView

from routing.serializers import RouteRequestSerializer
from routing.services.geo import GeoError, resolve_location
from routing.services.optimizer import OptimizerError, optimize_fuel_stops
from routing.services.ors import RoutingError, get_route
from routing.services.route import find_stations_along_route

# This module defines the views for the routing application, 
# including the route map view and the API view for handling route requests.

def route_map(request):
    return render(request, "routing/map.html")

class RouteView(APIView):
    def get(self, request, *args, **kwargs):
        return self._handle(request.query_params)

    def post(self, request, *args, **kwargs):
        return self._handle(request.data)

    def _handle(self, data):
        started = time.perf_counter()
        serializer = RouteRequestSerializer(data=data)
        if not serializer.is_valid():
            return self._response(
                {"error": serializer.errors}, 400, "MISS", started
            )

        start_text = self._normalize_input(serializer.validated_data["start"])
        finish_text = self._normalize_input(serializer.validated_data["finish"])
        cache_key = self._cache_key(start_text, finish_text)
        cached_payload = cache.get(cache_key)
        if cached_payload is not None:
            return self._response(cached_payload, 200, "HIT", started)

        try:
            start = resolve_location(serializer.validated_data["start"])
            finish = resolve_location(serializer.validated_data["finish"])
        except GeoError as error:
            return self._response({"error": str(error)}, 400, "MISS", started)

        try:
            route = get_route(start, finish)
        except RoutingError as error:
            return self._response({"error": str(error)}, 502, "MISS", started)

        try:
            matched = find_stations_along_route(route["coords"])
            optimized = optimize_fuel_stops(
                matched["total_miles"],
                matched["stations"],
            )
        except OptimizerError as error:
            return self._response({"error": str(error)}, 422, "MISS", started)

        coords = route["coords"]
        if len(coords) > 1500:
            step = (len(coords) - 1) / 1499
            selected = [coords[round(index * step)] for index in range(1499)]
            coords = selected + [coords[-1]]

        query = urlencode({
            "start": serializer.validated_data["start"],
            "finish": serializer.validated_data["finish"],
        })
        fuel_stops = [
            {
                "name": station["name"],
                "address": station["address"],
                "city": station["city"],
                "state": station["state"],
                "lat": float(station["lat"]),
                "lng": float(station["lng"]),
                "price": round(float(station["price"]), 3),
                "mile_marker": round(float(station["mile_marker"]), 1),
                "gallons": round(float(station["gallons_purchased"]), 2),
                "cost": round(float(station["cost"]), 2),
            }
            for station in optimized["stops"]
        ]
        payload = {
            "start": {
                "label": start["label"],
                "lat": float(start["lat"]),
                "lng": float(start["lng"]),
            },
            "finish": {
                "label": finish["label"],
                "lat": float(finish["lat"]),
                "lng": float(finish["lng"]),
            },
            "distance_miles": round(float(route["distance_miles"]), 1),
            "total_gallons": round(float(optimized["total_gallons"]), 2),
            "total_fuel_cost": round(float(optimized["total_cost"]), 2),
            "assumptions": {
                "max_range_miles": 500,
                "mpg": 10,
                "starts_with_full_tank": True,
            },
            "fuel_stops": fuel_stops,
            "route_geojson": {
                "type": "LineString",
                "coordinates": [
                    [float(lng), float(lat)] for lat, lng in coords
                ],
            },
            "map_url": self._map_url(
                serializer.validated_data["start"],
                serializer.validated_data["finish"],
            ),
        }
        cache.set(cache_key, payload, settings.ROUTE_CACHE_TTL)
        return self._response(payload, 200, "MISS", started)

    @staticmethod
    def _normalize_input(value):
        return " ".join(value.lower().strip().split())

    @staticmethod
    def _cache_key(start, finish):
        value = f"{start}\n{finish}".encode("utf-8")
        digest = hashlib.sha256(value).hexdigest()
        return f"route:v1:{digest}"

    @staticmethod
    def _response(payload, status, cache_status, started):
        response = Response(payload, status=status)
        response["X-Cache"] = cache_status
        elapsed_ms = (time.perf_counter() - started) * 1000
        response["X-Response-Time-ms"] = f"{elapsed_ms:.2f}"
        return response

    def _map_url(self, start, finish):
        path = "/api/route/map/?" + urlencode({
            "start": start,
            "finish": finish,
        })
        return self.request.build_absolute_uri(path)
