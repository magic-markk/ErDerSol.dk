import argparse
import csv
import json
import math
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bar_scoring import calculate_bar_score
from dotenv import load_dotenv
from geodata_client import fetch_buildings_osm
from shadow_service import point_in_building_shadow
from shapely.geometry import Point, Polygon
from weather_client import fetch_weather

import psycopg

PROJECT_ROOT = Path(__file__).resolve().parents[1]
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
    "price_score",
    "distance_score",
    "score_reasons",
    "google_rating",
    "google_user_rating_count",
    "google_price_level",
    "google_maps_uri",
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
    "shadow_cache_hit",
    "sun_status",
    "in_shadow",
    "shadow_reason",
    "building_count_fetched",
    "building_count_used",
    "building_cache_hit",
    "nearest_building_distance_m",
    "farthest_used_building_distance_m",
    "sun_elevation_deg",
    "sun_azimuth_deg",
    "blocking_building_id",
    "blocking_building_height_m",
    "blocking_building_distance_m",
    "blocking_building_shadow_length_m",
    "shadow_error",
]

SHADOW_CACHE_COLUMNS = [
    "outdoor_seating_place_id",
    "calculated_for",
    "cache_bucket_minutes",
    "lat",
    "lon",
    "shadow_test_lat",
    "shadow_test_lon",
    "shadow_test_point_source",
    "in_shadow",
    "shadow_reason",
    "shadow_error",
    "building_count_fetched",
    "building_count_used",
    "nearest_building_distance_m",
    "farthest_used_building_distance_m",
    "sun_elevation_deg",
    "sun_azimuth_deg",
    "blocking_building_id",
    "blocking_building_height_m",
    "blocking_building_distance_m",
    "blocking_building_shadow_length_m",
    "shadow_payload"
]


def parse_float(value: str) -> float:
    return float(value.strip().replace(",", "."))


def parse_categories(value: str) -> tuple[str, ...]:
    categories = tuple(part.strip().lower() for part in value.split(",") if part.strip())

    if not categories:
        raise argparse.ArgumentTypeError("categories maa ikke vaere tom")

    return categories


def load_env() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv(PROJECT_ROOT / "src" / ".env")


def create_db_connection():
    load_dotenv(PROJECT_ROOT / '.env')

    DATABASE_URL = os.getenv('DATABASE_URL')
    conn = psycopg.connect(DATABASE_URL, sslmode='require', prepare_threshold=0)

    return conn


def load_places_from_supabase(
    categories: tuple[str, ...],
    conn
) -> list[dict]:

    sql = '''
        SELECT
            id,
            name,
            address,
            lat,
            lon,
            outdoor_seating,
            category,
            google_rating,
            google_user_rating_count,
            google_price_level,
            google_maps_uri
        FROM outdoor_seating_places
        LIMIT 10000
    '''

    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(sql)
        rows = cur.fetchall()


    return [
        place
        for row in rows
        if (place := row_to_place(row, categories)) is not None
    ]


