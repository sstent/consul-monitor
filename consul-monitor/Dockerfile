FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install SQLite for debugging
RUN apt-get update && apt-get install -y sqlite3

# Copy application
COPY . .

# Create non-root user and ensure data directory exists
RUN mkdir -p /data && \
    useradd -m appuser && \
    chown -R appuser:appuser /app /data

USER appuser

# Set working directory to application code
WORKDIR /app

# Create data directory for database
RUN mkdir -p /data && chown appuser:appuser /data

# Expose port
EXPOSE 5000

# Environment variables
ENV FLASK_APP=app.py
ENV FLASK_ENV=production

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:5000/health', timeout=5)" || exit 1

CMD ["python", "-m", "flask", "run", "--host=0.0.0.0"]
