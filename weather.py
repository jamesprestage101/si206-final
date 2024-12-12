import requests
import sqlite3
import os
import matplotlib
import matplotlib.pyplot as plt
from flask import Flask, send_from_directory
import csv

matplotlib.use('Agg')

# Updated API Key
API_KEY = "4d21ed7c97869390f4c195badb4c451c"

# Historical Weather API URL
HISTORICAL_URL = "https://api.openweathermap.org/data/3.0/onecall/timemachine"

# Database file
DB_FILE = 'activities.db'


def init_weather_db():
    if os.path.exists(DB_FILE):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Create weather description table (you'll notice it's similar to activity_types in strava.py!)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS weather_descriptions (
                description_id INTEGER PRIMARY KEY,
                description_name TEXT UNIQUE
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS weather (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                activity_id INTEGER UNIQUE,
                temperature REAL,
                humidity REAL,
                wind_speed REAL,
                description_id INTEGER,
                FOREIGN KEY (activity_id) REFERENCES activities (activity_id),
                FOREIGN KEY (description_id) REFERENCES weather_descriptions (description_id)
            )
        ''')
        conn.commit()
        conn.close()
        print("Weather database initialized.")
    else:
        print("Database does not exist. Please run the Strava integration first.")

def fetch_historical_weather(lat, lon, timestamp):
    params = {
        'lat': lat,
        'lon': lon,
        'dt': int(timestamp),
        'appid': API_KEY,
        'units': 'metric'
    }
    try:
        response = requests.get(HISTORICAL_URL, params=params)
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

        # Insert or get weather description
        weather_description = current_weather.get('weather', [{}])[0].get('description', 'Unknown')
        cursor.execute('INSERT OR IGNORE INTO weather_descriptions (description_name) VALUES (?)', (weather_description,))
        cursor.execute('SELECT description_id FROM weather_descriptions WHERE description_name = ?', (weather_description,))
        description_id = cursor.fetchone()[0]

        cursor.execute('''
            INSERT OR IGNORE INTO weather (
                activity_id, temperature, humidity, wind_speed, description_id
            ) VALUES (?, ?, ?, ?, ?)
        ''', (
            activity_id,
            current_weather.get('temp'),
            current_weather.get('humidity'),
            current_weather.get('wind_speed'),
            description_id
        ))

        conn.commit()
        print(f"Weather data for activity {activity_id} stored successfully.")
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

    os.makedirs('static', exist_ok=True)

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Query for average distance by weather description
    distance_query = '''
        SELECT 
            wd.description_name, 
            AVG(a.distance) as avg_distance,
            COUNT(a.activity_id) as activity_count
        FROM activities AS a
        JOIN weather AS w ON a.activity_id = w.activity_id
        JOIN weather_descriptions AS wd ON w.description_id = wd.description_id
        GROUP BY wd.description_name
        ORDER BY avg_distance DESC
    '''
    cursor.execute(distance_query)
    distance_data = cursor.fetchall()

    # Query for average moving time by weather description
    moving_time_query = '''
        SELECT 
            wd.description_name, 
            AVG(a.moving_time) as avg_moving_time,
            COUNT(a.activity_id) as activity_count
        FROM activities AS a
        JOIN weather AS w ON a.activity_id = w.activity_id
        JOIN weather_descriptions AS wd ON w.description_id = wd.description_id
        GROUP BY wd.description_name
        ORDER BY avg_moving_time DESC
    '''
    cursor.execute(moving_time_query)
    moving_time_data = cursor.fetchall()

    # Query for activity count by weather description
    activity_count_query = '''
        SELECT 
            wd.description_name, 
            COUNT(a.activity_id) as activity_count
        FROM activities AS a
        JOIN weather AS w ON a.activity_id = w.activity_id
        JOIN weather_descriptions AS wd ON w.description_id = wd.description_id
        GROUP BY wd.description_name
        ORDER BY activity_count DESC
    '''
    cursor.execute(activity_count_query)
    activity_count_data = cursor.fetchall()

    conn.close()

    # Export average distance data to CSV
    distance_csv_path = 'static/average_distance_by_weather.csv'
    with open(distance_csv_path, 'w', newline='') as csvfile:
        csvwriter = csv.writer(csvfile)
        csvwriter.writerow(['Weather Description', 'Average Distance (m)', 'Activity Count'])
        for row in distance_data:
            csvwriter.writerow(row)

    # Export average moving time data to CSV
    moving_time_csv_path = 'static/average_moving_time_by_weather.csv'
    with open(moving_time_csv_path, 'w', newline='') as csvfile:
        csvwriter = csv.writer(csvfile)
        csvwriter.writerow(['Weather Description', 'Average Moving Time (sec)', 'Activity Count'])
        for row in moving_time_data:
            csvwriter.writerow(row)

    # Export activity count data to CSV (the third graph we added after preliminary grading)
    activity_count_csv_path = 'static/activity_count_by_weather.csv'
    with open(activity_count_csv_path, 'w', newline='') as csvfile:
        csvwriter = csv.writer(csvfile)
        csvwriter.writerow(['Weather Description', 'Activity Count'])
        for row in activity_count_data:
            csvwriter.writerow(row)

    print("CSV files exported successfully.")
    
def setup_weather_routes(app):
    
    # When you first run this file you'll get a 404 error. Just go to /process_weather then /weather_graphs and ignore this.

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

        # Drop the weather and weather_descriptions tables
        cursor.execute('DROP TABLE IF EXISTS weather')
        cursor.execute('DROP TABLE IF EXISTS weather_descriptions')
        conn.commit()
        conn.close()
        print("Weather tables deleted.")

        # Recreate the weather tables
        init_weather_db()
        print("Weather tables recreated.")

        # Fetch historical weather data
        process_activities_weather()
        return "Weather tables reset and historical data fetched."

    @app.route('/weather_graphs', methods=['GET'])
    def weather_graphs():
        """Generate three visualizations: average distance (bar graph), average moving time (scatter plot), and a stack plot for activities count by weather description."""
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # Graph 1 Average activity distance by weather description
        query1 = '''
            SELECT wd.description_name, 
                AVG(a.distance) as avg_distance
            FROM activities AS a
            JOIN weather AS w ON a.activity_id = w.activity_id
            JOIN weather_descriptions AS wd ON w.description_id = wd.description_id
            GROUP BY wd.description_name
            ORDER BY avg_distance DESC
        '''
        cursor.execute(query1)
        data_distance = cursor.fetchall()

        # Graph 2 Average moving time by weather description
        query2 = '''
            SELECT wd.description_name, 
                AVG(a.moving_time) as avg_moving_time
            FROM activities AS a
            JOIN weather AS w ON a.activity_id = w.activity_id
            JOIN weather_descriptions AS wd ON w.description_id = wd.description_id
            GROUP BY wd.description_name
            ORDER BY avg_moving_time DESC
        '''
        cursor.execute(query2)
        data_moving_time = cursor.fetchall()

        # Graph 3 Activity count by weather description for stack plot
        query3 = '''
            SELECT wd.description_name, COUNT(a.activity_id) as activity_count
            FROM activities AS a
            JOIN weather AS w ON a.activity_id = w.activity_id
            JOIN weather_descriptions AS wd ON w.description_id = wd.description_id
            GROUP BY wd.description_name
            ORDER BY wd.description_name ASC
        '''
        cursor.execute(query3)
        data_activity_count = cursor.fetchall()
        conn.close()

        if not data_distance or not data_moving_time or not data_activity_count:
            return "No data available for graphs."

        # Create Graph 1 average distance (bar graph)
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

        # Graph 2 average moving time (scatter plot)
        try:
            weather_descriptions_time, avg_moving_time = zip(*data_moving_time)
            fig2, ax2 = plt.subplots(figsize=(12, 6))
            ax2.scatter(weather_descriptions_time, avg_moving_time, color='orange')
            ax2.set_title('Average Moving Time by Weather Description')
            ax2.set_ylabel('Average Moving Time (seconds)')
            ax2.set_xlabel('Weather Description')
            ax2.set_xticks(range(len(weather_descriptions_time)))
            ax2.set_xticklabels(weather_descriptions_time, rotation=45, ha='right')
            plot_path2 = 'static/weather_graph_avg_time_scatter.png'
            plt.tight_layout()
            plt.savefig(plot_path2)
            plt.close(fig2)
        except Exception as e:
            return f"Failed to generate Average Moving Time Scatter Plot: {e}"

        # Graph 3 activity count by weather description (stack plot)
        try:
            weather_descriptions_stack, activity_counts = zip(*data_activity_count)
            fig3, ax3 = plt.subplots(figsize=(12, 6))
            ax3.stackplot(range(len(weather_descriptions_stack)), activity_counts, labels=['Activity Count'], colors=['green'])
            ax3.set_title('Activity Count by Weather Description (Stack Plot)')
            ax3.set_ylabel('Activity Count')
            ax3.set_xlabel('Weather Description')
            ax3.set_xticks(range(len(weather_descriptions_stack)))
            ax3.set_xticklabels(weather_descriptions_stack, rotation=45, ha='right')
            ax3.legend(loc='upper left')
            plot_path3 = 'static/weather_graph_activity_count_stack.png'
            plt.tight_layout()
            plt.savefig(plot_path3)
            plt.close(fig3)
        except Exception as e:
            return f"Failed to generate Activity Count Stack Plot: {e}"

        # Rendering the graphs on one page
        html_template = f"""
        <h1>Weather Analysis Graphs</h1>
        <div>
            <h2>Average Activity Distance by Weather Description</h2>
            <img src="/{plot_path1}" alt="Average Distance Graph">
        </div>
        <div>
            <h2>Average Moving Time by Weather Description (Scatter Plot)</h2>
            <img src="/{plot_path2}" alt="Average Moving Time Scatter Plot">
        </div>
        <div>
            <h2>Activity Count by Weather Description (Stack Plot)</h2>
            <img src="/{plot_path3}" alt="Activity Count Stack Plot">
        </div>
        """
        return html_template

    @app.route('/static/<path:filename>')
    def static_files(filename):
        return send_from_directory('static', filename)

app = Flask(__name__)
setup_weather_routes(app)

if __name__ == '__main__':
    if not os.path.exists('static'):
        os.makedirs('static')

    init_weather_db()
    app.run(debug=True)