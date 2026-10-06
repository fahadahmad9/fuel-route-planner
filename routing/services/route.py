import numpy as np

from routing.services.stations import EARTH_RADIUS_MILES, get_index


def haversine_miles(lat1, lng1, lat2, lng2):
    lat1 = np.radians(np.asarray(lat1, dtype=float))
    lng1 = np.radians(np.asarray(lng1, dtype=float))
    lat2 = np.radians(np.asarray(lat2, dtype=float))
    lng2 = np.radians(np.asarray(lng2, dtype=float))
    delta_lat = lat2 - lat1
    delta_lng = lng2 - lng1
    a = (
        np.sin(delta_lat / 2) ** 2
        + np.cos(lat1) * np.cos(lat2) * np.sin(delta_lng / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(a))


def cumulative_miles(coords):
    points = np.asarray(coords, dtype=float)
    segments = haversine_miles(
        points[:-1, 0],
        points[:-1, 1],
        points[1:, 0],
        points[1:, 1],
    )
    return np.concatenate(([0.0], np.cumsum(segments)))


def sample_route(coords, cum, step_miles=3.0):
    points = np.asarray(coords, dtype=float)
    cumulative = np.asarray(cum, dtype=float)
    total = float(cumulative[-1])
    if total == 0:
        miles = np.array([0.0])
    else:
        miles = np.concatenate((
            np.arange(0.0, total, step_miles),
            [total],
        ))
        miles = np.unique(miles)
    sampled = np.column_stack((
        np.interp(miles, cumulative, points[:, 0]),
        np.interp(miles, cumulative, points[:, 1]),
    ))
    return sampled, miles


def find_stations_along_route(
    coords,
    index=None,
    corridor_miles=5.0,
    step_miles=3.0,
):
    if index is None:
        index = get_index()
    cumulative = cumulative_miles(coords)
    points, miles = sample_route(coords, cumulative, step_miles)
    hits = index.nearest_to_points(points, corridor_miles)
    stations = []
    for station_index, (point_index, distance) in hits.items():
        station = index.station_dict(station_index)
        station["mile_marker"] = round(float(miles[point_index]), 2)
        station["off_route_miles"] = round(float(distance), 2)
        stations.append(station)
    stations.sort(key=lambda station: station["mile_marker"])
    return {
        "total_miles": float(cumulative[-1]),
        "stations": stations,
    }
