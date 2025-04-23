import os
import requests
from datetime import datetime
from flask import Flask, jsonify

app = Flask(__name__)

OWM_API_KEY   = os.getenv("OPENWEATHER_API_KEY")
WEBHOOK_URL  = os.getenv("DISCORD_WEBHOOK_URL")
CITY         = os.getenv("CITY_NAME", "Seoul,KR")

def fetch_weather(api_key: str, city: str) -> dict:
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {"q": city, "appid": api_key, "units": "metric", "lang": "kr"}
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    return resp.json()

def build_discord_payload(weather: dict) -> dict:
    desc     = weather["weather"][0]["description"].capitalize()
    temp     = weather["main"]["temp"]
    feels    = weather["main"]["feels_like"]
    humidity = weather["main"]["humidity"]
    icon     = weather["weather"][0]["icon"]
    icon_url = f"https://openweathermap.org/img/wn/{icon}@2x.png"
    title    = f"{CITY} 오늘의 날씨 ({datetime.now().strftime('%Y-%m-%d')})"
    embed = {
        "title": title,
        "description": desc,
        "color": 0x3498db,
        "thumbnail": {"url": icon_url},
        "fields": [
            {"name": "🌡️ 온도", "value": f"{temp}°C", "inline": True},
            {"name": "🤗 체감", "value": f"{feels}°C", "inline": True},
            {"name": "💧 습도", "value": f"{humidity}%", "inline": True},
        ],
        "footer": {"text": "Powered by OpenWeatherMap"}
    }
    return {"embeds": [embed]}

def send_to_discord(webhook_url: str, payload: dict):
    resp = requests.post(webhook_url, json=payload)
    resp.raise_for_status()

@app.route("/", methods=["GET"])
def handler():
    # 실행
    weather = fetch_weather(OWM_API_KEY, CITY)
    payload = build_discord_payload(weather)
    send_to_discord(WEBHOOK_URL, payload)
    return jsonify({"status":"sent"}), 200

if __name__ == "__main__":
    # 로컬 테스트용
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",8080)))
