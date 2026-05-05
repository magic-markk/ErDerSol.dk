from datetime import datetime, timezone
from math import atan2, degrees, tan, radians, cos, sin

from astral import Observer
from astral.sun import elevation, azimuth
from shapely.geometry import Point, Polygon


def get_sun_position(lat: float, lon: float, when_utc: datetime | None = None) -> dict:
    if when_utc is None:
        when_utc = datetime.now(timezone.utc)

    observer = Observer(latitude=lat, longitude=lon, elevation=0)

    return {
        "timestamp_utc": when_utc.isoformat(),
        "sun_elevation_deg": elevation(observer, when_utc),
        "sun_azimuth_deg": azimuth(observer, when_utc),
    }


def point_in_building_shadow(
    lat: float,
    lon: float,
    buildings: list[dict],
    when_utc: datetime | None = None
) -> dict:
    sun = get_sun_position(lat, lon, when_utc)
    sun_elev = sun["sun_elevation_deg"]
    sun_az = sun["sun_azimuth_deg"]

    target = Point(lon, lat)

    # 1) Tjek først om punktet ligger inde i en bygning
    for building in buildings:
        polygon_coords = building.get("polygon", [])

        if len(polygon_coords) < 3:
            continue

        poly = Polygon(polygon_coords)

        if not poly.is_valid:
            poly = poly.buffer(0)

        if poly.is_empty:
            continue

        # covers() er lidt mere robust end contains()
        # fordi den også accepterer punkter på kanten
        if poly.covers(target):
            return {
                "in_shadow": True,
                "reason": "Point is inside building footprint",
                "sun": sun,
                "blocking_building": {
                    "id": building.get("id"),
                    "height_m": building.get("height_m", 10.0),
                },
            }

    # 2) Hvis solen er under horisonten
    if sun_elev <= 0:
        return {
            "in_shadow": True,
            "reason": "Sun below horizon",
            "sun": sun,
            "blocking_building": None,
        }

    # 3) Ellers tjek om bygninger kaster skygge på punktet
    shadow_bearing = (sun_az + 180) % 360

    for building in buildings:
        polygon_coords = building.get("polygon", [])

        if len(polygon_coords) < 3:
            continue

        poly = Polygon(polygon_coords)

        if not poly.is_valid:
            poly = poly.buffer(0)

        if poly.is_empty:
            continue

        nearest = poly.exterior.interpolate(poly.exterior.project(target))
        nearest_lon, nearest_lat = nearest.x, nearest.y

        distance_m = approximate_distance_m(lat, lon, nearest_lat, nearest_lon)
        bearing_to_building = bearing_degrees(lat, lon, nearest_lat, nearest_lon)

        angle_diff = smallest_angle_diff(shadow_bearing, bearing_to_building)
        if angle_diff > 25:
            continue

        height_m = building.get("height_m", 10.0)
        shadow_length_m = height_m / tan(radians(sun_elev))

        if distance_m <= shadow_length_m:
            return {
                "in_shadow": True,
                "reason": "Blocked by building shadow",
                "sun": sun,
                "blocking_building": {
                    "id": building.get("id"),
                    "height_m": height_m,
                    "distance_m": round(distance_m, 1),
                    "shadow_length_m": round(shadow_length_m, 1),
                    "bearing_to_building": round(bearing_to_building, 1),
                },
            }

    return {
        "in_shadow": False,
        "reason": "No blocking building found",
        "sun": sun,
        "blocking_building": None,
    }


def approximate_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    meters_per_deg_lat = 111_320
    meters_per_deg_lon = 111_320 * abs(cos(radians((lat1 + lat2) / 2)))

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    return ((dlat * meters_per_deg_lat) ** 2 + (dlon * meters_per_deg_lon) ** 2) ** 0.5


def bearing_degrees(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlon = radians(lon2 - lon1)
    lat1r = radians(lat1)
    lat2r = radians(lat2)

    x = sin(dlon) * cos(lat2r)
    y = cos(lat1r) * sin(lat2r) - sin(lat1r) * cos(lat2r) * cos(dlon)

    return (degrees(atan2(x, y)) + 360) % 360


def smallest_angle_diff(a: float, b: float) -> float:
    diff = abs(a - b) % 360
    return min(diff, 360 - diff)