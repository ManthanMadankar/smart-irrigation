from flask import Flask, render_template, request, send_file, session
import pickle
import numpy as np
import requests
from datetime import datetime, timedelta, date
import os

#  IMPORTANT for Render (no display server)
import matplotlib
matplotlib.use('Agg')

app = Flask(__name__)
app.secret_key = "smartirrigate_secret"

#  Load model safely
model_path = os.path.join(os.path.dirname(__file__), 'irrigation_model.pkl')
with open(model_path, 'rb') as f:
    model = pickle.load(f)

API_KEY = "4ad5dac7e80eaae2c8fee266fa35043e"

# ================= WEATHER =================

def get_weather(city):
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={API_KEY}&units=metric"
        response = requests.get(url, timeout=5)
        data = response.json()

        temperature = data["main"]["temp"]
        humidity = data["main"]["humidity"]
        rainfall = data.get("rain", {}).get("1h", 0)

    except:
        temperature = 30
        humidity = 60
        rainfall = 0

    return temperature, humidity, rainfall


def get_forecast(city):
    try:
        url = f"https://api.openweathermap.org/data/2.5/forecast?q={city}&appid={API_KEY}&units=metric"
        response = requests.get(url, timeout=5)
        data = response.json()

        forecast_days = []
        for item in data["list"]:
            if "12:00:00" in item["dt_txt"]:
                date_str = item["dt_txt"].split(" ")[0]
                day_name = datetime.strptime(date_str, "%Y-%m-%d").strftime("%A")

                forecast_days.append({
                    "day": day_name,
                    "temp": item["main"]["temp"],
                    "humidity": item["main"]["humidity"],
                    "rainfall": item.get("rain", {}).get("3h", 0)
                })

            if len(forecast_days) == 8:
                break

        return forecast_days

    except:
        return []


# ================= ROUTES =================

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/predict', methods=['POST'])
def predict():
    try:
        location   = request.form['location']
        soil_type  = int(request.form['soil_type'])
        crop_stage = int(request.form['crop_stage'])
        field_size = float(request.form['field_size']) if request.form['field_size'] else 1.0

        temperature, humidity, rainfall = get_weather(location)

        features = np.array([[temperature, humidity, rainfall, soil_type, crop_stage]])
        irrigation_pred = model.predict(features)[0]

        # ===== Water per acre =====
        if crop_stage == 1:
            water_per_acre = 300
        elif crop_stage == 2:
            water_per_acre = 500
        else:
            water_per_acre = 400

        # ===== TODAY =====
        if irrigation_pred == 1 or (humidity < 35 and rainfall < 5):
            alert = "Irrigation Required Today"
            water_needed = round(water_per_acre * field_size, 2)
        elif humidity < 45:
            alert = "Irrigation Recommended Soon"
            water_needed = round((water_per_acre * field_size) * 0.5, 2)
        else:
            alert = "No Irrigation Needed"
            water_needed = 0

        forecast_weather = get_forecast(location)
        today_date = date.today()

        week_prediction = []

        for i in range(7):

            if i < len(forecast_weather):
                day_data = forecast_weather[i]
            else:
                last_day = forecast_weather[-1] if forecast_weather else {
                    "temp": 30, "humidity": 60, "rainfall": 0
                }
                temp = last_day["temp"] + np.random.randint(-2, 3)
                hum = max(0, min(100, last_day["humidity"] + np.random.randint(-5, 6)))
                rain = max(0, last_day["rainfall"] + np.random.randint(0, 3))
                day_data = {"temp": temp, "humidity": hum, "rainfall": rain}

            day_name = (today_date + timedelta(days=i)).strftime("%A")

            temp = day_data["temp"]
            hum  = day_data["humidity"]
            rain = day_data["rainfall"]

            features = np.array([[temp, hum, rain, soil_type, crop_stage]])
            irrigation = model.predict(features)[0]

            if crop_stage == 1:
                base_water = 300
            elif crop_stage == 2:
                base_water = 500
            else:
                base_water = 400

            temp_factor = (temp - 25) * 8
            humidity_factor = hum * 2
            rain_factor = rain * 10

            water = base_water + temp_factor - humidity_factor - rain_factor
            if water < 0:
                water = 0

            water = round(water * field_size, 2)

            if irrigation == 1:
                irrigation_status = "Irrigation Required"
                water = round(water)
            elif irrigation == 0 and hum < 40 and rain < 5:
                irrigation_status = "Irrigation Required"
                water = round(water * 0.5)
            else:
                irrigation_status = "No Irrigation"
                water = 0

            week_prediction.append({
                "day": day_name,
                "irrigation": irrigation_status,
                "water": water
            })

        
        # ===== GRAPH =====
        import matplotlib.pyplot as plt

        # Use BASE DIR (important for Render)
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))

        # Ensure static folder exists
        static_dir = os.path.join(BASE_DIR, "static")
        os.makedirs(static_dir, exist_ok=True)

        # Absolute path for saving
        graph_path = os.path.join(static_dir, "water_graph.png")

        days = [d["day"] for d in week_prediction]
        water_values = [d["water"] for d in week_prediction]

        plt.figure()
        plt.plot(days, water_values, marker='o')
        plt.title("6-Day Irrigation Water Requirement")
        plt.xticks(rotation=30)
        plt.grid()

        #  Important fix
        plt.savefig(graph_path, bbox_inches='tight')
        plt.close()

        return render_template(
            'result.html',
            location=location,
            soil_type=soil_type,
            crop_stage=crop_stage,
            temperature=temperature,
            humidity=humidity,
            rainfall=rainfall,
            irrigation=irrigation_pred,
            water_needed=water_needed,
            alert=alert,
            week_prediction=week_prediction,
            graph="water_graph.png"
        )

    except Exception as e:
        return f"Error: {str(e)}"


# ================= RUN =================

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
