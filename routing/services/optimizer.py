# This module provides a function to optimize fuel stops along a route based on total miles, 
# available stations, vehicle range, and fuel efficiency.

MAX_RANGE_MILES = 500.0
MPG = 10.0
TANK_GALLONS = MAX_RANGE_MILES / MPG

class OptimizerError(Exception):
    pass

def optimize_fuel_stops(
    total_miles: float,
    stations: list[dict],
    max_range=MAX_RANGE_MILES,
    mpg=MPG,
) -> dict:
    total_miles = float(total_miles)
    max_range = float(max_range)
    mpg = float(mpg)
    if total_miles <= max_range:
        return {
            "total_miles": total_miles,
            "total_gallons": round(total_miles / mpg, 2),
            "gallons_purchased": 0.0,
            "total_cost": 0.0,
            "stops": [],
        }

    candidates = {}
    for station in stations:
        mile = float(station["mile_marker"])
        if 0 <= mile <= total_miles:
            current = candidates.get(mile)
            if current is None or float(station["price"]) < float(current["price"]):
                candidates[mile] = dict(station)
    ordered = [candidates[mile] for mile in sorted(candidates)]

    def reachable(position, limit):
        return [
            station for station in ordered
            if position < float(station["mile_marker"]) <= limit
        ]

    position = 0.0
    fuel = TANK_GALLONS
    purchased = 0.0
    cost = 0.0
    stops = []

    initial_options = reachable(position, max_range)
    if not initial_options:
        raise OptimizerError(
            f"No fuel station reachable between mile {position:g} and "
            f"mile {min(total_miles, max_range):g} "
            f"(gap exceeds {max_range:g}-mile range)."
        )
    current = min(initial_options, key=lambda station: float(station["price"]))

    while True:
        current_mile = float(current["mile_marker"])
        distance = current_mile - position
        fuel -= distance / mpg
        assert fuel >= -1e-9
        fuel = max(0.0, fuel)
        position = current_mile

        ahead = reachable(position, position + max_range)
        destination_distance = total_miles - position
        if destination_distance <= max_range and destination_distance / mpg <= fuel:
            buy = 0.0
            next_station = None
        else:
            cheaper = [
                station for station in ahead
                if float(station["price"]) < float(current["price"])
            ]
            if cheaper:
                next_station = cheaper[0]
                target_distance = float(next_station["mile_marker"]) - position
                buy = max(0.0, target_distance / mpg - fuel)
            else:
                if destination_distance <= max_range:
                    next_station = None
                    buy = max(0.0, destination_distance / mpg - fuel)
                elif not ahead:
                    raise OptimizerError(
                        f"No fuel station reachable between mile {position:g} "
                        f"and mile {position + max_range:g} "
                        f"(gap exceeds {max_range:g}-mile range)."
                    )
                else:
                    next_station = min(
                        ahead, key=lambda station: float(station["price"])
                    )
                    buy = max(0.0, TANK_GALLONS - fuel)

        stop = dict(current)
        stop["gallons_purchased"] = buy
        stop["cost"] = buy * float(current["price"])
        stops.append(stop)
        purchased += buy
        cost += stop["cost"]
        fuel += buy
        assert fuel <= TANK_GALLONS + 1e-9

        if next_station is None:
            fuel -= destination_distance / mpg
            assert fuel >= -1e-9
            break
        current = next_station

    return {
        "total_miles": total_miles,
        "total_gallons": round(total_miles / mpg, 2),
        "gallons_purchased": purchased,
        "total_cost": round(cost, 2),
        "stops": stops,
    }
