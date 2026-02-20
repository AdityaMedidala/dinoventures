# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for psycopg2 (Postgres driver)
RUN apt-get update && apt-get install -y libpq-dev gcc

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Command to run the app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]