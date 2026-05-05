import sys
from shapely.geometry import Point, Polygon
from geodata_client import fetch_buildings_osm


def debug_inside_building(lat, lon):
    buildings = fetch_buildings_osm(lat, lon, radius_m=80)
    target = Point(lon, lat)

    print(f"Buildings found: {len(buildings)}")

    for b in buildings:
        poly = Polygon(b["polygon"])
        if not poly.is_valid:
            poly = poly.buffer(0)

        if poly.is_empty:
            continue

        if poly.covers(target):
            print("INSIDE BUILDING")
            print("id:", b["id"])
            print("height:", b.get("height_m"))
            return True

    print("Point is not inside any OSM building polygon")
    return False


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Brug: python debug_inside_building.py <lat> <lon>")
        sys.exit(1)

    lat = float(sys.argv[1])
    lon = float(sys.argv[2])

    debug_inside_building(lat, lon)