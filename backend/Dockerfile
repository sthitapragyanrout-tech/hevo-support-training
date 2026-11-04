FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

ENV PATH="/app/.venv/bin:$PATH"
ENV DJANGO_SETTINGS_MODULE=config.settings.dev

EXPOSE 8000

# Production-style by default (gunicorn.conf.py sizes it). docker-compose.yml overrides
# this with `runserver` for development (auto-reload).
CMD ["gunicorn", "config.wsgi:application", "-c", "gunicorn.conf.py"]
