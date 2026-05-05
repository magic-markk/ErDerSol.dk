import argparse
import csv
import json
import math
import re
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from pathlib import Path

from bar_scoring import calculate_bar_score
from geodata_client import fetch_buildings_osm
from shadow_service import point_in_building_shadow
from shapely.geometry import Point, Polygon
from weather_client import fetch_weather


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLACES_CSV = PROJECT_ROOT / "outdoor_seating_places.csv"
DEFAULT_SMILEY_XML = PROJECT_ROOT / "Smiley_xml.xml"
DEFAULT_CATEGORIES = ("bar", "pub", "biergarten")

OUTPUT_COLUMNS = [
    "name",
    "category",
    "address",
    "distance_m",
    "lat",
    "lon",
    "total_score",
    "score_max",
    "sun_score",
    "weather_score",
    "reviews_score",
    "smiley_score_points",
    "price_score",
    "distance_score",
    "score_reasons",
    "google_rating",
    "google_user_rating_count",
    "google_price_level",
    "google_maps_uri",
    "smiley_score",
    "smiley_latest_control_date",
    "smiley_name",
    "smiley_address",
    "smiley_postcode",
    "smiley_city",
    "smiley_url",
    "smiley_match_score",
    "smiley_name_similarity",
    "smiley_address_similarity",
    "smiley_match_status",
    "weather_forecast_time",
    "air_temperature",
    "relative_humidity",
    "wind_speed",
    "wind_from_direction",
    "cloud_area_fraction",
    "cloud_area_fraction_low",
    "cloud_area_fraction_medium",
    "cloud_area_fraction_high",
    "uv_index_clear_sky",
    "symbol_code_next_1h",
    "precipitation_amount_next_1h",
    "probability_of_precipitation_next_1h",
    "weather_error",
    "shadow_test_lat",
    "shadow_test_lon",
    "shadow_test_point_source",
    "sun_status",
    "in_shadow",
    "shadow_reason",
    "building_count_used",
    "sun_elevation_deg",
    "sun_azimuth_deg",
    "blocking_building_id",
    "blocking_building_height_m",
    "blocking_building_distance_m",
    "blocking_building_shadow_length_m",
    "shadow_error",
]


def parse_float(value: str) -> float:
    return float(value.strip().replace(",", "."))


def parse_categories(value: str) -> tuple[str, ...]:
    categories = tuple(part.strip().lower() for part in value.split(",") if part.strip())

    if not categories:
        raise argparse.ArgumentTypeError("categories maa ikke vaere tom")

    return categories


def load_places(csv_path: Path, categories: tuple[str, ...]) -> list[dict]:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV findes ikke: {csv_path}")

    places = []

    with csv_path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)

        for row in reader:
            category = (row.get("category") or "").strip().lower()
            outdoor_seating = (row.get("outdoor_seating") or "").strip().lower()

            if category not in categories:
                continue

            if outdoor_seating not in {"yes", "true", "1"}:
                continue

            try:
                lat = float(row["lat"])
                lon = float(row["lon"])
            except (KeyError, TypeError, ValueError):
                continue

            places.append(
                {
                    "name": row.get("name") or row.get("osm_name") or row.get("google_name"),
                    "category": category,
                    "address": row.get("address") or row.get("osm_address") or row.get("google_address"),
                    "lat": lat,
                    "lon": lon,
                    "google_rating": row.get("google_rating"),
                    "google_user_rating_count": row.get("google_user_rating_count"),
                    "google_price_level": row.get("google_price_level"),
                    "google_maps_uri": row.get("google_maps_uri"),
                    "raw": row,
                }
            )

    return places


def find_nearby_places(
    user_lat: float,
    user_lon: float,
    places: list[dict],
    radius_m: float,
    limit: int | None,
) -> list[dict]:
    nearby = []

    for place in places:
        distance_m = haversine_m(user_lat, user_lon, place["lat"], place["lon"])

        if distance_m <= radius_m:
            result = dict(place)
            result["distance_m"] = round(distance_m, 1)
            nearby.append(result)

    nearby.sort(key=lambda place: place["distance_m"])

    if limit is None:
        return nearby

    return nearby[:limit]


def add_smiley_to_places(
    places: list[dict],
    smiley_xml_path: Path,
    min_match_score: float,
) -> list[dict]:
    if not smiley_xml_path.exists():
        raise FileNotFoundError(f"Smiley XML findes ikke: {smiley_xml_path}")

    smiley_index = load_smiley_index(smiley_xml_path)
    enriched = []

    for place in places:
        result = dict(place)
        match = find_smiley_match(place, smiley_index, min_match_score)
        result["smiley"] = match
        enriched.append(result)

    return enriched


