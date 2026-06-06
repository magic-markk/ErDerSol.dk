from pprint import pprint

from weather_client import fetch_weather
from geodata_client import fetch_buildings_osm
from shadow_service import point_in_building_shadow


def evaluate_location(
    lat: float,
    lon: float,
    radius_m: int = 30,
    flatten_dict: bool = True
) -> dict:
    weather = fetch_weather(lat, lon)
    buildings = fetch_buildings_osm(lat, lon, radius_m=radius_m)
    shadow = point_in_building_shadow(lat, lon, buildings)
    if flatten_dict:
        result  = {'lat': lat, 'lon': lon, 'building_count_used': len(buildings)}

        for entry in weather:
            result[entry] = weather[entry]

        for entry in shadow:
            if isinstance(shadow[entry], dict):
                if entry == 'blocking_building':
                    for s in shadow[entry]:
                        result['blocking_building_'+s] = shadow[entry][s]
                for s in shadow[entry]:
                    if s == 'timestamp_utc':
                        continue
                    result[s] = shadow[entry][s]
            else:
                result[entry] = shadow[entry]

    else:
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

if __name__ == "__main__":
    # Eksempel: Nørrebro-ish
    lat = 55.6940791 # 55.679259, 12.568522
    lon = 12.5193054
    r = 30

    result = evaluate_location(lat, lon, r, True)
    pprint(result)