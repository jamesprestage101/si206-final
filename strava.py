import requests
from flask import Flask, request, jsonify, redirect
import sqlite3
import os
from weather import setup_weather_routes

app = Flask(__name__)
setup_weather_routes(app)

# My Strava API app credentials
CLIENT_ID = "141007"
CLIENT_SECRET = "052da5de5f06be8d811655a36f081cfad12ce338"
REDIRECT_URI = "http://127.0.0.1:5000/callback"  # Flask Localhost URL

# Temporary storage for access tokens
ACCESS_TOKEN = None

def init_db():
    if not os.path.exists('activities.db'):
        conn = sqlite3.connect('activities.db')
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                athlete_id INTEGER,
                activity_id INTEGER UNIQUE,
                name TEXT,
                start_date_local TEXT,
                distance REAL,
                type TEXT,
                start_lat REAL,
                start_long REAL
            )
        ''')
        conn.commit()
        conn.close()
        print("Database initialized.")
    else:
        print("Database already exists.")

@app.route('/')
def home():
    return """
    <h1>Strava API Demo</h1>
    <a href="/authorize"><button>Connect to Strava</button></a>
    """

@app.route('/authorize')
def authorize():
    # Redirects to Strava's OAuth page
    auth_url = (
        f"https://www.strava.com/oauth/authorize?client_id={CLIENT_ID}&response_type=code"
        f"&redirect_uri={REDIRECT_URI}&approval_prompt=force&scope=read,activity:read"
    )
    return redirect(auth_url)

@app.route('/callback')
def callback():
    # Handle the callback from Strava
    code = request.args.get('code')  # Gets the authorization code
    token_url = "https://www.strava.com/oauth/token"
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
    }
    response = requests.post(token_url, data=payload)
    response_data = response.json()
    global ACCESS_TOKEN
    ACCESS_TOKEN = response_data.get("access_token")
    if ACCESS_TOKEN:
        return "<h1>Authorization Successful!</h1><a href='/activities'><button>Fetch Activities</button></a>"
    else:
        return "<h1>Authorization Failed.</h1>"

@app.route('/activities')
def get_activities():
    # Fetch activities using the access token
    if not ACCESS_TOKEN:
        return jsonify({"error": "No access token. Please authenticate first."}), 400

    activities_url = "https://www.strava.com/api/v3/athlete/activities"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    response = requests.get(activities_url, headers=headers)

    if response.status_code != 200:
        return jsonify({"error": "Failed to fetch activities from Strava."}), response.status_code

    activities = response.json()
    conn = sqlite3.connect('activities.db')
    cursor = conn.cursor()

    for activity in activities:
        start_latlng = activity.get('start_latlng')
        if not start_latlng or len(start_latlng) < 2:
            continue

        athlete_id = activity.get('athlete', {}).get('id', 0)
        activity_id = activity.get('id')
        name = activity.get('name')
        start_date_local = activity.get('start_date_local')  # Start Time (Local)
        distance = activity.get('distance')
        activity_type = activity.get('type')
        start_lat = start_latlng[0]
        start_long = start_latlng[1]

        cursor.execute('''
            INSERT OR IGNORE INTO activities (
                athlete_id, activity_id, name, start_date_local, distance, type, start_lat, start_long
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (athlete_id, activity_id, name, start_date_local, distance, activity_type, start_lat, start_long))

    conn.commit()
    conn.close()

    filtered_activities = [
        {
            "name": activity.get("name"),
            "start_date_local": activity.get("start_date_local"),
            "distance": activity.get("distance"),
            "type": activity.get("type"),
            "start_lat": (activity.get("start_latlng") or [None, None])[0],
            "start_long": (activity.get("start_latlng") or [None, None])[1],
        }
        for activity in activities if activity.get("start_latlng") and len(activity.get("start_latlng")) >= 2
    ]
    return jsonify(filtered_activities)

# Go to this link if you want to erase the database file and reinitialize
@app.route('/reset_db')
def reset_db():
    if os.path.exists('activities.db'):
        os.remove('activities.db')
    init_db()
    return "Database has been reset and initialized."

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)