import os
from dotenv import load_dotenv
import psycopg

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')
conn = psycopg.connect(DATABASE_URL, sslmode='require')

weather_insert_sql = '''
    INSERT INTO venue_weather_cache (venue_id, lat, lon)
    SELECT id, lat, lon FROM outdoor_seating_places;
'''

with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
    cur.execute(weather_insert_sql)

conn.commit()
