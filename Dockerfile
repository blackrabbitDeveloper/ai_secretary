# 베이스 이미지
FROM python:3.12-slim

# 작업 디렉터리 설정
WORKDIR /app

# 종속성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 코드 복사
COPY main.py .

# Cloud Run 포트
ENV PORT 8080

# 컨테이너 시작 커맨드
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "main:app"]
