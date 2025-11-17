# ---------- Base image ----------
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data \
    TZ=UTC

WORKDIR /app

# Установим системные зависимости, если нужны для отчётов/WeasyPrint и т.п.
# Подкорректируй список под свои потребности (fonts, libffi, cairo и др.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libjpeg62-turbo-dev \
    libpng-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ---------- Install Python deps ----------
# Копируем только requirements, чтобы кешировался pip install
COPY back/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# ---------- Copy application ----------
COPY back /app

# Убедимся, что папка для данных существует
RUN mkdir -p "$DATA_DIR"

# ---------- Expose & command ----------
EXPOSE 8000

# В проде без --reload
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]