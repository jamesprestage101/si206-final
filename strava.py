import requests
import sqlite3
import os
import time
from flask import Flask, request, redirect

# Flask app initialization
app = Flask(__name__)

# Strava API credentials
CLIENT_ID = "141007"
CLIENT_SECRET = "052da5de5f06be8d811655a36f081cfad12ce338"
REDIRECT_URI = "http://127.0.0.1:5000/callback"

# Initialize database!
def init_db():
    if not os.path.exists('activities.db'):
        conn = sqlite3.connect('activities.db')
        cursor = conn.cursor()

        # Table for storing activities
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
                start_long REAL,
                moving_time INTEGER
            )
        ''')

        # Table for storing athlete tokens
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS athletes (
                athlete_id INTEGER PRIMARY KEY,
                refresh_token TEXT,
                access_token TEXT,
                expires_at INTEGER
            )
        ''')
        conn.commit()
        conn.close()
        print("Database initialized.")
    else:
        print("Database already exists.")

# Refresh access token
def refresh_access_token(client_id, client_secret, refresh_token):
    token_url = "https://www.strava.com/oauth/token"
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    response = requests.post(token_url, data=payload)
    if response.status_code == 200:
        tokens = response.json()
        return {
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "expires_at": tokens["expires_at"],
        }
    else:
        print(f"Failed to refresh token: {response.text}")
        return None

# Get valid access token for an athlete
def get_valid_access_token(athlete_id):
    conn = sqlite3.connect('activities.db')
    cursor = conn.cursor()
    cursor.execute('SELECT access_token, refresh_token, expires_at FROM athletes WHERE athlete_id = ?', (athlete_id,))
    athlete = cursor.fetchone()
    conn.close()

    if not athlete:
        return None

    access_token, refresh_token, expires_at = athlete
    current_time = int(time.time())

    if current_time >= expires_at:
        # Refresh token if expired
        tokens = refresh_access_token(CLIENT_ID, CLIENT_SECRET, refresh_token)
        if tokens:
            conn = sqlite3.connect('activities.db')
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE athletes
                SET access_token = ?, refresh_token = ?, expires_at = ?
                WHERE athlete_id = ?
            ''', (tokens["access_token"], tokens["refresh_token"], tokens["expires_at"], athlete_id))
            conn.commit()
            conn.close()
            return tokens["access_token"]
        else:
            return None
    else:
        return access_token

# Fetch and store activities
def fetch_and_store_activities(athlete_id, access_token):
    activities_url = "https://www.strava.com/api/v3/athlete/activities"
    headers = {"Authorization": f"Bearer {access_token}"}

    page = 1
    while True:
        response = requests.get(activities_url, headers=headers, params={"page": page, "per_page": 200})
        if response.status_code != 200:
            print(f"Failed to fetch activities for athlete {athlete_id}: {response.text}")
            break

        activities = response.json()
        if not activities:
            break

        conn = sqlite3.connect('activities.db')
        cursor = conn.cursor()

        for activity in activities:
            start_latlng = activity.get('start_latlng')
            if not start_latlng or len(start_latlng) < 2:
                continue

            cursor.execute('''
                INSERT OR IGNORE INTO activities (
                    athlete_id, activity_id, name, start_date_local, distance, type, start_lat, start_long, moving_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                athlete_id,
                activity.get('id'),
                activity.get('name'),
                activity.get('start_date_local'),
                activity.get('distance'),
                activity.get('type'),
                start_latlng[0],
                start_latlng[1],
                activity.get('moving_time'),
            ))

        conn.commit()
        conn.close()
        page += 1

@app.route('/')
def home():
    return """
    <h1>Strava API Demo</h1>
    <a href="/authorize"><button>Connect to Strava</button></a>
    """

@app.route('/authorize')
def authorize():
    # Redirect to Strava's OAuth page
    auth_url = (
        f"https://www.strava.com/oauth/authorize?client_id={CLIENT_ID}&response_type=code"
        f"&redirect_uri={REDIRECT_URI}&approval_prompt=force&scope=read,activity:read"
    )
    return redirect(auth_url)

@app.route('/callback')
def callback():
    # Handle callback from Strava
    code = request.args.get('code')
    token_url = "https://www.strava.com/oauth/token"
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
    }
    response = requests.post(token_url, data=payload)
    response_data = response.json()

    if "access_token" in response_data:
        athlete_id = response_data["athlete"]["id"]
        access_token = response_data["access_token"]
        refresh_token = response_data["refresh_token"]
        expires_at = response_data["expires_at"]

        conn = sqlite3.connect('activities.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO athletes (athlete_id, refresh_token, access_token, expires_at)
            VALUES (?, ?, ?, ?)
        ''', (athlete_id, refresh_token, access_token, expires_at))
        conn.commit()
        conn.close()

        return "<h1>Authorization Successful!</h1><a href='/activities'><button>Fetch Activities</button></a>"
    else:
        return "<h1>Authorization Failed.</h1>"

@app.route('/activities')
def get_activities():
    conn = sqlite3.connect('activities.db')
    cursor = conn.cursor()
    cursor.execute('SELECT athlete_id FROM athletes')
    athlete_ids = [row[0] for row in cursor.fetchall()]
    conn.close()

    for athlete_id in athlete_ids:
        access_token = get_valid_access_token(athlete_id)
        if access_token:
            fetch_and_store_activities(athlete_id, access_token)

    return "Activities fetched and stored for all athletes."

@app.route('/reset_db')
def reset_db():
    if os.path.exists('activities.db'):
        os.remove('activities.db')
    init_db()
    return "Database has been reset and initialized."

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)