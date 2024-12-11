import requests
import sqlite3
import os
import time
import csv
import matplotlib
import matplotlib.pyplot as plt
from flask import Flask, request, redirect, render_template_string, send_from_directory, flash

matplotlib.use('Agg')

CLIENT_ID = "141007"
CLIENT_SECRET = "052da5de5f06be8d811655a36f081cfad12ce338"
REDIRECT_URI = "http://127.0.0.1:5000/callback"

API_KEY = "4d21ed7c97869390f4c195badb4c451c"

DB_FILE = 'activities.db'

app = Flask(__name__)
app.secret_key = os.urandom(24)

def init_db():
    if not os.path.exists(DB_FILE):
        conn = sqlite3.connect(DB_FILE)
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
                start_long REAL,
                moving_time INTEGER
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS athletes (
                athlete_id INTEGER PRIMARY KEY,
                refresh_token TEXT,
                access_token TEXT,
                expires_at INTEGER
            )
        ''')

        # Weather table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS weather (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                activity_id INTEGER UNIQUE,
                temperature REAL,
                humidity REAL,
                wind_speed REAL,
                weather_main TEXT,
                weather_description TEXT,
                timezone INTEGER,
                timezone_offset INTEGER,
                FOREIGN KEY (activity_id) REFERENCES activities (activity_id)
            )
        ''')

        conn.commit()
        conn.close()
        print("Database initialized.")
    else:
        print("Database already exists.")

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

def get_valid_access_token(athlete_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT access_token, refresh_token, expires_at FROM athletes WHERE athlete_id = ?', (athlete_id,))
    athlete = cursor.fetchone()
    conn.close()

    if not athlete:
        return None

    access_token, refresh_token, expires_at = athlete
    current_time = int(time.time())

    if current_time >= expires_at:
        tokens = refresh_access_token(CLIENT_ID, CLIENT_SECRET, refresh_token)
        if tokens:
            conn = sqlite3.connect(DB_FILE)
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

        conn = sqlite3.connect(DB_FILE)
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

def fetch_historical_weather(lat, lon, timestamp):
    historical_url = "https://api.openweathermap.org/data/3.0/onecall/timemachine"
    params = {
        'lat': lat,
        'lon': lon,
        'dt': int(timestamp),
        'appid': API_KEY,
        'units': 'metric'
    }
    try:
        response = requests.get(historical_url, params=params)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error fetching historical weather data: {e}")
        return None

def store_weather_data(activity_id, weather_data):
    if not weather_data or 'data' not in weather_data:
        print(f"No valid weather data available for activity {activity_id}")
        return

    try:
        current_weather = weather_data['data'][0]
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT OR IGNORE INTO weather (
                activity_id, temperature, humidity, wind_speed, 
                weather_main, weather_description, timezone, timezone_offset
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            activity_id,
            current_weather.get('temp'),
            current_weather.get('humidity'),
            current_weather.get('wind_speed'),
            current_weather.get('weather', [{}])[0].get('main', 'Unknown'),
            current_weather.get('weather', [{}])[0].get('description', 'Unknown'),
            weather_data.get('timezone', 'Unknown'),
            weather_data.get('timezone_offset', 0)
        ))

        conn.commit()
    except sqlite3.Error as e:
        print(f"Error storing weather data for activity {activity_id}: {e}")
    except KeyError as e:
        print(f"Missing expected data in weather response: {e}")
    finally:
        if conn:
            conn.close()

def process_activities_weather():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT activity_id, start_lat, start_long, strftime("%s", start_date_local) FROM activities')
    activities = cursor.fetchall()
    conn.close()
    
    for activity_id, lat, lon, timestamp in activities:
        if lat is None or lon is None or (lat == 0 and lon == 0):
            print(f"Skipping activity {activity_id} due to invalid coordinates")
            continue

        print(f"Fetching weather data for Activity ID: {activity_id}, Coordinates: ({lat}, {lon}), Timestamp: {timestamp}")
        weather_data = fetch_historical_weather(lat, lon, timestamp)
        
        if weather_data:
            store_weather_data(activity_id, weather_data)
        else:
            print(f"Failed to fetch weather data for activity {activity_id}")

    # Added this to write data to a file to satisfy grading ruberic
    os.makedirs('static', exist_ok=True)

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    distance_query = '''
        SELECT 
            w.weather_description, 
            AVG(a.distance) as avg_distance,
            COUNT(a.activity_id) as activity_count
        FROM activities AS a
        JOIN weather AS w ON a.activity_id = w.activity_id
        GROUP BY w.weather_description
        ORDER BY avg_distance DESC
    '''
    cursor.execute(distance_query)
    distance_data = cursor.fetchall()

    moving_time_query = '''
        SELECT 
            w.weather_description, 
            AVG(a.moving_time) as avg_moving_time,
            COUNT(a.activity_id) as activity_count
        FROM activities AS a
        JOIN weather AS w ON a.activity_id = w.activity_id
        GROUP BY w.weather_description
        ORDER BY avg_moving_time DESC
    '''
    cursor.execute(moving_time_query)
    moving_time_data = cursor.fetchall()
    conn.close()

    distance_csv_path = 'static/average_distance_by_weather.csv'
    with open(distance_csv_path, 'w', newline='') as csvfile:
        csvwriter = csv.writer(csvfile)
        csvwriter.writerow(['Weather Description', 'Average Distance (m)', 'Activity Count'])
        for row in distance_data:
            csvwriter.writerow(row)

    moving_time_csv_path = 'static/average_moving_time_by_weather.csv'
    with open(moving_time_csv_path, 'w', newline='') as csvfile:
        csvwriter = csv.writer(csvfile)
        csvwriter.writerow(['Weather Description', 'Average Moving Time (sec)', 'Activity Count'])
        for row in moving_time_data:
            csvwriter.writerow(row)

    print("CSV files exported successfully.")