def load_smiley_index(xml_path: Path) -> dict:
    rows = []
    by_postcode = {}
    by_address_key = {}

    for _, element in ET.iterparse(xml_path, events=("end",)):
        if element.tag != "row":
            continue

        row = {
            "id": xml_text(element, "navnelbnr"),
            "cvr": xml_text(element, "cvrnr"),
            "p_number": xml_text(element, "pnr"),
            "name": xml_text(element, "navn1"),
            "address": xml_text(element, "adresse1"),
            "postcode": xml_text(element, "postnr"),
            "city": xml_text(element, "By"),
            "latest_control": xml_text(element, "seneste_kontrol"),
            "latest_control_date": xml_text(element, "seneste_kontrol_dato"),
            "url": xml_text(element, "URL"),
            "branch": xml_text(element, "branche"),
        }
        row["full_address"] = format_smiley_address(row)
        row["address_key"] = address_key(row["address"])
        rows.append(row)
        by_postcode.setdefault(row["postcode"], []).append(row)

        if row["address_key"]:
            by_address_key.setdefault(row["address_key"], []).append(row)

        element.clear()

    return {
        "rows": rows,
        "by_postcode": by_postcode,
        "by_address_key": by_address_key,
    }


def find_smiley_match(
    place: dict,
    smiley_index: dict,
    min_match_score: float,
) -> dict:
    place_postcode = extract_postcode(place.get("address"))
    candidates = smiley_candidates_for_place(place, smiley_index)

    best = None
    best_score = -1.0
    best_name_similarity = 0.0
    best_address_similarity = 0.0

    for candidate in candidates:
        name_similarity = max_name_similarity(place, candidate)
        address_similarity = max_address_similarity(place, candidate)
        same_postcode_bonus = 0.08 if place_postcode and place_postcode == candidate["postcode"] else 0.0
        score = min(1.0, (name_similarity * 0.45) + (address_similarity * 0.55) + same_postcode_bonus)

        if score > best_score:
            best = candidate
            best_score = score
            best_name_similarity = name_similarity
            best_address_similarity = address_similarity

    if best is None:
        return {
            "match_status": "not_found",
        }

    if is_low_confidence_smiley_match(
        best_score,
        best_name_similarity,
        best_address_similarity,
        min_match_score,
    ):
        return {
            "match_status": "low_confidence",
            "match_score": round(best_score, 3),
            "name_similarity": round(best_name_similarity, 3),
            "address_similarity": round(best_address_similarity, 3),
            "candidate_name": best["name"],
            "candidate_address": best["full_address"],
            "candidate_url": best["url"],
        }

    return {
        "match_status": "matched",
        "match_score": round(best_score, 3),
        "name_similarity": round(best_name_similarity, 3),
        "address_similarity": round(best_address_similarity, 3),
        "score": best["latest_control"],
        "latest_control_date": best["latest_control_date"],
        "name": best["name"],
        "address": best["address"],
        "postcode": best["postcode"],
        "city": best["city"],
        "url": best["url"],
        "cvr": best["cvr"],
        "p_number": best["p_number"],
    }


def smiley_candidates_for_place(place: dict, smiley_index: dict) -> list[dict]:
    candidates = []
    seen_ids = set()

    def add_rows(rows: list[dict]) -> None:
        for row in rows:
            row_id = row.get("id")

            if row_id in seen_ids:
                continue

            seen_ids.add(row_id)
            candidates.append(row)

    for key in address_keys_for_place(place):
        add_rows(smiley_index["by_address_key"].get(key, []))

    place_postcode = extract_postcode(place.get("address"))
    if place_postcode:
        add_rows(smiley_index["by_postcode"].get(place_postcode, []))

    if not candidates:
        return smiley_index["rows"]

    return candidates


def is_low_confidence_smiley_match(
    match_score: float,
    name_similarity: float,
    address_similarity: float,
    min_match_score: float,
) -> bool:
    if match_score < min_match_score:
        return True

    # Strong address matches can otherwise hit the wrong business in hotels,
    # food halls, stations, etc. A weak name needs a very strong combined score.
    if name_similarity < 0.55 and match_score < 0.88:
        return True

    if address_similarity < 0.45 and name_similarity < 0.85:
        return True

    return False


