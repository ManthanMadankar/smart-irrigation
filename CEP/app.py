from flask import Flask, render_template, request, send_file, session
import pickle
import numpy as np
import requests
from datetime import datetime, timedelta, date
import os

app = Flask(__name__)
app.secret_key = "smartirrigate_secret"  # needed for session

model = pickle.load(open('irrigation_model.pkl', 'rb'))

API_KEY = "4ad5dac7e80eaae2c8fee266fa35043e"

# ── Translation tables ──────────────────────────────────────────────────────

LANG = {
    "en": {
        "sheet":       "Irrigation Report",
        "col_day":     "Day",
        "col_irr":     "Irrigation",
        "col_water":   "Water (Litres)",
        "irr_req":     "Irrigation Required",
        "irr_no":      "No Irrigation",
        "days": {
            "Monday":"Monday","Tuesday":"Tuesday","Wednesday":"Wednesday",
            "Thursday":"Thursday","Friday":"Friday","Saturday":"Saturday","Sunday":"Sunday"
        }
    },
    "hi": {
        "sheet":       "सिंचाई रिपोर्ट",
        "col_day":     "दिन",
        "col_irr":     "सिंचाई",
        "col_water":   "पानी (लीटर)",
        "irr_req":     "सिंचाई आवश्यक",
        "irr_no":      "सिंचाई नहीं",
        "days": {
            "Monday":"सोमवार","Tuesday":"मंगलवार","Wednesday":"बुधवार",
            "Thursday":"गुरुवार","Friday":"शुक्रवार","Saturday":"शनिवार","Sunday":"रविवार"
        }
    },
    "mr": {
        "sheet":       "सिंचन अहवाल",
        "col_day":     "दिवस",
        "col_irr":     "सिंचन",
        "col_water":   "पाणी (लिटर)",
        "irr_req":     "सिंचन आवश्यक",
        "irr_no":      "सिंचन नाही",
        "days": {
            "Monday":"सोमवार","Tuesday":"मंगळवार","Wednesday":"बुधवार",
            "Thursday":"गुरुवार","Friday":"शुक्रवार","Saturday":"शनिवार","Sunday":"रविवार"
        }
    }
}

ALERT_TRANS = {
    "en": {
        "Irrigation Required Today":    "Irrigation Required Today",
        "Irrigation Recommended Soon":  "Irrigation Recommended Soon",
        "No Irrigation Needed":         "No Irrigation Needed"
    },
    "hi": {
        "Irrigation Required Today":    "आज सिंचाई आवश्यक है",
        "Irrigation Recommended Soon":  "जल्द सिंचाई की सिफारिश",
        "No Irrigation Needed":         "सिंचाई की आवश्यकता नहीं"
    },
    "mr": {
        "Irrigation Required Today":    "आज सिंचन आवश्यक आहे",
        "Irrigation Recommended Soon":  "लवकरच सिंचन शिफारस",
        "No Irrigation Needed":         "सिंचनाची गरज नाही"
    }
}

# ── Helpers ─────────────────────────────────────────────────────────────────

def get_weather(city):
    url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={API_KEY}&units=metric"
    response = requests.get(url)
    data = response.json()
    try:
        temperature = data["main"]["temp"]
        humidity = data["main"]["humidity"]
        rainfall = data.get("rain", {}).get("1h", 0)
    except:
        temperature = 30
        humidity = 60
        rainfall = 0
    return temperature, humidity, rainfall


def get_forecast(city):
    url = f"https://api.openweathermap.org/data/2.5/forecast?q={city}&appid={API_KEY}&units=metric"
    response = requests.get(url)
    data = response.json()

    forecast_days = []
    for item in data["list"]:
        if "12:00:00" in item["dt_txt"]:
            date_str = item["dt_txt"].split(" ")[0]
            day_name = datetime.strptime(date_str, "%Y-%m-%d").strftime("%A")
            temp = item["main"]["temp"]
            humidity = item["main"]["humidity"]
            rainfall = item.get("rain", {}).get("3h", 0)
            forecast_days.append({
                "day": day_name,
                "temp": temp,
                "humidity": humidity,
                "rainfall": rainfall
            })
        if len(forecast_days) == 8:
            break

    return forecast_days


