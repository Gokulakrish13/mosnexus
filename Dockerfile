# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# NexusOps â€” AI-Powered Unified Operations & Resource Management Portal â€” Production Dockerfile (Multi-stage)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Build:   docker build -t nexusops:$(cat VERSION) .
# Run:     docker run -p 8000:8000 --env-file .env nexusops:$(cat VERSION)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

# â”€â”€ Stage 1: Build dependencies â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
FROM python:3.12-slim AS builder

WORKDIR /build

# System dependencies for Pillow, psycopg2, Tesseract, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    libjpeg62-turbo-dev \
    zlib1g-dev \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt
RUN pip install --no-cache-dir --prefix=/install gunicorn psycopg2-binary

# â”€â”€ Stage 2: Production image â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
FROM python:3.12-slim AS production

# Labels for corporate container registry
LABEL maintainer="NexusOps Team <mostestautomation_2@philips.com>"
LABEL org.opencontainers.image.title="NexusOps"
LABEL org.opencontainers.image.description="Inventory & Asset Management Platform"
LABEL org.opencontainers.image.vendor="Koninklijke Philips N.V."

# Runtime system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libjpeg62-turbo \
    tesseract-ocr \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system nexusops \
    && adduser --system --ingroup nexusops nexusops

# Copy Python packages from builder stage
COPY --from=builder /install /usr/local

# Set up application directory
WORKDIR /app

# Copy application code
COPY . .

# Copy VERSION file for runtime version detection
COPY VERSION /app/VERSION

# Collect static files
RUN DJANGO_SECRET_KEY=build-placeholder python manage.py collectstatic --noinput 2>/dev/null || true

# Fix permissions
RUN chown -R nexusops:nexusops /app

USER nexusops

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/health/ || exit 1

EXPOSE 8000

# Gunicorn with concurrency-tuned defaults (50+ users)
# workers Ã— threads = max concurrent requests handled simultaneously
# 6 workers Ã— 4 threads = 24 concurrent slots (comfortable for 50 users)
CMD ["gunicorn", \
     "inventory.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "6", \
     "--threads", "4", \
     "--worker-class", "gthread", \
     "--timeout", "120", \
     "--keep-alive", "5", \
     "--max-requests", "1000", \
     "--max-requests-jitter", "50", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--log-level", "info"]
