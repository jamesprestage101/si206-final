import requests
import sqlite3
import os
from flask import Flask, send_from_directory, render_template_string
import matplotlib
import matplotlib.pyplot as plt

# Use a non-GUI backend for Matplotlib
matplotlib.use('Agg')

# As of December 5th 2024
# OpenWeatherMap API Key (James' API Key - currently awaiting a response from OpenWeatherMap to extend historical weather data range)
API_KEY = "84e21ea14bda415048a5852c8a6c9999"

# Historical Weather API URL
HISTORICAL_URL = "https://history.openweathermap.org/data/2.5/history/city"

# Database file
DB_FILE = 'activities.db'

def init_weather_db():
    """Initialize the weather table in the database if it doesn't exist."""
    if os.path.exists(DB_FILE):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
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
        print("Weather database initialized.")
    else:
        print("Database does not exist. Please run the Strava integration first.")

def fetch_historical_weather(lat, lon, timestamp):
    """Fetch historical weather data for a specific latitude, longitude, and timestamp."""
    params = {
        'lat': lat,
        'lon': lon,
        'type': 'hour',
        'start': int(timestamp),  # Ensure timestamp is an integer
        'cnt': 1,  # Number of timestamps to retrieve
        'appid': API_KEY,
        'units': 'metric'
    }
    
    try:
        response = requests.get(HISTORICAL_URL, params=params)
        response.raise_for_status()  # Raise an exception for bad status codes
        
        return response.json()
    except requests.RequestException as e:
        print(f"Error fetching historical weather data: {e}")
        print(f"Response content: {response.text if 'response' in locals() else 'No response'}")
        return None

def store_weather_data(activity_id, weather_data):
    """Store weather data into the SQLite database."""
    if not weather_data or 'list' not in weather_data or not weather_data['list']:
        print(f"No weather data available for activity {activity_id}")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    try:
        current_weather = weather_data['list'][0]
        
        cursor.execute('''
            INSERT OR IGNORE INTO weather (
                activity_id, temperature, humidity, wind_speed, 
                weather_main, weather_description, timezone, timezone_offset
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            activity_id,
            current_weather.get('main', {}).get('temp'),
            current_weather.get('main', {}).get('humidity'),
            current_weather.get('wind', {}).get('speed'),
            current_weather.get('weather', [{}])[0].get('main', 'Unknown'),
            current_weather.get('weather', [{}])[0].get('description', 'Unknown'),
            weather_data.get('city', {}).get('timezone', 0),
            0
        ))
        conn.commit()
        print(f"Weather data for activity {activity_id} stored successfully.")
    except Exception as e:
        print(f"Error storing weather data for activity {activity_id}: {e}")
    finally:
        conn.close()

def process_activities_weather():
    """Fetch historical weather data for each activity and store it in the database."""
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

def setup_weather_routes(app):
    """Define weather-related routes."""
    
    @app.route('/process_weather')
    def process_weather():
        """Fetch and store weather data for all activities."""
        process_activities_weather()
        return "Weather data fetched and stored."

    @app.route('/reset_weather_table', methods=['GET'])
    def reset_weather_table():
        """Delete and recreate the weather table, then fetch historical weather data."""
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # Drop the weather table
        cursor.execute('DROP TABLE IF EXISTS weather')
        conn.commit()
        conn.close()
        print("Weather table deleted.")

        # Recreate the weather table
        init_weather_db()
        print("Weather table recreated.")

        # Fetch historical weather data
        process_activities_weather()
        return "Weather table reset and historical data fetched."

    @app.route('/weather_graphs', methods=['GET'])
    def weather_graphs():
        """Generate two graphs: average distance and average moving time by weather description."""
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # IMPORTANT: Only activity data from the last year can currently be used with OpenWeatherMap API
        # Graph 1: Average activity distance by weather description
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

        # Graph 2: Average moving time by weather description
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

        # Create Graph 1: Average Distance
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

        # Create Graph 2: Average Moving Time
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

        # Rendering both the graphs on a single page
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

# Initialize Flask app
app = Flask(__name__)

# Set up routes
setup_weather_routes(app)

if __name__ == '__main__':
    # Create static directory if it doesn't exist
    if not os.path.exists('static'):
        os.makedirs('static')

    init_weather_db()  # Initialize the database
    app.run(debug=True)