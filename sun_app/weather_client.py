import requests

BASE_URL = "https://api.met.no/weatherapi/locationforecast/2.0/complete"

HEADERS = {
    "User-Agent": "SunScoreSchoolProject/0.1 your.email@example.com"
}


def fetch_weather(lat: float, lon: float, altitude: int | None = None) -> dict:
    params = {
        "lat": lat,
        "lon": lon,
    }

    if altitude is not None:
        params["altitude"] = altitude

    response = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=20)
    response.raise_for_status()
    data = response.json()

    first_entry = data["properties"]["timeseries"][0]
    details = first_entry["data"]["instant"]["details"]

    next_1h = first_entry["data"].get("next_1_hours", {})
    summary_1h = next_1h.get("summary", {})
    details_1h = next_1h.get("details", {})

    return {
        "forecast_time": first_entry["time"],
        "air_temperature": details.get("air_temperature"),
        "relative_humidity": details.get("relative_humidity"),
        "wind_speed": details.get("wind_speed"),
        "wind_from_direction": details.get("wind_from_direction"),
        "cloud_area_fraction": details.get("cloud_area_fraction"),
        "cloud_area_fraction_low": details.get("cloud_area_fraction_low"),
        "cloud_area_fraction_medium": details.get("cloud_area_fraction_medium"),
        "cloud_area_fraction_high": details.get("cloud_area_fraction_high"),
        "uv_index_clear_sky": details.get("ultraviolet_index_clear_sky"),
        "symbol_code_next_1h": summary_1h.get("symbol_code"),
        "precipitation_amount_next_1h": details_1h.get("precipitation_amount"),
        "probability_of_precipitation_next_1h": details_1h.get("probability_of_precipitation"),
    }