def build_excel(lang, alert, water_needed, week_prediction, graph_path):
    """Generate Excel report in the requested language and return file path."""
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image

    t = LANG.get(lang, LANG["en"])

    wb = Workbook()
    ws = wb.active
    ws.title = t["sheet"]

    # Header row
    ws.append([t["col_day"], t["col_irr"], t["col_water"]])

    # Today row
    today_day_en = date.today().strftime("%A")
    today_day    = t["days"].get(today_day_en, today_day_en)
    today_alert  = ALERT_TRANS.get(lang, ALERT_TRANS["en"]).get(alert, alert)
    ws.append([today_day, today_alert, water_needed])

    # Next 6 days
    for day in week_prediction[1:]:
        day_name = t["days"].get(day["day"], day["day"])
        irr_text = t["irr_req"] if day["irrigation"] == "Irrigation Required" else t["irr_no"]
        ws.append([day_name, irr_text, day["water"]])

    # Embed graph image
    if os.path.exists(graph_path):
        img = Image(graph_path)
        img.anchor = "E2"
        ws.add_image(img)

    excel_path = os.path.join("static", f"irrigation_report_{lang}.xlsx")
    wb.save(excel_path)
    return excel_path

# ── Routes ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/predict', methods=['POST'])
def predict():
    location   = request.form['location']
    soil_type  = int(request.form['soil_type'])
    crop_stage = int(request.form['crop_stage'])
    field_size = float(request.form['field_size']) if request.form['field_size'] else 1.0

    temperature, humidity, rainfall = get_weather(location)

    features       = np.array([[temperature, humidity, rainfall, soil_type, crop_stage]])
    irrigation_pred = model.predict(features)[0]

    # Water per acre by crop stage
    if crop_stage == 1:
        water_per_acre = 300
    elif crop_stage == 2:
        water_per_acre = 500
    else:
        water_per_acre = 400

    # Today decision
    if irrigation_pred == 1 or (humidity < 35 and rainfall < 5):
        alert        = "Irrigation Required Today"
        water_needed = round(water_per_acre * field_size, 2)
    elif humidity < 45:
        alert        = "Irrigation Recommended Soon"
        water_needed = round((water_per_acre * field_size) * 0.5, 2)
    else:
        alert        = "No Irrigation Needed"
        water_needed = 0

    forecast_weather = get_forecast(location)
    today_date       = date.today()
    week_prediction  = []

    for i in range(7):
        if i < len(forecast_weather):
            day_data = forecast_weather[i]
        else:
            last_day = forecast_weather[-1]
            temp  = last_day["temp"]     + np.random.randint(-2, 3)
            hum   = max(0, min(100, last_day["humidity"]  + np.random.randint(-5, 6)))
            rain  = max(0, last_day["rainfall"] + np.random.randint(0, 3))
            day_data = {"day": "", "temp": temp, "humidity": hum, "rainfall": rain}

        day_name = (today_date + timedelta(days=i)).strftime("%A")
        temp = day_data["temp"]
        hum  = day_data["humidity"]
        rain = day_data["rainfall"]

        features   = np.array([[temp, hum, rain, soil_type, crop_stage]])
        irrigation = model.predict(features)[0]

        if crop_stage == 1:
            base_water = 300
        elif crop_stage == 2:
            base_water = 500
        else:
            base_water = 400

        temp_factor     = (temp - 25) * 8
        humidity_factor = hum * 2
        rain_factor     = rain * 10

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
            "day":        day_name,
            "irrigation": irrigation_status,
            "water":      water
        })

    # ── Graph ────────────────────────────────────────────────────────────────
    import matplotlib.pyplot as plt

    days         = [day["day"]   for day in week_prediction]
    water_values = [day["water"] for day in week_prediction]

    plt.figure()
    plt.plot(days, water_values, marker='o')
    plt.title("6-Day Irrigation Water Requirement")
    plt.xlabel("Days")
    plt.ylabel("Water (Litres)")
    plt.xticks(rotation=30)
    plt.grid()

    graph_path = os.path.join("static", "water_graph.png")
    plt.savefig(graph_path)
    plt.close()

    # ── Default English Excel ────────────────────────────────────────────────
    build_excel("en", alert, water_needed, week_prediction, graph_path)

    # Store data in session so /download_excel can regenerate in any language
    session['excel_data'] = {
        "alert":           alert,
        "water_needed":    water_needed,
        "week_prediction": week_prediction,
        "graph_path":      graph_path
    }

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
        graph="water_graph.png",
        excel_file="irrigation_report_en.xlsx"
    )


@app.route('/download_excel')
def download_excel():
    """Generate and serve Excel in the requested language."""
    lang = request.args.get("lang", "en")
    if lang not in LANG:
        lang = "en"

    data = session.get('excel_data')
    if not data:
        # Fallback if session expired
        return "Session expired. Please go back and submit the form again.", 400

    excel_path = build_excel(
        lang,
        data["alert"],
        data["water_needed"],
        data["week_prediction"],
        data["graph_path"]
    )

    filename_map = {
        "en": "irrigation_report_english.xlsx",
        "hi": "irrigation_report_hindi.xlsx",
        "mr": "irrigation_report_marathi.xlsx"
    }

    return send_file(
        excel_path,
        as_attachment=True,
        download_name=filename_map.get(lang, "irrigation_report.xlsx")
    )


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
