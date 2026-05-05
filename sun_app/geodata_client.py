import requests

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

HEADERS = {
    "User-Agent": "SunScoreSchoolProject/0.1 your.email@example.com",
    "Accept": "application/json",
}


def fetch_buildings_osm(lat: float, lon: float, radius_m: int = 150) -> list[dict]:
    """
    Henter bygninger omkring et punkt fra OpenStreetMap via Overpass.
    Returnerer en liste af bygninger med polygon og estimeret højde.
    """

    query = f"""
    [out:json][timeout:25];
    (
      way["building"](around:{radius_m},{lat},{lon});
      relation["building"](around:{radius_m},{lat},{lon});
    );
    out geom;
    """

    response = requests.post(
        OVERPASS_URL,
        data=query.encode("utf-8"),
        headers=HEADERS,
        timeout=40
    )
    response.raise_for_status()

    data = response.json()
    buildings = []

    for element in data.get("elements", []):
        geometry = element.get("geometry")
        tags = element.get("tags", {})

        if not geometry or len(geometry) < 3:
            continue

        polygon = [(p["lon"], p["lat"]) for p in geometry]
        height = estimate_building_height(tags)

        buildings.append({
            "id": element.get("id"),
            "source": "osm",
            "polygon": polygon,
            "height_m": height,
            "tags": tags,
        })

    return buildings


def estimate_building_height(tags: dict) -> float:
    """
    Finder bygningens højde i meter.
    Prioritet:
    1) height
    2) building:levels
    3) fallback
    """
    if "height" in tags:
        raw = str(tags["height"]).lower().replace("m", "").strip()
        try:
            return float(raw)
        except ValueError:
            pass

    if "building:levels" in tags:
        try:
            levels = float(tags["building:levels"])
            return levels * 3.0
        except ValueError:
            pass

    return 10.0