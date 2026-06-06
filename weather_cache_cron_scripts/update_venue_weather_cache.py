import os
from dotenv import load_dotenv
import psycopg
import sys

load_dotenv()

BAR_SEARCH_RADIUS = 30

DATABASE_URL = os.getenv('DATABASE_URL')
conn = psycopg.connect(DATABASE_URL, sslmode='require')

sys.path.append('../sun_app')
from evaluate_location import evaluate_location

select_id_lat_lon_sql = '''
    SELECT venue_id, lat, lon
    FROM venue_weather_cache;
'''

update_cols = [
    'air_temperature',
    'cloud_area_fraction',
    'cloud_area_fraction_high',
    'cloud_area_fraction_low',
    'cloud_area_fraction_medium',
    'forecast_time',
    'precipitation_amount_next_1h',
    'relative_humidity',
    'symbol_code_next_1h',
    'uv_index_clear_sky',
    'wind_from_direction',
    'in_shadow',
    'shadow_reason',
    'building_count_fetched',
    'building_count_used',
    'nearest_building_distance_m',
    'farthest_used_building_distance_m',
    'sun_elevation_deg',
    'sun_azimuth_deg',
    'blocking_building_id',
    'blocking_building_height_m',
    'blocking_building_distance_m',
    'blocking_building_shadow_length_m',
    'shadow_payload',
]

update_sql = f'''
    UPDATE venue_weather_cache
    SET {', '.join([f'{c} = %({c})s' for c in update_cols])}
    WHERE venue_id = %(venue_id)s;
'''

with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
    cur.execute(select_id_lat_lon_sql)
    rows = cur.fetchall()

with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
    for i, row in enumerate(rows):
        print(row['venue_id'])
        evaluated = evaluate_location(
            lat=row['lat'],
            lon=row['lon'],
            radius_m=BAR_SEARCH_RADIUS
        )
        evaluated['venue_id'] = row['venue_id']
        for c in update_cols:
            if c not in evaluated.keys():
                evaluated[c] = None

        cur.execute(update_sql, evaluated)



conn.commit()
