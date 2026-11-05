# syntax=docker/dockerfile:1

# ---------- 1) Assets: Tailwind + bibliotecas JS + fontes ----------
FROM node:20-alpine AS assets
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY tailwind.config.js ./
COPY scripts ./scripts
COPY static ./static
COPY templates ./templates
COPY apps ./apps
RUN npm run vendor && npm run build:css

# ---------- 2) Aplicação Python ----------
FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends libjpeg62-turbo zlib1g libwebp7 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
COPY --from=assets /app/static/css ./static/css
COPY --from=assets /app/static/vendor ./static/vendor
COPY --from=assets /app/static/fonts ./static/fonts

RUN DJANGO_BUILD=1 python manage.py collectstatic --noinput

RUN useradd --create-home --uid 1000 appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "-c", "gunicorn.conf.py"]
