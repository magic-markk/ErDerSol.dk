DROP TABLE IF EXISTS venue_weather_cache;

CREATE TABLE venue_weather_cache (
    venue_id INT PRIMARY KEY,
    lat DOUBLE PRECISION,
    lon DOUBLE PRECISION,

    air_temperature NUMERIC(3,1),
    cloud_area_fraction NUMERIC(3,1),
    cloud_area_fraction_high NUMERIC(3,1),
    cloud_area_fraction_low NUMERIC(3,1),
    cloud_area_fraction_medium NUMERIC(3,1),
    forecast_time TIMESTAMPTZ,
    precipitation_amount_next_1h REAL,
    relative_humidity REAL,
    symbol_code_next_1h TEXT,
    uv_index_clear_sky REAL,
    wind_from_direction REAL,
    wind_speed REAL,

    in_shadow BOOL,
    shadow_reason TEXT,
    building_count_fetched INT,
    building_count_used INT,
    nearest_building_distance_m REAL,
    farthest_used_building_distance_m REAL,
    sun_elevation_deg REAL,
    sun_azimuth_deg REAL,
    blocking_building_id BIGINT,
    blocking_building_height_m REAL,
    blocking_building_distance_m REAL,
    blocking_building_shadow_length_m REAL,
    shadow_payload JSONB,

    CONSTRAINT fk_id
        FOREIGN KEY (venue_id)
            REFERENCES outdoor_seating_places(id)
);