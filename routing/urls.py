from django.urls import path
from routing.views import RouteView, route_map

# This module defines the URL patterns for the routing application,
# mapping specific URL paths to their corresponding views.

urlpatterns = [
    path("route/map/", route_map, name="route-map"),
    path("route/", RouteView.as_view(), name="route"),
]
