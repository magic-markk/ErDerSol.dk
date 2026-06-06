from flask import Flask, render_template, request, jsonify, send_from_directory
import psycopg
import requests

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT / 'sun_app'))
from evaluate_location import evaluate_location
from nearby_bars_weather import (
    DEFAULT_CATEGORIES,
    add_scores_to_places,
    add_shadow_to_places,
    add_weather_to_places,
    find_nearby_places,
    flatten_place,
    load_places_from_supabase,
)

from werkzeug.routing import BaseConverter

import os
from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / '.env')

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


@app.route('/assets/<path:filename>')
def assets(filename):
    return send_from_directory(PROJECT_ROOT / 'assets', filename)

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


    return jsonify(rows)


@app.route('/nearby_bars', methods=['POST'])
def nearby_bars():
    '''
    Find nearby outdoor bars for the user's browser location.
    '''
    data = request.get_json(silent=True) or {}

    try:
        user_lat = float(data.get('lat'))
        user_lon = float(data.get('lon'))
    except (TypeError, ValueError):
        return jsonify({'error': 'lat and lon are required numbers'}), 400

    radius_m = 3000
    limit = 25
    candidate_limit = 25

    places = load_places_from_supabase(DEFAULT_CATEGORIES)
    nearby = find_nearby_places(
        user_lat,
        user_lon,
        places,
        radius_m=radius_m,
        limit=candidate_limit,
    )
    enriched = add_weather_to_places(nearby)
    enriched = add_shadow_to_places(
        enriched,
        radius_m=150,
        point_mode='outdoor',
        max_buildings=25,
        max_building_distance_m=80,
        cache_grid_m=75,
        request_delay_s=1.0,
        shadow_cache_minutes=15,
        shadow_cache_max_age_minutes=120,
        refresh_shadow_cache=False,
    )
    enriched = add_scores_to_places(enriched, search_radius_m=radius_m)
    enriched.sort(
        key=lambda place: place.get('score', {}).get('total_score') or -1,
        reverse=True,
    )

    return jsonify([flatten_place(place) for place in enriched[:limit]])


if __name__ == '__main__':
    app.run(debug=True)
