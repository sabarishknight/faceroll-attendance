FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn
COPY . .
RUN python scripts/download_models.py
ENV STORE=firestore PYTHONUNBUFFERED=1
# one worker => face engine loaded once; threads serve concurrent requests (Cloud Run injects $PORT)
CMD exec gunicorn --chdir app -b 0.0.0.0:${PORT:-8080} -w 1 --threads 4 --timeout 300 server:app
