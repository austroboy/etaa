# ── ETAA Django Application – Dockerfile ──────────────────────
FROM python:3.11-slim

# System dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Create required directories
RUN mkdir -p outputs/cv_rankings outputs/job_posts outputs/code logs temp/cvs media staticfiles

# Collect static files
RUN python manage.py collectstatic --noinput || true

EXPOSE 8000

CMD ["gunicorn", "etaa_core.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--timeout", "120"]
