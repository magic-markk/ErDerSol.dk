"""
Scoring model for ranking bars.

This file is intentionally kept separate from API/CSV/XML code, so the score
model can be tuned quickly while the data pipeline stays stable.
"""


MAX_POINTS = {
    "sun": 35.0,
    "weather": 25.0,
    "reviews": 15.0,
    "smiley": 10.0,
    "price": 8.0,
    "distance": 7.0,
}

TOTAL_MAX_POINTS = sum(MAX_POINTS.values())


def calculate_bar_score(place: dict, search_radius_m: float) -> dict:
    weather = place.get("weather") or {}
    shadow = place.get("shadow") or {}
    smiley = place.get("smiley") or {}

    sun_score, sun_reasons = score_sun(weather, shadow)
    weather_score, weather_reasons = score_weather(weather)
    reviews_score, reviews_reasons = score_reviews(
        place.get("google_rating"),
        place.get("google_user_rating_count"),
    )
    smiley_score, smiley_reasons = score_smiley(smiley)
    price_score, price_reasons = score_price(place.get("google_price_level"))
    distance_score, distance_reasons = score_distance(
        place.get("distance_m"),
        search_radius_m,
    )

    total = (
        sun_score
        + weather_score
        + reviews_score
        + smiley_score
        + price_score
        + distance_score
    )

    return {
        "total_score": round(clamp(total, 0.0, TOTAL_MAX_POINTS), 1),
        "score_max": TOTAL_MAX_POINTS,
        "sun_score": round(sun_score, 1),
        "weather_score": round(weather_score, 1),
        "reviews_score": round(reviews_score, 1),
        "smiley_score_points": round(smiley_score, 1),
        "price_score": round(price_score, 1),
        "distance_score": round(distance_score, 1),
        "score_reasons": build_score_reasons(
            sun_reasons,
            weather_reasons,
            reviews_reasons,
            smiley_reasons,
            price_reasons,
            distance_reasons,
        ),
    }


def score_sun(weather: dict, shadow: dict) -> tuple[float, list[str]]:
    reasons = []
    points = 0.0
    in_shadow = shadow.get("in_shadow")
    uv_index = as_float(weather.get("uv_index_clear_sky"))
    cloud_low = as_float(weather.get("cloud_area_fraction_low"))
    cloud_medium = as_float(weather.get("cloud_area_fraction_medium"))
    cloud_high = as_float(weather.get("cloud_area_fraction_high"))

    if in_shadow is False:
        points += 22.0
        reasons.append("direct sun")
    elif in_shadow is True:
        points += 6.0
        reasons.append("in shadow")
    else:
        points += 14.0
        reasons.append("unknown shadow")

    if uv_index is None:
        points += 3.0
        reasons.append("unknown UV")
    else:
        uv_points = clamp(uv_index * 1.6, 0.0, 8.0)
        points += uv_points
        reasons.append(f"UV {uv_index:g}")

    cloud_penalty = 0.0
    if cloud_low is not None:
        cloud_penalty += cloud_low * 0.07
    if cloud_medium is not None:
        cloud_penalty += cloud_medium * 0.04
    if cloud_high is not None:
        cloud_penalty += cloud_high * 0.015

    if cloud_penalty > 0:
        points -= cloud_penalty
        reasons.append("clouds reduce sun")

    return clamp(points, 0.0, MAX_POINTS["sun"]), reasons


def score_weather(weather: dict) -> tuple[float, list[str]]:
    reasons = []
    points = 0.0

    temp = as_float(weather.get("air_temperature"))
    wind = as_float(weather.get("wind_speed"))
    rain = as_float(weather.get("precipitation_amount_next_1h"))
    rain_probability = as_float(weather.get("probability_of_precipitation_next_1h"))
    cloud_total = as_float(weather.get("cloud_area_fraction"))

    temp_points = temperature_points(temp)
    points += temp_points
    reasons.append("comfortable temperature" if temp_points >= 6 else "temperature penalty")

    wind_points = wind_points_from_speed(wind)
    points += wind_points
    reasons.append("calm wind" if wind_points >= 5 else "wind penalty")

    rain_points = rain_points_from_amount(rain, rain_probability)
    points += rain_points
    reasons.append("dry next hour" if rain_points >= 6 else "rain risk")

    cloud_points = cloud_points_from_total(cloud_total)
    points += cloud_points
    reasons.append("bright sky" if cloud_points >= 3 else "cloudy")

    return clamp(points, 0.0, MAX_POINTS["weather"]), reasons