def max_name_similarity(place: dict, smiley_row: dict) -> float:
    names = [
        place.get("name"),
        place.get("raw", {}).get("google_name"),
        place.get("raw", {}).get("osm_name"),
    ]
    similarities = [
        string_similarity(name, smiley_row["name"])
        for name in names
        if name
    ]
    return max(similarities, default=0.0)


def max_address_similarity(place: dict, smiley_row: dict) -> float:
    addresses = [
        place.get("address"),
        place.get("raw", {}).get("google_address"),
        place.get("raw", {}).get("osm_address"),
    ]
    smiley_addresses = [
        smiley_row["full_address"],
        " ".join(part for part in [smiley_row["address"], smiley_row["postcode"]] if part),
        smiley_row["address"],
    ]

    similarities = [
        string_similarity(address, smiley_address)
        for address in addresses
        for smiley_address in smiley_addresses
        if address and smiley_address
    ]
    return max(similarities, default=0.0)


def string_similarity(left: str, right: str) -> float:
    left_normalized = normalize_match_text(left)
    right_normalized = normalize_match_text(right)

    if not left_normalized or not right_normalized:
        return 0.0

    return SequenceMatcher(None, left_normalized, right_normalized).ratio()


def normalize_match_text(value: str) -> str:
    value = value.lower()
    value = value.replace("&", " og ")
    value = re.sub(r"[^0-9a-zæøå]+", " ", value)
    value = re.sub(r"\b(st|sal|tv|th|kl|kld|mf)\b", " ", value)
    return " ".join(value.split())


def extract_postcode(value: str | None) -> str | None:
    if not value:
        return None

    match = re.search(r"\b\d{4}\b", value)
    if not match:
        return None

    return match.group(0)


def address_keys_for_place(place: dict) -> list[str]:
    addresses = [
        place.get("address"),
        place.get("raw", {}).get("google_address"),
        place.get("raw", {}).get("osm_address"),
    ]
    keys = []

    for value in addresses:
        key = address_key(value)

        if key and key not in keys:
            keys.append(key)

    return keys


def address_key(value: str | None) -> str | None:
    if not value:
        return None

    address_part = value.split(",")[0]
    normalized = normalize_match_text(address_part)
    house_number_match = re.search(r"\b\d+[a-z]?\b", normalized)

    if not house_number_match:
        return normalized or None

    street = normalized[: house_number_match.start()].strip()
    house_number = house_number_match.group(0)

    if not street:
        return house_number

    return f"{street} {house_number}"


def xml_text(element: ET.Element, tag: str) -> str:
    child = element.find(tag)

    if child is None or child.text is None:
        return ""

    return " ".join(child.text.split())


def format_smiley_address(row: dict) -> str:
    return ", ".join(
        part
        for part in [
            row["address"],
            " ".join(part for part in [row["postcode"], row["city"]] if part),
        ]
        if part
    )


def add_weather_to_places(places: list[dict]) -> list[dict]:
    enriched = []

    for place in places:
        result = dict(place)

        try:
            weather = fetch_weather(place["lat"], place["lon"])
            result["weather"] = weather
            result["weather_error"] = None
        except Exception as exc:
            result["weather"] = {}
            result["weather_error"] = str(exc)

        enriched.append(result)

    return enriched


def add_shadow_to_places(
    places: list[dict],
    radius_m: int,
    point_mode: str,
) -> list[dict]:
    enriched = []

    for place in places:
        result = dict(place)

        try:
            buildings = fetch_buildings_osm(place["lat"], place["lon"], radius_m=radius_m)
            shadow_lat, shadow_lon, point_source = shadow_test_point(
                place["lat"],
                place["lon"],
                buildings,
                point_mode,
            )
            shadow = point_in_building_shadow(shadow_lat, shadow_lon, buildings)
            result["shadow"] = shadow
            result["shadow_test_lat"] = shadow_lat
            result["shadow_test_lon"] = shadow_lon
            result["shadow_test_point_source"] = point_source
            result["building_count_used"] = len(buildings)
            result["shadow_error"] = None
        except Exception as exc:
            result["shadow"] = {}
            result["shadow_test_lat"] = None
            result["shadow_test_lon"] = None
            result["shadow_test_point_source"] = None
            result["building_count_used"] = None
            result["shadow_error"] = str(exc)

        enriched.append(result)

    return enriched


def add_scores_to_places(places: list[dict], search_radius_m: float) -> list[dict]:
    enriched = []

    for place in places:
        result = dict(place)
        result["score"] = calculate_bar_score(result, search_radius_m)
        enriched.append(result)

    return enriched


