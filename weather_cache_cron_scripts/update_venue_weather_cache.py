import os
from dotenv import load_dotenv
import psycopg
import sys

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')
conn = psycopg.connect(DATABASE_URL, sslmode='require')

sys.path.append('../sun_app')
from weather_client import fetch_weather

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
    'wind_from_direction'
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
        weather = fetch_weather(lat=row['lat'], lon=row['lon'])
        weather['venue_id'] = row['venue_id']
        cur.execute(update_sql, weather)
        if i % 10 == 0:
            print(i)

conn.commit()
