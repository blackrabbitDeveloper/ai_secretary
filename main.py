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
GAMING_RSS_URLS = [
    "https://webzine.inven.co.kr/news/rss.php",
    "https://www.gamedeveloper.com/rss.xml",
    "https://game.donga.com/feeds/rss/",
    "https://www.gametoc.co.kr/rss/S1N86.xml",
    "https://bbs.ruliweb.com/news/537/rss"
]
TZ                 = pytz.timezone("Asia/Seoul")
# ────────────────────────────────────────────────────────────────────────

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash-preview-04-17')

# 1) 날씨 조회
def fetch_weather():
    # 현재 날씨
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {"q": CITY, "appid": OPENWEATHER_API_KEY, "units": "metric", "lang": "kr"}
    r = requests.get(url, params=params); r.raise_for_status()
    current = r.json()
    
    # 시간별 예보
    forecast_url = "https://api.openweathermap.org/data/2.5/forecast"
    r = requests.get(forecast_url, params=params); r.raise_for_status()
    forecast = r.json()
    
    # 다음 24시간 예보 (3시간 간격)
    hourly_temps = []
    now = datetime.now(TZ)
    for item in forecast['list']:
        dt = datetime.fromtimestamp(item['dt'], TZ)
        if dt <= now + timedelta(hours=24):
            hourly_temps.append({
                "time": dt.strftime("%H:%M"),
                "temp": item['main']['temp'],
                "icon": item['weather'][0]['icon']
            })
    
    return {
        "current": {
            "desc": current["weather"][0]["description"].capitalize(),
            "temp": current["main"]["temp"],
            "feels": current["main"]["feels_like"],
            "humidity": current["main"]["humidity"],
            "icon": current["weather"][0]["icon"],
        },
        "hourly": hourly_temps
    }

def create_temperature_graph(hourly_temps):
    # 온도 범위 계산
    temps = [hour['temp'] for hour in hourly_temps]
    min_temp = min(temps)
    max_temp = max(temps)
    temp_range = max_temp - min_temp
    
    # 그래프 높이 설정
    graph_height = 10
    graph_width = len(hourly_temps)
    
    # 그래프 생성
    graph = []
    for i in range(graph_height):
        row = []
        for temp in temps:
            # 온도를 그래프 높이에 맞게 정규화
            normalized = int((temp - min_temp) / temp_range * (graph_height - 1))
            if i == graph_height - 1 - normalized:
                row.append("🌡️")  # 온도 표시
            elif i > graph_height - 1 - normalized:
                row.append("█")   # 그래프 바
            else:
                row.append(" ")   # 빈 공간
        graph.append("".join(row))
    
    # 시간 축 추가
    time_labels = [hour['time'] for hour in hourly_temps]
    time_row = "".join([f"{time:<8}" for time in time_labels])
    
    # 온도 축 추가
    temp_labels = [f"{temp}°C" for temp in temps]
    temp_row = "".join([f"{temp:<8}" for temp in temp_labels])
    
    return "\n".join(graph) + "\n" + time_row + "\n" + temp_row

def build_weather_embed(data):
    icon_url = f"https://openweathermap.org/img/wn/{data['current']['icon']}@2x.png"
    title = f"{CITY} 오늘의 날씨 ({datetime.now(TZ).strftime('%Y-%m-%d')})"
    
    # 시간별 기온 그래프 생성
    graph = create_temperature_graph(data['hourly'])
    hourly_text = f"```\n{graph}\n```"
    
    return {
        "title": title,
        "description": data["current"]["desc"],
        "color": 0x3498db,
        "thumbnail": {"url": icon_url},
        "fields": [
            {"name": "🌡️ 현재 온도", "value": f"{data['current']['temp']}°C", "inline": True},
            {"name": "🤗 체감 온도", "value": f"{data['current']['feels']}°C", "inline": True},
            {"name": "💧 습도", "value": f"{data['current']['humidity']}%", "inline": True},
            {"name": "📊 시간별 기온 그래프", "value": hourly_text, "inline": False},
        ],
        "footer": {"text": "Powered by OpenWeatherMap"},
    }

# 2) 뉴스 수집 & 요약
def fetch_recent_entries():
    feed = feedparser.parse(RSS_URL)
    now = datetime.now(TZ)
    start = now - timedelta(hours=24)  # 24시간 이내로 변경
    entries = []
    
    for e in feed.entries:
        try:
            if hasattr(e, 'published_parsed'):
                pub = datetime(*e.published_parsed[:6], tzinfo=pytz.utc).astimezone(TZ)
            else:
                # 시간 정보가 없는 경우 현재 시간으로 처리
                pub = now
                
            if pub >= start:
                entries.append(f"- {e.title} ({e.link})")
        except Exception as e:
            print(f"Error processing entry: {e}")
            continue
            
    return entries

def summarize_news_with_gemini(entries):
    if not entries:
        return "최근 24시간 이내 새로운 뉴스가 없습니다."
    
    prompt = """아래 뉴스 목록을 보고, 최근 24시간 이내 주요 사건들을 다음 형식으로 정리해주세요:

## 📰 주요 뉴스

### [뉴스 제목]
🔹 핵심 내용
- 주요 포인트 1
- 주요 포인트 2
- 주요 포인트 3

[원문 링크]

각 뉴스는 위 형식으로 구분하여 작성해주세요.
중요도 순서대로 정렬하고, 각 뉴스 사이에 빈 줄을 넣어주세요.
뉴스 목록:
"""
    prompt += "\n".join(entries)

    try:
        res = model.generate_content(prompt)
        return res.text
    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        return "뉴스 요약 생성 중 오류가 발생했습니다."

def build_news_embed(summary):
    title = f"📰 세계 뉴스 요약 ({(datetime.now(TZ)-timedelta(days=0)).strftime('%Y-%m-%d')})"
    return {
        "title": title,
        "description": summary,
        "color": 0x2ecc71,
        "footer": {"text": "Powered by Google Gemini & BBC RSS"},
    }

def fetch_gaming_news():
    now = datetime.now(TZ)
    start = now - timedelta(hours=24)
    entries = []
    
    for rss_url in GAMING_RSS_URLS:
        try:
            feed = feedparser.parse(rss_url)
            for e in feed.entries:
                try:
                    if hasattr(e, 'published_parsed'):
                        pub = datetime(*e.published_parsed[:6], tzinfo=pytz.utc).astimezone(TZ)
                    else:
                        pub = now
                        
                    if pub >= start:
                        # 제목과 링크가 모두 있는 경우에만 추가
                        if hasattr(e, 'title') and hasattr(e, 'link'):
                            # RSS 출처를 함께 표시
                            source = feed.feed.title if hasattr(feed.feed, 'title') else rss_url.split('/')[2]
                            entries.append(f"- [{source}] {e.title.strip()} ({e.link.strip()})")
                except Exception as entry_error:
                    print(f"Error processing entry from {rss_url}: {entry_error}")
                    continue
        except Exception as feed_error:
            print(f"Error fetching RSS feed {rss_url}: {feed_error}")
            continue
            
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