def shadow_test_point(
    lat: float,
    lon: float,
    buildings: list[dict],
    point_mode: str,
) -> tuple[float, float, str]:
    if point_mode == "place":
        return lat, lon, "place_coordinate"

    target = Point(lon, lat)

    for building in buildings:
        polygon_coords = building.get("polygon", [])

        if len(polygon_coords) < 3:
            continue

        poly = Polygon(polygon_coords)

        if not poly.is_valid:
            poly = poly.buffer(0)

        if poly.is_empty or not poly.covers(target):
            continue

        outdoor_point = point_just_outside_polygon(poly, lat, lon)

        if outdoor_point is not None:
            outdoor_lat, outdoor_lon = outdoor_point
            return outdoor_lat, outdoor_lon, "nearest_building_edge"

    return lat, lon, "place_coordinate"


def point_just_outside_polygon(poly: Polygon, lat: float, lon: float) -> tuple[float, float] | None:
    target = Point(lon, lat)
    nearest = poly.exterior.interpolate(poly.exterior.project(target))
    centroid = poly.centroid

    meters_per_deg_lat = 111_320.0
    meters_per_deg_lon = 111_320.0 * abs(math.cos(math.radians(lat)))
    dx_m = (nearest.x - centroid.x) * meters_per_deg_lon
    dy_m = (nearest.y - centroid.y) * meters_per_deg_lat
    vector_length_m = math.hypot(dx_m, dy_m)

    if vector_length_m == 0:
        return None

    unit_x = dx_m / vector_length_m
    unit_y = dy_m / vector_length_m

    for offset_m in (2.0, 5.0, 10.0, 15.0, 25.0):
        candidate_lon = nearest.x + (unit_x * offset_m / meters_per_deg_lon)
        candidate_lat = nearest.y + (unit_y * offset_m / meters_per_deg_lat)

        if not poly.covers(Point(candidate_lon, candidate_lat)):
            return candidate_lat, candidate_lon

    return None


def flatten_place(place: dict) -> dict:
    weather = place.get("weather") or {}
    shadow = place.get("shadow") or {}
    smiley = place.get("smiley") or {}
    score = place.get("score") or {}
    sun = shadow.get("sun") or {}
    blocking_building = shadow.get("blocking_building") or {}
    in_shadow = shadow.get("in_shadow")

    return {
        "name": place.get("name"),
        "category": place.get("category"),
        "address": place.get("address"),
        "distance_m": place.get("distance_m"),
        "lat": place.get("lat"),
        "lon": place.get("lon"),
        "total_score": score.get("total_score"),
        "score_max": score.get("score_max"),
        "sun_score": score.get("sun_score"),
        "weather_score": score.get("weather_score"),
        "reviews_score": score.get("reviews_score"),
        "smiley_score_points": score.get("smiley_score_points"),
        "price_score": score.get("price_score"),
        "distance_score": score.get("distance_score"),
        "score_reasons": score.get("score_reasons"),
        "google_rating": place.get("google_rating"),
        "google_user_rating_count": place.get("google_user_rating_count"),
        "google_price_level": place.get("google_price_level"),
        "google_maps_uri": place.get("google_maps_uri"),
        "smiley_score": smiley.get("score"),
        "smiley_latest_control_date": smiley.get("latest_control_date"),
        "smiley_name": smiley.get("name") or smiley.get("candidate_name"),
        "smiley_address": smiley.get("address") or smiley.get("candidate_address"),
        "smiley_postcode": smiley.get("postcode"),
        "smiley_city": smiley.get("city"),
        "smiley_url": smiley.get("url") or smiley.get("candidate_url"),
        "smiley_match_score": smiley.get("match_score"),
        "smiley_name_similarity": smiley.get("name_similarity"),
        "smiley_address_similarity": smiley.get("address_similarity"),
        "smiley_match_status": smiley.get("match_status"),
        "weather_forecast_time": weather.get("forecast_time"),
        "air_temperature": weather.get("air_temperature"),
        "relative_humidity": weather.get("relative_humidity"),
        "wind_speed": weather.get("wind_speed"),
        "wind_from_direction": weather.get("wind_from_direction"),
        "cloud_area_fraction": weather.get("cloud_area_fraction"),
        "cloud_area_fraction_low": weather.get("cloud_area_fraction_low"),
        "cloud_area_fraction_medium": weather.get("cloud_area_fraction_medium"),
        "cloud_area_fraction_high": weather.get("cloud_area_fraction_high"),
        "uv_index_clear_sky": weather.get("uv_index_clear_sky"),
        "symbol_code_next_1h": weather.get("symbol_code_next_1h"),
        "precipitation_amount_next_1h": weather.get("precipitation_amount_next_1h"),
        "probability_of_precipitation_next_1h": weather.get("probability_of_precipitation_next_1h"),
        "weather_error": place.get("weather_error"),
        "shadow_test_lat": place.get("shadow_test_lat"),
        "shadow_test_lon": place.get("shadow_test_lon"),
        "shadow_test_point_source": place.get("shadow_test_point_source"),
        "sun_status": sun_status_from_shadow(in_shadow),
        "in_shadow": in_shadow,
        "shadow_reason": shadow.get("reason"),
        "building_count_used": place.get("building_count_used"),
        "sun_elevation_deg": sun.get("sun_elevation_deg"),
        "sun_azimuth_deg": sun.get("sun_azimuth_deg"),
        "blocking_building_id": blocking_building.get("id"),
        "blocking_building_height_m": blocking_building.get("height_m"),
        "blocking_building_distance_m": blocking_building.get("distance_m"),
        "blocking_building_shadow_length_m": blocking_building.get("shadow_length_m"),
        "shadow_error": place.get("shadow_error"),
    }


