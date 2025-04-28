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
NEWS_RSS_URLS = [
    "https://feeds.bbci.co.uk/news/business/rss.xml",            # BBC 비즈니스
    "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml", # BBC 과학/환경
    "https://feeds.bbci.co.uk/news/technology/rss.xml"           # BBC 기술
]

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
    # 새로운 수평 막대 그래프 구현 (Discord 코드블록에 잘 맞도록)
    # 최대 8개 구간을 선택해 표시
    graph_width = min(len(hourly_temps), 8)
    step = max(1, len(hourly_temps) // graph_width)
    points = hourly_temps[::step][:graph_width]

    # 온도값 리스트와 범위 계산
    temps = [pt['temp'] for pt in points]
    min_temp, max_temp = min(temps), max(temps)
    temp_range = max_temp - min_temp or 1  # 0으로 나누는 경우 방지
    max_bar = 20  # 막대 최대 길이

    # 각 구간별 수평 막대 생성
    lines = []
    for pt in points:
        # 비율에 따라 막대 길이 결정
        length = int((pt['temp'] - min_temp) / temp_range * max_bar)
        bars = '█' * length
        # "HH:MM | ███ 15.2°C" 형태
        lines.append(f"{pt['time']:>5} | {bars:<{max_bar}} {pt['temp']:.1f}°C")
    return "\n".join(lines)

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
    now = datetime.now(TZ)
    start = now - timedelta(hours=24)
    entries = []
    
    for rss_url in NEWS_RSS_URLS:
        try:
            feed = feedparser.parse(rss_url)
            category = feed.feed.title if hasattr(feed.feed, 'title') else rss_url.split('/')[-2].replace('_', ' ').title()
            
            for e in feed.entries:
                try:
                    if hasattr(e, 'published_parsed'):
                        pub = datetime(*e.published_parsed[:6], tzinfo=pytz.utc).astimezone(TZ)
                    else:
                        pub = now
                        
                    if pub >= start:
                        # 제목과 링크가 모두 있는 경우에만 추가
                        if hasattr(e, 'title') and hasattr(e, 'link'):
                            entries.append(f"- [{category}] {e.title.strip()} ({e.link.strip()})")
                except Exception as entry_error:
                    print(f"Error processing entry from {rss_url}: {entry_error}")
                    continue
        except Exception as feed_error:
            print(f"Error fetching RSS feed {rss_url}: {feed_error}")
            continue
            
    return entries

def summarize_news_with_gemini(entries):
    if not entries:
        return "최근 24시간 이내 새로운 뉴스가 없습니다."
    
    prompt = """아래 뉴스 목록을 보고, 최근 24시간 이내 정말 중요한 이슈들을 다음 형식으로 정리해주세요:

## 📰 주요 뉴스

### [뉴스 제목]
🔹 핵심 내용
- 주요 포인트 1
- 주요 포인트 2
- 주요 포인트 3

[원문 링크]

각 뉴스는 위 형식으로 구분하여 작성해주세요.
중요도 순서대로 정렬하고, 각 뉴스 사이에 빈 줄을 넣어주세요.
전체 내용이 2000자를 넘기지 않도록 하고 최대한 채워주세요.

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
5. 생각해볼 만한 점

전체 내용이 2000자를 넘기지 않도록 하고 최대한 채워주세요.

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
