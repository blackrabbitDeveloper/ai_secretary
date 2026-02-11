# main.py
import os
import sys
import logging
import hashlib
import requests
import feedparser
import pytz
import google.generativeai as genai
from datetime import datetime, timedelta
from flask import Flask, jsonify, request

# ─── 로깅 설정 ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ─── 환경변수 ─────────────────────────────────────────────────────────
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY")
CITY                = os.getenv("CITY_NAME", "Seoul,KR")
DISCORD_WEBHOOK     = os.getenv("DISCORD_WEBHOOK_URL")
AUTH_TOKEN           = os.getenv("AUTH_TOKEN")  # 선택: 중복/무단 호출 방지용

NEWS_RSS_URLS = [
    "https://feeds.bbci.co.uk/news/business/rss.xml",
    "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
    "https://feeds.bbci.co.uk/news/technology/rss.xml",
]

GAMING_RSS_URLS = [
    "https://webzine.inven.co.kr/news/rss.php",
    "https://www.gamedeveloper.com/rss.xml",
    "https://game.donga.com/feeds/rss/",
    "https://www.gametoc.co.kr/rss/S1N86.xml",
    "https://bbs.ruliweb.com/news/537/rss",
]

TZ = pytz.timezone("Asia/Seoul")

# ─── 필수 환경변수 검증 ─────────────────────────────────────────────────
REQUIRED_ENVS = ["OPENWEATHER_API_KEY", "GEMINI_API_KEY", "DISCORD_WEBHOOK_URL"]
_missing = [e for e in REQUIRED_ENVS if not os.getenv(e)]
if _missing:
    logger.critical("Missing required environment variables: %s", ", ".join(_missing))
    sys.exit(1)

# ─── Gemini 초기화 ──────────────────────────────────────────────────────
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")

# ─── 중복 실행 방지용 (메모리 기반, 컨테이너 수명 동안 유지) ──────────────
_last_run_date = None

DISCORD_EMBED_DESC_LIMIT = 4000  # Discord embed description 안전 한계


# ═════════════════════════════════════════════════════════════════════════
#  유틸리티
# ═════════════════════════════════════════════════════════════════════════

def truncate_for_discord(text: str, limit: int = DISCORD_EMBED_DESC_LIMIT) -> str:
    """Discord embed description 글자 수 제한 처리."""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n… *(글자 수 제한으로 일부 생략됨)*"


def parse_entry_date(entry) -> datetime | None:
    """RSS 엔트리에서 날짜를 파싱한다. 실패하면 None 반환."""
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=pytz.utc).astimezone(TZ)
            except Exception:
                continue
    return None


def safe_gemini(prompt: str, fallback: str = "AI 요약 생성 중 오류가 발생했습니다.") -> str:
    """Gemini API 호출을 안전하게 수행."""
    try:
        res = model.generate_content(prompt)
        return res.text
    except Exception as e:
        logger.error("Gemini API error: %s", e)
        return fallback


# ═════════════════════════════════════════════════════════════════════════
#  1) 날씨
# ═════════════════════════════════════════════════════════════════════════

def fetch_weather() -> dict:
    base_params = {
        "q": CITY,
        "appid": OPENWEATHER_API_KEY,
        "units": "metric",
        "lang": "kr",
    }

    # 현재 날씨
    r = requests.get(
        "https://api.openweathermap.org/data/2.5/weather",
        params=base_params,
        timeout=10,
    )
    r.raise_for_status()
    current = r.json()

    # 시간별 예보
    r = requests.get(
        "https://api.openweathermap.org/data/2.5/forecast",
        params=base_params,
        timeout=10,
    )
    r.raise_for_status()
    forecast = r.json()

    now = datetime.now(TZ)
    hourly_temps = []
    for item in forecast["list"]:
        dt = datetime.fromtimestamp(item["dt"], TZ)
        if dt <= now + timedelta(hours=24):
            hourly_temps.append(
                {
                    "time": dt.strftime("%H:%M"),
                    "temp": item["main"]["temp"],
                    "icon": item["weather"][0]["icon"],
                    "pop": item.get("pop", 0),  # 강수 확률
                }
            )

    return {
        "current": {
            "desc": current["weather"][0]["description"].capitalize(),
            "temp": current["main"]["temp"],
            "feels": current["main"]["feels_like"],
            "humidity": current["main"]["humidity"],
            "wind": current["wind"]["speed"],
            "icon": current["weather"][0]["icon"],
        },
        "hourly": hourly_temps,
    }