def row_to_place(row: dict, categories: tuple[str, ...]) -> dict | None:
    category = str(row.get("category") or "").strip().lower()

    if category not in categories:
        return None

    if not is_truthy(row.get("outdoor_seating")):
        return None

    try:
        lat = float(row["lat"])
        lon = float(row["lon"])
    except (KeyError, TypeError, ValueError):
        return None

    return {
        "id": row.get("id"),
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


def is_truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value

    return str(value or "").strip().lower() in {"yes", "true", "1"}


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
    conn,
    places: list[dict],
    radius_m: int,
    point_mode: str,
    max_buildings: int,
    max_building_distance_m: float,
    cache_grid_m: float,
    request_delay_s: float,
    shadow_cache_minutes: int,
    shadow_cache_max_age_minutes: int,
    refresh_shadow_cache: bool,
) -> list[dict]:
    enriched = []
    buildings_cache = {}
    cache_bucket = current_cache_bucket(shadow_cache_minutes)
    cache_rows = load_shadow_cache(
        conn,
        places,
        shadow_cache_max_age_minutes,
        refresh_shadow_cache,
    )
    print(
        f"Shadow cache: {len(cache_rows)}/{len(places)} hits "
        f"inden for {shadow_cache_max_age_minutes} min.",
        flush=True,
    )
    cache_records_to_write = []

    for index, place in enumerate(places, start=1):
        cached_row = cache_rows.get(place.get("id"))

        if cached_row:
            result = apply_shadow_cache_row(place, cached_row)
            enriched.append(result)
            print(
                f"Shadow cache hit {index}/{len(places)}: {place.get('name')}",
                flush=True,
            )
            continue

        result = dict(place)

        try:
            print(
                f"Henter bygninger {index}/{len(places)}: {place.get('name')}...",
                flush=True,
            )
            buildings, cache_hit = fetch_cached_buildings(
                place["lat"],
                place["lon"],
                radius_m=radius_m,
                cache_grid_m=cache_grid_m,
                request_delay_s=request_delay_s,
                cache=buildings_cache,
            )
            shadow_lat, shadow_lon, point_source = shadow_test_point(
                place["lat"],
                place["lon"],
                buildings,
                point_mode,
            )
            nearby_buildings = nearest_buildings(
                shadow_lat,
                shadow_lon,
                buildings,
                max_count=max_buildings,
                max_distance_m=max_building_distance_m,
            )
            shadow = point_in_building_shadow(
                shadow_lat,
                shadow_lon,
                nearby_buildings,
                when_utc=cache_bucket,
            )
            result["shadow"] = shadow
            result["shadow_test_lat"] = shadow_lat
            result["shadow_test_lon"] = shadow_lon
            result["shadow_test_point_source"] = point_source
            result["shadow_cache_hit"] = False
            result["building_count_fetched"] = len(buildings)
            result["building_count_used"] = len(nearby_buildings)
            result["building_cache_hit"] = cache_hit
            result["nearest_building_distance_m"] = building_distance_value(nearby_buildings, 0)
            result["farthest_used_building_distance_m"] = building_distance_value(nearby_buildings, -1)
            result["shadow_error"] = None
        except Exception as exc:
            result["shadow"] = {}
            result["shadow_test_lat"] = None
            result["shadow_test_lon"] = None
            result["shadow_test_point_source"] = None
            result["shadow_cache_hit"] = False
            result["building_count_fetched"] = None
            result["building_count_used"] = None
            result["building_cache_hit"] = None
            result["nearest_building_distance_m"] = None
            result["farthest_used_building_distance_m"] = None
            result["shadow_error"] = str(exc)

        enriched.append(result)
        cache_record = shadow_cache_record(result, cache_bucket, shadow_cache_minutes)

        if cache_record is not None:
            cache_records_to_write.append(cache_record)

    upsert_shadow_cache(cache_records_to_write, conn)

    return enriched


