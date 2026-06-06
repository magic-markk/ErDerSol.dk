from pprint import pprint

from weather_client import fetch_weather
from geodata_client import fetch_buildings_osm
from shadow_service import point_in_building_shadow


def evaluate_location(lat: float, lon: float) -> dict:
    weather = fetch_weather(lat, lon)
    buildings = fetch_buildings_osm(lat, lon, radius_m=150)
    shadow = point_in_building_shadow(lat, lon, buildings)

    result = {
        "location": {
            "lat": lat,
            "lon": lon,
        },
        "weather": weather,
        "shadow": shadow,
        "building_count_used": len(buildings),
    }

    return result