def temperature_points(temp: float | None) -> float:
    if temp is None:
        return 4.0

    if 18.0 <= temp <= 24.0:
        return 8.0
    if 15.0 <= temp < 18.0:
        return 6.0 + ((temp - 15.0) / 3.0) * 2.0
    if 24.0 < temp <= 28.0:
        return 8.0 - ((temp - 24.0) / 4.0) * 2.0
    if 10.0 <= temp < 15.0:
        return 2.5 + ((temp - 10.0) / 5.0) * 3.5
    if 28.0 < temp <= 32.0:
        return 6.0 - ((temp - 28.0) / 4.0) * 3.0

    return 2.0


def wind_points_from_speed(wind_speed: float | None) -> float:
    if wind_speed is None:
        return 3.0

    if wind_speed <= 3.0:
        return 6.0
    if wind_speed <= 6.0:
        return 6.0 - ((wind_speed - 3.0) / 3.0) * 2.5
    if wind_speed <= 10.0:
        return 3.5 - ((wind_speed - 6.0) / 4.0) * 3.0

    return 0.5


def rain_points_from_amount(rain_mm: float | None, rain_probability: float | None) -> float:
    points = 7.0

    if rain_mm is None:
        points -= 1.5
    else:
        points -= min(6.0, rain_mm * 4.0)

    if rain_probability is None:
        points -= 0.5
    else:
        points -= min(3.0, rain_probability * 0.03)

    return clamp(points, 0.0, 7.0)


def cloud_points_from_total(cloud_total: float | None) -> float:
    if cloud_total is None:
        return 2.0

    return clamp(4.0 - (cloud_total * 0.04), 0.0, 4.0)


def score_reviews(rating_raw: object, review_count_raw: object) -> tuple[float, list[str]]:
    rating = as_float(rating_raw)
    review_count = as_float(review_count_raw)

    if rating is None:
        return 7.0, ["unknown Google rating"]

    if review_count is None:
        review_count = 0.0

    # Bayesian adjustment: a 5.0 rating with 3 reviews should not beat a 4.6
    # rating with thousands of reviews too easily.
    prior_rating = 3.8
    prior_weight = 50.0
    adjusted_rating = ((rating * review_count) + (prior_rating * prior_weight)) / (
        review_count + prior_weight
    )
    rating_points = normalize(adjusted_rating, 3.0, 5.0) * MAX_POINTS["reviews"]
    confidence_bonus = clamp(review_count / 1000.0, 0.0, 1.0)
    points = clamp(rating_points + confidence_bonus, 0.0, MAX_POINTS["reviews"])

    return points, [f"rating {rating:g}", f"{int(review_count)} reviews"]


def score_smiley(smiley: dict) -> tuple[float, list[str]]:
    match_status = smiley.get("match_status")
    smiley_value = str(smiley.get("score") or "").strip()

    if match_status != "matched":
        if match_status == "low_confidence":
            return 4.0, ["uncertain smiley match"]
        return 5.0, ["unknown smiley"]

    mapping = {
        "1": 10.0,
        "2": 7.0,
        "3": 3.0,
        "4": 0.0,
    }
    points = mapping.get(smiley_value, 5.0)
    return points, [f"smiley {smiley_value or 'unknown'}"]


def score_price(price_level: object) -> tuple[float, list[str]]:
    price = str(price_level or "").strip().upper()

    mapping = {
        "PRICE_LEVEL_FREE": 6.0,
        "PRICE_LEVEL_INEXPENSIVE": 7.0,
        "PRICE_LEVEL_MODERATE": 8.0,
        "PRICE_LEVEL_EXPENSIVE": 4.0,
        "PRICE_LEVEL_VERY_EXPENSIVE": 2.0,
    }

    if not price:
        return 5.0, ["unknown price"]

    return mapping.get(price, 5.0), [price.lower()]


def score_distance(distance_m_raw: object, search_radius_m: float) -> tuple[float, list[str]]:
    distance_m = as_float(distance_m_raw)

    if distance_m is None or search_radius_m <= 0:
        return 3.0, ["unknown distance"]

    closeness = 1.0 - clamp(distance_m / search_radius_m, 0.0, 1.0)
    points = MAX_POINTS["distance"] * (closeness ** 0.7)
    return points, [f"{round(distance_m)} m away"]


def build_score_reasons(*reason_groups: list[str]) -> str:
    reasons = []

    for group in reason_groups:
        for reason in group:
            if reason and reason not in reasons:
                reasons.append(reason)

    return "; ".join(reasons[:8])


def normalize(value: float, low: float, high: float) -> float:
    if high <= low:
        return 0.0

    return clamp((value - low) / (high - low), 0.0, 1.0)


def as_float(value: object) -> float | None:
    if value is None or value == "":
        return None

    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
