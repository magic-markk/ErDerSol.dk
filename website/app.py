from flask import Flask, render_template, request, jsonify
import requests
from markupsafe import escape
from pathlib import Path

SUPABASE_URL = 'https://hpnemxpzexmxjkhuukpr.supabase.co' # supabase project url
SUPABASE_SERVICE_KEY_PATH = ( # txt filepath with service api key
    Path.cwd().parents[0]/
    'data'/
    'supabase_service_api_key.txt'
)
with open(SUPABASE_SERVICE_KEY_PATH, 'r') as f:
    SUPABASE_SERVICE_KEY = f.readline()

SUPABASE_HEADERS = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}"
}

app = Flask(__name__)

@app.route('/')
def home():
    '''
    render home page
    '''
    return render_template('home.html')

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
    url = f"{SUPABASE_URL}/rest/v1/outdoor_seating_places?select=name,address,lat,lon"

    res = requests.get(url, headers=SUPABASE_HEADERS)

    return jsonify(res.json())

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

    # optional sanitization (keeps it simple + safe)
    query = escape(query)

    url = f"{SUPABASE_URL}/rest/v1/outdoor_seating_places"

    params = {
        "select": "*",
        "or": f"(name.ilike.*{query}*,address.ilike.*{query}*)"
    }

    res = requests.get(
        url,
        headers=SUPABASE_HEADERS,
        params=params
    )

    return jsonify(res.json())


if __name__ == '__main__':
    app.run(debug=True)