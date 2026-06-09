from flask import Flask, render_template, request, jsonify, send_from_directory
import psycopg
import requests

import re

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


import os
from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / '.env')

DATABASE_URL = os.getenv('DATABASE_URL')


app = Flask(__name__)


WHITESPACE_REGEX_PATTERN = re.compile(r'\s+')


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
    conn = psycopg.connect(DATABASE_URL, sslmode='require', prepare_threshold=0)

    sql = '''
        SELECT name, address, lat, lon, google_maps_uri
        FROM outdoor_seating_places
    '''

    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    conn.close()

    return jsonify(rows)

@app.route('/search', methods=['POST'])
def search():
    '''
    Query from search bar
    '''
    data = request.get_json()
    query = data.get("query", "").strip()
    query = WHITESPACE_REGEX_PATTERN.sub(" ", query)

    regex_pattern = r'(?<!\w)(hjem|C)(?!\w)'

    if re.search(regex_pattern, query, re.IGNORECASE):
        user_wants_to_go_home = True
        actual_query = 'Caféen?'
    else:
        user_wants_to_go_home = False

    # basic safety checks
    if not query or len(query) > 50:
        return jsonify([])

    conn = psycopg.connect(DATABASE_URL, sslmode='require', prepare_threshold=0)

    sql = '''
        SELECT name, address, lat, lon, google_rating, google_user_rating_count, google_maps_uri
        FROM outdoor_seating_places
        WHERE name ILIKE %(q)s
        OR address ILIKE %(q)s;
    '''


    pattern = f"%{query.replace('%', '').replace('_', '')}%"

    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        if user_wants_to_go_home:
            actual_pattern = f"%{actual_query.replace('%', '').replace('_', '')}%"

            cur.execute(sql, {"q": actual_pattern})
            rows = cur.fetchall()

            cur.execute(sql, {"q": pattern})
            rows += cur.fetchall()

        else:
            cur.execute(sql, {"q": pattern})
            rows = cur.fetchall()

    conn.close()

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

    conn = psycopg.connect(DATABASE_URL, sslmode='require', prepare_threshold=0)

    radius_m = 3000
    limit = 10
    candidate_limit = 10

    places = load_places_from_supabase(DEFAULT_CATEGORIES, conn)
    nearby = find_nearby_places(
        user_lat,
        user_lon,
        places,
        radius_m=radius_m,
        limit=candidate_limit,
    )
    enriched = add_weather_to_places(nearby)
    enriched = add_shadow_to_places(
        conn,
        enriched,
        radius_m=30,
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

    conn.close()

    return jsonify([flatten_place(place) for place in enriched[:limit]])


if __name__ == '__main__':
    app.run(debug=True)
