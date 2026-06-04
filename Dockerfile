FROM python:3.10-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Collect static files
RUN python manage.py collectstatic --noinput 2>/dev/null || true

EXPOSE 8080

# FIX: Use gunicorn_conf.py (timeout=300, workers=2, threads=4, worker_class=gthread)
# Do NOT hardcode --timeout here — it was overriding gunicorn_conf.py's 300s setting
CMD ["gunicorn", "impact_sdg.wsgi", "--config", "gunicorn_conf.py"]