def print_results(places: list[dict]) -> None:
    if not places:
        print("Ingen barer fundet i den valgte radius.")
        return

    for index, place in enumerate(places, start=1):
        weather = place.get("weather") or {}
        shadow = place.get("shadow") or {}
        smiley = place.get("smiley") or {}
        score = place.get("score") or {}
        sun = shadow.get("sun") or {}

        print(f"\n{index}. {place.get('name')}")
        if score:
            print(
                f"   Score: {score.get('total_score')}/{score.get('score_max')} "
                f"(sun {score.get('sun_score')}, weather {score.get('weather_score')}, "
                f"reviews {score.get('reviews_score')}, smiley {score.get('smiley_score_points')}, "
                f"price {score.get('price_score')}, distance {score.get('distance_score')})"
            )
            print(f"   Score reasons: {score.get('score_reasons')}")
        print(f"   Category: {place.get('category')}")
        print(f"   Distance: {place.get('distance_m')} m")
        print(f"   Address: {place.get('address') or '-'}")
        print(f"   Coordinates: {place.get('lat')}, {place.get('lon')}")
        if place.get("shadow_test_point_source"):
            print(
                "   Shadow test point: "
                f"{place.get('shadow_test_lat')}, {place.get('shadow_test_lon')} "
                f"({place.get('shadow_test_point_source')})"
            )
        print(
            "   Google: "
            f"rating={place.get('google_rating') or '-'} "
            f"reviews={place.get('google_user_rating_count') or '-'} "
            f"price={place.get('google_price_level') or '-'}"
        )
        print(
            "   Smiley: "
            f"score={smiley.get('score') or '-'} "
            f"date={smiley.get('latest_control_date') or '-'} "
            f"match={smiley.get('match_status') or '-'} "
            f"confidence={smiley.get('match_score') or '-'}"
        )

        if place.get("weather_error"):
            print(f"   Weather error: {place['weather_error']}")
            continue

        print(
            "   Weather: "
            f"{weather.get('air_temperature')} C, "
            f"wind {weather.get('wind_speed')} m/s, "
            f"clouds {weather.get('cloud_area_fraction')}%, "
            f"rain next 1h {weather.get('precipitation_amount_next_1h')} mm, "
            f"UV clear sky {weather.get('uv_index_clear_sky')}"
        )

        if place.get("shadow_error"):
            print(f"   Shadow error: {place['shadow_error']}")
            continue

        if shadow:
            print(
                "   Sun/shadow: "
                f"{sun_status_from_shadow(shadow.get('in_shadow'))}, "
                f"reason={shadow.get('reason')}, "
                f"sun elevation={round(sun.get('sun_elevation_deg'), 1) if sun.get('sun_elevation_deg') is not None else '-'} deg, "
                f"buildings checked={place.get('building_count_used')}"
            )


