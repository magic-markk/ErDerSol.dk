import argparse
import csv
import json
import math
import os
import re
import time
from difflib import SequenceMatcher
from pathlib import Path

import requests


OVERPASS_URL = "https://overpass-api.de/api/interpreter"
GOOGLE_NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"

# Approx. Copenhagen municipality + close inner-city surroundings.
DEFAULT_COPENHAGEN_BBOX = (55.6150, 12.4500, 55.7350, 12.6750)

DEFAULT_OSM_AMENITY_VALUES = ("restaurant", "bar", "pub", "cafe", "biergarten")
DEFAULT_GOOGLE_INCLUDED_TYPES = ("restaurant", "bar", "cafe")

OUTDOOR_SEATING_YES_VALUES = {
    "yes",
    "true",
    "1",
    "terrace",
    "patio",
    "sidewalk",
    "street",
    "garden",
    "balcony",
    "veranda",
    "roof",
    "pedestrian_zone",
    "parklet",
}

OUTDOOR_SEATING_NO_VALUES = {"no", "false", "0", "none"}

GOOGLE_FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.primaryType",
        "places.types",
        "places.priceLevel",
        "places.priceRange",
        "places.rating",
        "places.userRatingCount",
        "places.outdoorSeating",
        "places.googleMapsUri",
    ]
)

CSV_COLUMNS = [
    "name",
    "address",
    "lat",
    "lon",
    "coordinate_source",
    "outdoor_seating",
    "outdoor_seating_source",
    "category",
    "osm_type",
    "osm_id",
    "osm_name",
    "osm_address",
    "osm_outdoor_seating_raw",
    "google_place_id",
    "google_name",
    "google_address",
    "google_outdoor_seating",
    "google_price_level",
    "google_price_range",
    "google_rating",
    "google_user_rating_count",
    "google_maps_uri",
    "google_match_distance_m",
    "google_match_name_similarity",
]


def parse_bbox(value: str) -> tuple[float, float, float, float]:
    if value.lower() == "copenhagen":
        return DEFAULT_COPENHAGEN_BBOX

    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            "bbox skal vaere enten 'copenhagen' eller 'south,west,north,east'"
        )

    try:
        south, west, north, east = [float(part) for part in parts]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("bbox skal kun indeholde tal") from exc

    if south >= north or west >= east:
        raise argparse.ArgumentTypeError("bbox skal vaere south,west,north,east")

    return south, west, north, east


def bbox_to_overpass(bbox: tuple[float, float, float, float]) -> str:
    south, west, north, east = bbox
    return f"{south},{west},{north},{east}"


def fetch_osm_food_places(
    bbox: tuple[float, float, float, float],
    amenity_values: tuple[str, ...],
    timeout_s: int = 120,
) -> list[dict]:
    amenity_regex = "^(" + "|".join(amenity_values) + ")$"
    bbox_text = bbox_to_overpass(bbox)

    query = f"""
    [out:json][timeout:{timeout_s}];
    (
      node["amenity"~"{amenity_regex}"]({bbox_text});
      way["amenity"~"{amenity_regex}"]({bbox_text});
      relation["amenity"~"{amenity_regex}"]({bbox_text});
      node["bar"="yes"]({bbox_text});
      way["bar"="yes"]({bbox_text});
      relation["bar"="yes"]({bbox_text});
    );
    out center;
    """

    response = requests.post(
        OVERPASS_URL,
        data=query.encode("utf-8"),
        headers={
            "User-Agent": "SunScoreSchoolProject/0.1 your.email@example.com",
            "Accept": "application/json",
        },
        timeout=timeout_s + 20,
    )
    response.raise_for_status()

    places = []
    seen = set()

    for element in response.json().get("elements", []):
        osm_type = element.get("type")
        osm_id = element.get("id")
        unique_key = (osm_type, osm_id)

        if unique_key in seen:
            continue
        seen.add(unique_key)

        lat = element.get("lat")
        lon = element.get("lon")
        center = element.get("center", {})

        if lat is None:
            lat = center.get("lat")
        if lon is None:
            lon = center.get("lon")
        if lat is None or lon is None:
            continue

        tags = element.get("tags", {})
        name = tags.get("name") or tags.get("brand")
        amenity = tags.get("amenity")
        category = amenity or ("bar" if tags.get("bar") == "yes" else None)

        places.append(
            {
                "osm_type": osm_type,
                "osm_id": osm_id,
                "name": name,
                "lat": float(lat),
                "lon": float(lon),
                "category": category,
                "address": format_osm_address(tags),
                "tags": tags,
                "osm_outdoor_seating": osm_outdoor_seating_value(tags, category),
            }
        )

    return places