def current_cache_bucket(bucket_minutes: int) -> datetime:
    if bucket_minutes <= 0:
        raise ValueError("shadow cache bucket skal vaere stoerre end 0 minutter")

    now = datetime.now(timezone.utc)
    minute = (now.minute // bucket_minutes) * bucket_minutes
    return now.replace(minute=minute, second=0, microsecond=0)


def load_shadow_cache(
    conn,
    places: list[dict],
    cache_max_age_minutes: int,
    refresh_shadow_cache: bool,
) -> dict[int, dict]:
    if refresh_shadow_cache:
        return {}

    place_ids = [
        int(place["id"])
        for place in places
        if place.get("id") is not None
    ]

    if not place_ids:
        return {}

    oldest_usable_cache = (
        datetime.now(timezone.utc) - timedelta(minutes=cache_max_age_minutes)
    )
    sql = f'''
        SELECT *
        FROM bar_shadow_cache
        WHERE
            calculated_for >= %s
            AND outdoor_seating_place_id = ANY(%s)
        ORDER BY calculated_for DESC;
    '''
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(sql, (oldest_usable_cache, place_ids))
        rows = cur.fetchall()


    # response = (
    #     supabase
    #     .table("bar_shadow_cache")
    #     .select("*")
    #     .gte("calculated_for", oldest_usable_cache.isoformat())
    #     .in_("outdoor_seating_place_id", place_ids)
    #     .order("calculated_for", desc=True)
    #     .execute()
    # )

    latest_rows = {}

    for row in rows:
        place_id = row["outdoor_seating_place_id"]

        if place_id not in latest_rows:
            latest_rows[place_id] = row

    return latest_rows


def apply_shadow_cache_row(place: dict, cache_row: dict) -> dict:
    result = dict(place)
    shadow_payload = cache_row.get("shadow_payload") or {}
    blocking_building = cached_blocking_building(cache_row)

    result["shadow"] = shadow_payload or {
        "in_shadow": cache_row.get("in_shadow"),
        "reason": cache_row.get("shadow_reason"),
        "sun": {
            "timestamp_utc": cache_row.get("calculated_for"),
            "sun_elevation_deg": cache_row.get("sun_elevation_deg"),
            "sun_azimuth_deg": cache_row.get("sun_azimuth_deg"),
        },
        "blocking_building": blocking_building,
    }
    result["shadow_test_lat"] = cache_row.get("shadow_test_lat")
    result["shadow_test_lon"] = cache_row.get("shadow_test_lon")
    result["shadow_test_point_source"] = cache_row.get("shadow_test_point_source")
    result["shadow_cache_hit"] = True
    result["building_count_fetched"] = cache_row.get("building_count_fetched")
    result["building_count_used"] = cache_row.get("building_count_used")
    result["building_cache_hit"] = True
    result["nearest_building_distance_m"] = cache_row.get("nearest_building_distance_m")
    result["farthest_used_building_distance_m"] = cache_row.get("farthest_used_building_distance_m")
    result["shadow_error"] = cache_row.get("shadow_error")
    return result


def cached_blocking_building(cache_row: dict) -> dict | None:
    if cache_row.get("blocking_building_id") is None:
        return None

    return {
        "id": cache_row.get("blocking_building_id"),
        "height_m": cache_row.get("blocking_building_height_m"),
        "distance_m": cache_row.get("blocking_building_distance_m"),
        "shadow_length_m": cache_row.get("blocking_building_shadow_length_m"),
    }


def shadow_cache_record(
    place: dict,
    cache_bucket: datetime,
    cache_bucket_minutes: int,
) -> dict | None:
    if place.get("id") is None:
        return None

    shadow = place.get("shadow") or {}
    sun = shadow.get("sun") or {}
    blocking_building = shadow.get("blocking_building") or {}

    return {
        "outdoor_seating_place_id": int(place["id"]),
        "calculated_for": cache_bucket.isoformat(),
        "cache_bucket_minutes": cache_bucket_minutes,
        "lat": place.get("lat"),
        "lon": place.get("lon"),
        "shadow_test_lat": place.get("shadow_test_lat"),
        "shadow_test_lon": place.get("shadow_test_lon"),
        "shadow_test_point_source": place.get("shadow_test_point_source"),
        "in_shadow": shadow.get("in_shadow"),
        "shadow_reason": shadow.get("reason"),
        "shadow_error": place.get("shadow_error"),
        "building_count_fetched": place.get("building_count_fetched"),
        "building_count_used": place.get("building_count_used"),
        "nearest_building_distance_m": place.get("nearest_building_distance_m"),
        "farthest_used_building_distance_m": place.get("farthest_used_building_distance_m"),
        "sun_elevation_deg": sun.get("sun_elevation_deg"),
        "sun_azimuth_deg": sun.get("sun_azimuth_deg"),
        "blocking_building_id": blocking_building.get("id"),
        "blocking_building_height_m": blocking_building.get("height_m"),
        "blocking_building_distance_m": blocking_building.get("distance_m"),
        "blocking_building_shadow_length_m": blocking_building.get("shadow_length_m"),
        "shadow_payload": shadow,
    }


def upsert_shadow_cache(records: list[dict], conn) -> None:
    if not records:
        return

    try:
        sql = f'''
            INSERT INTO bar_shadow_cache (
                {', '.join([c for c in SHADOW_CACHE_COLUMNS])}
            )
            VALUES (
                {', '.join([f'%({c})s' for c in SHADOW_CACHE_COLUMNS])}
            )
            ON CONFLICT (outdoor_seating_place_id)
            DO UPDATE SET
                {', '.join(
                    f'{c} = EXCLUDED.{c}'
                    for c in SHADOW_CACHE_COLUMNS
                    if c != 'outdoor_seating_place_id'
                )}
        '''
        for r in records:
            if r.get("shadow_payload") is not None:
                r["shadow_payload"] = psycopg.types.json.Jsonb(r["shadow_payload"])
        with conn.cursor() as cur:
            cur.executemany(sql, records)

        conn.commit()


        print(f"Skrev {len(records)} shadow-cache raekker til Supabase.", flush=True)
    except Exception as exc:
        print(f"Kunne ikke skrive shadow-cache til Supabase: {exc}", flush=True)


def fetch_cached_buildings(
    lat: float,
    lon: float,
    radius_m: int,
    cache_grid_m: float,
    request_delay_s: float,
    cache: dict,
) -> tuple[list[dict], bool]:
    key = building_cache_key(lat, lon, radius_m, cache_grid_m)

    if key in cache:
        return cache[key], True

    fetch_radius_m = radius_m
    if cache_grid_m > 0:
        fetch_radius_m = int(math.ceil(radius_m + cache_grid_m))

    if request_delay_s > 0 and cache:
        time.sleep(request_delay_s)

    buildings = fetch_buildings_osm(lat, lon, radius_m=fetch_radius_m)
    cache[key] = buildings
    return buildings, False


def building_cache_key(
    lat: float,
    lon: float,
    radius_m: int,
    cache_grid_m: float,
) -> tuple:
    if cache_grid_m <= 0:
        return (round(lat, 7), round(lon, 7), radius_m)

    lat_step = cache_grid_m / 111_320.0
    lon_step = cache_grid_m / (111_320.0 * abs(math.cos(math.radians(lat))))

    return (
        round(lat / lat_step),
        round(lon / lon_step),
        radius_m,
        round(cache_grid_m),
    )


def nearest_buildings(
    lat: float,
    lon: float,
    buildings: list[dict],
    max_count: int,
    max_distance_m: float,
) -> list[dict]:
    buildings_with_distance = []

    for building in buildings:
        distance_m = distance_to_building_m(lat, lon, building)

        if distance_m is None:
            continue

        if max_distance_m > 0 and distance_m > max_distance_m:
            continue

        building_copy = dict(building)
        building_copy["_distance_to_shadow_point_m"] = round(distance_m, 1)
        buildings_with_distance.append(building_copy)

    buildings_with_distance.sort(key=lambda item: item["_distance_to_shadow_point_m"])

    if max_count > 0:
        return buildings_with_distance[:max_count]

    return buildings_with_distance


def distance_to_building_m(lat: float, lon: float, building: dict) -> float | None:
    polygon_coords = building.get("polygon", [])

    if len(polygon_coords) < 3:
        return None

    poly = Polygon(polygon_coords)

    if not poly.is_valid:
        poly = poly.buffer(0)

    if poly.is_empty:
        return None

    target = Point(lon, lat)

    if poly.covers(target):
        return 0.0

    nearest = poly.exterior.interpolate(poly.exterior.project(target))
    return haversine_m(lat, lon, nearest.y, nearest.x)


def building_distance_value(buildings: list[dict], index: int) -> float | None:
    if not buildings:
        return None

    return buildings[index].get("_distance_to_shadow_point_m")


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
        "price_score": score.get("price_score"),
        "distance_score": score.get("distance_score"),
        "score_reasons": score.get("score_reasons"),
        "google_rating": place.get("google_rating"),
        "google_user_rating_count": place.get("google_user_rating_count"),
        "google_price_level": place.get("google_price_level"),
        "google_maps_uri": place.get("google_maps_uri"),
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
        "shadow_cache_hit": place.get("shadow_cache_hit"),
        "sun_status": sun_status_from_shadow(in_shadow),
        "in_shadow": in_shadow,
        "shadow_reason": shadow.get("reason"),
        "building_count_fetched": place.get("building_count_fetched"),
        "building_count_used": place.get("building_count_used"),
        "building_cache_hit": place.get("building_cache_hit"),
        "nearest_building_distance_m": place.get("nearest_building_distance_m"),
        "farthest_used_building_distance_m": place.get("farthest_used_building_distance_m"),
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
        score = place.get("score") or {}
        sun = shadow.get("sun") or {}

        print(f"\n{index}. {place.get('name')}")
        if score:
            print(
                f"   Score: {score.get('total_score')}/{score.get('score_max')} "
                f"(sun {score.get('sun_score')}, weather {score.get('weather_score')}, "
                f"reviews {score.get('reviews_score')}, "
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
                f"buildings checked={place.get('building_count_used')}/{place.get('building_count_fetched')}, "
                f"cache_hit={place.get('building_cache_hit')}"
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
        help="Kategorier fra Supabase, fx bar,pub,biergarten eller bar,pub,restaurant.",
    )
    parser.add_argument(
        "--shadow-radius-m",
        type=int,
        default=150,
        help="Radius i meter til bygninger der bruges i skyggeberegningen.",
    )
    parser.add_argument(
        "--shadow-max-buildings",
        type=int,
        default=25,
        help="Maks antal naermeste bygninger der sendes til skyggeberegningen. Brug 0 for alle.",
    )
    parser.add_argument(
        "--shadow-max-building-distance-m",
        type=float,
        default=80,
        help="Maks afstand fra skygge-testpunkt til bygning. Brug 0 for ingen afstandsgrænse.",
    )
    parser.add_argument(
        "--shadow-cache-grid-m",
        type=float,
        default=75,
        help=(
            "Genbrug bygningsdata for barer i samme ca. gridcelle. "
            "Saet 0 for at slaa cache fra."
        ),
    )
    parser.add_argument(
        "--shadow-request-delay-s",
        type=float,
        default=1.0,
        help="Pause mellem nye Overpass-kald til bygninger. Cache hits venter ikke.",
    )
    parser.add_argument(
        "--include-shadow",
        action="store_true",
        help="Hent OSM-bygninger og beregn skygge. Kan vaere langsomt pga. Overpass API.",
    )
    parser.add_argument(
        "--shadow-cache-minutes",
        type=int,
        default=15,
        help="Antal minutter per ny Supabase shadow-cache bucket.",
    )
    parser.add_argument(
        "--shadow-cache-max-age-minutes",
        type=int,
        default=120,
        help="Maks alder i minutter for cache-rækker der maa genbruges.",
    )
    parser.add_argument(
        "--refresh-shadow-cache",
        action="store_true",
        help="Ignorer eksisterende shadow-cache og skriv nye beregninger.",
    )
    parser.add_argument(
        "--skip-shadow",
        action="store_true",
        help="Beholdt for gamle kommandoer. Skyggeberegning er nu slaaet fra som default.",
    )
    parser.add_argument(
        "--shadow-point-mode",
        choices=("outdoor", "place"),
        default="outdoor",
        help=(
            "outdoor flytter testpunktet ud til naermeste bygningskant, hvis Supabase-punktet "
            "ligger inde i en bygning. place bruger Supabase-koordinatet direkte."
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

    conn = create_db_connection()

    places = load_places_from_supabase(args.categories, conn)
    candidate_limit = args.candidate_limit or args.limit
    nearby = find_nearby_places(user_lat, user_lon, places, args.radius_m, candidate_limit)
    enriched = nearby

    enriched = add_weather_to_places(enriched)

    if args.include_shadow and not args.skip_shadow:
        enriched = add_shadow_to_places(
            conn,
            enriched,
            radius_m=args.shadow_radius_m,
            point_mode=args.shadow_point_mode,
            max_buildings=args.shadow_max_buildings,
            max_building_distance_m=args.shadow_max_building_distance_m,
            cache_grid_m=args.shadow_cache_grid_m,
            request_delay_s=args.shadow_request_delay_s,
            shadow_cache_minutes=args.shadow_cache_minutes,
            shadow_cache_max_age_minutes=args.shadow_cache_max_age_minutes,
            refresh_shadow_cache=args.refresh_shadow_cache,
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
        f"ud af {len(places)} relevante Supabase-steder."
    )
    print_results(enriched)

    if args.output:
        write_csv(args.output, enriched)
        print(f"\nSkrev CSV: {args.output}")

    if args.json_output:
        write_json(args.json_output, enriched)
        print(f"Skrev JSON: {args.json_output}")

    conn.close()


if __name__ == "__main__":
    main()
