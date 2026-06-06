import os
import time

import requests

from dotenv import load_dotenv
load_dotenv()
MY_EMAIL = os.getenv('MY_EMAIL')

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
DEFAULT_OVERPASS_URLS = [
    OVERPASS_URL,
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
]

HEADERS = {
    "User-Agent": f"SunScoreSchoolProject/0.1 {MY_EMAIL}",
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

    response = post_overpass_query(query)

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


def post_overpass_query(query: str) -> requests.Response:
    """
    Sender en Overpass-query med enkel fallback/backoff.

    Public Overpass-instanser kan svare 429, hvis man kalder dem for hurtigt.
    Derfor prøver vi flere endpoints og respekterer Retry-After, når den findes.
    """
    last_error = None
    query_bytes = query.encode("utf-8")

    for endpoint in overpass_urls():
        for attempt in range(2):
            try:
                response = requests.post(
                    endpoint,
                    data=query_bytes,
                    headers=HEADERS,
                    timeout=40,
                )

                if response.status_code in {429, 502, 503, 504}:
                    last_error = requests.HTTPError(
                        f"{response.status_code} from {endpoint}",
                        response=response,
                    )
                    wait_seconds = retry_wait_seconds(response, attempt)
                    time.sleep(wait_seconds)
                    continue

                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                time.sleep(1.5 * (attempt + 1))

    if last_error is not None:
        raise last_error

    raise RuntimeError("No Overpass endpoint configured")


def overpass_urls() -> list[str]:
    raw_value = os.getenv("OVERPASS_URLS")

    if not raw_value:
        return DEFAULT_OVERPASS_URLS

    urls = [
        value.strip()
        for value in raw_value.replace(";", ",").split(",")
        if value.strip()
    ]
    return urls or DEFAULT_OVERPASS_URLS


def retry_wait_seconds(response: requests.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")

    if retry_after:
        try:
            return min(float(retry_after), 30.0)
        except ValueError:
            pass

    return 3.0 * (attempt + 1)


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
