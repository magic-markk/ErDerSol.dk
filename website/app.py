from flask import Flask, render_template, request, jsonify
import psycopg
import requests

import sys
sys.path.append('../sun_app')
from evaluate_location import evaluate_location

from werkzeug.routing import BaseConverter

import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')
conn = psycopg.connect(DATABASE_URL, sslmode='require')


app = Flask(__name__)


class RegexConverter(BaseConverter):
    def __init__(self, url_map, *items):
        super(RegexConverter, self).__init__(url_map)
        self.regex = items[0]

app.url_map.converters['regex'] = RegexConverter

@app.route('/')
def home():
    '''
    render home page
    '''
    query = request.args.get('search', '').strip()

    return render_template('home.html', initial_query=query)

@app.route('/bruger')
def bruger():
    '''
    render user page
    '''
    return render_template('user.html')

@app.route('/auto_query', methods=['GET'])
def auto_query():
    '''
    automatically query venues to add them to the map
    '''
    sql = '''
        SELECT
            V.name,
            V.address,
            V.lat,
            V.lon,
            V.google_maps_uri,
            W.cloud_area_fraction AS cloud_area
        FROM outdoor_seating_places V
            INNER JOIN venue_weather_cache W ON V.id = W.venue_id;
    '''

    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    return jsonify(rows)

@app.route('/search', methods=['POST'])
def search():
    '''
    Query from search bar
    '''
    data = request.get_json()
    query = data.get("query", "").strip()

    # basic safety checks
    if not query or len(query) > 50:
        return jsonify([])

    sql = '''
        SELECT name, address, lat, lon, google_rating, google_user_rating_count, google_maps_uri
        FROM outdoor_seating_places
        WHERE name ILIKE %(q)s
        OR address ILIKE %(q)s;
    '''

    pattern = f"%{query.replace('%', '').replace('_', '')}%"

    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(sql, {"q": pattern})
        rows = cur.fetchall()

    for row in rows:
        for key, val in evaluate_location(lat=row['lat'], lon=row['lon']).items():
            row[key] = val
    print(rows)
    return jsonify(rows)


if __name__ == '__main__':
    app.run(debug=True)