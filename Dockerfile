# 베이스 이미지
FROM python:3.12-slim

# 보안: 비-root 사용자 생성
RUN groupadd -r appuser && useradd -r -g appuser appuser

# 작업 디렉터리 설정
WORKDIR /app

# 종속성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 코드 복사
COPY main.py .

# 비-root 사용자로 전환
USER appuser

# Cloud Run 포트
ENV PORT=8080

# 헬스체크
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8080/health', timeout=3)" || exit 1

# 컨테이너 시작 커맨드
CMD ["python", "main.py"]
