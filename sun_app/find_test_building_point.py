from shapely.geometry import Polygon
from geodata_client import fetch_buildings_osm


def find_inside_point(lat: float, lon: float, radius_m: int = 150):
    buildings = fetch_buildings_osm(lat, lon, radius_m=radius_m)

    print(f"Buildings found: {len(buildings)}")

    for i, b in enumerate(buildings, start=1):
        poly = Polygon(b["polygon"])

        if not poly.is_valid:
            poly = poly.buffer(0)

        if poly.is_empty:
            continue

        inside_point = poly.representative_point()

        print(f"\nBuilding {i}")
        print(f"  id: {b.get('id')}")
        print(f"  height_m: {b.get('height_m')}")
        print(f"  test_lat: {inside_point.y}")
        print(f"  test_lon: {inside_point.x}")

        return inside_point.y, inside_point.x

    print("No usable building polygon found")
    return None


if __name__ == "__main__":
    # Brug et område hvor du ved der findes bygninger
    result = find_inside_point(55.700700, 12.557184, radius_m=150)

    if result:
        lat, lon = result
        print("\nUse these coordinates for testing:")
        print(f"lat = {lat}")
        print(f"lon = {lon}")