def format_osm_address(tags: dict) -> str | None:
    street = tags.get("addr:street")
    house_number = tags.get("addr:housenumber")
    postcode = tags.get("addr:postcode")
    city = tags.get("addr:city")

    street_line = " ".join(part for part in [street, house_number] if part)
    city_line = " ".join(part for part in [postcode, city] if part)

    if street_line and city_line:
        return f"{street_line}, {city_line}"
    if street_line:
        return street_line
    if city_line:
        return city_line
    return tags.get("addr:full")


def osm_outdoor_seating_value(tags: dict, category: str | None) -> bool | None:
    raw_value = tags.get("outdoor_seating")

    if category == "biergarten":
        return True

    if raw_value is None:
        return None

    normalized = str(raw_value).strip().lower()
    if normalized in OUTDOOR_SEATING_YES_VALUES:
        return True
    if normalized in OUTDOOR_SEATING_NO_VALUES:
        return False

    return None


def google_nearby_search(
    api_key: str,
    lat: float,
    lon: float,
    radius_m: int,
    included_types: tuple[str, ...],
    language_code: str = "da",
    region_code: str = "DK",
) -> list[dict]:
    payload = {
        "includedTypes": list(included_types),
        "maxResultCount": 20,
        "rankPreference": "DISTANCE",
        "languageCode": language_code,
        "regionCode": region_code,
        "locationRestriction": {
            "circle": {
                "center": {
                    "latitude": lat,
                    "longitude": lon,
                },
                "radius": float(radius_m),
            }
        },
    }

    response = requests.post(
        GOOGLE_NEARBY_URL,
        json=payload,
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": GOOGLE_FIELD_MASK,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json().get("places", [])


def find_best_google_match(
    osm_place: dict,
    google_places: list[dict],
    max_distance_m: int,
    min_name_similarity: float,
) -> dict | None:
    best_place = None
    best_score = -10_000.0
    osm_name = osm_place.get("name")

    for google_place in google_places:
        google_location = google_place.get("location") or {}
        google_lat = google_location.get("latitude")
        google_lon = google_location.get("longitude")

        if google_lat is None or google_lon is None:
            continue

        distance_m = haversine_m(osm_place["lat"], osm_place["lon"], google_lat, google_lon)
        if distance_m > max_distance_m:
            continue

        google_name = google_display_name(google_place)
        similarity = name_similarity(osm_name, google_name)

        if osm_name and similarity < min_name_similarity and distance_m > 25:
            continue

        score = (similarity * 100.0) - (distance_m * 0.7)

        if score > best_score:
            best_score = score
            best_place = dict(google_place)
            best_place["_match_distance_m"] = round(distance_m, 1)
            best_place["_match_name_similarity"] = round(similarity, 3)

    return best_place


def build_record(osm_place: dict, google_place: dict | None) -> dict | None:
    osm_outdoor = osm_place.get("osm_outdoor_seating")
    google_outdoor = None

    if google_place is not None and "outdoorSeating" in google_place:
        google_outdoor = bool(google_place.get("outdoorSeating"))

    if not osm_outdoor and not google_outdoor:
        return None

    if osm_outdoor and google_outdoor:
        outdoor_source = "osm+google"
    elif google_outdoor:
        outdoor_source = "google"
    else:
        outdoor_source = "osm"

    google_name = google_display_name(google_place)
    google_address = google_place.get("formattedAddress") if google_place else None
    osm_address = osm_place.get("address")

    record = {
        "name": google_name or osm_place.get("name"),
        "address": google_address or osm_address,
        "lat": osm_place["lat"],
        "lon": osm_place["lon"],
        "coordinate_source": "osm",
        "outdoor_seating": "yes",
        "outdoor_seating_source": outdoor_source,
        "category": osm_place.get("category"),
        "osm_type": osm_place.get("osm_type"),
        "osm_id": osm_place.get("osm_id"),
        "osm_name": osm_place.get("name"),
        "osm_address": osm_address,
        "osm_outdoor_seating_raw": osm_place.get("tags", {}).get("outdoor_seating"),
        "google_place_id": google_place.get("id") if google_place else None,
        "google_name": google_name,
        "google_address": google_address,
        "google_outdoor_seating": google_outdoor,
        "google_price_level": google_place.get("priceLevel") if google_place else None,
        "google_price_range": json.dumps(
            google_place.get("priceRange"),
            ensure_ascii=False,
        )
        if google_place and google_place.get("priceRange") is not None
        else None,
        "google_rating": google_place.get("rating") if google_place else None,
        "google_user_rating_count": google_place.get("userRatingCount") if google_place else None,
        "google_maps_uri": google_place.get("googleMapsUri") if google_place else None,
        "google_match_distance_m": google_place.get("_match_distance_m")
        if google_place
        else None,
        "google_match_name_similarity": google_place.get("_match_name_similarity")
        if google_place
        else None,
    }

    return record


def discover_google_outdoor_places(
    api_key: str,
    bbox: tuple[float, float, float, float],
    radius_m: int,
    included_types: tuple[str, ...],
    max_grid_points: int | None,
    sleep_s: float,
) -> list[dict]:
    places_by_id = {}

    for index, (lat, lon) in enumerate(grid_points_for_bbox(bbox, radius_m), start=1):
        if max_grid_points is not None and index > max_grid_points:
            break

        google_places = google_nearby_search(
            api_key,
            lat,
            lon,
            radius_m=radius_m,
            included_types=included_types,
        )

        for google_place in google_places:
            if google_place.get("outdoorSeating") is not True:
                continue

            place_id = google_place.get("id")
            if place_id:
                places_by_id[place_id] = google_place

        if sleep_s > 0:
            time.sleep(sleep_s)

    return list(places_by_id.values())


def match_google_discovery_to_osm(
    google_place: dict,
    osm_places: list[dict],
    max_distance_m: int,
    min_name_similarity: float,
) -> dict | None:
    google_location = google_place.get("location") or {}
    google_lat = google_location.get("latitude")
    google_lon = google_location.get("longitude")

    if google_lat is None or google_lon is None:
        return None

    best_osm = None
    best_score = -10_000.0
    google_name = google_display_name(google_place)

    for osm_place in osm_places:
        distance_m = haversine_m(osm_place["lat"], osm_place["lon"], google_lat, google_lon)
        if distance_m > max_distance_m:
            continue

        similarity = name_similarity(osm_place.get("name"), google_name)
        if osm_place.get("name") and google_name and similarity < min_name_similarity and distance_m > 25:
            continue

        score = (similarity * 100.0) - (distance_m * 0.7)
        if score > best_score:
            best_score = score
            best_osm = osm_place
            google_place["_match_distance_m"] = round(distance_m, 1)
            google_place["_match_name_similarity"] = round(similarity, 3)

    return best_osm


def grid_points_for_bbox(
    bbox: tuple[float, float, float, float],
    radius_m: int,
) -> list[tuple[float, float]]:
    south, west, north, east = bbox
    center_lat = (south + north) / 2.0

    step_m = max(radius_m * 1.4, 250)
    lat_step = step_m / 111_320.0
    lon_step = step_m / (111_320.0 * math.cos(math.radians(center_lat)))

    points = []
    lat = south

    while lat <= north:
        lon = west
        while lon <= east:
            points.append((round(lat, 6), round(lon, 6)))
            lon += lon_step
        lat += lat_step

    return points


def google_display_name(google_place: dict | None) -> str | None:
    if not google_place:
        return None

    display_name = google_place.get("displayName")
    if isinstance(display_name, dict):
        return display_name.get("text")

    return None


def normalize_name(value: str | None) -> str:
    if not value:
        return ""

    value = value.lower()
    value = value.replace("&", "and")
    value = re.sub(r"[^a-z0-9æøå ]+", " ", value)
    return " ".join(value.split())


def name_similarity(left: str | None, right: str | None) -> float:
    left_normalized = normalize_name(left)
    right_normalized = normalize_name(right)

    if not left_normalized or not right_normalized:
        return 0.0

    return SequenceMatcher(None, left_normalized, right_normalized).ratio()


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


def write_csv(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(records)


def write_json(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")


def resolve_google_api_key(args: argparse.Namespace) -> str | None:
    return (
        args.google_api_key
        or os.getenv("GOOGLE_MAPS_API_KEY")
        or os.getenv("GOOGLE_PLACES_API_KEY")
    )


def parse_csv_values(value: str) -> tuple[str, ...]:
    values = tuple(part.strip() for part in value.split(",") if part.strip())
    if not values:
        raise argparse.ArgumentTypeError("Listen maa ikke vaere tom")
    return values


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Find restauranter/barer med outdoor seating fra OSM og berig med "
            "Google Places-data."
        )
    )
    parser.add_argument(
        "--bbox",
        type=parse_bbox,
        default=DEFAULT_COPENHAGEN_BBOX,
        help="Omraade: 'copenhagen' eller 'south,west,north,east'.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outdoor_seating_places.csv"),
        help="CSV-fil der skal skrives.",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        help="Valgfri JSON-fil der ogsaa skal skrives.",
    )
    parser.add_argument(
        "--google-api-key",
        help="Google Maps/Places API key. Kan ogsaa saettes som GOOGLE_MAPS_API_KEY.",
    )
    parser.add_argument(
        "--skip-google",
        action="store_true",
        help="Brug kun OSM-data. God til gratis test.",
    )
    parser.add_argument(
        "--osm-amenities",
        type=parse_csv_values,
        default=DEFAULT_OSM_AMENITY_VALUES,
        help=(
            "OSM amenity-vaerdier, kommasepareret. Default: "
            + ",".join(DEFAULT_OSM_AMENITY_VALUES)
        ),
    )
    parser.add_argument(
        "--google-types",
        type=parse_csv_values,
        default=DEFAULT_GOOGLE_INCLUDED_TYPES,
        help=(
            "Google Places includedTypes, kommasepareret. Default: "
            + ",".join(DEFAULT_GOOGLE_INCLUDED_TYPES)
        ),
    )
    parser.add_argument(
        "--only-osm-outdoor",
        action="store_true",
        help="Match kun Google paa OSM-steder der allerede har outdoor_seating=yes.",
    )
    parser.add_argument(
        "--include-google-discovery",
        action="store_true",
        help="Lav grid-search i Google Places for at finde flere outdoorSeating=true steder.",
    )
    parser.add_argument(
        "--google-match-radius-m",
        type=int,
        default=80,
        help="Maks afstand mellem OSM-sted og Google-match.",
    )
    parser.add_argument(
        "--google-grid-radius-m",
        type=int,
        default=650,
        help="Radius per Google-gridkald ved --include-google-discovery.",
    )
    parser.add_argument(
        "--max-google-grid-points",
        type=int,
        help="Stop grid-discovery efter N punkter. Godt til test og kvotekontrol.",
    )
    parser.add_argument(
        "--min-name-similarity",
        type=float,
        default=0.45,
        help="Lavere vaerdi accepterer mere usikre OSM/Google-navnematches.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Behandl kun de foerste N OSM-kandidater. Godt til test.",
    )
    parser.add_argument(
        "--sleep-s",
        type=float,
        default=0.05,
        help="Pause mellem Google-kald.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=100,
        help="Print status efter hver N OSM-kandidater. Brug 0 for at skjule.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    api_key = resolve_google_api_key(args)

    if not args.skip_google and not api_key:
        raise SystemExit(
            "Mangler Google API key. Saet GOOGLE_MAPS_API_KEY eller brug --skip-google."
        )

    osm_places = fetch_osm_food_places(args.bbox, amenity_values=args.osm_amenities)
    osm_places.sort(key=lambda place: (place.get("name") or "", place["osm_type"], place["osm_id"]))

    if args.limit is not None:
        osm_places = osm_places[: args.limit]

    print(f"OSM candidates found: {len(osm_places)}")

    records_by_osm_key = {}

    for index, osm_place in enumerate(osm_places, start=1):
        google_match = None

        should_google_match = (
            not args.skip_google
            and api_key is not None
            and (not args.only_osm_outdoor or osm_place.get("osm_outdoor_seating") is True)
        )

        if should_google_match:
            google_candidates = google_nearby_search(
                api_key,
                osm_place["lat"],
                osm_place["lon"],
                radius_m=args.google_match_radius_m,
                included_types=args.google_types,
            )
            google_match = find_best_google_match(
                osm_place,
                google_candidates,
                max_distance_m=args.google_match_radius_m,
                min_name_similarity=args.min_name_similarity,
            )

            if args.sleep_s > 0:
                time.sleep(args.sleep_s)

        record = build_record(osm_place, google_match)
        if record:
            records_by_osm_key[(osm_place["osm_type"], osm_place["osm_id"])] = record

        if args.progress_every > 0 and index % args.progress_every == 0:
            print(f"Processed {index}/{len(osm_places)} OSM candidates")

    if args.include_google_discovery and not args.skip_google and api_key is not None:
        google_discovered = discover_google_outdoor_places(
            api_key,
            args.bbox,
            radius_m=args.google_grid_radius_m,
            included_types=args.google_types,
            max_grid_points=args.max_google_grid_points,
            sleep_s=args.sleep_s,
        )

        print(f"Google outdoorSeating=true places discovered: {len(google_discovered)}")

        for google_place in google_discovered:
            osm_match = match_google_discovery_to_osm(
                google_place,
                osm_places,
                max_distance_m=args.google_match_radius_m,
                min_name_similarity=args.min_name_similarity,
            )

            if not osm_match:
                continue

            key = (osm_match["osm_type"], osm_match["osm_id"])
            if key in records_by_osm_key:
                continue

            record = build_record(osm_match, google_place)
            if record:
                records_by_osm_key[key] = record

    records = sorted(
        records_by_osm_key.values(),
        key=lambda record: (record.get("name") or "", record["lat"], record["lon"]),
    )

    write_csv(args.output, records)
    print(f"Wrote {len(records)} records to {args.output}")

    if args.json_output:
        write_json(args.json_output, records)
        print(f"Wrote {len(records)} records to {args.json_output}")


if __name__ == "__main__":
    main()
