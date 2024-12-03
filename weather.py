import requests
import sqlite3
import os
from datetime import datetime
from flask import Flask
import matplotlib.pyplot as plt

# OpenWeatherMap API Key
API_KEY = "d0c7b342f4d12a569d5f934019090b11"
BASE_URL = "https://api.openweathermap.org/data/2.5/weather"

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

def fetch_weather_data(lat, lon):
    """Fetch current weather data for a specific latitude and longitude."""
    params = {
        'lat': lat,
        'lon': lon,
        'appid': API_KEY,
        'units': 'metric'  # Use Celsius for temperature
    }
    response = requests.get(BASE_URL, params=params)
    if response.status_code != 200:
        print(f"Failed to fetch weather data: {response.status_code}")
        print(f"Response: {response.text}")
        return None

    return response.json()

def store_weather_data(activity_id, weather_data):
    """Store weather data into the SQLite database."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR IGNORE INTO weather (
            activity_id, temperature, humidity, wind_speed, 
            weather_main, weather_description, timezone, timezone_offset
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        activity_id,
        weather_data.get('main', {}).get('temp'),
        weather_data.get('main', {}).get('humidity'),
        weather_data.get('wind', {}).get('speed'),
        weather_data.get('weather', [{}])[0].get('main'),
        weather_data.get('weather', [{}])[0].get('description'),
        weather_data.get('timezone'),
        weather_data.get('timezone_offset')
    ))
    conn.commit()
    conn.close()
    print(f"Weather data for activity {activity_id} stored.")

def process_activities_weather():
    """Fetch weather data for each activity and store it in the database."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT activity_id, start_lat, start_long FROM activities')
    activities = cursor.fetchall()
    conn.close()
    
    for activity_id, lat, lon in activities:
        if lat is not None and lon is not None:
            print(f"Fetching weather data for activity {activity_id}...")
            weather_data = fetch_weather_data(lat, lon)
            if weather_data:
                store_weather_data(activity_id, weather_data)

def setup_weather_routes(app):
    """Define weather-related routes."""
    
    @app.route('/process_weather')
    def process_weather():
        """Fetch and store weather data for all activities."""
        process_activities_weather()
        return "Weather data fetched and stored."

    @app.route('/weather_graph')
    def weather_graph():
        """Generate and display a graph of activity distance by weather condition."""
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # Fetch activity and weather data
        cursor.execute('''
            SELECT a.name, a.distance, a.start_date_local, w.weather_main
            FROM activities AS a
            JOIN weather AS w
            ON a.activity_id = w.activity_id
        ''')
        data = cursor.fetchall()
        conn.close()

        # Organize data based on weather conditions
        weather_categories = {'Sunny': 0, 'Rainy': 0}
        for _, distance, _, weather in data:
            if weather in ['Clear', 'Sunny']:
                weather_categories['Sunny'] += distance
            elif weather in ['Rain', 'Drizzle']:
                weather_categories['Rainy'] += distance

        # Create the graph
        labels = list(weather_categories.keys())
        values = list(weather_categories.values())

        fig, ax = plt.subplots()
        ax.bar(labels, values, color=['gold', 'blue'])
        ax.set_title('Activity Distance by Weather Condition')
        ax.set_ylabel('Distance (meters)')
        ax.set_xlabel('Weather Condition')

        # Display the graph
        plt.show()
        return "Graph displayed successfully."

# Initialize Flask app
app = Flask(__name__)

# Set up routes
setup_weather_routes(app)

if __name__ == '__main__':
    init_weather_db()  # Initialize the database
    app.run(debug=True)
