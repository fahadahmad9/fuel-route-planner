from django.urls import path

from routing.views import RouteView, route_map


urlpatterns = [
    path("route/map/", route_map, name="route-map"),
    path("route/", RouteView.as_view(), name="route"),
]