@app.route('/')
def landing_page():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(DISTINCT athlete_id) FROM athletes')
    athlete_count = cursor.fetchone()[0]
    conn.close()

    html = '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>XC Timekeepers</title>
        <!-- Bootswatch Minty Theme -->
        <link rel="stylesheet" href="https://stackpath.bootstrapcdn.com/bootswatch/4.5.2/minty/bootstrap.min.css">
        <style>
            body {
                font-family: Arial, sans-serif;
            }
            footer {
                margin-top: 20px;
                font-size: 0.8em;
                color: #666;
            }
            .container {
                margin-top: 30px;
            }
            .alert {
                font-size: 1.2em;
            }
            .navbar {
                margin-bottom: 20px;
                justify-content: center;
            }
            .navbar-brand {
                font-weight: bold;
            }
        </style>
    </head>
    <body>
        <!-- Navbar -->
        <nav class="navbar navbar-expand-lg navbar-light bg-success">
            <a class="navbar-brand text-white" href="/">SI 206 - XC Timekeepers</a>
        </nav>

        <div class="container">
            <header class="text-center">
                <h2>How weather conditions affect distance & moving time</h2>
                <p>Join our interactive study!</p>
                <p><strong>Total Registered Athletes:</strong> {{ athlete_count }}</p>
            </header>

            <!-- Flash Messages -->
            <div class="container">
                {% with messages = get_flashed_messages(with_categories=True) %}
                {% if messages %}
                    {% for category, message in messages %}
                    <div class="alert alert-dismissible {{ 'alert-' + category }} text-center">
                        {{ message }}
                    </div>
                    {% endfor %}
                {% endif %}
                {% endwith %}
            </div>

            <div class="text-center">
                <a href="/authorize" class="btn btn-success btn-lg m-2">1. Authorize Strava</a>
                <a href="/activities" class="btn btn-primary btn-lg m-2">2. Fetch Activities</a>
                <a href="/process_weather" class="btn btn-primary btn-lg m-2">3. Process Weather</a>
                <a href="/weather_graphs" class="btn btn-success btn-lg m-2">4. View Weather Graph</a>
            </div>
        </div>

        <footer class="text-center">
            SI 206 Final Project | James Prestage & Jack Kelke
        </footer>

        <!-- Bootstrap JS and dependencies -->
        <script src="https://code.jquery.com/jquery-3.5.1.slim.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/@popperjs/core@2.9.2/dist/umd/popper.min.js"></script>
        <script src="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/js/bootstrap.min.js"></script>
    </body>
    </html>
    '''
    
    return render_template_string(html, athlete_count=athlete_count)

@app.route('/authorize')
def authorize_strava():
    auth_url = f'https://www.strava.com/oauth/authorize?client_id={CLIENT_ID}&response_type=code&redirect_uri={REDIRECT_URI}&approval_prompt=force&scope=read,activity:read_all'
    return redirect(auth_url)

@app.route('/callback')
def strava_callback():
    code = request.args.get('code')
    if code:
        token_url = 'https://www.strava.com/oauth/token'
        payload = {
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'code': code,
            'grant_type': 'authorization_code',
        }
        response = requests.post(token_url, data=payload)
        if response.status_code == 200:
            tokens = response.json()
            access_token = tokens['access_token']
            refresh_token = tokens['refresh_token']
            athlete_id = tokens['athlete']['id']

            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO athletes (athlete_id, access_token, refresh_token, expires_at)
                VALUES (?, ?, ?, ?)
            ''', (athlete_id, access_token, refresh_token, tokens['expires_at']))
            conn.commit()
            conn.close()
            flash('Strava authorization successful!', 'success')
        else:
            flash('Failed to authorize with Strava', 'danger')
    else:
        flash('No authorization code received', 'danger')

    return redirect('/')

