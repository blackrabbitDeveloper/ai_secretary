# main.py
import os
import requests
import feedparser
import pytz
import google.generativeai as genai
from datetime import datetime, timedelta
from flask import Flask, jsonify

app = Flask(__name__)

# ─── 환경변수 ─────────────────────────────────────────────────────────
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
GEMINI_API_KEY        = os.environ.get('GEMINI_API_KEY')
CITY               = os.getenv("CITY_NAME", "Seoul,KR")
DISCORD_WEBHOOK    = os.getenv("DISCORD_WEBHOOK_URL")
RSS_URL            = "http://feeds.bbci.co.uk/news/world/rss.xml"
GAMING_RSS_URL     = "https://www.ign.com/rss/news.xml"  # IGN 게임 뉴스 RSS
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
    prompt = "아래 뉴스 목록을 보고, 전날 08:00(서울시간) 이후 주요 사건들을 제목 - 요약 템플릿으로 정리해주세요.\n\n"
    prompt += "\n".join(entries)

    try:
        res = model.generate_content(prompt)
        return res.text
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

def fetch_gaming_news():
    feed = feedparser.parse(GAMING_RSS_URL)
    now = datetime.now(TZ)
    today8 = now.replace(hour=8, minute=0, second=0, microsecond=0)
    start = today8 - timedelta(days=1)
    entries = []
    for e in feed.entries:
        pub = datetime(*e.published_parsed[:6], tzinfo=pytz.utc).astimezone(TZ)
        if pub >= start:
            entries.append(f"- {e.title} ({e.link})")
    return entries

def build_gaming_news_embed(summary):
    title = f"🎮 게임 뉴스 요약 ({(datetime.now(TZ)-timedelta(days=0)).strftime('%Y-%m-%d')})"
    return {
        "title": title,
        "description": summary,
        "color": 0x9b59b6,
        "footer": {"text": "Powered by Google Gemini & IGN RSS"},
    }

def analyze_gaming_trends(entries):
    if not entries:
        return "최근 게임 뉴스가 없어 트렌드 분석이 불가능합니다."
    
    prompt = """아래 게임 뉴스 목록을 분석하여 다음 정보를 제공해주세요:
1. 주요 트렌드 (3-5개)
2. 핵심 키워드 (5-7개)
3. 주목할 만한 게임/회사/이벤트
4. 시장 동향 분석

뉴스 목록:
"""
    prompt += "\n".join(entries)

    try:
        res = model.generate_content(prompt)
        return res.text
    except Exception as e:
        print(f"Error analyzing gaming trends: {e}")
        return "게임 트렌드 분석 중 오류가 발생했습니다."

def build_gaming_trends_embed(analysis):
    title = f"📊 게임 트렌드 분석 ({(datetime.now(TZ)-timedelta(days=0)).strftime('%Y-%m-%d')})"
    return {
        "title": title,
        "description": analysis,
        "color": 0x3498db,
        "footer": {"text": "Powered by Google Gemini & IGN RSS"},
    }

# 3) 디스코드 전송
def send_to_discord(embeds):
    for embed in embeds:
        payload = {"embeds": [embed]}
        try:
            r = requests.post(DISCORD_WEBHOOK, json=payload)
            r.raise_for_status()
        except Exception as e:
            print(f"Error sending embed to Discord: {e}")
            continue

@app.route("/", methods=["GET"])
def handler():
    # 날씨
    wdata = fetch_weather()
    wembed = build_weather_embed(wdata)
    send_to_discord([wembed])
    
    # 일반 뉴스
    entries = fetch_recent_entries()
    summary = summarize_news_with_gemini(entries)
    nembed = build_news_embed(summary)
    send_to_discord([nembed])
    
    # 게임 뉴스
    gaming_entries = fetch_gaming_news()
    if gaming_entries:
        # 게임 뉴스 요약
        gaming_summary = summarize_news_with_gemini(gaming_entries)
        gembed = build_gaming_news_embed(gaming_summary)
        send_to_discord([gembed])
        
        # 게임 트렌드 분석
        trends_analysis = analyze_gaming_trends(gaming_entries)
        tembed = build_gaming_trends_embed(trends_analysis)
        send_to_discord([tembed])
    
    return jsonify(status="ok"), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
