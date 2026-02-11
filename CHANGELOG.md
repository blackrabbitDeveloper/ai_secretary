# AI Secretary 개선 사항

## 🔧 버그 수정 & 안정성 개선

### 1. 독립적 에러 핸들링
- 각 섹션(날씨/뉴스/게임)이 독립적으로 try-except 처리됨
- 날씨 API 실패해도 뉴스는 정상 전송
- 응답에 `errors` 배열로 실패 내역 반환

### 2. Discord Embed 글자 수 제한
- `truncate_for_discord()` 함수로 4000자 초과 시 자동 잘림 처리
- Gemini 프롬프트에서도 1800자 제한으로 변경 (안전 마진 확보)

### 3. RSS 타임스탬프 파싱 개선
- `published_parsed` → `updated_parsed` 순으로 폴백
- 날짜 파싱 불가 시 기사 건너뜀 (오래된 기사 혼입 방지)

### 4. 게임 뉴스 전용 프롬프트
- `summarize_gaming_news()` 별도 함수 생성
- 게임 타이틀, 플랫폼, 개발사 등 구체적 정보 추출에 최적화

### 5. Footer 텍스트 수정
- "IGN RSS" → "인벤/루리웹/게임동아" (실제 소스에 맞게)

### 6. 불필요한 코드 제거
- `timedelta(days=0)` 제거
- RSS 수집 로직을 `fetch_rss_entries()`로 통합 (DRY)

---

## 🛡️ 보안 & 운영 개선

### 7. 필수 환경변수 시작 시 검증
- 누락 시 명확한 에러 메시지와 함께 즉시 종료

### 8. 인증 토큰 지원
- `AUTH_TOKEN` 환경변수 설정 시 `?token=xxx` 파라미터 필수
- 무단 호출 차단

### 9. 같은 날 중복 실행 방지
- 메모리 기반으로 동일 날짜 재실행 차단
- `?force=true` 파라미터로 강제 실행 가능

### 10. 헬스체크 엔드포인트
- `GET /health` — Cloud Run / 로드밸런서 상태 확인용

### 11. 구조화된 로깅
- `print()` → `logging` 모듈로 전환
- 타임스탬프 + 로그레벨 포함

### 12. HTTP 요청 타임아웃
- 모든 `requests.get/post`에 `timeout=10` 추가

### 13. Dockerfile 보안
- 비-root 사용자(`appuser`)로 실행
- Docker HEALTHCHECK 추가

### 14. Werkzeug 버전 고정
- `Werkzeug<3.0` 추가로 Flask 2.3 호환성 보장

---

## ✨ 새로운 기능

### 15. 🌅 데일리 인사 & 동기부여
- 매일 아침 날짜/요일 + Gemini 생성 명언 + 응원 메시지
- 하루의 시작을 기분 좋게

### 16. 📅 오늘의 일정 & 기념일
- 오늘 날짜의 기념일/국제일
- IT/게임 업계 예정 이벤트
- 역사 속 오늘의 IT/게임 사건

### 17. ☀️ 날씨 정보 확장
- 바람 속도 표시
- 강수 확률 20% 이상 시 그래프에 💧 표시
- 🌂 우산 추천 (강수 확률 기반)
- 👔 기온별 옷차림 추천

---

## 📋 환경변수 목록

| 변수명 | 필수 | 설명 |
|--------|------|------|
| `OPENWEATHER_API_KEY` | ✅ | OpenWeatherMap API 키 |
| `GEMINI_API_KEY` | ✅ | Google Gemini API 키 |
| `DISCORD_WEBHOOK_URL` | ✅ | Discord 웹훅 URL |
| `CITY_NAME` | ❌ | 날씨 조회 도시 (기본: Seoul,KR) |
| `AUTH_TOKEN` | ❌ | API 인증 토큰 |
| `PORT` | ❌ | 서버 포트 (기본: 8080) |
