# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for psycopg2 (Postgres driver)
RUN apt-get update && apt-get install -y libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Command to run the app
CMD ["sh", "-c", "python seed.py && uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-2}"]