@app.route('/process_weather')
def process_weather():
    try:
        process_activities_weather()
        flash('Weather data successfully processed for activities!', 'success')
    except Exception as e:
        flash(f'Error processing weather data: {str(e)}', 'danger')
    return redirect('/')

@app.route('/activities')
def fetch_activities():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT athlete_id FROM athletes')
        athletes = cursor.fetchall()
        conn.close()

        for athlete_id in athletes:
            athlete_id = athlete_id[0]
            access_token = get_valid_access_token(athlete_id)
            if access_token:
                fetch_and_store_activities(athlete_id, access_token)

        flash('Activities successfully fetched and stored!', 'success')
    except Exception as e:
        flash(f'Error fetching activities: {str(e)}', 'danger')
    return redirect('/')

@app.route('/weather_graphs', methods=['GET'])
def weather_graphs():
    """Generate two graphs: average distance and average moving time by weather description."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # IMPORTANT: Only activity data from the last year can currently be used with OpenWeatherMap API
    query1 = '''
        SELECT w.weather_description, 
            AVG(a.distance) as avg_distance
        FROM activities AS a
        JOIN weather AS w ON a.activity_id = w.activity_id
        GROUP BY w.weather_description
        ORDER BY avg_distance DESC
    '''
    cursor.execute(query1)
    data_distance = cursor.fetchall()

    query2 = '''
        SELECT w.weather_description, 
            AVG(a.moving_time) as avg_moving_time
        FROM activities AS a
        JOIN weather AS w ON a.activity_id = w.activity_id
        GROUP BY w.weather_description
        ORDER BY avg_moving_time DESC
    '''
    cursor.execute(query2)
    data_moving_time = cursor.fetchall()
    conn.close()

    if not data_distance or not data_moving_time:
        return "No data available for graphs."

    try:
        weather_descriptions_distance, avg_distances = zip(*data_distance)
        fig1, ax1 = plt.subplots(figsize=(12, 6))
        ax1.bar(weather_descriptions_distance, avg_distances, color='skyblue')
        ax1.set_title('Average Activity Distance by Weather Description')
        ax1.set_ylabel('Average Distance (meters)')
        ax1.set_xlabel('Weather Description')
        ax1.set_xticks(range(len(weather_descriptions_distance)))
        ax1.set_xticklabels(weather_descriptions_distance, rotation=45, ha='right')
        plot_path1 = 'static/weather_graph_avg_distance.png'
        plt.tight_layout()
        plt.savefig(plot_path1)
        plt.close(fig1)
    except Exception as e:
        return f"Failed to generate Average Distance Graph: {e}"

    try:
        weather_descriptions_time, avg_moving_time = zip(*data_moving_time)
        fig2, ax2 = plt.subplots(figsize=(12, 6))
        ax2.bar(weather_descriptions_time, avg_moving_time, color='orange')
        ax2.set_title('Average Moving Time by Weather Description')
        ax2.set_ylabel('Average Moving Time (seconds)')
        ax2.set_xlabel('Weather Description')
        ax2.set_xticks(range(len(weather_descriptions_time)))
        ax2.set_xticklabels(weather_descriptions_time, rotation=45, ha='right')
        plot_path2 = 'static/weather_graph_avg_time.png'
        plt.tight_layout()
        plt.savefig(plot_path2)
        plt.close(fig2)
    except Exception as e:
        return f"Failed to generate Average Moving Time Graph: {e}"

    html_template = f"""
    <h1>Weather Analysis Graphs</h1>
    <div>
        <h2>Average Activity Distance by Weather Description</h2>
        <img src="/{plot_path1}" alt="Average Distance Graph">
    </div>
    <div>
        <h2>Average Moving Time by Weather Description</h2>
        <img src="/{plot_path2}" alt="Average Moving Time Graph">
    </div>
    """
    return html_template

@app.route('/static/<path:filename>')
def static_files(filename):
    """Serve static files from the static folder."""
    return send_from_directory('static', filename)

@app.route('/reset', methods=['GET', 'POST'])
def reset_database():
    """Delete the database file and reset the application."""
    try:
        if os.path.exists(DB_FILE):
            os.remove(DB_FILE)
            init_db()
            flash('Database reset successfully!', 'success')
        else:
            flash('Database file does not exist, nothing to reset.', 'info')
    except Exception as e:
        flash(f'Error resetting database: {str(e)}', 'danger')
    return redirect('/')

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