def write_csv(path: Path, places: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(flatten_place(place) for place in places)


def write_json(path: Path, places: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [flatten_place(place) for place in places]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def sun_status_from_shadow(in_shadow: bool | None) -> str | None:
    if in_shadow is True:
        return "shadow"
    if in_shadow is False:
        return "direct_sun"
    return None


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_m = 6_371_000.0
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return earth_radius_m * c


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find naermeste barer med outdoor seating og hent vejrdata for dem."
    )
    parser.add_argument("--lat", type=parse_float, help="Din latitude, fx 55.6761")
    parser.add_argument("--lon", type=parse_float, help="Din longitude, fx 12.5683")
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_PLACES_CSV,
        help=f"CSV med outdoor seating-steder. Default: {DEFAULT_PLACES_CSV}",
    )
    parser.add_argument(
        "--radius-m",
        type=float,
        default=1500,
        help="Soege-radius i meter.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maks antal barer der vises efter sortering.",
    )
    parser.add_argument(
        "--candidate-limit",
        type=int,
        help=(
            "Antal naermeste barer der scores foer top-listen vaelges. "
            "Brug fx 50 for at finde bedste sted blandt flere kandidater."
        ),
    )
    parser.add_argument(
        "--categories",
        type=parse_categories,
        default=DEFAULT_CATEGORIES,
        help="Kategorier fra CSV, fx bar,pub,biergarten eller bar,pub,restaurant.",
    )
    parser.add_argument(
        "--smiley-xml",
        type=Path,
        default=DEFAULT_SMILEY_XML,
        help=f"FindSmiley XML-fil. Default: {DEFAULT_SMILEY_XML}",
    )
    parser.add_argument(
        "--skip-smiley",
        action="store_true",
        help="Spring smiley-match over.",
    )
    parser.add_argument(
        "--smiley-min-match-score",
        type=float,
        default=0.62,
        help="Minimum match-score for at acceptere et smiley-match.",
    )
    parser.add_argument(
        "--shadow-radius-m",
        type=int,
        default=150,
        help="Radius i meter til bygninger der bruges i skyggeberegningen.",
    )
    parser.add_argument(
        "--skip-shadow",
        action="store_true",
        help="Spring skyggeberegningen over. Godt til hurtig test.",
    )
    parser.add_argument(
        "--shadow-point-mode",
        choices=("outdoor", "place"),
        default="outdoor",
        help=(
            "outdoor flytter testpunktet ud til naermeste bygningskant, hvis CSV-punktet "
            "ligger inde i en bygning. place bruger CSV-koordinatet direkte."
        ),
    )
    parser.add_argument(
        "--sort",
        choices=("score", "distance"),
        default="score",
        help="Sorter resultater efter samlet score eller afstand.",
    )
    parser.add_argument("--output", type=Path, help="Valgfri CSV-outputfil.")
    parser.add_argument("--json-output", type=Path, help="Valgfri JSON-outputfil.")
    return parser.parse_args()


def prompt_for_coordinate(label: str) -> float:
    while True:
        raw_value = input(f"{label}: ")

        try:
            return parse_float(raw_value)
        except ValueError:
            print("Skriv koordinatet som et tal, fx 55.6761")


def main() -> None:
    args = parse_args()
    user_lat = args.lat if args.lat is not None else prompt_for_coordinate("Latitude")
    user_lon = args.lon if args.lon is not None else prompt_for_coordinate("Longitude")

    places = load_places(args.csv, args.categories)
    candidate_limit = args.candidate_limit or args.limit
    nearby = find_nearby_places(user_lat, user_lon, places, args.radius_m, candidate_limit)
    enriched = nearby

    if not args.skip_smiley:
        enriched = add_smiley_to_places(
            enriched,
            smiley_xml_path=args.smiley_xml,
            min_match_score=args.smiley_min_match_score,
        )

    enriched = add_weather_to_places(enriched)

    if not args.skip_shadow:
        enriched = add_shadow_to_places(
            enriched,
            radius_m=args.shadow_radius_m,
            point_mode=args.shadow_point_mode,
        )

    enriched = add_scores_to_places(enriched, search_radius_m=args.radius_m)

    if args.sort == "score":
        enriched.sort(
            key=lambda place: place.get("score", {}).get("total_score") or -1,
            reverse=True,
        )
    else:
        enriched.sort(key=lambda place: place.get("distance_m") or float("inf"))

    enriched = enriched[: args.limit]

    print(
        f"Fandt {len(enriched)} barer inden for {int(args.radius_m)} m "
        f"ud af {len(places)} relevante CSV-steder."
    )
    print_results(enriched)

    if args.output:
        write_csv(args.output, enriched)
        print(f"\nSkrev CSV: {args.output}")

    if args.json_output:
        write_json(args.json_output, enriched)
        print(f"Skrev JSON: {args.json_output}")


if __name__ == "__main__":
    main()
