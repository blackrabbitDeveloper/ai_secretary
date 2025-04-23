# main.py
import os
import requests
import feedparser
import pytz
from google import genai
from datetime import datetime, timedelta
from flask import Flask, jsonify

app = Flask(__name__)

# ─── 환경변수 ─────────────────────────────────────────────────────────
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
GEMINI_API_KEY        = os.environ.get('GEMINI_API_KEY')
CITY               = os.getenv("CITY_NAME", "Seoul,KR")
DISCORD_WEBHOOK    = os.getenv("DISCORD_WEBHOOK_URL")
RSS_URL            = "http://feeds.bbci.co.uk/news/world/rss.xml"
TZ                 = pytz.timezone("Asia/Seoul")
# ────────────────────────────────────────────────────────────────────────

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-pro')

# 1) 날씨 조회
def fetch_weather():
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {"q": CITY, "appid": OPENWEATHER_API_KEY, "units": "metric", "lang": "kr"}
    r = requests.get(url, params=params); r.raise_for_status()
    w = r.json()
    return {
        "desc": w["weather"][0]["description"].capitalize(),
        "temp": w["main"]["temp"],
        "feels": w["main"]["feels_like"],
        "humidity": w["main"]["humidity"],
        "icon": w["weather"][0]["icon"],
    }

def build_weather_embed(data):
    icon_url = f"https://openweathermap.org/img/wn/{data['icon']}@2x.png"
    title = f"{CITY} 오늘의 날씨 ({datetime.now(TZ).strftime('%Y-%m-%d')})"
    return {
        "title": title,
        "description": data["desc"],
        "color": 0x3498db,
        "thumbnail": {"url": icon_url},
        "fields": [
            {"name": "🌡️ 온도", "value": f"{data['temp']}°C", "inline": True},
            {"name": "🤗 체감", "value": f"{data['feels']}°C", "inline": True},
            {"name": "💧 습도", "value": f"{data['humidity']}%", "inline": True},
        ],
        "footer": {"text": "Powered by OpenWeatherMap"},
    }

# 2) 뉴스 수집 & 요약
def fetch_recent_entries():
    feed = feedparser.parse(RSS_URL)
    now      = datetime.now(TZ)
    today8   = now.replace(hour=8, minute=0, second=0, microsecond=0)
    start    = today8 - timedelta(days=1)
    entries = []
    for e in feed.entries:
        pub = datetime(*e.published_parsed[:6], tzinfo=pytz.utc).astimezone(TZ)
        if pub >= start:
            entries.append(f"- {e.title} ({e.link})")
    return entries

def summarize_news_with_gemini(entries):
    if not entries:
        return "전날 08:00 이후 새로운 세계 뉴스가 없습니다."
    prompt = "아래 뉴스 목록을 보고, 전날 08:00(서울시간) 이후 주요 사건을 3문장으로 요약해주세요.\n\n"
    prompt += "\n".join(entries)

    try:
        res = model.generate_content(prompt)
        return res.text.strip()
    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        return "AI 코드 리뷰 생성 중 오류가 발생했습니다."

def build_news_embed(summary):
    title = f"📰 세계 뉴스 요약 ({(datetime.now(TZ)-timedelta(days=0)).strftime('%Y-%m-%d')})"
    return {
        "title": title,
        "description": summary,
        "color": 0x2ecc71,
        "footer": {"text": "Powered by Google Gemini & BBC RSS"},
    }

# 3) 디스코드 전송
def send_to_discord(embeds):
    payload = {"embeds": embeds}
    r = requests.post(DISCORD_WEBHOOK, json=payload)
    r.raise_for_status()

@app.route("/", methods=["GET"])
def handler():
    # 날씨
    wdata  = fetch_weather()
    wembed = build_weather_embed(wdata)
    # 뉴스
    entries = fetch_recent_entries()
    summary = summarize_news_with_gemini(entries)
    nembed  = build_news_embed(summary)
    # 전송
    send_to_discord([wembed, nembed])
    return jsonify(status="ok"), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