def create_temperature_graph(hourly_temps: list) -> str:
    graph_width = min(len(hourly_temps), 8)
    step = max(1, len(hourly_temps) // graph_width)
    points = hourly_temps[::step][:graph_width]

    temps = [pt["temp"] for pt in points]
    min_temp, max_temp = min(temps), max(temps)
    temp_range = max_temp - min_temp or 1
    max_bar = 20

    lines = []
    for pt in points:
        length = int((pt["temp"] - min_temp) / temp_range * max_bar)
        bars = "█" * length
        rain = f" 💧{int(pt['pop']*100)}%" if pt.get("pop", 0) > 0.2 else ""
        lines.append(f"{pt['time']:>5} | {bars:<{max_bar}} {pt['temp']:.1f}°C{rain}")
    return "\n".join(lines)


def build_weather_embed(data: dict) -> dict:
    icon_url = f"https://openweathermap.org/img/wn/{data['current']['icon']}@2x.png"
    title = f"☀️ {CITY} 오늘의 날씨 ({datetime.now(TZ).strftime('%Y-%m-%d')})"
    graph = create_temperature_graph(data["hourly"])

    # 우산 추천 로직
    max_pop = max((h.get("pop", 0) for h in data["hourly"]), default=0)
    umbrella = ""
    if max_pop >= 0.5:
        umbrella = "🌂 **오늘 우산을 꼭 챙기세요!**"
    elif max_pop >= 0.3:
        umbrella = "🌂 접이식 우산을 챙기면 좋겠어요."

    # 옷차림 추천
    temp = data["current"]["temp"]
    if temp <= 5:
        clothing = "🧥 패딩, 두꺼운 코트, 목도리"
    elif temp <= 10:
        clothing = "🧥 코트, 가죽자켓, 니트"
    elif temp <= 15:
        clothing = "🧶 자켓, 가디건, 맨투맨"
    elif temp <= 20:
        clothing = "👕 얇은 긴팔, 셔츠"
    elif temp <= 25:
        clothing = "👕 반팔, 얇은 셔츠"
    else:
        clothing = "🩳 반팔, 반바지, 린넨"

    fields = [
        {"name": "🌡️ 현재 온도", "value": f"{data['current']['temp']}°C", "inline": True},
        {"name": "🤗 체감 온도", "value": f"{data['current']['feels']}°C", "inline": True},
        {"name": "💧 습도", "value": f"{data['current']['humidity']}%", "inline": True},
        {"name": "💨 바람", "value": f"{data['current']['wind']} m/s", "inline": True},
        {"name": "👔 오늘의 옷차림", "value": clothing, "inline": False},
    ]

    if umbrella:
        fields.append({"name": "🌧️ 강수 알림", "value": umbrella, "inline": False})

    fields.append(
        {"name": "📊 시간별 기온 그래프", "value": f"```\n{graph}\n```", "inline": False}
    )

    return {
        "title": title,
        "description": data["current"]["desc"],
        "color": 0x3498DB,
        "thumbnail": {"url": icon_url},
        "fields": fields,
        "footer": {"text": "Powered by OpenWeatherMap"},
    }


# ═════════════════════════════════════════════════════════════════════════
#  2) 뉴스 수집 & 요약
# ═════════════════════════════════════════════════════════════════════════

def fetch_rss_entries(rss_urls: list, hours: int = 24) -> list[str]:
    """범용 RSS 수집 함수."""
    now = datetime.now(TZ)
    start = now - timedelta(hours=hours)
    entries = []

    for rss_url in rss_urls:
        try:
            feed = feedparser.parse(rss_url)
            source = (
                feed.feed.title
                if hasattr(feed.feed, "title")
                else rss_url.split("/")[2]
            )

            for e in feed.entries:
                try:
                    pub = parse_entry_date(e)
                    if pub is None:
                        continue  # 날짜 없으면 건너뜀

                    if pub >= start and hasattr(e, "title") and hasattr(e, "link"):
                        entries.append(
                            f"- [{source}] {e.title.strip()} ({e.link.strip()})"
                        )
                except Exception as entry_err:
                    logger.warning("Entry parse error (%s): %s", rss_url, entry_err)
        except Exception as feed_err:
            logger.warning("Feed fetch error (%s): %s", rss_url, feed_err)

    return entries


def summarize_news(entries: list[str]) -> str:
    if not entries:
        return "최근 24시간 이내 새로운 뉴스가 없습니다."

    prompt = f"""아래 뉴스 목록을 보고, 최근 24시간 이내 정말 중요한 이슈들을 다음 형식으로 정리해주세요:

## 📰 주요 뉴스

### [뉴스 제목]
🔹 핵심 내용
- 주요 포인트 1
- 주요 포인트 2
- 주요 포인트 3

[원문 링크]

각 뉴스는 위 형식으로 구분하여 작성해주세요.
중요도 순서대로 정렬하고, 각 뉴스 사이에 빈 줄을 넣어주세요.
전체 내용이 1800자를 넘기지 않도록 하고 최대한 채워주세요.

뉴스 목록:
{chr(10).join(entries)}"""

    return safe_gemini(prompt, "뉴스 요약 생성 중 오류가 발생했습니다.")


def summarize_gaming_news(entries: list[str]) -> str:
    """게임 뉴스 전용 요약 프롬프트."""
    if not entries:
        return "최근 24시간 이내 게임 뉴스가 없습니다."

    prompt = f"""당신은 게임 업계 전문 에디터입니다.
아래 게임 뉴스 목록을 보고, 게이머와 게임 개발자가 관심 가질 만한 핵심 뉴스를 정리해주세요.

## 🎮 오늘의 게임 뉴스

### [게임/회사 이름] 뉴스 제목
🎯 핵심 내용
- 포인트 (게임 타이틀, 플랫폼, 출시일 등 구체적 정보 포함)

[원문 링크]

규칙:
- 중요도/화제성 순으로 정렬
- 게임 타이틀, 개발사, 플랫폼 등 구체적 정보를 반드시 포함
- 전체 1800자 이내

뉴스 목록:
{chr(10).join(entries)}"""

    return safe_gemini(prompt, "게임 뉴스 요약 생성 중 오류가 발생했습니다.")


def analyze_gaming_trends(entries: list[str]) -> str:
    if not entries:
        return "최근 게임 뉴스가 없어 트렌드 분석이 불가능합니다."

    prompt = f"""당신은 게임 산업 애널리스트입니다.
아래 게임 뉴스 목록을 분석하여 다음 정보를 제공해주세요:

📈 **주요 트렌드** (3~5개)
🔑 **핵심 키워드** (5~7개)
🎯 **주목할 게임 / 회사 / 이벤트**
💹 **시장 동향 분석**
💡 **게임 개발자가 참고할 점**

전체 내용이 1800자를 넘기지 않도록 하고 최대한 채워주세요.

뉴스 목록:
{chr(10).join(entries)}"""

    return safe_gemini(prompt, "게임 트렌드 분석 중 오류가 발생했습니다.")


# ═════════════════════════════════════════════════════════════════════════
#  3) 데일리 브리핑 (인사 & 동기부여)
# ═════════════════════════════════════════════════════════════════════════

def build_daily_greeting_embed() -> dict:
    """하루를 시작하는 인사 & 동기부여 메시지."""
    now = datetime.now(TZ)
    weekday_kr = ["월", "화", "수", "목", "금", "토", "일"][now.weekday()]
    date_str = now.strftime(f"%Y년 %m월 %d일 ({weekday_kr})")

    # Gemini로 오늘의 명언 + 짧은 응원 메시지 생성
    prompt = f"""오늘은 {date_str}입니다.
다음을 생성해주세요:

1. 오늘의 명언 (실존 인물의 명언 1개, 한국어 번역 포함)
2. 짧은 하루 응원 메시지 (2~3문장, 따뜻하고 유쾌한 톤)

형식:
💬 "[명언 원문]"
— 인물 이름

[한국어 번역]

🌟 [응원 메시지]

전체 300자 이내로 작성해주세요."""

    message = safe_gemini(prompt, "오늘도 좋은 하루 보내세요! 💪")

    return {
        "title": f"🌅 좋은 아침이에요! — {date_str}",
        "description": truncate_for_discord(message),
        "color": 0xF39C12,
        "footer": {"text": "AI Secretary • Daily Briefing"},
    }


# ═════════════════════════════════════════════════════════════════════════
#  4) 오늘의 일정 / 기념일 / 이슈 캘린더
# ═════════════════════════════════════════════════════════════════════════

def build_today_info_embed() -> dict:
    """오늘 날짜 관련 기념일, IT/게임 업계 일정 정보."""
    now = datetime.now(TZ)
    date_str = now.strftime("%m월 %d일")

    prompt = f"""오늘은 {now.strftime('%Y년 %m월 %d일')}입니다.
다음 정보를 알려주세요:

1. 📅 오늘의 기념일/국제일 (있다면, 1~2개)
2. 🎮 게임/IT 업계에서 오늘 예정된 주요 이벤트나 출시 (알려진 것이 있다면)
3. 📌 역사 속 오늘 (흥미로운 IT/게임 관련 사건 1개)

없는 항목은 생략하세요.
전체 500자 이내, 간결하게 작성해주세요."""

    info = safe_gemini(prompt, f"{date_str} — 특별한 일정 정보가 없습니다.")

    return {
        "title": f"📅 오늘의 일정 & 기념일 — {date_str}",
        "description": truncate_for_discord(info),
        "color": 0x1ABC9C,
        "footer": {"text": "AI Secretary • Today's Info"},
    }


# ═════════════════════════════════════════════════════════════════════════
#  5) Embed 빌더
# ═════════════════════════════════════════════════════════════════════════

def build_news_embed(summary: str) -> dict:
    return {
        "title": f"📰 세계 뉴스 요약 ({datetime.now(TZ).strftime('%Y-%m-%d')})",
        "description": truncate_for_discord(summary),
        "color": 0x2ECC71,
        "footer": {"text": "Powered by Google Gemini & BBC RSS"},
    }


def build_gaming_news_embed(summary: str) -> dict:
    return {
        "title": f"🎮 게임 뉴스 요약 ({datetime.now(TZ).strftime('%Y-%m-%d')})",
        "description": truncate_for_discord(summary),
        "color": 0x9B59B6,
        "footer": {"text": "Powered by Google Gemini & 인벤/루리웹/게임동아"},
    }


def build_gaming_trends_embed(analysis: str) -> dict:
    return {
        "title": f"📊 게임 트렌드 분석 ({datetime.now(TZ).strftime('%Y-%m-%d')})",
        "description": truncate_for_discord(analysis),
        "color": 0x3498DB,
        "footer": {"text": "Powered by Google Gemini & 인벤/루리웹/게임동아"},
    }


# ═════════════════════════════════════════════════════════════════════════
#  6) 디스코드 전송
# ═════════════════════════════════════════════════════════════════════════

def send_to_discord(embeds: list[dict]):
    for embed in embeds:
        try:
            r = requests.post(
                DISCORD_WEBHOOK, json={"embeds": [embed]}, timeout=10
            )
            r.raise_for_status()
            logger.info("Discord embed sent: %s", embed.get("title", "untitled"))
        except Exception as e:
            logger.error("Discord send error: %s", e)


# ═════════════════════════════════════════════════════════════════════════
#  라우트
# ═════════════════════════════════════════════════════════════════════════

@app.route("/health", methods=["GET"])
def health():
    """헬스체크 엔드포인트 (Cloud Run / 로드밸런서용)."""
    return jsonify(status="healthy", timestamp=datetime.now(TZ).isoformat()), 200


@app.route("/", methods=["GET"])
def handler():
    global _last_run_date

    # ── 인증 토큰 검증 (설정된 경우) ──
    if AUTH_TOKEN and request.args.get("token") != AUTH_TOKEN:
        logger.warning("Unauthorized access attempt from %s", request.remote_addr)
        return jsonify(error="unauthorized"), 401

    # ── 같은 날 중복 실행 방지 (선택적) ──
    today = datetime.now(TZ).date()
    force = request.args.get("force", "").lower() == "true"
    if _last_run_date == today and not force:
        logger.info("Already ran today (%s). Skipping. Use ?force=true to override.", today)
        return jsonify(status="already_ran", date=str(today)), 200
    _last_run_date = today

    errors = []

    # ── 1. 데일리 인사 ──
    try:
        greeting = build_daily_greeting_embed()
        send_to_discord([greeting])
    except Exception as e:
        logger.error("Greeting error: %s", e)
        errors.append(f"greeting: {e}")

    # ── 2. 오늘의 일정/기념일 ──
    try:
        today_info = build_today_info_embed()
        send_to_discord([today_info])
    except Exception as e:
        logger.error("Today info error: %s", e)
        errors.append(f"today_info: {e}")

    # ── 3. 날씨 ──
    try:
        wdata = fetch_weather()
        wembed = build_weather_embed(wdata)
        send_to_discord([wembed])
    except Exception as e:
        logger.error("Weather error: %s", e)
        errors.append(f"weather: {e}")

    # ── 4. 일반 뉴스 ──
    try:
        entries = fetch_rss_entries(NEWS_RSS_URLS)
        summary = summarize_news(entries)
        send_to_discord([build_news_embed(summary)])
        logger.info("News entries collected: %d", len(entries))
    except Exception as e:
        logger.error("News error: %s", e)
        errors.append(f"news: {e}")

    # ── 5. 게임 뉴스 ──
    try:
        gaming_entries = fetch_rss_entries(GAMING_RSS_URLS)
        logger.info("Gaming entries collected: %d", len(gaming_entries))
        if gaming_entries:
            gaming_summary = summarize_gaming_news(gaming_entries)
            send_to_discord([build_gaming_news_embed(gaming_summary)])

            trends = analyze_gaming_trends(gaming_entries)
            send_to_discord([build_gaming_trends_embed(trends)])
    except Exception as e:
        logger.error("Gaming news error: %s", e)
        errors.append(f"gaming: {e}")

    status = "ok" if not errors else "partial"
    return jsonify(status=status, errors=errors, date=str(today)), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    logger.info("Starting AI Secretary on port %d", port)
    app.run(host="0.0.0.0", port=port)
